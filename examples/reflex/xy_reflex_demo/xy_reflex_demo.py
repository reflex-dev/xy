"""XY Reflex showcase: ways to link chart data into a Reflex app.

One page of nine sections; each has a "Code" accordion showing its own source
via `inspect.getsource`. Charts use the data-bound component API — structure
declared in the page, compiled to a validated plan at ``reflex run``, columns
supplied by ``@reflex_xy.data`` state methods — except where a section
demonstrates the tier that behavior genuinely needs: ``@reflex_xy.figure``
when the chart *structure* depends on state (§2), ``reflex_xy.append``
streaming (§3), and ``reflex_xy.inline`` for shared fixed data (§5–§7).

1. **The flagship, data-bound.** A 1M-point drillable scatter composed in the
   page (``reflex_xy.chart(xy.scatter("x", "y", ...), data=Demo.cloud)``);
   ``@reflex_xy.data`` supplies the columns over the app websocket while
   Reflex state holds only a handle. Hover, click, and box-select arrive as
   ordinary Reflex events.
2. **The escape hatch: structure from state.** A histogram whose bin count is
   a slider var — bins are chart *structure*, not columns, so this is an
   ``@reflex_xy.figure`` method; its data is also cross-filtered by §1's
   box-selection, and changing either re-publishes the figure under a stable
   token.
3. **A dynamically updating chart.** A line grown from a background task via
   ``reflex_xy.append``.
4. **Data computed from ``on_view_change``.** Pan/zoom a data-bound overview;
   a second data var reads the reported window from state and republishes
   only the in-view columns — the detail histogram's plan never changes.
5. **Fixed data, two ways.** Concrete columns passed as ``data=`` to a
   composed chart (compiled to a static payload asset) and a
   ``reflex_xy.inline`` token (fixed data served through the kernel).
6. **The drilldown, adapter-native.** The 100M-point live drilldown
   scatter from ``examples/fastapi`` — identical data and mark config — as one
   ``reflex_xy.inline`` token with zero transport code, for A/B-ing the two
   hosts. ``XY_LIVE_POINTS`` resizes it (both apps honor the same override).
7. **Legend hover-highlight and click-to-toggle.** Left: named series on the
   direct tier — hovering a legend row dims the others, clicking hides a
   series entirely client-side (interaction spec §9/§10). Right: a categorical
   density scatter behind an ``inline()`` token — clicking a category row
   sends ``legend_toggle`` over the app websocket and the kernel re-bins the
   surface with that category masked out (§34).
8. **Column republish under a stable handle.** The §8 scatter's slider
   republishes only the columns (``reflex_xy.scatter_chart(data=..., x="x",
   ...)``); the compile-validated plan stays put, and viewport and selection
   survive every republish.
9. **``rx.cond`` + ``rx.foreach``.** Charts are ordinary Reflex components:
   a toggle conditionally swaps a composed three-series board for
   ``rx.foreach`` small multiples over a ``list[DataHandle[...]]`` var —
   one compile-validated plan, one mount per handle, column names checked
   inside the loop (fact R7), and both cond branches validated at
   ``reflex run``.

Run from ``examples/reflex``::

    uv run reflex run
"""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import warnings
from functools import lru_cache
from typing import Any, TypedDict

import numpy as np
import reflex as rx

import reflex_xy
import xy
from reflex_xy import DataHandle
from reflex_xy.tokens import BUILDER_ATTR


def _clamped_slider_value(value: object, lo: int, hi: int) -> int:
    """Server-side bound for a slider event value.

    The browser payload is untrusted input and these values size server
    allocations; the slider's min/max are UI hints, not a security boundary.
    Validate the shape and clamp the number before it reaches state.
    """
    if not isinstance(value, (list, tuple)) or not value:
        msg = f"slider event must be a non-empty [number] list, got {value!r}"
        raise ValueError(msg)
    first = value[0]
    if isinstance(first, bool) or not isinstance(first, (int, float)) or not math.isfinite(first):
        msg = f"slider value must be a finite number, got {first!r}"
        raise ValueError(msg)
    return max(lo, min(hi, int(first)))


class CloudCols(TypedDict):
    """Schema of the §1 and §8 data vars — the factories compile-check the
    column names in the page against these keys (design fact R7)."""

    x: np.ndarray
    y: np.ndarray
    mag: np.ndarray


class ScanCols(TypedDict):
    """Schema of the §4 overview data var."""

    t: np.ndarray
    value: np.ndarray


class InViewCols(TypedDict):
    """Schema of the §4 detail data var (the windowed values)."""

    value: np.ndarray


class SensorCols(TypedDict):
    """Schema of one §9 sensor — the rx.foreach element var keeps this
    parametrization, so column names are compile-checked inside the loop."""

    t: np.ndarray
    reading: np.ndarray


class SensorBoard(TypedDict):
    """Schema of the §9 combined board (all sensors in one table)."""

    t: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray
    gamma: np.ndarray


POINTS = 1_000_000
RNG_SEED = 11


# --- shared source data -----------------------------------------------------
# Shared columns are built once at module scope and cached; the figure builders
# read them and stay pure functions of state.


@lru_cache(maxsize=1)
def _cloud(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(RNG_SEED)
    x = rng.normal(0.0, 1.0, n)
    y = x * 0.55 + rng.normal(0.0, 0.55, n)
    return x, y, np.hypot(x, y)


@lru_cache(maxsize=1)
def _scan(n: int) -> tuple[np.ndarray, np.ndarray]:
    """An overview cloud whose y-distribution varies along x, so zooming into
    different x-windows yields a visibly different detail histogram."""
    rng = np.random.default_rng(5)
    x = rng.uniform(0.0, 100.0, n)
    y = np.sin(x / 6.0) * 12.0 + x * 0.15 + rng.normal(0.0, 4.0, n)
    return x, y


async def _magnitudes() -> tuple[np.ndarray, np.ndarray]:
    """Async data source for the histogram builder; awaits like a database or
    HTTP fetch would."""
    await asyncio.sleep(0)
    x, _, mag = _cloud(POINTS)
    return x, mag


@lru_cache(maxsize=1)
def _sensors() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Three correlated sensor traces for §9 (t, alpha, beta, gamma)."""
    rng = np.random.default_rng(17)
    t = np.linspace(0.0, 48.0, 2400)
    base = 20.0 + 6.0 * np.sin(t / 5.0)
    alpha = base + rng.normal(0.0, 0.7, t.size)
    beta = base * 0.8 + 4.0 * np.sin(t / 3.0 + 1.2) + rng.normal(0.0, 0.7, t.size)
    gamma = base * 1.15 - 3.0 * np.cos(t / 7.0) + rng.normal(0.0, 0.7, t.size)
    return t, alpha, beta, gamma


# --- fixed-data charts (module scope) ---------------------------------------


def orbits_chart() -> xy.Chart:
    """Fixed data registered with ``reflex_xy.inline`` and served through the
    kernel for hover/pick under a content-addressed token."""
    rng = np.random.default_rng(3)
    n = 400_000
    theta = rng.uniform(0.0, 2.0 * np.pi, n)
    r = rng.normal(1.0, 0.05, n) * (1.0 + 0.4 * np.sin(theta * 3.0))
    return xy.scatter_chart(
        xy.scatter(r * np.cos(theta), r * np.sin(theta), opacity=0.6, density=True),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        title="inline() token",
        width="100%",
        height=240,
    )


# Registered at import; the content-addressed token resolves on any backend
# worker.
ORBITS = reflex_xy.inline(orbits_chart())


# --- legend interactivity (§7) ----------------------------------------------


def legend_series_chart() -> xy.Chart:
    """Three named series on the direct tier. Hovering a legend row dims the
    other series; clicking a row hides its series — a pure client hide (0 wire
    bytes), so both work even on this static-payload chart. Defaults are on;
    ``xy.legend(highlight=False)`` / ``xy.legend(toggle=False)`` opt out."""
    rng = np.random.default_rng(7)
    marks = [
        xy.scatter(
            rng.normal(cx, 0.5, 60_000),
            rng.normal(cy, 0.5, 60_000),
            name=name,
            opacity=0.7,
        )
        for name, cx, cy in (
            ("baseline", -1.5, -0.8),
            ("candidate", 0.0, 0.9),
            ("control", 1.6, -0.4),
        )
    ]
    return xy.scatter_chart(
        *marks,
        xy.legend(),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        title="named series — hover dims, click hides",
        width="100%",
        height=300,
    )


def legend_category_chart() -> xy.Chart:
    """One categorical density scatter: a legend row per category. Clicking a
    row sends ``legend_toggle`` over the app websocket; the kernel drops that
    category before re-binning the density surface (§34 — the reply's binning
    is tagged ``-masked``) and the retained sample overlay filters instantly
    while the re-bin is in flight."""
    rng = np.random.default_rng(21)
    n = 1_200_000
    cat = rng.integers(0, 3, n)
    centers = np.array([[-1.2, -0.6], [0.2, 1.1], [1.5, -0.9]])
    x = rng.normal(centers[cat, 0], 0.55)
    y = rng.normal(centers[cat, 1], 0.55)
    labels = np.array(["sensor A", "sensor B", "sensor C"])[cat]
    return xy.scatter_chart(
        xy.scatter(x, y, color=labels, opacity=0.7, density=True),
        xy.legend(),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
        title="categorical density — click a row to mask & re-bin",
        width="100%",
        height=300,
    )


# Kernel-served so category toggles reach `legend_toggle` and the masked
# re-bin path; a static payload would only filter the local sample overlay.
LEGEND_CATS = reflex_xy.inline(legend_category_chart())


# --- the live drilldown, adapter-native (§6) --------------------------


def _drilldown_points() -> int:
    """Point count for the §6 drilldown chart, from ``XY_LIVE_POINTS`` — the
    same override ``examples/fastapi`` honors, so both apps build the identical
    dataset at any size."""
    raw = os.environ.get("XY_LIVE_POINTS")
    if raw is None:
        return 100_000_000
    try:
        points = int(raw)
    except ValueError:
        points = 0
    if points < 1:
        warnings.warn(
            f"XY_LIVE_POINTS={raw!r} is not a positive integer; using 100,000,000",
            RuntimeWarning,
            stacklevel=2,
        )
        return 100_000_000
    return points


DRILLDOWN_POINTS = _drilldown_points()


def _point_label(n: int) -> str:
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n % 1_000 == 0:
        return f"{n // 1_000}k"
    return f"{n:,}"


def drilldown_chart(n: int = DRILLDOWN_POINTS) -> xy.Chart:
    """The ``examples/fastapi`` live-drilldown scatter: same seed, same chunked
    generation, same mark config. That app wires the chart through its own
    HTTP transport (a Starlette endpoint plus a comm bridge); here the
    kernel's density tiers answer every pan/zoom over the app websocket."""
    rng = np.random.default_rng(11)
    x = np.empty(n, dtype=np.float64)
    y = np.empty(n, dtype=np.float64)
    color = np.empty(n, dtype=np.float64)
    size = np.empty(n, dtype=np.float64)
    chunk = 1_000_000
    for start in range(0, n, chunk):
        end = min(start + chunk, n)
        xs = rng.normal(0, 1.0, end - start)
        ys = rng.normal(0, 0.55, end - start)
        ys += xs * 0.55
        ss = rng.normal(6, 2.5, end - start)
        np.abs(ss, out=ss)
        np.clip(ss, 2, 16, out=ss)
        x[start:end] = xs
        y[start:end] = ys
        np.hypot(xs, ys, out=color[start:end])
        size[start:end] = ss
    return xy.scatter_chart(
        xy.scatter(x, y, color=color, size=size, colormap="viridis", opacity=0.72, density=True),
        xy.x_axis(label="feature A"),
        xy.y_axis(label="feature B"),
        title=f"{_point_label(n)} live drilldown scatter",
        width="100%",
        height=430,
    )


# One shared kernel-backed figure for every viewer, expressed as a single
# inline() token; the registry keeps it process-global.
DRILLDOWN = reflex_xy.inline(drilldown_chart())


# --- state ------------------------------------------------------------------


class Demo(rx.State):
    """Data-bound charts read columns from ``@reflex_xy.data`` vars; the §2
    histogram is an ``@reflex_xy.figure`` var (its structure reads state);
    everything else is ordinary app state."""

    # §1 semantic events
    hovered: dict = {}
    clicked: dict = {}
    click_events: int = 0
    select_events: int = 0
    # §2 state-driven + cross-filter
    bins: int = 60
    sel_active: bool = False
    sel_x0: float = 0.0
    sel_x1: float = 0.0
    select_note: str = "box-select on the scatter to cross-filter the histogram"
    # §3 streaming
    streaming: bool = False
    _stream_t: float = 0.0
    # §4 viewport-computed detail
    view_ready: bool = False
    view_x0: float = 0.0
    view_x1: float = 0.0
    visible: int = 0

    @reflex_xy.data
    def cloud(self) -> CloudCols:
        # Columns only — the chart structure lives in the page (cloud_view)
        # as a compile-validated plan; this method never runs at compile.
        x, y, mag = _cloud(POINTS)
        return {"x": x, "y": y, "mag": mag}

    @reflex_xy.figure
    async def histogram(self) -> xy.Chart:
        # Reads `bins` and the selection window; changing either re-publishes
        # the figure. The async builder may await a data source.
        x, mag = await _magnitudes()
        if self.sel_active and self.sel_x1 > self.sel_x0:
            mag = mag[(x >= self.sel_x0) & (x <= self.sel_x1)]
        label = "selection" if self.sel_active else "all points"
        return xy.histogram_chart(
            xy.histogram(mag, bins=self.bins),
            xy.x_axis(label=f"magnitude ({label})"),
            title=f"magnitude distribution — {self.bins} bins",
            width="100%",
            height=240,
        )

    @reflex_xy.figure
    def live(self) -> xy.Chart:
        return xy.line_chart(
            xy.line(np.array([0.0]), np.array([0.0])),
            title="live stream",
            width="100%",
            height=240,
        )

    @reflex_xy.data
    def scan_points(self) -> ScanCols:
        t, value = _scan(120_000)
        return {"t": t, "value": value}

    @reflex_xy.data
    def in_view(self) -> InViewCols:
        # Republished from the window the overview last reported through
        # `on_view_change`: only the values currently in view. The detail
        # histogram's plan is fixed; this data var is what changes.
        t, value = _scan(120_000)
        if self.view_ready and self.view_x1 > self.view_x0:
            value = value[(t >= self.view_x0) & (t <= self.view_x1)]
        return {"value": value}

    @rx.event
    def on_hover(self, event: reflex_xy.PointHoverEvent):
        # v1 point envelope: canonical_row_id + f64 data coordinates.
        self.hovered = event.get("data", {})

    @rx.event
    def on_click(self, event: reflex_xy.PointClickEvent):
        self.click_events += 1
        modifiers = event.get("modifiers", {})
        self.clicked = {
            "row": event.get("canonical_row_id"),
            **event.get("data", {}),
            "modifiers": ",".join(k for k, v in modifiers.items() if v) or "none",
        }

    @rx.event
    def on_select(self, event: reflex_xy.SelectEndEvent):
        self.select_events += 1
        selection = event.get("selection", {})
        total = int(selection.get("total_count") or 0)
        bounds = selection.get("data_bounds") or {}
        if total and bounds.get("x0") is not None:
            self.sel_x0 = float(bounds["x0"])
            self.sel_x1 = float(bounds["x1"])
            self.sel_active = True
            self.select_note = (
                f"{total:,} selected · {len(selection.get('rows', [])):,} rows in JSON · "
                f"truncated={bool(selection.get('truncated'))}"
            )
        else:
            self.sel_active = False
            self.select_note = "selection cleared"

    @rx.event
    def set_bins(self, value: list[int | float]):
        # mirrors the slider's min/max server-side: bins size an allocation
        self.bins = _clamped_slider_value(value, 20, 160)

    @rx.event
    def on_view(self, event: reflex_xy.ViewChangeEvent):
        # `event` is the v1 view-change envelope; `x_domain` is the reported
        # [x0, x1] window (throttled by the wrapper, streaming during the
        # gesture). Store the window; the `detail` figure var depends on it
        # and recomputes.
        x_domain = event.get("x_domain") or [0.0, 0.0]
        self.view_x0 = float(x_domain[0])
        self.view_x1 = float(x_domain[1])
        self.view_ready = True
        x, _ = _scan(120_000)
        self.visible = int(((x >= self.view_x0) & (x <= self.view_x1)).sum())

    # §8 data-bound component: state supplies columns, the page declares the
    # chart. The slider republishes only the columns; the chart structure is
    # a compile-validated plan baked into the JSX.
    bound_points: int = 150_000

    @reflex_xy.data
    def bound_cloud(self) -> CloudCols:
        rng = np.random.default_rng(23)
        x = rng.normal(size=self.bound_points)
        y = x * 0.6 + rng.normal(scale=0.6, size=self.bound_points)
        return {"x": x, "y": y, "mag": np.hypot(x, y)}

    @rx.event
    def set_bound_points(self, value: list[int | float]):
        # mirrors the slider's min/max server-side: this value sizes the
        # arrays bound_cloud allocates, so it must be clamped here, not
        # trusted from the wire
        self.bound_points = _clamped_slider_value(value, 10_000, 1_000_000)

    # §9 cond + foreach: one combined board or per-sensor small multiples.
    split: bool = False

    @reflex_xy.data
    def board(self) -> SensorBoard:
        t, alpha, beta, gamma = _sensors()
        return {"t": t, "alpha": alpha, "beta": beta, "gamma": gamma}

    @reflex_xy.data
    def sensor_alpha(self) -> SensorCols:
        t, alpha, _, _ = _sensors()
        return {"t": t, "reading": alpha}

    @reflex_xy.data
    def sensor_beta(self) -> SensorCols:
        t, _, beta, _ = _sensors()
        return {"t": t, "reading": beta}

    @reflex_xy.data
    def sensor_gamma(self) -> SensorCols:
        t, _, _, gamma = _sensors()
        return {"t": t, "reading": gamma}

    @rx.var
    def sensor_handles(self) -> list[DataHandle[SensorCols]]:
        """A typed handle list: rx.foreach charts stay schema-checked (R7)."""
        return [self.sensor_alpha, self.sensor_beta, self.sensor_gamma]

    @rx.event
    def toggle_split(self):
        self.split = not self.split

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


# --- introspection: the "Code" accordions -----------------------------------


def _source(obj: Any) -> str:
    """Source of a plain function, an ``@reflex_xy.figure`` var, or an
    ``@rx.event`` handler."""
    # Class-level access to an object-valued computed var hands back reflex's
    # casted wrapper; the declared var (with its fget) sits behind _original.
    obj = getattr(obj, "_original", obj)
    fget = getattr(obj, "_fget", None)
    if fget is not None:  # a @reflex_xy.figure / computed var
        builder = getattr(fget, BUILDER_ATTR, None)
        return inspect.getsource(builder if builder is not None else fget)
    handler = getattr(obj, "fn", None)
    if handler is not None:  # an @rx.event handler
        return inspect.getsource(handler)
    return inspect.getsource(obj)


def code_accordion(*objs: Any) -> rx.Component:
    source = "\n\n".join(inspect.cleandoc("\n" + _source(obj)) for obj in objs)
    return rx.el.details(
        rx.el.summary(
            "Code",
            cursor="pointer",
            padding="0.75rem 1rem",
            font_weight="700",
            font_size="0.85rem",
            list_style="none",
        ),
        rx.el.pre(
            rx.el.code(source),
            margin="0",
            padding="1rem 1.15rem",
            background="#0b1120",
            color="#e5e7eb",
            font_size="0.78rem",
            line_height="1.55",
            overflow_x="auto",
            white_space="pre",
            border_top="1px solid rgba(148,163,184,0.2)",
        ),
        border_top="1px solid var(--gray-5)",
        width="100%",
    )


# --- layout -----------------------------------------------------------------


def section(title: str, blurb: str, body: rx.Component, code: rx.Component) -> rx.Component:
    return rx.box(
        rx.box(
            rx.heading(title, size="5"),
            rx.text(blurb, color_scheme="gray", size="2", margin_top="0.25rem"),
            padding="1rem 1.15rem",
        ),
        rx.box(body, padding="0 1.15rem 1.15rem"),
        code,
        border="1px solid var(--gray-5)",
        border_radius="12px",
        background="var(--gray-1)",
        overflow="hidden",
        width="100%",
    )


def kv(label: str, value: Any) -> rx.Component:
    return rx.hstack(
        rx.badge(label),
        rx.text(value, font_family="monospace", font_size="13px"),
        spacing="3",
        align="center",
    )


# §1 wiring — the chart composed in the page, bound to the cloud data var.
# Marks and chrome are plain xy nodes compiled to a validated plan at
# `reflex run`; a wrong column, colormap, or kwarg fails the compile.
def cloud_view() -> rx.Component:
    return reflex_xy.chart(
        xy.scatter("x", "y", color="mag", colormap="viridis", opacity=0.8, density=True),
        # hover and click are off by default; enable them so the point
        # events reach the state handlers (select/pan/zoom are on already).
        xy.interaction_config(hover=True, click=True),
        xy.x_axis(label="feature A"),
        xy.y_axis(label="feature B"),
        data=Demo.cloud,
        title=f"{POINTS // 1_000_000}M points, drillable — declared in the page",
        on_point_hover=Demo.on_hover,
        on_point_click=Demo.on_click,
        on_select_end=Demo.on_select,
        height="460px",
        id="cloud",
    )


# §2 wiring — a chart driven by a slider and another chart's selection
def histogram_view() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(figure=Demo.histogram, height="240px", id="hist"),
        rx.hstack(
            rx.text("bins", size="2", color_scheme="gray"),
            rx.slider(
                default_value=[60], min=20, max=160, step=10, on_change=Demo.set_bins, id="bins"
            ),
            rx.text(Demo.bins, font_family="monospace", size="2", width="2.5rem"),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.text(Demo.select_note, size="2", color_scheme="gray"),
        width="100%",
        spacing="2",
    )


# §3 wiring — a chart that grows from a background task
def live_view() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(figure=Demo.live, height="240px", id="live"),
        rx.button(
            rx.cond(Demo.streaming, "stop stream", "go live"),
            on_click=Demo.stream,
            id="stream-btn",
        ),
        width="100%",
        spacing="2",
    )


# §4 wiring — two data-bound charts: the overview reports its window through
# on_view_change; the in_view data var reads that window from state and
# republishes the filtered column into the detail histogram's fixed plan.
def viewport_view() -> rx.Component:
    return rx.grid(
        reflex_xy.chart(
            xy.scatter("t", "value", opacity=0.5, density=True),
            xy.interaction_config(zoom_axes=("x",)),
            xy.x_axis(label="t"),
            xy.y_axis(label="value"),
            data=Demo.scan_points,
            title="overview — zoom the x range",
            on_view_change=Demo.on_view,
            height="240px",
            id="overview",
        ),
        reflex_xy.histogram_chart(
            data=Demo.in_view,
            values="value",
            bins=48,
            color="#7c3aed",
            x_axis=xy.x_axis(label="value in view"),
            title="detail — the points in view",
            height="240px",
            id="detail",
        ),
        columns="2",
        gap="1rem",
        width="100%",
    )


# §5 wiring — the two fixed-data tiers. Concrete columns as data= compile the
# composed chart to a static payload asset (renders kernel-less, works under
# `reflex export`); the inline() token serves fixed data through the kernel.
def sparkline_view() -> rx.Component:
    t = np.linspace(0.0, 6.0 * np.pi, 4000)
    decay = np.exp(-t / 9.0)
    return reflex_xy.chart(
        xy.line("t", "signal", name="signal"),
        xy.line("t", "envelope", name="envelope"),
        xy.x_axis(label="t"),
        data={"t": t, "signal": np.sin(t) * decay, "envelope": decay},
        title="static payload tier",
        height="240px",
        id="inline",
    )


def fixed_view() -> rx.Component:
    return rx.grid(
        sparkline_view(),
        reflex_xy.chart(figure=ORBITS, height="240px", id="orbits"),
        columns="2",
        gap="1rem",
        width="100%",
    )


# §6 wiring — the whole drilldown integration is this one line
def drilldown_view() -> rx.Component:
    return reflex_xy.chart(figure=DRILLDOWN, height="430px", id="drilldown")


# §8 wiring — the data-bound component: chart declared where it renders,
# state supplies only columns. Channels, colormap, and column names are all
# validated at compile (`reflex run` fails on a typo, not the browser).
def bound_view() -> rx.Component:
    return rx.vstack(
        reflex_xy.scatter_chart(
            data=Demo.bound_cloud,
            x="x",
            y="y",
            color="mag",
            colormap="viridis",
            mark_opacity=0.75,
            density=True,
            x_axis=xy.x_axis(label="feature A"),
            y_axis=xy.y_axis(label="feature B"),
            title="declared in the page, fed by @reflex_xy.data",
            height="300px",
            id="bound",
        ),
        rx.hstack(
            rx.text("points", size="2", color_scheme="gray"),
            rx.slider(
                default_value=[150_000],
                min=10_000,
                max=1_000_000,
                step=10_000,
                on_change=Demo.set_bound_points,
                id="bound-points",
            ),
            rx.text(Demo.bound_points, font_family="monospace", size="2", width="5.5rem"),
            width="100%",
            align="center",
            spacing="3",
        ),
        width="100%",
        spacing="2",
    )


# §9 wiring — charts are ordinary components, so rx.cond and rx.foreach just
# work. Both cond branches are built at page evaluation (both plans compile-
# validate); the foreach lambda runs once against the element var, producing
# ONE plan that mounts once per handle in the list.
def cond_foreach_view() -> rx.Component:
    combined = reflex_xy.chart(
        xy.line("t", "alpha", name="alpha"),
        xy.line("t", "beta", name="beta"),
        xy.line("t", "gamma", name="gamma"),
        xy.legend(),
        xy.x_axis(label="hours"),
        data=Demo.board,
        title="all sensors — one composed board",
        height="260px",
        id="board",
    )
    multiples = rx.grid(
        rx.foreach(
            Demo.sensor_handles,
            lambda handle: reflex_xy.area_chart(
                data=handle,
                x="t",
                y="reading",
                color="#0284c7",
                mark_opacity=0.5,
                height="180px",
            ),
        ),
        columns="3",
        gap="1rem",
        width="100%",
    )
    return rx.vstack(
        rx.cond(Demo.split, multiples, combined),
        rx.button(
            rx.cond(Demo.split, "one combined board", "small multiples"),
            on_click=Demo.toggle_split,
            id="split-btn",
        ),
        width="100%",
        spacing="2",
    )


# §7 wiring — legend interactivity ships with the charts; no handlers needed
def legend_view() -> rx.Component:
    return rx.grid(
        reflex_xy.chart(legend_series_chart(), height="300px", id="legend-series"),
        reflex_xy.chart(figure=LEGEND_CATS, height="300px", id="legend-cats"),
        columns="2",
        gap="1rem",
        width="100%",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("xy × reflex", size="8"),
            rx.text(
                "Chart data rides the app websocket as binary buffers, with "
                "kernel-side drilldown. Each section shows its own source below.",
                color_scheme="gray",
                size="3",
            ),
            section(
                "1 · The flagship, data-bound",
                "A 1M-point drillable scatter declared in the page: composed xy "
                "marks compile to a validated plan at reflex run, and "
                "@reflex_xy.data supplies only the columns. Zoom to drill "
                "density into exact points; hover, click, and box-select "
                "arrive as ordinary Reflex events.",
                rx.vstack(
                    cloud_view(),
                    kv(
                        "hover",
                        rx.cond(
                            Demo.hovered.length() > 0,
                            f"x={Demo.hovered['x']}  y={Demo.hovered['y']}",
                            "zoom in to drill, then hover a point",
                        ),
                    ),
                    kv(
                        "click",
                        rx.cond(
                            Demo.clicked.length() > 0,
                            f"row {Demo.clicked['row']} · x={Demo.clicked['x']}  "
                            f"y={Demo.clicked['y']} · modifiers={Demo.clicked['modifiers']}",
                            "zoom in to drill, then click a point",
                        ),
                    ),
                    kv(
                        "events",
                        f"{Demo.click_events} clicks · {Demo.select_events} selections",
                    ),
                    width="100%",
                    spacing="3",
                ),
                code_accordion(
                    Demo.cloud, Demo.on_hover, Demo.on_click, Demo.on_select, cloud_view
                ),
            ),
            section(
                "2 · The escape hatch: structure from state",
                "The histogram's bin count is a slider var — bins are chart "
                "structure, not columns, so this chart is an @reflex_xy.figure "
                "method rather than a plan. Its data is also cross-filtered by "
                "the box-selection above; changing either re-publishes the "
                "figure under a stable token.",
                histogram_view(),
                code_accordion(Demo.histogram, Demo.set_bins, histogram_view),
            ),
            section(
                "3 · A dynamically updating chart",
                "A line grown by a background task via reflex_xy.append; points "
                "are pushed to subscribers as they arrive.",
                live_view(),
                code_accordion(Demo.live, Demo.stream, live_view),
            ),
            section(
                "4 · Data computed from on_view_change",
                "Zoom the overview's x range; the in_view data var reads the "
                "reported window from state and republishes only the in-view "
                "column — the detail histogram's plan never changes, its data "
                "does.",
                rx.vstack(
                    viewport_view(),
                    kv(
                        "view",
                        rx.cond(
                            Demo.view_ready,
                            f"x ∈ [{Demo.view_x0}, {Demo.view_x1}] · {Demo.visible} points",
                            "pan or zoom the overview",
                        ),
                    ),
                    width="100%",
                    spacing="3",
                ),
                code_accordion(Demo.scan_points, Demo.in_view, Demo.on_view, viewport_view),
            ),
            section(
                "5 · Fixed data, two ways",
                "Left: concrete columns passed as data= to a composed chart, "
                "compiled to a static payload asset (no kernel, works under "
                "reflex export). Right: a reflex_xy.inline token, whose fixed "
                "data answers hover/pick from the kernel.",
                fixed_view(),
                code_accordion(sparkline_view, orbits_chart, fixed_view),
            ),
            section(
                f"6 · The {_point_label(DRILLDOWN_POINTS)} drilldown, adapter-native",
                "The live drilldown scatter from examples/fastapi — same data, "
                "same mark config — with the adapter replacing that app's custom "
                "HTTP transport (Starlette endpoint plus comm bridge). Zoom until "
                "the density surface drills into exact points; XY_LIVE_POINTS "
                "resizes both apps for side-by-side comparison.",
                drilldown_view(),
                code_accordion(drilldown_chart, drilldown_view),
            ),
            section(
                "7 · Legend: hover to emphasize, click to toggle",
                "Hover a legend row to dim every other series; click it to "
                "hide/show what it stands for. Left: named series — a pure "
                "client-side hide (0 wire bytes). Right: a categorical density "
                "scatter served by the kernel — a category click sends "
                "legend_toggle over the app websocket and the surface is "
                "re-binned with the category masked out (§34). Both default "
                "on: xy.legend(highlight=False) / xy.legend(toggle=False) "
                "opt out.",
                legend_view(),
                code_accordion(legend_series_chart, legend_category_chart, legend_view),
            ),
            section(
                "8 · Column republish under a stable handle",
                "The flat single-mark form of the same API as §1: "
                "reflex_xy.scatter_chart(data=Demo.bound_cloud, x='x', y='y', ...). "
                "The slider republishes only the columns under a stable handle; "
                "the compile-validated plan stays put, and viewport and "
                "selection survive every republish.",
                bound_view(),
                code_accordion(Demo.bound_cloud, Demo.set_bound_points, bound_view),
            ),
            section(
                "9 · rx.cond + rx.foreach",
                "Charts are ordinary Reflex components. The toggle swaps a "
                "composed three-series board for rx.foreach small multiples "
                "over a list[DataHandle[SensorCols]] var: one compile-validated "
                "plan, mounted once per handle, column names checked inside "
                "the loop — and both cond branches validate at reflex run.",
                cond_foreach_view(),
                code_accordion(
                    Demo.sensor_alpha, Demo.sensor_handles, Demo.toggle_split, cond_foreach_view
                ),
            ),
            spacing="5",
            width="100%",
        ),
        size="4",
        padding_y="28px",
    )


app = rx.App()
app.add_page(index, title="XY Reflex showcase")
