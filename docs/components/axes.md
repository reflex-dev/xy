---
title: Axes
description: Configure XY scale types, domains, ticks, labels, and named axes.
---

# Axes

Add `x_axis()` and `y_axis()` children when a chart needs an explicit scale or
presentation contract. Without them, XY infers ordinary numeric, datetime, and
categorical behavior from the bound data.

## Set the Scale Contract

~~~python
import numpy as np
import xy

x = np.logspace(0, 6, 240)
y = 96 - np.log10(x) * 11.5

chart = xy.line_chart(
    xy.line(x, y),
    xy.x_axis(
        type_="log",
        domain=(1, 1_000_000),
        label="requests",
        format=",.0f",
    ),
    xy.y_axis(domain=(0, 100), reverse=True, label="rank"),
)
~~~

Use `type_="linear"`, `"time"`, or `"log"` when inference is not the desired
contract. Explicit domains must be finite and increasing; log domains must also
be positive. `reverse=True` changes display direction without rewriting the
source values.

## Control Labels and Ticks

Use a requested tick count for an adaptive axis, or provide exact tick values
and matching labels:

~~~python
xy.y_axis(
    label="conversion",
    domain=(0, 1),
    tick_values=[0, 0.25, 0.5, 0.75, 1],
    tick_labels=["0%", "25%", "50%", "75%", "100%"],
)
~~~

Formatting, label placement, rotation, minimum gaps, and collision strategy
let the renderer adapt the axis to a dashboard or publication layout. Exact
option names and defaults are in the
[generated component reference](/docs/xy/api-reference/marks-and-components/).

## Bind Marks to Named Axes

Use named axes for different units in one panel. An x-axis identifier must
start with `x` and a y-axis identifier with `y`; every named binding must have a
matching axis component.

~~~python
chart = xy.chart(
    xy.line([1, 10, 100], [80, 70, 60], name="Rank"),
    xy.line(
        [1, 10, 100],
        [0.08, 0.12, 0.19],
        y_axis="y2",
        name="Conversion",
        color="#dc2626",
    ),
    xy.x_axis(type_="log", label="requests"),
    xy.y_axis(label="rank", domain=(0, 100)),
    xy.y_axis(
        id="y2",
        side="right",
        label="conversion",
        domain=(0, 0.25),
        format=".0%",
    ),
    xy.legend(),
)
~~~

## Style Axes

Axis `style=` uses a validated, cross-renderer vocabulary for grid, axis, tick,
and label paint and geometry. Browser DOM labels can additionally be targeted
through the chart's `tick_label` and `axis_title` slots. Use the validated axis
style for output that must agree across HTML, SVG, and native PNG.

For the scale model, including datetime and category handling, see
[Axes and scales](/docs/xy/core-concepts/axes-and-scales/). For styling, see
[Mark styles](/docs/xy/styling/mark-styles/).
