from __future__ import annotations

import numpy as np
import pytest

import fastcharts as fc
from fastcharts.finance import FinanceChart, FinanceLayer, FinanceTools, Instrument, PositionDrawing


def _ohlc():
    x = np.arange(5.0)
    open_ = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    high = open_ + 2
    low = open_ - 2
    close = open_ + 1
    return x, open_, high, low, close


def _ohlcv():
    x, open_, high, low, close = _ohlc()
    volume = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    return x, open_, high, low, close, volume


def test_finance_factories_return_components():
    assert isinstance(fc.instrument(), Instrument)
    assert isinstance(fc.finance_tools(), FinanceTools)
    assert isinstance(
        fc.long_position(source="price", entry=(1, 100.0), stop=95.0, target=115.0), PositionDrawing
    )
    assert isinstance(fc.anchored_vwap(source="price", anchor=(1, 100.0)), FinanceLayer)
    chart = fc.finance_chart(fc.candlestick(*_ohlc(), name="price"))
    assert isinstance(chart, FinanceChart)


def test_anchored_vwap_values_from_anchor_bar():
    x = np.array([0.0, 1.0, 2.0, 3.0])
    close = np.array([10.0, 20.0, 30.0, 40.0])
    volume = np.array([1.0, 3.0, 6.0, 1.0])
    xs, vwap = fc.anchored_vwap_values(
        x,
        close,
        close,
        close,
        close,
        volume,
        anchor={"bar": 1},
        price="close",
    )
    np.testing.assert_array_equal(xs, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(vwap, [20.0, 26.6666666667, 28.0])


def test_ta_reference_values():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    sma = fc.moving_average_values(values, window=3, method="sma")
    ema = fc.moving_average_values(values, window=3, method="ema")
    np.testing.assert_allclose(sma, [np.nan, np.nan, 2.0, 3.0, 4.0], equal_nan=True)
    np.testing.assert_allclose(ema, [1.0, 1.5, 2.25, 3.125, 4.0625])

    bands = fc.bollinger_bands_values(values, window=3, deviations=2.0)
    std = np.sqrt(2.0 / 3.0)
    np.testing.assert_allclose(bands["middle"], [np.nan, np.nan, 2.0, 3.0, 4.0], equal_nan=True)
    np.testing.assert_allclose(
        bands["upper"],
        [np.nan, np.nan, 2.0 + 2 * std, 3.0 + 2 * std, 4.0 + 2 * std],
        equal_nan=True,
    )
    np.testing.assert_allclose(
        bands["lower"],
        [np.nan, np.nan, 2.0 - 2 * std, 3.0 - 2 * std, 4.0 - 2 * std],
        equal_nan=True,
    )


def test_oscillator_reference_values():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    rsi = fc.rsi_values(values, window=3)
    np.testing.assert_allclose(rsi, [np.nan, np.nan, np.nan, 100.0, 100.0], equal_nan=True)
    np.testing.assert_allclose(
        fc.rsi_values(np.ones(5), window=3),
        [np.nan, np.nan, np.nan, 50.0, 50.0],
        equal_nan=True,
    )

    macd = fc.macd_values(values, fast=2, slow=3, signal=2)
    expected_macd = fc.moving_average_values(
        values, window=2, method="ema"
    ) - fc.moving_average_values(
        values,
        window=3,
        method="ema",
    )
    expected_signal = fc.moving_average_values(expected_macd, window=2, method="ema")
    np.testing.assert_allclose(macd["macd"], expected_macd)
    np.testing.assert_allclose(macd["signal"], expected_signal)
    np.testing.assert_allclose(macd["histogram"], expected_macd - expected_signal)

    high = np.array([2.0, 3.0, 4.0, 5.0, 6.0])
    low = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    close = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    stoch = fc.stochastic_values(high, low, close, k_window=3, d_window=2)
    np.testing.assert_allclose(stoch["k"], [np.nan, np.nan, 75.0, 75.0, 75.0], equal_nan=True)
    np.testing.assert_allclose(stoch["d"], [np.nan, np.nan, np.nan, 75.0, 75.0], equal_nan=True)


def test_vwap_values_from_start():
    x = np.array([0.0, 1.0, 2.0])
    close = np.array([10.0, 20.0, 30.0])
    volume = np.array([1.0, 3.0, 6.0])
    xs, vwap = fc.vwap_values(x, close, close, close, close, volume, price="close")
    np.testing.assert_array_equal(xs, x)
    np.testing.assert_allclose(vwap, [10.0, 17.5, 25.0])


def test_volume_profile_values_distributes_volume_by_price_overlap():
    x = np.array([0.0, 1.0])
    open_ = np.array([0.0, 3.0])
    high = np.array([2.0, 4.0])
    low = np.array([0.0, 2.0])
    close = np.array([2.0, 2.5])
    volume = np.array([10.0, 20.0])
    profile = fc.volume_profile_values(
        x,
        open_,
        high,
        low,
        close,
        volume,
        start={"bar": 0},
        end={"bar": 1},
        rows=4,
        value_area=0.5,
    )
    np.testing.assert_allclose(profile["price_low"], [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(profile["price_high"], [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(profile["total"], [5.0, 5.0, 10.0, 10.0])
    np.testing.assert_allclose(profile["up"], [5.0, 5.0, 0.0, 0.0])
    np.testing.assert_allclose(profile["down"], [0.0, 0.0, 10.0, 10.0])
    assert profile["poc_index"] == 2
    np.testing.assert_array_equal(profile["value_area"], [False, False, True, True])


def test_finance_chart_computes_anchored_vwap_trace_from_ohlcv_source():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
            name="candles",
        ),
        fc.anchored_vwap(
            source="price",
            anchor={"bar": 1},
            price="close",
            bands=(1.0,),
            id="avwap",
            style={"color": "#ffaa00"},
        ),
    )
    fig = chart.figure()
    assert [trace.kind for trace in fig.traces] == ["candlestick", "line", "line", "line"]
    assert fig.traces[1].name == "avwap"
    assert fig.traces[1].style["color"] == "#ffaa00"
    np.testing.assert_array_equal(fig.traces[1].x.values, x[1:])
    expected = np.cumsum(close[1:] * volume[1:]) / np.cumsum(volume[1:])
    np.testing.assert_allclose(fig.traces[1].y.values, expected)
    spec, _ = chart.build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["candlestick", "line", "line", "line"]
    assert spec["traces"][1]["name"] == "avwap"


def test_finance_chart_computes_ta_overlay_traces_from_ohlcv_source():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.moving_average(source="price", value="close", window=3, method="sma", id="sma3"),
        fc.bollinger_bands(
            source="price",
            value="close",
            window=3,
            deviations=2.0,
            id="bb3",
        ),
        fc.vwap(source="price", price="close", id="vwap"),
    )
    fig = chart.figure()
    assert [trace.kind for trace in fig.traces] == [
        "candlestick",
        "line",
        "line",
        "line",
        "line",
        "line",
    ]
    assert [trace.name for trace in fig.traces[1:]] == [
        "sma3",
        "bb3 mid",
        "bb3 upper",
        "bb3 lower",
        "vwap",
    ]
    np.testing.assert_allclose(
        fig.traces[1].y.values, [np.nan, np.nan, 102.0, 103.0, 104.0], equal_nan=True
    )
    band_std = np.sqrt(2.0 / 3.0)
    np.testing.assert_allclose(
        fig.traces[2].y.values, [np.nan, np.nan, 102.0, 103.0, 104.0], equal_nan=True
    )
    np.testing.assert_allclose(
        fig.traces[3].y.values,
        [np.nan, np.nan, 102.0 + 2 * band_std, 103.0 + 2 * band_std, 104.0 + 2 * band_std],
        equal_nan=True,
    )
    expected_vwap = np.cumsum(close * volume) / np.cumsum(volume)
    np.testing.assert_allclose(fig.traces[5].y.values, expected_vwap)
    spec, _ = chart.build_payload()
    assert [trace["name"] for trace in spec["traces"][1:]] == [
        "sma3",
        "bb3 mid",
        "bb3 upper",
        "bb3 lower",
        "vwap",
    ]


def test_finance_chart_materializes_volume_profile_layer_from_ohlcv_source():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.fixed_range_volume_profile(
            source="price",
            start={"bar": 0},
            end={"bar": 4},
            rows=6,
            volume="up_down",
        ),
    )
    spec, _ = chart.build_payload()
    profile = spec["layers"][0]["props"]["profile"]
    assert profile["rows"] == 6
    assert profile["poc_index"] >= 0
    assert profile["max_total"] > 0
    assert len(profile["total"]) == 6
    assert len(profile["value_area"]) == 6


def test_finance_chart_materializes_volume_bars_from_ohlcv_source():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.volume_bars(source="price", pane="volume", id="vol"),
    )
    spec, _ = chart.build_payload()
    layer = spec["layers"][0]
    assert layer["kind"] == "volume_bars"
    assert layer["props"]["pane"] == "volume"
    bars = layer["props"]["bars"]
    assert bars["rows"] == 5
    assert bars["max_volume"] == 50.0
    np.testing.assert_allclose(bars["x"], x)
    np.testing.assert_allclose(bars["volume"], volume)
    np.testing.assert_array_equal(bars["direction"], [True, True, True, True, True])


def test_finance_chart_materializes_oscillator_layers_from_ohlcv_source():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.rsi(source="price", window=3, id="rsi3"),
        fc.macd(source="price", fast=2, slow=3, signal=2, id="macd2"),
        fc.stochastic(source="price", k_window=3, d_window=2, id="stoch3"),
    )
    assert [trace.kind for trace in chart.figure().traces] == ["candlestick"]
    spec, _ = chart.build_payload()
    layers = {layer["kind"]: layer for layer in spec["layers"]}
    assert set(layers) == {"rsi", "macd", "stochastic"}

    rsi_series = layers["rsi"]["props"]["series"]
    assert rsi_series["rows"] == 5
    assert rsi_series["y_min"] == 0.0
    assert rsi_series["y_max"] == 100.0
    assert rsi_series["guides"] == [30.0, 70.0]
    np.testing.assert_allclose(rsi_series["x"], x)
    np.testing.assert_allclose(
        rsi_series["rsi"], [np.nan, np.nan, np.nan, 100.0, 100.0], equal_nan=True
    )

    macd_series = layers["macd"]["props"]["series"]
    expected_macd = fc.macd_values(close, fast=2, slow=3, signal=2)
    assert macd_series["rows"] == 5
    assert macd_series["guides"] == [0.0]
    assert macd_series["y_min"] < macd_series["y_max"]
    np.testing.assert_allclose(macd_series["macd"], expected_macd["macd"])
    np.testing.assert_allclose(macd_series["signal"], expected_macd["signal"])
    np.testing.assert_allclose(macd_series["histogram"], expected_macd["histogram"])

    stoch_series = layers["stochastic"]["props"]["series"]
    expected_stoch = fc.stochastic_values(high, low, close, k_window=3, d_window=2)
    assert stoch_series["rows"] == 5
    assert stoch_series["y_min"] == 0.0
    assert stoch_series["y_max"] == 100.0
    assert stoch_series["guides"] == [20.0, 80.0]
    np.testing.assert_allclose(stoch_series["k"], expected_stoch["k"], equal_nan=True)
    np.testing.assert_allclose(stoch_series["d"], expected_stoch["d"], equal_nan=True)


def test_finance_chart_materializes_bars_pattern_from_source_window():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.bars_pattern(
            source="price",
            start=1,
            end=3,
            destination=(10.0, 200.0),
            max_bars=10,
        ),
    )
    spec, _ = chart.build_payload()
    pattern = spec["layers"][0]["props"]["pattern"]
    assert pattern["rows"] == 3
    assert pattern["source_start_index"] == 1
    assert pattern["source_end_index"] == 4
    np.testing.assert_allclose(pattern["x"], [10.0, 11.0, 12.0])
    np.testing.assert_allclose(pattern["open"], [200.0, 201.0, 202.0])
    np.testing.assert_allclose(pattern["high"], [202.0, 203.0, 204.0])
    np.testing.assert_allclose(pattern["low"], [198.0, 199.0, 200.0])
    np.testing.assert_allclose(pattern["close"], [201.0, 202.0, 203.0])


def test_finance_chart_materializes_mirrored_flipped_normalized_bars_pattern():
    x, open_, high, low, close, volume = _ohlcv()
    chart = fc.finance_chart(
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.bars_pattern(
            source="price",
            start={"bar": 1},
            end={"bar": 3},
            destination=(20.0, 200.0),
            mirrored=True,
            flipped=True,
            normalize=True,
        ),
    )
    spec, _ = chart.build_payload()
    pattern = spec["layers"][0]["props"]["pattern"]
    assert pattern["rows"] == 3
    np.testing.assert_allclose(pattern["x"], [20.0, 21.0, 22.0])
    # Mirrored uses bar 3 as the destination baseline, then normalized percent
    # deltas are flipped around the destination price.
    np.testing.assert_allclose(pattern["open"], [200.0, 201.9417475728, 203.8834951456])
    np.testing.assert_allclose(pattern["close"], [198.0582524272, 200.0, 201.9417475728])
    assert all(
        high_value >= open_value >= low_value
        for high_value, open_value, low_value in zip(  # noqa: B905
            pattern["high"], pattern["open"], pattern["low"]
        )
    )


def test_finance_chart_materializes_deterministic_ghost_feed_from_source():
    x, open_, high, low, close, volume = _ohlcv()
    children = (
        fc.candlestick(
            x=x,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            id="price",
        ),
        fc.ghost_feed(
            source="price",
            anchor=(10.0, 200.0),
            direction="up",
            bars=4,
            avg_hl_ticks=100.0,
            variance_ticks=0.0,
            seed=123,
        ),
    )
    first, _ = fc.finance_chart(*children).build_payload()
    second, _ = fc.finance_chart(*children).build_payload()
    feed = first["layers"][0]["props"]["feed"]
    assert feed["rows"] == 4
    assert feed["tick_size"] == 0.04
    np.testing.assert_allclose(feed["x"], [10.0, 11.0, 12.0, 13.0])
    assert all(c > o for o, c in zip(feed["open"], feed["close"], strict=True))
    np.testing.assert_allclose(feed["open"], second["layers"][0]["props"]["feed"]["open"])
    np.testing.assert_allclose(feed["high"], second["layers"][0]["props"]["feed"]["high"])


def test_equity_curve_values_from_returns_and_pnl():
    equity_from_returns = fc.equity_curve_values(returns=[0.10, -0.05, 0.20], initial=100.0)
    equity_from_pnl = fc.equity_curve_values(pnl=[10.0, -4.0, 20.0], initial=100.0)
    np.testing.assert_allclose(equity_from_returns, [100.0, 110.0, 104.5, 125.4])
    np.testing.assert_allclose(equity_from_pnl, [100.0, 110.0, 106.0, 126.0])


def test_returns_values_simple_and_log():
    values = np.array([100.0, 110.0, 104.5, 125.4])
    np.testing.assert_allclose(fc.returns_values(values), [0.10, -0.05, 0.20])
    np.testing.assert_allclose(
        fc.returns_values([100.0, 110.0, 121.0], method="log"), np.log([1.1, 1.1])
    )


def test_drawdown_values_tracks_peak_trough_and_recovery():
    drawdown = fc.drawdown_values([100.0, 110.0, 105.0, 120.0, 90.0, 95.0, 130.0])
    np.testing.assert_allclose(
        drawdown["running_peak"], [100.0, 110.0, 110.0, 120.0, 120.0, 120.0, 130.0]
    )
    np.testing.assert_allclose(drawdown["drawdown"], [0.0, 0.0, -5.0, 0.0, -30.0, -25.0, 0.0])
    np.testing.assert_allclose(
        drawdown["drawdown_pct"],
        [0.0, 0.0, -5.0 / 110.0, 0.0, -0.25, -25.0 / 120.0, 0.0],
    )
    assert drawdown["max_drawdown"] == -30.0
    assert drawdown["max_drawdown_pct"] == -0.25
    assert drawdown["peak_index"] == 3
    assert drawdown["trough_index"] == 4
    assert drawdown["recovery_index"] == 6
    assert drawdown["drawdown_duration"] == 1
    assert drawdown["recovery_duration"] == 2


def test_equity_drawdown_materializes_stacked_performance_chart():
    chart = fc.performance_chart(
        x=np.array([1.0, 2.0, 3.0]),
        pnl=np.array([10.0, -15.0, 20.0]),
        initial=100.0,
        title="strategy",
        style={"color": "#155eef", "drawdown_color": "#d92d20"},
    )
    fig = chart.figure()
    assert [trace.kind for trace in fig.traces] == ["area"]
    assert fig.traces[0].name == "performance"
    assert fig.traces[0].style["baseline"] == 100.0
    np.testing.assert_allclose(fig.traces[0].y.values, [100.0, 110.0, 95.0, 115.0])
    np.testing.assert_allclose(fig.traces[0].x.values, [0.0, 1.0, 2.0, 3.0])

    spec, _ = chart.build_payload()
    assert spec["title"] == "strategy"
    assert spec["y_axis"]["side"] == "right"
    assert spec["traces"][0]["kind"] == "area"
    assert [layer["kind"] for layer in spec["layers"]] == ["equity_drawdown"]
    layer = spec["layers"][0]
    assert layer["props"]["pane"] == "drawdown"
    assert layer["props"]["mode"] == "area"
    assert layer["style"]["drawdown_color"] == "#d92d20"
    series = layer["props"]["series"]
    assert series["rows"] == 4
    assert series["drawdown_mode"] == "percent"
    np.testing.assert_allclose(series["equity"], [100.0, 110.0, 95.0, 115.0])
    np.testing.assert_allclose(series["running_peak"], [100.0, 110.0, 110.0, 115.0])
    np.testing.assert_allclose(series["drawdown"], [0.0, 0.0, -15.0, 0.0])
    np.testing.assert_allclose(series["drawdown_y"], [0.0, 0.0, -15.0 / 110.0 * 100.0, 0.0])
    assert series["metrics"]["max_drawdown"] == -15.0
    assert series["metrics"]["trough_index"] == 2
    assert series["y_min"] < 0.0
    assert series["y_max"] >= 0.0


def test_var_cvar_values_and_returns_distribution_markers():
    returns = np.array([-0.10, -0.04, -0.02, 0.0, 0.01, 0.03, 0.08])
    risk = fc.var_cvar_values(returns, confidence=0.80)
    expected_var = float(np.quantile(returns, 0.20, method="linear"))
    assert risk["confidence"] == 0.80
    assert risk["tail_probability"] == pytest.approx(0.20)
    assert risk["var"] == pytest.approx(expected_var)
    assert risk["cvar"] == pytest.approx(np.mean([-0.10, -0.04]))
    assert risk["var_loss"] == pytest.approx(-expected_var)
    assert risk["cvar_loss"] == pytest.approx(0.07)
    assert risk["tail_count"] == 2

    distribution = fc.returns_distribution_values(
        returns,
        bins=4,
        bin_range=(-0.10, 0.10),
        confidence=0.80,
    )
    np.testing.assert_array_equal(distribution["counts"], [1, 2, 3, 1])
    np.testing.assert_allclose(distribution["probability"], [1 / 7, 2 / 7, 3 / 7, 1 / 7])
    np.testing.assert_allclose(distribution["bin_edges"], [-0.10, -0.05, 0.0, 0.05, 0.10])
    np.testing.assert_allclose(distribution["bin_centers"], [-0.075, -0.025, 0.025, 0.075])
    assert distribution["rows"] == 4
    assert distribution["markers"][0]["role"] == "var"
    assert distribution["markers"][0]["x"] == pytest.approx(expected_var)
    assert distribution["markers"][1]["role"] == "cvar"
    assert distribution["markers"][1]["x"] == pytest.approx(-0.07)


def test_returns_distribution_chart_materializes_histogram_and_markers():
    returns = np.array([-0.10, -0.04, -0.02, 0.0, 0.01, 0.03, 0.08])
    chart = fc.returns_distribution_chart(
        returns,
        bins=4,
        bin_range=(-0.10, 0.10),
        confidence=0.80,
        y="probability",
        title="risk",
        style={"bar_color": "#3366c7", "marker_color": "#dc3038"},
    )
    assert chart.figure().traces == []

    spec, _ = chart.build_payload()
    assert spec["title"] == "risk"
    assert spec["traces"] == []
    assert spec["x_axis"]["label"] == "Return"
    assert spec["x_axis"]["range"] == [-0.10, 0.10]
    assert spec["y_axis"]["label"] == "Probability"
    assert spec["y_axis"]["side"] == "right"

    assert [layer["kind"] for layer in spec["layers"]] == ["returns_distribution"]
    layer = spec["layers"][0]
    assert layer["style"]["bar_color"] == "#3366c7"
    assert layer["style"]["marker_color"] == "#dc3038"
    series = layer["props"]["series"]
    assert series["rows"] == 4
    assert series["y_mode"] == "probability"
    assert series["x_min"] == -0.10
    assert series["x_max"] == 0.10
    assert series["y_min"] == 0.0
    assert series["y_max"] > max(series["probability"])
    np.testing.assert_array_equal(series["counts"], [1, 2, 3, 1])
    np.testing.assert_allclose(series["probability"], [1 / 7, 2 / 7, 3 / 7, 1 / 7])
    np.testing.assert_allclose(series["y"], [1 / 7, 2 / 7, 3 / 7, 1 / 7])
    np.testing.assert_allclose(series["bin_edges"], [-0.10, -0.05, 0.0, 0.05, 0.10])
    assert series["markers"][0]["role"] == "var"
    assert series["markers"][0]["x"] == pytest.approx(np.quantile(returns, 0.20, method="linear"))
    assert series["markers"][1]["role"] == "cvar"
    assert series["markers"][1]["x"] == pytest.approx(-0.07)


def test_long_position_metrics_match_risk_model():
    pos = fc.long_position(
        source="price",
        entry=("2026-02-03", 100.0),
        stop=95.0,
        target=115.0,
        account_size=100_000.0,
        risk=0.01,
        instrument=fc.instrument(tick_size=0.01, point_value=1.0, lot_size=1.0, qty_precision=2),
    )
    metrics = pos.metrics()
    assert metrics["side"] == "long"
    assert metrics["risk_amount"] == 1000.0
    assert metrics["qty_risk"] == 200.0
    assert metrics["qty_leverage"] == 1000.0
    assert metrics["qty"] == 200.0
    assert metrics["risk_reward"] == 3.0
    assert metrics["target_ticks"] == 1500.0
    assert metrics["stop_ticks"] == 500.0
    assert metrics["profit_pnl"] == 3000.0
    assert metrics["loss_pnl"] == -1000.0
    assert metrics["target_account_balance"] == 103_000.0
    assert metrics["stop_account_balance"] == 99_000.0


def test_short_position_metrics_match_risk_model():
    pos = fc.short_position(
        source="price",
        entry=("2026-02-03", 100.0),
        stop=110.0,
        target=80.0,
        account_size=100_000.0,
        risk=1000.0,
        risk_mode="amount",
    )
    metrics = pos.metrics()
    assert metrics["side"] == "short"
    assert metrics["risk_amount"] == 1000.0
    assert metrics["qty"] == 100.0
    assert metrics["risk_reward"] == 2.0
    assert metrics["profit_pnl"] == 2000.0
    assert metrics["loss_pnl"] == -1000.0


def test_position_spec_is_serializable_and_preserves_anchors():
    pos = fc.long_position(
        source="price",
        id="risk-1",
        entry=("2026-02-03", 100.0),
        stop=95.0,
        target=115.0,
        end="2026-03-01",
    )
    spec = pos.to_spec()
    assert spec["role"] == "drawing"
    assert spec["kind"] == "position"
    assert spec["side"] == "long"
    assert spec["id"] == "risk-1"
    assert spec["anchors"]["entry"] == {"x": "2026-02-03", "y": 100.0}
    assert spec["anchors"]["stop"] == {"y": 95.0}
    assert spec["anchors"]["target"] == {"y": 115.0}
    assert spec["anchors"]["end"] == {"x": "2026-03-01"}
    assert spec["metrics"]["risk_reward"] == 3.0


def test_finance_chart_payload_carries_layers_and_tools():
    chart = fc.finance_chart(
        fc.candlestick(*_ohlc(), name="price"),
        fc.x_axis(type_="time"),
        fc.y_axis(label="price", side="right", scale="linear"),
        fc.anchored_vwap(source="price", anchor=(1, 100.0), bands=(1.0, 2.0), id="avwap-1"),
        fc.fixed_range_volume_profile(source="price", start=(1, 98.0), end=(4, 108.0), rows=24),
        fc.xabcd_pattern(
            source="price",
            validate="gartley",
            points=[(0, 98.0), (1, 106.0), (2, 101.0), (3, 109.0), (4, 103.0)],
        ),
        fc.finance_tools(
            active="long_position", snap="ohlc", selected="avwap-1", on_change=lambda _: None
        ),
        title="finance",
    )
    spec, _ = chart.build_payload()
    assert spec["title"] == "finance"
    assert spec["y_axis"]["side"] == "right"
    assert spec["traces"][0]["kind"] == "candlestick"
    assert spec["tools"]["active"] == "long_position"
    assert spec["tools"]["snap"] == "ohlc"
    assert spec["tools"]["selected"] == "avwap-1"
    assert spec["tools"]["events"] == ["change"]
    assert [layer["kind"] for layer in spec["layers"]] == [
        "anchored_vwap",
        "fixed_range_volume_profile",
        "xabcd_pattern",
    ]
    assert spec["layers"][0]["role"] == "study"
    assert spec["layers"][0]["anchors"]["anchor"] == {"x": 1, "y": 100.0}
    assert spec["layers"][0]["props"]["bands"] == [1.0, 2.0]
    assert spec["layers"][2]["anchors"]["X"] == {"x": 0, "y": 98.0}
    assert spec["layers"][2]["props"]["validate"] == "gartley"


def test_finance_chart_html_export_keeps_layer_spec():
    chart = fc.finance_chart(
        fc.candlestick(*_ohlc(), name="price"),
        fc.long_position(source="price", entry=(1, 101.0), stop=98.0, target=108.0, id="risk-1"),
        fc.finance_tools(active="long_position"),
        title="finance export",
    )
    html = chart.to_html()
    assert "<title>finance export</title>" in html
    assert '"layers":' in html
    assert '"kind":"position"' in html
    assert '"id":"risk-1"' in html
    assert '"tools":' in html


def test_forecast_and_measurement_layer_shapes():
    layers = [
        fc.position_forecast(source="price", start=(1, 100.0), target=(5, 120.0)),
        fc.bars_pattern(source="price", start=1, end=5, destination=(10, 100.0), flipped=True),
        fc.ghost_feed(source="price", anchor=(5, 102.0), bars=12, seed=7),
        fc.sector(source="price", origin=(5, 100.0), horizon=10, target=(10, 120.0)),
        fc.date_price_range(source="price", start=(1, 100.0), end=(5, 120.0)),
    ]
    specs = [layer.to_spec() for layer in layers]
    assert [spec["kind"] for spec in specs] == [
        "position_forecast",
        "bars_pattern",
        "ghost_feed",
        "sector",
        "date_price_range",
    ]
    assert specs[1]["props"]["flipped"] is True
    assert specs[2]["props"]["bars"] == 12
    assert specs[2]["props"]["seed"] == 7


def test_finance_validation_errors():
    with pytest.raises(ValueError, match="long position"):
        fc.long_position(source="price", entry=(1, 100.0), stop=105.0, target=115.0)
    with pytest.raises(ValueError, match="short position"):
        fc.short_position(source="price", entry=(1, 100.0), stop=95.0, target=80.0)
    with pytest.raises(ValueError, match="ABCD"):
        fc.abcd_pattern(points=[(1, 1.0)])
    with pytest.raises(ValueError, match="XABCD"):
        fc.xabcd_pattern(points=[(1, 1.0)])
    with pytest.raises(ValueError, match="value_area"):
        fc.fixed_range_volume_profile(source="price", start=1, end=2, value_area=1.5)
    with pytest.raises(ValueError, match="direction"):
        fc.ghost_feed(source="price", anchor=(1, 100.0), direction="sideways")
    with pytest.raises(ValueError, match="method"):
        fc.moving_average(source="price", method="wma")
    with pytest.raises(ValueError, match="deviations"):
        fc.bollinger_bands(source="price", deviations=0.0)
    with pytest.raises(ValueError, match="mode"):
        fc.equity_drawdown(equity=[1.0, 2.0], mode="bars")
    with pytest.raises(ValueError, match="exactly one"):
        fc.equity_drawdown(equity=[1.0], pnl=[1.0])
    with pytest.raises(ValueError, match="x"):
        fc.equity_drawdown(x=[1.0, 2.0, 3.0], pnl=[1.0], initial=100.0)
    with pytest.raises(ValueError, match="window"):
        fc.rsi(source="price", window=0)
    with pytest.raises(ValueError, match="fast"):
        fc.macd(source="price", fast=5, slow=3)
    with pytest.raises(ValueError, match="k_window"):
        fc.stochastic(source="price", k_window=0)
    with pytest.raises(ValueError, match="exactly one"):
        fc.equity_curve_values(returns=[0.01], pnl=[1.0])
    with pytest.raises(ValueError, match="confidence"):
        fc.var_cvar_values([0.01, -0.01], confidence=1.0)
    with pytest.raises(ValueError, match="positive"):
        fc.returns_distribution_values([0.01, -0.01], bins=0)
    with pytest.raises(ValueError, match="y"):
        fc.returns_distribution([0.01, -0.01], y="density")
