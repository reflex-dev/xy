---
title: Interactions
description: Enable hover, click, selection, brushing, crosshairs, and linked views.
---

# Interactions

Interactive HTML and notebook charts support pan, zoom, hover, selection, and
exact source-row readout. Behavior can be enabled directly on the chart or with
an `interaction_config()` child.

## Configure Browser Behavior

~~~python
import xy as fc

chart = fc.scatter_chart(
    fc.scatter([0, 1, 2, 3], [1, 3, 2, 5]),
    fc.interaction_config(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
    ),
)
~~~

## Python Callbacks

Pass `on_hover`, `on_click`, `on_brush`, `on_select`, or `on_view_change` to a
chart container. Providing a callback automatically enables its corresponding
browser interaction.

~~~python
def selected(selection):
    print(len(selection), "rows")


chart = fc.scatter_chart(
    fc.scatter([0, 1, 2], [2, 4, 3]),
    on_select=selected,
)
~~~

Callbacks run through the live widget or a framework adapter. Standalone HTML
contains browser behavior but cannot call back into a Python process.

## Linked Views

Give charts the same `link_group` and select axes through `link_axes=("x", "y")`
to coordinate view changes. This is useful for dashboards and related panels.

For Python-side inspection, `chart.pick(trace_id, index)` returns an exact row,
and `chart.select_range(...)` returns the same `Selection` type delivered to
selection callbacks.
