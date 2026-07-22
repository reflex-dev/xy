---
title: Scatter Plot in Python
description: Create interactive scatter plots in Python with xy. Explore relationships, clusters, and outliers across millions of points with pan, zoom, and hover.
components:
  - xy.scatter_chart
---

# Scatter Plots in Python

## When to Use

A scatter plot (also called a scatter chart or scatter graph) accepts NumPy
arrays directly and preserves interactive navigation.
Use one for relationships, clusters, outliers, and multichannel point data.

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

## Styled Color Encoding

Map a value array to color with a fixed `color_domain`, pick a non-default
`symbol`, and add a crisp border with `stroke` and `stroke_width`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

style_rng = np.random.default_rng(11)
angle = style_rng.uniform(0, 4 * np.pi, 3_000)
radius = angle / (4 * np.pi) + style_rng.normal(scale=0.03, size=angle.size)
spiral_x = radius * np.cos(angle)
spiral_y = radius * np.sin(angle)

styled_scatter_chart = xy.scatter_chart(
    xy.scatter(
        spiral_x,
        spiral_y,
        color=angle,
        colormap="plasma",
        color_domain=(0.0, 4 * np.pi),
        symbol="diamond",
        size=7,
        stroke="#1a1a2e",
        stroke_width=1.0,
        opacity=0.9,
    ),
    xy.x_axis(label="x position"),
    xy.y_axis(label="y position"),
    title="Angle-colored spiral",
)


def styled_scatter_demo():
    return reflex_xy.chart(styled_scatter_chart, height="320px")
~~~

## Bubble Chart with Multiple Series

Encode a third variable as marker area with `size` plus `size_range`, give each
cluster its own named series and `symbol`, and let `xy.legend()` label them.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

bubble_rng = np.random.default_rng(42)
cluster_specs = [
    ("Compact", (-1.5, -0.8), 0.35, "circle"),
    ("Midsize", (0.4, 0.9), 0.55, "square"),
    ("Sprawling", (2.1, -0.4), 0.85, "triangle"),
]
bubble_marks = []
for series_name, (cx, cy), spread, marker in cluster_specs:
    bx = bubble_rng.normal(cx, spread, 400)
    by = bubble_rng.normal(cy, spread, 400)
    magnitude = np.hypot(bx - cx, by - cy)
    bubble_marks.append(
        xy.scatter(
            bx,
            by,
            name=series_name,
            size=magnitude,
            size_range=(3, 22),
            symbol=marker,
            opacity=0.45,
        )
    )

bubble_chart = xy.scatter_chart(
    *bubble_marks,
    xy.x_axis(label="component 1"),
    xy.y_axis(label="component 2"),
    xy.legend(title="Cluster"),
    title="Three clusters, size by distance from center",
)


def bubble_scatter_demo():
    return reflex_xy.chart(bubble_chart, height="320px")
~~~

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

## FAQ

### How do I make a scatter plot in Python?

Call `xy.scatter(x, y)` inside `xy.scatter_chart(...)` and render it. Pan, zoom,
and hover work automatically — no extra configuration required.

### How many points can an xy scatter plot handle?

Millions. When individual markers become sub-pixel, `xy` automatically switches
to a bounded density surface and refines back toward exact points as you zoom.

### How do I color scatter points by a value?

Pass an array (or column name) to `color` and choose a `colormap`; use
`color_domain` to fix the value range. Categorical values create a stable
palette instead.

### How do I make a bubble chart in Python?

Pass a value array to `size` along with `size_range` to map it to pixel
diameters — a bubble chart is a scatter plot with a third variable encoded as
point size.
