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

## JupyterLite and Pyodide (WASM Kernels)

XY publishes a Pyodide/Emscripten wheel, so `%pip install xy` works in a
JupyterLite notebook. Hosted deployments with a prebuilt frontend — for
example [try Jupyter](https://jupyter.org/try-jupyter/lab/) — cannot load the
`anywidget` frontend extension at runtime, because `%pip` installs only the
kernel-side package. Displaying the live widget there fails in the browser
with `Failed to load model class 'AnyModel' from module 'anywidget'`.

On WASM kernels XY therefore switches to its standalone-HTML display host
automatically: `chart.show()` (or a bare `chart`) renders the same
self-contained interactive document as `to_html()` inside an isolated iframe.
Pan, zoom, hover, the modebar, and export all work in the browser. Python
callbacks (`on_select`, ...), `chart.append(...)` live refreshes, and
kernel-served zoom refinement need the live widget host, so they stay
inactive on the HTML host; re-run the cell to display mutated chart state.

Marimo is the exception among WASM hosts: it ships its own anywidget frontend
as part of the app, so charts in Marimo's WASM build keep the live widget
host automatically.

Override the automatic choice per call with `chart.show(display="widget")` /
`chart.show(display="html")`, or process-wide with the `XY_NOTEBOOK_DISPLAY`
environment variable (`auto`, `widget`, or `html`):

~~~python
import os

os.environ["XY_NOTEBOOK_DISPLAY"] = "widget"
~~~

Forcing `widget` is useful in a self-built JupyterLite deployment that added
`anywidget` to `jupyter lite build`, where the frontend extension does exist.

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

## Run the Examples on Binder

The repository's example notebooks run hosted, with no local install, on
[mybinder.org](https://mybinder.org/v2/gh/reflex-dev/xy/main?urlpath=lab/tree/examples)
(the launch badge in the README opens the same link). Binder compiles XY from
source at the launched ref — including the native Rust core — so the
notebooks match the code of that revision; this link and the badge launch
`main`, and any branch or tag can be substituted in the URL. Expect the first
launch after a new commit to take several minutes while the image builds;
later launches reuse it.

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
