from __future__ import annotations

from io import BytesIO

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


def test_axline_reclips_to_the_final_shared_axes_view() -> None:
    fig, axes = plt.subplots(1, 2, sharex=True, sharey=True)
    axes[0].set(xlim=(0, 20), ylim=(2, 14))
    axes[0].plot([4, 14], [4, 9], "o")
    axes[1].plot([6, 13], [3, 9], "o")
    axes[1].axline((0, 3), slope=0.5, color="red")

    charts = fig._charts()
    final_x = charts[1].figure().x_range()
    final_y = charts[1].figure().y_range()
    trace = charts[1].figure().traces[-1]
    endpoints = list(zip(trace.x.values, trace.y.values, strict=True))

    assert all(
        x == pytest.approx(final_x[0])
        or x == pytest.approx(final_x[1])
        or y == pytest.approx(final_y[0])
        or y == pytest.approx(final_y[1])
        for x, y in endpoints
    )
    assert all(y == pytest.approx(3 + 0.5 * x) for x, y in endpoints)
    assert fig._charts()[1] is charts[1]


def test_transformed_axline_uses_the_final_shared_axes_view() -> None:
    fig, axes = plt.subplots(1, 2, sharex=True, sharey=True)
    axes[0].plot([-10, 10], [-2, 2])
    axes[1].plot([0, 1], [0, 1])
    axes[1].axline((0, 0), (1, 1), transform=axes[1].transAxes)

    charts = fig._charts()
    final_x = charts[1].figure().x_range()
    final_y = charts[1].figure().y_range()
    trace = charts[1].figure().traces[-1]

    np.testing.assert_allclose(trace.x.values, final_x)
    np.testing.assert_allclose(trace.y.values, final_y)


def test_transformed_axline_gallery_corner_tangencies_survive_png_then_svg() -> None:
    fig, ax = plt.subplots()
    for pos in np.linspace(-2, 1, 10):
        ax.axline((pos, 0), slope=0.5, color="black", transform=ax.transAxes)
    ax.set(xlim=(0, 1), ylim=(0, 1))

    traces = ax._build_chart(640, 480).figure().traces
    assert len(traces) == 10
    np.testing.assert_allclose(traces[0].x.values, [0, 0])
    np.testing.assert_allclose(traces[0].y.values, [1, 1])
    np.testing.assert_allclose(traces[-1].x.values, [1, 1])
    np.testing.assert_allclose(traces[-1].y.values, [0, 0])

    fig.savefig(BytesIO(), format="png", dpi=100)
    output = BytesIO()
    fig.savefig(output, format="svg")
    assert output.getvalue().startswith(b"<svg")


def test_transformed_axline_outside_view_emits_no_empty_trace() -> None:
    fig, ax = plt.subplots()
    ax.axline((-3, 0), slope=0.5, transform=ax.transAxes)
    ax.set(xlim=(0, 1), ylim=(0, 1))

    assert not ax._build_chart(640, 480).figure().traces
    output = BytesIO()
    fig.savefig(output, format="svg")
    assert output.getvalue().startswith(b"<svg")


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
