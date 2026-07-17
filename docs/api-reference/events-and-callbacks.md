---
title: Events and Callbacks
description: Reference core Chart callbacks, Selection payloads, browser events, and adapter names.
---

# Events and Callbacks

Core `Chart` callbacks run in Python through a live notebook widget or framework
transport. Browser interactions continue to work in standalone HTML, but a
self-contained file has no Python process to call.

## Core Python Callbacks

| Chart prop | Python payload |
| --- | --- |
| `on_hover` | Exact canonical row dictionary for the hovered point |
| `on_click` | Exact canonical row dictionary for the clicked point |
| `on_brush` | Selection geometry: normalized `x0`/`x1`/`y0`/`y1` or a `polygon` |
| `on_select` | A `Selection` with canonical row indices grouped by trace |
| `on_view_change` | Normalized `x0`, `x1`, `y0`, `y1`, and `source` |

Supplying a callback enables its corresponding browser interaction. Callback
payload details are still experimental during the alpha series.

Hover and click rows contain `trace`, canonical `index`, `x`, `y`, `x_kind`,
and `y_kind`. Depending on the mark's channels, they can also contain
`color_value`, `color_category`, or `size_value`. These are data dictionaries,
not DOM event objects or formatted tooltip strings.

~~~python
import xy


def selected(selection: xy.Selection) -> None:
    print(len(selection), selection.per_trace)


chart = xy.scatter_chart(
    xy.scatter([0, 1, 2], [2, 4, 3]),
    on_select=selected,
)
~~~

## Selection

`Selection` exposes:

- `per_trace` — `{trace_id: numpy_uint32_indices}` in canonical row space.
- `index` — all selected indices concatenated; use `per_trace` when trace
  identity matters.
- `xy(trace_id=0)` — canonical f64 x/y arrays for one selected trace.
- `len(selection)` — total selected rows across traces.

Clearing selection delivers an empty `Selection`. `Chart.select_range()`
returns the same type without requiring a browser gesture.

## Browser DOM Events

The client dispatches bubbling custom events from the chart root:

| Event | Detail |
| --- | --- |
| `xy:hover` | Resident or exact `row`, `trace`, `index`, viewport, and optional `exact` flag |
| `xy:click` | Data-space `x`/`y`, optional row hit, trace/index, and viewport |
| `xy:select` | Selected `total`, viewport, and range or polygon when resolved locally |
| `xy:view_change` | `x0`, `x1`, `y0`, `y1`, and interaction `source` |

A live hover can emit an immediate resident readout followed by an exact update.
Consumers that only need the canonical Python row should use `on_hover`.

## Reflex Adapter Events

The separate `reflex-xy` adapter intentionally uses semantic component props:
`on_point_hover`, `on_point_click`, `on_select_end`, and `on_view_change`.
Those are adapter props, not aliases accepted by core `Chart`. See the
[Reflex integration](/docs/xy/integrations/reflex/) for state-backed payloads.
`on_select_end` includes `total`, `cleared`, and either box bounds or the
data-space `polygon` used by a lasso selection.

Linked charts broadcast viewport ranges only. They do not automatically link
selection state or cross-filter data.
