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

import numbers
from dataclasses import dataclass
from typing import Any, cast

import numpy as np

from . import kernels
from .config import DENSITY_TARGET_POINTS_PER_CELL, DRILL_EXIT_FACTOR, MAX_SCREEN_DIM

_SPLITMIX_INCREMENT = np.uint64(0x9E3779B97F4A7C15)
_SPLITMIX_MUL_1 = np.uint64(0xBF58476D1CE4E5B9)
_SPLITMIX_MUL_2 = np.uint64(0x94D049BB133111EB)
_UINT64_MAX_INT = (1 << 64) - 1
_DEFAULT_SAMPLE_BASE_FRACTION = 1.0 / 1024.0


@dataclass(frozen=True)
class ViewportRequest:
    """Normalized client viewport shared by every tiered chart kind.

    Browser and adapter events can send reversed ranges, non-integer screen
    sizes, or malicious non-finite values. This object is the single checked
    boundary before kernels, drill state, or tile caches see a request.
    """

    lo_x: float
    hi_x: float
    lo_y: float
    hi_y: float
    width: int
    height: int

    @classmethod
    def from_client(
        cls,
        x0: float,
        x1: float,
        y0: float,
        y1: float,
        width: int,
        height: int,
        *,
        require_area: bool = True,
    ) -> "ViewportRequest":
        lo_x, hi_x, lo_y, hi_y = normalize_window(x0, x1, y0, y1, require_area=require_area)
        w, h = screen_shape(width, height)
        return cls(lo_x=lo_x, hi_x=hi_x, lo_y=lo_y, hi_y=hi_y, width=w, height=h)

    @property
    def x_range(self) -> tuple[float, float]:
        return (self.lo_x, self.hi_x)

    @property
    def y_range(self) -> tuple[float, float]:
        return (self.lo_y, self.hi_y)


@dataclass(frozen=True)
class LodPlan:
    """Chart-agnostic tier decision for a trace in a viewport.

    `mode` is the wire/client representation (`points`, `density`, future
    `buckets`, etc.). `tier` is the semantic reduction class used by docs,
    verifiers, and future adapters. `reduction` records what changed relative
    to direct marks.
    """

    mode: str
    tier: str
    visible: int
    budget: float
    grid_w: int
    grid_h: int
    reduction: str
    exact: bool

    def metadata(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "tier": self.tier,
            "visible": self.visible,
            "reduction": self.reduction,
        }


@dataclass(frozen=True)
class EncodedColumn:
    """Offset/scaled f32 column plus its wire metadata.

    First-payload builds, line/area re-decimation, scatter drilldown, and
    future bucketed chart updates all ship the same primitive: raw f32 values
    plus enough metadata for the client to recover data-space coordinates.
    """

    meta: dict[str, Any]
    values: np.ndarray

    @property
    def length(self) -> int:
        return int(len(self.values))


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


def screen_shape(w: int, h: int) -> tuple[int, int]:
    """Validate and clamp a browser/client screen shape.

    The floor avoids zero-size canvases causing invisible aggregate grids; the
    cap prevents a hostile client request from allocating an enormous density
    texture. This is shared by scatter density, line re-decimation, and future
    tiered chart kinds.
    """
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


def plan_view_lod(
    request: ViewportRequest,
    visible: object,
    budget: object,
    in_drill: bool,
    *,
    direct_mode: str = "points",
    aggregate_mode: str = "density",
    aggregate_reduction: str = "count",
    target_per_cell: float = DENSITY_TARGET_POINTS_PER_CELL,
    exit_factor: float = DRILL_EXIT_FACTOR,
) -> LodPlan:
    """Build the reusable tier decision for a viewport.

    The exact-vs-aggregate decision is common across tiered chart kinds; the
    representation names differ. Scatter passes `points`/`density`, while
    future histograms or candlesticks can pass `bins`/`ohlc-buckets` without
    reimplementing validation, hysteresis, or screen-bounded grid sizing.
    """
    visible_i = _integer_param(visible, "visible")
    budget_f = _float_param(budget, "LOD budget", min_exclusive=0.0)
    if not isinstance(in_drill, (bool, np.bool_)):
        raise ValueError("in_drill must be True or False")
    for value, label in (
        (direct_mode, "direct_mode"),
        (aggregate_mode, "aggregate_mode"),
        (aggregate_reduction, "aggregate_reduction"),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty string")
    exact = drill_decision(visible_i, budget_f, bool(in_drill), exit_factor=exit_factor)
    gw, gh = grid_shape(request.width, request.height, visible_i, target_per_cell)
    return LodPlan(
        mode=direct_mode if exact else aggregate_mode,
        tier="direct" if exact else aggregate_mode,
        visible=visible_i,
        budget=budget_f,
        grid_w=gw,
        grid_h=gh,
        reduction="none" if exact else aggregate_reduction,
        exact=exact,
    )


def _integer_param(
    value: object,
    label: str,
    *,
    min_value: int = 0,
    max_value: int | None = None,
) -> int:
    bound = f" and <= {max_value}" if max_value is not None else ""
    message = f"{label} must be an integer >= {min_value}{bound}"
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral):
        raise ValueError(message)
    out = int(value)
    if out < min_value:
        raise ValueError(message)
    if max_value is not None and out > max_value:
        raise ValueError(message)
    return out


def _float_param(
    value: object,
    label: str,
    *,
    min_exclusive: float | None = None,
    min_inclusive: float | None = None,
    max_inclusive: float | None = None,
) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be finite")
    try:
        out = float(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not np.isfinite(out):
        raise ValueError(f"{label} must be finite")
    if min_exclusive is not None and out <= min_exclusive:
        raise ValueError(f"{label} must be > {min_exclusive}")
    if min_inclusive is not None and out < min_inclusive:
        raise ValueError(f"{label} must be >= {min_inclusive}")
    if max_inclusive is not None and out > max_inclusive:
        raise ValueError(f"{label} must be <= {max_inclusive}")
    return out


def _row_ids(row_ids: Any, label: str = "row_ids") -> np.ndarray:
    ids = np.asarray(row_ids)
    if ids.ndim != 1:
        raise ValueError(f"{label} must be a one-dimensional integer array")
    if ids.dtype.kind == "b":
        raise ValueError(f"{label} must be a one-dimensional integer array")
    if ids.dtype.kind == "i":
        if len(ids) and bool(np.any(ids < 0)):
            raise ValueError(f"{label} must not contain negative values")
        return ids.astype(np.uint64, copy=False)
    if ids.dtype.kind == "u":
        return ids.astype(np.uint64, copy=False)
    raise ValueError(f"{label} must be a one-dimensional integer array")


def _sample_fraction(
    level: object,
    base_fraction: object,
    growth: object,
    *,
    label: str = "sample",
) -> float:
    level_i = _integer_param(level, f"{label} level")
    base = _float_param(
        base_fraction,
        f"{label} base_fraction",
        min_exclusive=0.0,
        max_inclusive=1.0,
    )
    growth_f = _float_param(growth, f"{label} growth", min_inclusive=1.0)
    if base >= 1.0 or growth_f == 1.0:
        return min(1.0, base)
    try:
        fraction = base * (growth_f**level_i)
    except OverflowError:
        return 1.0
    return min(1.0, fraction)


def _sample_threshold(fraction: float) -> np.uint64:
    if fraction >= 1.0:
        return np.uint64(_UINT64_MAX_INT)
    threshold = max(0, min(_UINT64_MAX_INT, int(fraction * _UINT64_MAX_INT)))
    return np.uint64(threshold)


def hash_row_ids(row_ids: Any, *, seed: int = 0) -> np.ndarray:
    """SplitMix64 row-id hash used by sampling tiers.

    The output is a pure function of `(row_id, seed)` and therefore independent
    of array order, viewport pan position, Python hash randomization, or runtime
    RNG state. Sampling tiers use this as the stable row ordering that prevents
    shimmer when zooming or panning.
    """
    ids = _row_ids(row_ids)
    seed_i = _integer_param(seed, "sample seed", max_value=_UINT64_MAX_INT)
    z = ids + np.uint64(seed_i) + _SPLITMIX_INCREMENT
    z = (z ^ (z >> np.uint64(30))) * _SPLITMIX_MUL_1
    z = (z ^ (z >> np.uint64(27))) * _SPLITMIX_MUL_2
    return z ^ (z >> np.uint64(31))


def sample_keep_mask(
    row_ids: Any,
    level: int,
    *,
    base_fraction: float = _DEFAULT_SAMPLE_BASE_FRACTION,
    growth: float = 2.0,
    seed: int = 0,
) -> np.ndarray:
    """Deterministic subset mask for sampled LOD overlays.

    `level` is a zoom/detail level: increasing it can only add rows because the
    hash threshold monotonically increases. That gives a future density+sample
    overlay stable anti-shimmer behavior: panning does not reshuffle points,
    and zooming in reveals more of the same row-id ordering instead of swapping
    one random subset for another.
    """
    ids = _row_ids(row_ids)
    fraction = _sample_fraction(level, base_fraction, growth)
    if len(ids) == 0:
        return np.zeros(0, dtype=bool)
    if fraction >= 1.0:
        return np.ones(len(ids), dtype=bool)
    seed_i = _integer_param(seed, "sample seed", max_value=_UINT64_MAX_INT)
    # Fused native pass — bit-identical to
    # `hash_row_ids(ids, seed=seed) <= _sample_threshold(fraction)` (the NumPy
    # reference, parity-tested), but without five full-width u64 temporaries.
    # At 10M rows this was ~68% of the density payload build.
    return kernels.sample_mask(ids, seed_i, int(_sample_threshold(fraction)))


def stratified_sample_keep_mask(
    row_ids: Any,
    categories: Any,
    level: int,
    *,
    base_fraction: float = _DEFAULT_SAMPLE_BASE_FRACTION,
    growth: float = 2.0,
    seed: int = 0,
    min_per_category: int = 1,
) -> np.ndarray:
    """Deterministic category-aware sampled LOD mask.

    Expected kept rows per category scale sublinearly with category size
    (`~sqrt(count)`) while `min_per_category` pins rare categories into view.
    The lowest-hash rows satisfy that floor at every level, so the mask remains
    monotonic as zoom/detail increases.
    """
    ids = _row_ids(row_ids)
    cats = np.asarray(categories)
    if cats.ndim != 1 or len(cats) != len(ids):
        raise ValueError("categories must be a one-dimensional array matching row_ids")
    min_count = _integer_param(min_per_category, "sample min_per_category")
    fraction = _sample_fraction(level, base_fraction, growth, label="stratified sample")
    if len(ids) == 0:
        return np.zeros(0, dtype=bool)
    if fraction >= 1.0:
        return np.ones(len(ids), dtype=bool)

    hashes = hash_row_ids(ids, seed=seed)
    keep = np.zeros(len(ids), dtype=bool)
    _, inverse, counts = np.unique(cats, return_inverse=True, return_counts=True)
    n = float(len(ids))
    for group, count in enumerate(counts):
        idx = np.flatnonzero(inverse == group)
        group_fraction = min(1.0, fraction * float(np.sqrt(n / float(count))))
        group_keep = hashes[idx] <= _sample_threshold(group_fraction)
        floor = min(min_count, len(idx))
        if floor and int(group_keep.sum()) < floor:
            winners = np.argpartition(hashes[idx], floor - 1)[:floor]
            group_keep[winners] = True
        keep[idx] = group_keep
    return keep


def sample_rows_for_target(
    row_ids: Any,
    target: object,
    *,
    categories: Any | None = None,
    level: int = 0,
    growth: float = 2.0,
    seed: int = 0,
    min_per_category: int = 1,
) -> np.ndarray:
    """Return a deterministic, target-sized representative subset of rows.

    Density overlays and future sampled tiers should share this wrapper instead
    of reimplementing "target N rows from this viewport" math. The returned
    rows preserve the caller's integer dtype, while hashing uses validated
    uint64 row ids internally. Subsets are stable across row order and viewport
    pans because row identity, not position in the current array, drives the
    decision.
    """
    raw_ids = np.asarray(row_ids)
    ids = _row_ids(raw_ids)
    target_i = _integer_param(target, "sample target", min_value=1)
    if len(ids) == 0:
        return raw_ids[:0]
    base_fraction = min(1.0, target_i / max(1, len(ids)))
    if categories is None:
        mask = sample_keep_mask(
            ids,
            level,
            base_fraction=base_fraction,
            growth=growth,
            seed=seed,
        )
    else:
        mask = stratified_sample_keep_mask(
            ids,
            categories,
            level,
            base_fraction=base_fraction,
            growth=growth,
            seed=seed,
            min_per_category=min_per_category,
        )
    return raw_ids[mask]


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

    def add_encoded(self, column: EncodedColumn) -> dict[str, Any]:
        """Append an `EncodedColumn` and return the common `{buf, len, ...meta}` ref."""
        return {"buf": self.add_f32(column.values), "len": column.length, **column.meta}


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


def encode_f32_values(
    values: Any,
    offset: float,
    lo: float,
    hi: float,
    *,
    kind: str | None = None,
) -> EncodedColumn:
    """Shared offset-encoded geometry primitive for every wire path.

    `offset` chooses the precision center, while `lo`/`hi` describe the
    expected numeric domain used to pick an f32-safe scale. Windowed updates
    usually pass viewport bounds; first-payload columns pass canonical column
    bounds. The optional `kind` rides only in first-payload column tables.
    """
    vals = np.ascontiguousarray(np.asarray(values, dtype=np.float64).ravel())
    offset_f = float(offset)
    scale = f32_safe_scale(offset_f, float(lo), float(hi))
    enc = (
        np.empty(0, dtype=np.float32)
        if len(vals) == 0
        else kernels.encode_f32(vals, offset_f, scale)
    )
    meta: dict[str, Any] = {"offset": offset_f, "scale": scale}
    if kind is not None:
        meta["kind"] = kind
    return EncodedColumn(meta=meta, values=enc)


def encode_window_xy_columns(
    xs: np.ndarray, ys: np.ndarray, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> tuple[EncodedColumn, EncodedColumn]:
    """Window-centered x/y encoding shared by drilled or sampled point updates."""
    x_off = (lo_x + hi_x) / 2.0
    y_off = (lo_y + hi_y) / 2.0
    return (
        encode_f32_values(xs, x_off, lo_x, hi_x),
        encode_f32_values(ys, y_off, lo_y, hi_y),
    )


def add_window_xy(
    writer: BufferWriter,
    xs: np.ndarray,
    ys: np.ndarray,
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Append a viewport-centered x/y pair to a shared LOD buffer writer.

    Sample overlays, drilldown points, and future point-like bucket expansions
    should share this path so deep-zoom f32 precision and `{buf, len, offset,
    scale}` wire metadata stay identical across tiered chart kinds.
    """
    x_col, y_col = encode_window_xy_columns(xs, ys, lo_x, hi_x, lo_y, hi_y)
    return writer.add_encoded(x_col), writer.add_encoded(y_col)


def encode_window_xy(
    xs: np.ndarray, ys: np.ndarray, lo_x: float, hi_x: float, lo_y: float, hi_y: float
) -> tuple[dict, dict, np.ndarray, np.ndarray]:
    """Offset-encode a drilled subset re-centered on the window midpoint (§16
    deep-zoom rule) — f32 precision follows the viewport, not the dataset.
    Returns wire metas ({offset, scale}) plus the encoded arrays."""
    x_col, y_col = encode_window_xy_columns(xs, ys, lo_x, hi_x, lo_y, hi_y)
    return (x_col.meta, y_col.meta, x_col.values, y_col.values)


def grid_shape(
    w: int, h: int, visible: int, target_per_cell: float = DENSITY_TARGET_POINTS_PER_CELL
) -> tuple[int, int]:
    """Keep aggregation grids screen-bounded, but avoid one-pixel bins when
    the visible count is only barely over the direct budget. A few points per
    cell gives smoother drill-out aggregates and smaller updates."""
    w, h = screen_shape(w, h)
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
