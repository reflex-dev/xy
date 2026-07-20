---
title: Facets and Layers
description: Build small multiples and combine different marks in one chart.
---

# Facets and Layers

## When to Use

Layer marks in a neutral `chart()` container when they share a coordinate
system. Use `facet_chart()` to repeat one composition across categories.

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
    facet_grid = facet_detail_chart.figure()
    return rx.grid(
        *[
            reflex_xy.chart(panel, height="260px")
            for panel in facet_grid.figures
        ],
        columns="2",
        gap="3",
        width="100%",
    )
~~~

`cols` controls wrapping, `gap` controls panel spacing, and shared axes keep
categories and numeric domains comparable. Each panel retains the same
per-mark decimation and aggregation behavior as a standalone chart.

Marks render in declaration order, so put broad fills first and then lines or
points. Annotations are composed separately from the mark trace order as
data-aligned chart chrome; see the
[annotation guide](/docs/xy/components/annotations/) for rules, bands, labels,
and callouts.

## Expected Data Shape

Layered marks may share chart-level `data=` or use their own sources, but they
must resolve into compatible axes. `facet_chart` takes a table plus a `by`
column whose distinct values define panels.

## Key Options

Layered charts use the ordinary mark and chart options. Facets add `by`,
`cols`, `gap`, `share_x`, and `share_y`; each panel keeps its own chart payload
and the same per-mark representation rules.
