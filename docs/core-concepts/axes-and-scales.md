---
title: Axes and Scales
description: Configure domains, scale types, ticks, formatting, and named axes.
---

# Axes and Scales

Add `x_axis()` and `y_axis()` children to label and constrain a chart. XY
infers linear, time, and categorical scales from the bound columns.
Datetime-like values select the time scale automatically, or you can make the
contract explicit.

## Scale type and domain

`type_` accepts `"linear"`, `"time"`, or `"log"`. Leave it as `None` to infer
the scale. The explicit token is `"time"`, not `"datetime"`.
`domain=(low, high)` pins a data-space window; `reverse=True` flips its display
direction without changing the source values.

~~~python demo exec
import numpy as np
import xy

x = np.logspace(0, 6, 240)
rank = 96 - np.log10(x) * 11.5

chart = xy.line_chart(
    xy.line(x, rank),
    xy.x_axis(
        label="Request volume",
        type_="log",
        domain=(1, 1_000_000),
        tick_values=[1, 10, 100, 1_000, 10_000, 100_000, 1_000_000],
        tick_labels=["1", "10", "100", "1k", "10k", "100k", "1M"],
    ),
    xy.y_axis(label="Rank", domain=(0, 100), reverse=True, format=".0f"),
)


def scale_type_and_domain_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

Log domains must be positive. Date and datetime values use XY's canonical
milliseconds-since-epoch coordinate system while their ticks render as time.
String categories preserve a stable category order and receive categorical
positions.

## Tick controls

Use `tick_count` as a target, or provide exact `tick_values` with optional
`tick_labels`:

~~~python demo exec
import xy

axis = xy.y_axis(
    label="Conversion",
    domain=(0, 1),
    tick_values=[0, 0.25, 0.5, 0.75, 1],
    tick_labels=["0%", "25%", "50%", "75%", "100%"],
)

chart = xy.line_chart(
    xy.line(["Jan", "Feb", "Mar", "Apr", "May"], [0.18, 0.34, 0.29, 0.57, 0.72]),
    xy.x_axis(label="Month"),
    axis,
)


def tick_controls_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

`format` uses the strict axis value grammar: fixed/grouped/currency/unit/percent
forms for numeric and log axes, or the UTC tokens `%Y`, `%m`, `%d`, `%H`, `%M`,
`%S`, `%b`, and `%B` for time axes. Unsupported formats raise rather than
falling back. For crowded labels, use
`tick_label_angle`, `tick_label_min_gap`, and `tick_label_strategy`.
`label_position`, `label_offset`, and `label_angle` position the axis title.

Axis `style=` uses a strict cross-renderer vocabulary for grid, axis, tick, and
label paint/geometry. See
[Customize Each Part](/docs/xy/styling/customize/#axes,-grid,-and-ticks)
for the supported keys.

## Named and opposite-side axes

Marks bind to axis identifiers through `x_axis=` and `y_axis=`. Define a
matching `id` on the axis component, and use `side="right"` or `side="top"`
for an opposite-side axis:

~~~python demo exec
import xy

chart = xy.chart(
    xy.line([1, 10, 100], [80, 70, 60], name="Rank"),
    xy.line(
        [1, 10, 100],
        [0.08, 0.12, 0.19],
        y_axis="y2",
        name="Conversion",
        color="#dc2626",
    ),
    xy.x_axis(type_="log", label="Requests", domain=(1, 100)),
    xy.y_axis(label="Rank", domain=(0, 100)),
    xy.y_axis(
        id="y2",
        side="right",
        label="Conversion",
        domain=(0, 0.25),
        format=".0%",
    ),
    xy.legend(),
)


def named_axes_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

Named axes share the panel but keep their own scale and tick contract. Bindings
that name an undefined axis fail at chart build time.
