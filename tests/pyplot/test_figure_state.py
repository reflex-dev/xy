from __future__ import annotations

import numpy as np
import pytest

from xy.pyplot._mplfig import Figure


def test_figure_clear_clf_removes_axes_and_chrome() -> None:
    fig = Figure(1)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [1, 2])
    fig.suptitle("title")
    fig.colorbar(ax.imshow([[1, 2], [3, 4]]), ax=[ax])

    fig.clear()

    assert fig.axes == []
    assert fig._current_ax is None
    assert fig._suptitle is None
    assert fig._shared_colorbar is None
    fresh = fig.gca()
    assert fresh.figure is fig
    assert fresh._entries == []

    fig.clf()
    assert fig.axes == []


def test_figure_sca_and_delaxes_keep_current_axes_consistent() -> None:
    fig = Figure(1)
    axes = fig.subplots(1, 3)

    assert fig.gca() is axes[-1]
    assert fig.sca(axes[0]) is axes[0]
    assert fig.gca() is axes[0]

    fig.delaxes(axes[0])

    assert axes[0].figure is None
    assert fig.gca() is axes[1]
    assert fig.axes == [axes[1], axes[2]]

    fig.delaxes(axes[2])
    assert fig.gca() is axes[1]

    with pytest.raises(ValueError, match="belong to this figure"):
        fig.delaxes(axes[0])


def test_figure_text_legend_and_super_labels_use_figure_transform() -> None:
    fig = Figure(1)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [1, 2], label="line label")

    text = fig.text(0.25, 0.75, "figure note", color="red")
    xlabel = fig.supxlabel("shared x")
    ylabel = fig.supylabel("shared y")
    fig.legend()

    assert text._entry["args"] == (0.25, 0.75, "figure note")
    assert text._entry["kwargs"]["style"]["coordinate_space"] == "figure_fraction"
    assert xlabel._entry["kwargs"]["style"]["coordinate_space"] == "figure_fraction"
    assert ylabel._entry["kwargs"]["style"]["coordinate_space"] == "figure_fraction"
    assert fig._supxlabel == "shared x"
    assert fig._supylabel == "shared y"
    assert ax._legend is True
    assert "figure note" in fig._repr_html_()


def test_figure_size_dpi_and_color_getters_setters() -> None:
    fig = Figure(1, figsize=(4, 3), dpi=120, facecolor="#112233")

    np.testing.assert_allclose(fig.get_size_inches(), np.asarray([4.0, 3.0]))
    assert fig.get_dpi() == 120.0
    assert fig.dpi == 120.0
    assert fig.get_facecolor() == "#112233"
    assert fig.get_edgecolor() == "white"

    fig.set_size_inches(5, 2)
    fig.set_dpi(80)
    fig.set_facecolor("black")
    fig.set_edgecolor("blue")

    np.testing.assert_allclose(fig.get_size_inches(), np.asarray([5.0, 2.0]))
    assert fig.dpi == 80.0
    assert fig.get_facecolor() == "black"
    assert fig.get_edgecolor() == "blue"

    fig.dpi = 96
    assert fig.get_dpi() == 96.0


def test_figure_subplots_sharing_ratios_and_squeeze() -> None:
    fig = Figure(1)

    axes = fig.subplots(
        2,
        2,
        sharex=True,
        sharey=True,
        squeeze=False,
        gridspec_kw={"width_ratios": [2, 1], "height_ratios": [1, 3]},
    )

    assert axes.shape == (2, 2)
    assert fig.axes == list(axes.ravel())
    assert fig.gca() is axes[-1, -1]
    assert fig._sharex == "all"
    assert fig._sharey == "all"
    assert fig._width_ratios == (2.0, 1.0)
    assert fig._height_ratios == (1.0, 3.0)


def test_add_gridspec_supports_single_cell_specs() -> None:
    fig = Figure(1)

    gs = fig.add_gridspec(2, 2, width_ratios=[1, 2])
    ax = fig.add_subplot(gs[1, 0])
    same = fig.add_subplot(gs[2])

    assert ax is same
    assert fig._width_ratios == (1.0, 2.0)
    assert fig.gca() is ax

    span = gs[0:2, 0]
    assert span.rows == (0, 2)
    assert span.cols == (0, 1)
    with pytest.raises(NotImplementedError):
        _ = gs[0:2:2, 0]  # step slicing stays out of the span contract
