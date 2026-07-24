---
title: Your First Chart
description: Create an interactive XY chart in a Python script or notebook, then choose where to go next.
---

# Your First Chart

You only need the core `xy` package to create, display, and export a chart. The
same chart object works in a Python script and a notebook; only the final
display line changes.

If XY is not installed yet, follow [Installation](/docs/xy/overview/installation/).

## Script path: export interactive HTML

Save this as `first_chart.py`:

~~~python
import random

import xy

rng = random.Random(7)
x = [rng.random() for _ in range(200)]
y = [rng.random() for _ in x]

chart = xy.scatter_chart(
    xy.scatter(x, y, color="#6e56cf", size=7, opacity=0.65),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="200 random points",
)

chart.to_html("scatter.html")
~~~

Run it, then open the `scatter.html` file it writes next to the script:

~~~bash
python first_chart.py
~~~

This is the chart it produces, live:

~~~python demo-only exec
import random

import reflex_xy
import xy

rng = random.Random(7)
x = [rng.random() for _ in range(200)]
y = [rng.random() for _ in x]

first_chart = xy.scatter_chart(
    xy.scatter(x, y, color="#6e56cf", size=7, opacity=0.65),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="200 random points",
)


def first_chart_demo():
    return reflex_xy.chart(first_chart, height="320px")
~~~

`scatter.html` is self-contained. Hover, pan, zoom, and the built-in controls
run locally without a Python process or network connection.
The seeded random generator keeps the example reproducible while filling the
plot with enough points to make those interactions useful.

## Notebook path: display a live widget

Run this cell in Jupyter, JupyterLab, VS Code, Colab, Marimo, or another
compatible anywidget frontend:

~~~python
import random

import xy

rng = random.Random(7)
x = [rng.random() for _ in range(200)]
y = [rng.random() for _ in x]

chart = xy.scatter_chart(
    xy.scatter(x, y, color="#6e56cf", size=7, opacity=0.65),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="200 random points",
)

chart
~~~

Leaving `chart` as the final expression displays the interactive widget. Use
`chart.show()` when an explicit display call is clearer. See
[Notebooks](/docs/xy/integrations/notebooks/) for supported hosts, callbacks,
and troubleshooting.

## What each part does

- `scatter()` binds the x/y values and describes the rendered marks.
- `x_axis()` and `y_axis()` add labeled axes.
- `scatter_chart()` composes the marks, axes, title, interactions, and output
  methods into one `Chart`.
- `to_html()`, `to_png()`, `to_svg()`, `show()`, and `widget()` all use that
  same chart; changing output does not require rebuilding it.

## Same code, millions of points

Those four values are a placeholder, not a limit. Hand the same mark a few
million points and nothing else in the script changes: XY switches the scatter
to a screen-bounded density view and keeps pan, zoom, and hover smooth.

~~~python
import numpy as np
import xy

rng = np.random.default_rng(0)
x = rng.normal(size=2_500_000)
y = x * 0.6 + rng.normal(scale=0.8, size=x.size)

chart = xy.scatter_chart(
    xy.scatter(x, y, size=4),
    title="2.5 million points",
)

chart.to_html("big_scatter.html")
~~~

~~~python demo-only exec
import numpy as np
import reflex_xy
import xy

big_rng = np.random.default_rng(0)
big_x = big_rng.normal(size=2_500_000)
big_y = big_x * 0.6 + big_rng.normal(scale=0.8, size=big_x.size)

million_point_chart = xy.scatter_chart(
    xy.scatter(big_x, big_y, size=4),
    title="2.5 million points",
)


def million_point_demo():
    return reflex_xy.chart(million_point_chart, height="320px")
~~~

Zoom in and the view refines back toward exact points. Read
[Large data and performance](/docs/xy/core-concepts/large-data-and-performance/)
for how the density switch works.

## Choose your next step

- Bring NumPy, Pandas, or Arrow values into a chart with
  [Data and columns](/docs/xy/core-concepts/data/).
- Start from the visual result you need in the
  [Chart Gallery](/docs/xy/overview/gallery/).
- Customize colors, typography, and component chrome in
  [Styling](/docs/xy/styling/).
- Export HTML, PNG, SVG, or image batches with
  [Display and export](/docs/xy/guides/display-and-export/).
