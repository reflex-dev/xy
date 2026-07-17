---
title: Modebars and Interaction Controls
description: Configure XY's toolbar, gestures, selection, exports, and linked viewports.
---

# Modebars and Interaction Controls

Interactive charts include a compact modebar by default. It exposes pan, zoom
in/out, box zoom, reset, selection modes when selection is enabled, and local
PNG, SVG, and CSV export.

Use `modebar()` to hide or style the toolbar:

~~~python
import xy

chart = xy.scatter_chart(
    xy.scatter([0, 1, 2, 3], [1, 3, 2, 5]),
    xy.modebar(
        button_class_name="rounded-md",
        button_style={"border": "1px solid #d0d5dd"},
    ),
)
~~~

`class_name` and `style` target the toolbar; `button_class_name` and
`button_style` target every control. The same surfaces are available through
the `modebar` and `modebar_button` chart slots. Use `show=False` to remove the
toolbar. The last modebar component supplies the effective configuration.

The CSV command exports data resident in the browser representation. On a
decimated or density-tier chart that is not necessarily every canonical source
row; export the source table from Python when a complete data extract is
required.

## Enable Interaction Behavior

Configure behavior as chart props or with an `interaction_config()` child:

~~~python
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
~~~

Supplying a Python callback on the chart automatically enables its matching
interaction. Browser gestures still work in standalone HTML, but Python
callbacks require a live notebook or framework transport.

Selection controls include box, lasso, x-range, and y-range modes. The
`on_select` callback receives a canonical `Selection`; `on_brush` receives the
box or polygon geometry.

## Link Viewports

Charts with the same non-empty `link_group` synchronize the axes named by
`link_axes`:

~~~python
shared = xy.interaction_config(
    link_group="dashboard-time",
    link_axes=("x",),
)
~~~

Linking uses browser-local viewport messages. It synchronizes pan and zoom
ranges, not selections or cross-filtered data. Build those behaviors with
callbacks and application state.

The toolbar uses named controls, focus state, keyboard-operable menus, and
forced-colors/reduced-motion affordances. The current accessibility boundary is
documented under
[Limitations and alpha status](/docs/xy/api-reference/limitations-and-alpha-status/).
For callback payloads, see
[Events and callbacks](/docs/xy/api-reference/events-and-callbacks/).
