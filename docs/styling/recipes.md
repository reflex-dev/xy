---
title: Styling Recipes
description: Copy visual recipes for dashboard areas, gradient bars, and dark charts.
---

# Styling Recipes

These recipes use only shipped styling surfaces. Copy the chart construction
into a script or notebook; the small `reflex_xy.chart(...)` wrapper exists only
to render the live documentation preview.

## Dashboard sparkline

Remove chart chrome, tighten the plot padding, and fade a smooth area into its
baseline:

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
            "--chart-bg": "#0f172a",
            "--chart-text": "#e2e8f0",
            "--chart-grid": "rgb(226 232 240 / 12%)",
            "--chart-axis": "rgb(226 232 240 / 55%)",
            "--chart-tooltip-bg": "#020617",
            "--chart-tooltip-text": "#f8fafc",
            "--chart-accent": "#a78bfa",
        }
    ),
    style={"background": "#0f172a", "border_radius": 14},
    title="Dark-mode card",
)


def dark_chart_card_recipe():
    return reflex_xy.chart(dark_card, height="320px")
~~~

To follow system dark mode rather than fixing one palette, move the token
values into the `@media (prefers-color-scheme: dark)` stylesheet shown in
[Themes and tokens](/docs/xy/styling/themes-and-tokens/#dark-mode-in-a-standalone-export).
