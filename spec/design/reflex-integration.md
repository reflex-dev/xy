# Reflex integration — design

Status: **implementation landed** (`python/reflex_xy`, tests under
`tests/reflex_adapter/`). This document is the authoritative design; the
prototype implements it end to end over Reflex 0.9.6. The deliverable is an
integration bundled in the `xy` distribution and installed with
`xy[reflex]`. It makes a xy figure a first-class Reflex component with the
same performance contract as the notebook path: screen-bounded binary wire
(§29), kernel-side canonical data (§27), stale-while-revalidate interaction
(§17).

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

**Attachment cap (hard browser limit).** socket.io-parser's `Decoder` ships
with `maxAttachments: 10`; one binary packet with more attachments makes the
browser throw `"too many attachments"`, which `Manager.ondata` converts into
closing the *entire shared websocket* as a parse error — the app plane then
reconnects, every chart re-`sub`s, the oversized payload is re-sent, and the
connection loops forever with no console error. The namespace therefore never
emits more than 10 attachments per packet (`_MAX_WIRE_ATTACHMENTS`):
payloads whose split layout would exceed the cap fall back to the joined
single-blob `build_payload()` form (no `buffer_layout: "split"` in the spec;
the wrapper's `toSpans` already dispatches on that flag), trading the join
copy for staying inside the parser's budget. `msg` replies are bounded by
channel construction; the namespace enforces the same cap as a contract
check and answers `err` instead of emitting an unparseable packet — on both
the reply path and the room-wide push path (`broadcast_message`, the
`reflex_xy.append` fan-out, where one oversized packet would close every
subscriber's connection at once). Regression:
`tests/reflex_adapter/test_socket_data_plane.py::`
`test_sub_over_attachment_limit_ships_single_blob`,
`::test_msg_reply_over_attachment_limit_answers_err_not_msg`, and
`::test_broadcast_over_attachment_limit_answers_err_not_msg`.

The envelope is below; the `m` payload it carries is specified field by field
in `spec/design/wire-protocol.md`.

```
client -> server (namespace /_xy)
  sub     {fig, px?, mid?}      subscribe; join figure room; reply `payload`
  unsub   {fig}                 leave the room
  msg     {fig, v?, mid?, m}    one xy.channel.handle_message dispatch

server -> client
  payload {fig, version, spec, buffers, mid?}   first paint / full refresh
  msg     {fig, version?, mid?, message, buffers}   reply or push (no mid)
  err     {fig, error, resync?}           failure; resync requests a new `sub`
```

`mid` is a validated optional per-mount id: several charts on a page share the
socket, so direct interaction replies and direct subscription payloads echo it
and other mounts ignore the addressed envelope. Pushes and full-payload
broadcasts remain unaddressed and room-wide. This prevents M same-token mounts
from each applying all M direct subscription responses after a resync. The
kernel dispatch is byte-for-byte the notebook dispatch —
`xy.channel.handle_message` (§3.1 of the old draft, now shipped), run off the
event loop via a worker thread (the Rust kernels release the GIL) under a
per-figure lock. Namespace payload builds and interaction dispatches take the
generation's async lock and then its synchronous figure lock, the same order as
wired append. Caller-thread view-state writes take only the synchronous lock;
there is no reverse acquisition. Thus payload emitter updates such as
`shipped_sel`, interaction/drill state, append mutation/version capture, and
row-mask construction cannot overlap for one generation, while unrelated
figures remain independent.

Each successful `sub` starts a client version epoch. The wrapper resets its
comparison state, ignores `msg` events until the authoritative `payload`
arrives, and then compares versions within that epoch. This permits a
reconnect to land on a fresh worker whose rebuilt cache starts at version 1.
Interaction replies, append pushes, and view-state pushes carry `version`.
View-state pushes stamp the figure generation they were built against without
advancing it. Resetting an epoch also cancels pending hover/view throttles, and
the still-mounted old view cannot emit new semantic callbacks while the
replacement payload is in flight. Generation-stamped programmatic
view/selection pushes that arrive before the payload mounts are buffered in
wire order and replayed only after a matching-generation payload or append;
newer generations remain queued while addressed and older-generation messages
are discarded. A queued matching-generation selection replacement suppresses
the payload swap's selection-mask restoration. A replacement that arrives
after mount invalidates every older outstanding selection sequence, including
user gestures and payload restores, so their later replies are discarded
before callbacks or view dispatch rather than overwriting the newer selection.

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
(`dispatchView` in `python/reflex_xy/assets/XYChart.jsx`), because
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

`@reflex_xy.figure` is a computed var whose **value is only a typed
`FigureHandle`** — a frozen dataclass wrapping the token string
`xyv1|<client_token>|<state_full_name>|<var_name>` (serialized to
`{"token": …}` on the delta path by a registered `@rx.serializer`) — and
whose evaluation is what (re)registers the figure in the per-process
registry. The handle type is what makes the component seam compile-checked:
the component's `figure` prop is `Var[FigureHandle]`, so the wrong var or a
raw string fails at `create()` with the framework's own `TypeError`
(design fact R1, pinned in `tests/reflex_adapter/test_framework_contracts.py`).
Reflex's own dependency tracker watches the *builder's* body (the var
subclass points dependency analysis at it), so:

- First render: var evaluates → figure built and registered → handle into
  state.
- A dependency changes: Reflex marks the var dirty; the next delta
  evaluation rebuilds the figure and re-publishes; every subscriber gets a
  fresh payload pushed over the data plane. The token is deterministic, so
  the frontend sees **no prop change at all** — pixels move, DOM doesn't.
- Reconnect (same node or another): the cached handle comes back with the
  state; the component re-`sub`s; hit → serve, miss → §3.2.

Two values carry no token. Before session hydration there is no client
token to mint from, so the var evaluates to `FigureHandle("")`; and a
builder may return `None` for "no chart right now", which **releases** any
existing registry entry and likewise yields the empty handle. The wrapper
treats the empty token as "not ready / no chart" and mounts nothing, so
both cases are a blank mount rather than an error — and the var type stays
non-optional.

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

**Compile probe.** With the data-bound tier (§3.6) validating everything at
page evaluation, the figure var is the one place chart-building user code
still defers to hydrate — so it gets a compile gate of its own.
`XYPlugin.post_compile` walks the state tree, and for every figure var runs
the builder once against a default state instance
(`@reflex_xy.figure(probe=...)` sets the level):

- `probe="build"` — the default for sync builders: run the body and check
  the return is a chart (or `None` for "no chart") — hallucinated `xy.*`
  names, wrong kwargs, eager chrome errors, and a return value no registry
  publish could accept fail `reflex run` with the state class, var name,
  and source location (`FigureProbeError` wrapping the original), instead
  of an `err` frame and a silently blank mount at hydrate.
- `probe="figure"` — additionally compile the result: full config/shape
  validation at the price of building one real figure per var at startup.
- `probe=False` — opt out; the default for `async def` builders (compile
  is sync, and awaiting a data source at compile is what constraint 2
  forbids). An async builder may opt in explicitly and runs under
  `asyncio.run`.

The three levels are the whole domain and validation is identity-strict:
`probe=0`/`0.0` (which compare equal to `False`) are refused at
decoration, never silently treated as an opt-out.

The escape valve for constraint 2: a builder whose source reads
`self.router` is session-dependent by declaration — its probe failure
degrades to a `RuntimeWarning` instead of failing the compile, because only
a live session can validate it. The probe's cost is the builder's own cost
against *default* state, once per backend worker start — the same order of
work Reflex already accepts evaluating ordinary computed vars at compile.

### 3.2 Registry miss: rebuild from state

`sub` (or `msg`) on an unknown state token parses it, resolves the state
class from the full name, loads that session's state through
`app.state_manager.get_state(BaseStateToken(...))` — memory, disk, or Redis,
whatever the app configured — finds the builder on the var, re-runs it, and
serves. The worker that answers a reconnect never needs to have seen the
figure before. **Reflex prod-mode multi-worker works without a figure
server, sticky routing, or chart data in Redis** — the state that was going
to be in Redis anyway is the recovery record.

Failure stays closed: unparseable tokens, unknown states/vars, and builders
that raise answer `err {fig, error}`; the client logs and shows an empty mount
rather than crashing the page. During rebuild, payload construction or room
fan-out failures likewise answer `err` and remove only the generation that
attempt inserted, so a later subscription retries; a concurrent normal
replacement is never removed.

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

`xy.facet_chart(...)` follows the same static tier, but preserves the core
facet contract: because a `FacetGrid` is a composition of independent Figures
rather than one Figure with a combined wire payload, the adapter emits a
responsive CSS grid containing one content-addressed static `XYChart` per
panel. The grid title, column count, gap, and panel height come from the core
`FacetGrid`; container props stay on the grid while semantic event handlers
are forwarded to each panel (with the static tier's event limitations
unchanged). Facet labels need no extra markup: `facet_chart` builds each
panel figure with its facet label as the figure title, so the label ships
inside the panel's payload and the render client draws it as the panel
heading — the same contract `FacetGrid.to_html` relies on.

Design note: the considered alternative was a composite facet spec rendered
by the client (one component instance laying out child payloads, as
Vega-Lite's facet operator does). Per-panel composition was chosen because it
matches every core composer (`to_html`, `widget()`, PNG export), keeps
payload assets content-addressed per panel (one changed facet invalidates
one file), and needs no new spec kind. Revisit the composite-spec approach
only if facets grow cross-panel chrome (shared legends, row/column label
strips) that a host-level CSS grid cannot express. Panel count is bounded in
practice by the render client's shared WebGL context budget, which the
per-panel path inherits unchanged.

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

Rooms track delivery subscriptions; the registry mirrors active SID membership
only for rebuildable state tokens so it can bound version tombstones.
Disconnects and explicit unsubs remove that membership, and the last departure
drops any evicted scalar tombstone; opaque tokens are never tracked. A page
reload still never destroys a live figure that its reconnect will re-request.
The TTL sweep (30 min idle, lifespan task) bounds leaked figures; state-derived
figures transparently rebuild after a sweep, so the TTL bounds large
figure/data memory, not correctness. While at least one rebuildable subscriber
remains, both the sweep and an explicit release retain only the removed token's
scalar version so a republish on the same worker stays monotonic; the figure
and its data buffers are released. If an interaction is the first touch after
eviction, the namespace
rebuilds, sends every subscribed mount a replacement payload room-wide, and
drops the old-generation interaction for the triggering client to retry. If a
new `sub` is first, the namespace broadcasts the rebuild to existing room
members before joining the requester, then sends that mount one `mid`-addressed
payload built for its own `px` hint. The direct path re-reads the current entry
after joining the room: a normal replacement that landed before the join is
sent directly, while a replacement after the join reaches the mount through
the room broadcast. Concurrent same-token misses share the complete rebuild
attempt, including failure and room fan-out: one state builder publishes and
broadcasts one current generation, while the remaining mounts wait for that
same result. Every interaction that observed the miss is dropped until its
authoritative payload arrives, even when another waiter inserted the entry or
the rebuilt version happens to match. One failed attempt answers every current
waiter with `err`; a later arrival may start a fresh retry. The rebuild's final
insertion carries a bounded guard that exists only for the active attempt. A
normal dependency-driven publish or release invalidates that guard while user
builder code is awaiting: a populated newer entry wins, and a newer absence
rejects the stale result so a later request rebuilds from current state. No
process-lifetime per-token revision map is retained. Subscribe/unsubscribe
handlers for one SID/token are serialized,
and a handler rechecks live Socket.IO membership after every await-heavy phase
so a slow rebuild cannot restore bookkeeping after disconnect. Active append
generations are leased; the sweep skips them until the mutation and version
bump finish. Rapid re-publishes coalesce: an un-started broadcast absorbs newer
publishes and always ships the latest payload.

### 3.6 The data-bound tier: `@reflex_xy.data`, plans, composite tokens

The primary component API (adopted design: Option 6 of
[`reflex-component-api-options.md`](reflex-component-api-options.md); work
plan in [`reflex-component-api-implementation.md`](reflex-component-api-implementation.md))
splits the figure var's job in two: **structure is declared in the page**,
**state supplies only columns**.

```python
class CloudData(TypedDict):
    x: np.ndarray; y: np.ndarray; mag: np.ndarray

class Dash(rx.State):
    points: int = 200_000

    @reflex_xy.data                     # columns only — no chart API inside
    def cloud(self) -> CloudData: ...

def index():
    return reflex_xy.scatter_chart(     # flat form; reflex_xy.chart(*nodes)
        data=Dash.cloud,                # is the composed multi-mark form
        x="x", y="y", color="mag", colormap="viridis",
        height="460px", on_select_end=Dash.select,
    )
```

**`@reflex_xy.data`** (`data_vars.py` — the module is named `data_vars`
because a `data.py` submodule would shadow the `reflex_xy.data` export) is
the exact sibling of `@reflex_xy.figure`: a computed var whose value is a
typed `DataHandle` wrapping `xyd1|<client>|<state>|<var>` (same grammar,
charset, purity contract, pre-session short-circuit, underscore refusal,
async dispatch, and `None`-releases semantics as figure vars). Evaluating
it validates the returned mapping — string keys, array-likes; the only
check that needs real data — and publishes the **columns** into the
registry. Columns may differ in length and dimensionality (a stairs mark's
`len+1` edges or a heatmap's 2-D grid beside ordinary row columns):
coupled-length and shape contracts belong to the mark validators when a
plan binds, where the errors name the mark and channels involved. The method's return annotation is the compile-time
schema channel (fact R7): a `TypedDict` parametrizes the handle
(`DataHandle[CloudData]`), and the factories read the column names from the
class-level var without executing anything; a plain `dict` annotation
degrades to first-execution validation.

**Plans** (`plan.py`). A chart factory call at page evaluation compiles its
xy nodes (string channels only) into a `ChartPlan`: the real tree is built,
placeholder columns are bound for every referenced channel through
the production resolution path (a recording table — the column list cannot
drift from what binding will look up), and `.figure()` runs once under
`xy.structural_probe()` — the full mark/config validation gate (X1/X2) at
compile time, in milliseconds, with no data ingestion (constraint 2).
Every placeholder is zero-row; data-requiring builders validate config and
emit no trace, so the probe contains no synthetic values (see "Kind coverage"
below). The canonical JSON of the tree
(`plan_version: 1`) is content-addressed into a sha256-prefix `digest` and
registered in a process-local `{digest: plan}` map. Fact X4 ("page bodies
run in every worker") turned out to hold only for processes that run the
frontend compile — **backend-only workers (dev backend subprocesses and
prod workers) import the app module but leave pages unevaluated**, which
would leave their plan maps empty and every plan subscription answering
`err {resync}`. The integration therefore makes X4 true by construction:
`setup(app)`'s lifespan evaluates the app's unevaluated page component
functions once at worker startup (`_ensure_page_plans`), before serving —
factories register their plans as a side effect and the built trees are
discarded (plans and payload assets are content-addressed and idempotent).
Failure is **fail-closed**: a page that cannot evaluate would leave this
worker's plan map incomplete — behind a load balancer that means charts
blank or not depending on which worker answers — so `_ensure_page_plans`
collects every failing page and refuses worker startup with an error
naming them, instead of serving inconsistently. "Refuses worker startup"
depends on *where* the pass runs: Reflex starts a coroutine lifespan task
with `asyncio.create_task(task())` and then yields, so an `async def`
lifespan body would raise in the background on an already-serving worker —
fail-open, the shape this exists to prevent. The registered task is
therefore a plain function that runs `_ensure_page_plans` synchronously and
*returns* the sweep coroutine; the raise happens in the `task()` call, in
Reflex's startup path, before serving. Pinned by
`test_page_plan_registration.py::test_page_evaluation_runs_before_the_lifespan_coroutine_is_scheduled`.
The contract this puts on
app code is **re-evaluability**: a page body runs at least twice per
process (the compile, then this pass) and must build the same charts each
time. Code that mutates module state a later page body reads — the docs
site's Markdown demo runner cached exec fences in one page-wide module
namespace, so a second render rebuilt each demo from the *last* fence's
data — either changes plan digests (leaving the compiled frontend's token
unregistered) or fails outright here; a page that only fails on the second
evaluation still passes `reflex run`'s compile, so the fail-closed error is
the check that catches it. Binding is the reverse:
columns + plan → a **fresh** `Chart` (never reused — X3) → `.figure()`.
Column-mismatch errors name both sides (*"plan binds column 'mag';
Dash.cloud produced {x, y}"*). Plans refuse concrete arrays, per-mark
`data=`, and `render=` components — data-free structure only. Callables
in mark props (hexbin's `reduce_C_function`, `np.mean` by default) are
**content-addressed, not name-addressed**: a pure-Python function
serializes as its import path *plus a code fingerprint* (bytecode, names,
nested code, defaults), so editing a reducer's body changes the digest —
two workers on either side of a rolling deployment can never execute
different behavior behind one address (mismatched digests resync
instead). C-level callables (ufuncs, builtins) must resolve back to the
same object by qualified name and carry their distribution's version.
Bound methods are refused outright (instance state has no content
address; two differently configured instances would collide on one
digest), as are lambdas, closures, and partials. Re-registration under a
digest is last-write-wins, so a hot-reloaded page replaces stale node
objects. **Recorded boundary:** the fingerprint addresses *code*, not
process state. A module-level function that reads a mutable module global
executes whatever that global holds in the serving worker — exactly like
an `@reflex_xy.figure` builder or `@reflex_xy.data` method that does the
same, and no more addressable: hashing referenced global *values* would
have to snapshot an unbounded, mutable object graph at registration and
still be stale by bind time, and refusing functions that reference any
global name would refuse every NumPy-using reducer (`np` is a global
reference). The declared state carriers — closures, partials, bound
methods — are refused; residual global-state impurity is the same
purity contract every server-side builder tier already carries (§3.1). The probe
figure also yields `dom_class_strings()`, so **live data-bound charts get
automatic Tailwind discovery** (previously live sources needed the manual
inventory).

**Factories.** `factories.py` provides the flat per-kind forms
(`reflex_xy.scatter_chart(data=…, x="x", y="y", …)`) and the composed
`reflex_xy.chart(*nodes, data=…)` for multi-mark charts, plus curated
re-exports of the xy node constructors (`reflex_xy.scatter` *is*
`xy.scatter`, so a hallucinated constructor dies at import instead of
surviving to hydrate). The kwarg partition between mark options, chrome,
component props, and event handlers is derived from `inspect.signature` at
import — not hand-listed — so it cannot drift from xy's own signatures;
collisions get generated aliases (`mark_<name>`, with `width` becoming
`stroke_width` where the mark hasn't claimed it), pinned by test. Derivation
is filtered on one axis only: underscore-prefixed signature params are xy's
private adapter knobs (the pyplot shim's `_artist_alpha`, `_marker_path`, …)
and are excluded from both the accepted set and the did-you-mean
candidates — deriving the public surface from signatures must not promote
private names into it. Top-level
kwargs are **strict**: an unknown name always raises `TypeError` at page
evaluation — with a did-you-mean when a known name is close — and never
silently becomes a CSS property (the R8 hazard, closed rather than
compensated for by a distance threshold); CSS goes through the explicit
`style={...}` prop, which reaches the DOM unchanged. Errors
this tier catches at `reflex run`: hallucinated factory names (import),
unknown kwargs (partition), bad colormaps/enums/axis
refs (plan probe), unknown column names against a typed data var
(schema channel), and the wrong var or a raw string in `data=` (typed
prop, R1).

**Static tier symmetry.** `data=` given a concrete mapping (not a Var)
binds immediately and routes to the §3.4 payload-asset path — same
validation, same spec-aware bind errors, works under `reflex export`,
never touches the registry.

**Kind coverage (recorded decision, revised 2026-08 twice).** Flat
factories exist for **every standalone mark kind**: scatter, line,
histogram, bar, area, step, stem, column, errorbar, error_band, segments,
triangle_mesh, funnel, box, violin, ecdf, hexbin, contour, heatmap, stairs — each
derived from the mark's signature, and the composed
`reflex_xy.chart(*nodes, data=...)` accepts any mix of those marks plus
annotations and chrome. The aggregating kinds were first excluded (their
validators refuse zero rows), then briefly probed with recorded synthetic
placeholder columns; review showed synthetic data is **not structurally
sound**: a column shared between an aggregating channel and a zero-row
channel falsely failed on invented lengths, a valid hexbin `range=` or
`mincnt=` falsely failed on invented values, and a large `gridsize` ran
real aggregation at page evaluation. The resolution is a core validation
seam instead of cleverer data: the probe compiles under
`xy.structural_probe()` (spec/api/chart-kind-contract.md "Structural
probe"), where a mark with all-empty channels validates configuration and
skips its data-dependent work. Every kind probes **zero-row**; there is no synthetic
data anywhere; configuration errors (bad enums/bounds/colormaps/range
shapes) still fail `reflex run`; data-dependent outcomes (range
filtering, mincnt, quantiles, marching) and real-data shape couplings
(`edges = len+1`, z 2-D-ness) are computed and checked at bind. Pinned by
`tests/test_validation_timing.py` (the xy half: every kind compiles empty
under the probe, still refuses empty normally, still raises config
errors) and `tests/reflex_adapter/test_plan.py` (the plan half, including
the shared-column and hexbin-config repros from review). The data-taking
composite factories (pie, radar, wind_rose, sankey — eager numeric work
at call time) remain outside the plan tier: they don't produce data-free
nodes, and keep the two recorded routes (`@reflex_xy.figure`, or a
concrete xy Chart on the static tier).

**Column entries.** Published columns are registry entries in their own
right, keyed by the data token: pure rebuildable caches of Reflex state
(the `@reflex_xy.data` method is the recipe), so they carry none of the
figure entry's kernel machinery — no locks (a republish replaces the whole
immutable generation and bumps its version), no pins, always sweepable
under the same TTL. The registry also keeps the `data token → {digests}`
index that lets a column republish rebuild every mounted dependent plan,
and an error seam (`on_error`) for room-wide failures that answer no
request.

**Composite tokens.** The two halves compose into one figure identity —
`xyp1|<digest>|<xyd1 token>` — assembled by the wrapper client-side from
the `plan` and `data` props, and subscribed once the data handle hydrates
(an empty handle token means "not ready", exactly as for figure handles).
Rooms, versions, `mid`
addressing, the attachment cap, and every message below the subscribe path
treat it as an ordinary `fig` string; the envelope grew no fields. Serving
it = `plan_of(digest)` + columns (registry hit, else `rebuild_data` re-runs
the data method against session state) + bind into a fresh `Chart` →
`figure()` → cached under the composite token as a normal, TTL-sweepable
`FigureEntry`. The rebuild recipe is (plan map, data method): both halves
independently recoverable on any worker, which is what keeps §3.2's
promise intact for this tier. Session affinity reads the embedded data
token, so a composite belonging to another session is refused exactly like
a figure token; a *bare* `xyd1` token names columns, never a figure, and is
refused as a subscription outright.

**Republish fan-out.** A data var recompute publishes new columns and
re-binds every mounted dependent through the `data token → {digests}`
index — fresh figures, bumped versions, coalesced room broadcasts, exactly
the figure-var republish machinery. The index is added to when a composite
binds (namespace `sub`) and pruned on **every transition that can end the
mount**: the last unsubscribe or disconnect for the composite token, its
entry's release, failed-rebuild cleanup, the TTL sweep, and a republish
that finds it unmounted (`_unbind_plan_if_unmounted_locked`). "Bounded by
mounted plans" therefore holds for short-lived sessions too — cleanup never
depends on that same session republishing later. Pinned by
`test_data_var.py::test_unmount_transitions_drop_plan_bindings`. Failure
stays loud: a bind that stops matching
(possible only for untyped data vars) logs server-side, releases the
composite entry, and answers the room `err {resync}`; a stale digest
(hot-reload drift) answers `err {resync}` naming the digest. The client
bounds consecutive err-triggered resyncs (5 without an intervening
payload), so a permanently failing identity settles into a visible console
error instead of a subscribe loop.

**Republish ordering.** Dependent rebuilds run outside the registry mutex
(they execute user-scale figure builds), so two republishes of one data
token may finish in reverse order. Every rebuild therefore carries the
`ColumnEntry` generation it serves, and each of its outcomes — the figure
publish, and the failure path's release + `err {resync}` frame — is gated
on that generation still being current, *atomically with the registry
mutation*. An older generation that finishes late is dropped whole:
subscribers can never observe a newer generation's pixels replaced by an
older one's, and a superseded failure raises no stale error. Pinned by
`test_data_var.py::test_stale_column_generation_cannot_overwrite_a_newer_publish`.

**Plan immutability.** `build_plan` hashes — and registers — a deep
snapshot of the node tree and chart props, not the caller's objects.
Page code that reuses and later mutates a mark node (or the props dict)
cannot change binding behavior behind an unchanged digest/columns record;
the canonical representation is the source of truth. Pinned by
`test_plan.py::test_plan_is_a_snapshot_immune_to_later_node_mutation`.

**Plan format stability.** `plan_version: 1` is part of the canonical
serialization and a golden digest is pinned in
`tests/reflex_adapter/test_plan.py`. Digests are content addresses, not a
migration surface: after a format (or grammar) change, old subscribers'
digests simply miss and resync against the recompiled page — the golden
exists to catch *accidental* churn, and an intentional change bumps
`PLAN_VERSION` and re-records it.

## 4. Updates and streaming

- **State-driven rebuild** (filter changed): the figure var recomputes,
  `registry.publish` bumps the version and pushes one full `payload` to the
  room. Stable token: no component re-render, one screen-bounded reship. The
  in-place swap re-homes the viewport to the incoming spec's axis ranges — a
  full payload carries no follow policy of its own. If an incoming
  constructor-owned chrome input differs — `dom`, title, legend, colorbar,
  badge presence, modebar/interaction topology, padding, or axis-band layout —
  the adapter performs a full view rebuild instead: persistent nodes otherwise
  retain the old structure, classes, and inline styles. It snapshots the
  public durable-state document first, restores every named-axis range and
  box/range/lasso geometry without broadcasting or replaying semantic
  callbacks, then issues one selection-mask refresh. A chart the viewer has
  navigated is re-pinned to its prior window afterward (the restore contract
  below); a dependent chart sitting at its home simply follows the new data.
  In both cases the home *must* be the new spec's own extents, not the previous
  payload's: it is what lets an
  `on_view_change`-computed detail chart track its source both ways — when the
  linked overview zooms *out*, the recomputed detail's count axis grows and the
  view expands with it instead of clamping to the previous, smaller home
  (`ChartView.updatePayload`, `js/src/56_animation.ts`).
- **Streaming**: `reflex_xy.append(token, x=..., y=...)` from any handler,
  background task, or thread → `Figure.append` under the figure lock (worker
  thread) → the same `append` message the kernel builds for the notebook
  widget (which delivers it as its spec/buffers trait update, wire-protocol
  §4), pushed room-wide as a `msg` event with split-layout buffers. The
  push carries the post-append figure version; the client applies it only when
  it is the next version in the active payload epoch, using the existing
  follow policy (refit at home, slide when pinned to the live edge, hold when
  inspecting history). A forward version gap triggers a new `sub`; an
  over-attachment-limit append emits `err {resync: true}` for the same full-
  payload recovery instead of leaving the client permanently behind.
- **Interaction** (pan/zoom/hover/select): `msg` round-trips into the
  kernel, exactly the anywidget flow — tier updates, density re-bins, exact
  f64 pick rows, selection masks as binary buffers.

## 5. The component

```python
reflex_xy.chart(
    figure=Dash.cloud,               # a figure var, or an inline()/register() handle
    on_point_hover=Dash.on_hover,    # semantic events -> normal handlers
    on_select_end=Dash.on_select,
    tailwind_classes="rounded-xl dark:bg-slate-950",  # build-time scan inventory
    height="460px",
)

reflex_xy.chart(xy.line_chart(...))  # …or a Chart directly: static tier (§3.4)
```

One factory, dispatched on the source. `figure=` takes the live tier: a
`@reflex_xy.figure` state var or the `FigureHandle` returned by
`register()`/`inline()`, landing in the typed `figure` prop
(`Var[FigureHandle]`) and riding the socket data plane. Because the prop is
`Var`-typed, `chart(figure=Dash.points)` and `chart(figure="raw string")`
fail at `create()` — page evaluation, before any browser — with the
framework's `TypeError` (R1, §3.1). A Chart/Figure
passed positionally compiles to a payload asset and lands in the `src`
prop, which the wrapper fetches and renders kernel-less — the static tier
stays positional (it is the only route for arbitrary Charts, e.g. facet
grids) and is not deprecated.

**Deprecation (one release cycle).** The pre-handle positional spellings —
`chart(Dash.cloud)` and `chart(token_string)` — remain as a shim and warn:
handle-typed sources (vars or `FigureHandle`s) are routed to `figure=`;
legacy `str`-typed vars and raw token strings keep the old `Var[str]`
`token` prop, which the wrapper still accepts alongside `figure`
(`figure` wins when both are set). Public APIs that take "a figure"
(`append`, `set_view`, `reset_view`, `select`, `clear_selection`,
`release`) accept both a `FigureHandle` and its bare `.token` string —
and *only* those: a `DataHandle` (columns, never a figure) or any other
value raises `TypeError` immediately instead of resolving to a token that
can never name a figure room.

Kernel-backed event props (`on_point_hover`, `on_point_click`,
`on_select_end`) on a static `src` source are refused at `create()` with a
`ValueError` naming the live alternatives — previously they compiled and
silently never fired. Client-resolved events (`on_hover`,
`on_view_change`, animation events) stay valid on every tier. A
`None`-valued `on_*` prop is an explicitly disabled handler: `create()`
drops it before validation and before the framework sees it, so
`on_point_hover=None` is legal on every tier.

Static Chart/Figure sources mirror every class string from
`Figure.dom_class_strings()` into the scan-only `tailwindClassTokens` JSX prop,
because their XYBF payload is opaque to Tailwind. Token/Var sources have no
compile-time figure, so `tailwind_classes=` supplies their possible complete
utility names explicitly. The adapter accepts one string or an ordered iterable
of strings, rejects mappings and unordered sets, validates concrete strings,
de-duplicates tokens in order, merges an explicit inventory with static
discovery, and applies the explicit inventory to every panel of a facet grid.
Only real DOM emitters enter automatic discovery: chart/slot and annotation
label classes, never adapter-only mark metadata.

Tailwind scans generated source as text rather than evaluating JavaScript.
Serializing the inventory as an ordinary JSON string would therefore change
candidate names containing quotes, backslashes, or non-ASCII characters. The
adapter emits each normalized manifest verbatim inside a JavaScript line
comment whose expression evaluates to an empty string. `XYChart.jsx`
destructures and discards that scan prop before `divProps` reaches the DOM.

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

reflex_xy.chart(figure=Dash.cloud, on_point_click=Dash.inspect_point)
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

reflex_xy.chart(figure=Dash.cloud, on_view_change=Dash.remember_view)
```

Every kernel request echoes the last payload version as `v`; the namespace
silently rejects requests for another figure version and drops an explicitly
malformed `v`. Omitted `v` remains accepted for compatibility. Replies echo
the operation version; room-wide append pushes carry the newly bumped version,
and view-state pushes carry the current, non-bumped generation. This prevents
an in-flight pick, selection, or mask from resolving in a replacement
coordinate space. On subscribe/reconnect, the client waits for the new payload
before accepting messages and treats it as a fresh comparison epoch, so a
different worker may safely begin again at version 1. Once a room payload has
mounted, a duplicate room broadcast at that same generation is ignored; this
lets canonical rebuild recovery retry delivery without clearing a rows mask
that was already replayed for the generation.
While disconnected, the wrapper does not enqueue kernel messages: socket.io
flushes its send buffer before its `connect` callback, which would otherwise
send old-epoch requests ahead of the resetting `sub`.

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

**Plan-tier costs (measured).** The data-bound tier moves work to page
evaluation and worker startup; `scripts/bench_reflex_plans.py` measures it
reproducibly (`uv run python scripts/bench_reflex_plans.py [--json]`).
Recorded 2026-08-06 (Linux, Python 3.12, native core, dev machine):

| metric | recorded | scale contract |
|---|---|---|
| plan build (compile + probe + digest) | 0.26 ms median | per chart factory call, milliseconds — page evaluation stays compile-scale |
| worker startup page evaluation | 15 ms (20 pages × 4 charts) | `_ensure_page_plans` re-runs pages once per worker boot; linear in charts |
| column republish → new mounted payload | see the sweep below | dominated by the dependent figure build, not registry bookkeeping |
| plan map entry | ~1.5 KB/plan | process-lifetime map, bounded by page code |

Republish is recorded as a **sweep**, not as one number: "state deltas are
independent of data size, a republish is one screen-bounded reship" is a
scaling claim, and a single measurement at a single N is consistent with
every growth curve while revealing none of them. The sweep straddles
`SCATTER_DENSITY_THRESHOLD` (200k) so both regimes are visible — below it
each republish rebuilds a full exact-marker figure, above it the density
tier takes over — and the range spans the direct soft ceiling (2M). Each size
is measured over `REPUBLISH_TRIALS` independent trials, because at the top of
the sweep run-to-run variance is comparable to the gap between neighbouring
sizes: a single median per size cannot tell a trend from noise, and reading
one high point as a trend is precisely the error this table must not invite.
Recorded 2026-08-06 (Linux, Python 3.11, native core, CI-class container; a
faster dev machine records lower across the board, so the contract is the
*shape* of the normalized column, not its constant):

| points | republish | per 1M points | per 1M across trials |
|---|---|---|---|
| 10,000 | 0.23 ms | 22.81 ms | 21.54 – 24.78 |
| 100,000 | 1.22 ms | 12.22 ms | 12.09 – 12.47 |
| 1,000,000 | 2.95 ms | 2.95 ms | 2.94 – 3.06 |
| 2,000,000 | 5.72 ms | 2.86 ms | 2.78 – 2.87 |
| 5,000,000 | 13.83 ms | 2.77 ms | 2.65 – 2.90 |

The normalized column falls steeply while fixed per-publish work still
dominates, then settles into a band — ~2.7–3.1 ms/1M from 1M up, with the
three large sizes' trial ranges overlapping. Above the threshold the cost is
the per-point figure build the republish fans out, and nothing is growing
faster than it.

The regression signal is the normalized value at the top of the sweep rising
*clear of that band* — a second pass over the columns, a copy that used to be
a view — not any increase between adjacent rows. Neighbouring sizes here
differ by less than the spread within a single size, so a one-row uptick is
noise until a trial range separates it. Compare bands, not medians.

Re-record when the probe or serialization changes materially; a plan build
drifting toward tens of milliseconds, or a republish cost growing faster
than its figure build, is a regression against this table.

## 7. What shipped where (prototype map)

```
python/reflex_xy/
  registry.py                token -> FigureEntry(figure, version, lock); TTL;
                             publish/push/error fan-out seams; append; column
                             entries + data-token -> digest index (§3.6)
  tokens.py                  xyv1/xyd1/xyp1 token grammar; builder discovery
  handles.py                 FigureHandle / DataHandle[S] (+ serializers):
                             the typed values chart state vars carry
  vars.py                    @reflex_xy.figure (FigureVar: builder-tracked deps)
  data_vars.py               @reflex_xy.data (DataVar: columns in, handle out)
  plan.py                    ChartPlan: placeholder probe, canonical digest,
                             process-local plan map, bind (§3.6)
  factories.py               scatter/line/histogram/bar_chart flat factories +
                             composed chart(*nodes): signature-derived kwarg
                             partition, schema checks, plan/data/static mount
  state_bridge.py            token -> state_manager -> builder/data/plan
                             rebuild hooks
  namespace.py               XYNamespace: sub/unsub/msg, payload/msg/err,
                             affinity (incl. composite), rebuild-on-miss,
                             binary attachments
  app.py                     setup(app), XYPlugin (post_compile), lifespan
  component.py               chart(figure=...) -> rx.Component (local-JSX
                             library); typed figure/data props; static tier
  payload_asset.py           static tier: Chart -> content-addressed XYBF
                             asset in assets/xy/ (§3.4)
  assets/                    XYChart.jsx; links xy's installed render client
examples/reflex/  (repo root) Reflex showcase on the §3.6 data-bound API: a
                             composed 1M drillable scatter with hover/click/
                             select events, an on_view_change data var
                             republishing in-view columns into a fixed
                             histogram plan, a flat scatter whose slider
                             republishes columns under a stable handle, and
                             an rx.cond toggle between a composed board and
                             rx.foreach small multiples over a
                             list[DataHandle] var; the
                             @reflex_xy.figure escape hatch where structure
                             reads state (slider-driven + cross-filtered
                             histogram), a streaming line (append), both
                             fixed-data tiers (concrete data= columns ->
                             payload asset; inline() token), the fastapi live
                             drilldown served adapter-natively from an
                             inline() token (same data and XY_LIVE_POINTS
                             override, zero transport code — the cross-host
                             A/B for that chart), plus legend hover-highlight
                             and click-to-toggle (named series client-side; a
                             categorical density inline() token whose category
                             toggles re-bin kernel-side, §34)
examples/fastapi/ (repo root) the same charts + a live 100M drilldown served
                             from a plain FastAPI app (no committed HTML)
tests/reflex_adapter/        token/registry/var/data-var/plan/factory/bridge/
                             payload-asset units, component compile, framework
                             contract pins (R1/R7/R8), and a real-websocket
                             integration suite (uvicorn + socketio client)
                             covering payload/pick/select/affinity/rebuild/
                             publish-broadcast/append/unsub + the composite
                             plan tier (fan-out, plan-miss resync, bind errs)
```

`inline()` (content-addressed pinned tokens, §3.4) lives in the package
root beside `register()`/`release()`.

The core `python/xy` package itself stays Reflex-free (CLAUDE.md rule).
`xy[reflex]` adds full `reflex>=0.9.6` for now — the `reflex-base` split covers
components/vars but not yet App/state-manager access; revisit when a smaller
supported surface exists.

**Versioning & releases.** The integration ships in every `xy` wheel and sdist,
so it shares the core's version and bare `vX.Y.Z` release tags. The published
extra is dependency metadata only: it adds the supported Reflex floor without
creating another distribution or release pipeline.

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
