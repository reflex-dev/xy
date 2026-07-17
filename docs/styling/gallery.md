---
title: Styling Gallery
description: Exercise every XY mark family, chart shell, facet, badge, axis, and custom-chrome boundary.
---

# Styling Gallery

This gallery demonstrates the full range of XY's public styling features. The
examples combine mark styles, DOM slots, theme tokens, responsive sizing, and
less common axis and annotation configurations. Use the shorter
[recipes](/docs/xy/styling/recipes/) when you want one polished treatment;
use this page when you need to see how far a styling surface reaches.

## Complete coverage map

| Family | Components exercised here | Useful styling variations |
| --- | --- | --- |
| Trend | `line`, `area`, `step`, `stairs`, `ecdf` | smooth and stepped geometry, gradients, outlines, dashes, opacity |
| Points | `scatter` | all symbols, fill/stroke separation, continuous color and size |
| Categories | `bar`, `column` | horizontal/vertical layout, gradients, outline, asymmetric corner radii |
| Distributions | `histogram` / `hist`, `box`, `violin` | rounded bins, density fill, translucent comparison layers |
| Grids and density | `heatmap`, `hexbin`, `contour` | colormaps, cell alpha, contour strokes, layered scalar fields |
| Uncertainty | `error_band`, `errorbar` | translucent interval fill, boundary strokes, caps, estimate overlays |
| Explicit geometry | `segments`, `stem`, `triangle_mesh` | per-item color, stroke width, marker paint, mesh borders |
| Annotations | `vline`, `hline`, `x_band`, `y_band`, `text`, `label`, `marker`, `arrow`, `threshold`, `threshold_zone`, `callout` | geometry paint plus independently styled DOM labels |
| Chrome | `x_axis`, `y_axis`, `legend`, `tooltip`, `colorbar`, `modebar`, `theme`, `interaction_config` | classes, inline slot styles, tokens, crosshair, selection |
| Composition | `chart`, typed chart factories, `facet_chart` | layered marks, shared panel styles, responsive wrappers, export CSS |

`hist` is an alias of `histogram`; `label` is an alias of `text`; and
`threshold` / `threshold_zone` resolve to the corresponding rule or band.
The aliases are listed for completeness; they use the same rendering behavior
as their corresponding components.

## Responsive chart shells

Both cards use `width="100%"`; resize the page to exercise the chart's
`ResizeObserver`. They use different accent colors while their background,
text, axes, legend, tooltip, and modebar follow the page's light or dark theme.
Hover the live marks to inspect the tooltip.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy


def shell_chart(accent: str, title: str):
    return xy.line_chart(
        xy.area(
            [0, 1, 2, 3, 4, 5],
            [3, 5, 4, 7, 6, 9],
            color=accent,
            curve="smooth",
            fill="linear-gradient(currentColor, transparent)",
            opacity=0.42,
            line_width=2,
        ),
        xy.scatter(
            [0, 1, 2, 3, 4, 5],
            [3, 5, 4, 7, 6, 9],
            name="Observed",
            color=accent,
            size=7,
            stroke="#ffffff",
            stroke_width=1.5,
        ),
        xy.legend(
            loc="upper left",
            title="Series",
            style={
                "background": "var(--shell-legend-bg, rgb(255 255 255 / 86%))",
                "color": "var(--shell-text, #0f172a)",
                "border": "1px solid var(--shell-border, #e2e8f0)",
            },
        ),
        xy.tooltip(title="Sample {x}", format={"y": ".1f"}),
        xy.x_axis(label="sample", tick_count=6),
        xy.y_axis(label="value"),
        xy.theme(
            style={
                "--chart-bg": "var(--shell-bg, #ffffff)",
                "--chart-text": "var(--shell-text, #0f172a)",
                "--chart-grid": "var(--shell-grid, rgb(148 163 184 / 22%))",
                "--chart-axis": "var(--shell-axis, #64748b)",
                "--chart-legend-bg": "var(--shell-legend-bg, rgb(255 255 255 / 86%))",
                "--chart-tooltip-bg": "#020617",
                "--chart-tooltip-text": "#f8fafc",
            }
        ),
        class_name=(
            "rounded-2xl border bg-[var(--shell-bg)] text-[var(--shell-text)] "
            "shadow-sm [--shell-bg:#ffffff] [--shell-text:#0f172a] "
            "[--shell-grid:#94a3b838] [--shell-axis:#64748b] "
            "[--shell-border:#e2e8f0] [--shell-legend-bg:#ffffffdb] "
            "dark:[--shell-bg:#0f172a] dark:[--shell-text:#e2e8f0] "
            "dark:[--shell-grid:#e2e8f01f] dark:[--shell-axis:#94a3b8] "
            "dark:[--shell-border:#334155] dark:[--shell-legend-bg:#020617db]"
        ),
        class_names={
            "title": "font-semibold tracking-tight",
            "legend": "rounded-lg backdrop-blur-sm",
            "tooltip": "rounded-lg shadow-2xl",
            "modebar_button": "rounded-md focus:ring-2",
        },
        styles={
            "root": {"border_color": "var(--shell-border, #e2e8f0)"},
            "legend_item": {"padding": "2px 4px"},
            "legend_swatch": {"border_radius": 999},
        },
        style={"background": "var(--shell-bg, #ffffff)"},
        width="100%",
        height=350,
        padding=[42, 40, 64, 58],
        title=title,
    )


def responsive_shells_preview():
    return rx.el.div(
        rx.box(
            reflex_xy.chart(
                shell_chart("#7c3aed", "Responsive shell"),
                height="350px",
            ),
            class_name="min-w-0",
        ),
        rx.box(
            reflex_xy.chart(
                shell_chart("#38bdf8", "Alternate accent"),
                height="350px",
            ),
            class_name="min-w-0",
        ),
        class_name="flex w-full flex-col gap-5",
    )
~~~

Do not put `overflow-hidden` on the XY root when axis titles or annotation
labels may reach its edge; those labels are DOM chrome and can be clipped by
normal CSS overflow. Put clipping on an outer host wrapper only when that is
the visual effect you actually want.

In a standalone document, system dark mode belongs in author CSS rather than
Python conditionals:

~~~css
@media (prefers-color-scheme: dark) {
  .xy {
    --chart-bg: #0f172a;
    --chart-text: #e2e8f0;
    --chart-grid: rgb(226 232 240 / 12%);
  }
}
~~~

## Long legends and edge tooltips

This example keeps a few operational series in a centered legend and puts four
resident fields in the tooltip. Resize the page until the chart crosses 520 px.
The legend stays centered on the new plot without escaping the chart; the
tooltip wraps horizontally and flips above points near the bottom edge.

Tab to the plot and press Home, End, or an arrow key for a deterministic
tooltip readout. Move the pointer to inspect the styled crosshair, or
Shift-drag across the plot to inspect the box-selection slot.

~~~python demo exec
import reflex_xy
import xy


stress_x = [0, 1, 2, 3, 4, 5, 6, 7]
stress_names = [
    "Authentication reconciliation",
    "Payments settlement",
    "Inventory replication coordinator",
]
stress_colors = [
    "#2563eb",
    "#7c3aed",
    "#db2777",
]
incident_data = {
    "sample": stress_x,
    "latency_ms": [8.4, 7.1, 6.3, 5.8, 4.7, 3.6, 2.4, 1.0],
    "service_tier": [
        "edge",
        "edge",
        "core",
        "core",
        "priority",
        "priority",
        "critical",
        "critical-payments-reconciliation-with-extra-long-label",
    ],
    "requests_per_minute": [1200, 1800, 2400, 3300, 4700, 6800, 9100, 12400],
}

responsive_chrome_chart = xy.chart(
    *(
        xy.line(
            stress_x,
            [2.2 + index * 0.35 + ((point + index) % 3) * 0.24 for point in stress_x],
            name=name,
            color=color,
            width=1.2,
            opacity=0.58,
        )
        for index, (name, color) in enumerate(zip(stress_names, stress_colors))
    ),
    xy.scatter(
        x="sample",
        y="latency_ms",
        color="#f97316",
        size="requests_per_minute",
        data=incident_data,
        name="Incident samples",
        opacity=0.92,
        stroke="#ffffff",
        stroke_width=1.5,
    ),
    xy.legend(
        loc="upper center",
        ncols=2,
        title="Operational series",
    ),
    xy.tooltip(
        fields=["sample", "latency_ms", "service_tier", "requests_per_minute"],
        title="{service_tier}",
        format={"latency_ms": ".1f", "requests_per_minute": ",.0f"},
    ),
    xy.interaction_config(
        hover=True,
        click=True,
        select=True,
        brush=True,
        crosshair=True,
        view_change=True,
    ),
    # Keep this example focused on legend, tooltip, and interaction overlays.
    xy.modebar(show=False),
    xy.theme(
        crosshair_color="#e11d48",
        selection_color="#7c3aed",
        selection_fill="rgb(124 58 237 / 16%)",
    ),
    class_name=(
        "rounded-2xl border border-slate-200 bg-white text-slate-900 shadow-sm "
        "dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
    ),
    class_names={
        "legend": (
            "rounded-xl bg-white/90 shadow-lg backdrop-blur-sm dark:bg-slate-900/90"
        ),
        "tooltip": "rounded-xl bg-slate-950/95 px-3 py-2 text-white shadow-2xl",
    },
    styles={
        "legend_item": {"padding": "2px 5px"},
        "crosshair_x": {"width": 2},
        "crosshair_y": {"height": 2},
        "selection": {"border_radius": 6},
    },
    width="100%",
    height=360,
    title="Responsive legend and tooltip",
)


def long_legend_edge_tooltip_preview():
    return reflex_xy.chart(responsive_chrome_chart, height="360px")
~~~

The automatic legend width and height are browser defaults, not inline
author styles. `class_names["legend"]`, `styles["legend"]`, or the
component-local `legend(style=...)` can therefore replace either limit. The
same is true for tooltip wrapping and maximum size. If you remove those
limits intentionally, overflow becomes the responsibility of your CSS.

## Trend and cumulative marks

One coordinate system can layer the entire line-like paint vocabulary. The
lower-opacity area goes first, followed by smooth, dashed, and stepped strokes.
The `ecdf` uses a named right axis so its 0–1 range stays legible.

~~~python demo exec
import reflex_xy
import xy

x = [0, 1, 2, 3, 4, 5, 6]

trend_atlas = xy.chart(
    xy.area(
        x,
        [2, 3, 3, 5, 4, 6, 7],
        name="Area",
        color="#c4b5fd",
        fill="linear-gradient(to top, transparent, currentColor)",
        opacity=0.46,
        line_color="#7c3aed",
        line_width=1.5,
    ),
    xy.line(
        x,
        [3, 4, 4, 6, 5, 7, 8],
        name="Line",
        color="#2563eb",
        width=2.5,
        curve="smooth",
    ),
    xy.step(
        x,
        [1, 2, 2, 4, 3, 5, 6],
        name="Step",
        color="#ea580c",
        width=2,
        dash="dashed",
    ),
    xy.stairs(
        [1.4, 2.1, 1.8, 3.2, 2.7, 4.1, 4.8],
        edges=[0, 1, 2, 3, 4, 5, 6, 7],
        name="Stairs",
        color="#0f766e",
        width=1.8,
        dash="dotted",
    ),
    xy.ecdf(
        [0.3, 0.8, 1.1, 1.9, 2.7, 3.4, 4.8, 5.2, 5.9],
        name="ECDF",
        color="#be123c",
        width=2,
        y_axis="y2",
    ),
    xy.x_axis(label="ordered domain"),
    xy.y_axis(label="value"),
    xy.y_axis(
        id="y2",
        side="right",
        label="cumulative share",
        domain=(0, 1),
        format=".0%",
        style={"label_color": "#be123c", "tick_label_color": "#be123c"},
    ),
    xy.legend(loc="upper left", ncols=3),
    title="Line, area, step, stairs, and ECDF",
)


def trend_mark_atlas_preview():
    return reflex_xy.chart(trend_atlas, height="430px")
~~~

## Points, categories, and distributions

The first chart uses all 17 scatter symbols and separates fill from stroke.
The remaining cards show `column`, `histogram`, `box`, and `violin`
treatments at independent scales so each filled-geometry path can be judged at
a useful size. `bar` uses the same paint contract as `column`, with horizontal
layout.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy


symbol_names = [
    "circle",
    "square",
    "diamond",
    "triangle",
    "triangle_down",
    "triangle_left",
    "triangle_right",
    "cross",
    "x",
    "hexagon",
    "pentagon",
    "star",
    "point",
    "pixel",
    "thin_diamond",
    "plus_line",
    "x_line",
]
symbol_colors = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#0f766e"]
symbol_children = []
for index, symbol in enumerate(symbol_names):
    symbol_x = (index % 3) * 4
    symbol_y = 5 - index // 3
    symbol_color = symbol_colors[index % len(symbol_colors)]
    symbol_stroke = symbol_color if symbol in {"plus_line", "x_line"} else "#ffffff"
    symbol_children.extend([
        xy.scatter(
            [symbol_x],
            [symbol_y],
            symbol=symbol,
            size=14,
            color=symbol_color,
            stroke=symbol_stroke,
            stroke_width=2,
        ),
        xy.text(
            symbol_x + 0.35,
            symbol_y,
            symbol,
            dy=3,
            color="var(--chart-text)",
            style={"font_size": 10},
        ),
    ])

symbol_chart = xy.scatter_chart(
    *symbol_children,
    xy.legend(show=False),
    xy.x_axis(
        domain=(-0.5, 11.8),
        tick_label_strategy="none",
        style={"axis_color": "transparent", "tick_color": "transparent"},
    ),
    xy.y_axis(
        domain=(-0.5, 5.5),
        tick_label_strategy="none",
        style={"axis_color": "transparent", "tick_color": "transparent"},
    ),
    padding=[42, 20, 24, 20],
    title="All 17 scatter symbols",
)

column_chart = xy.column_chart(
    xy.column(
        ["Starter", "Team", "Business", "Enterprise"],
        [34, 58, 76, 93],
        name="Adoption",
        fill="linear-gradient(to top, #2563eb, #93c5fd)",
        stroke="#1e3a8a",
        stroke_width=1,
        corner_radius=(8, 1),
    ),
    xy.y_axis(domain=(0, 100), format=".0f"),
    title="Gradient columns",
)

histogram_chart = xy.histogram_chart(
    xy.histogram(
        [2, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 7, 8, 9],
        bins=7,
        name="Histogram",
        color="#c4b5fd",
        fill="linear-gradient(to top, #ede9fe, #7c3aed)",
        opacity=0.82,
        corner_radius=(5, 1),
        stroke="#6d28d9",
        stroke_width=0.8,
    ),
    title="Rounded histogram",
)

distribution_chart = xy.chart(
    xy.violin(
        [2, 3, 3, 4, 4, 4.5, 5, 5, 5.5, 6, 6, 7, 8, 9],
        name="Violin",
        color="#0ea5e9",
        opacity=0.38,
        width=0.9,
    ),
    xy.box(
        [2, 3, 3, 4, 4, 5, 5, 6, 7, 9],
        name="Box",
        color="#7c3aed",
        opacity=0.62,
        width=0.42,
    ),
    xy.legend(loc="upper right"),
    title="Violin with box overlay",
)

matrix_categories = ["Starter", "Team", "Business", "Enterprise"]
matrix_values = [
    [18, 27, 34, 43],
    [11, 19, 28, 37],
    [7, 13, 22, 31],
]
matrix_colors = ["#2563eb", "#7c3aed", "#db2777"]

grouped_bar_chart = xy.bar_chart(
    xy.bar(
        matrix_categories,
        matrix_values,
        orientation="horizontal",
        mode="grouped",
        series=["Core", "Growth", "New"],
        colors=matrix_colors,
        corner_radius=(7, 2),
        stroke="#ffffff",
        stroke_width=0.8,
    ),
    xy.legend(loc="lower right", ncols=3),
    padding=[42, 30, 54, 88],
    title="Grouped horizontal bars",
)

normalized_column_chart = xy.column_chart(
    xy.column(
        matrix_categories,
        matrix_values,
        mode="normalized",
        series=["Core", "Growth", "New"],
        colors=matrix_colors,
        corner_radius=(6, 1),
        stroke="#ffffff",
        stroke_width=0.8,
    ),
    xy.legend(loc="upper left", ncols=3),
    xy.y_axis(domain=(0, 1), format=".0%"),
    title="Normalized stacked columns",
)


def categorical_distribution_atlas_preview():
    return rx.el.div(
        reflex_xy.chart(symbol_chart, height="430px"),
        reflex_xy.chart(column_chart, height="310px"),
        reflex_xy.chart(histogram_chart, height="310px"),
        reflex_xy.chart(distribution_chart, height="310px"),
        reflex_xy.chart(grouped_bar_chart, height="330px"),
        reflex_xy.chart(normalized_column_chart, height="330px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

Grouped, stacked, and normalized matrix modes share the same per-series color,
stroke, gradient, and asymmetric-corner contract. The final two cards make the
grouped and normalized paths visible; use `mode="stacked"` for absolute stacks.
`hist(values, ...)` is the short spelling for `histogram(values, ...)`.

## Scalar fields and density

`heatmap` supplies the filled scalar field and `contour` supplies its crisp
isolines. The second chart shows screen-bounded `hexbin` geometry. These marks
accept deliberately narrower paint vocabularies than DOM chrome because their
color is data-driven.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

field = [
    [0.0, 0.2, 0.4, 0.1],
    [0.2, 0.8, 1.1, 0.5],
    [0.1, 0.6, 0.9, 0.4],
    [0.0, 0.2, 0.3, 0.1],
]

field_chart = xy.chart(
    xy.heatmap(field, colormap="purples", opacity=0.86),
    xy.contour(
        field,
        levels=7,
        color="#312e81",
        colormap="purples",
        width=1.4,
        opacity=0.9,
    ),
    xy.colorbar(
        title="Intensity",
        orientation="vertical",
        ticks=[0.0, 0.5, 1.1],
        style={
            "background": "var(--chart-bg)",
            "border": "1px solid var(--chart-axis)",
            "color": "var(--chart-text)",
            "border-radius": 8,
        },
    ),
    styles={
        "colorbar_bar": {"border_radius": 4},
        "colorbar_tick": {"color": "var(--chart-text)"},
        "colorbar_title": {"font_weight": 700},
    },
    title="Heatmap with contour overlay",
)

hex_x = (
    [
        -1.8,
        -1.5,
        -1.3,
        -1.1,
        -0.9,
        -0.7,
        -0.5,
        -0.3,
        -0.1,
        0.1,
        0.3,
        0.5,
        0.7,
        0.9,
        1.1,
        1.3,
        1.5,
        1.8,
    ]
    + [-0.3] * 4
    + [0.9] * 6
)
hex_y = (
    [
        -0.9,
        -0.5,
        -0.7,
        -0.2,
        -0.4,
        0.1,
        -0.1,
        0.4,
        0.2,
        0.7,
        0.4,
        0.9,
        0.6,
        1.2,
        0.8,
        1.4,
        1.1,
        1.6,
    ]
    + [0.4] * 4
    + [1.2] * 6
)

hexbin_chart = xy.hexbin_chart(
    xy.hexbin(
        hex_x,
        hex_y,
        gridsize=9,
        mincnt=1,
        colormap="viridis",
        opacity=0.9,
        style={"fill-opacity": 0.9},
    ),
    xy.colorbar(
        title="Points per hexagon",
        orientation="horizontal",
        ticks=[1, 3, 6],
    ),
    xy.x_axis(style={"grid_dash": "dotted"}),
    title="Hexagonal density",
)


def scalar_field_atlas_preview():
    return rx.el.div(
        reflex_xy.chart(field_chart, height="350px"),
        reflex_xy.chart(hexbin_chart, height="350px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

## Uncertainty and explicit geometry

This pair covers the remaining renderer paths: `error_band`, `errorbar`,
`segments`, `stem`, and `triangle_mesh`. The mesh demonstrates data-driven
fills with a constant border; segments demonstrate per-item color; stem keeps
its marker visually distinct from its shaft.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

x = [0, 1, 2, 3, 4, 5]
estimate = [3, 4, 4.5, 6, 6.5, 8]

uncertainty_chart = xy.chart(
    xy.error_band(
        x,
        [value - 0.8 for value in estimate],
        [value + 0.8 for value in estimate],
        name="90% interval",
        color="#a78bfa",
        fill="linear-gradient(to top, transparent, currentColor)",
        opacity=0.38,
        line_width=1,
        line_opacity=0.65,
    ),
    xy.errorbar(
        x,
        estimate,
        yerr=[0.4, 0.7, 0.5, 0.8, 0.6, 0.5],
        name="Observed error",
        color="#6d28d9",
        width=1.7,
        cap_size=5,
    ),
    xy.line(x, estimate, name="Estimate", color="#312e81", width=2.4),
    xy.legend(loc="upper left"),
    title="Uncertainty layers",
)

geometry_chart = xy.chart(
    xy.triangle_mesh(
        [0, 1, 1],
        [0, 0, 1],
        [1, 2, 2],
        [0, 0, 1],
        [0.5, 1.5, 1.5],
        [1.2, 1.3, 2.1],
        color=[0.2, 0.65, 1.0],
        colormap="purples",
        domain=(0, 1),
        opacity=0.42,
        stroke="#6d28d9",
        stroke_width=1,
        name="Mesh",
    ),
    xy.segments(
        [0.1, 0.6, 1.1],
        [0.3, 0.7, 1.1],
        [0.8, 1.3, 1.9],
        [0.8, 1.2, 1.7],
        color=[0.1, 0.55, 1.0],
        colormap="viridis",
        domain=(0, 1),
        width=4,
        name="Segments",
    ),
    xy.stem(
        [0.25, 0.9, 1.55],
        [0.7, 1.45, 1.9],
        base=0,
        color="#e11d48",
        width=1.8,
        marker_size=7,
        name="Stems",
    ),
    xy.legend(loc="upper left"),
    title="Segments, stems, and triangle mesh",
)


def uncertainty_geometry_atlas_preview():
    return rx.el.div(
        reflex_xy.chart(uncertainty_chart, height="380px"),
        reflex_xy.chart(geometry_chart, height="380px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

## Categorical and time axis styling

Rotated category labels, explicit time axes, and annotation labels are common
places for spacing bugs. This example keeps both cases live and gives labels
opaque backgrounds so overlap and clipping are easy to spot.

~~~python demo exec
import datetime as dt

import reflex as rx
import reflex_xy
import xy

category_chart = xy.bar_chart(
    xy.bar(
        ["Design review", "Build candidate", "Security review", "General release"],
        [46, 72, 61, 88],
        orientation="horizontal",
        fill="linear-gradient(to top, #bfdbfe, #2563eb)",
        corner_radius=(7, 1),
    ),
    xy.threshold(70, axis="x", text="target", color="#16a34a", width=2),
    xy.x_axis(label="completion", domain=(0, 100), format=".0f"),
    xy.y_axis(
        tick_label_angle=-8,
        tick_label_strategy="rotate",
        style={"tick_label_color": "var(--chart-text)", "tick_label_size": 12},
    ),
    padding=[44, 28, 54, 128],
    title="Categorical labels",
)

dates = [dt.datetime(2026, 7, day) for day in range(1, 8)]
time_chart = xy.line_chart(
    xy.line(
        dates,
        [42, 48, 45, 56, 54, 63, 68],
        color="#7c3aed",
        width=2.5,
        curve="smooth",
    ),
    xy.x_band(
        dt.datetime(2026, 7, 3),
        dt.datetime(2026, 7, 4),
        text="deploy",
        color="#f59e0b",
        opacity=0.14,
        style={
            "background": "var(--time-warning-bg, #fffbeb)",
            "label_color": "var(--time-warning-text, #92400e)",
            "padding": "2px 5px",
        },
    ),
    xy.hline(
        60,
        text="SLO",
        color="#16a34a",
        style={
            "background": "var(--time-success-bg, #f0fdf4)",
            "label_color": "var(--time-success-text, #166534)",
            "padding": "2px 5px",
        },
    ),
    xy.marker(dates[5], 63, text="marker", color="#0ea5e9", symbol="diamond"),
    xy.arrow(dates[4], 52, dates[5], 63, text="arrow", color="#e11d48"),
    xy.callout(
        dates[6],
        68,
        "callout",
        dx=-62,
        dy=-28,
        color="#7c3aed",
        style={
            "label_color": "var(--time-callout-text, #6b21a8)",
            "background": "var(--time-callout-bg, #faf5ff)",
            "border": "1px solid var(--time-callout-border, #d8b4fe)",
            "padding": "3px 6px",
        },
    ),
    xy.text(
        dates[1],
        48,
        "text / label",
        dx=8,
        dy=-18,
        color="var(--chart-text)",
    ),
    xy.x_axis(type_="time", label="July 2026", label_offset=12, tick_count=7),
    xy.y_axis(label="requests"),
    class_name=(
        "[--time-warning-bg:#fffbeb] [--time-warning-text:#92400e] "
        "[--time-success-bg:#f0fdf4] [--time-success-text:#166534] "
        "[--time-callout-bg:#faf5ff] [--time-callout-text:#6b21a8] "
        "[--time-callout-border:#d8b4fe] "
        "dark:[--time-warning-bg:#451a03] dark:[--time-warning-text:#fde68a] "
        "dark:[--time-success-bg:#14532d] dark:[--time-success-text:#bbf7d0] "
        "dark:[--time-callout-bg:#3b0764] dark:[--time-callout-text:#e9d5ff] "
        "dark:[--time-callout-border:#7e22ce]"
    ),
    padding=[48, 82, 76, 58],
    title="Time axis and annotation labels",
)


def axis_edge_cases_preview():
    return rx.el.div(
        reflex_xy.chart(category_chart, height="390px"),
        reflex_xy.chart(time_chart, height="390px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

`y_band`, `vline`, `label`, `threshold_zone`, and the corresponding x/y alias
directions use the same geometry/label split demonstrated above. The complete
annotation atlas is in [Component Variations](/docs/xy/styling/component-variations/#annotation-variants).

## A real reduction badge

Badges exist only when the representation reports a real quality tradeoff.
Enabling density while supplying per-point color produces an “aggregated
channels” badge. This example styles the badge generated from that real data
reduction.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(17)
x = rng.normal(size=12_000)
y = 0.65 * x + rng.normal(scale=0.7, size=x.size)

reduction_chart = xy.scatter_chart(
    xy.scatter(
        x,
        y,
        color=np.hypot(x, y),
        density=True,
        colormap="viridis",
        opacity=0.9,
    ),
    class_names={
        "badge": "gap-1",
        "badge_item": "rounded-full font-mono text-[10px] shadow-sm",
    },
    styles={
        "badge_item": {
            "background": "rgb(15 23 42 / 88%)",
            "border": "1px solid rgb(148 163 184 / 40%)",
            "color": "#f8fafc",
            "padding": "3px 7px",
        }
    },
    title="Density with disclosed aggregation",
)


def reduction_badge_preview():
    return reflex_xy.chart(reduction_chart, height="380px")
~~~

## Styled facets

`facet_chart` applies the same mark, axis, annotation, theme, and chart-slot
styles to every panel. XY's standalone wrapper owns the grid, so wrapper
layout selectors belong in export CSS. The docs preview below uses XY's own
SVG compositor, avoiding multiple live WebGL contexts just to demonstrate the
panel layout.

~~~python demo exec
import reflex as rx
import xy

facet_data = {
    "x": [0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3],
    "y": [1, 3, 2, 4, 4, 2, 3, 1, 2, 4, 3, 5],
    "region": ["West"] * 4 + ["East"] * 4 + ["Central"] * 4,
}

styled_facets = xy.facet_chart(
    xy.area(
        x="x",
        y="y",
        color="var(--facet-accent, #a78bfa)",
        fill="linear-gradient(currentColor, transparent)",
        line_color="var(--facet-line, #6d28d9)",
        line_width=2,
    ),
    xy.x_axis(style={"grid_dash": "dotted"}),
    xy.theme(
        plot_background="var(--facet-bg, #ffffff)",
        grid_color="var(--facet-grid, rgb(148 163 184 / 22%))",
        axis_color="var(--facet-axis, #64748b)",
        text_color="var(--facet-text, #334155)",
    ),
    xy.modebar(show=False),
    by="region",
    data=facet_data,
    cols=3,
    gap=16,
    width=900,
    height=230,
    padding=[28, 18, 34, 40],
    title="Regional trend",
)


def styled_facet_preview():
    return rx.html(
        styled_facets.to_svg(),
        class_name=(
            "w-full overflow-hidden rounded-xl border border-slate-200 "
            "bg-[var(--facet-bg)] p-2 [--facet-bg:#ffffff] "
            "[--facet-text:#334155] [--facet-grid:#94a3b838] "
            "[--facet-axis:#64748b] [--facet-accent:#a78bfa] "
            "[--facet-line:#6d28d9] [&>svg]:h-auto [&>svg]:w-full "
            "dark:border-slate-700 dark:[--facet-bg:#0f172a] "
            "dark:[--facet-text:#e2e8f0] dark:[--facet-grid:#e2e8f01f] "
            "dark:[--facet-axis:#94a3b8] dark:[--facet-accent:#c4b5fd] "
            "dark:[--facet-line:#a78bfa]"
        ),
    )
~~~

For standalone HTML, style the grid itself at export time:

~~~python
html = styled_facets.to_html(
    custom_css="""
.xy-facet-grid { gap: 1rem; padding: 1rem; background: #f8fafc; }
.xy-facet-panel { overflow: hidden; border: 1px solid #e2e8f0; border-radius: 12px; }
.xy-facet-title { color: #312e81; letter-spacing: .02em; }
"""
)
~~~

## Custom legend and custom tooltip

XY can fully restyle its built-in legend and tooltip. A genuinely custom
legend or custom tooltip is host-owned UI: hide the built-ins, keep the chart
in Reflex state, and render ordinary Reflex components from that same state.
This requires no change to Reflex or XY, but it intentionally does not become
part of a standalone XY export.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy


class StyledChromeState(rx.State):
    show_plan: bool = True
    hovered: dict = {}

    @reflex_xy.figure
    def figure(self) -> xy.Chart:
        marks = [xy.line([0, 1, 2, 3], [2, 5, 3, 7], name="Actual", color="#7c3aed")]
        if self.show_plan:
            marks.append(
                xy.line([0, 1, 2, 3], [1, 3, 4, 6], name="Plan", color="#0ea5e9")
            )
        return xy.line_chart(
            *marks,
            xy.legend(show=False),
            xy.tooltip(show=False),
        )

    @rx.event
    def record_hover(self, row: dict):
        self.hovered = row

    @rx.event
    def set_show_plan(self, value: bool):
        self.show_plan = value


def custom_chrome():
    return rx.vstack(
        reflex_xy.chart(
            StyledChromeState.figure,
            on_point_hover=StyledChromeState.record_hover,
            height="340px",
        ),
        rx.hstack(
            rx.badge("Actual", color_scheme="purple"),
            rx.checkbox(
                "Plan",
                checked=StyledChromeState.show_plan,
                on_change=StyledChromeState.set_show_plan,
            ),
        ),
        rx.callout(StyledChromeState.hovered.to_string(), icon="info"),
        width="100%",
    )
~~~

That pattern makes the legend interactive and the tooltip layout arbitrary.
For a fixed chart, a simpler host-owned key can sit next to
`reflex_xy.chart(...)`, as shown in
[Component Variations](/docs/xy/styling/component-variations/#custom-component-replacements).

## Export parity checklist

- Keep mark paint in typed props or mark `style`; WebGL, SVG, and native raster
  can all consume that contract.
- Keep essential colors in chart tokens when the export must be self-contained.
- Pass ordinary compiled CSS with `to_html(custom_css=...)` for standalone DOM
  chrome, facets, media queries, or a portable design system.
- Tailwind class names remain in the exported markup, but Tailwind's compiled
  rules are not bundled automatically.
- Host-owned Reflex components and interaction state are application UI, not
  serializable XY chart content.
- Compare live HTML with `to_svg()` and both native and Chromium `to_png()`
  when exact renderer parity matters.
