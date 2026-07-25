---
title: Heatmap in Python
description: Heatmap python made easy with xy. Render a matrix as an interactive colored grid, pick a colormap, set the value domain, and add a colorbar scale.
components:
  - xy.heatmap_chart
---

# Heatmaps in Python

A **python heatmap** (also written as heat map, and sometimes called a heatmap
chart or heatmap plot) maps a 2D grid of values onto a color scale so patterns,
clusters, and gradients read at a glance. With `xy` you build an interactive
heatmap in Python from a NumPy matrix: pan, zoom, and hover work by default, and
the grid stays crisp as you navigate.

Jump to [creating a heatmap](#create-a-heatmap),
[choosing a colormap](#colormaps-and-value-domain), or
[adding a colorbar](#add-a-colorbar-scale).

## Create a Heatmap

Pass a 2D array of values to `heatmap`, with optional `x` and `y` coordinates
for the grid edges. This is the minimal Python heatmap:

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

## Diverging Colormap with a Fixed Domain

A signed field reads best with a diverging `colormap`, an explicit
`domain=(min, max)` pinned symmetrically around zero, and an `xy.colorbar()` so
the scale is visible:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

wave_x = np.linspace(0, 4 * np.pi, 120)
wave_y = np.linspace(0, 2 * np.pi, 80)
wave_xx, wave_yy = np.meshgrid(wave_x, wave_y)
wave_z = np.sin(wave_xx) * np.cos(wave_yy)

heatmap_scale_chart = xy.heatmap_chart(
    xy.heatmap(wave_z, x=wave_x, y=wave_y, colormap="coolwarm", domain=(-1, 1)),
    xy.colorbar(title="amplitude"),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Standing wave, fixed domain",
)


def heatmap_scale_demo():
    return reflex_xy.chart(heatmap_scale_chart, height="360px")
~~~

## Correlation-Matrix Heatmap

A small labeled grid turns a heatmap into a correlation matrix: pass cell
coordinates for `x` and `y`, relabel the ticks with feature names, fix
`domain=(-1, 1)`, and add a colorbar with explicit `ticks`:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

corr_rng = np.random.default_rng(3)
factors = corr_rng.normal(size=(300, 2))
loadings = corr_rng.normal(scale=0.7, size=(2, 6))
signals = factors @ loadings + corr_rng.normal(scale=0.5, size=(300, 6))
corr = np.corrcoef(signals, rowvar=False)
feature_labels = ["open", "high", "low", "close", "volume", "spread"]
feature_positions = np.arange(len(feature_labels), dtype=float)

corr_matrix_chart = xy.heatmap_chart(
    xy.heatmap(
        corr,
        x=feature_positions,
        y=feature_positions,
        colormap="coolwarm",
        domain=(-1, 1),
        opacity=1.0,
    ),
    xy.colorbar(title="correlation", ticks=[-1, -0.5, 0, 0.5, 1]),
    xy.x_axis(
        tick_values=feature_positions,
        tick_labels=feature_labels,
        tick_label_angle=-40,
    ),
    xy.y_axis(tick_values=feature_positions, tick_labels=feature_labels),
    title="Feature correlation matrix",
)


def heatmap_corr_demo():
    return reflex_xy.chart(corr_matrix_chart, height="360px")
~~~

## Colormaps and Value Domain

The `colormap` controls how values map to color — sequential maps like
`"viridis"` suit magnitudes, while a diverging map reads better around a
midpoint. Set `domain` to fix the value range the colors span, so separate
heatmaps stay comparable instead of each rescaling to its own min and max.

## Add a Colorbar Scale

A heatmap is only readable with a legend for its colors. Add an
[`xy.colorbar()`](/docs/xy/components/colorbars/) to draw a visible scale that
ties each color back to a value. Use `opacity` to blend the grid over other
marks when you overlay a heatmap on additional context.

## Heatmap Options

| Option | Purpose |
| --- | --- |
| `colormap` | Named color scale, e.g. `"viridis"`, mapping values to color. |
| `domain` | `(min, max)` value range the colors span; fixes the scale across charts. |
| `opacity` | Grid opacity from 0 to 1, for overlaying on other marks. |

Add [`xy.colorbar()`](/docs/xy/components/colorbars/) to show the value-to-color
scale. Pass column names with `data=` instead of arrays when your data is a
table.

## Related Charts

- [Hexbin plots](/docs/xy/charts/hexbin/) — bin scattered points into a colored
  hexagonal grid.
- [Contour plots](/docs/xy/charts/contour-plot/) — draw iso-value lines over a
  field.
- [Colorbar component](/docs/xy/components/colorbars/) — add a visible color
  scale to any heatmap.

## FAQ

### How do I make a heatmap in Python?

Pass a 2D array to `xy.heatmap(z, x=x, y=y)` inside `xy.heatmap_chart(...)` and
render it. The rendered heatmap graph pans, zooms, and hovers without extra
configuration.

### How do I change the heatmap colors?

Set `colormap` on `heatmap`, for example `colormap="viridis"`. Sequential maps
suit magnitudes; diverging maps read better around a midpoint.

### How do I add a color scale legend to a heatmap?

Add [`xy.colorbar()`](/docs/xy/components/colorbars/) to the chart to draw a
visible scale tying each color back to a value.

### How do I keep two heatmaps on the same color scale?

Set the same `domain=(min, max)` on both so the colors span an identical value
range instead of each rescaling to its own data.
