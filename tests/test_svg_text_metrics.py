"""Focused static-text layout regressions shared by SVG and native export."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from xy import _fontmetrics, _svg, _textblock


def test_text_box_width_uses_embedded_advances_with_unknown_glyph_fallback() -> None:
    font_size = 11.0

    assert _svg._estimated_text_width(["gamma"], font_size) == pytest.approx(
        _fontmetrics.advance("gamma", font_size)
    )
    assert _svg._estimated_text_width(["iiii", "gamma"], font_size) == pytest.approx(
        _fontmetrics.advance("gamma", font_size)
    )
    assert _svg._estimated_text_width(["🦉"], font_size) == pytest.approx(font_size)
    assert _svg._estimated_text_width([], font_size) == 0.0


def test_svg_mathtext_ranges_are_sorted_clamped_and_merged_without_duplicate_text() -> None:
    rendered = _svg._svg_mathtext_spans(
        "abcdef",
        {"math_italic_ranges": "2:4,0:3,2:4,-5:1,5:99"},
        0,
    )
    root = ET.fromstring(f"<text>{rendered}</text>")

    assert "".join(root.itertext()) == "abcdef"
    assert [node.text for node in root if node.tag.endswith("tspan")] == ["abcd", "f"]


def test_left_gutter_measures_y_tick_labels_once_for_an_outside_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def measured_room(axis: dict[str, object], plot_h: float) -> tuple[float, float]:
        nonlocal calls
        calls += 1
        assert axis["label"] == "Y"
        assert plot_h == 300.0
        return 7.0, 23.0

    monkeypatch.setattr(_svg, "_y_tick_label_room", measured_room)
    label_size = 12.0
    spec = {
        "x_axis": {},
        "y_axis": {
            "label": "Y",
            "side": "left",
            "style": {"label_size": label_size},
        },
    }

    room = _svg._y_axis_left_room(spec, 300.0)
    ascent, descent = _svg._text_cell(label_size)
    expected = (
        _svg._AXIS_TEXT_EDGE_PAD
        + ascent
        + descent
        + _svg._Y_TITLE_TICK_GAP * label_size
        + 7.0
        + 23.0
    )

    assert calls == 1
    assert room == pytest.approx(expected)


def test_measurements_are_reused_only_within_one_layout_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = _fontmetrics.advance

    def measured(text: str, font_size: float) -> float:
        nonlocal calls
        calls += 1
        return original(text, font_size)

    monkeypatch.setattr(_fontmetrics, "advance", measured)
    with _textblock.measurement_cache():
        first = _textblock.measure("first\r\nsecond", 12.0)
        second = _textblock.measure("first\nsecond", 12.0)

    assert second is first
    assert calls == 2

    with _textblock.measurement_cache():
        _textblock.measure("first\nsecond", 12.0)
    assert calls == 4


def test_default_layout_resolves_x_tick_room_once_when_y_gutter_does_not_grow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = _svg._x_axis_rooms

    def measured(
        axes: dict[str, dict[str, object]],
        plot_w: float,
        compact: bool,
    ) -> tuple[float, float, float]:
        nonlocal calls
        calls += 1
        return original(axes, plot_w, compact)

    monkeypatch.setattr(_svg, "_x_axis_rooms", measured)

    def unexpected_label_layout(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ordinary numeric x ticks must keep the fixed single-line band")

    monkeypatch.setattr(_svg, "_axis_tick_label_layout", unexpected_label_layout)
    spec = {
        "width": 640,
        "height": 480,
        "x_axis": {"range": [0.0, 1.0]},
        "y_axis": {"range": [0.0, 1.0], "side": "left"},
    }

    _svg.layout(spec)

    assert calls == 1
