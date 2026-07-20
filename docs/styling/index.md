---
title: Styling Overview
description: Choose between CSS/Tailwind chrome hooks, mark styles, theme tokens, and export CSS.
---

# Styling Overview

For ready-made light and dark treatments, browse the
[theme preset gallery](/docs/xy/styling/theme-presets/). For token-level
customization and precedence, see
[Themes and Tokens](/docs/xy/styling/themes-and-tokens/).

XY has two rendering surfaces. Chart chrome—titles, axis labels, legends,
tooltips, controls, and annotation labels—is DOM and participates in the normal
CSS cascade. Data marks are painted by WebGL, SVG, or the native rasterizer, so
XY compiles a deliberate CSS-property subset for them instead of claiming that
arbitrary browser selectors can reach a canvas.

## Choose the styling surface

Start with the thing you want to change. DOM chrome can use classes or arbitrary
safe DOM declarations; rendered geometry must use XY's validated mark or axis
vocabulary.

| Mechanism | Small example | Best for |
| --- | --- | --- |
| Chart root class | `class_name="rounded-xl border"` | Host layout, card chrome, and Tailwind utilities on one chart |
| Chart root style | `style={"--brand": "#6e56cf"}` | Root CSS declarations and custom variables |
| Theme component | `xy.theme(grid_color="#e2e8f0")` | Portable chart tokens shared by chrome and exports |
| Slot classes | `class_names={"tooltip": "rounded-lg"}` | Tailwind utilities or existing classes on stable DOM slots |
| Slot styles | `styles={"title": {"font_size": 18}}` | Computed inline DOM styles on stable slots |
| Component-local style | `xy.legend(class_name="text-xs")` | Keeping one legend, tooltip, colorbar, or modebar configuration self-contained |
| Mark style | `xy.line(..., style={"stroke-width": 3})` | Cross-renderer paint for lines, points, areas, bars, and grids |
| Annotation style | `xy.hline(5, style={"label_color": "red"})` | Annotation geometry and its DOM label |
| Export CSS | `chart.to_html(custom_css="...")` | Raw author CSS and attribute selectors in one browser export |

If you are unsure, use this shortcut:

- Styling a line, point, area, bar, or grid? Use its typed props or mark
  `style=`.
- Styling a title, legend, tooltip, control, tick label, or annotation label?
  Use a slot class/style or the component's local class/style.
- Styling the chart as a whole or defining reusable colors? Use chart
  `class_name`/`style` or `xy.theme()`.
- Styling only a self-contained HTML or Chromium export? Use `custom_css`.

~~~python demo exec
import reflex_xy
import xy

weeks = list(range(1, 13))
conversion = [3.2, 4.7, 4.1, 6.0, 5.4, 7.1, 6.7, 8.3, 7.8, 9.1, 8.7, 10.2]
traffic = [120, 180, 150, 260, 210, 340, 280, 420, 360, 510, 450, 620]

chart = xy.scatter_chart(
    xy.scatter(
        weeks,
        conversion,
        size=traffic,
        size_range=(8, 18),
        style={
            "fill": "var(--accent)",
            "fill-opacity": 0.88,
            "stroke": "#ffffff",
            "stroke-width": 2,
        },
        name="Weekly signal",
    ),
    xy.x_axis(label="week", tick_count=6),
    xy.y_axis(label="conversion (%)", domain=(2, 11)),
    xy.legend(loc="upper left"),
    class_name=(
        "rounded-xl border border-slate-200 bg-white text-slate-900 shadow-sm "
        "dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
    ),
    class_names={
        "tooltip": "rounded-lg bg-zinc-900/90 text-white shadow-xl",
        "legend": (
            "rounded-md border border-slate-200 bg-white/90 text-xs font-medium "
            "dark:border-zinc-700 dark:bg-zinc-900/90"
        ),
        "modebar_button": "hover:bg-zinc-200 dark:hover:bg-zinc-800",
    },
    styles={"title": {"font_size": 18, "letter_spacing": "0.02em"}},
    style={
        "--accent": "#6e56cf",
        "--chart-grid": "rgb(148 163 184 / 22%)",
    },
    padding=[48, 48, 54, 62],
    title="Weekly conversion signals",
)


def styling_overview_preview():
    return reflex_xy.chart(chart, height="340px")
~~~

## What “your styles win” means

XY's built-in **visual** chrome rules live in the low-priority `base` cascade
layer and use `:where(...)`, which has zero CSS specificity. A later utility
layer or ordinary unlayered author selector therefore overrides the default
background, color, padding, border, font, shadow, or cursor without
`!important`.

The promise is scoped to built-in visual defaults. XY still applies structural
inline layout—position, size, z-index, and interaction state—and an explicit
inline `styles[slot]` or per-annotation style naturally outranks a class. Marks
follow their compiled style contract rather than the DOM cascade.

## Styling troubleshooting

Start by identifying whether the thing you want to change is DOM chrome or a
rendered mark. Inspect titles, legends, tooltips, controls, ticks, and labels as
ordinary elements with `data-xy-slot`; style lines, areas, points, bars, and
other canvas geometry through typed props or mark `style=`.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Tailwind classes are present but have no effect | The utility was not emitted by the host's Tailwind build, or the Tailwind plugin is missing. | Enable Reflex's `TailwindV4Plugin`, keep fixed-chart classes literal, and follow [Classes and Tailwind in Reflex](/docs/xy/styling/chrome-slots/#classes-and-tailwind-in-reflex). |
| A custom font silently falls back | `font-family` names a face the browser has not loaded. | Register it in host CSS with `@font-face`, then apply the family to the chart root; see [Custom fonts and export limitations](/docs/xy/styling/themes-and-tokens/#custom-fonts-and-export-limitations). |
| A class changes the legend but not a line or point | Marks are WebGL/canvas geometry, not DOM nodes. | Use the mark's typed paint props or supported `style=` declarations from [Mark styles](/docs/xy/styling/mark-styles/). |
| Standalone HTML looks different from the application | The exported document cannot inherit the host page's stylesheet or design-system variables. | Put essential tokens on the chart and pass author rules with `to_html(custom_css=...)`. |
| Native PNG ignores CSS or a custom font | The native renderer does not run a browser cascade and uses XY's baked bitmap font. | Use `engine=Engine.chromium` with `custom_css` when browser CSS/font fidelity is required. |
| Axis titles or annotation labels are clipped | `overflow-hidden` is applied to the XY root or a tight ancestor. | Leave the chart root visible; apply intentional clipping to an outer wrapper and provide enough padding. |
| A responsive chart is blank or collapsed | `height="100%"` has no ancestor with a defined height, or the container initially measures zero. | Give the chart/component an explicit height while debugging; `width="100%"` can remain fluid. |
| A class loses to another declaration | Inline `styles`, component-local styles, or later author rules win through the normal cascade. | Remove the competing declaration or move the intended value to the same/higher-priority styling surface instead of adding `!important`. |

For build, export, and adapter failures beyond styling, continue with the
[Troubleshooting guide](/docs/xy/guides/troubleshooting/).

## Choose the next page

- [Styling gallery](/docs/xy/styling/gallery/) exercises every mark family,
  responsive shells, facets, reduction badges, custom host chrome, and
  categorical/time-axis treatments in live or XY-rendered examples.
- [Chrome slots](/docs/xy/styling/chrome-slots/) lists every stable DOM hook
  and shows the Tailwind workflow.
- [Component variations](/docs/xy/styling/component-variations/) shows built-in
  legends and tooltips, dual axes, reference lines, bands, and interaction
  chrome, and states the custom-component boundary.
- [Mark styles](/docs/xy/styling/mark-styles/) documents the compiled CSS
  subset, axis styles, validation, and canvas boundary.
- [Themes and tokens](/docs/xy/styling/themes-and-tokens/) defines reusable
  `--chart-*` variables and dark-mode patterns.
- [Recipes](/docs/xy/styling/recipes/) provides polished, ready-to-use chart
  treatments.
