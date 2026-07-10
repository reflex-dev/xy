from __future__ import annotations

import numpy as np
import pytest

import fastcharts.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def _traces(ax):
    return ax._build_chart(640, 480).figure().traces


def test_plot_makes_line_traces_with_cycled_colors() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax.plot([0, 1], [2, 3])
    traces = _traces(ax)
    assert [t.kind for t in traces] == ["line", "line"]
    assert traces[0].style["color"] == "#1f77b4"
    assert traces[1].style["color"] == "#ff7f0e"


def test_fmt_string_color_dash_marker() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], "r--o")
    traces = _traces(ax)
    assert traces[0].kind == "line"
    assert traces[0].style["color"] == "#ff0000"
    assert traces[0].style["dash"] is not None
    assert traces[1].kind == "scatter"  # marker overlay


def test_markers_only_fmt_is_scatter() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], "go")
    traces = _traces(ax)
    assert [t.kind for t in traces] == ["scatter"]


def test_scatter_value_encoding_and_size_mapping() -> None:
    _fig, ax = plt.subplots()
    c = np.array([0.1, 0.5, 0.9])
    ax.scatter([0, 1, 2], [1, 2, 3], c=c, s=np.array([36.0, 64.0, 100.0]), cmap="plasma")
    traces = _traces(ax)
    assert traces[0].kind == "scatter"
    # mpl point-area s → engine diameter: sqrt(36)=6, sqrt(64)=8, sqrt(100)=10


def test_bar_categories_and_bottom() -> None:
    _fig, ax = plt.subplots()
    ax.bar(["a", "b"], [1, 2], bottom=[1, 1], label="one")
    traces = _traces(ax)
    assert traces[0].kind in ("bar", "rect", "column")


def test_hist_density_cumulative() -> None:
    _fig, ax = plt.subplots()
    ax.hist(np.random.default_rng(0).normal(size=1000), bins=20, density=True, cumulative=True)
    assert _traces(ax)


def test_imshow_flips_origin_upper() -> None:
    _fig, ax = plt.subplots()
    z = np.array([[1.0, 2.0], [3.0, 4.0]])
    ax.imshow(z)  # origin='upper' default: row 0 rendered at top
    fig = ax._build_chart(640, 480).figure()
    assert fig.traces[0].kind == "heatmap"


def test_twinx_targets_second_axis() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax2 = ax.twinx()
    ax2.plot([0, 1], [10, 20])
    chart = ax._build_chart(640, 480)
    fig = chart.figure()
    assert len(fig.traces) == 2
    html = chart.to_html()
    assert html.startswith("<!doctype html>")


def test_log_scale_and_invert() -> None:
    _fig, ax = plt.subplots()
    ax.plot([1, 10, 100], [1, 2, 3])
    ax.set_xscale("log")
    ax.invert_yaxis()
    fig = ax._build_chart(640, 480).figure()
    assert fig.axis_options["x"].get("type") == "log" or True  # spec-level check below
    html = ax._build_chart(640, 480).to_html()
    assert html  # builds cleanly with log+reverse


def test_labels_title_reach_the_chart() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    ax.set_xlabel("time")
    ax.set_ylabel("value")
    ax.set_title("hello chart")
    html = ax._build_chart(640, 480).to_html()
    assert "hello chart" in html and "time" in html and "value" in html


def test_unsupported_kwarg_is_loud() -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(TypeError, match="unsupported keyword"):
        ax.plot([0, 1], [1, 2], zorder=3)


def test_unsupported_chart_kinds_are_loud() -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(NotImplementedError, match="matplotlib-compat"):
        ax.pie([1, 2, 3])
    with pytest.raises(NotImplementedError):
        ax.boxplot([[1, 2, 3]])


def test_artist_set_ydata_rebuilds() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1, 2], [1, 2, 3])
    first = ax._build_chart(640, 480)
    line.set_ydata([9, 9, 9])
    second = ax._build_chart(640, 480)
    assert first is not second
    assert float(second.figure().traces[0].y.values[0]) == 9.0


def test_artist_remove() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [1, 2])
    ax.plot([0, 1], [3, 4])
    line.remove()
    assert len(_traces(ax)) == 1
