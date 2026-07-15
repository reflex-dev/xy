"""Seaborn-shaped FacetGrid: the faceting contract that seaborn's
``FacetGrid.map`` drives through pyplot state, reproduced natively.

Corpus anchor: PDSH 04.14 ``FacetGrid(tips, row=, col=, margin_titles=True)
.map(plt.hist, ...)`` — subsetting per panel, shared domains, edge-only axis
labels, top-row column titles, and rotated right-margin row titles.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot import FacetGrid


def _tips(n: int = 120) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(7)
    return {
        "tip_pct": rng.uniform(0.0, 40.0, n),
        "sex": np.where(rng.random(n) < 0.5, "Male", "Female"),
        "time": np.where(rng.random(n) < 0.5, "Lunch", "Dinner"),
    }


def test_grid_shape_and_figsize() -> None:
    grid = FacetGrid(_tips(), row="sex", col="time")
    assert grid.axes.shape == (2, 2)
    assert grid.figure._figsize == (6.0, 6.0)  # ncol*height*aspect x nrow*height
    single = FacetGrid(_tips())
    assert single.axes.shape == (1, 1)
    assert single.ax is single.axes[0, 0]
    with pytest.raises(AttributeError):
        _ = grid.ax


def test_map_draws_each_facet_subset() -> None:
    data = _tips()
    grid = FacetGrid(data, row="sex", col="time")
    grid.map(plt.hist, "tip_pct", bins=np.linspace(0, 40, 15))
    for (row_i, col_j), ax in np.ndenumerate(grid.axes):
        mask = (data["sex"] == grid.row_names[row_i]) & (data["time"] == grid.col_names[col_j])
        counts = np.histogram(data["tip_pct"][mask], bins=np.linspace(0, 40, 15))[0]
        bars = [entry for entry in ax._entries if entry["kind"] == "bar"]
        assert len(bars) == 1
        assert np.array_equal(np.asarray(bars[0]["y"], dtype=int), counts)


def test_map_skips_empty_facets() -> None:
    data = {
        "v": np.array([1.0, 2.0, 3.0]),
        "r": np.array(["a", "a", "b"]),
        "c": np.array(["x", "y", "x"]),  # (b, y) is empty
    }
    grid = FacetGrid(data, row="r", col="c")
    grid.map(plt.hist, "v")
    drawn = {
        (i, j): bool([e for e in ax._entries if e["kind"] == "bar"])
        for (i, j), ax in np.ndenumerate(grid.axes)
    }
    assert drawn == {(0, 0): True, (0, 1): True, (1, 0): True, (1, 1): False}


def test_titles_margin_titles_and_edge_labels() -> None:
    grid = FacetGrid(_tips(), row="sex", col="time", margin_titles=True)
    grid.map(plt.hist, "tip_pct")
    top = [ax.get_title() for ax in grid.axes[0, :]]
    assert top == [f"time = {name}" for name in grid.col_names]
    assert [ax.get_title() for ax in grid.axes[1, :]] == ["", ""]
    for row_i, row_name in enumerate(grid.row_names):
        texts = [e for e in grid.axes[row_i, -1]._entries if e["kind"] == "@text"]
        assert texts, "margin title missing"
        entry = texts[-1]
        assert entry["args"][2] == f"sex = {row_name}"
        style = entry["kwargs"]["style"]
        assert style["coordinate_space"] == "axes_fraction"
        assert style["rotation"] == 270.0
        assert float(entry["args"][0]) > 1.0
    assert [ax.get_xlabel() for ax in grid.axes[-1, :]] == ["tip_pct", "tip_pct"]
    assert [ax.get_xlabel() for ax in grid.axes[0, :]] == ["", ""]


def test_combined_titles_without_margin_titles() -> None:
    grid = FacetGrid(_tips(), row="sex", col="time")
    grid.map(plt.hist, "tip_pct")
    assert grid.axes[0, 0].get_title() == f"sex = {grid.row_names[0]} | time = {grid.col_names[0]}"


def test_shared_domains_union_across_panels() -> None:
    grid = FacetGrid(_tips(), row="sex", col="time")
    grid.map(plt.hist, "tip_pct", bins=np.linspace(0, 40, 15))
    figures = [chart.figure() for chart in grid.figure._charts()]
    assert len({fig.y_range() for fig in figures}) == 1
    assert len({fig.x_range() for fig in figures}) == 1


def test_margin_title_ink_lands_right_of_the_plot() -> None:
    """The full chain: axes-fraction x>1 text reserves right padding, escapes
    the plot clip, and rasterizes rotated — ink must land in the margin."""
    from xy import _raster
    from xy._svg import layout

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.annotate(
        "sex = Male",
        xy=(1.02, 0.5),
        xycoords="axes fraction",
        rotation=270,
        ha="left",
        va="center",
    )
    chart = ax._build_chart(640, 480)
    spec, blob, borrowed = chart.figure()._build_raster_payload()
    width, _height, _compact, plot = layout(spec)
    assert width - (plot["x"] + plot["w"]) >= 30, "right margin not reserved"
    image = _raster.render_raster(spec, blob, 1.0, borrowed=borrowed)
    margin = image[:, int(plot["x"] + plot["w"]) + 2 :, :3]
    assert int((margin < 200).sum()) > 20, "no margin-title ink right of the plot"


def test_rotated_annotation_survives_svg_export() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.annotate(
        "row title",
        xy=(1.02, 0.5),
        xycoords="axes fraction",
        rotation=270,
        ha="left",
        va="center",
    )
    svg = ax._build_chart(640, 480).to_svg()
    assert "row title" in svg
    assert "rotate(90" in svg


def test_unsupported_surface_stays_loud() -> None:
    data = _tips()
    with pytest.raises(NotImplementedError):
        FacetGrid(data, col="time", hue="sex")
    with pytest.raises(NotImplementedError):
        FacetGrid(data, col="time", col_wrap=2)
    with pytest.raises(NotImplementedError):
        FacetGrid(data, col="time", subplot_kws={"xscale": "log"})
    with pytest.raises(TypeError):
        FacetGrid(data, col="time", nonsense=True)
    grid = FacetGrid(data, col="time")
    with pytest.raises(NotImplementedError):
        grid.add_legend()
    with pytest.raises(NotImplementedError):
        grid.map_dataframe(plt.hist, "tip_pct")
    with pytest.raises(TypeError):
        grid.map("not callable", "tip_pct")
    with pytest.raises(TypeError):
        grid.map(plt.hist, np.arange(3.0))
    with pytest.raises(KeyError):
        grid.map(plt.hist, "no_such_column")


def test_darkgrid_and_deep_styles_reproduce_the_seaborn_look() -> None:
    """The 04.14 corpus styles both engines with sns.set()-equivalent sheets:
    darkgrid panel + white forced patch edges + the deep color cycle."""
    plt.style.use(["seaborn-v0_8-darkgrid", "seaborn-v0_8-deep"])
    assert plt.rcParams["axes.facecolor"] == "#EAEAF2"
    assert plt.rcParams["grid.color"] == "white"
    assert plt.rcParams["patch.force_edgecolor"] is True
    fig, ax = plt.subplots()
    ax.hist(np.arange(10.0))
    entry = next(e for e in ax._entries if e["kind"] == "bar")
    assert entry["kwargs"]["stroke"] == "white"
    assert entry["kwargs"]["color"] == "#4C72B0"  # deep C0, not tab10 blue


def test_explicit_hist_edgecolor_beats_forced_patch_edges() -> None:
    plt.style.use("seaborn-v0_8-darkgrid")
    fig, ax = plt.subplots()
    ax.hist(np.arange(10.0), edgecolor="black")
    entry = next(e for e in ax._entries if e["kind"] == "bar")
    assert entry["kwargs"]["stroke"] == "black"


def test_explicit_orders_and_row_only_grid() -> None:
    data = _tips()
    grid = FacetGrid(data, row="sex", row_order=["Female", "Male"])
    assert grid.axes.shape == (2, 1)
    assert grid.row_names == ["Female", "Male"]
    grid.map(plt.hist, "tip_pct")
    assert grid.axes[0, 0].get_title() == "sex = Female"
