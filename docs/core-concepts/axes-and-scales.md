---
title: Axes and Scales
description: Configure domains, scale types, formatting, ticks, and multiple axes.
---

# Axes and Scales

Add `x_axis()` and `y_axis()` children to label and constrain a chart. XY can
infer ordinary linear, datetime, and categorical axes, or you can configure
them explicitly.

## Domains and Scale Types

~~~python
import numpy as np
import xy as fc

x = np.logspace(0, 6, 240)
rank = 96 - np.log10(x) * 11.5
conversion = 0.08 + np.log10(x) * 0.035

chart = fc.chart(
    fc.line(x, rank, name="Rank", color="#2563eb"),
    fc.line(x, conversion, y_axis="y2", name="Conversion", color="#dc2626"),
    fc.x_axis(
        label="request volume",
        type_="log",
        domain=(1, 1_000_000),
        format=",.0f",
    ),
    fc.y_axis(label="rank", domain=(0, 100), reverse=True, format=".0f"),
    fc.y_axis(
        id="y2",
        label="conversion",
        side="right",
        domain=(0, 0.35),
        format=".0%",
    ),
    fc.legend(),
)
~~~

## Tick Controls

Use `tick_count` for a target count or provide exact `tick_values` and optional
`tick_labels`. Long labels can use `tick_label_angle`, `tick_label_min_gap`, or
the `tick_label_strategy` supported by the axis component.

`label_position`, `label_offset`, and `label_angle` control the axis title.
`side="right"` or `side="top"` places compatible axes on the opposite side.

## Bind a Mark to a Named Axis

Every mark accepts `x_axis` and `y_axis` identifiers. Define matching axes with
`x_axis(id="x2", ...)` or `y_axis(id="y2", ...)` before building the chart.
