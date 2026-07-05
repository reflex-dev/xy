"""Pure-NumPy fallback kernels — the defined no-wheel behavior (§33).

Semantically identical to the native core (asserted by the parity tests);
slower, and it says so once at import time via `fastcharts.kernels`.
"""

from __future__ import annotations

import operator
from typing import Optional

import numpy as np
import numpy.typing as npt

from .config import MAX_SCREEN_DIM


def _as_f64(arr: npt.NDArray[np.float64], label: str = "data") -> npt.NDArray[np.float64]:
    out = np.ascontiguousarray(arr, dtype=np.float64)
    if out.ndim != 1:
        raise ValueError(f"{label} must be 1-D, got shape {out.shape}")
    return out


def _positive_int(value: int, label: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a positive integer")
    try:
        out = operator.index(value)
    except TypeError as e:
        raise ValueError(f"{label} must be a positive integer") from e
    if out <= 0:
        raise ValueError(f"{label} must be > 0")
    return int(out)


def _bounded_positive_int(value: int, label: str, max_value: int = MAX_SCREEN_DIM) -> int:
    out = _positive_int(value, label)
    if out > max_value:
        raise ValueError(f"{label} must be <= {max_value}")
    return out


def _finite_float(value: float, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite real number")
    out = float(value)
    if not np.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def _finite_increasing(lo: float, hi: float, label: str) -> tuple[float, float]:
    lo_f = _finite_float(lo, label)
    hi_f = _finite_float(hi, label)
    if not hi_f > lo_f:
        raise ValueError(f"{label} must be finite and increasing")
    return lo_f, hi_f


def _finite_ordered(lo: float, hi: float, label: str) -> tuple[float, float]:
    lo_f = _finite_float(lo, label)
    hi_f = _finite_float(hi, label)
    if hi_f < lo_f:
        raise ValueError(f"{label} must be finite and ordered low-to-high")
    return lo_f, hi_f


def zone_maps(
    data: npt.NDArray[np.float64], chunk_size: int = 65_536
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.uint64],
    npt.NDArray[np.uint64],
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
]:
    chunk_size = _positive_int(chunk_size, "chunk_size")
    data = _as_f64(data, "data")
    n = len(data)
    if n == 0:
        empty_f = np.empty(0, dtype=np.float64)
        empty_u = np.empty(0, dtype=np.uint64)
        return empty_f, empty_f, empty_u, empty_u, empty_f.copy(), empty_f.copy()
    n_chunks = -(-n // chunk_size)
    mins = np.empty(n_chunks, dtype=np.float64)
    maxs = np.empty(n_chunks, dtype=np.float64)
    counts = np.empty(n_chunks, dtype=np.uint64)
    nulls = np.empty(n_chunks, dtype=np.uint64)
    sums = np.empty(n_chunks, dtype=np.float64)
    sum_sqs = np.empty(n_chunks, dtype=np.float64)
    for i in range(n_chunks):
        chunk = data[i * chunk_size : (i + 1) * chunk_size]
        valid = chunk[np.isfinite(chunk)]  # NaN and ±inf are null (§19)
        counts[i] = len(valid)
        nulls[i] = len(chunk) - len(valid)
        if len(valid):
            mins[i] = valid.min()
            maxs[i] = valid.max()
            with np.errstate(over="ignore"):
                sums[i] = valid.sum()
                sum_sqs[i] = np.square(valid).sum()
        else:
            mins[i] = np.inf
            maxs[i] = -np.inf
            sums[i] = 0.0
            sum_sqs[i] = 0.0
    return mins, maxs, counts, nulls, sums, sum_sqs


def encode_f32(
    data: npt.NDArray[np.float64], offset: float, scale: float = 1.0
) -> npt.NDArray[np.float32]:
    data = _as_f64(data, "data")
    offset = _finite_float(offset, "offset")
    scale = _finite_float(scale, "scale")
    return ((data - offset) * scale).astype(np.float32)


def m4_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    n_buckets: int,
) -> npt.NDArray[np.uint32]:
    n_buckets = _bounded_positive_int(n_buckets, "n_buckets")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    if len(x) == 0:
        return np.empty(0, dtype=np.uint32)

    start = int(np.searchsorted(x, x0, side="left"))
    end = int(np.searchsorted(x, x1, side="left"))
    if start >= end:
        return np.empty(0, dtype=np.uint32)

    idx = np.arange(start, end, dtype=np.uint32)
    xv = x[start:end]
    yv = y[start:end]
    valid = np.isfinite(yv)  # NaN and ±inf are non-plottable (§19)
    idx, xv, yv = idx[valid], xv[valid], yv[valid]
    if len(idx) == 0:
        return np.empty(0, dtype=np.uint32)

    buckets = np.minimum(((xv - x0) * (n_buckets / (x1 - x0))).astype(np.int64), n_buckets - 1)
    # x is sorted, so bucket ids are non-decreasing: group boundaries suffice.
    starts = np.unique(buckets, return_index=True)[1]
    ends = np.append(starts[1:], len(buckets))
    out: list[int] = []
    for s, e in zip(starts, ends, strict=True):
        seg = yv[s:e]
        picks = (
            int(idx[s]),
            int(idx[s + int(np.argmin(seg))]),
            int(idx[s + int(np.argmax(seg))]),
            int(idx[e - 1]),
        )
        prev = -1
        for pick in sorted(picks):
            if pick != prev:
                out.append(pick)
                prev = pick
    return np.array(out, dtype=np.uint32)


def bin_2d(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    w: int,
    h: int,
) -> npt.NDArray[np.float32]:
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    x0, x1 = _finite_increasing(x0, x1, "x range")
    y0, y1 = _finite_increasing(y0, y1, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    valid = np.isfinite(x) & np.isfinite(y)  # NaN and ±inf excluded (§19)
    valid &= (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
    xv, yv = x[valid], y[valid]
    cx = np.minimum(((xv - x0) * (w / (x1 - x0))).astype(np.int64), w - 1)
    cy = np.minimum(((yv - y0) * (h / (y1 - y0))).astype(np.int64), h - 1)
    # bincount is the fast, exact equivalent of the Rust additive loop.
    flat = np.bincount(cy * w + cx, minlength=w * h).astype(np.float32)
    return flat.reshape(h, w)


def min_max(data: npt.NDArray[np.float64]) -> Optional[tuple[float, float]]:
    data = _as_f64(data, "data")
    valid = data[np.isfinite(data)]  # NaN and ±inf excluded (§19)
    if len(valid) == 0:
        return None
    return float(valid.min()), float(valid.max())


def histogram_uniform(
    data: npt.NDArray[np.float64],
    lo: float,
    hi: float,
    n_bins: int,
    *,
    density: bool = False,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    n_bins = _bounded_positive_int(n_bins, "n_bins")
    lo, hi = _finite_increasing(lo, hi, "histogram range")
    data = _as_f64(data, "data")
    counts = np.zeros(n_bins, dtype=np.float64)
    valid = np.isfinite(data) & (data >= lo) & (data <= hi)
    if np.any(valid):
        scaled = ((data[valid] - lo) * (n_bins / (hi - lo))).astype(np.int64)
        scaled = np.minimum(scaled, n_bins - 1)
        counts += np.bincount(scaled, minlength=n_bins)
        if density:
            total = counts.sum()
            if total > 0:
                counts /= total * ((hi - lo) / n_bins)
    edges = np.linspace(lo, hi, n_bins + 1, dtype=np.float64)
    return counts, edges


def normalize_f32(
    data: npt.NDArray[np.float64],
    domain: tuple[float, float],
    *,
    nonfinite: str = "zero",
) -> npt.NDArray[np.float32]:
    if nonfinite not in {"zero", "nan"}:
        raise ValueError("nonfinite must be 'zero' or 'nan'")
    data = _as_f64(data, "data")
    try:
        lo_raw, hi_raw = domain
    except (TypeError, ValueError) as e:
        raise ValueError("domain must contain exactly two finite increasing values") from e
    lo, hi = _finite_increasing(lo_raw, hi_raw, "domain")
    span = hi - lo if hi > lo else 1.0
    out = ((data - lo) / span).clip(0.0, 1.0).astype(np.float32)
    bad = ~np.isfinite(data)
    if np.any(bad):
        out[bad] = np.nan if nonfinite == "nan" else 0.0
    return out


def range_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
) -> npt.NDArray[np.uint32]:
    lo_x, hi_x = _finite_ordered(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_ordered(lo_y, hi_y, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    mask = (x >= lo_x) & (x <= hi_x) & (y >= lo_y) & (y <= hi_y)
    return np.flatnonzero(mask).astype(np.uint32)


def local_log_density(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    lo_x: float,
    hi_x: float,
    lo_y: float,
    hi_y: float,
    w: int,
    h: int,
) -> npt.NDArray[np.float32]:
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    lo_x, hi_x = _finite_increasing(lo_x, hi_x, "x range")
    lo_y, hi_y = _finite_increasing(lo_y, hi_y, "y range")
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    if len(x) != len(y):
        raise ValueError("x and y must have equal length")
    out = np.zeros(len(x), dtype=np.float32)
    if len(x):
        grid = bin_2d(x, y, lo_x, hi_x, lo_y, hi_y, w, h)
        gmax = float(grid.max()) if grid.size else 0.0
        if gmax > 0:
            inside = (
                np.isfinite(x)
                & np.isfinite(y)
                & (x >= lo_x)
                & (x < hi_x)
                & (y >= lo_y)
                & (y < hi_y)
            )
            if np.any(inside):
                ix = np.clip(((x[inside] - lo_x) * (w / (hi_x - lo_x))).astype(np.int64), 0, w - 1)
                iy = np.clip(((y[inside] - lo_y) * (h / (hi_y - lo_y))).astype(np.int64), 0, h - 1)
                out[inside] = (np.log1p(grid[iy, ix]) / np.log1p(gmax)).astype(np.float32)
    return out


# -- tile pyramid (§5 Tier 3) — parity with tiles.rs ---------------------------

_PYRAMIDS: dict = {}
_PYR_NEXT = [0]


def _pyr_crange(lo, hi, flo, fhi, dim):
    cell = (fhi - flo) / dim
    first = max(0, int(np.ceil((lo - flo) / cell - 0.5)))
    last = max(0, int(np.floor((hi - flo) / cell - 0.5)) + 1)
    return min(first, dim), min(last, dim)


def pyramid_build(x, y, x0, x1, y0, y1, base_dim):
    x = _as_f64(x, "x")
    y = _as_f64(y, "y")
    base_dim = int(base_dim)
    if (
        len(x) != len(y)
        or len(x) == 0
        or base_dim < 2
        or base_dim & (base_dim - 1)
        or not np.all(np.isfinite([x0, x1, y0, y1]))
        or not (x1 > x0 and y1 > y0)
    ):
        return 0
    grid = np.asarray(bin_2d(x, y, x0, x1, y0, y1, base_dim, base_dim))
    levels = [grid.reshape(base_dim, base_dim).astype(np.uint64)]
    while levels[-1].shape[0] > 1:
        g = levels[-1]
        d = g.shape[0] // 2
        levels.append(g.reshape(d, 2, d, 2).sum(axis=(1, 3)))
    _PYR_NEXT[0] += 1
    handle = _PYR_NEXT[0]
    _PYRAMIDS[handle] = {"levels": levels, "bounds": (x0, x1, y0, y1)}
    return handle


def pyramid_count(handle, lo_x, hi_x, lo_y, hi_y):
    p = _PYRAMIDS.get(handle)
    if p is None or not (hi_x > lo_x and hi_y > lo_y):
        return None
    x0, x1, y0, y1 = p["bounds"]
    lvl = p["levels"][0]
    dim = lvl.shape[0]
    cx0, cx1 = _pyr_crange(lo_x, hi_x, x0, x1, dim)
    cy0, cy1 = _pyr_crange(lo_y, hi_y, y0, y1, dim)
    return float(lvl[cy0:cy1, cx0:cx1].sum())


def pyramid_compose(handle, lo_x, hi_x, lo_y, hi_y, w, h):
    p = _PYRAMIDS.get(handle)
    w = _bounded_positive_int(w, "w")
    h = _bounded_positive_int(h, "h")
    if p is None or not (hi_x > lo_x and hi_y > lo_y):
        return None
    x0, x1, y0, y1 = p["bounds"]
    levels = p["levels"]
    chosen = None
    for level in range(len(levels) - 1, -1, -1):
        dim = levels[level].shape[0]
        cx0, cx1 = _pyr_crange(lo_x, hi_x, x0, x1, dim)
        cy0, cy1 = _pyr_crange(lo_y, hi_y, y0, y1, dim)
        if cx1 - cx0 >= w and cy1 - cy0 >= h:
            chosen = level
            break
    if chosen is None:
        dim = levels[0].shape[0]
        cx0, cx1 = _pyr_crange(lo_x, hi_x, x0, x1, dim)
        cy0, cy1 = _pyr_crange(lo_y, hi_y, y0, y1, dim)
        if (cx1 - cx0) * 2 >= w and (cy1 - cy0) * 2 >= h:
            chosen = 0
        else:
            return None
    lvl = levels[chosen]
    dim = lvl.shape[0]
    cx0, cx1 = _pyr_crange(lo_x, hi_x, x0, x1, dim)
    cy0, cy1 = _pyr_crange(lo_y, hi_y, y0, y1, dim)
    sub = lvl[cy0:cy1, cx0:cx1]
    cell_x = (x1 - x0) / dim
    cell_y = (y1 - y0) / dim
    xc = x0 + (np.arange(cx0, cx1) + 0.5) * cell_x
    yc = y0 + (np.arange(cy0, cy1) + 0.5) * cell_y
    ox = np.minimum(((xc - lo_x) * (w / (hi_x - lo_x))).astype(np.int64), w - 1)
    oy = np.minimum(((yc - lo_y) * (h / (hi_y - lo_y))).astype(np.int64), h - 1)
    out = np.zeros((h, w), dtype=np.float64)
    np.add.at(out, (oy[:, None], ox[None, :]), sub)
    return out.astype(np.float32).ravel(), int(chosen)


def pyramid_free(handle) -> bool:
    return _PYRAMIDS.pop(handle, None) is not None
