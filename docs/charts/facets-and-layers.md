---
title: Facets and Layers
description: Build small multiples and combine different marks in one chart.
---

# Facets and Layers

Layer marks in a neutral `chart()` container when they share a coordinate
system. Use `facet_chart()` to repeat one composition across categories.

## Small Multiples

~~~python
import xy as fc

data = {
    "x": [0, 1, 2, 0, 1, 2],
    "y": [1, 2, 3, 3, 2, 1],
    "region": ["West", "West", "West", "East", "East", "East"],
}

grid = fc.facet_chart(
    fc.scatter(x="x", y="y", color="#6e56cf"),
    by="region",
    data=data,
    cols=2,
    share_x=True,
    share_y=True,
)
~~~

`cols` controls wrapping, `gap` controls panel spacing, and shared axes keep
categories and numeric domains comparable. Each panel retains the normal
screen-bounded payload behavior.

## Layer Different Marks

~~~python demo exec
import reflex_xy
import xy as fc

chart = fc.chart(
    fc.bar(["A", "B", "C"], [4, 7, 5], color="#c4b5fd"),
    fc.scatter(["A", "B", "C"], [4.5, 6.5, 5.5], color="#1b212a"),
    fc.hline(6, text="Target"),
)


def layered_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

Children render in declaration order. Put broad fills and bands first, then
lines or points, followed by annotations and chart chrome.
