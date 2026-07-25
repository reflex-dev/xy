"""Chart-wide typography: `theme(font_family=)` and `theme(font_size=)`."""

from __future__ import annotations

import re

import pytest

import xy


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


def titled_chart(**theme_kwargs) -> xy.Chart:
    children = [xy.line([1, 2, 3], [1, 2, 3]), xy.x_axis(label="x")]
    if theme_kwargs:
        children.append(xy.theme(**theme_kwargs))
    return xy.line_chart(*children, title="T")


def test_theme_font_family_reaches_the_svg() -> None:
    svg = titled_chart(font_family="Georgia, serif").to_svg()
    assert 'font-family="Georgia, serif"' in svg
    assert "system-ui" not in svg


def test_theme_font_size_scales_every_chrome_size_together() -> None:
    default = set(re.findall(r'font-size="([^"]+)"', titled_chart().to_svg()))
    assert default == {"11", "12", "14"}
    scaled = set(re.findall(r'font-size="([^"]+)"', titled_chart(font_size=22).to_svg()))
    # 22/11 = exactly 2x the defaults, so the proportions are preserved.
    assert scaled == {"22", "24", "28"}


def test_an_unthemed_chart_keeps_its_pre_existing_font_chrome() -> None:
    """The font tokens must be a pure addition: with no theme, the root font
    stack and every chrome size are exactly what they were before."""
    svg = titled_chart().to_svg()
    assert "font-family=\"system-ui, -apple-system, 'Segoe UI', sans-serif\"" in svg
    assert 'font-size="11"' in svg  # root / tick labels
    assert 'font-size="12"' in svg  # axis title
    assert 'font-size="14"' in svg  # chart title


def test_font_size_is_bounded() -> None:
    with pytest.raises(ValueError, match="between 6 and 48"):
        xy.theme(font_size=200)
    with pytest.raises(ValueError, match="between 6 and 48"):
        xy.theme(font_size=1)


def test_font_family_is_declaration_checked() -> None:
    with pytest.raises(ValueError):
        xy.theme(font_family="Georgia; background:url(evil)")


def test_font_size_changes_the_native_png_even_though_the_family_cannot(tmp_path) -> None:
    plain = tmp_path / "plain.png"
    sized = tmp_path / "sized.png"
    serif = tmp_path / "serif.png"
    titled_chart().to_png(str(plain), width=420, height=260)
    titled_chart(font_size=18).to_png(str(sized), width=420, height=260)
    titled_chart(font_family="Georgia, serif").to_png(str(serif), width=420, height=260)
    assert sized.read_bytes() != plain.read_bytes()
    # The native rasterizer draws a baked bitmap face; the family is honored by
    # SVG/PDF and the browser instead (docs/styling/themes-and-tokens.md).
    assert serif.read_bytes() == plain.read_bytes()
