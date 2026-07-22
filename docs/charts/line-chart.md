---
title: Line Chart in Python
description: Create interactive line charts in Python with xy. Plot smooth curves, multiple series, and millions of points with real-time pan and zoom — no lag.
components:
  - xy.line_chart
---

# Line Charts in Python

A **line chart** (also called a line graph or line plot) connects ordered
observations to show a trend over time or any
continuous sequence. With `xy` you create an interactive line chart in Python
that stays smooth at millions of points: pan, zoom, and hover work by default,
and long lines are decimated to the visible resolution and refined as you zoom.

Jump to [multiple series](#plot-multiple-line-series),
[smooth curves](#smooth-vs-straight-lines), or
[large and real-time data](#large-and-real-time-line-charts).

## Create a Line Chart

Pass equal-length x and y arrays to `line`. This is the minimal Python line
chart:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

month = np.arange(12)
revenue = np.array([12, 15, 14, 19, 22, 21, 27, 30, 29, 34, 38, 41])

chart = xy.chart(
    xy.line(month, revenue, color="#6e56cf", width=2.5),
    xy.x_axis(label="month"),
    xy.y_axis(label="revenue ($k)"),
    title="Monthly revenue",
)


def basic_line_chart():
    return reflex_xy.chart(chart, height="320px")
~~~

## Interactive Line Charts

Every line chart is interactive out of the box — drag to pan, scroll or pinch to
zoom, and hover to inspect exact values with a [tooltip](/docs/xy/components/tooltips/).
No configuration is required; the same chart renders in a notebook, a Reflex
app, or exported HTML.

## Smooth vs. Straight Lines

Keep the default straight segments when each observation should stay explicit,
or set `curve="smooth"` for interpolation. Use `dash` for plan/actual or
forecast comparisons.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.linspace(0, 12, 240)
plan = 48 + 1.8 * x
actual = plan + 7 * np.sin(x * 0.9)

chart = xy.chart(
    xy.line(x, plan, name="Plan", color="#2563eb", dash="dashed"),
    xy.line(x, actual, name="Actual", color="#6e56cf", width=2.5, curve="smooth"),
    xy.x_axis(label="month"),
    xy.y_axis(label="revenue"),
    xy.legend(),
    title="Plan vs. actual",
)


def smooth_line_chart():
    return reflex_xy.chart(chart, height="320px")
~~~

## Plot Multiple Line Series

Layer several named `line` marks and add a `legend()` to compare series. Bind
marks to named axes when series use different units. The example above overlays
two series; add as many as you need.

## Large and Real-Time Line Charts

`xy` is built for large data: a line with millions of points renders as a
decimated path sized to the screen, then refines when the viewport changes, so
navigation never blocks. For streaming updates, see
[real-time and streaming data](/docs/xy/guides/real-time-and-streaming-data/),
and for the performance model see
[large data and performance](/docs/xy/core-concepts/large-data-and-performance/).

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(0)
t = np.linspace(0, 100, 200_000)
signal = np.sin(t) + rng.normal(0, 0.1, t.size)

chart = xy.chart(
    xy.line(t, signal, color="#6e56cf"),
    xy.x_axis(label="time (s)"),
    xy.y_axis(label="signal"),
    title="200,000-point line",
)


def large_line_chart():
    return reflex_xy.chart(chart, height="320px")
~~~

## Line Chart Options

| Option | Purpose |
| --- | --- |
| `color` | Line color (any CSS color). |
| `width` | Stroke width in pixels. |
| `opacity` | Line opacity from 0 to 1. |
| `curve` | `"linear"` (default) or `"smooth"` for interpolation. |
| `dash` | Dash pattern, e.g. `"dashed"`, for plan/actual comparisons. |
| `name` | Series label shown in the `legend()`. |

Missing numeric values create gaps in the line. Pass column names with `data=`
instead of arrays when your data is a table.

## Related Charts

- [Area charts](/docs/xy/charts/area-chart/) — fill the region to a baseline.
- [Step and stairs charts](/docs/xy/charts/area-chart/#step-and-stairs) — for
  piecewise-constant states.
- [Scatter charts](/docs/xy/charts/scatter/) — for relationships without a
  connecting line.

## FAQ

### How do I make an interactive line chart in Python?

Call `xy.line(x, y)` inside `xy.chart(...)` and render it. Pan, zoom, and hover
are enabled automatically — no callbacks or extra libraries required.

### How many points can a line chart plot?

Millions. `xy` decimates a long line to the visible pixels and refines it on
zoom, so a multi-million-point line stays interactive instead of freezing the
page.

### How do I plot multiple lines on one chart?

Add one named `line` mark per series inside the same `xy.chart(...)` and include
`xy.legend()`.

### How do I draw a smooth line instead of straight segments?

Pass `curve="smooth"` to `line`. Omit it to keep straight segments between
observations.
