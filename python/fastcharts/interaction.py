"""Kernel-side interaction handlers (§17/§28/§34): what the client's messages
resolve to. Each function takes the Figure whose canonical store answers the
question — the widget (or any other frontend) is a thin transport over these.

- pick: exact f64 row readout for hover (§16/§17)
- select_range: box-select → range predicate (§34 Filter Tier A)
- to_shipped_indices: canonical rows → shipped vertex positions (mask space)
- decimate_view: re-decimate visible line/area windows on zoom (§28)
- density_view: re-aggregate a Tier-2 scatter per viewport — density grid when
  the window is over budget, real points (drill-in) when it fits (§5)
"""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import channels, kernels, lod
from .config import (
    DECIMATION_THRESHOLD,
    DENSITY_TARGET_POINTS_PER_CELL,  # noqa: F401  (historic import path)
    DRILL_EXIT_FACTOR,  # noqa: F401  (historic import path)
    MAX_SCREEN_DIM,
    SCATTER_DENSITY_THRESHOLD,
)

if TYPE_CHECKING:
    from .figure import Figure


def _integer_id(value: int, label: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be an integer")
    try:
        return operator.index(value)
    except TypeError as e:
        raise ValueError(f"{label} must be an integer") from e


def _trace_id(trace_id: int) -> int:
    return _integer_id(trace_id, "trace_id")


def _trace(fig: "Figure", trace_id: int) -> Any:
    tid = _trace_id(trace_id)
    if tid < 0 or tid >= len(fig.traces):
        raise ValueError(f"trace_id {tid} is out of range")
    return fig.traces[tid]


def _screen_shape(w: int, h: int) -> tuple[int, int]:
    # `grid_shape` clamps tiny/zero browser sizes to a visible floor, but NaN/inf
    # and non-numeric dimensions are programmer/client bugs and must fail before
    # drill state changes.
    if isinstance(w, (bool, np.bool_)) or isinstance(h, (bool, np.bool_)):
        raise ValueError("screen dimensions must be finite")
    try:
        wf = float(w)
        hf = float(h)
    except (TypeError, ValueError) as e:
        raise ValueError("screen dimensions must be finite") from e
    if not np.isfinite(wf) or not np.isfinite(hf):
        raise ValueError("screen dimensions must be finite")
    return max(16, min(int(wf), MAX_SCREEN_DIM)), max(16, min(int(hf), MAX_SCREEN_DIM))


def pick(
    fig: "Figure", trace_id: int, index: int, drill_seq: Optional[int] = None
) -> Optional[dict[str, Any]]:
    """Exact source-row readout for a hover/pick (§17 Tier-0 hover; §16 —
    values come from the f64 canonical store, never through the f32 GPU path).

    `index` is a *shipped* vertex index (what the client's GPU pick sees);
    it is translated to a canonical row when the shipped copy dropped NaN
    rows (§19). Returns None if out of range.

    `drill_seq` is the subset version the client picked against. If the drill
    advanced (or exited) since, the index is in a dead coordinate space —
    return None rather than translate it into the wrong row (§16: exact or
    nothing; a stale pick after drill-out would otherwise read `index` as a
    *canonical* row, i.e. an arbitrary point)."""
    try:
        t = _trace(fig, trace_id)
        idx = _integer_id(index, "index")
        dseq = None if drill_seq is None else _integer_id(drill_seq, "drill_seq")
    except ValueError:
        return None
    if dseq is not None and dseq != t.drill_seq:
        return None
    shipped_sel = _point_shipped_sel(t)
    if shipped_sel is not None:
        if idx < 0 or idx >= len(shipped_sel):
            return None
        idx = int(shipped_sel[idx])
    if idx < 0 or idx >= t.n_points:
        return None
    out: dict[str, Any] = {
        "trace": t.id,
        "index": idx,
        "x": float(t.x.values[idx]),
        "y": float(t.y.values[idx]),
        "x_kind": t.x.kind,
        "y_kind": t.y.kind,
    }
    cc = t.color_ch
    if cc and cc.mode == "continuous" and cc.values is not None:
        out["color_value"] = float(cc.values[idx])
    elif cc and cc.mode == "categorical" and cc.codes is not None and cc.categories is not None:
        code = int(cc.codes[idx])
        if 0 <= code < len(cc.categories):
            out["color_category"] = cc.categories[code]
    sc = t.size_ch
    if sc and sc.mode == "continuous" and sc.values is not None:
        out["size_value"] = float(sc.values[idx])
    return out


def select_range(
    fig: "Figure", x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
) -> dict[int, np.ndarray]:
    """Indices of points inside the box, per scatter trace (§34 Filter Tier A:
    an indexed range predicate). A plain NumPy mask over canonical here; the
    zone-map-pruned version is the scale path. Returns {trace_id: indices}."""
    lo_x, hi_x, lo_y, hi_y = lod.normalize_window(x0, x1, y0, y1, require_area=False)
    tid = None if trace_id is None else _trace(fig, trace_id).id
    out: dict[int, np.ndarray] = {}
    for t in fig.traces:
        if t.kind != "scatter":
            continue
        if tid is not None and t.id != tid:
            continue
        xv, yv = t.x.values, t.y.values
        out[t.id] = kernels.range_indices(xv, yv, lo_x, hi_x, lo_y, hi_y)
    return out


def to_shipped_indices(fig: "Figure", trace_id: int, canonical: np.ndarray) -> np.ndarray:
    """Translate canonical row indices to *shipped* vertex positions for a
    trace — the coordinate space the client's per-vertex selection mask uses.
    Identity when nothing was dropped at ship time."""
    sel = _point_shipped_sel(_trace(fig, trace_id))
    if sel is None:
        return np.asarray(canonical, dtype=np.uint32)
    # sel is sorted ascending (flatnonzero/m4 output); membership → position.
    return np.flatnonzero(np.isin(sel, canonical)).astype(np.uint32)


def _point_shipped_sel(t: Any) -> Optional[np.ndarray]:
    """Shipped point vertices → canonical rows, even before first payload build.

    `build_payload` records this on the Trace for the widget path. Direct public
    calls to pick()/to_shipped_indices() still deserve the same coordinate-space
    contract, so derive the direct-scatter mapping lazily when it has not been
    established yet. Density full-view has no point vertices until drill-in.
    """
    if t.shipped_sel is not None:
        return t.shipped_sel
    if t.kind != "scatter":
        return None
    if t.use_density() and not t.drill_mode:
        return np.empty(0, dtype=np.uint32)
    if not (t.x.zone.null_count or t.y.zone.null_count):
        return None
    return np.flatnonzero(np.isfinite(t.x.values) & np.isfinite(t.y.values)).astype(np.uint32)


def decimate_view(
    fig: "Figure", x0: float, x1: float, px_width: int
) -> tuple[dict[str, Any], list[bytes]]:
    """Re-decimate visible windows for a zoomed view (§28 line/area rule:
    recompute for the visible x-range only). The offset re-centers on the
    window midpoint — the §16 deep-zoom rule — so f32 precision follows the
    viewport instead of the whole series.
    """
    lo_x, hi_x, _lo_y, _hi_y = lod.normalize_window(x0, x1, 0.0, 1.0)
    px_width, _ = _screen_shape(px_width, 16)
    updates: list[dict[str, Any]] = []
    buffers: list[bytes] = []
    for t in fig.traces:
        if t.kind not in {"line", "area"} or t.n_points <= DECIMATION_THRESHOLD:
            continue
        if t.kind == "area" and t.base is None:
            continue
        idx = kernels.m4_indices(t.x.values, t.y.values, lo_x, hi_x, max(16, px_width))
        if len(idx):
            xv, yv = t.x.values[idx], t.y.values[idx]
            bv = t.base.values[idx] if t.kind == "area" and t.base is not None else None
            if bv is not None:
                sel = np.flatnonzero(np.isfinite(bv))
                if len(sel) != len(xv):
                    xv, yv, bv = xv[sel], yv[sel], bv[sel]
        else:
            xv, yv = t.x.values[:0], t.y.values[:0]
            bv = t.base.values[:0] if t.kind == "area" and t.base is not None else None
        x_off = (lo_x + hi_x) / 2.0
        y_off = t.y.suggest_offset()
        x_enc = kernels.encode_f32(xv, x_off, 1.0)
        y_enc = kernels.encode_f32(yv, y_off, 1.0)
        update = {
            "id": t.id,
            "x": {"buf": len(buffers), "len": len(x_enc), "offset": x_off, "scale": 1.0},
            "y": {
                "buf": len(buffers) + 1,
                "len": len(y_enc),
                "offset": y_off,
                "scale": 1.0,
            },
        }
        buffers.append(x_enc.tobytes())
        buffers.append(y_enc.tobytes())
        if bv is not None and t.base is not None:
            b_off = t.base.suggest_offset()
            b_enc = kernels.encode_f32(bv, b_off, 1.0)
            update["base"] = {
                "buf": len(buffers),
                "len": len(b_enc),
                "offset": b_off,
                "scale": 1.0,
            }
            buffers.append(b_enc.tobytes())
        updates.append(update)
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
    t = _trace(fig, trace_id)
    lo_x, hi_x, lo_y, hi_y = lod.normalize_window(x0, x1, y0, y1)
    w, h = _screen_shape(w, h)
    if not t.use_density():
        return {"traces": []}, []
    xv, yv = t.x.values, t.y.values
    sel = kernels.range_indices(xv, yv, lo_x, hi_x, lo_y, hi_y)
    visible = int(len(sel))
    if lod.drill_decision(visible, SCATTER_DENSITY_THRESHOLD, t.drill_mode):
        return _drill_points(fig, t, sel, visible, lo_x, hi_x, lo_y, hi_y, w, h)

    lod.exit_drill(t)
    w, h = lod.grid_shape(w, h, visible)
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


def _drill_points(
    fig: "Figure",
    t: Any,
    sel: np.ndarray,
    visible: int,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
    w: int,
    h: int,
) -> tuple[dict[str, Any], list[bytes]]:
    """Ship the visible subset of a Tier-2 scatter as real points (§5 drill-in).

    Scatter-specific wiring over the chart-agnostic pieces in `lod`: channels
    ship in the direct-scatter wire shape, normalized over their *global*
    domain so colors/sizes stay stable across views; offsets re-center on the
    window midpoint (§16); each point carries its local log-density plus a
    `lod_blend` weight (visible/budget) so the density→points handoff is
    color-continuous instead of a palette jump (§5)."""
    xs, ys = t.x.values[sel], t.y.values[sel]
    x_off, y_off, x_enc, y_enc = lod.encode_window_xy(xs, ys, lo_x, hi_x, lo_y, hi_y)
    writer = lod.BufferWriter()
    writer.add_raw(x_enc.tobytes())
    writer.add_raw(y_enc.tobytes())
    buffers = writer.buffers

    color_spec, size_spec = fig._ship_channels(t, sel, writer.add_f32)
    n = len(sel)

    # Local log-density per drilled point, binned at the same screen-derived
    # grid shape density would use, so the two representations line up.
    gw, gh = lod.grid_shape(w, h, visible)
    dval_buf = writer.add_f32(lod.local_log_density(xs, ys, lo_x, hi_x, lo_y, hi_y, gw, gh))
    drill_seq = lod.enter_drill(t, sel)
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
                    "drill_seq": drill_seq,
                    "style": dict(t.style),
                }
            ]
        },
        buffers,
    )
