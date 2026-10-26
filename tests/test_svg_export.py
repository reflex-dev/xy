"""Static SVG export (_svg.py): well-formed output for every chart kind, the
screen-bounded size guarantee, styling fidelity markers, and sync guards
against the JS client tables it mirrors."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from tests.svg_test_utils import tick_label_positions

import xy
from xy import channels
from xy._figure import Figure
from xy._svg import (
    COLORMAP_STOPS,
    _axis_tick_label_layout,
    _colormap_stops,
    _Scale,
    layout,
    render_svg,
)

ROOT = Path(__file__).resolve().parents[1]


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def _text_element(root: ET.Element, value: str) -> ET.Element:
    """Return the SVG ``text`` owner whether content is direct or in tspans."""
    return next(
        node
        for node in root.iter()
        if node.tag.endswith("text") and "".join(node.itertext()) == value
    )


def test_single_line_ticks_stay_direct_svg_text_while_multiline_uses_tspans() -> None:
    chart = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(
            tick_values=(0.0, 1.0),
            tick_labels=("plain tick", "split\ntick"),
            tick_label_strategy="preserve",
        ),
        width=360,
        height=240,
    )

    root = _parse(chart.figure().to_svg())
    plain = _text_element(root, "plain tick")
    split = _text_element(root, "splittick")

    assert plain.text == "plain tick"
    assert not list(plain)
    assert split.text is None
    assert [node.text for node in split if node.tag.endswith("tspan")] == ["split", "tick"]


def test_every_chart_kind_exports_wellformed_svg() -> None:
    rng = np.random.default_rng(0)
    x = np.linspace(0.0, 10.0, 50)

    figs = []
    figs.append(Figure().line(x, np.sin(x), dash="dashed", curve="smooth"))
    figs.append(
        Figure().area(x, np.abs(np.sin(x)), fill="linear-gradient(currentColor, transparent)")
    )
    figs.append(
        Figure().scatter(
            x, np.cos(x), symbol="triangle", stroke="#111", color=np.sin(x), size=np.abs(np.cos(x))
        )
    )
    figs.append(Figure().scatter(x, np.cos(x), color=np.array(["a", "b"] * 25)))
    figs.append(Figure().bar(["a", "b", "c"], [1.0, 3.0, 2.0], corner_radius=(4, 0)))
    figs.append(Figure().bar(["a", "b"], [1.0, 2.0], orientation="horizontal"))
    figs.append(Figure().histogram(rng.normal(size=500), corner_radius=2))
    figs.append(Figure().heatmap(rng.random((8, 6))))
    figs.append(Figure().scatter(rng.normal(size=200_000), rng.normal(size=200_000), density=True))
    t = np.datetime64("2024-01-01") + np.arange(50).astype("timedelta64[h]")
    figs.append(Figure().line(t, np.sin(x)))
    log_fig = Figure().scatter(x + 1, 10.0 ** np.linspace(0, 4, 50))
    log_fig.set_axis("y", type_="log")
    figs.append(log_fig)

    for fig in figs:
        svg = fig.to_svg()
        root = _parse(svg)
        assert root.tag.endswith("svg")
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_svg_best_legend_rescores_the_final_export_size(monkeypatch) -> None:
    figure = xy.chart(
        xy.bar([0.75], [1.0], base=[0.90], width=0.04, name="series"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=640,
        height=360,
    ).figure()
    initial, _ = figure.build_payload()
    assert initial["legend"]["loc"] == "upper right"

    from xy import _legendfit

    calls = []
    original = _legendfit.resolve_for_figure

    def record(figure, spec=None, legend_options=None, rendered_columns=None):
        result = original(figure, spec, legend_options, rendered_columns)
        calls.append((spec["width"], spec["height"], rendered_columns, result))
        return result

    monkeypatch.setattr(_legendfit, "resolve_for_figure", record)
    root = _parse(figure.to_svg(width=280))

    # Payload construction first resolves at the authored 640 px. The static
    # post-pass must then score the emitted columns at the final 280 px layout.
    assert calls[-1][:2] == (280, 360)
    assert isinstance(calls[-1][2], bytes)
    assert calls[-1][3] == "upper left"
    assert float(_text_element(root, "series").attrib["x"]) < 140.0
    assert figure.legend_options["loc"] == "best"


def test_svg_paints_figure_and_plot_backgrounds() -> None:
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        xy.theme(background="#000000", plot_background="#101418"),
        width=300,
        height=200,
    )
    svg = chart.figure().to_svg()
    assert '<rect width="300" height="200" fill="#000000"/>' in svg  # figure patch
    assert 'fill="#101418"' in svg  # plot rect

    # Browser-only paints (gradients) are omitted, never fallback-painted.
    gradient = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        xy.theme(style={"background": "linear-gradient(red, blue)"}),
        width=300,
        height=200,
    )
    assert "linear-gradient" not in gradient.figure().to_svg()


def test_svg_honors_tick_label_anchor() -> None:
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        xy.x_axis(tick_label_anchor="right"),  # mpl `ha` alias -> "end"
        xy.y_axis(tick_label_anchor="center"),
        width=300,
        height=200,
    )
    svg = chart.figure().to_svg()
    # No title/axis labels, so the only text-anchor sources are tick labels:
    # x pins its right edge ("end"), y centers ("middle"), nothing at "start".
    assert 'text-anchor="end"' in svg
    assert 'text-anchor="middle"' in svg
    assert 'text-anchor="start"' not in svg

    # Defaults reproduce the classic layout: x centered, y right edge at the
    # tick ("end" — labels sit left of the plot).
    default = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        width=300,
        height=200,
    )
    default_svg = default.figure().to_svg()
    assert 'text-anchor="middle"' in default_svg
    assert 'text-anchor="end"' in default_svg


def test_svg_tick_padding_starts_after_the_outward_tick() -> None:
    from xy import _svg

    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        xy.x_axis(
            tick_values=(0.5,),
            tick_labels=("middle",),
            style={"tick_length": 6, "tick_padding": 5, "tick_label_size": 10},
        ),
        width=300,
        height=200,
    )
    spec, _blob = chart.figure().build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    root = _parse(chart.figure().to_svg())
    label = _text_element(root, "middle")

    # SVG text y is its baseline. The label's top begins after the 6 px
    # outward tick plus the independent 5 px Matplotlib-style pad.
    assert float(label.get("y", "nan")) == pytest.approx(plot["y"] + plot["h"] + 6 + 5 + 8)


def test_svg_tick_label_anchor_collision_parity() -> None:
    """Anchor-aware collision model matches JS _tickLabelsCollide.

    9 categories, tick_label_angle=-30, tick_label_anchor="end", wide chart:
      spacing * sin(30°) > lineHeight + minGap  →  JS keeps all 9 labels.
    The old centered-extent model treated labels as ±half-extent boxes centred
    on each tick and found them colliding (extent > spacing), so it would
    stride-2 downsample to 5.  The fixed Python exporter must also keep all 9.
    """
    # 15-char labels; font_size=11, angle=-30, anchor="end", min_gap=8.
    #   new model:  spacing * sin(30°) = 90*0.5 = 45  >  11*1.2+8 = 21.2  → ok
    #   old model:  extent = cos(30°)*109.1 + sin(30°)*13.2 ≈ 101.1
    #               gap = 90 - 101.1 = -11.1  <  8  → would collide → stride-2
    n = 9
    categories = [f"Category_Name_{i:02d}" for i in range(n)]  # 16 chars each
    axis: dict = {
        "kind": "category",
        "categories": categories,
        "range": [0.0, float(n - 1)],
        "tick_label_angle": -30,
        "tick_label_anchor": "end",
        "tick_label_strategy": "rotate",
    }
    # plot_width=720px → spacing = 720/8 = 90px
    scale = _Scale(axis, px0=100.0, px1=820.0)
    values = [float(i) for i in range(n)]
    kept = _axis_tick_label_layout(axis, values, 1.0, scale, is_x=True)
    assert len(kept) == n, (
        f"anchor-aware collision model should keep all {n} labels, got {len(kept)}"
    )

    # Sanity: without the anchor the old centered-extent model is used and the
    # same geometry collides, so strategy="rotate" still downsample to fit.
    axis_no_anchor: dict = {**axis}
    del axis_no_anchor["tick_label_anchor"]
    kept_no_anchor = _axis_tick_label_layout(axis_no_anchor, values, 1.0, scale, is_x=True)
    assert len(kept_no_anchor) < n, (
        "centered-extent model should find collision (geometry not wide enough) "
        f"but kept {len(kept_no_anchor)} of {n}"
    )


@pytest.mark.parametrize(("side", "room_key"), [("bottom", "bottom"), ("top", "top")])
def test_rotated_x_tick_labels_measure_their_outward_gutter(side, room_key) -> None:
    labels = [
        "Democratic Republic of the Congo",
        "United States of America",
        "Papua New Guinea",
    ]
    chart = xy.chart(
        xy.line([0.0, 1.0, 2.0], [1.0, 2.0, 3.0]),
        xy.x_axis(
            side=side,
            tick_values=[0.0, 1.0, 2.0],
            tick_labels=labels,
            tick_label_angle=45,
            tick_label_anchor="end",
            tick_label_strategy="preserve",
        ),
        width=640,
        height=360,
    )
    spec, _blob = chart.figure().build_payload()
    width, height, _compact, plot = layout(spec)
    room = plot["y"] if room_key == "top" else height - plot["y"] - plot["h"]

    assert width == 640
    assert room > 100


def test_svg_legend_text_honors_theme_text_color() -> None:
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0], name="walk"),
        xy.legend(loc="upper right", title="models"),
        xy.theme(text_color="#ffffff"),
        width=300,
        height=200,
    )
    svg = chart.figure().to_svg()
    assert re.search(r'<text[^>]*fill="#ffffff"[^>]*>walk</text>', svg)
    assert re.search(r'<text[^>]*fill="#ffffff"[^>]*>models</text>', svg)

    # Without a theme the legend keeps the light-mode default text color.
    plain = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0], name="walk"),
        xy.legend(loc="upper right"),
        width=300,
        height=200,
    )
    assert re.search(
        r'<text[^>]*fill="rgba\(32,32,32,0\.85\)"[^>]*>walk</text>', plain.figure().to_svg()
    )


def test_svg_stays_screen_bounded_for_large_lines() -> None:
    n = 2_000_000
    y = np.cumsum(np.random.default_rng(1).normal(size=n))
    fig = Figure(width=950, height=420, title="big")
    fig.line(np.arange(n, dtype=np.float64), y, name="walk")
    svg = fig.to_svg()
    # M4 keeps ≤4 points per pixel column: 2M source points must not leak into
    # the file. Generous ceiling: ~4*950 points at ~15 bytes each + chrome.
    assert len(svg) < 300_000, f"SVG not screen-bounded: {len(svg)} bytes"
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["n_points"] == n  # source size recorded (§28)


def test_svg_styling_fidelity_markers() -> None:
    x = np.linspace(0.0, 5.0, 12)
    fig = Figure(title="styled")
    fig.area(
        x,
        np.abs(np.sin(x)) + 0.1,
        curve="smooth",
        dash="dotted",
        fill="linear-gradient(currentColor, transparent)",
        name="a",
    )
    fig.bar(
        ["a", "b"],
        [1.0, 2.0],
        corner_radius=(6, 0),
        stroke="#123456",
        stroke_width=2,
        fill="linear-gradient(to top, #1e40af, #93c5fd)",
    )
    fig.scatter([1.0], [0.5], symbol="cross", stroke="#ff0000")
    svg = fig.to_svg()
    assert "linearGradient" in svg  # gradient fills -> defs
    assert "stroke-dasharray" in svg  # dashes -> native SVG dashes
    assert " C " in svg  # smooth curve -> cubic Béziers, not polyline
    assert re.search(r'<path d="M [^"]*A [^"]*A ', svg)  # rounded corners -> arc path
    assert 'stroke="#123456"' in svg  # bar border
    assert 'stroke="#ff0000"' in svg  # point border
    assert "<title" not in svg  # no stray elements; title is <text>
    assert ">styled<" in svg


def test_svg_transparent_gradient_stops_preserve_adjacent_hues() -> None:
    fade = (
        Figure()
        .area(
            [0.0, 1.0],
            [1.0, 2.0],
            color="#a78bfa",
            fill="linear-gradient(currentColor, transparent)",
        )
        .to_svg()
    )
    assert 'stop-color="#a78bfa" stop-opacity="0"' in fade
    assert 'stop-color="transparent"' not in fade

    split = (
        Figure()
        .bar(
            [0.0, 1.0],
            [1.0, 2.0],
            fill="linear-gradient(#ff0000, transparent 50%, #0000ff)",
        )
        .to_svg()
    )
    assert split.count('offset="50%"') == 2
    assert 'offset="50%" stop-color="#ff0000" stop-opacity="0"' in split
    assert 'offset="50%" stop-color="#0000ff" stop-opacity="0"' in split


def test_svg_axes_chrome_and_hiding() -> None:
    fig = Figure(title="t", x_label="xx", y_label="yy")
    fig.line([0.0, 1.0], [0.0, 1.0], name="n")
    svg = fig.to_svg()
    for text in (">t<", ">xx<", ">yy<", ">n<"):
        assert text in svg

    spark = Figure(padding=0)
    spark.line([0.0, 1.0], [0.0, 1.0])
    for ax in ("x", "y"):
        spark.set_axis(ax, tick_label_strategy="none")
    sparse = spark.to_svg()
    assert 'text-anchor="end"' not in sparse  # no y tick labels
    assert 'text-anchor="middle">' not in sparse  # no x tick labels / titles


def test_svg_long_legend_is_clamped_and_ellipsized_inside_plot() -> None:
    from xy import _svg

    names = [f"series-{index}-" + "very-long-operational-label-" * 2 for index in range(4)]
    chart = xy.line_chart(
        *(
            xy.line([0.0, 1.0], [float(index), float(index + 1)], name=name)
            for index, name in enumerate(names)
        ),
        xy.legend(
            loc="upper right",
            ncols=2,
            title="Long operational series",
            style={"background": "#ff00ff", "--xy-legend-frame-alpha": 1},
        ),
        width=320,
        height=260,
    )
    fig = chart.figure()
    spec, _blob = fig.build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    svg = fig.to_svg()
    root = _parse(svg)

    frame = next(node for node in root.iter() if node.get("fill") == "#ff00ff")
    x, y = float(frame.get("x", "nan")), float(frame.get("y", "nan"))
    width, height = float(frame.get("width", "nan")), float(frame.get("height", "nan"))
    assert plot["x"] <= x <= x + width <= plot["x"] + plot["w"]
    assert plot["y"] <= y <= y + height <= plot["y"] + plot["h"]
    assert any(node.tag.endswith("clipPath") for node in root.iter())
    assert all(name not in svg for name in names)
    assert any((node.text or "").endswith("...") for node in root.iter())


def test_svg_secondary_y_axis_scales_trace_and_renders_right_chrome() -> None:
    from xy import _svg

    chart = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0], color="#2563eb"),
        xy.line([0.0, 1.0], [100.0, 200.0], color="#dc2626", y_axis="y2"),
        xy.y_axis(label="Primary"),
        xy.y_axis(
            id="y2",
            label="Secondary",
            side="right",
            domain=(100.0, 200.0),
            tick_values=(100.0, 150.0, 200.0),
            style={
                "axis_color": "#dc2626",
                "tick_color": "#dc2626",
                "tick_label_color": "#dc2626",
                "label_color": "#dc2626",
                "tick_length": 5,
            },
        ),
        width=400,
        height=240,
    )
    fig = chart.figure()
    spec, _blob = fig.build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    root = _parse(fig.to_svg())

    secondary_path = next(
        node
        for node in root.iter()
        if node.tag.endswith("path") and node.get("stroke") == "#dc2626"
    )
    coords = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", secondary_path.get("d", ""))]
    ys = coords[1::2]
    assert ys
    assert all(plot["y"] <= value <= plot["y"] + plot["h"] for value in ys)

    texts = {node.text for node in root.iter() if node.text}
    assert {"100", "150", "200", "Secondary"} <= texts
    right_edge = plot["x"] + plot["w"]
    red_lines = [
        node
        for node in root.iter()
        if node.tag.endswith("line") and node.get("stroke") == "#dc2626"
    ]
    assert any(
        float(node.get("x1", "nan")) == right_edge and float(node.get("x2", "nan")) == right_edge
        for node in red_lines
    )
    assert sum(float(node.get("x2", "0")) > right_edge for node in red_lines) >= 3


def test_svg_short_chart_with_titled_legend_emits_no_empty_legend_box() -> None:
    # A plot too short for even one legend row must not paint a floating
    # frame/title-only box.
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series-a"),
        xy.legend(title="Legend title", style={"background": "#ff00ff"}),
        width=400,
        height=70,
    )
    svg = chart.to_svg()
    assert "#ff00ff" not in svg
    assert "Legend title" not in svg
    assert "series-a" not in svg


def test_svg_vertical_colorbar_clears_right_named_axis_chrome() -> None:
    from xy import _svg

    chart = xy.chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], name="field", colormap="viridis"),
        xy.line([0.0, 1.0], [100.0, 200.0], y_axis="y2"),
        xy.y_axis(id="y2", label="Secondary", side="right", domain=(100.0, 200.0)),
        xy.colorbar(title="Field"),
        width=560,
        height=300,
    )
    fig = chart.figure()
    spec, _blob = fig.build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    root = _parse(fig.to_svg())

    bar = next(
        node for node in root.iter() if (node.get("fill") or "").startswith("url(#xy-colorbar-")
    )
    # The whole colorbar shifts right of the axis gutter, past the rotated
    # secondary-axis title at plot-right+40.
    assert float(bar.get("x", "nan")) > plot["x"] + plot["w"] + 40


def test_svg_vertical_colorbar_label_is_rotated_beside_the_bar_inside_the_canvas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SVG places a vertical colorbar's label like Matplotlib — rotated 90° CCW,
    centered beside the bar, on canvas — and the native PNG exporter must agree
    on the baseline so the two static paths cannot drift apart."""
    from xy import _raster, _svg

    chart = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis", domain=(0.0, 3.0)),
        xy.colorbar(title="counts in bin"),
        width=560,
        height=320,
    )
    fig = chart.figure()
    spec, blob = fig.build_payload()
    width, _height, _compact, plot = _svg.layout(spec)
    root = _parse(fig.to_svg())

    label = _text_element(root, "counts in bin")
    label_x, label_y = float(label.get("x", "nan")), float(label.get("y", "nan"))
    bar = next(
        node for node in root.iter() if (node.get("fill") or "").startswith("url(#xy-colorbar-")
    )
    bar_x, bar_w = float(bar.get("x", "nan")), float(bar.get("width", "nan"))

    # Rotated a quarter turn counter-clockwise about its own anchor.
    assert label.get("transform") == f"rotate(-90 {label_x:g} {label_y:g})"
    assert label.get("text-anchor") == "middle"
    # Beside the bar and centered on it, never above it.
    assert label_x > bar_x + bar_w
    assert label_y == plot["y"] + plot["h"] / 2
    # Inside the canvas the labeled colorbar reserved room for.
    assert label_x < width

    # The native PNG exporter shares this baseline.
    recorded: list[tuple[float, float, int, float, str]] = []
    original_text = _raster._Cmd.text

    def record_text(self, x, y, anchor, size, color, value, *args, **kwargs):
        recorded.append((float(x), float(y), int(anchor), float(size), str(value)))
        return original_text(self, x, y, anchor, size, color, value, *args, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", record_text)
    _raster.render_raster(spec, blob, scale=1)
    native_x, native_y, anchor, _size, _text = next(
        entry for entry in recorded if entry[4] == "counts in bin"
    )
    assert (native_x, native_y) == (label_x, label_y)
    assert anchor == 1 | _raster._TEXT_ROT_CCW


def test_svg_colorbar_clears_primary_right_axis_and_bottom_axis_chrome() -> None:
    from xy import _svg

    vertical = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis"),
        xy.y_axis(label="Primary right", side="right"),
        xy.colorbar(),
        width=560,
        height=320,
    )
    vertical_spec, _blob = vertical.figure().build_payload()
    _width, _height, _compact, vertical_plot = _svg.layout(vertical_spec)
    vertical_root = _parse(vertical.to_svg())
    vertical_bar = next(
        node
        for node in vertical_root.iter()
        if (node.get("fill") or "").startswith("url(#xy-colorbar-")
    )
    right_title = _text_element(vertical_root, "Primary right")
    assert float(vertical_bar.get("x", "nan")) > float(right_title.get("x", "nan"))
    assert float(vertical_bar.get("x", "nan")) > vertical_plot["x"] + vertical_plot["w"] + 40

    horizontal = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis"),
        xy.x_axis(label="Bottom axis"),
        xy.colorbar(orientation="horizontal", title="Intensity"),
        width=560,
        height=320,
    )
    horizontal_spec, _blob = horizontal.figure().build_payload()
    _width, _height, _compact, horizontal_plot = _svg.layout(horizontal_spec)
    horizontal_root = _parse(horizontal.to_svg())
    horizontal_bar = next(
        node
        for node in horizontal_root.iter()
        if (node.get("fill") or "").startswith("url(#xy-colorbar-")
    )
    bottom_title = _text_element(horizontal_root, "Bottom axis")
    assert float(horizontal_bar.get("y", "nan")) > float(bottom_title.get("y", "nan"))
    assert float(horizontal_bar.get("y", "nan")) >= (
        horizontal_plot["y"] + horizontal_plot["h"] + horizontal_plot["bottom_axis_room"]
    )


def test_svg_secondary_x_axis_scales_trace_and_renders_top_chrome() -> None:
    from xy import _svg

    chart = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0], color="#2563eb"),
        xy.line([100.0, 200.0], [0.2, 0.8], color="#dc2626", x_axis="x2"),
        xy.x_axis(label="Primary X"),
        xy.x_axis(
            id="x2",
            label="Secondary X",
            side="top",
            domain=(100.0, 200.0),
            tick_values=(100.0, 150.0, 200.0),
            style={
                "axis_color": "#dc2626",
                "tick_color": "#dc2626",
                "tick_label_color": "#dc2626",
                "label_color": "#dc2626",
                "tick_length": 5,
            },
        ),
        width=400,
        height=240,
    )
    fig = chart.figure()
    spec, _blob = fig.build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    root = _parse(fig.to_svg())

    secondary_path = next(
        node
        for node in root.iter()
        if node.tag.endswith("path") and node.get("stroke") == "#dc2626"
    )
    coords = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", secondary_path.get("d", ""))]
    xs = coords[0::2]
    assert xs
    assert all(plot["x"] <= value <= plot["x"] + plot["w"] for value in xs)

    texts = {node.text for node in root.iter() if node.text}
    assert {"100", "150", "200", "Secondary X"} <= texts
    red_lines = [
        node
        for node in root.iter()
        if node.tag.endswith("line") and node.get("stroke") == "#dc2626"
    ]
    assert any(
        float(node.get("y1", "nan")) == plot["y"] and float(node.get("y2", "nan")) == plot["y"]
        for node in red_lines
    )
    assert sum(float(node.get("y1", "inf")) < plot["y"] for node in red_lines) >= 3


def test_svg_mixed_primary_and_named_x_axis_kinds_render_independently() -> None:
    cases = (
        (
            xy.chart(
                xy.line(["Primary Alpha", "Primary Beta", "Primary Gamma"], [1.0, 2.0, 3.0]),
                xy.line([100.0, 200.0, 300.0], [3.0, 2.0, 1.0], x_axis="x2"),
                xy.x_axis(tick_label_strategy="rotate"),
                xy.x_axis(
                    id="x2",
                    side="top",
                    type_="linear",
                    tick_values=(100.0, 200.0, 300.0),
                    tick_labels=("N100", "N200", "N300"),
                    tick_label_strategy="rotate",
                ),
                width=560,
                height=300,
            ),
            {"Primary Alpha", "Primary Beta", "Primary Gamma", "N100", "N200", "N300"},
        ),
        (
            xy.chart(
                xy.line([10.0, 20.0, 30.0], [1.0, 2.0, 3.0]),
                xy.line(["Named Red", "Named Green", "Named Blue"], [3.0, 2.0, 1.0], x_axis="x2"),
                xy.x_axis(
                    type_="linear",
                    tick_values=(10.0, 20.0, 30.0),
                    tick_labels=("P10", "P20", "P30"),
                    tick_label_strategy="rotate",
                ),
                xy.x_axis(id="x2", side="top", tick_label_strategy="rotate"),
                width=560,
                height=300,
            ),
            {"P10", "P20", "P30", "Named Red", "Named Green", "Named Blue"},
        ),
    )

    for chart, expected_labels in cases:
        root = _parse(chart.figure().to_svg())
        rendered_labels = {node.text for node in root.iter() if node.text}
        assert expected_labels <= rendered_labels


@pytest.mark.parametrize(
    ("side", "angle", "expected_anchor"),
    [
        ("bottom", -35, "end"),
        ("bottom", 35, "start"),
        ("top", 35, "end"),
        ("top", -35, "start"),
    ],
)
def test_svg_rotated_x_tick_labels_anchor_away_from_plot(
    side: str,
    angle: int,
    expected_anchor: str,
) -> None:
    axis_id = "x" if side == "bottom" else "x2"
    chart = xy.chart(
        xy.line([0, 1], [0, 1], x_axis=axis_id),
        xy.x_axis(
            id=axis_id,
            side=side,
            tick_values=(0, 1),
            tick_labels=("Long category alpha", "Long category beta"),
            tick_label_strategy="rotate",
            tick_label_angle=angle,
        ),
        width=480,
        height=280,
    )

    root = _parse(chart.figure().to_svg())
    labels = {
        value: _text_element(root, value) for value in ("Long category alpha", "Long category beta")
    }
    assert set(labels) == {"Long category alpha", "Long category beta"}
    assert {node.get("text-anchor") for node in labels.values()} == {expected_anchor}
    assert all(f"rotate({angle}" in node.get("transform", "") for node in labels.values())


def test_static_named_axes_handle_reverse_silence_and_tick_count() -> None:
    from xy import _svg

    base = xy.chart(xy.line([0.0, 1.0], [0.0, 1.0]), width=400, height=240)
    silent = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(id="x2", side="top", tick_label_strategy="none"),
        xy.y_axis(id="y2", side="right", tick_label_strategy="none"),
        width=400,
        height=240,
    )
    base_spec, _ = base.figure().build_payload()
    silent_spec, _ = silent.figure().build_payload()
    assert _svg.layout(silent_spec)[3] == _svg.layout(base_spec)[3]

    chart = xy.chart(
        xy.line([100.0, 150.0, 200.0], [0.0, 1.0, 2.0], x_axis="x2"),
        xy.x_axis(
            id="x2",
            side="top",
            domain=(100.0, 200.0),
            reverse=True,
            tick_values=(100.0, 150.0, 200.0),
            tick_labels=("low", "middle", "high"),
        ),
        xy.y_axis(id="y2", side="right", domain=(0.0, 100.0), tick_count=2),
        width=400,
        height=240,
    )
    spec, _ = chart.figure().build_payload()
    ticks, labels, _step = _svg.axis_ticks(spec["axes"]["x2"], 300, True)
    assert ticks == labels == [100.0, 150.0, 200.0]
    y_ticks, _y_labels, _y_step = _svg.axis_ticks(spec["axes"]["y2"], 180, False)
    assert len(y_ticks) <= 3  # tick_count is a target and includes both endpoints
    texts = {node.text for node in _parse(chart.to_svg()).iter() if node.text}
    assert {"low", "middle", "high"} <= texts


def test_svg_named_axis_collision_and_title_placement_controls() -> None:
    values = list(range(30))
    tick_labels = [f"very-long-secondary-label-{value}" for value in values]
    chart = xy.chart(
        xy.line(values, values, x_axis="x2"),
        xy.x_axis(
            id="x2",
            side="top",
            label="Secondary positioned title",
            label_position="inside_end",
            label_offset=6,
            label_angle=47,
            domain=(0.0, 29.0),
            tick_values=values,
            tick_labels=tick_labels,
            tick_label_strategy="hide",
        ),
        width=400,
        height=240,
    )
    spec, _ = chart.figure().build_payload()
    _width, _height, _compact, plot = xy._svg.layout(spec)
    root = _parse(chart.to_svg())

    rendered_tick_labels = [node.text for node in root.iter() if node.text in tick_labels]
    assert 0 < len(rendered_tick_labels) < len(tick_labels)
    title = _text_element(root, "Secondary positioned title")
    assert float(title.get("x", "nan")) == plot["x"] + plot["w"]
    assert plot["y"] < float(title.get("y", "nan")) < plot["y"] + plot["h"]
    assert title.get("text-anchor") == "end"
    assert title.get("transform", "").startswith("rotate(47 ")


def test_svg_write_and_dimension_override(tmp_path: Path) -> None:
    fig = Figure(width="100%", height="100%")
    fig.line([0.0, 1.0], [0.0, 1.0])
    out = tmp_path / "chart.svg"
    svg = fig.to_svg(out, width=640, height=360)
    assert out.read_text(encoding="utf-8") == svg
    root = _parse(svg)
    assert root.get("width") == "640"
    assert root.get("height") == "360"


def test_composition_chart_to_svg_parity() -> None:
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[1.0, 2.0], name="s"),
        xy.x_axis(label="time"),
        title="comp",
    )
    svg = chart.to_svg(width=500, height=300)
    _parse(svg)
    assert ">comp<" in svg
    assert ">time<" in svg


def test_density_and_heatmap_embed_png_rasters() -> None:
    rng = np.random.default_rng(2)
    fig = Figure()
    fig.scatter(rng.normal(size=200_000), rng.normal(size=200_000), density=True)
    svg = fig.to_svg()
    assert "data:image/png;base64," in svg  # density grid -> embedded raster
    assert svg.count("<image") == 1

    fig2 = Figure().heatmap(rng.random((16, 12)))
    svg2 = fig2.to_svg()
    assert "data:image/png;base64," in svg2


def test_colormap_stops_stay_in_sync_with_js_client() -> None:
    """The Python tables are ports of 10_colormaps.ts — every stop must appear
    verbatim in the JS source, and the map names must match."""
    js = (ROOT / "js" / "src" / "10_colormaps.ts").read_text(encoding="utf-8")
    body = js.split("COLORMAP_STOPS = {", 1)[1].split("};", 1)[0]
    js_names = set(re.findall(r"^\s*(\w+): (?:\[|flagStops\(\))", body, re.MULTILINE))
    assert js_names == set(COLORMAP_STOPS), "colormap names diverged from 10_colormaps.ts"
    for name, stops in COLORMAP_STOPS.items():
        if name == "flag":
            assert "function flagStops()" in js
            assert "x * 31.5 + 0.25" in js
            assert "x * 31.5 - 0.25" in js
            continue
        for r, g, b in stops:
            assert f"[{r}, {g}, {b}]" in body, (
                f"{name} stop ({r},{g},{b}) missing in 10_colormaps.ts"
            )
    assert set(COLORMAP_STOPS) == set(channels.COLORMAPS), (
        "renderer and public colormap registries diverged"
    )


def test_matplotlib_gallery_colormap_stops_and_reversal() -> None:
    from xy.pyplot._colors import resolve_cmap

    expected = {
        "reds": [
            (255, 245, 240),
            (254, 229, 216),
            (253, 202, 181),
            (252, 171, 143),
            (252, 138, 106),
            (251, 105, 74),
            (241, 68, 50),
            (217, 37, 35),
            (188, 20, 26),
            (152, 12, 19),
            (103, 0, 13),
        ],
        "bone": [
            (0, 0, 0),
            (22, 22, 30),
            (45, 45, 62),
            (66, 66, 93),
            (89, 92, 121),
            (112, 123, 144),
            (134, 154, 166),
            (157, 185, 188),
            (185, 210, 210),
            (221, 233, 233),
            (255, 255, 255),
        ],
        "autumn": [
            (255, 0, 0),
            (255, 25, 0),
            (255, 51, 0),
            (255, 76, 0),
            (255, 102, 0),
            (255, 128, 0),
            (255, 153, 0),
            (255, 179, 0),
            (255, 204, 0),
            (255, 230, 0),
            (255, 255, 0),
        ],
        "winter": [
            (0, 0, 255),
            (0, 25, 242),
            (0, 51, 230),
            (0, 76, 217),
            (0, 102, 204),
            (0, 128, 191),
            (0, 153, 178),
            (0, 179, 166),
            (0, 204, 153),
            (0, 230, 140),
            (0, 255, 128),
        ],
        "bupu": [
            (247, 252, 253),
            (229, 239, 246),
            (204, 221, 236),
            (178, 202, 225),
            (154, 180, 214),
            (140, 149, 198),
            (140, 116, 181),
            (138, 81, 165),
            (133, 45, 144),
            (118, 12, 113),
            (77, 0, 75),
        ],
        "rdylbu": [
            (165, 0, 38),
            (214, 47, 38),
            (244, 109, 67),
            (252, 172, 96),
            (254, 224, 144),
            (254, 254, 192),
            (224, 243, 247),
            (169, 216, 232),
            (116, 173, 209),
            (68, 115, 179),
            (49, 54, 149),
        ],
        "ylgn": [
            (255, 255, 229),
            (248, 252, 194),
            (229, 244, 171),
            (200, 232, 154),
            (162, 216, 137),
            (119, 197, 120),
            (75, 176, 98),
            (46, 146, 76),
            (21, 120, 62),
            (0, 96, 51),
            (0, 69, 41),
        ],
        "wistia": [
            (228, 255, 122),
            (238, 245, 84),
            (249, 236, 45),
            (255, 223, 21),
            (255, 206, 10),
            (255, 188, 0),
            (255, 177, 0),
            (255, 165, 0),
            (254, 153, 0),
            (253, 139, 0),
            (252, 127, 0),
        ],
        "puor": [
            (127, 59, 8),
            (177, 87, 6),
            (224, 130, 20),
            (252, 182, 97),
            (254, 224, 182),
            (246, 246, 246),
            (216, 218, 235),
            (177, 169, 209),
            (128, 115, 172),
            (83, 38, 134),
            (45, 0, 75),
        ],
    }
    for name, stops in expected.items():
        assert COLORMAP_STOPS[name] == stops
        assert channels.is_colormap(name)
        assert channels.is_colormap(f"{name}_r")
        assert resolve_cmap(name) == name
        assert resolve_cmap(f"{name}_r") == f"{name}_r"
        assert _colormap_stops(f"{name}_r") == list(reversed(stops))


def test_flag_colormap_matches_matplotlib_lut_and_gray_aliases() -> None:
    """Gallery cmap names resolve without flattening flag's rapid color cycle."""
    from xy.pyplot._colors import resolve_cmap

    flag = COLORMAP_STOPS["flag"]
    assert len(flag) == 256

    # Full Matplotlib 3.11 ``colormaps["flag"](linspace(...), bytes=True)``
    # parity. The digest guards every channel of all 256 entries, including
    # the truncation behavior that sparse samples previously missed.
    flag_bytes = np.asarray(flag, dtype=np.uint8).tobytes()
    assert hashlib.sha256(flag_bytes).hexdigest() == (
        "c84ac1f0b2edd3a53ed05fc90dcf6a41e78c2cf52adf1b2288b2d03777505443"
    )

    js_path = ROOT / "js" / "src" / "10_colormaps.ts"
    encoded_source = base64.b64encode(js_path.read_bytes()).decode("ascii")
    completed = subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            (
                f'const module = await import("data:text/javascript;base64,{encoded_source}");'
                'console.log(JSON.stringify(module.colormapStops("flag")));'
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(completed.stdout) == [list(rgb) for rgb in flag]

    assert channels.is_colormap("flag")
    assert channels.is_colormap("flag_r")
    assert _colormap_stops("flag_r") == list(reversed(flag))
    assert resolve_cmap("flag") == "flag"
    assert resolve_cmap("flag_r") == "flag_r"

    assert resolve_cmap("gray") == "gray"
    assert resolve_cmap("grey") == "gray"
    assert resolve_cmap("gray_r") == "gray_r"
    assert resolve_cmap("grey_r") == "gray_r"


def test_scalar_stroke_color_survives_vectorized_style_path() -> None:
    """Scalar CSS stroke= on rect-family and mesh marks must not collapse to
    the face paint (regression: the per-item style refactor resolved strokes
    from the trace stroke channel or face only, skipping style['stroke'])."""
    bar_svg = (
        Figure()
        .bar([0, 1, 2], [1.0, 2.0, 3.0], color="steelblue", stroke="black", stroke_width=2.0)
        .to_svg()
    )
    assert 'stroke="rgb(0,0,0)"' in bar_svg
    assert 'stroke="rgb(70,130,180)"' not in bar_svg

    mesh_svg = (
        Figure()
        .triangle_mesh(
            [0.0],
            [0.0],
            [1.0],
            [0.0],
            [0.5],
            [1.0],
            color="steelblue",
            stroke="black",
            stroke_width=2.0,
        )
        .to_svg()
    )
    assert 'stroke="rgb(0,0,0)"' in mesh_svg


def test_segment_constant_translucent_color_applies_alpha_once() -> None:
    """A translucent constant segment color must not appear verbatim in
    stroke= while its alpha also feeds stroke-opacity (double application)."""
    svg = Figure().segments([0.2], [0.2], [0.8], [0.8], color="rgba(255,0,0,0.5)").to_svg()
    data_lines = [line for line in re.findall(r"<line[^>]*/>", svg) if "255,0,0" in line]
    assert data_lines, "segment line missing from SVG"
    (line,) = data_lines
    assert 'stroke="rgb(255,0,0)"' in line
    assert 'stroke-opacity="0.5"' in line

    opaque = Figure().segments([0.2], [0.2], [0.8], [0.8], color="red").to_svg()
    opaque_lines = [
        entry for entry in re.findall(r"<line[^>]*/>", opaque) if 'stroke="red"' in entry
    ]
    assert opaque_lines, "opaque constant color should pass through verbatim"


def _geometry_chart(side_x: str = "bottom", side_y: str = "left", style=None) -> xy.Chart:
    """A 3x3 tick grid with a pinned plot rect, so offsets are exact integers."""
    return xy.chart(
        xy.line([0.0, 1.0, 2.0], [0.0, 1.0, 0.5]),
        xy.x_axis(domain=(0.0, 2.0), tick_values=[0.0, 1.0, 2.0], side=side_x, style=style),
        xy.y_axis(domain=(0.0, 1.0), tick_values=[0.0, 0.5, 1.0], side=side_y, style=style),
        width=400,
        height=300,
        padding=(40, 50, 40, 50),
    )


def test_unstyled_tick_labels_keep_their_historical_svg_placement() -> None:
    """A chart that authors no tick styling places its tick labels at the exact
    pixels it always has.

    `tick_padding` derives the spine-to-label gap from tick geometry, but
    core's default `tick_length` is 0, so deriving it unconditionally silently
    pulls every unstyled chart's labels toward the spine. The per-side unstyled
    defaults in `_axis_tick_label_offset` exist to prevent that, and these are
    the literal numbers they have to reproduce.
    """
    plot = layout(_geometry_chart().figure().build_payload()[0])[3]
    assert (plot["x"], plot["y"], plot["w"], plot["h"]) == (50.0, 40.0, 300.0, 220.0)

    bottom_left = tick_label_positions(_geometry_chart().to_svg())
    # x, bottom: baseline 16 px below the spine, centered on the tick.
    assert bottom_left["0"] == (50.0, 276.0)
    assert bottom_left["1"] == (200.0, 276.0)
    assert bottom_left["2"] == (350.0, 276.0)
    # y, left: 8 px outside the spine, baseline nudged 4 px below the tick.
    assert bottom_left["0.0"] == (42.0, 264.0)
    assert bottom_left["0.5"] == (42.0, 154.0)
    assert bottom_left["1.0"] == (42.0, 44.0)

    flipped = _geometry_chart(side_x="top", side_y="right")
    top_plot = layout(flipped.figure().build_payload()[0])[3]
    assert (top_plot["x"], top_plot["y"], top_plot["w"], top_plot["h"]) == (
        50.0,
        66.0,
        258.0,
        194.0,
    )
    top_right = tick_label_positions(flipped.to_svg())
    # x, top: baseline 7 px above the spine. y, right: 8 px outside it.
    assert top_right["0"] == (50.0, 59.0)
    assert top_right["2"] == (308.0, 59.0)
    assert top_right["0.0"] == (316.0, 264.0)
    assert top_right["1.0"] == (316.0, 70.0)


def test_unstyled_tick_label_placement_ignores_the_tick_font_size() -> None:
    """The unstyled gaps are flat constants, as they were before
    `tick_padding` existed: a bigger tick font must not move the labels,
    because scaling the gap with the font belongs to the authored rule."""
    plain = tick_label_positions(_geometry_chart().to_svg())
    big = tick_label_positions(_geometry_chart(style={"tick_size": 20}).to_svg())
    assert big["0"] == plain["0"]
    assert big["1.0"] == plain["1.0"]


def test_authored_tick_geometry_moves_the_labels_off_the_spine() -> None:
    """Authoring `tick_length`/`tick_padding` switches to matplotlib's rule:
    padding measured from the outward end of the tick mark, with the anchor
    then clearing the glyph box."""
    styled = tick_label_positions(
        _geometry_chart(style={"tick_length": 6, "tick_padding": 5}).to_svg()
    )
    # 6 px outward tick + 5 px pad = 11 px, then 0.8 * the 11 px font to the baseline.
    assert styled["0"] == (50.0, 279.8)
    # y: 11 px outside the spine, baseline centered on 0.35 * the font size.
    assert styled["0.0"] == (39.0, 263.85)

    # tick_direction decides how much of tick_length counts as outward.
    inward = tick_label_positions(
        _geometry_chart(
            style={"tick_length": 6, "tick_padding": 5, "tick_direction": "in"}
        ).to_svg()
    )
    assert inward["0.0"] == (45.0, 263.85)
    halfway = tick_label_positions(
        _geometry_chart(
            style={"tick_length": 6, "tick_padding": 5, "tick_direction": "inout"}
        ).to_svg()
    )
    assert halfway["0.0"] == (42.0, 263.85)

    # A pad alone opts in; tick_length then contributes its default 0.
    pad_only = tick_label_positions(_geometry_chart(style={"tick_padding": 5}).to_svg())
    assert pad_only["0.0"] == (45.0, 263.85)


def test_tick_label_offset_defaults_stay_in_sync_with_js_client() -> None:
    """`tickLabelOffset` in 50_chartview.ts is the third implementation of this
    rule and carries its own unstyled per-side gaps (the client positions a
    label's box, not its baseline, so its numbers differ from the exporters').
    Pin them at the source: this suite has no browser."""
    js = (ROOT / "js" / "src" / "50_chartview.ts").read_text(encoding="utf-8")
    body = js.split("const tickLabelOffset = (axis, unstyled, fontRoomPx = 0) => {", 1)
    assert len(body) == 2, "tickLabelOffset signature changed; re-check the unstyled gaps"
    assert 'const rawPadding = this._axisStyleValue(axis, "tick_padding")' in body[1]
    assert 'const rawLength = this._axisStyleValue(axis, "tick_length")' in body[1]
    assert 'const rawWidth = this._axisStyleValue(axis, "tick_width")' in body[1]
    assert "const hiddenSentinel = Number(rawLength) === 0 && Number(rawWidth) === 0" in body[1]
    assert "if (!authored) return unstyled;" in body[1]
    # x bottom 6, x top 18 (plus its own line box), y 8 — unchanged since before
    # tick_padding existed. Primary and extra axes each have one call site.
    assert js.count("tickLabelOffset(xAxis, 6)") == 1
    assert js.count("tickLabelOffset(axis, 6)") == 1
    assert js.count("tickLabelOffset(xAxis, 18, Math.max(8, tickLabelSize) * 1.2)") == 1
    assert js.count("tickLabelOffset(axis, 18, Math.max(8, tickLabelSize) * 1.2)") == 1
    assert js.count("tickLabelOffset(axis, 8)") == 1


def test_svg_scopes_the_legend_clip_exemption_per_legend() -> None:
    """An anchored legend escapes the plot-rect clip that bounds static
    legends; a non-anchored sibling in the same figure must still be clipped
    (the native raster exporter mirrors this)."""
    spec, blob = Figure().line([0.0, 1.0], [0.0, 1.0], name="a").build_payload()
    spec["show_legend"] = False
    spec["extra_legends"] = [
        {
            "title": "anchored",
            "loc": "lower left",
            "anchor": [0.0, 1.0],
            "items": [{"name": "outside", "kind": "line", "style": {}}],
        },
        {
            "title": "bounded",
            "loc": "upper right",
            "items": [{"name": "inside", "kind": "line", "style": {}}],
        },
    ]

    svg = render_svg(spec, blob)
    groups = {
        title: match
        for title, match in (
            (title, match)
            for match in re.findall(r"<g(?: [^>]*)?>(?:(?!<g).)*?</g>", svg, re.S)
            for title in ("anchored", "bounded")
            if f">{title}</text>" in match
        )
    }
    assert set(groups) == {"anchored", "bounded"}, "both legend boxes should render"
    assert "clip-path=" not in groups["anchored"].split(">", 1)[0]
    assert "clip-path=" in groups["bounded"].split(">", 1)[0]


# --- what the browser draws, the export must draw too -------------------------
#
# Every case here is one option the live client honored while all three static
# exporters silently dropped it — the failure mode a user only discovers in the
# PNG they already pasted into a report.


def _texts(svg: str) -> list[str]:
    """Rendered strings, whether a <text> holds them directly or in <tspan>s."""
    return [
        "".join(node.itertext()).strip()
        for node in _parse(svg).iter("{http://www.w3.org/2000/svg}text")
    ]


@pytest.mark.parametrize(
    ("spec_format", "values", "expected"),
    [
        ("$,.0f", [1e6, 3e6, 5e6], "$1,000,000"),
        (".1%", [0.1, 0.2, 0.3], "10.0%"),
        (",.2f", [1000.0, 2000.0, 3000.0], "1,000.00"),
    ],
)
def test_axis_format_reaches_the_static_export(spec_format, values, expected) -> None:
    chart = xy.line_chart(
        xy.line([1, 2, 3], values),
        xy.y_axis(format=spec_format),
        width=640,
        height=380,
    )
    assert expected in _texts(chart.to_svg())


def test_time_axis_format_reaches_the_static_export() -> None:
    import datetime as dt

    days = [dt.datetime(2024, month, 1) for month in (1, 3, 5)]
    chart = xy.line_chart(
        xy.line(days, [1, 2, 3]),
        xy.x_axis(type_="time", format="%Y-%m"),
        width=680,
        height=380,
    )
    assert "2024-01" in _texts(chart.to_svg())


def test_an_unparseable_format_falls_back_instead_of_erroring() -> None:
    chart = xy.line_chart(xy.line([1, 2, 3], [1, 2, 3]), xy.y_axis(format="nonsense"))
    assert "1.0" in _texts(chart.to_svg())


def test_log_decades_below_one_get_distinct_labels() -> None:
    """0.001 and 0.01 both rendered as a bare "0": two identical, wrong labels.

    A log axis steps multiplicatively, so precision taken from the tick step
    is meaningless below 1.0."""
    chart = xy.line_chart(
        xy.line([1, 2, 3], [0.001, 0.01, 1.0]),
        xy.y_axis(type_="log"),
        width=560,
        height=340,
    )
    labels = [t for t in _texts(chart.to_svg()) if t.startswith("0")]
    assert labels, "expected sub-unit decade labels"
    assert len(labels) == len(set(labels)), f"duplicate decade labels: {labels}"


@pytest.mark.parametrize("spec_format", ["$,.0f", ".0fK", ".0f", ".0%"])
def test_a_log_axis_survives_an_affixed_format(spec_format) -> None:
    """The sub-unit fallback tested the whole label, not its numeric core.

    `"$,.0f"` renders a sub-unit decade as `"$0"`, and `float("$0")` raises —
    taking the entire render down. The client's `Number("$0")` is `NaN`
    instead, so it shipped the collapsed label: two different wrong answers
    from the layer that exists to keep them identical."""
    chart = xy.line_chart(
        xy.line([1, 2, 3], [0.001, 0.01, 1.0]),
        xy.y_axis(type_="log", format=spec_format),
        width=560,
        height=340,
    )
    labels = [t for t in _texts(chart.to_svg()) if (t and t[0].isdigit()) or t.startswith("$")]
    assert labels, "the axis rendered no labels at all"
    # Whatever the affix, no sub-unit decade may collapse to a bare zero.
    cores = [re.sub(r"[^0-9eE+.\-]", "", t) for t in labels]
    assert not any(core and float(core) == 0.0 for core in cores), labels


def test_formatted_labels_widen_the_gutter_instead_of_running_off_the_canvas() -> None:
    wide = xy.line_chart(
        xy.line([1, 2, 3], [1e9, 2e9, 3e9]),
        xy.y_axis(format="$,.0f"),
        width=640,
        height=380,
    )
    svg = wide.to_svg()
    plot_x = float(re.search(r'<rect x="([0-9.]+)"', svg).group(1))
    starts = [float(x) for x, text in re.findall(r'<text x="(-?[0-9.]+)"[^>]*>([^<]+)</text>', svg)]
    assert min(starts) >= 0.0, "a tick label was placed off the left edge"
    assert plot_x > 62, "the gutter must grow for $1,000,000,000-wide labels"


def test_an_ordinary_chart_keeps_its_historical_gutter() -> None:
    svg = xy.line_chart(xy.line([1, 2, 3], [1, 2, 3]), width=640, height=380).to_svg()
    assert re.search(r'<rect x="62"', svg), "auto-sizing must only ever widen"


def test_a_categorical_color_channel_gets_one_legend_row_per_category() -> None:
    """One trace, three categories: the export drew a single row bearing the
    trace name and the trace's constant color — a legend that misdescribed the
    three colors printed beside it."""
    species = ["setosa"] * 4 + ["versicolor"] * 4 + ["virginica"] * 4
    chart = xy.scatter_chart(
        xy.scatter(list(range(12)), list(range(12)), color=species, name="iris"),
        xy.legend(),
        width=560,
        height=380,
    )
    svg = chart.to_svg()
    assert {"setosa", "versicolor", "virginica"} <= set(_texts(svg))
    assert "iris" not in _texts(svg), "the trace name must not stand in for the categories"


def test_categorical_legend_swatches_use_the_category_colors() -> None:
    species = ["a"] * 3 + ["b"] * 3
    chart = xy.scatter_chart(
        xy.scatter(list(range(6)), list(range(6)), color=species, name="s"),
        xy.theme(palette=["#ff0000", "#0000ff"]),
        xy.legend(),
    )
    svg = chart.to_svg()
    assert "#ff0000" in svg and "#0000ff" in svg


@pytest.mark.parametrize(
    ("annotation", "label"),
    [
        (lambda: xy.hline(y=2, text="target"), "target"),
        (lambda: xy.vline(x=2, text="launch"), "launch"),
        (lambda: xy.x_band(x0=1.2, x1=1.8, text="window"), "window"),
        (lambda: xy.marker(x=2, y=3, text="peak"), "peak"),
        (lambda: xy.arrow(x0=1, y0=1, x1=2, y1=3, text="rise"), "rise"),
    ],
)
def test_annotation_text_reaches_the_static_export(annotation, label) -> None:
    chart = xy.line_chart(xy.line([1, 2, 3], [1, 3, 2]), annotation(), width=680, height=400)
    assert label in _texts(chart.to_svg())


def test_a_marker_annotation_draws_its_glyph_not_just_its_label() -> None:
    plain = xy.line_chart(xy.line([1, 2, 3], [1, 3, 2]), width=680, height=400).to_svg()
    marked = xy.line_chart(
        xy.line([1, 2, 3], [1, 3, 2]), xy.marker(x=2, y=3), width=680, height=400
    ).to_svg()
    assert marked.count("<circle") == plain.count("<circle") + 1
