---
title: Your First Chart
description: Build and display a minimal XY scatter chart from Python.
---

# Your First Chart

An XY chart is a small component tree: a chart container owns layout and output,
while marks and axes describe what belongs inside it.

## In a Python script

Create a scatter chart and write one self-contained interactive HTML file:

~~~python
import xy

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3, 4], [3, 5, 4, 7], color="#6e56cf", size=10),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    title="First chart",
)
chart.to_html("scatter.html")
~~~

The same chart is rendered live below. Hover the points or use the toolbar to
pan, zoom, and reset the view.

~~~python demo-only exec
import reflex_xy
import xy

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3, 4], [3, 5, 4, 7], color="#6e56cf", size=10),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    title="First chart",
)


def first_chart_demo():
    return reflex_xy.chart(chart, height="320px")
~~~

Open `scatter.html` in a browser. Hover, pan, zoom, and the built-in controls
run locally; the file does not need a Python process or a network connection
after export.

## In a notebook

Run the same construction code in Jupyter, JupyterLab, VS Code, Colab, Marimo,
or another compatible anywidget frontend, then leave the chart as the final
expression in a cell:

~~~python
chart
~~~

XY displays the interactive widget automatically. Use `chart.show()` when an
explicit display call is clearer.

## What each line contributes

- `scatter()` is the rendered mark and binds the x/y values.
- `scatter_chart()` composes the mark, axes, title, interaction settings, and
  output methods into a `Chart`.
- `to_html()`, `to_png()`, `to_svg()`, `show()`, and `widget()` all read from
  that same chart; changing output does not require rebuilding it.

Continue with [Data and columns](/docs/xy/core-concepts/data/), browse the
[Gallery](/docs/xy/overview/gallery/), or customize the result in
[Styling](/docs/xy/styling/).
