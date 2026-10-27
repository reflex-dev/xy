from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as plt
from xy._figure import Figure


def teardown_function() -> None:
    plt.close("all")


def test_default_boxplot_has_matplotlib_component_cardinalities_and_geometry() -> None:
    _fig, ax = plt.subplots()
    result = ax.boxplot(
        [[0.0, 0.0, 0.0, 0.0, 10.0], [1.0, 1.0, 1.0, 1.0, 20.0]],
        showmeans=True,
    )

    assert {name: len(artists) for name, artists in result.items()} == {
        "whiskers": 4,
        "caps": 4,
        "boxes": 2,
        "medians": 2,
        "fliers": 2,
        "means": 2,
    }
    assert all(artist._entry["factory"] == "segments" for artist in result["boxes"])
    assert all(artist._entry["kwargs"]["color"] == "black" for artist in result["boxes"])
    assert all(artist._entry["kwargs"]["color"] == "#ff7f0e" for artist in result["medians"])

    # Two positions use Matplotlib's clipped 0.15 default box width.
    first_box_x = np.concatenate(
        (result["boxes"][0]._entry["args"][0], result["boxes"][0]._entry["args"][2])
    )
    np.testing.assert_allclose([first_box_x.min(), first_box_x.max()], [0.925, 1.075])
    np.testing.assert_allclose(result["fliers"][0]._entry["x"], [1.0])
    np.testing.assert_allclose(result["fliers"][1]._entry["x"], [2.0])


def test_default_boxplot_returns_one_empty_flier_handle_per_group() -> None:
    _fig, ax = plt.subplots()
    result = ax.boxplot([[1.0, 2.0, 3.0], [2.0, 4.0, 8.0]])

    assert len(result["fliers"]) == 2
    assert all(len(artist._entry["x"]) == 0 for artist in result["fliers"])


def test_patch_boxplot_returns_mutable_filled_boxes_with_labels() -> None:
    _fig, ax = plt.subplots()
    result = ax.bxp(
        [
            {
                "med": 2.0,
                "q1": 1.0,
                "q3": 3.0,
                "whislo": 0.0,
                "whishi": 4.0,
                "fliers": [],
                "label": "A",
            },
            {
                "med": 3.0,
                "q1": 2.0,
                "q3": 4.0,
                "whislo": 1.0,
                "whishi": 5.0,
                "fliers": [],
                "label": "B",
            },
        ],
        patch_artist=True,
        boxprops={"facecolor": "bisque", "edgecolor": "navy", "linewidth": 2.0},
        label=["first", "second"],
    )

    assert [box._entry["factory"] for box in result["boxes"]] == [
        "triangle_mesh",
        "triangle_mesh",
    ]
    assert all(box._entry["kwargs"]["color"] == "bisque" for box in result["boxes"])
    assert all(box._entry["kwargs"]["stroke"] == "navy" for box in result["boxes"])
    assert ax._axis_props("x")["tick_labels"] == ["A", "B"]
    assert ax.get_legend_handles_labels()[1] == ["first", "second"]

    first = result["boxes"][0]
    first.set_facecolor("tomato")
    first.set_edgecolor("black")
    first.set_linewidth(3.0)
    np.testing.assert_allclose(first.get_facecolor(), [[1.0, 99 / 255, 71 / 255, 1.0]])
    np.testing.assert_allclose(first.get_edgecolor(), [[0.0, 0.0, 0.0, 1.0]])
    np.testing.assert_array_equal(first.get_linewidth(), [3.0])


def test_boxplot_patch_mutation_matches_custom_fill_gallery_idiom() -> None:
    _fig, ax = plt.subplots()
    result = ax.boxplot(
        [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]],
        patch_artist=True,
        tick_labels=["peaches", "oranges"],
    )

    for patch, color in zip(result["boxes"], ["peachpuff", "orange"], strict=True):
        patch.set_facecolor(color)

    assert [patch._entry["kwargs"]["color"] for patch in result["boxes"]] == [
        "rgba(255,218,185,1)",
        "rgba(255,165,0,1)",
    ]
    assert ax._axis_props("x")["tick_labels"] == ["peaches", "oranges"]


@pytest.mark.parametrize(
    ("bw_method", "factor"),
    [
        (None, 5 ** (-1 / 5)),
        ("scott", 5 ** (-1 / 5)),
        ("silverman", (5 * 3 / 4) ** (-1 / 5)),
        (0.5, 0.5),
    ],
)
def test_violinplot_uses_gaussian_kde_for_supported_bandwidths(
    bw_method: str | float | None, factor: float
) -> None:
    values = np.asarray([0.0, 0.25, 1.0, 2.0, 4.0])
    _fig, ax = plt.subplots()
    result = ax.violinplot([values], points=31, bw_method=bw_method, showextrema=False)

    assert len(result["bodies"]) == 1
    body = result["bodies"][0]._entry
    assert body["factory"] == "triangle_mesh"
    assert body["kwargs"]["_joined_fill"] is True
    assert body["kwargs"]["opacity"] == pytest.approx(0.3)

    coords = np.linspace(values.min(), values.max(), 31)
    bandwidth = np.std(values, ddof=1) * factor
    delta = (coords[:, None] - values[None, :]) / bandwidth
    density = np.mean(np.exp(-0.5 * delta * delta), axis=1) / (bandwidth * np.sqrt(2 * np.pi))
    target = 11
    target_x = np.concatenate(
        [
            np.asarray(x)[np.isclose(y, coords[target])]
            for x, y in zip(body["args"][::2], body["args"][1::2], strict=True)
        ]
    )
    expected_half_width = density[target] / density.max() * 0.25
    np.testing.assert_allclose(
        [target_x.min(), target_x.max()],
        [1.0 - expected_half_width, 1.0 + expected_half_width],
    )


def test_violinplot_returns_one_joined_body_per_group_and_renders() -> None:
    fig, ax = plt.subplots(figsize=(4, 3))
    result = ax.violinplot(
        [[0.0, 0.5, 1.0, 2.0], [1.0, 2.0, 4.0, 8.0]],
        showmedians=True,
    )

    assert len(result["bodies"]) == 2
    traces = ax._build_chart(400, 300).figure().traces
    body_traces = [trace for trace in traces if trace.kind == "triangle_mesh"]
    assert len(body_traces) == 2
    assert all(trace.style["joined_fill"] is True for trace in body_traces)

    pixels = np.asarray(plt.imread(BytesIO(fig._to_png())))
    assert pixels.shape[:2] == (300, 400)
    assert np.count_nonzero(np.any(pixels[..., :3] < 242, axis=-1)) > 500


def test_violinplot_cycles_explicit_colors_and_returns_mutable_bodies() -> None:
    _fig, ax = plt.subplots()
    result = ax.violinplot(
        [
            [0.0, 1.0, 2.0],
            [1.0, 2.0, 4.0],
            [2.0, 3.0, 5.0],
        ],
        facecolor=[("yellow", 0.3), ("blue", 0.4)],
        linecolor=["black", "red"],
    )

    assert [body._entry["kwargs"]["color"] for body in result["bodies"]] == [
        "rgba(255,255,0,0.3)",
        "rgba(0,0,255,0.4)",
        "rgba(255,255,0,0.3)",
    ]
    assert all(body._entry["kwargs"]["opacity"] == 1.0 for body in result["bodies"])
    assert result["cmins"]._entry["kwargs"]["color"] == ["black", "red", "black"]

    body = result["bodies"][0]
    body.set_edgecolor("black")
    body.set_linewidth(1.5)
    body.set_alpha(0.8)
    assert body._entry["kwargs"]["stroke"] == "rgba(0,0,0,1)"
    assert body._entry["kwargs"]["stroke_width"] == pytest.approx(1.5)
    assert body._entry["kwargs"]["opacity"] == pytest.approx(0.8)


def test_default_violin_body_keeps_artist_alpha_after_facecolor_mutation() -> None:
    _fig, ax = plt.subplots()
    body = ax.violinplot([[0.0, 1.0, 2.0]])["bodies"][0]

    body.set_facecolor("red")

    assert body._entry["kwargs"]["color"] == "rgba(255,0,0,1)"
    assert body._entry["kwargs"]["opacity"] == pytest.approx(0.3)


def test_native_core_box_and_violin_marks_keep_their_fast_paths() -> None:
    figure = Figure()
    figure.box([[1.0, 2.0, 3.0], [2.0, 4.0, 8.0]])
    figure.violin([[1.0, 2.0, 3.0], [2.0, 4.0, 8.0]])

    assert [trace.kind for trace in figure.traces] == [
        "box_whisker",
        "box",
        "box_median",
        "violin",
    ]
