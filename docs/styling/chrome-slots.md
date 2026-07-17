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
| `selection` | Box/lasso selection rectangle |
| `crosshair_x` | Vertical crosshair line |
| `crosshair_y` | Horizontal crosshair line |
| `badge` | Reduction/density badge container |
| `badge_item` | One reduction/density badge |
| `tick_label` | Axis tick label |
| `axis_title` | Axis title label |
| `annotation_label` | Text, label, or callout DOM overlay |

Unknown slot names raise while the chart is built, before a typo can become a
silently unstyled client element.

## Classes and Tailwind

~~~python
import xy

chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [2, 5, 3, 8], name="Signal"),
    xy.legend(),
    class_name="rounded-xl border border-slate-200 bg-white shadow-sm",
    class_names={
        "title": "text-base font-semibold text-slate-900",
        "legend": "bg-transparent text-xs text-slate-600",
        "tooltip": "rounded-lg bg-slate-950/90 px-3 py-2 text-white shadow-xl",
        "modebar_button": "hover:bg-slate-100 focus:ring-2",
    },
    title="Tailwind chrome",
)
~~~

Tailwind must see these literal class strings during its normal source scan.
An XY standalone HTML export carries class names but does not bundle the
Tailwind framework automatically; inject the compiled rules with `custom_css`
or use ordinary CSS for a portable file.

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

Built-in visual rules use zero-specificity `:where(...)`, so classes and author
selectors beat them without `!important`. XY retains structural inline styles
for positioning, dimensions, z-index, and interaction state. Avoid overriding
those unless you intentionally take responsibility for chart layout.

Annotation **labels** use `annotation_label`; canvas-painted arrow shafts,
markers, rules, and zones do not. Style those through their annotation props as
described in [Mark styles](/docs/xy/styling/mark-styles/#what-css-cannot-reach).
