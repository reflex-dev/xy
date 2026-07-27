"""Renderer-independent geometry for newline-delimited chart chrome.

Axis titles and tick labels are text *blocks*, not strings.  Keeping their
line splitting and geometry here lets SVG layout, native raster layout, and
the pyplot compositor reserve the same footprint.  The browser mirrors these
small formulas because it must resolve responsive layout client-side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import _fontmetrics

LINE_HEIGHT = 1.2


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


def measure(text: object, font_size: float, line_height: float = LINE_HEIGHT) -> TextBlock:
    """Measure a newline-delimited block in the core DejaVu metrics."""
    size = max(0.0, float(font_size))
    lines = split_lines(text)
    line_step = size * float(line_height)
    ascent = size * _fontmetrics.ASCENT / _fontmetrics.BASE_PX
    descent = size * _fontmetrics.DESCENT / _fontmetrics.BASE_PX
    return TextBlock(
        lines=lines,
        width=max((_fontmetrics.advance(line, size) for line in lines), default=0.0),
        # CSS line boxes own the full line-height, including the last line.
        height=max(line_step, len(lines) * line_step),
        line_step=line_step,
        ascent=ascent,
        descent=descent,
    )


def rotated_extent(block: TextBlock, angle_degrees: float) -> tuple[float, float]:
    """Axis-aligned ``(width, height)`` after rotating ``block``."""
    angle = abs(float(angle_degrees)) * math.pi / 180.0
    cosine = abs(math.cos(angle))
    sine = abs(math.sin(angle))
    return (
        cosine * block.width + sine * block.height,
        sine * block.width + cosine * block.height,
    )
