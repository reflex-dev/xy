"""Reflex-style composition API: fc.scatter_chart(fc.scatter(...), fc.x_axis(...)).

Verifies the component tree builds the same Figure the fluent API would, plus
data= column-name resolution, event-prop wiring, and box-select (§34)."""

from __future__ import annotations

import numpy as np
import pytest

import fastcharts as fc
from fastcharts.components import Axis, Chart, Legend, Mark
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
    assert fc.area(x=[1], y=[2]).kind == "area"
    assert fc.histogram(values=[1, 2, 3]).kind == "histogram"
    assert fc.hist(values=[1, 2, 3]).kind == "histogram"
    assert fc.bar(x=["a"], y=[1]).kind == "bar"
    assert fc.column(x=["a"], y=[1]).kind == "column"
    assert fc.heatmap(z=[[1]]).kind == "heatmap"
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
    df = FakeFrame(
        {
            "gdp": np.array([1.0, 2.0, 3.0]),
            "life": np.array([70.0, 75.0, 80.0]),
            "pop": np.array([10.0, 20.0, 30.0]),
            "cont": np.array(["a", "b", "a"]),
        }
    )
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


def test_component_axis_and_legend_validate_public_props_without_caching_failure():
    with pytest.raises(ValueError, match="axis type_"):
        fc.x_axis(type_="logg")
    with pytest.raises(ValueError, match="legend show"):
        fc.legend(show="false")

    bad_axis = Axis(which="z")
    chart = fc.scatter_chart(fc.scatter(x=np.arange(3.0), y=np.arange(3.0)), bad_axis)
    with pytest.raises(ValueError, match=r"axis\.which"):
        chart.figure()
    assert chart._figure is None

    bad_axis.which = "x"
    fig = chart.figure()
    assert fig is chart.figure()
    assert fig.x_label is None

    bad_legend = Legend(show="false")
    chart2 = fc.scatter_chart(fc.scatter(x=np.arange(3.0), y=np.arange(3.0)), bad_legend)
    with pytest.raises(ValueError, match="legend show"):
        chart2.figure()
    assert chart2._figure is None
    assert bad_legend.show == "false"


def test_component_axis_types_accept_current_surface_and_warn_for_log_only():
    fig = fc.scatter_chart(
        fc.scatter(x=np.arange(3.0), y=np.arange(3.0)),
        fc.x_axis(type_="linear"),
        fc.y_axis(type_="time"),
    ).figure()
    assert len(fig.traces) == 1

    with pytest.warns(RuntimeWarning, match="log axes"):
        fc.scatter_chart(
            fc.scatter(x=np.arange(3.0), y=np.arange(3.0)),
            Axis(which="y", type_="log"),
        ).figure()


def test_line_chart():
    x = np.arange(100.0)
    chart = fc.line_chart(fc.line(x=x, y=np.sin(x), name="wave", color="#123456"))
    fig = chart.figure()
    assert fig.traces[0].kind == "line"
    assert fig.traces[0].style["color"] == "#123456"


def test_area_chart_resolves_base_column():
    df = FakeFrame(
        {
            "x": np.arange(3.0),
            "y": np.array([2.0, 4.0, 3.0]),
            "base": np.array([1.0, 1.5, 1.0]),
        }
    )
    fig = fc.area_chart(fc.area(x="x", y="y", base="base", color="#3355aa"), data=df).figure()
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "area"
    assert tr["style"]["color"] == "#3355aa"
    base = spec["columns"][tr["base"]]
    vals = np.frombuffer(blob, dtype=np.float32, count=base["len"], offset=base["byte_offset"])
    np.testing.assert_allclose(vals.astype(np.float64) + base["offset"], [1.0, 1.5, 1.0])


def test_histogram_chart_data_key():
    df = FakeFrame({"value": np.array([0.2, 0.4, 1.2, 1.8])})
    chart = fc.histogram_chart(fc.histogram(values="value", bins=[0.0, 1.0, 2.0]), data=df)
    fig = chart.figure()
    spec, _ = fig.build_payload()
    assert fig.traces[0].kind == "histogram"
    assert spec["traces"][0]["n_points"] == 4
    assert spec["traces"][0]["n_marks"] == 2


def test_bar_chart_data_keys_and_category_axis():
    df = FakeFrame({"label": np.array(["a", "b", "c"]), "value": np.array([3.0, 2.0, 4.0])})
    chart = fc.bar_chart(fc.bar(x="label", y="value", color="#3355aa"), data=df)
    fig = chart.figure()
    assert fig.traces[0].kind == "bar"
    assert fig.traces[0].style["color"] == "#3355aa"
    spec, _ = fig.build_payload()
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["a", "b", "c"]


def test_bar_chart_grouped_component_options():
    df = FakeFrame(
        {
            "label": np.array(["a", "b"]),
            "values": np.array([[3.0, 2.0], [4.0, 5.0]]),
        }
    )
    fig = fc.bar_chart(
        fc.bar(
            x="label",
            y="values",
            mode="stacked",
            series=["desktop", "mobile"],
            colors=["#111111", "#222222"],
        ),
        data=df,
    ).figure()
    spec, _ = fig.build_payload()
    assert len(spec["traces"]) == 2
    assert [t["name"] for t in spec["traces"]] == ["desktop", "mobile"]
    assert [t["style"]["role"] for t in spec["traces"]] == ["bar-stacked", "bar-stacked"]


def test_bar_chart_horizontal_component_option():
    df = FakeFrame({"label": np.array(["a", "b"]), "value": np.array([3.0, 2.0])})
    fig = fc.bar_chart(fc.bar(x="label", y="value", orientation="horizontal"), data=df).figure()
    spec, _ = fig.build_payload()
    assert spec["y_axis"]["kind"] == "category"
    assert spec["y_axis"]["categories"] == ["a", "b"]


def test_column_chart_resolves_base_column():
    df = FakeFrame(
        {
            "label": np.array(["a", "b"]),
            "value": np.array([3.0, 2.0]),
            "base": np.array([1.0, 10.0]),
        }
    )
    fig = fc.column_chart(fc.column(x="label", y="value", base="base"), data=df).figure()
    spec, blob = fig.build_payload()
    bar = spec["traces"][0]["bar"]
    y0 = spec["columns"][bar["value0"]]
    vals = np.frombuffer(blob, dtype=np.float32, count=y0["len"], offset=y0["byte_offset"])
    np.testing.assert_allclose(vals.astype(np.float64) + y0["offset"], [1.0, 10.0])


def test_heatmap_chart_data_keys():
    df = FakeFrame(
        {
            "z": np.array([[1.0, 2.0], [3.0, 4.0]]),
            "cols": np.array(["a", "b"]),
            "rows": np.array(["north", "south"]),
        }
    )
    fig = fc.heatmap_chart(
        fc.heatmap(z="z", x="cols", y="rows", colormap="cividis", name="values"),
        data=df,
    ).figure()
    spec, _ = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "heatmap"
    assert tr["name"] == "values"
    assert tr["color"]["colormap"] == "cividis"
    assert spec["x_axis"]["categories"] == ["a", "b"]
    assert spec["y_axis"]["categories"] == ["north", "south"]


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

    with pytest.raises(ValueError, match="trace_id"):
        payload.xy(-1)
