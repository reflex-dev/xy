"""xy — an experimental Python charting engine.

Cost scales with pixels on screen, not points in the dataset: native Rust core
in the Python process, offset-encoded f32 binary transport, M4 decimation, GPU
density aggregation, and a WebGL2 render client. See spec/design-dossier.md.

One declarative API over one engine — Reflex-flavored composition with
`on_*` event props:

      import xy
      xy.scatter_chart(
          xy.scatter(x="gdp", y="life", color="continent", size="pop", data=df),
          xy.x_axis(label="GDP"), xy.y_axis(label="life expectancy"),
          xy.legend(),
          on_select=lambda sel: print(len(sel), "points"),
      )

Import does no heavy work (§33 import-time budget). Public symbols below are
exported lazily so `import xy` does not import NumPy or dlopen the
native core; those initialize when a chart-building API is first imported/used.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

# ``__getattr__`` materializes this lazily at runtime.  The declaration keeps
# the PEP 561 surface concrete for static consumers without paying the
# ``importlib.metadata`` lookup during ``import xy``.
__version__: str

_EXPORTS = {
    "Annotation": ".components",
    "Animation": ".components",
    "Axis": ".components",
    "CHART_DOM_SLOTS": ".dom",
    "Chart": ".components",
    "Colorbar": ".components",
    "Column": ".columns",
    "ColumnStore": ".columns",
    "Component": ".components",
    "Engine": ".export",
    "ExportConfig": ".components",
    "FacetChart": ".components",
    "Interaction": ".components",
    "Legend": ".components",
    "Mark": ".components",
    "MarkContext": ".plugins",
    "MarkPlugin": ".plugins",
    "Modebar": ".components",
    "Selection": "._figure",
    "Spring": ".components",
    "Theme": ".components",
    "Tooltip": ".components",
    "ZoneMaps": ".columns",
    "area": ".components",
    "animation": ".components",
    "area_chart": ".components",
    "arrow": ".components",
    "bar": ".components",
    "bar_chart": ".components",
    "box": ".components",
    "box_chart": ".components",
    "callout": ".components",
    "chart": ".components",
    "column": ".components",
    "column_chart": ".components",
    "colorbar": ".components",
    "contour": ".components",
    "contour_chart": ".components",
    "ecdf": ".components",
    "ecdf_chart": ".components",
    "facet_chart": ".components",
    "error_band": ".components",
    "error_band_chart": ".components",
    "errorbar": ".components",
    "errorbar_chart": ".components",
    "export_config": ".components",
    "hexbin": ".components",
    "hexbin_chart": ".components",
    "heatmap": ".components",
    "mark": ".components",
    "heatmap_chart": ".components",
    "hline": ".components",
    "hist": ".components",
    "histogram": ".components",
    "histogram_chart": ".components",
    "interaction_config": ".components",
    "label": ".components",
    "legend": ".components",
    "register_mark": ".plugins",
    "registered_marks": ".plugins",
    "unregister_mark": ".plugins",
    "line": ".components",
    "line_chart": ".components",
    "pie_chart": ".components",
    "polar_bar_chart": ".components",
    "polar_chart": ".components",
    "radar_chart": ".components",
    "marker": ".components",
    "modebar": ".components",
    "ribbon": ".components",
    "sankey": ".components",
    "sankey_chart": ".components",
    "scatter": ".components",
    "scatter_chart": ".components",
    "segments": ".components",
    "segments_chart": ".components",
    "step": ".components",
    "step_chart": ".components",
    "structural_probe": ".components",
    "stairs": ".components",
    "stairs_chart": ".components",
    "stem": ".components",
    "stem_chart": ".components",
    "spring": ".components",
    "threshold": ".components",
    "threshold_zone": ".components",
    "triangle_mesh": ".components",
    "triangle_mesh_chart": ".components",
    "theme": ".components",
    "tooltip": ".components",
    "text": ".components",
    "vline": ".components",
    "x_band": ".components",
    "write_images": ".export",
    "r_axis": ".components",
    "theta_axis": ".components",
    "wind_rose": ".components",
    "x_axis": ".components",
    "y_band": ".components",
    "y_axis": ".components",
    "violin": ".components",
    "violin_chart": ".components",
}

__all__ = [
    "CHART_DOM_SLOTS",
    "Animation",
    "Annotation",
    "Axis",
    "Chart",
    "Colorbar",
    "Column",
    "ColumnStore",
    "Component",
    "Engine",
    "ExportConfig",
    "FacetChart",
    "Interaction",
    "Legend",
    "Mark",
    "MarkContext",
    "MarkPlugin",
    "Modebar",
    "Selection",
    "Spring",
    "Theme",
    "Tooltip",
    "ZoneMaps",
    "__version__",
    "animation",
    "area",
    "area_chart",
    "arrow",
    "bar",
    "bar_chart",
    "box",
    "box_chart",
    "callout",
    "chart",
    "colorbar",
    "column",
    "column_chart",
    "contour",
    "contour_chart",
    "ecdf",
    "ecdf_chart",
    "error_band",
    "error_band_chart",
    "errorbar",
    "errorbar_chart",
    "export_config",
    "facet_chart",
    "heatmap",
    "heatmap_chart",
    "hexbin",
    "hexbin_chart",
    "hist",
    "histogram",
    "histogram_chart",
    "hline",
    "interaction_config",
    "label",
    "legend",
    "line",
    "line_chart",
    "mark",
    "marker",
    "modebar",
    "pie_chart",
    "polar_bar_chart",
    "polar_chart",
    "r_axis",
    "radar_chart",
    "register_mark",
    "registered_marks",
    "ribbon",
    "sankey",
    "sankey_chart",
    "scatter",
    "scatter_chart",
    "segments",
    "segments_chart",
    "spring",
    "stairs",
    "stairs_chart",
    "stem",
    "stem_chart",
    "step",
    "step_chart",
    "structural_probe",
    "text",
    "theme",
    "theta_axis",
    "threshold",
    "threshold_zone",
    "tooltip",
    "triangle_mesh",
    "triangle_mesh_chart",
    "unregister_mark",
    "violin",
    "violin_chart",
    "vline",
    "wind_rose",
    "write_images",
    "x_axis",
    "x_band",
    "y_axis",
    "y_band",
]


def _load_export(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def _load_version() -> str:
    """Resolve the installed distribution's version.

    The version is not written down in the source tree at all — it is derived
    from the `v*` git tag at build time (pyproject's uv-dynamic-versioning
    config) and baked into the wheel's METADATA, so package metadata is the
    only place that can answer this at runtime.

    Resolved lazily, like every other export: `importlib.metadata` costs tens
    of milliseconds against a 200 ms `import xy` budget (§33), which is a poor
    trade for a string most callers never read. A source tree that was never
    installed has no metadata to read, and reports the same unreal `0.0.0` the
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


if TYPE_CHECKING:
    from ._figure import Selection
    from .columns import Column, ColumnStore, ZoneMaps
    from .components import (
        Animation,
        Annotation,
        Axis,
        Chart,
        Colorbar,
        Component,
        ExportConfig,
        FacetChart,
        Interaction,
        Legend,
        Mark,
        Modebar,
        Spring,
        Theme,
        Tooltip,
        animation,
        area,
        area_chart,
        arrow,
        bar,
        bar_chart,
        box,
        box_chart,
        callout,
        chart,
        colorbar,
        column,
        column_chart,
        contour,
        contour_chart,
        ecdf,
        ecdf_chart,
        error_band,
        error_band_chart,
        errorbar,
        errorbar_chart,
        export_config,
        facet_chart,
        heatmap,
        heatmap_chart,
        hexbin,
        hexbin_chart,
        hist,
        histogram,
        histogram_chart,
        hline,
        interaction_config,
        label,
        legend,
        line,
        line_chart,
        mark,
        marker,
        modebar,
        pie_chart,
        polar_bar_chart,
        polar_chart,
        r_axis,
        radar_chart,
        ribbon,
        sankey,
        sankey_chart,
        scatter,
        scatter_chart,
        segments,
        segments_chart,
        spring,
        stairs,
        stairs_chart,
        stem,
        stem_chart,
        step,
        step_chart,
        structural_probe,
        text,
        theme,
        theta_axis,
        threshold,
        threshold_zone,
        tooltip,
        triangle_mesh,
        triangle_mesh_chart,
        violin,
        violin_chart,
        vline,
        wind_rose,
        x_axis,
        x_band,
        y_axis,
        y_band,
    )
    from .dom import CHART_DOM_SLOTS
    from .export import Engine, write_images
    from .plugins import (
        MarkContext,
        MarkPlugin,
        register_mark,
        registered_marks,
        unregister_mark,
    )
