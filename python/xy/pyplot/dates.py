"""The matplotlib.dates subset gallery scripts use, in the engine's time unit.

matplotlib's date machinery works in *days* resolved through its unit
registry; the shim has no registry — datetime data is canonicalized once to
f64 ms since epoch (columns.py) and every axis quantity stays in that space.
These locators and formatters therefore speak ms directly, so they compose
with the same ``set_major_locator``/``set_major_formatter`` contract as
``xy.pyplot``'s numeric tickers.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import numpy as np

from ._ticker import Formatter, Locator

_EPOCH = dt.datetime(1970, 1, 1)
_MAXTICKS = 1000  # matplotlib.dates.RRuleLocator's runaway-locator guard


def _from_ms(value: float) -> dt.datetime:
    return _EPOCH + dt.timedelta(milliseconds=float(value))


def _to_ms(value: dt.datetime) -> float:
    return (value - _EPOCH).total_seconds() * 1000.0


class DateFormatter(Formatter):
    """``strftime`` of a tick position taken as ms since epoch (naive UTC)."""

    def __init__(self, fmt: str, tz: Any = None, *, usetex: Any = None) -> None:
        del tz, usetex  # compat-noop: naive timestamps, plain-text labels
        self._fmt = str(fmt)

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return _from_ms(value).strftime(self._fmt)


def _month_set(bymonth: Any) -> tuple[int, ...]:
    if bymonth is None:
        return tuple(range(1, 13))
    if isinstance(bymonth, (int, np.integer)):
        bymonth = (bymonth,)
    months = tuple(sorted({int(month) for month in bymonth}))
    if any(month < 1 or month > 12 for month in months):
        raise ValueError("bymonth values must be in 1..12")
    return months


class _CalendarLocator(Locator):
    """Shared clip loop over calendar-rule candidates (rrule approximation:
    occurrence counting for ``interval`` is anchored at the 1970 epoch, the
    same dtstart matplotlib's rules default to)."""

    _interval: int

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        raise NotImplementedError

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        lo, hi = sorted((float(vmin), float(vmax)))
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return np.asarray([], dtype=float)
        ticks: list[float] = []
        for occurrence, when in self._candidates(_from_ms(lo), _from_ms(hi)):
            if occurrence % self._interval:
                continue
            value = _to_ms(when)
            if lo <= value <= hi:
                ticks.append(value)
            if len(ticks) > _MAXTICKS:
                raise RuntimeError(f"Locator attempting to generate more than {_MAXTICKS} ticks")
        return np.asarray(ticks, dtype=float)


class MonthLocator(_CalendarLocator):
    """Ticks on the given day of the given months, every *interval* matches."""

    def __init__(
        self, bymonth: Any = None, bymonthday: int = 1, interval: int = 1, tz: Any = None
    ) -> None:
        del tz  # compat-noop: naive timestamps
        self._months = _month_set(bymonth)
        self._day = int(bymonthday)
        if not 1 <= self._day <= 31:
            raise ValueError("bymonthday must be in 1..31")
        self._interval = max(1, int(interval))

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        out = []
        for year in range(lo.year, hi.year + 1):
            for index, month in enumerate(self._months):
                try:
                    when = dt.datetime(year, month, self._day)
                except ValueError:  # bymonthday past the month's end: rrule skips it
                    continue
                out.append(((year - 1970) * len(self._months) + index, when))
        return out


class YearLocator(_CalendarLocator):
    """Ticks on month/day of years that are multiples of *base*."""

    def __init__(self, base: int = 1, month: int = 1, day: int = 1, tz: Any = None) -> None:
        del tz  # compat-noop: naive timestamps
        self._interval = max(1, int(base))
        self._month, self._day = int(month), int(day)

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        out = []
        for year in range(lo.year, hi.year + 1):
            try:
                out.append((year, dt.datetime(year, self._month, self._day)))
            except ValueError:
                continue
        return out


class DayLocator(_CalendarLocator):
    """Ticks on the given days of the month (all days when omitted)."""

    def __init__(self, bymonthday: Any = None, interval: int = 1, tz: Any = None) -> None:
        del tz  # compat-noop: naive timestamps
        if isinstance(bymonthday, (int, np.integer)):
            bymonthday = (bymonthday,)
        self._days = None if bymonthday is None else tuple(sorted({int(d) for d in bymonthday}))
        if self._days is not None and any(day < 1 or day > 31 for day in self._days):
            raise ValueError("bymonthday values must be in 1..31")
        self._interval = max(1, int(interval))

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        out = []
        day = dt.datetime(lo.year, lo.month, lo.day)
        while day <= hi:
            if self._days is None or day.day in self._days:
                out.append((day.toordinal() - _EPOCH.toordinal(), day))
            if len(out) > _MAXTICKS * max(1, self._interval):
                break  # tick_values raises past _MAXTICKS; stop generating
            day += dt.timedelta(days=1)
        return out
