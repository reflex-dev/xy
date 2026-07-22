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

## Chart Types

### Heatmap

Use `heatmap` when values already form a two-dimensional matrix and color should
encode each cell.

### Hexbin

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(21)
points_x = rng.normal(size=100_000)
points_y = 0.65 * points_x + rng.normal(scale=0.55, size=points_x.size)

hexbin_detail_chart = xy.hexbin_chart(
    xy.hexbin(
        points_x,
        points_y,
        gridsize=72,
        mincnt=1,
        colormap="viridis",
    ),
    xy.x_axis(label="signal A"),
    xy.y_axis(label="signal B"),
    title="Correlated point density",
)


def hexbin_demo():
    return reflex_xy.chart(hexbin_detail_chart, height="340px")
~~~

Hexbin supports count bins or an additional `C` channel reduced per cell with
`reduce_C_function`.

### Contour

~~~python demo exec
import numpy as np
import reflex_xy
import xy

contour_x = np.linspace(-3, 3, 100)
contour_y = np.linspace(-2.5, 2.5, 90)
contour_xx, contour_yy = np.meshgrid(contour_x, contour_y)
contour_z = (
    np.exp(-((contour_xx - 0.8) ** 2 + contour_yy**2))
    + 0.7 * np.exp(-((contour_xx + 1.1) ** 2 + (contour_yy - 0.5) ** 2))
)

contour_detail_chart = xy.contour_chart(
    xy.contour(
        contour_z,
        x=contour_x,
        y=contour_y,
        levels=14,
        filled=True,
        colormap="viridis",
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Density contours",
)


def contour_demo():
    return reflex_xy.chart(contour_detail_chart, height="340px")
~~~

## Expected Data Shape

Heatmaps and contours take a two-dimensional z matrix with optional x and y
coordinates. Hexbin takes equal-length x and y point arrays and may take a
third value channel to reduce within each cell.

## Key Options

Heatmaps use `colormap`, `domain`, and `opacity`. Hexbin uses `gridsize`,
`bins`, `mincnt`, `C`, and `reduce_C_function`. Contours use `levels`,
`filled`, `colormap`, `width`, `opacity`, and `dash_negative`.

The colormap is encoded directly into these marks. Add declarative
[`xy.colorbar()`](/docs/xy/components/colorbars/) to derive visible scale
chrome from the last compatible heatmap, hexbin, or contour domain and
colormap. Use its `title`, `orientation`, and `ticks` options to override the
inferred presentation.

`hexbin` bins source points in the native engine and ships occupied cell
centers plus values, so its rendered geometry is bounded by `gridsize`; the
binning pass still scales with source rows. The browser keeps that compact
shape on the GPU—three floats per occupied cell—and generates the shared
hexagon ring in an instanced vertex shader; it does not materialize or upload
six triangles per cell. `heatmap` ships the supplied grid as a GPU texture, and
contour work scales with grid cells times levels. These marks do not use
scatter's automatic density tier.
