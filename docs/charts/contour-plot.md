---
title: Contour Plot in Python
description: Contour plot python made easy with xy. Draw filled or line iso-value contours over a 2D field, set levels and a colormap, and pan and zoom smoothly.
components:
  - xy.contour_chart
---

# Contour Plots in Python

A **contour plot** (also called a contour graph) in python draws iso-value lines across a 2D field so ridges,
basins, and gradients in the surface become visible. With `xy` you build an
interactive contour plot from a NumPy grid: choose the number of levels, fill
between them or keep clean lines, and pan, zoom, and hover work by default.

Jump to [creating a contour plot](#create-a-contour-plot),
[levels and fills](#levels-filled-and-line-contours), or
[the options table](#contour-plot-options).

## Create a Contour Plot

Pass a 2D array of values to `contour`, with optional `x` and `y` coordinates.
Set `levels` to control how many iso-value bands are drawn and `filled=True` to
shade between them:

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

## Line Contours at Explicit Levels

Keep `filled=False` for clean iso-lines and pass `levels` an explicit list to
place contours at exact values — useful when specific thresholds matter — with
`width` thickening the strokes:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

ridge_x = np.linspace(-3, 3, 110)
ridge_y = np.linspace(-2.5, 2.5, 90)
ridge_xx, ridge_yy = np.meshgrid(ridge_x, ridge_y)
ridge_z = np.exp(-(ridge_xx**2 + ridge_yy**2) / 2.4) * (
    1.0 + 0.35 * np.sin(3.0 * ridge_xx)
)

contour_lines_chart = xy.contour_chart(
    xy.contour(
        ridge_z,
        x=ridge_x,
        y=ridge_y,
        levels=[0.1, 0.2, 0.35, 0.5, 0.7, 0.9],
        filled=False,
        colormap="plasma",
        width=2.0,
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Line contours at explicit levels",
)


def contour_lines_demo():
    return reflex_xy.chart(contour_lines_chart, height="340px")
~~~

## Signed Fields with Dashed Negatives

For a field that crosses zero, set `dash_negative=True` so negative contours
are dashed, use more `levels` to resolve the structure, and add an
`xy.colorbar()` to tie levels back to values:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

dipole_x = np.linspace(-3, 3, 120)
dipole_y = np.linspace(-3, 3, 120)
dipole_xx, dipole_yy = np.meshgrid(dipole_x, dipole_y)
dipole_z = np.exp(-((dipole_xx - 1) ** 2 + dipole_yy**2)) - np.exp(
    -((dipole_xx + 1) ** 2 + dipole_yy**2)
)

contour_signed_chart = xy.contour_chart(
    xy.contour(
        dipole_z,
        x=dipole_x,
        y=dipole_y,
        levels=18,
        filled=False,
        colormap="coolwarm",
        width=1.6,
        dash_negative=True,
    ),
    xy.colorbar(title="field strength"),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Dipole field, dashed negatives",
)


def contour_signed_demo():
    return reflex_xy.chart(contour_signed_chart, height="340px")
~~~

## Levels, Filled, and Line Contours

`levels` sets how many iso-value bands the field is sliced into — more levels
resolve finer structure. Keep `filled=False` for clean contour lines, or set
`filled=True` to shade each band with the `colormap`. Use `dash_negative` to
distinguish contours below zero, which is handy for signed fields.

## Contour Plot Options

| Option | Purpose |
| --- | --- |
| `levels` | Number of iso-value bands, or an explicit list of level values. |
| `filled` | `True` to shade between contours, `False` for lines only. |
| `colormap` | Named color scale mapping levels to color. |
| `width` | Contour line stroke width in pixels. |
| `opacity` | Contour opacity from 0 to 1. |
| `dash_negative` | Dash contours with negative values to distinguish sign. |

Add [`xy.colorbar()`](/docs/xy/components/colorbars/) to show the level-to-color
scale. Pass column names with `data=` instead of arrays when your data is a
table.

## Related Charts

- [Heatmaps](/docs/xy/charts/heatmap/) — color every grid cell instead of
  drawing bands.
- [Hexbin plots](/docs/xy/charts/hexbin/) — build a density field from scattered
  points.
- [Colorbar component](/docs/xy/components/colorbars/) — add a visible color
  scale to a contour plot.

## FAQ

### How do I make a contour plot in Python?

Pass a 2D array to `xy.contour(z, x=x, y=y)` inside `xy.contour_chart(...)` and
render it. The contour chart supports pan, zoom, and hover out of the box.

### What is the difference between a filled and a line contour?

`filled=False` draws only the iso-value lines; `filled=True` shades each band
between contours with the `colormap` for a continuous surface look.

### How do I control the number of contour levels?

Set `levels` to an integer for that many evenly spaced bands, or pass an
explicit list of values to place contours at exact levels.

### How do I show negative contours differently?

Set `dash_negative=True` so contours with negative values are dashed, making the
sign of a signed field easy to read.
