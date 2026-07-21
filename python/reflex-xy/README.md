# reflex-xy

[xy](https://github.com/reflex-dev/xy) figures as first-class
[Reflex](https://reflex.dev) components: WebGL rendering, million-point
interactivity, and streaming updates — with chart data riding the app's
**existing websocket**, not a sidecar API.

Status: **prototype** implementing `spec/design/reflex-integration.md`.

## How it works

- **Control plane (Reflex-native).** The only chart state is a token string,
  minted by a `@reflex_xy.figure` computed var. Semantic events —
  `on_point_hover(row)`, `on_select_end(summary)` — arrive as ordinary Reflex
  event handlers with small JSON payloads.
- **Data plane (xy-native).** A second socket.io namespace (`/_xy`)
  multiplexed onto the app's own engine.io websocket ships the spec as JSON
  and every data column as a binary frame (no JSON numbers, no base64, no
  extra endpoints to reverse-proxy). Pan/zoom/hover round-trips go straight
  to the figure kernel and never touch Reflex state.
- **No figure server.** Figures live in a per-process registry as
  *rebuildable caches*: the token encodes `(client, state, var)`, so any
  backend worker can re-run the builder against Reflex state (already
  distributed via redis in prod) when a reconnect lands on it.

## Usage

```python
# rxconfig.py
import reflex as rx
import reflex_xy

config = rx.Config(app_name="dash", plugins=[reflex_xy.XYPlugin()])
```

```python
# dash/dash.py
import numpy as np
import reflex as rx
import xy
import reflex_xy


class Dash(rx.State):
    points: int = 200_000
    hovered: dict = {}

    @reflex_xy.figure
    def chart(self) -> xy.Chart:
        rng = np.random.default_rng(7)
        xs = rng.normal(size=self.points)
        ys = xs * 0.6 + rng.normal(scale=0.6, size=self.points)
        return xy.scatter_chart(xy.scatter(xs, ys), width="100%", height=460)

    @rx.event
    def on_hover(self, row: dict):
        self.hovered = row


def index() -> rx.Component:
    return rx.vstack(
        reflex_xy.chart(Dash.chart, on_point_hover=Dash.on_hover, height="460px"),
        rx.text(Dash.hovered.to_string()),
        width="100%",
    )


app = rx.App()
```

Change `points` in an event handler and the chart re-publishes itself to
every subscriber — the token never changes, so nothing re-renders except
pixels.

Builders can be `async def` (they become reflex `AsyncComputedVar`s, same
rule as `rx.var`) — await a database, HTTP endpoint, or dataframe store:

```python
    @reflex_xy.figure
    async def remote(self) -> xy.Chart:
        rows = await fetch_rows(self.query)
        return xy.line_chart(xy.line(rows.t, rows.value))
```

Streaming: `reflex_xy.append(token, x=[...], y=[...])` from any handler or
background task pushes an incremental update over the same socket.

## Fixed-data charts

For a chart that doesn't depend on state, skip the state var entirely —
pass the Chart straight in:

```python
def index() -> rx.Component:
    return reflex_xy.chart(
        xy.line_chart(xy.line(t, np.sin(t)), width="100%", height=220),
        height="220px",
    )
```

That compiles the figure to a content-addressed binary asset at page build
and renders it with **zero backend involvement** — client-side hover,
pan/zoom, and density re-bin, same as `Figure.to_html()` exports; works
under `reflex export`. When a fixed chart still needs kernel round-trips
(deep drilldown into millions of points), register it once at module scope
instead:

```python
cloud = reflex_xy.inline(xy.scatter_chart(xy.scatter(x, y)))  # module scope

def index() -> rx.Component:
    return reflex_xy.chart(cloud, height="460px")
```

`inline()` tokens are content-addressed, so every backend worker derives
the same one — no state, no coordination. The escalation path is:
direct Chart (static) → `inline()` (fixed data, live kernel) →
`@reflex_xy.figure` (per-session, state-driven).

## Demo

`examples/demo_app/` in this directory is a runnable dashboard (drilldown
scatter, hover readout, box-select cross-filter, live streaming line).
