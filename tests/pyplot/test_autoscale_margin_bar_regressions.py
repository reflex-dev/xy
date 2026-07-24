from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    plt.rcdefaults()
    yield
    plt.close("all")
    plt.rcdefaults()


def _axis_domain(ax, which: str) -> tuple[float, float]:
    chart = ax._build_chart(640, 480)
    child = next(child for child in chart.children if getattr(child, "which", None) == which)
    return tuple(child.domain)


def test_default_rc_margins_apply_to_public_and_rendered_line_limits() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [1.0, 3.0, 2.0])

    assert ax.get_xlim() == pytest.approx((-0.1, 2.1))
    assert ax.get_ylim() == pytest.approx((0.9, 3.1))
    assert _axis_domain(ax, "x") == pytest.approx((-0.1, 2.1))
    assert _axis_domain(ax, "y") == pytest.approx((0.9, 3.1))


def test_axes_snapshot_rc_margins_at_creation() -> None:
    with plt.rc_context({"axes.xmargin": 0.1, "axes.ymargin": 0.2}):
        _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [-1.0, 1.0])

    assert ax.get_xlim() == pytest.approx((-1.0, 11.0))
    assert ax.get_ylim() == pytest.approx((-1.4, 1.4))


def test_default_margin_is_applied_in_log_coordinate_space() -> None:
    _fig, ax = plt.subplots()
    ax.plot([1.0, 10.0, 100.0], [1.0, 2.0, 3.0])
    ax.set_xscale("log")

    expected = (10.0**-0.1, 10.0**2.1)
    assert ax.get_xlim() == pytest.approx(expected)
    assert _axis_domain(ax, "x") == pytest.approx(expected)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.2, 1.8, 1.4], (0.0, 1.89)),
        ([-1.2, -1.8, -1.4], (-1.89, 0.0)),
        ([-2.0, 3.0, 1.0], (-2.25, 3.25)),
    ],
)
def test_vertical_bar_limits_include_sticky_baseline_and_margin(values, expected) -> None:
    _fig, ax = plt.subplots()
    ax.bar([0.0, 1.0, 2.0], values)

    assert ax.get_ylim() == pytest.approx(expected)
    assert _axis_domain(ax, "y") == pytest.approx(expected)


def test_stacked_bar_limits_include_bases_and_cumulative_tops() -> None:
    _fig, ax = plt.subplots()
    ax.bar([0.0, 1.0, 2.0], [1.0, 1.5, 0.8])
    ax.bar(
        [0.0, 1.0, 2.0],
        [2.0, 1.0, 2.5],
        bottom=[1.0, 1.5, 0.8],
    )

    assert ax.get_xlim() == pytest.approx((-0.54, 2.54))
    assert ax.get_ylim() == pytest.approx((0.0, 3.465))
    assert _axis_domain(ax, "x") == pytest.approx((-0.54, 2.54))
    assert _axis_domain(ax, "y") == pytest.approx((0.0, 3.465))


def test_horizontal_bar_limits_include_value_baseline_and_category_width() -> None:
    _fig, ax = plt.subplots()
    ax.barh(["A", "B", "C"], [1.2, 1.8, 1.4])

    assert ax.get_xlim() == pytest.approx((0.0, 1.89))
    assert ax.get_ylim() == pytest.approx((-0.54, 2.54))
    assert _axis_domain(ax, "x") == pytest.approx((0.0, 1.89))
    assert _axis_domain(ax, "y") == pytest.approx((-0.54, 2.54))


def test_categorical_bar_domain_covers_every_category() -> None:
    _fig, ax = plt.subplots()
    ax.bar(
        ["first category", "second category", "third category", "fourth category"],
        [1.0, 3.0, 2.0, 4.0],
    )

    assert ax.get_xlim() == pytest.approx((-0.59, 3.59))
    assert ax.get_ylim() == pytest.approx((0.0, 4.2))
    assert _axis_domain(ax, "x") == pytest.approx((-0.59, 3.59))


def test_default_bar_margin_keeps_edge_labels_inside_the_view() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0.0, 1.0, 2.0], [1.2, 1.8, 1.4], width=0.55)
    labels = ax.bar_label(bars, fmt="%.1f", padding=3)

    assert [label.get_text() for label in labels] == ["1.2", "1.8", "1.4"]
    assert ax.get_ylim() == pytest.approx((0.0, 1.89))
    assert _axis_domain(ax, "y") == pytest.approx((0.0, 1.89))
    assert max(np.asarray(bars.tops, dtype=float)) < ax.get_ylim()[1]
