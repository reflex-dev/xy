"""Regressions reduced from Matplotlib's layout gallery examples."""

from __future__ import annotations

from io import BytesIO

import numpy as np

import xy.pyplot as plt
from xy.pyplot._grid import _composite_rgba


def test_set_aspect_accepts_positional_adjustable() -> None:
    _fig, ax = plt.subplots()
    ax.plot([-3.0, 3.0], [-3.0, 3.0])

    ax.set_aspect("equal", "box")

    assert ax._aspect_equal is True
    assert ax._aspect_adjustable == "box"


def test_uniform_subplot_axes_expose_one_shared_gridspec() -> None:
    fig, axes = plt.subplots(nrows=3, ncols=3)

    gridspec = axes[1, 2].get_gridspec()

    assert gridspec is axes[0, 0].get_gridspec()
    assert gridspec is axes[2, 2].get_gridspec()
    assert gridspec.nrows == 3
    assert gridspec.ncols == 3
    assert axes[1, 2].get_subplotspec().rows == (1, 2)
    assert axes[1, 2].get_subplotspec().cols == (2, 3)

    for ax in axes[1:, -1]:
        ax.remove()
    spanning = fig.add_subplot(gridspec[1:, -1])

    assert spanning.get_gridspec() is gridspec
    assert spanning.get_subplotspec().rows == (1, 3)
    assert spanning.get_subplotspec().cols == (2, 3)
    assert (fig._nrows, fig._ncols) == (3, 3)


def test_absolute_subplot_composition_preserves_neighboring_spines() -> None:
    fig, _axes = plt.subplots(nrows=1, ncols=2, figsize=(6.4, 4.8))
    output = BytesIO()

    fig.savefig(output, dpi=100, format="png")
    output.seek(0)

    pixels = np.asarray(plt.imread(output))
    left_rect = fig._effective_rects()[0]
    scale = 2
    right = round((left_rect[0] + left_rect[2]) * 640 * scale)
    top = round((1.0 - left_rect[1] - left_rect[3]) * 480 * scale)
    bottom = round((1.0 - left_rect[1]) * 480 * scale)
    spine_strip = pixels[top:bottom, right - 2 : right + 3, :3]
    dark_by_column = np.all(spine_strip < 64, axis=2).sum(axis=0)

    assert dark_by_column.max() > 0.9 * (bottom - top)


def test_tight_layout_reserves_subplot_tick_chrome() -> None:
    fig, axes = plt.subplots(nrows=3, ncols=3, figsize=(6.4, 4.8))
    axes[1, 2].get_gridspec()

    fig.tight_layout()

    first = axes[0, 0]._figure_rect
    second = axes[0, 1]._figure_rect
    below = axes[1, 0]._figure_rect
    assert first is not None and second is not None and below is not None
    horizontal_gap = (second[0] - first[0] - first[2]) * 640
    vertical_gap = (first[1] - below[1] - below[3]) * 480
    assert horizontal_gap >= 57
    assert vertical_gap >= 43


def test_rgba_compositor_preserves_transparent_chrome() -> None:
    destination = np.array(
        [[[255, 255, 255, 255], [0, 0, 255, 255]]],
        dtype=np.uint8,
    )
    source = np.array(
        [[[0, 0, 0, 0], [255, 0, 0, 128]]],
        dtype=np.uint8,
    )

    _composite_rgba(destination, source)

    np.testing.assert_array_equal(destination[0, 0], [255, 255, 255, 255])
    np.testing.assert_array_equal(destination[0, 1], [128, 0, 127, 255])
