---
title: Specialized Charts
description: Draw stems, independent segments, and triangle meshes.
components:
  - xy.stem_chart
  - xy.segments_chart
  - xy.triangle_mesh_chart
---

# Specialized Charts

## When to Use

XY includes compact marks for impulses, explicit geometry, and precomputed
triangle topology. Thresholds belong to the
[annotation guide](/docs/xy/components/annotations/). Step and stairs charts live with
[line and area charts](/docs/xy/charts/line-and-area/).

## Live Demo

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.arange(10)
values = np.array([2, 5, 3, 7, 6, 9, 8, 11, 10, 13])

chart = xy.chart(
    xy.stem(x, values - 1.5, name="Events", color="#2563eb"),
    xy.legend(),
)


def specialized_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

## Chart Types

### Stem

Use `stem` for discrete values or impulses that should remain visibly anchored
to a baseline.

### Segments

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

### Triangle Mesh

`triangle_mesh` accepts explicit `x0/y0`, `x1/y1`, and `x2/y2` vertices for
each triangle, plus a constant color or per-triangle color values, a colormap,
stroke, and opacity. It is the low-level choice for irregular surfaces and
precomputed topology.

~~~python demo exec
import reflex_xy
import xy

triangle_mesh_detail_chart = xy.triangle_mesh_chart(
    xy.triangle_mesh(
        x0=[0, 1, 1, 2],
        y0=[0, 0, 1, 0],
        x1=[1, 2, 2, 3],
        y1=[0, 0, 1, 0],
        x2=[0.5, 1.5, 1.5, 2.5],
        y2=[1.2, 1.4, 2.2, 1.6],
        color=[0.15, 0.4, 0.7, 1.0],
        colormap="purples",
        domain=(0, 1),
        stroke="#6d28d9",
        stroke_width=1.2,
        opacity=0.8,
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Irregular triangle surface",
)


def triangle_mesh_demo():
    return reflex_xy.chart(triangle_mesh_detail_chart, height="340px")
~~~

## Expected Data Shape

`stem` takes matching one-dimensional x and y arrays. `segments` takes matching
start/end coordinate arrays. `triangle_mesh` takes three x/y vertex pairs per
triangle.

## Key Options

Stems expose line and marker styling. Segments expose width, opacity, and color
channels. Triangle meshes expose constant or per-triangle color, `domain`,
`colormap`, stroke, and opacity.
