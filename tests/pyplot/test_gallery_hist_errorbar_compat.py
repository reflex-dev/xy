from __future__ import annotations

import re
from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as plt


def test_hist_patch_styles_apply_per_dataset() -> None:
    _fig, ax = plt.subplots()
    values = np.arange(18.0).reshape(6, 3)

    _counts, _edges, containers = ax.hist(
        values,
        bins=3,
        facecolor=["red", "green", "blue"],
        edgecolor=["black", "gray", "white"],
        linewidth=[1, 2, 3],
    )

    assert len(containers) == 3
    assert [entry["kwargs"]["stroke_width"] for entry in ax._entries] == [1.0, 2.0, 3.0]
    assert [entry["kwargs"]["color"] for entry in ax._entries] == [
        "red",
        "green",
        "blue",
    ]


def test_hist_fill_false_is_unfilled_and_scalar_input_is_one_dataset() -> None:
    _fig, ax = plt.subplots()

    counts, _edges, container = ax.hist(
        2.0, bins=2, fill=False, facecolor="red", edgecolor="blue", linewidth=3
    )

    assert counts.shape == (2,)
    assert len(container) == 2
    entry = ax._entries[-1]
    assert entry["kwargs"]["color"] == "transparent"
    assert entry["kwargs"]["stroke"] == "blue"
    assert entry["kwargs"]["stroke_width"] == 3.0


def test_hist_default_patch_edge_is_transparent_like_matplotlib() -> None:
    _fig, ax = plt.subplots()

    ax.hist([0.0, 1.0, 2.0], bins=2)

    kwargs = ax._entries[-1]["kwargs"]
    assert "stroke" not in kwargs
    assert "stroke_width" not in kwargs


def test_dense_histogram_remains_visible_on_dark_absolute_inset() -> None:
    rng = np.random.default_rng(19680801)
    fig, main_ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    main_ax.plot([0.0, 1.0], [0.0, 1.0])
    inset = fig.add_axes((0.65, 0.6, 0.2, 0.2), facecolor="black")
    inset.hist(rng.normal(size=10_000), 400, density=True)
    inset.set(xticks=[], yticks=[])

    pixels = np.asarray(plt.imread(BytesIO(fig._to_png())))
    crop = pixels[96:192, 416:544, :3]
    blue = (crop[:, :, 2] > crop[:, :, 0] + 0.2) & (crop[:, :, 2] > crop[:, :, 1] + 0.1)
    assert np.count_nonzero(blue) > 100

    output = BytesIO()
    fig.savefig(output, format="svg")
    histogram_rects = re.findall(
        r'<rect[^>]+fill="rgb\(31,119,180\)"[^>]*/>',
        output.getvalue().decode(),
    )
    assert len(histogram_rects) == 400
    assert all("stroke=" not in rect for rect in histogram_rects)


def test_hist_step_fill_and_linewidth_override_histtype_defaults() -> None:
    _fig, ax = plt.subplots()
    ax.hist([0, 1, 2], bins=2, histtype="step", fill=True, facecolor="green", linewidth=4)
    ax.hist([0, 1, 2], bins=2, histtype="stepfilled", fill=False, linewidth=5)

    filled, connectors, unfilled = ax._entries
    assert filled["factory"] == "area"
    assert filled["kwargs"]["color"] == "green"
    assert filled["kwargs"]["line_color"] == "#1f77b4"
    assert connectors["factory"] == "segments"
    assert connectors["kwargs"].get("name") is None
    assert unfilled["factory"] == "stairs"
    assert unfilled["kwargs"]["color"] == "black"
    assert unfilled["kwargs"]["width"] == 5.0


def test_hist_step_outline_connects_to_baseline_in_both_orientations() -> None:
    _fig, (vertical_ax, horizontal_ax) = plt.subplots(1, 2)
    data = [0.2, 0.4, 1.2, 1.4, 1.6]
    bins = [0.0, 1.0, 2.0]

    vertical_counts, vertical_edges, _ = vertical_ax.hist(data, bins=bins, histtype="step")
    horizontal_counts, horizontal_edges, _ = horizontal_ax.hist(
        data,
        bins=bins,
        histtype="step",
        orientation="horizontal",
    )

    connectors, stairs = vertical_ax._entries
    assert connectors["factory"] == "segments"
    assert stairs["factory"] == "stairs"
    x0, y0, x1, y1 = connectors["args"]
    np.testing.assert_allclose(x0, [vertical_edges[0], vertical_edges[-1]])
    np.testing.assert_allclose(x1, [vertical_edges[0], vertical_edges[-1]])
    np.testing.assert_allclose(y0, [0.0, vertical_counts[-1]])
    np.testing.assert_allclose(y1, [vertical_counts[0], 0.0])

    (outline,) = horizontal_ax._entries
    assert outline["factory"] == "segments"
    x0, y0, x1, y1 = outline["args"]
    assert (x0[0], y0[0]) == pytest.approx((0.0, horizontal_edges[0]))
    assert (x1[0], y1[0]) == pytest.approx((horizontal_counts[0], horizontal_edges[0]))
    assert (x0[-1], y0[-1]) == pytest.approx((horizontal_counts[-1], horizontal_edges[-1]))
    assert (x1[-1], y1[-1]) == pytest.approx((0.0, horizontal_edges[-1]))


def test_stacked_hist_step_outline_connects_to_previous_stack() -> None:
    _fig, ax = plt.subplots()
    datasets = [[0.2, 0.4, 1.2], [0.3, 1.3, 1.5]]

    counts, edges, _ = ax.hist(
        datasets,
        bins=[0.0, 1.0, 2.0],
        histtype="step",
        stacked=True,
    )

    # Matplotlib inserts stacked step artists from the top dataset downward,
    # then restores only the returned container list to dataset order. Keep
    # this geometry assertion independent of that renderer insertion order.
    connectors = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    assert len(connectors) == 2
    actual = []
    for connector in connectors:
        x0, y0, x1, y1 = connector["args"]
        np.testing.assert_allclose(x0, [edges[0], edges[-1]])
        np.testing.assert_allclose(x1, [edges[0], edges[-1]])
        actual.append((tuple(y0), tuple(y1)))
    expected = [
        ((0.0, counts[0, -1]), (counts[0, 0], 0.0)),
        ((counts[0, 0], counts[1, -1]), (counts[1, 0], counts[0, -1])),
    ]
    assert sorted(actual) == sorted(expected)


def test_hist_dataset_style_lengths_must_match_dataset_count() -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(ValueError, match="sequence must have length 2"):
        ax.hist([[0, 1], [2, 3]], bins=2, linewidth=[1, 2, 3])


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("first", ["first", None]),
        (["first"], ["first", None]),
        (["first", "second"], ["first", "second"]),
        (["first", "second", "unused"], ["first", "second"]),
        (None, [None, None]),
    ],
)
def test_hist_labels_are_padded_or_truncated_like_matplotlib(
    label: object, expected: list[str | None]
) -> None:
    _fig, ax = plt.subplots()

    _counts, _edges, containers = ax.hist(
        [[0, 1], [2, 3]],
        bins=2,
        label=label,
    )

    assert [container.get_label() for container in containers] == expected


@pytest.mark.parametrize("histtype", ["step", "stepfilled"])
def test_hist_step_geometry_contributes_to_autoscale(histtype: str) -> None:
    _fig, ax = plt.subplots()

    counts, edges, _container = ax.hist(
        [-3.0, -1.0, -0.5, 0.0, 0.5, 1.0, 3.0],
        bins=np.arange(-4.0, 4.1, 0.5),
        histtype=histtype,
        weights=np.full(7, 1 / 7),
    )

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    assert ax._entry_extent("x") == pytest.approx((edges[0], edges[-1]))
    assert ax._entry_extent("y") == pytest.approx((0.0, counts.max()))

    core = ax._build_chart(350, 300).figure()
    # Matplotlib's default axes.xmargin is 5% of the eight-unit data span.
    assert core.x_range() == pytest.approx((-4.4, 4.4))
    assert core.y_range()[1] > counts.max()


def test_hist_density_and_probability_weights_match_numpy() -> None:
    values = np.array([-2.2, -1.8, -0.4, -0.1, 0.2, 0.7, 1.1, 2.4])
    edges = np.array([-3.0, -1.0, 0.0, 0.5, 1.5, 3.0])
    _fig, (density_ax, weights_ax) = plt.subplots(1, 2)

    density, returned_edges, _ = density_ax.hist(values, bins=edges, density=True, histtype="step")
    weighted, _, _ = weights_ax.hist(
        values,
        bins=edges,
        weights=np.full(len(values), 1 / len(values)),
        histtype="step",
    )

    expected_density, expected_edges = np.histogram(values, bins=edges, density=True)
    expected_weighted, _ = np.histogram(
        values, bins=edges, weights=np.full(len(values), 1 / len(values))
    )
    np.testing.assert_allclose(density, expected_density)
    np.testing.assert_array_equal(returned_edges, expected_edges)
    np.testing.assert_allclose(weighted, expected_weighted)
    assert np.sum(density * np.diff(edges)) == pytest.approx(1.0)
    assert weighted.sum() == pytest.approx(1.0)


def test_errorbar_forwards_marker_size_and_linestyle_to_data_line_only() -> None:
    _fig, ax = plt.subplots()
    container = ax.errorbar(
        [0, 1],
        [1, 2],
        yerr=0.1,
        marker="o",
        markersize=8,
        linestyle="dotted",
    )

    assert container.lines[0] is not None
    assert [entry["kind"] for entry in ax._entries] == ["@mark", "line", "scatter"]
    line, markers = ax._entries[1:]
    assert line["kwargs"]["dash"]
    assert markers["kwargs"]["symbol"] == "circle"
    assert markers["kwargs"]["size"] > 8


def test_errorbar_fmt_none_accepts_marker_keywords_without_data_line() -> None:
    _fig, ax = plt.subplots()
    container = ax.errorbar([0, 1], [1, 2], yerr=0.1, fmt="none", marker="o", markersize=8)

    assert container.lines[0] is None
    assert len(ax._entries) == 1


def test_errorbar_uses_matplotlib_default_caps_width_and_limit_marker_size() -> None:
    _fig, ax = plt.subplots()
    ax.errorbar([1], [3], yerr=[0.5], lolims=True, fmt="none")

    errorbar, marker = ax._entries
    assert errorbar["kwargs"]["cap_size"] == plt.rcParams["errorbar.capsize"] == 0.0
    assert errorbar["kwargs"]["width"] == plt.rcParams["lines.linewidth"] == 1.5
    assert marker["kwargs"]["size"] == pytest.approx(
        plt.rcParams["lines.markersize"] * plt.rcParams["figure.dpi"] / 72.0
    )


def test_errorbar_limit_flags_render_directional_endpoint_markers() -> None:
    _fig, ax = plt.subplots()
    ax.errorbar(
        [1, 2],
        [3, 4],
        xerr=[0.2, 0.4],
        yerr=[0.5, 0.6],
        lolims=[True, False],
        uplims=[False, True],
        xlolims=[False, True],
        xuplims=[True, False],
        fmt="none",
    )

    marker_entries = [entry for entry in ax._entries if entry["kind"] == "scatter"]
    assert {entry["kwargs"]["symbol"] for entry in marker_entries} == {
        "triangle",
        "triangle_down",
        "triangle_left",
        "triangle_right",
    }
    points = {
        entry["kwargs"]["symbol"]: (
            np.asarray(entry["x"]).tolist(),
            np.asarray(entry["y"]).tolist(),
        )
        for entry in marker_entries
    }
    assert points["triangle"] == ([1], [3.5])
    assert points["triangle_down"] == ([2], [3.4])
    assert points["triangle_right"] == ([2.4], [4])
    assert points["triangle_left"] == ([0.8], [3])
