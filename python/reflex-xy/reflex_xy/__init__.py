"""reflex-xy: xy figures as first-class Reflex components.

The integration in one paragraph (full design:
docs/design/reflex-integration.md in the xy repo): chart data rides
the app's *existing* websocket as a second socket.io namespace — binary
columns, no JSON numbers, no extra endpoints to proxy. Figures live in a
per-process registry keyed by tokens; the tokens live in Reflex state. A
`@reflex_xy.figure` state method is both the chart definition and the
recovery recipe: any worker can rebuild the figure from state when a
reconnect lands somewhere new, so there is no central figure store to
operate.

Quickstart::

    # rxconfig.py
    config = rx.Config(app_name="dash", plugins=[reflex_xy.XYPlugin()])

    # dash/dash.py
    import numpy as np
    import reflex as rx
    import xy as fc
    import reflex_xy

    class Dash(rx.State):
        points: int = 200_000

        @reflex_xy.figure
        def chart(self) -> fc.Chart:
            rng = np.random.default_rng(7)
            xs = rng.normal(size=self.points)
            ys = xs * 0.6 + rng.normal(scale=0.6, size=self.points)
            return fc.scatter_chart(fc.scatter(xs, ys), width="100%", height=460)

    def index() -> rx.Component:
        return reflex_xy.chart(Dash.chart, height="460px")

    app = rx.App()
"""

from __future__ import annotations

from typing import Any

from .app import XYPlugin, append, setup
from .component import chart
from .namespace import XY_NAMESPACE, XYNamespace
from .registry import FigureRegistry, _figure_of, registry
from .vars import FigureVar, figure

__all__ = [
    "XY_NAMESPACE",
    "FigureRegistry",
    "FigureVar",
    "XYNamespace",
    "XYPlugin",
    "append",
    "chart",
    "figure",
    "register",
    "registry",
    "release",
    "setup",
]

__version__ = "0.1.0"


def register(chart_or_figure: Any) -> str:
    """Imperatively register a chart; returns an opaque token for state.

    Dev-tier API: the figure lives only in this process and cannot be
    rebuilt after a worker restart or on another node — prefer
    `@reflex_xy.figure` for anything long-lived (see the module doc).
    """
    return registry.register(_figure_of(chart_or_figure))


def release(token: str) -> None:
    """Drop a registered figure (idempotent)."""
    registry.release(token)
