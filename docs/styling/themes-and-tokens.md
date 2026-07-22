---
title: Themes and Export
description: Build reusable chart themes and keep colors, fonts, and chrome predictable across HTML, SVG, and PNG output.
---

# Themes and Export

Use this page when a visual system must travel beyond one chart. Start with
`xy.theme()` and reusable palette tokens, add light/dark host values, then pick
an export path based on whether the output can run a browser CSS cascade.

Use this page to:

- **Set chart-wide colors and chrome.**
  [Start with the theme component →](#start-with-the-theme-component)
- **Build and reuse a semantic palette.**
  [Open the palette example →](#build-a-reusable-palette)
- **Understand which declaration wins.**
  [Review style resolution →](#style-resolution-without-surprises)
- **Support the page's color mode.**
  [Review automatic dark mode →](#automatic-dark-mode-for-the-toolbar)
- **Use a brand font.**
  [Review custom-font behavior →](#custom-fonts-and-export-limitations)
- **Choose HTML, SVG, or PNG behavior.**
  [Compare output behavior →](#what-survives-each-output)

If you are still choosing a finished visual, start with
[Examples](/docs/xy/styling/examples/). To adjust a single mark, axis, legend,
tooltip, or annotation, use
[Customize Each Part](/docs/xy/styling/customize/). For density, uncertainty,
facets, and renderer edge cases, continue to the
[Advanced Gallery](/docs/xy/styling/gallery/).

## Start with the theme component

Use `xy.theme()` when the value belongs to the chart rather than one specific
mark. Its named arguments are readable aliases for the standard tokens: for
example, `plot_background` writes `--chart-bg`, while `grid_color` writes
`--chart-grid`.

~~~python demo exec toggle preview-code id=theme-chrome-area-demo
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
revenue = [32, 45, 41, 58, 63, 74]

# --- chart ---
import reflex_xy
import xy

chart = xy.area_chart(
    xy.area(
        months,
        revenue,
        name="Revenue",
        color="#f43f5e",
        fill="linear-gradient(#f43f5e4d 5%, #f43f5e00 95%)",
        opacity=1,
        curve="smooth",
        line_width=2,
    ),
    xy.legend(show=False),
    xy.tooltip(title="{x}", format={"y": "$,.0fK"}),
    # Keep horizontal guides only; omit axis chrome and tick text.
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
            "grid_width": 1,
            "grid_opacity": 1,
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_length": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.theme(
        plot_background="var(--demo-surface, #ffffff)",
        grid_color="var(--demo-grid, #e5e7eb)",
        axis_color="var(--demo-axis, #d1d5db)",
        text_color="var(--demo-text, #4b5563)",
    ),
    class_name=(
        "bg-[#ffffff] [--demo-surface:#ffffff] [--demo-grid:#e5e7eb] "
        "[--demo-axis:#d1d5db] [--demo-text:#4b5563] dark:bg-[#000000] "
        "dark:[--demo-surface:#000000] dark:[--demo-grid:#27272a] "
        "dark:[--demo-axis:#3f3f46] dark:[--demo-text:#d4d4d8]"
    ),
    width="100%",
    height=410,
    padding=(16, 20, 20, 20),
)


def theme_component_preview():
    return reflex_xy.chart(chart, height="410px")
~~~

The preview separates two kinds of values:

- `plot_background`, `grid_color`, `axis_color`, and `text_color` configure
  standard XY chrome through `xy.theme()`.
- The chart class supplies neutral light and dark hex values for the demo
  surface and chrome. The area keeps one saturated rose stroke and matching
  30%-to-transparent fade so the theme choices stay visually distinct.
- Axis components decide which chrome is drawn: both axes omit labels and tick
  marks, the x grid is disabled, and the y axis keeps only horizontal guides.

Keep a mark's stroke and fade stops on the same vivid hue:

~~~python
xy.area(
    x,
    y,
    color="#f43f5e",
    fill="linear-gradient(#f43f5e4d 5%, #f43f5e00 95%)",
    opacity=1,
    curve="smooth",
    line_width=2,
)
~~~

## Build a reusable palette

Application tokens are useful when several marks should move together. This
grouped column chart maps three semantic names to three colors; swapping the
values in `style=` restyles the whole preview without touching the marks.
Explicit numeric offsets and narrow columns leave a visible gap inside every
group.

~~~python demo exec toggle preview-code id=semantic-palette-columns-demo
months = ["Jan", "Feb", "Mar", "Apr"]
category_centers = list(range(len(months)))
series = [
    ("Primary", [42, 51, 58, 68], "var(--series-primary)", -0.24),
    ("Secondary", [28, 34, 39, 47], "var(--series-secondary)", 0.0),
    ("Accent", [16, 21, 25, 31], "var(--series-accent)", 0.24),
]

# --- chart ---
import reflex_xy
import xy

columns = [
    xy.column(
        [center + offset for center in category_centers],
        values,
        name=name,
        color=color,
        width=0.18,
        opacity=1,
        corner_radius=4,
        stroke_width=0,
    )
    for name, values, color, offset in series
]

palette_chart = xy.column_chart(
    *columns,
    xy.legend(loc="upper left", ncols=3),
    xy.tooltip(title="Monthly totals", format={"y": ",.0fK"}),
    xy.x_axis(
        domain=(-0.5, 3.5),
        tick_values=category_centers,
        tick_labels=months,
        tick_label_strategy="none",
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
        plot_background="var(--palette-surface, #ffffff)",
        grid_color="var(--palette-grid, #e5e7eb)",
        axis_color="#00000000",
        text_color="var(--palette-text, #4b5563)",
        style={
            "--series-primary": "#2b7fff",
            "--series-secondary": "#8e51ff",
            "--series-accent": "#fe9a00",
        },
    ),
    class_name=(
        "bg-[#ffffff] [--palette-surface:#ffffff] [--palette-grid:#e5e7eb] "
        "[--palette-text:#4b5563] dark:bg-[#000000] "
        "dark:[--palette-surface:#000000] dark:[--palette-grid:#27272a] "
        "dark:[--palette-text:#d4d4d8]"
    ),
)


def semantic_palette_preview():
    return reflex_xy.chart(palette_chart, height="320px")
~~~

## Style resolution without surprises

Think from the narrowest styling surface to the broadest:

1. **Typed mark or axis props** describe rendered geometry and paint.
2. **Component-local `style=`** customizes one legend, tooltip, modebar, or
   annotation label.
3. **Chart `styles={slot: ...}` and `class_names={slot: ...}`** apply a shared
   rule to that chrome slot.
4. **`xy.theme()` and chart-root `style=`** define chart-wide tokens and root
   appearance.
5. **Host CSS** supplies inherited defaults, application tokens, and color-mode
   values in a browser.

That list is a **scope ladder**, not one universal cascade. Marks and axes are
painted geometry, while legends and tooltips are DOM chrome. When two
declarations target the same property, use these concrete winner rules:

| Target | Strongest to weakest |
| --- | --- |
| Mark paint | Mark `style={"fill"/"stroke": ...}` → typed paint prop such as `fill=`, `color=`, or `line_width=` → resolved token or palette default |
| Axis paint | Axis `style={...}` → chart-local theme token → token inherited from host CSS → built-in default |
| One DOM chrome component | Component `style=` → chart `styles={slot: ...}` → ordinary class/host rule → inherited theme token |
| Chart-root token | Chart `style=` → last `xy.theme()` → earlier `xy.theme()` → token inherited from a host ancestor → built-in default |

Component `style=` and chart `styles=` become inline DOM styles. The component
is merged last, so it wins for the same property. Classes and normal host CSS
remain ideal for shared or stateful styling, but they do not override an inline
declaration unless the host deliberately uses `!important`. A CSS variable is
resolved where it is used: `color="var(--series-primary)"` does not make host
CSS stronger than a chart-local `--series-primary` declaration.

For example, the mark is violet, the legend is compact, and the chart-root
token is amber:

~~~python
chart = xy.area_chart(
    xy.area(
        x,
        y,
        color="#2b7fff",                    # typed blue
        style={"stroke": "#8e51ff"},       # mark style wins: violet
    ),
    xy.legend(style={"font_size": 12}),     # wins over the slot's 14px
    xy.theme(style={"--series-primary": "#2b7fff"}),
    styles={"legend": {"font_size": 14}},
    style={"--series-primary": "#fe9a00"}, # chart root wins: amber
)
~~~

Use typed props for readable geometry, component styles for one-off chrome,
chart slots for reusable chrome rules, and theme tokens for values that should
move together across the whole chart.

### Where should a token be set?

| Goal | Recommended location |
| --- | --- |
| Keep browser, SVG, and PNG exports consistent | `xy.theme(...)` or chart-root `style={...}` |
| Share a palette across many browser charts | CSS variables on a common host ancestor |
| Let Reflex state choose a palette | Resolve the state to a chart class or `style` mapping |
| Change only one mark | Use the mark's `color`, `fill`, `stroke`, or `style` directly |

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
chart = xy.area_chart(
    xy.area(
        [0, 1, 2],
        [2, 5, 3],
        color="var(--chart-accent)",
        fill="linear-gradient(currentColor, transparent)",
    ),
    class_name="analytics-theme",
)
~~~

In Reflex, resolve reactive theme choices into ordinary classes, styles, or CSS
variables. XY does not duplicate Reflex conditions or application state.

## What survives each output

Browser-backed output can run a CSS cascade; browser-free output cannot. Put
export-critical paint and tokens on the chart itself, then use host CSS for
browser-only adaptation.

| Output | Typed mark/axis paint | Chart theme and root style | Component and slot chrome | Host CSS | Dark mode |
| --- | --- | --- | --- | --- | --- |
| Live browser / Reflex | Full | Full | Full component styles, slot styles, and classes | Full host cascade | Adaptive while the page is open |
| Standalone HTML | Full | Full | Full serialized component and slot styling | Only CSS included with `custom_css` | Adaptive through included class or media rules |
| Python `to_svg()` | Full validated static surface | Chart-local tokens and `var()` fallbacks | Supported static chrome fields; no general slot-class cascade | No | One resolved state |
| Native PNG | Full validated static surface | Chart-local tokens and `var()` fallbacks | Supported static chrome fields; no general slot-class cascade | No | One resolved state |
| Chromium PNG | Full | Full | Full serialized component and slot styling | Only CSS included with `custom_css` | Evaluated at capture time, then frozen |

“Supported static chrome fields” means options the SVG/native renderer owns,
such as axes and the built-in legend. It does not mean arbitrary DOM CSS or
Tailwind classes are evaluated without a browser. Browser-only color
expressions may also need a concrete fallback for SVG or native PNG:
`var(--accent, #8e51ff)`.

The toolbar’s client PNG and SVG actions are a separate browser snapshot path:
they read the live chart’s computed tokens and font styles, so inherited host
styling is captured at download time. Python `to_svg()` and native `to_png()`
never inspect the host page. Chromium `to_png()` renders standalone HTML, so
pass any required author rules explicitly with `custom_css`.

For exporter selection, engine arguments, and complete code examples, see
[Display and Export](/docs/xy/guides/display-and-export/).

## Custom fonts and export limitations

Browser charts inherit fonts from the chart root. Load the font in the host
application first, then set `font_family` through chart `style=` or apply a
class that defines `font-family`. The live example uses a system serif so it
does not depend on a network font; replace that stack with the family your host
loads.

~~~python demo exec toggle preview-code id=custom-font-columns-demo
quarters = ["Q1", "Q2", "Q3", "Q4", "Q5"]
revenue = [3, 6, 4, 8, 7]

# --- chart ---
import reflex_xy
import xy

font_chart = xy.column_chart(
    xy.column(
        quarters,
        revenue,
        name="Revenue",
        color="#8e51ff",
        width=0.56,
        opacity=1,
        stroke_width=0,
        corner_radius=(6, 0),
    ),
    xy.legend(),
    xy.tooltip(),
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
        plot_background="var(--font-surface, #ffffff)",
        grid_color="var(--font-grid, #e5e7eb)",
        axis_color="#00000000",
        text_color="var(--font-text, #4b5563)",
    ),
    class_name=(
        "bg-[#ffffff] [--font-surface:#ffffff] [--font-grid:#e5e7eb] "
        "[--font-text:#4b5563] dark:bg-[#000000] "
        "dark:[--font-surface:#000000] dark:[--font-grid:#27272a] "
        "dark:[--font-text:#d4d4d8]"
    ),
    style={"font_family": "Georgia, 'Times New Roman', serif"},
    styles={
        "legend": {"font_style": "italic"},
    },
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
chart = xy.area_chart(
    xy.area(
        [0, 1, 2],
        [2, 5, 3],
        fill="linear-gradient(currentColor, transparent)",
    ),
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
