"""Kernel dispatch: native Rust core when available, NumPy fallback otherwise.

The fallback is loud, never silent (§33: "no-wheel behavior is defined") — one
warning at import, and `BACKEND` is inspectable so tests and debug tooling can
assert which path served a figure (§28: every tier decision is observable).

Set FASTCHARTS_FORCE_FALLBACK=1 to force the NumPy path (used by parity tests).
"""

from __future__ import annotations

import os
import warnings

if os.environ.get("FASTCHARTS_FORCE_FALLBACK") == "1":
    from . import _fallback as _impl

    BACKEND = "numpy"
else:
    try:
        from . import _native as _impl  # type: ignore[no-redef]

        BACKEND = "native"
    except ImportError as err:
        from . import _fallback as _impl  # type: ignore[no-redef]

        BACKEND = "numpy"
        warnings.warn(
            f"fastcharts: native core unavailable ({err}); using the NumPy "
            "fallback. Interaction stays correct but ingest/decimation is "
            "slower — install a platform wheel or `cargo build --release`.",
            RuntimeWarning,
            stacklevel=2,
        )

zone_maps = _impl.zone_maps
encode_f32 = _impl.encode_f32
m4_indices = _impl.m4_indices
min_max = _impl.min_max
bin_2d = _impl.bin_2d


def ohlc_decimate(x, o, h, low, c, x0, x1, px):  # noqa: ANN001, ANN201
    """OHLC-bucket decimation: the candlestick analog of M4 (§5/§28).

    Buckets the finite candles in [x0, x1] into `px` pixel columns and
    synthesizes one candle per occupied bucket — open=first, high=max, low=min,
    close=last — preserving the candle's meaning while keeping the shipped set
    screen-bounded. Returns (x, open, high, low, close) f64 arrays, length ≤ px.

    Backend-independent NumPy (candles are x-sorted at ingest, so buckets are
    contiguous and reduceat is exact); a native kernel can replace this on the
    hot path later, like bin_2d did for density.
    """
    import numpy as np

    x = np.ascontiguousarray(x, dtype=np.float64)
    o = np.ascontiguousarray(o, dtype=np.float64)
    h = np.ascontiguousarray(h, dtype=np.float64)
    low = np.ascontiguousarray(low, dtype=np.float64)
    c = np.ascontiguousarray(c, dtype=np.float64)
    px = max(1, int(px))
    span = x1 - x0
    if not (span > 0):
        return (np.empty(0),) * 5
    m = np.isfinite(x) & np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c)
    m &= (x >= x0) & (x <= x1)
    xs, os_, hs, ls, cs = x[m], o[m], h[m], low[m], c[m]
    if len(xs) == 0:
        return (np.empty(0),) * 5
    col = np.clip(((xs - x0) / span * px).astype(np.int64), 0, px - 1)
    # xs is sorted → col is non-decreasing → buckets are contiguous segments.
    _, first = np.unique(col, return_index=True)
    return (
        xs[first],  # representative x = first candle's open time in the bucket
        os_[first],  # open = first
        np.maximum.reduceat(hs, first),  # high = max over the segment
        np.minimum.reduceat(ls, first),  # low = min
        cs[np.r_[first[1:] - 1, len(cs) - 1]],  # close = last
    )


__all__ = [
    "BACKEND",
    "bin_2d",
    "encode_f32",
    "m4_indices",
    "min_max",
    "ohlc_decimate",
    "zone_maps",
]
