"""Regressions reduced from Matplotlib's layout gallery examples."""

from __future__ import annotations

import xy.pyplot as plt


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
