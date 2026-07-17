---
title: Themes and Tokens
description: Theme chart chrome and rendered marks with cascading CSS custom properties.
---

# Themes and Tokens

XY routes its default chrome colors through `--chart-*` CSS custom properties.
Set common tokens with `theme()`, add any token through chart/theme `style=`, or
let a host application's CSS cascade them from an ancestor.

## Theme component

~~~python
import xy

chart = xy.line_chart(
    xy.line(
        [0, 1, 2, 3],
        [2, 5, 3, 8],
        style={"stroke": "var(--chart-accent)", "stroke-width": 2.5},
    ),
    xy.theme(
        plot_background="#ffffff",
        grid_color="#e2e8f0",
        axis_color="#64748b",
        text_color="#1e293b",
        style={"--chart-accent": "#6e56cf"},
    ),
)
~~~

`plot_background`, `grid_color`, `axis_color`, `text_color`,
`crosshair_color`, `selection_color`, and `selection_fill` are readable aliases
for their CSS tokens. Later theme values override earlier theme values, and the
chart's own `style=` is the final root-level override.

## Token reference

| Token | Surface | Default behavior |
| --- | --- | --- |
| `--chart-bg` | Plot background | transparent |
| `--chart-text` | Titles, ticks, legend, labels | inherited text color |
| `--chart-grid` | Canvas grid lines | current color at low opacity |
| `--chart-axis` | Axis lines and ticks | current color at medium opacity |
| `--chart-tooltip-bg` / `--chart-tooltip-text` | Tooltip | dark translucent / white |
| `--chart-legend-bg` | Legend background | faint neutral fill |
| `--chart-badge-bg` / `--chart-badge-text` | Reduction badges | light / dark |
| `--chart-modebar-bg` / `--chart-modebar-active` | Toolbar and active button | light translucent / neutral |
| `--chart-selection` / `--chart-selection-fill` | Selection outline/fill | blue outline / translucent blue |
| `--chart-zoom-selection` / `--chart-zoom-selection-fill` | Box-zoom outline/fill | neutral outline/fill |
| `--chart-crosshair` | Crosshair lines | translucent dark |
| `--chart-annotation-text` | Annotation labels | falls back to `--chart-text` |
| `--chart-cursor` / `--chart-cursor-pan` | Plot cursors | `crosshair` / `grab` |
| `--chart-focus` | Keyboard focus outline | blue |

You can define application-specific variables such as `--chart-accent` and use
them from mark styles. XY validates the `var(...)` shape, then the browser
resolves it against the chart root on each render.

## Cascading from host CSS

~~~css
.analytics-theme {
  --chart-bg: transparent;
  --chart-text: #e5e7eb;
  --chart-grid: rgb(255 255 255 / 12%);
  --chart-axis: rgb(255 255 255 / 50%);
  --chart-tooltip-bg: #0b1220;
  --chart-tooltip-text: #f8fafc;
  --chart-accent: #a78bfa;
}
~~~

~~~python
chart = xy.line_chart(
    xy.line([0, 1, 2], [2, 5, 3], style={"stroke": "var(--chart-accent)"}),
    class_name="analytics-theme",
)
~~~

In Reflex, resolve reactive theme choices into ordinary classes, styles, or CSS
variables. XY does not duplicate Reflex conditions or application state.

## Dark mode in a standalone export

~~~python
chart.to_html(
    "chart.html",
    custom_css="""
      .xy { --chart-accent: #6e56cf; }
      @media (prefers-color-scheme: dark) {
        .xy {
          --chart-bg: #0f172a;
          --chart-text: #e2e8f0;
          --chart-grid: rgb(226 232 240 / 12%);
          --chart-axis: rgb(226 232 240 / 55%);
          --chart-accent: #a78bfa;
        }
      }
    """,
)
~~~

Standalone HTML and Chromium PNG use the browser cascade. Native PNG and SVG
can resolve variables declared on the chart's own `style`/`theme` plus
`var(--name, fallback)` values, but they cannot see an external host page's
stylesheet. Put export-critical tokens on the chart itself when output must be
identical outside the browser host.
