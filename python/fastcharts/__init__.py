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

Import does no heavy work (§33 import-time budget); the native core loads on
first use via `fastcharts.kernels`.
"""

from __future__ import annotations

from .column import Column, ColumnStore, ZoneMaps
from .components import (
    Chart,
    candlestick,
    candlestick_chart,
    legend,
    line,
    line_chart,
    scatter,
    scatter_chart,
    x_axis,
    y_axis,
)
from .figure import Figure, Selection

__version__ = "0.1.0"

__all__ = [
    "Chart",
    "Column",
    "ColumnStore",
    "Figure",
    "Selection",
    "ZoneMaps",
    "__version__",
    "candlestick",
    "candlestick_chart",
    "legend",
    "line",
    "line_chart",
    "scatter",
    "scatter_chart",
    "x_axis",
    "y_axis",
]
