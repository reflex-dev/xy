---
title: Specialized Charts
description: Draw steps, stairs, stems, segments, and triangle meshes.
---

# Specialized Charts

XY includes compact marks for discrete signals and explicit geometry.

## Step, Stairs, and Stem

~~~python demo exec
import numpy as np
import reflex_xy
import xy as fc

x = np.arange(10)
values = np.array([2, 5, 3, 7, 6, 9, 8, 11, 10, 13])

chart = fc.chart(
    fc.step(x, values, where="post", name="State", color="#6e56cf"),
    fc.stem(x, values - 1.5, name="Events", color="#2563eb"),
    fc.legend(),
)


def specialized_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

`stairs(values, edges=...)` is useful when bin edges are already known. `where`
on step-like marks controls whether transitions occur before, at, or after a
sample.

## Independent Segments

~~~python
chart = fc.segments_chart(
    fc.segments(
        x0=[0, 1, 2],
        y0=[0, 1, 0],
        x1=[1, 2, 3],
        y1=[1, 0, 2],
        color=[0.2, 0.6, 1.0],
    )
)
~~~

## Triangle Meshes

`triangle_mesh` accepts explicit `x0/y0`, `x1/y1`, and `x2/y2` vertices for
each triangle, plus optional scalar color, colormap, stroke, and opacity. It is
the low-level choice for irregular surfaces and precomputed topology.
