---
title: Scatter Charts
description: Render and explore large point collections.
components:
  - xy.scatter_chart
---

# Scatter Charts

## When to Use

Scatter charts accept NumPy arrays directly and preserve interactive navigation.
Use them for relationships, clusters, outliers, and multichannel point data.

## Live Demo

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(7)
x = rng.normal(size=20_000)
y = 0.55 * x + rng.normal(scale=0.65, size=x.size)

chart = xy.scatter_chart(
    xy.scatter(
        x,
        y,
        color=y,
        size=np.abs(y),
        colormap="viridis",
        size_range=(2, 14),
        opacity=0.55,
    ),
    xy.x_axis(label="feature A"),
    xy.y_axis(label="feature B"),
    title="20k interactive points",
)


def scatter_chart_demo():
    return reflex_xy.chart(chart, height="420px")
~~~

Selections in a live widget resolve canonical source rows even when the visible
overview is aggregated. Point hover becomes available when the view refines to
direct points; the density surface itself does not pretend that a pixel is one
source row.

## Scatter

Use `scatter` for individual observations positioned by two variables. Optional
size, color, symbol, opacity, and stroke channels can reveal additional groups
or measures without changing the x/y relationship.

## Variants

`color` and `size` accept constants, arrays, or named columns. Numeric color
uses `colormap` and optional `color_domain`; categorical color creates a stable
palette. `size_range` maps numeric size values into pixel diameters.

Markers support 17 renderer-backed symbols, from `circle`, `square`, and
directional triangles through `star`, `hexagon`, pixel/point, and line-only
glyphs, plus `stroke` and `stroke_width` for crisp borders. The complete list
is in [Customize Each Part](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients).

## Expected Data Shape

Pass equal-length one-dimensional x and y values, or resolve both from a
mapping, DataFrame, or Arrow-compatible table through `data=`. Optional color
and size channels may be constants, matching arrays, or column names.

## Key Options

Use `symbol`, `size`, `size_range`, `color`, `colormap`, `color_domain`,
`opacity`, `stroke`, and `stroke_width`. Set `density` only when you need to
override automatic tier selection.

### Density Mode

Large point collections automatically switch to a bounded density surface when
individual markers become sub-pixel. Set `density=True` to force aggregation,
`False` to keep points, or leave it as `None` for automatic selection. Zooming
can refine the visible window back toward exact points.
