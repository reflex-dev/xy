"""reflex-xy showcase: ways to link chart data into a Reflex app.

One page of five sections; each has a "Code" accordion showing its own source
via `inspect.getsource`.

1. **Live figure var + events.** A 1M-point drillable scatter from an
   ``@reflex_xy.figure`` state method; its data rides the app websocket while
   Reflex state holds only the token. Hover, click, and box-select arrive as
   ordinary Reflex events.
2. **A chart driven by state vars.** A histogram whose bin count is a slider var
   and whose data is cross-filtered by §1's box-selection; changing either
   recomputes the figure and re-publishes it under a stable token.
3. **A dynamically updating chart.** A line grown from a background task via
   ``reflex_xy.append``.
4. **Data computed from ``on_view_change``.** Pan/zoom an overview scatter; a
   detail figure recomputes from the window the view-change event reports.
5. **Fixed data, two ways.** A ``xy.Chart`` passed straight to
   ``reflex_xy.chart`` (static payload tier) and a ``reflex_xy.inline`` token
   (fixed data served through the kernel).

Run from ``examples/reflex``::

    uv run reflex run
"""

from __future__ import annotations

import asyncio
import inspect
from functools import lru_cache
from typing import Any

import numpy as np
import reflex as rx
import reflex_xy
from reflex_xy.tokens import BUILDER_ATTR

import xy

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


# --- fixed-data charts (module scope) ---------------------------------------


def sparkline_chart() -> xy.Chart:
    """A fixed chart passed directly to ``reflex_xy.chart``, which compiles it
    to a static payload asset."""
    t = np.linspace(0.0, 6.0 * np.pi, 4000)
    decay = np.exp(-t / 9.0)
    return xy.line_chart(
        xy.line(t, np.sin(t) * decay, name="signal"),
        xy.line(t, decay, name="envelope"),
        xy.x_axis(label="t"),
        title="static payload tier",
        width="100%",
        height=240,
    )


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
ORBITS_TOKEN = reflex_xy.inline(orbits_chart())


# --- state ------------------------------------------------------------------


class Demo(rx.State):
    """Charts are figure vars; everything else is ordinary app state."""

    # §1 semantic events
    hovered: dict = {}
    clicked: dict = {}
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

    @reflex_xy.figure
    def cloud(self) -> xy.Chart:
        x, y, mag = _cloud(POINTS)
        return xy.scatter_chart(
            xy.scatter(x, y, color=mag, colormap="viridis", opacity=0.8, density=True),
            # hover and click are off by default; enable them so the point
            # events reach the handlers below (select/pan/zoom are on already).
            xy.interaction_config(hover=True, click=True),
            xy.x_axis(label="feature A"),
            xy.y_axis(label="feature B"),
            title=f"{POINTS // 1_000_000}M points, drillable",
            width="100%",
            height=460,
        )

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

    @reflex_xy.figure
    def overview(self) -> xy.Chart:
        x, y = _scan(120_000)
        return xy.scatter_chart(
            xy.scatter(x, y, opacity=0.5, density=True),
            xy.interaction_config(zoom_axes=("x",)),
            xy.x_axis(label="t"),
            xy.y_axis(label="value"),
            title="overview — zoom the x range",
            width="100%",
            height=240,
        )

    @reflex_xy.figure
    def detail(self) -> xy.Chart:
        # Recomputed from the window the overview last reported through
        # `on_view_change`: a histogram of only the y-values currently in view.
        x, y = _scan(120_000)
        if self.view_ready and self.view_x1 > self.view_x0:
            y = y[(x >= self.view_x0) & (x <= self.view_x1)]
        title = (
            f"detail — {y.size:,} points in view"
            if self.view_ready
            else "detail — pan/zoom the overview"
        )
        return xy.histogram_chart(
            xy.histogram(y, bins=48, color="#7c3aed"),
            xy.x_axis(label="value in view"),
            title=title,
            width="100%",
            height=240,
        )

    @rx.event
    def on_hover(self, row: dict):
        self.hovered = row

    @rx.event
    def on_click(self, row: dict):
        self.clicked = row

    @rx.event
    def on_select(self, selection: dict):
        total = int(selection.get("total") or 0)
        if total and selection.get("x0") is not None:
            self.sel_x0 = float(selection["x0"])
            self.sel_x1 = float(selection["x1"])
            self.sel_active = True
            self.select_note = f"{total:,} points selected"
        else:
            self.sel_active = False
            self.select_note = "selection cleared"

    @rx.event
    def set_bins(self, value: list[int | float]):
        self.bins = int(value[0])

    @rx.event
    def on_view(self, view: dict):
        # `view` is the small view-change payload: {x0, x1, y0, y1, ...}. Store
        # the window; the `detail` figure var depends on it and recomputes.
        self.view_x0 = float(view.get("x0", 0.0))
        self.view_x1 = float(view.get("x1", 0.0))
        self.view_ready = True
        x, _ = _scan(120_000)
        self.visible = int(((x >= self.view_x0) & (x <= self.view_x1)).sum())

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


# §1 wiring — the live figure var and its semantic events
def cloud_view() -> rx.Component:
    return reflex_xy.chart(
        Demo.cloud,
        on_point_hover=Demo.on_hover,
        on_point_click=Demo.on_click,
        on_select_end=Demo.on_select,
        height="460px",
        id="cloud",
    )


# §2 wiring — a chart driven by a slider and another chart's selection
def histogram_view() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(Demo.histogram, height="240px", id="hist"),
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
        reflex_xy.chart(Demo.live, height="240px", id="live"),
        rx.button(
            rx.cond(Demo.streaming, "stop stream", "go live"),
            on_click=Demo.stream,
            id="stream-btn",
        ),
        width="100%",
        spacing="2",
    )


# §4 wiring — a detail chart computed from the overview's view-change events
def viewport_view() -> rx.Component:
    return rx.grid(
        reflex_xy.chart(Demo.overview, on_view_change=Demo.on_view, height="240px", id="overview"),
        reflex_xy.chart(Demo.detail, height="240px", id="detail"),
        columns="2",
        gap="1rem",
        width="100%",
    )


# §5 wiring — the two fixed-data tiers
def fixed_view() -> rx.Component:
    return rx.grid(
        reflex_xy.chart(sparkline_chart(), height="240px", id="inline"),
        reflex_xy.chart(ORBITS_TOKEN, height="240px", id="orbits"),
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
                "1 · Live figure var + events",
                "A 1M-point drillable scatter from an @reflex_xy.figure method. "
                "Zoom to drill density into exact points; hover, click, and box-select.",
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
                            f"x={Demo.clicked['x']}  y={Demo.clicked['y']}",
                            "zoom in to drill, then click a point",
                        ),
                    ),
                    width="100%",
                    spacing="3",
                ),
                code_accordion(
                    Demo.cloud, Demo.on_hover, Demo.on_click, Demo.on_select, cloud_view
                ),
            ),
            section(
                "2 · A chart driven by state vars",
                "The histogram's bin count is a slider var, and its data is "
                "cross-filtered by the box-selection above. Changing either "
                "re-publishes the figure under a stable token.",
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
                "Zoom the overview's x range; the detail histogram recomputes from "
                "only the points in view, driven by the view-change event.",
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
                code_accordion(Demo.overview, Demo.detail, Demo.on_view, viewport_view),
            ),
            section(
                "5 · Fixed data, two ways",
                "Left: a xy.Chart passed straight to reflex_xy.chart, compiled to "
                "a static payload asset. Right: a reflex_xy.inline token, whose "
                "fixed data answers hover/pick from the kernel.",
                fixed_view(),
                code_accordion(sparkline_chart, orbits_chart, fixed_view),
            ),
            spacing="5",
            width="100%",
        ),
        size="4",
        padding_y="28px",
    )


app = rx.App()
app.add_page(index, title="reflex-xy showcase")
