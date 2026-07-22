"""Behavioral contracts for the pyplot options intentionally kept as no-ops.

Every entry is also registered with a rationale in
``spec/testing/pyplot-noops.json``.  These tests prove that changing the value
does not change the bounded behavior the shim promises today.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot import FacetGrid


def teardown_function() -> None:
    plt.close("all")
    plt.rcdefaults()


def test_artist_compat_noops_are_invariant() -> None:
    _fig, ax = plt.subplots()
    collection = ax.scatter([0.0, 1.0], [1.0, 2.0])
    collection.set_sizes([9.0, 25.0], dpi=72)
    at_72 = collection.get_sizes().copy()
    collection.set_sizes([9.0, 25.0], dpi=288)
    np.testing.assert_array_equal(collection.get_sizes(), at_72)

    text = ax.text(0.25, 0.75, "renderer independent")
    assert (
        text.get_window_extent(renderer=None).bounds
        == text.get_window_extent(renderer=object()).bounds
    )


def _new_axes() -> tuple[object, object]:
    fig, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [1.0, 3.0, 2.0])
    return fig, ax


def _aspect_snapshot(ax: object) -> tuple[object, ...]:
    return (
        ax._aspect_equal,
        ax._aspect_adjustable,
        ax._aspect_bounds,
        ax.get_xlim(),
        ax.get_ylim(),
    )


def test_axes_compat_noops_are_invariant() -> None:
    fig, ax = _new_axes()
    assert ax.get_figure(root=False) is fig
    assert ax.get_figure(root=True) is fig
    assert ax.get_position(original=False).bounds == ax.get_position(original=True).bounds

    _fig_a, ax_a = _new_axes()
    _fig_b, ax_b = _new_axes()
    assert ax_a.axis(xmin=-1.0, ymax=5.0, emit=False) == ax_b.axis(xmin=-1.0, ymax=5.0, emit=True)

    _fig_a, ax_a = _new_axes()
    _fig_b, ax_b = _new_axes()
    ax_a.margins(x=0.2, y=0.3, tight=False)
    ax_b.margins(x=0.2, y=0.3, tight=True)
    assert (ax_a.get_xlim(), ax_a.get_ylim()) == (ax_b.get_xlim(), ax_b.get_ylim())

    _fig_a, ax_a = _new_axes()
    _fig_b, ax_b = _new_axes()
    ax_a.lines[0].set_visible(False)
    ax_b.lines[0].set_visible(False)
    ax_a.relim(visible_only=False)
    ax_b.relim(visible_only=True)
    assert (ax_a.get_xlim(), ax_a.get_ylim()) == (ax_b.get_xlim(), ax_b.get_ylim())

    _fig_a, ax_a = _new_axes()
    _fig_b, ax_b = _new_axes()
    ax_a.set_aspect("equal", adjustable="box")
    ax_b.set_aspect("equal", adjustable="box", anchor="NE", share=True)
    assert _aspect_snapshot(ax_a) == _aspect_snapshot(ax_b)


def test_facetgrid_legend_out_noop_is_bounded_by_hue_rejection() -> None:
    data = {
        "group": np.asarray(["a", "a", "b", "b"]),
        "x": np.asarray([0.0, 1.0, 0.0, 1.0]),
        "y": np.asarray([1.0, 2.0, 3.0, 4.0]),
    }

    def snapshot(legend_out: bool) -> tuple[object, ...]:
        grid = FacetGrid(data, row="group", legend_out=legend_out)
        grid.map(plt.plot, "x", "y")

        def stable(value: object) -> object:
            if isinstance(value, dict):
                return {key: stable(item) for key, item in value.items() if key != "link_group"}
            if isinstance(value, list):
                return [stable(item) for item in value]
            return value

        payloads = tuple(
            (stable(spec), blob)
            for spec, blob in (chart.figure().build_payload() for chart in grid.figure._charts())
        )
        return grid.axes.shape, tuple(grid.row_names), payloads

    assert snapshot(False) == snapshot(True)
    with pytest.raises(NotImplementedError):
        FacetGrid(data, row="group", hue="group", legend_out=False)
    with pytest.raises(NotImplementedError):
        FacetGrid(data, row="group", hue="group", legend_out=True)


def test_figure_clear_observer_noop_is_invariant() -> None:
    def cleared(keep_observers: bool) -> tuple[object, ...]:
        fig, ax = _new_axes()
        ax.set_title("discard me")
        fig.clear(keep_observers=keep_observers)
        return (
            tuple(fig.axes),
            fig._current_ax,
            fig._nrows,
            fig._ncols,
            fig._suptitle,
            fig._gci,
        )

    assert cleared(False) == cleared(True)


def test_clabel_compat_noops_are_invariant() -> None:
    def labels(**kwargs: object) -> tuple[tuple[object, ...], ...]:
        _fig, ax = plt.subplots()
        z = np.asarray([[0.0, 1.0, 2.0], [1.0, 3.0, 4.0], [2.0, 4.0, 6.0]])
        contours = ax.contour(z, levels=[2.0, 4.0])
        result = ax.clabel(contours, fmt="L=%.0f", **kwargs)
        return tuple(
            (
                label.get_text(),
                tuple(float(value) for value in label._entry["args"][:2]),
                tuple(sorted(label._entry["kwargs"].items())),
            )
            for label in result
        )

    baseline = labels()
    altered = labels(
        fontsize=31,
        inline=False,
        inline_spacing=40,
        use_clabeltext=True,
        rightside_up=False,
        zorder=99,
    )
    assert altered == baseline


def test_locator_compat_noops_are_invariant() -> None:
    np.testing.assert_array_equal(
        plt.NullLocator().tick_values(-10.0, 20.0),
        plt.NullLocator().tick_values(100.0, 200.0),
    )
    fixed = plt.FixedLocator([-1.0, 0.0, 3.0])
    np.testing.assert_array_equal(
        fixed.tick_values(-1_000.0, -900.0), fixed.tick_values(900.0, 1_000.0)
    )
    np.testing.assert_array_equal(
        plt.MaxNLocator(4, prune=None).tick_values(-2.0, 9.0),
        plt.MaxNLocator(4, prune="both").tick_values(-2.0, 9.0),
    )
    np.testing.assert_array_equal(
        plt.LogLocator(numticks=2).tick_values(0.1, 10_000.0),
        plt.LogLocator(numticks=200).tick_values(0.1, 10_000.0),
    )


def test_formatter_compat_noops_are_invariant() -> None:
    assert plt.ScalarFormatter()(12.5, pos=0) == plt.ScalarFormatter()(12.5, pos=99)
    assert plt.NullFormatter()(-1.0, pos=0) == plt.NullFormatter()(999.0, pos=99) == ""
    fixed = plt.FixedFormatter(["first", "second"])
    assert fixed(-1_000.0, pos=1) == fixed(1_000.0, pos=1) == "second"
    percent = plt.FormatStrFormatter("%.1f")
    assert percent(3.25, pos=0) == percent(3.25, pos=99)


def _ms(value: dt.datetime) -> float:
    return (value - dt.datetime(1970, 1, 1)).total_seconds() * 1000.0


def test_date_compat_noops_are_invariant() -> None:
    value = _ms(dt.datetime(2025, 6, 15, 12, 30))
    baseline = plt.dates.DateFormatter("%Y-%m-%d %H:%M")
    configured = plt.dates.DateFormatter(
        "%Y-%m-%d %H:%M", tz=dt.timezone(dt.timedelta(hours=9)), usetex=True
    )
    assert baseline(value, pos=0) == configured(value, pos=99)

    lo = _ms(dt.datetime(2024, 1, 1))
    hi = _ms(dt.datetime(2025, 12, 31))
    factories = (
        lambda tz: plt.dates.DayLocator(bymonthday=[1, 15], interval=2, tz=tz),
        lambda tz: plt.dates.MonthLocator(bymonth=[1, 4, 7, 10], interval=2, tz=tz),
        lambda tz: plt.dates.YearLocator(base=1, month=6, day=1, tz=tz),
    )
    for factory in factories:
        np.testing.assert_array_equal(
            factory(None).tick_values(lo, hi),
            factory(dt.timezone(dt.timedelta(hours=-7))).tick_values(lo, hi),
        )
