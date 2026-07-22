---
title: Bar Chart in Python
description: Create interactive bar and column charts in Python with xy. Compare categories with grouped, stacked, normalized, horizontal, and vertical bars.
components:
  - xy.bar_chart
  - xy.column_chart
---

# Bar Charts in Python

A **bar chart** (also called a bar graph) compares values across categories using horizontal bars, one bar
per category, with length encoding the measured value. With `xy` you build a
Python bar chart that is interactive by default — pan, zoom, and hover all work
without configuration — and horizontal bars keep long category labels readable
where a vertical layout would crowd them. Layer several series to make grouped
or stacked bar charts from the same simple API. The vertical form of the same
mark is a **column chart** — see [Column Charts](#column-charts-vertical-bars)
below.

Jump to [grouped and stacked bars](#grouped-and-stacked-bars),
[column charts](#column-charts-vertical-bars), or
[options](#bar-chart-options).

## Create a Bar Chart

Pass a list of categories and a matching array of values to `bar`, and set
`orientation="horizontal"` so the bars run left to right. This is the minimal
Python bar chart:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

channels = ["Email", "Social", "Search", "Direct", "Referral"]
sessions = np.array([38, 27, 21, 14, 9])

chart = xy.bar_chart(
    xy.bar(channels, sessions, color="#6e56cf", orientation="horizontal", corner_radius=4),
    xy.x_axis(label="sessions (k)"),
    xy.y_axis(label="channel"),
    title="Sessions by channel",
)


def sessions_by_channel():
    return reflex_xy.chart(chart, height="320px")
~~~

## Grouped and Stacked Bars

Add one named `bar` mark per series and include a `legend()` to compare
categories across groups. Set `base` to stack each series on top of the
previous one — pass the cumulative totals so bars sit flush — or leave `base`
off to place bars side by side.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

teams = ["Alpha", "Beta", "Gamma", "Delta"]
open_ = np.array([12, 9, 15, 7])
closed = np.array([28, 22, 19, 31])

chart = xy.bar_chart(
    xy.bar(teams, open_, name="Open", color="#6e56cf", orientation="horizontal"),
    xy.bar(teams, closed, base=open_, name="Closed", color="#c4b5fd", orientation="horizontal"),
    xy.x_axis(label="tickets"),
    xy.y_axis(label="team"),
    xy.legend(),
    title="Ticket status by team",
)


def ticket_status_by_team():
    return reflex_xy.chart(chart, height="320px")
~~~

## Column Charts (Vertical Bars)

A **column chart** is the same mark drawn vertically: use `column` (or `bar`
with `orientation="vertical"`, the default) when categories are ordered — such
as quarters or months — so the left-to-right reading follows time. Columns
stack the same way bars do, with `base` set to the running total below each
series.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
signups = np.array([120, 145, 138, 172, 190, 210])

chart = xy.column_chart(
    xy.column(months, signups, color="#6e56cf", corner_radius=4),
    xy.x_axis(label="month"),
    xy.y_axis(label="signups"),
    title="Monthly signups",
)


def monthly_signups():
    return reflex_xy.chart(chart, height="320px")
~~~

Stack several `column` marks the same way as bars — pass a pair to
`corner_radius`, such as `corner_radius=(5, 0)`, to round only the exposed top:

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
    xy.column(quarters, values[:, 0], name="Core", color="#6e56cf"),
    xy.column(quarters, values[:, 1], base=values[:, 0], name="Growth", color="#8e7cc3"),
    xy.column(
        quarters,
        values[:, 2],
        base=values[:, 0] + values[:, 1],
        name="Enterprise",
        color="#c4b5fd",
        corner_radius=(5, 0),
    ),
    xy.legend(),
    title="Quarterly product mix",
)


def quarterly_mix():
    return reflex_xy.chart(chart, height="320px")
~~~

## Interactive Bar Charts

Every bar chart is interactive out of the box — drag to pan, scroll or pinch to
zoom, and hover to read exact values in a
[tooltip](/docs/xy/components/tooltips/). The same chart renders in a notebook,
a Reflex app, or exported HTML with no extra configuration.

## Bar Chart Options

| Option | Purpose |
| --- | --- |
| `orientation` | `"horizontal"` for bars, `"vertical"` for columns. |
| `mode` | `"grouped"`, `"stacked"`, or `"normalized"` for multi-series layout. |
| `base` | Stacking baseline as a scalar, array, or another bar series. |
| `color` | Bar fill color (any CSS color). |
| `corner_radius` | Rounded bar corners in pixels. |
| `width` | Bar thickness as a fraction of the category band. |
| `opacity` | Bar opacity from 0 to 1. |
| `name` | Series label shown in the `legend()`. |

Pass column names with `data=` instead of arrays when your data is a table.
Note `bar` and `column` share the same implementation — use `bar` for
horizontal category comparison and `column` for vertical.

## Related Charts

- [Histograms](/docs/xy/charts/histogram/) — for the distribution of a single
  continuous variable rather than named categories.
- [Line charts](/docs/xy/charts/line-chart/) — for a continuous trend over time
  rather than discrete category comparison.

## FAQ

### How do I make a horizontal bar chart in Python?

Call `xy.bar(categories, values, orientation="horizontal")` inside
`xy.bar_chart(...)` and render it. The resulting bar plot pans, zooms, and
hovers automatically.

### What is the difference between a bar chart and a column chart in xy?

They share one implementation. A bar chart uses `orientation="horizontal"` so
bars run left to right; a column chart runs vertical. Pick the name that reads
best in your app.

### How do I stack bars in a Python bar chart?

Add one named `bar` mark per series and set `base` on each stacked series to the
running total of the series below it, then add `xy.legend()`.

### How do I sort bars by value?

Order your category and value arrays before passing them to `bar`; the chart
draws categories in the order you supply.
