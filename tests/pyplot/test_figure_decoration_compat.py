from __future__ import annotations

from xy import pyplot as plt
from xy.pyplot._mplfig import Figure


def test_three_axes_title_slots_survive_in_one_renderer_payload() -> None:
    fig = Figure(1, dpi=100)
    ax = fig.add_subplot(111)

    with plt.rc_context(
        {
            "axes.titlelocation": "left",
            "axes.titlepad": 9.0,
            "axes.titley": 1.04,
        }
    ):
        ax.set_title("Left from rc")
    ax.set_title("Center", loc="center", pad=3, color="red")
    ax.set_title("Right", loc="right", y=0.92)

    spec, _blob = ax._build_chart(640, 480).figure().build_payload()
    titles = {entry["loc"]: entry for entry in spec["title_options"]}

    assert list(titles) == ["left", "center", "right"]
    assert titles["left"]["text"] == "Left from rc"
    assert titles["left"]["y"] == 1.04
    assert titles["left"]["automatic_y"] is False
    assert titles["left"]["pad"] == 12.5
    assert titles["center"]["style"]["color"] == "red"
    assert titles["right"]["y"] == 0.92
    assert ax.get_title("left") == "Left from rc"
    assert ax.get_title() == "Center"


def test_figure_super_labels_are_compositor_owned_and_mutable() -> None:
    fig = Figure(1, figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    xlabel = fig.supxlabel("shared x", fontsize=12)
    ylabel = fig.supylabel("shared y", color="navy")

    xlabel.set_text("updated x")
    labels = {label["role"]: label for label in fig._resolved_figure_labels()}

    assert all(entry is not xlabel._entry for entry in ax._entries)
    assert all(entry is not ylabel._entry for entry in ax._entries)
    assert labels["x"]["text"] == "updated x"
    assert labels["x"]["x"] == 0.5
    assert labels["y"]["rotation"] == 90.0
    assert labels["y"]["color"] == "navy"
    assert fig._effective_rects() is not None


def test_figure_legend_aggregates_axes_and_reserves_outside_right() -> None:
    fig = Figure(1, figsize=(6, 3), dpi=100)
    axes = fig.subplots(1, 2)
    axes[0].plot([0, 1], [0, 1], label="first")
    axes[1].plot([0, 1], [1, 0], label="second")
    fig.tight_layout()

    legend = fig.legend(loc="outside right upper")
    before = fig._subplot_adjust.get("right", 1.0)
    fig._ensure_layout()

    assert legend is fig._figure_legend_handle
    assert [item["name"] for item in fig._figure_legend["items"]] == ["first", "second"]
    assert fig._figure_legend["figure_loc"] == "outside right upper"
    assert fig._subplot_adjust["right"] < before
    assert not any(ax._legend for ax in axes)
