---
title: Chrome Slots
description: Target stable chart DOM slots with CSS, Tailwind, classes, and inline styles.
---

# Chrome Slots

Every chart-chrome element carries `data-xy-slot="<slot>"`. The same validated
slot name works in `class_names`, `styles`, component-local class/style props,
and a plain CSS attribute selector.

## Slot reference

| Slot | Element |
| --- | --- |
| `root` | Outer chart container |
| `title` | Chart title |
| `chrome` | Non-plot chrome layer |
| `canvas` | WebGL2 plot canvas |
| `labels` | Axis and annotation label layer |
| `legend` | Legend container |
| `legend_item` | One legend row |
| `legend_swatch` | One legend color swatch |
| `colorbar` | Colorbar container |
| `colorbar_bar` | Colorbar gradient or bands |
| `colorbar_tick` | One colorbar tick label |
| `colorbar_title` | Colorbar title |
| `tooltip` | Hover tooltip |
| `modebar` | Mode/tool bar container |
| `modebar_button` | One mode/tool button; `.xy-active` when active |
| `selection` | Box/x-range/y-range select or box-zoom rectangle (persists until cleared for selects) |
| `crosshair_x` | Vertical crosshair line |
| `crosshair_y` | Horizontal crosshair line |
| `badge` | Reduction/density badge container |
| `badge_item` | One reduction/density badge |
| `tick_label` | Axis tick label |
| `axis_title` | Axis title label |
| `annotation_label` | Text, label, or callout DOM overlay |

Unknown slot names raise while the chart is built, before a typo can become a
silently unstyled client element.

## Classes and Tailwind in Reflex

In a Reflex app, enable its Tailwind plugin once in `rxconfig.py`:

~~~python
import reflex as rx

config = rx.Config(
    app_name="dashboard",
    plugins=[rx.plugins.TailwindV4Plugin()],
)
~~~

For a fixed `xy.Chart` or `xy.Figure` passed directly to `reflex_xy.chart(...)`,
Reflex includes the chart's literal class strings in Tailwind's default scan
paths. The complete utility names below therefore work without adding the
original Python or Markdown file to Tailwind's source configuration.

~~~python demo exec
import reflex_xy
import xy

chart = xy.area_chart(
    xy.area(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
        [32, 45, 41, 58, 63, 74],
        name="Signal",
        color="#00b8db",
        fill="linear-gradient(#00b8db4d 5%, #00b8db00 95%)",
        opacity=1,
        curve="smooth",
        line_width=2,
    ),
    xy.x_axis(
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.y_axis(
        domain=(0, 80),
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_color": "#e2e8f0",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.legend(),
    class_name="text-slate-900 dark:text-zinc-100",
    class_names={
        "legend": "bg-transparent text-xs text-slate-600 dark:text-slate-300",
        "tooltip": "rounded-lg bg-zinc-950/90 px-3 py-2 text-white shadow-xl",
        "modebar_button": "hover:bg-zinc-100 focus:ring-2 dark:hover:bg-zinc-800",
    },
    width="100%",
    height=320,
    padding=(24, 24, 44, 32),
)


def tailwind_chrome_preview():
    return reflex_xy.chart(chart, height="320px")
~~~

Keep each utility name complete and literal, such as `bg-zinc-950/90`. Tailwind
cannot discover a name assembled at runtime from fragments such as
`f"bg-{tone}-950"`; map dynamic state to complete class strings instead.

For charts produced from a token or `Var`, Tailwind still needs to see every
possible utility at build time. Put each complete utility name in a normal
Reflex component or safelist it in the host app. The same rule applies when
application logic chooses classes dynamically.

Without `TailwindV4Plugin`, XY still places the names in the DOM but no Tailwind
utilities are generated, so the chart renders without those styles. An XY
standalone HTML export likewise carries the names but does not bundle Tailwind;
inject already-compiled rules with `custom_css` or use ordinary CSS for a
portable file.

## One tooltip, three styling approaches

All three examples target the same `tooltip` slot. Choose based on where the
style originates; do not combine them unless you intentionally want normal CSS
cascade precedence.

Use `class_names` when the host already provides utilities or reusable classes:

~~~python
chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4]),
    class_names={
        "tooltip": (
            "rounded-lg border border-zinc-700 bg-zinc-950 "
            "px-3 py-2 text-white shadow-xl"
        )
    },
)
~~~

Use `styles` for values computed in Python or when no stylesheet is involved:

~~~python
chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4]),
    styles={
        "tooltip": {
            "background": "#09090b",
            "color": "#ffffff",
            "border": "1px solid #334155",
            "border_radius": 8,
            "padding": "8px 12px",
            "box_shadow": "0 12px 30px rgb(15 23 42 / 35%)",
        }
    },
)
~~~

Use a `data-xy-slot` selector when one host rule should style many charts or an
export needs raw author CSS:

~~~python
tooltip_css = """
.analytics [data-xy-slot="tooltip"] {
  background: #09090b;
  color: #fff;
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 8px 12px;
  box-shadow: 0 12px 30px rgb(15 23 42 / 35%);
}
"""

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4]),
    class_name="analytics",
)
chart.to_html("analytics.html", custom_css=tooltip_css)
~~~

An inline `styles["tooltip"]` declaration normally wins over a class or plain
author rule targeting the same property. Prefer one primary approach per slot
instead of escalating to `!important`.

## Inline slot styles

Use `styles` when values are computed in Python or when no stylesheet is
appropriate:

~~~python
chart = xy.scatter_chart(
    xy.scatter([1, 2], [3, 5]),
    styles={
        "title": {"font_size": 18, "letter_spacing": "0.02em"},
        "tooltip": {
            "background_color": "rgba(24, 24, 27, 0.94)",
            "border_radius": 10,
        },
    },
    title="Inline slot styles",
)
~~~

Snake_case property aliases normalize to CSS kebab-case. Bare numbers on
length properties become pixels; custom properties and unitless values pass
through. Values are declaration-safety checked even though DOM styles accept a
broader property set than rendered marks.

## Plain CSS and exported documents

~~~python
css = """
.analytics [data-xy-slot="tooltip"] {
  border: 1px solid rgb(148 163 184 / 35%);
  backdrop-filter: blur(8px);
}
.analytics [data-xy-slot="annotation_label"] { font-style: italic; }
.analytics [data-xy-slot="canvas"] { cursor: cell; }
"""

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4]),
    class_name="analytics",
)
chart.to_html("analytics.html", custom_css=css)
~~~

`custom_css` becomes an author `<style>` in the self-contained HTML document.
XY rejects strings that could break out of that style element. The same option
works for Chromium PNG capture; native PNG has no browser cascade and rejects
`custom_css`.

## Cascade and structural layout

Built-in visual rules live in the low-priority `base` cascade layer and use
zero-specificity `:where(...)`, so Tailwind's utility layer and ordinary
unlayered author selectors beat them without `!important`. XY retains structural inline styles
for positioning, dimensions, z-index, and interaction state. Avoid overriding
those unless you intentionally take responsibility for chart layout.

Responsive legend bounds, anchors, and tooltip wrapping use the same layered,
zero-specificity defaults. Long legends become scrollable and edge tooltips
wrap or flip inside the chart, while a class or `styles` entry can still
replace those defaults. Completed lasso polygons are canvas chrome and use the
`--chart-selection` / `--chart-selection-fill` tokens rather than the
`selection` DOM slot.

Annotation **labels** use `annotation_label`; canvas-painted arrow shafts,
markers, rules, and zones do not. Style those through their annotation props as
described in
[Customize Each Part](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients).
