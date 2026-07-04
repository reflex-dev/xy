"""View-dependent LOD machinery shared by aggregated chart kinds (§5/§28).

Everything here is chart-agnostic — nothing knows about scatter. It covers the
mechanics every tiered chart repeats:

- the visible-window mask (§19: non-finite rows never enter a subset),
- the hysteresis-guarded drill decision (§5: tier = f(visible_count)),
- drilled-subset bookkeeping on a Trace (shipped_sel / drill_mode / drill_seq,
  the §16/§17 index-space versioning),
- §16 window-centered offset encoding for shipped geometry,
- the screen-derived aggregation grid shape,
- per-point local log-density (the drill handoff's LUT coordinate),
- wire-buffer packing (raw f32, §29).

`interaction.density_view` wires these together for scatter; a future
heatmap/histogram tier reuses them with a different aggregate kernel — the
per-chart-kind rules live in the LOD/Tiling Contract (§28).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import kernels
from .config import DENSITY_TARGET_POINTS_PER_CELL, DRILL_EXIT_FACTOR


def normalize_window(
    x0: float, x1: float, y0: float, y1: float
) -> tuple[float, float, float, float]:
    """Order a possibly-flipped request window as (lo_x, hi_x, lo_y, hi_y)."""
    return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)


def visible_mask(
    xv: np.ndarray, yv: np.ndarray, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> np.ndarray:
    """Boolean mask of rows inside the window. NaN/±inf compare False on
    either side, so non-finite rows never enter a drilled subset (§19)."""
    return (xv >= lo_x) & (xv <= hi_x) & (yv >= lo_y) & (yv <= hi_y)


def drill_decision(
    visible: int, budget: float, in_drill: bool, exit_factor: float = DRILL_EXIT_FACTOR
) -> bool:
    """§5: the tier is a function of the *visible* count, hysteresis-guarded —
    once drilled, stay until the count clearly exceeds the budget again."""
    return visible <= budget * (exit_factor if in_drill else 1.0)


def enter_drill(trace: Any, sel: np.ndarray) -> int:
    """Adopt `sel` as the trace's shipped subset. Picks/selections translate
    through it (§17), and the version bump invalidates in-flight replies built
    against the previous subset (§16: exact or nothing). Returns the seq."""
    trace.drill_mode = True
    trace.shipped_sel = sel
    trace.drill_seq += 1
    return trace.drill_seq


def exit_drill(trace: Any) -> None:
    """Back to the aggregate: no per-point marks, no pick mapping. Bumps the
    version when leaving an actual drill so a drilled-index pick arriving late
    is rejected instead of being read as a *canonical* index."""
    if trace.drill_mode:
        trace.drill_seq += 1
    trace.drill_mode = False
    trace.shipped_sel = None


class BufferWriter:
    """Accumulates a view-update's binary buffers (raw f32 on the wire, §29).
    The update spec references entries by index — the same shape every tiered
    chart's incremental updates use."""

    def __init__(self) -> None:
        self.buffers: list[bytes] = []

    def add_f32(self, arr: np.ndarray) -> int:
        self.buffers.append(np.ascontiguousarray(arr, dtype=np.float32).tobytes())
        return len(self.buffers) - 1

    def add_raw(self, raw: bytes) -> int:
        self.buffers.append(raw)
        return len(self.buffers) - 1


def encode_window_xy(
    xs: np.ndarray, ys: np.ndarray, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Offset-encode a drilled subset re-centered on the window midpoint (§16
    deep-zoom rule) — f32 precision follows the viewport, not the dataset."""
    x_off = (lo_x + hi_x) / 2.0
    y_off = (lo_y + hi_y) / 2.0
    if len(xs):
        x_enc = kernels.encode_f32(xs, x_off, 1.0)
        y_enc = kernels.encode_f32(ys, y_off, 1.0)
    else:
        x_enc = y_enc = np.empty(0, dtype=np.float32)
    return x_off, y_off, x_enc, y_enc


def grid_shape(
    w: int, h: int, visible: int, target_per_cell: float = DENSITY_TARGET_POINTS_PER_CELL
) -> tuple[int, int]:
    """Keep aggregation grids screen-bounded, but avoid one-pixel bins when
    the visible count is only barely over the direct budget. A few points per
    cell gives smoother drill-out aggregates and smaller updates."""
    w = max(16, min(int(w), 4096))
    h = max(16, min(int(h), 4096))
    requested = w * h
    if visible <= 0:
        return w, h
    target = min(requested, max(16 * 16, int(np.ceil(visible / target_per_cell))))
    if target >= requested:
        return w, h
    scale = float(np.sqrt(target / requested))
    return max(16, int(round(w * scale))), max(16, int(round(h * scale)))


def local_log_density(
    xs: np.ndarray,
    ys: np.ndarray,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
    gw: int,
    gh: int,
) -> np.ndarray:
    """Per-point log-normalized local density in [0,1] — the LUT coordinate
    the client blends during the drill handoff so freshly drilled marks wear
    the aggregate's colormap (§5: never a palette jump)."""
    n = len(xs)
    dval = np.zeros(n, dtype=np.float32)
    if n and hi_x > lo_x and hi_y > lo_y:
        grid = kernels.bin_2d(xs, ys, lo_x, hi_x, lo_y, hi_y, gw, gh)
        gmax = float(grid.max()) if grid.size else 0.0
        if gmax > 0:
            ix = np.clip(((xs - lo_x) * (gw / (hi_x - lo_x))).astype(np.int64), 0, gw - 1)
            iy = np.clip(((ys - lo_y) * (gh / (hi_y - lo_y))).astype(np.int64), 0, gh - 1)
            dval = (np.log1p(grid[iy, ix]) / np.log1p(gmax)).astype(np.float32)
    return dval
