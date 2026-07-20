"""Reflex-style composition API: xy.scatter_chart(xy.scatter(...), xy.x_axis(...)).

Verifies the component tree builds the same Figure the fluent API would, plus
data= column-name resolution, event-prop wiring, and box-select (§34)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

import xy
import xy.components as components_module
import xy.export as export_module
from xy._figure import Figure
from xy.components import (
    Annotation,
    Axis,
    Chart,
    Colorbar,
    Interaction,
    Legend,
    Mark,
    Modebar,
    Theme,
    Tooltip,
)
from xy.widget import Selection


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


class LeakyCallback:
    """Callable whose repr would be obvious if it leaked into exported specs."""

    def __init__(self, name: str):
        self.name = name

    def __call__(self, payload):
        return payload

    def __repr__(self) -> str:
        return f"<LeakyCallback {self.name}>"


def _inline_spec_literal(html: str) -> str:
    body = html.split("<body>", 1)[1]
    return body.rsplit("const spec = ", 1)[1].split(";\n  const buf", 1)[0]


def test_factories_return_components():
    assert isinstance(xy.scatter(x=[1], y=[2]), Mark)
    assert xy.scatter(x=[1], y=[2]).kind == "scatter"
    assert xy.line(x=[1], y=[2]).kind == "line"
    assert xy.area(x=[1], y=[2]).kind == "area"
    assert xy.histogram(values=[1, 2, 3]).kind == "histogram"
    assert xy.hist(values=[1, 2, 3]).kind == "histogram"
    assert xy.bar(x=["a"], y=[1]).kind == "bar"
    assert xy.column(x=["a"], y=[1]).kind == "column"
    assert xy.heatmap(z=[[1]]).kind == "heatmap"
    assert isinstance(xy.arrow(0.0, 1.0, 2.0, 3.0), Annotation)
    assert isinstance(xy.callout(0.0, 1.0, "label"), Annotation)
    assert isinstance(xy.vline(1.0), Annotation)
    assert isinstance(xy.hline(1.0), Annotation)
    assert isinstance(xy.x_band(0.0, 1.0), Annotation)
    assert isinstance(xy.y_band(0.0, 1.0), Annotation)
    assert isinstance(xy.text(0.0, 1.0, "label"), Annotation)
    assert isinstance(xy.label(0.0, 1.0, "label"), Annotation)
    assert isinstance(xy.marker(0.0, 1.0), Annotation)
    assert isinstance(xy.threshold(1.0), Annotation)
    assert isinstance(xy.threshold_zone(0.0, 1.0), Annotation)
    assert isinstance(xy.tooltip(fields=["x"]), Tooltip)
    assert isinstance(xy.colorbar(show=False), Colorbar)
    assert isinstance(xy.modebar(show=False), Modebar)
    assert isinstance(xy.theme(style={"--chart-bg": "transparent"}), Theme)
    assert isinstance(xy.interaction_config(crosshair=True), Interaction)
    assert not hasattr(xy, "mark_style")
    chart = xy.scatter_chart(xy.scatter(x=[1.0], y=[2.0]))
    assert isinstance(chart, Chart)
    assert isinstance(xy.chart(xy.scatter(x=[1.0], y=[2.0])), Chart)


def test_neutral_chart_overlays_marks():
    x = np.arange(20.0)
    chart = xy.chart(
        xy.scatter(x=x, y=np.sin(x), name="points"),
        xy.line(x=x, y=np.cos(x), name="fit"),
        xy.x_axis(label="x"),
        xy.y_axis(label="y"),
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
    line_over_scatter = xy.chart(
        xy.scatter(x=x, y=np.sin(x), name="samples"),
        xy.line(x=x, y=np.sin(x) * 0.8, name="trend", color="#111111"),
        xy.legend(),
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
    bars_plus_line = xy.chart(
        xy.bar(x="month", y="actual", data=data, name="actual"),
        xy.line(x="month", y="target", data=data, name="target", color="#dc2626"),
        xy.x_axis(label="month"),
    )
    fig = bars_plus_line.figure()
    spec, _ = fig.build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["bar", "line"]
    assert spec["x_axis"]["kind"] == "category"
    assert spec["x_axis"]["categories"] == ["Jan", "Feb", "Mar", "Apr"]
    np.testing.assert_array_equal(fig.traces[1].x.values, [0.0, 1.0, 2.0, 3.0])

    area_plus_points = xy.chart(
        xy.area(x=x, y=np.cos(x) + 2.0, name="range", color="#0891b2"),
        xy.scatter(x=x, y=np.cos(x) + 2.0, name="samples", size=8.0, color="#0f172a"),
    )
    spec, _ = area_plus_points.figure().build_payload()
    assert [trace["kind"] for trace in spec["traces"]] == ["area", "scatter"]


def test_heatmap_can_compose_with_category_annotations():
    chart = xy.chart(
        xy.heatmap(
            z=np.array([[0.1, 0.8], [0.4, 0.95]]),
            x=["Mon", "Tue"],
            y=["AM", "PM"],
            name="load",
        ),
        xy.vline("Tue", text="deploy", color="#ef4444", width=2.0),
        xy.hline("PM", text="peak"),
        xy.x_band("Mon", "Tue", text="workweek", opacity=0.2),
        xy.text("Tue", "PM", "max", dx=4.0, dy=-8.0, anchor="middle"),
        xy.arrow("Mon", "AM", "Tue", "PM", text="flow", color="#0f172a"),
        xy.callout("Tue", "AM", "watch", dx=18.0, dy=-16.0),
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
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0, 3.0], y=[2.0, 5.0, 4.0]),
        xy.marker(
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
        xy.label(3.0, 4.0, "last", anchor="end"),
        xy.threshold(4.5, text="target"),
        xy.threshold_zone(4.0, 6.0, text="warning"),
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
        xy.chart(xy.scatter(x=[1.0], y=[1.0]), xy.marker(1.0, 1.0, symbol="pin")).figure()
    with pytest.raises(ValueError, match="threshold axis"):
        xy.threshold(1.0, axis="z")


def test_annotation_label_opacity_is_independent_from_geometry_opacity():
    chart = xy.chart(
        xy.x_band(
            1.0,
            2.0,
            text="window",
            opacity=0.12,
            style={"label_opacity": 0.85},
        )
    )

    spec, _ = chart.figure().build_payload()
    style = spec["annotations"][0]["style"]

    assert style["opacity"] == 0.12
    assert style["label_opacity"] == 0.85

    with pytest.raises(ValueError, match="label_opacity"):
        xy.chart(xy.x_band(1.0, 2.0, text="window", style={"label_opacity": 1.1})).figure()


def test_layered_tooltip_sources_keep_fields_tied_to_their_traces():
    data = FakeFrame(
        {
            "month": np.array(["Jan", "Feb", "Mar"]),
            "bookings": np.array([12.0, 18.0, 16.0]),
            "target": np.array([14.0, 15.0, 17.0]),
            "sample": np.array([13.0, 19.0, 15.0]),
        }
    )
    chart = xy.chart(
        xy.bar(x="month", y="bookings", data=data, name="bookings"),
        xy.scatter(x="month", y="sample", data=data, name="sample"),
        xy.line(x="month", y="target", data=data, name="target"),
        xy.tooltip(
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
    marker = xy.vline("Wed")
    chart = xy.chart(
        xy.heatmap(z=np.array([[1.0, 2.0]]), x=["Mon", "Tue"], y=["AM"]),
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


def test_failed_declarative_mark_does_not_leak_axis_categories():
    fig = Figure()
    mark = xy.scatter(x=["new-category"], y=[1.0], color=np.array([1.0, 2.0]))

    with pytest.raises(ValueError, match="color array"):
        components_module._apply_scatter(fig, mark, None)

    assert fig.traces == []
    assert fig._axis_categories == {}


def test_component_api_default_payload_matches_fluent_figure():
    x = np.arange(16.0)
    y = x * 2

    component = xy.chart(xy.line(x=x, y=y)).figure()
    fluent = Figure().line(x, y)
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
    chart = xy.chart(
        xy.scatter(
            x="feature_a",
            y="feature_b",
            color="segment",
            data=df,
            name="accounts",
            class_name="xy-mark-accounts",
        ),
        xy.legend(class_name="legend-node", style={"max-height": 220}),
        xy.tooltip(
            fields=["feature_a", "feature_b", "segment"],
            title="{segment}",
            format={"feature_a": ".2f"},
            class_name="tooltip-node",
            style={"background-color": "black"},
        ),
        xy.modebar(
            show=False,
            class_name="modebar-node",
            button_class_name="modebar-button-node",
            button_style={"border-radius": 4},
        ),
        xy.theme(
            plot_background="transparent",
            grid_color="rgba(0,0,0,.1)",
            selection_fill="rgba(37,99,235,.14)",
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
    assert spec["traces"][0]["style"]["class_name"] == "xy-mark-accounts"


def test_theme_background_separates_figure_and_plot():
    # mpl parity: background= is the figure facecolor (root CSS background,
    # margins included); plot_background= is the axes facecolor (--chart-bg,
    # plot rect only).
    chart = xy.scatter_chart(
        xy.scatter(x=[1.0], y=[2.0]),
        xy.theme(background="#000000", plot_background="#111111"),
    )
    spec, _ = chart.figure().build_payload()
    style = spec["dom"]["style"]
    assert style["background"] == "#000000"
    assert style["--chart-bg"] == "#111111"


def test_figure_dom_class_strings_covers_every_class_carrying_surface():
    """`Figure.dom_class_strings()` is the Tailwind scan inventory (see its
    docstring): chart root, chrome slots, per-mark styles, annotation nodes."""
    chart = xy.chart(
        xy.line([0, 1], [1, 2], class_name="mark-node"),
        xy.line([0, 1], [2, 3], class_name="mark-node"),  # dedupe, keep order
        xy.vline(0.5, text="release", class_name="annotation-node"),
        xy.legend(class_name="legend-node"),
        class_name="root-node",
        class_names={"title": "title-slot"},
    )

    class_strings = chart.figure().dom_class_strings()

    for class_string in ("root-node", "title-slot", "legend-node", "mark-node", "annotation-node"):
        assert class_string in class_strings, class_strings
    assert len(class_strings) == len(set(class_strings)), class_strings
    assert class_strings[0] == "root-node", class_strings


def test_declarative_core_contract_for_layered_axis_chrome_and_interaction():
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    colorbar_component = FakeReflexComponent("colorbar")
    data = FakeFrame(
        {
            "month": np.array(["Jan", "Feb", "Mar"]),
            "revenue": np.array([40.0, 52.0, 61.0]),
            "latency": np.array([100.0, 70.0, 30.0]),
        }
    )

    chart = xy.chart(
        xy.bar(
            x="month",
            y="revenue",
            data=data,
            name="revenue",
            class_name="revenue-bars",
        ),
        xy.line(
            x="month",
            y="latency",
            data=data,
            name="latency",
            y_axis="y2",
            color="#dc2626",
        ),
        xy.vline("Feb", text="campaign", color="#7c3aed"),
        xy.x_axis(
            label="month",
            tick_count=3,
            tick_label_strategy="rotate",
        ),
        xy.y_axis(
            label="revenue",
            domain=(0.0, 100.0),
            format="$,.0f",
            side="left",
        ),
        xy.y_axis(
            id="y2",
            label="latency",
            type_="log",
            domain=(10.0, 1000.0),
            reverse=True,
            format=".0f",
            side="right",
            label_position={"right": 18, "top": "50%"},
            style={"axis_color": "#dc2626"},
        ),
        xy.legend(
            legend_component,
            class_name="legend-node",
            style={"max-height": 180},
        ),
        xy.tooltip(
            tooltip_component,
            show=False,
            fields=["month", "revenue", "latency"],
            title="{month}",
            class_name="tooltip-node",
            style={"background": "linear-gradient(red,blue)"},
        ),
        xy.colorbar(
            colorbar_component,
            class_name="colorbar-node",
            style={"font-size": 12},
        ),
        xy.modebar(
            show=True,
            class_name="modebar-node",
            button_class_name="modebar-button",
        ),
        xy.theme(plot_background="transparent", crosshair_color="#0f172a"),
        xy.interaction_config(
            hover=True,
            click=True,
            brush=True,
            crosshair=True,
            pan=True,
            zoom=True,
            view_change=True,
            link_group="ops",
            link_axes=("x",),
        ),
        title="ops overview",
        class_name="chart-root",
        class_names={"legend": "legend-slot"},
        style={"--chart-axis": "#111827"},
        width="100%",
        height=430,
    )

    assert chart.chrome_components() == {
        "legend": legend_component,
        "tooltip": tooltip_component,
        "colorbar": colorbar_component,
    }

    spec, _ = chart.figure().build_payload()

    assert spec["width"] == "100%"
    assert spec["height"] == 430
    assert spec["show_legend"] is True
    assert spec["show_tooltip"] is False
    assert spec["dom"]["class_names"]["colorbar"] == "colorbar-node"
    assert spec["dom"]["styles"]["colorbar"] == {"font-size": 12}
    assert [trace["kind"] for trace in spec["traces"]] == ["bar", "line"]
    assert [trace["y_axis"] for trace in spec["traces"]] == ["y", "y2"]
    assert spec["traces"][0]["style"]["class_name"] == "revenue-bars"
    assert spec["axes"]["x"]["kind"] == "category"
    assert spec["axes"]["x"]["categories"] == ["Jan", "Feb", "Mar"]
    assert spec["axes"]["x"]["tick_count"] == 3
    assert spec["axes"]["x"]["tick_label_strategy"] == "rotate"
    assert spec["axes"]["y"]["domain"] == [0.0, 100.0]
    assert spec["axes"]["y"]["format"] == "$,.0f"
    assert spec["axes"]["y2"] == {
        "id": "y2",
        "kind": "linear",
        "label": "latency",
        "range": [1000.0, 10.0],
        "side": "right",
        "label_position": {"right": 18, "top": "50%"},
        "scale": "log",
        "reverse": True,
        "domain": [10.0, 1000.0],
        "format": ".0f",
        "style": {"axis_color": "#dc2626"},
    }
    assert spec["annotations"] == [
        {
            "text": "campaign",
            "style": {"color": "#7c3aed", "width": 1.5, "opacity": 1.0},
            "kind": "rule",
            "axis": "x",
            "value": 1.0,
        }
    ]
    assert spec["dom"] == {
        "class_name": "chart-root",
        "class_names": {
            "legend": "legend-slot legend-node",
            "modebar": "modebar-node",
            "modebar_button": "modebar-button",
            "tooltip": "tooltip-node",
            "colorbar": "colorbar-node",
        },
        "style": {
            "--chart-bg": "transparent",
            "--chart-crosshair": "#0f172a",
            "--chart-axis": "#111827",
        },
        "styles": {
            "legend": {"max-height": 180},
            "tooltip": {"background": "linear-gradient(red,blue)"},
            "colorbar": {"font-size": 12},
        },
    }
    assert spec["tooltip"]["fields"] == ["month", "revenue", "latency"]
    assert spec["tooltip"]["sources"] == {
        "month": [{"trace": 0, "channel": "x"}, {"trace": 1, "channel": "x"}],
        "revenue": [{"trace": 0, "channel": "y"}],
        "latency": [{"trace": 1, "channel": "y"}],
    }
    assert spec["interaction"] == {
        "hover": True,
        "click": True,
        "brush": True,
        "crosshair": True,
        "pan": True,
        "zoom": True,
        "view_change": True,
        "link_group": "ops",
        "link_axes": ["x"],
    }


def test_interaction_component_disables_pan_and_zoom():
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[2.0, 3.0]),
        xy.interaction_config(pan=False, zoom=False),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["interaction"] == {"pan": False, "zoom": False}


def test_chart_level_pan_and_zoom_kwargs_build_declarative_spec():
    chart = xy.bar_chart(
        xy.bar(x=["A", "B"], y=[1.0, 2.0]),
        pan=False,
        zoom=False,
    )

    spec, _ = chart.figure().build_payload()

    assert spec["interaction"] == {"pan": False, "zoom": False}


def test_legend_and_tooltip_accept_opaque_framework_components_without_serializing():
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[2.0, 3.0], name="points"),
        xy.legend(legend_component, show=False),
        xy.tooltip(
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


def test_colorbar_show_false_clears_generated_colorbar_options(monkeypatch):
    original = components_module._MARK_APPLIERS["line"]

    def apply_with_colorbar(fig, mark, data):
        original(fig, mark, data)
        fig.colorbar_options = {"domain": [0.0, 1.0], "colormap": "viridis"}

    monkeypatch.setitem(components_module._MARK_APPLIERS, "line", apply_with_colorbar)
    chart = xy.chart(
        xy.line(x=[0.0, 1.0], y=[1.0, 2.0]),
        xy.colorbar(show=False),
    )

    figure = chart.figure()
    spec, _ = figure.build_payload()
    assert figure.colorbar_options is None
    assert "colorbar" not in spec


def test_declarative_chart_keeps_notebook_export_and_framework_chrome_contract(
    monkeypatch,
    tmp_path,
):
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    events = {
        "hover": lambda row: row,
        "click": lambda row: row,
        "brush": lambda brush: brush,
        "select": lambda selection: selection,
        "view": lambda view: view,
    }
    data = FakeFrame(
        {
            "activation": np.array([0.11, 0.24, 0.38]),
            "retention": np.array([0.52, 0.61, 0.73]),
            "segment": np.array(["enterprise", "growth", "enterprise"]),
        }
    )
    chart = xy.chart(
        xy.scatter(
            x="activation",
            y="retention",
            color="segment",
            size=12,
            data=data,
            name="accounts",
            class_name="tw-mark-accounts",
        ),
        xy.line(
            x="activation",
            y="retention",
            data=data,
            name="trend",
            color="var(--chart-trend)",
        ),
        xy.vline(
            0.24,
            text="release",
            color="#7c3aed",
            class_name="tw-release-marker",
        ),
        xy.callout(
            0.38,
            0.73,
            "best cohort",
            dx=-64,
            dy=-24,
            color="#0f172a",
            class_name="tw-callout",
        ),
        xy.x_axis(label="activation", format=".0%"),
        xy.y_axis(label="retention", format=".0%"),
        xy.legend(
            legend_component,
            show=False,
            class_name="tw-legend",
            style={"display": "grid"},
        ),
        xy.tooltip(
            tooltip_component,
            show=False,
            fields=["activation", "retention", "segment"],
            title="{segment}",
            format={"activation": ".1%", "retention": ".1%"},
            class_name="tw-tooltip",
            style={"background": "linear-gradient(135deg,#020617,#2563eb)"},
        ),
        xy.modebar(show=False, class_name="tw-modebar"),
        xy.theme(grid_color="rgba(148,163,184,.28)"),
        xy.interaction_config(hover=True, click=True, brush=True, crosshair=True),
        title="Custom Reflex legend + tooltip",
        width="100%",
        height=360,
        class_name="h-[360px] w-full rounded-md border border-slate-200",
        class_names={"legend": "right-3 top-3", "tooltip": "pointer-events-none"},
        style={"--chart-trend": "#dc2626", "--chart-axis": "currentColor"},
        on_hover=events["hover"],
        on_click=events["click"],
        on_brush=events["brush"],
        on_select=events["select"],
        on_view_change=events["view"],
    )

    for name in (
        "to_html",
        "html",
        "to_png",
        "widget",
        "show",
        "memory_report",
        "chrome_components",
        "reflex_components",
        "_repr_html_",
    ):
        assert callable(getattr(chart, name))

    chrome = chart.chrome_components()
    assert chrome == {"legend": legend_component, "tooltip": tooltip_component}
    assert chart.reflex_components() == chrome

    html_path = tmp_path / "chart.html"
    html = chart.to_html(html_path)
    assert html_path.read_text(encoding="utf-8") == html
    assert "FakeReflexComponent" not in html
    assert "Custom Reflex legend + tooltip" in html

    alias_path = tmp_path / "chart-alias.html"
    assert chart.html(alias_path) == alias_path.read_text(encoding="utf-8")
    repr_html = chart._repr_html_()
    assert repr_html.startswith('<iframe class="xy-notebook-frame"')
    assert "FakeReflexComponent" not in repr_html
    assert "Custom Reflex legend + tooltip" in repr_html

    spec = json.loads(_inline_spec_literal(html))
    assert spec["show_legend"] is False
    assert spec["show_tooltip"] is False
    assert spec["show_modebar"] is False
    assert [annotation["kind"] for annotation in spec["annotations"]] == ["rule", "callout"]
    assert spec["annotations"][0] == {
        "text": "release",
        "class_name": "tw-release-marker",
        "style": {"color": "#7c3aed", "width": 1.5, "opacity": 1.0},
        "kind": "rule",
        "axis": "x",
        "value": 0.24,
    }
    assert spec["annotations"][1] == {
        "text": "best cohort",
        "class_name": "tw-callout",
        "style": {"color": "#0f172a", "width": 1.5, "opacity": 1.0},
        "kind": "callout",
        "x": 0.38,
        "y": 0.73,
        "dx": -64.0,
        "dy": -24.0,
        "anchor": "start",
    }
    assert spec["width"] == "100%"
    assert spec["height"] == 360
    assert spec["dom"]["class_name"] == "h-[360px] w-full rounded-md border border-slate-200"
    assert spec["dom"]["class_names"]["legend"] == "right-3 top-3 tw-legend"
    assert spec["dom"]["class_names"]["tooltip"] == "pointer-events-none tw-tooltip"
    assert spec["dom"]["class_names"]["modebar"] == "tw-modebar"
    assert spec["dom"]["style"] == {
        "--chart-grid": "rgba(148,163,184,.28)",
        "--chart-trend": "#dc2626",
        "--chart-axis": "currentColor",
    }
    assert spec["dom"]["styles"]["legend"] == {"display": "grid"}
    assert spec["dom"]["styles"]["tooltip"] == {
        "background": "linear-gradient(135deg,#020617,#2563eb)"
    }
    assert spec["traces"][0]["style"]["class_name"] == "tw-mark-accounts"
    assert spec["traces"][1]["style"]["color"] == "var(--chart-trend)"
    assert spec["tooltip"]["fields"] == ["activation", "retention", "segment"]
    assert spec["tooltip"]["format"] == {"activation": ".1%", "retention": ".1%"}

    report = chart.memory_report()
    assert report["transport_bytes_first_paint"] > 0
    assert report["backend"] in {"native", "numpy"}

    class CapturingWidget:
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
            self.figure = figure
            self.on_hover = on_hover
            self.on_click = on_click
            self.on_brush = on_brush
            self.on_select = on_select
            self.on_view_change = on_view_change

    monkeypatch.setattr("xy.widget.FigureWidget", CapturingWidget)

    widget = chart.widget()
    assert chart.show() is widget
    assert widget.figure is chart.figure()
    assert widget.on_hover is events["hover"]
    assert widget.on_click is events["click"]
    assert widget.on_brush is events["brush"]
    assert widget.on_select is events["select"]
    assert widget.on_view_change is events["view"]


def test_interaction_component_builds_declarative_spec():
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[2.0, 3.0], name="points"),
        xy.interaction_config(
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
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[2.0, 3.0]),
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


def test_chart_callbacks_are_python_only_and_do_not_serialize_to_html(monkeypatch):
    callbacks = {
        "hover": LeakyCallback("hover"),
        "click": LeakyCallback("click"),
        "brush": LeakyCallback("brush"),
        "select": LeakyCallback("select"),
        "view": LeakyCallback("view"),
    }
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[2.0, 3.0], name="points"),
        xy.legend(legend_component, show=False),
        xy.tooltip(tooltip_component, show=False, fields=["x", "y"]),
        on_hover=callbacks["hover"],
        on_click=callbacks["click"],
        on_brush=callbacks["brush"],
        on_select=callbacks["select"],
        on_view_change=callbacks["view"],
    )

    spec, _ = chart.figure().build_payload()
    assert spec["interaction"] == {
        "hover": True,
        "click": True,
        "brush": True,
        "select": True,
        "view_change": True,
    }

    html = chart.to_html()
    spec_json = _inline_spec_literal(html)
    for forbidden in ("LeakyCallback", "FakeReflexComponent", "on_hover", "on_click"):
        assert forbidden not in spec_json
        assert forbidden not in html

    class CapturingWidget:
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
            self.figure = figure
            self.on_hover = on_hover
            self.on_click = on_click
            self.on_brush = on_brush
            self.on_select = on_select
            self.on_view_change = on_view_change

    monkeypatch.setattr("xy.widget.FigureWidget", CapturingWidget)

    widget = chart.widget()
    assert widget.figure is chart.figure()
    assert widget.on_hover is callbacks["hover"]
    assert widget.on_click is callbacks["click"]
    assert widget.on_brush is callbacks["brush"]
    assert widget.on_select is callbacks["select"]
    assert widget.on_view_change is callbacks["view"]
    assert chart.show() is widget


def test_bad_interaction_options_do_not_cache_partial_chart_figure():
    chart = xy.chart(
        xy.scatter(x=[1.0], y=[2.0]),
        xy.interaction_config(click="yes"),
    )

    with pytest.raises(ValueError, match="interaction click"):
        chart.figure()
    assert chart._figure is None

    chart = xy.chart(
        xy.scatter(x=[1.0], y=[2.0]),
        xy.interaction_config(view_change="yes"),
    )

    with pytest.raises(ValueError, match="interaction view_change"):
        chart.figure()
    assert chart._figure is None

    for option in ("pan", "zoom"):
        chart = xy.chart(
            xy.scatter(x=[1.0], y=[2.0]),
            xy.interaction_config(**{option: "yes"}),
        )

        with pytest.raises(ValueError, match=f"interaction {option}"):
            chart.figure()
        assert chart._figure is None

    chart = xy.chart(
        xy.scatter(x=[1.0], y=[2.0]),
        xy.interaction_config(link_group="dash", link_axes=("x", "z")),
    )
    with pytest.raises(ValueError, match="link_axes"):
        chart.figure()
    assert chart._figure is None


def test_legend_and_tooltip_accept_render_keyword_components():
    legend_component = FakeReflexComponent("legend")
    tooltip_component = FakeReflexComponent("tooltip")
    chart = xy.chart(
        xy.scatter(x=[1.0], y=[2.0]),
        xy.legend(render=legend_component),
        xy.tooltip(render=tooltip_component),
    )

    assert chart.chrome_components()["legend"] is legend_component
    assert chart.chrome_components()["tooltip"] is tooltip_component
    spec, _ = chart.figure().build_payload()
    assert "show_tooltip" not in spec
    assert spec["show_legend"] is True


def test_component_style_validation_rejects_non_serializable_values():
    with pytest.raises(ValueError, match="chart class_names"):
        xy.chart(xy.scatter(x=[1.0], y=[2.0]), class_names={"legend": 2})
    with pytest.raises(ValueError, match="unknown slot"):
        xy.chart(xy.scatter(x=[1.0], y=[2.0]), class_names={"legnd": "typo"})
    with pytest.raises(ValueError, match="chart style"):
        xy.chart(xy.scatter(x=[1.0], y=[2.0]), style={"--bad": np.inf})
    with pytest.raises(ValueError, match="tooltip fields"):
        xy.tooltip(fields=["x", 2])
    with pytest.raises(TypeError, match="at most one"):
        xy.legend(FakeReflexComponent("a"), FakeReflexComponent("b"))
    with pytest.raises(TypeError, match="component child with render"):
        xy.tooltip(FakeReflexComponent("a"), render=FakeReflexComponent("b"))


def test_composition_builds_figure():
    x = np.arange(100.0)
    y = np.sin(x)
    chart = xy.scatter_chart(
        xy.scatter(x=x, y=y, name="a"),
        xy.x_axis(label="time"),
        xy.y_axis(label="value"),
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
    chart = xy.scatter_chart(
        xy.scatter(x="gdp", y="life", color="cont", size="pop", data=df),
    )
    fig = chart.figure()
    t = fig.traces[0]
    np.testing.assert_array_equal(t.x.values, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(t.y.values, [70.0, 75.0, 80.0])
    assert t.color_ch.mode == "categorical"  # "cont" column is strings
    assert t.size_ch.mode == "continuous"  # "pop" column is numbers


def test_chart_level_data_default():
    df = FakeFrame({"a": np.arange(5.0), "b": np.arange(5.0) * 2})
    chart = xy.scatter_chart(xy.scatter(x="a", y="b"), data=df)
    fig = chart.figure()
    np.testing.assert_array_equal(fig.traces[0].y.values, np.arange(5.0) * 2)


def test_css_color_vs_column():
    # A CSS color stays constant; a non-CSS string is a column name.
    df = FakeFrame({"x": np.arange(3.0), "y": np.arange(3.0), "grp": np.array(["p", "q", "p"])})
    c1 = xy.scatter_chart(xy.scatter(x="x", y="y", color="#ff0000", data=df)).figure()
    assert c1.traces[0].color_ch.mode == "constant"
    c2 = xy.scatter_chart(xy.scatter(x="x", y="y", color="red", data=df)).figure()
    assert c2.traces[0].color_ch.mode == "constant"
    c3 = xy.scatter_chart(xy.scatter(x="x", y="y", color="grp", data=df)).figure()
    assert c3.traces[0].color_ch.mode == "categorical"


def test_missing_column_errors():
    df = FakeFrame({"a": np.arange(3.0)})
    with pytest.raises(ValueError, match=r"scatter\.y column 'missing' not found"):
        xy.scatter_chart(xy.scatter(x="a", y="missing", data=df)).figure()


@pytest.mark.parametrize(
    ("chart", "match"),
    [
        (
            lambda df: xy.scatter_chart(xy.scatter(x="a", y="b", color="missing"), data=df),
            r"scatter\.color column 'missing' not found",
        ),
        (
            lambda df: xy.scatter_chart(xy.scatter(x="a", y="b", size="missing"), data=df),
            r"scatter\.size column 'missing' not found",
        ),
        (
            lambda df: xy.area_chart(xy.area(x="a", y="b", base="missing"), data=df),
            r"area\.base column 'missing' not found",
        ),
        (
            lambda df: xy.histogram_chart(xy.histogram(values="missing"), data=df),
            r"histogram\.values column 'missing' not found",
        ),
        (
            lambda df: xy.heatmap_chart(xy.heatmap(z="missing"), data=df),
            r"heatmap\.z column 'missing' not found",
        ),
        (
            lambda df: xy.bar_chart(xy.bar(x="label", y="value", base="missing"), data=df),
            r"bar\.base column 'missing' not found",
        ),
        (
            lambda df: xy.column_chart(xy.column(x="label", y="value", base="missing"), data=df),
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
    second = xy.scatter(x="x", y="missing")
    chart = xy.scatter_chart(
        xy.line(x="x", y="y", name="first"),
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
        xy.scatter_chart(xy.scatter(x="a", y="b")).figure()


def test_unknown_mark_kind_failure_does_not_cache_partial_chart_figure():
    mark = xy.line([0.0, 1.0], [1.0, 2.0])
    mark.kind = "not-real"
    chart = xy.line_chart(mark)

    with pytest.raises(TypeError, match="not-real"):
        chart.figure()
    assert chart._figure is None

    mark.kind = "line"
    fig = chart.figure()

    assert chart.figure() is fig
    assert [trace.kind for trace in fig.traces] == ["line"]


def test_legend_off():
    chart = xy.scatter_chart(
        xy.scatter(x=np.arange(3.0), y=np.arange(3.0), name="s"),
        xy.legend(show=False),
    )
    spec, _ = chart.figure().build_payload()
    assert spec["show_legend"] is False


def test_legend_location_and_columns_are_serialized():
    chart = xy.scatter_chart(
        xy.scatter(x=np.arange(3.0), y=np.arange(3.0), name="s"),
        xy.legend(loc="upper left", ncols=2),
    )
    spec, _ = chart.figure().build_payload()
    assert spec["legend"] == {"loc": "upper left", "ncols": 2}


def test_component_axis_and_legend_validate_public_props_without_caching_failure():
    with pytest.raises(ValueError, match="axis type_"):
        xy.x_axis(type_="logg")
    with pytest.raises(ValueError, match="legend show"):
        xy.legend(show="false")

    bad_axis = Axis(which="z")
    chart = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)), bad_axis)
    with pytest.raises(ValueError, match=r"axis\.which"):
        chart.figure()
    assert chart._figure is None

    bad_axis.which = "x"
    fig = chart.figure()
    assert fig is chart.figure()
    assert fig.x_label is None

    bad_legend = Legend(show="false")
    chart2 = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)), bad_legend)
    with pytest.raises(ValueError, match="legend show"):
        chart2.figure()
    assert chart2._figure is None
    assert bad_legend.show == "false"


def test_component_text_metadata_errors_do_not_cache_partial_chart_figure():
    chart = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)), title=123)

    with pytest.raises(ValueError, match="title must be a string or None"):
        chart.figure()
    assert chart._figure is None

    chart.title = "ok"
    fig = chart.figure()
    assert chart.figure() is fig
    assert fig.title == "ok"

    bad_axis = xy.x_axis(label="ok")
    bad_axis.label = 42
    chart2 = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)), bad_axis)
    with pytest.raises(ValueError, match="x_label must be a string or None"):
        chart2.figure()
    assert chart2._figure is None

    chart3 = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0), name=123))
    with pytest.raises(ValueError, match="scatter name must be a string or None"):
        chart3.figure()
    assert chart3._figure is None


def test_component_axis_types_emit_log_domain_reverse_and_format():
    fig = xy.scatter_chart(
        xy.scatter(x=np.array([1.0, 10.0, 100.0]), y=np.arange(3.0)),
        xy.x_axis(type_="linear"),
        xy.y_axis(type_="time"),
    ).figure()
    assert len(fig.traces) == 1

    chart = xy.scatter_chart(
        xy.scatter(x=np.array([1.0, 10.0, 100.0]), y=np.array([0.2, 0.4, 0.8])),
        xy.x_axis(
            type_="log",
            domain=(1.0, 100.0),
            reverse=True,
            format=".0f",
            style={"grid_color": "rgba(37,99,235,.2)", "tick_color": "#1d4ed8"},
        ),
        xy.y_axis(
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
    chart = xy.chart(
        xy.scatter(x=np.arange(3.0), y=np.arange(3.0)),
        xy.x_axis(
            label="custom x",
            label_position="inside-end",
            label_offset=8,
            label_angle=12,
        ),
        xy.y_axis(
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
        xy.x_axis(label_position="middle-ish")
    with pytest.raises(ValueError, match="label_offset"):
        xy.y_axis(label_offset=True)
    with pytest.raises(ValueError, match="label_angle"):
        xy.y_axis(label_angle=np.nan)


def test_component_axis_tick_layout_controls_emit_to_payload():
    chart = xy.chart(
        xy.line(x=np.arange(3.0), y=np.arange(3.0)),
        xy.x_axis(
            tick_count=4,
            tick_label_angle=-35,
            tick_label_strategy="stagger",
            tick_label_anchor="end",
            tick_label_min_gap=12,
        ),
        xy.y_axis(tick_count=3, tick_label_strategy="hide"),
    )

    spec, _ = chart.figure().build_payload()

    assert spec["x_axis"]["tick_count"] == 4
    assert spec["x_axis"]["tick_label_angle"] == -35.0
    assert spec["x_axis"]["tick_label_strategy"] == "stagger"
    assert spec["x_axis"]["tick_label_anchor"] == "end"
    assert spec["x_axis"]["tick_label_min_gap"] == 12.0
    assert spec["y_axis"]["tick_count"] == 3
    assert spec["y_axis"]["tick_label_strategy"] == "hide"
    assert "tick_label_anchor" not in spec["y_axis"]

    # mpl `ha` vocabulary normalizes to the canonical anchors
    assert xy.x_axis(tick_label_anchor="right").tick_label_anchor == "end"
    assert xy.x_axis(tick_label_anchor="left").tick_label_anchor == "start"
    assert xy.x_axis(tick_label_anchor="middle").tick_label_anchor == "center"

    with pytest.raises(ValueError, match="tick_count"):
        xy.x_axis(tick_count=0)
    with pytest.raises(ValueError, match="tick_label_strategy"):
        xy.x_axis(tick_label_strategy="squish")
    with pytest.raises(ValueError, match="tick_label_anchor"):
        xy.x_axis(tick_label_anchor="sideways")
    with pytest.raises(ValueError, match="tick_label_min_gap"):
        xy.y_axis(tick_label_min_gap=-1)


def test_line_chart():
    x = np.arange(100.0)
    chart = xy.line_chart(xy.line(x=x, y=np.sin(x), name="wave", color="#123456"))
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
    fig = xy.area_chart(xy.area(x="x", y="y", base="base", color="#3355aa"), data=df).figure()
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["kind"] == "area"
    assert tr["style"]["color"] == "#3355aa"
    base = spec["columns"][tr["base"]]
    vals = np.frombuffer(blob, dtype=np.float32, count=base["len"], offset=base["byte_offset"])
    np.testing.assert_allclose(vals.astype(np.float64) + base["offset"], [1.0, 1.5, 1.0])


def test_histogram_chart_data_key():
    df = FakeFrame({"value": np.array([0.2, 0.4, 1.2, 1.8])})
    chart = xy.histogram_chart(xy.histogram(values="value", bins=[0.0, 1.0, 2.0]), data=df)
    fig = chart.figure()
    spec, _ = fig.build_payload()
    assert fig.traces[0].kind == "histogram"
    assert spec["traces"][0]["n_points"] == 4
    assert spec["traces"][0]["n_marks"] == 2


def test_bar_chart_data_keys_and_category_axis():
    df = FakeFrame({"label": np.array(["a", "b", "c"]), "value": np.array([3.0, 2.0, 4.0])})
    chart = xy.bar_chart(xy.bar(x="label", y="value", color="#3355aa"), data=df)
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
    chart = xy.chart(xy.line(x=x, y=np.array([1.0, 2.0, 3.0])))

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
    fig = xy.bar_chart(
        xy.bar(
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
    chart = xy.bar_chart(
        xy.bar(
            x="label",
            y="values",
            series=[evil, also_evil],
            colors=["#111111", "#222222"],
        ),
        xy.text(evil, 2.0, evil, class_name=also_evil, style={"color": "#111111"}),
        xy.x_axis(label=evil),
        xy.y_axis(label=also_evil),
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


def test_component_to_html_path_keeps_existing_file_on_atomic_replace_failure(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "component.html"
    target.write_text("old declarative chart artifact", encoding="utf-8")
    chart = xy.chart(
        xy.scatter(x=[1.0, 2.0], y=[2.0, 4.0], name="points"),
        xy.line(x=[1.0, 2.0], y=[2.1, 3.9], name="trend"),
        xy.legend(class_name="tw-legend"),
        xy.tooltip(fields=["x", "y"]),
        title="declarative atomic export",
    )

    def fail_replace(src, dst) -> None:
        assert Path(src).name.startswith(".component.html.")
        assert Path(dst) == target
        raise OSError("synthetic component replace failure")

    monkeypatch.setattr(export_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="synthetic component replace failure"):
        chart.to_html(target)

    assert target.read_text(encoding="utf-8") == "old declarative chart artifact"
    assert not list(tmp_path.glob(".component.html.*.tmp"))


def test_component_to_png_delegates_to_composed_figure(monkeypatch):
    chart = xy.line_chart(xy.line([0, 1], [1, 2]))
    seen = {}

    def fake_to_png(
        self,
        path=None,
        *,
        width=None,
        height=None,
        scale=2.0,
        engine=xy.Engine.default,
        optimize=False,
        custom_css=None,
        sandbox=True,
        gl="software",
    ):
        seen.update(
            {
                "figure": self,
                "path": path,
                "width": width,
                "height": height,
                "scale": scale,
                "engine": engine,
                "optimize": optimize,
                "custom_css": custom_css,
                "sandbox": sandbox,
                "gl": gl,
            }
        )
        return b"PNG"

    monkeypatch.setattr("xy._figure.Figure.to_png", fake_to_png)

    data = chart.to_png(
        "out.png",
        width=320,
        height=200,
        scale=1.5,
        engine=xy.Engine.chromium,
        optimize=True,
        custom_css=".chart { color: rebeccapurple; }",
        sandbox=False,
        gl="hardware",
    )

    assert data == b"PNG"
    assert seen == {
        "figure": chart.figure(),
        "path": "out.png",
        "width": 320,
        "height": 200,
        "scale": 1.5,
        "engine": xy.Engine.chromium,
        "optimize": True,
        "custom_css": ".chart { color: rebeccapurple; }",
        "sandbox": False,
        "gl": "hardware",
    }


def test_widget_failure_does_not_cache_partial_widget(monkeypatch):
    chart = xy.line_chart(xy.line([0.0, 1.0], [1.0, 2.0]))
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

    monkeypatch.setattr("xy.widget.FigureWidget", FlakyWidget)

    with pytest.raises(RuntimeError, match="synthetic widget failure"):
        chart.widget()
    assert chart._widget is None

    widget = chart.widget()

    assert chart._widget is widget
    assert widget.figure is fig
    assert calls["count"] == 2


def test_bar_chart_horizontal_component_option():
    df = FakeFrame({"label": np.array(["a", "b"]), "value": np.array([3.0, 2.0])})
    fig = xy.bar_chart(xy.bar(x="label", y="value", orientation="horizontal"), data=df).figure()
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
    fig = xy.column_chart(xy.column(x="label", y="value", base="base"), data=df).figure()
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
    fig = xy.heatmap_chart(
        xy.heatmap(z="z", x="cols", y="rows", colormap="cividis", name="values"),
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
    chart = xy.chart(
        xy.line(x=np.arange(3.0), y=np.array([1.0, 2.0, 3.0]), name="left"),
        xy.line(x=np.arange(3.0), y=np.array([20.0, 40.0, 80.0]), name="right", y_axis="y2"),
        xy.y_axis(label="primary"),
        xy.y_axis(id="y2", label="secondary", side="right", domain=(0.0, 100.0), format=",.1f"),
    )

    spec, _ = chart.figure().build_payload()

    assert set(spec["axes"]) >= {"x", "y", "y2"}
    assert spec["axes"]["y2"]["label"] == "secondary"
    assert spec["axes"]["y2"]["side"] == "right"
    assert spec["axes"]["y2"]["domain"] == [0.0, 100.0]
    assert spec["axes"]["y2"]["format"] == ",.1f"
    assert [trace["y_axis"] for trace in spec["traces"]] == ["y", "y2"]

    with pytest.raises(ValueError, match=r"matching xy\.y_axis"):
        xy.chart(
            xy.line(x=np.arange(3.0), y=np.arange(3.0), y_axis="y2"),
        ).figure()


@pytest.mark.parametrize("axis_dim", ["x", "y"])
@pytest.mark.parametrize(
    "primary_is_category",
    [True, False],
    ids=["primary-category-named-linear", "primary-linear-named-category"],
)
def test_declarative_named_axis_category_state_is_scoped_per_axis_id(
    axis_dim: str, primary_is_category: bool
) -> None:
    named_axis_id = f"{axis_dim}2"
    axis_factory = xy.x_axis if axis_dim == "x" else xy.y_axis
    side = "top" if axis_dim == "x" else "right"
    category_values = ["Alpha", "Beta"]
    numeric_values = [100.0, 200.0]
    primary_values = category_values if primary_is_category else numeric_values
    named_values = numeric_values if primary_is_category else category_values

    def mark(values, *, named: bool = False):
        props = (
            {"x": values, "y": [1.0, 2.0]} if axis_dim == "x" else {"x": [1.0, 2.0], "y": values}
        )
        if named:
            props[f"{axis_dim}_axis"] = named_axis_id
        return xy.line(**props)

    chart = xy.chart(
        mark(primary_values),
        mark(named_values, named=True),
        axis_factory(type_="linear" if not primary_is_category else None),
        axis_factory(
            id=named_axis_id,
            side=side,
            type_="linear" if primary_is_category else None,
        ),
    )

    fig = chart.figure()
    spec, _ = fig.build_payload()
    category_axis_id = axis_dim if primary_is_category else named_axis_id
    linear_axis_id = named_axis_id if primary_is_category else axis_dim

    assert fig._axis_categories == {category_axis_id: category_values}
    assert spec["axes"][category_axis_id]["kind"] == "category"
    assert spec["axes"][category_axis_id]["categories"] == category_values
    assert spec["axes"][linear_axis_id]["kind"] == "linear"
    assert "categories" not in spec["axes"][linear_axis_id]
    assert [trace[f"{axis_dim}_axis"] for trace in spec["traces"]] == [
        axis_dim,
        named_axis_id,
    ]


def test_bad_child_type():
    with pytest.raises(TypeError, match="children"):
        xy.scatter_chart("not a component").figure()


def test_figure_cached():
    chart = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)))
    assert chart.figure() is chart.figure()


# -- selection (§34) ---------------------------------------------------------


def test_select_range():
    x = np.arange(100.0)
    y = np.arange(100.0)
    fig = Figure().scatter(x, y)
    sel = fig.select_range(10.0, 20.0, 0.0, 1000.0)
    idx = sel[0]
    assert idx.dtype == np.uint32
    np.testing.assert_array_equal(idx, np.arange(10, 21, dtype=np.uint32))


def test_select_range_box():
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 100, 1000)
    y = rng.uniform(0, 100, 1000)
    fig = Figure().scatter(x, y)
    sel = fig.select_range(25.0, 75.0, 25.0, 75.0)
    idx = sel[0]
    expect = np.flatnonzero((x >= 25) & (x <= 75) & (y >= 25) & (y <= 75))
    np.testing.assert_array_equal(np.sort(idx), expect.astype(np.uint32))


def test_selection_payload():
    x = np.arange(10.0)
    fig = Figure().scatter(x, x)
    sel = fig.select_range(2.0, 5.0, 0.0, 100.0)
    payload = Selection(fig, sel)
    assert len(payload) == 4  # indices 2,3,4,5
    sx, sy = payload.xy(0)
    np.testing.assert_array_equal(sx, [2.0, 3.0, 4.0, 5.0])
    np.testing.assert_array_equal(payload.index, [2, 3, 4, 5])

    with pytest.raises(ValueError, match="trace_id"):
        payload.xy(-1)


def test_chart_styles_prop_is_the_documented_per_slot_mechanism() -> None:
    """docs/engineering/styling.md's fourth mechanism: `styles={slot: {...}}` on xy.chart —
    slot-validated, CSS-validated, merged with per-component `style=`."""
    xs = np.arange(6.0)
    chart = xy.chart(
        xy.scatter(x=xs, y=xs),
        xy.tooltip(style={"color": "#fff"}),
        styles={
            "title": {"font_size": 18, "letter_spacing": "0.02em"},
            "tooltip": {"border_radius": "10px"},
        },
    )
    dom = chart.figure().build_payload()[0]["dom"]
    assert dom["styles"]["title"] == {"font_size": 18, "letter_spacing": "0.02em"}
    assert dom["styles"]["tooltip"] == {"color": "#fff", "border_radius": "10px"}
    with pytest.raises(ValueError, match="unknown slot"):
        xy.chart(xy.scatter(x=xs, y=xs), styles={"tooltp": {"color": "#fff"}})
    with pytest.raises(ValueError, match="not a valid hex color"):
        xy.chart(xy.scatter(x=xs, y=xs), styles={"title": {"color": "#3b82zz"}})


# -- Chart live surface (data-live, structure-immutable) ----------------------


def test_chart_append_routes_through_live_widget(monkeypatch):
    appends = []

    class CapturingWidget:
        def __init__(self, figure, **kwargs):
            self.figure = figure

        def append(self, trace_id, x, y, *, color=None, size=None):
            appends.append((trace_id, x, y, color, size))

    monkeypatch.setattr("xy.widget.FigureWidget", CapturingWidget)
    chart = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)))
    chart.widget()
    n_before = len(chart.figure().traces[0].x.values)

    chart.append(0, [3.0], [4.0])

    assert appends == [(0, [3.0], [4.0], None, None)]
    # Routed to the widget only — the figure was not double-appended (the
    # real FigureWidget.append mutates it; the capture stub records instead).
    assert len(chart.figure().traces[0].x.values) == n_before


def test_chart_append_headless_mutates_figure_without_widget_stack():
    chart = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)))

    chart.append(0, [3.0], [4.0])

    assert chart._widget is None  # no widget instantiated as a side effect
    trace = chart.figure().traces[0]
    assert len(trace.x.values) == 4
    assert trace.x.values[-1] == 3.0
    spec, _blob = chart.figure().build_payload()
    assert spec["traces"][0]["n_points"] == 4


def test_chart_append_contract_violations_raise():
    chart = xy.scatter_chart(xy.scatter(x=np.arange(3.0), y=np.arange(3.0)))

    with pytest.raises(ValueError):
        chart.append(0, [1.0], [1.0, 2.0])  # length mismatch


def test_chart_pick_matches_figure_pick():
    chart = xy.scatter_chart(xy.scatter(x=np.arange(5.0), y=np.arange(5.0) * 2))

    row = chart.pick(0, 2)

    assert row == chart.figure().pick(0, 2)
    assert row["x"] == 2.0
    assert row["y"] == 4.0
    assert chart.pick(0, 99) is None  # out of range → None, like Figure


def test_chart_select_range_returns_selection():
    chart = xy.scatter_chart(xy.scatter(x=np.arange(10.0), y=np.arange(10.0)))

    sel = chart.select_range(2.0, 5.0, 0.0, 6.0)

    assert isinstance(sel, Selection)
    np.testing.assert_array_equal(sel.index, [2, 3, 4, 5])
    xs, ys = sel.xy(0)
    np.testing.assert_array_equal(xs, [2.0, 3.0, 4.0, 5.0])
    empty = chart.select_range(100.0, 200.0, 100.0, 200.0)
    assert len(empty) == 0


def test_declarative_chart_live_roundtrip():
    """End to end: declarative chart -> real widget -> simulated client
    messages fire callbacks -> chart.append streams -> readouts see new rows."""
    hovered, brushes, sels = [], [], []
    chart = xy.chart(
        xy.scatter(x=np.arange(10.0), y=np.arange(10.0), name="pts"),
        on_hover=hovered.append,
        on_brush=brushes.append,
        on_select=sels.append,
    )
    w = chart.widget()  # real FigureWidget -> real channel dispatch
    sent = []
    w.send = lambda content, buffers=None: sent.append((content, buffers))

    w._on_custom_msg(None, {"type": "pick", "trace": 0, "index": 2, "seq": 1}, None)
    w._on_custom_msg(None, {"type": "select", "x0": 5.0, "x1": 2.0, "y0": 0.0, "y1": 6.0}, None)
    w._on_custom_msg(None, {"type": "select", "x0": "bad", "x1": 1, "y0": 0, "y1": 1}, None)
    chart.append(0, [10.0], [11.0])

    assert hovered[0]["x"] == 2.0
    assert brushes == [{"x0": 2.0, "x1": 5.0, "y0": 0.0, "y1": 6.0}]  # normalized, before select
    np.testing.assert_array_equal(sels[0].index, [2, 3, 4, 5])
    kinds = [c["type"] for c, _ in sent]
    assert kinds == ["pick_result", "selection", "append"]  # malformed select added nothing
    assert w.spec["traces"][0]["n_points"] == 11  # trait re-sync carried the append
    assert len(chart.figure().traces[0].x.values) == 11
    assert chart.pick(0, 10)["x"] == 10.0  # readout sees the streamed row
