"""CSS-first mark styling stays a renderer contract, not a state framework."""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy import _raster, _svg
from xy._figure import Figure
from xy.styles import compile_mark_style, normalize_css_style


def test_renderer_style_capabilities_are_not_a_public_schema() -> None:
    assert not hasattr(xy, "mark_style_schema")


def test_python_style_aliases_normalize_to_css_names() -> None:
    assert normalize_css_style({"stroke_width": "2px", "fill_opacity": 0.5}) == {
        "stroke-width": "2px",
        "fill-opacity": 0.5,
    }
    with pytest.raises(ValueError, match="more than once"):
        normalize_css_style({"stroke_width": 1, "stroke-width": 2})


def test_line_css_compiles_to_existing_renderer_contract() -> None:
    compiled = compile_mark_style(
        "line",
        {
            "stroke": "#ef4444",
            "stroke-width": "2.5px",
            "stroke-opacity": "0.75",
            "stroke-dasharray": "6px 3px",
        },
    )

    assert compiled == {
        "color": "#ef4444",
        "width": 2.5,
        "stroke_opacity": 0.75,
        "dash": [6.0, 3.0],
    }


def test_css_opacity_channels_remain_independent_in_svg() -> None:
    fig = xy.chart(
        xy.scatter(
            x=[0.0],
            y=[1.0],
            size=10,
            style={
                "opacity": 0.5,
                "fill-opacity": 0.4,
                "stroke": "black",
                "stroke-width": 2,
                "stroke-opacity": 0.8,
            },
        )
    ).figure()

    assert fig.traces[0].style["fill_opacity"] == pytest.approx(0.4)
    assert fig.traces[0].style["stroke_opacity"] == pytest.approx(0.8)
    svg = fig.to_svg()
    assert 'fill-opacity="0.2"' in svg
    assert 'stroke-opacity="0.4"' in svg


def test_css_style_wins_over_legacy_appearance_aliases() -> None:
    fig = xy.chart(
        xy.line(
            x=[0.0, 1.0],
            y=[1.0, 2.0],
            color="blue",
            width=9,
            opacity=1,
            style={"stroke": "red", "stroke-width": "2px", "opacity": 0.4},
        )
    ).figure()

    assert fig.traces[0].style == {"color": "red", "width": 2.0, "opacity": 0.4}


def test_css_color_is_not_an_alias_for_mark_paint() -> None:
    with pytest.raises(ValueError, match=r"unsupported CSS property.*color"):
        xy.chart(
            xy.line(
                x=[0.0, 1.0],
                y=[1.0, 2.0],
                style={"color": "red", "stroke": "currentColor"},
            )
        ).figure()

    fig = xy.chart(
        xy.line(
            x=[0.0, 1.0],
            y=[1.0, 2.0],
            color="red",
            style={"stroke": "blue"},
        )
    ).figure()
    assert fig.traces[0].style["color"] == "blue"


def test_scatter_and_rect_css_use_fill_stroke_and_border_radius() -> None:
    chart = xy.chart(
        xy.scatter(
            x=[0.0, 1.0],
            y=[1.0, 2.0],
            style={"fill": "#22c55e", "stroke": "#052e16", "stroke-width": 2},
        ),
        xy.bar(
            x=[3.0, 4.0],
            y=[1.0, 2.0],
            style={
                "fill": "linear-gradient(to top, #2563eb, #93c5fd)",
                "stroke": "#1e3a8a",
                "stroke-width": "1px",
                "border-radius": "4px",
            },
        ),
    )
    fig = chart.figure()

    scatter = fig.traces[0]
    assert scatter.color_ch is not None and scatter.color_ch.constant == "#22c55e"
    assert scatter.style["stroke"] == "#052e16"
    assert scatter.style["stroke_width"] == 2.0

    bar = fig.traces[1]
    assert bar.style["stroke"] == "#1e3a8a"
    assert bar.style["stroke_width"] == 1.0
    assert bar.style["corner_radius"] == 4.0
    assert bar.style["fill"]["stops"][0][1] == "#2563eb"


def test_css_mark_style_reaches_svg_and_native_renderers() -> None:
    fig = xy.chart(
        xy.scatter(
            x=[0.0, 1.0],
            y=[1.0, 2.0],
            size=8,
            style={
                "fill": "#22c55e",
                "stroke": "#052e16",
                "stroke-width": "2px",
                "opacity": 1,
            },
        )
    ).figure()

    svg = fig.to_svg()
    assert 'fill="#22c55e"' in svg
    assert 'stroke="#052e16"' in svg
    assert 'stroke-width="2"' in svg

    image = _raster.render_raster(*fig.build_payload(), scale=1)
    assert np.any(np.all(image == np.array([34, 197, 94, 255], dtype=np.uint8), axis=2))
    assert np.any(np.all(image == np.array([5, 46, 22, 255], dtype=np.uint8), axis=2))


def test_axis_style_reaches_svg_and_native_renderers() -> None:
    fig = xy.chart(
        xy.line(x=[0.0, 1.0], y=[1.0, 2.0]),
        xy.x_axis(
            label="time",
            style={
                "grid_color": "#ff0000",
                "grid_width": 3,
                "grid_dash": "dashed",
                "grid_opacity": 0.6,
                "axis_color": "#0000ff",
                "axis_width": 2,
                "tick_length": 6,
                "tick_width": 2,
                "tick_color": "#00aa00",
                "tick_label_color": "#cc5500",
                "tick_size": 13,
                "label_color": "#aa00aa",
                "label_size": 15,
            },
        ),
    ).figure()

    svg = fig.to_svg()
    assert 'stroke="#ff0000" stroke-width="3" stroke-opacity="0.6" stroke-dasharray="6,4"' in svg
    assert 'stroke="#0000ff" stroke-width="2"' in svg
    assert 'stroke="#00aa00" stroke-width="2"' in svg
    assert 'fill="#cc5500" font-size="13" text-anchor="middle"' in svg
    assert 'font-size="15" font-weight="500" fill="#aa00aa"' in svg
    assert _raster.render_raster(*fig.build_payload(), scale=1).shape[-1] == 4


def test_axis_style_is_normalized_and_rejected_before_render() -> None:
    axis = xy.x_axis(
        style={
            "grid-width": "3px",
            "tick_label_size": "13px",
            "tick-direction": "inout",
            "label-color": "rebeccapurple",
        }
    )
    assert axis.style == {
        "grid_width": 3.0,
        "tick_label_size": 13.0,
        "tick_direction": "inout",
        "label_color": "rebeccapurple",
    }

    with pytest.raises(ValueError, match=r"unsupported property 'box-shadow'"):
        xy.x_axis(style={"box-shadow": "0 0 2px red"})
    with pytest.raises(ValueError, match=r"finite CSS px length"):
        xy.x_axis(style={"grid_width": "3em"})
    with pytest.raises(ValueError, match=r"not a recognized CSS color"):
        xy.y_axis(style={"tick_color": "definitely-not-a-color"})
    with pytest.raises(ValueError, match=r"must be one of"):
        xy.y_axis(style={"tick_direction": "sideways"})


def test_area_outline_obeys_whole_mark_and_stroke_opacity() -> None:
    default = xy.chart(xy.area(x=[0.0, 1.0], y=[1.0, 2.0])).figure().to_svg()
    assert 'stroke-opacity="0.35"' in default

    styled = xy.chart(
        xy.area(
            x=[0.0, 1.0],
            y=[1.0, 2.0],
            opacity=0.4,
            line_opacity=0.5,
            style={"stroke-opacity": 0.5},
        )
    ).figure()
    assert 'stroke-opacity="0.1"' in styled.to_svg()


def test_static_invalid_paint_fallback_matches_browser_renderer() -> None:
    expected = (76, 120, 168, 255)
    assert _svg._paint_rgba8("var(--unresolved)") == expected
    assert _raster._parse_color("var(--unresolved)") == expected


def test_mark_style_rejects_unrenderable_css_before_mutating_figure() -> None:
    fig = Figure()
    with pytest.raises(ValueError, match="unsupported CSS property"):
        fig.line([0.0, 1.0], [1.0, 2.0], style={"box-shadow": "0 0 4px red"})
    assert fig.traces == []
    assert len(fig.store) == 0


def test_css_variables_remain_reflex_owned_dom_values() -> None:
    chart = xy.chart(
        xy.line(x=[0.0, 1.0], y=[1.0, 2.0], style={"stroke": "var(--accent)"}),
        style={"--accent": "oklch(0.7 0.2 250)"},
    )
    fig = chart.figure()
    spec, _ = fig.build_payload()

    assert spec["dom"]["style"]["--accent"] == "oklch(0.7 0.2 250)"
    assert spec["traces"][0]["style"]["color"] == "var(--accent)"


def test_static_renderers_resolve_complete_chart_color_tokens() -> None:
    fig = xy.chart(
        xy.line(x=[0.0, 1.0], y=[1.0, 2.0], style={"stroke": "var(--accent)"}),
        xy.line(x=[0.0, 1.0], y=[2.0, 1.0], style={"stroke": "var(--missing, #0ea5e9)"}),
        style={"--accent": "var(--brand)", "--brand": "#7c3aed"},
    ).figure()

    spec, blob = fig.build_payload()
    svg = fig.to_svg()
    assert 'stroke="#7c3aed"' in svg
    assert 'stroke="#0ea5e9"' in svg
    assert spec["traces"][0]["style"]["color"] == "var(--accent)"

    image = _raster.render_raster(spec, blob, scale=1)
    assert np.any(np.all(image == np.array([124, 58, 237, 255], dtype=np.uint8), axis=2))


def test_scatter_css_fill_survives_density_lod() -> None:
    fig = xy.chart(
        xy.scatter(
            x=[0.0, 1.0, 2.0],
            y=[1.0, 2.0, 3.0],
            density=True,
            style={"fill": "rgb(37 99 235 / 80%)", "opacity": 0.6},
        )
    ).figure()
    spec, _ = fig.build_payload()

    trace = spec["traces"][0]
    assert trace["tier"] == "density"
    assert trace["density"]["color"] == "rgb(37 99 235 / 80%)"
    assert trace["style"]["opacity"] == 0.6


def test_faceting_preserves_concrete_css_style() -> None:
    data = {"x": [0.0, 1.0], "y": [1.0, 2.0], "panel": ["a", "b"]}
    chart = xy.facet_chart(
        xy.line(x="x", y="y", data=data, style={"stroke": "#7c3aed"}),
        data=data,
        by="panel",
    )
    grid = chart.figure()

    assert all(figure.traces[0].style["color"] == "#7c3aed" for figure in grid.figures)
