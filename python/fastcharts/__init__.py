"""fastcharts — a faster charting engine.

Cost scales with pixels on screen, not points in the dataset: native Rust core
in the Python process, offset-encoded f32 binary transport, M4 decimation, and
a WebGL2 render client. See docs/design-dossier.md for the full design.

Import does no heavy work (§33 import-time budget); the native core loads on
first use via `fastcharts.kernels`.
"""

from __future__ import annotations

from .column import Column, ColumnStore, ZoneMaps
from .figure import Figure

__version__ = "0.1.0"

__all__ = ["Column", "ColumnStore", "Figure", "ZoneMaps", "__version__"]
