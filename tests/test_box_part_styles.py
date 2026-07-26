"""Box plots expose each visible part without inventing a second style system."""

from __future__ import annotations

import re

import pytest

import xy
from xy._figure import Figure

VALUES = [1.0, 2.0, 3.0, 4.0, 100.0]
GROUPS = ["cohort"] * len(VALUES)


def _styled_figure() -> Figure:
    return Figure().box(
        VALUES,
        group=GROUPS,
        color="#60a5fa",
        style={
            "fill": "#dbeafe",
            "fill-opacity": 0.4,
            "stroke": "#2563eb",
            "stroke-width": 2,
            "stroke-opacity": 0.9,
        },
        whisker_style={
            "stroke": "#64748b",
            "stroke-width": 1.5,
            "stroke-opacity": 0.7,
        },
        median_style={"stroke": "#0f172a", "stroke-width": 3},
        outlier_style={
            "fill": "#ffffff",
            "stroke": "#dc2626",
            "stroke-width": 2,
            "marker-shape": "diamond",
        },
    )


def test_box_parts_compile_to_independent_shared_renderer_traces() -> None:
    spec, _ = _styled_figure().build_payload()
    traces = {trace["kind"]: trace for trace in spec["traces"]}

    assert traces["box"]["style"] == {
        "color": "#dbeafe",
        "opacity": 0.85,
        "role": "box",
        "stroke_width": 2.0,
        "box_orientation": "vertical",
        "stroke": "#2563eb",
        "fill_opacity": 0.4,
        "stroke_opacity": 0.9,
    }
    assert traces["box_whisker"]["style"] == {
        "color": "#64748b",
        "opacity": 0.85,
        "width": 1.5,
        "role": "box-whisker",
        "stroke_opacity": 0.7,
    }
    assert traces["box_median"]["style"] == {
        "color": "#0f172a",
        "opacity": 0.85,
        "width": 3.0,
        "role": "box-median",
    }
    assert traces["scatter"]["style"] == {
        "opacity": 0.85,
        "symbol": "diamond",
        "stroke": "#dc2626",
        "stroke_width": 2.0,
    }


def test_unstyled_box_keeps_its_existing_trace_style_defaults() -> None:
    spec, _ = Figure().box(VALUES, group=GROUPS).build_payload()

    assert [trace["style"] for trace in spec["traces"]] == [
        {
            "color": "#3987e5",
            "opacity": 0.85,
            "width": 1.0,
            "role": "box-whisker",
        },
        {
            "color": "#3987e5",
            "opacity": 0.85,
            "role": "box",
            "stroke_width": 1.0,
            "box_orientation": "vertical",
        },
        {
            "color": "#3987e5",
            "opacity": 0.85,
            "width": 1.4,
            "role": "box-median",
        },
        {"opacity": 0.85},
    ]


def test_box_component_routes_part_styles_to_the_figure() -> None:
    chart = xy.box_chart(
        xy.box(
            VALUES,
            group=GROUPS,
            style={"fill": "#dbeafe", "stroke": "#2563eb", "stroke-width": 2},
            median_style={"stroke": "#0f172a", "stroke-width": 3},
            whisker_style={"stroke-opacity": 0.5},
            outlier_style={"marker-shape": "diamond"},
        )
    )
    spec, _ = chart.figure().build_payload()

    assert [trace["kind"] for trace in spec["traces"]] == [
        "box_whisker",
        "box",
        "box_median",
        "scatter",
    ]
    assert spec["traces"][1]["style"]["stroke"] == "#2563eb"
    assert spec["traces"][2]["style"]["width"] == 3.0
    assert spec["traces"][3]["style"]["symbol"] == "diamond"


def test_box_part_styles_keep_strict_family_specific_validation() -> None:
    with pytest.raises(
        ValueError,
        match=re.escape("box whisker_style has unsupported CSS property/properties ['fill']"),
    ):
        Figure().box(VALUES, group=GROUPS, whisker_style={"fill": "#ef4444"})

    with pytest.raises(
        ValueError,
        match=re.escape("box style has unsupported CSS property/properties ['marker-shape']"),
    ):
        Figure().box(VALUES, group=GROUPS, style={"marker-shape": "diamond"})


def test_box_part_styles_survive_native_vector_export() -> None:
    svg = _styled_figure().to_svg()

    for paint in ("#64748b", "#0f172a", "#dc2626"):
        assert paint in svg
    assert 'fill="rgb(219,234,254)"' in svg
    assert 'stroke="rgb(37,99,235)"' in svg
    assert 'stroke-width="3"' in svg
    assert re.search(r'<path d="M [^"]+ Z"[^>]+stroke="#dc2626"', svg)
