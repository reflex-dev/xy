"""Finance overlay/study/drawing API foundation.

This module deliberately does not teach `candlestick()` about every trading
tool. Candles stay a fast OHLC mark; finance-specific behavior is modeled as
small, serializable layers that can be composed over the same axes. The WebGL
editor/renderer can consume this layer spec later without changing the mark
payload contract.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from . import export
from .components import Axis, Chart, Component, Legend, Mark, _resolve, x_axis, y_axis


def _jsonable(value: Any) -> Any:
    """Return a stable JSON-shaped value without importing heavy serializers."""
    if hasattr(value, "to_spec") and callable(value.to_spec):
        return value.to_spec()
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return [_jsonable(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        return _jsonable(value.item())
    return value


def _anchor(value: Any) -> dict[str, Any]:
    """Normalize common finance anchor shorthands to data/bar/price coords.

    - `(x, y)` -> exact data coordinate
    - `{"x": ..., "y": ...}` -> passed through
    - number -> price-only anchor
    - anything else -> x-only anchor
    """
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return _jsonable(value)
    if isinstance(value, tuple):
        if len(value) == 2:
            return {"x": _jsonable(value[0]), "y": _jsonable(value[1])}
        if len(value) == 3:
            return {"x": _jsonable(value[0]), "y": _jsonable(value[1]), "bar": _jsonable(value[2])}
        raise ValueError("anchor tuples must be (x, y) or (x, y, bar)")
    if isinstance(value, (int, float)):
        return {"y": float(value)}
    return {"x": _jsonable(value)}


def _bar_anchor(value: Any) -> dict[str, Any]:
    if isinstance(value, int) and not isinstance(value, bool):
        return {"bar": int(value)}
    return _anchor(value)


def _axis_values(x: Any) -> np.ndarray:
    arr = np.asarray(x)
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[ms]").astype(np.float64)
    return arr.astype(np.float64)


def _anchor_x_value(value: Any, x_values: np.ndarray) -> Optional[float]:
    anchor = _anchor(value)
    if "bar" in anchor:
        return None
    raw = anchor.get("x")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # Date-like anchors follow the x-axis dtype convention: milliseconds
        # since epoch for datetime64 series.
        try:
            return float(np.datetime64(raw, "ms").astype("int64"))
        except (TypeError, ValueError):
            return None


def _anchor_index(x: Any, anchor: Any, n: int) -> int:
    spec = _anchor(anchor)
    if "bar" in spec:
        idx = int(spec["bar"])
    else:
        xv = _axis_values(x)
        ax = _anchor_x_value(anchor, xv)
        idx = 0 if ax is None else int(np.searchsorted(xv, ax, side="left"))
    return min(max(idx, 0), max(n - 1, 0))


def _anchor_slice_index(x: Any, anchor: Any, n: int, *, default: int, side: str) -> int:
    spec = _anchor(anchor)
    if "bar" in spec:
        idx = int(spec["bar"]) + (1 if side == "right" else 0)
    else:
        xv = _axis_values(x)
        ax = _anchor_x_value(anchor, xv)
        idx = default if ax is None else int(np.searchsorted(xv, ax, side=side))  # ty: ignore[no-matching-overload]
    return min(max(idx, 0), n)


def _price_source(
    price: str,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> np.ndarray:
    if price in {"hlc3", "typical"}:
        return (high + low + close) / 3.0
    if price == "close":
        return close
    if price == "ohlc4":
        return (open_ + high + low + close) / 4.0
    if price == "open":
        return open_
    if price == "high":
        return high
    if price == "low":
        return low
    raise ValueError(
        "price must be one of 'hlc3', 'typical', 'close', 'ohlc4', 'open', 'high', 'low'"
    )


def _anchored_vwap_arrays(
    x: Any,
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    *,
    anchor: Any,
    price: str = "hlc3",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    arrays = [np.asarray(v) for v in (x, open_, high, low, close, volume)]
    n = len(arrays[0])
    if any(len(a) != n for a in arrays):
        raise ValueError("anchored VWAP x/open/high/low/close/volume must have equal length")
    if n == 0:
        return arrays[0], np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    x_arr = arrays[0]
    open_f, high_f, low_f, close_f, volume_f = [np.asarray(a, dtype=np.float64) for a in arrays[1:]]
    start = _anchor_index(x_arr, anchor, n)
    px = _price_source(price, open_f, high_f, low_f, close_f)[start:]
    vol = volume_f[start:]
    if np.any(vol < 0):
        raise ValueError("anchored VWAP volume must be non-negative")
    finite = np.isfinite(px) & np.isfinite(vol)
    weight = np.where(finite, vol, 0.0)
    cum_vol = np.cumsum(weight)
    cum_pv = np.cumsum(np.where(finite, px * vol, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = cum_pv / cum_vol
        second = np.cumsum(np.where(finite, px * px * vol, 0.0)) / cum_vol
    variance = np.maximum(second - vwap * vwap, 0.0)
    std = np.sqrt(variance)
    vwap[cum_vol <= 0] = np.nan
    std[cum_vol <= 0] = np.nan
    return x_arr[start:], vwap, std


def anchored_vwap_values(
    x: Any,
    open: Any,  # noqa: A002 - OHLC domain naming
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    *,
    anchor: Any,
    price: str = "hlc3",
) -> tuple[np.ndarray, np.ndarray]:
    """Compute anchored VWAP values from OHLCV arrays.

    Returns `(x_from_anchor, vwap)`. This is the deterministic Python-side
    reference used by the composed finance study; native acceleration can be
    added underneath without changing the API.
    """
    xs, vwap, _ = _anchored_vwap_arrays(
        x, open, high, low, close, volume, anchor=anchor, price=price
    )
    return xs, vwap


def vwap_values(
    x: Any,
    open: Any,  # noqa: A002 - OHLC domain naming
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    *,
    price: str = "hlc3",
) -> tuple[np.ndarray, np.ndarray]:
    """Compute cumulative VWAP values from the first bar."""
    xs, vwap, _ = _anchored_vwap_arrays(
        x, open, high, low, close, volume, anchor={"bar": 0}, price=price
    )
    return xs, vwap


def moving_average_values(values: Any, *, window: int = 20, method: str = "sma") -> np.ndarray:
    """Compute a simple or exponential moving average.

    SMA values are `nan` until a full window is available. EMA values start at
    the first input and use the standard `2 / (window + 1)` smoothing factor.
    """
    if window <= 0:
        raise ValueError("window must be positive")
    if method not in {"sma", "ema"}:
        raise ValueError("method must be 'sma' or 'ema'")
    values_f = np.asarray(values, dtype=np.float64)
    if values_f.ndim != 1:
        raise ValueError("values must be one-dimensional")
    out = np.full(len(values_f), np.nan, dtype=np.float64)
    finite = np.isfinite(values_f)
    if len(values_f) == 0 or not finite.any():
        return out
    if method == "sma":
        valid_values = np.where(finite, values_f, 0.0)
        valid_counts = np.cumsum(finite.astype(np.int64))
        csum = np.cumsum(valid_values)
        for i in range(window - 1, len(values_f)):
            count = valid_counts[i] - (valid_counts[i - window] if i >= window else 0)
            if count == window:
                total = csum[i] - (csum[i - window] if i >= window else 0.0)
                out[i] = total / window
        return out

    alpha = 2.0 / (window + 1.0)
    first = int(np.flatnonzero(finite)[0])
    out[first] = values_f[first]
    prev = out[first]
    for i in range(first + 1, len(values_f)):
        if not finite[i]:
            out[i] = prev
            continue
        prev = alpha * values_f[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def bollinger_bands_values(
    values: Any,
    *,
    window: int = 20,
    deviations: float = 2.0,
) -> dict[str, np.ndarray]:
    """Compute Bollinger middle/upper/lower bands using rolling population std."""
    if window <= 0:
        raise ValueError("window must be positive")
    if not math.isfinite(deviations) or deviations <= 0:
        raise ValueError("deviations must be positive")
    values_f = np.asarray(values, dtype=np.float64)
    if values_f.ndim != 1:
        raise ValueError("values must be one-dimensional")
    middle = moving_average_values(values_f, window=window, method="sma")
    std = np.full(len(values_f), np.nan, dtype=np.float64)
    finite = np.isfinite(values_f)
    for i in range(window - 1, len(values_f)):
        chunk = values_f[i - window + 1 : i + 1]
        if finite[i - window + 1 : i + 1].all():
            std[i] = float(np.std(chunk, ddof=0))
    return {
        "middle": middle,
        "upper": middle + deviations * std,
        "lower": middle - deviations * std,
        "std": std,
    }


def rsi_values(values: Any, *, window: int = 14) -> np.ndarray:
    """Compute Wilder RSI in the 0-100 range."""
    if window <= 0:
        raise ValueError("window must be positive")
    values_f = np.asarray(values, dtype=np.float64)
    if values_f.ndim != 1:
        raise ValueError("values must be one-dimensional")
    out = np.full(len(values_f), np.nan, dtype=np.float64)
    if len(values_f) <= window or not np.all(np.isfinite(values_f)):
        return out
    delta = np.diff(values_f)
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    avg_gain = float(np.mean(gain[:window]))
    avg_loss = float(np.mean(loss[:window]))

    def score(gain_value: float, loss_value: float) -> float:
        if loss_value == 0.0 and gain_value == 0.0:
            return 50.0
        if loss_value == 0.0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + gain_value / loss_value)

    out[window] = score(avg_gain, avg_loss)
    for i in range(window + 1, len(values_f)):
        avg_gain = (avg_gain * (window - 1) + gain[i - 1]) / window
        avg_loss = (avg_loss * (window - 1) + loss[i - 1]) / window
        out[i] = score(avg_gain, avg_loss)
    return out


def macd_values(
    values: Any,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, np.ndarray]:
    """Compute MACD line, signal line, and histogram."""
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast, slow, and signal must be positive")
    if fast >= slow:
        raise ValueError("fast must be less than slow")
    values_f = np.asarray(values, dtype=np.float64)
    if values_f.ndim != 1:
        raise ValueError("values must be one-dimensional")
    fast_ema = moving_average_values(values_f, window=fast, method="ema")
    slow_ema = moving_average_values(values_f, window=slow, method="ema")
    macd = fast_ema - slow_ema
    signal_line = moving_average_values(macd, window=signal, method="ema")
    return {"macd": macd, "signal": signal_line, "histogram": macd - signal_line}


def stochastic_values(
    high: Any,
    low: Any,
    close: Any,
    *,
    k_window: int = 14,
    d_window: int = 3,
) -> dict[str, np.ndarray]:
    """Compute stochastic oscillator %K and %D in the 0-100 range."""
    if k_window <= 0 or d_window <= 0:
        raise ValueError("k_window and d_window must be positive")
    high_f = np.asarray(high, dtype=np.float64)
    low_f = np.asarray(low, dtype=np.float64)
    close_f = np.asarray(close, dtype=np.float64)
    if high_f.ndim != 1 or low_f.ndim != 1 or close_f.ndim != 1:
        raise ValueError("high/low/close must be one-dimensional")
    n = len(high_f)
    if len(low_f) != n or len(close_f) != n:
        raise ValueError("high/low/close must have equal length")
    k = np.full(n, np.nan, dtype=np.float64)
    finite = np.isfinite(high_f) & np.isfinite(low_f) & np.isfinite(close_f)
    for i in range(k_window - 1, n):
        window_slice = slice(i - k_window + 1, i + 1)
        if not finite[window_slice].all():
            continue
        highest = float(np.max(high_f[window_slice]))
        lowest = float(np.min(low_f[window_slice]))
        if highest == lowest:
            k[i] = 50.0
        else:
            k[i] = (close_f[i] - lowest) / (highest - lowest) * 100.0
    d = moving_average_values(k, window=d_window, method="sma")
    return {"k": k, "d": d}


def _value_area_mask(total: np.ndarray, value_area: float) -> tuple[np.ndarray, int, float, float]:
    mask = np.zeros(len(total), dtype=bool)
    if len(total) == 0 or float(np.sum(total)) <= 0:
        return mask, -1, math.nan, math.nan
    poc = int(np.argmax(total))
    target = float(np.sum(total)) * value_area
    lo = hi = poc
    acc = float(total[poc])
    mask[poc] = True
    while acc < target and (lo > 0 or hi < len(total) - 1):
        left = float(total[lo - 1]) if lo > 0 else -1.0
        right = float(total[hi + 1]) if hi < len(total) - 1 else -1.0
        if right > left:
            hi += 1
            acc += float(total[hi])
            mask[hi] = True
        else:
            lo -= 1
            acc += float(total[lo])
            mask[lo] = True
    return mask, poc, acc, target


def _volume_profile_arrays(
    x: Any,
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    *,
    start: Any = None,
    end: Any = None,
    anchor: Any = None,
    rows: int = 100,
    row_size: Optional[float] = None,
    value_area: float = 0.70,
) -> dict[str, Any]:
    arrays = [np.asarray(v) for v in (x, open_, high, low, close, volume)]
    n = len(arrays[0])
    if any(len(a) != n for a in arrays):
        raise ValueError("volume profile x/open/high/low/close/volume must have equal length")
    if rows <= 0:
        raise ValueError("rows must be positive")
    if row_size is not None and row_size <= 0:
        raise ValueError("row_size must be positive")
    if not math.isfinite(value_area) or not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    if n == 0:
        empty = np.asarray([], dtype=np.float64)
        return {
            "price_low": empty,
            "price_high": empty,
            "price_mid": empty,
            "total": empty,
            "up": empty,
            "down": empty,
            "delta": empty,
            "value_area": np.asarray([], dtype=bool),
            "poc_index": -1,
            "value_area_low": math.nan,
            "value_area_high": math.nan,
            "max_total": 0.0,
            "start_index": 0,
            "end_index": 0,
            "rows": 0,
        }

    x_arr = arrays[0]
    x_axis = _axis_values(x_arr)
    order = None if np.all(np.diff(x_axis) >= 0) else np.argsort(x_axis, kind="stable")
    if order is not None:
        arrays = [a[order] for a in arrays]
        x_arr = arrays[0]
        x_axis = x_axis[order]
    open_f, high_f, low_f, close_f, volume_f = [np.asarray(a, dtype=np.float64) for a in arrays[1:]]
    if np.any(volume_f < 0):
        raise ValueError("volume profile volume must be non-negative")

    if anchor is not None:
        i0 = _anchor_slice_index(x_arr, anchor, n, default=0, side="left")
        i1 = n
    else:
        i0 = _anchor_slice_index(x_arr, start, n, default=0, side="left")
        i1 = _anchor_slice_index(x_arr, end, n, default=n, side="right")
    if i1 < i0:
        i0, i1 = i1, i0

    finite_window = (
        np.isfinite(open_f[i0:i1])
        & np.isfinite(high_f[i0:i1])
        & np.isfinite(low_f[i0:i1])
        & np.isfinite(close_f[i0:i1])
        & np.isfinite(volume_f[i0:i1])
    )
    if i1 <= i0 or not finite_window.any():
        low_edge = high_edge = 0.0
    else:
        lows = np.minimum(low_f[i0:i1][finite_window], high_f[i0:i1][finite_window])
        highs = np.maximum(low_f[i0:i1][finite_window], high_f[i0:i1][finite_window])
        low_edge = float(np.min(lows))
        high_edge = float(np.max(highs))
    if not math.isfinite(low_edge) or not math.isfinite(high_edge):
        low_edge, high_edge = 0.0, 1.0
    if low_edge == high_edge:
        pad = abs(low_edge) * 0.005 or 0.5
        low_edge -= pad
        high_edge += pad

    if row_size is not None:
        row_count = max(1, int(math.ceil((high_edge - low_edge) / row_size)))
        edges = low_edge + np.arange(row_count + 1, dtype=np.float64) * row_size
        edges[-1] = max(edges[-1], high_edge)
    else:
        row_count = int(rows)
        edges = np.linspace(low_edge, high_edge, row_count + 1, dtype=np.float64)

    total = np.zeros(row_count, dtype=np.float64)
    up = np.zeros(row_count, dtype=np.float64)
    down = np.zeros(row_count, dtype=np.float64)
    for o, h, lo, c, vol in zip(  # noqa: B905 - equal-length slices
        open_f[i0:i1], high_f[i0:i1], low_f[i0:i1], close_f[i0:i1], volume_f[i0:i1]
    ):
        if not all(math.isfinite(v) for v in (o, h, lo, c, vol)) or vol <= 0:
            continue
        bar_low = min(lo, h)
        bar_high = max(lo, h)
        if bar_low == bar_high:
            idx = int(np.searchsorted(edges, bar_low, side="right") - 1)
            idx = min(max(idx, 0), row_count - 1)
            share = vol
            total[idx] += share
            if c > o:
                up[idx] += share
            else:
                down[idx] += share
            continue
        first = int(np.searchsorted(edges, bar_low, side="right") - 1)
        last = int(np.searchsorted(edges, bar_high, side="left"))
        first = min(max(first, 0), row_count - 1)
        last = min(max(last, 0), row_count - 1)
        span = bar_high - bar_low
        for idx in range(first, last + 1):
            overlap = max(0.0, min(bar_high, edges[idx + 1]) - max(bar_low, edges[idx]))
            if overlap <= 0:
                continue
            share = vol * overlap / span
            total[idx] += share
            if c > o:
                up[idx] += share
            else:
                down[idx] += share

    mask, poc, _, _ = _value_area_mask(total, value_area)
    price_low = edges[:-1]
    price_high = edges[1:]
    price_mid = (price_low + price_high) / 2.0
    va_prices = np.flatnonzero(mask)
    value_area_low = float(price_low[va_prices[0]]) if len(va_prices) else math.nan
    value_area_high = float(price_high[va_prices[-1]]) if len(va_prices) else math.nan
    return {
        "price_low": price_low,
        "price_high": price_high,
        "price_mid": price_mid,
        "total": total,
        "up": up,
        "down": down,
        "delta": up - down,
        "value_area": mask,
        "poc_index": poc,
        "value_area_low": value_area_low,
        "value_area_high": value_area_high,
        "max_total": float(np.max(total)) if len(total) else 0.0,
        "start_index": int(i0),
        "end_index": int(i1),
        "rows": int(row_count),
    }


def _bars_pattern_arrays(
    x: Any,
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
    *,
    start: Any,
    end: Any,
    destination: Any,
    mirrored: bool = False,
    flipped: bool = False,
    normalize: bool = False,
    max_bars: Optional[int] = 240,
) -> dict[str, Any]:
    arrays = [np.asarray(v) for v in (x, open_, high, low, close)]
    n = len(arrays[0])
    if any(len(a) != n for a in arrays):
        raise ValueError("bars pattern x/open/high/low/close must have equal length")
    if max_bars is not None and max_bars <= 0:
        raise ValueError("max_bars must be positive")
    if n == 0:
        empty = np.asarray([], dtype=np.float64)
        return {
            "x": empty,
            "open": empty,
            "high": empty,
            "low": empty,
            "close": empty,
            "source_start_index": 0,
            "source_end_index": 0,
            "rows": 0,
        }

    x_arr = arrays[0]
    x_axis = _axis_values(x_arr)
    order = None if np.all(np.diff(x_axis) >= 0) else np.argsort(x_axis, kind="stable")
    if order is not None:
        arrays = [a[order] for a in arrays]
        x_arr = arrays[0]
        x_axis = x_axis[order]
    open_f, high_f, low_f, close_f = [np.asarray(a, dtype=np.float64) for a in arrays[1:]]
    i0 = _anchor_slice_index(x_arr, start, n, default=0, side="left")
    i1 = _anchor_slice_index(x_arr, end, n, default=n, side="right")
    if i1 < i0:
        i0, i1 = i1, i0
    finite = (
        np.isfinite(x_axis[i0:i1])
        & np.isfinite(open_f[i0:i1])
        & np.isfinite(high_f[i0:i1])
        & np.isfinite(low_f[i0:i1])
        & np.isfinite(close_f[i0:i1])
    )
    rel_idx = np.flatnonzero(finite)
    if len(rel_idx) == 0:
        empty = np.asarray([], dtype=np.float64)
        return {
            "x": empty,
            "open": empty,
            "high": empty,
            "low": empty,
            "close": empty,
            "source_start_index": int(i0),
            "source_end_index": int(i1),
            "rows": 0,
        }
    idx = rel_idx + i0
    if max_bars is not None and len(idx) > max_bars:
        keep = np.unique(np.linspace(0, len(idx) - 1, int(max_bars)).round().astype(int))
        idx = idx[keep]
    if mirrored:
        idx = idx[::-1]

    raw_x = x_axis[idx]
    raw_o = open_f[idx]
    raw_h = high_f[idx]
    raw_l = low_f[idx]
    raw_c = close_f[idx]

    dest = _anchor(destination)
    dest_x = _anchor_x_value(dest, raw_x)
    if dest_x is None:
        step = float(np.nanmedian(np.diff(x_axis))) if n > 1 else 1.0
        if not math.isfinite(step) or step == 0:
            step = 1.0
        dest_x = float(x_axis[min(max(i1 - 1, 0), n - 1)] + step)
    dest_y_raw = dest.get("y")
    dest_y = float(dest_y_raw) if dest_y_raw is not None else float(raw_o[0])

    if len(raw_x) > 1:
        source_offsets = np.abs(np.diff(raw_x if not mirrored else raw_x[::-1]))
        if (
            len(source_offsets)
            and np.all(np.isfinite(source_offsets))
            and np.any(source_offsets > 0)
        ):
            offsets = np.concatenate(([0.0], np.cumsum(source_offsets)))
        else:
            offsets = np.arange(len(raw_x), dtype=np.float64)
    else:
        offsets = np.asarray([0.0], dtype=np.float64)
    out_x = float(dest_x) + offsets

    ref = float(raw_o[0])

    def transform(values: np.ndarray) -> np.ndarray:
        vals = np.asarray(values, dtype=np.float64)
        out = dest_y * (vals / ref) if normalize and ref != 0 else dest_y + (vals - ref)
        if flipped:
            out = dest_y - (out - dest_y)
        return out

    t_o = transform(raw_o)
    t_h = transform(raw_h)
    t_l = transform(raw_l)
    t_c = transform(raw_c)
    out_high = np.maximum.reduce([t_o, t_h, t_l, t_c])  # ty: ignore[no-matching-overload]
    out_low = np.minimum.reduce([t_o, t_h, t_l, t_c])  # ty: ignore[no-matching-overload]
    return {
        "x": out_x,
        "open": t_o,
        "high": out_high,
        "low": out_low,
        "close": t_c,
        "source_start_index": int(i0),
        "source_end_index": int(i1),
        "rows": int(len(out_x)),
    }


def _positive_step(x_axis: np.ndarray) -> float:
    if len(x_axis) < 2:
        return 1.0
    diffs = np.diff(x_axis)
    positive = diffs[np.isfinite(diffs) & (diffs > 0)]
    if len(positive) == 0:
        return 1.0
    step = float(np.median(positive))
    return step if math.isfinite(step) and step > 0 else 1.0


def _ghost_feed_arrays(
    x: Any,
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
    *,
    anchor: Any,
    direction: str = "up",
    bars: int = 24,
    avg_hl_ticks: float = 100.0,
    variance_ticks: float = 100.0,
    tick_size: Optional[float] = None,
    seed: Optional[int] = None,
) -> dict[str, Any]:
    arrays = [np.asarray(v) for v in (x, open_, high, low, close)]
    n = len(arrays[0])
    if any(len(a) != n for a in arrays):
        raise ValueError("ghost feed x/open/high/low/close must have equal length")
    if direction not in {"up", "down", "flat"}:
        raise ValueError("direction must be 'up', 'down', or 'flat'")
    if bars <= 0:
        raise ValueError("bars must be positive")
    if avg_hl_ticks <= 0:
        raise ValueError("avg_hl_ticks must be positive")
    if variance_ticks < 0:
        raise ValueError("variance_ticks must be non-negative")
    if tick_size is not None and tick_size <= 0:
        raise ValueError("tick_size must be positive")
    if n == 0:
        empty = np.asarray([], dtype=np.float64)
        return {"x": empty, "open": empty, "high": empty, "low": empty, "close": empty, "rows": 0}

    x_arr = arrays[0]
    x_axis = _axis_values(x_arr)
    order = None if np.all(np.diff(x_axis) >= 0) else np.argsort(x_axis, kind="stable")
    if order is not None:
        arrays = [a[order] for a in arrays]
        x_arr = arrays[0]
        x_axis = x_axis[order]
    open_f, high_f, low_f, close_f = [np.asarray(a, dtype=np.float64) for a in arrays[1:]]
    finite = (
        np.isfinite(x_axis)
        & np.isfinite(open_f)
        & np.isfinite(high_f)
        & np.isfinite(low_f)
        & np.isfinite(close_f)
    )
    if not finite.any():
        empty = np.asarray([], dtype=np.float64)
        return {"x": empty, "open": empty, "high": empty, "low": empty, "close": empty, "rows": 0}

    anchor_spec = _anchor(anchor)
    anchor_x = _anchor_x_value(anchor_spec, x_axis)
    step = _positive_step(x_axis)
    if anchor_x is None:
        anchor_x = float(x_axis[np.flatnonzero(finite)[-1]] + step)
    anchor_y_raw = anchor_spec.get("y")
    anchor_y = (
        float(anchor_y_raw)
        if anchor_y_raw is not None
        else float(close_f[np.flatnonzero(finite)[-1]])
    )

    window_idx = np.flatnonzero(finite)[-120:]
    median_range = float(np.median(np.maximum(high_f[window_idx] - low_f[window_idx], 0.0)))
    if not math.isfinite(median_range) or median_range <= 0:
        median_range = abs(anchor_y) * 0.01 or 1.0
    inferred_tick = tick_size or median_range / avg_hl_ticks
    avg_hl = max(avg_hl_ticks * inferred_tick, abs(anchor_y) * 1e-6)
    variance = variance_ticks * inferred_tick
    sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
    drift = sign * max(variance * 0.18, avg_hl * 0.06)
    rng = np.random.default_rng(0 if seed is None else seed)

    xs = anchor_x + np.arange(bars, dtype=np.float64) * step
    out_o = np.empty(bars, dtype=np.float64)
    out_h = np.empty(bars, dtype=np.float64)
    out_l = np.empty(bars, dtype=np.float64)
    out_c = np.empty(bars, dtype=np.float64)
    prev_close = anchor_y
    noise_std = variance * 0.35
    for i in range(bars):
        o = prev_close
        change = drift + (float(rng.normal(0.0, noise_std)) if noise_std > 0 else 0.0)
        c = max(abs(anchor_y) * 1e-6, o + change)
        span = max(abs(c - o) * 1.35, avg_hl * float(rng.lognormal(0.0, 0.18)))
        upper = span * float(rng.uniform(0.18, 0.48))
        lower = span * float(rng.uniform(0.18, 0.48))
        out_o[i] = o
        out_c[i] = c
        out_h[i] = max(o, c) + upper
        out_l[i] = min(o, c) - lower
        prev_close = c
    return {
        "x": xs,
        "open": out_o,
        "high": out_h,
        "low": out_l,
        "close": out_c,
        "rows": int(bars),
        "tick_size": float(inferred_tick),
        "avg_hl": float(avg_hl),
        "variance": float(variance),
    }


def volume_profile_values(
    x: Any,
    open: Any,  # noqa: A002 - OHLC domain naming
    high: Any,
    low: Any,
    close: Any,
    volume: Any,
    *,
    start: Any = None,
    end: Any = None,
    anchor: Any = None,
    rows: int = 100,
    row_size: Optional[float] = None,
    value_area: float = 0.70,
) -> dict[str, Any]:
    """Compute fixed/anchored volume profile bins from OHLCV arrays.

    Bar volume is distributed across price rows by overlap with each bar's
    high-low span. Up/down volume follows the common OHLC rule: `close > open`
    is up volume; every other candle contributes down volume.
    """
    return _volume_profile_arrays(
        x,
        open,
        high,
        low,
        close,
        volume,
        start=start,
        end=end,
        anchor=anchor,
        rows=rows,
        row_size=row_size,
        value_area=value_area,
    )


def _volume_bar_arrays(x: Any, open_: Any, close: Any, volume: Any) -> dict[str, Any]:
    arrays = [np.asarray(v) for v in (x, open_, close, volume)]
    n = len(arrays[0])
    if any(len(a) != n for a in arrays):
        raise ValueError("volume bars x/open/close/volume must have equal length")
    if n == 0:
        empty = np.asarray([], dtype=np.float64)
        return {
            "x": empty,
            "volume": empty,
            "direction": np.asarray([], dtype=bool),
            "max_volume": 0.0,
            "rows": 0,
        }

    x_axis = _axis_values(arrays[0])
    order = None if np.all(np.diff(x_axis) >= 0) else np.argsort(x_axis, kind="stable")
    if order is not None:
        arrays = [a[order] for a in arrays]
        x_axis = x_axis[order]
    open_f, close_f, volume_f = [np.asarray(a, dtype=np.float64) for a in arrays[1:]]
    if np.any(volume_f < 0):
        raise ValueError("volume bars volume must be non-negative")
    finite = (
        np.isfinite(x_axis) & np.isfinite(open_f) & np.isfinite(close_f) & np.isfinite(volume_f)
    )
    x_out = x_axis[finite]
    volume_out = volume_f[finite]
    direction = close_f[finite] >= open_f[finite]
    return {
        "x": x_out,
        "volume": volume_out,
        "direction": direction,
        "max_volume": float(np.max(volume_out)) if len(volume_out) else 0.0,
        "rows": int(len(volume_out)),
    }


def _finite_range(*arrays: Any, default: tuple[float, float]) -> tuple[float, float]:
    vals = []
    for arr in arrays:
        a = np.asarray(arr, dtype=np.float64)
        finite = a[np.isfinite(a)]
        if len(finite):
            vals.append(finite)
    if not vals:
        return default
    all_vals = np.concatenate(vals)
    lo = float(np.min(all_vals))
    hi = float(np.max(all_vals))
    if lo == hi:
        pad = abs(lo) * 0.05 or 1.0
        return lo - pad, hi + pad
    pad = (hi - lo) * 0.10
    return lo - pad, hi + pad


def _prepend_x_value(x_arr: np.ndarray) -> np.ndarray:
    if len(x_arr) == 0:
        return np.asarray([0.0], dtype=np.float64)
    if np.issubdtype(x_arr.dtype, np.datetime64):
        x_ms = x_arr.astype("datetime64[ms]")
        if len(x_ms) > 1:
            diffs = np.diff(x_ms.astype("int64"))
            positive = diffs[np.isfinite(diffs) & (diffs > 0)]
            step_ms = int(np.median(positive)) if len(positive) else 86_400_000
        else:
            step_ms = 86_400_000
        return np.concatenate(([x_ms[0] - np.timedelta64(step_ms, "ms")], x_ms))
    x_float = np.asarray(x_arr, dtype=np.float64)
    step = _positive_step(x_float)
    return np.concatenate(([x_float[0] - step], x_float))


def _float_vector(values: Any, *, name: str, allow_empty: bool = False) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if len(arr) == 0 and not allow_empty:
        raise ValueError(f"{name} must not be empty")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def equity_curve_values(
    *,
    returns: Any = None,
    pnl: Any = None,
    initial: float = 1.0,
) -> np.ndarray:
    """Compute an equity curve from periodic returns or absolute PnL.

    The returned series includes the starting equity as the first value, so
    `n` returns or PnL observations produce `n + 1` equity points.
    """
    if (returns is None) == (pnl is None):
        raise ValueError("provide exactly one of returns or pnl")
    if not math.isfinite(initial):
        raise ValueError("initial must be finite")
    if returns is not None:
        returns_f = _float_vector(returns, name="returns", allow_empty=True)
        if np.any(returns_f < -1.0):
            raise ValueError("returns must be greater than or equal to -100%")
        equity = np.empty(len(returns_f) + 1, dtype=np.float64)
        equity[0] = initial
        equity[1:] = initial * np.cumprod(1.0 + returns_f)
        return equity

    pnl_f = _float_vector(pnl, name="pnl", allow_empty=True)
    equity = np.empty(len(pnl_f) + 1, dtype=np.float64)
    equity[0] = initial
    equity[1:] = initial + np.cumsum(pnl_f)
    return equity


def returns_values(values: Any, *, method: str = "simple") -> np.ndarray:
    """Compute period returns from a price, NAV, or equity series."""
    values_f = _float_vector(values, name="values", allow_empty=True)
    if method not in {"simple", "log"}:
        raise ValueError("method must be 'simple' or 'log'")
    if len(values_f) < 2:
        return np.asarray([], dtype=np.float64)

    prev = values_f[:-1]
    curr = values_f[1:]
    if method == "simple":
        if np.any(prev == 0):
            raise ValueError("simple returns require non-zero previous values")
        return curr / prev - 1.0

    if np.any(prev <= 0) or np.any(curr <= 0):
        raise ValueError("log returns require positive values")
    return np.log(curr / prev)


def drawdown_values(equity: Any) -> dict[str, Any]:
    """Compute drawdown arrays and max-drawdown summary from an equity curve."""
    equity_f = _float_vector(equity, name="equity")
    running_peak = np.maximum.accumulate(equity_f)
    drawdown = equity_f - running_peak
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown_pct = drawdown / running_peak
    drawdown_pct[~np.isfinite(drawdown_pct)] = np.nan

    trough_index = int(np.argmin(drawdown))
    peak_level = running_peak[trough_index]
    peak_candidates = np.flatnonzero(equity_f[: trough_index + 1] == peak_level)
    peak_index = int(peak_candidates[-1]) if len(peak_candidates) else 0
    recovered = np.flatnonzero(equity_f[trough_index + 1 :] >= peak_level)
    recovery_index = int(trough_index + 1 + recovered[0]) if len(recovered) else None
    return {
        "equity": equity_f,
        "running_peak": running_peak,
        "drawdown": drawdown,
        "drawdown_pct": drawdown_pct,
        "max_drawdown": float(drawdown[trough_index]),
        "max_drawdown_pct": float(drawdown_pct[trough_index]),
        "peak_index": peak_index,
        "trough_index": trough_index,
        "recovery_index": recovery_index,
        "drawdown_duration": int(trough_index - peak_index),
        "recovery_duration": None if recovery_index is None else int(recovery_index - trough_index),
    }


def _drawdown_range(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return -1.0, 0.0
    lo = min(0.0, float(np.min(finite)))
    hi = max(0.0, float(np.max(finite)))
    if lo == hi:
        return lo - 1.0, hi + 1.0
    pad = (hi - lo) * 0.06
    return lo - pad, hi + pad


def _performance_curve_arrays(
    *,
    x: Any = None,
    equity: Any = None,
    returns: Any = None,
    pnl: Any = None,
    initial: float = 1.0,
    drawdown: str = "percent",
) -> dict[str, Any]:
    if drawdown not in {"percent", "pct", "absolute"}:
        raise ValueError("drawdown must be 'percent', 'pct', or 'absolute'")
    if sum(v is not None for v in (equity, returns, pnl)) != 1:
        raise ValueError("provide exactly one of equity, returns, or pnl")
    if equity is None:
        equity_f = equity_curve_values(returns=returns, pnl=pnl, initial=initial)
    else:
        equity_f = _float_vector(equity, name="equity")
        initial = float(equity_f[0])

    if x is None:
        x_arr = np.arange(len(equity_f), dtype=np.float64)
    else:
        raw_x = np.asarray(x)
        if len(raw_x) == len(equity_f) - 1:
            x_arr = _prepend_x_value(raw_x)
        elif len(raw_x) == len(equity_f):
            x_arr = (
                raw_x.astype("datetime64[ms]")
                if np.issubdtype(raw_x.dtype, np.datetime64)
                else raw_x
            )
        else:
            raise ValueError("x must have length equal to equity length or returns/pnl length")

    if len(x_arr) != len(equity_f):
        raise ValueError("x and equity must have equal length after alignment")
    x_axis = _axis_values(x_arr)
    order = (
        None
        if len(x_axis) < 2 or np.all(np.diff(x_axis) >= 0)
        else np.argsort(x_axis, kind="stable")
    )
    if order is not None:
        x_arr = x_arr[order]
        equity_f = equity_f[order]

    dd = drawdown_values(equity_f)
    drawdown_abs = np.asarray(dd["drawdown"], dtype=np.float64)
    drawdown_pct = np.asarray(dd["drawdown_pct"], dtype=np.float64) * 100.0
    drawdown_y = drawdown_abs if drawdown == "absolute" else drawdown_pct
    y_min, y_max = _drawdown_range(drawdown_y)
    return {
        "x": x_arr,
        "equity": equity_f,
        "running_peak": dd["running_peak"],
        "drawdown": drawdown_abs,
        "drawdown_pct": drawdown_pct,
        "drawdown_y": drawdown_y,
        "drawdown_mode": "absolute" if drawdown == "absolute" else "percent",
        "initial": float(initial),
        "rows": int(len(equity_f)),
        "y_min": y_min,
        "y_max": y_max,
        "guides": [0.0],
        "metrics": {
            "max_drawdown": dd["max_drawdown"],
            "max_drawdown_pct": dd["max_drawdown_pct"],
            "peak_index": dd["peak_index"],
            "trough_index": dd["trough_index"],
            "recovery_index": dd["recovery_index"],
            "drawdown_duration": dd["drawdown_duration"],
            "recovery_duration": dd["recovery_duration"],
        },
    }


def _confidence_level(confidence: float) -> float:
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    return float(confidence)


def var_cvar_values(returns: Any, *, confidence: float = 0.95) -> dict[str, Any]:
    """Compute left-tail historical VaR and CVaR for a return series."""
    confidence_f = _confidence_level(confidence)
    returns_f = _float_vector(returns, name="returns")
    tail_probability = 1.0 - confidence_f
    var = float(np.quantile(returns_f, tail_probability, method="linear"))
    tail = returns_f[returns_f <= var]
    cvar = float(np.mean(tail)) if len(tail) else var
    return {
        "confidence": confidence_f,
        "tail_probability": tail_probability,
        "var": var,
        "cvar": cvar,
        "var_loss": -var,
        "cvar_loss": -cvar,
        "tail_count": int(len(tail)),
    }


def returns_distribution_values(
    returns: Any,
    *,
    bins: Any = 50,
    bin_range: Optional[tuple[float, float]] = None,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Compute a returns histogram plus VaR/CVaR marker positions."""
    returns_f = _float_vector(returns, name="returns")
    if isinstance(bins, int) and bins <= 0:
        raise ValueError("bins must be positive")
    if bin_range is not None:
        if len(bin_range) != 2:
            raise ValueError("bin_range must be a two-value tuple")
        lo, hi = float(bin_range[0]), float(bin_range[1])
        if not math.isfinite(lo) or not math.isfinite(hi) or lo >= hi:
            raise ValueError("bin_range must be finite and increasing")
        hist_range = (lo, hi)
    else:
        hist_range = None

    counts, bin_edges = np.histogram(returns_f, bins=bins, range=hist_range)
    counts_f = counts.astype(np.float64)
    total = float(np.sum(counts_f))
    probability = counts_f / total if total > 0 else counts_f
    centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0
    risk = var_cvar_values(returns_f, confidence=confidence)
    confidence_pct = risk["confidence"] * 100.0
    return {
        "counts": counts,
        "probability": probability,
        "bin_edges": bin_edges,
        "bin_centers": centers,
        "rows": int(len(counts)),
        "var": risk["var"],
        "cvar": risk["cvar"],
        "risk": risk,
        "markers": [
            {"role": "var", "label": f"VaR {confidence_pct:g}%", "x": risk["var"]},
            {"role": "cvar", "label": f"CVaR {confidence_pct:g}%", "x": risk["cvar"]},
        ],
    }


def _histogram_y_range(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    hi = float(np.max(finite)) if len(finite) else 1.0
    if hi <= 0:
        hi = 1.0
    return 0.0, hi * 1.12


@dataclass(frozen=True)
class Instrument:
    """Instrument metadata needed by risk tools and price-axis formatting."""

    tick_size: float = 0.01
    point_value: float = 1.0
    lot_size: float = 1.0
    qty_precision: int = 0
    currency: Optional[str] = None
    leverage: float = 1.0
    multiplier: float = 1.0

    def __post_init__(self) -> None:
        for name in ("tick_size", "point_value", "lot_size", "leverage", "multiplier"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.qty_precision < 0:
            raise ValueError("qty_precision must be non-negative")

    def to_spec(self) -> dict[str, Any]:
        return {
            "tick_size": self.tick_size,
            "point_value": self.point_value,
            "lot_size": self.lot_size,
            "qty_precision": self.qty_precision,
            "currency": self.currency,
            "leverage": self.leverage,
            "multiplier": self.multiplier,
        }


def instrument(
    *,
    tick_size: float = 0.01,
    point_value: float = 1.0,
    lot_size: float = 1.0,
    qty_precision: int = 0,
    currency: Optional[str] = None,
    leverage: float = 1.0,
    multiplier: float = 1.0,
) -> Instrument:
    return Instrument(
        tick_size=tick_size,
        point_value=point_value,
        lot_size=lot_size,
        qty_precision=qty_precision,
        currency=currency,
        leverage=leverage,
        multiplier=multiplier,
    )


class FinanceLayer(Component):
    role: str
    kind: str

    def to_spec(self) -> dict[str, Any]:  # pragma: no cover - interface marker
        raise NotImplementedError


@dataclass(frozen=True)
class Layer(FinanceLayer):
    role: str
    kind: str
    source: Optional[str] = None
    id: Optional[str] = None
    anchors: Mapping[str, Any] = field(default_factory=dict)
    props: Mapping[str, Any] = field(default_factory=dict)
    style: Mapping[str, Any] = field(default_factory=dict)

    def to_spec(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "kind": self.kind,
            "id": self.id,
            "source": self.source,
            "anchors": _jsonable(self.anchors),
            "props": _jsonable(self.props),
            "style": _jsonable(self.style),
        }


@dataclass(frozen=True)
class FinanceTools(Component):
    active: str = "crosshair"
    snap: str = "ohlc"
    editable: bool = True
    locked: bool = False
    hidden: tuple[str, ...] = ()
    selected: Optional[str] = None
    on_change: Optional[Callable[[dict[str, Any]], None]] = None
    on_create: Optional[Callable[[dict[str, Any]], None]] = None
    on_update: Optional[Callable[[dict[str, Any]], None]] = None
    on_delete: Optional[Callable[[dict[str, Any]], None]] = None
    on_select: Optional[Callable[[dict[str, Any]], None]] = None
    on_hover: Optional[Callable[[dict[str, Any]], None]] = None
    on_commit: Optional[Callable[[dict[str, Any]], None]] = None

    def to_spec(self) -> dict[str, Any]:
        # Callbacks are Python-side hooks; the serializable spec only declares
        # which events the client should emit.
        event_names = [
            name
            for name in ("change", "create", "update", "delete", "select", "hover", "commit")
            if getattr(self, f"on_{name}") is not None
        ]
        return {
            "active": self.active,
            "snap": self.snap,
            "editable": self.editable,
            "locked": self.locked,
            "hidden": list(self.hidden),
            "selected": self.selected,
            "events": event_names,
        }


def finance_tools(
    *,
    active: str = "crosshair",
    snap: str = "ohlc",
    editable: bool = True,
    locked: bool = False,
    hidden: tuple[str, ...] = (),
    selected: Optional[str] = None,
    on_change: Optional[Callable[[dict[str, Any]], None]] = None,
    on_create: Optional[Callable[[dict[str, Any]], None]] = None,
    on_update: Optional[Callable[[dict[str, Any]], None]] = None,
    on_delete: Optional[Callable[[dict[str, Any]], None]] = None,
    on_select: Optional[Callable[[dict[str, Any]], None]] = None,
    on_hover: Optional[Callable[[dict[str, Any]], None]] = None,
    on_commit: Optional[Callable[[dict[str, Any]], None]] = None,
) -> FinanceTools:
    return FinanceTools(
        active=active,
        snap=snap,
        editable=editable,
        locked=locked,
        hidden=hidden,
        selected=selected,
        on_change=on_change,
        on_create=on_create,
        on_update=on_update,
        on_delete=on_delete,
        on_select=on_select,
        on_hover=on_hover,
        on_commit=on_commit,
    )


def _risk_amount(account_size: float, risk: float, risk_mode: str) -> tuple[float, str]:
    if account_size <= 0:
        raise ValueError("account_size must be positive")
    if risk <= 0:
        raise ValueError("risk must be positive")
    if risk_mode == "auto":
        risk_mode = "fraction" if risk <= 1 else "amount"
    if risk_mode == "fraction":
        return account_size * risk, risk_mode
    if risk_mode == "amount":
        return risk, risk_mode
    raise ValueError("risk_mode must be 'auto', 'fraction', or 'amount'")


@dataclass(frozen=True)
class PositionDrawing(FinanceLayer):
    side: str
    source: str
    entry: Any
    stop: float
    target: float
    end: Any = None
    account_size: float = 100_000.0
    risk: float = 0.01
    risk_mode: str = "auto"
    instrument: Instrument = field(default_factory=Instrument)
    id: Optional[str] = None
    style: Mapping[str, Any] = field(default_factory=dict)
    role: str = field(default="drawing", init=False)
    kind: str = field(default="position", init=False)

    def __post_init__(self) -> None:
        if self.side not in {"long", "short"}:
            raise ValueError("side must be 'long' or 'short'")
        entry_price = self.entry_price
        if entry_price <= 0:
            raise ValueError("entry price must be positive")
        if self.stop <= 0 or self.target <= 0:
            raise ValueError("stop and target must be positive")
        if self.side == "long" and not (self.stop < entry_price < self.target):
            raise ValueError("long position requires stop < entry < target")
        if self.side == "short" and not (self.target < entry_price < self.stop):
            raise ValueError("short position requires target < entry < stop")
        _risk_amount(self.account_size, self.risk, self.risk_mode)

    @property
    def entry_price(self) -> float:
        anchor = _anchor(self.entry)
        y = anchor.get("y")
        if y is None:
            raise ValueError("entry must include a price")
        return float(y)

    def metrics(self) -> dict[str, Any]:
        entry = self.entry_price
        risk_amount, risk_mode = _risk_amount(self.account_size, self.risk, self.risk_mode)
        inst = self.instrument
        if self.side == "long":
            stop_distance = entry - self.stop
            target_distance = self.target - entry
        else:
            stop_distance = self.stop - entry
            target_distance = entry - self.target
        risk_per_lot = stop_distance * inst.point_value * inst.lot_size * inst.multiplier
        if risk_per_lot <= 0:
            raise ValueError("stop distance must be positive")
        qty_risk = risk_amount / risk_per_lot
        qty_leverage = (
            (self.account_size * inst.leverage / entry) * inst.point_value / inst.lot_size
        )
        qty = min(qty_risk, qty_leverage)
        qty_display = round(qty, inst.qty_precision)
        pnl_unit = inst.point_value * inst.lot_size * inst.multiplier
        profit_pnl = target_distance * qty * pnl_unit
        loss_pnl = -stop_distance * qty * pnl_unit
        tick = inst.tick_size
        return {
            "side": self.side,
            "entry": entry,
            "stop": self.stop,
            "target": self.target,
            "account_size": self.account_size,
            "risk_mode": risk_mode,
            "risk_amount": risk_amount,
            "qty_risk": qty_risk,
            "qty_leverage": qty_leverage,
            "qty": qty,
            "qty_display": qty_display,
            "risk_reward": target_distance / stop_distance,
            "target_offset": target_distance,
            "target_percent": target_distance / entry * 100.0,
            "target_ticks": target_distance / tick,
            "stop_offset": stop_distance,
            "stop_percent": stop_distance / entry * 100.0,
            "stop_ticks": stop_distance / tick,
            "profit_pnl": profit_pnl,
            "loss_pnl": loss_pnl,
            "target_account_balance": self.account_size + profit_pnl,
            "stop_account_balance": self.account_size + loss_pnl,
        }

    def to_spec(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "kind": self.kind,
            "id": self.id,
            "source": self.source,
            "side": self.side,
            "anchors": {
                "entry": _anchor(self.entry),
                "stop": _anchor(self.stop),
                "target": _anchor(self.target),
                "end": _anchor(self.end),
            },
            "risk": {
                "account_size": self.account_size,
                "amount": self.risk,
                "mode": self.risk_mode,
            },
            "instrument": self.instrument.to_spec(),
            "metrics": self.metrics(),
            "style": _jsonable(self.style),
        }


def long_position(
    *,
    source: str,
    entry: Any,
    stop: float,
    target: float,
    end: Any = None,
    account_size: float = 100_000.0,
    risk: float = 0.01,
    risk_mode: str = "auto",
    instrument: Optional[Instrument] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> PositionDrawing:
    return PositionDrawing(
        side="long",
        source=source,
        entry=entry,
        stop=stop,
        target=target,
        end=end,
        account_size=account_size,
        risk=risk,
        risk_mode=risk_mode,
        instrument=instrument or Instrument(),
        id=id,
        style=style or {},
    )


def short_position(
    *,
    source: str,
    entry: Any,
    stop: float,
    target: float,
    end: Any = None,
    account_size: float = 100_000.0,
    risk: float = 0.01,
    risk_mode: str = "auto",
    instrument: Optional[Instrument] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> PositionDrawing:
    return PositionDrawing(
        side="short",
        source=source,
        entry=entry,
        stop=stop,
        target=target,
        end=end,
        account_size=account_size,
        risk=risk,
        risk_mode=risk_mode,
        instrument=instrument or Instrument(),
        id=id,
        style=style or {},
    )


def _study(
    kind: str, *, source: str, id: Optional[str], anchors=None, props=None, style=None
) -> Layer:
    return Layer(
        "study",
        kind,
        source=source,
        id=id,
        anchors=anchors or {},
        props=props or {},
        style=style or {},
    )


def _drawing(
    kind: str,
    *,
    source: Optional[str] = None,
    id: Optional[str] = None,
    anchors=None,
    props=None,
    style=None,
) -> Layer:
    return Layer(
        "drawing",
        kind,
        source=source,
        id=id,
        anchors=anchors or {},
        props=props or {},
        style=style or {},
    )


def volume_bars(
    *,
    source: str,
    pane: str = "volume",
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    return _study("volume_bars", source=source, id=id, props={"pane": pane}, style=style)


def equity_drawdown(
    x: Any = None,
    *,
    equity: Any = None,
    returns: Any = None,
    pnl: Any = None,
    initial: float = 1.0,
    drawdown: str = "percent",
    pane: str = "drawdown",
    mode: str = "area",
    id: Optional[str] = None,
    name: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    """A performance curve with a synced drawdown pane.

    Provide exactly one of `equity`, `returns`, or `pnl`. The top pane renders
    the equity/PnL curve as a normal line/area trace; the layer renders the
    drawdown series in a lower synced pane.
    """
    if mode not in {"area", "line"}:
        raise ValueError("mode must be 'area' or 'line'")
    series = _performance_curve_arrays(
        x=x,
        equity=equity,
        returns=returns,
        pnl=pnl,
        initial=initial,
        drawdown=drawdown,
    )
    return _study(
        "equity_drawdown",
        source="",
        id=id,
        props={
            "pane": pane,
            "mode": mode,
            "name": name,
            "drawdown_mode": series["drawdown_mode"],
            "series": series,
        },
        style=style,
    )


def returns_distribution(
    returns: Any,
    *,
    bins: Any = 50,
    bin_range: Optional[tuple[float, float]] = None,
    confidence: float = 0.95,
    y: str = "probability",
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    """A returns histogram with VaR/CVaR marker lines."""
    if y not in {"probability", "count"}:
        raise ValueError("y must be 'probability' or 'count'")
    dist = returns_distribution_values(
        returns,
        bins=bins,
        bin_range=bin_range,
        confidence=confidence,
    )
    y_values = dist["counts"].astype(np.float64) if y == "count" else dist["probability"]
    y_min, y_max = _histogram_y_range(np.asarray(y_values, dtype=np.float64))
    series = {
        "bin_edges": dist["bin_edges"],
        "bin_centers": dist["bin_centers"],
        "counts": dist["counts"],
        "probability": dist["probability"],
        "y": y_values,
        "y_mode": y,
        "rows": dist["rows"],
        "x_min": float(dist["bin_edges"][0]),
        "x_max": float(dist["bin_edges"][-1]),
        "y_min": y_min,
        "y_max": y_max,
        "markers": dist["markers"],
        "risk": dist["risk"],
    }
    return _study(
        "returns_distribution",
        source="",
        id=id,
        props={"series": series, "confidence": confidence, "y": y},
        style=style,
    )


def moving_average(
    *,
    source: str,
    value: str = "close",
    window: int = 20,
    method: str = "sma",
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if window <= 0:
        raise ValueError("window must be positive")
    if method not in {"sma", "ema"}:
        raise ValueError("method must be 'sma' or 'ema'")
    return _study(
        "moving_average",
        source=source,
        id=id,
        props={"value": value, "window": window, "method": method},
        style=style,
    )


def bollinger_bands(
    *,
    source: str,
    value: str = "close",
    window: int = 20,
    deviations: float = 2.0,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if window <= 0:
        raise ValueError("window must be positive")
    if not math.isfinite(deviations) or deviations <= 0:
        raise ValueError("deviations must be positive")
    return _study(
        "bollinger_bands",
        source=source,
        id=id,
        props={"value": value, "window": window, "deviations": deviations},
        style=style,
    )


def vwap(
    *,
    source: str,
    price: str = "hlc3",
    bands: Optional[tuple[float, ...]] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    return _study(
        "vwap",
        source=source,
        id=id,
        props={"price": price, "bands": list(bands) if bands else []},
        style=style,
    )


def rsi(
    *,
    source: str,
    value: str = "close",
    window: int = 14,
    pane: str = "rsi",
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if window <= 0:
        raise ValueError("window must be positive")
    return _study(
        "rsi",
        source=source,
        id=id,
        props={"value": value, "window": window, "pane": pane},
        style=style,
    )


def macd(
    *,
    source: str,
    value: str = "close",
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    pane: str = "macd",
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast, slow, and signal must be positive")
    if fast >= slow:
        raise ValueError("fast must be less than slow")
    return _study(
        "macd",
        source=source,
        id=id,
        props={"value": value, "fast": fast, "slow": slow, "signal": signal, "pane": pane},
        style=style,
    )


def stochastic(
    *,
    source: str,
    k_window: int = 14,
    d_window: int = 3,
    pane: str = "stochastic",
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if k_window <= 0 or d_window <= 0:
        raise ValueError("k_window and d_window must be positive")
    return _study(
        "stochastic",
        source=source,
        id=id,
        props={"k_window": k_window, "d_window": d_window, "pane": pane},
        style=style,
    )


def anchored_vwap(
    *,
    source: str,
    anchor: Any,
    price: str = "hlc3",
    bands: Optional[tuple[float, ...]] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    return _study(
        "anchored_vwap",
        source=source,
        id=id,
        anchors={"anchor": _anchor(anchor)},
        props={"price": price, "bands": list(bands) if bands else []},
        style=style,
    )


def fixed_range_volume_profile(
    *,
    source: str,
    start: Any,
    end: Any,
    rows: int = 100,
    row_size: Optional[float] = None,
    volume: str = "total",
    value_area: float = 0.70,
    extend_right: bool = False,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if rows <= 0:
        raise ValueError("rows must be positive")
    if not math.isfinite(value_area) or not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    return _study(
        "fixed_range_volume_profile",
        source=source,
        id=id,
        anchors={"start": _anchor(start), "end": _anchor(end)},
        props={
            "rows": rows,
            "row_size": row_size,
            "volume": volume,
            "value_area": value_area,
            "extend_right": extend_right,
        },
        style=style,
    )


def anchored_volume_profile(
    *,
    source: str,
    anchor: Any,
    rows: int = 100,
    row_size: Optional[float] = None,
    volume: str = "total",
    value_area: float = 0.70,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if rows <= 0:
        raise ValueError("rows must be positive")
    if not math.isfinite(value_area) or not 0 < value_area <= 1:
        raise ValueError("value_area must be in (0, 1]")
    return _study(
        "anchored_volume_profile",
        source=source,
        id=id,
        anchors={"anchor": _anchor(anchor)},
        props={"rows": rows, "row_size": row_size, "volume": volume, "value_area": value_area},
        style=style,
    )


def position_forecast(
    *,
    source: str,
    start: Any,
    target: Any,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    return _drawing(
        "position_forecast",
        source=source,
        id=id,
        anchors={"start": _anchor(start), "target": _anchor(target)},
        style=style,
    )


def bars_pattern(
    *,
    source: str,
    start: Any,
    end: Any,
    destination: Any,
    mode: str = "candlestick",
    mirrored: bool = False,
    flipped: bool = False,
    normalize: bool = False,
    max_bars: Optional[int] = 240,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if max_bars is not None and max_bars <= 0:
        raise ValueError("max_bars must be positive")
    return _drawing(
        "bars_pattern",
        source=source,
        id=id,
        anchors={
            "start": _bar_anchor(start),
            "end": _bar_anchor(end),
            "destination": _anchor(destination),
        },
        props={
            "mode": mode,
            "mirrored": mirrored,
            "flipped": flipped,
            "normalize": normalize,
            "max_bars": max_bars,
        },
        style=style,
    )


def ghost_feed(
    *,
    source: str,
    anchor: Any,
    direction: str = "up",
    bars: int = 24,
    avg_hl_ticks: float = 100.0,
    variance_ticks: float = 100.0,
    tick_size: Optional[float] = None,
    seed: Optional[int] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if bars <= 0:
        raise ValueError("bars must be positive")
    if direction not in {"up", "down", "flat"}:
        raise ValueError("direction must be 'up', 'down', or 'flat'")
    if avg_hl_ticks <= 0:
        raise ValueError("avg_hl_ticks must be positive")
    if variance_ticks < 0:
        raise ValueError("variance_ticks must be non-negative")
    if tick_size is not None and tick_size <= 0:
        raise ValueError("tick_size must be positive")
    return _drawing(
        "ghost_feed",
        source=source,
        id=id,
        anchors={"anchor": _anchor(anchor)},
        props={
            "direction": direction,
            "bars": bars,
            "avg_hl_ticks": avg_hl_ticks,
            "variance_ticks": variance_ticks,
            "tick_size": tick_size,
            "seed": seed,
        },
        style=style,
    )


def sector(
    *,
    source: str,
    origin: Any,
    horizon: Any,
    target: Any,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    return _drawing(
        "sector",
        source=source,
        id=id,
        anchors={"origin": _anchor(origin), "horizon": _anchor(horizon), "target": _anchor(target)},
        style=style,
    )


def price_range(*, source: str, start: Any, end: Any, id: Optional[str] = None) -> Layer:
    return _drawing(
        "price_range", source=source, id=id, anchors={"start": _anchor(start), "end": _anchor(end)}
    )


def date_range(*, source: str, start: Any, end: Any, id: Optional[str] = None) -> Layer:
    return _drawing(
        "date_range", source=source, id=id, anchors={"start": _anchor(start), "end": _anchor(end)}
    )


def date_price_range(*, source: str, start: Any, end: Any, id: Optional[str] = None) -> Layer:
    return _drawing(
        "date_price_range",
        source=source,
        id=id,
        anchors={"start": _anchor(start), "end": _anchor(end)},
    )


def abcd_pattern(
    *,
    points: list[Any],
    source: Optional[str] = None,
    validate: Optional[str] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if len(points) != 4:
        raise ValueError("ABCD pattern requires exactly four points")
    return _drawing(
        "abcd_pattern",
        source=source,
        id=id,
        anchors={label: _anchor(point) for label, point in zip("ABCD", points, strict=True)},
        props={"validate": validate},
        style=style,
    )


def xabcd_pattern(
    *,
    points: list[Any],
    source: Optional[str] = None,
    validate: Optional[str] = None,
    id: Optional[str] = None,
    style: Optional[Mapping[str, Any]] = None,
) -> Layer:
    if len(points) != 5:
        raise ValueError("XABCD pattern requires exactly five points")
    return _drawing(
        "xabcd_pattern",
        source=source,
        id=id,
        anchors={label: _anchor(point) for label, point in zip("XABCD", points, strict=True)},
        props={"validate": validate},
        style=style,
    )


def _source_key(mark: Mark) -> Optional[str]:
    return mark.id or mark.name


def _resolve_mark_value(mark: Mark, chart_data: Any, value: Any) -> Any:
    data = mark.data if mark.data is not None else chart_data
    return _resolve(data, value)


def _ohlcv_sources(children: tuple[Component, ...], chart_data: Any) -> dict[str, dict[str, Any]]:
    sources: dict[str, dict[str, Any]] = {}
    for child in children:
        if not isinstance(child, Mark) or child.kind not in {"candlestick", "ohlc"}:
            continue
        key = _source_key(child)
        if not key:
            continue
        props = child.props
        src = {
            "x": _resolve_mark_value(child, chart_data, child.x),
            "open": _resolve_mark_value(child, chart_data, props["open"]),
            "high": _resolve_mark_value(child, chart_data, props["high"]),
            "low": _resolve_mark_value(child, chart_data, props["low"]),
            "close": _resolve_mark_value(child, chart_data, props["close"]),
            "volume": None
            if props.get("volume") is None
            else _resolve_mark_value(child, chart_data, props["volume"]),
        }
        sources[key] = src
    return sources


class FinanceChart(Component):
    """A composed chart plus finance layers/tools.

    `figure()` returns the ordinary fastcharts Figure for marks and axes.
    `finance_spec()` returns the non-rendered finance overlay intent. When the
    client layer registry lands, `build_payload()` already has a place to carry
    these layers beside the normal mark payload.
    """

    def __init__(self, children: tuple[Component, ...], **props: Any) -> None:
        self.children = children
        self._tools = [c for c in children if isinstance(c, FinanceTools)]
        self.layers = [c for c in children if isinstance(c, FinanceLayer)]
        base_children = [c for c in children if isinstance(c, (Mark, Axis, Legend))]
        unknown = [
            c
            for c in children
            if not isinstance(c, (Mark, Axis, Legend, FinanceLayer, FinanceTools))
        ]
        if unknown:
            raise TypeError(
                "finance_chart() children must be marks/axes/legend/finance layers/tools, "
                f"got {[type(c).__name__ for c in unknown]}"
            )
        if len(self._tools) > 1:
            raise ValueError("finance_chart() accepts at most one finance_tools() child")
        self._chart = Chart("finance_chart", tuple(base_children), **props)
        self._base_children = tuple(base_children)
        self._figure = None
        self._widget: Any = None

    def figure(self):
        if self._figure is not None:
            return self._figure
        fig = self._chart.figure()
        self._apply_computed_studies(fig)
        self._figure = fig
        return fig

    def _apply_computed_studies(self, fig) -> None:
        sources = _ohlcv_sources(self._base_children, self._chart.data)
        for layer in self.layers:
            if not isinstance(layer, Layer):
                continue
            if layer.kind == "equity_drawdown":
                series = layer.props.get("series")
                if not isinstance(series, Mapping):
                    continue
                name = layer.props.get("name") or layer.id or "Equity"
                color = str(layer.style.get("color") or "#2563eb")
                width = float(layer.style.get("width", 1.6))
                opacity = float(layer.style.get("opacity", 0.96))
                mode = str(layer.props.get("mode", "area"))
                if mode == "line":
                    fig.line(
                        series["x"],
                        series["equity"],
                        name=str(name),
                        color=color,
                        width=width,
                        opacity=opacity,
                    )
                else:
                    fig.area(
                        series["x"],
                        series["equity"],
                        name=str(name),
                        color=color,
                        fill_color=str(layer.style.get("fill_color") or color),
                        width=width,
                        opacity=opacity,
                        fill_opacity=float(layer.style.get("fill_opacity", 0.16)),
                        baseline=float(series.get("initial", series["equity"][0])),
                    )
                continue
            source = sources.get(layer.source or "")
            if not source:
                continue
            if layer.kind == "moving_average":
                value = str(layer.props.get("value", "close"))
                window = int(layer.props.get("window", 20))
                method = str(layer.props.get("method", "sma"))
                values = _price_source(
                    value,
                    np.asarray(source["open"], dtype=np.float64),
                    np.asarray(source["high"], dtype=np.float64),
                    np.asarray(source["low"], dtype=np.float64),
                    np.asarray(source["close"], dtype=np.float64),
                )
                avg = moving_average_values(values, window=window, method=method)
                color = str(layer.style.get("color") or "#60a5fa")
                width = float(layer.style.get("width", 1.4))
                opacity = float(layer.style.get("opacity", 0.92))
                name = layer.id or f"{method.upper()}{window}"
                fig.line(source["x"], avg, name=name, color=color, width=width, opacity=opacity)
                continue
            if layer.kind == "bollinger_bands":
                value = str(layer.props.get("value", "close"))
                window = int(layer.props.get("window", 20))
                deviations = float(layer.props.get("deviations", 2.0))
                values = _price_source(
                    value,
                    np.asarray(source["open"], dtype=np.float64),
                    np.asarray(source["high"], dtype=np.float64),
                    np.asarray(source["low"], dtype=np.float64),
                    np.asarray(source["close"], dtype=np.float64),
                )
                bands = bollinger_bands_values(values, window=window, deviations=deviations)
                color = str(layer.style.get("color") or "#a78bfa")
                band_color = str(layer.style.get("band_color") or color)
                width = float(layer.style.get("width", 1.2))
                band_width = float(layer.style.get("band_width", max(0.8, width * 0.85)))
                opacity = float(layer.style.get("opacity", 0.88))
                band_opacity = float(layer.style.get("band_opacity", min(opacity, 0.62)))
                name = layer.id or f"BB{window}"
                fig.line(
                    source["x"],
                    bands["middle"],
                    name=f"{name} mid",
                    color=color,
                    width=width,
                    opacity=opacity,
                )
                fig.line(
                    source["x"],
                    bands["upper"],
                    name=f"{name} upper",
                    color=band_color,
                    width=band_width,
                    opacity=band_opacity,
                )
                fig.line(
                    source["x"],
                    bands["lower"],
                    name=f"{name} lower",
                    color=band_color,
                    width=band_width,
                    opacity=band_opacity,
                )
                continue
            if layer.kind in {"anchored_vwap", "vwap"}:
                if source["volume"] is None:
                    continue
                price = str(layer.props.get("price", "hlc3"))
                anchor = (
                    layer.anchors.get("anchor", {"bar": 0})
                    if layer.kind == "anchored_vwap"
                    else {"bar": 0}
                )
                xs, vwap, std = _anchored_vwap_arrays(
                    source["x"],
                    source["open"],
                    source["high"],
                    source["low"],
                    source["close"],
                    source["volume"],
                    anchor=anchor,
                    price=price,
                )
                if len(xs) == 0:
                    continue
                color = str(
                    layer.style.get("color")
                    or ("#f59e0b" if layer.kind == "anchored_vwap" else "#22c55e")
                )
                width = float(layer.style.get("width", 1.4))
                opacity = float(layer.style.get("opacity", 0.95))
                name = layer.id or ("AVWAP" if layer.kind == "anchored_vwap" else "VWAP")
                fig.line(xs, vwap, name=name, color=color, width=width, opacity=opacity)
                band_color = str(layer.style.get("band_color") or color)
                band_width = float(layer.style.get("band_width", max(0.8, width * 0.75)))
                band_opacity = float(layer.style.get("band_opacity", min(opacity, 0.55)))
                for band in layer.props.get("bands", ()):
                    b = float(band)
                    fig.line(
                        xs,
                        vwap + std * b,
                        name=f"{name} +{b:g} std",
                        color=band_color,
                        width=band_width,
                        opacity=band_opacity,
                    )
                    fig.line(
                        xs,
                        vwap - std * b,
                        name=f"{name} -{b:g} std",
                        color=band_color,
                        width=band_width,
                        opacity=band_opacity,
                    )
                continue

    def finance_spec(self) -> dict[str, Any]:
        tools = self._tools[-1] if self._tools else FinanceTools()
        return {"tools": tools.to_spec(), "layers": self._materialized_layers()}

    def _materialized_layers(self) -> list[dict[str, Any]]:
        sources = _ohlcv_sources(self._base_children, self._chart.data)
        specs: list[dict[str, Any]] = []
        for layer in self.layers:
            spec = layer.to_spec()
            if isinstance(layer, Layer) and layer.kind == "volume_bars":
                source = sources.get(layer.source or "")
                if source and source["volume"] is not None:
                    bars = _volume_bar_arrays(
                        source["x"],
                        source["open"],
                        source["close"],
                        source["volume"],
                    )
                    spec.setdefault("props", {})["bars"] = _jsonable(bars)
            if isinstance(layer, Layer) and layer.kind in {"rsi", "macd", "stochastic"}:
                source = sources.get(layer.source or "")
                if source:
                    props = layer.props
                    x_arr = np.asarray(source["x"])
                    close_f = np.asarray(source["close"], dtype=np.float64)
                    if layer.kind == "rsi":
                        value = str(props.get("value", "close"))
                        values = _price_source(
                            value,
                            np.asarray(source["open"], dtype=np.float64),
                            np.asarray(source["high"], dtype=np.float64),
                            np.asarray(source["low"], dtype=np.float64),
                            close_f,
                        )
                        rsi_arr = rsi_values(values, window=int(props.get("window", 14)))
                        spec.setdefault("props", {})["series"] = _jsonable(
                            {
                                "x": x_arr,
                                "rsi": rsi_arr,
                                "rows": int(len(rsi_arr)),
                                "y_min": 0.0,
                                "y_max": 100.0,
                                "guides": [30.0, 70.0],
                            }
                        )
                    elif layer.kind == "macd":
                        value = str(props.get("value", "close"))
                        values = _price_source(
                            value,
                            np.asarray(source["open"], dtype=np.float64),
                            np.asarray(source["high"], dtype=np.float64),
                            np.asarray(source["low"], dtype=np.float64),
                            close_f,
                        )
                        series = macd_values(
                            values,
                            fast=int(props.get("fast", 12)),
                            slow=int(props.get("slow", 26)),
                            signal=int(props.get("signal", 9)),
                        )
                        y_min, y_max = _finite_range(
                            series["macd"],
                            series["signal"],
                            series["histogram"],
                            default=(-1.0, 1.0),
                        )
                        spec.setdefault("props", {})["series"] = _jsonable(
                            {
                                "x": x_arr,
                                "macd": series["macd"],
                                "signal": series["signal"],
                                "histogram": series["histogram"],
                                "rows": int(len(series["macd"])),
                                "y_min": y_min,
                                "y_max": y_max,
                                "guides": [0.0],
                            }
                        )
                    else:
                        series = stochastic_values(
                            source["high"],
                            source["low"],
                            close_f,
                            k_window=int(props.get("k_window", 14)),
                            d_window=int(props.get("d_window", 3)),
                        )
                        spec.setdefault("props", {})["series"] = _jsonable(
                            {
                                "x": x_arr,
                                "k": series["k"],
                                "d": series["d"],
                                "rows": int(len(series["k"])),
                                "y_min": 0.0,
                                "y_max": 100.0,
                                "guides": [20.0, 80.0],
                            }
                        )
            if isinstance(layer, Layer) and layer.kind in {
                "fixed_range_volume_profile",
                "anchored_volume_profile",
            }:
                source = sources.get(layer.source or "")
                if source and source["volume"] is not None:
                    props = layer.props
                    kwargs: dict[str, Any] = {
                        "rows": int(props.get("rows", 100)),
                        "row_size": props.get("row_size"),
                        "value_area": float(props.get("value_area", 0.70)),
                    }
                    if layer.kind == "fixed_range_volume_profile":
                        kwargs["start"] = layer.anchors.get("start")
                        kwargs["end"] = layer.anchors.get("end")
                    else:
                        kwargs["anchor"] = layer.anchors.get("anchor")
                    profile = _volume_profile_arrays(
                        source["x"],
                        source["open"],
                        source["high"],
                        source["low"],
                        source["close"],
                        source["volume"],
                        **kwargs,
                    )
                    spec.setdefault("props", {})["profile"] = _jsonable(profile)
            if isinstance(layer, Layer) and layer.kind == "bars_pattern":
                source = sources.get(layer.source or "")
                if source:
                    props = layer.props
                    pattern = _bars_pattern_arrays(
                        source["x"],
                        source["open"],
                        source["high"],
                        source["low"],
                        source["close"],
                        start=layer.anchors.get("start"),
                        end=layer.anchors.get("end"),
                        destination=layer.anchors.get("destination"),
                        mirrored=bool(props.get("mirrored", False)),
                        flipped=bool(props.get("flipped", False)),
                        normalize=bool(props.get("normalize", False)),
                        max_bars=props.get("max_bars"),
                    )
                    spec.setdefault("props", {})["pattern"] = _jsonable(pattern)
            if isinstance(layer, Layer) and layer.kind == "ghost_feed":
                source = sources.get(layer.source or "")
                if source:
                    props = layer.props
                    feed = _ghost_feed_arrays(
                        source["x"],
                        source["open"],
                        source["high"],
                        source["low"],
                        source["close"],
                        anchor=layer.anchors.get("anchor"),
                        direction=str(props.get("direction", "up")),
                        bars=int(props.get("bars", 24)),
                        avg_hl_ticks=float(props.get("avg_hl_ticks", 100.0)),
                        variance_ticks=float(props.get("variance_ticks", 100.0)),
                        tick_size=props.get("tick_size"),
                        seed=props.get("seed"),
                    )
                    spec.setdefault("props", {})["feed"] = _jsonable(feed)
            specs.append(spec)
        return specs

    def _apply_layer_axis_ranges(self, spec: dict[str, Any], layers: list[dict[str, Any]]) -> None:
        for layer in layers:
            if layer.get("kind") != "returns_distribution":
                continue
            series = layer.get("props", {}).get("series", {})
            if not series:
                continue
            spec["x_axis"]["range"] = [series["x_min"], series["x_max"]]
            spec["x_axis"]["label"] = spec["x_axis"].get("label") or "Return"
            spec["y_axis"]["range"] = [series["y_min"], series["y_max"]]
            spec["y_axis"]["label"] = spec["y_axis"].get("label") or (
                "Probability" if series.get("y_mode") == "probability" else "Count"
            )

    def build_payload(self, px_width: int = 2048):
        spec, blob = self.figure().build_payload(px_width=px_width)
        finance_spec = self.finance_spec()
        self._apply_layer_axis_ranges(spec, finance_spec["layers"])
        spec.update(finance_spec)
        return spec, blob

    @property
    def title(self) -> Optional[str]:
        return self._chart.title

    def density_view(
        self, trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
    ):
        return self.figure().density_view(trace_id, x0, x1, y0, y1, w, h)

    def pick(self, trace_id: int, index: int, drill_seq: Optional[int] = None):
        return self.figure().pick(trace_id, index, drill_seq)

    def select_range(
        self, x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
    ):
        return self.figure().select_range(x0, x1, y0, y1, trace_id)

    def to_shipped_indices(self, trace_id: int, canonical):
        return self.figure().to_shipped_indices(trace_id, canonical)

    def decimate_view(self, x0: float, x1: float, px_width: int):
        return self.figure().decimate_view(x0, x1, px_width)

    def widget(self) -> Any:
        if getattr(self, "_widget", None) is None:
            from .widget import FigureWidget

            # FinanceChart duck-types the Figure payload surface (runtime-verified).
            self._widget = FigureWidget(self)  # ty: ignore[invalid-argument-type]
        return self._widget

    def show(self) -> Any:
        return self.widget()

    def _ipython_display_(self) -> None:
        self._chart._ipython_display_()

    def to_html(self, path: Optional[str] = None) -> str:
        return export.to_html(self, path)  # ty: ignore[invalid-argument-type]

    def memory_report(self) -> dict:
        return self.figure().memory_report()


def finance_chart(*children: Component, **props: Any) -> FinanceChart:
    """Compose normal marks with finance studies, drawings, and tool state."""
    return FinanceChart(children, **props)


def performance_chart(
    x: Any = None,
    *,
    equity: Any = None,
    returns: Any = None,
    pnl: Any = None,
    initial: float = 1.0,
    drawdown: str = "percent",
    mode: str = "area",
    title: Optional[str] = None,
    width: "int | str" = 900,
    height: "int | str" = 420,
    style: Optional[Mapping[str, Any]] = None,
) -> FinanceChart:
    """Create an equity/PnL performance chart with a synced drawdown pane."""
    return finance_chart(
        equity_drawdown(
            x=x,
            equity=equity,
            returns=returns,
            pnl=pnl,
            initial=initial,
            drawdown=drawdown,
            mode=mode,
            id="performance",
            style=style,
        ),
        x_axis(),
        y_axis(label="Equity", side="right"),
        title=title,
        width=width,
        height=height,
    )


def returns_distribution_chart(
    returns: Any,
    *,
    bins: Any = 50,
    bin_range: Optional[tuple[float, float]] = None,
    confidence: float = 0.95,
    y: str = "probability",
    title: Optional[str] = None,
    width: "int | str" = 900,
    height: "int | str" = 420,
    style: Optional[Mapping[str, Any]] = None,
) -> FinanceChart:
    """Create a returns histogram with VaR/CVaR marker lines."""
    return finance_chart(
        returns_distribution(
            returns,
            bins=bins,
            bin_range=bin_range,
            confidence=confidence,
            y=y,
            id="returns_distribution",
            style=style,
        ),
        x_axis(label="Return"),
        y_axis(label="Probability" if y == "probability" else "Count", side="right"),
        title=title,
        width=width,
        height=height,
    )
