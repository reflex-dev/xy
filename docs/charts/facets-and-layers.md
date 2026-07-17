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

## Variants

### Small Multiples

~~~python
import xy

data = {
    "x": [0, 1, 2, 0, 1, 2],
    "y": [1, 2, 3, 3, 2, 1],
    "region": ["West", "West", "West", "East", "East", "East"],
}

grid = xy.facet_chart(
    xy.scatter(x="x", y="y", color="#6e56cf"),
    by="region",
    data=data,
    cols=2,
    share_x=True,
    share_y=True,
)
~~~

`cols` controls wrapping, `gap` controls panel spacing, and shared axes keep
categories and numeric domains comparable. Each panel retains the same
per-mark decimation and aggregation behavior as a standalone chart.

Marks render in declaration order, so put broad fills first and then lines or
points. Annotations are composed separately from the mark trace order as
data-aligned chart chrome.

## Expected Data Shape

Layered marks may share chart-level `data=` or use their own sources, but they
must resolve into compatible axes. `facet_chart` takes a table plus a `by`
column whose distinct values define panels.

## Key Options

Layered charts use the ordinary mark and chart options. Facets add `by`,
`cols`, `gap`, `share_x`, and `share_y`; each panel keeps its own chart payload
and the same per-mark representation rules.
