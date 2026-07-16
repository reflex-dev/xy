# reflex-xy

[xy](https://github.com/reflex-dev/xy) figures as first-class
[Reflex](https://reflex.dev) components: WebGL rendering, million-point
interactivity, and streaming updates — with chart data riding the app's
**existing websocket**, not a sidecar API.

Status: **prototype** implementing `docs/design/reflex-integration.md`.

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
import xy as fc
import reflex_xy


class Dash(rx.State):
    points: int = 200_000
    hovered: dict = {}

    @reflex_xy.figure
    def chart(self) -> fc.Chart:
        rng = np.random.default_rng(7)
        xs = rng.normal(size=self.points)
        ys = xs * 0.6 + rng.normal(scale=0.6, size=self.points)
        return fc.scatter_chart(fc.scatter(xs, ys), width="100%", height=460)

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

Streaming: `reflex_xy.append(token, x=[...], y=[...])` from any handler or
background task pushes an incremental update over the same socket.

## Demo

`examples/demo_app/` in this directory is a runnable dashboard (drilldown
scatter, hover readout, box-select cross-filter, live streaming line).
