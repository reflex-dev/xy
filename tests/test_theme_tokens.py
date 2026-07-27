"""`xy.theme()`'s token vocabulary, and the tokens that reach a static file.

`**tokens` used to pass any keyword straight through as a CSS declaration, so a
typo emitted a property no renderer reads and changed nothing, silently. The
vocabulary is closed now, and the real `--chart-*` tokens became reachable by
name in the process.
"""

from __future__ import annotations

import re

import pytest

import xy
from xy.components import _THEME_TOKEN_NAMES


@pytest.mark.parametrize("token", sorted(_THEME_TOKEN_NAMES))
def test_every_named_token_maps_to_its_custom_property(token: str) -> None:
    style = xy.theme(**{token: "#123456"}).style
    assert style == {f"--chart-{token.replace('_', '-')}": "#123456"}


@pytest.mark.parametrize(
    "alias,prop",
    [
        ("plot_background", "--chart-bg"),
        ("grid_color", "--chart-grid"),
        ("axis_color", "--chart-axis"),
        ("text_color", "--chart-text"),
        ("crosshair_color", "--chart-crosshair"),
        ("selection_color", "--chart-selection"),
        ("selection_fill", "--chart-selection-fill"),
    ],
)
def test_the_documented_aliases_still_map(alias: str, prop: str) -> None:
    assert xy.theme(**{alias: "#123456"}).style == {prop: "#123456"}


def test_background_passes_through_as_the_root_css_property() -> None:
    # Deliberately not a token: it paints the whole figure card, margins and
    # all (mpl figure.facecolor), not just the plot rect.
    assert xy.theme(background="#123456").style == {"background": "#123456"}


@pytest.mark.parametrize("typo", ["grid_colour", "fnot_size", "colour", "textcolor", "bgcolor"])
def test_an_unknown_token_raises_instead_of_emitting_dead_css(typo: str) -> None:
    with pytest.raises(ValueError, match="unknown token"):
        xy.theme(**{typo: "#123456"})


def test_the_error_names_the_accepted_set() -> None:
    with pytest.raises(ValueError, match=r"tooltip_bg") as excinfo:
        xy.theme(grid_colour="#123456")
    assert "grid_color" in str(excinfo.value)


def test_legend_bg_token_reaches_the_static_writers() -> None:
    # A documented public token neither native writer read at all.
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series"),
        xy.theme(legend_bg="#ff00ff"),
    )
    frame = next(node for node in re.findall(r"<rect[^>]*/>", chart.to_svg()) if "#ff00ff" in node)
    assert 'fill-opacity="1"' in frame


def test_the_component_spelling_still_wins_over_the_token() -> None:
    # Narrowest selector last: token, then slot, then xy.legend(style=).
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series"),
        xy.theme(legend_bg="#ff00ff"),
        xy.legend(style={"background": "#00ff00"}),
    )
    svg = chart.to_svg()
    assert "#00ff00" in svg
    assert "#ff00ff" not in svg


def test_an_unset_token_leaves_the_default_frame_untouched() -> None:
    svg = xy.line_chart(xy.line([0.0, 1.0], [0.0, 1.0], name="series")).to_svg()
    assert 'fill="rgba(128,128,128,0.08)"' in svg


@pytest.mark.parametrize("spelling", ["__grid_colour", "__chart_bg", "__anything"])
def test_a_dunder_keyword_is_not_a_custom_property_escape_hatch(spelling: str) -> None:
    # An earlier draft mapped `__x_y` to `--x-y`, which reopened exactly the
    # dead-CSS hole the closed vocabulary exists to shut. `style=` is the
    # documented way to set a custom property directly.
    with pytest.raises(ValueError, match="unknown token"):
        xy.theme(**{spelling: "#123456"})


def test_style_remains_the_custom_property_channel() -> None:
    assert xy.theme(style={"--chart-bg": "#123456"}).style == {"--chart-bg": "#123456"}
