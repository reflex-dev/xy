"""Matplotlib authored-marker normalization.

The native scatter fast path intentionally has a small fixed symbol table.
Pyplot accepts a wider marker grammar, so this module compiles the bounded
parts of that grammar into renderer-neutral contours or a single embedded
font glyph.  Unknown forms fail here instead of silently becoming circles.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from xy import _fontmetrics

from ._mathtext import mathtext_to_unicode
from ._translate import MARKER_TO_SYMBOL, not_implemented

_MAX_CONTOURS = 32
_MAX_VERTICES = 64


def marker_render_spec(marker: Any) -> dict[str, Any]:
    """Return core scatter kwargs for one Matplotlib marker value."""
    try:
        symbol = MARKER_TO_SYMBOL.get(marker)
    except TypeError:
        symbol = None
    if symbol is not None:
        return {"symbol": symbol}

    if isinstance(marker, str):
        if marker.startswith("$") and marker.endswith("$"):
            glyph = mathtext_to_unicode(marker)
            if glyph == marker or len(glyph) != 1 or not _embedded_font_has(glyph):
                raise not_implemented(
                    f"marker mathtext {marker!r}",
                    "a single supported math symbol such as r'$\\clubsuit$'",
                )
            return {"symbol": "circle", "_marker_glyph": glyph}
        raise ValueError(f"unsupported marker: {marker!r}")

    regular = _regular_marker(marker)
    if regular is not None:
        return {"symbol": "circle", "_marker_path": regular}

    try:
        vertices = np.asarray(marker, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported marker: {marker!r}") from exc
    if vertices.ndim != 2 or vertices.shape[1] != 2:
        raise ValueError("custom marker vertices must have shape (N, 2)")
    if not 3 <= len(vertices) <= _MAX_VERTICES:
        raise ValueError(
            f"custom marker paths require 3-{_MAX_VERTICES} vertices, got {len(vertices)}"
        )
    if not np.all(np.isfinite(vertices)):
        raise ValueError("custom marker vertices must be finite")
    extent = float(np.max(np.abs(vertices)))
    if extent <= 0:
        raise ValueError("custom marker vertices must span a non-zero extent")
    normalized = vertices * (0.5 / extent)
    closed = bool(np.allclose(normalized[0], normalized[-1]))
    if not closed:
        normalized = np.vstack((normalized, normalized[0]))
    return {
        "symbol": "circle",
        "_marker_path": {
            "contours": [_flat(normalized)],
            "filled": True,
        },
    }


def _embedded_font_has(glyph: str) -> bool:
    code = ord(glyph)
    return _fontmetrics.FIRST <= code <= _fontmetrics.LAST or code in _fontmetrics.EXTRA_ADVANCES


def _regular_marker(marker: Any) -> dict[str, Any] | None:
    if not isinstance(marker, tuple) or len(marker) not in {2, 3}:
        return None
    sides, style = marker[:2]
    angle = marker[2] if len(marker) == 3 else 0.0
    if not isinstance(sides, (int, np.integer)) or not isinstance(style, (int, np.integer)):
        return None
    sides, style = int(sides), int(style)
    if not 3 <= sides <= _MAX_CONTOURS:
        raise ValueError(f"regular marker side count must be 3-{_MAX_CONTOURS}")
    if style not in {0, 1, 2}:
        raise ValueError("regular marker style must be 0 (polygon), 1 (star), or 2 (asterisk)")
    try:
        angle = float(angle)
    except (TypeError, ValueError) as exc:
        raise ValueError("regular marker angle must be a finite number") from exc
    if not math.isfinite(angle):
        raise ValueError("regular marker angle must be a finite number")

    # Matplotlib's regular markers start at 90 degrees in y-up marker space.
    phase = math.radians(90.0 + angle)
    outer = np.asarray(
        [
            (
                0.5 * math.cos(phase + 2 * math.pi * index / sides),
                0.5 * math.sin(phase + 2 * math.pi * index / sides),
            )
            for index in range(sides)
        ],
        dtype=np.float64,
    )
    if style == 2:
        return {
            "contours": [[0.0, 0.0, float(vertex[0]), float(vertex[1])] for vertex in outer],
            "filled": False,
        }
    vertices = outer
    if style == 1:
        inner = np.asarray(
            [
                (
                    0.25 * math.cos(phase + (2 * index + 1) * math.pi / sides),
                    0.25 * math.sin(phase + (2 * index + 1) * math.pi / sides),
                )
                for index in range(sides)
            ],
            dtype=np.float64,
        )
        vertices = np.empty((sides * 2, 2), dtype=np.float64)
        vertices[0::2], vertices[1::2] = outer, inner
    vertices = np.vstack((vertices, vertices[0]))
    return {"contours": [_flat(vertices)], "filled": True}


def _flat(vertices: np.ndarray) -> list[float]:
    return [float(value) for value in vertices.reshape(-1)]
