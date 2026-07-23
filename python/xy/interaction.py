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

import math
import operator
import weakref
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import channels, columns, kernels, lod
from ._ooc import is_memmapped
from .config import (
    DECIMATION_THRESHOLD,
    DEFAULT_PALETTE,
    DENSITY_TARGET_POINTS_PER_CELL,  # noqa: F401  (historic import path)
    DRILL_EXIT_FACTOR,
    DRILL_PAD_SPAN_CAP,
    DRILL_PAD_TARGETS,
    PYRAMID_BASE_DIM,
    PYRAMID_MAX_DIM,
    PYRAMID_MIN_POINTS,
    PYRAMID_NO_RESCAN_ROWS,
    SCATTER_DENSITY_THRESHOLD,
    SPATIAL_EXACT_MAX_POINTS,
)

if TYPE_CHECKING:
    from ._figure import Figure
    from ._trace import Trace

# Passed to pyramid_compose for no-rescan traces so the finest level is served
# upsampled instead of refusing (Rust saturating-multiplies, so this never
# overflows); every practical zoom then stays O(visible tiles).
_PYRAMID_UNBOUNDED_UPSAMPLE = 1 << 30


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
    return lod.screen_shape(w, h)


def pick(
    fig: "Figure", trace_id: int, index: int, drill_seq: Optional[int] = None
) -> Optional[dict[str, Any]]:
    """Exact source-row readout for a hover/pick — values come from the f64
    canonical store, never through the f32 GPU path (design dossier §16/§17).

    `index` is a *shipped* vertex index (what the client's GPU pick sees);
    it is translated to a canonical row when the shipped copy dropped NaN
    rows. Returns None if out of range.

    `drill_seq` is the subset version the client picked against. If the drill
    advanced (or exited) since, the index is in a dead coordinate space —
    return None rather than translate it into the wrong row (exact or
    nothing; a stale pick after drill-out would otherwise read `index` as a
    *canonical* row, i.e. an arbitrary point)."""
    try:
        t = _trace(fig, trace_id)
        idx = _integer_id(index, "index")
        dseq = None if drill_seq is None else _integer_id(drill_seq, "drill_seq")
    except ValueError:
        return None
    if dseq is not None and dseq != t.drill_seq:
        # The client may pick against a RETIRED cached point window (LOD doc
        # T13) whose subset version is no longer the current drill. Recent
        # subsets stay resolvable through the bounded history; anything older
        # (or bumped by exits/data changes) drops the pick rather than reading
        # the index in the wrong subset space (§16 exact-or-nothing).
        shipped_sel = lod.drill_history(t, dseq)
        if shipped_sel is None:
            return None
    else:
        shipped_sel = _point_shipped_sel(t)
    if shipped_sel is not None:
        if idx < 0 or idx >= len(shipped_sel):
            return None
        idx = int(shipped_sel[idx])
    if idx < 0 or idx >= t.n_points:
        return None
    return row_dict(fig, t, idx)


def _json_scalar(value: Any) -> Any:
    """Return the small scalar values used by semantic events as JSON values."""
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def row_dict(fig: "Figure", t: "Trace", idx: int) -> dict[str, Any]:
    """Project one canonical trace row using the exact pick-result shape."""
    del fig  # Kept in the signature for symmetry with other interaction helpers.
    if t.grid_shape is not None:
        # Heatmap x/y contain only the outer edges. The client already has the
        # cell center (including categorical labels), so return only grid data.
        _, cols = t.grid_shape
        row, col = divmod(idx, cols)
        out: dict[str, Any] = {
            "trace": t.id,
            "index": idx,
            "row": row,
            "col": col,
        }
        if t.grid is not None:
            val = float(t.grid.values[idx])
            if np.isfinite(val):
                out["color_value"] = val
        return out
    out: dict[str, Any] = {
        "trace": t.id,
        "index": idx,
        "x": _json_scalar(float(t.x.values[idx])),
        "y": _json_scalar(float(t.y.values[idx])),
        "x_kind": t.x.kind,
        "y_kind": t.y.kind,
    }
    cc = t.color_ch
    if cc and cc.mode == "continuous" and cc.values is not None:
        out["color_value"] = _json_scalar(float(cc.values[idx]))
    elif cc and cc.mode == "categorical" and cc.codes is not None and cc.categories is not None:
        code = int(cc.codes[idx])
        if 0 <= code < len(cc.categories):
            out["color_category"] = _json_scalar(cc.categories[code])
    sc = t.size_ch
    if sc and sc.mode == "continuous" and sc.values is not None:
        out["size_value"] = _json_scalar(float(sc.values[idx]))
    return out


def selection_rows(
    fig: "Figure", per_trace: dict[int, np.ndarray], limit: Optional[int] = None
) -> tuple[list[dict[str, Any]], bool]:
    """Deterministic, JSON-safe row projection for a selection.

    Traces are ascending by trace id and canonical indices are ascending
    within a trace. ``limit=None`` means unbounded. The boolean reports
    whether rows were omitted by the limit.
    """
    max_rows = None if limit is None else max(0, operator.index(limit))
    rows: list[dict[str, Any]] = []
    total = sum(len(indices) for indices in per_trace.values())
    for tid in sorted(per_trace):
        t = _trace(fig, tid)
        for raw_idx in np.sort(np.asarray(per_trace[tid]).ravel()):
            if max_rows is not None and len(rows) >= max_rows:
                return rows, len(rows) < total
            idx = int(raw_idx)
            if 0 <= idx < t.n_points:
                rows.append(row_dict(fig, t, idx))
    return rows, len(rows) < total


def select_range(
    fig: "Figure", x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
) -> dict[int, np.ndarray]:
    """Indices of points inside the box, per scatter trace (an indexed range
    predicate; design dossier §34). A plain NumPy mask over canonical here;
    the zone-map-pruned version is the scale path. Returns
    {trace_id: indices}."""
    lo_x, hi_x, lo_y, hi_y = lod.normalize_window(x0, x1, y0, y1, require_area=False)
    tid = None if trace_id is None else _trace(fig, trace_id).id
    out: dict[int, np.ndarray] = {}
    for t in fig.traces:
        if t.kind != "scatter":
            continue
        if tid is not None and t.id != tid:
            continue
        x_chunks = _zone_candidate_chunks(t.x, lo_x, hi_x)
        y_chunks = _zone_candidate_chunks(t.y, lo_y, hi_y)
        candidate_chunks = np.intersect1d(x_chunks, y_chunks, assume_unique=True)
        if len(candidate_chunks) == len(t.x.zone.counts):
            out[t.id] = kernels.range_indices(t.x.values, t.y.values, lo_x, hi_x, lo_y, hi_y)
        elif len(candidate_chunks) == 0:
            out[t.id] = np.empty(0, dtype=np.uint32)
        else:
            candidates = _expand_zone_chunks(t.x, candidate_chunks)
            out[t.id] = kernels.range_indices(
                t.x.values[candidates], t.y.values[candidates], lo_x, hi_x, lo_y, hi_y
            )
            out[t.id] = candidates[out[t.id]]
    return out


def select_polygon(
    fig: "Figure", points: Any, trace_id: Optional[int] = None
) -> dict[int, np.ndarray]:
    """Canonical scatter indices inside a finite lasso polygon.

    The polygon's bounding box first reuses the zone-pruned range predicate;
    ray casting then runs only on those candidates rather than every row.
    """
    polygon = np.asarray(points, dtype=np.float64)
    if polygon.ndim != 2 or polygon.shape[1:] != (2,) or not 3 <= len(polygon) <= 2048:
        raise ValueError("selection polygon must contain 3 to 2048 x/y points")
    if not np.isfinite(polygon).all():
        raise ValueError("selection polygon must be finite")
    candidates = select_range(
        fig,
        float(polygon[:, 0].min()),
        float(polygon[:, 0].max()),
        float(polygon[:, 1].min()),
        float(polygon[:, 1].max()),
        trace_id,
    )
    out: dict[int, np.ndarray] = {}
    for tid, rows in candidates.items():
        if len(rows) == 0:
            out[tid] = rows
            continue
        trace = fig.traces[tid]
        x = trace.x.values[rows]
        y = trace.y.values[rows]
        inside = np.zeros(len(rows), dtype=np.bool_)
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            crosses = (yi > y) != (yj > y)
            with np.errstate(divide="ignore", invalid="ignore"):
                edge_x = (xj - xi) * (y - yi) / (yj - yi) + xi
            inside ^= crosses & (x < edge_x)
            j = i
        out[tid] = rows[inside]
    return out


def to_shipped_indices(fig: "Figure", trace_id: int, canonical: np.ndarray) -> np.ndarray:
    """Translate canonical row indices to *shipped* vertex positions for a
    trace — the coordinate space the client's per-vertex selection mask uses.
    Identity when nothing was dropped at ship time."""
    sel = _point_shipped_sel(_trace(fig, trace_id))
    if sel is None:
        return np.asarray(canonical, dtype=np.uint32)
    # `sel` is sorted ascending (flatnonzero/m4 output); membership maps each
    # canonical input row to its shipped position, preserving canonical order
    # and duplicate rows in `canonical`.
    canonical = np.asarray(canonical, dtype=np.uint32).ravel()
    positions = np.searchsorted(sel, canonical)
    valid = positions < len(sel)
    valid[valid] &= sel[positions[valid]] == canonical[valid]
    return positions[valid].astype(np.uint32)


def _zone_candidate_chunks(col: Any, lo: float, hi: float) -> np.ndarray:
    """Return chunk ids whose zone can overlap an inclusive range."""
    mins = col.zone.mins
    maxs = col.zone.maxs
    counts = col.zone.counts
    return np.flatnonzero((counts > 0) & (maxs >= lo) & (mins <= hi)).astype(np.uint32, copy=False)


def _expand_zone_chunks(col: Any, chunks: np.ndarray) -> np.ndarray:
    """Expand selected chunk ids to canonical row ids once, after pruning."""
    if len(chunks) == 0:
        return np.empty(0, dtype=np.uint32)
    widths = (
        np.minimum((chunks.astype(np.int64) + 1) * columns.ZONE_CHUNK, len(col))
        - chunks.astype(np.int64) * columns.ZONE_CHUNK
    )
    rows = np.empty(int(widths.sum()), dtype=np.uint32)
    offset = 0
    for chunk, width in zip(chunks, widths, strict=True):
        start = int(chunk) * columns.ZONE_CHUNK
        rows[offset : offset + int(width)] = np.arange(start, start + int(width), dtype=np.uint32)
        offset += int(width)
    return rows


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
    """Re-decimate visible windows for a zoomed view (recompute for the
    visible x-range only; design dossier §28). The offset re-centers on the
    window midpoint — the §16 deep-zoom rule — so f32 precision follows the
    viewport instead of the whole series.
    """
    lo_x, hi_x, _lo_y, _hi_y = lod.normalize_window(x0, x1, 0.0, 1.0)
    px_width, _ = _screen_shape(px_width, 16)
    updates: list[dict[str, Any]] = []
    writer = lod.BufferWriter()
    for t in fig.traces:
        if t.kind not in {"line", "area"} or t.n_points <= DECIMATION_THRESHOLD:
            continue
        if t.kind == "area" and t.base is None:
            continue
        x_scale = fig._axis_scale(t.x_axis)
        y_scale = fig._axis_scale(t.y_axis)
        # Bucket in scale coordinates so every bucket covers one screen strip.
        mx, (m_lo, m_hi) = fig._binning_coords(t.x_axis, t.x.values, (lo_x, hi_x))
        idx = kernels.m4_indices(mx, t.y.values, m_lo, m_hi, max(16, px_width))
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
        x_col = lod.encode_f32_values(xv, lod.geometry_offset(x_scale, lo_x, hi_x), lo_x, hi_x)
        y_col = lod.encode_f32_values(
            yv, lod.geometry_offset(y_scale, t.y.min, t.y.max), t.y.min, t.y.max
        )
        update = {
            "id": t.id,
            "x": writer.add_encoded(x_col),
            "y": writer.add_encoded(y_col),
        }
        if bv is not None and t.base is not None:
            b_col = lod.encode_f32_values(
                bv, lod.geometry_offset(y_scale, t.base.min, t.base.max), t.base.min, t.base.max
            )
            update["base"] = writer.add_encoded(b_col)
        updates.append(update)
    return {"traces": updates}, writer.buffers


def _pyramid_base_dim_for(t: Trace) -> int:
    """Finest-level dimension for a trace's pyramid. Normal traces use the
    default; no-rescan traces (huge or out-of-core) get a finer level so the
    upsampled deep-zoom floor stays sharp, sized ~sqrt(N / target-per-cell) and
    capped at PYRAMID_MAX_DIM (§28 / dossier §5)."""
    n = len(t.x)
    if not (is_memmapped(t.x.values) or n > PYRAMID_NO_RESCAN_ROWS):
        return PYRAMID_BASE_DIM
    ideal_side = math.sqrt(max(2.0, n / DENSITY_TARGET_POINTS_PER_CELL))
    pow2 = 1 << max(1, math.ceil(math.log2(ideal_side)))
    return int(min(PYRAMID_MAX_DIM, max(PYRAMID_BASE_DIM, pow2)))


def trace_bin_colors(t: Trace) -> Optional[dict]:
    """The trace's full-column kernel color source for mean-color binning
    (LOD doc §2), resolved once and cached on the trace.

    `channels.resolve_bin_colors` over the full column quantizes every
    canonical row — an O(N) pass whose NumPy temporaries reach multiple GB on
    a 100M-point trace — while its result depends only on the channel's
    immutable values and global domain. Cache it so each of its consumers
    (pyramid build, the exact and no-rescan mean-color re-bins, the
    first-paint density emit) pays that pass once per trace instead of once
    per request; `density_view` must never resolve it for a reply that ships
    no mean-color grid (pyramid replies use the prebuilt color planes, drills
    ship sliced channels). A rebuildable derived cache (§27), dropped by
    `append_data` (appended rows' colors and a possibly moved channel domain
    both change the resolution)."""
    cached = t._bin_colors
    if cached is None:
        resolved = channels.resolve_bin_colors(t.color_ch, None, DEFAULT_PALETTE)
        t._bin_colors = 0 if resolved is None else resolved
        return resolved
    return None if cached == 0 else cached


def bin_color_cache_bytes(fig: Any) -> int:
    """Memory-report line (design dossier §27): bytes held by resolved
    bin-color caches (per-row idx/rgba planes plus their LUTs)."""
    total = 0
    for t in fig.traces:
        cached = getattr(t, "_bin_colors", None)
        if cached:
            total += sum(int(v.nbytes) for v in cached.values() if isinstance(v, np.ndarray))
    return total


def _ensure_pyramid(t: Trace) -> int | None:
    """Lazily build the trace's count pyramid (§5 Tier 3). Cached on the
    trace; 0 is remembered as "tried and not applicable" so we never rebuild.
    Only worth the memory for genuinely large traces.

    Channel-bearing traces build mean-color planes alongside the counts
    (LOD doc §2) so pyramid-served zoom-outs keep the mean point color; those
    pyramids refuse native appends and are invalidated + lazily rebuilt
    instead (the appended rows' colors and a possibly moved channel domain
    both require a rescan)."""
    handle = getattr(t, "_pyr_handle", None)
    if handle is not None:
        return handle or None
    if len(t.x) < PYRAMID_MIN_POINTS:
        t._pyr_handle = 0
        return None
    x0, x1, y0, y1 = t.x.min, t.x.max, t.y.min, t.y.max
    import math

    if not all(math.isfinite(v) for v in (x0, x1, y0, y1)) or not (x1 > x0 and y1 > y0):
        t._pyr_handle = 0
        return None
    # Nudge the upper edge so points exactly at max land in the last cell
    # (bin_2d's window is half-open).
    x1 += (x1 - x0) * 1e-9
    y1 += (y1 - y0) * 1e-9
    base_dim = _pyramid_base_dim_for(t)
    bin_colors = trace_bin_colors(t)
    if bin_colors is not None:
        handle = kernels.pyramid_build_color(
            t.x.values, t.y.values, x0, x1, y0, y1, base_dim, **bin_colors
        )
    else:
        handle = kernels.pyramid_build(t.x.values, t.y.values, x0, x1, y0, y1, base_dim)
    t._pyr_handle = handle
    t._pyr_base_dim = base_dim
    t._pyr_colored = bool(handle) and bin_colors is not None
    if handle:
        # §27: the pyramid is native-side memory owned by this trace. Tie its
        # lifetime to the Trace object so a discarded Figure (the notebook
        # cell-re-run pattern) frees it instead of leaking it in the
        # process-lifetime registry.
        t._pyr_finalizer = weakref.finalize(t, kernels.pyramid_free, handle)
    return handle or None


def _free_pyramid(t: Trace) -> None:
    """Free the trace's pyramid now and disarm its GC finalizer.

    Resets the handle to None ("never tried") so the next far-out view
    rebuilds lazily; safe to call when no pyramid was ever built.
    """
    fin = getattr(t, "_pyr_finalizer", None)
    if fin is not None:
        fin()  # runs pyramid_free exactly once; later GC becomes a no-op
        t._pyr_finalizer = None
    elif t._pyr_handle:
        kernels.pyramid_free(t._pyr_handle)
    t._pyr_handle = None


def _pyramid_resident_bytes(base_dim: int = PYRAMID_BASE_DIM, *, colored: bool = False) -> int:
    """Exact native bytes of one pyramid: u32 count levels from base_dim²
    halving per side down to 1² (mirrors tiles.rs level construction), plus
    the [u16; 4] mean-color planes when the trace bins colors."""
    per_cell = 4 + (8 if colored else 0)
    total, dim = 0, base_dim
    while True:
        total += dim * dim * per_cell
        if dim == 1:
            return total
        dim >>= 1


def pyramid_report_bytes(fig: Any) -> int:
    """Memory-report line (design dossier §27): native bytes held by live
    trace pyramids, at each trace's actual (possibly adaptive) base dim,
    including the mean-color planes of colored pyramids."""
    return sum(
        _pyramid_resident_bytes(
            getattr(t, "_pyr_base_dim", None) or PYRAMID_BASE_DIM,
            colored=bool(getattr(t, "_pyr_colored", False)),
        )
        for t in fig.traces
        if getattr(t, "_pyr_handle", 0)
    )


def _encode_log_u8(grid: np.ndarray) -> tuple[bytes, float]:
    """Density grid -> log-encoded u8 wire bytes (client decodes via expm1).
    Zero cells stay zero; any nonzero cell maps to at least 1 so the "lit if
    occupied" texture contract survives quantization."""
    enc, maximum = kernels.density_log_u8(np.asarray(grid, dtype=np.float32))
    return enc.tobytes(), maximum


def _decode_log_u8(buf: bytes, gmax: float) -> np.ndarray:
    """Inverse of :func:`_encode_log_u8` — the Python twin of the client's
    ``lodDecodeLogU8`` and the executable wire contract for tests. Lossy
    (8-bit in log space, sub-percent per-cell at typical maxima), but zeros
    are exact and the grid max is restored exactly."""
    v = np.frombuffer(buf, dtype=np.uint8).astype(np.float64)
    if gmax <= 0.0:
        return np.zeros(v.size, dtype=np.float64)
    return np.expm1((v / 255.0) * np.log1p(gmax))


# Interactive density replies deliberately ship NO point sample (#225): a
# fixed-size sample above the drill budget reads as individual data points at
# a zoom where real points are sub-pixel — misrepresenting the dataset — and
# the density surface already wears the data's own colors (LOD doc §2). Real
# points arrive the moment a window fits the budget. The only retained sample
# is the first-payload one (`_payload._density_sample_spec`), which the client
# draws solely below the resolvable-count gate and the standalone re-bin
# worker keeps as its CPU source.


def _pyramid_source_shape(
    t: Any, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> tuple[int, int] | None:
    """The pyramid's finest-level cell budget under a window, per axis.

    Wire economy (§29 / #225 follow-up): composing a pyramid-served window to
    full screen resolution upsamples blocky base cells into a grid several
    times larger than the information it carries — a ~2.7 MB reply whose
    content is a few hundred KB of source cells. Clamping the composed grid
    to `(cells under the window at the finest level) + 1` per axis ships the
    same detail (the client's own texture filtering reproduces the upscale)
    at a fraction of the bytes.
    """
    base = int(getattr(t, "_pyr_base_dim", 0) or PYRAMID_BASE_DIM)
    ex0, ex1, ey0, ey1 = t.x.min, t.x.max, t.y.min, t.y.max
    span_x, span_y = ex1 - ex0, ey1 - ey0
    if not all(np.isfinite(v) for v in (ex0, ex1, ey0, ey1)) or span_x <= 0 or span_y <= 0:
        return None
    frac_x = min(1.0, max(0.0, (hi_x - lo_x) / span_x))
    frac_y = min(1.0, max(0.0, (hi_y - lo_y) / span_y))
    return max(1, math.ceil(base * frac_x) + 1), max(1, math.ceil(base * frac_y) + 1)


def _padded_drill_window(
    fig: "Figure",
    t: Any,
    pyr: int | None,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
) -> Optional[tuple[float, float, float, float, np.ndarray]]:
    """The widest aligned window around the view that still drills (T13).

    The client elides any request whose view an exact shipped window already
    contains (T12) and caches retired windows, so every extra span this window
    can afford converts future pans and zooms into zero-round-trip renders.
    Bounds snap outward to the power-of-two grid over the trace's extent
    (`lod.aligned_window`), making consecutive pans resolve to the SAME
    window; the coarsest ladder rung whose exact in-window count fits the
    budget wins. Returns None (drill the raw view window) when padding buys
    nothing: nonlinear axes (raw-space alignment mis-sizes log windows near
    zero), non-finite extents, or every rung over budget.
    """
    if fig._axis_scale(t.x_axis) != "linear" or fig._axis_scale(t.y_axis) != "linear":
        return None
    ex0, ex1, ey0, ey1 = t.x.min, t.x.max, t.y.min, t.y.max
    if not all(np.isfinite(v) for v in (ex0, ex1, ey0, ey1)):
        return None
    span_x, span_y = hi_x - lo_x, hi_y - lo_y
    budget = SCATTER_DENSITY_THRESHOLD
    for pad in DRILL_PAD_TARGETS:
        px0, px1 = lod.aligned_window(lo_x, hi_x, ex0, ex1, pad)
        py0, py1 = lod.aligned_window(lo_y, hi_y, ey0, ey1, pad)
        if px0 == lo_x and px1 == hi_x and py0 == lo_y and py1 == hi_y:
            continue
        # §16 precision guard: the shipped offset encoding centers on THIS
        # window, and the client re-requests precision only below 1/256 of the
        # window span — a window unboundedly wider than the view (tiny view
        # over a small dataset) would let deep zooms outrun f32 first.
        if px1 - px0 > span_x * DRILL_PAD_SPAN_CAP or py1 - py0 > span_y * DRILL_PAD_SPAN_CAP:
            continue
        if pyr is not None:
            # Cheap center-in-cell estimate gates the exact O(N) verify scan;
            # the margin keeps a boundary-straddling estimate from wasting a
            # scan on a window the exact count then rejects.
            est = kernels.pyramid_count(pyr, px0, px1, py0, py1)
            if est is not None and est > budget * 0.85:
                continue
        sel = kernels.range_indices(t.x.values, t.y.values, px0, px1, py0, py1)
        if len(sel) <= budget:
            return px0, px1, py0, py1, sel
    return None


def _quantize_dval(dval: np.ndarray) -> np.ndarray:
    """Quantize per-point local log-density ([0,1] by construction) to u8.

    The value only weights the density→points intensity handoff (§5) — 256
    levels exceed what the crossfade can show, at a quarter of the f32 wire
    bytes (§29)."""
    return np.rint(np.clip(dval, 0.0, 1.0) * 255.0).astype(np.uint8)


def _has_point_channels(t: "Trace") -> bool:
    """True when the trace carries any per-point (non-constant) encoding —
    color/size/stroke/style data the position-only spatial index can't restore
    per row (§27). Such a trace keeps the exact density grid at deep zoom; a
    plain constant-styled trace can drill to real points straight from the
    index."""
    cc, sc = t.color_ch, t.size_ch
    if cc is not None and cc.mode in {"continuous", "categorical", "direct_rgba"}:
        return True
    if sc is not None and sc.mode == "continuous":
        return True
    return t.stroke_ch is not None or bool(t.style_channels)


def _ship_index_points(
    t: "Trace",
    request: Any,
    xs: np.ndarray,
    ys: np.ndarray,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
) -> tuple[dict[str, Any], list[bytes]]:
    """Ship a spatial-indexed trace's in-window points as real point vertices
    (§5 drill-in), straight from the disk index — crisp marks at deep zoom
    without the O(N) canonical rescan the out-of-core path forbids. `xs`/`ys`
    are the already-gathered, already-window-clipped f32 coordinates.

    Position-only: the caller guarantees the trace has no per-point channels, so
    color/size ride their constant spec. Hover can't resolve an index point back
    to a canonical row (the derived index carries no row ids), and entering the
    drill with an empty subset makes that explicit — a pick maps into the empty
    subset and returns nothing rather than a wrong row (§16/§17)."""
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    visible = int(len(xs))
    writer = lod.BufferWriter()
    x_ref, y_ref = lod.add_window_xy(writer, xs, ys, lo_x, hi_x, lo_y, hi_y)
    gw, gh = lod.grid_shape(request.width, request.height, visible)
    dval_buf = writer.add_u8(
        _quantize_dval(lod.local_log_density(xs, ys, lo_x, hi_x, lo_y, hi_y, gw, gh))
    )
    drill_seq = lod.enter_drill(t, np.empty(0, dtype=np.uint32))
    lod_blend = float(min(1.0, visible / SCATTER_DENSITY_THRESHOLD))
    color_spec = (
        t.color_ch.spec() if t.color_ch is not None else {"mode": "constant", "color": None}
    )
    size_spec = t.size_ch.spec() if t.size_ch is not None else {"mode": "constant", "size": 4.0}
    trace_update = {
        "id": t.id,
        "mode": "points",
        "tier": "direct",
        "visible": visible,
        "reduction": "none",
        "binning": "spatial-points",
        "x_range": [lo_x, hi_x],
        "y_range": [lo_y, hi_y],
        "x": x_ref,
        "y": y_ref,
        "color": color_spec,
        "size": size_spec,
        "density_val": {"buf": dval_buf, "dtype": "u8"},
        "lod_blend": lod_blend,
        "drill_seq": drill_seq,
        "style": dict(t.style),
    }
    return {"traces": [trace_update]}, writer.buffers


def density_view(
    fig: "Figure", trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
) -> tuple[dict[str, Any], list[bytes]]:
    """Re-aggregate a density-mode scatter for a new viewport (O(visible
    points); the client requests this when pan/zoom leaves the shipped grid).

    The render tier is a function of the *visible* count, not the total
    (design dossier §5) — deep
    zoom drills back to real points, color/size channels restored, once the
    window fits the direct budget; zooming out returns to density. The per-view
    decision rides each update as `mode` — never silent."""
    t = _trace(fig, trace_id)
    request = lod.ViewportRequest.from_client(x0, x1, y0, y1, w, h)
    lo_x, hi_x = request.x_range
    lo_y, hi_y = request.y_range
    w, h = request.width, request.height
    if not t.use_density():
        return {"traces": []}, []
    xv, yv = t.x.values, t.y.values
    # Nonlinear axes aggregate in scale coordinates (§28) so grid cells are
    # uniform on screen. The raw-space tile pyramid can't compose such a grid,
    # so those traces always take the exact scan; selection/count queries stay
    # raw (monotone transforms preserve window membership).
    nonlinear = fig._axis_scale(t.x_axis) != "linear" or fig._axis_scale(t.y_axis) != "linear"
    # Tile-pyramid fast path (§5 Tier 3): when the window is clearly still in
    # density territory, the view is served from pre-binned counts in
    # O(visible cells) — no O(N) rescan. The margin keeps the approximate
    # pyramid count from ever usurping a would-be drill; anywhere near the
    # budget we fall through to the exact scan that drilling needs anyway.
    binning = "exact"
    grid = None
    # Mean point color plane (LOD doc §2): channel-bearing traces ship it
    # alongside the counts wherever a grid is produced below. Only the cheap
    # does-it-bin-colors fact is decided up front; the full-column idx/lut
    # source (`trace_bin_colors` — an O(N) resolve, cached on the trace) is
    # materialized solely by the branches that feed `bin_2d_mean_color`.
    # Pyramid replies compose prebuilt color planes and point drills ship
    # sliced channels, so resolving here would charge every request a
    # full-column pass those tiers never consume (the 100M drilldown demo
    # paid 1–2 s per reply for it).
    rgba_grid: np.ndarray | None = None
    mean_colors = channels.bins_mean_color(t.color_ch)
    # Texture sampling for the density grid: "nearest" when the grid is at full
    # screen resolution (exact deep-zoom detail — crisp, no interpolation bleed),
    # "linear" when it is upsampled from a coarser tier (smooth aggregate).
    density_filter = "linear"
    # A window that outresolves the pyramid normally refuses → exact O(N) re-bin,
    # which is cheap for in-RAM traces but a multi-second full scan for a huge
    # out-of-core column. Past PYRAMID_NO_RESCAN_ROWS (and always past 2³²-1
    # rows, where per-row index kernels overflow u32 and would allocate tens of
    # GB), we forbid the rescan: the pyramid is served upsampled (progressively
    # blurry, floored at its cell size) instead, so every zoom stays O(tiles).
    no_rescan = is_memmapped(xv) or len(xv) > PYRAMID_NO_RESCAN_ROWS
    max_upsample = _PYRAMID_UNBOUNDED_UPSAMPLE if no_rescan else 2
    est = None
    # Nonlinear axes can't compose from the raw-space pyramid (see above) → no
    # pyramid, exact scan instead.
    pyr = None if nonlinear else _ensure_pyramid(t)
    if pyr is not None:
        est = kernels.pyramid_count(pyr, lo_x, hi_x, lo_y, hi_y)
        # Serve from the pyramid when the window is clearly aggregate territory,
        # or unconditionally for no-rescan traces (drilling to exact points is
        # unavailable there — the exact path is what we are avoiding).
        if no_rescan or (
            est is not None and est > SCATTER_DENSITY_THRESHOLD * DRILL_EXIT_FACTOR * 1.5
        ):
            plan = lod.plan_view_lod(
                request,
                int(est) if est is not None else SCATTER_DENSITY_THRESHOLD * 2,
                SCATTER_DENSITY_THRESHOLD,
                False,
                aggregate_reduction="pyramid-count",
            )
            # Wire economy: never compose more grid cells than the finest
            # level resolves under this window — a full-screen grid of
            # upsampled base cells is the same picture at several times the
            # bytes (the client's texture filtering does the upscale).
            gw, gh = plan.grid_w, plan.grid_h
            source = _pyramid_source_shape(t, lo_x, hi_x, lo_y, hi_y)
            if source is not None:
                gw = max(16, min(gw, source[0]))
                gh = max(16, min(gh, source[1]))
            # Colored pyramids compose the mean-color plane with the counts
            # (same level, same max_upsample); both refusals (outresolved
            # window, missing planes) fall through to the paths below.
            if getattr(t, "_pyr_colored", False):
                res_color = kernels.pyramid_compose_color(
                    pyr, lo_x, hi_x, lo_y, hi_y, gw, gh, max_upsample
                )
                res = (res_color[0], res_color[2]) if res_color is not None else None
                rgba_grid = res_color[1] if res_color is not None else None
            else:
                res = kernels.pyramid_compose(pyr, lo_x, hi_x, lo_y, hi_y, gw, gh, max_upsample)
            if res is not None:
                grid, level = res
                visible = plan.visible
                w, h = gw, gh
                binning = f"pyramid-L{level}{'-upsampled' if no_rescan and level == 0 else ''}"
                lod.exit_drill(t)
    # Tier-3 spatial index: when the pyramid can only serve this window blurry
    # (upsampled), re-bin it *exactly* from just its in-window points — as long
    # as that count is affordable to read. This is what turns a blocky deep zoom
    # into real detail (streets), and it gets cheaper the deeper you go.
    # The derived index is position-only (§27): it can neither ship channels
    # with a points drill nor bin a mean-color plane (LOD doc §2), so a
    # color-channelled trace skips this tier and keeps its upsampled
    # colored-pyramid grid — blurry but truthful, recorded via `binning`.
    sidx = getattr(t, "_spatial_index", None)
    # `window_count` is a cheap (offsets-only, no point reads) upper bound —
    # whole overlapping cells, which at tight zoom overshoots the true in-window
    # count by orders of magnitude. Use it only to gate the read; once the cells
    # are affordable, gather **once** and decide by the *actual* in-window count.
    if (
        sidx is not None
        and not mean_colors
        and (grid is None or binning.endswith("-upsampled"))
        and sidx.window_count(lo_x, hi_x, lo_y, hi_y) <= SPATIAL_EXACT_MAX_POINTS
    ):
        lon, lat = sidx._gather_f32(lo_x, hi_x, lo_y, hi_y)
        inside = (lon >= lo_x) & (lon <= hi_x) & (lat >= lo_y) & (lat <= hi_y)
        in_window = int(inside.sum())
        # Fits the direct budget → ship the real in-window points so they render
        # *crisp* (individual marks) rather than as a blocky ~16-points-per-cell
        # grid. Position-only: the derived index stores no channels (§27), so
        # this drill needs a constant-styled trace; a channelled trace keeps the
        # exact grid below.
        if in_window <= SCATTER_DENSITY_THRESHOLD and not _has_point_channels(t):
            return _ship_index_points(t, request, lon[inside], lat[inside], lo_x, hi_x, lo_y, hi_y)
        # Otherwise bin the same gathered points to a grid at **full screen
        # resolution** — one cell per pixel, not the ~16-points-per-cell
        # aggregate grid that would then be stretched (and blur). At this zoom we
        # have the exact points, so the raster should be as sharp as the display;
        # it is uploaded with nearest-neighbour filtering (no interpolation
        # bleed) since there is no upscaling to smooth. The cell overhang outside
        # the window is dropped by bin_2d's half-open range test. This is the
        # deep-zoom detail (streets) the blurry upsampled pyramid can't give.
        w, h = _screen_shape(request.width, request.height)
        grid = kernels.bin_2d_f32(lon, lat, lo_x, hi_x, lo_y, hi_y, w, h)
        visible = in_window
        binning = "spatial-exact"
        density_filter = "nearest"
        lod.exit_drill(t)
    if grid is None and no_rescan:
        # No pyramid (below PYRAMID_MIN_POINTS is impossible here) or compose
        # still declined: bin the window once rather than never rendering. This
        # is the O(N) path we normally avoid, kept only as a correctness net.
        approx = int(est) if est is not None else len(xv)
        plan = lod.plan_view_lod(
            request,
            max(approx, SCATTER_DENSITY_THRESHOLD + 1),
            SCATTER_DENSITY_THRESHOLD,
            False,
            aggregate_reduction="bin2d-oversized",
        )
        visible = plan.visible
        w, h = plan.grid_w, plan.grid_h
        grid = kernels.bin_2d(xv, yv, lo_x, hi_x, lo_y, hi_y, w, h)
        bin_colors = trace_bin_colors(t) if mean_colors else None
        if bin_colors is not None:
            # This branch is already the O(N) correctness net; the mean-color
            # pass (LOD doc §2) rides the same full-column scan cost.
            rgba_grid = kernels.bin_2d_mean_color(
                xv, yv, lo_x, hi_x, lo_y, hi_y, w, h, **bin_colors
            )
        binning = "bin2d-oversized"
        lod.exit_drill(t)
    if grid is None:
        rgba_grid = None
        sel = kernels.range_indices(xv, yv, lo_x, hi_x, lo_y, hi_y)
        plan = lod.plan_view_lod(request, len(sel), SCATTER_DENSITY_THRESHOLD, t.drill_mode)
        visible = plan.visible
        if plan.exact:
            # Ship the widest aligned window that still fits the budget (T13)
            # so the client's point-window cache answers nearby pans/zooms
            # locally; the raw view window is the floor. `visible` describes
            # the SHIPPED window; the view's own count keeps driving the
            # density→points intensity handoff.
            padded = _padded_drill_window(fig, t, pyr, lo_x, hi_x, lo_y, hi_y)
            if padded is not None:
                lo_x, hi_x, lo_y, hi_y, sel = padded
            return _drill_points(
                fig, t, sel, len(sel), lo_x, hi_x, lo_y, hi_y, w, h, blend_visible=visible
            )

        lod.exit_drill(t)
        w, h = plan.grid_w, plan.grid_h
        bx, (bx0, bx1) = fig._binning_coords(t.x_axis, xv, (lo_x, hi_x))
        by, (by0, by1) = fig._binning_coords(t.y_axis, yv, (lo_y, hi_y))
        grid = kernels.bin_2d(bx, by, bx0, bx1, by0, by1, w, h)
        bin_colors = trace_bin_colors(t) if mean_colors else None
        if bin_colors is not None:
            # Mean point color per cell (LOD doc §2): same window, same
            # binning space, occupied cells match the count grid exactly.
            rgba_grid = kernels.bin_2d_mean_color(bx, by, bx0, bx1, by0, by1, w, h, **bin_colors)
    else:
        plan = lod.plan_view_lod(
            request,
            visible,
            SCATTER_DENSITY_THRESHOLD,
            False,
            aggregate_reduction="pyramid-count",
        )
    writer = lod.BufferWriter()
    density_wire, gmax = _encode_log_u8(grid)
    density_buf = writer.add_raw(density_wire)
    density = {
        "buf": density_buf,
        "w": w,
        "h": h,
        "max": gmax,
        # Quantized wire: log-encoded u8 (4x smaller than f32).
        # The client's texture is 8-bit log anyway, so the
        # round-trip is visually exact; `max` restores scale.
        "enc": "log-u8",
        "filter": density_filter,
        "x_range": [lo_x, hi_x],
        "y_range": [lo_y, hi_y],
    }
    if rgba_grid is not None:
        density["rgba"] = writer.add_u8(np.ascontiguousarray(rgba_grid).reshape(-1))
        density["color_agg"] = "mean"
    if t.color_ch and t.color_ch.mode == "constant" and t.color_ch.constant is not None:
        density["color"] = t.color_ch.constant
    return (
        {
            "traces": [
                {
                    "id": trace_id,
                    "mode": "density",
                    "tier": plan.tier,
                    "visible": visible,
                    "reduction": plan.reduction,
                    "binning": binning,
                    "density": density,
                }
            ]
        },
        writer.buffers,
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
    blend_visible: int | None = None,
) -> tuple[dict[str, Any], list[bytes]]:
    """Ship the visible subset of a Tier-2 scatter as real points (§5 drill-in).

    Scatter-specific wiring over the chart-agnostic pieces in `lod`: channels
    ship in the direct-scatter wire shape, normalized over their *global*
    domain so colors/sizes stay stable across views; offsets re-center on the
    window midpoint (§16); each point carries its local log-density plus a
    `lod_blend` weight so the density→points handoff stays continuous (§5).
    The window may be a padded aligned superset of the requested view (T13),
    so `visible` counts the SHIPPED window while `blend_visible` — the
    requested view's own count — drives the handoff weight: the intensity a
    user sees at the swap belongs to the view, not to padding they can't see.
    The surface wears the mean point color (LOD doc §2), so the handoff is
    intensity-only: fresh marks enter at their cell's count-alpha and ease to
    native opacity, with hue continuous throughout."""
    xs, ys = t.x.values[sel], t.y.values[sel]
    writer = lod.BufferWriter()
    x_ref, y_ref = lod.add_window_xy(
        writer,
        xs,
        ys,
        lo_x,
        hi_x,
        lo_y,
        hi_y,
        fig._axis_scale(t.x_axis),
        fig._axis_scale(t.y_axis),
    )
    buffers = writer.buffers

    color_spec, size_spec = fig._ship_channels(
        t, sel, writer.add_f32, writer.add_u8, quantize_continuous=True
    )

    # Local log-density per drilled point, binned at the same screen-derived
    # grid shape density would use — in the same (scale-coordinate) binning
    # space — so the two representations line up.
    gw, gh = lod.grid_shape(w, h, visible)
    dx, (d_x0, d_x1) = fig._binning_coords(t.x_axis, xs, (lo_x, hi_x))
    dy, (d_y0, d_y1) = fig._binning_coords(t.y_axis, ys, (lo_y, hi_y))
    dval_buf = writer.add_u8(
        _quantize_dval(lod.local_log_density(dx, dy, d_x0, d_x1, d_y0, d_y1, gw, gh))
    )
    drill_seq = lod.enter_drill(t, sel)
    # 1.0 right at the boundary → points enter at the density surface's
    # local count-alpha; →0 as zoom deepens. The surface wears the mean point
    # color (LOD doc §2), so marks arrive in their native colors and only
    # intensity eases. Keyed on the VIEW's count when the window is padded —
    # padding widens what ships, not what the user is looking at.
    lod_blend = float(
        min(1.0, (visible if blend_visible is None else blend_visible) / SCATTER_DENSITY_THRESHOLD)
    )
    trace_update = {
        "id": t.id,
        "mode": "points",
        "tier": "direct",
        "visible": visible,
        "reduction": "none",
        # The window these points cover: the client draws points
        # while the view stays inside it, and falls back to the
        # density overview the instant a zoom-out leaves it — so
        # zooming out is never blank (§5 smooth transitions).
        "x_range": [lo_x, hi_x],
        "y_range": [lo_y, hi_y],
        "x": x_ref,
        "y": y_ref,
        "color": color_spec,
        "size": size_spec,
        "density_val": {"buf": dval_buf, "dtype": "u8"},
        "lod_blend": lod_blend,
        "drill_seq": drill_seq,
        "style": dict(t.style),
    }
    if t.stroke_ch is not None:
        trace_update["stroke"] = channels.ship_color_channel(
            t.stroke_ch, sel, writer.add_f32, writer.add_u8, DEFAULT_PALETTE
        )
    if t.style_channels:
        trace_update["channels"] = channels.ship_style_channels(
            t.style_channels, sel, writer.add_f32, writer.add_u8
        )
    return ({"traces": [trace_update]}, buffers)


def append_data(
    fig: "Figure",
    trace_id: int,
    x: Any,
    y: Any,
    color: Any = None,
    size: Any = None,
    stroke: Any = None,
    opacity: Any = None,
    alpha: Any = None,
    stroke_width: Any = None,
    symbol: Any = None,
) -> tuple[dict[str, Any], list[memoryview]]:
    """Streaming append (Phase-0): extend a trace's canonical
    columns in place and return the client refresh message.

    The wire never ships deltas because it never needs to: every tier's payload
    is screen-bounded by construction (design dossier §29 — direct ≤ budget,
    M4 ≤ 4·px, density = grid), so re-emitting the affected trace costs
    O(pixels), not O(N). The message carries a complete fresh payload in the
    split layout (per-column borrowed views, no join copy); the client rebuilds
    only the traces named in `affected` and re-requests its current view
    through the normal stale-while-revalidate path. The spec carries
    `append: {seq, affected}` so a host whose transport is the payload itself
    (the widget's spec+buffers trait update) can detect and apply the refresh
    without a separate message envelope.

    Phase-0 contract (violations raise before anything mutates):
    - scatter and line traces only;
    - line appends must be finite, ascending, and start at or after the
      current last x (the ingest-time sort is never silently invalidated);
    - a continuous color/size channel must be appended alongside x/y
      (categorical channels would need new-category resolution — later);
    - columns shared with another trace are rejected (a partial append would
      desync that trace's lengths).

    Cache effects: an existing scatter tile pyramid is incremented natively in
    O(appended rows · levels) when the new finite points stay inside its domain.
    Domain growth, a stale handle, or a concurrent reader invalidates it for a
    safe lazy rebuild. Any active drill exits so the next view decision is made
    against the new data.
    """
    t = _trace(fig, trace_id)
    if t.kind not in {"scatter", "line"}:
        raise ValueError(f"append supports scatter/line traces, not {t.kind!r}")

    ax, x_kind, _ = columns._canonicalize(x)
    ay, y_kind, _ = columns._canonicalize(y)
    if x_kind != t.x.kind or y_kind != t.y.kind:
        raise ValueError(
            f"appended kinds ({x_kind!r}, {y_kind!r}) must match the trace's "
            f"columns ({t.x.kind!r}, {t.y.kind!r})"
        )
    if len(ax) != len(ay):
        raise ValueError(f"appended x and y must have equal length, got {len(ax)} and {len(ay)}")
    if len(ax) == 0:
        raise ValueError("append needs at least one row")

    if t.kind == "line":
        if not bool(np.all(np.isfinite(ax))):
            raise ValueError("line append requires finite x values")
        if len(ax) > 1 and bool(np.any(np.diff(ax) < 0)):
            raise ValueError("line append requires ascending x")
        prev = t.x.zone.max  # NaN when the column is empty/all-null
        if np.isfinite(prev) and ax[0] < prev:
            raise ValueError(
                f"line append must continue the series: new x starts at {ax[0]!r}, "
                f"before the current last x {prev!r} (lines are sorted once at ingest)"
            )

    def _channel_tail(ch: Any, values: Any, name: str) -> Optional[np.ndarray]:
        has = ch is not None and ch.mode not in {"constant", "match_fill"}
        if has and ch.mode not in {"continuous", "direct_rgba"}:
            raise ValueError(f"append does not support categorical {name} channels yet")
        if has and values is None:
            qualifier = "continuous" if ch.mode == "continuous" else "per-point"
            raise ValueError(f"trace {t.id} has a {qualifier} {name} channel; pass {name}=")
        if not has and values is not None:
            raise ValueError(f"trace {t.id} has no per-point {name} channel")
        if values is None:
            return None
        if ch.mode == "direct_rgba":
            resolved = channels.resolve_color(values, len(ax), default_constant="#000000")
            if resolved.mode != "direct_rgba" or resolved.rgba is None:
                raise ValueError(f"appended {name} must be an RGB(A) array")
            return resolved.rgba
        arr = np.asarray(values, dtype=np.float64).ravel()
        if len(arr) != len(ax):
            raise ValueError(f"{name} length {len(arr)} != appended row count {len(ax)}")
        return arr

    symbol_ids = {
        name: index
        for index, name in enumerate(
            (
                "circle",
                "square",
                "diamond",
                "triangle",
                "cross",
                "hexagon",
                "pentagon",
                "star",
                "triangle_down",
                "triangle_left",
                "triangle_right",
                "x",
                "point",
                "pixel",
                "thin_diamond",
                "plus_line",
                "x_line",
            )
        )
    }

    def _style_tail(name: str, values: Any) -> Optional[np.ndarray]:
        channel = t.style_channels.get(name)
        if channel is None:
            if values is not None:
                raise ValueError(f"trace {t.id} has no per-point {name} channel")
            return None
        if values is None:
            raise ValueError(f"trace {t.id} has a per-point {name} channel; pass {name}=")
        if name == "symbol":
            raw = np.asarray(values)
            if raw.shape != (len(ax),):
                raise ValueError(f"symbol length {raw.size} != appended row count {len(ax)}")
            try:
                result = np.asarray([symbol_ids[str(value)] for value in raw], dtype=np.uint8)
            except KeyError as exc:
                raise ValueError(f"unsupported appended symbol {exc.args[0]!r}") from None
            return result
        expected = (len(ax),) if channel.components == 1 else (len(ax), channel.components)
        arr = np.asarray(values, dtype=np.float64)
        if arr.shape != expected:
            raise ValueError(f"{name} array must have shape {expected}, got {arr.shape}")
        if not np.isfinite(arr).all():
            raise ValueError(f"{name} array must contain only finite values")
        if name in {"opacity", "artist_alpha"} and (
            np.any(arr < (-1.0 if name == "artist_alpha" else 0.0)) or np.any(arr > 1.0)
        ):
            raise ValueError(f"{name} array values must be within [0, 1]")
        if name == "stroke_width" and np.any(arr < 0.0):
            raise ValueError("stroke_width array values must be non-negative")
        return np.ascontiguousarray(arr)

    color_tail = _channel_tail(t.color_ch, color, "color")
    size_tail = _channel_tail(t.size_ch, size, "size")
    stroke_tail = _channel_tail(t.stroke_ch, stroke, "stroke")
    style_tails = {
        "opacity": _style_tail("opacity", opacity),
        "artist_alpha": _style_tail("artist_alpha", alpha),
        "stroke_width": _style_tail("stroke_width", stroke_width),
        "symbol": _style_tail("symbol", symbol),
    }

    appended = {id(t.x), id(t.y)}
    for other in fig.traces:
        if other.id == t.id:
            continue
        for col in (
            other.x,
            other.y,
            other.base,
            other.grid,
            other.x0,
            other.x1,
            other.y0,
            other.y1,
        ):
            if col is not None and id(col) in appended:
                raise ValueError(
                    f"trace {t.id} shares a column with trace {other.id}; "
                    "appending to shared columns is not supported"
                )

    # -- validation done; mutate ------------------------------------------------
    t.x.append(ax)
    t.y.append(ay)
    if color_tail is not None:
        if t.color_ch.mode == "direct_rgba":
            t.color_ch.rgba = np.concatenate((t.color_ch.rgba, color_tail), axis=0)
        else:
            channels.append_continuous(t.color_ch, color_tail, "color")
    if size_tail is not None:
        channels.append_continuous(t.size_ch, size_tail, "size")
    if stroke_tail is not None:
        t.stroke_ch.rgba = np.concatenate((t.stroke_ch.rgba, stroke_tail), axis=0)
    for name, tail in style_tails.items():
        if tail is not None:
            channel = t.style_channels[name]
            channel.values = np.concatenate((channel.values, tail), axis=0)

    pyramid = getattr(t, "_pyr_handle", None)
    if t.kind == "scatter" and pyramid:
        if not kernels.pyramid_append(pyramid, ax, ay):
            _free_pyramid(t)
    elif pyramid == 0 and len(t.x) >= PYRAMID_MIN_POINTS:
        # The trace crossed the lazy-index threshold after an earlier
        # "not applicable" result; let the next wide view build it.
        t._pyr_handle = None
    # The cached bin-color resolution covered the pre-append rows over the
    # pre-append domain; drop it for a lazy full re-resolve (LOD doc §2).
    t._bin_colors = None
    lod.exit_drill(t)
    # Remembered subsets were computed against the pre-append canonical state;
    # the client rebuilds its GPU traces (and drops its cached point windows)
    # on the refresh anyway, so stale-seq picks must die rather than translate.
    lod.clear_drill_history(t)

    # Split layout, same as first paint (§29): per-column borrowed views, no
    # join copy. The spec itself names the append — `append.seq` is the apply
    # signal for the widget host, where the refresh rides the spec+buffers
    # trait update as one comm message that doubles as notebook-reopen state.
    # The socket.io host wraps the same spec in an `append` message push.
    fig._append_seq += 1
    seq = fig._append_seq
    spec, buffers = fig.build_payload_split()
    spec["append"] = {"seq": seq, "affected": [t.id]}
    return {"type": "append", "affected": [t.id], "spec": spec}, buffers
