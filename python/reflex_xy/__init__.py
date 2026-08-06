"""Reflex integration for xy figures.

The integration in one paragraph (full design:
spec/design/reflex-integration.md in the xy repo): chart data rides
the app's *existing* websocket as a second socket.io namespace — binary
columns, no JSON numbers, no extra endpoints to proxy. Figures and columns
live in a per-process registry keyed by tokens; Reflex state holds only
small typed handles. State methods are both the definition and the
recovery recipe: any worker can rebuild what it serves from state when a
reconnect lands somewhere new, so there is no central figure store to
operate.

Quickstart (the data-bound component API — structure is declared in the
page and validated at ``reflex run``; state supplies only columns)::

    # rxconfig.py
    config = rx.Config(app_name="dash", plugins=[reflex_xy.XYPlugin()])

    # dash/dash.py
    from typing import TypedDict
    import numpy as np
    import reflex as rx
    import reflex_xy

    class CloudData(TypedDict):
        x: np.ndarray
        y: np.ndarray
        mag: np.ndarray

    class Dash(rx.State):
        points: int = 200_000

        @reflex_xy.data
        def cloud(self) -> CloudData:
            rng = np.random.default_rng(7)
            x = rng.normal(size=self.points)
            y = x * 0.6 + rng.normal(scale=0.6, size=self.points)
            return {"x": x, "y": y, "mag": np.hypot(x, y)}

    def index() -> rx.Component:
        return reflex_xy.scatter_chart(
            data=Dash.cloud,
            x="x", y="y", color="mag", colormap="viridis",
            height="460px",
        )

    app = rx.App()

Multi-mark charts compose xy nodes around the same data var
(``reflex_xy.chart(reflex_xy.scatter("x", "y"), reflex_xy.line("x", "mag"),
data=Dash.cloud)``), and charts whose *structure* depends on state keep the
escape hatch: an ``@reflex_xy.figure`` method returning an ``xy.Chart``,
rendered with ``reflex_xy.chart(figure=Dash.built)`` and probed at compile
(§3.1 of the design).
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
    "chart": ".factories",
    "area_chart": ".factories",
    "bar_chart": ".factories",
    "column_chart": ".factories",
    "error_band_chart": ".factories",
    "errorbar_chart": ".factories",
    "histogram_chart": ".factories",
    "line_chart": ".factories",
    "scatter_chart": ".factories",
    "segments_chart": ".factories",
    "stem_chart": ".factories",
    "step_chart": ".factories",
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

#: Curated re-exports of xy node constructors: `reflex_xy.scatter` *is*
#: `xy.scatter`, so composed data-bound charts read uniformly
#: (`reflex_xy.chart(reflex_xy.scatter("x", "y"), data=...)`) and a
#: hallucinated constructor dies at import against this explicit map
#: instead of surviving to hydrate. Marks whose validators need data
#: (box, violin, hexbin, …) are still listed — the plan probe refuses them
#: with the recorded Phase 3 guidance rather than a misleading
#: AttributeError. Chart factories are deliberately absent: the flat
#: `*_chart` names above are reflex-native factories, not xy's.
_XY_REEXPORTS = frozenset(
    {
        # marks
        "scatter",
        "line",
        "area",
        "step",
        "stairs",
        "stem",
        "column",
        "bar",
        "histogram",
        "errorbar",
        "error_band",
        "segments",
        "ecdf",
        "box",
        "violin",
        "hexbin",
        "contour",
        "heatmap",
        # annotations
        "vline",
        "hline",
        "x_band",
        "y_band",
        "text",
        "label",
        "marker",
        "arrow",
        "threshold",
        "threshold_zone",
        "callout",
        # chrome + config constructors
        "x_axis",
        "y_axis",
        "theta_axis",
        "r_axis",
        "legend",
        "tooltip",
        "colorbar",
        "modebar",
        "export_config",
        "theme",
        "interaction_config",
        "animation",
        "spring",
    }
)

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
    "animation",
    "append",
    "area",
    "area_chart",
    "arrow",
    "bar",
    "bar_chart",
    "box",
    "callout",
    "chart",
    "clear_selection",
    "colorbar",
    "column",
    "column_chart",
    "contour",
    "data",
    "ecdf",
    "error_band",
    "error_band_chart",
    "errorbar",
    "errorbar_chart",
    "export_config",
    "figure",
    "heatmap",
    "hexbin",
    "histogram",
    "histogram_chart",
    "hline",
    "inline",
    "interaction_config",
    "label",
    "legend",
    "line",
    "line_chart",
    "marker",
    "modebar",
    "r_axis",
    "register",
    "registry",
    "release",
    "reset_view",
    "resolve_selection",
    "scatter",
    "scatter_chart",
    "segments",
    "segments_chart",
    "select",
    "set_view",
    "setup",
    "spring",
    "stairs",
    "stem",
    "stem_chart",
    "step",
    "step_chart",
    "text",
    "theme",
    "theta_axis",
    "threshold",
    "threshold_zone",
    "tooltip",
    "violin",
    "vline",
    "x_axis",
    "x_band",
    "y_axis",
    "y_band",
]


def _load_export(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        if name in _XY_REEXPORTS:
            import xy

            value = getattr(xy, name)
            globals()[name] = value
            return value
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
    # The curated xy node re-exports (`_XY_REEXPORTS`) resolve at runtime
    # through `__getattr__`; restate them here so a type checker sees the real
    # constructor signatures instead of `Any` (or nothing at all).
    from xy import (
        animation,
        area,
        arrow,
        bar,
        box,
        callout,
        colorbar,
        column,
        contour,
        ecdf,
        error_band,
        errorbar,
        export_config,
        heatmap,
        hexbin,
        histogram,
        hline,
        interaction_config,
        label,
        legend,
        line,
        marker,
        modebar,
        r_axis,
        scatter,
        segments,
        spring,
        stairs,
        stem,
        step,
        text,
        theme,
        theta_axis,
        threshold,
        threshold_zone,
        tooltip,
        violin,
        vline,
        x_axis,
        x_band,
        y_axis,
        y_band,
    )

    from .app import XYPlugin, append, clear_selection, reset_view, select, set_view, setup
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
    from .factories import (
        area_chart,
        bar_chart,
        chart,
        column_chart,
        error_band_chart,
        errorbar_chart,
        histogram_chart,
        line_chart,
        scatter_chart,
        segments_chart,
        stem_chart,
        step_chart,
    )
    from .handles import DataHandle, FigureHandle
    from .namespace import XY_NAMESPACE, XYNamespace
    from .registry import FigureRegistry, registry
    from .selections import resolve_selection
    from .vars import AsyncFigureVar, FigureVar, figure
