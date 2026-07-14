"""Tick locators/formatters: the matplotlib.ticker subset gallery scripts use.

Locators own tick *positions* over the axis view interval; formatters own
label text. The Axes applies them at chart-build time, when data limits are
known, so locator-driven axes keep refreshing as data lands — the same
contract as the native tick generator they displace. The math is xy-owned
and approximates matplotlib's locators (documented in the compat table);
positions are exact for Null/Fixed/Multiple, heuristic for MaxN.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

import numpy as np

from ._translate import check_unsupported


class Locator:
    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<xy.pyplot.{type(self).__name__}>"


class AutoLocator(Locator):
    """The default: the engine's nice-linear tick generator."""

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        from xy._svg import _linear_ticks

        if not (np.isfinite(vmin) and np.isfinite(vmax)) or vmin == vmax:
            return np.asarray([], dtype=float)
        return np.asarray(_linear_ticks(float(vmin), float(vmax))[0], dtype=float)


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
    """At most *nbins* intervals on nice step sizes (1, 2, 2.5, 5) × 10^k."""

    _default_steps = (1.0, 2.0, 2.5, 5.0, 10.0)

    def __init__(self, nbins: Any = 10, **kwargs: Any) -> None:
        self._integer = bool(kwargs.pop("integer", False))
        steps = kwargs.pop("steps", None)
        kwargs.pop("prune", None)  # compat-noop: ticks outside the view never draw
        check_unsupported(kwargs, "MaxNLocator()")
        if nbins == "auto":
            nbins = 9  # matplotlib's density heuristic collapsed to its default
        self._nbins = max(1, int(nbins))
        self._steps = (
            tuple(sorted(float(step) for step in steps))
            if steps is not None
            else MaxNLocator._default_steps
        )

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        if not (np.isfinite(vmin) and np.isfinite(vmax)) or vmin == vmax:
            return np.asarray([vmin], dtype=float)
        raw = (vmax - vmin) / self._nbins
        magnitude = 10.0 ** np.floor(np.log10(raw))
        for scale in (magnitude, magnitude * 10.0, magnitude * 100.0):
            for step in self._steps:
                candidate = step * scale
                if self._integer:
                    candidate = max(1.0, np.round(candidate))
                first = np.ceil(vmin / candidate - 1e-9)
                last = np.floor(vmax / candidate + 1e-9)
                if last < first or last - first > self._nbins:
                    continue
                return np.arange(first, last + 1) * candidate
        return np.asarray([vmin, vmax], dtype=float)


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
