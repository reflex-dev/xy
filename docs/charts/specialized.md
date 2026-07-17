---
title: Specialized Charts
description: Draw stems, segments, thresholds, and triangle meshes.
---

# Specialized Charts

## When to Use

XY includes compact marks for impulses, explicit geometry, and precomputed
triangle topology. It also includes `threshold`, a semantic rule annotation.
Step and stairs charts live with
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
    xy.threshold(6, text="target", color="#6e56cf"),
    xy.legend(),
)


def specialized_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

## Variants

### Independent Segments

~~~python
chart = xy.segments_chart(
    xy.segments(
        x0=[0, 1, 2],
        y0=[0, 1, 0],
        x1=[1, 2, 3],
        y1=[1, 0, 2],
        color=[0.2, 0.6, 1.0],
    )
)
~~~

### Triangle Meshes

`triangle_mesh` accepts explicit `x0/y0`, `x1/y1`, and `x2/y2` vertices for
each triangle, plus a constant color or per-triangle color values, a colormap,
stroke, and opacity. It is the low-level choice for irregular surfaces and
precomputed topology.

## Expected Data Shape

`stem` takes matching one-dimensional x and y arrays. `segments` takes matching
start/end coordinate arrays. `triangle_mesh` takes three x/y vertex pairs per
triangle. `threshold` takes one coordinate and an axis.

## Key Options

Stems expose line and marker styling. Segments expose width, opacity, and color
channels. The `threshold` annotation exposes axis, text, color, width, and
opacity. Triangle meshes expose constant or per-triangle color, `domain`,
`colormap`, stroke, and opacity.
