"""Use explicit unit conversion at XY's dependency-free native API boundary.

XY-native companion for Matplotlib 3.11.0's ``units/basic_units.py``.
This is an explicit API port, not a ``xy.pyplot`` import-swap example.

Upstream source SHA-256:
6a29366e933d0b0e268a66cbb5f67ce90e5759544f23ee2cc66df4c853a2e83d
Matplotlib's license is retained at ``../../LICENSE``.

The upstream helper exists to register converters in Matplotlib's unit
registry. Native XY intentionally has no Matplotlib registry. This companion
keeps the example's named units and conversions, then resolves them to ordinary
numbers before constructing an ``xy.line_chart``.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TypeVar

import xy

_T = TypeVar("_T", int, float)


def _map_values(
    values: _T | Sequence[_T],
    convert: Callable[[float], float],
) -> float | list[float]:
    if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
        return [convert(float(value)) for value in values]
    return convert(float(values))


class BasicUnit:
    """A small named unit with explicit conversion functions."""

    def __init__(self, name: str, fullname: str | None = None) -> None:
        self.name = name
        self.fullname = fullname or name
        self._conversions: dict[BasicUnit, Callable[[float], float]] = {}

    def __repr__(self) -> str:
        return f"BasicUnit({self.name!r})"

    def __str__(self) -> str:
        return self.fullname

    def __call__(self, value: _T | Sequence[_T]) -> TaggedValue:
        return TaggedValue(value, self)

    def __rmul__(self, value: _T) -> TaggedValue:
        return self(value)

    def add_conversion_factor(self, target: BasicUnit, factor: float) -> None:
        self._conversions[target] = lambda value: value * factor

    def add_conversion_fn(
        self,
        target: BasicUnit,
        convert: Callable[[float], float],
    ) -> None:
        self._conversions[target] = convert

    def convert(self, value: _T | Sequence[_T], target: BasicUnit) -> float | list[float]:
        if target is self:
            return _map_values(value, float)
        try:
            conversion = self._conversions[target]
        except KeyError as exc:
            raise ValueError(f"cannot convert {self.name} to {target.name}") from exc
        return _map_values(value, conversion)


class TaggedValue:
    """A value paired with a :class:`BasicUnit`."""

    def __init__(self, value: _T | Sequence[_T], unit: BasicUnit) -> None:
        self.value = value
        self.unit = unit

    def __repr__(self) -> str:
        return f"TaggedValue({self.value!r}, {self.unit!r})"

    def convert_to(self, target: BasicUnit) -> TaggedValue:
        return TaggedValue(self.unit.convert(self.value, target), target)

    def numbers(self) -> list[float]:
        values = self.value
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            return [float(value) for value in values]
        return [float(values)]


cm = BasicUnit("cm", "centimeters")
inch = BasicUnit("inch", "inches")
inch.add_conversion_factor(cm, 2.54)
cm.add_conversion_factor(inch, 1 / 2.54)

radians = BasicUnit("rad", "radians")
degrees = BasicUnit("deg", "degrees")
radians.add_conversion_factor(degrees, 180 / math.pi)
degrees.add_conversion_factor(radians, math.pi / 180)

secs = BasicUnit("s", "seconds")
hertz = BasicUnit("Hz", "Hertz")
minutes = BasicUnit("min", "minutes")
secs.add_conversion_fn(hertz, lambda value: 1 / value)
secs.add_conversion_factor(minutes, 1 / 60)


def rad_fn(value: float, _position: object = None) -> str:
    """Format multiples of pi/2 like the upstream helper."""

    offset = 0.25 if value >= 0 else -0.25
    numerator = int((value / math.pi) * 2 + offset)
    if numerator == 0:
        return "0"
    if numerator == 1:
        return r"$\pi/2$"
    if numerator == 2:
        return r"$\pi$"
    if numerator == -1:
        return r"$-\pi/2$"
    if numerator == -2:
        return r"$-\pi$"
    if numerator % 2 == 0:
        return rf"${numerator // 2}\pi$"
    return rf"${numerator}\pi/2$"


def cos(values: TaggedValue) -> float | list[float]:
    """Return cosine after resolving ``values`` to radians."""

    resolved = values.convert_to(radians)
    converted = resolved.value
    if isinstance(converted, Iterable) and not isinstance(
        converted,
        (str, bytes, bytearray),
    ):
        return [math.cos(float(value)) for value in converted]
    return math.cos(float(converted))


def build_chart() -> xy.Chart:
    """Construct the native companion chart from explicitly resolved units."""

    angles = degrees([0, 45, 90, 135, 180, 225, 270, 315, 360])
    x_values = angles.convert_to(radians).numbers()
    y_values = cos(angles)
    assert isinstance(y_values, list)
    return xy.line_chart(
        xy.line(x=x_values, y=y_values, name="cosine"),
        xy.x_axis(label=radians.fullname),
        xy.y_axis(label="cos(angle)"),
        xy.legend(),
        title="Explicit units at the native XY boundary",
        width=640,
        height=400,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("xy_basic_units.svg"))
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build_chart().to_svg(str(args.output))
    print(args.output)


if __name__ == "__main__":
    main()
