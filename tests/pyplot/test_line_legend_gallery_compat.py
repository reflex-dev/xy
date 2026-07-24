from io import BytesIO
from xml.etree import ElementTree

import numpy as np
import pytest

import xy.pyplot as plt
from xy._svg import _legend_layout, layout
from xy.pyplot import Legend


def teardown_function():
    plt.close("all")


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


def test_outside_top_legend_reserves_its_measured_box_and_axes_gap():
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

    spec, _ = ax._build_chart(920, 500).figure().build_payload()
    _, _, _, plot = layout(spec)
    legend = _legend_layout(
        [trace for trace in spec["traces"] if trace.get("name")],
        plot,
        spec["legend"],
    )

    assert spec["padding"][0] >= legend["box_h"] + spec["legend"]["border_pad"] + 6
    assert legend["y"] >= 6
    assert plot["y"] - (legend["y"] + legend["box_h"]) == pytest.approx(
        spec["legend"]["border_pad"]
    )


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
    assert box["box_w"] >= len("Classes") * box["font_size"] * (6.2 / 11.0) + box["pad"]
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
    assert all(item["name"].startswith("$ ") for item in spec["extra_legends"][1]["items"])


def test_round_dash_capstyle_mutation_matches_fixed_round_renderers():
    _, ax = plt.subplots()
    line = ax.plot([0, 1], [0, 1], "--")[0]

    line.set_dash_capstyle("round")

    assert line.get_dash_capstyle() == "round"
    assert line._entry["kwargs"]["dash_capstyle"] == "round"
