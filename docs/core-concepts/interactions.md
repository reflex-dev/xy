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

x = [0, 1, 2, 3]
y = [1, 3, 2, 5]

chart = xy.area_chart(
    xy.area(x, y, color="#6e56cf"),
    xy.scatter(x, y, color="#6e56cf", size=6),
    xy.interaction_config(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
    ),
)


def browser_behavior_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

Standalone HTML keeps these local browser behaviors. It cannot invoke Python
because no kernel or server is attached.

Viewport DOM events are always available. Add ``on_view_change`` to a live
notebook or Reflex adapter when Python needs the semantic range events; there
is no separate transport configuration flag.

## Handle chart events in Reflex

Core chart containers accept `on_hover`, `on_click`, `on_brush`, `on_select`,
and `on_view_change` for live notebook widgets. In Reflex, put event handlers
on the outer adapter component instead. This area chart shows a toast after a
point click or completed selection:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

x = [0, 1, 2, 3, 4, 5, 6]
y = [2, 4, 3, 5, 4, 6, 5]

callback_chart = xy.area_chart(
    xy.area(x, y, color="#6e56cf"),
    xy.scatter(x, y, color="#6e56cf", size=7),
    xy.interaction_config(click=True, select=True, brush=True),
)
callback_chart_token = reflex_xy.inline(callback_chart)


class PythonCallbacksState(rx.State):
    @rx.event
    def show_point(self, event: reflex_xy.PointClickEvent):
        point = event.get("data") or {}
        return rx.toast.info(
            f"Clicked x={point.get('x', 0):g}, y={point.get('y', 0):g}"
        )

    @rx.event
    def show_selection(self, event: reflex_xy.SelectEndEvent):
        selection = event.get("selection") or {}
        if selection.get("cleared"):
            return rx.toast.info("Selection cleared")
        total = int(selection.get("total_count") or 0)
        return rx.toast.success(f"Selected {total} points")


def python_callbacks_demo():
    return reflex_xy.chart(
        callback_chart_token,
        on_point_click=PythonCallbacksState.show_point,
        on_select_end=PythonCallbacksState.show_selection,
        height="360px",
    )
~~~

Click a point, or Shift-drag across several points, to trigger the Reflex
toasts. The module-scope `inline()` token keeps this fixed-data chart connected
to the backend so those events can reach `PythonCallbacksState`.

The Reflex adapter exposes a separate event surface on the outer
`reflex_xy.chart(...)` component:

| Core notebook callback | Callback payload | Reflex component prop | Reflex payload |
| --- | --- | --- | --- |
| `on_hover` | Resolved row dictionary | `on_point_hover` | Point envelope with data and canonical row ID |
| `on_click` | Resolved row dictionary | `on_point_click` | Point envelope with data and canonical row ID |
| `on_brush` | Bounds or polygon dictionary | No dedicated prop | — |
| `on_select` | `xy.Selection` with canonical rows | `on_select_end` | Selection envelope with count, bounds, and cleared state |
| `on_view_change` | View dictionary | `on_view_change` | View-change envelope |

Reflex event props work with a live adapter source—an `inline()` token or an
`@reflex_xy.figure` var—not with the direct static-Chart tier. See
[Reflex integration](/docs/xy/integrations/reflex/).

## Exact readout and selection

The renderer may display a decimated line, density grid, or retained sample,
but XY keeps canonical rows in Python:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

exact_readout_x = list(range(16))
exact_readout_y = [1, 3, 2, 5, 4, 6, 3, 7, 5, 8, 6, 9, 7, 10, 8, 11]

exact_readout_chart = xy.scatter_chart(
    xy.scatter(exact_readout_x, exact_readout_y, color="#6e56cf", size=7),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    xy.interaction_config(click=True, select=True, brush=True),
)
exact_readout_chart_token = reflex_xy.inline(exact_readout_chart)


class ExactReadoutState(rx.State):
    picked_row: str = "Click a point"
    selected_count: int = 0
    selected_x: str = "Shift-drag across points"
    selected_y: str = "No active selection"

    @rx.event
    def pick_point(self, event: reflex_xy.PointClickEvent):
        point = event.get("data") or {}
        trace = int(event.get("trace") or 0)
        index = int(event.get("canonical_row_id") or 0)
        x_value = float(point.get("x") or 0)
        y_value = float(point.get("y") or 0)
        self.picked_row = (
            f"trace={trace} · index={index} · x={x_value:g} · y={y_value:g}"
        )

    @rx.event
    def select_points(self, event: reflex_xy.SelectEndEvent):
        selection = event.get("selection") or {}
        if selection.get("cleared"):
            self.selected_count = 0
            self.selected_x = "[]"
            self.selected_y = "[]"
            return

        rows = [
            row
            for row in selection.get("rows") or []
            if int(row.get("trace") or 0) == 0
        ]
        self.selected_count = int(selection.get("total_count") or 0)
        self.selected_x = "[" + ", ".join(
            f"{float(row['x']):g}" for row in rows
        ) + "]"
        self.selected_y = "[" + ", ".join(
            f"{float(row['y']):g}" for row in rows
        ) + "]"


def exact_readout_demo():
    return rx.el.div(
        reflex_xy.chart(
            exact_readout_chart_token,
            on_point_click=ExactReadoutState.pick_point,
            on_select_end=ExactReadoutState.select_points,
            height="320px",
        ),
        rx.el.dl(
            rx.el.div(
                rx.el.dt(
                    "Picked row",
                    class_name="text-xs font-medium text-secondary-10",
                ),
                rx.el.dd(
                    rx.el.code(ExactReadoutState.picked_row),
                    class_name="mt-1 text-sm text-secondary-12",
                ),
                class_name="min-w-0",
            ),
            rx.el.div(
                rx.el.dt(
                    "Selected x · ",
                    ExactReadoutState.selected_count,
                    " rows",
                    class_name="text-xs font-medium text-secondary-10",
                ),
                rx.el.dd(
                    rx.el.code(ExactReadoutState.selected_x),
                    class_name="mt-1 text-sm text-secondary-12",
                ),
                class_name="min-w-0",
            ),
            rx.el.div(
                rx.el.dt(
                    "Selected y",
                    class_name="text-xs font-medium text-secondary-10",
                ),
                rx.el.dd(
                    rx.el.code(ExactReadoutState.selected_y),
                    class_name="mt-1 text-sm text-secondary-12",
                ),
                class_name="min-w-0",
            ),
            class_name=(
                "grid w-full grid-cols-1 gap-3 rounded-lg border "
                "border-secondary-4 bg-secondary-1 p-3 sm:grid-cols-3"
            ),
        ),
        class_name="flex w-full flex-col gap-3",
    )
~~~

Click a point to update **Picked row**. Shift-drag a box across points to update
the selected x and y values. Both readouts are Reflex state populated by
`on_point_click` and `on_select_end`.

The selection event includes canonical row IDs and a bounded `rows` projection,
which is sufficient for this small chart. For large or truncated selections,
call `reflex_xy.resolve_selection(event)` in the handler to recover every
canonical row.

## Linked views

Give related charts the same `link_group` and choose which axes participate:

~~~python demo exec
import xy

x = list(range(16))
overview_y = [2, 4, 3, 5, 4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11]
detail_y = [20, 38, 31, 47, 42, 58, 51, 69, 63, 77, 72, 88, 81, 96, 91, 108]

overview = xy.line_chart(
    xy.line(x, overview_y, color="#6e56cf"),
    link_group="revenue",
    link_axes=("x",),
)

detail = xy.scatter_chart(
    xy.scatter(x, detail_y, color="#6e56cf", size=7),
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
