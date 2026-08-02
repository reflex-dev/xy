"""Deterministic simulated market data for the XY terminal example.

Nothing in this module reaches the network.  Every quote, story, calendar
entry, portfolio value, and risk result is reproducible from the fixed
``AS_OF`` date and seeds below.  Large NumPy columns live behind module-level
caches rather than in Reflex state.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from functools import cache, lru_cache
from typing import Any

import numpy as np

AS_OF = date(2026, 7, 31)
SIMULATED_DATA_LABEL = f"SIMULATED DATA · AS OF {AS_OF.isoformat()}"

_AS_OF64 = np.datetime64(AS_OF.isoformat(), "D")
_START64 = np.datetime64("2023-08-01", "D")
_RANGE_DAYS = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366}
_RESOLUTIONS = frozenset({"1D", "1W"})
_RANGES = frozenset((*_RANGE_DAYS, "MAX"))


def _readonly(values: Any, *, dtype: Any = np.float64) -> np.ndarray:
    array = np.ascontiguousarray(values, dtype=dtype)
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True)
class Instrument:
    """Metadata and simulation parameters for a terminal security."""

    symbol: str
    name: str
    asset_class: str
    sector: str
    currency: str
    exchange: str
    tick_size: float
    price_decimals: int
    base_price: float
    annual_drift: float
    annual_volatility: float
    beta: float
    base_volume: float
    seed: int


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    name: str
    asset_class: str
    last: float
    change: float
    change_percent: float
    open: float
    high: float
    low: float
    volume: float
    as_of: str = AS_OF.isoformat()


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: float
    average_cost: float
    account: str = "SIM-PRIMARY"


@dataclass(frozen=True, slots=True)
class NewsItem:
    id: str
    timestamp: str
    source: str
    headline: str
    summary: str
    symbols: tuple[str, ...]
    sentiment: str
    impact: str


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str
    timestamp: str
    country: str
    event: str
    importance: str
    actual: str
    forecast: str
    previous: str


@dataclass(frozen=True, slots=True)
class OHLCV:
    """Read-only aligned OHLCV columns."""

    dates: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    symbol: str
    resolution: str
    range_key: str

    def __post_init__(self) -> None:
        dates = _readonly(self.dates, dtype="datetime64[D]")
        columns = tuple(
            _readonly(getattr(self, name)) for name in ("open", "high", "low", "close", "volume")
        )
        size = len(dates)
        if any(column.ndim != 1 or len(column) != size for column in columns):
            raise ValueError("OHLCV columns must be aligned one-dimensional arrays")
        if size and not all(np.isfinite(column).all() for column in columns):
            raise ValueError("OHLCV columns must contain only finite values")
        open_, high, low, close, volume = columns
        if np.any(high < np.maximum(open_, close)) or np.any(low > np.minimum(open_, close)):
            raise ValueError("OHLCV high/low invariants are violated")
        if np.any(low <= 0) or np.any(volume < 0):
            raise ValueError("OHLCV prices must be positive and volume non-negative")
        object.__setattr__(self, "dates", dates)
        for name, column in zip(("open", "high", "low", "close", "volume"), columns, strict=True):
            object.__setattr__(self, name, column)

    @property
    def x(self) -> np.ndarray:
        return self.dates

    def __len__(self) -> int:
        return len(self.dates)


@dataclass(frozen=True, slots=True)
class PortfolioSeries:
    dates: np.ndarray
    equity: np.ndarray
    returns: np.ndarray
    pnl: np.ndarray

    def __post_init__(self) -> None:
        dates = _readonly(self.dates, dtype="datetime64[D]")
        equity = _readonly(self.equity)
        returns = _readonly(self.returns)
        pnl = _readonly(self.pnl)
        if (
            len(dates) != len(equity)
            or len(pnl) != len(equity)
            or len(returns) != max(0, len(equity) - 1)
        ):
            raise ValueError("portfolio series columns are not aligned")
        if (
            not np.isfinite(equity).all()
            or not np.isfinite(returns).all()
            or not np.isfinite(pnl).all()
        ):
            raise ValueError("portfolio series must contain only finite values")
        object.__setattr__(self, "dates", dates)
        object.__setattr__(self, "equity", equity)
        object.__setattr__(self, "returns", returns)
        object.__setattr__(self, "pnl", pnl)


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    description: str
    confidence: float
    pnl: float
    loss_percent: float
    nav_after: float


INSTRUMENTS: Mapping[str, Instrument] = {
    item.symbol: item
    for item in (
        Instrument(
            "SPY",
            "S&P 500 ETF",
            "Equity ETF",
            "Broad Market",
            "USD",
            "ARCX",
            0.01,
            2,
            420.0,
            0.085,
            0.17,
            1.00,
            74_000_000,
            101,
        ),
        Instrument(
            "AAPL",
            "Apple Inc.",
            "Equity",
            "Technology",
            "USD",
            "XNAS",
            0.01,
            2,
            155.0,
            0.10,
            0.25,
            1.18,
            58_000_000,
            103,
        ),
        Instrument(
            "MSFT",
            "Microsoft Corp.",
            "Equity",
            "Technology",
            "USD",
            "XNAS",
            0.01,
            2,
            310.0,
            0.11,
            0.23,
            1.08,
            24_000_000,
            107,
        ),
        Instrument(
            "NVDA",
            "NVIDIA Corp.",
            "Equity",
            "Technology",
            "USD",
            "XNAS",
            0.01,
            2,
            44.0,
            0.18,
            0.48,
            1.62,
            310_000_000,
            109,
        ),
        Instrument(
            "JPM",
            "JPMorgan Chase",
            "Equity",
            "Financials",
            "USD",
            "XNYS",
            0.01,
            2,
            145.0,
            0.08,
            0.24,
            1.10,
            9_500_000,
            113,
        ),
        Instrument(
            "XOM",
            "Exxon Mobil",
            "Equity",
            "Energy",
            "USD",
            "XNYS",
            0.01,
            2,
            102.0,
            0.055,
            0.25,
            0.88,
            17_000_000,
            127,
        ),
        Instrument(
            "EURUSD",
            "Euro / U.S. Dollar",
            "FX",
            "G10 FX",
            "USD",
            "OTC",
            0.0001,
            4,
            1.09,
            0.002,
            0.085,
            0.08,
            5_200_000_000,
            131,
        ),
        Instrument(
            "USDJPY",
            "U.S. Dollar / Yen",
            "FX",
            "G10 FX",
            "JPY",
            "OTC",
            0.01,
            2,
            142.0,
            0.005,
            0.10,
            0.12,
            4_600_000_000,
            137,
        ),
        Instrument(
            "XAUUSD",
            "Gold Spot / U.S. Dollar",
            "Commodity",
            "Metals",
            "USD",
            "OTC",
            0.10,
            1,
            1_940.0,
            0.06,
            0.18,
            0.18,
            185_000,
            139,
        ),
        Instrument(
            "BTCUSD",
            "Bitcoin / U.S. Dollar",
            "Crypto",
            "Digital Assets",
            "USD",
            "24/7",
            0.10,
            1,
            29_000.0,
            0.20,
            0.62,
            1.25,
            31_000,
            149,
        ),
    )
}

_SYMBOLS = tuple(INSTRUMENTS)
_WATCHLIST = _SYMBOLS
_PORTFOLIO_CASH = 175_000.0
_POSITIONS = (
    Position("SPY", 180.0, 468.20),
    Position("AAPL", 240.0, 181.35),
    Position("MSFT", 120.0, 374.60),
    Position("NVDA", 480.0, 92.80),
    Position("JPM", 190.0, 188.10),
    Position("XOM", 260.0, 109.40),
    Position("XAUUSD", 16.0, 2_180.0),
    Position("BTCUSD", 0.75, 54_500.0),
)


def instrument_symbols() -> tuple[str, ...]:
    return _SYMBOLS


def instrument(symbol: str) -> Instrument:
    key = symbol.upper().replace("/", "").strip()
    try:
        return INSTRUMENTS[key]
    except KeyError as exc:
        raise ValueError(f"unknown simulated instrument {symbol!r}") from exc


@lru_cache(maxsize=1)
def _business_dates() -> np.ndarray:
    dates = np.arange(_START64, _AS_OF64 + np.timedelta64(1, "D"), dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)]
    return _readonly(dates, dtype="datetime64[D]")


@lru_cache(maxsize=1)
def _market_factors() -> tuple[np.ndarray, Mapping[str, np.ndarray]]:
    n = len(_business_dates())
    rng = np.random.default_rng(20260802)
    market = rng.standard_normal(n)
    class_seeds = {"Equity ETF": 211, "Equity": 223, "FX": 227, "Commodity": 229, "Crypto": 233}
    factors = {
        name: np.random.default_rng(seed).standard_normal(n) for name, seed in class_seeds.items()
    }
    return _readonly(market), {name: _readonly(values) for name, values in factors.items()}


@cache
def _daily_history(symbol: str) -> OHLCV:
    meta = instrument(symbol)
    dates = _business_dates()
    market, class_factors = _market_factors()
    rng = np.random.default_rng(meta.seed)
    idiosyncratic = rng.standard_normal(len(dates))
    raw = meta.beta * 0.46 * market + 0.34 * class_factors[meta.asset_class] + 0.72 * idiosyncratic
    raw = (raw - float(np.mean(raw))) / float(np.std(raw))
    daily_sigma = meta.annual_volatility / math.sqrt(252.0)
    log_returns = meta.annual_drift / 252.0 - 0.5 * daily_sigma**2 + daily_sigma * raw
    close = meta.base_price * np.exp(np.cumsum(log_returns))

    previous = np.concatenate(([meta.base_price], close[:-1]))
    overnight = rng.normal(0.0, daily_sigma * 0.20, len(dates))
    open_ = previous * np.exp(overnight)
    spread = np.maximum(
        np.abs(rng.normal(daily_sigma * 0.48, daily_sigma * 0.16, len(dates))),
        daily_sigma * 0.08,
    )
    high = np.maximum(open_, close) * (1.0 + spread)
    low = np.minimum(open_, close) * np.maximum(
        0.02, 1.0 - spread * rng.uniform(0.72, 1.12, len(dates))
    )
    volume = meta.base_volume * rng.lognormal(mean=-0.08, sigma=0.33, size=len(dates))
    volume *= 1.0 + np.minimum(np.abs(log_returns) / max(daily_sigma, 1e-12), 4.0) * 0.15
    return OHLCV(dates, open_, high, low, close, volume, meta.symbol, "1D", "MAX")


def _weekly(daily: OHLCV) -> OHLCV:
    python_dates = daily.dates.astype(object)
    week_keys = np.fromiter(
        (value.isocalendar().year * 100 + value.isocalendar().week for value in python_dates),
        dtype=np.int64,
        count=len(python_dates),
    )
    starts = np.flatnonzero(np.r_[True, week_keys[1:] != week_keys[:-1]])
    ends = np.r_[starts[1:], len(week_keys)]
    return OHLCV(
        daily.dates[ends - 1],
        daily.open[starts],
        np.asarray(
            [np.max(daily.high[start:end]) for start, end in zip(starts, ends, strict=True)]
        ),
        np.asarray([np.min(daily.low[start:end]) for start, end in zip(starts, ends, strict=True)]),
        daily.close[ends - 1],
        np.asarray(
            [np.sum(daily.volume[start:end]) for start, end in zip(starts, ends, strict=True)]
        ),
        daily.symbol,
        "1W",
        "MAX",
    )


def _slice_history(source: OHLCV, range_key: str) -> OHLCV:
    if range_key == "MAX":
        return source
    cutoff = _AS_OF64 - np.timedelta64(_RANGE_DAYS[range_key], "D")
    start = int(np.searchsorted(source.dates, cutoff, side="left"))
    return OHLCV(
        source.dates[start:],
        source.open[start:],
        source.high[start:],
        source.low[start:],
        source.close[start:],
        source.volume[start:],
        source.symbol,
        source.resolution,
        range_key,
    )


@cache
def _history_cached(symbol: str, resolution: str, range_key: str) -> OHLCV:
    daily = _daily_history(symbol)
    source = daily if resolution == "1D" else _weekly(daily)
    return _slice_history(source, range_key)


def history(symbol: str, resolution: str = "1D", range_key: str = "MAX") -> OHLCV:
    """Return cached read-only history for a supported symbol/resolution/range."""

    key = instrument(symbol).symbol
    normalized_resolution = resolution.upper().strip()
    normalized_range = range_key.upper().strip()
    if normalized_resolution not in _RESOLUTIONS:
        raise ValueError(f"resolution must be one of {sorted(_RESOLUTIONS)}")
    if normalized_range not in _RANGES:
        raise ValueError(f"range_key must be one of {sorted(_RANGES)}")
    return _history_cached(key, normalized_resolution, normalized_range)


@cache
def quote(symbol: str) -> Quote:
    meta = instrument(symbol)
    values = history(meta.symbol)
    previous = float(values.close[-2])
    last = float(values.close[-1])
    change = last - previous
    return Quote(
        symbol=meta.symbol,
        name=meta.name,
        asset_class=meta.asset_class,
        last=last,
        change=change,
        change_percent=change / previous * 100.0,
        open=float(values.open[-1]),
        high=float(values.high[-1]),
        low=float(values.low[-1]),
        volume=float(values.volume[-1]),
    )


def _quote_row(value: Quote) -> dict[str, Any]:
    row = asdict(value)
    row["direction"] = "UP" if value.change > 0 else "DOWN" if value.change < 0 else "FLAT"
    row["last_display"] = f"{value.last:,.{instrument(value.symbol).price_decimals}f}"
    row["change_display"] = f"{value.change:+,.{instrument(value.symbol).price_decimals}f}"
    row["change_percent_display"] = f"{value.change_percent:+.2f}%"
    return row


def watchlist_rows() -> tuple[dict[str, Any], ...]:
    return tuple(_quote_row(quote(symbol)) for symbol in _WATCHLIST)


def movers(limit: int = 5) -> tuple[Quote, ...]:
    if limit <= 0:
        return ()
    values = sorted(
        (quote(symbol) for symbol in _WATCHLIST),
        key=lambda item: abs(item.change_percent),
        reverse=True,
    )
    return tuple(values[:limit])


def breadth_metrics() -> dict[str, float | int]:
    equity_symbols = tuple(
        symbol
        for symbol, meta in INSTRUMENTS.items()
        if meta.asset_class in {"Equity", "Equity ETF"}
    )
    quotes = tuple(quote(symbol) for symbol in equity_symbols)
    above_20d = sum(
        history(symbol, range_key="1M").close[-1] > np.mean(history(symbol, range_key="1M").close)
        for symbol in equity_symbols
    )
    advances = sum(value.change > 0 for value in quotes)
    return {
        "advancers": advances,
        "decliners": len(quotes) - advances,
        "advance_decline": float(advances - (len(quotes) - advances)),
        "average_change_percent": float(np.mean([value.change_percent for value in quotes])),
        "above_20d": int(above_20d),
        "universe": len(quotes),
    }


def market_heatmap_data() -> tuple[tuple[str, ...], tuple[str, ...], np.ndarray]:
    ranges = ("1D", "1M", "3M")
    matrix = np.empty((len(ranges), len(_SYMBOLS)), dtype=np.float64)
    for row, range_key in enumerate(ranges):
        for column, symbol in enumerate(_SYMBOLS):
            values = history(symbol, range_key="MAX" if range_key == "1D" else range_key)
            first = float(values.close[-2] if range_key == "1D" else values.close[0])
            matrix[row, column] = (float(values.close[-1]) / first - 1.0) * 100.0
    return _SYMBOLS, ranges, _readonly(matrix)


def yield_curve() -> tuple[tuple[str, ...], np.ndarray, np.ndarray]:
    tenors = ("3M", "6M", "1Y", "2Y", "5Y", "10Y", "20Y", "30Y")
    years = _readonly([0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0])
    rates = _readonly([4.68, 4.49, 4.18, 3.96, 4.08, 4.31, 4.61, 4.52])
    return tenors, years, rates


@lru_cache(maxsize=1)
def pulse_seed() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(991)
    x = np.arange(36, dtype=np.float64)
    y = 100.0 + np.cumsum(rng.normal(0.0, 0.16, len(x)))
    return _readonly(x), _readonly(y)


def positions() -> tuple[Position, ...]:
    return _POSITIONS


def position_rows() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in _POSITIONS:
        last = quote(item.symbol).last
        market_value = item.quantity * last
        cost = item.quantity * item.average_cost
        pnl = market_value - cost
        rows.append(
            {
                **asdict(item),
                "last": last,
                "market_value": market_value,
                "cost_basis": cost,
                "pnl": pnl,
                "pnl_percent": pnl / cost * 100.0,
                "pnl_pct": pnl / cost * 100.0,
            }
        )
    return tuple(rows)


def portfolio_summary() -> dict[str, float]:
    rows = position_rows()
    market_value = float(sum(row["market_value"] for row in rows))
    cost_basis = float(sum(row["cost_basis"] for row in rows))
    pnl = market_value - cost_basis
    nav = _PORTFOLIO_CASH + market_value
    return {
        "cash": _PORTFOLIO_CASH,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "pnl": pnl,
        "pnl_percent": pnl / cost_basis * 100.0,
        "nav": nav,
        "gross_exposure_percent": market_value / nav * 100.0,
    }


@cache
def portfolio_equity(range_key: str = "MAX") -> PortfolioSeries:
    normalized_range = range_key.upper().strip()
    if normalized_range not in _RANGES:
        raise ValueError(f"range_key must be one of {sorted(_RANGES)}")
    source = history(_POSITIONS[0].symbol, range_key=normalized_range)
    equity = np.full(len(source), _PORTFOLIO_CASH, dtype=np.float64)
    for item in _POSITIONS:
        equity += item.quantity * history(item.symbol, range_key=normalized_range).close
    pnl = equity - equity[0]
    returns = np.diff(equity) / equity[:-1]
    return PortfolioSeries(source.dates, equity, returns, pnl)


def portfolio_returns(range_key: str = "1Y") -> np.ndarray:
    return portfolio_equity(range_key).returns


def portfolio_allocation() -> tuple[tuple[str, ...], np.ndarray]:
    rows = position_rows()
    values = np.asarray([row["market_value"] for row in rows], dtype=np.float64)
    return tuple(row["symbol"] for row in rows), _readonly(values / np.sum(values) * 100.0)


def portfolio_contribution() -> tuple[tuple[str, ...], np.ndarray]:
    rows = position_rows()
    return tuple(row["symbol"] for row in rows), _readonly([row["pnl"] for row in rows])


def sector_exposures() -> tuple[tuple[str, ...], np.ndarray]:
    grouped: dict[str, float] = {}
    for row in position_rows():
        sector = instrument(row["symbol"]).sector
        grouped[sector] = grouped.get(sector, 0.0) + float(row["market_value"])
    nav = portfolio_summary()["nav"]
    return tuple(grouped), _readonly([value / nav * 100.0 for value in grouped.values()])


def correlation_matrix(
    symbols: Sequence[str] | None = None, range_key: str = "1Y"
) -> tuple[tuple[str, ...], np.ndarray]:
    selected = tuple(
        instrument(symbol).symbol
        for symbol in (symbols or ("SPY", "AAPL", "MSFT", "NVDA", "JPM", "XOM"))
    )
    if len(selected) < 2:
        raise ValueError("correlation_matrix requires at least two symbols")
    columns = []
    for symbol in selected:
        close = history(symbol, range_key=range_key).close
        columns.append(np.diff(close) / close[:-1])
    matrix = np.corrcoef(np.vstack(columns))
    if not np.isfinite(matrix).all():
        raise ValueError("correlation matrix contains non-finite values")
    return selected, _readonly(matrix)


def factor_exposures() -> tuple[tuple[str, ...], np.ndarray]:
    rows = position_rows()
    total = sum(float(row["market_value"]) for row in rows)
    weights = {row["symbol"]: float(row["market_value"]) / total for row in rows}
    market = sum(weights[symbol] * instrument(symbol).beta for symbol in weights)
    technology = sum(
        weights[symbol] for symbol in weights if instrument(symbol).sector == "Technology"
    )
    defensive = sum(
        weights[symbol] for symbol in weights if instrument(symbol).sector in {"Energy", "Metals"}
    )
    dollar = sum(weights[symbol] for symbol in weights if instrument(symbol).currency == "USD")
    alternatives = sum(
        weights[symbol]
        for symbol in weights
        if instrument(symbol).asset_class in {"Commodity", "Crypto"}
    )
    labels = ("Market beta", "Technology", "Defensive", "USD", "Alternatives")
    return labels, _readonly([market, technology, defensive, dollar, alternatives])


def _normalize_confidence(value: float | int | str) -> float:
    if isinstance(value, str):
        value = float(value.strip().rstrip("%"))
    confidence = float(value)
    if confidence > 1.0:
        confidence /= 100.0
    if confidence not in {0.95, 0.99}:
        raise ValueError("confidence must be 0.95/95% or 0.99/99%")
    return confidence


def stress_scenarios(confidence: float | int | str = 0.95) -> tuple[ScenarioResult, ...]:
    normalized = _normalize_confidence(confidence)
    multiplier = 1.0 if normalized == 0.95 else 1.18
    nav = portfolio_summary()["nav"]
    values = {row["symbol"]: float(row["market_value"]) for row in position_rows()}
    definitions: tuple[tuple[str, str, Mapping[str, float]], ...] = (
        (
            "Equity selloff",
            "Broad risk assets gap lower; gold provides a partial hedge.",
            {
                "SPY": -0.12,
                "AAPL": -0.16,
                "MSFT": -0.15,
                "NVDA": -0.24,
                "JPM": -0.17,
                "XOM": -0.10,
                "XAUUSD": 0.045,
                "BTCUSD": -0.27,
            },
        ),
        (
            "Rates +150 bp",
            "Long-duration growth reprices while financials are comparatively resilient.",
            {
                "SPY": -0.07,
                "AAPL": -0.10,
                "MSFT": -0.11,
                "NVDA": -0.16,
                "JPM": -0.025,
                "XOM": -0.04,
                "XAUUSD": -0.08,
                "BTCUSD": -0.13,
            },
        ),
        (
            "Energy shock",
            "Oil-linked assets rally as margins and consumer risk deteriorate.",
            {
                "SPY": -0.045,
                "AAPL": -0.04,
                "MSFT": -0.035,
                "NVDA": -0.06,
                "JPM": -0.05,
                "XOM": 0.18,
                "XAUUSD": 0.025,
                "BTCUSD": -0.07,
            },
        ),
        (
            "Dollar squeeze",
            "USD liquidity pressure hits alternatives and multinational earnings.",
            {
                "SPY": -0.04,
                "AAPL": -0.055,
                "MSFT": -0.05,
                "NVDA": -0.075,
                "JPM": -0.03,
                "XOM": -0.035,
                "XAUUSD": -0.09,
                "BTCUSD": -0.16,
            },
        ),
    )
    results = []
    for name, description, shocks in definitions:
        pnl = multiplier * sum(values[symbol] * shock for symbol, shock in shocks.items())
        results.append(
            ScenarioResult(
                name=name,
                description=description,
                confidence=normalized,
                pnl=float(pnl),
                loss_percent=float(pnl / nav * 100.0),
                nav_after=float(nav + pnl),
            )
        )
    return tuple(results)


_STORIES = (
    NewsItem(
        "N-001",
        "2026-07-31T15:42:00Z",
        "XY Wire",
        "Semiconductor complex leads late-session rebound",
        "A broad technology bid accelerated after systematic flows turned positive into the close. All values and events in this terminal are simulated.",
        ("NVDA", "MSFT", "SPY"),
        "Positive",
        "High",
    ),
    NewsItem(
        "N-002",
        "2026-07-31T14:18:00Z",
        "Terminal Research",
        "Yield curve steepens as front-end expectations ease",
        "The simulated curve bull-steepened after a softer activity proxy, while long-end term premium remained firm.",
        ("SPY", "JPM", "XAUUSD"),
        "Mixed",
        "High",
    ),
    NewsItem(
        "N-003",
        "2026-07-31T12:05:00Z",
        "Market Desk",
        "Dollar pauses; gold holds above technical support",
        "G10 FX volatility compressed and the fictional spot-gold series consolidated above its 20-day average.",
        ("EURUSD", "USDJPY", "XAUUSD"),
        "Neutral",
        "Medium",
    ),
    NewsItem(
        "N-004",
        "2026-07-31T10:31:00Z",
        "Digital Ledger",
        "Crypto beta rises with broader risk appetite",
        "Bitcoin's simulated realized volatility moved higher as cross-asset correlations strengthened.",
        ("BTCUSD", "SPY", "NVDA"),
        "Positive",
        "Medium",
    ),
    NewsItem(
        "N-005",
        "2026-07-31T09:12:00Z",
        "Energy Brief",
        "Integrated energy shares lag despite firm commodity tape",
        "Refining-margin concerns offset a fictional increase in spot energy benchmarks.",
        ("XOM", "SPY"),
        "Negative",
        "Medium",
    ),
    NewsItem(
        "N-006",
        "2026-07-30T20:45:00Z",
        "Global Close",
        "Asia handoff points to cautious open",
        "Index futures were little changed in the deterministic overnight scenario; no live venue data is used.",
        ("SPY", "USDJPY"),
        "Neutral",
        "Low",
    ),
)

_CALENDAR = (
    CalendarEvent(
        "C-001", "2026-08-03T14:00:00Z", "US", "ISM Manufacturing", "High", "--", "49.8", "49.2"
    ),
    CalendarEvent(
        "C-002", "2026-08-04T04:30:00Z", "AU", "RBA Rate Decision", "High", "--", "3.60%", "3.60%"
    ),
    CalendarEvent(
        "C-003",
        "2026-08-05T12:15:00Z",
        "US",
        "ADP Employment Change",
        "Medium",
        "--",
        "118K",
        "105K",
    ),
    CalendarEvent(
        "C-004", "2026-08-06T11:00:00Z", "GB", "BoE Bank Rate", "High", "--", "3.75%", "4.00%"
    ),
    CalendarEvent(
        "C-005", "2026-08-07T12:30:00Z", "US", "Nonfarm Payrolls", "High", "--", "165K", "142K"
    ),
)


def stories(symbol: str | None = None) -> tuple[NewsItem, ...]:
    if symbol is None:
        return _STORIES
    key = instrument(symbol).symbol
    return tuple(item for item in _STORIES if key in item.symbols)


def calendar_events() -> tuple[CalendarEvent, ...]:
    return _CALENDAR


__all__ = [
    "AS_OF",
    "INSTRUMENTS",
    "OHLCV",
    "SIMULATED_DATA_LABEL",
    "CalendarEvent",
    "Instrument",
    "NewsItem",
    "PortfolioSeries",
    "Position",
    "Quote",
    "ScenarioResult",
    "breadth_metrics",
    "calendar_events",
    "correlation_matrix",
    "factor_exposures",
    "history",
    "instrument",
    "instrument_symbols",
    "market_heatmap_data",
    "movers",
    "portfolio_allocation",
    "portfolio_contribution",
    "portfolio_equity",
    "portfolio_returns",
    "portfolio_summary",
    "position_rows",
    "positions",
    "pulse_seed",
    "quote",
    "sector_exposures",
    "stories",
    "stress_scenarios",
    "watchlist_rows",
    "yield_curve",
]
