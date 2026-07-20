---
title: Styling Overview
description: Choose between CSS/Tailwind chrome hooks, mark styles, theme tokens, and export CSS.
---

# Styling Overview

XY has two rendering surfaces. Chart chrome—titles, axis labels, legends,
tooltips, controls, and annotation labels—is DOM and participates in the normal
CSS cascade. Data marks are painted by WebGL, SVG, or the native rasterizer, so
XY compiles a deliberate CSS-property subset for them instead of claiming that
arbitrary browser selectors can reach a canvas.

~~~python demo exec toggle preview-code id=styling-overview-area-demo
import reflex_xy
import xy

months = [
    "Jan 23", "Feb 23", "Mar 23", "Apr 23", "May 23", "Jun 23",
    "Jul 23", "Aug 23", "Sep 23", "Oct 23", "Nov 23", "Dec 23",
]
solar_panels = [2890, 2756, 3322, 3470, 3475, 3129, 3490, 2903, 2643, 2837, 2954, 3239]
inverters = [2338, 2103, 2194, 2108, 1812, 1726, 1982, 2012, 2342, 2473, 3848, 3736]

overview_area = xy.area_chart(
    xy.area(
        months,
        solar_panels,
        name="Solar panels",
        color="#2b7fff",
        fill="linear-gradient(#2b7fff4d 5%, #2b7fff00 95%)",
        opacity=1,
        curve="linear",
        line_width=2,
    ),
    xy.area(
        months,
        inverters,
        name="Inverters",
        color="#00bc7d",
        fill="linear-gradient(#00bc7d4d 5%, #00bc7d00 95%)",
        opacity=1,
        curve="linear",
        line_width=2,
    ),
    xy.tooltip(title="{x}", format={"y": "$,.0f"}),
    xy.legend(show=False),
    xy.modebar(show=False),
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
        domain=(0, 4200),
        format="$,.0f",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.theme(
        plot_background="var(--overview-surface, #ffffff)",
        grid_color="var(--overview-grid, #e5e7eb)",
        text_color="var(--overview-text, #52525b)",
    ),
    class_name=(
        "bg-[#ffffff] text-[#52525b] [--overview-surface:#ffffff] "
        "[--overview-grid:#e5e7eb] [--overview-text:#52525b] "
        "dark:bg-[#000000] dark:text-[#d4d4d8] "
        "dark:[--overview-surface:#000000] dark:[--overview-grid:#27272a] "
        "dark:[--overview-text:#d4d4d8]"
    ),
    width="100%",
    height=320,
    padding=(62, 28, 48, 70),
)


def styling_overview_area_preview():
    return reflex_xy.chart(overview_area, height="320px")
~~~

## Customize by part

Start with the visible part you want to change. Each link opens the exact
section that owns it.

- **Fill, stroke, opacity, and gradients** — area, line, point, bar, and column
  paint. [Open section →](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients)
- **Axes, grid, and ticks** — axis lines, horizontal guides, tick marks, and
  tick text. [Open section →](/docs/xy/styling/customize/#axes,-grid,-and-ticks)
- **Color scales and colorbars** — continuous palettes, domains, ticks, and
  scale chrome. [Open section →](/docs/xy/styling/customize/#color-scales-and-colorbars)
- **Legend** — content, placement, swatches, and DOM styling.
  [Open section →](/docs/xy/styling/customize/#legend)
- **Tooltip** — fields, formatting, placement, and container styling.
  [Open section →](/docs/xy/styling/customize/#tooltip)
- **Annotations** — rules, bands, arrows, markers, and callouts.
  [Open section →](/docs/xy/styling/customize/#annotations)
- **Interaction chrome** — crosshair, selection, and toolbar controls.
  [Open section →](/docs/xy/styling/customize/#interaction-chrome)
- **Themes and Export** — reusable palettes, dark mode, fonts, and output
  behavior. [Open page →](/docs/xy/styling/themes-and-tokens/)

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

months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
core = [28, 31, 35, 38, 42, 46]
growth = [16, 18, 19, 23, 25, 29]
enterprise = [7, 8, 10, 12, 14, 17]
enterprise_base = [
    core_value + growth_value
    for core_value, growth_value in zip(core, growth, strict=True)
]

chart = xy.column_chart(
    xy.column(
        months,
        core,
        name="Core",
        color="#7c3aed",
    ),
    xy.column(
        months,
        growth,
        base=core,
        name="Growth",
        color="#db2777",
    ),
    xy.column(
        months,
        enterprise,
        base=enterprise_base,
        name="Enterprise",
        color="#fb7185",
        corner_radius=(6, 0),
    ),
    xy.tooltip(title="{x}", format={"y": "$,.0fK"}),
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
        domain=(0, 100),
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.legend(loc="upper left"),
    class_name="bg-white text-slate-900 dark:bg-black dark:text-zinc-100",
    class_names={
        "tooltip": "rounded-lg bg-zinc-900/90 text-white shadow-xl",
        "legend": (
            "rounded-md border border-slate-200 bg-white/90 text-xs font-medium "
            "dark:border-zinc-700 dark:bg-zinc-900/90"
        ),
        "modebar_button": "hover:bg-zinc-200 dark:hover:bg-zinc-800",
    },
    style={"--chart-grid": "#94a3b838"},
    padding=[48, 48, 54, 62],
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
| Tailwind classes are present but have no effect | The utility was not emitted by the host's Tailwind build, or the Tailwind plugin is missing. | Enable Reflex's `TailwindV4Plugin`, keep fixed-chart classes literal, and continue to [Customize Each Part](/docs/xy/styling/customize/). |
| A custom font silently falls back | `font-family` names a face the browser has not loaded. | Register it in host CSS with `@font-face`, then apply the family to the chart root; see [Custom fonts and export limitations](/docs/xy/styling/themes-and-tokens/#custom-fonts-and-export-limitations). |
| A class changes the legend but not a line or point | Marks are WebGL/canvas geometry, not DOM nodes. | Use the mark's typed paint props or supported `style=` declarations from [Customize Each Part](/docs/xy/styling/customize/). |
| Standalone HTML looks different from the application | The exported document cannot inherit the host page's stylesheet or design-system variables. | Put essential tokens on the chart and pass author rules with `to_html(custom_css=...)`. |
| Native PNG ignores CSS or a custom font | The native renderer does not run a browser cascade and uses XY's baked bitmap font. | Use `engine=Engine.chromium` with `custom_css` when browser CSS/font fidelity is required. |
| Axis titles or annotation labels are clipped | `overflow-hidden` is applied to the XY root or a tight ancestor. | Leave the chart root visible; apply intentional clipping to an outer wrapper and provide enough padding. |
| A responsive chart is blank or collapsed | `height="100%"` has no ancestor with a defined height, or the container initially measures zero. | Give the chart/component an explicit height; `width="100%"` can remain fluid. |
| A class loses to another declaration | Inline `styles`, component-local styles, or later author rules win through the normal cascade. | Remove the competing declaration or move the intended value to the same/higher-priority styling surface instead of adding `!important`. |

For build, export, and adapter failures beyond styling, continue with the
[Troubleshooting guide](/docs/xy/guides/troubleshooting/).

## The five styling destinations

- **Styling Overview** (you are here) — identify the rendering surface and
  choose the right styling mechanism.
- **Examples** — start from a polished, copyable chart or experiment with the
  interactive palette playground. [Open Examples →](/docs/xy/styling/examples/)
- **Customize Each Part** — change marks, axes, grid, color scales, legends,
  tooltips, annotations, and interaction chrome.
  [Open Customize Each Part →](/docs/xy/styling/customize/)
- **Themes and Export** — define reusable tokens, dark mode, fonts, and
  consistent HTML, SVG, or PNG output.
  [Open Themes and Export →](/docs/xy/styling/themes-and-tokens/)
- **Advanced Styling Gallery** — inspect specialized renderer paths,
  uncertainty, density, facets, and export edge cases.
  [Open Advanced Styling Gallery →](/docs/xy/styling/gallery/)
