---
title: Bar and Column Charts
description: Compare categories with grouped, stacked, normalized, and horizontal bars.
---

# Bar and Column Charts

`bar` and `column` share the same grouped-series implementation. Use either name
to match the vocabulary of your application, and set `orientation="horizontal"`
when category labels read better along the vertical axis.

## Grouped and Stacked Data

Pass a two-dimensional value array and label its columns with `series`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy as fc

quarters = ["Q1", "Q2", "Q3", "Q4"]
values = np.array([
    [42, 18, 9],
    [47, 21, 11],
    [51, 24, 13],
    [58, 27, 16],
])

chart = fc.column_chart(
    fc.column(
        quarters,
        values,
        mode="stacked",
        series=["Core", "Growth", "Enterprise"],
        colors=["#6e56cf", "#8e7cc3", "#c4b5fd"],
        corner_radius=(5, 0),
    ),
    fc.legend(),
    title="Quarterly product mix",
)


def quarterly_mix():
    return reflex_xy.chart(chart, height="320px")
~~~

`mode` accepts `"grouped"`, `"stacked"`, or `"normalized"`. Use `base` for
waterfalls or non-zero baselines, `width` for category occupancy, and
`corner_radius`, `stroke`, `stroke_width`, and `fill` for CSS-like styling.
