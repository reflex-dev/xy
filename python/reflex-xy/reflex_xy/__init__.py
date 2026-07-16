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

import hashlib
import json
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
    "inline",
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


def inline(chart_or_figure: Any) -> str:
    """Register a fixed, kernel-backed chart at module scope; returns its token.

    For charts whose data never changes but which still want server-side
    drilldown/picks on the shared websocket. Call at **module scope** so the
    registration side effect runs in every backend worker (page bodies only
    run where the frontend compiles)::

        cloud = reflex_xy.inline(fc.scatter_chart(fc.scatter(x, y)))

        def index():
            return reflex_xy.chart(cloud, height="460px")

    The token is content-addressed — every worker independently derives the
    same one, so the frontend's baked-in token resolves everywhere without
    state or rebuild hooks. The entry is pinned (exempt from the TTL sweep):
    there is no recipe to rebuild it from, so it lives with the process.

    Shared by design: one figure object serves every viewer, so kernel-side
    drill state is shared too (like N notebook views of one widget). Data
    depending on who's looking belongs in `@reflex_xy.figure`; data needing
    no kernel at all can be passed straight to `reflex_xy.chart()` (static
    payload tier).
    """
    fig = _figure_of(chart_or_figure)
    spec, blob = fig.build_payload()
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical + blob).hexdigest()[:20]
    token = f"xyin-{digest}"
    registry.publish(token, fig, broadcast=False, pinned=True)
    return token


def release(token: str) -> None:
    """Drop a registered figure (idempotent)."""
    registry.release(token)
