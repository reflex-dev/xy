---
title: Reflex Integration
description: Render XY charts as first-class Reflex components.
---

# Reflex Integration

The `reflex-xy` adapter renders an XY chart as a first-class Reflex component.
The core `xy` package stays framework-neutral: application state and events
remain in Reflex while XY owns chart data, rendering, and interaction math.

## Install and Configure

Install both packages and register the adapter plugin:

~~~bash
uv add xy reflex-xy
~~~

~~~python
# rxconfig.py
import reflex as rx
import reflex_xy

config = rx.Config(
    app_name="dashboard",
    plugins=[reflex_xy.XYPlugin()],
)
~~~

The plugin attaches XY's binary data plane to the Reflex app's existing
Socket.IO server. It does not add another HTTP service or websocket endpoint to
deploy.

## Fixed Charts

Pass a regular `xy.Chart` directly to `reflex_xy.chart` when its data does not
depend on state. The adapter compiles a content-addressed binary asset during
the frontend build, so the result works with `reflex export` and needs no
backend connection.

~~~python
import numpy as np
import reflex as rx
import reflex_xy
import xy as fc

t = np.linspace(0, 4 * np.pi, 800)


def index() -> rx.Component:
    return reflex_xy.chart(
        fc.line_chart(
            fc.line(t, np.sin(t), name="signal"),
            fc.x_axis(label="t"),
            title="Static payload",
            width="100%",
            height=280,
        ),
        height="280px",
    )
~~~

These documentation previews use this static tier. Hover, pan, zoom, and local
density refinement remain interactive in the browser.

## State-Backed Charts

Use `@reflex_xy.figure` when chart data depends on session state. The computed
var stores only an opaque token; numeric columns travel as binary frames over
the app's existing websocket rather than through Reflex state JSON.

~~~python
import numpy as np
import reflex as rx
import reflex_xy
import xy as fc


class Dashboard(rx.State):
    points: int = 20_000
    hovered: dict = {}

    @reflex_xy.figure
    def cloud(self) -> fc.Chart:
        rng = np.random.default_rng(7)
        x = rng.normal(size=self.points)
        y = 0.6 * x + rng.normal(scale=0.6, size=self.points)
        return fc.scatter_chart(
            fc.scatter(x, y, density=True),
            width="100%",
            height=420,
        )

    @rx.event
    def on_hover(self, row: dict):
        self.hovered = row


def index() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(
            Dashboard.cloud,
            on_point_hover=Dashboard.on_hover,
            height="420px",
        ),
        rx.text(Dashboard.hovered.to_string()),
        width="100%",
    )
~~~

Figure builders may also be `async def`, following the same rules as Reflex
async computed vars.

## Events and Streaming

`on_point_hover`, `on_point_click`, `on_select_end`, and `on_view_change`
dispatch small semantic payloads through normal Reflex event handlers. Large
chart buffers never enter those payloads.

To extend a registered chart from an event or background task, append new
points without rebuilding the component:

~~~python
reflex_xy.append(token, x=[next_x], y=[next_y])
~~~

## Choose a Data Tier

| Source passed to `reflex_xy.chart` | Best for | Backend |
| --- | --- | --- |
| `xy.Chart` | Fixed, exportable charts | None |
| `reflex_xy.inline(chart)` | Fixed data with kernel round-trips | XY registry |
| `@reflex_xy.figure` var | Session and state-driven charts | Reflex + XY registry |

`inline()` should run at module scope so every backend worker registers the
same content-addressed token.

## Custom Chrome Slots

Legend, tooltip, and colorbar components can retain opaque framework objects:

~~~python
import xy as fc

custom_legend = object()
custom_tooltip = object()

chart = fc.scatter_chart(
    fc.scatter([1, 2], [3, 5]),
    fc.legend(custom_legend, show=False),
    fc.tooltip(custom_tooltip, show=False),
)

chrome = chart.reflex_components()
assert chrome["legend"] is custom_legend
~~~

The adapter can mount those objects beside its chart host. Opaque render
objects never enter standalone HTML.

~~~md alert warning
### Experimental Boundary

The Reflex adapter and callback payload details are still experimental. Build
against `reflex_xy.chart`, `@reflex_xy.figure`, and `reflex_xy.append` rather
than private transport or registry modules.
~~~
