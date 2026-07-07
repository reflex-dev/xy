"""Reflex-style composition API: fc.scatter_chart(fc.scatter(...), fc.x_axis(...)).

Verifies the component tree builds the same Figure the fluent API would, plus
data= column-name resolution, event-prop wiring, and box-select (§34)."""

from __future__ import annotations

import json

import numpy as np
import pytest

import fastcharts as fc
from fastcharts.components import (
    Annotation,
    Axis,
    Chart,
    Interaction,
    Legend,
    Mark,
    MarkStyle,
    Modebar,
    Theme,
    Tooltip,
)
from fastcharts.widget import Selection


class FakeFrame:
    """Minimal DataFrame-like: __getitem__ returns a column array (so the tests
    don't require pandas)."""

    def __init__(self, cols):
        self._cols = {k: np.asarray(v) for k, v in cols.items()}

    def __getitem__(self, key):
        return self._cols[key]


class FakeReflexComponent:
    """Opaque stand-in for a Reflex component without importing Reflex."""

    def __init__(self, name: str):
        self.name = name


def _inline_spec_literal(html: str) -> str:
    body = html.split("<body>", 1)[1]
    return body.rsplit("const spec = ", 1)[1].split(";\n  const b64", 1)[0]


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
    assert isinstance(fc.arrow(0.0, 1.0, 2.0, 3.0), Annotation)
    assert isinstance(fc.callout(0.0, 1.0, "label"), Annotation)
    assert isinstance(fc.vline(1.0), Annotation)
    assert isinstance(fc.hline(1.0), Annotation)
    assert isinstance(fc.x_band(0.0, 1.0), Annotation)
    assert isinstance(fc.y_band(0.0, 1.0), Annotation)
    assert isinstance(fc.text(0.0, 1.0, "label"), Annotation)
    assert isinstance(fc.label(0.0, 1.0, "label"), Annotation)
    assert isinstance(fc.marker(0.0, 1.0), Annotation)
    assert isinstance(fc.threshold(1.0), Annotation)
    assert isinstance(fc.threshold_zone(0.0, 1.0), Annotation)
    assert isinstance(fc.tooltip(fields=["x"]), Tooltip)
    assert isinstance(fc.modebar(show=False), Modebar)
    assert isinstance(fc.theme(style={"--chart-bg": "transparent"}), Theme)
    assert isinstance(fc.mark_style(hover={"size": 14}), MarkStyle)
    assert isinstance(fc.interaction_config(crosshair=True), Interaction)
    chart = fc.scatter_chart(fc.scatter(x=[1.0], y=[2.0]))
    assert isinstance(chart, Chart)
    assert isinstance(fc.chart(fc.scatter(x=[1.0], y=[2.0])), Chart)


def test_neutral_chart_overlays_marks():
    x = np.arange(20.0)
    chart = fc.chart(
        fc.scatter(x=x, y=np.sin(x), name="points"),
        fc.line(x=x, y=np.cos(x), name="fit"),
        fc.x_axis(label="x"),
        fc.y_axis(label="y"),
        title="overlay",
    )

    fig = chart.figure()

    assert fig.title == "overlay"
    assert fig.x_label == "x"
    assert fig.y_label == "y"
    assert [trace.kind for trace in fig.traces] == ["scatter", "line"]
    assert [trace.name for trace in fig.traces] == ["points", "fit"]


def test_composed_layered_chart_families_build_payload():
    x = np.arange(8.0)
    line_over_scatter = fc.chart(
        fc.scatter(x=x, y=np.sin(x), name="samples"),
        fc.line(x=x, y=np.sin(x) * 0.8, name="trend", color="#111111"),
        fc.legend(),
    )
    spec, _ = line_over_scatter.figure().build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["scatter", "line"]
    assert [trace["name"] for trace in spec["traces"]] == ["samples", "trend"]

    data = FakeFrame(
        {
            "month": np.array(["Jan", "Feb", "Mar", "Apr"]),
            "actual": np.array([12.0, 18.0, 16.0, 22.0]),
            "target": np.array([14.0, 15.0, 17.0, 20.0]),
        }
    )
    bars_plus_line = fc.chart(
        fc.bar(x="month", y="actual", data=data, name="actual"),
        fc.line(x="month", y="target", data=data, name="target", color="#dc2626"),
        fc.x_axis(label="month"),
    )
    fig = bars_plus_line.figure()
    spec, _ = fig.build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["bar", "line"]
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["Jan", "Feb", "Mar", "Apr"]
    np.testing.assert_array_equal(fig.traces[1].x.values, [0.0, 1.0, 2.0, 3.0])

    area_plus_points = fc.chart(
        fc.area(x=x, y=np.cos(x) + 2.0, name="range", color="#0891b2"),
        fc.scatter(x=x, y=np.cos(x) + 2.0, name="samples", size=8.0, color="#0f172a"),
    )
    spec, _ = area_plus_points.figure().build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["area", "scatter"]


def test_heatmap_can_compose_with_category_annotations():
    chart = fc.chart(
        fc.heatmap(
            z=np.array([[0.1, 0.8], [0.4, 0.95]]),
            x=["Mon", "Tue"],
            y=["AM", "PM"],
            name="load",
        ),
        fc.vline("Tue", text="deploy", color="#ef4444", width=2.0),
        fc.hline("PM", text="peak"),
        fc.x_band("Mon", "Tue", text="workweek", opacity=0.2),
        fc.text("Tue", "PM", "max", dx=4.0, dy=-8.0, anchor="middle"),
        fc.arrow("Mon", "AM", "Tue", "PM", text="flow", color="#0f172a"),
        fc.callout("Tue", "AM", "watch", dx=18.0, dy=-16.0),
    )

    spec, _ = chart.figure().build_payload()

    assert [trace["kind"] for trace in spec["traces"]] == ["heatmap"]
    assert spec["x_axis"]["categories"] == ["Mon", "Tue"]
    assert spec["y_axis"]["categories"] == ["AM", "PM"]
    assert spec["annotations"] == [
        {
            "text": "deploy",
            "style": {"color": "#ef4444", "width": 2.0, "opacity": 1.0},
            "kind": "rule",
            "axis": "x",
            "value": 1.0,
        },
        {
            "text": "peak",
            "style": {"color": "#667085", "width": 1.5, "opacity": 1.0},
            "kind": "rule",
            "axis": "y",
            "value": 1.0,
        },
        {
            "text": "workweek",
            "style": {"color": "#64748b", "opacity": 0.2},
            "kind": "band",
            "axis": "x",
            "start": 0.0,
            "end": 1.0,
        },
        {
            "kind": "text",
            "x": 1.0,
            "y": 1.0,
            "text": "max",
            "dx": 4.0,
            "dy": -8.0,
            "anchor": "middle",
        },
        {
            "text": "flow",
            "style": {"color": "#0f172a", "width": 1.5, "opacity": 1.0},
            "kind": "arrow",
            "x0": 0.0,
            "y0": 0.0,
            "x1": 1.0,
            "y1": 1.0,
        },
        {
            "text": "watch",
            "style": {"color": "#344054", "width": 1.5, "opacity": 1.0},
            "kind": "callout",
            "x": 1.0,
            "y": 0.0,
            "dx": 18.0,
            "dy": -16.0,
            "anchor": "start",
        },
    ]


def test_semantic_annotations_and_markers_emit_expected_specs():
    chart = fc.chart(
        fc.scatter(x=[1.0, 2.0, 3.0], y=[2.0, 5.0, 4.0]),
        fc.marker(
            2.0,
            5.0,
            text="peak",
            color="#16a34a",
            size=10,
            symbol="diamond",
            stroke_color="#052e16",
            stroke_width=2,
            dx=10,
            dy=-12,
            anchor="middle",
        ),
        fc.label(3.0, 4.0, "last", anchor="end"),
        fc.threshold(4.5, text="target"),
        fc.threshold_zone(4.0, 6.0, text="warning"),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["annotations"] == [
        {
            "text": "peak",
            "style": {
                "color": "#16a34a",
                "stroke_color": "#052e16",
                "stroke_width": 2.0,
                "opacity": 1.0,
            },
            "kind": "marker",
            "x": 2.0,
            "y": 5.0,
            "size": 10.0,
            "symbol": "diamond",
            "dx": 10.0,
            "dy": -12.0,
            "anchor": "middle",
        },
        {
            "kind": "text",
            "x": 3.0,
            "y": 4.0,
            "text": "last",
            "dx": 6.0,
            "dy": -6.0,
            "anchor": "end",
        },
        {
            "text": "target",
            "style": {"color": "#e11d48", "width": 1.5, "opacity": 1.0},
            "kind": "rule",
            "axis": "y",
            "value": 4.5,
        },
        {
            "text": "warning",
            "style": {"color": "#e11d48", "opacity": 0.12},
            "kind": "band",
            "axis": "y",
            "start": 4.0,
            "end": 6.0,
        },
    ]

    with pytest.raises(ValueError, match="marker symbol"):
        fc.chart(fc.scatter(x=[1.0], y=[1.0]), fc.marker(1.0, 1.0, symbol="pin")).figure()
    with pytest.raises(ValueError, match="threshold axis"):
        fc.threshold(1.0, axis="z")


def test_layered_tooltip_sources_keep_fields_tied_to_their_traces():
    data = FakeFrame(
        {
            "month": np.array(["Jan", "Feb", "Mar"]),
            "bookings": np.array([12.0, 18.0, 16.0]),
            "target": np.array([14.0, 15.0, 17.0]),
            "sample": np.array([13.0, 19.0, 15.0]),
        }
    )
    chart = fc.chart(
        fc.bar(x="month", y="bookings", data=data, name="bookings"),
        fc.scatter(x="month", y="sample", data=data, name="sample"),
        fc.line(x="month", y="target", data=data, name="target"),
        fc.tooltip(
            fields=["month", "bookings", "sample", "target"],
            title="{month}",
            format={"bookings": ".1f", "target": ".1f", "sample": ".1f"},
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["tooltip"]["fields"] == ["month", "bookings", "sample", "target"]
    assert spec["tooltip"]["sources"] == {
        "month": [
            {"trace": 0, "channel": "x"},
            {"trace": 1, "channel": "x"},
            {"trace": 2, "channel": "x"},
        ],
        "bookings": [{"trace": 0, "channel": "y"}],
        "sample": [{"trace": 1, "channel": "y"}],
        "target": [{"trace": 2, "channel": "y"}],
    }


def test_bad_category_annotation_does_not_cache_partial_chart_figure():
    marker = fc.vline("Wed")
    chart = fc.chart(
        fc.heatmap(z=np.array([[1.0, 2.0]]), x=["Mon", "Tue"], y=["AM"]),
        marker,
    )

    with pytest.raises(ValueError, match="category 'Wed' is not present"):
        chart.figure()
    assert chart._figure is None

    marker.x = "Tue"
    fig = chart.figure()

    assert chart.figure() is fig
    spec, _ = fig.build_payload()
    assert spec["annotations"][0]["value"] == 1.0


def test_component_api_default_payload_matches_fluent_figure():
    x = np.arange(16.0)
    y = x * 2

    component = fc.chart(fc.line(x=x, y=y)).figure()
    fluent = fc.Figure().line(x, y)
    component_spec, component_blob = component.build_payload()
    fluent_spec, fluent_blob = fluent.build_payload()

    assert "dom" not in component_spec
    assert "tooltip" not in component_spec
    assert "show_modebar" not in component_spec
    assert component_spec == fluent_spec
    assert component_blob == fluent_blob


def test_component_style_tooltip_and_modebar_metadata_is_opt_in():
    df = FakeFrame(
        {
            "feature_a": np.array([1.0, 2.0, 3.0]),
            "feature_b": np.array([2.0, 1.0, 4.0]),
            "segment": np.array(["enterprise", "growth", "enterprise"]),
        }
    )
    chart = fc.chart(
        fc.scatter(
            x="feature_a",
            y="feature_b",
            color="segment",
            data=df,
            name="accounts",
            class_name="fc-mark-accounts",
        ),
        fc.legend(class_name="legend-node", style={"max-height": 220}),
        fc.tooltip(
            fields=["feature_a", "feature_b", "segment"],
            title="{segment}",
            format={"feature_a": ".2f"},
            class_name="tooltip-node",
            style={"background-color": "black"},
        ),
        fc.modebar(
            show=False,
            class_name="modebar-node",
            button_class_name="modebar-button-node",
            button_style={"border-radius": 4},
        ),
        fc.theme(
            plot_background="transparent",
            grid_color="rgba(0,0,0,.1)",
            selection_fill="rgba(37,99,235,.14)",
        ),
        fc.mark_style(
            hover={"color": "#0f172a", "size": 18, "opacity": 0.9},
            selected={"opacity": 1},
            unselected={"opacity": 0.2},
        ),
        class_name="root-node",
        class_names={"legend": "legend-slot", "tooltip": "tooltip-slot"},
        style={"--chart-grid": "rgba(1,2,3,.25)", "--chart-axis": "currentColor"},
    )

    spec, _ = chart.figure().build_payload()

    assert spec["show_modebar"] is False
    assert spec["dom"]["class_name"] == "root-node"
    assert spec["dom"]["class_names"]["legend"] == "legend-slot legend-node"
    assert spec["dom"]["class_names"]["tooltip"] == "tooltip-slot tooltip-node"
    assert spec["dom"]["class_names"]["modebar"] == "modebar-node"
    assert spec["dom"]["class_names"]["modebar_button"] == "modebar-button-node"
    assert spec["dom"]["style"] == {
        "--chart-bg": "transparent",
        "--chart-grid": "rgba(1,2,3,.25)",
        "--chart-axis": "currentColor",
        "--chart-selection-fill": "rgba(37,99,235,.14)",
    }
    assert spec["dom"]["styles"]["legend"] == {"max-height": 220}
    assert spec["dom"]["styles"]["tooltip"] == {"background-color": "black"}
    assert spec["dom"]["styles"]["modebar_button"] == {"border-radius": 4}
    assert spec["mark_style"] == {
        "hover": {"color": "#0f172a", "size": 18, "opacity": 0.9},
        "selected": {"opacity": 1},
        "unselected": {"opacity": 0.2},
    }
    assert spec["tooltip"] == {
        "fields": ["feature_a", "feature_b", "segment"],
        "title": "{segment}",
        "format": {"feature_a": ".2f"},
        "aliases": {
            "feature_a": "x",
            "feature_b": "y",
            "segment": "color_category",
        },
        "sources": {
            "feature_a": [{"trace": 0, "channel": "x"}],
            "feature_b": [{"trace": 0, "channel": "y"}],
            "segment": [{"trace": 0, "channel": "color_category"}],
        },
    }
    assert spec["traces"][0]["style"]["class_name"] == "fc-mark-accounts"


def test_legend_and_tooltip_accept_opaque_framework_components_without_serializing():
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    chart = fc.chart(
        fc.scatter(x=[1.0, 2.0], y=[2.0, 3.0], name="points"),
        fc.legend(legend_component, show=False),
        fc.tooltip(
            tooltip_component,
            show=False,
            fields=["x", "y"],
            class_name="tooltip-node",
        ),
    )

    chrome = chart.chrome_components()
    assert chrome == {"legend": legend_component, "tooltip": tooltip_component}
    assert chart.reflex_components() == chrome

    spec, _ = chart.figure().build_payload()
    assert spec["show_legend"] is False
    assert spec["show_tooltip"] is False
    assert spec["tooltip"] == {"fields": ["x", "y"]}
    assert spec["dom"]["class_names"]["tooltip"] == "tooltip-node"
    assert "FakeReflexComponent" not in json.dumps(spec)

    html = chart.to_html()
    assert "FakeReflexComponent" not in html
    assert "show_tooltip" in html


def test_interaction_component_builds_declarative_spec():
    chart = fc.chart(
        fc.scatter(x=[1.0, 2.0], y=[2.0, 3.0], name="points"),
        fc.interaction_config(
            hover=True,
            click=True,
            select=True,
            brush=True,
            crosshair=True,
            view_change=True,
            link_group="dashboard",
            link_axes=("x",),
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["interaction"] == {
        "hover": True,
        "click": True,
        "select": True,
        "brush": True,
        "crosshair": True,
        "view_change": True,
        "link_group": "dashboard",
        "link_axes": ["x"],
    }


def test_chart_callbacks_enable_matching_event_streams():
    chart = fc.chart(
        fc.scatter(x=[1.0, 2.0], y=[2.0, 3.0]),
        on_hover=lambda row: row,
        on_click=lambda row: row,
        on_brush=lambda brush: brush,
        on_select=lambda sel: sel,
        on_view_change=lambda view: view,
    )

    spec, _ = chart.figure().build_payload()

    assert spec["interaction"] == {
        "hover": True,
        "click": True,
        "brush": True,
        "select": True,
        "view_change": True,
    }


def test_bad_interaction_options_do_not_cache_partial_chart_figure():
    chart = fc.chart(
        fc.scatter(x=[1.0], y=[2.0]),
        fc.interaction_config(click="yes"),
    )

    with pytest.raises(ValueError, match="interaction click"):
        chart.figure()
    assert chart._figure is None

    chart = fc.chart(
        fc.scatter(x=[1.0], y=[2.0]),
        fc.interaction_config(view_change="yes"),
    )

    with pytest.raises(ValueError, match="interaction view_change"):
        chart.figure()
    assert chart._figure is None

    chart = fc.chart(
        fc.scatter(x=[1.0], y=[2.0]),
        fc.interaction_config(link_group="dash", link_axes=("x", "z")),
    )
    with pytest.raises(ValueError, match="link_axes"):
        chart.figure()
    assert chart._figure is None


def test_legend_and_tooltip_accept_render_keyword_components():
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    chart = fc.chart(
        fc.scatter(x=[1.0], y=[2.0]),
        fc.legend(render=legend_component),
        fc.tooltip(render=tooltip_component),
    )

    assert chart.chrome_components()["legend"] is legend_component
    assert chart.chrome_components()["tooltip"] is tooltip_component
    spec, _ = chart.figure().build_payload()
    assert "show_tooltip" not in spec
    assert spec["show_legend"] is True


def test_component_style_validation_rejects_non_serializable_values():
    with pytest.raises(ValueError, match="chart class_names"):
        fc.chart(fc.scatter(x=[1.0], y=[2.0]), class_names={"legend": 2})
    with pytest.raises(ValueError, match="chart style"):
        fc.chart(fc.scatter(x=[1.0], y=[2.0]), style={"--bad": np.inf})
    with pytest.raises(ValueError, match="tooltip fields"):
        fc.tooltip(fields=["x", 2])
    with pytest.raises(TypeError, match="at most one"):
        fc.legend(FakeReflexComponent("a"), FakeReflexComponent("b"))
    with pytest.raises(TypeError, match="component child with render"):
        fc.tooltip(FakeReflexComponent("a"), render=FakeReflexComponent("b"))


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
    with pytest.raises(ValueError, match=r"scatter\.y column 'missing' not found"):
        fc.scatter_chart(fc.scatter(x="a", y="missing", data=df)).figure()


@pytest.mark.parametrize(
    ("chart", "match"),
    [
        (
            lambda df: fc.scatter_chart(fc.scatter(x="a", y="b", color="missing"), data=df),
            r"scatter\.color column 'missing' not found",
        ),
        (
            lambda df: fc.scatter_chart(fc.scatter(x="a", y="b", size="missing"), data=df),
            r"scatter\.size column 'missing' not found",
        ),
        (
            lambda df: fc.area_chart(fc.area(x="a", y="b", base="missing"), data=df),
            r"area\.base column 'missing' not found",
        ),
        (
            lambda df: fc.histogram_chart(fc.histogram(values="missing"), data=df),
            r"histogram\.values column 'missing' not found",
        ),
        (
            lambda df: fc.heatmap_chart(fc.heatmap(z="missing"), data=df),
            r"heatmap\.z column 'missing' not found",
        ),
        (
            lambda df: fc.bar_chart(fc.bar(x="label", y="value", base="missing"), data=df),
            r"bar\.base column 'missing' not found",
        ),
        (
            lambda df: fc.column_chart(fc.column(x="label", y="value", base="missing"), data=df),
            r"column\.base column 'missing' not found",
        ),
    ],
)
def test_component_data_key_errors_name_mark_field(chart, match):
    df = FakeFrame(
        {
            "a": np.arange(3.0),
            "b": np.arange(3.0) + 1.0,
            "label": np.array(["a", "b", "c"]),
            "value": np.array([3.0, 2.0, 4.0]),
        }
    )

    with pytest.raises(ValueError, match=match):
        chart(df).figure()


def test_failed_mark_application_does_not_cache_partial_chart_figure():
    df = FakeFrame({"x": np.arange(3.0), "y": np.arange(3.0) * 2})
    second = fc.scatter(x="x", y="missing")
    chart = fc.scatter_chart(
        fc.line(x="x", y="y", name="first"),
        second,
        data=df,
    )

    with pytest.raises(ValueError, match="not found"):
        chart.figure()
    assert chart._figure is None

    second.y = "y"
    fig = chart.figure()

    assert chart.figure() is fig
    assert [trace.kind for trace in fig.traces] == ["line", "scatter"]
    assert [trace.name for trace in fig.traces] == ["first", None]


def test_column_name_without_data_errors():
    with pytest.raises(ValueError, match=r"scatter\.x.*no data"):
        fc.scatter_chart(fc.scatter(x="a", y="b")).figure()


def test_unknown_mark_kind_failure_does_not_cache_partial_chart_figure():
    mark = fc.line([0.0, 1.0], [1.0, 2.0])
    mark.kind = "not-real"
    chart = fc.line_chart(mark)

    with pytest.raises(TypeError, match="not-real"):
        chart.figure()
    assert chart._figure is None

    mark.kind = "line"
    fig = chart.figure()

    assert chart.figure() is fig
    assert [trace.kind for trace in fig.traces] == ["line"]


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


def test_component_text_metadata_errors_do_not_cache_partial_chart_figure():
    chart = fc.scatter_chart(fc.scatter(x=np.arange(3.0), y=np.arange(3.0)), title=123)

    with pytest.raises(ValueError, match="title must be a string or None"):
        chart.figure()
    assert chart._figure is None

    chart.title = "ok"
    fig = chart.figure()
    assert chart.figure() is fig
    assert fig.title == "ok"

    bad_axis = fc.x_axis(label="ok")
    bad_axis.label = 42
    chart2 = fc.scatter_chart(fc.scatter(x=np.arange(3.0), y=np.arange(3.0)), bad_axis)
    with pytest.raises(ValueError, match="x_label must be a string or None"):
        chart2.figure()
    assert chart2._figure is None

    chart3 = fc.scatter_chart(fc.scatter(x=np.arange(3.0), y=np.arange(3.0), name=123))
    with pytest.raises(ValueError, match="scatter name must be a string or None"):
        chart3.figure()
    assert chart3._figure is None


def test_component_axis_types_emit_log_domain_reverse_and_format():
    fig = fc.scatter_chart(
        fc.scatter(x=np.array([1.0, 10.0, 100.0]), y=np.arange(3.0)),
        fc.x_axis(type_="linear"),
        fc.y_axis(type_="time"),
    ).figure()
    assert len(fig.traces) == 1

    chart = fc.scatter_chart(
        fc.scatter(x=np.array([1.0, 10.0, 100.0]), y=np.array([0.2, 0.4, 0.8])),
        fc.x_axis(
            type_="log",
            domain=(1.0, 100.0),
            reverse=True,
            format=".0f",
            style={"grid_color": "rgba(37,99,235,.2)", "tick_color": "#1d4ed8"},
        ),
        fc.y_axis(
            domain=(0.0, 1.0),
            format=".1%",
            style={"axis_color": "#dc2626", "label_size": 13},
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["scale"] == "log"
    assert spec["x_axis"]["domain"] == [1.0, 100.0]
    assert spec["x_axis"]["range"] == [100.0, 1.0]
    assert spec["x_axis"]["reverse"] is True
    assert spec["x_axis"]["format"] == ".0f"
    assert spec["x_axis"]["style"] == {
        "grid_color": "rgba(37,99,235,.2)",
        "tick_color": "#1d4ed8",
    }
    assert spec["y_axis"]["domain"] == [0.0, 1.0]
    assert spec["y_axis"]["format"] == ".1%"
    assert spec["y_axis"]["style"] == {"axis_color": "#dc2626", "label_size": 13}


def test_component_axis_label_position_controls_emit_to_payload():
    chart = fc.chart(
        fc.scatter(x=np.arange(3.0), y=np.arange(3.0)),
        fc.x_axis(
            label="custom x",
            label_position="inside-end",
            label_offset=8,
            label_angle=12,
        ),
        fc.y_axis(
            label="custom y",
            label_position={"left": 18, "top": "52%", "transform": "rotate(-75deg)"},
            label_offset=-4,
            label_angle=-75,
        ),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["label_position"] == "inside_end"
    assert spec["x_axis"]["label_offset"] == 8.0
    assert spec["x_axis"]["label_angle"] == 12.0
    assert spec["y_axis"]["label_position"] == {
        "left": 18,
        "top": "52%",
        "transform": "rotate(-75deg)",
    }
    assert spec["y_axis"]["label_offset"] == -4.0
    assert spec["y_axis"]["label_angle"] == -75.0


def test_component_axis_label_position_rejects_invalid_values():
    with pytest.raises(ValueError, match="label_position"):
        fc.x_axis(label_position="middle-ish")
    with pytest.raises(ValueError, match="label_offset"):
        fc.y_axis(label_offset=True)
    with pytest.raises(ValueError, match="label_angle"):
        fc.y_axis(label_angle=np.nan)


def test_component_axis_tick_layout_controls_emit_to_payload():
    chart = fc.chart(
        fc.line(x=np.arange(3.0), y=np.arange(3.0)),
        fc.x_axis(
            tick_count=4,
            tick_label_angle=-35,
            tick_label_strategy="stagger",
            tick_label_min_gap=12,
        ),
        fc.y_axis(tick_count=3, tick_label_strategy="hide"),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["tick_count"] == 4
    assert spec["x_axis"]["tick_label_angle"] == -35.0
    assert spec["x_axis"]["tick_label_strategy"] == "stagger"
    assert spec["x_axis"]["tick_label_min_gap"] == 12.0
    assert spec["y_axis"]["tick_count"] == 3
    assert spec["y_axis"]["tick_label_strategy"] == "hide"

    with pytest.raises(ValueError, match="tick_count"):
        fc.x_axis(tick_count=0)
    with pytest.raises(ValueError, match="tick_label_strategy"):
        fc.x_axis(tick_label_strategy="squish")
    with pytest.raises(ValueError, match="tick_label_min_gap"):
        fc.y_axis(tick_label_min_gap=-1)


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


def test_component_xy_datetime_object_axes_do_not_become_categories():
    x = np.array(
        [
            np.datetime64("2026-01-01").astype(object),
            np.datetime64("2026-01-02").astype(object),
            np.datetime64("2026-01-03").astype(object),
        ],
        dtype=object,
    )
    chart = fc.chart(fc.line(x=x, y=np.array([1.0, 2.0, 3.0])))

    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["kind"] == "time"
    assert "categories" not in spec["x_axis"]


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


def test_component_to_html_escapes_user_strings_across_public_surface(tmp_path):
    evil = "</script><img src=x onerror=alert(1)>&\u2028\u2029"
    also_evil = "<b data-x='1'>&</b>"
    target = tmp_path / "component.html"
    df = FakeFrame(
        {
            "label": np.array([evil, "safe"], dtype=object),
            "values": np.array([[1.0, 3.0], [2.0, 4.0]], dtype=np.float64),
        }
    )
    chart = fc.bar_chart(
        fc.bar(
            x="label",
            y="values",
            series=[evil, also_evil],
            colors=["#111111", "#222222"],
        ),
        fc.text(evil, 2.0, evil, class_name=also_evil, style={"color": "#111111"}),
        fc.x_axis(label=evil),
        fc.y_axis(label=also_evil),
        title=evil,
        data=df,
    )

    html = chart.to_html(target)
    spec_literal = _inline_spec_literal(html)

    assert target.read_text(encoding="utf-8") == html
    assert "&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt;&amp;" in html.split("</head>", 1)[0]
    assert "</script><img" not in html.split("<body>", 1)[1]
    assert "<b data-x=" not in html.split("<body>", 1)[1]
    assert "<" not in spec_literal
    assert ">" not in spec_literal
    assert "&" not in spec_literal
    assert "\\u003c/script\\u003e" in spec_literal
    assert "\\u0026" in spec_literal
    assert "\\u2028" in spec_literal
    assert "\\u2029" in spec_literal

    decoded = json.loads(spec_literal)
    assert decoded["title"] == evil
    assert decoded["x_axis"]["label"] == evil
    assert decoded["y_axis"]["label"] == also_evil
    assert evil in decoded["x_axis"]["categories"]
    assert [trace["name"] for trace in decoded["traces"]] == [evil, also_evil]
    assert decoded["annotations"][0]["text"] == evil
    assert decoded["annotations"][0]["class_name"] == also_evil


def test_component_to_png_delegates_to_composed_figure(monkeypatch):
    chart = fc.line_chart(fc.line([0, 1], [1, 2]))
    seen = {}

    def fake_to_png(
        self,
        path=None,
        *,
        width=None,
        height=None,
        scale=2.0,
        chromium=None,
        sandbox=True,
    ):
        seen.update(
            {
                "figure": self,
                "path": path,
                "width": width,
                "height": height,
                "scale": scale,
                "chromium": chromium,
                "sandbox": sandbox,
            }
        )
        return b"PNG"

    monkeypatch.setattr("fastcharts.figure.Figure.to_png", fake_to_png)

    data = chart.to_png(
        "out.png",
        width=320,
        height=200,
        scale=1.5,
        chromium="/chrome",
        sandbox=False,
    )

    assert data == b"PNG"
    assert seen == {
        "figure": chart.figure(),
        "path": "out.png",
        "width": 320,
        "height": 200,
        "scale": 1.5,
        "chromium": "/chrome",
        "sandbox": False,
    }


def test_widget_failure_does_not_cache_partial_widget(monkeypatch):
    chart = fc.line_chart(fc.line([0.0, 1.0], [1.0, 2.0]))
    fig = chart.figure()
    calls = {"count": 0}

    class FlakyWidget:
        def __init__(
            self,
            figure,
            *,
            on_hover=None,
            on_click=None,
            on_brush=None,
            on_select=None,
            on_view_change=None,
        ):
            calls["count"] += 1
            self.figure = figure
            self.on_hover = on_hover
            self.on_click = on_click
            self.on_brush = on_brush
            self.on_select = on_select
            self.on_view_change = on_view_change
            if calls["count"] == 1:
                raise RuntimeError("synthetic widget failure")

    monkeypatch.setattr("fastcharts.widget.FigureWidget", FlakyWidget)

    with pytest.raises(RuntimeError, match="synthetic widget failure"):
        chart.widget()
    assert chart._widget is None

    widget = chart.widget()

    assert chart._widget is widget
    assert widget.figure is fig
    assert calls["count"] == 2


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


def test_dual_axis_component_payload_binds_traces_to_secondary_axis():
    chart = fc.chart(
        fc.line(x=np.arange(3.0), y=np.array([1.0, 2.0, 3.0]), name="left"),
        fc.line(x=np.arange(3.0), y=np.array([20.0, 40.0, 80.0]), name="right", y_axis="y2"),
        fc.y_axis(label="primary"),
        fc.y_axis(id="y2", label="secondary", side="right", domain=(0.0, 100.0), format=",.1f"),
    )

    spec, _ = chart.figure().build_payload()

    assert set(spec["axes"]) >= {"x", "y", "y2"}
    assert spec["axes"]["y2"]["label"] == "secondary"
    assert spec["axes"]["y2"]["side"] == "right"
    assert spec["axes"]["y2"]["domain"] == [0.0, 100.0]
    assert spec["axes"]["y2"]["format"] == ",.1f"
    assert [trace["y_axis"] for trace in spec["traces"]] == ["y", "y2"]

    with pytest.raises(ValueError, match=r"matching fc\.y_axis"):
        fc.chart(
            fc.line(x=np.arange(3.0), y=np.arange(3.0), y_axis="y2"),
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
