---
title: Scatter Charts
description: Render and explore large point collections.
---

# Scatter Charts

Scatter charts accept NumPy arrays directly and preserve interactive navigation.

## Create a Scatter Chart

~~~python demo exec
import numpy as np
import reflex_xy
import xy as fc

rng = np.random.default_rng(7)
x = rng.normal(size=20_000)
y = 0.55 * x + rng.normal(scale=0.65, size=x.size)

chart = fc.scatter_chart(
    fc.scatter(
        x,
        y,
        color=y,
        size=np.abs(y),
        colormap="viridis",
        size_range=(2, 14),
        opacity=0.55,
    ),
    fc.x_axis(label="feature A"),
    fc.y_axis(label="feature B"),
    title="20k interactive points",
)


def scatter_chart_demo():
    return reflex_xy.chart(chart, height="420px")
~~~

Hover and selection resolve canonical source rows even when the visible
overview uses an aggregated representation.

## Color and Size Encodings

`color` and `size` accept constants, arrays, or named columns. Numeric color
uses `colormap` and optional `color_domain`; categorical color creates a stable
palette. `size_range` maps numeric size values into pixel diameters.

Markers support `circle`, `square`, `diamond`, `triangle`, and `cross` symbols,
plus `stroke` and `stroke_width` for crisp borders.

## Density Mode

Large point collections automatically switch to a bounded density surface when
individual markers become sub-pixel. Set `density=True` to force aggregation,
`False` to keep points, or leave it as `None` for automatic selection. Zooming
can refine the visible window back toward exact points.
