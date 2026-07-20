from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

import xy
from xy import _themes

ALLOWED_TOKENS = {
    "background",
    "--chart-bg",
    "--chart-grid",
    "--chart-axis",
    "--chart-text",
    "--chart-crosshair",
    "--chart-selection",
    "--chart-selection-fill",
    "--chart-zoom-selection",
    "--chart-zoom-selection-fill",
    "--chart-tooltip-bg",
    "--chart-tooltip-text",
    "--chart-legend-bg",
    "--chart-badge-bg",
    "--chart-badge-text",
    "--chart-annotation-text",
    "--chart-modebar-bg",
    "--chart-modebar-active",
    "--chart-cursor",
    "--chart-cursor-pan",
    "--chart-focus",
}


def test_catalog_uses_implemented_tokens_and_valid_hex_palettes() -> None:
    for preset in _themes.PRESETS.values():
        assert set(preset.light) <= ALLOWED_TOKENS
        assert set(preset.dark) <= ALLOWED_TOKENS
        assert "background" in preset.light
        assert "background" in preset.dark
    for palette in _themes.PALETTES.values():
        assert palette
        assert all(color.startswith("#") and len(color) in {4, 7, 9} for color in palette)
        assert all(int(color[1:], 16) >= 0 for color in palette)
    assert xy.theme_presets() == tuple(sorted(_themes.PRESETS))
    assert xy.theme_palettes() == tuple(sorted(_themes.PALETTES))


def test_resolver_is_pure_and_preset_is_frozen() -> None:
    first = _themes.resolve_theme(preset="dashboard", color_scheme="dark")
    second = _themes.resolve_theme(preset="dashboard", color_scheme="dark")
    assert first == second
    assert first.style is not second.style
    first.style["background"] = "#123456"
    assert _themes.resolve_theme(preset="dashboard", color_scheme="dark") == second
    with pytest.raises(FrozenInstanceError):
        _themes.PRESETS["xy"].name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("kwargs", "bad", "expected"),
    [
        ({"preset": "nope"}, "nope", xy.theme_presets()),
        ({"palette": "nope"}, "nope", xy.theme_palettes()),
        ({"color_scheme": "nope"}, "nope", _themes.SCHEMES),
        ({"contrast": "nope"}, "nope", _themes.CONTRASTS),
    ],
)
def test_unknown_high_level_names_are_actionable(kwargs, bad, expected) -> None:
    with pytest.raises(ValueError) as exc_info:
        xy.theme(**kwargs)
    message = str(exc_info.value)
    assert bad in message
    assert repr(expected) in message


def test_accent_must_be_hex() -> None:
    with pytest.raises(ValueError) as exc_info:
        xy.theme(accent="red")
    message = str(exc_info.value)
    assert "accent" in message and "'red'" in message
    assert "#rgb" in message and "#rrggbb" in message and "#rrggbbaa" in message


def test_existing_theme_calls_keep_their_style_shape() -> None:
    assert xy.theme(style={"--chart-grid": "red"}).style == {"--chart-grid": "red"}
    assert xy.theme(background="#000000", plot_background="#111111").style == {
        "background": "#000000",
        "--chart-bg": "#111111",
    }


def test_resolution_precedence() -> None:
    light = xy.theme(preset="xy", color_scheme="light")
    dark = xy.theme(preset="xy", color_scheme="dark")
    assert light.style["background"] != dark.style["background"]
    accented = xy.theme(preset="xy", accent="#abc")
    assert accented.style["--chart-selection"] == "#aabbcc"
    named = xy.theme(preset="xy", grid_color="#123456")
    assert named.style["--chart-grid"] == "#123456"
    styled = xy.theme(
        preset="xy",
        grid_color="#123456",
        style={"--chart-grid": "#654321"},
    )
    assert styled.style["--chart-grid"] == "#654321"


def test_high_contrast_selects_accessible_defaults_unless_palette_is_explicit() -> None:
    high = _themes.resolve_theme(preset="dashboard", contrast="high")
    assert high.style["--chart-text"] == "#000000"
    assert high.palette == _themes.PALETTES["okabe_ito"]
    explicit = _themes.resolve_theme(contrast="high", palette="vibrant")
    assert explicit.palette == _themes.PALETTES["vibrant"]


def test_system_carries_both_variants_and_fixed_overrides() -> None:
    themed = xy.theme(preset="xy", color_scheme="system")
    expected_light = {**_themes.PRESETS["xy"].light, **_themes.accent_tokens("#6366f1")}
    expected_dark = {**_themes.PRESETS["xy"].dark, **_themes.accent_tokens("#6366f1")}
    assert themed.style == expected_light
    assert themed.dark_style == expected_dark
    overridden = xy.theme(preset="xy", color_scheme="system", grid_color="#123456")
    assert overridden.style["--chart-grid"] == "#123456"
    assert "--chart-grid" not in overridden.dark_style


def test_system_and_dark_scheme_wire_specs() -> None:
    system = xy.line_chart(
        xy.line([0, 1], [0, 1]),
        xy.theme(preset="dashboard", color_scheme="system"),
    ).figure()
    system_spec, _ = system.build_payload()
    assert system_spec["dom"]["styleDark"]
    assert system_spec["dom"]["colorScheme"] == "system"
    assert system_spec["dom"]["style"]["background"] == "#ffffff"

    dark = xy.line_chart(
        xy.line([0, 1], [0, 1]),
        xy.theme(preset="dashboard", color_scheme="dark"),
    ).figure()
    dark_spec, _ = dark.build_payload()
    assert "styleDark" not in dark_spec["dom"]
    assert dark_spec["dom"]["style"]["background"] == "#09090b"


def test_theme_palette_reaches_series_categories_and_respects_explicit_color() -> None:
    palette = _themes.PALETTES["okabe_ito"]
    chart = xy.line_chart(
        xy.line([0, 1], [0, 1]),
        xy.line([0, 1], [1, 2]),
        xy.theme(palette="okabe_ito"),
        style={"--chart-grid": "#123456"},
    )
    spec, _ = chart.figure().build_payload()
    assert [trace["style"]["color"] for trace in spec["traces"]] == list(palette[:2])
    assert spec["dom"]["style"]["--chart-grid"] == "#123456"

    explicit = xy.line_chart(
        xy.line([0, 1], [0, 1], color="#abcdef"),
        xy.theme(palette="okabe_ito"),
    ).figure()
    explicit_spec, _ = explicit.build_payload()
    assert explicit_spec["traces"][0]["style"]["color"] == "#abcdef"

    categorical = xy.scatter_chart(
        xy.scatter([0, 1], [0, 1], color=["a", "b"]),
        xy.theme(palette="okabe_ito"),
    ).figure()
    categorical_spec, _ = categorical.build_payload()
    assert categorical_spec["traces"][0]["color"]["palette"] == list(palette[:2])
