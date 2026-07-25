"""Colorbar tick formatting, and the gutters that keep formatted labels legible."""

from __future__ import annotations

import re

import numpy as np
import pytest

import xy
from xy import _svg


def svg_texts(chart: xy.Chart) -> list[str]:
    return re.findall(r">([^<>]+)</text>", chart.to_svg())


# ---------------------------------------------------------------------------
# Colorbar formats
# ---------------------------------------------------------------------------


def scatter_with_colorbar(**colorbar_kwargs) -> xy.Chart:
    values = np.linspace(12_000.0, 150_000.0, 200)
    return xy.scatter_chart(
        xy.scatter(np.arange(200.0), values, color=values, colormap="viridis"),
        xy.colorbar(**colorbar_kwargs),
    )


def test_colorbar_format_reaches_svg() -> None:
    labels = svg_texts(scatter_with_colorbar(title="spend", format="$,.0f"))
    assert any(label.startswith("$") and "," in label for label in labels), labels


def test_colorbar_without_format_keeps_the_general_default() -> None:
    labels = svg_texts(scatter_with_colorbar(title="spend"))
    assert not any(label.startswith("$") for label in labels)


def test_unparsable_colorbar_format_falls_back_to_general() -> None:
    labels = svg_texts(scatter_with_colorbar(title="spend", format="nonsense"))
    assert "nonsense" not in labels
    assert any(re.fullmatch(r"-?[\d.e+]+", label) for label in labels)


def test_colorbar_gutter_widens_for_wide_formatted_labels() -> None:
    plain = {"domain": [12_000.0, 150_000.0]}
    formatted = {"domain": [12_000.0, 150_000.0], "format": "$,.0f"}
    assert _svg.colorbar_right_room(formatted) > _svg.colorbar_right_room(plain)
    assert _svg.colorbar_label_offset(formatted) > _svg.colorbar_label_offset(plain)


def test_colorbar_gutter_never_narrows_below_the_historical_reserve() -> None:
    assert _svg.colorbar_right_room({"domain": [0.0, 1.0]}) == 86.0
    assert _svg.colorbar_label_offset({"domain": [0.0, 1.0]}) == 38.0


def test_colorbar_format_is_validated() -> None:
    with pytest.raises(ValueError, match="colorbar format"):
        xy.colorbar(format=3)


# ---------------------------------------------------------------------------
# The left gutter grows for tick labels wider than the default reserve
# ---------------------------------------------------------------------------


def plot_left(chart: xy.Chart) -> float:
    spec, _blob = chart.figure().build_payload()
    return _svg.layout(spec)[3]["x"]


SIX_FIGURE = [412_000.0, 468_000.0, 559_000.0]


def test_a_formatted_label_widens_the_left_gutter() -> None:
    plain = xy.line_chart(xy.line([1, 2, 3], SIX_FIGURE), xy.y_axis(label="revenue"))
    formatted = xy.line_chart(
        xy.line([1, 2, 3], SIX_FIGURE), xy.y_axis(label="revenue", format="$,.0f")
    )
    assert plot_left(formatted) > plot_left(plain)


def test_labels_that_already_fit_keep_the_historical_geometry() -> None:
    """The reserve is sized for ~6 characters; anything at or under that must
    not move, or every existing chart's layout shifts."""
    assert plot_left(xy.line_chart(xy.line([1, 2, 3], [1, 2, 3]), xy.y_axis(label="y"))) == 62.0
    assert plot_left(xy.line_chart(xy.line([1, 2, 3], SIX_FIGURE), xy.y_axis(label="r"))) == 62.0


def test_explicit_padding_is_never_second_guessed() -> None:
    chart = xy.line_chart(
        xy.line([1, 2, 3], SIX_FIGURE),
        xy.y_axis(label="r", format="$,.0f"),
        padding=(10, 10, 40, 50),
    )
    assert plot_left(chart) == 50.0


def test_the_gutter_is_capped_so_one_label_cannot_eat_the_plot() -> None:
    axes = {"y": {"id": "y", "range": [0.0, 1.0], "format": "$,.8f" + "x" * 40, "label": "y"}}
    room = _svg._left_axis_room(axes, 300.0, 62.0, _svg._BASE_FONT_SIZE)
    assert room <= 62.0 + _svg._Y_EXTRA_ROOM_CAP


def test_a_hidden_axis_contributes_no_gutter() -> None:
    chart = xy.line_chart(
        xy.line([1, 2, 3], SIX_FIGURE), xy.y_axis(format="$,.0f", tick_label_strategy="none")
    )
    assert plot_left(chart) == 62.0
