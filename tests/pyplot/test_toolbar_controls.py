"""Interactive modebar controls: off by default (Matplotlib's inline backend
shows no toolbar), opt-in via the figure/subplots ``toolbar`` kwarg or
``rcParams["toolbar"]``; dense grids size the notebook iframe to real content."""

from __future__ import annotations

import numpy as np

import xy.pyplot as plt


def _spec(ax):
    spec, _blob = ax._build_chart(640, 480).figure().build_payload()
    return spec


def test_controls_hidden_by_default_for_plot_subplots_and_imshow() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    assert _spec(ax).get("show_modebar", True) is False

    plt.close("all")
    _fig, axes = plt.subplots(2, 2)
    axes[0, 0].imshow(np.zeros((4, 4)))
    assert all(_spec(axi).get("show_modebar", True) is False for axi in axes.ravel())


def test_toolbar_kwarg_enables_controls() -> None:
    _fig, ax = plt.subplots(toolbar=True)
    ax.plot([0, 1], [0, 1])
    assert "show_modebar" not in _spec(ax)  # spec omits the True default

    plt.close("all")
    fig = plt.figure(toolbar=True)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [0, 1])
    assert "show_modebar" not in _spec(ax)


def test_rc_toolbar_enables_controls_and_kwarg_wins_over_rc() -> None:
    plt.rcParams["toolbar"] = "toolbar2"
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    assert "show_modebar" not in _spec(ax)

    plt.close("all")
    _fig, ax = plt.subplots(toolbar=False)  # kwarg overrides the rc opt-in
    ax.plot([0, 1], [0, 1])
    assert _spec(ax).get("show_modebar", True) is False


def test_notebook_iframe_matches_figsize_for_dense_grids() -> None:
    fig, axes = plt.subplots(8, 8, figsize=(6, 6))
    for axi in axes.ravel():
        axi.imshow(np.zeros((8, 8)), cmap="binary")
        axi.set(xticks=[], yticks=[])
    _doc, width, height = fig._to_notebook_html()
    # Multi-panel grids place plot boxes at their matplotlib gridspec rects on
    # a figsize canvas — the old CSS-grid path floored panels at 120 px and
    # blew this figure up to ~1000 px of scrollbars.
    assert (width, height) == (600, 600)


def test_notebook_iframe_matches_figsize_with_suptitle() -> None:
    fig, _axes = plt.subplots(2, 3, figsize=(6, 4))
    fig.suptitle("grid")
    _doc, width, height = fig._to_notebook_html()
    assert (width, height) == (600, 400)
