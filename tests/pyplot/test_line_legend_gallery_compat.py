import numpy as np

import xy.pyplot as plt
from xy._svg import _legend_layout
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

    plot = {"x": 10.0, "y": 20.0, "w": 100.0, "h": 80.0}
    layout = _legend_layout(
        [{"name": "line"}],
        plot,
        {"loc": "lower left", "anchor": (0.0, 1.0)},
    )
    assert layout["x"] == 10.0
    assert layout["y"] + layout["box_h"] == 20.0


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
