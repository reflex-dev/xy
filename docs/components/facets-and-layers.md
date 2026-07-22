---
title: Facet Charts and Layered Marks in Python
description: Build faceted small multiples and layer different marks in one chart in Python with xy, with shared axes and per-panel interactivity.
components:
  - xy.chart
  - xy.facet_chart
---

# Facet Charts and Layered Marks in Python

## When to Use

Layer marks in a neutral `chart()` container when they share a coordinate
system. Use `facet_chart()` to repeat one composition across categories — a
facet chart (also called a facet plot, or simply small multiples) draws each
category in its own panel.

## Live Demo

The live example layers different mark types in one coordinate system.

~~~python demo exec
import reflex_xy
import xy

chart = xy.chart(
    xy.bar(["A", "B", "C"], [4, 7, 5], color="#c4b5fd"),
    xy.scatter(["A", "B", "C"], [4.5, 6.5, 5.5], color="#1b212a"),
    xy.hline(6, text="Target"),
)


def layered_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

## Chart Types

### Layered Marks

Use a neutral `chart()` container to layer different marks in one coordinate
system. Declare broad fills first, followed by lines, points, and annotations.

### Facet Chart

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

facet_detail_data = {
    "x": [0, 1, 2, 0, 1, 2],
    "y": [1, 2, 3, 3, 2, 1],
    "region": ["West", "West", "West", "East", "East", "East"],
}

facet_detail_chart = xy.facet_chart(
    xy.line(x="x", y="y", color="#6e56cf", width=2.5),
    xy.scatter(x="x", y="y", color="#6e56cf", size=7),
    xy.x_axis(label="period"),
    xy.y_axis(label="value"),
    by="region",
    data=facet_detail_data,
    cols=2,
    share_x=True,
    share_y=True,
    width=720,
    height=260,
    title="Regional trends",
)


def facet_chart_demo():
    return reflex_xy.chart(facet_detail_chart)
~~~

`cols` controls wrapping, `gap` controls panel spacing, and shared axes keep
categories and numeric domains comparable. Each panel retains the same
per-mark decimation and aggregation behavior as a standalone chart.

Marks render in declaration order, so put broad fills first and then lines or
points. Annotations are composed separately from the mark trace order as
data-aligned chart chrome; see the
[annotation guide](/docs/xy/components/annotations/) for rules, bands, labels,
and callouts.

### Ordered Layers with a Legend

Declaration order is the z-order — this composition stacks an `area` fill, a
dashed forecast `line`, a solid actuals `line` with `scatter` markers, and an
`hline` goal, with `name=` on each mark feeding a positioned `legend`:

~~~python demo exec
import reflex_xy
import xy

layer_months = list(range(1, 13))
layer_actual = [4.2, 4.8, 5.1, 4.6, 5.9, 6.4, 7.1, 6.8, 7.6, 8.2, 7.9, 8.8]
layer_forecast = [4.0, 4.5, 5.0, 5.2, 5.8, 6.3, 6.9, 7.2, 7.5, 8.0, 8.3, 8.6]

layered_legend_chart = xy.chart(
    xy.area(
        layer_months,
        layer_forecast,
        name="Forecast band",
        color="#c4b5fd",
        opacity=0.3,
    ),
    xy.line(
        layer_months,
        layer_forecast,
        name="Forecast",
        color="#8b5cf6",
        width=2,
        dash="dashed",
    ),
    xy.line(layer_months, layer_actual, name="Actual", color="#1b212a", width=2.5),
    xy.scatter(layer_months, layer_actual, name="Monthly close", color="#1b212a", size=6),
    xy.hline(7.5, text="Goal", color="#dc2626"),
    xy.legend(loc="top left"),
    xy.x_axis(label="month"),
    xy.y_axis(label="revenue ($M)"),
    title="Actuals over a forecast band",
)


def layered_legend_demo():
    return reflex_xy.chart(layered_legend_chart, height="360px")
~~~

## Expected Data Shape

Layered marks may share chart-level `data=` or use their own sources, but they
must resolve into compatible axes. `facet_chart` takes a table plus a `by`
column whose distinct values define panels.

## Key Options

Layered charts use the ordinary mark and chart options. Facets add `by`,
`cols`, `gap`, `share_x`, and `share_y`; each panel keeps its own chart payload
and the same per-mark representation rules.

## FAQ

### How do I make small multiples (facets) in Python?

Use `xy.facet_chart(...)` with a `by=` column; xy repeats the composition once
per distinct value and lays the panels out on a grid you control with `cols`,
one small facet graph per category.

### How do I layer multiple chart types together?

Add several marks to a neutral `xy.chart(...)` container. They render in
declaration order, so put broad fills first, then lines, points, and
annotations.

### How do I keep axes consistent across facet panels?

Set `share_x=True` and `share_y=True` so every panel uses the same numeric and
categorical domains for direct comparison.

### Do faceted charts stay interactive?

Yes. Each panel keeps the same per-mark decimation and aggregation as a
standalone chart, so pan, zoom, and hover work in every panel.
