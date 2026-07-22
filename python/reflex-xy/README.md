# reflex-xy

[xy](https://github.com/reflex-dev/xy) figures as first-class
[Reflex](https://reflex.dev) components: WebGL rendering, million-point
interactivity, and streaming updates — with chart data riding the app's
**existing websocket**, not a sidecar API.

Status: **prototype** implementing `spec/design/reflex-integration.md`.

## How it works

- **Control plane (Reflex-native).** The only chart state is a token string,
  minted by a `@reflex_xy.figure` computed var. Semantic events —
  `on_point_hover(event)`, `on_point_click(event)`, `on_select_end(event)`, and
  `on_view_change(event)` — arrive as ordinary Reflex
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

## Events and cross-filtering

Live token-backed charts emit versioned, bounded dictionaries with a stable
token and canonical row IDs. Selection rows can update ordinary State, which
causes dependent `@reflex_xy.figure` builders to republish without changing
their tokens or remounting the chart:

```python
class Dash(rx.State):
    selected_groups: list[str] = []

    @rx.event
    def filter_groups(self, event: dict):
        selection = event["selection"]
        self.selected_groups = [] if selection["cleared"] else sorted({
            row["color_category"] for row in selection["rows"]
        })

def index():
    return rx.grid(
        reflex_xy.chart(Dash.groups, on_select_end=Dash.filter_groups),
        reflex_xy.chart(Dash.filtered_detail),
    )
```

Selection JSON is capped and reports `total_count` plus `truncated`; call
`reflex_xy.resolve_selection(event)` in the handler when all canonical rows
are required. Hover is latest-wins throttled, view changes are debounced, and
view/selection state survives dependent republishes without feedback events.
The complete envelopes, limits, clear/shared-handler/viewport examples, and
static-versus-live availability are documented in
`docs/engineering/design/reflex-integration.md`.

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

The repository's [`examples/reflex/`](../../examples/reflex) is a runnable
showcase of every linking method: a drillable figure var with hover / click /
box-select events, a histogram driven by a slider and cross-filtered by the
selection, a streaming line, a detail chart recomputed from `on_view_change`,
and the two fixed-data tiers (a direct `xy.Chart` and an `inline()` token).
Each section shows its own source, read live with `inspect.getsource`.

For serving the same charts without Reflex, [`examples/fastapi/`](../../examples/fastapi)
renders standalone HTML and a live 100M-point drilldown from a plain FastAPI app.
