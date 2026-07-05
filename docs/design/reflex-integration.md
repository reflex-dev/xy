# Reflex integration — design

Status: **design** (validated in part by the working prototype in
`reflex_fastcharts_app/`). The deliverable is a `reflex-fastcharts` package
that makes a fastcharts figure a first-class Reflex component with the same
performance contract as the notebook path: screen-bounded binary wire (§29),
kernel-side canonical data (§27), stale-while-revalidate interaction (§17).

## 1. What the prototype proved, and what it fudged

`reflex_fastcharts_app/` (the demo dashboard) bridges with `Figure.to_html()`
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

## 4. What lands in `reflex-fastcharts` (the new package)

Dependency direction: `reflex-fastcharts → fastcharts` (+ `reflex`).
`fastcharts` itself stays Reflex-free (existing CLAUDE.md rule; also why
`components.py` — the Reflex-flavored composition API — imports nothing).

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

`rfc.chart` is an `rx.Component` whose React wrapper: (1) fetches the framed
payload for `token`, (2) instantiates `ChartView(el, spec, blob, comm)` with
a fetch/SSE comm adapter (the prototype's shim, productionized), (3) forwards
`pick_result`/`selection` replies into the Reflex event dispatcher as plain
JSON, (4) destroys the view and fires a release beacon on unmount. The JS
client is the same committed ESM bundle the wheel ships — one renderer for
notebooks, static export, and Reflex.

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

## 6. Build order

1. `fastcharts/channel.py`: extract `handle_message` from `widget.py`; add
   the binary framing helpers + tests (no behavior change to the widget).
2. `reflex-fastcharts` package: registry + routes + framed-wire JS comm
   adapter; port the prototype's drilldown page onto it (deleting the
   base64/global-figure shortcuts) as the acceptance test.
3. The `rfc.chart` component + semantic event forwarding; demo app switches
   from iframes to components.
4. SSE push + `rfc.append`; wire the streaming demo.
5. Multi-worker story (document first, figure-server later).
