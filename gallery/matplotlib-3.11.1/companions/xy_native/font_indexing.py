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

_EXTRA_CODEPOINTS = tuple(sorted(_fontmetrics.EXTRA_ADVANCES))


def _atlas_row_for_codepoint(codepoint: int) -> int | None:
    if _fontmetrics.FIRST <= codepoint <= _fontmetrics.LAST:
        return codepoint - _fontmetrics.FIRST
    try:
        return _fontmetrics.LAST - _fontmetrics.FIRST + 1 + _EXTRA_CODEPOINTS.index(codepoint)
    except ValueError:
        return None


def _native_glyph(character: str) -> str | None:
    if len(character) != 1:
        raise ValueError("atlas_row expects exactly one character")
    codepoint = ord(character)
    if _atlas_row_for_codepoint(codepoint) is not None:
        return character
    if codepoint <= 0x1F or 0x7F <= codepoint <= 0x9F:
        return None
    if 0x200B <= codepoint <= 0x200F or codepoint == 0xFEFF:
        return None
    if character.isspace():
        return " "
    return "\ufffd"


def atlas_row(character: str) -> int | None:
    """Return the native atlas row used for one character.

    Controls and zero-width characters are dropped, unsupported whitespace
    uses the ordinary space row, and other unsupported codepoints resolve to
    the visible U+FFFD replacement glyph, matching the native rasterizer.
    """

    glyph = _native_glyph(character)
    if glyph is None:
        return None
    row = _atlas_row_for_codepoint(ord(glyph))
    assert row is not None
    return row


def glyph_record(character: str) -> dict[str, int | float | None]:
    """Describe the native atlas entry for one character."""

    glyph = _native_glyph(character)
    return {
        "codepoint": ord(character),
        "atlas_row": atlas_row(character),
        "advance_px": (0.0 if glyph is None else _fontmetrics.advance(glyph, _fontmetrics.BASE_PX)),
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
