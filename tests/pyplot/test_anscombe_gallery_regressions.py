"""State and layout contracts exercised by Matplotlib's Anscombe example."""

from __future__ import annotations

import pytest

from xy import pyplot as plt


def test_anscombe_gridspec_spacing_reaches_subplot_rects() -> None:
    _fig, axes = plt.subplots(
        2,
        2,
        figsize=(6, 6),
        gridspec_kw={"wspace": 0.08, "hspace": 0.08},
    )

    # Matplotlib 3.11's GridSpec uses 0.08 of the average cell width/height.
    # These are its exact SubplotParams-default rectangles for a 2 x 2 grid.
    expected = (
        (0.125, 0.5098076923, 0.3725961538, 0.3701923077),
        (0.5274038462, 0.5098076923, 0.3725961538, 0.3701923077),
        (0.125, 0.11, 0.3725961538, 0.3701923077),
        (0.5274038462, 0.11, 0.3725961538, 0.3701923077),
    )

    for ax, bounds in zip(axes.flat, expected, strict=True):
        assert ax.get_position().bounds == pytest.approx(bounds)


def test_anscombe_shared_source_ticks_and_limits_reach_every_panel() -> None:
    fig, axes = plt.subplots(2, 2, sharex=True, sharey=True, figsize=(6, 6))
    source = axes[0, 0]
    source.set(xlim=(0, 20), ylim=(2, 14))
    source.set(xticks=(0, 10, 20), yticks=(4, 8, 12))
    assert all(source.get_shared_x_axes().joined(source, ax) for ax in axes.flat)
    assert all(source.get_shared_y_axes().joined(source, ax) for ax in axes.flat)

    for index, ax in enumerate(axes.flat):
        ax.plot([4, 8, 13], [4 + index, 8, 10], "o")
        assert ax.get_xlim() == pytest.approx((0, 20))
        assert ax.get_xticks() == pytest.approx((0, 10, 20))
        assert ax.get_ylim() == pytest.approx((2, 14))
        assert ax.get_yticks() == pytest.approx((4, 8, 12))

    figures = [chart.figure() for chart in fig._charts()]
    for figure in figures:
        assert figure.axis_options["x"]["domain"] == pytest.approx((0, 20))
        assert figure.axis_options["x"]["tick_values"] == pytest.approx((0, 10, 20))
        assert figure.axis_options["y"]["domain"] == pytest.approx((2, 14))
        assert figure.axis_options["y"]["tick_values"] == pytest.approx((4, 8, 12))

    # Ticker state is shared, but Matplotlib keeps edge-label visibility local.
    assert [figure.axis_options["x"]["tick_label_strategy"] for figure in figures] == [
        "off",
        "off",
        "preserve",
        "preserve",
    ]
    assert [figure.axis_options["y"]["tick_label_strategy"] for figure in figures] == [
        "preserve",
        "off",
        "preserve",
        "off",
    ]


def test_shared_source_locator_is_reused_and_invalidates_linked_charts() -> None:
    fig, axes = plt.subplots(2, 2, sharex=True, sharey=True)
    source = axes[0, 0]
    source.set(xlim=(0, 20), ylim=(2, 14))
    source.xaxis.set_major_locator(plt.FixedLocator([0, 10, 20]))
    source.yaxis.set_major_locator(plt.FixedLocator([4, 8, 12]))
    for index, ax in enumerate(axes.flat):
        ax.plot([4, 13], [4 + index, 10])

    initial = fig._charts()
    assert all(ax.xaxis.get_major_locator() is source.xaxis.get_major_locator() for ax in axes.flat)
    assert all(
        chart.figure().axis_options["x"]["tick_values"] == pytest.approx((0, 10, 20))
        for chart in initial
    )

    source.xaxis.set_major_locator(plt.FixedLocator([0, 5, 10, 15, 20]))
    rebuilt = fig._charts()
    assert all(before is not after for before, after in zip(initial, rebuilt, strict=True))
    assert all(
        chart.figure().axis_options["x"]["tick_values"] == pytest.approx((0, 5, 10, 15, 20))
        for chart in rebuilt
    )
