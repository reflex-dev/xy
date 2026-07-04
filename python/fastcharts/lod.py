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
from .config import DENSITY_TARGET_POINTS_PER_CELL, DRILL_EXIT_FACTOR, MAX_SCREEN_DIM


def normalize_window(
    x0: float, x1: float, y0: float, y1: float, *, require_area: bool = True
) -> tuple[float, float, float, float]:
    """Order a possibly-flipped request window as (lo_x, hi_x, lo_y, hi_y).

    Browser events are untrusted input at this boundary: reject NaN/inf before
    native kernels see them, and before a failed LOD request can mutate drill
    state.
    """
    if any(isinstance(v, (bool, np.bool_)) for v in (x0, x1, y0, y1)):
        raise ValueError("view window bounds must be finite")
    try:
        vals = [float(v) for v in (x0, x1, y0, y1)]
    except (TypeError, ValueError) as e:
        raise ValueError("view window bounds must be finite") from e
    if not all(np.isfinite(vals)):
        raise ValueError("view window bounds must be finite")
    lo_x, hi_x = min(vals[0], vals[1]), max(vals[0], vals[1])
    lo_y, hi_y = min(vals[2], vals[3]), max(vals[2], vals[3])
    if require_area and (lo_x == hi_x or lo_y == hi_y):
        raise ValueError("view window must have non-zero width and height")
    return lo_x, hi_x, lo_y, hi_y


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


# Encoded extremes stay well inside f32 (max ~3.4e38); the margin also keeps
# the client's 1/(span*scale) map uniforms clear of f32 subnormals.
F32_SAFE_MAG = 1e37


def f32_safe_scale(offset: float, lo: float, hi: float) -> float:
    """Scale for offset-encoding so finite f64 can never overflow f32 (§19:
    nothing non-finite may reach a vertex buffer — a 1e300-magnitude domain
    would otherwise encode to ±inf). Exactly 1.0 for every normal domain, so
    the common path is unchanged; only absurd magnitudes normalize."""
    half = max(abs(lo - offset), abs(hi - offset))
    if not np.isfinite(half) or half <= F32_SAFE_MAG:
        return 1.0
    return F32_SAFE_MAG / half


def encode_window_xy(
    xs: np.ndarray, ys: np.ndarray, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> tuple[dict, dict, np.ndarray, np.ndarray]:
    """Offset-encode a drilled subset re-centered on the window midpoint (§16
    deep-zoom rule) — f32 precision follows the viewport, not the dataset.
    Returns wire metas ({offset, scale}) plus the encoded arrays."""
    x_off = (lo_x + hi_x) / 2.0
    y_off = (lo_y + hi_y) / 2.0
    x_scale = f32_safe_scale(x_off, lo_x, hi_x)
    y_scale = f32_safe_scale(y_off, lo_y, hi_y)
    if len(xs):
        x_enc = kernels.encode_f32(xs, x_off, x_scale)
        y_enc = kernels.encode_f32(ys, y_off, y_scale)
    else:
        x_enc = y_enc = np.empty(0, dtype=np.float32)
    return (
        {"offset": x_off, "scale": x_scale},
        {"offset": y_off, "scale": y_scale},
        x_enc,
        y_enc,
    )


def grid_shape(
    w: int, h: int, visible: int, target_per_cell: float = DENSITY_TARGET_POINTS_PER_CELL
) -> tuple[int, int]:
    """Keep aggregation grids screen-bounded, but avoid one-pixel bins when
    the visible count is only barely over the direct budget. A few points per
    cell gives smoother drill-out aggregates and smaller updates."""
    if isinstance(w, (bool, np.bool_)) or isinstance(h, (bool, np.bool_)):
        raise ValueError("screen dimensions must be finite")
    try:
        wf = float(w)
        hf = float(h)
    except (TypeError, ValueError) as e:
        raise ValueError("screen dimensions must be finite") from e
    if not np.isfinite(wf) or not np.isfinite(hf):
        raise ValueError("screen dimensions must be finite")
    w = max(16, min(int(wf), MAX_SCREEN_DIM))
    h = max(16, min(int(hf), MAX_SCREEN_DIM))
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
    if len(xs) and hi_x > lo_x and hi_y > lo_y:
        return kernels.local_log_density(xs, ys, lo_x, hi_x, lo_y, hi_y, gw, gh)
    return np.zeros(len(xs), dtype=np.float32)
