from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def _traces(ax):
    return ax._build_chart(640, 480).figure().traces


def test_line2d_marker_style_setters_mutate_marker_overlay() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [1, 2], "o-")

    first = ax._build_chart(640, 480)
    line.set_markerfacecolor("tab:red")
    line.set_markeredgecolor("k")
    line.set_markersize(9)
    second = ax._build_chart(640, 480)

    assert first is not second
    traces = second.figure().traces
    assert [trace.kind for trace in traces] == ["line", "scatter"]
    assert traces[1].color_ch.constant == "#d62728"
    assert traces[1].style["stroke"] == "#000000"
    assert traces[1].size_ch.constant == 12.0


def test_marker_only_plot_handle_supports_marker_style_setters() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [1, 2], "o")

    line.set_markerfacecolor("tab:green")
    line.set_markeredgecolor("none")
    line.set_ms(6)

    (trace,) = _traces(ax)
    assert trace.kind == "scatter"
    assert trace.color_ch.constant == "#2ca02c"
    assert "stroke" not in trace.style
    assert trace.size_ch.constant == 8.0


def test_segment_backed_line2d_set_ydata_rebuilds_retained_logical_data() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 2, 1], [1, 2, 3])

    line.set_ydata([4, 5, 6])

    (trace,) = _traces(ax)
    assert trace.kind == "segments"
    np.testing.assert_array_equal(trace.x0.values, [0, 2])
    np.testing.assert_array_equal(trace.y0.values, [4, 5])
    np.testing.assert_array_equal(trace.x1.values, [2, 1])
    np.testing.assert_array_equal(trace.y1.values, [5, 6])
    np.testing.assert_array_equal(line.get_ydata(), [4, 5, 6])


def test_segment_backed_line2d_set_xdata_rebuilds_retained_logical_data() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 2, 1], [1, 2, 3])

    line.set_xdata([3, 1, 2])

    (trace,) = _traces(ax)
    assert trace.kind == "segments"
    np.testing.assert_array_equal(trace.x0.values, [3, 1])
    np.testing.assert_array_equal(trace.y0.values, [1, 2])
    np.testing.assert_array_equal(trace.x1.values, [1, 2])
    np.testing.assert_array_equal(trace.y1.values, [2, 3])
    np.testing.assert_array_equal(line.get_xdata(), [3, 1, 2])
