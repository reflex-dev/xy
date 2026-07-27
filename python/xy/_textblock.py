"""Renderer-independent geometry for newline-delimited chart chrome.

Axis titles and tick labels are text *blocks*, not strings.  Keeping their
line splitting and geometry here lets SVG layout, native raster layout, and
the pyplot compositor reserve the same footprint.  The browser mirrors these
small formulas because it must resolve responsive layout client-side.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar, cast

from . import _fontmetrics

LINE_HEIGHT = 1.2
_MeasurementKey = tuple[str, float, float]
_MEASUREMENTS: ContextVar[dict[_MeasurementKey, "TextBlock"] | None] = ContextVar(
    "xy_textblock_measurements",
    default=None,
)
_Return = TypeVar("_Return")


@dataclass(frozen=True)
class TextBlock:
    lines: tuple[str, ...]
    width: float
    height: float
    line_step: float
    ascent: float
    descent: float

    @property
    def line_count(self) -> int:
        return len(self.lines)


def split_lines(text: object) -> tuple[str, ...]:
    """Normalize line endings and preserve authored empty label lines."""
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    return tuple(normalized.split("\n")) or ("",)


@contextmanager
def measurement_cache() -> Iterator[None]:
    """Reuse pure text metrics within one nested layout or export pass."""
    if _MEASUREMENTS.get() is not None:
        yield
        return
    token = _MEASUREMENTS.set({})
    try:
        yield
    finally:
        _MEASUREMENTS.reset(token)


def cached_measurements(
    function: Callable[..., _Return],
) -> Callable[..., _Return]:
    """Run ``function`` inside one pass-scoped text-measurement cache."""

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> _Return:
        with measurement_cache():
            return function(*args, **kwargs)

    return cast(Callable[..., _Return], wrapped)


def measure(text: object, font_size: float, line_height: float = LINE_HEIGHT) -> TextBlock:
    """Measure a newline-delimited block in the core DejaVu metrics."""
    size = max(0.0, float(font_size))
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    resolved_line_height = float(line_height)
    key = (normalized, size, resolved_line_height)
    cache = _MEASUREMENTS.get()
    if cache is not None and key in cache:
        return cache[key]
    lines = tuple(normalized.split("\n")) or ("",)
    line_step = size * resolved_line_height
    ascent = size * _fontmetrics.ASCENT / _fontmetrics.BASE_PX
    descent = size * _fontmetrics.DESCENT / _fontmetrics.BASE_PX
    block = TextBlock(
        lines=lines,
        width=max((_fontmetrics.advance(line, size) for line in lines), default=0.0),
        # CSS line boxes own the full line-height, including the last line.
        height=max(line_step, len(lines) * line_step),
        line_step=line_step,
        ascent=ascent,
        descent=descent,
    )
    if cache is not None:
        cache[key] = block
    return block


def rotated_extent(block: TextBlock, angle_degrees: float) -> tuple[float, float]:
    """Axis-aligned ``(width, height)`` after rotating ``block``."""
    angle = abs(float(angle_degrees)) * math.pi / 180.0
    cosine = abs(math.cos(angle))
    sine = abs(math.sin(angle))
    return (
        cosine * block.width + sine * block.height,
        sine * block.width + cosine * block.height,
    )
