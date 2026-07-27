from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def teardown_function() -> None:
    plt.close("all")


def test_axline_is_clipped_to_the_final_view_and_keeps_dash_style() -> None:
    _fig, ax = plt.subplots()
    ax.axline((0, 0.5), slope=0.25, color="black", linestyle=(0, (5, 5)))
    ax.set(xlim=(-10, 10), ylim=(-0.05, 1.05))

    trace = ax._build_chart(640, 480).figure().traces[0]

    np.testing.assert_allclose(trace.x.values, [-2.2, 2.2])
    np.testing.assert_allclose(trace.y.values, [-0.05, 1.05])
    assert trace.style["dash"] == [10.4167, 10.4167]
    assert trace.style["width"] == pytest.approx(1.5 * 100 / 72)


def test_axline_axes_transform_is_deferred_but_slope_stays_in_data_space() -> None:
    _fig, ax = plt.subplots()
    ax.axline((-1 / 3, 0), slope=0.5, color="black", transform=ax.transAxes)

    # A transformed defining point does not alter the dataless view.
    assert ax.get_xlim() == (0.0, 1.0)
    assert ax.get_ylim() == (0.0, 1.0)

    ax.set(xlim=(0, 1), ylim=(0, 1))
    trace = ax._build_chart(640, 480).figure().traces[0]
    np.testing.assert_allclose(trace.x.values, [0.0, 1.0])
    np.testing.assert_allclose(trace.y.values, [1 / 6, 2 / 3])


def test_axline_reclips_after_limits_change_and_handles_vertical_lines() -> None:
    _fig, ax = plt.subplots()
    ax.axline((0.25, 0.5), slope=np.inf)
    ax.set(xlim=(0, 1), ylim=(-2, 2))
    first = ax._build_chart(640, 480).figure().traces[0]
    np.testing.assert_allclose(first.x.values, [0.25, 0.25])
    np.testing.assert_allclose(first.y.values, [-2, 2])

    ax.set_ylim(-4, 4)
    second = ax._build_chart(640, 480).figure().traces[0]
    np.testing.assert_allclose(second.y.values, [-4, 4])


def test_axline_slope_rejects_nonlinear_scales_like_matplotlib() -> None:
    _fig, ax = plt.subplots()
    ax.set_xscale("log")

    with pytest.raises(TypeError, match=r"slope.*non-linear"):
        ax.axline((1, 1), slope=1)


def test_line_set_dashes_updates_the_rendered_dash_pattern() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], linewidth=2)

    line.set_dashes([2, 2, 10, 2])

    trace = ax._build_chart(640, 480).figure().traces[0]
    assert trace.style["dash"] == pytest.approx(
        [value * 2 * 100 / 72 for value in (2, 2, 10, 2)],
        abs=1e-4,
    )
