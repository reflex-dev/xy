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

## Label the Axes and Fix the Domain

The most common axis contract is a label, an explicit `domain=(min, max)`, and
a requested `tick_count=` so the view stays put regardless of the data:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

ax_hours = np.arange(0, 25, 3)
ax_temp = np.array([12.1, 11.4, 13.0, 17.6, 21.3, 23.8, 22.0, 17.2, 13.9])

ax_domain_chart = xy.chart(
    xy.line(ax_hours, ax_temp, color="#6e56cf", width=2.5),
    xy.x_axis(label="hour of day", domain=(0, 24), tick_count=9),
    xy.y_axis(label="temperature (°C)", domain=(0, 30), tick_count=4),
    title="Fixed domains with requested tick counts",
)


def axes_domain_demo():
    return reflex_xy.chart(ax_domain_chart, height="320px")
~~~

## Set the Scale Contract

~~~python demo exec
import numpy as np
import reflex_xy
import xy

log_x = np.logspace(0, 6, 240)
log_y = 96 - np.log10(log_x) * 11.5

log_chart = xy.line_chart(
    xy.line(log_x, log_y),
    xy.x_axis(
        type_="log",
        domain=(1, 1_000_000),
        label="requests",
        format=",.0f",
    ),
    xy.y_axis(domain=(0, 100), reverse=True, label="rank"),
)


def axes_scale_contract_demo():
    return reflex_xy.chart(log_chart, height="320px")
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

Here the x-axis carries category names with `tick_values=` + `tick_labels=`,
rotated with `tick_label_angle=` and anchored at their ends, while
`label_position=` and `label_offset=` move the axis title out of the way:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

tick_stage = np.arange(5)
tick_rate = np.array([1.0, 0.62, 0.38, 0.21, 0.09])

tick_style_chart = xy.chart(
    xy.bar(tick_stage, tick_rate, color="#0ea5e9", width=0.6),
    xy.x_axis(
        tick_values=[0, 1, 2, 3, 4],
        tick_labels=["Visited", "Signed up", "Activated", "Subscribed", "Renewed"],
        tick_label_angle=-30,
        tick_label_anchor="end",
        label="funnel stage",
        label_position="end",
        label_offset=28,
    ),
    xy.y_axis(
        domain=(0, 1),
        tick_values=[0, 0.25, 0.5, 0.75, 1],
        tick_labels=["0%", "25%", "50%", "75%", "100%"],
        label="conversion",
    ),
    title="Exact ticks with rotated labels",
)


def axes_tick_styling_demo():
    return reflex_xy.chart(tick_style_chart, height="320px")
~~~

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

Named axes compose with every mark kind. Below, monthly rain probability rides
a right-hand percentage axis (`id="y2"`, `side="right"`, `format=".0%"`) while
temperature keeps the primary y-axis:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

dual_month = np.arange(1, 13)
dual_temp = np.array(
    [2.1, 3.0, 6.8, 11.2, 15.6, 19.3, 21.8, 21.2, 17.0, 11.9, 6.4, 3.2]
)
dual_rain = np.array(
    [0.18, 0.14, 0.12, 0.09, 0.07, 0.05, 0.04, 0.05, 0.09, 0.13, 0.17, 0.19]
)

dual_axis_chart = xy.chart(
    xy.bar(
        dual_month,
        dual_rain,
        y_axis="y2",
        name="Rain probability",
        color="#93c5fd",
        opacity=0.6,
    ),
    xy.line(dual_month, dual_temp, name="Temperature", color="#dc2626", width=2.5),
    xy.x_axis(label="month", tick_count=12),
    xy.y_axis(label="temperature (°C)", domain=(0, 25)),
    xy.y_axis(
        id="y2",
        side="right",
        label="rain probability",
        domain=(0, 0.4),
        format=".0%",
    ),
    xy.legend(),
    title="Two units, one panel",
)


def axes_dual_axis_demo():
    return reflex_xy.chart(dual_axis_chart, height="320px")
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
