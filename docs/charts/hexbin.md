---
title: Hexbin Plot in Python
description: Hexbin python made simple with xy. Bin large point clouds into a hexagonal density grid, count or reduce a value per cell, and color by a colormap.
components:
  - xy.hexbin_chart
---

# Hexbin Plots in Python

A **hexbin plot** (also called a hexbin chart or hexbin graph) in python
aggregates a dense point cloud into a hexagonal grid, coloring each cell by how
many points fall inside it. With `xy` you build
an interactive hexbin from millions of points without overplotting: pan, zoom,
and hover work by default, and dense regions stay legible.

Jump to [creating a hexbin](#create-a-hexbin-plot),
[value channels](#count-bins-and-value-channels), or
[the options table](#hexbin-options).

## Create a Hexbin Plot

Pass paired x and y arrays to `hexbin`. It aggregates large point clouds into a
grid of hexagonal cells, so a scatter that would smear into a solid blob becomes
a readable density map:

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

## Tune the Grid and Add a Colorbar

Pass a `(nx, ny)` tuple to `gridsize` to control cell resolution per axis,
raise `mincnt` to clear out sparse background cells, swap the `colormap`, and
add an `xy.colorbar()` so the count scale is readable:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

hx_rng = np.random.default_rng(5)
cluster_a = hx_rng.normal(loc=(-1.5, -1.0), scale=(0.5, 0.9), size=(60_000, 2))
cluster_b = hx_rng.normal(loc=(1.8, 1.4), scale=(0.9, 0.4), size=(60_000, 2))
clusters = np.vstack([cluster_a, cluster_b])

hexbin_tuned_chart = xy.hexbin_chart(
    xy.hexbin(
        clusters[:, 0],
        clusters[:, 1],
        gridsize=(48, 36),
        mincnt=5,
        colormap="magma",
    ),
    xy.colorbar(title="points per cell"),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Two clusters, tuned grid",
)


def hexbin_tuned_demo():
    return reflex_xy.chart(hexbin_tuned_chart, height="340px")
~~~

## Color Cells by a Mean Value

Instead of counting points, pass a `C` value array and a `reduce_C_function`
such as `np.mean` — each cell is colored by the reduced value of the samples
that land in it, turning scattered measurements into a surface:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

survey_rng = np.random.default_rng(9)
site_x = survey_rng.uniform(-2.5, 2.5, size=40_000)
site_y = survey_rng.uniform(-2.5, 2.5, size=40_000)
elevation = np.exp(-(site_x**2 + site_y**2)) + survey_rng.normal(
    scale=0.05, size=site_x.size
)

hexbin_weighted_chart = xy.hexbin_chart(
    xy.hexbin(
        site_x,
        site_y,
        C=elevation,
        reduce_C_function=np.mean,
        gridsize=40,
        mincnt=3,
        colormap="plasma",
    ),
    xy.colorbar(title="mean elevation"),
    xy.x_axis(label="easting (km)"),
    xy.y_axis(label="northing (km)"),
    title="Mean elevation per cell",
)


def hexbin_weighted_demo():
    return reflex_xy.chart(hexbin_weighted_chart, height="340px")
~~~

## Count Bins and Value Channels

By default each cell is colored by its point count. Raise `gridsize` for finer
cells and use `mincnt` to hide sparse cells below a threshold. To color by a
quantity instead of a raw count, pass a `C` value array and set
`reduce_C_function` (for example `np.mean`) to reduce the values that fall in
each cell into a single color.

## Hexbin Options

| Option | Purpose |
| --- | --- |
| `gridsize` | Number of hexagons across; higher means finer cells. |
| `bins` | Color-scale binning, e.g. `"log"` for skewed counts. |
| `mincnt` | Minimum points a cell needs to be drawn. |
| `C` | Optional value array reduced per cell instead of counting points. |
| `reduce_C_function` | Reducer applied to `C` in each cell, e.g. `np.mean`. |
| `colormap` | Named color scale mapping cell values to color. |
| `opacity` | Cell opacity from 0 to 1. |

Add [`xy.colorbar()`](/docs/xy/components/colorbars/) to show the value-to-color
scale. Pass column names with `data=` instead of arrays when your data is a
table.

## Related Charts

- [Heatmaps](/docs/xy/charts/heatmap/) — color a regular grid of precomputed
  values.
- [Contour plots](/docs/xy/charts/contour-plot/) — draw iso-value lines over a
  density field.
- [Scatter charts](/docs/xy/charts/scatter/) — plot individual points when the
  cloud is small enough to read.

## FAQ

### How do I make a hexbin plot in Python?

Pass paired x and y arrays to `xy.hexbin(x, y)` inside `xy.hexbin_chart(...)` and
render it. Cells are colored by point count automatically.

### When should I use a hexbin instead of a scatter?

Use a hexbin when a scatter overplots — tens of thousands of points or more that
smear into a solid mass. Hexbin aggregates them into a density grid you can read.

### How do I color a hexbin by a value instead of a count?

Pass a `C` value array and set `reduce_C_function`, such as `np.mean`, to reduce
the values in each cell into a single color.

### How do I hide sparse hexagons?

Set `mincnt` to the minimum number of points a cell must contain before it is
drawn, which clears out near-empty background cells.
