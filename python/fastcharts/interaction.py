"""Kernel-side interaction handlers (§17/§28/§34): what the client's messages
resolve to. Each function takes the Figure whose canonical store answers the
question — the widget (or any other frontend) is a thin transport over these.

- pick: exact f64 row readout for hover (§16/§17)
- select_range: box-select → range predicate (§34 Filter Tier A)
- to_shipped_indices: canonical rows → shipped vertex positions (mask space)
- decimate_view: re-decimate visible line windows on zoom (§28)
- density_view: re-bin a Tier-2 scatter for a new viewport (§5)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import kernels
from .config import DECIMATION_THRESHOLD

if TYPE_CHECKING:
    from .figure import Figure


def pick(fig: "Figure", trace_id: int, index: int) -> Optional[dict[str, Any]]:
    """Exact source-row readout for a hover/pick (§17 Tier-0 hover; §16 —
    values come from the f64 canonical store, never through the f32 GPU path).

    `index` is a *shipped* vertex index (what the client's GPU pick sees);
    it is translated to a canonical row when the shipped copy dropped NaN
    rows (§19). Returns None if out of range."""
    t = fig.traces[trace_id]
    if t.shipped_sel is not None:
        if index < 0 or index >= len(t.shipped_sel):
            return None
        index = int(t.shipped_sel[index])
    if index < 0 or index >= t.n_points:
        return None
    out: dict[str, Any] = {
        "trace": trace_id,
        "index": index,
        "x": float(t.x.values[index]),
        "y": float(t.y.values[index]),
        "x_kind": t.x.kind,
        "y_kind": t.y.kind,
    }
    cc = t.color_ch
    if cc and cc.mode == "continuous" and cc.values is not None:
        out["color_value"] = float(cc.values[index])
    elif cc and cc.mode == "categorical" and cc.codes is not None:
        out["color_category"] = cc.categories[int(cc.codes[index])]
    sc = t.size_ch
    if sc and sc.mode == "continuous" and sc.values is not None:
        out["size_value"] = float(sc.values[index])
    return out


def select_range(
    fig: "Figure", x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
) -> dict[int, np.ndarray]:
    """Indices of points inside the box, per scatter trace (§34 Filter Tier A:
    an indexed range predicate). A plain NumPy mask over canonical here; the
    zone-map-pruned version is the scale path. Returns {trace_id: indices}."""
    lo_x, hi_x = min(x0, x1), max(x0, x1)
    lo_y, hi_y = min(y0, y1), max(y0, y1)
    out: dict[int, np.ndarray] = {}
    for t in fig.traces:
        if t.kind != "scatter":
            continue
        if trace_id is not None and t.id != trace_id:
            continue
        xv, yv = t.x.values, t.y.values
        mask = (xv >= lo_x) & (xv <= hi_x) & (yv >= lo_y) & (yv <= hi_y)
        out[t.id] = np.flatnonzero(mask).astype(np.uint32)
    return out


def to_shipped_indices(fig: "Figure", trace_id: int, canonical: np.ndarray) -> np.ndarray:
    """Translate canonical row indices to *shipped* vertex positions for a
    trace — the coordinate space the client's per-vertex selection mask uses.
    Identity when nothing was dropped at ship time."""
    sel = fig.traces[trace_id].shipped_sel
    if sel is None:
        return np.asarray(canonical, dtype=np.uint32)
    # sel is sorted ascending (flatnonzero/m4 output); membership → position.
    return np.flatnonzero(np.isin(sel, canonical)).astype(np.uint32)


def decimate_view(
    fig: "Figure", x0: float, x1: float, px_width: int
) -> tuple[dict[str, Any], list[bytes]]:
    """Re-decimate visible windows for a zoomed view (§28 line rule:
    recompute for the visible x-range only). The offset re-centers on the
    window midpoint — the §16 deep-zoom rule — so f32 precision follows the
    viewport instead of the whole series.
    """
    updates: list[dict[str, Any]] = []
    buffers: list[bytes] = []
    for t in fig.traces:
        if t.kind != "line" or t.n_points <= DECIMATION_THRESHOLD:
            continue
        idx = kernels.m4_indices(t.x.values, t.y.values, x0, x1, max(16, px_width))
        if len(idx) == 0:
            continue
        xv, yv = t.x.values[idx], t.y.values[idx]
        x_off = (x0 + x1) / 2.0
        y_off = t.y.suggest_offset()
        x_enc = kernels.encode_f32(xv, x_off, 1.0)
        y_enc = kernels.encode_f32(yv, y_off, 1.0)
        updates.append(
            {
                "id": t.id,
                "x": {"buf": len(buffers), "len": len(x_enc), "offset": x_off, "scale": 1.0},
                "y": {
                    "buf": len(buffers) + 1,
                    "len": len(y_enc),
                    "offset": y_off,
                    "scale": 1.0,
                },
            }
        )
        buffers.append(x_enc.tobytes())
        buffers.append(y_enc.tobytes())
    return {"traces": updates}, buffers


def density_view(
    fig: "Figure", trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
) -> tuple[dict[str, Any], list[bytes]]:
    """Re-bin a Tier-2 scatter for a new viewport (§5: O(visible points);
    the client requests this when pan/zoom leaves the shipped grid)."""
    t = fig.traces[trace_id]
    if not t.use_density():
        return {"traces": []}, []
    w = max(16, min(w, 4096))
    h = max(16, min(h, 4096))
    grid = kernels.bin_2d(t.x.values, t.y.values, x0, x1, y0, y1, w, h)
    return (
        {
            "traces": [
                {
                    "id": trace_id,
                    "density": {
                        "buf": 0,
                        "w": w,
                        "h": h,
                        "max": float(grid.max()) if grid.size else 0.0,
                        "x_range": [x0, x1],
                        "y_range": [y0, y1],
                    },
                }
            ]
        },
        [grid.reshape(-1).astype(np.float32).tobytes()],
    )
