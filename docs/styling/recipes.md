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

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.arange(12)
y = np.array([42, 45, 44, 49, 53, 51, 58, 61, 60, 66, 70, 74])

sparkline = xy.area_chart(
    xy.area(
        x,
        y,
        color="#3b82f6",
        curve="smooth",
        line_width=2.5,
        line_opacity=1,
        fill="linear-gradient(currentColor, transparent)",
    ),
    xy.x_axis(
        tick_label_strategy="none",
        style={"grid_color": "transparent", "axis_color": "transparent"},
    ),
    xy.y_axis(
        tick_label_strategy="none",
        style={"grid_color": "transparent", "axis_color": "transparent"},
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

`currentColor` follows the area's `color`, so the same fade recipe works with
another palette value or CSS variable.

## Rounded gradient columns

Use a mark-space gradient so every column fades along its own value direction,
and round only the value end:

~~~python demo exec
import reflex_xy
import xy

gradient_columns = xy.column_chart(
    xy.column(
        ["Starter", "Team", "Business", "Enterprise"],
        [34, 58, 76, 93],
        fill="linear-gradient(to top, #2563eb, #93c5fd)",
        corner_radius=(8, 0),
        stroke="#1e3a8a",
        stroke_width=1,
    ),
    xy.y_axis(label="adoption", domain=(0, 100), format=".0f"),
    title="Plan adoption",
)


def gradient_columns_recipe():
    return reflex_xy.chart(gradient_columns, height="320px")
~~~

For one continuous gradient across the whole plot, pass
`fill={"gradient": "linear-gradient(to right, #2563eb, #a78bfa)",
"space": "plot"}`.

## Accessible monochrome comparison

Do not rely on hue alone when a chart must survive grayscale printing or serve
users with color-vision differences. Combine stroke dash, marker shape, and a
clear legend so each series has multiple visual identifiers:

~~~python demo exec
import reflex_xy
import xy

periods = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]

monochrome = xy.line_chart(
    xy.line(
        periods,
        [42, 48, 51, 57, 61, 68],
        name="Actual",
        color="var(--secondary-12)",
        width=2.5,
    ),
    xy.scatter(
        periods,
        [42, 48, 51, 57, 61, 68],
        symbol="circle",
        color="var(--secondary-2)",
        stroke="var(--secondary-12)",
        stroke_width=2,
        size=8,
    ),
    xy.line(
        periods,
        [40, 46, 53, 55, 63, 66],
        name="Plan",
        color="var(--secondary-10)",
        width=2.5,
        dash="dashed",
    ),
    xy.scatter(
        periods,
        [40, 46, 53, 55, 63, 66],
        symbol="square",
        color="var(--secondary-10)",
        size=7,
    ),
    xy.legend(loc="upper left", ncols=2),
    xy.tooltip(title="{x}"),
    xy.theme(
        plot_background="var(--secondary-2)",
        grid_color="var(--secondary-a5)",
        axis_color="var(--secondary-a8)",
        text_color="var(--secondary-11)",
    ),
    class_name="bg-secondary-2 text-secondary-11",
    style={"background": "var(--secondary-2)"},
    title="Actual versus plan",
)


def accessible_monochrome_recipe():
    return reflex_xy.chart(monochrome, height="320px")
~~~

The points intentionally have no legend names, so they reinforce the two line
series without creating duplicate legend rows.

## Dense categorical labels

Long category names can overlap or be clipped. Rotate the x-axis labels and
reserve extra space below the plot so every region name remains readable. If
showing every label is unnecessary, use `tick_label_strategy="hide"` instead.

~~~python demo exec
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
        fill="linear-gradient(to top, #4338ca, #a5b4fc)",
        corner_radius=(6, 0),
    ),
    xy.x_axis(
        tick_label_strategy="rotate",
        tick_label_angle=-35,
        tick_label_min_gap=8,
    ),
    xy.y_axis(label="adoption (%)", domain=(0, 100)),
    width="100%",
    height=360,
    padding=[38, 24, 92, 54],
    title="Regional adoption",
)


def dense_categorical_axis_recipe():
    return reflex_xy.chart(dense_categories, height="360px")
~~~

Keep the chart root's overflow visible. Axis labels are DOM chrome and can be
clipped when `overflow-hidden` is applied directly to the XY root.

## Dark chart card

Keep every export-critical color on the chart. Marks can consume a custom
accent variable while chrome uses the standard token set:

~~~python demo exec
import reflex_xy
import xy

dark_card = xy.scatter_chart(
    xy.scatter(
        [1, 2, 3, 4, 5],
        [2, 5, 4, 7, 6],
        size=11,
        style={
            "fill": "var(--chart-accent)",
            "stroke": "#f8fafc",
            "stroke-width": 1.5,
        },
    ),
    xy.theme(
        style={
            "--chart-bg": "#18181b",
            "--chart-text": "#e4e4e7",
            "--chart-grid": "rgb(212 212 216 / 12%)",
            "--chart-axis": "rgb(212 212 216 / 55%)",
            "--chart-tooltip-bg": "#09090b",
            "--chart-tooltip-text": "#fafafa",
            "--chart-accent": "#a78bfa",
        }
    ),
    style={"background": "#18181b", "border_radius": 14},
    title="Dark-mode card",
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

~~~python demo exec
import reflex_xy
import xy

branded = xy.area_chart(
    xy.area(
        [0, 1, 2, 3, 4, 5],
        [18, 24, 22, 31, 35, 43],
        name="Active teams",
        color="var(--brand-primary, #2563eb)",
        curve="smooth",
        line_width=2.5,
        fill="linear-gradient(currentColor, transparent)",
    ),
    xy.legend(loc="upper left"),
    xy.tooltip(title="Month {x}"),
    xy.theme(
        plot_background="var(--brand-surface, #fafafa)",
        text_color="var(--brand-text, #172554)",
        grid_color="var(--brand-grid, rgb(37 99 235 / 14%))",
        axis_color="var(--brand-axis, rgb(30 64 175 / 55%))",
        style={
            "--brand-primary": "var(--brand-accent, #2563eb)",
            "--chart-tooltip-bg": "var(--brand-tooltip, #27272a)",
            "--chart-tooltip-text": "var(--brand-tooltip-text, #fafafa)",
            "--chart-legend-bg": "var(--brand-legend, rgb(250 250 250 / 88%))",
        },
    ),
    class_name=(
        "[--brand-surface:#fafafa] [--brand-text:#172554] "
        "[--brand-grid:#2563eb24] [--brand-axis:#1e40af8c] "
        "[--brand-accent:#2563eb] [--brand-tooltip:#27272a] "
        "[--brand-tooltip-text:#fafafa] [--brand-legend:#fafafae0] "
        "dark:[--brand-surface:#18181b] dark:[--brand-text:#dbeafe] "
        "dark:[--brand-grid:#93c5fd33] dark:[--brand-axis:#93c5fd99] "
        "dark:[--brand-accent:#60a5fa] dark:[--brand-tooltip:#09090b] "
        "dark:[--brand-tooltip-text:#eff6ff] dark:[--brand-legend:#27272ae6]"
    ),
    style={"background": "var(--brand-surface, #fafafa)"},
    title="Branded growth",
)


def export_safe_brand_recipe():
    return reflex_xy.chart(branded, height="320px")
~~~

The same chart can now use `to_svg()` or native `to_png()` without depending on
an ancestor stylesheet. Use `custom_css` with the Chromium engine only when an
export intentionally needs browser selectors or a host-loaded font.

## Responsive dashboard card

Make the chart fluid horizontally but give it a real height. Constrain an outer
host card—not the XY root—so labels remain free to extend into the chart's
padding and the chart can remeasure when its container changes.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

dashboard_card = xy.line_chart(
    xy.line(
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        [82, 91, 87, 104, 112, 108, 126],
        name="Requests",
        color="#0f766e",
        width=2.5,
        curve="smooth",
    ),
    xy.line(
        ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        [76, 84, 90, 96, 102, 108, 114],
        name="Expected",
        color="#94a3b8",
        dash="dashed",
    ),
    xy.legend(loc="upper left", ncols=2),
    xy.tooltip(title="{x}", format={"y": ".0f"}),
    xy.theme(grid_color="rgb(148 163 184 / 20%)"),
    class_names={
        "legend": "rounded-md bg-white/90 text-xs dark:bg-zinc-900/90",
        "tooltip": "rounded-lg bg-zinc-950 px-3 py-2 text-white shadow-xl",
    },
    width="100%",
    height=280,
    padding=[42, 22, 48, 48],
    title="Weekly traffic",
)


def responsive_dashboard_card_recipe():
    return rx.box(
        reflex_xy.chart(dashboard_card, height="280px"),
        width="100%",
        max_width="36rem",
        margin_x="auto",
        padding="3",
        border="1px solid var(--gray-a5)",
        border_radius="12px",
        box_shadow="0 8px 24px rgb(15 23 42 / 8%)",
    )
~~~

Avoid `height="100%"` unless every ancestor has a defined height. An explicit
component height with chart `width="100%"` is the most reliable responsive
starting point.
