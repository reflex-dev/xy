---
title: Reflex
description: Render fixed and state-backed XY charts as first-class Reflex components.
components:
  - reflex_xy.chart
  - reflex_xy.data
  - reflex_xy.figure
  - reflex_xy.scatter_chart
  - reflex_xy.line_chart
  - reflex_xy.inline
  - reflex_xy.append
---

# Reflex

The experimental Reflex integration bundled with `xy` renders an XY chart as a
first-class Reflex component. The core stays framework-neutral at runtime:
application state and events remain in Reflex while XY owns chart data,
rendering, and interaction math.

## Install and Configure

Install the `reflex` extra from PyPI. It installs the supported Reflex
dependency floor; the `reflex_xy` import namespace is already included in
every `xy` wheel:

~~~~md tabs
## uv

~~~bash
uv add "xy[reflex]"
~~~

## pip

~~~bash
python -m pip install "xy[reflex]"
~~~
~~~~

Then register the bundled plugin:

~~~python
# rxconfig.py
import reflex as rx
import reflex_xy as rxy

config = rx.Config(
    app_name="dashboard",
    plugins=[rxy.XYPlugin()],
)
~~~

The plugin attaches XY's binary data plane to the Reflex app's existing
Socket.IO server. It does not add another HTTP service or websocket endpoint to
deploy.

## Fixed Data

Pass concrete columns through `data=` when they do not depend on state. The
adapter compiles a content-addressed binary asset during the frontend build, so
the result works with `reflex export` and needs no backend connection.

~~~python demo exec
import numpy as np
import reflex as rx
import reflex_xy as rxy
import xy

t = np.linspace(0, 4 * np.pi, 800)


def index() -> rx.Component:
    return rxy.line_chart(
        data={"t": t, "signal": np.sin(t)},
        x="t",
        y="signal",
        x_axis=xy.x_axis(label="t"),
        title="Static payload",
        height="280px",
    )
~~~

Static charts retain browser-local hover, pan, zoom, and density refinement.
They do not dispatch backend event handlers because there is no live kernel to
resolve semantic event payloads.

## State-Backed Data

Use `@rxy.data` when chart columns depend on session state. Declare the
chart where it renders and return only its columns from the state method. The
chart structure is validated when `reflex run` compiles the app, without
running the data method. At runtime the computed var holds only a typed handle;
numeric columns travel as binary frames over the app's existing websocket
rather than through Reflex state JSON.

~~~python demo exec
from typing import TypedDict

import numpy as np
import reflex as rx
import reflex_xy as rxy


class CloudData(TypedDict):
    x: np.ndarray
    y: np.ndarray
    magnitude: np.ndarray


class Dashboard(rx.State):
    points: int = 20_000
    hovered: dict = {}

    @rxy.data
    def cloud(self) -> CloudData:
        rng = np.random.default_rng(7)
        x = rng.normal(size=self.points)
        y = 0.6 * x + rng.normal(scale=0.6, size=self.points)
        return {"x": x, "y": y, "magnitude": np.hypot(x, y)}

    @rx.event
    def record_hover(self, event: rxy.PointHoverEvent):
        self.hovered = {**event.get("data", {}), **event.get("datum", {})}


def index() -> rx.Component:
    return rx.vstack(
        rxy.scatter_chart(
            data=Dashboard.cloud,
            x="x",
            y="y",
            color="magnitude",
            colormap="viridis",
            density=True,
            on_point_hover=Dashboard.record_hover,
            height="420px",
        ),
        rx.text(Dashboard.hovered.to_string()),
        width="100%",
    )
~~~

The `TypedDict` return annotation lets the integration catch misspelled column
names while the page compiles. A plain mapping return type also works, but its
column names can only be checked when the data method first runs. Data methods
may be `async def` and may return `None` when no data is currently available.

### Compose Multiple Marks

For multiple marks, pass data-free XY nodes to `rxy.chart`. Channel values are
column-name strings, and every mark binds to the same data handle:

~~~python
from typing import TypedDict

import numpy as np
import reflex as rx
import reflex_xy as rxy
import xy


class TrendData(TypedDict):
    x: np.ndarray
    y: np.ndarray
    magnitude: np.ndarray


class Trends(rx.State):
    @rxy.data
    def samples(self) -> TrendData:
        x = np.linspace(0, 10, 1_000)
        y = np.sin(x)
        return {"x": x, "y": y, "magnitude": np.abs(y)}


def trends() -> rx.Component:
    return rxy.chart(
        xy.scatter("x", "y", color="magnitude", density=True),
        xy.line("x", "magnitude", name="magnitude"),
        xy.x_axis(label="feature A"),
        xy.legend(),
        data=Trends.samples,
        height="420px",
    )
~~~

Both the flat factories such as `rxy.scatter_chart` and composed `rxy.chart`
build a data-free plan at page evaluation. Invalid chart options and unknown
columns in a typed schema therefore fail at compile time rather than producing
a blank chart in the browser. Changing state republishes only the columns under
the stable data handle, preserving the mounted chart's view and selection.

Data handles are ordinary Reflex vars. They can be selected with `rx.cond`, or
collected in a typed `list[rxy.DataHandle[Schema]]` for `rx.foreach`, as long as
each source satisfies the chart's column schema.

Use `@rxy.data` for every state-backed chart whose marks, axes, and other
structure can be declared in the page. `@rxy.figure` remains an escape hatch
only for the uncommon case where state changes that structure itself.

## Events and Streaming

`on_point_hover`, `on_point_click`, `on_select_end`, `on_view_change`,
`on_animation_start`, and `on_animation_end` dispatch small semantic payloads
through normal Reflex event handlers. Large
chart buffers never enter those payloads. These props belong on the outer
`rxy` chart factory and work with a live `@rxy.data` source.

They are separate from the core callbacks accepted by `xy` chart containers.
Core `on_hover`, `on_click`, `on_brush`, `on_select`, and `on_view_change`
callbacks are ordinary Python callables for the notebook widget. The Reflex
adapter does not turn those callbacks into Reflex events. Instead, use its
component props:

| Core notebook callback | Reflex component prop | Reflex payload |
| --- | --- | --- |
| `on_hover` | `on_point_hover` | Resolved row dictionary |
| `on_click` | `on_point_click` | Resolved row dictionary |
| `on_brush` | No dedicated prop | — |
| `on_select` | `on_select_end` | JSON-safe summary with `total`, optional bounds, and `cleared` |
| `on_view_change` | `on_view_change` | View dictionary |
| `xy.animation(on_start=...)` | `on_animation_start` | Animation phase/view dictionary |
| `xy.animation(on_end=...)` | `on_animation_end` | Animation phase/view dictionary, with `cancelled` on interruption |

In particular, notebook `on_select` receives an `xy.Selection` with canonical
row indices, while Reflex `on_select_end` receives a compact summary suitable
for an ordinary Reflex event. See
[Interactions and selections](/docs/xy/core-concepts/interactions/) for the
core callback contract.

State-driven full payloads update the existing browser view in place, so
stable mark `key=` values and an `xy.animation(match="key")` child preserve
identity across a Reflex recompute. See
[Animations and data transitions](/docs/xy/styling/animations/).

To extend a registered chart from an event or background task, append new
points without rebuilding the component:

~~~python
rxy.append(token, x=[next_x], y=[next_y])
~~~

See [Real-time and streaming data](/docs/xy/guides/real-time-and-streaming-data/)
for the mutation and snapshot contract.

## Choose a Data Tier

| Component source | Best for | Backend |
| --- | --- | --- |
| Concrete columns: `rxy.scatter_chart(data={...}, ...)` | Fixed, compile-bound columns | None |
| An `@rxy.data` var: `rxy.scatter_chart(data=State.data, ...)` | State-driven columns with fixed, compile-validated structure | Reflex + XY registry |

Prefer the concrete-column form for fixed data and `@rxy.data` for state-backed
data. Both use the same compile-validated chart API; only the transport changes.

## Custom Chrome Slots

Legend, tooltip, and colorbar components can retain opaque framework objects:

~~~python
import xy

custom_legend = object()
custom_tooltip = object()

chart = xy.scatter_chart(
    xy.scatter([1, 2], [3, 5]),
    xy.legend(custom_legend, show=False),
    xy.tooltip(custom_tooltip, show=False),
)

chrome = chart.reflex_components()
assert chrome["legend"] is custom_legend
~~~

The shipped adapter does not currently mount those objects beside its chart
host. A custom adapter can read `chart.chrome_components()` (or its
`reflex_components()` alias) and mount them alongside the chart. Opaque render
objects never enter standalone HTML. For ordinary DOM customization, use the
[Customize Each Part](/docs/xy/styling/customize/#legend) slot styling guide.

~~~md alert warning
### Experimental Boundary

The Reflex adapter and callback payload details are still experimental. Pin
`xy` when you need a stable integration contract, and build against
`rxy.chart`, `@rxy.data`, and `rxy.append` rather than private transport or
registry modules.
~~~
