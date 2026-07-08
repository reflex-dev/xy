# Reflex integration — design

Status: **design** (validated in part by the working prototype in
`examples/reflex/`). The deliverable is an external Reflex adapter
package (working name: `reflex-fastcharts`) that makes a fastcharts figure a
first-class Reflex component with the same performance contract as the notebook
path: screen-bounded binary wire (§29), kernel-side canonical data (§27),
stale-while-revalidate interaction (§17). The adapter dependency budget is
strict: no Reflex dependency if practical, otherwise only a supported
core/component Reflex package unless full Reflex is proven necessary. Full
`reflex` is acceptable for demo apps and user application code, but not as a
default dependency of `fastcharts`, and not as the adapter default unless a
smaller public integration surface cannot work.

## 1. What the prototype proved, and what it fudged

`examples/reflex/` (the demo dashboard) bridges with `Figure.to_html()`
iframes plus one hand-rolled `POST /api/fastcharts/drilldown` route serving a
100M-point drilldown chart. It proves the load-bearing claim: **the kernel-side
Figure can serve a browser client over plain HTTP with in-frame-budget
latency** — the client's `ChartView` takes any `comm` object with
`send`/`onMessage`, and a fetch-shim comm works today.

It also shows exactly what a real integration must fix:

| Prototype shortcut | Real integration |
|---|---|
| buffers as **base64 inside JSON** (~33% overhead + megabyte JSON strings — against the §29 spirit) | length-prefixed binary responses (`application/octet-stream`) |
| message dispatcher **hand-copied** from `widget.py` | one shared dispatcher in `fastcharts` proper (§3.1) |
| **one global figure** behind a module lock | a session-scoped figure registry (§4) |
| iframe + static HTML file per chart | a real `rx.Component` mounting `ChartView` directly (§5) |

## 2. The core decision: two planes

Reflex state sync is JSON diffing over a websocket — excellent for app state,
wrong for data buffers. So the integration splits every chart into:

- **Control plane (Reflex-native, low-frequency, JSON).** Which figure a
  component shows (a token string in `rx.State`), style/layout props, and
  *semantic* events out: `on_hover(row_dict)`, `on_select(selection_summary)`.
  These go through normal Reflex event handlers so app code composes the
  usual way. Row dicts and selection summaries are small by construction —
  never data buffers.
- **Data plane (fastcharts-native, high-frequency, binary).** Initial payload,
  `density_view`/`view`/`pick`/`select` round-trips, and streaming `append`
  pushes, on dedicated backend routes mounted next to the Reflex API. Reflex
  state never sees a data byte, so state diffing cost is independent of data
  size — the same property that makes the notebook path fast.

This preserves every dossier invariant without asking Reflex to change: the
figure kernel doesn't know it's inside Reflex, and Reflex doesn't know the
chart ships megabytes.

## 3. What lands in `fastcharts` (transport-agnostic)

### 3.1 Factor the message dispatcher out of `widget.py`

Today the anywidget `_on_custom_msg` inlines the message→handler routing, and
the prototype re-implements it. Extract:

```python
# fastcharts/channel.py
def handle_message(fig: Figure, content: dict) -> tuple[dict, list[bytes]] | None:
    """One kernel-side dispatcher for every transport: anywidget, Reflex
    routes, and anything else. Returns (reply_message, buffers) or None
    for malformed/ignorable input. Never raises on client-supplied data."""
```

`FigureWidget` becomes a thin wrapper (comm in → `handle_message` → comm out),
the Reflex endpoint another. Third copies are how protocols drift.

### 3.2 Wire framing for HTTP

One binary response format shared by payload fetch and message replies:

```
[u32 spec_len][spec JSON utf-8][u32 n_buffers][u32 len_0][buf_0]…
```

Little-endian, `application/octet-stream`. The client already consumes
`(message, buffers[])`; a ~15-line JS decoder replaces the prototype's
base64 path. No JSON numbers for data, no 33% inflation, no giant-string
JSON parse on the main thread.

## 4. What lands in the Reflex adapter package

Dependency direction: adapter package → `fastcharts`; `fastcharts` itself stays
Reflex-free (existing CLAUDE.md rule; also why `components.py` — the
Reflex-flavored composition API — imports nothing).

The adapter must use the smallest supported Reflex dependency surface:

- Required for `fastcharts`: no Reflex dependency of any kind.
- Best for the adapter: no hard Reflex dependency; expose registry/data-plane helpers and a
  component declaration that works when a Reflex app already has Reflex
  installed.
- Good: depend only on a supported Reflex core/component package if Reflex
  publishes one.
- Last resort: depend on full `reflex`, with the reason documented and isolated
  to an explicit adapter extra or app package. Full Reflex must never become a
  transitive dependency of `fastcharts`, and should not be the default
  `reflex-fastcharts` install unless there is no supported smaller API.

### 4.1 Figure registry

Figures must NOT live in `rx.State`: state is serialized per event
(pickled to Redis in prod), and canonical columns can be gigabytes. Instead:

```python
token = rfc.register(fig)          # uuid string; THIS goes in state
rfc.figure(token)                  # kernel-side lookup
rfc.release(token)                 # explicit; plus TTL sweep as backstop
```

Registry entries: `{token: (figure, version, lock, last_access)}`. `version`
bumps on any mutation (`append`, filter rebuilds); the client sends its
version so replies can say "stale, refetch". Per-figure locks serialize
kernel calls (the kernels release the GIL in Rust, so concurrent figures
still parallelize).

**The honest hard problem — multi-worker deployment.** The registry is
process-local; Reflex prod can run several backend workers. v0 ships with
that documented: single worker, or sticky routing by token. The clean later
fix is making the data plane a separate single process (a "figure server")
that all workers talk to — the registry API above is already the seam for it.
Do not silently pretend this away; it's the §28 rule applied to deployment.

### 4.2 Backend routes

Mounted on Reflex's FastAPI app by `rfc.setup(app)` (the prototype proves
`app._api.add_route` works; use the public `api_transformer` hook where
available):

```
GET  /_fastcharts/{token}/payload          → framed spec+blob   (ETag: version)
POST /_fastcharts/{token}/msg              → handle_message()   (framed reply)
GET  /_fastcharts/{token}/events           → SSE stream of append/version pushes
```

`payload` is cacheable by version — a re-render after an unrelated state
change costs a 304, not a reship. `events` is how `Figure.append` from a
`rx.background` task reaches the client without polling; the pushed message
is the same `append` message the notebook widget sends, applied by the same
client code (rebuild affected traces + follow policy).

### 4.3 The component

```python
import reflex_fastcharts as rfc

class Dash(rx.State):
    chart: str = ""                      # figure token — the ONLY chart state

    def load(self):
        fig = fc.Figure().scatter(x, y, color=c)   # or fc.scatter_chart(...)
        self.chart = rfc.register(fig)

    def picked(self, row: dict): ...
    def selected(self, sel: dict): ...

def index():
    return rfc.chart(
        token=Dash.chart,
        on_hover=Dash.picked,            # semantic events → normal handlers
        on_select=Dash.selected,
        width="100%", height="480px",
    )
```

`rfc.chart` is the thinnest Reflex-compatible component wrapper possible. If
Reflex exposes a core component API, use that instead of importing the full app
framework. Its React wrapper: (1) fetches the framed payload for `token`, (2)
instantiates `ChartView(el, spec, blob, comm)` with a fetch/SSE comm adapter
(the prototype's shim, productionized), (3) forwards `pick_result`/`selection`
replies into the Reflex event dispatcher as plain JSON, (4) destroys the view
and fires a release beacon on unmount. The JS client is the same committed ESM
bundle the wheel ships — one renderer for notebooks, static export, and Reflex.

### 4.4 State-driven updates and streaming

- **App-driven rebuild** (filter changed): the handler mutates the figure via
  the registry (or registers a fresh one), version bumps, and either the
  token prop change or an SSE version ping makes the component refetch.
  Cost: one screen-bounded payload.
- **Streaming**: `rfc.append(token, x=..., y=...)` from a background task →
  `Figure.append` → the `append` message broadcast on `/events`. The client
  applies it with the existing follow policy (refit at home, slide when
  pinned to the live edge, hold when inspecting history). This is the
  "live 100M-point dashboard in pure Python" demo, minus the iframe.

## 5. Latency budget (why this matches the notebook path)

Same-host POST round-trip ~1–3 ms + kernel view compute 1.5–12 ms (pyramid /
exact re-bin at 10M) lands inside the client's 120 ms request debounce and
under typical frame-budget perception either way. Hover uses client-side GPU
picking with only the row readout crossing the wire, already throttled. The
transport differences vs anywidget (HTTP vs Jupyter comm) are noise against
the compute; SSE replaces comm push. If hover/pick volume ever argues for it,
the data plane can switch POST→WebSocket without touching the message
protocol — `comm` is already the abstraction seam.

## 6. What an example app looks like (target DX)

A fleet-telemetry dashboard: 10M GPS pings as a drillable density scatter,
box-select cross-filtering a latency histogram, and a live throughput line
fed by a background task. This is the acceptance bar for the whole design —
**aspirational code**, written against the API of §4, not runnable yet.

```python
import numpy as np
import reflex as rx
import fastcharts as fc
import reflex_fastcharts as rfc


def load_pings() -> dict[str, np.ndarray]:
    ...  # 10M rows: lon, lat, latency_ms — parquet via pyarrow, zero-copy ingest


class Telemetry(rx.State):
    # Figure TOKENS are the only chart state — strings, cheap to diff.
    # The figures themselves (80+ MB of canonical columns) live in the
    # kernel-side registry, never in rx.State.
    map_chart: str = ""
    latency_chart: str = ""
    live_chart: str = ""

    hovered: dict = {}          # row under the cursor (semantic, small)
    selected_count: int = 0
    streaming: bool = False

    @rx.event
    def load(self):
        pings = load_pings()
        self._pings = pings     # backend-only var: raw arrays for cross-filter

        # 10M points: ships as a density surface, drills to real points on
        # zoom, hover reads exact f64 rows — all default behavior.
        fig = fc.Figure().scatter(
            pings["lon"], pings["lat"], color=pings["latency_ms"]
        )
        self.map_chart = rfc.register(fig)

        self.latency_chart = rfc.register(
            fc.Figure().histogram(pings["latency_ms"], bins=120)
        )

        self.live_chart = rfc.register(
            fc.Figure().line(np.array([0.0]), np.array([0.0]))
        )

    @rx.event
    def on_map_hover(self, row: dict):
        self.hovered = row      # {'x': lon, 'y': lat, 'color_value': latency…}

    @rx.event
    def on_map_select(self, selection: dict):
        # Box-select on 10M points → cross-filter the histogram. The
        # selection payload carries indices (capped) + count; the handler
        # rebuilds the small figure and swaps the token. One screen-bounded
        # refetch on the client; rx.State never sees a data buffer.
        idx = rfc.selection_indices(selection)          # np.ndarray[u32]
        self.selected_count = int(len(idx))
        rfc.release(self.latency_chart)
        self.latency_chart = rfc.register(
            fc.Figure().histogram(self._pings["latency_ms"][idx], bins=120)
        )

    @rx.event(background=True)
    async def stream(self):
        async with self:
            self.streaming = True
        t = 0.0
        while self.streaming:
            t += 1.0
            # append → version bump → SSE push → client applies the same
            # `append` message the notebook widget sends (follow policy:
            # refit at home / slide when pinned to the live edge).
            rfc.append(self.live_chart, x=[t], y=[throughput_sample()])
            await asyncio.sleep(0.25)

    @rx.event
    def cleanup(self):
        for token in (self.map_chart, self.latency_chart, self.live_chart):
            rfc.release(token)


def index() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rfc.chart(                      # 10M-point drillable map
                token=Telemetry.map_chart,
                on_hover=Telemetry.on_map_hover,
                on_select=Telemetry.on_map_select,
                width="100%", height="520px",
            ),
            rx.vstack(
                rfc.chart(token=Telemetry.latency_chart, height="250px"),
                rfc.chart(token=Telemetry.live_chart, height="250px"),
                rx.text(f"{Telemetry.selected_count:,} pings selected"),
                rx.button("Go live", on_click=Telemetry.stream),
            ),
        ),
        on_mount=Telemetry.load,
        on_unmount=Telemetry.cleanup,
    )


app = rx.App()
rfc.setup(app)                              # mounts /_fastcharts/* routes
app.add_page(index)
```

What this example is designed to prove, line by line:

- **State stays tiny.** Three token strings, a hovered row, a count, a flag.
  The 10M-point figure never crosses the state serializer; `_pings` is a
  backend-only var (never synced).
- **Interaction costs what the notebook costs.** Pan/zoom on the map goes
  component → `/msg` → pyramid/re-bin → framed binary back. No Reflex event
  round-trip, no state diff, no re-render of anything else on the page.
- **Cross-filtering is just Python.** `on_map_select` receives a semantic
  selection, slices NumPy, registers a fresh small figure, swaps the token.
  The component sees a new token prop and refetches one screen-bounded
  payload. No special "linked charts" machinery to learn.
- **Streaming is one call in a background task.** `rfc.append` reuses the
  whole Phase-0 streaming stack; the client-side follow policy makes the
  live line march without any frontend code.
- **Lifecycle is visible.** `register`/`release` bracket the figures;
  unmount cleans up; the TTL sweep catches whatever a crashed tab leaks.

## 7. Build order

1. `fastcharts/channel.py`: extract `handle_message` from `widget.py`; add
   the binary framing helpers + tests (no behavior change to the widget).
2. External adapter package: registry + routes + framed-wire JS comm adapter;
   use no Reflex dependency, or only a supported Reflex core/component
   dependency, unless full Reflex is proven necessary. Port the prototype's
   drilldown page onto it (deleting the base64/global-figure shortcuts) as the
   acceptance test.
3. The `rfc.chart` component + semantic event forwarding; demo app switches
   from iframes to components.
4. SSE push + `rfc.append`; wire the streaming demo.
5. Multi-worker story (document first, figure-server later).
