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
import weakref
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import channels, columns, kernels, lod
from .config import (
    DECIMATION_THRESHOLD,
    DENSITY_SAMPLE_SEED,
    DENSITY_SAMPLE_TARGET,
    DENSITY_TARGET_POINTS_PER_CELL,  # noqa: F401  (historic import path)
    DRILL_EXIT_FACTOR,
    PYRAMID_BASE_DIM,
    PYRAMID_MIN_POINTS,
    SCATTER_DENSITY_THRESHOLD,
)

if TYPE_CHECKING:
    from ._figure import Figure


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
        x_candidates = _zone_candidates(t.x, lo_x, hi_x)
        y_candidates = _zone_candidates(t.y, lo_y, hi_y)
        candidates = np.intersect1d(x_candidates, y_candidates, assume_unique=True)
        if len(candidates) == len(t.x):
            out[t.id] = kernels.range_indices(t.x.values, t.y.values, lo_x, hi_x, lo_y, hi_y)
        elif len(candidates) == 0:
            out[t.id] = np.empty(0, dtype=np.uint32)
        else:
            out[t.id] = kernels.range_indices(
                t.x.values[candidates], t.y.values[candidates], lo_x, hi_x, lo_y, hi_y
            )
            out[t.id] = candidates[out[t.id]]
    return out


def to_shipped_indices(fig: "Figure", trace_id: int, canonical: np.ndarray) -> np.ndarray:
    """Translate canonical row indices to *shipped* vertex positions for a
    trace — the coordinate space the client's per-vertex selection mask uses.
    Identity when nothing was dropped at ship time."""
    sel = _point_shipped_sel(_trace(fig, trace_id))
    if sel is None:
        return np.asarray(canonical, dtype=np.uint32)
    # sel is sorted ascending (flatnonzero/m4 output); membership → position.
    canonical = np.asarray(canonical, dtype=np.uint32).ravel()
    positions = np.searchsorted(sel, canonical)
    valid = positions < len(sel)
    valid[valid] &= sel[positions[valid]] == canonical[valid]
    return positions[valid].astype(np.uint32)


def _zone_candidates(col: Any, lo: float, hi: float) -> np.ndarray:
    """Return row ids from chunks whose zone can overlap an inclusive range."""
    if len(col) == 0:
        return np.empty(0, dtype=np.uint32)
    mins = col.zone.mins
    maxs = col.zone.maxs
    counts = col.zone.counts
    chunks = np.flatnonzero((counts > 0) & (maxs >= lo) & (mins <= hi))
    if len(chunks) == len(mins):
        return np.arange(len(col), dtype=np.uint32)
    pieces = [
        np.arange(
            int(chunk) * columns.ZONE_CHUNK,
            min((int(chunk) + 1) * columns.ZONE_CHUNK, len(col)),
            dtype=np.uint32,
        )
        for chunk in chunks
    ]
    return np.concatenate(pieces) if pieces else np.empty(0, dtype=np.uint32)


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
    writer = lod.BufferWriter()
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
        x_col = lod.encode_f32_values(xv, (lo_x + hi_x) / 2.0, lo_x, hi_x)
        y_col = lod.encode_f32_values(yv, t.y.suggest_offset(), t.y.min, t.y.max)
        update = {
            "id": t.id,
            "x": writer.add_encoded(x_col),
            "y": writer.add_encoded(y_col),
        }
        if bv is not None and t.base is not None:
            b_col = lod.encode_f32_values(bv, t.base.suggest_offset(), t.base.min, t.base.max)
            update["base"] = writer.add_encoded(b_col)
        updates.append(update)
    return {"traces": updates}, writer.buffers


def _ensure_pyramid(t) -> int | None:
    """Lazily build the trace's count pyramid (§5 Tier 3). Cached on the
    trace; 0 is remembered as "tried and not applicable" so we never rebuild.
    Only worth the memory for genuinely large traces."""
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
    handle = kernels.pyramid_build(t.x.values, t.y.values, x0, x1, y0, y1, PYRAMID_BASE_DIM)
    t._pyr_handle = handle
    if handle:
        # §27: the pyramid is native-side memory owned by this trace. Tie its
        # lifetime to the Trace object so a discarded Figure (the notebook
        # cell-re-run pattern) frees it instead of leaking it in the
        # process-lifetime registry.
        t._pyr_finalizer = weakref.finalize(t, kernels.pyramid_free, handle)
    return handle or None


def _free_pyramid(t) -> None:
    """Free the trace's pyramid now and disarm its GC finalizer.

    Resets the handle to None ("never tried") so the next far-out view
    rebuilds lazily; safe to call when no pyramid was ever built.
    """
    fin = getattr(t, "_pyr_finalizer", None)
    if fin is not None:
        fin()  # runs pyramid_free exactly once; later GC becomes a no-op
        t._pyr_finalizer = None
    elif getattr(t, "_pyr_handle", None):
        kernels.pyramid_free(t._pyr_handle)
    t._pyr_handle = None


def _pyramid_resident_bytes(base_dim: int = PYRAMID_BASE_DIM) -> int:
    """Exact native bytes of one count pyramid: u32 levels from base_dim²
    halving per side down to 1² (mirrors tiles.rs level construction)."""
    total, dim = 0, base_dim
    while True:
        total += dim * dim * 4
        if dim == 1:
            return total
        dim >>= 1


def pyramid_report_bytes(fig) -> int:
    """§27 memory-report line: native bytes held by live trace pyramids."""
    return sum(_pyramid_resident_bytes() for t in fig.traces if getattr(t, "_pyr_handle", 0))


def _encode_log_u8(grid: np.ndarray, gmax: float) -> bytes:
    """Density grid -> log-encoded u8 wire bytes (client decodes via expm1).
    Zero cells stay zero; any nonzero cell maps to at least 1 so the "lit if
    occupied" texture contract survives quantization."""
    arr = np.asarray(grid, dtype=np.float64).ravel()
    if gmax <= 0.0:
        return bytes(arr.size)
    enc = np.round(255.0 * np.log1p(arr) / np.log1p(gmax)).astype(np.uint8)
    enc[(arr > 0) & (enc == 0)] = 1
    return enc.tobytes()


def _decode_log_u8(buf: bytes, gmax: float) -> np.ndarray:
    """Inverse of :func:`_encode_log_u8` — the Python twin of the client's
    ``lodDecodeLogU8`` and the executable wire contract for tests. Lossy
    (8-bit in log space, sub-percent per-cell at typical maxima), but zeros
    are exact and the grid max is restored exactly."""
    v = np.frombuffer(buf, dtype=np.uint8).astype(np.float64)
    if gmax <= 0.0:
        return np.zeros(v.size, dtype=np.float64)
    return np.expm1((v / 255.0) * np.log1p(gmax))


def _density_sample_update(
    fig: "Figure",
    t: Any,
    sel: np.ndarray,
    visible: int,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
    writer: lod.BufferWriter,
) -> Optional[dict[str, Any]]:
    if visible <= 0:
        return None
    categories = None
    if t.color_ch and t.color_ch.mode == "categorical" and t.color_ch.codes is not None:
        categories = t.color_ch.codes[sel]
    sample_sel = lod.sample_rows_for_target(
        sel,
        DENSITY_SAMPLE_TARGET,
        categories=categories,
        seed=DENSITY_SAMPLE_SEED,
    )
    if len(sample_sel) == 0:
        return None
    xs, ys = t.x.values[sample_sel], t.y.values[sample_sel]
    x_ref, y_ref = lod.add_window_xy(writer, xs, ys, lo_x, hi_x, lo_y, hi_y)
    color_spec, size_spec = fig._ship_channels(t, sample_sel, writer.add_f32)
    style = dict(t.style)
    try:
        style["opacity"] = min(float(style.get("opacity", 0.8)), 0.55)
    except (TypeError, ValueError):
        style["opacity"] = 0.55
    return {
        "mode": "sampled",
        "n": int(len(sample_sel)),
        "visible": int(visible),
        "target": DENSITY_SAMPLE_TARGET,
        "level": 0,
        "seed": DENSITY_SAMPLE_SEED,
        "x": x_ref,
        "y": y_ref,
        "x_range": [lo_x, hi_x],
        "y_range": [lo_y, hi_y],
        "color": color_spec,
        "size": size_spec,
        "style": style,
    }


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
    request = lod.ViewportRequest.from_client(x0, x1, y0, y1, w, h)
    lo_x, hi_x = request.x_range
    lo_y, hi_y = request.y_range
    w, h = request.width, request.height
    if not t.use_density():
        return {"traces": []}, []
    xv, yv = t.x.values, t.y.values
    # Tile-pyramid fast path (§5 Tier 3): when the window is clearly still in
    # density territory, the view is served from pre-binned counts in
    # O(visible cells) — no O(N) rescan. The margin keeps the approximate
    # pyramid count from ever usurping a would-be drill; anywhere near the
    # budget we fall through to the exact scan that drilling needs anyway.
    binning = "exact"
    grid = None
    pyr = _ensure_pyramid(t)
    if pyr is not None:
        est = kernels.pyramid_count(pyr, lo_x, hi_x, lo_y, hi_y)
        if est is not None and est > SCATTER_DENSITY_THRESHOLD * DRILL_EXIT_FACTOR * 1.5:
            plan = lod.plan_view_lod(
                request,
                int(est),
                SCATTER_DENSITY_THRESHOLD,
                False,
                aggregate_reduction="pyramid-count",
            )
            res = kernels.pyramid_compose(pyr, lo_x, hi_x, lo_y, hi_y, plan.grid_w, plan.grid_h)
            if res is not None:
                grid, level = res
                visible = plan.visible
                w, h = plan.grid_w, plan.grid_h
                binning = f"pyramid-L{level}"
                lod.exit_drill(t)
    if grid is None:
        sel = kernels.range_indices(xv, yv, lo_x, hi_x, lo_y, hi_y)
        plan = lod.plan_view_lod(request, len(sel), SCATTER_DENSITY_THRESHOLD, t.drill_mode)
        visible = plan.visible
        if plan.exact:
            return _drill_points(fig, t, sel, visible, lo_x, hi_x, lo_y, hi_y, w, h)

        lod.exit_drill(t)
        w, h = plan.grid_w, plan.grid_h
        grid = kernels.bin_2d(xv, yv, lo_x, hi_x, lo_y, hi_y, w, h)
    else:
        plan = lod.plan_view_lod(
            request,
            visible,
            SCATTER_DENSITY_THRESHOLD,
            False,
            aggregate_reduction="pyramid-count",
        )
    # numpy's .max() stub mis-resolves the overload for the kernel's f32 grid.
    gmax = float(grid.max()) if grid.size else 0.0  # ty: ignore[invalid-argument-type]
    writer = lod.BufferWriter()
    density_buf = writer.add_raw(_encode_log_u8(grid, gmax))
    sample = (
        _density_sample_update(fig, t, sel, visible, lo_x, hi_x, lo_y, hi_y, writer)
        if binning == "exact"
        else None
    )
    density = {
        "buf": density_buf,
        "w": w,
        "h": h,
        "max": gmax,
        # Quantized wire: log-encoded u8 (4x smaller than f32).
        # The client's texture is 8-bit log anyway, so the
        # round-trip is visually exact; `max` restores scale.
        "enc": "log-u8",
        "x_range": [lo_x, hi_x],
        "y_range": [lo_y, hi_y],
    }
    if sample is not None:
        density["sample"] = sample
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
) -> tuple[dict[str, Any], list[bytes]]:
    """Ship the visible subset of a Tier-2 scatter as real points (§5 drill-in).

    Scatter-specific wiring over the chart-agnostic pieces in `lod`: channels
    ship in the direct-scatter wire shape, normalized over their *global*
    domain so colors/sizes stay stable across views; offsets re-center on the
    window midpoint (§16); each point carries its local log-density plus a
    `lod_blend` weight (visible/budget) so the density→points handoff is
    color-continuous instead of a palette jump (§5)."""
    xs, ys = t.x.values[sel], t.y.values[sel]
    writer = lod.BufferWriter()
    x_ref, y_ref = lod.add_window_xy(writer, xs, ys, lo_x, hi_x, lo_y, hi_y)
    buffers = writer.buffers

    color_spec, size_spec = fig._ship_channels(t, sel, writer.add_f32)

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


def append_data(
    fig: "Figure",
    trace_id: int,
    x: Any,
    y: Any,
    color: Any = None,
    size: Any = None,
) -> tuple[dict[str, Any], list[bytes]]:
    """Streaming append (rust-engine §5, Phase-0): extend a trace's canonical
    columns in place and return the client refresh message.

    The wire never ships deltas because it never needs to: every tier's payload
    is screen-bounded by construction (§29 — direct ≤ budget, M4 ≤ 4·px,
    density = grid), so re-emitting the affected trace costs O(pixels), not
    O(N). The message carries a complete fresh payload; the client rebuilds
    only the traces named in `affected` and re-requests its current view
    through the normal stale-while-revalidate path (§17).

    Phase-0 contract (violations raise before anything mutates):
    - scatter and line traces only;
    - line appends must be finite, ascending, and start at or after the
      current last x (the ingest-time sort is never silently invalidated);
    - a continuous color/size channel must be appended alongside x/y
      (categorical channels would need new-category resolution — later);
    - columns shared with another trace are rejected (a partial append would
      desync that trace's lengths).

    Cache effects: the trace's tile pyramid is freed for lazy rebuild (the §5
    dirty-tile incremental rebuild is the known follow-up; a >2M-point stream
    pays a full pyramid rebuild on its next far-out view for now — recorded
    here, not hidden) and any active drill exits so the next view decision is
    made against the new data.
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
        has = ch is not None and ch.mode != "constant"
        if has and ch.mode != "continuous":
            raise ValueError(f"append does not support categorical {name} channels yet")
        if has and values is None:
            raise ValueError(f"trace {t.id} has a continuous {name} channel; pass {name}=")
        if not has and values is not None:
            raise ValueError(f"trace {t.id} has no per-point {name} channel")
        if values is None:
            return None
        arr = np.asarray(values, dtype=np.float64).ravel()
        if len(arr) != len(ax):
            raise ValueError(f"{name} length {len(arr)} != appended row count {len(ax)}")
        return arr

    color_tail = _channel_tail(t.color_ch, color, "color")
    size_tail = _channel_tail(t.size_ch, size, "size")

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
        channels.append_continuous(t.color_ch, color_tail, "color")
    if size_tail is not None:
        channels.append_continuous(t.size_ch, size_tail, "size")

    _free_pyramid(t)  # lazily rebuilt; n grew so "not applicable" may flip
    lod.exit_drill(t)

    spec, blob = fig.build_payload()
    return {"type": "append", "affected": [t.id], "spec": spec}, [blob]
