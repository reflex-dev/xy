---
title: Bar and Column Charts
description: Compare categories with grouped, stacked, normalized, and horizontal bars.
---

# Bar and Column Charts

## When to Use

`bar` and `column` share the same grouped-series implementation. Use either name
to match the vocabulary of your application, and set `orientation="horizontal"`
when category labels read better along the vertical axis.

## Live Demo

Pass a two-dimensional value array and label its columns with `series`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

quarters = ["Q1", "Q2", "Q3", "Q4"]
values = np.array([
    [42, 18, 9],
    [47, 21, 11],
    [51, 24, 13],
    [58, 27, 16],
])

chart = xy.column_chart(
    xy.column(
        quarters,
        values,
        mode="stacked",
        series=["Core", "Growth", "Enterprise"],
        colors=["#6e56cf", "#8e7cc3", "#c4b5fd"],
        corner_radius=(5, 0),
    ),
    xy.legend(),
    title="Quarterly product mix",
)


def quarterly_mix():
    return reflex_xy.chart(chart, height="320px")
~~~

## Variants

Choose `mode="grouped"`, `"stacked"`, or `"normalized"`. Use
`orientation="horizontal"` for long labels and `base` for waterfall-like or
non-zero-baseline charts.

## Expected Data Shape

For one series, pass categories and a one-dimensional value array. For grouped
or stacked bars, pass a matrix with one dimension matching the category count
and matching `series` labels. The example uses `(categories, series)`; a
`(series, categories)` matrix is also accepted. Named columns work through
`data=`.

## Key Options

Use `mode`, `orientation`, `series`, `colors`, `base`, and `width` for layout.
Use `corner_radius`, `stroke`, `stroke_width`, `fill`, and `opacity` for visual
styling.
