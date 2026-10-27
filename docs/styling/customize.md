---
title: Customize Each Part
description: Style marks, axes, color scales, legends, tooltips, annotations, and interaction chrome with the right XY API.
---

# Customize Each Part

Start with the part you want to change. Data marks and axis geometry use XY's
validated renderer-neutral style vocabulary. Colorbars, legends, tooltips,
controls, and annotation labels are DOM chrome and also accept component or
slot styles.

| Part | Use |
| --- | --- |
| Area, line, point, or bar paint | Typed mark props or mark `style=` |
| Grid, axis line, ticks, or tick text | `x_axis(...)` / `y_axis(...)` |
| Continuous color scale and colorbar | Mark `colormap=` / `domain=`, then `xy.colorbar(...)` |
| Built-in legend or tooltip | The component's `class_name` / `style`, or chart slots |
| Rules, bands, arrows, and callouts | Annotation geometry props plus label `style` |
| Crosshair, selection, and toolbar | `interaction_config`, `modebar`, theme tokens, or slots |

## Fill, stroke, opacity, and gradients

Marks are rendered geometry rather than DOM nodes. Use typed props for common
choices, or the mark's validated `style=` mapping when CSS-shaped paint is
clearer. Unsupported properties raise while the chart is built instead of
silently disappearing in one renderer.

~~~python demo exec toggle preview-code id=customize-mark-paint-demo
x = [0, 1, 2, 3, 4, 5]
y = [22, 31, 29, 44, 51, 63]

# --- chart ---
import reflex_xy
import xy


def customize_mark_paint_preview():
    chart = xy.area_chart(
        xy.area(
            x,
            y,
            name="Revenue",
            style={
                "fill": "linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
                "fill-opacity": 1,
                "stroke": "#8e51ff",
                "stroke-width": 2,
            },
            opacity=1,
            curve="smooth",
        ),
        xy.tooltip(title="Period {x}", format={"y": "$,.0fK"}),
        xy.legend(show=False),
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
            domain=(0, 70),
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
            plot_background="var(--custom-surface, #ffffff)",
            grid_color="var(--custom-grid, #e5e7eb)",
            text_color="var(--custom-text, #6a7282)",
        ),
        class_name=(
            "bg-[#ffffff] [--custom-surface:#ffffff] [--custom-grid:#e5e7eb] "
            "[--custom-text:#6a7282] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--custom-grid:#27272a] "
            "dark:[--custom-text:#d4d4d8]"
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

Use `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, and
`opacity` only on mark families that support them. Lines use stroke properties;
areas, points, bars, and columns also support fill properties. Bar-like marks
add `border-radius`. `line`, `step`, `stairs`, and `ecdf` add
`stroke-dasharray` and `stroke-linecap`; `area` adds `stroke-dasharray` only,
because a cap is open-path geometry. `scatter` adds `marker-shape`.

`stroke-linecap` (`butt`, `round`, `square`) carries its standard SVG meaning,
and XY defaults it to `round` rather than to the CSS initial value — the native
rasterizer has always drawn round caps and it is the reference for static
export. `marker-shape` is the CSS spelling of `symbol=` and takes any of the 17
built-in marker names.

~~~python
xy.line(x, y, style={"stroke-width": "6px", "stroke-linecap": "butt"})
xy.scatter(x, y, size=12, style={"marker-shape": "diamond"})
~~~

## Axes, grid, and ticks

Treat the x and y axes independently. Grid lines are owned by the axis they
cross: the y axis draws horizontal guides and the x axis draws vertical ones.
Axis baselines, tick marks, tick text, and titles are separate style properties,
so hiding one never requires hiding the others.

### Customize horizontal grid lines

Keep the y-axis grid and turn off the x-axis grid for a calm reporting chart.
`grid_color`, `grid_width`, `grid_dash`, and `grid_opacity` style the guides;
the remaining zero-width and transparent properties remove the baseline and
ticks without removing the horizontal grid.

~~~python demo exec toggle preview-code id=customize-horizontal-grid-demo
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul"]
revenue = [38, 46, 43, 57, 54, 65, 72]

# --- chart ---
import reflex_xy
import xy


def customize_horizontal_grid_preview():
    chart = xy.area_chart(
        xy.area(
            months,
            revenue,
            name="Revenue",
            color="#00b8db",
            fill="linear-gradient(#00b8db4d 5%, #00b8db00 95%)",
            opacity=1,
            line_width=2,
            curve="smooth",
        ),
        xy.x_axis(
            tick_label_strategy="none",
            style={
                "grid_opacity": 0,
                "axis_color": "#00000000",
                "axis_width": 0,
                "tick_color": "#00000000",
                "tick_width": 0,
            },
        ),
        xy.y_axis(
            tick_label_strategy="off",
            style={
                "grid_color": "var(--axis-grid, #e5e7eb)",
                "grid_width": 1,
                "grid_dash": "solid",
                "grid_opacity": 0.9,
                "axis_color": "#00000000",
                "axis_width": 0,
                "tick_color": "#00000000",
                "tick_width": 0,
                "tick_label_color": "#00000000",
            },
        ),
        xy.legend(show=False),
        xy.tooltip(title="{x}", format={"y": "$,.0fK"}),
        xy.theme(plot_background="var(--custom-surface, #ffffff)"),
        class_name=(
            "bg-[#ffffff] [--custom-surface:#ffffff] [--axis-grid:#e5e7eb] "
            "dark:bg-[#000000] dark:[--custom-surface:#000000] "
            "dark:[--axis-grid:#27272a]"
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

Use `"solid"`, `"dashed"`, `"dotted"`, or `"dashdot"` for `grid_dash`.
Setting `grid_opacity=0` is the direct way to disable one direction of grid.

### Customize the axis line, ticks, and tick text

This column chart keeps a deliberate bottom axis. The baseline uses
`axis_color` and `axis_width`; tick marks use `tick_color`, `tick_width`, and
`tick_length`; the month text uses `tick_label_color`. The y axis remains
visually quiet while still drawing horizontal guides.

~~~python demo exec toggle preview-code id=customize-axis-details-demo
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
orders = [32, 47, 41, 58, 54, 68]

# --- chart ---
import reflex_xy
import xy


def customize_axis_details_preview():
    chart = xy.column_chart(
        xy.column(
            months,
            orders,
            name="Orders",
            color="#00bc7d",
            corner_radius=(5, 0),
            stroke_width=0,
        ),
        xy.x_axis(
            style={
                "grid_opacity": 0,
                "axis_color": "var(--axis-accent, #00bc7d)",
                "axis_width": 2,
                "tick_color": "var(--axis-accent, #00bc7d)",
                "tick_width": 2,
                "tick_length": 6,
                "tick_label_color": "var(--axis-text, #4b5563)",
            },
        ),
        xy.y_axis(
            tick_label_strategy="none",
            style={
                "grid_color": "var(--axis-grid, #e5e7eb)",
                "grid_width": 1,
                "axis_color": "#00000000",
                "axis_width": 0,
                "tick_color": "#00000000",
                "tick_width": 0,
            },
        ),
        xy.legend(show=False),
        xy.tooltip(title="{x}", format={"y": ",.0f"}),
        xy.theme(plot_background="var(--custom-surface, #ffffff)"),
        class_name=(
            "bg-[#ffffff] [--custom-surface:#ffffff] [--axis-grid:#e5e7eb] "
            "[--axis-accent:#00bc7d] [--axis-text:#4b5563] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--axis-grid:#27272a] "
            "dark:[--axis-accent:#00d492] dark:[--axis-text:#d4d4d8]"
        ),
        padding=(24, 24, 48, 24),
    )
    return reflex_xy.chart(chart, height="330px")
~~~

Add `label="Month"` and `label_color` only when the axis title adds information
that the surrounding heading does not already provide. `tick_label_strategy`
controls collisions independently: use `"rotate"`, `"stagger"`, `"hide"`, or
`"none"` for dense categorical axes.

### Clean dashboard axes

For compact dashboard charts, remove both baselines, ticks, and tick text;
disable the x grid; and retain only the y grid. This is the same quiet axis
treatment used by the product-ready examples, shown here with two vivid series
and a compact stroke-shaped legend.

~~~python demo exec toggle preview-code id=customize-clean-dashboard-axis-demo
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
direct = [34, 41, 39, 52, 48, 59, 56, 69]
partner = [22, 28, 34, 31, 39, 44, 53, 61]

# --- chart ---
import reflex_xy
import xy


def customize_clean_dashboard_axis_preview():
    chart = xy.area_chart(
        xy.area(
            months,
            direct,
            name="Direct",
            color="#8e51ff",
            fill="linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
            opacity=1,
            line_width=2,
            curve="smooth",
        ),
        xy.area(
            months,
            partner,
            name="Partner",
            color="#2b7fff",
            fill="linear-gradient(#2b7fff4d 5%, #2b7fff00 95%)",
            opacity=1,
            line_width=2,
            curve="smooth",
        ),
        xy.x_axis(
            tick_label_strategy="none",
            style={
                "grid_opacity": 0,
                "axis_color": "#00000000",
                "axis_width": 0,
                "tick_color": "#00000000",
                "tick_width": 0,
            },
        ),
        xy.y_axis(
            tick_label_strategy="none",
            style={
                "grid_color": "var(--axis-grid, #e5e7eb)",
                "grid_width": 1,
                "axis_color": "#00000000",
                "axis_width": 0,
                "tick_color": "#00000000",
                "tick_width": 0,
            },
        ),
        xy.legend(
            loc="upper right",
            ncols=2,
            style={"background": "transparent", "border": 0, "box-shadow": "none"},
        ),
        xy.tooltip(title="{x}", format={"y": ",.0f"}),
        xy.theme(
            plot_background="var(--custom-surface, #ffffff)",
            grid_color="var(--axis-grid, #e5e7eb)",
        ),
        styles={
            "legend_item": {"gap": 8, "padding": 0},
            "legend_swatch": {"width": 24, "height": 3, "border-radius": 999},
        },
        class_name=(
            "bg-[#ffffff] py-3 sm:py-4 [--custom-surface:#ffffff] "
            "[--axis-grid:#e5e7eb] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--axis-grid:#27272a]"
        ),
        padding=(58, 24, 24, 24),
    )
    return reflex_xy.chart(chart, height="340px")
~~~

The reusable recipe is: `tick_label_strategy="none"`, transparent axis and
tick colors with zero widths on both axes, `grid_opacity=0` on the x axis, and
a subtle `grid_color` on the y axis. Keep extra top padding when a legend sits
inside the plot.

### Hide axis chrome with a switch

Because hiding axis parts is subtraction, each axis takes plain switches
instead of transparent colors: `show`, `line`, `ticks`, `grid`, and `text`
(tick labels plus the axis title). `show` sets the other four, and each of them
overrides `show`, so the reporting look above is two lines.

| Want | Write |
| --- | --- |
| No axis chrome at all | `xy.x_axis(show=False)` |
| Horizontal guides only | `xy.y_axis(show=False, grid=True)` |
| Labels, but no baseline or ticks | `xy.x_axis(line=False, ticks=False)` |
| Everything except the grid | `xy.x_axis(grid=False)` |

~~~python
chart = xy.area_chart(
    xy.area(months, revenue, name="Revenue", color="#00b8db", curve="smooth"),
    xy.x_axis(show=False),
    xy.y_axis(show=False, grid=True, style={"grid_color": "#e5e7eb"}),
)
~~~

An explicit `style=` property still wins, so you can switch a part off and then
bring one property back — `xy.x_axis(show=False, style={"grid_color": "#eee",
"grid_opacity": 1})` — without writing the other six.

## Color scales and colorbars

Set a continuous mark's `colormap=` and `domain=` together when colors must
have a stable meaning across charts. Add `xy.colorbar(...)` to explain that
scale, then style its container, gradient, ticks, and title through the
`colorbar`, `colorbar_bar`, `colorbar_tick`, `colorbar_title`,
`colorbar_extension`, `colorbar_line`, and `colorbar_minor_tick` slots.

### Build a colormap from your own colors

`colormap=` takes any of XY's twenty built-in names, and also a **custom ramp**
built from the colors your design system already defines:

| Form | Example |
| --- | --- |
| A list of CSS colors, evenly spaced | `colormap=["#0b1220", "#2563eb", "#22d3ee", "#fde68a"]` |
| `(position, color)` pairs | `colormap=[(0.0, "#f8fafc"), (0.2, "#38bdf8"), (1.0, "#0f172a")]` |
| A CSS gradient (2–8 stops) | `colormap="linear-gradient(#0b1220, #2563eb 30%, #fde68a)"` |

A gradient takes up to 8 stops, the list forms up to 256. Colormap stops are
opaque: use the mark's `opacity`/`fill-opacity` for transparency rather than a
translucent stop, which XY refuses instead of silently flattening to black.

~~~python
chart = xy.hexbin_chart(
    xy.hexbin(throughput, latency, gridsize=54, colormap=BRAND_RAMP),
    xy.colorbar(title="Requests"),
)
~~~

The ramp is resolved once, in Python, so the browser, `to_svg()`, and
`to_png()` paint identical marks, and the colorbar follows it in every renderer.
In the browser the legend row for a continuous encoding also becomes a gradient
swatch of the ramp; the static legend draws a solid handle, as it always has.

One rule follows from that: colormap stops must be colors XY can resolve
without a browser — hex, `rgb()`, `hsl()`, or a named color. `var(--brand)`,
`oklch(...)`, and `color-mix(...)` are fine on an individual `color=`, `stroke`,
or `fill`, but not as a colormap stop or an `xy.theme(palette=...)` entry. Both
are indexed color lookups used by static renderers that have no cascade to
resolve browser-only colors. Resolve the token to a literal in Python and pass
that.

### Recolor categories with a chart palette

A categorical `color=` channel and unnamed series both draw from the chart's
palette. `xy.theme(palette=[...])` replaces it for the whole chart, so a set of
brand swatches colors every series and every category at once:

~~~python
BRAND = ["#38bdf8", "#e879f9", "#fbbf24", "#34d399", "#a78bfa", "#fb7185"]

chart = xy.scatter_chart(
    xy.scatter(x, y, color=stage_labels, size=2.2, opacity=0.7),
    xy.theme(palette=BRAND),
)
~~~

Series take the palette in order — one slot per series, whatever its trace
count, so a box plot (four traces) or a stem (two) advances the cycle by one
like everything else. An explicit `color=` on a mark still wins, and takes no
slot, so the next series that needs a color still gets the palette's first.
A palette shorter than the number of series or categories repeats, and says so
with a warning rather than quietly reusing a color.

To pin specific categories to specific colors, pass a mapping instead of a
list:

~~~python
chart = xy.scatter_chart(
    xy.scatter(x, y, color=species),
    xy.theme(palette={"setosa": "#4c72b0", "versicolor": "#dd8452"}),
)
~~~

A list can only say "the first category is blue", so the same category changes
color whenever the set of categories does — most visibly across facet panels,
where a panel that happens to be missing one category silently recolors the
rest. A mapping keys on the label, so a category keeps its color everywhere.
Categories the mapping does not name take the next default color it has not
already used, and say so with a warning.

Palette entries follow the same rule as colormap stops: literal colors only —
hex, `rgb()`, `hsl()`, or a named color. `var(--brand-500)` is fine on an
individual `color=`, but not in a palette, because a palette is indexed and XY
has to resolve each entry itself for density surfaces and for `to_svg()` /
`to_png()`. Several `var()` entries would land on one fallback and merge
distinct categories into a single color, so XY refuses them and says why.
Resolve your token to a literal in Python and pass that. Named colors,
`rgb()`, and `hsl()` are all fine — XY normalizes them to hex for you.

~~~python demo exec toggle preview-code id=customize-palette-demo
stages = ["Ingest", "Compact", "Query", "Replicate", "Snapshot", "Vacuum"]
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
throughput = [
    [42, 47, 45, 53, 58, 61, 66, 71],
    [31, 34, 38, 36, 41, 45, 44, 49],
    [58, 61, 66, 70, 68, 74, 79, 83],
    [22, 25, 24, 29, 33, 31, 36, 39],
    [15, 17, 21, 20, 24, 27, 26, 30],
    [9, 11, 10, 14, 16, 15, 19, 22],
]

# --- chart ---
import reflex_xy
import xy

palette_chart = xy.line_chart(
    *[
        xy.line(months, values, name=stage, width=2, curve="smooth")
        for stage, values in zip(stages, throughput, strict=True)
    ],
    xy.theme(
        palette=[
            "#0ea5e9", "#d946ef", "#f59e0b", "#10b981", "#8b5cf6", "#f43f5e",
        ],
    ),
    xy.x_axis(line=False, ticks=False),
    xy.y_axis(show=False, grid=True, style={"grid_color": "#e2e8f0"}),
    xy.legend(loc="upper left", ncols=3),
    class_name="text-slate-600 dark:text-zinc-300",
    width="100%",
    height=320,
    padding=(48, 20, 40, 44),
)


def customize_palette_preview():
    return reflex_xy.chart(palette_chart, height="320px")
~~~

~~~python demo exec toggle preview-code id=customize-colorbar-demo
conversion = [
    [0.12, 0.35, 0.62, 0.46],
    [0.28, 0.71, 0.94, 0.68],
    [0.18, 0.54, 0.82, 0.57],
]

# --- chart ---
import reflex_xy
import xy


def customize_colorbar_preview():
    chart = xy.heatmap_chart(
        xy.heatmap(
            conversion,
            name="Conversion rate",
            colormap="purples",
            domain=(0, 1),
            opacity=0.94,
        ),
        xy.colorbar(
            title="Conversion rate",
            ticks=[0, 0.5, 1],
            orientation="horizontal",
            style={
                "background": "var(--colorbar-surface, #ffffff)",
                "color": "var(--colorbar-text, #4b5563)",
                "border": "1px solid var(--colorbar-border, #e5e7eb)",
                "border-radius": 8,
                "padding": "8px 10px",
            },
        ),
        xy.x_axis(
            tick_label_strategy="none",
            style={"axis_width": 0, "grid_opacity": 0, "tick_width": 0},
        ),
        xy.y_axis(
            tick_label_strategy="none",
            style={"axis_width": 0, "grid_opacity": 0, "tick_width": 0},
        ),
        xy.theme(
            plot_background="var(--custom-surface, #ffffff)",
            text_color="var(--colorbar-text, #4b5563)",
        ),
        styles={
            "colorbar_bar": {"border_radius": 6},
            "colorbar_tick": {"font_size": 11},
            "colorbar_title": {"font_weight": 600},
        },
        class_name=(
            "bg-[#ffffff] py-3 [--custom-surface:#ffffff] "
            "[--colorbar-surface:#ffffff] [--colorbar-text:#4b5563] "
            "[--colorbar-border:#e5e7eb] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--colorbar-surface:#18181f] "
            "dark:[--colorbar-text:#d4d4d8] dark:[--colorbar-border:#3f3f46]"
        ),
        padding=(24, 24, 56, 24),
    )
    return reflex_xy.chart(chart, height="340px")
~~~

Use a legend instead when colors identify discrete categories. Built-in
colorbars are available in browser, SVG, native PNG, and Chromium output; host
framework components passed through `render=` are not part of standalone XY
exports. See [Colorbars](/docs/xy/components/colorbars/) for supported marks,
orientation, inferred scales, and custom-component boundaries.

## Legend

Configure legend content and layout with `xy.legend(...)`. Style the component
directly, or use the chart's `legend`, `legend_title`, `legend_item`,
`legend_swatch`, and `legend_label` slots when one rule should cover several
charts. Complete literal Tailwind utilities work through `class_name` /
`class_names` when the host enables Reflex's `TailwindV4Plugin`.

~~~python demo exec toggle preview-code id=customize-legend-demo
periods = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
desktop = [31, 38, 35, 46, 43, 54, 51, 62]
mobile = [22, 27, 32, 29, 38, 42, 49, 57]

# --- chart ---
import reflex_xy
import xy


def customize_legend_preview():
    chart = xy.area_chart(
        xy.area(
            periods,
            desktop,
            name="Desktop",
            color="#8e51ff",
            fill="linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
            opacity=1,
            line_width=2,
            curve="smooth",
        ),
        xy.area(
            periods,
            mobile,
            name="Mobile",
            color="#2b7fff",
            fill="linear-gradient(#2b7fff4d 5%, #2b7fff00 95%)",
            opacity=1,
            line_width=2,
            curve="smooth",
        ),
        xy.legend(
            loc="upper right",
            ncols=2,
            style={
                "color": "var(--custom-text, #4b5563)",
                "background": "transparent",
                "border": 0,
                "box-shadow": "none",
            },
        ),
        xy.tooltip(show=False),
        xy.modebar(show=False),
        xy.x_axis(
            tick_label_strategy="none",
            style={"axis_width": 0, "grid_opacity": 0, "tick_width": 0},
        ),
        xy.y_axis(
            tick_label_strategy="off",
            style={
                "grid_color": "var(--custom-grid, #e5e7eb)",
                "grid_width": 1,
                "grid_opacity": 1,
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        xy.theme(
            plot_background="var(--custom-surface, #ffffff)",
            grid_color="var(--custom-grid, #e5e7eb)",
        ),
        styles={
            "legend_item": {"gap": 8, "padding": 0},
            "legend_swatch": {
                "width": 24,
                "height": 3,
                "border-radius": 999,
            },
        },
        class_name=(
            "bg-[#ffffff] py-3 sm:py-4 [--custom-surface:#ffffff] "
            "[--custom-grid:#e5e7eb] [--custom-text:#4b5563] "
            "dark:bg-[#000000] dark:[--custom-surface:#000000] "
            "dark:[--custom-grid:#27272a] dark:[--custom-text:#d4d4d8] "
        ),
        padding=(58, 28, 34, 28),
    )
    return reflex_xy.chart(chart, height="340px")
~~~

A short, rounded swatch makes an area-series legend read like its visible
stroke instead of a generic color chip. A genuinely custom host legend is
ordinary Reflex UI: hide the built-in legend
with `xy.legend(show=False)`, keep the chart in state, and render the controls
beside it. Host-owned UI is not included in standalone XY exports.

## Tooltip

Tooltip fields must already be resident in a rendered data channel. Use named
data columns for stable lookup, map them to readable display text with
`labels=`, and format them with `format=`. Style the built-in container
directly or target `tooltip_title`, `tooltip_row`, `tooltip_label`, and
`tooltip_value` independently.

~~~python demo exec toggle preview-code id=customize-tooltip-demo
data = {
    "period": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
    "revenue": [32_000, 45_000, 41_000, 58_000, 63_000, 74_000],
}

# --- chart ---
import reflex_xy
import xy


def customize_tooltip_preview():
    chart = xy.area_chart(
        xy.area(
            x="period",
            y="revenue",
            data=data,
            color="#00b8db",
            fill="linear-gradient(#00b8db4d 5%, #00b8db00 95%)",
            opacity=1,
            line_width=2,
            curve="smooth",
        ),
        xy.legend(show=False),
        xy.tooltip(
            fields=["revenue"],
            title="{period}",
            format={"revenue": "$,.0f"},
            labels={"revenue": "Revenue"},
            style={
                "background": "var(--tooltip-surface, #ffffff)",
                "color": "var(--tooltip-text, #1d293d)",
                "border": "1px solid var(--tooltip-border, #e5e7eb)",
                "border-radius": 8,
                "box-shadow": "0 8px 24px #1118271f",
                "padding": "8px 10px",
            },
        ),
        xy.x_axis(
            tick_label_strategy="none",
            style={"axis_width": 0, "grid_opacity": 0, "tick_width": 0},
        ),
        xy.y_axis(
            domain=(0, 80_000),
            tick_label_strategy="off",
            style={
                "grid_color": "var(--custom-grid, #e5e7eb)",
                "grid_width": 1,
                "grid_opacity": 1,
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        xy.theme(
            plot_background="var(--custom-surface, #ffffff)",
            grid_color="var(--custom-grid, #e5e7eb)",
        ),
        styles={
            "tooltip_title": {"font-weight": 700, "margin-bottom": 4},
            "tooltip_row": {
                "display": "grid",
                "grid-template-columns": "5rem 1fr",
                "gap": 8,
            },
            "tooltip_label": {"color": "var(--tooltip-muted, #64748b)"},
            "tooltip_value": {"font-weight": 700, "text-align": "right"},
        },
        class_name=(
            "bg-[#ffffff] [--custom-surface:#ffffff] [--custom-grid:#e5e7eb] "
            "[--tooltip-surface:#ffffff] [--tooltip-text:#1d293d] "
            "[--tooltip-muted:#64748b] "
            "[--tooltip-border:#e5e7eb] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--custom-grid:#27272a] "
            "dark:[--tooltip-surface:#18181f] dark:[--tooltip-text:#f3f4f6] "
            "dark:[--tooltip-muted:#a1a1aa] "
            "dark:[--tooltip-border:#3f3f46]"
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

For a host-owned tooltip, set `xy.tooltip(show=False)`, handle
`on_point_hover`, and render ordinary framework UI from the received row. The
built-in tooltip remains the right choice when it must track the pointer or
survive a standalone export.

## Annotations

Annotation geometry is painted with the chart; annotation text is DOM chrome.
Use geometry props such as `color`, `width`, and `opacity`, then use the
annotation's `style` or the chart's `annotation_label` slot for its label.

~~~python demo exec toggle preview-code id=customize-annotations-demo
x = [0, 1, 2, 3, 4, 5]
y = [3, 5, 4, 7, 6, 9]

# --- chart ---
import reflex_xy
import xy


def customize_annotations_preview():
    chart = xy.area_chart(
        xy.area(
            x,
            y,
            color="#2b7fff",
            fill="linear-gradient(#2b7fff4d 5%, #2b7fff00 95%)",
            opacity=1,
            curve="smooth",
            line_width=2,
        ),
        xy.hline(
            6,
            text="Target",
            color="#fe9a00",
            width=2,
            style={
                "label_color": "#fe9a00",
                "background_color": "#fe9a001a",
                "padding": "2px 5px",
            },
        ),
        xy.x_band(
            2.5,
            3.5,
            text="Launch",
            color="#00bc7d",
            opacity=0.12,
            style={
                "label_color": "#00bc7d",
                "background": "#00bc7d1a",
                "padding": "2px 5px",
            },
        ),
        xy.callout(
            5,
            9,
            "Peak",
            dx=-16,
            dy=-24,
            anchor="end",
            color="#2b7fff",
            width=2,
            style={
                "label_color": "#2b7fff",
                "background": "#2b7fff1a",
                "border": "1px solid #2b7fff66",
                "border-radius": 6,
                "padding": "3px 6px",
            },
        ),
        xy.x_axis(
            tick_label_strategy="none",
            style={"axis_width": 0, "grid_opacity": 0, "tick_width": 0},
        ),
        xy.y_axis(
            domain=(0, 12),
            tick_values=[0, 3, 6, 9, 12],
            tick_label_strategy="off",
            style={
                "grid_color": "var(--custom-grid, #e5e7eb)",
                "grid_width": 1,
                "grid_opacity": 1,
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        xy.theme(
            plot_background="var(--custom-surface, #ffffff)",
            grid_color="var(--custom-grid, #e5e7eb)",
            text_color="var(--custom-text, #6a7282)",
        ),
        class_name=(
            "bg-[#ffffff] py-2 [--custom-surface:#ffffff] [--custom-grid:#e5e7eb] "
            "[--custom-text:#6a7282] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--custom-grid:#27272a] "
            "dark:[--custom-text:#d4d4d8]"
        ),
        padding=(28, 48, 32, 32),
    )
    return reflex_xy.chart(chart, height="350px")
~~~

`threshold(...)` and `threshold_zone(...)` are semantic aliases for reference
lines and bands. Arrow shafts, markers, rules, and zones remain painted
geometry; only their labels respond to DOM slot styles.

## Interaction chrome

Crosshairs, selections, and the modebar are configured independently from data
marks. Interaction colors belong in `xy.theme(...)`; DOM pieces can also use
the `crosshair_x`, `crosshair_y`, `selection`, `modebar`, and `modebar_button`
slots. The remaining `modebar_*` slots reach the draggable grip, control group,
separators, icons, zoom value, indicators, selection icon, menus, menu content,
and history controls independently.

~~~python demo exec toggle preview-code id=customize-interaction-demo
x = [0, 1, 2, 3, 4, 5, 6, 7]
y = [2, 5, 3, 7, 6, 9, 8, 11]

# --- chart ---
import reflex_xy
import xy


def customize_interaction_preview():
    chart = xy.scatter_chart(
        xy.scatter(
            x,
            y,
            size=10,
            style={
                "fill": "#fe9a00",
                "stroke": "#ffffff",
                "stroke-width": 1.5,
            },
        ),
        xy.interaction_config(crosshair=True, select=True, brush=True),
        xy.modebar(
            class_name=(
                "rounded-lg border border-[#e5e7eb] bg-[#fffffff2] shadow-md "
                "dark:border-[#3f3f46] dark:bg-[#18181ff2]"
            ),
            button_class_name=(
                "rounded-md hover:bg-[#8e51ff1a] focus:ring-2 focus:ring-[#8e51ff]"
            ),
        ),
        xy.x_axis(
            tick_label_strategy="none",
            style={"axis_width": 0, "grid_opacity": 0, "tick_width": 0},
        ),
        xy.y_axis(
            domain=(0, 12),
            tick_values=[0, 3, 6, 9, 12],
            tick_label_strategy="off",
            style={
                "grid_color": "var(--custom-grid, #e5e7eb)",
                "grid_width": 1,
                "grid_opacity": 1,
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        xy.theme(
            plot_background="var(--custom-surface, #ffffff)",
            grid_color="var(--custom-grid, #e5e7eb)",
            text_color="var(--custom-text, #6a7282)",
            crosshair_color="#2b7fff",
            selection_color="#8e51ff",
            selection_fill="#8e51ff29",
        ),
        styles={
            "crosshair_x": {"width": 2},
            "crosshair_y": {"height": 2},
            "selection": {"border-radius": 6},
        },
        class_name=(
            "bg-[#ffffff] [--custom-surface:#ffffff] [--custom-grid:#e5e7eb] "
            "[--custom-text:#6a7282] dark:bg-[#000000] "
            "dark:[--custom-surface:#000000] dark:[--custom-grid:#27272a] "
            "dark:[--custom-text:#d4d4d8]"
        ),
    )
    return reflex_xy.chart(chart, height="340px")
~~~

Move across the plot to inspect the crosshair. Open the modebar selection menu,
or Shift-drag, to inspect the styled selection rectangle. Framework callbacks
such as `on_select_end` can turn the result into filters or related views.
