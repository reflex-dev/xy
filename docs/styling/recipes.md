---
title: Styling Recipes
description: Ready-to-use styling examples for dashboard areas, gradient bars, and dark charts.
---

# Styling Recipes

Each recipe uses public XY styling APIs. Copy the chart construction into a
script or notebook; the `reflex_xy.chart(...)` function simply displays the
interactive preview on this page.

## Dashboard sparkline

Build a compact trend chart by hiding the axes, legend, tooltip, and toolbar.
The reduced padding saves space, while the gradient makes the area fill fade
toward the baseline:

~~~python demo exec toggle preview-code id=dashboard-sparkline-recipe
import numpy as np
import reflex_xy
import xy

x = np.arange(12)
y = np.array([42, 45, 44, 49, 53, 51, 58, 61, 60, 66, 70, 74])

sparkline = xy.area_chart(
    xy.area(
        x,
        y,
        color="#fe9a00",
        curve="smooth",
        line_width=2,
        line_opacity=1,
        fill="linear-gradient(#fe9a004d 5%, #fe9a0000 95%)",
    ),
    xy.x_axis(
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
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.legend(show=False),
    xy.tooltip(show=False),
    xy.modebar(show=False),
    width="100%",
    height=180,
    padding=[8, 2, 2, 2],
)


def dashboard_sparkline_recipe():
    return reflex_xy.chart(sparkline, height="180px")
~~~

Keep the stroke and both gradient stops on the same hue when adapting this
recipe to another palette value.

## Rounded gradient columns

Use a mark-space gradient so every column fades along its own value direction,
and round only the value end:

~~~python demo exec toggle preview-code id=rounded-gradient-columns-recipe
import reflex_xy
import xy

gradient_columns = xy.column_chart(
    xy.column(
        ["Starter", "Team", "Business", "Enterprise"],
        [34, 58, 76, 93],
        fill="linear-gradient(to top, #2b7fff, #00b8db)",
        corner_radius=(6, 0),
        stroke_width=0,
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
        domain=(0, 100),
        format=".0f",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.tooltip(title="{x}", format={"y": ".0f"}),
)


def gradient_columns_recipe():
    return reflex_xy.chart(gradient_columns, height="320px")
~~~

For one continuous gradient across the whole plot, pass
`fill={"gradient": "linear-gradient(to right, #2b7fff, #8e51ff)",
"space": "plot"}`.

## Accessible monochrome comparison

Do not rely on hue alone when a chart must survive grayscale printing or serve
users with color-vision differences. Combine stroke dash, marker shape, and a
clear legend so each series has multiple visual identifiers:

~~~python demo exec toggle preview-code id=accessible-monochrome-comparison-recipe
import reflex_xy
import xy

periods = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]

monochrome = xy.line_chart(
    xy.line(
        periods,
        [42, 48, 51, 57, 61, 68],
        name="Actual",
        color="#6a7282",
        width=2.5,
    ),
    xy.scatter(
        periods,
        [42, 48, 51, 57, 61, 68],
        symbol="circle",
        color="#ffffff",
        stroke="#6a7282",
        stroke_width=2,
        size=8,
    ),
    xy.line(
        periods,
        [40, 46, 53, 55, 63, 66],
        name="Plan",
        color="#6a7282",
        width=2.5,
        dash="dashed",
    ),
    xy.scatter(
        periods,
        [40, 46, 53, 55, 63, 66],
        symbol="square",
        color="#6a7282",
        size=7,
    ),
    xy.legend(loc="upper left", ncols=2),
    xy.tooltip(title="{x}"),
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
        plot_background="var(--recipe-surface, #ffffff)",
        grid_color="var(--recipe-grid, #e5e7eb)",
        text_color="var(--recipe-text, #4b5563)",
    ),
    class_name=(
        "bg-[#ffffff] [--recipe-surface:#ffffff] [--recipe-grid:#e5e7eb] "
        "[--recipe-text:#4b5563] dark:bg-[#000000] "
        "dark:[--recipe-surface:#000000] dark:[--recipe-grid:#27272a] "
        "dark:[--recipe-text:#d4d4d8]"
    ),
)


def accessible_monochrome_recipe():
    return reflex_xy.chart(monochrome, height="320px")
~~~

The points intentionally have no legend names, so they reinforce the two line
series without creating duplicate legend rows.

## Dense categorical labels

Long category names can overwhelm a compact dashboard. This treatment leaves
the categories available to the tooltip while removing axis chrome so the
columns remain easy to compare at a glance.

~~~python demo exec toggle preview-code id=dense-categorical-labels-recipe
import reflex_xy
import xy

dense_categories = xy.column_chart(
    xy.column(
        [
            "North America",
            "Latin America",
            "Western Europe",
            "Eastern Europe",
            "Middle East",
            "Asia Pacific",
        ],
        [78, 54, 69, 47, 58, 83],
        color="#8e51ff",
        corner_radius=(6, 0),
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
    xy.tooltip(title="{x}", format={"y": ".0f"}),
    width="100%",
    height=360,
    padding=[28, 24, 36, 32],
)


def dense_categorical_axis_recipe():
    return reflex_xy.chart(dense_categories, height="360px")
~~~

Keep the chart root's overflow visible. Tooltips and other DOM chrome can be
clipped when `overflow-hidden` is applied directly to the XY root.

## Theme-aware scatter

Keep the exact violet mark color on the chart while neutral surface and grid
tokens follow the host's light or dark mode:

~~~python demo exec toggle preview-code id=dark-chart-card-recipe
import reflex_xy
import xy

dark_card = xy.scatter_chart(
    xy.scatter(
        [1, 2, 3, 4, 5],
        [2, 5, 4, 7, 6],
        size=11,
        style={
            "fill": "#8e51ff",
            "stroke": "#ffffff",
            "stroke-width": 1.5,
        },
    ),
    xy.theme(
        style={
            "--chart-bg": "var(--recipe-surface, #ffffff)",
            "--chart-text": "var(--recipe-text, #4b5563)",
            "--chart-grid": "var(--recipe-grid, #e5e7eb)",
            "--chart-axis": "#00000000",
            "--chart-tooltip-bg": "#09090b",
            "--chart-tooltip-text": "#fafafa",
        }
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
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    class_name=(
        "bg-[#ffffff] [--recipe-surface:#ffffff] [--recipe-grid:#e5e7eb] "
        "[--recipe-text:#4b5563] dark:bg-[#000000] "
        "dark:[--recipe-surface:#000000] dark:[--recipe-grid:#27272a] "
        "dark:[--recipe-text:#d4d4d8]"
    ),
)


def dark_chart_card_recipe():
    return reflex_xy.chart(dark_card, height="320px")
~~~

To follow system dark mode rather than fixing one palette, move the token
values into the `@media (prefers-color-scheme: dark)` stylesheet shown in
[Themes and tokens](/docs/xy/styling/themes-and-tokens/#dark-mode-in-a-standalone-export).

## Export-safe brand theme

Put export-critical variables on the chart itself. Browser-only host CSS is
appropriate for application decoration, but native SVG and PNG cannot inherit
from the page that happened to contain the chart.

~~~python demo exec toggle preview-code id=export-safe-brand-theme-recipe
import reflex_xy
import xy

branded = xy.area_chart(
    xy.area(
        [0, 1, 2, 3, 4, 5],
        [18, 24, 22, 31, 35, 43],
        name="Active teams",
        color="#00b8db",
        curve="smooth",
        line_width=2,
        fill="linear-gradient(#00b8db4d 5%, #00b8db00 95%)",
    ),
    xy.legend(loc="upper left"),
    xy.tooltip(title="Month {x}"),
    xy.theme(
        plot_background="var(--brand-surface, #ffffff)",
        text_color="var(--brand-text, #4b5563)",
        grid_color="var(--brand-grid, #e5e7eb)",
        axis_color="var(--brand-axis, #d1d5db)",
        style={
            "--chart-tooltip-bg": "var(--brand-tooltip, #27272a)",
            "--chart-tooltip-text": "var(--brand-tooltip-text, #fafafa)",
            "--chart-legend-bg": "var(--brand-legend, #fafafae0)",
        },
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
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    class_name=(
        "[--brand-surface:#ffffff] [--brand-text:#4b5563] "
        "[--brand-grid:#e5e7eb] [--brand-axis:#d1d5db] "
        "[--brand-tooltip:#27272a] "
        "[--brand-tooltip-text:#fafafa] [--brand-legend:#fafafae0] "
        "dark:[--brand-surface:#000000] dark:[--brand-text:#d4d4d8] "
        "dark:[--brand-grid:#27272a] dark:[--brand-axis:#3f3f46] "
        "dark:[--brand-tooltip:#09090b] "
        "dark:[--brand-tooltip-text:#f8fafc] dark:[--brand-legend:#18181be6]"
    ),
    style={"background": "var(--brand-surface, #ffffff)"},
)


def export_safe_brand_recipe():
    return reflex_xy.chart(branded, height="320px")
~~~

The same chart can now use `to_svg()` or native `to_png()` without depending on
an ancestor stylesheet. Use `custom_css` with the Chromium engine only when an
export intentionally needs browser selectors or a host-loaded font.

## Responsive combo chart

Combine columns and a line in one responsive coordinate system when two related
signals need different visual emphasis. Blue bars, an amber line, a compact
legend, and horizontal guides keep both measures easy to compare.

~~~python demo exec toggle preview-code id=responsive-dashboard-card-recipe
import reflex_xy
import xy

months = [
    "Jan 23", "Feb 23", "Mar 23", "Apr 23", "May 23", "Jun 23",
    "Jul 23", "Aug 23", "Sep 23", "Oct 23", "Nov 23", "Dec 23",
]
solar_panels = [2890, 2756, 3322, 3470, 3475, 3129, 3490, 2903, 2643, 2837, 2954, 3239]
inverters = [2338, 2103, 2194, 2108, 1812, 1726, 1982, 2012, 2342, 2473, 3848, 3736]

dashboard_combo = xy.chart(
    xy.column(
        months,
        solar_panels,
        name="Solar panels",
        color="#2b7fff",
        corner_radius=0,
        stroke_width=0,
    ),
    xy.line(
        months,
        inverters,
        name="Inverters",
        color="#fe9a00",
        width=2,
        curve="linear",
        y_axis="y2",
    ),
    xy.legend(loc="upper right", ncols=2),
    xy.tooltip(title="{x}", format={"y": ",.0f"}),
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
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.y_axis(
        id="y2",
        side="right",
        domain=(0, 4200),
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
    xy.theme(
        plot_background="var(--recipe-surface, #ffffff)",
        grid_color="var(--recipe-grid, #e5e7eb)",
        text_color="var(--recipe-text, #4b5563)",
    ),
    class_name=(
        "bg-[#ffffff] [--recipe-surface:#ffffff] [--recipe-grid:#e5e7eb] "
        "[--recipe-text:#4b5563] dark:bg-[#000000] "
        "dark:[--recipe-surface:#000000] dark:[--recipe-grid:#27272a] "
        "dark:[--recipe-text:#d4d4d8]"
    ),
    class_names={
        "legend": "rounded-md bg-white/90 text-xs dark:bg-zinc-900/90",
        "tooltip": "rounded-lg bg-zinc-950 px-3 py-2 text-white shadow-xl",
    },
    width="100%",
    height=280,
    padding=[42, 24, 36, 32],
)


def responsive_dashboard_card_recipe():
    return reflex_xy.chart(dashboard_combo, height="280px")
~~~

Avoid `height="100%"` unless every ancestor has a defined height. The shared
preview owns the border and surface; the chart only needs fluid width and an
explicit component height.
