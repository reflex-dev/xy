# Reflex integration — design

Status: **prototype landed** (`python/reflex-xy`, tests under
`tests/reflex_adapter/`). This document is the authoritative design; the
prototype implements it end to end over Reflex 0.9.6. The deliverable is an
external adapter package (`reflex-xy`) that makes a xy figure a
first-class Reflex component with the same performance contract as the
notebook path: screen-bounded binary wire (§29), kernel-side canonical data
(§27), stale-while-revalidate interaction (§17).

Two decisions define this revision (superseding the HTTP-routes draft — see
§8 for the audit trail):

1. **The data plane rides the app's existing websocket.** No new endpoints;
   a second socket.io namespace multiplexes onto the engine.io connection
   Reflex already maintains.
2. **There is no figure server and no chart data in Redis.** Figures are
   per-process *rebuildable caches*; Reflex state (already durable and
   already distributed) is the only source of truth. The figure token is the
   rebuild recipe.

## 1. The core decision: two planes, one socket

Reflex state sync is JSON diffing over a websocket — excellent for app
state, wrong for data buffers. The integration splits every chart into:

- **Control plane (Reflex-native, low-frequency, JSON).** Which figure a
  component shows (a token string minted by a computed var), style/layout
  props, and *semantic* events out: `on_point_hover(event)`,
  `on_select_end(event)`, `on_view_change(event)`, `on_point_click(event)`.
  These go through normal Reflex event handlers, so app code composes the
  usual way. Rows and summaries are small by construction — never buffers.
- **Data plane (xy-native, high-frequency, binary).** First paint,
  `view`/`density_view`/`pick`/`select` round-trips, streaming `append`
  pushes, and full-payload refreshes — on a dedicated socket.io namespace
  (`/_xy`) **carried by the same physical websocket** as the control plane.
  Reflex state never sees a data byte; state diffing cost is independent of
  data size.

Sharing the connection is the point, not an economy: the data plane inherits
the app connection's lifecycle (connect/reconnect/visibility handling that
Reflex's frontend already implements), its origin/CORS posture, its query
`?token=` identity, and any future connection-level auth — for free, forever,
because it *is* the same connection. Operationally, anything that can proxy
the Reflex app can serve charts; there is no second route to forward, no
per-request HTTP overhead, no SSE keep-alive tuning.

### Why not three HTTP endpoints (the previous draft)

`GET /payload` + `POST /msg` + SSE invalidation works — the old prototype
proved it — but each piece costs something the socket gets free: reverse
proxies must be taught each route; every `/msg` pays request setup + headers;
SSE is a second long-lived connection per chart with its own reconnect
logic; and none of it inherits app-plane auth. The XYBF binary frame format
(`python/xy/_framing.py`; versioning in [wire-protocol.md](wire-protocol.md)
§7) exists because HTTP bodies need framing — socket.io attachments
already carry length-delimited binary, so on this transport the framing
layer disappears too. XYBF remains in `python/xy/_framing.py` (re-exported
from `xy.channel`) for HTTP/export hosts; the namespace does not use it.

### The cost we accept (recorded, §28 spirit)

- **Head-of-line blocking.** A multi-megabyte payload frame shares the TCP
  stream with state deltas; on slow links a full refresh can delay an app
  event behind it. Payloads are screen-bounded (§29) so the practical size
  is single-digit MB; if it ever matters, chunked payload emission (bounded
  frames interleaved with other traffic) fits behind the same events without
  protocol change.
- **Version coupling.** The wrapper mirrors Reflex's socket options
  (`transports`, ws subprotocol, `?token=` query) so the manager cache
  merges the connections. Those names are pinned by
  `tests/reflex_adapter/test_assets.py` — a Reflex upgrade that renames
  them fails loudly in CI, not silently in prod.
- **One engine.io connection per tab** stays the invariant. If a chart page
  somehow loads without state enabled there is no socket at all — but
  figure tokens come from state, so that page has no charts either.

## 2. Transport: a second namespace on the app's socket

**Backend.** Reflex builds a python-socketio `AsyncServer` at app
construction and registers its `/_event` namespace on it. The adapter
registers one more namespace on the same server:

```python
app.sio.register_namespace(XYNamespace(registry, rebuild=...))   # "/_xy"
```

A namespace is a socket.io protocol concept, not a URL: no route, no mount,
no proxy entry. Wiring is one line in `rxconfig.py` —
`plugins=[reflex_xy.XYPlugin()]` — whose `post_compile` hook receives the
live `App` at backend-worker startup (after the socket server exists, before
any client connects), or an explicit `reflex_xy.setup(app)` for people who
prefer it in `app.py`. A lifespan task captures the serving loop (for
thread-safe fan-out from sync handlers) and runs the registry TTL sweep.

**Frontend.** socket.io-client caches managers by
`(protocol, host, port, engine.io path)`. The wrapper connects to namespace
`/_xy` with the *same* URL and options Reflex's `connect()` uses
(`getBackendURL(env.EVENT)`, `path: endpoint.pathname`,
`transports: [env.TRANSPORT]`, `protocols: [version]`,
`query: {token: getToken()}`) — so whichever side connects first creates the
manager and the other multiplexes onto it. One websocket in the browser's
network tab, two namespaces inside it. React effect ordering means the chart
often connects first; mirroring the options exactly is what makes that safe
(the backend sees an identical connection either way).

Reflex owns reconnection: its `reconnect()` reopens the shared manager, our
namespace socket re-CONNECTs automatically, and every mounted chart re-`sub`s
on the `connect` event.

**Wire shape.** Metadata is one small JSON object per event; every data
column is a `bytes` value inside it, which python-socketio hoists into
binary attachments and the browser receives as `ArrayBuffer`s *in place* —
aligned, zero-copy into `Float32Array`s. No JSON numbers for data, no
base64, no custom framing (§29 preserved; the socket.io protocol already
length-prefixes attachments).

The envelope is below; the `m` payload it carries is specified field by field
in `spec/design/wire-protocol.md`.

```
client -> server (namespace /_xy)
  sub     {fig, px?, mid}       subscribe; join figure room; reply `payload`
  unsub   {fig, mid}            leave the room
  msg     {fig, mid, m}         one xy.channel.handle_message dispatch

server -> client
  payload {fig, version, spec, buffers}   first paint / full refresh
  msg     {fig, mid?, message, buffers}   reply (mid echoed) or push (no mid)
  err     {fig, error}                    unknown/foreign token, rebuild failed
```

`mid` is a per-mount id: several charts on a page share the socket, replies
are mount-addressed, pushes are room-wide. The kernel dispatch is byte-for-
byte the notebook dispatch — `xy.channel.handle_message` (§3.1 of the
old draft, now shipped), run off the event loop via a worker thread (the
Rust kernels release the GIL) under a per-figure lock.

Inbound handlers are total: malformed input drops or answers `err`, never
raises — `channel.py`'s "hostile client must not crash the kernel" contract
extended to the transport.

### 2.1 Message catalog (specified in wire-protocol.md)

The envelope above is transport; the `m` object it carries is the kernel
protocol, dispatched by `xy.channel.handle_message`. Every request type, every
reply shape, and the `seq` / `_pickSeq` / `drill_seq` staleness rules are
specified in [wire-protocol.md](wire-protocol.md), which is the sole authority
for all of it. Unknown types and malformed fields return no reply at all (§2's
totality contract). This section records only what is specific to this host.

**`view_change` does not reach the kernel here.** The wrapper intercepts the
outgoing message and invokes the Reflex `on_view_change` prop directly
(`dispatchView` in `python/reflex-xy/reflex_xy/assets/XYChart.jsx`), because
the namespace registers no Python-side view callback (§5). Every other request
type crosses the socket unchanged and is dispatched by the shared
`handle_message`.

**Client-supplied dimensions are untrusted.** `px`, `w`, and `h` pass through
`lod.screen_shape`, which rejects non-finite values and clamps the rest to
`[16, MAX_SCREEN_DIM]` (`MAX_SCREEN_DIM = 4096`, `xy/config.py`) — a hostile
client cannot make the kernel allocate an arbitrary density texture. The bound
matters more here than in the notebook: the namespace is reachable by anyone
who can reach the app, so the clamp is an access-control boundary rather than
a sanity check (§3.3).

## 3. Figures: registry as cache, state as truth

### 3.1 The figure var (the pattern that sidesteps the distributed problem)

```python
class Dash(rx.State):
    points: int = 1_000_000

    @reflex_xy.figure
    def cloud(self) -> xy.Chart:
        x, y, mag = load(self.points)
        return xy.scatter_chart(xy.scatter(x, y, color=mag), width="100%", height=460)

    @reflex_xy.figure
    async def remote(self) -> xy.Chart:
        rows = await fetch_rows(self.query)      # db / http / dataframe store
        return xy.line_chart(xy.line(rows.t, rows.value), width="100%", height=220)
```

`@reflex_xy.figure` is a computed var whose **value is only the token
string** — `xyv1|<client_token>|<state_full_name>|<var_name>` — and whose
evaluation is what (re)registers the figure in the per-process registry.
Reflex's own dependency tracker watches the *builder's* body (the var
subclass points dependency analysis at it), so:

- First render: var evaluates → figure built and registered → token into
  state.
- A dependency changes: Reflex marks the var dirty; the next delta
  evaluation rebuilds the figure and re-publishes; every subscriber gets a
  fresh payload pushed over the data plane. The token is deterministic, so
  the frontend sees **no prop change at all** — pixels move, DOM doesn't.
- Reconnect (same node or another): the cached token comes back with the
  state; the component re-`sub`s; hit → serve, miss → §3.2.

Two values are not tokens. Before session hydration there is no client
token to mint from, so the var evaluates to `""`; and a builder may return
`None` for "no chart right now", which **releases** any existing registry
entry and likewise yields `""`. The wrapper treats `""` as "not ready / no
chart" and mounts nothing, so both cases are a blank mount rather than an
error.

Async builders are first-class, mirroring reflex's own
`ComputedVar`/`AsyncComputedVar` split with the same
`iscoroutinefunction` dispatch `rx.var` uses: an `async def` builder becomes
an `AsyncFigureVar` (an `AsyncComputedVar`), evaluated and cached by
reflex's normal async-var machinery, and the rebuild path awaits the same
builder when a fresh worker recovers the figure.

Figure vars must be **public**: a leading-underscore builder name is refused
at decoration time with `ValueError`, because backend (underscore) vars never
sync to the client and so their tokens could never reach the wrapper —
failing at import beats compiling a chart nobody can subscribe to.
`@reflex_xy.figure(...)` forwards arbitrary computed-var keywords (`deps=`,
`auto_deps=`, `interval=`, …) straight through to the underlying var, with
`cache=True` set as the default.

Builders must be pure functions of their state instance — the discipline
cached computed vars already impose — because purity is exactly what makes
the figure a *rebuildable cache* instead of precious process state (for
async builders: deterministic given state — refetching the rows state
points at is exactly the recovery contract). This is §27 applied to
processes: canonical data is Reflex state; every registered figure is a
derived buffer.

### 3.2 Registry miss: rebuild from state

`sub` (or `msg`) on an unknown state token parses it, resolves the state
class from the full name, loads that session's state through
`app.state_manager.get_state(BaseStateToken(...))` — memory, disk, or Redis,
whatever the app configured — finds the builder on the var, re-runs it, and
serves. The worker that answers a reconnect never needs to have seen the
figure before. **Reflex prod-mode multi-worker works without a figure
server, sticky routing, or chart data in Redis** — the state that was going
to be in Redis anyway is the recovery record.

Failure stays closed: unparseable tokens, unknown states/vars, or builders
that raise all answer `err {fig, error}`; the client logs and shows an empty
mount rather than crashing the page.

### 3.3 Access control

The connection's `?token=` (the Reflex client token) is captured at
namespace connect. A state token embeds the client token it was minted for,
and `sub`/`msg` refuse a figure whose embedded client token differs from the
connection's (`err: figure belongs to another session`). Tokens carry
nothing their own client doesn't already know. When Reflex grows real
connection auth, it lands on this same connection and the data plane
inherits it (§1).

One deliberate consequence of rebuild-from-state: subscribing to a
never-registered token of your *own* session materializes a default-state
figure — indistinguishable from loading the page fresh, and gated by the
same affinity check.

### 3.4 Fixed-data tiers: direct Charts and `inline()`

Not every chart derives from state. Two tiers cover fixed data, chosen by
whether the kernel still matters:

**Static payload tier — pass the Chart straight to the component.**
`reflex_xy.chart(xy.scatter_chart(...))` compiles the figure to its
first-paint payload at page build, writes it into the app's `assets/xy/` as
one content-addressed XYBF frame (`<digest>.xyf` — the `_framing.py`
envelope's natural home), and hands the wrapper a `src` URL instead of a
token. The
wrapper fetches the static file and runs the render client **kernel-less**:
the exact `renderStandalone` semantics of `Figure.to_html()` exports —
client-side hover from retained columns, pan/zoom, worker-based density
re-bin — with no registry entry, no subscription, no backend coupling at
all. Deployment story is airtight by construction: page bodies run in the
process that compiles the frontend, *before* the compiler copies `assets/`
into the web build, so the file ships with every compile — including
`reflex export` static hosting, where this tier keeps working with no
backend running. Content addressing makes writes idempotent across workers
and recompiles (prod workers re-evaluate stateful pages but skip writing,
mirroring `rx.asset`'s backend-only guard) and makes the browser cache
correct for free. What this tier gives up, deliberately: kernel round-trips
(deep drilldown past the shipped tiers, exact server picks, streaming) and
semantic events.

**`inline()` — fixed data that still wants the kernel.**
`token = reflex_xy.inline(chart)` at **module scope** registers the figure
under a content-addressed token (`xyin-<digest>`): every backend worker
independently derives the same token when it imports the app module, so the
token baked into the compiled frontend resolves on any worker with no state
and no rebuild hook. Module scope is the load-bearing requirement — page
bodies only run where the frontend compiles, module bodies run everywhere.
Entries are **pinned** (exempt from the TTL sweep) because no rebuild
recipe exists. Shared by design: one figure serves every viewer, so
kernel-side drill state is shared too — same shape as N notebook views of
one widget. Per-viewer data or isolation belongs in `@reflex_xy.figure`.

**`register()` — the dev tier.** `reflex_xy.register(chart) ->
"xyfig-<uuid>"` / `release(token)` keep the old draft's explicit API for
ad-hoc exploration and tests. Opaque uuid tokens rely on unguessability
(same trust model as the client token itself), are **not** rebuildable and
not stable across workers — documented as dev-only, not deployment-safe.

### 3.5 Lifecycle

Rooms track subscriptions; disconnects clean rooms, never figures (a page
reload must not destroy what its reconnect will re-request). The TTL sweep
(30 min idle, lifespan task) bounds leaked figures; state-derived figures
transparently rebuild after a sweep, so the TTL is a memory bound, not a
correctness bound. Rapid re-publishes coalesce: an un-started broadcast
absorbs newer publishes and always ships the latest payload.

## 4. Updates and streaming

- **State-driven rebuild** (filter changed): the figure var recomputes,
  `registry.publish` bumps the version and pushes one full `payload` to the
  room. Stable token: no component re-render, one screen-bounded reship. The
  in-place swap re-homes the viewport to the incoming spec's axis ranges — a
  full payload carries no follow policy of its own. A chart the viewer has
  navigated is re-pinned to its prior window afterward (the restore contract
  below); a dependent chart sitting at its home simply follows the new data. In
  both cases the home *must* be the new spec's own extents, not the previous
  payload's: it is what lets an `on_view_change`-computed detail chart track its
  source both ways — when the linked overview zooms *out*, the recomputed
  detail's count axis grows and the view expands with it instead of clamping to
  the previous, smaller home (`ChartView.updatePayload`, `js/src/56_animation.ts`).
- **Streaming**: `reflex_xy.append(token, x=..., y=...)` from any handler,
  background task, or thread → `Figure.append` under the figure lock (worker
  thread) → the same `append` message the notebook widget ships, pushed
  room-wide as a `msg` event. The client applies it with the existing follow
  policy (refit at home, slide when pinned to the live edge, hold when
  inspecting history).
- **Interaction** (pan/zoom/hover/select): `msg` round-trips into the
  kernel, exactly the anywidget flow — tier updates, density re-bins, exact
  f64 pick rows, selection masks as binary buffers.

## 5. The component

```python
reflex_xy.chart(
    Dash.cloud,                      # a figure var / inline() / register() token…
    on_point_hover=Dash.on_hover,    # semantic events -> normal handlers
    on_select_end=Dash.on_select,
    height="460px",
)

reflex_xy.chart(xy.line_chart(...))  # …or a Chart directly: static tier (§3.4)
```

One factory, dispatched on the source: tokens (state vars or strings)
compile to the `token` prop and ride the socket data plane; a Chart/Figure
passed directly compiles to a payload asset and lands in the `src` prop,
which the wrapper fetches and renders kernel-less. Semantic-event props
apply to live sources; a static chart resolves hover tooltips client-side
but dispatches no backend events.

Sizing is the mount's, not the payload's. `chart()` defaults the outer
element to `width: 100%` / `height: 420px` (override with any style prop),
and the wrapper rewrites the payload spec's own `width`/`height` to `100%`
on both the static and live paths, so a chart always follows the box Reflex
reserved instead of the dimensions baked into its payload. Charts built with
`width="100%"` therefore track the element responsively, and a fixed-size
payload cannot paint outside the page flow.

`chart()` is a plain `rx.Component` whose `library` is a **local JSX shared
asset** (`$/public/external/reflex_xy/assets/XYChart.jsx`, the same
mechanism reflex's own radix color-mode provider uses) — no npm package, no
CDN. Beside it, `register()` links `xy_client.js` **out of the installed
`xy` package** (`xy/static/index.js`): the adapter carries no copy
of the render client at all, so client/kernel drift is structurally
impossible — the JS that renders a payload is always the build that shipped
with the Python that produced it. One renderer for notebooks, static
export, and Reflex.

The wrapper: opens/reuses the shared namespace socket, `sub`s with the
element's measured width, builds a `ChartView` for the first `payload`, and
passes later full payloads to `ChartView.updatePayload` (preserving keyed
animation state; destroy + rebuild is only the compatibility fallback),
bridges `comm` to `msg` events, and forwards semantic
events into Reflex's event system via the component's event-trigger props
(`props.onPointHover(row)` → `addEvents(...)` → the user's handler).
Client-side niceties: `view_change` resolves locally (no kernel round-trip;
the namespace registers no Python callbacks), `click` issues a tagged `pick`
so `on_point_click` delivers the exact row, `selection` replies pair with
the brush rect that produced them.

Multiple mounts of one figure render and stream correctly (room fan-out,
`mid`-addressed replies); concurrent *drilldown* from several views of the
same figure shares kernel drill state — same known engine-level shape as
multiple notebook views today, acceptable and documented.

### 5.1 Semantic event contract

Semantic events are available for live, token-backed figures created with
`@reflex_xy.figure`, `inline()`, or `register()`. A static `src` chart has no
socket: browser-local tooltip and navigation behavior remains available, but
it cannot dispatch Reflex handlers or drive server-side cross-filtering.
Unset event props install no corresponding interaction work.

Every handler receives a versioned dictionary with `version: 1`, `type`, and
the stable figure `token`. Point events also contain `trace`, the canonical
CPU-store `canonical_row_id`, `data: {x, y}`, and a bounded `datum` containing
the remaining configured pick fields. Click adds canvas-relative `screen`
coordinates and keyboard `modifiers`. Canonical IDs never refer to a shipped,
sampled, decimated, or GPU-buffer position.

```python
@rx.event
def inspect_point(self, event: dict):
    self.last_id = event["canonical_row_id"]
    self.last_xy = event["data"]

reflex_xy.chart(Dash.cloud, on_point_click=Dash.inspect_point)
```

Selection events use the following shape. P0 supports deterministic `replace`
mode; an empty clear is explicit (`kind: "clear"`, `cleared: true`). Box and
lasso rows are ordered by trace then canonical ID.

```python
{
  "version": 1, "type": "select_end", "token": "xyv1|...",
  "selection": {
    "kind": "box", "mode": "replace",
    "data_bounds": {"x0": 0, "x1": 10, "y0": 20, "y1": 50},
    "polygon": None,
    "canonical_row_ids": [{"trace": 0, "ids": [12, 18, 27]}],
    "rows": [{"trace": 0, "index": 12, "x": 2.0, "y": 30.0,
              "x_kind": "linear", "y_kind": "linear"}],
    "total_count": 3, "truncated": False, "cleared": False,
  },
}
```

The JSON projection is capped at `SELECTION_EVENT_ROW_LIMIT = 1000` rows and
`SELECTION_EVENT_ID_LIMIT = 10000` canonical IDs. `total_count` always reports
the complete count and `truncated` is never silent. For complete server-side
data, re-resolve the geometry against the current live figure; `rows()` is
unbounded unless the caller supplies a limit:

Every envelope shape is declared as a `TypedDict` in `reflex_xy.events`
(exported from the package root: `PointHoverEvent`, `PointClickEvent`,
`SelectEndEvent`, `SelectionPayload`, `ViewChangeEvent`, plus their component
pieces). Handlers still receive plain dicts — the declarations exist for type
checking and editor support; `assets/XYChart.jsx` is the single producer they
mirror, and the two must change together.

```python
@rx.event
def filter_regions(self, event: reflex_xy.SelectEndEvent):
    selection = event["selection"]
    if selection["cleared"]:
        self.selected_regions = []
        return
    self.selected_regions = sorted({
        row["color_category"] for row in selection["rows"]
        if "color_category" in row
    })
    complete = reflex_xy.resolve_selection(event)
    if selection["truncated"] and complete is not None:
        process_all_rows(complete.rows())
```

LOD and density rendering do not change this contract. For example, a box
drawn over a million-point density tier may return 1000 projected rows and
10,000 IDs with `total_count: 247381, truncated: true`; `resolve_selection`
re-runs that box against canonical f64 columns and returns all 247,381 rows,
never the visible sample or decimated buffer positions.

The source chart retains its box/lasso highlight and viewport when the state
change republishes its figure; dependent charts update behind their unchanged
tokens. A restore is tagged `source: "republish"` and does not redispatch
`on_select_end` or `on_view_change`, preventing feedback loops. Clearing the
selection resets dependent filters through the same handler.

A republish first attempts an in-place data swap through
`ChartView.updatePayload` (the animations path): the canvas never tears down,
but the swap re-homes the viewport and rebuilds trace state, so the restore
contract still applies — the wrapper pins the domain (clearing any in-flight
domain interpolation) and re-requests the selection mask. When the in-place
swap is refused, the wrapper destroys the outgoing view immediately and builds
the replacement. The client retains brush geometry, so points arriving in a
re-drill can reconstruct their selection mask without a second selection
request.

One handler can route several charts by stable token:

```python
@rx.event
def shared(self, event: dict):
    if event["token"] == self.region_chart:
        self.apply_regions(event["selection"]["rows"])
    elif event["token"] == self.product_chart:
        self.apply_products(event["selection"]["rows"])
```

View events are `{version, type: "view_change", token, x_domain, y_domain,
source, phase: "update" | "final"}`. User changes are throttled to one
dispatch per 120 ms with a leading edge and a latest-wins trailing flush:
`update`-phase events stream while the gesture is in progress (this is what
lets an `on_view_change`-computed detail chart track a pan/zoom live), and the
resting viewport always lands as the last event with `phase: "final"`. Linked
and republish sources are suppressed. Hover events are latest-wins and
throttled to one dispatch per 120 ms. For viewport synchronization:

```python
@rx.event
def remember_view(self, event: dict):
    self.x_domain = event["x_domain"]
    self.y_domain = event["y_domain"]

reflex_xy.chart(Dash.cloud, on_view_change=Dash.remember_view)
```

Every kernel message echoes the last payload version as `v`; the namespace
silently rejects messages for an older figure version. This prevents an
in-flight pick or selection from resolving in a replacement coordinate space,
while clients that omit `v` remain compatible.

## 6. Latency budget

Unchanged from the notebook comparison, minus HTTP: an interaction message
is one ws frame each way (~0.1–1 ms same-host) around the same kernel
compute (1.5–12 ms view/re-bin at 10M, §12 numbers), inside the client's
120 ms request debounce. Hover stays client-side GPU picking with a
row-readout reply. Appends are push, so streaming latency is producer-bound,
not poll-bound. The figure-var rebuild path adds builder time on state
changes — builders are user code and should be O(state); heavy shared data
prep belongs outside the builder (module cache / backend var), which the
demo app models.

## 7. What shipped where (prototype map)

```
python/reflex-xy/
  reflex_xy/registry.py      token -> FigureEntry(figure, version, lock); TTL;
                             publish/push fan-out seams; append
  reflex_xy/tokens.py        xyv1 token grammar; builder discovery on vars
  reflex_xy/vars.py          @reflex_xy.figure (FigureVar: builder-tracked deps)
  reflex_xy/state_bridge.py  token -> state_manager -> builder rebuild hook
  reflex_xy/namespace.py     XYNamespace: sub/unsub/msg, payload/msg/err,
                             affinity, rebuild-on-miss, binary attachments
  reflex_xy/app.py           setup(app), XYPlugin (post_compile), lifespan
  reflex_xy/component.py     chart() -> rx.Component (local-JSX library);
                             dispatches token (live) vs Chart (static tier)
  reflex_xy/payload_asset.py static tier: Chart -> content-addressed XYBF
                             asset in assets/xy/ (§3.4)
  reflex_xy/assets/          XYChart.jsx; links xy's installed render client
examples/reflex/  (repo root) reflex-xy showcase: figure-var drilldown with
                             hover/click/select events, a slider-driven +
                             cross-filtered histogram, a streaming line, an
                             on_view_change-computed detail chart, and both
                             fixed-data tiers (direct Chart + inline() token)
examples/fastapi/ (repo root) the same charts + a live 100M drilldown served
                             from a plain FastAPI app (no committed HTML)
tests/reflex_adapter/        69 tests: token/registry/var/bridge/payload-asset
                             units, component compile, and a real-websocket
                             integration suite (uvicorn + socketio client)
                             covering payload/pick/select/affinity/rebuild/
                             publish-broadcast/append/unsub
```

`inline()` (content-addressed pinned tokens, §3.4) lives in the package
root beside `register()`/`release()`.

`xy` itself stays Reflex-free (CLAUDE.md rule); the adapter depends on
`xy` + full `reflex` for now — the 0.9.6 `reflex-base` split covers
components/vars but not yet App/state-manager access; revisit when a smaller
supported surface exists.

## 8. Superseded: the HTTP-routes draft

The previous revision of this document specified `GET /_xy/{token}/payload`,
`POST /_xy/{token}/msg`, an SSE `/events` invalidation stream, and the XYBF
binary frame (`python/xy/_framing.py`). What survives: `handle_message`
extraction (shipped as
`xy.channel`), the XYBF frame helpers (still in `python/xy/_framing.py`,
re-exported from `xy.channel`, for HTTP/export hosts), the registry API
shape, and the two-planes analysis. What
changed: transport (§1–§2) and the multi-worker story — the old draft called
the registry's process-locality "the honest hard problem" and sketched a
figure-server; the figure-var + rebuild-from-state design (§3) dissolves it
instead of centralizing it. A future host that genuinely needs HTTP (static
export drilldown, non-Reflex embedding) picks the frame helpers back up; the
message protocol is transport-agnostic either way.

## 9. Open items (tracked, §28: nothing silent)

- **Payload push sizing**: room-wide refreshes use the figure's default
  `px_width`; per-sid re-fit to each viewport is a straightforward follow-up.
- **Static tier px baseline**: payload assets build at the figure's own
  resolved px width, same as `to_html()` exports — a chart declared with a
  numeric `width=` builds at that width, and a responsive chart
  (`width="100%"`) falls back to the 2048 px fluid default until a browser
  reports a real width. With no kernel, decimated line tiers cannot re-refine,
  so extreme upscaling shows the export tier's limits.
  Orphaned `assets/xy/*.xyf` digests accumulate under changing data until
  manually cleared; a compile-time sweep of unreferenced digests is a
  possible follow-up.
- **Chunked payload emission** if head-of-line blocking ever shows up in
  traces (§1).
- **Server-side event dispatch** (kernel callbacks → `app.event_processor`)
  would save the client hop for hover-driven state updates; measure first.
- **reflex-base-only dependency** once App/state-manager surfaces land there.
- **Browser E2E in CI**: `scripts/reflex_ws_smoke.py` asserts the
  one-websocket invariant, painted pixels, density→points drilldown, the
  hover event loop, and append streaming against the running demo app
  (stdlib CDP driver, no new deps). Runs locally today; needs a CI story
  (bun + vite in the runner).
