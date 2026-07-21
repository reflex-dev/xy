# View state, history, and programmatic control — design

**Status: implemented** (all four §11 phases, this PR).
[`../api/interaction.md`](../api/interaction.md) is the authority on the
*shipped* interaction surface and [`wire-protocol.md`](wire-protocol.md) §4 on
the wire messages; this document records the rationale and the §13
implementation divergences. The implementation lives in
`js/src/57_viewstate.js` (state document, history, axis bands, hover payload)
plus hooks in `50_chartview.js`/`52_tooltip.js`/`53_interaction.js`/
`54_kernel.js`, `python/xy/_figure.py` (message builders, `view_state()`
cache), `widget.py`, `channel.py`, and
`python/reflex-xy/reflex_xy/` (registry push path, `on_hover`, tooltip
mount). It builds directly on the per-axis
pan/zoom contract of PR #117 (canonical per-axis `ranges`, one clamped
mutation path, semantic view events with `source`, `axes`, `phase`,
`interaction_id`), which has landed.

## 1. Problem: four requests, one missing primitive

Four open requests are, individually, small features:

- **#110** — a view history stack, so a user can step back to a previous view.
- **#111** — custom tooltip renderers in `reflex_xy` with a structured
  payload and cursor coordinates.
- **#120** — per-axis navigation gestures: hover an axis, get a resize
  cursor, drag/scroll to change only that axis.
- **#121** — out-of-band programmatic zoom/pan/select through `reflex_xy`,
  "similar to `.append`", without recreating the chart.

Designed separately, each grows its own code path for describing "where the
chart is looking and what is selected", its own clamping rules, and its own
event story. Designed together, they are one primitive: a **canonical,
serializable view state** with a single mutation path, which history
snapshots, programmatic APIs write, axis gestures scope, and hover events
read. This document defines that primitive and derives the four features
from it.

## 2. The state object

View state has two tiers with different lifetimes:

- **Durable state** — axis ranges and geometric selection. Snapshotted by
  history, writable programmatically, serializable, restorable.
- **Ephemeral state** — hover/cursor. Evented and readable (§7), never
  snapshotted, never serialized, never broadcast to link groups.

The durable state is one JSON document:

```json
{
  "v": 1,
  "ranges": {"x": [1706.25, 1834.5], "y2": [-3.0, 3.0]},
  "selection": {"range": {"x0": 10, "x1": 20, "y0": 0, "y1": 5}}
}
```

Rules:

- `v` is the state-schema version, independent of the wire-protocol
  handshake. A client that receives a higher `v` than it understands rejects
  the whole document; it never applies a partial interpretation.
- `ranges` is keyed by exact axis ID (`"x"`, `"y"`, `"y2"`, …), matching the
  PR #117 event payload. Values are `[lo, hi]` f64 pairs.
- `selection` is one of `{"range": {x0, x1, y0, y1}}`,
  `{"polygon": [[x, y], …]}`, or `null`. The two non-null shapes are exactly
  the shipped `on_brush` payloads. Row-index selections (§5.1
  `select(rows=...)`) are deliberately *not* representable here: an arbitrary
  per-trace index set can be arbitrarily large, and snapshots must stay a
  handful of floats. Rows-selections are therefore non-durable (§5.1).
  The modebar drag mode is UI mode, not view state; it is not part of this
  document (an early draft included `drag_action` and it was removed — the
  kernel cannot observe modebar tool changes, and "which tool is armed" says
  nothing about where the chart is looking).
- All numbers must be finite. Like standalone HTML export, `NaN` and
  infinity are rejected at the boundary, not coerced.
- Unknown top-level keys and unknown axis IDs are errors at `v: 1`. Forward
  compatibility comes from bumping `v`, not from silently ignoring content.

**Patch semantics.** Everywhere a state document is *applied* (programmatic
set, history restore, linked update), it is a merge-patch against the live
state: an absent key leaves that facet unchanged, an explicit `null`
selection clears the selection, an absent axis in `ranges` leaves that axis
alone. A full snapshot (as stored by history) is therefore just a patch that
happens to mention everything. `fig.reset_view()` is not "apply empty
patch"; it is an explicit navigation to the home ranges (§5).

## 3. One mutation path

The load-bearing invariant, extended from PR #117:

> Every durable-state change — pointer drag, wheel, box zoom, toolbar
> button, double-click, linked update, history restore, and programmatic
> write — flows through the same validate → clamp → commit → emit path in
> the browser client.

Consequences:

- Programmatic writes and history restores obey the same per-axis clamps as
  gestures: `zoom_limits`, pan-lock containment, and `bounds`. An
  application cannot construct a view that a user gesture could not reach.
  (`navigation=False` charts keep their PR #117 behavior: they accept linked
  and programmatic updates — that gate is a *capability* gate on user input,
  not a clamp.)
- Every change emits the same semantic view event. New `source` values are
  added for the new writers: `"api"` (programmatic), `"history"`
  (back/forward), joining `"pan"`, `"linked"`, and the PR #117 source set.
  Handlers that must not react to their own writes filter on `source`
  — the same discipline the `BroadcastChannel` link layer already applies
  with `_linkedSource` echo-dropping.
- Selection changes keep the shipped ordering invariant (`on_brush` before
  `on_select`) regardless of writer.
- There is exactly one implementation of "apply a state patch" in
  `js/src/53_interaction.js`, and every entry point in this document is a
  caller of it.

The browser client owns the live state; the kernel and the Reflex backend
are writers and observers, never a second source of truth. This keeps every
feature below functional in kernel-less standalone HTML.

## 4. History (#110)

A client-side ring buffer of durable-state snapshots. No kernel required —
history works in notebooks, Reflex, and standalone HTML export identically.

- **Push policy.** A snapshot of the *previous* durable state is pushed when
  a mutation with a new `interaction_id` commits. All phases of one gesture
  (`phase: "start"` → moves → `"end"`) share an `interaction_id`, so a drag
  is one history entry, not hundreds. Geometric selection changes push like
  range changes: they are durable and undoable. Rows-selections do not push
  (§5.1) — stepping back over one restores the prior *geometric* state.
  A write that lands while an animated navigation is still in flight
  coalesces into it: no new entry (its pre-state is a mid-flight frame the
  user never settled on), and the settle event carries the *latest*
  writer's `source` and `interaction_id`.
- **Writers that push:** user gestures, toolbar actions, double-click reset,
  and programmatic writes (opt out per call with `history=False`).
- **Writers that do not push:** linked updates (`source: "linked"`) and
  history navigation itself. A linked peer does not record the group's
  churn; stepping back on the *originating* chart re-broadcasts through the
  normal mutation path, so the group follows the originator's history.
- **Reset is navigation, not amnesia.** Double-click / Reset View pushes the
  pre-reset state, so "I double-clicked and lost my zoom" — the literal
  #110 complaint — is one Back away. Reset continues to preserve the
  selection per PR #117.
- **Capacity** is 64 entries, oldest evicted. Snapshots are a handful of
  floats; memory is not a concern, predictability is.
- **Surface.** Two modebar buttons, Back and Forward, enabled only when the
  corresponding stack side is non-empty, subject to the existing modebar fit
  rule; and the static handle's `back()`/`forward()` (§5.3). History
  navigation is *client-scoped by construction* — there is deliberately no
  Python-side `view_back()`: stacks live in each client, clients in one
  Reflex room (or views of one notebook model) accumulate different stacks
  after local gestures, so a broadcast "back" operation would have each
  client restore a different snapshot (§5.2). Keyboard bindings are deferred
  with touch pinch; the existing keyboard point traversal is untouched.
- **Switch.** `interaction_config(history=…)`, default on, following the
  absent-key-fallback resolution of interaction.md §1. Disabling removes the
  buttons and stops snapshotting.

## 5. Programmatic control (#121)

### 5.1 Core figure API (kernel-connected: notebook widget, live Reflex)

```python
fig.set_view(ranges={"x": (0, 100)}, *, animate=True, history=True)
fig.reset_view(axes=None)              # None = the configured reset_axes
fig.select(range=..., polygon=..., rows=..., *, history=True)
fig.clear_selection()
fig.view_state()                       # -> last committed durable state
```

- `set_view` takes a partial `ranges` mapping — patch semantics (§2). It is
  the write-side mirror of the `on_view_change` payload.
- `select(rows=...)` accepts per-trace row indices — the same canonical form
  the shipped `Selection` object reports — and resolves them kernel-side
  into the existing binary selection-mask buffers. `range=`/`polygon=` ship
  the geometric forms and let the client resolve, exactly like a gesture.
  Indices are validated against the trace's canonical row count before the
  uint32 wire encoding — negative, non-integral, or out-of-range input
  raises; duplicates deduplicate, and `total` reports validated unique
  rows. A rows document *replaces* the whole selection: traces omitted
  from it are cleared, not left holding stale masks.
  Rows-selections are **non-durable and non-undoable**: `history=` is
  ignored for them, they never enter the §4 stack, and `view_state()`
  reports them as the opaque marker `{"selection": {"rows": true}}` rather
  than the index set (§2 records why).
- `view_state()` does not round-trip: the kernel already observes every
  committed change through view/selection events; it caches the last
  durable state and serves reads from that cache. Immediately after a
  write, the cache reflects the *requested* state only once the client's
  event confirms the clamped result — reads are eventually consistent and
  documented as such.

### 5.2 `reflex_xy` out-of-band API

Mirrors `reflex_xy.append(token, …)` exactly — callable from any event
handler, background task, or thread, with no component re-render and no
payload reship:

```python
reflex_xy.set_view(token, ranges={"x": (t0, t1)})
reflex_xy.reset_view(token)
reflex_xy.select(token, range=..., polygon=..., rows=...)
reflex_xy.clear_selection(token)
```

History navigation is deliberately absent from this surface. §4 stacks are
client-local, and clients in one room hold different stacks after local
gestures, so a broadcast back/forward *operation* would restore a different
snapshot on every client — no room convergence is possible, and a
server-initiated "back" has no originating stack to resolve against.
Back/Forward exist only where a single client resolves them locally (the
modebar and the §5.3 handle). An app that needs a server-driven "return to
X" flow composes it from what it already has: record the state it cares
about from `on_view_change`, restore it with `set_view` — an absolute patch,
which does converge room-wide.

Path: figure lock → one wire message (§8) → pushed room-wide as a `msg`
event on the `/_xy` namespace → every client in the room applies it through
the §3 mutation path with `source: "api"`. Multi-client semantics are
therefore identical to `append` and `registry.publish`: the room converges.
The token stays the only chart state Reflex holds; setting a view does not
touch the figure payload or version. Like `append`, a call holds the figure
lock only long enough to serialize one small message and performs no network
round-trip in the caller's thread, so it is safe from ordinary event
handlers as well as background tasks and threads; prefer a background task
for long programmatic sequences, as for any bulk work in a handler.

`on_view_change` handlers still fire for api-sourced changes (an app may
need to persist them) but carry `source: "api"`, so a state bridge that
writes what it reads can break the loop by filtering — no suppression
mechanism, no special cases.

### 5.3 Static tier

Zero-backend charts (static payload tier, standalone HTML) have no Python
side, but the client-side controller from §3 exists there too. The mount
exposes it as a JS handle on the chart root (`root.xy.applyState(patch)`,
`root.xy.state()`, `root.xy.back()`, `root.xy.forward()`), which is the
whole public JS control surface — one object, same patch semantics. This
handle and the modebar are the *only* history-navigation surfaces (§4). This is what makes "shareable
view" utilities possible on exported files without any server.

## 6. Per-axis gestures (#120)

PR #117 makes ranges, clamps, and events per-axis; what remains is a gesture
*scope*, not a new state model.

- Hovering an axis band — the tick-label strip plus a small gutter on the
  plot side — shows a resize cursor (`ew-resize` for x-axes, `ns-resize`
  for y-axes) when that axis is navigable.
- Wheel over the band zooms only that axis, anchored at the cursor's
  position along it. Drag along the band pans only that axis. Drag
  *across* it (perpendicular) box-zooms the axis span, mirroring the
  existing `select-x`/`select-y` one-axis brush shapes.
- The gesture feeds the §3 path with `axes: ["y2"]` (the hovered axis
  only); `pan_axes`, `zoom_axes`, `zoom_limits`, containment, and `bounds`
  govern it exactly as they govern plot-area gestures. An axis excluded
  from both `pan_axes` and `zoom_axes` shows no resize cursor.
- Secondary axes get their band on their own side, so `y` vs `y2` scoping
  is by geometry, with no modifier keys. `shift` remains the only modifier
  the renderer reads.
- History and events see nothing new: an axis-band gesture is an ordinary
  interaction with a narrower `axes` list.

## 7. Structured hover and framework-owned tooltips (#111)

Hover is the ephemeral tier: rich, evented, never durable.

### 7.1 The payload

```json
{
  "active": true,
  "cursor": {
    "px": [412.5, 118.0],
    "data": {"x": 1731.4, "y": 0.82, "y2": -1.37}
  },
  "points": [
    {"trace": "sensor A", "index": 1042, "row": {"x": 1731.0, "y": 0.81},
     "x_axis": "x", "y_axis": "y", "color": "rgb(31, 119, 180)"}
  ]
}
```

`cursor.px` is chart-root-relative pixels (what a framework needs to
position an element). `cursor.data` is keyed by **exact axis ID** with one
entry per declared axis — a chart-root pixel maps to a different data value
on each axis, so a bare `{x, y}` pair would be ambiguous the moment a chart
declares `y2`. Each point carries its `x_axis`/`y_axis` binding so a custom
tooltip can pick the right `cursor.data` entries for that point's trace.
`points` carries the resolved rows with series metadata. The
existing `xy:hover` two-stage behavior is preserved: the payload
re-dispatches with `exact: true` when the kernel's f64 pick reply lands, and
on static/standalone charts `points[].row` comes from browser-resident data
with no exact upgrade — the same honesty rule the LOD tiers follow.

### 7.2 Consumers

- `xy:hover` / `xy:leave` gain the payload under `detail` (existing `row`,
  `trace`, `index`, `view` keys remain — genuinely additive there).
- `reflex_xy` grows a **new** `on_hover` prop that receives the full
  payload. The existing `on_point_hover(row)` contract is untouched —
  handlers reading `row["x"]` keep working. Replacing `on_point_hover`'s
  argument was considered and rejected: nesting `row` inside a payload
  breaks every existing subscript access, so "keep a `row` key" is not
  compatibility. `on_point_hover` is documented as the narrow legacy form;
  new code uses `on_hover`.
- `xy.tooltip(render=…)`: the adapter finally honors it. `reflex_xy.chart`
  reads `chart.chrome_components()`, mounts the supplied Reflex component
  into an overlay that the client positions with the built-in tooltip's
  placement logic (flip-at-edges included), and pipes the §7.1 payload in as
  props. The built-in tooltip is suppressed while a custom renderer is
  mounted. Static charts get the same mount fed by the browser-resident
  payload, which removes the "static charts cannot use the backend-event
  workaround" gap from #111.

## 8. Wire and event additions

Client → kernel: nothing new. The PR #117 view events and existing
brush/select messages already report every commit.

Kernel/backend → client, added to the catalog in
[`wire-protocol.md`](wire-protocol.md) behind the existing version
handshake:

| Message | Content | Effect |
| --- | --- | --- |
| `state_patch` | one §2 document (plus `animate`, `history` flags) | apply through the §3 path, `source: "api"` |
| `view_nav` | `{"op": "reset", "axes": […]}` | navigation to home ranges |
| `selection_rows` | per-trace index buffers (binary attachments) | kernel-resolved mask, same buffers the selection path ships today; applies as a non-durable selection (§5.1) |

History back/forward have **no wire message**: stacks and their navigation
are client-local (§4, §5.2). `view_nav` carries only `reset`, which is
well-defined for every receiver because home ranges are client-known.

All three reuse the existing `msg` envelope in both transports (anywidget
comm and the `/_xy` socket.io namespace), so Reflex room broadcast and
notebook delivery need no new plumbing. Hover payloads (§7) ride the
existing hover/pick messages — no new message, larger detail.

## 9. Testing contract

Locked in before implementation, in the PR #117 fail-first style:

- **Round-trip:** for any reachable durable state, `apply(serialize(state))`
  is a no-op (exact f64 range equality, selection identity).
- **Clamp equivalence:** property test that a programmatic `state_patch` and
  the equivalent gesture sequence commit identical clamped ranges — the §3
  invariant, tested differentially.
- **History:** N gestures produce exactly N entries (coalescing by
  `interaction_id`); back restores exact pre-gesture ranges; linked
  applications push nothing; eviction at capacity; reset-then-back restores
  the pre-reset view.
- **Ordering:** `on_brush` before `on_select` holds for programmatic
  geometric selects.
- **Rows non-durability:** a rows-selection never enters the history stack,
  `view_state()` reports the `{"rows": true}` marker rather than indices,
  and Back after a rows-select restores the prior geometric state.
- **Hover compatibility:** `on_point_hover` still receives the bare row
  dict (subscript access probed); the payload ships only on `on_hover`.
- **Loop safety:** a state bridge that echoes `on_view_change` back into
  `set_view` converges (source filtering documented and probed).
- **Headless-Chromium probes:** axis-band wheel mutates only the hovered
  axis; Back button state tracks stack emptiness; custom tooltip component
  receives a payload with `cursor.px` on a static page.

## 10. What this unlocks (recorded, not promised)

Shareable view permalinks (`serialize` → URL fragment → `applyState` on the
static handle), server-driven guided tours in Reflex apps, cross-session
view restore, and "sync my dashboard to this incident window" flows — all
without new primitives.

## 11. Rollout

| Phase | Ships | Delivers |
| --- | --- | --- |
| 0 | PR #117 lands | per-axis ranges, clamps, semantic events (dependency) |
| 1 | §2 state object, §3 client controller, §5 Python + `reflex_xy` + static handle, §8 messages | #121 |
| 2 | §4 history, modebar Back/Forward, reset-as-navigation | #110 |
| 3 | §6 axis-band gestures | #120 |
| 4 | §7 hover payload + adapter tooltip mount | #111 |

Each phase updates [`../api/interaction.md`](../api/interaction.md) (and
`wire-protocol.md` for phase 1) in the same PR; this document then records
divergences rather than duplicating the shipped authority.

## 12. Implementation divergences (recorded per §11)

Shipped behavior that refines this design rather than following it verbatim:

- **View-event transport.** For `view_state()` to be event-fed without a
  registered callback, the client now ships `phase: "end"` view events
  unconditionally (one rAF-coalesced message per gesture); `"update"`
  streams stay gated on listener presence. Recorded in interaction.md §3 and
  wire-protocol.md §2 — a deliberate refinement of the pre-existing
  "listener presence" gate, costing one small message per gesture.
- **Reflex tooltip payload.** §7.2 says the payload is piped "as props".
  Reflex components are compiled ahead of time, so live per-frame props are
  not expressible; the mounted component is positioned by the client (built-in
  placement logic, built-in tooltip suppressed) and the payload reaches app
  code through the new `on_hover` event prop — Reflex state is the dynamic
  channel, which is the framework-native equivalent. `reflex_xy.chart` also
  accepts an explicit `tooltip=` component for live (token) sources, where
  `chrome_components()` is unreachable.
- **Axis-band drag classification.** "Drag along" vs "drag across" is decided
  once per gesture by the dominant displacement direction at the 3 px
  threshold, then locked; a pan-ineligible axis falls back to span-zoom and
  vice versa, so a band drag never dead-ends when only one capability is
  enabled.
- **The JS handle is universal.** `root.xy` (`applyState`/`state`/`back`/
  `forward`) is attached by every mount — notebook and Reflex included — not
  only the static tier; the §5.3 guarantee is the static tier's, the handle
  itself has one implementation.
- **History restores animate** (like reset); `prefers-reduced-motion` is
  respected as everywhere else.

## 13. Non-goals

- Animation/keyed-transition depth (ENG-10446) — `animate` stays the
  existing boolean.
- Touch pinch and keyboard viewport navigation — still deferred, as in
  PR #117.
- Cross-chart or cross-page shared history; link groups share views, not
  stacks.
- URL-router integration in `reflex_xy` — apps compose it from
  `on_view_change` + `set_view`.
- Persisting view state into the figure payload — the browser client stays
  the single owner of live view state.
