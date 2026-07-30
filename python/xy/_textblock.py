"""Renderer-independent geometry for newline-delimited chart chrome.

Axis titles and tick labels are text *blocks*, not strings.  Keeping their
line splitting and geometry here lets SVG layout, native raster layout, and
the pyplot compositor reserve the same footprint.  The browser mirrors these
small formulas because it must resolve responsive layout client-side.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar, cast

from . import _fontmetrics

LINE_HEIGHT = 1.2
_MeasurementKey = tuple[str, float, float, float | None]
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


def wrap_lines(lines: Sequence[str], font_size: float, max_width: float) -> tuple[str, ...]:
    """Greedy word wrap of already newline-split lines, at `max_width` px.

    Mirrors `xyWrapLines` in js/src/50_chartview.ts, and matches how CSS
    `white-space: pre-line` treats the same string: authored newlines are hard
    breaks (the caller has already split on them), runs of other whitespace
    collapse to one space, and a break is only ever taken at a space. A single
    word wider than `max_width` keeps its own line and overflows, because that
    is what a browser does without an explicit `overflow-wrap`.
    """
    size = max(0.0, float(font_size))
    limit = float(max_width)
    wrapped: list[str] = []
    for line in lines:
        words = str(line).split()
        if not words:
            wrapped.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _fontmetrics.advance(candidate, size) <= limit:
                current = candidate
            else:
                wrapped.append(current)
                current = word
        wrapped.append(current)
    return tuple(wrapped)


def measure(
    text: object,
    font_size: float,
    line_height: float = LINE_HEIGHT,
    max_width: float | None = None,
) -> TextBlock:
    """Measure a newline-delimited block in the core DejaVu metrics.

    A finite positive `max_width` word-wraps the block first, so the measured
    height is the height the wrapped text actually occupies. Callers that wrap
    must draw `block.lines`, not the original string, or the reservation and the
    drawing disagree — which is exactly how a wrapped chart title came to be
    clipped in the browser while layout reserved one line for it.
    """
    size = max(0.0, float(font_size))
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    resolved_line_height = float(line_height)
    limit: float | None = None if max_width is None else float(max_width)
    if limit is not None and not (math.isfinite(limit) and limit > 0.0):
        limit = None
    key = (normalized, size, resolved_line_height, limit)
    cache = _MEASUREMENTS.get()
    if cache is not None and key in cache:
        return cache[key]
    lines = tuple(normalized.split("\n")) or ("",)
    if limit is not None:
        lines = wrap_lines(lines, size, limit)
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
