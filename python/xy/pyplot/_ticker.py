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


def _nonsingular(
    vmin: float,
    vmax: float,
    *,
    expander: float,
    tiny: float,
) -> tuple[float, float]:
    """Matplotlib's finite, increasing fallback for a singular interval."""
    if not (np.isfinite(vmin) and np.isfinite(vmax)):
        return -expander, expander
    if vmax < vmin:
        vmin, vmax = vmax, vmin
    vmin, vmax = float(vmin), float(vmax)
    max_abs = max(abs(vmin), abs(vmax))
    if max_abs < (1e6 / tiny) * np.finfo(float).tiny:
        return -expander, expander
    if vmax - vmin <= max_abs * tiny:
        vmin -= expander * abs(vmin)
        vmax += expander * abs(vmax)
    return vmin, vmax


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

    def _raw_ticks(self, vmin: float, vmax: float) -> np.ndarray:
        from ._rc import rcParams

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
        large_steps = steps >= raw_step
        if rcParams["axes.autolimit_mode"] == "round_numbers":
            # Match Matplotlib's MaxNLocator round-number mode: reject a step
            # that cannot span the entire padded view in ``nbins`` intervals.
            floored_vmins = (_vmin // steps) * steps
            floored_vmaxs = floored_vmins + steps * nbins
            large_steps &= floored_vmaxs >= _vmax
        large = np.nonzero(large_steps)[0]
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

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = _nonsingular(vmin, vmax, expander=1e-13, tiny=1e-14)
        return self._raw_ticks(vmin, vmax)

    def view_limits(self, vmin: float, vmax: float) -> tuple[float, float]:
        """Return data limits, or edge ticks in Matplotlib round-number mode."""
        from ._rc import rcParams

        vmin, vmax = _nonsingular(vmin, vmax, expander=1e-12, tiny=1e-13)
        if rcParams["axes.autolimit_mode"] != "round_numbers":
            return vmin, vmax
        ticks = self._raw_ticks(vmin, vmax)
        return float(ticks[0]), float(ticks[-1])


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
        self._subs = None if subs is None else tuple(float(sub) for sub in subs)

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        if vmax <= 0:
            return np.asarray([], dtype=float)
        vmin = max(vmin, np.finfo(float).tiny)
        first = np.floor(np.log(vmin) / np.log(self._base)) - 1
        last = np.ceil(np.log(vmax) / np.log(self._base)) + 1
        decades = self._base ** np.arange(first, last + 1)
        # Matplotlib's ``subs=None`` means automatic minor ticks: all integral
        # subdivisions between adjacent powers.  ``(1,)`` remains the major
        # decade locator.
        subs = (
            tuple(float(sub) for sub in np.arange(2.0, self._base))
            if self._subs is None
            else self._subs
        )
        if not subs:
            return np.asarray([], dtype=float)
        ticks = np.sort(np.concatenate([decades * sub for sub in subs]))
        return ticks[(ticks >= vmin) & (ticks <= vmax)]


class SymmetricalLogLocator(Locator):
    """Matplotlib's decade locator on both sides of a symlog linear region."""

    def __init__(
        self,
        *,
        base: float,
        linthresh: float,
        subs: Any = None,
        numticks: int = 15,
    ) -> None:
        self._base = float(base)
        self._linthresh = float(linthresh)
        if self._base <= 1:
            raise ValueError("SymmetricalLogLocator base must be greater than 1")
        if self._linthresh <= 0:
            raise ValueError("SymmetricalLogLocator linthresh must be positive")
        self._subs = (1.0,) if subs is None else tuple(float(value) for value in subs)
        self.numticks = max(2, int(numticks))

    def set_params(self, subs: Any = None, numticks: Optional[int] = None) -> None:
        if numticks is not None:
            self.numticks = max(2, int(numticks))
        if subs is not None:
            self._subs = tuple(float(value) for value in subs)

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        threshold = self._linthresh
        if -threshold <= vmin < vmax <= threshold:
            return np.asarray(sorted({vmin, 0.0, vmax}), dtype=float)

        has_negative = vmin < -threshold
        has_positive = vmax > threshold
        has_linear = (has_negative and vmax > -threshold) or (has_positive and vmin < threshold)

        def log_range(lo: float, hi: float) -> tuple[int, int]:
            return (
                int(np.floor(np.log(lo) / np.log(self._base))),
                int(np.ceil(np.log(hi) / np.log(self._base))),
            )

        negative_lo = negative_hi = positive_lo = positive_hi = 0
        if has_negative:
            negative_lo, negative_hi = log_range(abs(min(-threshold, vmax)), abs(vmin) + 1)
        if has_positive:
            positive_lo, positive_hi = log_range(max(threshold, vmin), vmax + 1)
        total = negative_hi - negative_lo + positive_hi - positive_lo + int(has_linear)
        stride = max(total // (self.numticks - 1), 1)

        decades: list[float] = []
        if has_negative:
            decades.extend(-(self._base ** np.arange(negative_lo, negative_hi, stride)[::-1]))
        if has_linear:
            decades.append(0.0)
        if has_positive:
            decades.extend(self._base ** np.arange(positive_lo, positive_hi, stride))
        ticks = [
            decade if decade == 0 else float(sub) * decade
            for decade in decades
            for sub in ((1.0,) if decade == 0 else self._subs)
        ]
        return np.asarray(ticks, dtype=float)


class AsinhLocator(Locator):
    """Source-faithful rounded ticks for Matplotlib's asinh scale."""

    def __init__(
        self,
        linear_width: float,
        *,
        numticks: int = 11,
        symthresh: float = 0.2,
        base: float = 10,
        subs: Any = None,
    ) -> None:
        self.linear_width = float(linear_width)
        self.numticks = max(2, int(numticks))
        self.symthresh = float(symthresh)
        self.base = float(base)
        self.subs = None if subs is None else tuple(float(value) for value in subs)
        if self.linear_width <= 0:
            raise ValueError("AsinhLocator linear_width must be positive")

    def set_params(
        self,
        *,
        numticks: Optional[int] = None,
        symthresh: Optional[float] = None,
        base: Optional[float] = None,
        subs: Any = None,
    ) -> None:
        if numticks is not None:
            self.numticks = max(2, int(numticks))
        if symthresh is not None:
            self.symthresh = float(symthresh)
        if base is not None:
            self.base = float(base)
        if subs is not None:
            self.subs = tuple(float(value) for value in subs) or None

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        ymin, ymax = self.linear_width * np.arcsinh(
            np.asarray([vmin, vmax], dtype=float) / self.linear_width
        )
        transformed = np.linspace(ymin, ymax, self.numticks)
        if ymin * ymax < 0:
            zero_distance = np.abs(transformed / (ymax - ymin))
            transformed = np.hstack([transformed[zero_distance > 0.5 / self.numticks], 0.0])
        values = self.linear_width * np.sinh(transformed / self.linear_width)
        zero = transformed == 0
        with np.errstate(divide="ignore", invalid="ignore"):
            if self.base > 1:
                powers = np.sign(values) * self.base ** np.floor(
                    np.log(np.abs(values)) / np.log(self.base)
                )
                rounded = np.outer(powers, self.subs).reshape(-1) if self.subs else powers
            else:
                powers = np.where(zero, 1.0, 10 ** np.floor(np.log10(np.abs(values))))
                rounded = powers * np.round(values / powers)
        ticks = np.asarray(sorted(set(map(float, rounded))), dtype=float)
        return ticks if len(ticks) >= 2 else np.linspace(vmin, vmax, self.numticks)


class LogitLocator(Locator):
    """Matplotlib's probability-decade locator without an Axis dependency."""

    def __init__(self, minor: bool = False, *, nbins: Any = "auto") -> None:
        self.minor = bool(minor)
        self._nbins = nbins if nbins == "auto" else max(1, int(nbins))

    @staticmethod
    def _ideal_tick(index: int) -> float:
        if index < 0:
            return float(10**index)
        if index > 0:
            return float(1 - 10 ** (-index))
        return 0.5

    def tick_values(self, vmin: float, vmax: float) -> np.ndarray:
        vmin, vmax = sorted((float(vmin), float(vmax)))
        epsilon = 1e-7
        if not (np.isfinite(vmin) and np.isfinite(vmax)):
            vmin, vmax = epsilon, 1 - epsilon
        vmin, vmax = max(vmin, epsilon), min(vmax, 1 - epsilon)
        if vmin >= vmax:
            return np.asarray([], dtype=float)
        nbins = max(2, int(self._nbins_hint or 9)) if self._nbins == "auto" else self._nbins
        lower = (
            int(np.floor(np.log10(vmin)))
            if vmin < 0.5
            else 0
            if vmin < 0.9
            else int(-np.ceil(np.log10(1 - vmin)))
        )
        upper = (
            int(np.ceil(np.log10(vmax)))
            if vmax <= 0.5
            else 1
            if vmax <= 0.9
            else int(-np.floor(np.log10(1 - vmax)))
        )
        ideal_count = upper - lower - 1
        if ideal_count >= 2:
            if ideal_count > nbins:
                stride = math.ceil(ideal_count / nbins)
                indexes = [
                    value
                    for value in range(lower, upper + 1)
                    if (value % stride != 0) == self.minor
                ]
                return np.asarray([self._ideal_tick(value) for value in indexes])
            if self.minor:
                ticks: list[float] = []
                for value in range(lower, upper):
                    if value < -1:
                        ticks.extend(np.arange(2, 10) * 10**value)
                    elif value == -1:
                        ticks.extend(np.arange(2, 5) / 10)
                    elif value == 0:
                        ticks.extend(np.arange(6, 9) / 10)
                    else:
                        ticks.extend(1 - np.arange(2, 10)[::-1] * 10 ** (-value - 1))
                return np.asarray(ticks, dtype=float)
            return np.asarray([self._ideal_tick(value) for value in range(lower, upper + 1)])
        if self.minor:
            return np.asarray([], dtype=float)
        locator = MaxNLocator(nbins=nbins, steps=(1, 2, 5, 10))
        return locator.tick_values(vmin, vmax)


class Formatter:
    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<xy.pyplot.{type(self).__name__}>"


class ScalarFormatter(Formatter):
    """The default: the shim's ``%g`` rendering of tick values."""

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        return f"{value:g}"


_SUPERSCRIPT_DIGITS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


class LogFormatterSciNotation(Formatter):
    """Readable decade labels for log, symlog, and asinh axes."""

    def __init__(self, base: float = 10.0) -> None:
        self.base = float(base)

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        del pos
        if value == 0:
            return "0"
        absolute = abs(float(value))
        exponent = (
            np.log(absolute) / np.log(self.base) if absolute > 0 and self.base > 1 else np.nan
        )
        if not np.isfinite(exponent) or abs(exponent - round(exponent)) > 1e-9:
            return f"{value:g}"
        sign = "−" if value < 0 else ""  # noqa: RUF001 - intentional math minus
        power = str(round(float(exponent))).translate(_SUPERSCRIPT_DIGITS)
        return f"{sign}{self.base:g}{power}"


class LogitFormatter(Formatter):
    """Probability labels matching Matplotlib's major LogitFormatter forms."""

    def __init__(
        self,
        *,
        use_overline: bool = False,
        one_half: str = r"\frac{1}{2}",
        minor: bool = False,
    ) -> None:
        self.use_overline = bool(use_overline)
        self.one_half = "1/2" if one_half == r"\frac{1}{2}" else str(one_half)
        self.minor = bool(minor)
        self._locs = np.asarray([], dtype=float)

    def set_locs(self, locs: Any) -> None:
        self._locs = np.asarray(locs, dtype=float)

    @staticmethod
    def _power(value: float) -> str:
        exponent = round(float(np.log10(value)))
        return "10" + str(exponent).translate(_SUPERSCRIPT_DIGITS)

    @staticmethod
    def _overline(value: str) -> str:
        return "".join(character + "\N{COMBINING OVERLINE}" for character in value)

    def __call__(self, value: float, pos: Optional[int] = None) -> str:
        del pos
        value = float(value)
        if self.minor or not 0 < value < 1:
            return ""
        if np.isclose(value, 0.5, rtol=0, atol=1e-12):
            return self.one_half
        if value < 0.5 and np.isclose(np.log10(value), round(np.log10(value)), rtol=0, atol=1e-7):
            return self._power(value)
        complement = 1 - value
        if value > 0.5 and np.isclose(
            np.log10(complement),
            round(np.log10(complement)),
            rtol=0,
            atol=1e-7,
        ):
            power = self._power(complement)
            return (
                self._overline(power) if self.use_overline else f"1−{power}"  # noqa: RUF001 - intentional math minus
            )
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
