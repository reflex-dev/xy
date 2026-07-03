"""Pure-NumPy fallback kernels — the defined no-wheel behavior (§33).

Semantically identical to the native core (asserted by the parity tests);
slower, and it says so once at import time via `fastcharts.kernels`.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import numpy.typing as npt


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
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    data = np.ascontiguousarray(data, dtype=np.float64)
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
            sums[i] = valid.sum()
            sum_sqs[i] = (valid * valid).sum()
        else:
            mins[i] = np.inf
            maxs[i] = -np.inf
            sums[i] = 0.0
            sum_sqs[i] = 0.0
    return mins, maxs, counts, nulls, sums, sum_sqs


def encode_f32(
    data: npt.NDArray[np.float64], offset: float, scale: float = 1.0
) -> npt.NDArray[np.float32]:
    data = np.ascontiguousarray(data, dtype=np.float64)
    return ((data - offset) * scale).astype(np.float32)


def m4_indices(
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    x0: float,
    x1: float,
    n_buckets: int,
) -> npt.NDArray[np.uint32]:
    if n_buckets <= 0:
        raise ValueError("n_buckets must be > 0")
    if not x1 > x0:
        raise ValueError("x1 must be > x0")
    x = np.ascontiguousarray(x, dtype=np.float64)
    y = np.ascontiguousarray(y, dtype=np.float64)
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
    out: list[np.uint32] = []
    for s, e in zip(starts, ends):
        seg = yv[s:e]
        picks = np.unique(
            np.array(
                [idx[s], idx[s + int(np.argmin(seg))], idx[s + int(np.argmax(seg))], idx[e - 1]],
                dtype=np.uint32,
            )
        )
        out.extend(picks)
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
    if not (w > 0 and h > 0 and x1 > x0 and y1 > y0):
        raise ValueError("require w>0, h>0, x1>x0, y1>y0")
    x = np.ascontiguousarray(x, dtype=np.float64)
    y = np.ascontiguousarray(y, dtype=np.float64)
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
    data = np.ascontiguousarray(data, dtype=np.float64)
    valid = data[np.isfinite(data)]  # NaN and ±inf excluded (§19)
    if len(valid) == 0:
        return None
    return float(valid.min()), float(valid.max())
