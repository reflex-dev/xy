---
title: Modebars & Controls in Python
description: Configure XY's toolbar, gestures, selection, exports, and linked viewports.
components:
  - xy.modebar
  - xy.interaction_config
---

# Modebars & Controls in Python

Interactive charts include a compact modebar by default. It exposes pan, zoom
in/out, box zoom, reset, selection modes when selection is enabled, and local
PNG, SVG, and CSV export. The modebar appears at the plot's top-left on chart
hover or keyboard focus. Drag its background, padding, gaps, or separators to
move it within the chart; buttons and menus remain dedicated click targets. A
small drag affordance appears just outside the toolbar on hover or focus and
flips sides when the preferred edge would clip.

Pan is enabled by default. Click the active Pan button to disable drag, wheel,
and double-click navigation; wheel gestures then scroll the containing page.
Click Pan again—or choose it after a selection mode—to restore navigation.
Back and Next view-history controls live at the top of the zoom menu. They
disable automatically at the ends of the history, remain open while stepping
through views, and a new navigation after going Back clears the forward stack.

### The default toolbar

Every interactive chart gets the modebar for free — hover over the top-right
corner of this chart to see the pan, zoom, reset, and export controls:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng_signal = np.random.default_rng(11)
signal_walk = np.cumsum(rng_signal.normal(0.0, 1.0, 60)).round(2)

default_toolbar_chart = xy.line_chart(
    xy.line(list(range(60)), signal_walk, name="signal"),
    title="Default modebar",
)


def default_toolbar_demo():
    return reflex_xy.chart(default_toolbar_chart, height="320px")
~~~

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

The toolbar's default surface follows your page's light or dark mode
automatically: a `.dark` class on the chart root or any ancestor (as Reflex,
Radix, and Tailwind set on the root `<html>`) switches it to a dark palette,
while `--chart-modebar-*` tokens you supply still override it. See
[Themes and tokens](/docs/xy/styling/themes-and-tokens/#automatic-dark-mode-for-the-toolbar).

The CSV command exports data resident in the browser representation. On a
decimated or density-tier chart that is not necessarily every canonical source
row; export the source table from Python when a complete data extract is
required.

### Styling or removing the toolbar

The left chart restyles the toolbar surface and every button, while the right
chart removes the toolbar entirely with `modebar(show=False)`:

~~~python demo exec
import numpy as np
import reflex as rx
import reflex_xy
import xy

rng_pair = np.random.default_rng(5)
toolbar_x = list(range(30))

styled_toolbar = xy.line_chart(
    xy.line(
        toolbar_x,
        np.cumsum(rng_pair.normal(0.0, 1.0, 30)).round(2),
        name="styled",
    ),
    xy.modebar(
        style={"background": "#f8fafc", "border_radius": 8},
        button_class_name="rounded-md",
        button_style={"border": "1px solid #d0d5dd"},
    ),
    title="Styled toolbar",
)

hidden_toolbar = xy.line_chart(
    xy.line(
        toolbar_x,
        np.cumsum(rng_pair.normal(0.0, 1.0, 30)).round(2),
        name="hidden",
        color="#b45309",
    ),
    xy.modebar(show=False),
    title="modebar(show=False)",
)


def toolbar_visibility_demo():
    return rx.el.div(
        reflex_xy.chart(styled_toolbar, height="320px"),
        reflex_xy.chart(hidden_toolbar, height="320px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

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
    ),
)
~~~

Supplying a Python callback on the chart automatically enables its matching
interaction. Browser gestures still work in standalone HTML, but Python
callbacks require a live notebook or framework transport.

## Configure Pan and Zoom

Limit an action to concrete declared axis IDs with `pan_axes` or `zoom_axes`.
The zoom policy applies consistently to wheel zoom, modebar zoom-in/out, and box
zoom:

~~~python
chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [1, 3, 2, 5]),
    xy.interaction_config(zoom_axes=("x",)),
)
~~~

Use `zoom_axes=("y",)` for y-only zoom. Omitting the option preserves the
default of all declared axes. On a multi-axis chart, IDs are exact:
`zoom_axes=("x", "y2")` changes x and y2 while primary y remains fixed.

`default_drag_action` controls only an unmodified primary-button drag. The default
`"auto"` chooses pan when available, then box zoom, then selection. Use `"zoom"`
for box zoom, `"none"` for no plain-drag action, or one of `"select"`,
`"select-x"`, `"select-y"`, and `"select-lasso"`. It does not enable the
corresponding capability.

The complete navigation policy is:

| Option | Purpose |
| --- | --- |
| `navigation` | Master switch for local pan, zoom, and reset input. |
| `pan`, `pan_axes` | Enable pan and name the exact axes it moves freely. An axis zoom can navigate but pan cannot is contained: it drags only within its home extents. |
| `zoom`, `zoom_axes` | Enable zoom and name the exact axes it changes. |
| `zoom_limits` | Set `(minimum, maximum)` magnification relative to the original range, globally or by axis ID. |
| `wheel_zoom` | Enable wheel and trackpad zoom. |
| `box_zoom` | Make box zoom available as a drag tool. |
| `zoom_buttons` | Show modebar Zoom In and Zoom Out commands. |
| `double_click_reset` | Let double-click restore the configured reset axes. |
| `reset_axes` | Name the exact axes restored by Reset View. |

Omitted `zoom_limits` resolves to `(1.0, None)` on every zoom axis. This prevents
zooming out past the original window while leaving zoom-in unconstrained except by
axis bounds and renderer precision. A tuple applies to all zoom axes; a mapping can
set independent limits:

~~~python
xy.interaction_config(
    default_drag_action="zoom",
    pan_axes=("x", "y2"),
    zoom_axes=("x", "y2"),
    zoom_limits={"x": (1.0, None), "y2": (0.5, 32.0)},
    reset_axes=("x", "y2"),
)
~~~

Reset is independent from zoom and does not clear selection. `navigation=False`
blocks local viewport input, but linked and application-driven ranges may still
update the chart.

### Constrained navigation in practice

The left chart limits box zoom to the x axis with a 16x magnification cap and
double-click reset, while the right chart disables all local navigation with
`navigation=False` — its toolbar drops the pan, zoom, and reset commands:

~~~python demo exec
import numpy as np
import reflex as rx
import reflex_xy
import xy

rng_nav = np.random.default_rng(17)
nav_x = rng_nav.uniform(0.0, 10.0, 80)
nav_y = rng_nav.uniform(0.0, 4.0, 80)

x_zoom_only = xy.scatter_chart(
    xy.scatter(nav_x, nav_y, size=6, color="#2563eb"),
    xy.interaction_config(
        default_drag_action="zoom",
        zoom_axes=("x",),
        zoom_limits={"x": (1.0, 16.0)},
        double_click_reset=True,
        zoom_buttons=True,
    ),
    title="X-only box zoom, max 16x",
)

locked_viewport = xy.scatter_chart(
    xy.scatter(nav_x, nav_y, size=6, color="#64748b"),
    xy.interaction_config(navigation=False),
    title="navigation=False",
)


def navigation_policy_demo():
    return rx.el.div(
        reflex_xy.chart(x_zoom_only, height="320px"),
        reflex_xy.chart(locked_viewport, height="320px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

Selection controls include box, lasso, x-range, and y-range modes. The
`on_select` callback receives a canonical `Selection`; `on_brush` receives the
box or polygon geometry. While any selection mode is active, double-click the
chart to clear the active selection; for a lasso this also removes its editable
polygon. Double-click an editable lasso vertex to remove it; the minimum three
vertices remain protected. A plain click outside the polygon leaves it visible
and unchanged; it is replaced only when a new selection drag crosses the
movement threshold. In Pan mode, double-click continues to reset the viewport
without clearing a selection.

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

## FAQ

### How do I disable zoom and pan on a chart?

Add `xy.interaction_config(navigation=False)` — it is the master switch that
blocks all local pan, zoom, and reset input (linked and application-driven
ranges can still update the chart). To disable selectively, use `pan=False`,
`zoom=False`, or `wheel_zoom=False`, or restrict an action to specific axes
with `pan_axes=` and `zoom_axes=`, e.g. `zoom_axes=("x",)` for x-only zoom.

### How do I reset a chart to its original view after zooming?

The modebar's Reset View command restores the view, and
`double_click_reset=True` lets a double-click do the same; `reset_axes=` names
exactly which axes are restored. Zooming out past the original window is
already prevented by the default `zoom_limits` of `(1.0, None)` on every zoom
axis, and reset does not clear an active selection.

### How do I hide or customize the chart toolbar?

Add `xy.modebar(show=False)` to remove the toolbar entirely. To restyle it,
`class_name` and `style` target the toolbar while `button_class_name` and
`button_style` target every control (the `modebar` and `modebar_button` chart
slots expose the same surfaces), and `zoom_buttons=` in
`xy.interaction_config()` controls whether the Zoom In and Zoom Out commands
appear.

### Can users export a chart as PNG, SVG, or CSV from the toolbar?

Yes — the default modebar includes local PNG, SVG, and CSV export commands.
Note that CSV exports the data resident in the browser representation, so on a
decimated or density-tier chart that is not necessarily every canonical source
row; export the source table from Python when a complete extract is required.
