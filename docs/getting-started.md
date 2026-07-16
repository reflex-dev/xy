---
title: Getting Started
description: Install XY and render your first interactive chart.
---

# Getting Started

## Installation

Install XY from your project environment:

~~~bash
uv add xy
~~~

XY supports Python 3.11 and newer. Published wheels include the Python package,
browser client, and native compute core; using XY does not require a local Rust
or Node installation.

## Your First Chart

Create a chart from regular Python sequences:

~~~python
import xy as fc

chart = fc.line_chart(
    fc.line([0, 1, 2, 3], [2, 5, 3, 8], name="series"),
    fc.x_axis(label="sample"),
    fc.y_axis(label="value"),
    title="First chart",
)

chart.to_html("chart.html")
~~~

The generated HTML is standalone and keeps XY's hover, zoom, and pan behavior.

In a notebook, leave `chart` as the final expression in a cell. XY displays an
interactive widget automatically.

## Build From Named Columns

Marks can resolve strings against chart-level or mark-level `data`. Dictionaries,
DataFrames, and other column-indexable objects work with the same API.

~~~python
import xy as fc

data = {
    "month": ["Jan", "Feb", "Mar", "Apr"],
    "revenue": [42, 45, 48, 53],
}

chart = fc.line_chart(
    fc.line(x="month", y="revenue", name="Revenue"),
    fc.x_axis(label="month"),
    fc.y_axis(label="USD thousands"),
    fc.tooltip(fields=["month", "revenue"]),
    data=data,
    title="Monthly revenue",
)
~~~

## Choose a Container

Family containers such as `line_chart`, `scatter_chart`, and `bar_chart` make
single-family charts easy to scan. Use neutral `chart(...)` when layering
different mark types in one panel. Both produce the same `Chart` interface.

## Continue Learning

- [Composition](/docs/xy/core-concepts/composition/)
- [Data and columns](/docs/xy/core-concepts/data/)
- [Axes and scales](/docs/xy/core-concepts/axes-and-scales/)
- [Chart families](/docs/xy/charts/)
