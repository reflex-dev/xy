---
title: Themes and Tokens
description: Theme chart chrome and rendered marks with cascading CSS custom properties.
---

# Themes and Tokens

XY routes its default chrome colors through `--chart-*` CSS custom properties.
Set common tokens with `theme()`, add any token through chart/theme `style=`, or
let a host application's CSS cascade them from an ancestor.

## Built-in presets

Choose a complete visual treatment with `preset`. XY includes `xy`, `minimal`,
`dashboard`, `publication`, and `high_contrast`. The other high-level knobs are
independent: `color_scheme` chooses `light`, `dark`, or `system`; `palette`
chooses the default series and categorical colors; `accent` controls selection,
focus, and active emphasis; and `contrast` chooses `normal` or accessible
`high` contrast.

~~~python demo exec
import reflex_xy
import xy

preset_chart = xy.line_chart(
    xy.line([1, 2, 3, 4], [4, 7, 5, 9], name="Revenue"),
    xy.scatter([1, 2, 3, 4], [3, 5, 6, 8], name="Forecast"),
    xy.legend(),
    xy.theme(
        preset="dashboard",
        color_scheme="dark",
        palette="vibrant",
        accent="#8b5cf6",
        contrast="normal",
    ),
    title="Quarterly outlook",
)


def built_in_preset_preview():
    return reflex_xy.chart(preset_chart, height="320px")
~~~

Discover names programmatically with `xy.theme_presets()` and
`xy.theme_palettes()`. See every built-in treatment in the
[theme preset gallery](/docs/xy/styling/theme-presets/). Matplotlib-compatible
stylesheet names remain a separate compatibility surface under
`xy.pyplot.style`.

Theme values resolve in this order, with each later layer winning:

1. XY engine defaults
2. Preset
3. Color scheme
4. Palette, accent, and contrast
5. Named low-level theme arguments
6. `theme(style={...})`
7. Chart-level `style={...}`

Explicit mark colors and palettes override all theme defaults. This makes it
safe to customize any low-level token on top of a preset, for example
`xy.theme(preset="dashboard", grid_color="#ffffff14",
style={"--chart-tooltip-bg": "#09090b"})`.

With `color_scheme="system"`, browser charts follow
`prefers-color-scheme`. Browser-free SVG and native PNG exports, as well as
headless Chromium export, deterministically use the light variant. Pass
`color_scheme="dark"` explicitly when exporting dark output.

## Start with the theme component

Use `xy.theme()` when the value belongs to the chart rather than one specific
mark. Its named arguments are readable aliases for the standard tokens: for
example, `plot_background` writes `--chart-bg`, while `grid_color` writes
`--chart-grid`.

~~~python demo exec
import reflex_xy
import xy

chart = xy.line_chart(
    xy.line(
        ["Jan", "Feb", "Mar", "Apr"],
        [2, 5, 3, 8],
        name="Revenue",
        color="var(--series-primary, #6e56cf)",
        width=2.5,
    ),
    xy.legend(loc="upper left"),
    xy.tooltip(title="{x}", format={"y": ".1f"}),
    xy.theme(
        plot_background="var(--secondary-2)",
        grid_color="var(--secondary-a5)",
        axis_color="var(--secondary-a8)",
        text_color="var(--secondary-11)",
        # Custom variables belong in style and can be reused by marks.
        style={"--series-primary": "var(--primary-9)"},
    ),
    class_name="bg-secondary-2 text-secondary-11",
    style={"background": "var(--secondary-2)"},
    title="Monthly revenue",
)


def theme_component_preview():
    return reflex_xy.chart(chart, height="320px")
~~~

There are two kinds of values in this example:

- `plot_background`, `grid_color`, `axis_color`, and `text_color` configure
  standard XY chrome.
- `--series-primary` is an application token. XY does not assign it a meaning;
  the line opts into it with `var(--series-primary)`.

Use a fallback when a custom variable may not be defined by every host:

~~~python
xy.line(
    x,
    y,
    color="var(--series-primary, #6e56cf)",
)
~~~

## Where should a token be set?

| Goal | Recommended location |
| --- | --- |
| Keep browser, SVG, and PNG exports consistent | `xy.theme(...)` or chart `style={...}` |
| Share a palette across many browser charts | CSS variables on a common host ancestor |
| Let Reflex state choose a palette | Resolve the state to a chart class or `style` mapping |
| Change only one mark | Use the mark's `color`, `fill`, `stroke`, or `style` directly |

If the same token is set in more than one place, XY resolves it in this order:

1. A chart inherits the host ancestor's value when it has no local value.
2. `xy.theme()` writes a local chart value; later theme components win over
   earlier ones.
3. The chart's own `style=` mapping is the final XY-level override.

For example, this line is red because chart `style=` wins over the earlier
theme value:

~~~python
chart = xy.line_chart(
    xy.line([0, 1, 2], [2, 5, 3], color="var(--series-primary)"),
    xy.theme(style={"--series-primary": "#2563eb"}),  # blue default
    style={"--series-primary": "#dc2626"},  # final red override
)
~~~

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
| `--chart-modebar-bg` / `--chart-modebar-active` | Toolbar and active button | light or dark translucent (follows a `.dark` root class) / neutral |
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
  --chart-tooltip-bg: #09090b;
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

## What survives each output

Browser-backed output can preserve computed host styling that browser-free
exporters cannot evaluate. Use this table when choosing where to define a
visual treatment:

| Styling surface | Browser / HTML | Toolbar PNG / SVG | Python SVG | Native PNG |
| --- | --- | --- | --- | --- |
| Theme tokens | Yes | Yes | Resolved subset | Resolved subset |
| Slot classes and CSS | Yes | Computed snapshot | No | No |
| Mark styles | Yes | Yes | Yes | Yes |
| Custom fonts | Host-loaded | Usually | Limited | Bitmap fallback |
| Custom `render=` chrome | Adapter-dependent | Adapter-dependent | No | No |

“Resolved subset” means the browser-free exporter understands the tokens it
uses directly, but it does not run a general CSS cascade. “Computed snapshot”
means the toolbar export reads the live chart’s computed browser styles at the
moment of export. For exporter selection and code examples, see
[Display and Export](/docs/xy/guides/display-and-export/).

## Custom fonts and export limitations

Browser charts inherit fonts from the chart root. Load the font in the host
application first, then set `font_family` through chart `style=` or apply a
class that defines `font-family`. The live example uses a system serif so it
does not depend on a network font; replace that stack with the family your host
loads.

~~~python demo exec
import reflex_xy
import xy

font_chart = xy.line_chart(
    xy.line(
        [0, 1, 2, 3, 4],
        [3, 6, 4, 8, 7],
        name="Revenue",
        color="#7c3aed",
        width=2.5,
        curve="smooth",
    ),
    xy.legend(),
    xy.tooltip(),
    xy.x_axis(label="quarter"),
    xy.y_axis(label="revenue"),
    style={"font_family": "Georgia, 'Times New Roman', serif"},
    styles={
        "title": {"font_weight": 700, "letter_spacing": "0.02em"},
        "legend": {"font_style": "italic"},
    },
    title="Host font family",
)


def custom_font_preview():
    return reflex_xy.chart(font_chart, height="320px")
~~~

For a downloaded or self-hosted font, define `@font-face` in the Reflex
application's global stylesheet and use the same family on the chart:

~~~css
@font-face {
  font-family: "Acme Sans";
  src: url("/fonts/acme-sans.woff2") format("woff2");
  font-display: swap;
}

.xy-font-brand {
  font-family: "Acme Sans", system-ui, sans-serif;
}
~~~

~~~python
chart = xy.line_chart(
    xy.line([0, 1, 2], [2, 5, 3]),
    class_name="xy-font-brand",
)
~~~

Tailwind users can apply a configured font utility through `class_name` in the
same way. XY does not download, register, or rewrite font files itself.

Standalone HTML and Chromium PNG accept the font declaration through
`custom_css`. Embed the font as a data URL when the HTML file must remain fully
portable; an ordinary URL still depends on that resource being reachable.

~~~python
from xy import Engine

font_css = """
  @font-face {
    font-family: "Acme Sans";
    src: url("data:font/woff2;base64,...") format("woff2");
  }
  .xy { font-family: "Acme Sans", system-ui, sans-serif; }
"""

chart.to_html("chart.html", custom_css=font_css)
chart.to_png(
    "chart.png",
    engine=Engine.chromium,
    custom_css=font_css,
)
~~~

| Output | Custom-font behavior |
| --- | --- |
| Live browser / Reflex | Uses a font already loaded by the host page. |
| Toolbar PNG | Captures the browser-rendered font into pixels. |
| Toolbar SVG | Preserves the computed family and font styles, but does not embed the font file. |
| Standalone HTML | Supports `@font-face` and root `font-family` through `custom_css`. |
| Chromium PNG | Supports the same browser CSS through `custom_css`. |
| Native PNG | Uses XY's baked bitmap font; custom fonts are not supported. |
| Python `to_svg()` | Uses XY's fixed system font stack and cannot embed a custom font. |

## Automatic dark mode for the toolbar

The interactive toolbar (modebar) has no colored default a page can show
through, so it reads the light/dark state straight from your page: when a
`.dark` class is present on the chart root or any ancestor — the convention
Reflex (next-themes), Radix Themes, and Tailwind all set on the root `<html>`
element — its background, border, and shadow switch to a dark palette. Icon
color already follows the inherited text color, so the toolbar stays readable in
both modes with no configuration. An explicit `.light` class (or no class at
all) keeps the light palette.

That is only the built-in default. A `--chart-modebar-bg` or
`--chart-modebar-active` value you set — through `theme()`, chart `style=`, or a
host stylesheet — still wins in either mode, so mapping the toolbar onto your
own adaptive design tokens (for example Radix's `--secondary-2`) replaces the
automatic palette entirely.

## Dark mode in a standalone export

~~~python
chart.to_html(
    "chart.html",
    custom_css="""
      .xy { --chart-accent: #6e56cf; }
      @media (prefers-color-scheme: dark) {
        .xy {
          --chart-bg: #18181b;
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
