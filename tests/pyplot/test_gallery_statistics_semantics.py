from __future__ import annotations

import numpy as np

import xy.pyplot as plt
from xy._figure import Figure


def teardown_function() -> None:
    plt.close("all")


def test_core_bar_accepts_per_item_widths_and_ships_exact_rectangles() -> None:
    spec, _ = Figure().bar([0.0, 2.0], [1.0, 3.0], width=[0.5, 1.5]).build_payload()

    trace = spec["traces"][0]
    assert "bar" not in trace
    assert {"x0", "x1", "y0", "y1"} <= trace.keys()


def test_barh_accepts_one_height_per_bar() -> None:
    _fig, ax = plt.subplots()
    bars = ax.barh([1.0, 3.0], [2.0, 4.0], height=[0.4, 1.2])

    np.testing.assert_allclose(bars._entry["kwargs"]["width"], [0.4, 1.2])


def test_hist_rwidth_scales_each_nonuniform_bin() -> None:
    _fig, ax = plt.subplots()
    _counts, edges, bars = ax.hist(
        [0.2, 1.5, 3.0],
        bins=[0.0, 1.0, 2.0, 4.0],
        histtype="barstacked",
        rwidth=0.8,
    )

    np.testing.assert_allclose(edges, [0.0, 1.0, 2.0, 4.0])
    np.testing.assert_allclose(bars._entry["kwargs"]["width"], [0.8, 0.8, 1.6])
    np.testing.assert_allclose(bars._entry["x"], [0.5, 1.5, 3.0])


def test_hist_legend_does_not_treat_bin_widths_as_line_widths() -> None:
    _fig, ax = plt.subplots()
    ax.hist(
        [0.2, 1.5, 3.0],
        bins=[0.0, 1.0, 2.0, 4.0],
        label="samples",
    )

    legend = ax.legend()
    ax._build_chart(640, 480).figure().build_payload()

    assert legend is ax.get_legend()
    assert legend._items[0]["name"] == "samples"
    assert legend._items[0]["kind"] == "bar"
    assert "width" not in legend._items[0]["style"]


def test_multiseries_histogram_legend_builds_with_per_bin_width_arrays() -> None:
    _fig, ax = plt.subplots()
    data = np.arange(18, dtype=np.float64).reshape(6, 3)
    ax.hist(
        data,
        bins=[0.0, 3.0, 9.0, 18.0],
        color=["red", "tan", "lime"],
        label=["red", "tan", "lime"],
    )
    legend = ax.legend(prop={"size": 10})

    ax._build_chart(640, 480).figure().build_payload()

    assert [item["name"] for item in legend._items] == [
        "red",
        "tan",
        "lime",
    ]
    assert all(item["kind"] == "bar" for item in legend._items)
    assert all("width" not in item["style"] for item in legend._items)


def test_hist_hatch_families_emit_visible_overlay_geometry() -> None:
    _fig, ax = plt.subplots()
    ax.hist(
        [[0.1, 0.2], [0.3, 0.4]],
        bins=[0.0, 0.5, 1.0],
        histtype="barstacked",
        hatch=["/", "O"],
    )

    factories = [entry.get("factory", entry.get("kind")) for entry in ax._entries]
    assert "segments" in factories
    assert "scatter" not in factories
    hatch_entries = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    assert {entry["kwargs"]["color"] for entry in hatch_entries} == {"black"}


def test_hist_ring_hatches_stay_inside_each_bar_rectangle() -> None:
    _fig, ax = plt.subplots()
    counts, edges, _bars = ax.hist(
        [-0.9, -0.8, -0.7, 0.1, 0.2, 0.8],
        bins=[-1.0, -0.5, 0.0, 0.5, 1.0],
        hatch="o",
    )

    hatch = next(entry for entry in ax._entries if entry.get("factory") == "segments")
    endpoint_x = np.concatenate((hatch["args"][0], hatch["args"][2]))
    endpoint_y = np.concatenate((hatch["args"][1], hatch["args"][3]))
    assert hatch["kwargs"]["color"] == "black"
    assert np.all(endpoint_y >= 0.0)
    for x_value, y_value in zip(endpoint_x, endpoint_y, strict=True):
        containing = np.flatnonzero((edges[:-1] <= x_value) & (x_value <= edges[1:]))
        assert len(containing)
        assert y_value <= np.max(counts[containing]) + 1e-12


def test_hist_per_dataset_linestyles_emit_distinct_outlines() -> None:
    _fig, ax = plt.subplots()
    ax.hist(
        [[0.1, 0.2], [0.3, 0.4]],
        bins=[0.0, 0.5, 1.0],
        fill=False,
        linestyle=["-", ":"],
        edgecolor=["green", "red"],
    )

    outlined = [
        entry
        for entry in ax._entries
        if entry.get("factory") == "segments" and entry["kwargs"].get("dash")
    ]
    assert len(outlined) == 1
    assert outlined[0]["kwargs"]["color"] == "red"


def test_horizontal_stepfilled_hist_dashes_use_segment_perimeters() -> None:
    _fig, ax = plt.subplots()

    ax.hist(
        [0.1, 0.2, 0.8, 1.3, 1.7],
        bins=[0.0, 0.5, 1.0, 2.0],
        histtype="stepfilled",
        orientation="horizontal",
        edgecolor="red",
        linestyle="--",
    )

    bars, outline = ax._entries
    assert bars["kind"] == "bar"
    assert "stroke" not in bars["kwargs"]
    assert "stroke_width" not in bars["kwargs"]
    assert outline["factory"] == "segments"
    assert outline["kwargs"]["color"] == "red"
    assert outline["kwargs"]["dash"]
    assert len(outline["args"][0]) == 12  # four perimeter segments per bin


def test_hist_negative_cumulative_runs_from_right_to_left() -> None:
    _fig, ax = plt.subplots()

    counts, edges, _bars = ax.hist([0.2, 0.4, 1.2, 2.2], bins=[0.0, 1.0, 2.0, 3.0], cumulative=-1)

    np.testing.assert_allclose(edges, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_allclose(counts, [4.0, 2.0, 1.0])


def test_boxplot_component_dashes_and_point_means_are_rendered() -> None:
    _fig, ax = plt.subplots()
    result = ax.boxplot(
        [[1.0, 2.0, 3.0, 9.0]],
        showmeans=True,
        boxprops={"linestyle": "--", "linewidth": 3.0, "color": "goldenrod"},
        meanprops={
            "marker": "D",
            "markerfacecolor": "firebrick",
            "markeredgecolor": "black",
        },
    )

    box_entry = result["boxes"][0]._entry
    assert box_entry["factory"] == "segments"
    assert len(box_entry["args"][0]) > 4
    assert result["means"][0]._entry["kind"] == "scatter"
    assert result["means"][0]._entry["kwargs"]["symbol"] == "diamond"
