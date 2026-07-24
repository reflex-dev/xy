from io import BytesIO
from xml.etree import ElementTree

import numpy as np

import xy.pyplot as plt
from xy import _raster
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
        assert float(sample.min()) < 0.5


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


def test_round_dash_capstyle_mutation_matches_fixed_round_renderers():
    _, ax = plt.subplots()
    line = ax.plot([0, 1], [0, 1], "--")[0]

    line.set_dash_capstyle("round")

    assert line.get_dash_capstyle() == "round"
    assert line._entry["kwargs"]["dash_capstyle"] == "round"


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

    def record_stroke(self, pts, width, color, closed=False, dash=None):
        recorded.append(([tuple(map(float, point)) for point in pts], bool(closed)))
        return original_stroke(self, pts, width, color, closed=closed, dash=dash)

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
        if len(pts) == 4
        and all(
            abs(pts[index][axis] - corners[index][axis]) < 1e-6
            for index in range(4)
            for axis in (0, 1)
        )
    ]
    assert matches, [pts for pts, _ in recorded if len(pts) == 4]
    # Four corners stroked open would leave the closing left edge unpainted.
    assert all(matches), "legend frame stroked as an open polyline (left edge missing)"
