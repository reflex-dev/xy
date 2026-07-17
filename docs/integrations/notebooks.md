---
title: Notebooks
description: Display interactive XY charts in Jupyter, VS Code, Colab, and Marimo.
---

# Notebooks

An XY chart displays interactively when it is the final expression in a
Jupyter, JupyterLab, VS Code, Colab, or Marimo cell.

~~~python
import numpy as np
import xy

x = np.linspace(0, 8, 400)
chart = xy.line_chart(
    xy.line(x, np.sin(x), name="signal"),
    xy.x_axis(label="time"),
    xy.y_axis(label="value"),
)

chart
~~~

Use `chart.show()` or `chart.widget()` as the final expression when explicit
display intent is clearer. Both return the live widget; `show()` does not open
a separate desktop window. In code that calls IPython directly, passing
`chart.widget()` to `display()` is equivalent.

## One Widget Across Notebook Hosts

XY uses one `anywidget` implementation across the supported notebook hosts.
The chart spec travels as small JSON metadata and numeric columns travel as
binary comm frames instead of JSON number arrays.

The JavaScript/WebGL client is bundled in the installed XY wheel. Notebook
display does not fetch a client from a CDN, so it also works in an air-gapped
runtime once the Python packages are installed.

## Callbacks

Pass `on_hover`, `on_click`, `on_brush`, `on_select`, or `on_view_change` to a
chart container. Supplying a callback enables the corresponding interaction
and routes its semantic payload to Python.

~~~python
import xy


def selected(selection):
    print(len(selection), "rows")


chart = xy.scatter_chart(
    xy.scatter([0, 1, 2], [2, 4, 3]),
    on_select=selected,
)
chart
~~~

These are core `xy.Chart` callback keywords for the live notebook widget.
They are not Reflex component props: the Reflex adapter instead accepts
`on_point_hover`, `on_point_click`, `on_select_end`, and `on_view_change` on
the outer `reflex_xy.chart(...)` component. Notebook `on_select` receives an
`xy.Selection` with canonical row indices; Reflex `on_select_end` receives a
small JSON-safe selection summary. See
[Interactions and selections](/docs/xy/core-concepts/interactions/) for the
full mapping.

Notebook callbacks need a live widget. A standalone HTML export keeps browser
interactions but cannot call into the notebook kernel; a framework adapter uses
its own event surface.

## Streaming in a Notebook

Calling `chart.append(...)` after the widget exists updates the browser client
and refreshes the widget's synchronized state. If the widget has not been
created, the next display or export uses the mutated chart state. See
[Real-time and streaming data](/docs/xy/guides/real-time-and-streaming-data/)
for validation rules and snapshot behavior.

## Display Problems

After installing or upgrading XY in a running notebook environment, restart
the kernel so Python and the bundled client come from the same installation.
If a chart remains blank, see [Troubleshooting](/docs/xy/guides/troubleshooting/).
