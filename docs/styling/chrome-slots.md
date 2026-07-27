---
title: Chrome Slots
description: Target stable chart DOM slots with CSS, Tailwind, classes, and inline styles.
---

# Chrome Slots

Each public chart-chrome slot is attached to a DOM element as
`data-xy-slot="<slot>"`. The same validated slot name works in `class_names`,
`styles`, component-local class/style props, and a plain CSS attribute
selector. A slot is a supported styling hook, not a promise that every painted
primitive or structural descendant is a separate DOM element.

## Slot reference

| Slot | Element |
| --- | --- |
| `root` | Outer chart container |
| `title` | Chart title |
| `chrome` | Canvas-painted plot chrome |
| `canvas` | WebGL2 plot canvas |
| `labels` | Axis and annotation label layer |
| `legend` | Legend container |
| `legend_title` | Legend title |
| `legend_item` | One legend row |
| `legend_swatch` | One legend color swatch |
| `legend_label` | One legend text label |
| `colorbar` | Colorbar container |
| `colorbar_bar` | Colorbar gradient or bands |
| `colorbar_tick` | One colorbar tick label |
| `colorbar_title` | Colorbar title |
| `tooltip` | Hover tooltip container |
| `tooltip_title` | Formatted tooltip title |
| `tooltip_row` | One tooltip field row |
| `tooltip_label` | One tooltip field label |
| `tooltip_value` | One formatted tooltip value |
| `modebar` | Mode/tool bar container |
| `modebar_button` | One mode/tool button; `.xy-active` when active |
| `selection` | Box/x-range/y-range rectangle plus completed lasso path and editable handles |
| `crosshair_x` | Vertical crosshair line |
| `crosshair_y` | Horizontal crosshair line |
| `badge` | Reduction/density badge container |
| `badge_item` | One reduction/density badge |
| `tick_label` | Axis tick label |
| `axis_title` | Axis title label |
| `annotation_label` | Text, label, or callout DOM overlay |

Unknown slot names raise while the chart is built, before a typo can become a
silently unstyled client element.

## Tailwind capability by surface

The slot name tells you where a class lands; the surface type tells you what
that class can control.

| Surface | Examples | Tailwind contract |
| --- | --- | --- |
| Visually overridable DOM | `root`, `title`, legend, colorbar, tooltip, badge, label, `selection`, `crosshair_*`, `modebar`, `modebar_button` | Normal utilities override XY's layered visual defaults: color, background, border, typography, padding, shadow, and cursor. An explicit `styles={...}` value is inline author intent and still outranks a normal utility. |
| Structural-owned DOM | Chart layers; legend/colorbar/modebar anchors; tooltip, selection, and crosshair geometry | XY keeps required position, size, display, z-index, pointer-event, and transform state inline. A normal utility does not necessarily override those declarations; changing them means taking responsibility for layout or interaction. |
| Whole bitmap | `canvas` and `chrome` | A class styles the canvas element as one box, so cursor, opacity, filter, border, or transform affect the whole bitmap. It cannot select WebGL marks or canvas-painted grid, axes, and annotation shapes; use mark/axis/annotation props and `--chart-*` tokens for those pixels. |
| Repeated or ephemeral DOM | `legend_item`, `legend_swatch`, `legend_label`, `colorbar_tick`, tooltip rows, `modebar_button`, `badge_item`, tick/annotation labels, selection/crosshair overlays | One slot class applies to every matching node whenever XY creates it. Counts and node identities can change with payloads, hover content, interaction state, and responsive layout, so target the slot or an exposed state attribute rather than retaining a particular node. |
| State-owned / conditional inline | Legend hover/toggle, tooltip/selection/crosshair visibility and geometry, modebar active/open/fit state | The client writes the live property or exposes a state class/attribute. Durable visual utilities still apply, but replacing an inline state property requires `!important` and transfers responsibility for that behavior to the author. |

`modebar` styles the toolbar surface. `modebar_button` reaches both its
top-level controls and menu-item buttons. Tool groups, menus, separators,
indicators, and the drag handle are modebar substructure rather than additional
public slots; use `--chart-modebar-*` tokens or a descendant selector based on
their `data-xy-modebar-*` attributes. XY continues to own toolbar/menu
placement, fit visibility, opacity, and pointer-event state.

Some visible state is intentionally inline and conditional. Toggled or
hover-deemphasized legend rows receive client-owned `opacity`/`filter`;
tooltips, selections, and crosshairs receive live display and geometry; active
modebar controls expose `.xy-active`, `aria-pressed`, or `aria-expanded`.
Utilities still control their durable appearance, but overriding those inline
properties requires `!important` and also assumes responsibility for the
interaction state.

## Classes and Tailwind in Reflex

In a Reflex app, enable its Tailwind plugin once in `rxconfig.py`:

~~~python
import reflex as rx

config = rx.Config(
    app_name="dashboard",
    plugins=[
        rx.plugins.TailwindV4Plugin(config={"darkMode": "selector"}),
    ],
)
~~~

`darkMode="selector"` makes Tailwind's `dark:` utilities follow the `.dark`
class used by Reflex's manual color-mode switch. Omit that option when the
application intentionally wants Tailwind's default OS
`prefers-color-scheme` behavior instead.

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
    xy.x_axis(show=False),
    xy.y_axis(
        domain=(0, 80),
        show=False,
        grid=True,
        style={"grid_color": "#e2e8f0"},
    ),
    xy.legend(),
    class_name="text-slate-900 dark:text-zinc-100",
    class_names={
        "legend": "bg-transparent text-xs text-slate-600 dark:text-slate-300",
        "legend_label": "font-medium",
        "tooltip": "rounded-lg bg-zinc-950/90 px-3 py-2 text-white shadow-xl",
        "tooltip_label": "text-slate-400",
        "tooltip_value": "text-right font-semibold tabular-nums",
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

For charts produced from a token or `Var`, pass every possible complete
utility through the adapter's build-time inventory:

~~~python
LIVE_CHART_CLASSES = [
    "rounded-2xl border border-slate-200 dark:border-slate-800",
    "bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100",
    "hover:bg-slate-100 dark:hover:bg-slate-800",
]
live_chart = reflex_xy.chart(
    Dashboard.chart,
    tailwind_classes=LIVE_CHART_CLASSES,
    height="360px",
)
~~~

`tailwind_classes` accepts one string or an ordered iterable of strings and
exists only for Tailwind's compile-time source scan.
It never becomes a DOM attribute; mappings and unordered sets raise instead of
making generated source depend on key iteration or hash order. Static
Chart/Figure sources still discover their own classes automatically, and an
explicit inventory is merged with those discovered classes.

List every complete class that a state-driven figure can emit, not just the
classes in its initial state. When a live payload changes root or slot classes,
XY rebuilds its DOM chrome so the new class set replaces the old one while the
stable figure token remains mounted. The replacement preserves every named-axis
range and silently rehydrates durable box/range/lasso geometry before
refreshing the selection mask, so a theme swap does not replay callbacks or
erase durable viewport/selection state. Transient view-local UI state—such as
the selected drag tool, undo/redo history, legend toggles, and a manually moved
modebar—belongs to the replaced chrome and resets.

Advanced Tailwind v4 candidates are preserved verbatim through the scan
inventory, including quotes, backslashes, arbitrary properties, and Unicode
content:

~~~python
LIVE_CHART_CLASSES = [
    "before:content-['✓']",
    "[backdrop-filter:blur(6px)]",
    r"[&_[data-xy-slot=legend\_label]]:font-semibold",
]
~~~

Tailwind interprets an underscore inside an arbitrary variant as a space. Slot
names such as `legend_label` contain a real underscore, so escape it as `\_`
and use a raw Python string when writing a descendant selector. Prefer
`class_names={"legend_label": "font-semibold"}` when styling one slot directly;
the arbitrary selector form is useful when one root class needs to target
descendants.

Without `TailwindV4Plugin`, XY still places the names in the DOM but no Tailwind
utilities are generated, so the chart renders without those styles. An XY
standalone HTML export likewise carries the names but does not bundle Tailwind;
inject already-compiled rules with `custom_css` or use ordinary CSS for a
portable file.

## One tooltip, three styling approaches

All three examples target the tooltip container. The same mechanisms also
target `tooltip_title`, `tooltip_row`, `tooltip_label`, and `tooltip_value`.
Choose based on where the style originates; do not combine them unless you
intentionally want normal CSS cascade precedence.

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
        },
        "tooltip_row": {
            "display": "grid",
            "grid_template_columns": "7rem 1fr",
            "gap": 8,
        },
        "tooltip_label": {"color": "#94a3b8"},
        "tooltip_value": {"font_weight": 700, "text_align": "right"},
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

### What survives which export

Slot styling is a browser mechanism, and the native writers have no cascade to
apply it with. Rather than leave that to be discovered, it is a contract:

| You wrote | Browser (HTML, widget, Chromium capture) | Native PNG/JPEG/WebP | Native SVG/PDF |
| --- | --- | --- | --- |
| mark / axis `style=` | yes | yes | yes |
| chart-level `style=` (design tokens) | yes | yes | yes |
| `styles={slot: {...}}` | yes, all 29 slots | text subset, 9 slots | text subset, 9 slots |
| `class_names={slot: "..."}` | yes, all 29 slots | dropped | dropped |
| `custom_css=` | yes | raises | raises |
| `xy.legend(style=...)` | yes | 6 keys | 6 keys |
| `xy.colorbar(style=...)` | yes | dropped | dropped |

A per-slot `styles=` block reaches a file for the nine slots that name chrome a
file actually contains — `title`, `axis_title`, `tick_label`, the three legend
slots and the three colorbar slots — carrying `font-size`, `font-weight`,
`font-style`, `font-family`, `letter-spacing`, `opacity` and the text paint.
The rest are live-only chrome (`tooltip*`, `modebar*`, `crosshair_*`,
`selection`, `badge*`) with nothing in a file to paint. The native raster's
baked atlas is one face, so it honors a slot's size and paint and leaves the
typeface properties to the vector writers.

The `class_names` row is dropped rather than raising: raising would break every
native export of a chart that carries Tailwind classes for its live view, which
is the normal way to use both surfaces together — and a class name is the one
surface a file genuinely cannot honor, since it selects a rule out of a
stylesheet an export does not have. `custom_css` raises because there is no honest
partial application of an author stylesheet, and the error names
`Engine.chromium` as the fix.

A chart that must look identical on screen and in a PNG should carry its design
decisions in chart-level `style=` tokens and mark/axis `style=`, which every
renderer reads, and use slot classes only for things the browser alone shows —
tooltips, the modebar, hover chrome.

## Cascade and structural layout

Built-in visual rules live in the low-priority `base` cascade layer and use
zero-specificity `:where(...)`, so Tailwind's utility layer and ordinary
unlayered author selectors beat those visual defaults without `!important`.
That priority is not blanket: XY retains structural and conditional inline
styles for positioning, dimensions, visibility, z-index, and interaction
state. Avoid overriding those unless you intentionally take responsibility for
chart layout or behavior.

The chart root's default typography also lives in that base layer, so
`font-*`, `text-*`, and `leading-*` utilities on `class_name` work through the
normal cascade. An explicit chart `style={"font_family": ...}` or slot
`styles={...}` remains inline author intent and therefore wins over a normal
utility.

Responsive legend bounds and tooltip wrapping use the same layered,
zero-specificity visual defaults; their anchors and live placement remain
structural. Long legends become scrollable and edge tooltips wrap or flip
inside the chart.

Responsive utilities on DOM chrome react to media queries normally. A narrower
case needs care: canvas paint samples `--chart-bg`, `--chart-grid`,
`--chart-axis`, and the canvas use of `--chart-text` into renderer state.
OS color-scheme changes and mutations to an ancestor's `class`, `data-theme`,
or `style` refresh that state, but crossing a Tailwind breakpoint alone does
not. Pair responsive canvas-token changes with such a state mutation or a
figure rebuild; CSS-only tokens used by DOM chrome update immediately.

The `selection` slot reaches box/range rectangles and the completed lasso's SVG
path and editable handles. Use box-oriented background/border utilities for
rectangles and SVG `fill-*` / `stroke-*` utilities for the lasso nodes. XY keeps
the lasso path non-interactive and the handles draggable even if a shared
selection class contains `pointer-events-none`.

The `legend_swatch` slot lands on the visible chip wrapper. Solid/bar swatches
consume background and size utilities there; scatter and line SVG handles
inherit `fill-*`, `stroke-*`, stroke-width, and dash utilities from the same
wrapper. Renderer paint and geometry are private base-layer fallbacks, so those
utilities remain defeatable.

Annotation **labels** use `annotation_label`; canvas-painted arrow shafts,
markers, rules, and zones do not. Style those through their annotation props as
described in
[Customize Each Part](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients).
