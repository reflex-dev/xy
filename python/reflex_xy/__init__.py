"""Reflex integration for xy figures.

The integration in one paragraph (full design:
spec/design/reflex-integration.md in the xy repo): chart data rides
the app's *existing* websocket as a second socket.io namespace — binary
columns, no JSON numbers, no extra endpoints to proxy. Figures live in a
per-process registry keyed by tokens; Reflex state holds only a small typed
handle wrapping the token. A `@reflex_xy.figure` state method is both the
chart definition and the recovery recipe: any worker can rebuild the figure
from state when a reconnect lands somewhere new, so there is no central
figure store to operate.

Quickstart::

    # rxconfig.py
    config = rx.Config(app_name="dash", plugins=[reflex_xy.XYPlugin()])

    # dash/dash.py
    import numpy as np
    import reflex as rx
    import xy
    import reflex_xy

    class Dash(rx.State):
        points: int = 200_000

        @reflex_xy.figure
        def chart(self) -> xy.Chart:
            rng = np.random.default_rng(7)
            xs = rng.normal(size=self.points)
            ys = xs * 0.6 + rng.normal(scale=0.6, size=self.points)
            return xy.scatter_chart(xy.scatter(xs, ys), width="100%", height=460)

    def index() -> rx.Component:
        return reflex_xy.chart(figure=Dash.chart, height="460px")

    app = rx.App()
"""

from __future__ import annotations

import hashlib
import json
import sys
from importlib import import_module
from typing import TYPE_CHECKING, Any

_EXPORTS = {
    "XYPlugin": ".app",
    "append": ".app",
    "clear_selection": ".app",
    "reset_view": ".app",
    "select": ".app",
    "set_view": ".app",
    "setup": ".app",
    "chart": ".component",
    "AsyncDataVar": ".data_vars",
    "DataVar": ".data_vars",
    "data": ".data_vars",
    "DataHandle": ".handles",
    "FigureHandle": ".handles",
    "CanonicalRowIdGroup": ".events",
    "DataBounds": ".events",
    "Modifiers": ".events",
    "PointClickEvent": ".events",
    "PointData": ".events",
    "PointHoverEvent": ".events",
    "ScreenPoint": ".events",
    "SelectEndEvent": ".events",
    "SelectionPayload": ".events",
    "ViewChangeEvent": ".events",
    "XY_NAMESPACE": ".namespace",
    "XYNamespace": ".namespace",
    "FigureRegistry": ".registry",
    "registry": ".registry",
    "resolve_selection": ".selections",
    "AsyncFigureVar": ".vars",
    "FigureVar": ".vars",
    "figure": ".vars",
}

__all__ = [
    "XY_NAMESPACE",
    "AsyncDataVar",
    "AsyncFigureVar",
    "CanonicalRowIdGroup",
    "DataBounds",
    "DataHandle",
    "DataVar",
    "FigureHandle",
    "FigureRegistry",
    "FigureVar",
    "Modifiers",
    "PointClickEvent",
    "PointData",
    "PointHoverEvent",
    "ScreenPoint",
    "SelectEndEvent",
    "SelectionPayload",
    "ViewChangeEvent",
    "XYNamespace",
    "XYPlugin",
    "append",
    "chart",
    "clear_selection",
    "data",
    "figure",
    "inline",
    "register",
    "registry",
    "release",
    "reset_view",
    "resolve_selection",
    "select",
    "set_view",
    "setup",
]


def _load_export(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)

    # Importing a child module binds it on its parent package. Loading `.app`,
    # for example, imports `.registry` and would otherwise replace the public
    # singleton export with the `reflex_xy.registry` module object.
    registry_module = sys.modules.get(f"{__name__}.registry")
    if registry_module is not None:
        globals()["registry"] = registry_module.registry

    globals()[name] = value
    return value


def _load_version() -> str:
    """Resolve ``__version__`` lazily from the installed distribution.

    The version is not written down in the source tree — it is derived from
    the latest ``xy`` release tag at build time and baked into the wheel's
    METADATA, so package metadata is the only place that can answer this at
    runtime. An uninstalled source tree reports the same unreal ``0.0.0`` the
    build-time fallback uses.
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _distribution_version

    try:
        return _distribution_version("xy")
    except PackageNotFoundError:
        return "0.0.0"


def __getattr__(name: str) -> Any:
    if name == "__version__":
        value = _load_version()
        globals()["__version__"] = value
        return value
    return _load_export(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def register(chart_or_figure: Any) -> "FigureHandle":
    """Imperatively register a chart; returns a typed handle for state.

    The handle's ``.token`` is the registry key; pass the handle itself to
    ``chart(figure=...)`` (or store it in state). Dev-tier API: the figure
    lives only in this process and cannot be rebuilt after a worker restart
    or on another node — prefer `@reflex_xy.figure` for anything long-lived
    (see the module doc).
    """
    from .handles import FigureHandle
    from .registry import _figure_of, registry

    globals()["registry"] = registry

    return FigureHandle(registry.register(_figure_of(chart_or_figure)))


def inline(chart_or_figure: Any) -> "FigureHandle":
    """Register a fixed, kernel-backed chart at module scope; returns its handle.

    For charts whose data never changes but which still want server-side
    drilldown/picks on the shared websocket. Call at **module scope** so the
    registration side effect runs in every backend worker (page bodies only
    run where the frontend compiles)::

        cloud = reflex_xy.inline(xy.scatter_chart(xy.scatter(x, y)))

        def index():
            return reflex_xy.chart(figure=cloud, height="460px")

    The handle's token is content-addressed — every worker independently
    derives the same one, so the frontend's baked-in token resolves
    everywhere without state or rebuild hooks. The entry is pinned (exempt
    from the TTL sweep): there is no recipe to rebuild it from, so it lives
    with the process.

    Shared by design: one figure object serves every viewer, so kernel-side
    drill state is shared too (like N notebook views of one widget). Data
    depending on who's looking belongs in `@reflex_xy.figure`; data needing
    no kernel at all can be passed straight to `reflex_xy.chart()` (static
    payload tier).
    """
    from .handles import FigureHandle
    from .registry import _figure_of, registry

    globals()["registry"] = registry

    fig = _figure_of(chart_or_figure)
    spec, blob = fig.build_payload()
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical + blob).hexdigest()[:20]
    token = f"xyin-{digest}"
    registry.publish(token, fig, broadcast=False, pinned=True)
    return FigureHandle(token)


def release(token: "str | FigureHandle") -> None:
    """Drop a registered figure (idempotent). Takes a handle or its token."""
    from .handles import token_of
    from .registry import registry

    globals()["registry"] = registry

    resolved = token_of(token)
    if resolved is None:
        msg = f"expected a FigureHandle or figure token string, got {type(token).__name__}"
        raise TypeError(msg)
    registry.release(resolved)


if TYPE_CHECKING:
    from .app import XYPlugin, append, clear_selection, reset_view, select, set_view, setup
    from .component import chart
    from .data_vars import AsyncDataVar, DataVar, data
    from .events import (
        CanonicalRowIdGroup,
        DataBounds,
        Modifiers,
        PointClickEvent,
        PointData,
        PointHoverEvent,
        ScreenPoint,
        SelectEndEvent,
        SelectionPayload,
        ViewChangeEvent,
    )
    from .handles import DataHandle, FigureHandle
    from .namespace import XY_NAMESPACE, XYNamespace
    from .registry import FigureRegistry, registry
    from .selections import resolve_selection
    from .vars import AsyncFigureVar, FigureVar, figure
