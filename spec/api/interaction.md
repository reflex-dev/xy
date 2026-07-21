# Interaction and events

This document is the authority on which browser interactions exist, which are
configurable, and what every event payload contains. Shipped in PRs #103/#105.
Where another spec describes an interaction as "free" or "always on" (e.g.
[chart-kind-contract.md](chart-kind-contract.md) §"What you get for free"),
this document governs.

Implementation: `python/xy/components.py` (`interaction_config`, `Chart`,
`FacetChart`), `python/xy/_figure.py` (`set_interaction`,
`_interaction_spec`), `python/xy/channel.py` (kernel-side dispatch),
`js/src/53_interaction.js` (gestures, modebar, view state machine),
`js/src/50_chartview.js` (flag resolution, link channel),
`python/reflex-xy/reflex_xy/` (Reflex event props).

## 1. How a switch resolves

`Figure.interaction` starts empty. `_interaction_spec` serializes only keys
that were explicitly set, so an unset switch is *absent* from the wire spec,
not `False`. The client resolves each read through
`_interactionFlag(name, fallback = false)`: an absent key takes the call
site's fallback; a present key is enabled only when it is exactly `true`.
The fallback therefore *is* the default, and it differs per switch.

`Chart` writes the interaction dict in three passes: chart-level keyword
arguments, then any `xy.interaction_config(...)` children in order, then a
final pass derived from the attached handlers (`components.py:2736-2740`).
That last pass is not a defaulting step — it overwrites. Passing `on_hover=`
together with `hover=False` yields `hover=True`.

## 2. `xy.interaction_config(...)`

`python/xy/components.py:2424`. All switches are `Optional[bool]` and default
to `None` (leave unset). "Default" below is the client-side behavior when the
switch is never set.

| Switch | Default | Effect when disabled |
| --- | --- | --- |
| `hover` | off | Suppresses the `xy:hover` and `xy:leave` DOM events. The tooltip still renders and the kernel `pick` round-trip still runs; only the event surface is gated. |
| `click` | off | `_click` returns immediately: no `xy:click` event and no `click` message to the kernel. |
| `select` | on | Suppresses the `xy:select` event and the `select_clear` message, removes the modebar Selection menu, and (with `brush`) disables shift-drag. |
| `brush` | on | Same conjunction: `canBrush = brush && select` (`53_interaction.js:115`) gates every selection drag and the modebar Selection menu. |
| `crosshair` | off | The two guide elements are created only when the flag is true, at init (`53_interaction.js:80`). Not togglable after mount. |
| `navigation` | on | Master gate on pointer-drag pan, wheel zoom, box-zoom drags, and dblclick reset. |
| `pan` | on | Plain-drag pan is ignored and the modebar Pan button is not built. Requires `navigation` as well. |
| `zoom` | on | Wheel zoom, box zoom, dblclick reset, and the modebar zoom menu are all ignored. Requires `navigation` as well. |
| `view_change` | off | Suppresses the `xy:view_change` event and the `view_change` kernel message. Linked-figure broadcast is independent (§4). |
| `link_group` | unset | See §4. |
| `link_axes` | `("x", "y")` | See §4. |

`link_select` is the one linking switch `interaction_config` does not expose:
the table above carries `link_group` and `link_axes`, and
`Figure.set_interaction` adds `link_select` (`_figure.py:257`). It is
reachable there and via `facet_chart(link_select=True)` (§6). Its default is
off.

Selection additionally requires a point-pickable trace: `canBrush` and the
modebar Selection menu both test `this._pickable`, which is true only when
some GPU trace has `pointPick` and is not an undrilled density tier.
Selection visuals are continuous across drill swaps (§34): the client
retains the last brush geometry in data space (`_lastBrush` — set on every
box/lasso send, adopted from enriched kernel replies that echo
`bounds`/`polygon`, cleared on `select_clear` and empty selections). When a
re-drill ships a new subset, `lodRestoreBrushMask` re-derives the mask
locally from the decoded window coordinates — the same containment test the
kernel runs for range predicates — so the highlight never blinks out while
the kernel's authoritative reply round-trips. Stale kernel masks (mismatched
`drill_seq`) are still dropped, as before.

Pickability is *dynamic* for density traces — drill-in to exact points grants
it, drill-out revokes it — so the Selection trigger is built whenever the
`brush`/`select` flags allow it and its visibility tracks `_pickable` live:
every recompute funnels through `ChartView._updatePickable()` (initial build,
kernel payload swaps, drill updates, and drill drop), which also calls
`_syncModebarSelect`. Losing pickability hides the trigger, closes its menu,
and reverts an active `select*` drag mode to `pan`; regaining it (including a
re-drill) shows the trigger again. Regression coverage:
`tests/test_modebar_select_drill.py`.

## 3. Event surface

Every event is a `CustomEvent` on the chart root (`bubbles`, `composed`),
named `xy:<name>`. `view` is `_eventView(source)` —
`{x0, x1, y0, y1, source}` in data coordinates.

| Event | Detail |
| --- | --- |
| `xy:hover` | `{row, trace, index, view}`; the kernel's exact-value reply re-dispatches with `exact: true`. |
| `xy:leave` | `{view}` with `source: "leave"`. |
| `xy:click` | `{x, y, view, row, trace, index}`; `row`/`trace`/`index` are `null` when the click hit no mark. |
| `xy:brush` | `{range: {x0, x1, y0, y1}, view}` for box/axis-range drags, or `{polygon: [[x, y], …], view}` for lasso. |
| `xy:select` | `{total, view}` — the resolved count after the kernel replies, or `total: 0` on clear. |
| `xy:view_change` | `{x0, x1, y0, y1, source}`, coalesced to one dispatch per animation frame. |

`source` on a view event is `"pan"` for drag-pan (`53_interaction.js:158`),
`"linked"` for a view applied from a link-group peer, and `"view"` for
everything else (wheel, box zoom, zoom in/out, reset, programmatic). The
kernel coerces it with `str(content.get("source", "view"))`.

Three further events report GL context lifecycle rather than user intent.
They carry no `view`, and no interaction switch gates them:

| Event | Detail |
| --- | --- |
| `xy:context_lost` | `{loss_count}` — the canvas lost its WebGL2 context (`50_chartview.js:693`). |
| `xy:context_restored` | `{loss_count, restore_count}` — a live frame is back (`:775`). |
| `xy:context_restore_failed` | `{loss_count, message}` — recovery gave up; the root is replaced with an error string (`:761`). |

Those nine are the whole `xy:` surface — every one goes through
`_dispatchChartEvent` (`50_chartview.js:451`), and there is no other
`CustomEvent` dispatch in `js/src/`.

Kernel-side callbacks (`python/xy/channel.py`), wired through
`Chart(on_hover=…, on_click=…, on_brush=…, on_select=…, on_view_change=…)`:

- `on_hover(row)` / `on_click(row)` — the picked row dict resolved by
  `fig.pick(trace, index, drill_seq)`. Not called when the pick misses.
- `on_view_change(view)` — `{"x0", "x1", "y0", "y1", "source"}`, after
  `normalize_window(..., require_area=False)` (`channel.py:216-233`).
- `on_brush(brush)` — `{"x0", "x1", "y0", "y1"}` for a range select, or
  `{"polygon": [[x, y], …]}` for a lasso.
- `on_select(Selection)` — canonical row indices per trace, not JSON.
  `on_brush` always fires before `on_select` for the same gesture; that
  ordering is an invariant and is tested.

Reflex props (`python/reflex-xy/reflex_xy/component.py:82-85`) are the live-mode
mirror: `on_point_hover(row)`, `on_point_click(row)`,
`on_select_end({total, x0, x1, y0, y1, polygon, cleared})`, and
`on_view_change(msg)`. `on_view_change` is resolved in the browser and never
reaches the kernel — `XYChart.jsx` intercepts the outgoing `view_change`
message and invokes the handler directly, because the socket namespace
registers no Python-side view callback.

## 4. Linking

`link_group` names a `BroadcastChannel` opened as `` `xy:${group}` ``
(`50_chartview.js:487`). Every view instance mints a random `_linkedSource`
id and drops messages carrying its own id, so a figure never re-applies its
own broadcast. Because the transport is `BroadcastChannel`, linking spans
tabs and windows of the same origin, and is a no-op where the constructor is
unavailable.

View messages carry the emitting figure's `_eventView` detail. A receiver
copies only the axes listed in `link_axes` (filtered to `x`/`y`; anything
else is dropped) onto its current view, rejects non-finite results, and
applies the result with `animate: false`, `source: "linked"`, and
`broadcast: false` so the update does not echo. A receiver with both `pan`
and `zoom` disabled ignores view messages entirely.

Broadcast is not gated on `view_change`: `_emitViewChange` runs whenever
either `view_change` is on *or* a link channel exists, and then gates the DOM
event and the kernel message separately. Linked figures therefore stay in
sync without emitting events.

Selection messages are gated on `link_select` at both ends. The payload is
one of `{clear: true}`, `{range: {x0, x1, y0, y1}}`, or `{polygon: [...]}`;
the receiver applies it locally with `dispatch: false`, so a linked selection
updates the peer's rendering without re-emitting its own events.

## 5. Gesture map

From `js/src/53_interaction.js`. `shift` is the only modifier key the
renderer reads anywhere in `js/src/`.

| Gesture | Action | Requires |
| --- | --- | --- |
| Plain drag | Pan (`dragMode === "pan"`) | `navigation` and `pan` |
| **Shift**-drag | Box select, overriding the current drag mode (`53_interaction.js:117`) | `brush`, `select`, `_pickable` |
| Drag in `select` / `select-lasso` / `select-x` / `select-y` mode | That selection shape | `brush`, `select`, `_pickable` |
| Drag in `zoom` mode | Box zoom | `navigation` and `zoom` |
| Wheel | Cursor-anchored zoom, factor `1.0015 ** deltaY`; `preventDefault` | `navigation` and `zoom` |
| Double click | Clear selection, animate to the home view | `navigation` and `zoom` |
| Click without drag | Pick; a drag past threshold sets `_ignoreNextClick` and swallows the click | `click` |
| Pointer down on a lasso vertex handle | Drag that vertex; re-runs the selection on release | an existing lasso |
| `ArrowRight`/`ArrowDown`, `ArrowLeft`/`ArrowUp`, `Home`, `End` | Keyboard traversal of pickable points in data order | pickable points |
| `Escape` | Dismiss the readout and invalidate the in-flight pick | — |

A box gesture counts as moved past 3 px in either axis; a lasso needs at
least 3 sampled vertices, sampled at 3 px spacing and capped at 2048. In
`select-x` the y bounds are replaced with the full current view and in
`select-y` the x bounds are, so those modes brush one axis.

The modebar exposes the same actions: Pan; a zoom menu with Zoom In (×0.5),
Zoom Out (×2), Box Zoom, and Reset View; and a selection menu with Box
Select, Lasso Select, X Range, and Y Range. Each menu is built only when its
flags allow it, and the whole bar is hidden when it does not fit inside the
plot box — hiding is a fit state, not a capability change, and wheel/drag
gestures keep working without it.

## 6. Facet-level linking

`facet_chart(..., link=…, link_select=…)` (`python/xy/components.py:4480`; normalization in `FacetChart.__init__`,
`components.py:3514`).
`link` accepts `True` (normalized to `"both"`), `False`/`None`, `"x"`, `"y"`,
or `"both"`; anything else raises. `link_select` is a strict bool.

`link` expands to `linked_dims`, and each linked dimension is forced into the
shared-domain set alongside `share_x`/`share_y` — a linked axis must start
from the same domain or the first interaction would make panels jump between
incomparable views. When `linked_dims` is non-empty *or* `link_select` is
set, every panel figure receives a common `link_group`: an existing panel
group id if one is present, otherwise `xy-facet-<8 hex>`. `link_axes` is set
to exactly `linked_dims`, so `link_select=True` with `link=None` produces an
empty `link_axes` — panels share selections and nothing else. `link_select`
is written straight into each panel's interaction dict.

## 7. Unconditional behavior

Not configurable through any switch: tooltip rendering and the kernel `pick`
round-trip on hover; keyboard point traversal and the live-region readout;
lasso vertex editing on an existing lasso; selection overlay rendering;
modebar presence (subject only to the fit check); and view clamping to axis
bounds. Everything in the §2 table is configurable; nothing else is.
