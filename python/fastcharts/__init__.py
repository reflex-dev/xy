"""fastcharts — a faster charting engine.

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
    "Chart": ".components",
    "Column": ".columns",
    "ColumnStore": ".columns",
    "Figure": ".figure",
    "Selection": ".figure",
    "ZoneMaps": ".columns",
    "area": ".components",
    "area_chart": ".components",
    "bar": ".components",
    "bar_chart": ".components",
    "column": ".components",
    "column_chart": ".components",
    "heatmap": ".components",
    "heatmap_chart": ".components",
    "hist": ".components",
    "histogram": ".components",
    "histogram_chart": ".components",
    "legend": ".components",
    "line": ".components",
    "line_chart": ".components",
    "scatter": ".components",
    "scatter_chart": ".components",
    "x_axis": ".components",
    "y_axis": ".components",
}

__all__ = [
    "Chart",
    "Column",
    "ColumnStore",
    "Figure",
    "Selection",
    "ZoneMaps",
    "__version__",
    "area",
    "area_chart",
    "bar",
    "bar_chart",
    "column",
    "column_chart",
    "heatmap",
    "heatmap_chart",
    "hist",
    "histogram",
    "histogram_chart",
    "legend",
    "line",
    "line_chart",
    "scatter",
    "scatter_chart",
    "x_axis",
    "y_axis",
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
        Chart,
        area,
        area_chart,
        bar,
        bar_chart,
        column,
        column_chart,
        heatmap,
        heatmap_chart,
        hist,
        histogram,
        histogram_chart,
        legend,
        line,
        line_chart,
        scatter,
        scatter_chart,
        x_axis,
        y_axis,
    )
    from .figure import Figure, Selection
