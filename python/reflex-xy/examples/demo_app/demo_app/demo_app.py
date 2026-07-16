"""reflex-xy demo: one page, every integration surface.

- 1M-point drillable scatter (density tier -> exact points on zoom),
  defined by a `@reflex_xy.figure` state method. Data buffers never touch
  Reflex state; the only chart state is the token string.
- Hover reads exact f64 rows through the data plane and lands in a normal
  Reflex event handler.
- Box-select cross-filters a histogram: the selection summary arrives as a
  small JSON event, the handler bumps a state var, and the histogram's
  figure var recomputes + republishes over the shared websocket.
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

import xy as fc

POINTS = 1_000_000
RNG_SEED = 11


@lru_cache(maxsize=1)
def _cloud(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    # Deterministic source data, cached at module scope: figure builders are
    # pure functions of state, so shared raw columns belong outside them.
    rng = np.random.default_rng(RNG_SEED)
    x = rng.normal(0.0, 1.0, n)
    y = x * 0.55 + rng.normal(0.0, 0.55, n)
    return x, y, np.hypot(x, y)


class Demo(rx.State):
    """Charts are figure vars; everything else is ordinary app state."""

    hovered: dict = {}
    select_note: str = "box-select on the scatter to cross-filter"
    sel_x0: float = 0.0
    sel_x1: float = 0.0
    sel_active: bool = False
    streaming: bool = False
    _stream_t: float = 0.0

    @reflex_xy.figure
    def cloud(self) -> fc.Chart:
        x, y, mag = _cloud(POINTS)
        return fc.scatter_chart(
            fc.scatter(x, y, color=mag, colormap="viridis", opacity=0.8, density=True),
            fc.x_axis(label="feature A"),
            fc.y_axis(label="feature B"),
            title=f"{POINTS // 1_000_000}M points, drillable",
            width="100%",
            height=460,
        )

    @reflex_xy.figure
    def histogram(self) -> fc.Chart:
        x, _, mag = _cloud(POINTS)
        if self.sel_active and self.sel_x1 > self.sel_x0:
            mag = mag[(x >= self.sel_x0) & (x <= self.sel_x1)]
        label = "selection" if self.sel_active else "all points"
        return fc.histogram_chart(
            fc.histogram(mag, bins=80),
            fc.x_axis(label=f"magnitude ({label})"),
            title="magnitude distribution",
            width="100%",
            height=220,
        )

    @reflex_xy.figure
    def live(self) -> fc.Chart:
        return fc.line_chart(
            fc.line(np.array([0.0]), np.array([0.0])),
            title="live stream",
            width="100%",
            height=220,
        )

    @rx.event
    def on_hover(self, row: dict):
        self.hovered = row

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


def sparkline_chart() -> fc.Chart:
    """A fixed chart passed *directly* to reflex_xy.chart(): compiled to a
    static payload asset at page build — no token, no registry, no socket."""
    t = np.linspace(0.0, 6.0 * np.pi, 4000)
    decay = np.exp(-t / 9.0)
    return fc.line_chart(
        fc.line(t, np.sin(t) * decay, name="signal"),
        fc.line(t, decay, name="envelope"),
        fc.x_axis(label="t"),
        title="static payload (no backend)",
        width="100%",
        height=220,
    )


def hover_readout() -> rx.Component:
    return rx.hstack(
        rx.badge("hover"),
        rx.text(
            rx.cond(
                Demo.hovered.length() > 0,
                f"x={Demo.hovered['x']}  y={Demo.hovered['y']}",
                "move the cursor over the cloud",
            ),
            font_family="monospace",
            font_size="13px",
        ),
        spacing="3",
        align="center",
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
                on_select_end=Demo.on_select,
                height="460px",
                id="cloud",
            ),
            hover_readout(),
            rx.hstack(
                rx.vstack(
                    reflex_xy.chart(Demo.histogram, height="220px", id="hist"),
                    rx.text(Demo.select_note, size="2", color_scheme="gray"),
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
