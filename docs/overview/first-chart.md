---
title: Your First Chart
description: Build and display a minimal XY scatter chart from Python.
---

# Your First Chart

An XY chart is a small component tree: a chart container owns layout and output,
while marks and axes describe what belongs inside it.

## In a Python script

Build the chart once and choose how to display it. The demo below renders the
same `xy.Chart` that the script exports; the small `first_chart_demo()` function
is only the Reflex wrapper used by this documentation site.

~~~python demo exec
import xy

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3, 4], [3, 5, 4, 7], color="#6e56cf", size=10),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    title="First chart",
)


# This documentation site uses Reflex to render the chart above.
def first_chart_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="320px")


if __name__ == "__main__":
    chart.to_html("scatter.html")
~~~

Run the file with `python first_chart.py`, then open `scatter.html`. Hover, pan,
zoom, and the built-in controls run locally; the exported file does not need a
Python process or network connection. In your own script or notebook, you do
not need the `first_chart_demo()` wrapper.

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
