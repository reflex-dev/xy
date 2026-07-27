from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _raster, _svg
from xy._svg import _LEGEND_CHAR_WIDTH, _legend_layout, _legend_text_width, layout
from xy.pyplot import Legend


def teardown_function():
    plt.close("all")


def _legend_frame_and_labels(svg_root, names):
    """The emitted legend frame rect and label texts, from real SVG geometry.

    The legend frame is the only rect carrying both a fill and a stroke opacity
    in a line chart, so it is identified without consulting the layout that is
    under test.
    """
    frames = [
        element
        for element in svg_root.iter()
        if element.tag.endswith("rect")
        and "fill-opacity" in element.attrib
        and "stroke-opacity" in element.attrib
    ]
    assert len(frames) == 1, [frame.attrib for frame in frames]
    labels = [
        element
        for element in svg_root.iter()
        if element.tag.endswith("text") and (element.text or "") in names
    ]
    return frames[0], labels


def test_plot_drawstyle_steps_aliases_steps_pre():
    _, ax = plt.subplots()
    line = ax.plot([0, 1, 2], [2, 1, 3], drawstyle="steps")[0]

    assert line._entry["factory"] == "step"
    assert line._entry["kwargs"]["where"] == "pre"
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["traces"][0]["kind"] == "line"
    assert spec["traces"][0]["style"]["step"] == "pre"


def test_legend_bbox_to_anchor_reaches_payload_and_static_layout():
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="line")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1))

    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["anchor"] == [0.0, 1.0]
    assert spec["legend"]["style"]["--xy-legend-frame-alpha"] == 0.8
    assert spec["legend"]["style"]["borderColor"] == "#cccccc"
    assert spec["legend"]["style"]["borderWidth"] == "1px"

    plot = {"x": 10.0, "y": 20.0, "w": 100.0, "h": 80.0}
    layout = _legend_layout(
        [{"name": "line"}],
        plot,
        {"loc": "lower left", "anchor": (0.0, 1.0)},
    )
    assert layout["x"] == 10.0
    assert layout["y"] + layout["box_h"] == 20.0


def test_multicolumn_legend_sizes_each_column_to_its_own_labels():
    named = [
        {"name": "Strongly disagree"},
        {"name": "Disagree"},
        {"name": "Neither agree nor disagree"},
        {"name": "Agree"},
        {"name": "Strongly agree"},
    ]
    plot = {"x": 0.0, "y": 0.0, "w": 900.0, "h": 200.0}

    layout = _legend_layout(named, plot, {"ncols": 5, "loc": "upper center"})

    assert layout["names"] == [entry["name"] for entry in named]
    assert len(set(layout["column_widths"])) > 1
    assert layout["column_offsets"][1] == (
        layout["column_offsets"][0] + layout["column_widths"][0] + layout["column_gap"]
    )
    equal_width_box = 5 * max(layout["column_widths"]) + 4 * layout["column_gap"] + layout["pad"]
    assert layout["box_w"] < equal_width_box


def test_outside_top_legend_preserves_gallery_labels_and_reserves_its_box(monkeypatch):
    fig, ax = plt.subplots(figsize=(9.2, 5))
    labels = [
        "Strongly disagree",
        "Disagree",
        "Neither agree nor disagree",
        "Agree",
        "Strongly agree",
    ]
    for index, label in enumerate(labels):
        ax.barh(["Question 1", "Question 2"], [index + 1, index + 2], label=label)
    ax.legend(
        ncols=len(labels),
        bbox_to_anchor=(0, 1),
        loc="lower left",
        fontsize="small",
    )

    spec, blob = ax._build_chart(920, 500).figure().build_payload()
    _, _, _, plot = layout(spec)
    legend = _legend_layout(
        [trace for trace in spec["traces"] if trace.get("name")],
        plot,
        spec["legend"],
    )

    assert legend["names"] == labels
    assert spec["padding"][0] >= legend["box_h"] + spec["legend"]["border_pad"] + 6
    assert legend["y"] >= 6
    assert plot["y"] - (legend["y"] + legend["box_h"]) == pytest.approx(
        spec["legend"]["border_pad"]
    )

    output = BytesIO()
    fig.savefig(output, format="svg", dpi=100)
    texts = {
        element.text
        for element in ElementTree.fromstring(output.getvalue()).iter()
        if element.tag.endswith("text")
    }
    assert set(labels) <= texts

    raster_text: set[str] = set()
    original_text = _raster._Cmd.text

    def record_text(self, x, y, anchor, size, color, text, **kwargs):
        raster_text.add(str(text))
        return original_text(self, x, y, anchor, size, color, text, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", record_text)
    _raster.render_raster(spec, blob, scale=1)
    assert set(labels) <= raster_text


def test_titled_scatter_legend_box_fits_title_and_every_entry():
    _, ax = plt.subplots()
    scatter = ax.scatter(
        np.arange(4),
        np.arange(4),
        c=np.array([1, 2, 3, 4]),
        s=np.array([10, 40, 90, 160]),
    )
    handles, labels = scatter.legend_elements()
    legend = ax.legend(handles, labels, loc="lower left", title="Classes")

    spec = legend.spec()
    box = _legend_layout(
        spec["items"],
        {"x": 62.0, "y": 10.0, "w": 564.0, "h": 428.0},
        spec,
    )

    assert box["title"] == "Classes"
    assert box["names"] == labels
    assert box["visible_count"] == len(labels)
    char_width = box["font_size"] * (_LEGEND_CHAR_WIDTH / 11.0)
    assert box["box_w"] >= _legend_text_width("Classes", char_width) + box["pad"]
    assert box["box_h"] > 100


def test_hidden_axis_keeps_explicit_matplotlib_spines_in_static_exports():
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.xaxis.set_visible(False)
    spec, _ = ax._build_chart(300, 200).figure().build_payload()
    assert spec["frame_sides"] == ["left", "bottom", "top", "right"]
    _, _, _, plot = layout(spec)

    output = BytesIO()
    fig.savefig(output, format="svg")
    root = ElementTree.fromstring(output.getvalue())
    lines = [element for element in root.iter() if element.tag.endswith("line")]
    full_width_rules = {
        round(float(line.attrib["y1"]), 6)
        for line in lines
        if abs(float(line.attrib["x1"]) - plot["x"]) < 1e-6
        and abs(float(line.attrib["x2"]) - (plot["x"] + plot["w"])) < 1e-6
        and abs(float(line.attrib["y1"]) - float(line.attrib["y2"])) < 1e-6
    }
    assert round(plot["y"], 6) in full_width_rules
    assert round(plot["y"] + plot["h"], 6) in full_width_rules

    output = BytesIO()
    fig.savefig(output, format="png", dpi=100)
    output.seek(0)
    pixels = plt.imread(output)
    scale_x = pixels.shape[1] / 300
    scale_y = pixels.shape[0] / 200
    x = round((plot["x"] + plot["w"] / 2) * scale_x)
    for edge in (plot["y"], plot["y"] + plot["h"]):
        y = round(edge * scale_y)
        sample = pixels[max(0, y - 2) : min(pixels.shape[0], y + 3), x, :3]
        dark_threshold = 128.0 if np.issubdtype(sample.dtype, np.integer) else 0.5
        assert float(sample.min()) < dark_threshold


def test_bar_numpy_rgba_row_is_one_color_for_trace_and_legend():
    _, ax = plt.subplots()
    rgba = np.array([0.9, 0.2, 0.1, 1.0])
    ax.barh(["a", "b"], [1, 2], label="answers", color=rgba)

    entry = ax._entries[-1]
    assert entry["kwargs"]["color"] == "rgba(230,51,26,1)"


def test_scalar_scatter_alpha_survives_native_affine_fast_path():
    fig, ax = plt.subplots(figsize=(2, 2))
    ax.scatter([0.5], [0.5], s=2500, c="red", alpha=0.25, edgecolors="none")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    output = BytesIO()
    fig.savefig(output, format="png", dpi=100)
    output.seek(0)
    pixels = plt.imread(output).astype(np.float64) / 255.0
    red_pixels = pixels[(pixels[..., 0] > 0.95) & (pixels[..., 1] < 0.9) & (pixels[..., 2] < 0.9)]
    assert red_pixels.size
    assert float(red_pixels[..., 1].min()) > 0.6


def test_scatter_legend_elements_return_real_legend_artists_and_two_boxes():
    _, ax = plt.subplots()
    scatter = ax.scatter(
        np.arange(4),
        np.arange(4),
        c=np.array([1, 2, 3, 4]),
        s=np.array([10, 40, 90, 160]),
    )

    color_handles, color_labels = scatter.legend_elements()
    first = ax.legend(color_handles, color_labels, loc="lower left", title="Classes")
    assert isinstance(first, Legend)
    ax.add_artist(first)

    size_handles, size_labels = scatter.legend_elements(
        prop="sizes",
        num=3,
        alpha=0.6,
        fmt="$ {x:.0f}",
        func=lambda value: np.sqrt(value),
    )
    second = ax.legend(size_handles, size_labels, loc="upper right", title="Sizes")
    assert isinstance(second, Legend)
    assert ax.get_legend() is second

    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["show_legend"] is False
    assert [legend["title"] for legend in spec["extra_legends"]] == ["Classes", "Sizes"]
    assert len(spec["extra_legends"][0]["items"]) == 4
    sizes = [item["style"]["size"] for item in spec["extra_legends"][1]["items"]]
    assert sizes == sorted(sizes)
    assert all(label.startswith("$ ") for label in size_labels)
    assert all(item["name"].startswith("$ ") for item in spec["extra_legends"][1]["items"])


def test_scatter_legend_elements_none_and_array_num_follow_matplotlib() -> None:
    _, ax = plt.subplots()
    scatter = ax.scatter(
        np.arange(4),
        np.arange(4),
        c=np.array([1.0, 2.0, 2.0, 4.0]),
        s=np.array([10.0, 20.0, 20.0, 40.0]),
    )

    color_handles, color_labels = scatter.legend_elements(num=None)
    size_handles, size_labels = scatter.legend_elements(prop="sizes", num=None)
    fixed_handles, fixed_labels = scatter.legend_elements(num=np.array([1.0, 4.0]))

    assert len(color_handles) == len(color_labels) == 3
    assert color_labels == ["1", "2", "4"]
    assert len(size_handles) == len(size_labels) == 3
    assert size_labels == ["10", "20", "40"]
    assert len(fixed_handles) == len(fixed_labels) == 2
    assert fixed_labels == ["1", "4"]


def test_round_dash_capstyle_mutation_matches_fixed_round_renderers():
    _, ax = plt.subplots()
    line = ax.plot([0, 1], [0, 1], "--")[0]

    line.set_dash_capstyle("round")

    assert line.get_dash_capstyle() == "round"
    assert line._entry["kwargs"]["dash_capstyle"] == "round"
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["traces"][0]["kind"] == "line"
    assert "dash_capstyle" not in spec["traces"][0]["style"]


def test_round_dash_capstyle_mutation_is_filtered_for_step_lines():
    _, ax = plt.subplots()
    line = ax.plot([0, 1, 2], [0, 1, 0], "--", drawstyle="steps-post")[0]

    line.set_dash_capstyle("round")

    assert line.get_dash_capstyle() == "round"
    assert line._entry["kwargs"]["dash_capstyle"] == "round"
    assert line._entry["kind"] == "@mark"
    assert line._entry["factory"] == "step"
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["traces"][0]["kind"] == "line"
    assert "dash_capstyle" not in spec["traces"][0]["style"]


def test_legend_frame_is_wide_enough_for_its_measured_labels():
    """The frame must contain its own labels, wide glyphs included.

    Regression: columns were sized as ``len(label) * _LEGEND_CHAR_WIDTH``, a
    flat per-character average. "gamma" sets 42.6 px at 11 px against a 31.0 px
    estimate, so the 1 px frame landed ~7.6 px inside the label's right edge and
    "alpha"/"gamma" visibly crossed the border. Matplotlib insets the widest
    label from its frame by ``borderpad``; the sign is what matters here.
    """
    names = ("alpha", "beta", "gamma")
    fig, ax = plt.subplots(figsize=(6.4, 4.8))
    for name in names:
        ax.plot([0, 1], [0, 1], label=name)
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        frameon=True,
        edgecolor="black",
        title="series",
    )

    output = BytesIO()
    fig.savefig(output, format="svg")
    frame, labels = _legend_frame_and_labels(ElementTree.fromstring(output.getvalue()), names)

    assert {label.text for label in labels} == set(names)
    frame_right = float(frame.attrib["x"]) + float(frame.attrib["width"])
    for label in labels:
        label_right = float(label.attrib["x"]) + _legend_text_width(label.text)
        assert label_right <= frame_right, (
            f"{label.text!r} runs to {label_right:.3f}, past the frame's {frame_right:.3f}"
        )
    # The label is inset, not merely touching, as matplotlib's borderpad is.
    widest = max(float(label.attrib["x"]) + _legend_text_width(label.text) for label in labels)
    assert frame_right - widest > 0.0


def test_legend_column_width_measures_glyphs_not_character_count():
    """A flat per-character average cannot bound a proportional face."""
    # "m" is far wider than the average and "l" far narrower, yet a character
    # count scores these two identically -- which is exactly the bug.
    assert _legend_text_width("mmmmm") > 5 * _LEGEND_CHAR_WIDTH
    assert _legend_text_width("lllll") < 5 * _LEGEND_CHAR_WIDTH
    assert _legend_text_width("gamma") > _legend_text_width("alpha")

    plot = {"x": 0.0, "y": 0.0, "w": 560.0, "h": 400.0}
    result = _legend_layout([{"name": "gamma"}], plot, {"loc": "upper right"})
    # The column is sized to the measured label, so the frame encloses text
    # drawn at handle + gap with the border pad still to spare on the right.
    text_x = result["column_offsets"][0] + result["handle"] + result["gap"]
    assert text_x + _legend_text_width("gamma") <= result["box_w"]


def test_legend_handle_geometry_uses_legend_font_units():
    plot = {"x": 0.0, "y": 0.0, "w": 560.0, "h": 400.0}
    default = _legend_layout([{"name": "line"}], plot, {"loc": "upper right"})
    custom = _legend_layout(
        [{"name": "line"}],
        plot,
        {"loc": "upper right", "handlelength": 4, "handletextpad": 1.25},
    )

    assert default["handle"] == pytest.approx(2 * default["font_size"])
    assert default["gap"] == pytest.approx(0.8 * default["font_size"])
    assert custom["handle"] == pytest.approx(4 * custom["font_size"])
    assert custom["gap"] == pytest.approx(1.25 * custom["font_size"])
    assert custom["box_w"] > default["box_w"]


def test_ellipsized_legend_label_fits_the_column_it_was_sized_for():
    """Truncation is measured too, so a shortened label cannot overrun either."""
    plot = {"x": 0.0, "y": 0.0, "w": 150.0, "h": 400.0}
    names = ["Wmmmmmmmmmmmmmmmmmmmm", "iiiiiiiiiiiiiiiiiiii"]
    result = _legend_layout([{"name": name} for name in names], plot, {"loc": "upper right"})

    assert any(name.endswith("...") for name in result["names"])
    text_x = result["column_offsets"][0] + result["handle"] + result["gap"]
    for rendered in result["names"]:
        assert text_x + _legend_text_width(rendered) <= result["box_w"]


def test_titled_legend_frame_contains_its_title():
    """A title is ellipsized against measured width, so it stays in the frame.

    Regression: the title budget subtracted two border pads from a box that had
    only been grown by one, so "Classes" over short entries lost two more
    characters than it needed to -- "Cl..." where the merge-base rendered
    "Cla...". Measuring the title's real extent more than restores it.
    """
    plot = {"x": 0.0, "y": 0.0, "w": 560.0, "h": 400.0}
    short = _legend_layout(
        [{"name": name} for name in ("1", "2", "3", "4")],
        plot,
        {"loc": "lower left", "title": "Classes"},
    )
    # Whatever survives truncation fits between the two border pads, since the
    # title is drawn at x + pad.
    assert _legend_text_width(short["title"]) <= short["box_w"] - short["pad"]
    # Strictly longer than the "Cl..." this branch produced before the fix, and
    # than the "Cla..." the merge-base produced.
    assert short["title"].startswith("Clas")

    # Given entries wide enough to carry it, the title is not truncated at all.
    wide = _legend_layout(
        [{"name": name} for name in ("alpha", "beta", "gamma")],
        plot,
        {"loc": "lower left", "title": "Classes"},
    )
    assert wide["title"] == "Classes"


def test_raster_legend_frame_strokes_all_four_sides(monkeypatch):
    """The frame is a closed rectangle, like matplotlib's FancyBboxPatch.

    Regression: ``_rect_pts`` is four corners, so stroking it as an open
    polyline painted top/right/bottom and silently dropped the left edge.
    """
    recorded: list[tuple[list[tuple[float, float]], bool]] = []
    original_stroke = _raster._Cmd.stroke

    def record_stroke(self, pts, width, color, closed=False, dash=None, cap="round"):
        recorded.append(([tuple(map(float, point)) for point in pts], bool(closed)))
        return original_stroke(self, pts, width, color, closed=closed, dash=dash, cap=cap)

    monkeypatch.setattr(_raster._Cmd, "stroke", record_stroke)

    _, ax = plt.subplots(figsize=(4.2, 3.0))
    for name in ("alpha", "beta", "gamma"):
        ax.plot([0, 1], [0, 1], label=name)
    ax.legend(loc="upper right", frameon=True, edgecolor="black")
    spec, blob = ax._build_chart(420, 300).figure().build_payload()
    _width, _height, _compact, plot = layout(spec)
    legend = _legend_layout(
        [{"name": name} for name in ("alpha", "beta", "gamma")], plot, spec["legend"]
    )
    _raster.render_raster(spec, blob, scale=1)

    corners = [
        (legend["x"], legend["y"]),
        (legend["x"] + legend["box_w"], legend["y"]),
        (legend["x"] + legend["box_w"], legend["y"] + legend["box_h"]),
        (legend["x"], legend["y"] + legend["box_h"]),
    ]
    matches = [
        closed
        for pts, closed in recorded
        if abs(min(point[0] for point in pts) - corners[0][0]) < 1e-6
        and abs(max(point[0] for point in pts) - corners[1][0]) < 1e-6
        and abs(min(point[1] for point in pts) - corners[0][1]) < 1e-6
        and abs(max(point[1] for point in pts) - corners[2][1]) < 1e-6
    ]
    assert matches, [pts for pts, _ in recorded]
    # Four corners stroked open would leave the closing left edge unpainted.
    assert all(matches), "legend frame stroked as an open polyline (left edge missing)"


def test_raster_legend_rounds_frame_and_shadow_only_when_requested():
    class Recorder:
        def __init__(self):
            self.fills = []
            self.strokes = []

        def fill(self, pts, _color):
            self.fills.append(list(pts))

        def stroke(self, pts, _width, _color, closed=False, dash=None, cap="round"):
            self.strokes.append((list(pts), closed))

        def text(self, *_args, **_kwargs):
            pass

    named = [{"name": "line", "kind": "line", "style": {}}]
    plot = {"x": 0.0, "y": 0.0, "w": 240.0, "h": 160.0}

    rounded = Recorder()
    _raster._emit_legend(
        rounded,
        named,
        plot,
        {
            "style": {
                "background": "#ffffff",
                "borderRadius": "4px",
                "boxShadow": "0 2px 8px rgba(0,0,0,.3)",
            }
        },
    )
    assert len(rounded.fills) == 2
    assert all(len(points) > 4 for points in rounded.fills)
    rounded_frame = [points for points, closed in rounded.strokes if closed]
    assert len(rounded_frame) == 1
    assert len(rounded_frame[0]) > 4

    square = Recorder()
    _raster._emit_legend(
        square,
        named,
        plot,
        {"style": {"background": "#ffffff", "boxShadow": "0 2px 8px rgba(0,0,0,.3)"}},
    )
    assert [len(points) for points in square.fills] == [4, 4]
    square_frame = [points for points, closed in square.strokes if closed]
    assert len(square_frame) == 1
    assert len(square_frame[0]) == 4


def test_raster_line_only_legend_symbols_receive_visible_strokes():
    class Recorder:
        def __init__(self):
            self.points = []

        def fill(self, *_args, **_kwargs):
            pass

        def stroke(self, *_args, **_kwargs):
            pass

        def text(self, *_args, **_kwargs):
            pass

        def point(self, _x, _y, _r, symbol, _fill, width, stroke):
            self.points.append((symbol, width, stroke))

    recorder = Recorder()
    _raster._emit_legend(
        recorder,
        [
            {
                "name": "plus",
                "kind": "scatter",
                "style": {"symbol": "plus_line", "color": "#123456"},
            },
            {
                "name": "x",
                "kind": "scatter",
                "style": {
                    "symbol": "x_line",
                    "color": "#abcdef",
                    "stroke": "#ff0000",
                    "stroke_width": 2.5,
                },
            },
        ],
        {"x": 0.0, "y": 0.0, "w": 240.0, "h": 160.0},
        {},
    )

    assert recorder.points == [
        (_raster._SYMBOLS["plus_line"], 1.0, (18, 52, 86, 255)),
        (_raster._SYMBOLS["x_line"], 2.5, (255, 0, 0, 255)),
    ]


def test_hollow_patch_legend_swatch_preserves_its_outline_in_every_renderer():
    class Recorder:
        def __init__(self):
            self.fills = []
            self.strokes = []

        def fill(self, points, color):
            self.fills.append((list(points), color))

        def stroke(self, points, width, color, closed=False, dash=None, cap="round"):
            self.strokes.append((list(points), width, color, closed))

        def text(self, *_args, **_kwargs):
            pass

    named = [
        {
            "name": "hollow",
            "kind": "bar",
            "style": {
                "color": "transparent",
                "opacity": 1.0,
                "stroke": "green",
                "stroke_width": 2.0,
            },
        }
    ]
    plot = {"x": 0.0, "y": 0.0, "w": 240.0, "h": 160.0}

    recorder = Recorder()
    _raster._emit_legend(recorder, named, plot, {"style": {"background": "transparent"}})
    assert recorder.strokes == [
        (
            recorder.fills[0][0],
            2.0,
            (0, 128, 0, 255),
            True,
        )
    ]

    svg = ElementTree.fromstring(
        _svg._legend(
            named,
            plot,
            {"style": {"background": "transparent"}},
            "legend-clip",
            "black",
            ["#1f77b4"],
        )
    )
    swatches = [
        element
        for element in svg.iter()
        if element.tag.endswith("rect") and element.attrib.get("fill") == "transparent"
    ]
    assert [swatch.attrib.get("stroke") for swatch in swatches] == ["green"]
    assert [swatch.attrib.get("stroke-width") for swatch in swatches] == ["2"]


def test_explicit_hollow_bar_legend_item_keeps_patch_stroke():
    _, ax = plt.subplots()
    _counts, _edges, container = ax.hist(
        [0.0, 1.0, 2.0],
        bins=2,
        fill=False,
        edgecolor="green",
        linewidth=2,
        label="hollow",
    )
    legend = Legend(ax, [container], ["hollow"])

    assert legend.spec()["items"] == [
        {
            "name": "hollow",
            "kind": "bar",
            "style": {
                "color": "transparent",
                "opacity": 1.0,
                "stroke": "green",
                "stroke_width": 2.0,
            },
        }
    ]
