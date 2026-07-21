---
title: Interactions and Selections
description: Configure hover, click, selection, brushing, crosshairs, callbacks, and linked views.
---

# Interactions and Selections

Interactive HTML and notebook charts support pan, zoom, hover, click,
selection, brushing, crosshairs, and view changes. Interaction settings control
browser behavior; callbacks decide whether a live Python process also receives
an event.

## Configure browser behavior

Set flags directly on a chart or compose an `interaction_config()` child:

~~~python demo exec
import xy

chart = xy.scatter_chart(
    xy.scatter([0, 1, 2, 3], [1, 3, 2, 5]),
    xy.interaction_config(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    ),
)


def browser_behavior_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

Standalone HTML keeps these local browser behaviors. It cannot invoke Python
because no kernel or server is attached.

## Python callbacks

Core chart containers accept `on_hover`, `on_click`, `on_brush`, `on_select`,
and `on_view_change`. Supplying a callback enables the corresponding browser
interaction automatically.

~~~python demo exec
import xy


def selected(selection):
    if len(selection):
        xs, ys = selection.xy(0)
        print(f"selected {len(selection)} rows; first x={xs[0]}")


chart = xy.scatter_chart(
    xy.scatter([0, 1, 2], [2, 4, 3]),
    on_select=selected,
)


def python_callbacks_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

These callbacks run through a live notebook widget. They are ordinary Python
callables stored on the core `xy.Chart`; they are not host-framework event
props.

The Reflex adapter exposes a separate event surface on the outer
`reflex_xy.chart(...)` component:

| Core notebook callback | Callback payload | Reflex component prop | Reflex payload |
| --- | --- | --- | --- |
| `on_hover` | Resolved row dictionary | `on_point_hover` | Resolved row dictionary |
| `on_click` | Resolved row dictionary | `on_point_click` | Resolved row dictionary |
| `on_brush` | Bounds or polygon dictionary | No dedicated prop | — |
| `on_select` | `xy.Selection` with canonical rows | `on_select_end` | JSON-safe summary with `total`, optional bounds, and `cleared` |
| `on_view_change` | View dictionary | `on_view_change` | View dictionary |

Reflex event props work with a live adapter source—an `inline()` token or an
`@reflex_xy.figure` var—not with the direct static-Chart tier. See
[Reflex integration](/docs/xy/integrations/reflex/).

## Exact readout and selection

The renderer may display a decimated line, density grid, or retained sample,
but XY keeps canonical rows in Python:

~~~python demo exec
import xy

chart = xy.scatter_chart(
    xy.scatter([0, 1, 2, 3], [1, 3, 2, 5]),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
)

row = chart.pick(trace_id=0, index=1)

selection = chart.select_range(
    x0=0.5,
    x1=2.5,
    y0=0.0,
    y1=5.0,
)
xs, ys = selection.xy(0)


def exact_readout_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

`Selection` stores canonical row indices per trace, supports
`len(selection)`, and returns selected coordinates with `xy(trace_id)`.
Browser selections delivered to `on_select` use the same type after the widget
resolves their canonical rows.

## Linked views

Give related charts the same `link_group` and choose which axes participate:

~~~python demo exec
import xy

overview = xy.line_chart(
    xy.line([0, 1, 2], [2, 4, 3]),
    link_group="revenue",
    link_axes=("x",),
)

detail = xy.scatter_chart(
    xy.scatter([0, 1, 2], [20, 40, 30]),
    link_group="revenue",
    link_axes=("x",),
)


def linked_views_demo():
    import reflex as rx
    import reflex_xy

    return rx.el.div(
        reflex_xy.chart(overview, height="280px"),
        reflex_xy.chart(detail, height="280px"),
        class_name="grid w-full grid-cols-1 gap-4 lg:grid-cols-2",
    )
~~~

Pan or zoom changes propagate between mounted charts in that group. Linking
coordinates the view window; cross-filtering application data still belongs in
a widget callback or host-framework state. For complete dashboard patterns,
read [Dashboards and linked views](/docs/xy/guides/dashboards-and-linked-views/).
