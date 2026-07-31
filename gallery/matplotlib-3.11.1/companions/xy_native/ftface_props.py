"""List properties of XY's embedded native font atlas.

XY-native companion for Matplotlib 3.11.0's ``misc/ftface_props.py``.
This is an explicit API port, not a ``xy.pyplot`` import-swap example.

Upstream source SHA-256:
ef85c2d8cf306cbfb9eb6b376f7693ead021bad07e7d9d5dd0445f186a463e0f
Matplotlib's license is retained at ``../../LICENSE``.

The upstream program describes an FT2Font object. XY does not link FreeType at
runtime; its Rust rasterizer scales a generated DejaVu Sans coverage atlas.
These are the corresponding stable atlas properties.
"""

from __future__ import annotations

from xy import _fontmetrics


def atlas_properties() -> dict[str, int | str]:
    """Return the global metrics baked into XY's native rasterizer."""

    ascii_count = _fontmetrics.LAST - _fontmetrics.FIRST + 1
    return {
        "family": "DejaVu Sans",
        "style": "Regular",
        "runtime_font_engine": "embedded coverage atlas",
        "base_px": _fontmetrics.BASE_PX,
        "cell_height": _fontmetrics.CELL_H,
        "ascent": _fontmetrics.ASCENT,
        "descent": _fontmetrics.DESCENT,
        "glyph_count": ascii_count + len(_fontmetrics.EXTRA_ADVANCES),
        "first_ascii_codepoint": _fontmetrics.FIRST,
        "last_ascii_codepoint": _fontmetrics.LAST,
    }


def main() -> None:
    for name, value in atlas_properties().items():
        print(f"{name:22} {value}")


if __name__ == "__main__":
    main()
