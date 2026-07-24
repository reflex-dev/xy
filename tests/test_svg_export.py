"""Static SVG export (_svg.py): well-formed output for every chart kind, the
screen-bounded size guarantee, styling fidelity markers, and sync guards
against the JS client tables it mirrors."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

import xy
from xy._figure import Figure
from xy._svg import COLORMAP_STOPS, _axis_tick_label_layout, _Scale

ROOT = Path(__file__).resolve().parents[1]


def _parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


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
    label = next(node for node in root.iter() if node.text == "middle")

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
    right_title = next(node for node in vertical_root.iter() if node.text == "Primary right")
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
    bottom_title = next(node for node in horizontal_root.iter() if node.text == "Bottom axis")
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
        node.text: node
        for node in root.iter()
        if node.text in {"Long category alpha", "Long category beta"}
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
    title = next(node for node in root.iter() if node.text == "Secondary positioned title")
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
    js_names = set(re.findall(r"^\s*(\w+): \[", body, re.MULTILINE))
    assert js_names == set(COLORMAP_STOPS), "colormap names diverged from 10_colormaps.ts"
    for name, stops in COLORMAP_STOPS.items():
        for r, g, b in stops:
            assert f"[{r}, {g}, {b}]" in body, (
                f"{name} stop ({r},{g},{b}) missing in 10_colormaps.ts"
            )


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
