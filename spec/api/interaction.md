# Interaction and events

This document is the authority on which browser interactions exist, which are
configurable, and what every event payload contains. Selection, hover, click,
and crosshair shipped in PRs #103/#105. The per-axis pan/zoom, reset, and
view-event contract is specified in full by
[`../design/pan-and-zoom-configuration.md`](../design/pan-and-zoom-configuration.md)
and summarized here; where the two agree this document governs the surface and
that one governs the rationale. Where another spec describes an interaction as
"free" or "always on" (e.g. [chart-kind-contract.md](chart-kind-contract.md)
§"What you get for free"), this document governs.

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

The viewport keys that are not plain booleans — `default_drag_action` (a
string), `pan_axes`/`zoom_axes`/`reset_axes` (axis-ID tuples), and
`zoom_limits` (an axis-keyed magnification map) — serialize verbatim when set
and are absent otherwise; the client fills their defaults (all declared axes,
`"auto"`, `(1.0, None)`). Python validates them at chart construction, so a
malformed policy fails before it reaches the wire (§2.1).

`Chart` writes the interaction dict in three passes: chart-level keyword
arguments, then any `xy.interaction_config(...)` children in order, then a
final pass derived from the attached handlers (`components.py:2736-2740`).
That last pass is not a defaulting step — it overwrites. Passing `on_hover=`
together with `hover=False` yields `hover=True`.

## 2. `xy.interaction_config(...)`

`python/xy/components.py:2437`. The boolean switches below are `Optional[bool]`
and default to `None` (leave unset). "Default" is the client-side behavior when
the switch is never set. The non-boolean viewport keys — `default_drag_action`,
`pan_axes`, `zoom_axes`, `zoom_limits`, and `reset_axes` — are in §2.1.

| Switch | Default | Effect when disabled |
| --- | --- | --- |
| `hover` | off | Suppresses the `xy:hover` and `xy:leave` DOM events. The tooltip still renders and the kernel `pick` round-trip still runs; only the event surface is gated. |
| `click` | off | `_click` returns immediately: no `xy:click` event and no `click` message to the kernel. |
| `select` | on | Suppresses the `xy:select` event and the `select_clear` message, removes the modebar Selection menu, and (with `brush`) disables shift-drag. |
| `brush` | on | Same conjunction: `canBrush = brush && select` (`53_interaction.js:115`) gates every selection drag and the modebar Selection menu. |
| `crosshair` | off | The two guide elements are created only when the flag is true, at init (`53_interaction.js:80`). Not togglable after mount. |
| `navigation` | on | Master gate on pointer-drag pan, wheel zoom, box-zoom drags, dblclick reset, and every modebar viewport control. |
| `pan` | on | Plain-drag pan is ignored, the modebar Pan button is not built, and every zoom-enabled axis is contained (§2.2). Requires `navigation`. Pans `pan_axes` (§2.1). |
| `zoom` | on | Master zoom gate: wheel zoom, box zoom, and the modebar zoom menu are all ignored. Requires `navigation`. Zooms `zoom_axes` (§2.1). |
| `wheel_zoom` | on | Cursor-anchored wheel/trackpad zoom is ignored and the page keeps scrolling; box and button zoom are unaffected. Requires `navigation` and `zoom` (`53_interaction.js:271-273`). |
| `box_zoom` | on | Box-zoom drags and the modebar Box Zoom button are removed, and `default_drag_action="zoom"` has no usable drag tool. Requires `navigation` and `zoom` (`53_interaction.js:112-113`, `50_chartview.js:419`). |
| `zoom_buttons` | on | The modebar Zoom In (×0.5) / Zoom Out (×2) commands are removed; wheel and box zoom keep working. Requires `navigation` and `zoom` (`53_interaction.js:883`). |
| `double_click_reset` | on | Double-click no longer resets the view. The modebar Reset View button is unaffected. Requires `navigation` only — reset is independent of `zoom` (`53_interaction.js:283-284`). |
| `link_group` | unset | See §4. |
| `link_axes` | all declared axes | See §4. |

`link_select` is the one linking switch `interaction_config` does not expose:
the table above carries `link_group` and `link_axes`, and
`Figure.set_interaction` adds `link_select` (`_figure.py:257`). It is
reachable there and via `facet_chart(link_select=True)` (§6). Its default is
off.

Selection additionally requires a point-pickable trace: `canBrush` and the
modebar Selection menu both test `this._pickable`, which is true only when
some GPU trace has `pointPick` and is not an undrilled density tier.

### 2.1 Axis policy, drag mode, and zoom limits

These keys are not booleans. They scope the actions above to concrete axes and
bound how far zoom may travel. Python validates them at chart construction, so
an empty tuple, an unknown or undeclared axis ID, or a zoom-limit interval that
omits home magnification `1.0` fails before serialization. The full contract,
including per-source semantics and the shared clamp pipeline, is
[`../design/pan-and-zoom-configuration.md`](../design/pan-and-zoom-configuration.md).

| Key | Type | Default | Role |
| --- | --- | --- | --- |
| `default_drag_action` | `"auto" \| "none" \| "pan" \| "zoom" \| "select" \| "select-x" \| "select-y" \| "select-lasso"` | `"auto"` | Initial tool for an unmodified primary-button drag. `"auto"` resolves pan → box zoom → rectangular select → none. `"zoom"` means **box zoom for drag only**; it does not touch wheel or button zoom. The modebar can change the live tool without mutating this configured default. |
| `pan_axes` | axis-ID tuple | all declared axes | Concrete axis IDs a pan gesture may translate freely. An axis excluded here while zoom can navigate it is **contained** (§2.2). |
| `zoom_axes` | axis-ID tuple | all declared axes | Concrete axis IDs wheel, box, and button zoom may scale. Selecting `"y"` never implies `"y2"`. |
| `reset_axes` | axis-ID tuple | enabled `pan_axes` ∪ enabled `zoom_axes` | Axis IDs restored by reset. Resolved client-side; the modebar Reset button hides when it resolves empty. |
| `zoom_limits` | `(min, max)` pair, or axis-ID → pair map | `(1.0, None)` per zoom axis | Magnification bounds relative to each axis's home span (`magnification = home_span / current_span`). The default stops zoom-out at the home window. Each interval must contain `1.0`; `(None, None)` opts an axis out. A bare pair broadcasts to every `zoom_axes` entry; a map applies per axis and missing selected axes inherit `(1.0, None)`. Python normalizes both forms to an axis-keyed wire map. |

Axis policies are filters, not permissions: they never grant an action whose
capability switch is off, and a disabled capability may still carry a dormant
policy for reuse. Bounds set by `x_axis(bounds=…)` clamp position and maximum
span after `zoom_limits`, on every mutation path.

### 2.2 Containment of pan-locked axes

Cursor-anchored zoom is a scaling composed with a translation
(`Δcenter = span · (anchor − ½) · (1 − f)`), so merely excluding an axis from
the pan *gesture* would leave its position reachable through zoom: a zoom-in /
zoom-out chain at two cursor positions is an exact pan. Exclusion from pan
therefore means containment, not gesture removal.

An axis is **contained** when zoom navigation can change it but pan cannot:
`navigation` and `zoom` are enabled, the axis is in `zoom_axes`, and either
`pan` is off or the axis is outside `pan_axes`. A contained axis's window can
never extend past its home extents, on any mutation path — pan, wheel, box,
and button zoom, linked ranges, and programmatic updates share one clamp.
Inside that envelope the axis stays live: zoomed in, plain drag still slides
its window (containment bounds the motion instead of dropping the axis from
the gesture) and pins flush at the home extent; at home magnification it
cannot move at all. Consequently `zoom_limits` values that would allow
magnification below `1.0` cannot carry a contained axis past its home window.
Containment tightens the positional envelope only; an explicit
`x_axis(bounds=…)` narrower than home still wins, and axes outside
`zoom_axes` need no containment because nothing can change their span.

## 3. Event surface

Every event is a `CustomEvent` on the chart root (`bubbles`, `composed`),
named `xy:<name>`. `view` is `_eventView(source)` —
`{ranges: {axisId: [lo, hi]}, x0, x1, y0, y1, source}` in data coordinates. The
per-axis `ranges` map is canonical and covers every declared axis (including
independent secondary axes such as `y2`); `x0`/`x1`/`y0`/`y1` are compatibility
aliases for `ranges.x`/`ranges.y` (`50_chartview.js`, `_eventView`).

| Event | Detail |
| --- | --- |
| `xy:hover` | `{row, trace, index, view}`; the kernel's exact-value reply re-dispatches with `exact: true`. |
| `xy:leave` | `{view}` with `source: "leave"`. |
| `xy:click` | `{x, y, view, row, trace, index}`; `row`/`trace`/`index` are `null` when the click hit no mark. |
| `xy:brush` | `{range: {x0, x1, y0, y1}, view}` for box/axis-range drags, or `{polygon: [[x, y], …], view}` for lasso. |
| `xy:select` | `{total, view}` — the resolved count after the kernel replies, or `total: 0` on clear. |
| `xy:view_change` | `{ranges, source, axes, phase, interaction_id}` plus `x0`/`x1`/`y0`/`y1` aliases, coalesced to one dispatch per animation frame. Fields explained below. |

A view event carries four fields beyond `ranges`/aliases. `source` names the
input that caused the change — exactly one of `pan_drag`, `wheel_zoom`,
`box_zoom`, `zoom_in`, `zoom_out`, `reset`, `linked`, or `programmatic`. `axes`
lists only the axis IDs that actually changed after clamping, so a one-axis
zoom on a dual-axis chart reports one ID. `phase` is `update` during a
continuous gesture and `end` on its final frame (`start` is reserved but not
currently emitted); discrete commands — zoom in/out, reset, box zoom,
programmatic — emit `end` only. `interaction_id` is a monotonic id shared by
every event of one continuous gesture. The kernel coerces `source` and `phase`
with `str(...)`, defaulting to `"view"`/`"end"` when absent
(`channel.py:246-253`).

Local DOM `xy:view_change` events are always dispatched. Notebook and Reflex
transport of the same payload is gated on *listener presence*, not a switch:
the kernel handler returns immediately unless an `on_view_change` callback is
registered (`channel.py:218`), and the anywidget path ships view events only
when Python sets the derived `_transport_view_change` flag — which it does iff a
callback exists (`widget.py:83-87`). There is no public `view_change`
configuration flag; linked-figure broadcast is separate again (§4).

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
- `on_view_change(view)` — `{"ranges", "source", "axes", "phase",
  "interaction_id"}`, plus `"x0"/"x1"/"y0"/"y1"` aliases when `x`/`y` are
  present. A legacy `{x0, x1, y0, y1}` message with no `ranges` is still
  accepted and normalized into a `ranges` map (`channel.py:217-258`). The
  handler is a no-op unless a callback is registered.
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

View messages carry the emitting figure's `_eventView` detail (the full
`ranges` map). A receiver copies only the axis IDs in its own `link_axes` —
resolved against *declared* axes, so a secondary `y2` links when both peers
declare it and any absent or non-matching ID is left alone — onto its current
view, rejects non-finite results, clamps to its own bounds, and applies the
result with `animate: false`, `source: "linked"`, and `broadcast: false` so the
update does not echo (`50_chartview.js:591-609`). Outgoing axes are the mirror:
`actually-changed ∩ link_axes`. Applying a linked view does **not** consult
local `navigation`/`pan`/`zoom`, so a read-only chart (`navigation=False`) still
follows its link group — the mechanism behind an overview-plus-linked-detail
pairing.

Broadcast has no dedicated switch. `_emitViewChange` runs on every committed
view change: it always dispatches the local DOM event, sends kernel/Reflex
transport only when a listener is registered (§3), and calls
`_broadcastLinkedView` when a link channel exists. Linked figures therefore
stay in sync whether or not anything listens for view events.

Selection messages are gated on `link_select` at both ends. The payload is
one of `{clear: true}`, `{range: {x0, x1, y0, y1}}`, or `{polygon: [...]}`;
the receiver applies it locally with `dispatch: false`, so a linked selection
updates the peer's rendering without re-emitting its own events.

## 5. Gesture map

From `js/src/53_interaction.js`. `shift` is the only modifier key the
renderer reads anywhere in `js/src/`.

| Gesture | Action | Requires |
| --- | --- | --- |
| Plain drag | The resolved drag mode — pan by default (`default_drag_action`, §2.1) | mode-dependent; pan needs `navigation` and `pan` |
| **Shift**-drag | Box select, overriding the current drag mode (`53_interaction.js:117`) | `brush`, `select`, `_pickable` |
| Drag in `select` / `select-lasso` / `select-x` / `select-y` mode | That selection shape | `brush`, `select`, `_pickable` |
| Drag in `zoom` mode | Box zoom, fitting `zoom_axes` on release | `navigation`, `zoom`, and `box_zoom` |
| Wheel | Cursor-anchored zoom of `zoom_axes`, factor `1.0015 ** deltaY`; `preventDefault` | `navigation`, `zoom`, and `wheel_zoom` |
| Double click | Reset `reset_axes` to home (animated); does **not** clear selection | `navigation` and `double_click_reset` |
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
bounds. Everything in the §2 and §2.1 tables is configurable; nothing else is.
