---
title: Axes in Python
description: Configure XY scale types, domains, ticks, labels, and named axes.
components:
  - xy.x_axis
  - xy.y_axis
---

# Axes in Python

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
[Customize Each Part](/docs/xy/styling/customize/#axes,-grid,-and-ticks).

## FAQ

### How do I set the axis range in Python?

Pass `domain=(min, max)` to `xy.x_axis()` or `xy.y_axis()`, e.g.
`xy.y_axis(domain=(0, 100))`. Explicit domains must be finite and increasing,
and a `type_="log"` axis additionally requires a positive domain.

### How do I rotate or format axis tick labels?

Use `format=` with a numeric format string (e.g.
`xy.x_axis(format=",.0f")` or `format=".0%"`) and `tick_label_angle=` to rotate
the labels. For full control, supply exact `tick_values=` with matching
`tick_labels=` strings instead of the adaptive `tick_count=`.

### How do I add a second y-axis to a chart?

Declare a named axis such as `xy.y_axis(id="y2", side="right")` and bind marks
to it with `y_axis="y2"`. Y-axis identifiers must start with `y` (x identifiers
with `x`), and every named binding needs a matching axis component in the
chart.

### How do I reverse an axis in Python?

Pass `reverse=True`, e.g. `xy.y_axis(domain=(0, 100), reverse=True)`. This
flips the display direction only — the source data values are not rewritten.
