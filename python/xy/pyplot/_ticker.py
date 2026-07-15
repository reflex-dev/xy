"""Tick locators/formatters: the matplotlib.ticker subset gallery scripts use.

Locators own tick *positions* over the axis view interval; formatters own
label text. The Axes applies them at chart-build time, when data limits are
known, so locator-driven axes keep refreshing as data lands — the same
contract as the native tick generator they displace. The math is xy-owned;
positions are exact for Null/Fixed/Multiple/Linear and MaxN/Auto port
matplotlib's ``MaxNLocator._raw_ticks`` (Log stays approximate, documented
in the compat table).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, Optional

import numpy as np

from ._translate import check_unsupported


def _scale_range(vmin: float, vmax: float, n: int) -> tuple[float, float]:
    """matplotlib's ``ticker.scale_range``: decade scale and offset for a span."""
    dv = abs(vmax - vmin)
    if dv == 0:
        return 1.0, 0.0
    meanv = (vmax + vmin) / 2
    offset = 0.0
    if abs(meanv) / dv >= 100:  # threshold: far-from-zero spans get an offset
        offset = math.copysign(10 ** (math.log10(abs(meanv)) // 1), meanv)
    scale = 10 ** (math.log10(dv / n) // 1)
    return scale, offset


class _EdgeInteger:
    """matplotlib's ``ticker._Edge_integer``: offset-tolerant edge rounding."""

    def __init__(self, step: float, offset: float) -> None:
        self.step = step
        self._offset = abs(offset)

    def _close_to(self, ms: float, edge: float) -> bool:
        if self._offset > 0:
            digits = np.log10(self._offset / self.step)
            tol = min(0.4999, max(1e-10, 10 ** (digits - 12)))
        else:
            tol = 1e-10
        return abs(ms - edge) < tol

    def le(self, x: float) -> float:
        d, m = divmod(x, self.step)
        return d + 1 if self._close_to(m / self.step, 1) else d

    def ge(self, x: float) -> float:
        d, m = divmod(x, self.step)
        return d if self._close_to(m / self.step, 0) else d + 1


class Locator:
    # Axes-size tick budget, set by the Axes before tick_values() when the
    # axis pixel length is known (matplotlib reads it off self.axis instead).
    _nbins_hint: Optional[int] = None

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<xy.pyplot.{type(self).__name__}>"


class NullLocator(Locator):
    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        return np.asarray([], dtype=float)


class FixedLocator(Locator):
    def __init__(self, locs: Any, nbins: Optional[int] = None) -> None:
        self.locs = np.asarray(locs, dtype=float).reshape(-1)
        self._nbins = None if nbins is None else max(1, int(nbins))

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        if self._nbins is None or len(self.locs) <= self._nbins + 1:
            return self.locs
        step = max(1, len(self.locs) // self._nbins)
        return self.locs[::step]


class MultipleLocator(Locator):
    def __init__(self, base: float = 1.0, offset: float = 0.0) -> None:
        self._base = float(base)
        self._offset = float(offset)
        if not (np.isfinite(self._base) and self._base > 0):
            raise ValueError("MultipleLocator base must be positive")

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        first = np.ceil((vmin - self._offset) / self._base - 1e-9)
        last = np.floor((vmax - self._offset) / self._base + 1e-9)
        if last < first:
            return np.asarray([], dtype=float)
        return self._offset + np.arange(first, last + 1) * self._base


class MaxNLocator(Locator):
    """matplotlib's MaxNLocator (``_raw_ticks`` port): at most *nbins* intervals
    on nice step values; edge ticks may overrun the view — the axis clips them,
    exactly as matplotlib trims at draw time."""

    _default_steps = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)

    def __init__(self, nbins: Any = 10, **kwargs: Any) -> None:
        self._integer = bool(kwargs.pop("integer", False))
        steps = kwargs.pop("steps", None)
        kwargs.pop("prune", None)  # compat-noop: ticks outside the view never draw
        self._min_n_ticks = max(1, int(kwargs.pop("min_n_ticks", 2)))
        check_unsupported(kwargs, "MaxNLocator()")
        self._nbins: Any = nbins if nbins == "auto" else max(1, int(nbins))
        if steps is None:
            validated = list(MaxNLocator._default_steps)
        else:
            validated = sorted(float(step) for step in steps)
            if any(step < 1 or step > 10 for step in validated):
                raise ValueError("steps must be numbers between 1 and 10 inclusive")
            if validated[0] != 1.0:
                validated.insert(0, 1.0)
            if validated[-1] != 10.0:
                validated.append(10.0)
        self._steps = tuple(validated)
        self._extended_steps = np.concatenate(
            [
                0.1 * np.asarray(self._steps[:-1]),
                np.asarray(self._steps),
                [10.0 * self._steps[1]],
            ]
        )

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        if not (np.isfinite(vmin) and np.isfinite(vmax)) or vmin == vmax:
            return np.asarray([vmin], dtype=float)
        if self._nbins == "auto":
            hint = 9 if self._nbins_hint is None else int(self._nbins_hint)
            nbins = int(np.clip(hint, max(1, self._min_n_ticks - 1), 9))
        else:
            nbins = self._nbins
        scale, offset = _scale_range(vmin, vmax, nbins)
        _vmin = vmin - offset
        _vmax = vmax - offset
        steps = self._extended_steps * scale
        if self._integer:
            # For steps > 1, keep only integer values.
            steps = steps[(steps < 1) | (np.abs(steps - np.round(steps)) < 0.001)]
        raw_step = (_vmax - _vmin) / nbins
        large = np.nonzero(steps >= raw_step)[0]
        istep = int(large[0]) if len(large) else len(steps) - 1
        # Start at the smallest step >= the raw step; walk down only if it
        # leaves fewer than min_n_ticks ticks inside the view.
        ticks = np.asarray([_vmin, _vmax])
        for step in steps[: istep + 1][::-1]:
            step = float(step)
            if self._integer and np.floor(_vmax) - np.ceil(_vmin) >= self._min_n_ticks - 1:
                step = max(1.0, step)
            best_vmin = (_vmin // step) * step
            edge = _EdgeInteger(step, offset)
            low = edge.le(_vmin - best_vmin)
            high = edge.ge(_vmax - best_vmin)
            ticks = np.arange(low, high + 1) * step + best_vmin
            if ((ticks >= _vmin) & (ticks <= _vmax)).sum() >= self._min_n_ticks:
                break
        return ticks + offset


class AutoLocator(MaxNLocator):
    """The default: matplotlib's AutoLocator — MaxNLocator with axes-size
    density and the restricted (1, 2, 2.5, 5, 10) step table, which is also
    the engine's native nice-step rule."""

    def __init__(self) -> None:
        super().__init__(nbins="auto", steps=(1.0, 2.0, 2.5, 5.0, 10.0))


class LinearLocator(Locator):
    def __init__(self, numticks: Optional[int] = None) -> None:
        self._numticks = 11 if numticks is None else max(2, int(numticks))

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        return np.linspace(vmin, vmax, self._numticks)


class LogLocator(Locator):
    def __init__(self, base: float = 10.0, subs: Any = (1.0,), **kwargs: Any) -> None:
        kwargs.pop("numticks", None)  # compat-noop: every decade tick fits our axes
        check_unsupported(kwargs, "LogLocator()")
        self._base = float(base)
        if self._base <= 1.0:
            raise ValueError("LogLocator base must be greater than 1")
        self._subs = (1.0,) if subs is None else tuple(float(sub) for sub in subs)

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        if vmax <= 0:
            return np.asarray([], dtype=float)
        vmin = max(vmin, np.finfo(float).tiny)
        first = np.floor(np.log(vmin) / np.log(self._base)) - 1
        last = np.ceil(np.log(vmax) / np.log(self._base)) + 1
        decades = self._base ** np.arange(first, last + 1)
        ticks = np.sort(np.concatenate([decades * sub for sub in self._subs]))
        return ticks[(ticks >= vmin) & (ticks <= vmax)]


class Formatter:
    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<xy.pyplot.{type(self).__name__}>"


class ScalarFormatter(Formatter):
    """The default: the shim's ``%g`` rendering of tick values."""

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return f"{value:g}"


class NullFormatter(Formatter):
    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return ""


class FixedFormatter(Formatter):
    def __init__(self, seq: Any) -> None:
        self.seq = [str(item) for item in seq]

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        index = 0 if pos is None else int(pos)
        return self.seq[index] if 0 <= index < len(self.seq) else ""


class FuncFormatter(Formatter):
    def __init__(self, func: Callable[[float, Optional[int]], Any]) -> None:
        if not callable(func):
            raise TypeError("FuncFormatter requires a callable(value, pos)")
        self._func = func

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return str(self._func(value, pos))


class FormatStrFormatter(Formatter):
    def __init__(self, fmt: str) -> None:
        self._fmt = str(fmt)

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return self._fmt % value


class StrMethodFormatter(Formatter):
    def __init__(self, fmt: str) -> None:
        self._fmt = str(fmt)

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return self._fmt.format(x=value, pos=pos)


def as_formatter(value: Any, where: str) -> Formatter:
    """matplotlib's set_major_formatter coercions: Formatter, str, callable."""
    if isinstance(value, Formatter):
        return value
    if isinstance(value, str):
        return StrMethodFormatter(value)
    if callable(value):
        return FuncFormatter(value)
    raise TypeError(f"{where} requires a Formatter, format string, or callable")
