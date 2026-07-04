"""Candlestick (OHLC) chart: multi-column trace, OHLC-bucket decimation,
low..high autorange, and the wire shape the client's rect renderer reads."""

from __future__ import annotations

import numpy as np
import pytest

from fastcharts import Figure, candlestick, candlestick_chart, kernels, ohlc, ohlc_chart, x_axis
from fastcharts.figure import DECIMATION_THRESHOLD


def _col(spec, blob, ref, dtype=np.float32):
    m = spec["columns"][ref]
    return np.frombuffer(blob, dtype=dtype, count=m["len"], offset=m["byte_offset"])


def _decode(spec, blob, ref):
    m = spec["columns"][ref]
    return _col(spec, blob, ref) + m["offset"]


def _series(n, seed=0):
    rng = np.random.default_rng(seed)
    x = np.arange(n, dtype=np.float64)
    o = 100 + np.cumsum(rng.normal(0, 1, n))
    c = o + rng.normal(0, 1, n)
    hi = np.maximum(o, c) + np.abs(rng.normal(0, 0.5, n))
    lo = np.minimum(o, c) - np.abs(rng.normal(0, 0.5, n))
    return x, o, hi, lo, c


def test_candlestick_direct_wire_shape():
    x, o, h, low, c = _series(500)
    fig = Figure().candlestick(x, o, h, low, c, name="px")
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "candlestick" and tr["tier"] == "direct"
    for k in ("x", "open", "high", "low", "close"):
        assert k in tr
    # open/high/low/close share one y offset so they map on a single axis (§16).
    yoff = {spec["columns"][tr[k]]["offset"] for k in ("open", "high", "low", "close")}
    assert len(yoff) == 1
    # values round-trip through the offset encoding.
    np.testing.assert_allclose(_decode(spec, blob, tr["close"]), c, rtol=1e-4, atol=1e-3)
    assert tr["style"]["up_color"] and tr["style"]["down_color"]


def test_candlestick_y_autorange_spans_low_high():
    # The deferred contract hook: y must cover low..high, not close.
    x, o, h, low, c = _series(300, seed=3)
    fig = Figure().candlestick(x, o, h, low, c)
    _, (y0, y1) = fig.x_range(), fig.y_range()
    assert y0 <= low.min() and y1 >= h.max()
    # close alone would have clipped the wicks:
    assert y0 < c.min() and y1 > c.max()


def test_candlestick_decimates_above_threshold():
    n = DECIMATION_THRESHOLD * 3
    x, o, h, low, c = _series(n, seed=1)
    fig = Figure().candlestick(x, o, h, low, c)
    spec, blob = fig.build_payload(px_width=800)
    tr = spec["traces"][0]
    assert tr["tier"] == "decimated"
    shipped = spec["columns"][tr["x"]]["len"]
    assert shipped <= 800  # screen-bounded
    assert tr["n_points"] == n  # true count preserved in the spec (§28)
    # decimated extent still covers the full data low..high (buckets keep extremes)
    hi_ship = _decode(spec, blob, tr["high"])
    lo_ship = _decode(spec, blob, tr["low"])
    assert hi_ship.max() == pytest.approx(h.max(), rel=1e-4)
    assert lo_ship.min() == pytest.approx(low.min(), rel=1e-4)


def test_ohlc_decimate_bucket_semantics():
    # open=first, high=max, low=min, close=last per pixel bucket.
    x = np.arange(10, dtype=np.float64)
    o = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=np.float64)
    h = o + 1
    low = o - 1
    c = o + 0.5
    xd, od, hd, ld, cd = kernels.ohlc_decimate(x, o, h, low, c, 0.0, 9.0, 2)
    assert len(xd) == 2  # two pixel columns
    # first bucket covers x in [0,4.5): open=1 (first), close=5.5 (last), hi=6, lo=0
    assert od[0] == 1.0 and cd[0] == 5.5 and hd[0] == 6.0 and ld[0] == 0.0


def test_candlestick_unsorted_x_is_sorted():
    x = np.array([2.0, 0.0, 1.0])
    o = np.array([1.0, 2.0, 3.0])
    fig = Figure().candlestick(x, o, o + 1, o - 1, o)
    assert np.all(np.diff(fig.traces[0].x.values) >= 0)


def test_candlestick_length_mismatch_raises():
    with pytest.raises(ValueError, match="equal length"):
        Figure().candlestick([0, 1, 2], [1, 2], [3, 4, 5], [0, 1, 2], [1, 2, 3])


def test_candlestick_hollow_and_wick_style():
    x, o, h, low, c = _series(50)
    fig = Figure().candlestick(x, o, h, low, c, hollow=True, wick_color="#888888")
    tr = fig.build_payload()[0]["traces"][0]
    assert tr["style"]["hollow"] is True
    assert tr["style"]["wick_color"] == "#888888"


def test_ohlc_shares_candlestick_wire_shape():
    x, o, h, low, c = _series(400, seed=5)
    fig = Figure().ohlc(x, o, h, low, c, name="bars")
    spec, _ = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "ohlc"
    for k in ("x", "open", "high", "low", "close"):
        assert k in tr
    # y-autorange spans low..high, same hook as candlestick.
    y0, y1 = fig.y_range()
    assert y0 <= low.min() and y1 >= h.max()


def test_ohlc_decimates_above_threshold():
    n = DECIMATION_THRESHOLD * 2
    x, o, h, low, c = _series(n, seed=6)
    tr = Figure().ohlc(x, o, h, low, c).build_payload(px_width=500)[0]["traces"][0]
    assert tr["kind"] == "ohlc" and tr["tier"] == "decimated"


def test_candlestick_zoom_redecimation():
    # decimate_view re-buckets a candlestick for a zoomed window (§28), shipping
    # the OHLC columns keyed by kind so the client refills its rect buffers.
    n = DECIMATION_THRESHOLD * 4
    x, o, h, low, c = _series(n, seed=9)
    fig = Figure().candlestick(x, o, h, low, c)
    fig.build_payload(px_width=1000)  # initial decimated paint
    update, buffers = fig.decimate_view(1000.0, 2000.0, 600)
    tr = next(t for t in update["traces"] if t["id"] == 0)
    assert tr["kind"] == "candlestick"
    for k in ("x", "open", "high", "low", "close"):
        assert k in tr and "offset" in tr[k]
    # x offset re-centers on the window midpoint (§16 deep-zoom rule).
    assert tr["x"]["offset"] == pytest.approx(1500.0)
    shipped = tr["x"]["len"]
    assert 0 < shipped <= 600


def test_candlestick_component_api():
    pd = pytest.importorskip("pandas")

    df = pd.DataFrame(
        {
            "t": range(5),
            "o": [1, 2, 3, 4, 5],
            "h": [2, 3, 4, 5, 6],
            "l": [0, 1, 2, 3, 4],
            "c": [1.5, 2.5, 3.5, 4.5, 5.5],
        }
    )
    chart = candlestick_chart(
        candlestick(x="t", open="o", high="h", low="l", close="c", data=df, name="p"),
        x_axis(label="t"),
    )
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["kind"] == "candlestick"
    assert spec["traces"][0]["name"] == "p"

    bars = ohlc_chart(ohlc(x="t", open="o", high="h", low="l", close="c", data=df))
    assert bars.figure().build_payload()[0]["traces"][0]["kind"] == "ohlc"
