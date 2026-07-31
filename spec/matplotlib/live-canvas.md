# Matplotlib live canvas

`FigureCanvasXY` has two connected browser hosts: a kernel-connected anywidget
in IPython, and an authenticated loopback host for ordinary Python scripts.
Both are separate from the native `xy.FigureWidget`: compat figures retain
genuine Matplotlib `Figure`, `Axes`, `Artist`, callback-registry, widget, and
event semantics.

```python
import matplotlib

matplotlib.use("module://xy.backends.backend_xy")
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.plot([0, 1], [0, 1])

display(fig.canvas.widget)
# Equivalent explicit method form:
assert fig.canvas.get_widget() is fig.canvas.widget
assert fig.canvas.manager.widget is fig.canvas.widget
```

`plt.show()` displays that cached widget once when IPython is active. Outside
IPython it starts a stdlib-only server on an ephemeral `127.0.0.1` port and
opens the default browser at a per-figure URL containing a random 256-bit
token. The server accepts only exact same-token paths, caps JSON event bodies,
serves no remote assets, and applies a restrictive CSP. Closing the figure
stops the server and releases its thread and port.

The view refreshes its SVG from the shared, fallback-free XY display list after
every `draw()` or `draw_idle()`. Resizing the view changes the Matplotlib figure
size and causes a fresh draw.

The browser maps pointer or mouse movement, press, release, double-click,
wheel, enter, leave, keyboard, resize, and close input to Matplotlib's
`MouseEvent`, `LocationEvent`, `KeyEvent`, `ResizeEvent`, and `CloseEvent`
classes. Events run through Matplotlib's normal `_process()` route, so
`mpl_connect`, callback registries, picking, Matplotlib widgets, and axes
enter/leave behavior receive standard event objects. Browser coordinates are
scaled to the figure's logical device dimensions and converted to Matplotlib's
bottom-left origin. The loopback server only queues input; blocking `show()`
and `flush_events()` dispatch it on Matplotlib's Python thread. Browser timer
heartbeats drive the same deadline-checked event loop for live animations.

## Standalone boundary

Live callbacks require a running Python process and either the anywidget comm or
the loopback `show()` host. The HTML from `DisplayList.to_html()` and
`FigureCanvasXY.print_html()` is deliberately static: it contains the rendered
display list but does not start a server or claim that arbitrary Python
callbacks remain available after the process exits.

A standalone document may embed precomputed animation frames. It is not a live
Matplotlib canvas, and tests and documentation must not describe it as one.
