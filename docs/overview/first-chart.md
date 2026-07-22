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

Build the chart once and choose how to display it. The small
`first_chart_demo()` function only lets this documentation site show the live
result; you do not need it in your own script or notebook.

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

Run it and open the generated file:

~~~bash
python first_chart.py
~~~

`scatter.html` is self-contained. Hover, pan, zoom, and the built-in controls
run locally without a Python process or network connection.

## Notebook path: display a live widget

Run this cell in Jupyter, JupyterLab, VS Code, Colab, Marimo, or another
compatible anywidget frontend:

~~~python
import xy

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3, 4], [3, 5, 4, 7], color="#6e56cf", size=10),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    title="First chart",
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

## Choose your next step

- Bring NumPy, Pandas, or Arrow values into a chart with
  [Data and columns](/docs/xy/core-concepts/data/).
- Start from the visual result you need in the
  [Chart Gallery](/docs/xy/overview/gallery/).
- Customize colors, typography, and component chrome in
  [Styling](/docs/xy/styling/).
- Export HTML, PNG, SVG, or image batches with
  [Display and export](/docs/xy/guides/display-and-export/).
