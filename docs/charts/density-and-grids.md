---
title: Density and Grid Charts
description: Render matrices, binned point density, and contour fields.
---

# Density and Grid Charts

Use `heatmap` for an existing matrix, `hexbin` to aggregate point clouds, and
`contour` for isolines or filled levels over a scalar field.

## Heatmaps

~~~python
import numpy as np
import xy as fc

x = np.linspace(-3, 3, 80)
y = np.linspace(-2, 2, 60)
xx, yy = np.meshgrid(x, y)
z = np.exp(-(xx**2 + yy**2))

chart = fc.heatmap_chart(
    fc.heatmap(z, x=x, y=y, colormap="viridis"),
    fc.colorbar(),
)
~~~

`domain=(min, max)` fixes the color window. `x` and `y` may provide numeric or
categorical cell coordinates.

## Hexbin

~~~python
rng = np.random.default_rng(21)
points_x = rng.normal(size=100_000)
points_y = 0.65 * points_x + rng.normal(scale=0.55, size=points_x.size)

chart = fc.hexbin_chart(
    fc.hexbin(points_x, points_y, gridsize=72, mincnt=1),
    fc.colorbar(),
)
~~~

Hexbin supports count bins or an additional `C` channel reduced per cell with
`reduce_C_function`.

## Contours

~~~python
chart = fc.contour_chart(
    fc.contour(z, x=x, y=y, levels=12, filled=True, colormap="viridis"),
)
~~~

## Live Reflex Preview

~~~python demo-only exec
import reflex_xy
import xy as fc


def density_preview():
    values = [
        [0.05, 0.12, 0.20, 0.12, 0.05],
        [0.10, 0.28, 0.52, 0.28, 0.10],
        [0.18, 0.50, 1.00, 0.50, 0.18],
        [0.10, 0.28, 0.52, 0.28, 0.10],
        [0.05, 0.12, 0.20, 0.12, 0.05],
    ]
    figure = fc.heatmap_chart(
        fc.heatmap(
            values,
            x=["Mon", "Tue", "Wed", "Thu", "Fri"],
            y=["North", "East", "Central", "South", "West"],
            colormap="viridis",
        ),
        fc.colorbar(),
        title="Activity density",
    )
    return reflex_xy.chart(figure, height="360px")
~~~
