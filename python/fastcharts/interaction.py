"""Kernel-side interaction handlers (§17/§28/§34): what the client's messages
resolve to. Each function takes the Figure whose canonical store answers the
question — the widget (or any other frontend) is a thin transport over these.

- pick: exact f64 row readout for hover (§16/§17)
- select_range: box-select → range predicate (§34 Filter Tier A)
- to_shipped_indices: canonical rows → shipped vertex positions (mask space)
- decimate_view: re-decimate visible line windows on zoom (§28)
- density_view: re-aggregate a Tier-2 scatter per viewport — density grid when
  the window is over budget, real points (drill-in) when it fits (§5)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import channels, kernels
from .config import DECIMATION_THRESHOLD, SCATTER_DENSITY_THRESHOLD

# Hysteresis on the drill boundary (§5 "tier transitions hysteresis-guarded"):
# once drilled to points, stay until the visible count clearly exceeds the
# budget again, so a view hovering at the threshold doesn't thrash modes.
DRILL_EXIT_FACTOR = 1.15
DENSITY_TARGET_POINTS_PER_CELL = 16.0

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
    """Re-aggregate a Tier-2 scatter for a new viewport (§5: O(visible points);
    the client requests this when pan/zoom leaves the shipped grid).

    The tier is a function of the *visible* count, not the total (§5) — deep
    zoom drills back to real points, color/size channels restored, once the
    window fits the direct budget; zooming out returns to density. The per-view
    decision rides each update as `mode` — never silent (§28)."""
    t = fig.traces[trace_id]
    if not t.use_density():
        return {"traces": []}, []
    lo_x, hi_x = min(x0, x1), max(x0, x1)
    lo_y, hi_y = min(y0, y1), max(y0, y1)
    xv, yv = t.x.values, t.y.values
    # NaN/±inf compare False on either side, so non-finite rows never enter the
    # drilled subset (§19: nothing non-finite reaches vertex buffers).
    vis = (xv >= lo_x) & (xv <= hi_x) & (yv >= lo_y) & (yv <= hi_y)
    visible = int(np.count_nonzero(vis))
    budget = SCATTER_DENSITY_THRESHOLD * (DRILL_EXIT_FACTOR if t.drill_mode else 1.0)
    if visible <= budget:
        return _drill_points(fig, t, vis, visible, lo_x, hi_x, lo_y, hi_y, w, h)

    t.drill_mode = False
    t.shipped_sel = None  # aggregate view: no per-point marks, no pick mapping
    w, h = _density_grid_shape(w, h, visible)
    grid = kernels.bin_2d(xv, yv, lo_x, hi_x, lo_y, hi_y, w, h)
    return (
        {
            "traces": [
                {
                    "id": trace_id,
                    "mode": "density",
                    "visible": visible,
                    "density": {
                        "buf": 0,
                        "w": w,
                        "h": h,
                        "max": float(grid.max()) if grid.size else 0.0,
                        "x_range": [lo_x, hi_x],
                        "y_range": [lo_y, hi_y],
                    },
                }
            ]
        },
        [grid.reshape(-1).astype(np.float32).tobytes()],
    )


def _density_grid_shape(w: int, h: int, visible: int) -> tuple[int, int]:
    """Keep density grids screen-bounded, but avoid one-pixel bins when the
    visible count is only barely over the direct draw budget. A few points per
    cell gives smoother drill-out density and smaller updates."""
    w = max(16, min(int(w), 4096))
    h = max(16, min(int(h), 4096))
    requested = w * h
    if visible <= 0:
        return w, h
    target = min(requested, max(16 * 16, int(np.ceil(visible / DENSITY_TARGET_POINTS_PER_CELL))))
    if target >= requested:
        return w, h
    scale = float(np.sqrt(target / requested))
    return max(16, int(round(w * scale))), max(16, int(round(h * scale)))


def _drill_points(
    fig: "Figure",
    t: Any,
    vis: np.ndarray,
    visible: int,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
    w: int,
    h: int,
) -> tuple[dict[str, Any], list[bytes]]:
    """Ship the visible subset of a Tier-2 scatter as real points (§5 drill-in).

    Channels ship in the same wire shape as a direct scatter, normalized over
    their *global* domain so colors/sizes stay stable across views. Offsets
    re-center on the window midpoint (§16 deep-zoom rule).

    Each point also carries its *local log-density* plus a `lod_blend` weight
    (visible/budget): right at the drill boundary the client paints points with
    the density colormap by local density — the same picture as the texture,
    just sharp — and eases into native channel colors as the zoom deepens. This
    is what makes the density→points handoff color-continuous instead of a
    palette jump."""
    sel = np.flatnonzero(vis)
    t.drill_mode = True
    t.shipped_sel = sel  # pick/selection translate through the drilled subset (§17)
    x_off = (lo_x + hi_x) / 2.0
    y_off = (lo_y + hi_y) / 2.0
    xs, ys = t.x.values[sel], t.y.values[sel]
    if len(sel):
        x_enc = kernels.encode_f32(xs, x_off, 1.0)
        y_enc = kernels.encode_f32(ys, y_off, 1.0)
    else:
        x_enc = y_enc = np.empty(0, dtype=np.float32)
    buffers: list[bytes] = [x_enc.tobytes(), y_enc.tobytes()]

    def ship_scalar(arr: np.ndarray) -> int:
        buffers.append(np.ascontiguousarray(arr, dtype=np.float32).tobytes())
        return len(buffers) - 1

    color_spec, size_spec = fig._ship_channels(t, sel, ship_scalar)
    n = len(sel)

    # Local log-density per drilled point, normalized within the window — the
    # LUT coordinate the client blends with. Binned at the same screen-derived
    # grid shape density would use, so the two representations line up.
    dval = np.zeros(n, dtype=np.float32)
    if n and hi_x > lo_x and hi_y > lo_y:
        gw, gh = _density_grid_shape(w, h, visible)
        grid = kernels.bin_2d(xs, ys, lo_x, hi_x, lo_y, hi_y, gw, gh)
        gmax = float(grid.max()) if grid.size else 0.0
        if gmax > 0:
            ix = np.clip(((xs - lo_x) * (gw / (hi_x - lo_x))).astype(np.int64), 0, gw - 1)
            iy = np.clip(((ys - lo_y) * (gh / (hi_y - lo_y))).astype(np.int64), 0, gh - 1)
            dval = (np.log1p(grid[iy, ix]) / np.log1p(gmax)).astype(np.float32)
    dval_buf = ship_scalar(dval)
    # 1.0 right at the boundary → density-colored points; →0 as zoom deepens.
    lod_blend = float(min(1.0, visible / SCATTER_DENSITY_THRESHOLD))
    cmap = (
        t.color_ch.colormap
        if (t.color_ch and t.color_ch.mode == "continuous")
        else channels.DEFAULT_COLORMAP
    )
    return (
        {
            "traces": [
                {
                    "id": t.id,
                    "mode": "points",
                    "visible": visible,
                    # The window these points cover: the client draws points
                    # while the view stays inside it, and falls back to the
                    # density overview the instant a zoom-out leaves it — so
                    # zooming out is never blank (§5 smooth transitions).
                    "x_range": [lo_x, hi_x],
                    "y_range": [lo_y, hi_y],
                    "x": {"buf": 0, "len": n, "offset": x_off, "scale": 1.0},
                    "y": {"buf": 1, "len": n, "offset": y_off, "scale": 1.0},
                    "color": color_spec,
                    "size": size_spec,
                    "density_val": {"buf": dval_buf},
                    "lod_blend": lod_blend,
                    "density_colormap": cmap,
                    "style": dict(t.style),
                }
            ]
        },
        buffers,
    )
