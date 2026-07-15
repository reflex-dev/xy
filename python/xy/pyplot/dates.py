"""The matplotlib.dates subset gallery scripts use, in the engine's time unit.

matplotlib's date machinery works in *days* resolved through its unit
registry; the shim has no registry — datetime data is canonicalized once to
f64 ms since epoch (columns.py) and every axis quantity stays in that space.
These locators and formatters therefore speak ms directly, so they compose
with the same ``set_major_locator``/``set_major_formatter`` contract as
``xy.pyplot``'s numeric tickers.
"""

from __future__ import annotations

import calendar
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


def _shift_months(base: dt.datetime, months: int) -> dt.datetime:
    """Calendar-arithmetic month shift with day-of-month clamping."""
    total = base.year * 12 + (base.month - 1) + months
    year, month0 = divmod(total, 12)
    day = min(base.day, calendar.monthrange(year, month0 + 1)[1])
    return base.replace(year=year, month=month0 + 1, day=day)


def _rrule_dtstart(lo: dt.datetime, hi: dt.datetime) -> dt.datetime:
    """matplotlib's RRuleLocator recurrence anchor for a view interval.

    ``RRuleLocator._create_rrule`` sets ``dtstart = vmin - relativedelta(vmax,
    vmin)``, so ``interval`` counting is phased relative to the view, not a
    fixed epoch. This reproduces that arithmetic (months first, then the
    residual timedelta) without dateutil.
    """
    months = (hi.year - lo.year) * 12 + (hi.month - lo.month)
    while _shift_months(lo, months) > hi:
        months -= 1
    remainder = hi - _shift_months(lo, months)
    try:
        return _shift_months(lo, -months) - remainder
    except (ValueError, OverflowError):
        return dt.datetime(1, 1, 1)  # matplotlib caps at the datetime floor


class _CalendarLocator(Locator):
    """Shared clip loop over calendar-rule candidates (rrule approximation:
    ``interval`` filters occurrence numbers relative to the same view-derived
    dtstart matplotlib's rules use)."""

    _interval: int

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        raise NotImplementedError

    def _anchor(self, dtstart: dt.datetime) -> int:
        """The occurrence number of the rule's dtstart (0 = epoch-anchored,
        matching YearLocator's multiple-of-base years)."""
        del dtstart
        return 0

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        lo, hi = sorted((float(vmin), float(vmax)))
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return np.asarray([], dtype=float)
        lo_dt, hi_dt = _from_ms(lo), _from_ms(hi)
        anchor = self._anchor(_rrule_dtstart(lo_dt, hi_dt)) if self._interval > 1 else 0
        ticks: list[float] = []
        for occurrence, when in self._candidates(lo_dt, hi_dt):
            if (occurrence - anchor) % self._interval:
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

    def _anchor(self, dtstart: dt.datetime) -> int:
        return dtstart.year * 12 + dtstart.month - 1

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        # Occurrence numbers count *all* months (rrule's MONTHLY stride);
        # bymonth only filters which survivors become candidates.
        out = []
        for year in range(lo.year, hi.year + 1):
            for month in self._months:
                try:
                    when = dt.datetime(year, month, self._day)
                except ValueError:  # bymonthday past the month's end: rrule skips it
                    continue
                out.append((year * 12 + month - 1, when))
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

    def _anchor(self, dtstart: dt.datetime) -> int:
        return dtstart.toordinal()

    def _candidates(self, lo: dt.datetime, hi: dt.datetime) -> list[tuple[int, dt.datetime]]:
        out = []
        day = dt.datetime(lo.year, lo.month, lo.day)
        while day <= hi:
            if self._days is None or day.day in self._days:
                out.append((day.toordinal(), day))
            if len(out) > _MAXTICKS * max(1, self._interval):
                break  # tick_values raises past _MAXTICKS; stop generating
            day += dt.timedelta(days=1)
        return out
