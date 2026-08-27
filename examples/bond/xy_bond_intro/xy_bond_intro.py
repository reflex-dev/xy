"""XY × Reflex: the 007 gun-barrel intro, rendered as a live chart.

A title sequence is an unusual thing to build out of a charting library, which
is the point: it exercises the parts of `xy[reflex]` that a dashboard leans on
hardest — a fixed compile-validated plan, binary columns on the app's own
websocket, and the engine's animation interpolation — under a load where any
stutter, remount, or rescale is *immediately* visible. A dropped frame in a
dashboard looks like nothing. A dropped frame here looks like a broken film.

**How it works.** One chart, one fixed plan, six scatter layers
(``charts.py``). A background task advances a cycle clock and a single
``@reflex_xy.data`` var republishes the whole scene's columns for that instant
(``scene.py``). Reflex state holds a tiny handle; the ~100k f32 coordinates per
keyframe ride the app's websocket as raw binary on the XY namespace — no JSON
numbers, no base64 (dossier §29).

**The part worth stealing.** The server publishes only ~12 keyframes a second.
The 60 fps motion in between is the engine's: ``xy.animation(match="index",
update="interpolate")`` tweens positions and colors from the previous payload to
the new one. That is sound rather than a cheat because ``scene.py`` keeps *row
identity stable* — row ``i`` is the same groove sample, the same knee point, in
every frame of the sequence — so the straight line between two keyframes is the
correct in-between. Sixty frames a second of geometry never crosses the wire;
twelve do, and the GPU draws the rest.

Everything on the page is a knob on that claim. Drop the publish rate to 6 Hz
and the motion stays continuous because the tweens stretch. Turn interpolation
off and the same 12 Hz feed becomes a visible flip-book. Scrub the clock while
paused and the same pure function of state renders any instant of the sequence.

The browser sets the pace, not a timer. ``on_animation_end`` publishes the next
keyframe once the previous one has finished tweening, so at most one frame is
ever in flight. Without that the server publishes at whatever rate *it* can
manage, which is not the rate the browser can decode, upload and draw — and the
difference accumulates as a backlog that leaves the page minutes behind real
time with every individual frame still looking perfect. With it, the pipeline
self-tunes to the machine, and the RATE readout shows what it settled on.

Run from ``examples/bond``::

    uv run reflex run
"""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import time
from typing import Any, TypedDict

import numpy as np
import reflex as rx

import reflex_xy
from reflex_xy.tokens import BUILDER_ATTR

from .charts import gun_barrel_marks
from .scene import BEATS, CYCLE, WORLD_ASPECT, beat_label, frame_columns, scene_spec

# Point budgets offered in the UI. A fixed menu rather than a free number: the
# value sizes every per-frame allocation and the browser payload, and a slider
# event is untrusted input, so the server never takes an arbitrary count.
POINT_CHOICES: dict[str, int] = {
    "40k — light": 40_000,
    "90k — default": 90_000,
    "180k — dense": 180_000,
    "400k — showing off": 400_000,
}
DEFAULT_POINTS = int(os.environ.get("XY_BOND_POINTS", 90_000))

# Publish rates. The whole demo is the claim that the low end still looks
# smooth, so the menu goes well below anything you would call a frame rate.
RATE_CHOICES: dict[str, int] = {
    "6 Hz - interpolation carrying it": 6,
    "12 Hz - default": 12,
    "20 Hz": 20,
    "30 Hz": 30,
}
DEFAULT_RATE = 12
#: Distinct ceilings, each of which gets its own plan (see `stage`).
_RATES = tuple(sorted(set(RATE_CHOICES.values())))


#: How long the server waits for the browser to report a finished tween before
#: publishing anyway. Long enough never to race normal play, short enough that a
#: chart reporting no animations at all (interpolation off, reduced motion, a
#: hidden tab) still advances at a watchable rate.
_WATCHDOG_S = 0.35


class SceneCols(TypedDict):
    """Schema of the one data var that feeds every layer.

    The annotation is the compile-time schema channel (design fact R7): the
    class-level var carries ``DataHandle[SceneCols]``, and the marks in the page
    are checked against these column names at ``reflex run`` — without executing
    a single frame of geometry.
    """

    wash_x: np.ndarray
    wash_y: np.ndarray
    wash_c: np.ndarray
    rifle_x: np.ndarray
    rifle_y: np.ndarray
    rifle_c: np.ndarray
    ring_x: np.ndarray
    ring_y: np.ndarray
    ring_c: np.ndarray
    fig_x: np.ndarray
    fig_y: np.ndarray
    fig_c: np.ndarray
    flash_x: np.ndarray
    flash_y: np.ndarray
    flash_c: np.ndarray
    blood_x: np.ndarray
    blood_y: np.ndarray
    blood_c: np.ndarray


def _choice(value: object, choices: dict[str, int], fallback: int) -> int:
    """Resolve a select event value against a fixed menu.

    Browser payloads are untrusted and these values size server allocations, so
    the menu is the authority: an unknown label falls back instead of reaching
    ``scene_spec``.
    """
    if isinstance(value, str) and value in choices:
        return choices[value]
    return fallback


def _clamped_seconds(value: object) -> float:
    """Validate and clamp a slider event into the cycle."""
    if not isinstance(value, (list, tuple)) or not value:
        return 0.0
    first = value[0]
    if isinstance(first, bool) or not isinstance(first, (int, float)) or not math.isfinite(first):
        return 0.0
    return float(np.clip(float(first), 0.0, CYCLE))


class Intro(rx.State):
    """The clock, and one data var that is a pure function of it."""

    playing: bool = False
    # Seconds into the 15-second cycle. The only thing the scene depends on.
    clock: float = 0.0
    points: int = DEFAULT_POINTS
    rate: int = DEFAULT_RATE
    interpolate: bool = True
    # Telemetry
    keyframes: int = 0
    bytes_per_frame: int = 0
    build_ms: float = 0.0
    achieved_hz: float = 0.0
    stalls: int = 0
    # Bumped on every transport change so a stale background task exits.
    _run: int = 0
    # Wall-clock anchor: `clock` is derived from elapsed real time, never
    # accumulated per tick. See `play`.
    _anchor: float = 0.0
    _last_tick: float = 0.0

    @reflex_xy.data
    def scene(self) -> SceneCols:
        """The whole scene's columns for the current instant.

        Columns only — the plan lives in the page and never changes. This is a
        pure function of ``clock`` and ``points``, which is what makes the token
        a rebuild recipe the adapter can re-run on a fresh worker, and what
        makes the sequence seekable rather than a stream you can only watch.
        """
        return frame_columns(self.clock, points=self.points)

    # --- readouts: formatting lives in state, not in f-strings over Vars ---

    @rx.var
    def beat(self) -> str:
        """Which beat of the sequence the clock is in."""
        return beat_label(self.clock)

    @rx.var
    def clock_text(self) -> str:
        return f"{self.clock:5.2f}s / {CYCLE:.0f}s"

    @rx.var
    def points_label(self) -> str:
        for label, count in POINT_CHOICES.items():
            if count == self.points:
                return label
        return f"{self.points:,}"

    @rx.var
    def rate_label(self) -> str:
        for label, hz in RATE_CHOICES.items():
            if hz == self.rate:
                return label
        return f"{self.rate} Hz"  # pragma: no cover - _choice pins to the menu

    @rx.var
    def points_text(self) -> str:
        return f"{scene_spec(self.points).total:,}"

    @rx.var
    def payload_text(self) -> str:
        return f"{self.bytes_per_frame / 1e6:.2f} MB"

    @rx.var
    def rate_text(self) -> str:
        """Achieved publish rate against the requested one.

        Reported separately on purpose. The requested rate is a target, not a
        promise: past some point budget the server stops keeping up, and the
        page should say so rather than print the number it was asked for.
        """
        if not self.achieved_hz:
            return f"— / {self.rate} Hz"
        return f"{self.achieved_hz:.1f} / {self.rate} Hz"

    @rx.var
    def wire_text(self) -> str:
        """Bytes per second the columns actually cost, at the measured rate."""
        rate = self.achieved_hz or self.rate
        return f"{self.bytes_per_frame * rate / 1e6:.1f} MB/s"

    @rx.var
    def build_text(self) -> str:
        return f"{self.build_ms:.2f} ms"

    @rx.event
    def measure(self):
        """Record payload size and build cost for the readout (not on the hot path)."""
        started = time.perf_counter()
        columns = frame_columns(self.clock, points=self.points)
        self.build_ms = round((time.perf_counter() - started) * 1000.0, 2)
        self.bytes_per_frame = sum(int(col.nbytes) for col in columns.values())

    @rx.event
    def seek(self, value: list[float]):
        """Scrub the clock. Works paused or playing — same pure function.

        Re-anchors as well as sets: the clock is derived from elapsed real time
        while playing, so assigning it without moving the anchor would be
        overwritten by the very next tick.
        """
        self.clock = _clamped_seconds(value)
        self._anchor = time.monotonic() - self.clock

    @rx.event
    def set_points(self, value: str):
        self.points = _choice(value, POINT_CHOICES, DEFAULT_POINTS)
        return Intro.measure

    @rx.event
    def set_rate(self, value: str):
        self.rate = _choice(value, RATE_CHOICES, DEFAULT_RATE)

    @rx.event
    def toggle_interpolation(self, value: bool):
        """Swap which of the two plans is mounted.

        The animation policy is part of the plan, so tweened and flip-book are
        two plans, not one plan with a live flag — the page mounts them behind
        an ``rx.cond`` and both are validated at ``reflex run``. Flipping this
        remounts the canvas (and so resets the run's tween count); the clock is
        state, so the sequence picks up where it was.
        """
        self.interpolate = bool(value)

    @rx.event
    def restart(self):
        self.clock = 0.0
        self.keyframes = 0
        self.stalls = 0
        self.achieved_hz = 0.0
        self._anchor = time.monotonic()
        self._last_tick = 0.0

    def _advance(self) -> bool:
        """Publish one keyframe, unless the rate ceiling says not yet.

        Two rules, both load-bearing:

        * The clock is read from the **wall**, never accumulated one period per
          publish. If publishing runs slower than requested, an accumulating
          clock would play the sequence in slow motion — the one failure a title
          sequence cannot hide. Anchored to real time it publishes fewer,
          wider-spaced keyframes at the correct speed instead, and the
          interpolation covers the wider gaps: it degrades into the very thing
          the demo is about.
        * The requested rate is a **ceiling**, not a metronome. What actually
          paces publishing is the browser — see `frame_rendered` — so this only
          ever refuses to go *faster* than asked.
        """
        now = time.monotonic()
        if self._last_tick and now - self._last_tick < 1.0 / self.rate:
            return False
        self.clock = (now - self._anchor) % CYCLE
        self.keyframes += 1
        if self._last_tick:
            # Smoothed, so the readout reports what the pipeline really managed
            # rather than the rate it was asked for.
            instant = 1.0 / max(now - self._last_tick, 1e-6)
            self.achieved_hz = round(
                instant if not self.achieved_hz else 0.75 * self.achieved_hz + 0.25 * instant,
                1,
            )
        self._last_tick = now
        return True

    @rx.event
    def frame_rendered(self, _payload: dict):
        """The engine finished tweening a keyframe — so send the next one.

        This is `on_animation_end` used as **flow control**, and it is the piece
        that makes the rest hold together. A free-running timer publishes at
        whatever rate the *server* can manage, which is not the rate the browser
        can decode, upload and draw. When the server wins that race the
        difference becomes an ever-growing backlog: every individual frame still
        looks perfect while the page falls further and further behind real time,
        which is a genuinely confusing way to fail. Publishing the next keyframe
        only once the previous one has finished animating caps the work in
        flight at one, so the pipeline self-tunes to whatever the machine can
        actually do — fast box, many keyframes; software rasteriser, fewer — and
        never queues.

        `play`'s loop stays on as a watchdog for the cases where no animation
        ever ends: interpolation switched off, reduced motion, a hidden tab.
        """
        if self.playing:
            self._advance()

    @rx.event(background=True)
    async def play(self):
        """Start the sequence, then watchdog underneath the browser's pacing."""
        async with self:
            if self.playing:
                self.playing = False
                return
            self.playing = True
            self._run += 1
            run = self._run
            self._anchor = time.monotonic() - self.clock
            self._last_tick = 0.0
            self._advance()  # prime the pipeline; the browser drives from here
        while True:
            await asyncio.sleep(_WATCHDOG_S)
            async with self:
                if not self.playing or self._run != run:
                    break
                # Only steps in when the browser has gone quiet. Under normal
                # play `frame_rendered` is doing the pacing and this does
                # nothing at all.
                if time.monotonic() - self._last_tick >= _WATCHDOG_S:
                    self.stalls += 1
                    self._advance()


# --- introspection: the "Code" accordions -----------------------------------


def _source(obj: Any) -> str:
    """Source of a plain function, a ``@reflex_xy.data`` var, or an event handler."""
    obj = getattr(obj, "_original", obj)
    fget = getattr(obj, "_fget", None)
    if fget is not None:  # a @reflex_xy.data / computed var
        builder = getattr(fget, BUILDER_ATTR, None)
        return inspect.getsource(builder if builder is not None else fget)
    handler = getattr(obj, "fn", None)
    if handler is not None:  # an @rx.event handler
        return inspect.getsource(handler)
    return inspect.getsource(obj)


def code_accordion(label: str, *objs: Any) -> rx.Component:
    return rx.accordion.root(
        rx.accordion.item(
            header=label,
            content=rx.code_block(
                "\n\n".join(inspect.cleandoc(_source(obj)) for obj in objs),
                language="python",
                show_line_numbers=False,
                wrap_long_lines=True,
                font_size="0.72rem",
            ),
        ),
        collapsible=True,
        variant="ghost",
        width="100%",
    )


# --- page -------------------------------------------------------------------

_MONO = "ui-monospace, SFMono-Regular, Menlo, monospace"


def readout(label: str, value: Any, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.text(label, font_size="0.68rem", color="#6b7280", letter_spacing="0.08em"),
        rx.text(value, font_size="1.05rem", color="#e5e7eb", font_family=_MONO),
        rx.text(hint, font_size="0.62rem", color="#4b5563"),
        spacing="0",
        align="start",
        min_width="8.5rem",
    )


def _mounted(interpolate: bool, hz: int) -> rx.Component:
    """One mounted plan, bound to the one data var.

    ``gun_barrel_marks()`` returns the same nodes the standalone still renderer
    uses, so what is compiled here and what ``to_png`` previews cannot drift.
    Column names are checked against ``SceneCols`` at ``reflex run``.

    The tween duration is matched to ``hz``'s period. It has to be: a tween
    fixed at one duration would finish early and then hold whenever keyframes
    arrive further apart, which is exactly the stutter the interpolation is
    there to remove.
    """
    return reflex_xy.chart(
        *gun_barrel_marks(frame_ms=round(1000 / hz), interpolate=interpolate),
        data=Intro.scene,
        width="100%",
        height="100%",
        # Edge-to-edge, so the plot rect is exactly the box the stage sizes.
        padding=0,
        # Flow control, not telemetry — see `Intro.frame_rendered`.
        on_animation_end=Intro.frame_rendered,
    )


def stage() -> rx.Component:
    """The chart, as one plan per animation policy.

    The animation config is part of the plan, so "tweened at 6 Hz", "tweened at
    12 Hz" and "flip-book" are *different plans* rather than one plan with live
    flags — hence ``rx.match`` over the rate rather than a prop. Every branch is
    compiled and validated at ``reflex run`` and every one binds the same
    ``@reflex_xy.data`` var, so switching swaps the plan and keeps the data.
    """
    return rx.box(
        rx.cond(
            Intro.interpolate,
            rx.match(
                Intro.rate,
                *((hz, _mounted(True, hz)) for hz in _RATES),
                _mounted(True, DEFAULT_RATE),
            ),
            # Snapping has no duration to match, so one plan covers every rate.
            _mounted(False, DEFAULT_RATE),
        ),
        width="100%",
        # The stage carries the world's aspect ratio. Without it the plot rect
        # takes whatever shape the layout gives it and every ring in the barrel
        # renders as an ellipse.
        aspect_ratio=str(WORLD_ASPECT),
        max_height="72vh",
        margin_x="auto",
        border_radius="10px",
        overflow="hidden",
        background="#000000",
        border="1px solid #1f2937",
    )


def transport() -> rx.Component:
    return rx.hstack(
        rx.button(
            rx.cond(Intro.playing, "❚❚  pause", "▶  play"),
            on_click=Intro.play,
            size="3",
            color_scheme="gray",
            variant="solid",
            min_width="7rem",
        ),
        rx.button(
            "↺ restart", on_click=Intro.restart, size="3", variant="soft", color_scheme="gray"
        ),
        rx.vstack(
            rx.hstack(
                rx.text("cycle", font_size="0.7rem", color="#6b7280"),
                rx.text(
                    Intro.clock_text,
                    font_size="0.7rem",
                    color="#9ca3af",
                    font_family=_MONO,
                ),
                rx.badge(Intro.beat, color_scheme="crimson", variant="soft"),
                spacing="2",
                align="center",
            ),
            rx.slider(
                min=0.0,
                max=CYCLE,
                step=0.05,
                value=[Intro.clock],
                on_change=Intro.seek,
                width="100%",
                color_scheme="crimson",
            ),
            spacing="1",
            width="100%",
            flex="1",
        ),
        spacing="4",
        align="center",
        width="100%",
    )


def controls() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text("points per keyframe", font_size="0.68rem", color="#6b7280"),
            rx.select(
                list(POINT_CHOICES),
                value=Intro.points_label,
                on_change=Intro.set_points,
                size="2",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("publish rate", font_size="0.68rem", color="#6b7280"),
            rx.select(
                list(RATE_CHOICES),
                value=Intro.rate_label,
                on_change=Intro.set_rate,
                size="2",
            ),
            spacing="1",
            align="start",
        ),
        rx.vstack(
            rx.text("engine interpolation", font_size="0.68rem", color="#6b7280"),
            rx.hstack(
                rx.switch(
                    checked=Intro.interpolate,
                    on_change=Intro.toggle_interpolation,
                    color_scheme="crimson",
                ),
                rx.text(
                    rx.cond(Intro.interpolate, "tweened", "flip-book"),
                    font_size="0.8rem",
                    color="#9ca3af",
                ),
                spacing="2",
                align="center",
            ),
            spacing="1",
            align="start",
        ),
        spacing="6",
        align="end",
        wrap="wrap",
        width="100%",
    )


def telemetry() -> rx.Component:
    return rx.hstack(
        readout("POINTS", Intro.points_text, "rows per layer set"),
        readout("PAYLOAD / KEYFRAME", Intro.payload_text, "raw f32, no JSON numbers"),
        readout("PUBLISHED", Intro.keyframes.to_string(), "keyframes this run"),
        readout("RATE", Intro.rate_text, "achieved / ceiling"),
        readout("WIRE RATE", Intro.wire_text, "server → browser, measured"),
        readout("BUILD", Intro.build_text, "numpy, per keyframe"),
        spacing="6",
        wrap="wrap",
        width="100%",
    )


def explainer() -> rx.Component:
    return rx.vstack(
        rx.heading("Why this is not 60 frames a second of data", size="4", color="#e5e7eb"),
        rx.text(
            "The server publishes ~12 keyframes a second. The motion you see between "
            'them is the engine\'s: xy.animation(match="index", update="interpolate") '
            "tweens every point's position and color from the previous payload to the "
            "new one. That is correct rather than a smear because the scene keeps row "
            "identity stable — row i is the same rifling sample and the same knee point "
            "in every frame — so a straight line between two keyframes is the true "
            "in-between.",
            color="#9ca3af",
            font_size="0.9rem",
        ),
        rx.unordered_list(
            rx.list_item(
                rx.text.strong("Drop the rate to 6 Hz. "),
                "The motion stays continuous; the tweens simply stretch.",
                color="#9ca3af",
                font_size="0.86rem",
            ),
            rx.list_item(
                rx.text.strong("Switch interpolation off. "),
                "Same feed, now a visible flip-book — that is what the engine is adding.",
                color="#9ca3af",
                font_size="0.86rem",
            ),
            rx.list_item(
                rx.text.strong("Scrub while paused. "),
                "The scene is a pure function of the clock, so any instant renders "
                "on demand — the same property that lets the adapter rebuild the "
                "columns on a fresh worker.",
                color="#9ca3af",
                font_size="0.86rem",
            ),
            rx.list_item(
                rx.text.strong("Turn the points up to 400k. "),
                "The plan, the transport, and the tween are unchanged; only the "
                "column lengths grow — and watch the RATE readout, which reports "
                "what the server actually managed, not what it was asked for. "
                "Past some budget it stops keeping up, and the sequence still "
                "plays at the right speed on fewer, wider-spaced keyframes.",
                color="#9ca3af",
                font_size="0.86rem",
            ),
            spacing="2",
        ),
        rx.text(
            f"Beats: {', '.join(f'{name} {lo:g}-{hi:g}s' for name, (lo, hi) in BEATS.items())}.",
            color="#4b5563",
            font_size="0.75rem",
            font_family=_MONO,
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading("007", size="8", color="#f3f4f6", letter_spacing="0.3em"),
                    rx.text(
                        "the gun-barrel intro, as one xy chart",
                        color="#6b7280",
                        font_size="0.85rem",
                        letter_spacing="0.12em",
                    ),
                    spacing="0",
                    align="start",
                ),
                rx.spacer(),
                rx.badge("xy 0.0.7 + reflex_xy", color_scheme="gray", variant="surface"),
                width="100%",
                align="center",
            ),
            stage(),
            transport(),
            rx.divider(),
            controls(),
            telemetry(),
            rx.divider(),
            explainer(),
            code_accordion("Code — the plan and the data var", stage, Intro.scene),
            code_accordion("Code — the clock", Intro.play, Intro.toggle_interpolation),
            rx.text(
                "scene.py holds the geometry (pure numpy, no xy and no Reflex import); "
                "charts.py holds the plan. Neither knows it is being served by Reflex.",
                color="#4b5563",
                font_size="0.75rem",
            ),
            spacing="5",
            width="100%",
            padding_y="2rem",
        ),
        max_width="1100px",
        background="#08090b",
    )


# The dark theme is configured in rxconfig.py (RadixThemesPlugin).
app = rx.App(style={"background": "#08090b"})
app.add_page(index, route="/", title="007 - the gun-barrel intro", on_load=Intro.measure)
