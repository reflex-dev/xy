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
| `selection` | Active box-select or box-zoom rectangle |
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
the adapter mirrors its chart, slot, mark, and annotation class strings into
generated JSX. That JSX is already in the plugin's default scan paths, so the
complete utility names below work without adding the original Python or
Markdown file to Tailwind's source configuration.

~~~python demo exec
import reflex_xy
import xy

chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [2, 5, 3, 8], name="Signal"),
    xy.legend(),
    class_name=(
        "rounded-xl border border-slate-200 bg-white text-slate-900 shadow-sm "
        "dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
    ),
    class_names={
        "title": "text-base font-semibold",
        "legend": "bg-transparent text-xs text-slate-600 dark:text-slate-300",
        "tooltip": "rounded-lg bg-slate-950/90 px-3 py-2 text-white shadow-xl",
        "modebar_button": "hover:bg-slate-100 focus:ring-2 dark:hover:bg-slate-800",
    },
    title="Tailwind chrome",
)


def tailwind_chrome_preview():
    return reflex_xy.chart(chart, height="320px")
~~~

Keep each utility name complete and literal, such as `bg-slate-950/90`. Tailwind
cannot discover a name assembled at runtime from fragments such as
`f"bg-{tone}-950"`; map dynamic state to complete class strings instead.

Live token/Var charts are different: their figure is produced at runtime, after
Tailwind has compiled the app, so the adapter cannot mirror those class names
ahead of time. Put every complete utility name used by a live chart literally
in a normal Reflex component (or safelist it in the host app). The same rule
applies when application logic chooses classes that were not present on the
fixed figure at compile time.

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
            "rounded-lg border border-slate-700 bg-slate-950 "
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
            "background": "#020617",
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
  background: #020617;
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
            "background_color": "rgba(15, 23, 42, 0.94)",
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
described in [Mark styles](/docs/xy/styling/mark-styles/#what-css-cannot-reach).
