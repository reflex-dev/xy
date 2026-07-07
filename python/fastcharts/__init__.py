"""fastcharts — an experimental Python charting engine.

Cost scales with pixels on screen, not points in the dataset: native Rust core
in the Python process, offset-encoded f32 binary transport, M4 decimation, GPU
density aggregation, and a WebGL2 render client. See docs/design-dossier.md.

Two APIs over one engine:

- **Fluent** (`Figure().scatter(...).line(...)`) — quick and imperative.
- **Composition** (Reflex-flavored) — declarative, `on_*` event props:

      import fastcharts as fc
      fc.scatter_chart(
          fc.scatter(x="gdp", y="life", color="continent", size="pop", data=df),
          fc.x_axis(label="GDP"), fc.y_axis(label="life expectancy"),
          fc.legend(),
          on_select=lambda sel: print(len(sel), "points"),
      )

Import does no heavy work (§33 import-time budget). Public symbols below are
exported lazily so `import fastcharts` does not import NumPy or dlopen the
native core; those initialize when a chart-building API is first imported/used.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"

_EXPORTS = {
    "Annotation": ".components",
    "Axis": ".components",
    "Chart": ".components",
    "Column": ".columns",
    "ColumnStore": ".columns",
    "Component": ".components",
    "Figure": ".figure",
    "Interaction": ".components",
    "Legend": ".components",
    "Mark": ".components",
    "MarkStyle": ".components",
    "Modebar": ".components",
    "Selection": ".figure",
    "Theme": ".components",
    "Tooltip": ".components",
    "ZoneMaps": ".columns",
    "area": ".components",
    "area_chart": ".components",
    "arrow": ".components",
    "bar": ".components",
    "bar_chart": ".components",
    "callout": ".components",
    "chart": ".components",
    "column": ".components",
    "column_chart": ".components",
    "heatmap": ".components",
    "heatmap_chart": ".components",
    "hline": ".components",
    "hist": ".components",
    "histogram": ".components",
    "histogram_chart": ".components",
    "interaction_config": ".components",
    "label": ".components",
    "legend": ".components",
    "line": ".components",
    "line_chart": ".components",
    "marker": ".components",
    "mark_style": ".components",
    "modebar": ".components",
    "scatter": ".components",
    "scatter_chart": ".components",
    "threshold": ".components",
    "threshold_zone": ".components",
    "theme": ".components",
    "tooltip": ".components",
    "text": ".components",
    "vline": ".components",
    "x_band": ".components",
    "x_axis": ".components",
    "y_band": ".components",
    "y_axis": ".components",
}

__all__ = [
    "Annotation",
    "Axis",
    "Chart",
    "Column",
    "ColumnStore",
    "Component",
    "Figure",
    "Interaction",
    "Legend",
    "Mark",
    "MarkStyle",
    "Modebar",
    "Selection",
    "Theme",
    "Tooltip",
    "ZoneMaps",
    "__version__",
    "area",
    "area_chart",
    "arrow",
    "bar",
    "bar_chart",
    "callout",
    "chart",
    "column",
    "column_chart",
    "heatmap",
    "heatmap_chart",
    "hist",
    "histogram",
    "histogram_chart",
    "hline",
    "interaction_config",
    "label",
    "legend",
    "line",
    "line_chart",
    "mark_style",
    "marker",
    "modebar",
    "scatter",
    "scatter_chart",
    "text",
    "theme",
    "threshold",
    "threshold_zone",
    "tooltip",
    "vline",
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


def __getattr__(name: str) -> Any:
    return _load_export(name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


if TYPE_CHECKING:
    from .columns import Column, ColumnStore, ZoneMaps
    from .components import (
        Annotation,
        Axis,
        Chart,
        Component,
        Interaction,
        Legend,
        Mark,
        MarkStyle,
        Modebar,
        Theme,
        Tooltip,
        area,
        area_chart,
        arrow,
        bar,
        bar_chart,
        callout,
        chart,
        column,
        column_chart,
        heatmap,
        heatmap_chart,
        hist,
        histogram,
        histogram_chart,
        hline,
        interaction_config,
        label,
        legend,
        line,
        line_chart,
        mark_style,
        marker,
        modebar,
        scatter,
        scatter_chart,
        text,
        theme,
        threshold,
        threshold_zone,
        tooltip,
        vline,
        x_axis,
        x_band,
        y_axis,
        y_band,
    )
    from .figure import Figure, Selection
