---
title: XY
description: Fast interactive charts from Python.
---

# XY

XY is a Python charting library for responsive, interactive visualizations.
Its native compute core and screen-bounded renderer are designed to keep charts
responsive as datasets grow, without making ordinary charts complicated.

Compose charts from marks, axes, annotations, legends, tooltips, and interaction
settings. The same chart displays in a notebook and exports to standalone HTML,
PNG, or SVG.

## Basic Example

~~~python demo exec
import numpy as np
import reflex_xy
import xy as fc

months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
values = np.array([
    [42, 35],
    [45, 38],
    [48, 42],
    [51, 40],
    [55, 46],
    [59, 50],
])

chart = fc.column_chart(
    fc.column(
        months,
        values,
        mode="grouped",
        series=["Revenue", "Pipeline"],
    ),
    fc.legend(),
    title="Business overview",
)


def business_overview():
    return reflex_xy.chart(chart, height="320px")
~~~

## What to Read Next

- Start with [Getting Started](/docs/xy/getting-started/) to install XY and build a chart.
- Learn the [composition model](/docs/xy/core-concepts/composition/) and
  [data binding](/docs/xy/core-concepts/data/).
- Browse every [chart family](/docs/xy/charts/) and [component](/docs/xy/components/).
- Use [Exporting](/docs/xy/guides/exporting/) for HTML, PNG, and SVG output.

~~~md alert warning
### Alpha Software

XY is currently an early alpha. The declarative composition model is
stabilizing, but callback payloads, framework adapters, and advanced internals
may change before 1.0.
~~~
