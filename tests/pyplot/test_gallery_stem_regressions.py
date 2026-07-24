"""Regressions reduced from Matplotlib's ``stem_plot`` gallery example."""

from __future__ import annotations

import numpy as np

import xy.pyplot as plt


def test_stem_contributes_tip_and_baseline_to_autoscale() -> None:
    x = np.linspace(0.1, 2 * np.pi, 41)
    y = np.exp(np.sin(x))
    _fig, ax = plt.subplots()

    ax.stem(x, y, bottom=0.0)

    assert not ax._axis_is_dataless("x")
    assert not ax._axis_is_dataless("y")
    np.testing.assert_allclose(ax._entry_extent("x"), (x.min(), x.max()))
    np.testing.assert_allclose(ax._entry_extent("y"), (0.0, y.max()))


def test_stem_nonzero_bottom_is_part_of_the_value_extent() -> None:
    _fig, ax = plt.subplots()

    markerline, stemlines, baseline = ax.stem([1.0, 2.0], [1.5, 1.8], bottom=1.1)

    np.testing.assert_allclose(ax._entry_extent("x"), (1.0, 2.0))
    np.testing.assert_allclose(ax._entry_extent("y"), (1.1, 1.8))
    assert markerline is not stemlines
    assert baseline is not stemlines
    np.testing.assert_allclose(baseline.get_xdata(), (1.0, 2.0))
    np.testing.assert_allclose(baseline.get_ydata(), (1.1, 1.1))
    assert baseline.get_color() == "#d62728"


def test_stem_marker_face_mutation_does_not_recolor_stems() -> None:
    _fig, ax = plt.subplots()
    markerline, stemlines, _baseline = ax.stem(
        [1.0, 2.0],
        [1.5, 1.8],
        linefmt="grey",
        markerfmt="D",
    )

    markerline.set_markerfacecolor("none")

    assert markerline._entry["kwargs"]["color"] == "transparent"
    assert markerline._entry["kwargs"]["stroke"] == "grey"
    assert stemlines._entry["kwargs"]["color"] == "grey"


def test_stem_basefmt_controls_the_independent_baseline() -> None:
    _fig, ax = plt.subplots()

    _markerline, _stemlines, baseline = ax.stem(
        [1.0, 2.0],
        [1.5, 1.8],
        basefmt="k-",
    )

    assert baseline.get_color() == "#000000"
