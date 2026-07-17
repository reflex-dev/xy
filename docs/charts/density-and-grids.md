---
title: Density and Grid Charts
description: Render matrices, binned point density, and contour fields.
---

# Density and Grid Charts

## When to Use

Use `heatmap` for an existing matrix, `hexbin` to aggregate point clouds, and
`contour` for isolines or filled levels over a scalar field.

## Live Demo

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.linspace(-3, 3, 80)
y = np.linspace(-2, 2, 60)
xx, yy = np.meshgrid(x, y)
z = np.exp(-(xx**2 + yy**2))

chart = xy.heatmap_chart(
    xy.heatmap(z, x=x, y=y, colormap="viridis"),
)


def heatmap_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

## Variants

### Hexbin

~~~python
rng = np.random.default_rng(21)
points_x = rng.normal(size=100_000)
points_y = 0.65 * points_x + rng.normal(scale=0.55, size=points_x.size)

chart = xy.hexbin_chart(
    xy.hexbin(points_x, points_y, gridsize=72, mincnt=1),
)
~~~

Hexbin supports count bins or an additional `C` channel reduced per cell with
`reduce_C_function`.

### Contours

~~~python
chart = xy.contour_chart(
    xy.contour(z, x=x, y=y, levels=12, filled=True, colormap="viridis"),
)
~~~

## Expected Data Shape

Heatmaps and contours take a two-dimensional z matrix with optional x and y
coordinates. Hexbin takes equal-length x and y point arrays and may take a
third value channel to reduce within each cell.

## Key Options

Heatmaps use `colormap`, `domain`, and `opacity`. Hexbin uses `gridsize`,
`bins`, `mincnt`, `C`, and `reduce_C_function`. Contours use `levels`,
`filled`, `colormap`, `width`, `opacity`, and `dash_negative`.

The colormap is encoded directly into these marks. Declarative
[`xy.colorbar()`](/docs/xy/components/colorbars/) only configures or replaces
colorbar chrome; it does not generate colorbar metadata from a mark's colormap
and domain. Without adapter-supplied metadata it adds no visible scale, so the
examples omit it.

`hexbin` bins source points in the native engine and ships occupied cell
centers plus values, so its rendered geometry is bounded by `gridsize`; the
binning pass still scales with source rows. `heatmap` ships the supplied grid
as a GPU texture, and contour work scales with grid cells times levels. These
marks do not use scatter's automatic density tier.
