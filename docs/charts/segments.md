---
title: Line Segment Chart in Python
description: Draw line segments in Python with xy. Plot independent start-to-end segments for transitions, ranges, and arbitrary geometry, interactive by default.
components:
  - xy.segments_chart
---

# Line Segment Charts in Python

A **line segments** chart (also called a segment plot or segment graph) draws
independent start-to-end segments, each with its
own pair of endpoints. With `xy` you plot line segments in Python for
transitions, ranges, or arbitrary geometry that a connected line can't express,
and you can color each segment by a data channel. Every segment chart is
interactive out of the box: pan, zoom, and hover work with no configuration.

Jump to [creating a segment chart](#create-a-segment-chart),
[when to use segments](#when-to-use-segments), or the
[options](#line-segment-options).

## Create a Segment Chart

Pass start endpoints (`x0`, `y0`) and end endpoints (`x1`, `y1`) to `segments`.
Each row becomes one independent segment, and a per-segment `color` channel maps
through the `colormap`:

~~~python demo exec
import reflex_xy
import xy

segments_detail_chart = xy.segments_chart(
    xy.segments(
        x0=[0, 1, 2, 3, 4],
        y0=[1, 2, 1.5, 3, 2.5],
        x1=[0.8, 1.8, 2.8, 3.8, 4.8],
        y1=[2.2, 1.2, 3.1, 2.1, 4.0],
        color=[0.1, 0.3, 0.5, 0.7, 0.9],
        colormap="viridis",
        width=4,
    ),
    xy.x_axis(label="start to end"),
    xy.y_axis(label="value"),
    title="Independent transitions",
)


def segments_demo():
    return reflex_xy.chart(segments_detail_chart, height="340px")
~~~

## Draw Ranges as Horizontal Segments

Give every segment the same `y0` and `y1` to draw horizontal ranges — one row
per category — and use a constant `color` with a thick `width` and reduced
`opacity` for a Gantt-style timeline:

~~~python demo exec
import reflex_xy
import xy

task_row = [0, 1, 2, 3, 4]
start_day = [0.0, 2.0, 3.5, 6.0, 8.5]
end_day = [3.0, 5.5, 7.0, 9.0, 12.0]

range_segments_chart = xy.segments_chart(
    xy.segments(
        x0=start_day,
        y0=task_row,
        x1=end_day,
        y1=task_row,
        color="#2563eb",
        width=10,
        opacity=0.75,
    ),
    xy.x_axis(label="day"),
    xy.y_axis(
        label="task",
        tick_values=[0, 1, 2, 3, 4],
        tick_labels=["Design", "Prototype", "Review", "Build", "Ship"],
    ),
    title="Task ranges",
)


def range_segments_demo():
    return reflex_xy.chart(range_segments_chart, height="340px")
~~~

## Map a Color Channel with a Colorbar

Pass a numeric array to `color`, pin its scale with `domain`, and add
`xy.colorbar()` so readers can decode the mapped values — here a slope field
colored by gradient:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

grid_x, grid_y = np.meshgrid(np.linspace(-2, 2, 9), np.linspace(-2, 2, 9))
gx = grid_x.ravel()
gy = grid_y.ravel()
slope = gy - gx**2 / 2
step_len = 0.16 / np.sqrt(1 + slope**2)

slope_field_chart = xy.segments_chart(
    xy.segments(
        x0=gx - step_len,
        y0=gy - slope * step_len,
        x1=gx + step_len,
        y1=gy + slope * step_len,
        color=slope,
        colormap="plasma",
        domain=(-4.0, 2.0),
        width=2.2,
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    xy.colorbar(title="dy/dx"),
    title="Slope field",
)


def slope_field_segments_demo():
    return reflex_xy.chart(slope_field_chart, height="340px")
~~~

## When to Use Segments

Segments draw independent start-to-end line segments, each with its own
endpoints, so they suit transitions, ranges, error bars, or arbitrary geometry
that isn't a single ordered path. When observations form one continuous trend
that should be connected in order, use the
[line chart](/docs/xy/charts/line-chart/). For discrete impulses anchored to a
baseline, use the [stem plot](/docs/xy/charts/stem-plot/).

## Line Segment Options

| Option | Purpose |
| --- | --- |
| `x0` / `y0` | Start endpoint of each segment. |
| `x1` / `y1` | End endpoint of each segment. |
| `color` | Constant color, or a per-segment channel mapped through `colormap`. |
| `colormap` | Named colormap for the `color` channel, e.g. `"viridis"`. |
| `width` | Segment stroke width in pixels. |
| `opacity` | Segment opacity from 0 to 1. |

Pass column names with `data=` instead of arrays when your endpoints live in a
table.

## Related Charts

- [Stem plots](/docs/xy/charts/stem-plot/) — impulses anchored to a common
  baseline.
- [Line charts](/docs/xy/charts/line-chart/) — connect ordered observations into
  a single trend.

## FAQ

### How do I draw line segments in Python?

Call `xy.segments(x0=..., y0=..., x1=..., y1=...)` inside `xy.segments_chart(...)`
and render it. Each row of endpoints becomes one independent segment.

### How do I color each segment differently?

Pass a per-segment list to `color` and set a `colormap`. Each segment's value is
mapped through the colormap; pass a single CSS color instead for a constant hue.

### How are segments different from a line chart?

A line chart connects ordered points into one continuous path. Segments are
independent — each has its own start and end — so they can point in any
direction and need not share endpoints.

### Can I use segments for ranges or error bars?

Yes. Set the start and end endpoints to the low and high values of each range;
because every segment is independent, they can represent arbitrary intervals.
