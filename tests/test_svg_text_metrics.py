"""Focused static-text layout regressions shared by SVG and native export."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from xy import _fontmetrics, _svg


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
