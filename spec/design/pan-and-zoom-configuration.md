# Pan and Zoom Configuration

**Status:** implemented. The public Python API, wire format, browser mutation
pipeline, linked views, semantic events, Reflex transport, and examples described
here ship together. Touch pinch and dedicated keyboard viewport navigation remain
the explicitly deferred follow-ups in section 22.

**Audience:** XY maintainers, adapter authors, and application developers who need
predictable viewport behavior across standalone HTML, notebooks, and Reflex apps.

## 1. Decision summary

Viewport navigation is five independent concerns:

1. **Master capability** — whether local input may change the viewport.
2. **Action capability** — whether pan, zoom, and reset are available.
3. **Affected axes** — which concrete axis IDs each action may change.
4. **Input source** — drag, wheel/trackpad, box, toolbar, or double-click.
5. **Coordination** — bounds, events, linked charts, and programmatic updates.

The target Python API stays flat and declarative:

```python
import xy

chart = xy.histogram_chart(
    xy.hist(latency_ms, bins=120),
    xy.x_axis(label="latency (ms)", bounds="data"),
    xy.y_axis(label="requests"),
    xy.interaction_config(
        navigation=True,
        default_drag_action="pan",
        pan=True,
        pan_axes=("x",),
        zoom=True,
        zoom_axes=("x",),
        wheel_zoom=True,
        box_zoom=True,
        zoom_buttons=True,
        double_click_reset=True,
    ),
)
```

These defaults preserve the established gesture model except for one deliberate
constraint: every zoom-enabled axis stops at its original home span when zooming out.

## 2. Goals

- Make both-axis, x-only, y-only, and disabled navigation concise.
- Apply one axis policy consistently to every source of the same action.
- Keep pan, zoom, reset, selection, hover, and linking independent.
- Preserve smooth client-local interaction without a Python round trip per frame.
- Emit stable semantic events for notebooks and Reflex applications.
- Respect linear, time, log, categorical, and reversed axes.
- Clamp every viewport mutation to optional hard axis bounds.
- Keep standalone, notebook, and Reflex behavior equivalent.
- Preserve existing charts when new options are omitted.

## 3. Non-goals

- A reactive state system inside XY.
- Sending every pointer or wheel frame through Reflex state.
- Arbitrary transforms, rotation, or 3D cameras.
- Per-mark viewport policies inside one panel.
- Public wheel acceleration/easing controls in the first version.
- Full navigation history. Reset-to-home is in scope; undo/redo is later.

## 4. Terminology

| Term | Meaning |
| --- | --- |
| **home view** | Initial range for every declared axis, keyed by axis ID. |
| **current view** | Current browser range for every declared axis, keyed by axis ID. |
| **domain** | Initial visible axis range. It defines home, not a hard limit. |
| **bounds** | Optional hard navigation envelope. |
| **action** | Semantic operation: pan, zoom, or reset. |
| **source** | Input that initiated an action: drag, wheel, box, toolbar, double-click, link, or application code. |
| **axis policy** | Concrete axis IDs an action may mutate, such as `x`, `y`, or `y2`. |
| **drag mode** | Operation assigned to an unmodified primary-button drag. |
| **view event** | Small semantic payload describing a viewport change. |

Axis policies use the same IDs as `x_axis(id=...)`, `y_axis(id=...)`, and mark
bindings. The primary IDs are `"x"` and `"y"`; secondary axes may be `"x2"`,
`"y2"`, or another declared ID. There are no wildcard dimension selectors.

## 5. Configuration model

### 5.1 Public surface

```python
xy.interaction_config(
    navigation: bool | None = None,
    default_drag_action: Literal[
        "auto", "none", "pan", "zoom", "select", "select-x", "select-y", "select-lasso"
    ] | None = None,
    pan: bool | None = None,
    pan_axes: tuple[str, ...] | None = None,
    zoom: bool | None = None,
    zoom_axes: tuple[str, ...] | None = None,
    zoom_limits: (
        tuple[float | None, float | None]
        | Mapping[str, tuple[float | None, float | None]]
        | None
    ) = None,
    wheel_zoom: bool | None = None,
    box_zoom: bool | None = None,
    zoom_buttons: bool | None = None,
    double_click_reset: bool | None = None,
    reset_axes: tuple[str, ...] | None = None,
    link_group: str | None = None,
    link_axes: tuple[str, ...] | None = None,
)
```

The same keywords remain available directly on chart factories for small cases.
`interaction_config()` is preferred when more than one behavior changes because it
keeps policy in one visible node.

### 5.2 Resolved defaults

| Field | Default | Meaning |
| --- | --- | --- |
| `navigation` | `True` | Local viewport changes are allowed. |
| `default_drag_action` | `"auto"` | Choose pan when available, then another enabled drag tool. |
| `pan` | `True` | Drag panning is available. |
| `pan_axes` | all declared axes | Pan every axis unless explicitly narrowed. A narrowed-out zoom axis is contained to its home window (§7.1). |
| `zoom` | `True` | Zoom actions are available. |
| `zoom_axes` | all declared axes | Zoom every axis unless explicitly narrowed. |
| `zoom_limits` | `(1.0, None)` on every axis in `zoom_axes` | Do not zoom out past home; allow zoom-in to bounds/precision. |
| `wheel_zoom` | `True` | Wheel and trackpad zoom. |
| `box_zoom` | `True` | Box zoom is available as a drag tool. |
| `zoom_buttons` | `True` | Toolbar zoom in/out are available. |
| `double_click_reset` | `True` | Double-click invokes reset. |
| `reset_axes` | enabled `pan_axes` union enabled `zoom_axes` | Restore every axis users can move. |
| `link_axes` | all declared axes | Link matching axis IDs unless explicitly narrowed. |

For a standard chart with primary x and y axes, omitted zoom configuration resolves
to `{"x": (1.0, None), "y": (1.0, None)}`. A declared `y2` also receives
`(1.0, None)` when it participates in `zoom_axes`.

Unspecified keys should remain absent from the payload. The client resolves defaults,
keeping exports compact and compatibility explicit.

### 5.3 Precedence

1. `navigation=False` disables local pan, zoom, reset, and matching modebar
   controls. It does not disable hover, click, or selection.
2. `pan=False` disables every pan source regardless of `pan_axes`; every
   enabled zoom axis is then contained (§7.1).
3. `zoom=False` disables wheel, box, and button zoom regardless of their switches.
4. A source-specific `False` disables only that source.
5. Axis policy filters the action's candidate ranges.
6. `zoom_limits` clamps each participating axis's candidate span relative to home.
7. Each axis's positional envelope — `bounds`, tightened to the home window on
   contained axes — clamps its filtered position and maximum available span.
8. `link_axes` filters broadcast axis IDs; it never grants local permission.

Disabled capabilities may carry dormant axis/source settings. This supports reusable
policies; the capability flag wins and no validation error is raised.

### 5.4 Validation

- Axis tuples contain one or more declared axis IDs.
- Empty tuples and unknown IDs fail at chart construction. For example, selecting
  `"y2"` requires a declared `y_axis(id="y2")`.
- Duplicates normalize in first-seen order.
- An unavailable explicit `default_drag_action` fails at chart construction.
- `default_drag_action="auto"` resolves to pan, box zoom, a selection mode, or no drag tool.
- Bounds are increasing data-space pairs, including on reversed axes.
- Log domains and bounds are positive.
- Zoom-limit endpoints are positive finite numbers or `None`, the lower endpoint is
  not greater than the upper endpoint, and the interval contains home magnification
  `1.0`.
- A `zoom_limits` mapping contains only declared axis IDs. Missing selected IDs inherit
  the default `(1.0, None)` limit; use `(None, None)` to opt an axis out explicitly.
- Source switches accept strict booleans only.

Python should fail early. The client still treats malformed external payloads
defensively and falls back to safe defaults.

### 5.5 What `default_drag_action` controls

`default_drag_action` selects the initial tool for an unmodified primary-button drag inside the
plot. It does not enable a capability, choose axes, configure the wheel, or perform an
action immediately.

| `default_drag_action` | Plain-drag behavior | Required capability |
| --- | --- | --- |
| `"auto"` | Resolve the first usable tool from the priority below. | None |
| `"none"` | Do nothing on plain drag. Wheel, click, and toolbar actions may still work. | None |
| `"pan"` | Translate the ranges in `pan_axes`. | `navigation and pan` |
| `"zoom"` | Draw a rectangle and box-zoom `zoom_axes` on release. | `navigation and zoom and box_zoom` |
| `"select"` | Rectangular x/y selection. | `select and brush` plus pickable data |
| `"select-x"` | Select an x interval across the full visible y range. | `select and brush` plus pickable data |
| `"select-y"` | Select a y interval across the full visible x range. | `select and brush` plus pickable data |
| `"select-lasso"` | Draw a free-form polygon selection. | `select and brush` plus pickable data |

`"zoom"` means **box zoom for drag only**. It does not control wheel zoom or the
Zoom In/Out toolbar commands. Those remain governed by `wheel_zoom` and
`zoom_buttons`.

`"auto"` resolves once at mount and whenever configuration invalidates the active
tool:

1. `"pan"` when local pan is available;
2. `"zoom"` when box zoom is available;
3. `"select"` when rectangular selection is available;
4. `"none"` otherwise.

An explicit mode is a request, not a preference. If its required capability is
disabled, chart construction fails rather than silently choosing another tool. Use
`"auto"` when a reusable configuration should adapt to capability changes.

Examples:

```python
# Drag pans x; wheel still zooms x.
xy.interaction_config(
    default_drag_action="pan",
    pan_axes=("x",),
    zoom_axes=("x",),
)

# Drag box-zooms; panning remains available from the modebar.
xy.interaction_config(
    default_drag_action="zoom",
    pan=True,
    box_zoom=True,
)

# No plain-drag gesture; keep cursor-anchored wheel zoom.
xy.interaction_config(
    default_drag_action="none",
    wheel_zoom=True,
)
```

## 6. Shared mutation pipeline

Every action follows one path:

```text
input -> capability check -> action transform -> axis filter -> zoom-limit clamp
      -> positional clamp (hard bounds, tightened to home containment on
         pan-locked axes)
      -> render -> LOD request -> event -> linked-view broadcast
```

The action computes candidate ranges keyed by axis ID. Filtering discards candidates
for non-participating axes. Clamping happens afterward, so changing `x` cannot perturb
`y`, and changing `y` cannot perturb `y2`.

If the clamped result equals the current view, XY redraws nothing, requests no LOD,
emits no event, and broadcasts no update.

## 7. Action semantics

### 7.1 Drag pan

- Primary drag pans when the resolved drag mode is `"pan"`.
- Pointer displacement is converted in axis scale coordinates.
- `pan_axes` chooses the freely panning axis IDs.
- Linear/time/category axes translate additively in scale coordinates.
- Log axes translate multiplicatively because their scale coordinate is logarithmic.
- Reversed axes preserve direction.
- A hard bound stops motion on that axis without blocking another axis.
- Pointer capture keeps a drag coherent outside the plot.

An axis zoom may navigate but pan may not is **contained**: cursor-anchored
zoom is a scaling composed with a translation, so a zoom-in/zoom-out chain at
two cursor positions would otherwise pan the "locked" axis exactly. The
positional clamp therefore keeps a contained axis's window inside its home
extents on every mutation path. The drag still includes it — zoomed in, its
window slides within home and pins flush at the extent — while at home
magnification the window fills the envelope and cannot move (see the API
spec, `interaction.md` §2.2).

Horizontal pointer movement applies independently to selected x-oriented axes;
vertical movement applies independently to selected y-oriented axes. For
`pan_axes=("x", "y2")`, x and y2 move through their own scales while primary y —
contained, because the default `zoom_axes` still lets zoom navigate it — never
leaves its home extents and stays bit-for-bit unchanged at home magnification.

### 7.2 Wheel and trackpad zoom

- Wheel zoom is cursor-anchored on every axis in `zoom_axes`.
- The pointer fraction is converted through each selected axis's own scale.
- Non-participating axes stay unchanged.
- On contained axes (§7.1) the positional clamp keeps the zoomed window inside
  home extents, so cursor anchoring cannot relocate a pan-locked axis.
- Deltas accumulate and apply at most once per animation frame.
- XY calls `preventDefault()` only inside the plot while wheel zoom is enabled.
  Otherwise the page remains scrollable.
- A precision floor prevents ranges smaller than the renderer can represent.
- Sensitivity is not public until cross-device normalization is stable.

### 7.3 Toolbar zoom

- Zoom In and Zoom Out are center-anchored and use `zoom_axes`.
- The percentage reports magnification, not pan offset.
- For one-axis zoom it reports that axis. With several axes, the compact label reports
  the first configured axis. Its accessible description lists per-axis percentages
  when bounds cause them to diverge.
- `zoom_buttons=False` removes the commands without disabling wheel or box zoom.
- Hiding the modebar changes presentation only; gestures remain enabled.

### 7.4 Box zoom

- Requires `navigation`, `zoom`, and `box_zoom`.
- `default_drag_action="zoom"` makes box zoom the active unmodified primary-drag tool.
- Pointer down records the starting screen/data coordinates and shows the zoom band.
- Pointer move updates the band without changing the viewport.
- Pointer release commits only after the drag exceeds the click threshold. A click or
  tiny drag removes the band without zooming, so normal click handling may continue.
- The rectangle is drawn in screen space, but only `zoom_axes` are fitted.
- Each selected x-oriented axis maps the rectangle's horizontal edges through its
  own scale; each selected y-oriented axis maps the vertical edges through its scale.
- When only x-oriented axes participate, rectangle height is decorative. When only
  y-oriented axes participate, width is decorative.
- Non-participating ranges remain exactly unchanged.
- Degeneracy is checked only on participating axes.
- `zoom_limits` then clamp magnification around the box center, followed by the
  positional envelope (hard bounds, tightened to home containment on pan-locked
  axes — §7.1). A box implying more than the maximum allowed magnification is
  expanded to the minimum permitted span rather than over-zooming.
- The final range is clamped and animated unless reduced motion is active.
- Pointer cancel or Escape removes the band and preserves the current view.
- After a completed box zoom, the active drag mode remains `"zoom"` for the next
  drag. The user may switch to Pan or a selection tool through the modebar.

Because the dragged rectangle is contained by the current plot, box zoom normally
zooms in. Zoom Out remains a wheel or toolbar action. `zoom_limits=(1.0, None)` still
guarantees that no edge case produces a span larger than home.

### 7.5 Zoom extent limits

`zoom` answers whether zoom is enabled. `zoom_limits` answers how far it may go.
Limits use magnification relative to each axis's home range, measured in that axis's
scale coordinates:

```text
magnification = home span / current span
```

Home is `1.0`; zooming in produces values greater than `1.0`, and zooming out
produces values below `1.0`. The tuple is `(minimum_magnification,
maximum_magnification)`; `None` leaves that side unconstrained except for hard bounds
and the renderer precision floor. The resolved default is `(1.0, None)` for every
axis in `zoom_axes`—on a normal chart, both x and y stop at their original spans.
On a contained axis (§7.1) the home envelope also caps the effective minimum
magnification at `1.0`: a window that would exceed home pins to it exactly, so
limits permitting magnification below `1.0` cannot carry the axis past its home
window.

```python
# Explicit form of the default: never zoom out beyond the original window.
xy.interaction_config(
    zoom_axes=("x",),
    zoom_limits=(1.0, None),
)

# Allow 4× zoom-out and at most 64× zoom-in on every selected axis.
xy.interaction_config(
    zoom_limits=(0.25, 64.0),
)

# Set different limits for independently scaled axes.
xy.interaction_config(
    zoom_axes=("x", "y2"),
    zoom_limits={
        "x": (1.0, None),
        "y2": (0.5, 32.0),
    },
)
```

A tuple applies to every axis in `zoom_axes`. A mapping applies per declared axis ID;
selected axes missing from the mapping inherit `(1.0, None)`. Use
`{"y2": (None, None)}` when a specific axis should have no home-relative limit.
Python normalizes both forms into an axis-keyed wire map.

Every zoom source uses the same limits:

- wheel zoom preserves the pointer anchor while clamping the requested span;
- toolbar zoom preserves the center anchor;
- box zoom preserves the selected box center when its span is smaller than the
  maximum allowed magnification;
- linked and programmatic ranges clamp to the receiver's limits so they cannot violate
  local product constraints.

Pan is unaffected because it preserves span. Reset returns to magnification `1.0`,
which is why every explicit interval must contain `1.0`. Hard axis `bounds` still
apply after zoom limits. For example, `zoom_limits=(0.25, None)` permits a theoretical
4× zoom-out, but narrower hard bounds may stop it sooner.

When a multi-axis action reaches a limit on one axis, that axis clamps independently;
other selected axes may continue. The event's `axes` field includes only ranges that
actually changed.

### 7.6 Reset

Reset is a navigation action, not a kind of zoom.

- Toolbar Reset View and double-click use `reset_axes`.
- `reset_axes=None` resolves to the union of axes enabled pan and zoom can mutate.
- Participating axes copy their home ranges; others keep current ranges.
- The result clamps to current bounds.
- View reset and selection clear are separate commands.

Reset never clears selection. Selection clearing remains an independent selection
command, so resetting a viewport cannot silently discard a user's selected rows.

### 7.7 Programmatic updates

Adapters may apply a view from application state or a linked peer. These updates use
the same zoom limits, bounds, scale validation, and home containment (§7.1) as
gestures — one clamped mutation path.

Programmatic updates are not filtered by `pan_axes` or `zoom_axes`; those select
which axes user gestures may touch. Containment is a clamp, not a filter, so a
contained axis accepts programmatic and linked updates but keeps them inside its
home extents. `navigation=False` blocks local input, disables containment (no
gesture can navigate anything), and does not block application-driven view
updates, allowing a read-only chart to follow a dashboard controller freely.

## 8. Drag-mode runtime state and gesture conflicts

`default_drag_action` initializes browser-local `active_drag_action`. One unmodified
primary-button drag behavior is active at a time. Selecting Pan, Box Zoom, or a
selection tool in the modebar changes `active_drag_action`; it does not mutate the
Python configuration or enable/disable capabilities. Remounting the chart restores
the configured initial mode. A future dynamic prop update to `default_drag_action` explicitly
replaces the active mode.

| Input | Default behavior |
| --- | --- |
| Primary drag | Resolved drag mode; pan by default. |
| Shift + primary drag | Box select when selection/brush are enabled. |
| Wheel/trackpad | Zoom when enabled, independent of drag mode. |
| Double-click | Reset when enabled. |
| Toolbar | Execute the named enabled action. |
| Escape | Cancel active drag/band or close transient readout UI. |

Shift-drag selection is a temporary override when selection is enabled. Releasing or
canceling the gesture returns to the previous active mode; it does not change the
modebar's pressed tool. Wheel zoom is likewise independent of active drag mode.

Selection owns its own x/y modes and does not reuse pan/zoom axis policy. A completed
mode change emits no view event because the viewport did not change. Modifier
remapping is deferred because platform shortcuts and assistive technologies require a
single coordinated keymap design.

## 9. Domain, bounds, scales, and multiple axes

```python
xy.x_axis(
    domain=(20, 80),   # initial/home view
    bounds=(0, 100),   # hard navigation envelope
)
```

Domain is never a hard limit. `bounds="data"` resolves the canonical data range in
Python independently of an explicit domain.

`bounds` and `zoom_limits` are complementary:

- `bounds` constrains where a range may be positioned and therefore affects pan,
  zoom, linked, and programmatic updates;
- `zoom_limits` constrains range span relative to home and does not restrict pan;
- `zoom_limits=(1.0, None)` prevents zooming out beyond home while still allowing a
  zoomed-in window to pan anywhere permitted by `bounds`.

Setting `bounds` equal to `domain` is stronger: it keeps every viewport inside the
original envelope, restricting both zoom-out and pan. Applications should choose that
when data outside the home window must never be exposed.

Pan, zoom, precision checks, and clamping operate in each axis's scale coordinates:
numeric for linear/time, logarithmic for log axes, and stable numeric positions for
categories. Values return to data space after the transform. This preserves
multiplicative log behavior and reversed range direction.

### 9.1 Two y axes

Every declared axis owns an independent home range, current range, scale, and bounds:

```python
chart = xy.chart(
    xy.line(time, temperature, y_axis="y", name="temperature"),
    xy.line(time, pressure, y_axis="y2", name="pressure"),
    xy.x_axis(id="x", label="time"),
    xy.y_axis(id="y", label="temperature (°C)", side="left"),
    xy.y_axis(id="y2", label="pressure (kPa)", side="right"),
    xy.interaction_config(
        pan_axes=("x", "y2"),
        zoom_axes=("x", "y2"),
    ),
)
```

In this example:

- x pans and zooms;
- y2 pans and zooms through the pressure scale;
- primary y remains unchanged;
- marks use the current range of the axis named by their `x_axis`/`y_axis` binding;
- ticks, bounds, log/reverse behavior, and reset are evaluated independently per ID.

To change both y axes, list both: `zoom_axes=("y", "y2")`. Omitting
`zoom_axes` selects all declared axes in declaration order. Selecting `"y"` never
implicitly selects `"y2"`; explicit IDs avoid surprising coupling between unrelated
units.

For a wheel gesture, the same vertical pointer fraction anchors both selected y axes,
but each computes its data range through its own scale. For box zoom, the same screen
rectangle maps independently into each selected scale. A bound may clamp one axis
without preventing another from completing the action.

### 9.2 View representation

Supporting independent y and y2 navigation requires the browser to replace its
single `{x0, x1, y0, y1}` viewport with a range map:

```json
{
  "ranges": {
    "x": [0.0, 24.0],
    "y": [-10.0, 50.0],
    "y2": [95.0, 105.0]
  }
}
```

The renderer resolves each mark against its bound axis ID. Primary x/y scalar fields
may remain as transition aliases, but they are not the canonical multi-axis model.

## 10. Modebar behavior

| Control | Visible/enabled when |
| --- | --- |
| Pan tool | `navigation and pan` |
| Box Zoom | `navigation and zoom and box_zoom` |
| Zoom In/Out | `navigation and zoom and zoom_buttons` |
| Reset View | `navigation` and resolved `reset_axes` is non-empty |
| Selection tools | Existing select/brush capability permits them |

If a dynamic update makes the active tool unavailable, the client resolves `"auto"`
again and updates pressed state and cursor in one transaction.

Accessible names should identify constrained actions when useful: “Zoom in on x
axis”, “Pan x and y axes”, or “Reset x axis”. Icons need not change.

## 11. View state and events

### 11.1 Ownership

The browser owns transient viewport state. Reflex or notebook Python receives
semantic events; it does not render every wheel frame back into the chart. Application
state may persist the last committed view. Feeding it back must be idempotent and must
not create an event loop.

### 11.2 Payload

`on_view_change` and `xy:view_change` converge on this shape:

```json
{
  "ranges": {
    "x": [210.0, 480.0],
    "y": [0.0, 16995.0],
    "y2": [95.0, 105.0]
  },
  "source": "wheel_zoom",
  "axes": ["x", "y2"],
  "phase": "update",
  "interaction_id": 42
}
```

Sources are `pan_drag`, `wheel_zoom`, `box_zoom`, `zoom_in`, `zoom_out`,
`reset`, `linked`, and `programmatic`. `axes` contains axis IDs actually changed
after clamping. `phase` is `start`, `update`, or `end`; discrete commands may emit
only `end`. One `interaction_id` groups a continuous gesture.

Primary-axis `x0`, `x1`, `y0`, and `y1` remain compatibility aliases for
`ranges.x` and `ranges.y`. New consumers use `ranges`.

There is no `view_change` configuration switch. Local DOM events are always
available, and notebook/Reflex transport subscribes only when the user supplies an
`on_view_change` callback. Listener presence, rather than a second behavior flag,
controls transport work.

### 11.3 Cadence

- DOM events may emit once per animation frame.
- Python/Reflex events are coalesced.
- Continuous gestures always deliver a final `end` event.
- LOD and view-event throttles may differ.
- Linked peers receive browser-local updates without a Python round trip.

## 12. Linked charts

Action axes and link axes answer different questions:

- `pan_axes` / `zoom_axes`: what this chart may change locally.
- `link_axes`: what this chart may broadcast and accept.

Outgoing axes are `actually changed axes intersect link_axes`. Incoming updates copy
only matching declared IDs in `link_axes`, preserve other local axes, clamp to
receiver limits (bounds and, on contained axes, the home window — §7.7), and never
rebroadcast. An absent ID is ignored. Linking axes with different IDs requires an
explicit mapping API in a later proposal.

Different policies in one group are valid. An overview can navigate x while a detail
chart disables local navigation but follows linked x. Receivers may also have
different bounds and clamp independently.

## 13. Reflex integration

The adapter uses the same semantic policy instead of inventing another gesture
vocabulary:

```python
class Dashboard(rx.State):
    visible_ranges: dict[str, list[float]] = {}

    @rx.event
    def remember_view(self, view: dict[str, object]):
        if view.get("phase") == "end":
            self.visible_ranges = {
                axis_id: [float(bounds[0]), float(bounds[1])]
                for axis_id, bounds in view["ranges"].items()
            }


chart = xy.line_chart(
    xy.line(timestamps, values),
    xy.interaction_config(
        pan_axes=("x",),
        zoom_axes=("x",),
    ),
)

reflex_xy.chart(chart, on_view_change=Dashboard.remember_view)
```

Large arrays never enter Reflex state. The small view event may be stored while the
browser continues to navigate locally.

## 14. Accessibility and devices

- Modebar actions are keyboard reachable with semantic names, state, and focus.
- Reduced-motion users receive immediate changes instead of easing.
- Forced-colors mode keeps zoom bands and focus visible.
- Disabled navigation never traps wheel input.
- Escape cancels an in-progress gesture without committing.
- Pointer targets preserve the modebar hit-area contract.

Keyboard viewport navigation is a follow-up: arrows pan through `pan_axes`, `+`/`-`
zoom through `zoom_axes`, and Home resets. It must activate only in an explicit plot
navigation mode so it does not replace current point-exploration keys.

Touch needs an implementation pass. The target mapping is one-finger pan and
two-finger pinch zoom, filtered by the same axis policies. XY must not claim touch
parity before pinch zoom is tested.

## 15. Performance requirements

- Input handlers do no Python work.
- Wheel deltas and linked updates coalesce to one mutation per animation frame.
- Pan draws resident geometry immediately and refines LOD separately.
- Sequence numbers invalidate stale viewport replies.
- Continuous input has a maximum wait so refinement is not starved.
- Animation retargets rather than queues.
- Axis filtering and bounds clamping allocate no data-sized objects.
- Event coalescing never drops the final committed range.

## 16. Wire contract

```json
{
  "interaction": {
    "navigation": true,
    "default_drag_action": "pan",
    "pan": true,
    "pan_axes": ["x", "y2"],
    "zoom": true,
    "zoom_axes": ["x", "y2"],
    "zoom_limits": {
      "x": [1.0, null],
      "y2": [0.5, 32.0]
    },
    "wheel_zoom": true,
    "box_zoom": true,
    "zoom_buttons": true,
    "double_click_reset": true,
    "reset_axes": ["x", "y2"],
    "link_group": "latency-dashboard",
    "link_axes": ["x", "y2"]
  },
  "view": {
    "ranges": {
      "x": [210.0, 480.0],
      "y": [0.0, 16995.0],
      "y2": [95.0, 105.0]
    }
  }
}
```

A flat contract extends existing bools, keeps precedence visible, and serializes
identically across Python, exports, and adapters. Nested `PanConfig`/`ZoomConfig`
objects can be reconsidered only if source policy grows substantially.

## 17. Examples

### X-only histogram

```python
xy.histogram_chart(
    xy.hist(values, bins=140),
    xy.interaction_config(
        pan_axes=("x",),
        zoom_axes=("x",),
        reset_axes=("x",),
    ),
)
```

The count scale remains stable while the distribution is explored. The default
`zoom_limits=(1.0, None)` prevents x from zooming out beyond its original window.

### Dual y axes with independent zoom

```python
xy.chart(
    xy.line(time, temperature, y_axis="y"),
    xy.line(time, pressure, y_axis="y2"),
    xy.y_axis(id="y", label="temperature (°C)"),
    xy.y_axis(id="y2", label="pressure (kPa)", side="right"),
    xy.interaction_config(
        pan_axes=("x", "y2"),
        zoom_axes=("x", "y2"),
        zoom_limits={"x": (1.0, None), "y2": (0.5, 32.0)},
        reset_axes=("x", "y2"),
    ),
)
```

The time and pressure ranges change; temperature remains fixed. Use
`zoom_axes=("x", "y", "y2")` when both y scales should change.

### Selection-first chart with wheel zoom

```python
xy.scatter_chart(
    xy.scatter(x, y),
    xy.interaction_config(
        default_drag_action="select",
        select=True,
        brush=True,
        wheel_zoom=True,
        box_zoom=False,
    ),
)
```

Plain drag selects, wheel zoom remains, and competing rectangular zoom is removed.

### Read-only linked detail

```python
xy.line_chart(
    xy.line(time, value),
    xy.interaction_config(
        navigation=False,
        link_group="shared-time",
        link_axes=("x",),
    ),
)
```

Local input cannot mutate the chart, but linked/programmatic x updates still apply.

## 18. Testing and acceptance

### Python contract

- Configuration keys work on chart kwargs and `interaction_config()`.
- Child interaction nodes override chart-level values in declaration order.
- Axis tuples validate, deduplicate, and serialize consistently.
- Zoom-limit tuples/maps validate and normalize to an axis-keyed wire map.
- Omitted keys preserve the existing payload.
- Invalid explicit drag modes fail before payload generation.

### Client and browser

For drag pan, wheel, box zoom, zoom in/out, and reset, assert:

```text
participating axis ranges change as expected
non-participating axis ranges are exactly unchanged
the result stays inside bounds
the resulting magnification stays inside per-axis zoom limits
event source and axes match the actual mutation
linked peers update only link_axes and do not echo
```

Run the matrix on linear, log, reversed, categorical, and dual-y axes, plus reduced motion.
Also verify no-op clamped actions emit no event/LOD request and modebar state follows
the resolved policy. Cover `(1.0, None)`, finite zoom-out/in limits, partial per-axis
maps, and limits reached on only one axis of a multi-axis action.

### Reflex

- Payloads are JSON-safe.
- Continuous events coalesce and always end with `phase="end"`.
- Applying a stored committed view does not loop.
- Static charts retain local interaction without a backend.
- Live charts refine LOD without placing buffers in Reflex state.

## 19. Implementation status

The completed implementation includes:

1. `navigation`, action/source switches, exact per-axis policies, bounds, zoom
   limits, linking, and validation.
2. A canonical per-axis `ranges` viewport with primary-axis compatibility aliases.
3. Shared transforms for drag pan, wheel zoom, box zoom, toolbar zoom, reset,
   linked updates, and programmatic updates.
4. `default_drag_action` resolution and modebar controls that reflect the resolved
   capabilities.
5. Reset independent from selection clear.
6. Semantic `ranges`, `source`, `axes`, `phase`, and `interaction_id` events, with
   callback-gated notebook/Reflex transport.
7. Python contract tests, client smoke coverage, generated examples, and matching
   canonical/generated JavaScript bundles.

Touch pinch and a separate focused keyboard navigation mode are deferred as stated in
sections 14 and 22; neither is claimed as part of the current device contract.

## 20. Compatibility

- Existing boolean `pan` and `zoom` remain valid.
- Existing `zoom_axes=("x",)` behavior remains unchanged.
- On primary-axis charts, existing `zoom_axes=("x", "y")` behavior remains unchanged.
- On multi-axis charts, selectors are exact IDs; `"y"` does not imply `"y2"`.
- Missing axis policies resolve to all declared axes.
- Missing or `None` `zoom_limits` resolves to `(1.0, None)` for every selected axis.
- Use `zoom_limits=(None, None)` to opt into bounds/precision-only zooming on all
  selected axes.
- Missing source switches resolve to current enabled behavior.
- Hiding the modebar still does not disable gestures.
- Existing primary x/y coordinates remain as transitional event aliases.
- New fields are additive until a documented major-version boundary.
- Older standalone HTML retains its embedded client's original behavior.

## 21. Alternatives considered

### Nested pan/zoom config objects

They group fields but change established bool types, complicate merging, and add tiny
configuration classes. Reject for now.

### One shared `navigation_axes`

It cannot express “pan both, zoom x only” or “fixed x, inspect y.” Reject because
axis policy is action-specific. Independence needs the containment clamp to be
real, though: cursor-anchored zoom embeds a translation, so “zoom without pan”
holds only because a pan-locked axis is confined to its home window (§7.1).

### Infer locked axes from domain

Domain is home, not a lock; bounds are the hard envelope. Reject as ambiguous.

### Control every frame through Reflex state

This puts network latency and JSON state diffing in the input loop. Reject. The
browser owns transient view state; Reflex owns application state and committed
coordination.

## 22. Resolved and deferred

Resolved here:

- Axis policy is per action and uses concrete declared axis IDs.
- Every axis owns an independent home/current range, scale, and bounds.
- Zoom extent is a per-axis magnification interval relative to home.
- Reset is independent from zoom and selection.
- Bounds apply after filtering on every mutation path.
- Local input can be disabled while external updates continue.
- Events describe actual axes and phases.
- Configuration remains flat for compatibility.

Deferred to separate designs:

- linked-axis mapping when charts use different axis IDs;
- keyboard shortcut customization;
- touch pinch implementation details;
- navigation undo/redo;
- wheel sensitivity/easing;
- controlled-view reconciliation beyond idempotent updates.
