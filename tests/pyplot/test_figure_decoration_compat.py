from __future__ import annotations

import numpy as np
import pytest

from xy import _textblock
from xy import pyplot as plt
from xy._svg import _decode_title_geometry, render_svg
from xy.pyplot._grid import _figure_label_baseline, _html_figure_labels
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

    spec, blob = ax._build_chart(640, 480).figure().build_payload()
    assert all("y" not in entry and "pad" not in entry for entry in spec["title_options"])
    assert all(isinstance(entry["geometry"], int) for entry in spec["title_options"])
    decoded = _decode_title_geometry(spec, blob)
    titles = {entry["loc"]: entry for entry in decoded["title_options"]}

    assert list(titles) == ["left", "center", "right"]
    assert titles["left"]["text"] == "Left from rc"
    assert titles["left"]["y"] == pytest.approx(1.04)
    assert titles["left"]["automatic_y"] is False
    assert titles["left"]["pad"] == pytest.approx(12.5)
    assert titles["center"]["style"]["color"] == "red"
    assert titles["right"]["y"] == pytest.approx(0.92)
    np.testing.assert_allclose(
        [titles["left"]["y"], titles["left"]["pad"], titles["right"]["y"]],
        [1.04, 12.5, 0.92],
    )
    svg = render_svg(spec, blob)
    assert all(text in svg for text in ("Left from rc", "Center", "Right"))
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


def test_figure_supylabel_defaults_to_center_and_honors_alignment_aliases() -> None:
    fig = Figure(1)

    fig.supylabel("default")
    assert fig._resolved_figure_labels()[0]["vertical_align"] == "center"

    fig.supylabel("long form", verticalalignment="top")
    assert fig._resolved_figure_labels()[0]["vertical_align"] == "top"

    fig.supylabel("short form", va="bottom")
    assert fig._resolved_figure_labels()[0]["vertical_align"] == "bottom"


def test_figure_label_baseline_and_html_honor_vertical_alignment() -> None:
    block = _textblock.measure("shared label", 12)
    label = {"text": "shared label", "y": 0.25, "vertical_align": "baseline"}

    assert _figure_label_baseline(200, label, block) == 150
    assert "translate(-50%,-100%)" in _html_figure_labels([label])
    label["vertical_align"] = "top"
    assert _figure_label_baseline(200, label, block) == 150 + block.ascent
    assert "translate(-50%,0%)" in _html_figure_labels([label])


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
