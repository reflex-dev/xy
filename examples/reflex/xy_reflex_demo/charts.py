"""Pure :mod:`xy` chart builders for the simulated terminal example.

The Reflex app wraps state-dependent builders with ``@reflex_xy.figure`` and
chooses whether fixed charts travel as direct payloads or ``inline()`` tokens.
Keeping this module framework-neutral makes the data and finance composition
cheap to test without starting a server.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np

import xy

from . import data

_BG = "#050505"
_PLOT_BG = "#090806"
_AMBER = "#f6c453"
_AMBER_DIM = "#9b7428"
_GRID = "#30240d"
_GREEN = "#35d07f"
_RED = "#ff5a5f"
_BLUE = "#5aa9ff"
_VIOLET = "#b892ff"

_FINANCE_STYLE = {
    "background": _BG,
    "color": _AMBER,
    "--chart-bg": _PLOT_BG,
    "--chart-grid": _GRID,
    "--chart-axis": _AMBER_DIM,
    "--chart-text": _AMBER,
    "--chart-crosshair": "#ffe19a",
    "--chart-tooltip-bg": "#17130a",
    "--chart-tooltip-text": "#fff1c2",
}


def _theme() -> xy.Theme:
    return xy.theme(
        background=_BG,
        plot_background=_PLOT_BG,
        grid_color=_GRID,
        axis_color=_AMBER_DIM,
        text_color=_AMBER,
        crosshair_color="#ffe19a",
        tooltip_bg="#17130a",
        tooltip_text="#fff1c2",
        palette=[_AMBER, _GREEN, _BLUE, _VIOLET, _RED, "#70d6ff"],
    )


def market_heatmap_chart() -> xy.Chart:
    symbols, ranges, values = data.market_heatmap_data()
    bound = max(1.0, float(np.max(np.abs(values))))
    return xy.heatmap_chart(
        xy.heatmap(
            values,
            x=symbols,
            y=ranges,
            name="return %",
            colormap="spectral",
            domain=(-bound, bound),
        ),
        xy.x_axis(tick_label_angle=-34, tick_label_anchor="end"),
        xy.y_axis(label="window"),
        xy.colorbar(title="return %"),
        _theme(),
        title="CROSS-ASSET RETURN MAP · SIMULATED",
        width="100%",
        height=260,
    )


def yield_curve_chart() -> xy.Chart:
    tenors, years, rates = data.yield_curve()
    return xy.line_chart(
        xy.line(years, rates, name="Treasury", color=_AMBER, width=2.0),
        xy.scatter(years, rates, name="tenors", color=_GREEN, size=7.0, opacity=0.95),
        xy.x_axis(label="maturity", tick_values=years, tick_labels=tenors),
        xy.y_axis(label="yield (%)", side="right", format=".2f"),
        xy.legend(show=False),
        _theme(),
        title="SIMULATED U.S. TREASURY CURVE",
        width="100%",
        height=260,
    )


def market_pulse_chart() -> xy.Chart:
    x, values = data.pulse_seed()
    return xy.line_chart(
        xy.line(x, values, name="pulse", color=_AMBER, width=1.8),
        xy.x_axis(show=False),
        xy.y_axis(label="normalized", side="right", tick_count=4),
        xy.legend(show=False),
        _theme(),
        title="LIVE MARKET PULSE · SIMULATED",
        width="100%",
        height=190,
        padding=(22, 44, 28, 14),
    )


def market_focus_chart() -> Any:
    """Build the landing-page finance chart from the native finance surface.

    The Markets workspace is the first screen a visitor sees, so it should not
    make the flagship ``FinanceChart`` look like a hidden Security-only detail.
    This fixed SPY view deliberately exercises the same candlestick, study,
    oscillator, projection, and finance-tool payload used by the state-backed
    Security workspace.
    """

    return security_chart(
        "SPY",
        range_key="6M",
        resolution="1D",
        overlays=("SMA 20", "Anchored VWAP", "Volume Profile"),
        oscillator="MACD",
        drawing="Forecast",
    )


def _canonical(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


_OVERLAYS = {
    "sma20": "sma20",
    "ema50": "ema50",
    "bollinger": "bollinger",
    "bollingerbands": "bollinger",
    "vwap": "vwap",
    "anchoredvwap": "anchored_vwap",
    "avwap": "anchored_vwap",
    "volumeprofile": "volume_profile",
    "anchoredvolumeprofile": "volume_profile",
}
_OSCILLATORS = {
    "": "none",
    "none": "none",
    "rsi": "rsi",
    "macd": "macd",
    "stochastic": "stochastic",
}
_DRAWINGS = {
    "": "none",
    "none": "none",
    "long": "long_position",
    "longposition": "long_position",
    "short": "short_position",
    "shortposition": "short_position",
    "forecast": "forecast",
    "positionforecast": "forecast",
    "barspattern": "bars_pattern",
    "ghost": "ghost_feed",
    "ghostfeed": "ghost_feed",
    "xabcd": "xabcd",
    "xabcdpattern": "xabcd",
}


def _number(ticket: Mapping[str, Any], key: str) -> float:
    try:
        value = float(ticket[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key.replace('_', ' ')} must be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{key.replace('_', ' ')} must be finite")
    return value


def _ticket_drawing(
    ticket: Mapping[str, Any],
    *,
    anchor: Any = (0.0, 1.0),
    end: Any | None = None,
) -> Any:
    side = str(ticket.get("side", "long")).lower().strip()
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    entry = _number(ticket, "entry")
    stop = _number(ticket, "stop")
    target = _number(ticket, "target")
    account_size = _number(ticket, "account_size")
    risk_percent = _number(ticket, "risk_percent")
    if account_size <= 0:
        raise ValueError("account size must be positive")
    if not 0 < risk_percent <= 100:
        raise ValueError("risk percent must be greater than 0 and at most 100")
    symbol = str(ticket.get("symbol", "SPY"))
    meta = data.instrument(symbol)
    qty_precision = 4 if meta.asset_class in {"FX", "Crypto"} else 2
    instrument = xy.instrument(
        tick_size=meta.tick_size,
        point_value=1.0,
        lot_size=1.0,
        qty_precision=qty_precision,
        currency=meta.currency,
    )
    kwargs = {
        "source": "price",
        "entry": (anchor, entry) if not isinstance(anchor, tuple) else (anchor[0], entry),
        "stop": stop,
        "target": target,
        "account_size": account_size,
        "risk": risk_percent / 100.0,
        "risk_mode": "fraction",
        "instrument": instrument,
        "id": "paper-risk",
        "style": {"profit_color": _GREEN, "loss_color": _RED, "text_color": _AMBER},
    }
    if end is not None:
        kwargs["end"] = end
    return xy.long_position(**kwargs) if side == "long" else xy.short_position(**kwargs)


def ticket_metrics(ticket: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate a paper ticket and return a small JSON-safe metric mapping."""

    if not ticket:
        return {"valid": False, "error": "Complete the paper ticket to preview risk."}
    try:
        drawing = _ticket_drawing(ticket)
        metrics = drawing.metrics()
    except (TypeError, ValueError) as exc:
        return {"valid": False, "error": str(exc)}
    return {
        "valid": True,
        "error": "",
        "side": metrics["side"],
        "entry": float(metrics["entry"]),
        "stop": float(metrics["stop"]),
        "target": float(metrics["target"]),
        "account_size": float(metrics["account_size"]),
        "risk_percent": float(ticket["risk_percent"]),
        "risk_amount": float(metrics["risk_amount"]),
        "quantity": float(metrics["qty_display"]),
        "risk_reward": float(metrics["risk_reward"]),
        "reward_risk": float(metrics["risk_reward"]),
        "profit_pnl": float(metrics["profit_pnl"]),
        "loss_pnl": float(metrics["loss_pnl"]),
    }


def _default_ticket(symbol: str, side: str, last: float) -> dict[str, Any]:
    if side == "long":
        stop, target = last * 0.97, last * 1.06
    else:
        stop, target = last * 1.03, last * 0.94
    return {
        "symbol": symbol,
        "side": side,
        "entry": last,
        "stop": stop,
        "target": target,
        "account_size": 100_000.0,
        "risk_percent": 1.0,
    }


def _future_date(days: int) -> str:
    value = np.datetime64(data.AS_OF.isoformat(), "D") + np.timedelta64(days, "D")
    return str(np.datetime_as_string(value, unit="D"))


def security_chart(
    symbol: str,
    range_key: str = "1Y",
    resolution: str = "1D",
    overlays: Iterable[str] = (),
    oscillator: str = "None",
    drawing: str = "None",
    ticket: Mapping[str, Any] | None = None,
) -> Any:
    """Build the state-dependent OHLCV finance chart for a security workspace."""

    values = data.history(symbol, resolution=resolution, range_key=range_key)
    meta = data.instrument(symbol)
    overlay_values = (overlays,) if isinstance(overlays, str) else tuple(overlays)
    normalized_overlays: list[str] = []
    for item in overlay_values:
        try:
            normalized = _OVERLAYS[_canonical(str(item))]
        except KeyError as exc:
            raise ValueError(f"unknown finance overlay {item!r}") from exc
        if normalized not in normalized_overlays:
            normalized_overlays.append(normalized)
    try:
        normalized_oscillator = _OSCILLATORS[_canonical(oscillator)]
    except KeyError as exc:
        raise ValueError(f"unknown oscillator {oscillator!r}") from exc
    try:
        normalized_drawing = _DRAWINGS[_canonical(drawing)]
    except KeyError as exc:
        raise ValueError(f"unknown drawing preset {drawing!r}") from exc

    layers: list[Any] = [
        xy.volume_bars(
            source="price",
            pane="volume",
            id="volume",
            style={"up_color": _GREEN, "down_color": _RED, "opacity": 0.62},
        )
    ]
    for overlay in normalized_overlays:
        if overlay == "sma20":
            layers.append(
                xy.moving_average(
                    source="price",
                    window=20,
                    method="sma",
                    id="SMA 20",
                    style={"color": _BLUE, "width": 1.35},
                )
            )
        elif overlay == "ema50":
            layers.append(
                xy.moving_average(
                    source="price",
                    window=50,
                    method="ema",
                    id="EMA 50",
                    style={"color": _VIOLET, "width": 1.35},
                )
            )
        elif overlay == "bollinger":
            layers.append(
                xy.bollinger_bands(
                    source="price",
                    window=20,
                    deviations=2.0,
                    id="Bollinger",
                    style={"color": "#70d6ff", "band_opacity": 0.44},
                )
            )
        elif overlay == "vwap":
            layers.append(
                xy.vwap(source="price", id="VWAP", style={"color": _GREEN, "width": 1.45})
            )
        elif overlay == "anchored_vwap":
            layers.append(
                xy.anchored_vwap(
                    source="price",
                    anchor={"bar": max(0, len(values) - 80)},
                    bands=(1.0,),
                    id="Anchored VWAP",
                    style={"color": _AMBER, "band_opacity": 0.42},
                )
            )
        elif overlay == "volume_profile":
            layers.append(
                xy.anchored_volume_profile(
                    source="price",
                    anchor={"bar": max(0, len(values) - 120)},
                    rows=30,
                    volume="up_down",
                    value_area=0.70,
                    id="Volume profile",
                    style={"up_color": _GREEN, "down_color": _RED},
                )
            )

    if normalized_oscillator == "rsi":
        layers.append(
            xy.rsi(source="price", pane="oscillator", id="RSI 14", style={"color": _AMBER})
        )
    elif normalized_oscillator == "macd":
        layers.append(
            xy.macd(
                source="price",
                pane="oscillator",
                id="MACD",
                style={"macd_color": _BLUE, "signal_color": _AMBER},
            )
        )
    elif normalized_oscillator == "stochastic":
        layers.append(
            xy.stochastic(
                source="price",
                pane="oscillator",
                id="Stochastic",
                style={"k_color": _AMBER, "d_color": _VIOLET},
            )
        )

    last = float(values.close[-1])
    if normalized_drawing in {"long_position", "short_position"}:
        selected_side = "long" if normalized_drawing == "long_position" else "short"
        selected_ticket = dict(
            _default_ticket(meta.symbol, selected_side, last) if ticket is None else ticket
        )
        selected_ticket["side"] = selected_side
        selected_ticket.setdefault("symbol", meta.symbol)
        if ticket_metrics(selected_ticket)["valid"]:
            start_index = max(0, len(values) - 32)
            layers.append(
                _ticket_drawing(
                    selected_ticket,
                    anchor=str(values.dates[start_index]),
                    end=_future_date(21),
                )
            )
    elif normalized_drawing == "forecast":
        start_index = max(0, len(values) - 24)
        layers.append(
            xy.position_forecast(
                source="price",
                start=(str(values.dates[start_index]), float(values.close[start_index])),
                target=(_future_date(35), last * 1.08),
                id="forecast",
                style={"color": _AMBER, "fill_color": "rgba(246,196,83,0.12)"},
            )
        )
    elif normalized_drawing == "bars_pattern":
        layers.append(
            xy.bars_pattern(
                source="price",
                start={"bar": max(0, len(values) - 64)},
                end={"bar": max(0, len(values) - 40)},
                destination=(_future_date(7), last),
                normalize=True,
                max_bars=30,
                id="bars-pattern",
                style={"up_color": _GREEN, "down_color": _RED, "opacity": 0.58},
            )
        )
    elif normalized_drawing == "ghost_feed":
        layers.append(
            xy.ghost_feed(
                source="price",
                anchor=(_future_date(7), last),
                direction="up",
                bars=24,
                avg_hl_ticks=60.0,
                variance_ticks=35.0,
                tick_size=meta.tick_size,
                seed=meta.seed + 900,
                id="ghost-feed",
                style={"up_color": _GREEN, "down_color": _RED, "opacity": 0.48},
            )
        )
    elif normalized_drawing == "xabcd":
        indices = np.linspace(max(0, len(values) - 90), len(values) - 1, 5).round().astype(int)
        points = [(str(values.dates[index]), float(values.close[index])) for index in indices]
        layers.append(
            xy.xabcd_pattern(
                source="price", points=points, id="xabcd", style={"color": _VIOLET, "width": 1.5}
            )
        )

    active_tool = normalized_drawing if normalized_drawing != "none" else "crosshair"
    return xy.finance_chart(
        xy.candlestick(
            values.dates,
            values.open,
            values.high,
            values.low,
            values.close,
            volume=values.volume,
            id="price",
            name=f"{meta.symbol} OHLCV",
            up_color=_GREEN,
            down_color=_RED,
            wick_color=_AMBER_DIM,
        ),
        *layers,
        xy.x_axis(type_="time", tick_count=7),
        xy.y_axis(label=f"{meta.currency} price", side="right", format=f".{meta.price_decimals}f"),
        xy.legend(loc="upper left", ncols=3),
        xy.finance_tools(
            active=active_tool,
            snap="ohlc",
            selected="paper-risk" if active_tool.endswith("position") else None,
        ),
        title=f"{meta.symbol} · {resolution.upper()} · {range_key.upper()} · SIMULATED",
        width="100%",
        height=620,
        style=_FINANCE_STYLE,
    )


def portfolio_performance_chart() -> Any:
    series = data.portfolio_equity("1Y")
    return xy.finance_chart(
        xy.equity_drawdown(
            x=series.dates,
            equity=series.equity,
            pane="drawdown",
            mode="area",
            id="portfolio-performance",
            name="NAV",
            style={"color": _AMBER, "fill_color": _AMBER, "drawdown_color": _RED},
        ),
        xy.x_axis(type_="time", tick_count=6),
        xy.y_axis(label="NAV (USD)", side="right"),
        title="PORTFOLIO NAV + DRAWDOWN · SIMULATED",
        width="100%",
        height=410,
        style=_FINANCE_STYLE,
    )


def portfolio_allocation_chart() -> xy.Chart:
    labels, weights = data.portfolio_allocation()
    colors = (_AMBER, _BLUE, _VIOLET, _GREEN, "#70d6ff", "#ff9f43", "#d5b3ff", _RED)
    marks = [
        xy.bar([label], [float(weight)], name=label, color=colors[index % len(colors)], width=0.72)
        for index, (label, weight) in enumerate(zip(labels, weights, strict=True))
    ]
    return xy.bar_chart(
        *marks,
        xy.x_axis(label="security"),
        xy.y_axis(label="weight (%)", side="right"),
        xy.legend(show=False),
        _theme(),
        title="PORTFOLIO ALLOCATION",
        width="100%",
        height=285,
    )


def portfolio_contribution_chart() -> xy.Chart:
    labels, contribution = data.portfolio_contribution()
    marks = [
        xy.bar(
            [label], [float(value)], name=label, color=_GREEN if value >= 0 else _RED, width=0.72
        )
        for label, value in zip(labels, contribution, strict=True)
    ]
    return xy.bar_chart(
        *marks,
        xy.hline(0.0, color=_AMBER_DIM, width=1.0),
        xy.x_axis(label="security"),
        xy.y_axis(label="unrealized P&L (USD)", side="right"),
        xy.legend(show=False),
        _theme(),
        title="P&L CONTRIBUTION",
        width="100%",
        height=285,
    )


def portfolio_exposure_chart() -> xy.Chart:
    labels, exposures = data.sector_exposures()
    return xy.bar_chart(
        xy.bar(
            labels, exposures, orientation="horizontal", name="exposure", color=_AMBER, width=0.68
        ),
        xy.x_axis(label="NAV exposure (%)"),
        xy.y_axis(label="sector"),
        xy.legend(show=False),
        _theme(),
        title="SECTOR EXPOSURE",
        width="100%",
        height=285,
    )


def _confidence(value: float | int | str) -> float:
    if isinstance(value, str):
        value = float(value.strip().rstrip("%"))
    normalized = float(value)
    if normalized > 1.0:
        normalized /= 100.0
    if normalized not in {0.95, 0.99}:
        raise ValueError("confidence must be 95% or 99%")
    return normalized


def risk_distribution_chart(confidence: float | int | str = 0.95) -> Any:
    normalized = _confidence(confidence)
    returns = data.portfolio_returns("1Y")
    return xy.finance_chart(
        xy.returns_distribution(
            returns,
            bins=46,
            confidence=normalized,
            y="probability",
            id="portfolio-returns",
            style={"bar_color": _AMBER, "marker_color": _RED, "tail_color": "#71282b"},
        ),
        xy.x_axis(label="daily return", format=".1%"),
        xy.y_axis(label="probability", side="right", format=".1%"),
        title=f"PORTFOLIO VaR / CVaR · {normalized:.0%} CONFIDENCE",
        width="100%",
        height=360,
        style=_FINANCE_STYLE,
    )


def risk_correlation_chart() -> xy.Chart:
    labels, matrix = data.correlation_matrix()
    return xy.heatmap_chart(
        xy.heatmap(
            matrix, x=labels, y=labels, name="correlation", colormap="coolwarm", domain=(-1.0, 1.0)
        ),
        xy.x_axis(tick_label_angle=-34, tick_label_anchor="end"),
        xy.y_axis(),
        xy.colorbar(title="ρ"),
        _theme(),
        title="1Y RETURN CORRELATION",
        width="100%",
        height=360,
    )


def risk_factor_chart() -> xy.Chart:
    labels, exposures = data.factor_exposures()
    values = exposures * 100.0
    return xy.bar_chart(
        xy.bar(
            labels, values, orientation="horizontal", name="exposure", color=_VIOLET, width=0.68
        ),
        xy.x_axis(label="exposure / beta × 100"),
        xy.y_axis(label="factor"),
        xy.legend(show=False),
        _theme(),
        title="FACTOR EXPOSURE",
        width="100%",
        height=320,
    )


def abbreviated_spec(chart: Any | None = None) -> dict[str, Any]:
    """Return a deliberately small, JSON-safe chart/layer description."""

    selected = chart or security_chart(
        "AAPL",
        range_key="6M",
        overlays=("SMA 20", "VWAP"),
        oscillator="RSI",
    )
    if hasattr(selected, "build_payload"):
        spec, _buffers = selected.build_payload()
    else:
        spec, _buffers = selected.figure().build_payload()
    traces = [
        {
            "kind": str(trace.get("kind", "")),
            "name": str(trace.get("name") or ""),
        }
        for trace in spec.get("traces", [])
    ]
    layers = []
    for layer in spec.get("layers", []):
        props = layer.get("props") or {}
        materialized = (
            props.get("series")
            or props.get("bars")
            or props.get("profile")
            or props.get("pattern")
            or props.get("feed")
            or {}
        )
        layers.append(
            {
                "role": str(layer.get("role", "")),
                "kind": str(layer.get("kind", "")),
                "id": str(layer.get("id") or ""),
                "pane": str(props.get("pane") or ""),
                "rows": int(materialized.get("rows", 0))
                if isinstance(materialized, Mapping)
                else 0,
            }
        )
    return {
        "title": str(spec.get("title") or ""),
        "trace_count": len(traces),
        "traces": traces,
        "layer_count": len(layers),
        "layers": layers,
        "x_axis": {
            "label": str((spec.get("x_axis") or {}).get("label") or ""),
            "type": str(
                (spec.get("x_axis") or {}).get("kind")
                or (spec.get("x_axis") or {}).get("type")
                or ""
            ),
        },
        "y_axis": {
            "label": str((spec.get("y_axis") or {}).get("label") or ""),
            "type": str(
                (spec.get("y_axis") or {}).get("kind")
                or (spec.get("y_axis") or {}).get("type")
                or ""
            ),
        },
        "tools": spec.get("tools") or {},
    }


MARKET_FOCUS_CHART = market_focus_chart()
MARKET_HEATMAP_CHART = market_heatmap_chart()
YIELD_CURVE_CHART = yield_curve_chart()


__all__ = [
    "MARKET_FOCUS_CHART",
    "MARKET_HEATMAP_CHART",
    "YIELD_CURVE_CHART",
    "abbreviated_spec",
    "market_focus_chart",
    "market_heatmap_chart",
    "market_pulse_chart",
    "portfolio_allocation_chart",
    "portfolio_contribution_chart",
    "portfolio_exposure_chart",
    "portfolio_performance_chart",
    "risk_correlation_chart",
    "risk_distribution_chart",
    "risk_factor_chart",
    "security_chart",
    "ticket_metrics",
    "yield_curve_chart",
]
