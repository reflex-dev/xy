"""Inspect the glyph indexing used by XY's embedded native font atlas.

XY-native companion for Matplotlib 3.11.0's ``misc/font_indexing.py``.
This is an explicit API port, not a ``xy.pyplot`` import-swap example.

Upstream source SHA-256:
db0d48faec6711f9d6fb6e266efb47a242de0d5176f4460e28b5833a5083bbf8
Matplotlib's license is retained at ``../../LICENSE``.

Matplotlib's example inspects a FreeType face. XY's dependency-free native
rasterizer instead uses a generated DejaVu Sans bitmap atlas, so the analogous
diagnostic reports atlas rows and advances. The native atlas deliberately has
no kerning table: pair advances are additive.
"""

from __future__ import annotations

from xy import _fontmetrics


def atlas_row(character: str) -> int:
    """Return the native atlas row used for one character.

    Unsupported codepoints resolve to the visible U+FFFD replacement glyph,
    matching the native rasterizer.
    """

    if len(character) != 1:
        raise ValueError("atlas_row expects exactly one character")
    codepoint = ord(character)
    if _fontmetrics.FIRST <= codepoint <= _fontmetrics.LAST:
        return codepoint - _fontmetrics.FIRST
    extras = tuple(sorted(_fontmetrics.EXTRA_ADVANCES))
    try:
        return _fontmetrics.LAST - _fontmetrics.FIRST + 1 + extras.index(codepoint)
    except ValueError:
        replacement = extras.index(0xFFFD)
        return _fontmetrics.LAST - _fontmetrics.FIRST + 1 + replacement


def glyph_record(character: str) -> dict[str, int | float]:
    """Describe the native atlas entry for one character."""

    return {
        "codepoint": ord(character),
        "atlas_row": atlas_row(character),
        "advance_px": _fontmetrics.advance(character, _fontmetrics.BASE_PX),
    }


def main() -> None:
    for character in ("A", "V", "T"):
        record = glyph_record(character)
        print(
            character,
            record["atlas_row"],
            record["codepoint"],
            record["advance_px"],
        )
    for pair in ("AV", "AT"):
        print(
            pair,
            _fontmetrics.advance(pair, _fontmetrics.BASE_PX),
            "kerning=0",
        )


if __name__ == "__main__":
    main()
