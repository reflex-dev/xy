"""Custom colormaps and a settable series palette."""

from __future__ import annotations

import re

import numpy as np
import pytest

import xy
from xy import channels
from xy.config import DEFAULT_PALETTE

# ---------------------------------------------------------------------------
# Custom colormaps
# ---------------------------------------------------------------------------

CUSTOM_CMAP = ["#0d1b2a", "#1b6ca8", "#48cae4", "#ffd166", "#ef476f"]


def test_custom_colormap_resolves_to_rgb_stops() -> None:
    assert channels.resolve_colormap(["#ff0000", "#0000ff"]) == [[255, 0, 0], [0, 0, 255]]
    assert channels.resolve_colormap("viridis") == "viridis"


def test_custom_colormap_paints_marks_and_the_colorbar() -> None:
    values = np.linspace(0.0, 1.0, 200)
    chart = xy.scatter_chart(
        xy.scatter(np.arange(200.0), values, color=values, colormap=CUSTOM_CMAP),
        xy.colorbar(title="t"),
    )
    svg = chart.to_svg()
    stops = re.findall(r'stop-color="rgb\(([^)]+)\)"', svg)
    assert stops == ["13,27,42", "27,108,168", "72,202,228", "255,209,102", "239,71,111"]


def test_custom_colormap_reaches_the_wire_for_the_browser() -> None:
    values = np.linspace(0.0, 1.0, 50)
    figure = xy.scatter_chart(
        xy.scatter(np.arange(50.0), values, color=values, colormap=CUSTOM_CMAP)
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["traces"][0]["color"]["colormap"] == [
        [13, 27, 42],
        [27, 108, 168],
        [72, 202, 228],
        [255, 209, 102],
        [239, 71, 111],
    ]


def test_custom_colormap_works_on_heatmaps() -> None:
    grid = np.add.outer(np.linspace(0.0, 1.0, 8), np.linspace(0.0, 1.0, 8))
    svg = xy.heatmap_chart(xy.heatmap(z=grid, colormap=CUSTOM_CMAP)).to_svg()
    assert svg.startswith("<svg")


@pytest.mark.parametrize(
    ("colormap", "message"),
    [
        (["#ff0000"], "between 2 and 256"),
        (["#ff0000"] * 257, "between 2 and 256"),
        (["#ff0000", "not-a-color"], "not a color XY can resolve"),
        # A browser-resolved form has no RGB this process can sample.
        (["#ff0000", "var(--brand)"], "not a color XY can resolve"),
        (["#ff0000", 7], "must be a CSS color string"),
        (7, "must be a built-in colormap name"),
        ({"a": "#ff0000"}, "must be a built-in colormap name"),
        ("nope", "unknown colormap"),
    ],
)
def test_bad_colormaps_raise_a_message_that_names_the_problem(colormap, message) -> None:
    with pytest.raises(ValueError, match=message):
        channels.resolve_colormap(colormap)


# ---------------------------------------------------------------------------
# Series palette
# ---------------------------------------------------------------------------

BRAND = ["#ff5c00", "#111827", "#00b3a4", "#8b5cf6"]


def test_theme_palette_colors_unnamed_series() -> None:
    x = np.arange(6.0)
    chart = xy.line_chart(
        *[xy.line(x, x + index, name=f"s{index}") for index in range(4)],
        xy.theme(palette=BRAND),
    )
    svg = chart.to_svg().lower()
    assert all(color in svg for color in BRAND)


def test_theme_palette_colors_a_categorical_channel() -> None:
    codes = np.array(["a", "b", "c", "d"] * 25)
    figure = xy.scatter_chart(
        xy.scatter(np.arange(100.0), np.arange(100.0), color=codes),
        xy.theme(palette=BRAND),
    ).figure()
    spec, _blob = figure.build_payload()
    assert spec["traces"][0]["color"]["palette"] == BRAND


def test_palette_repeats_once_it_runs_out() -> None:
    x = np.arange(4.0)
    figure = xy.line_chart(
        *[xy.line(x, x + index, name=f"s{index}") for index in range(6)],
        xy.theme(palette=BRAND[:2]),
    ).figure()
    spec, _blob = figure.build_payload()
    colors = [trace["style"]["color"] for trace in spec["traces"]]
    assert colors == [BRAND[0], BRAND[1]] * 3


def test_no_palette_keeps_the_cvd_validated_default() -> None:
    x = np.arange(4.0)
    figure = xy.line_chart(*[xy.line(x, x + i, name=f"s{i}") for i in range(3)]).figure()
    spec, _blob = figure.build_payload()
    assert [trace["style"]["color"] for trace in spec["traces"]] == DEFAULT_PALETTE[:3]


def test_a_user_palette_skips_the_default_palette_wrap_warning() -> None:
    """The eight-slot warning polices XY's CVD guarantee, which a user palette
    never claimed — warning about it would be noise.

    Uses more series than the DEFAULT palette has slots, so the warning would
    definitely fire if the user palette still went through
    `config.default_palette_color`.
    """
    import warnings

    x = np.arange(3.0)
    marks = [xy.line(x, x + index, name=f"s{index}") for index in range(len(DEFAULT_PALETTE) + 3)]

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        xy.line_chart(*marks, xy.theme(palette=BRAND)).figure().build_payload()
    assert [str(record.message) for record in records] == []

    # Same chart on the shipped default still warns, so the assertion above is
    # about the palette source and not about the warning being unreachable.
    with warnings.catch_warnings(record=True) as default_records:
        warnings.simplefilter("always")
        xy.line_chart(*marks).figure().build_payload()
    assert any("default palette repeats" in str(r.message) for r in default_records)


@pytest.mark.parametrize(
    ("palette", "message"),
    [
        ("#ff0000", "must be a sequence"),
        ([], "at least one color"),
        (["not-a-color"], "theme palette"),
    ],
)
def test_bad_palettes_raise(palette, message) -> None:
    with pytest.raises(ValueError, match=message):
        xy.theme(palette=palette)
