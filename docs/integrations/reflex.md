---
title: Reflex
description: Render fixed and state-backed XY charts as first-class Reflex components.
---

# Reflex

The experimental `reflex-xy` adapter renders an XY chart as a first-class
Reflex component. The core `xy` package stays framework-neutral: application
state and events remain in Reflex while XY owns chart data, rendering, and
interaction math.

~~~md alert warning
### Unreleased Adapter

`reflex-xy` is not published on PyPI. The adapter is an opt-in prototype whose
API and event payloads may change before its first release. Install it from the
tagged Git subdirectory below; installing it by package name alone with uv or
pip will not work.
~~~

## Install and Configure

Pair the public `xy` 0.0.1 wheel with the adapter from the matching `v0.0.1`
repository tag. Pinning both sides avoids mixing an unreleased adapter revision
with a different core API:

~~~~md tabs
## uv

~~~bash
uv add "xy==0.0.1" "reflex-xy @ git+https://github.com/reflex-dev/xy.git@v0.0.1#subdirectory=python/reflex-xy"
~~~

## pip

~~~bash
python -m pip install "xy==0.0.1" "reflex-xy @ git+https://github.com/reflex-dev/xy.git@v0.0.1#subdirectory=python/reflex-xy"
~~~
~~~~

The adapter installs Reflex as a dependency. Then register its plugin:

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
import xy

t = np.linspace(0, 4 * np.pi, 800)


def index() -> rx.Component:
    return reflex_xy.chart(
        xy.line_chart(
            xy.line(t, np.sin(t), name="signal"),
            xy.x_axis(label="t"),
            title="Static payload",
            width="100%",
            height=280,
        ),
        height="280px",
    )
~~~

Static charts retain browser-local hover, pan, zoom, and density refinement.
They do not dispatch backend event handlers because there is no live kernel to
resolve semantic event payloads.

## State-Backed Charts

Use `@reflex_xy.figure` when chart data depends on session state. The computed
var stores only an opaque token; numeric columns travel as binary frames over
the app's existing websocket rather than through Reflex state JSON.

~~~python
import numpy as np
import reflex as rx
import reflex_xy
import xy


class Dashboard(rx.State):
    points: int = 20_000
    hovered: dict = {}

    @reflex_xy.figure
    def cloud(self) -> xy.Chart:
        rng = np.random.default_rng(7)
        x = rng.normal(size=self.points)
        y = 0.6 * x + rng.normal(scale=0.6, size=self.points)
        return xy.scatter_chart(
            xy.scatter(x, y, density=True),
            width="100%",
            height=420,
        )

    @rx.event
    def record_hover(self, row: dict):
        self.hovered = row


def index() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(
            Dashboard.cloud,
            on_point_hover=Dashboard.record_hover,
            height="420px",
        ),
        rx.text(Dashboard.hovered.to_string()),
        width="100%",
    )
~~~

Figure builders may also be `async def`, following the same rules as Reflex
async computed vars.

## Events and Streaming

`on_point_hover`, `on_point_click`, `on_select_end`, `on_view_change`,
`on_animation_start`, and `on_animation_end` dispatch small semantic payloads
through normal Reflex event handlers. Large
chart buffers never enter those payloads. These props belong on the outer
`reflex_xy.chart(...)` component and work only with a live token source, such
as an `inline()` token or an `@reflex_xy.figure` var.

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
reflex_xy.append(token, x=[next_x], y=[next_y])
~~~

Constant renderer styles can likewise change without rebuilding or re-shipping
the chart's binary columns:

~~~python
reflex_xy.restyle(token, 0, {"fill": "#dc2626", "opacity": 0.7}, size=7)
~~~

The strict `style` subset matches the corresponding XY mark. Geometry and
data-driven channels deliberately stay on the state-driven full-payload path.
For full recomputes, the adapter encodes once per figure-version/64 px width
bucket and sends only columns absent from that socket's immediately preceding
content-hash manifest.

See [Real-time and streaming data](/docs/xy/guides/real-time-and-streaming-data/)
for the mutation and snapshot contract.

## Choose a Data Tier

| Component source | Best for | Backend |
| --- | --- | --- |
| A direct `xy.Chart`: `reflex_xy.chart(chart)` | Fixed, exportable charts | None |
| A module-scope `token = reflex_xy.inline(chart)`, then `reflex_xy.chart(token)` | Fixed data with kernel round-trips | XY registry |
| An `@reflex_xy.figure` var: `reflex_xy.chart(State.figure)` | Session and state-driven charts | Reflex + XY registry |

`inline()` should run at module scope so every backend worker registers the
same content-addressed token. Despite its name, `inline()` is the live,
kernel-backed fixed-data tier; passing a Chart directly is the static tier.

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

The Reflex adapter and callback payload details are still experimental and the
package has no PyPI release. Keep `xy` and the adapter on the matching tag, and
build against `reflex_xy.chart`, `@reflex_xy.figure`, and `reflex_xy.append`
rather than private transport or registry modules.
~~~
