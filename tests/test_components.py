"""Reflex-style composition API: fc.scatter_chart(fc.scatter(...), fc.x_axis(...)).

Verifies the component tree builds the same Figure the fluent API would, plus
data= column-name resolution, event-prop wiring, and box-select (§34)."""

from __future__ import annotations

import numpy as np
import pytest

import fastcharts as fc
from fastcharts.components import Chart, Mark
from fastcharts.widget import Selection


class FakeFrame:
    """Minimal DataFrame-like: __getitem__ returns a column array (so the tests
    don't require pandas)."""

    def __init__(self, cols):
        self._cols = {k: np.asarray(v) for k, v in cols.items()}

    def __getitem__(self, key):
        return self._cols[key]


def test_factories_return_components():
    assert isinstance(fc.scatter(x=[1], y=[2]), Mark)
    assert fc.scatter(x=[1], y=[2]).kind == "scatter"
    assert fc.line(x=[1], y=[2]).kind == "line"
    chart = fc.scatter_chart(fc.scatter(x=[1.0], y=[2.0]))
    assert isinstance(chart, Chart)


def test_composition_builds_figure():
    x = np.arange(100.0)
    y = np.sin(x)
    chart = fc.scatter_chart(
        fc.scatter(x=x, y=y, name="a"),
        fc.x_axis(label="time"),
        fc.y_axis(label="value"),
        title="t",
        width=800,
        height=300,
    )
    fig = chart.figure()
    assert fig.title == "t"
    assert fig.width == 800 and fig.height == 300
    assert fig.x_label == "time" and fig.y_label == "value"
    assert len(fig.traces) == 1
    assert fig.traces[0].kind == "scatter"
    assert fig.traces[0].name == "a"


def test_data_key_resolution():
    df = FakeFrame({
        "gdp": np.array([1.0, 2.0, 3.0]),
        "life": np.array([70.0, 75.0, 80.0]),
        "pop": np.array([10.0, 20.0, 30.0]),
        "cont": np.array(["a", "b", "a"]),
    })
    chart = fc.scatter_chart(
        fc.scatter(x="gdp", y="life", color="cont", size="pop", data=df),
    )
    fig = chart.figure()
    t = fig.traces[0]
    np.testing.assert_array_equal(t.x.values, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(t.y.values, [70.0, 75.0, 80.0])
    assert t.color_ch.mode == "categorical"  # "cont" column is strings
    assert t.size_ch.mode == "continuous"  # "pop" column is numbers


def test_chart_level_data_default():
    df = FakeFrame({"a": np.arange(5.0), "b": np.arange(5.0) * 2})
    chart = fc.scatter_chart(fc.scatter(x="a", y="b"), data=df)
    fig = chart.figure()
    np.testing.assert_array_equal(fig.traces[0].y.values, np.arange(5.0) * 2)


def test_css_color_vs_column():
    # A CSS color stays constant; a non-CSS string is a column name.
    df = FakeFrame({"x": np.arange(3.0), "y": np.arange(3.0), "grp": np.array(["p", "q", "p"])})
    c1 = fc.scatter_chart(fc.scatter(x="x", y="y", color="#ff0000", data=df)).figure()
    assert c1.traces[0].color_ch.mode == "constant"
    c2 = fc.scatter_chart(fc.scatter(x="x", y="y", color="red", data=df)).figure()
    assert c2.traces[0].color_ch.mode == "constant"
    c3 = fc.scatter_chart(fc.scatter(x="x", y="y", color="grp", data=df)).figure()
    assert c3.traces[0].color_ch.mode == "categorical"


def test_missing_column_errors():
    df = FakeFrame({"a": np.arange(3.0)})
    with pytest.raises(ValueError, match="not found"):
        fc.scatter_chart(fc.scatter(x="a", y="missing", data=df)).figure()


def test_column_name_without_data_errors():
    with pytest.raises(ValueError, match="no data"):
        fc.scatter_chart(fc.scatter(x="a", y="b")).figure()


def test_legend_off():
    chart = fc.scatter_chart(
        fc.scatter(x=np.arange(3.0), y=np.arange(3.0), name="s"),
        fc.legend(show=False),
    )
    spec, _ = chart.figure().build_payload()
    assert spec["show_legend"] is False


def test_line_chart():
    x = np.arange(100.0)
    chart = fc.line_chart(fc.line(x=x, y=np.sin(x), name="wave", color="#123456"))
    fig = chart.figure()
    assert fig.traces[0].kind == "line"
    assert fig.traces[0].style["color"] == "#123456"


def test_log_axis_warns():
    with pytest.warns(RuntimeWarning, match="log axes"):
        fc.scatter_chart(
            fc.scatter(x=np.arange(3.0), y=np.arange(3.0)),
            fc.y_axis(type_="log"),
        ).figure()


def test_bad_child_type():
    with pytest.raises(TypeError, match="children"):
        fc.scatter_chart("not a component").figure()


def test_figure_cached():
    chart = fc.scatter_chart(fc.scatter(x=np.arange(3.0), y=np.arange(3.0)))
    assert chart.figure() is chart.figure()


# -- selection (§34) ---------------------------------------------------------


def test_select_range():
    x = np.arange(100.0)
    y = np.arange(100.0)
    fig = fc.Figure().scatter(x, y)
    sel = fig.select_range(10.0, 20.0, 0.0, 1000.0)
    idx = sel[0]
    assert idx.dtype == np.uint32
    np.testing.assert_array_equal(idx, np.arange(10, 21, dtype=np.uint32))


def test_select_range_box():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 100, 1000)
    y = rng.uniform(0, 100, 1000)
    fig = fc.Figure().scatter(x, y)
    sel = fig.select_range(25.0, 75.0, 25.0, 75.0)
    idx = sel[0]
    expect = np.flatnonzero((x >= 25) & (x <= 75) & (y >= 25) & (y <= 75))
    np.testing.assert_array_equal(np.sort(idx), expect.astype(np.uint32))


def test_selection_payload():
    x = np.arange(10.0)
    fig = fc.Figure().scatter(x, x)
    sel = fig.select_range(2.0, 5.0, 0.0, 100.0)
    payload = Selection(fig, sel)
    assert len(payload) == 4  # indices 2,3,4,5
    sx, sy = payload.xy(0)
    np.testing.assert_array_equal(sx, [2.0, 3.0, 4.0, 5.0])
    np.testing.assert_array_equal(payload.index, [2, 3, 4, 5])
