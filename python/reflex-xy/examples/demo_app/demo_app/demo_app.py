"""reflex-xy demo: one page, every integration surface.

- 1M-point drillable scatter (density tier -> exact points on zoom),
  defined by a `@reflex_xy.figure` state method. Data buffers never touch
  Reflex state; the only chart state is the token string.
- Hover reads exact f64 rows through the data plane and lands in a normal
  Reflex event handler.
- Click, box-select, and view-change handlers visibly record their v1 event
  envelopes and force the source chart to republish behind its stable token.
- Box-select cross-filters a histogram: bounded semantic rows arrive in a
  small JSON event, complete rows can be re-resolved server-side, and both
  figure vars recompute + republish over the shared websocket.
- A live line streams from a background task via `reflex_xy.append`.

Run:  uv pip install -e '.[dev]' && uv pip install -e python/reflex-xy
      cd python/reflex-xy/examples/demo_app && reflex run
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

import numpy as np
import reflex as rx
import reflex_xy

import xy

POINTS = 1_000_000
RNG_SEED = 11


@lru_cache(maxsize=1)
def _cloud(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Deterministic source data, cached at module scope: figure builders are
    # pure functions of state, so shared raw columns belong outside them.
    rng = np.random.default_rng(RNG_SEED)
    x = rng.normal(0.0, 1.0, n)
    y = x * 0.55 + rng.normal(0.0, 0.55, n)
    segment = np.where(x < 0, "west", "east")
    return x, y, np.hypot(x, y), segment


async def _magnitudes() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Async data source for the histogram builder — stands in for a
    database, HTTP endpoint, or dataframe-store round trip."""
    await asyncio.sleep(0)
    x, _, mag, segment = _cloud(POINTS)
    return x, mag, segment


class Demo(rx.State):
    """Charts are figure vars; everything else is ordinary app state."""

    hover_note: str = "move the cursor over the cloud"
    click_note: str = "click a point to inspect its canonical row"
    select_note: str = "box-select on the scatter to cross-filter"
    view_note: str = "pan or zoom to emit a debounced view event"
    click_events: int = 0
    select_events: int = 0
    view_events: int = 0
    interaction_revision: int = 0
    sel_x0: float = 0.0
    sel_x1: float = 0.0
    sel_active: bool = False
    selected_segments: list[str] = []
    streaming: bool = False
    _stream_t: float = 0.0

    @reflex_xy.figure
    def cloud(self) -> xy.Chart:
        x, y, _, segment = _cloud(POINTS)
        return xy.scatter_chart(
            xy.scatter(x, y, color=segment, opacity=0.8, density=True),
            xy.x_axis(label="feature A"),
            xy.y_axis(label="feature B"),
            # Click/select/view handlers bump this revision, deliberately
            # republishing the source figure. The wrapper must preserve its
            # viewport and selection without dispatching feedback events.
            title=(
                f"{POINTS // 1_000_000}M points, drillable · "
                f"handler revision {self.interaction_revision}"
            ),
            width="100%",
            height=460,
        )

    @reflex_xy.figure
    async def histogram(self) -> xy.Chart:
        # Async builder: reflex evaluates it as an AsyncComputedVar, so the
        # data pull can await a database / HTTP endpoint / dataframe store.
        x, mag, segment = await _magnitudes()
        if self.sel_active and self.sel_x1 > self.sel_x0:
            keep = (x >= self.sel_x0) & (x <= self.sel_x1)
            if self.selected_segments:
                keep &= np.isin(segment, self.selected_segments)
            mag = mag[keep]
        label = "selection" if self.sel_active else "all points"
        return xy.histogram_chart(
            xy.histogram(mag, bins=80),
            xy.x_axis(label=f"magnitude ({label})"),
            title="magnitude distribution",
            width="100%",
            height=220,
        )

    @reflex_xy.figure
    def live(self) -> xy.Chart:
        return xy.line_chart(
            xy.line(np.array([0.0]), np.array([0.0])),
            title="live stream",
            width="100%",
            height=220,
        )

    @rx.event
    def on_hover(self, event: dict):
        data = event.get("data", {})
        self.hover_note = (
            f"row {event.get('canonical_row_id')} · x={data.get('x')} y={data.get('y')}"
        )

    @rx.event
    def on_click(self, event: dict):
        self.click_events += 1
        self.interaction_revision += 1
        data = event.get("data", {})
        screen = event.get("screen", {})
        modifiers = event.get("modifiers", {})
        active_modifiers = [name for name, active in modifiers.items() if active]
        self.click_note = (
            f"row {event.get('canonical_row_id')} · "
            f"x={data.get('x')} y={data.get('y')} · "
            f"canvas=({screen.get('x')}, {screen.get('y')}) · "
            f"modifiers={','.join(active_modifiers) or 'none'}"
        )

    @rx.event
    def on_select(self, event: dict):
        self.select_events += 1
        self.interaction_revision += 1
        selection = event.get("selection", {})
        total = int(selection.get("total_count") or 0)
        bounds = selection.get("data_bounds")
        if total and bounds:
            self.sel_x0 = float(bounds["x0"])
            self.sel_x1 = float(bounds["x1"])
            self.sel_active = True
            self.selected_segments = sorted(
                {
                    str(row["color_category"])
                    for row in selection.get("rows", [])
                    if row.get("color_category") is not None
                }
            )
            complete = reflex_xy.resolve_selection(event)
            complete_count = len(complete) if complete is not None else total
            self.select_note = (
                f"{total:,} selected · {len(selection.get('rows', [])):,} rows / "
                f"{sum(len(group.get('ids', [])) for group in selection.get('canonical_row_ids', [])):,} ids in JSON · "
                f"truncated={bool(selection.get('truncated'))} · "
                f"{complete_count:,} resolved server-side · segments="
                f"{','.join(self.selected_segments) or 'none'}"
            )
        else:
            self.sel_active = False
            self.selected_segments = []
            self.select_note = "selection cleared"

    @rx.event
    def on_view(self, event: dict):
        self.view_events += 1
        self.interaction_revision += 1
        self.view_note = (
            f"x={event.get('x_domain')} · y={event.get('y_domain')} · "
            f"source={event.get('source')} · phase={event.get('phase')}"
        )

    @rx.event(background=True)
    async def stream(self):
        async with self:
            if self.streaming:
                self.streaming = False
                return
            self.streaming = True
            token = self.live
        while True:
            async with self:
                if not self.streaming or token != self.live:
                    break
                self._stream_t += 1.0
                t = self._stream_t
            reflex_xy.append(
                token,
                x=[t],
                y=[float(np.sin(t / 9.0) * 4.0 + np.random.default_rng(int(t)).normal(0, 0.4))],
            )
            await asyncio.sleep(0.25)


def sparkline_chart() -> xy.Chart:
    """A fixed chart passed *directly* to reflex_xy.chart(): compiled to a
    static payload asset at page build — no token, no registry, no socket."""
    t = np.linspace(0.0, 6.0 * np.pi, 4000)
    decay = np.exp(-t / 9.0)
    return xy.line_chart(
        xy.line(t, np.sin(t) * decay, name="signal"),
        xy.line(t, decay, name="envelope"),
        xy.x_axis(label="t"),
        title="static payload (no backend)",
        width="100%",
        height=220,
    )


def hover_readout() -> rx.Component:
    return rx.hstack(
        rx.badge("hover"),
        rx.text(
            Demo.hover_note,
            font_family="monospace",
            font_size="13px",
        ),
        spacing="3",
        align="center",
    )


def event_readout(label: str, count: rx.Var[int], note: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.badge(label),
        rx.badge(count, variant="soft", color_scheme="gray"),
        rx.text(note, font_family="monospace", font_size="12px"),
        spacing="3",
        align="center",
        width="100%",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("xy × reflex", size="6"),
            rx.text(
                "chart data rides the app websocket — no extra endpoints, "
                "no JSON numbers, kernel-side drilldown",
                color_scheme="gray",
                size="2",
            ),
            reflex_xy.chart(
                Demo.cloud,
                on_point_hover=Demo.on_hover,
                on_point_click=Demo.on_click,
                on_select_end=Demo.on_select,
                on_view_change=Demo.on_view,
                height="460px",
                id="cloud",
            ),
            hover_readout(),
            event_readout("click", Demo.click_events, Demo.click_note),
            event_readout("select", Demo.select_events, Demo.select_note),
            event_readout("view", Demo.view_events, Demo.view_note),
            rx.hstack(
                rx.vstack(
                    reflex_xy.chart(Demo.histogram, height="220px", id="hist"),
                    width="50%",
                ),
                rx.vstack(
                    reflex_xy.chart(Demo.live, height="220px", id="live"),
                    rx.button(
                        rx.cond(Demo.streaming, "stop stream", "go live"),
                        on_click=Demo.stream,
                        id="stream-btn",
                    ),
                    width="50%",
                ),
                width="100%",
            ),
            # A Chart object passed directly: static payload tier, zero backend.
            reflex_xy.chart(sparkline_chart(), height="220px", id="inline"),
            spacing="4",
            width="100%",
        ),
        size="4",
        padding_y="24px",
    )


app = rx.App()
app.add_page(index, title="reflex-xy demo")
