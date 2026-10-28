"""Stateful pyplot compatibility behavior without optional Matplotlib."""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as xyplt


def test_limit_helpers_accept_matplotlib_bound_aliases() -> None:
    _fig, ax = xyplt.subplots()
    ax.plot([0.0, 10.0], [0.0, 10.0])

    assert xyplt.xlim(xmin=1.0, xmax=8.0) == (1.0, 8.0)
    assert xyplt.xlim(xmin=2.0) == (2.0, 8.0)
    assert xyplt.ylim(ymin=3.0, ymax=9.0) == (3.0, 9.0)
    assert xyplt.ylim(ymax=7.0) == (3.0, 7.0)
    with pytest.raises(TypeError, match="both 'left' and 'xmin'"):
        xyplt.xlim(left=0.0, xmin=1.0)
    with pytest.raises(TypeError, match="both 'bottom' and 'ymin'"):
        xyplt.ylim(bottom=0.0, ymin=1.0)
    with pytest.raises(TypeError, match="limit pair"):
        xyplt.xlim((0.0, 1.0), xmax=2.0)
    with pytest.raises(TypeError, match="limit pair"):
        xyplt.xlim((0.0, 1.0), right=2.0)
    with pytest.raises(TypeError, match="limit pair"):
        xyplt.ylim((0.0, 1.0), ymax=2.0)
    with pytest.raises(TypeError, match="limit pair"):
        xyplt.ylim((0.0, 1.0), top=2.0)
    assert ax.get_xlim() == (2.0, 8.0)
    assert ax.get_ylim() == (3.0, 7.0)


def test_minor_tick_setter_returns_current_minor_ticks_not_major_ticks() -> None:
    _fig, ax = xyplt.subplots()
    ax.plot([0.0, 10.0], [0.0, 10.0])
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 10.0)
    ax.minorticks_on()
    major_x = ax.get_xticks().copy()
    major_y = ax.get_yticks().copy()
    minor_x = ax.get_xticks(minor=True).copy()
    minor_y = ax.get_yticks(minor=True).copy()
    assert minor_x.size > 0
    assert minor_y.size > 0

    xlocations, xlabels = xyplt.xticks([2.5, 7.5], minor=True)
    ylocations, ylabels = xyplt.yticks([2.5, 7.5], minor=True)

    np.testing.assert_array_equal(xlocations, minor_x)
    np.testing.assert_array_equal(ylocations, minor_y)
    np.testing.assert_array_equal(ax.get_xticks(), major_x)
    np.testing.assert_array_equal(ax.get_yticks(), major_y)
    assert xlabels == ax.xaxis.get_minorticklabels()
    assert ylabels == ax.yaxis.get_minorticklabels()


@pytest.mark.parametrize("figsize", [(2.5, 2.5), (5.0, 3.0)])
def test_minor_tick_getters_match_rendered_locations_at_figure_size(
    figsize: tuple[float, float],
) -> None:
    fig, ax = xyplt.subplots(figsize=figsize)
    ax.plot([0.0, 10.0], [0.0, 10.0])
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 10.0)
    ax.minorticks_on()

    for size in (figsize, (3.0, 2.0)):
        fig.set_size_inches(size)
        # Query before each build: the getter must use the current dimensions,
        # including after a prior render cached a different locator hint.
        x_minor = ax.get_xticks(minor=True)
        y_minor = ax.get_yticks(minor=True)
        spec = fig._charts()[0].figure().build_payload_split()[0]

        np.testing.assert_array_equal(x_minor, spec["x_axis"]["minor_tick_values"])
        np.testing.assert_array_equal(y_minor, spec["y_axis"]["minor_tick_values"])


def test_minor_tick_getters_support_inset_freeform_and_twin_axes() -> None:
    fig, ax = xyplt.subplots(figsize=(3.0, 2.0))
    inset = ax.inset_axes((0.1, 0.1, 0.4, 0.4))
    inset.plot([0.0, 1.0], [0.0, 1.0])
    inset.set_xlim(0.0, 10.0)
    inset.xaxis.set_major_locator(xyplt.MultipleLocator(2.0))
    inset.xaxis.set_minor_locator(xyplt.MultipleLocator(1.0))
    np.testing.assert_array_equal(inset.get_xticks(minor=True), [1.0, 3.0, 5.0, 7.0, 9.0])

    freeform = fig.add_axes((0.1, 0.1, 0.3, 0.3))
    freeform.plot([0.0, 1.0], [0.0, 1.0])
    freeform.set_ylim(0.0, 10.0)
    freeform.yaxis.set_major_locator(xyplt.MultipleLocator(2.0))
    freeform.yaxis.set_minor_locator(xyplt.MultipleLocator(1.0))
    np.testing.assert_array_equal(freeform.get_yticks(minor=True), [1.0, 3.0, 5.0, 7.0, 9.0])

    twin = ax.twinx()
    twin.set_ylim(0.0, 10.0)
    twin.yaxis.set_major_locator(xyplt.MultipleLocator(2.0))
    twin.yaxis.set_minor_locator(xyplt.MultipleLocator(1.0))
    np.testing.assert_array_equal(twin.get_yticks(minor=True), [1.0, 3.0, 5.0, 7.0, 9.0])


def test_shared_minor_tick_getters_use_the_queried_panel_size() -> None:
    fig, axes = xyplt.subplots(
        1,
        2,
        figsize=(5.0, 2.0),
        sharex=True,
        width_ratios=(1.0, 2.0),
    )
    for ax in axes:
        ax.plot([0.0, 10.0], [0.0, 10.0])
        ax.set_xlim(0.0, 10.0)
        ax.minorticks_on()

    queried = [ax.get_xticks(minor=True) for ax in axes]
    chart_specs = [chart.figure().build_payload_split()[0] for chart in fig._charts()]
    for ticks, spec in zip(queried, chart_specs, strict=True):
        np.testing.assert_array_equal(ticks, spec["x_axis"]["minor_tick_values"])
