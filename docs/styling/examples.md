---
title: Examples
description: Copy polished chart patterns and explore live palette variations built with XY.
---

# Examples

Explore polished chart treatments built for real product interfaces. Each
responsive preview includes the complete Python needed to recreate it: switch
to **Code** for the chart itself and **Data** for the hardcoded series, compare
the patterns, or recolor the live playground.

Each preview displays a compact legend above the plot. The copied chart uses
`xy.legend(show=False)` so it does not render a second legend; replace it with
`xy.legend(...)` when the legend should be part of your application or export.

~~~python exec
from xy_docs.examples import chart_examples_layout_marker
~~~

~~~python eval
chart_examples_layout_marker()
~~~

## Layered momentum

Use a soft violet gradient to keep the trend readable while letting the area
carry the full visual weight.

~~~python demo exec toggle preview-code id=layered-momentum-demo
weeks = list(range(1, 13))
active_teams = [28, 32, 31, 38, 43, 41, 49, 55, 53, 61, 66, 72]

# --- chart ---
import reflex_xy
import xy


def layered_momentum():
    chart = xy.area_chart(
        xy.area(
            weeks,
            active_teams,
            name="This period",
            color="#8e51ff",
            fill="linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
            opacity=1,
            curve="smooth",
            line_width=2,
        ),
        xy.tooltip(title="Week {x}", format={"y": ",.0f"}),
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
            domain=(0, 80),
            style={
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Solar fleet output

Compare two monthly production signals with vivid blue and emerald
strokes and independent fades that preserve both series when they overlap.

~~~python demo exec toggle preview-code id=solar-fleet-output-demo
months = [
    "Jan 23", "Feb 23", "Mar 23", "Apr 23", "May 23", "Jun 23",
    "Jul 23", "Aug 23", "Sep 23", "Oct 23", "Nov 23", "Dec 23",
]
solar_panels = [2890, 2756, 3322, 3470, 3475, 3129, 3490, 2903, 2643, 2837, 2954, 3239]
inverters = [2338, 2103, 2194, 2108, 1812, 1726, 1982, 2012, 2342, 2473, 3848, 3736]

# --- chart ---
import reflex_xy
import xy


def solar_fleet_output():
    chart = xy.area_chart(
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
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Stacked product mix

Stacked columns make the total easy to compare while retaining the contribution
of each product tier. Only the exposed top of each stack is rounded.

~~~python demo exec toggle preview-code id=stacked-product-mix-demo
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
core = [28, 31, 35, 38, 42, 46]
growth = [16, 18, 19, 23, 25, 29]
enterprise = [7, 8, 10, 12, 14, 17]
growth_base = core
enterprise_base = [
    core_value + growth_value
    for core_value, growth_value in zip(core, growth, strict=True)
]

# --- chart ---
import reflex_xy
import xy


def stacked_product_mix():
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
            base=growth_base,
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
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Normalized traffic share

A 100% stacked area emphasizes how the mix changes over time independently of
the total volume. The shared boundary makes the handoff between channels easy
to follow, while the tooltip reports the actual Desktop and Mobile shares.

~~~python demo exec toggle preview-code id=normalized-traffic-share-demo
months = list(range(1, 9))
desktop = [0.68, 0.65, 0.63, 0.59, 0.61, 0.57, 0.54, 0.52]
mobile = [1.0 - share for share in desktop]
total = [1.0] * len(months)
data = {
    "month": months,
    "desktop": desktop,
    "mobile": mobile,
    "total": total,
}

# --- chart ---
import reflex_xy
import xy


def normalized_traffic_share():
    chart = xy.area_chart(
        xy.area(
            x="month",
            y="desktop",
            data=data,
            name="Desktop",
            color="#8e51ff",
            fill="linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
            opacity=1,
            curve="smooth",
            line_width=2,
        ),
        xy.area(
            x="month",
            y="total",
            base="desktop",
            data=data,
            name="Mobile",
            color="#00b8db",
            fill="linear-gradient(#00b8db4d 5%, #00b8db00 95%)",
            opacity=1,
            curve="smooth",
            line_width=2,
        ),
        # Bind the actual mobile share so both percentages are resident in the
        # tooltip payload while the visible mobile area still ends at 100%.
        xy.scatter(
            x="month",
            y="mobile",
            data=data,
            color="#00000000",
            opacity=0,
            size=1,
        ),
        xy.tooltip(
            fields=["desktop", "mobile"],
            title="Period {month}",
            format={"desktop": ".0%", "mobile": ".0%"},
        ),
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
            domain=(0, 1),
            format=".0%",
            style={
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Regional product demand

Compare demand for each product across six regions without hiding the individual
series inside a stack. Even with axis text removed, each hovered bar reports its
product and region together.

~~~python demo exec toggle preview-code id=grouped-channel-mix-demo
products = ["Analytics", "Automation", "Security", "Collaboration"]
category_centers = list(range(len(products)))
regions = [
    ("North America", [890, 289, 380, 90], "#2b7fff"),
    ("Europe", [338, 233, 535, 98], "#00bc7d"),
    ("Asia Pacific", [538, 253, 352, 28], "#8e51ff"),
    ("Latin America", [396, 333, 718, 33], "#fe9a00"),
    ("Middle East", [138, 133, 539, 61], "#6a7282"),
    ("Africa", [436, 533, 234, 53], "#00b8db"),
]
offsets = [-0.30, -0.18, -0.06, 0.06, 0.18, 0.30]

# --- chart ---
import reflex_xy
import xy


def regional_product_demand():
    columns = [
        xy.column(
            [category_centers[product_index] + offsets[region_index]],
            [values[product_index]],
            name=f"{product} · {region}",
            color=color,
            width=0.10,
            opacity=1,
            corner_radius=0,
            stroke_width=0,
        )
        for region_index, (region, values, color) in enumerate(regions)
        for product_index, product in enumerate(products)
    ]

    chart = xy.column_chart(
        *columns,
        xy.tooltip(title="Product demand", format={"y": ",.0f"}),
        xy.legend(show=False),
        xy.x_axis(
            domain=(-0.5, 3.5),
            tick_values=category_centers,
            tick_labels=products,
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
            domain=(0, 1000),
            style={
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Conversion by stage

The clean plot omits category-axis text, so each stage keeps a distinct
categorical color and the hover tooltip reports the full stage name and
completion value.

~~~python demo exec toggle preview-code id=conversion-by-stage-demo
stages = [
    "Workspace created",
    "Data connected",
    "First chart published",
    "Teammate invited",
    "Weekly habit formed",
]
completion = [94, 86, 78, 64, 52]
colors = ["#2b7fff", "#00bc7d", "#8e51ff", "#fe9a00", "#6a7282"]

# --- chart ---
import reflex_xy
import xy


def conversion_by_stage():
    bars = [
        xy.bar(
            x="stage",
            y="completion",
            data={"stage": [stage], "completion": [value]},
            name=stage,
            orientation="horizontal",
            color=color,
            corner_radius=6,
        )
        for stage, value, color in zip(stages, completion, colors, strict=True)
    ]

    chart = xy.bar_chart(
        *bars,
        xy.tooltip(
            title="{stage} · {completion}%",
            format={"completion": ".0f"},
        ),
        xy.legend(show=False),
        xy.x_axis(
            domain=(0, 100),
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
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Monthly balance

Diverging columns preserve one shared zero baseline, so gains and pullbacks are
immediately comparable without introducing a warning-red color.

~~~python demo exec toggle preview-code id=monthly-balance-demo
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
change = [0.18, 0.26, -0.14, 0.21, -0.19, 0.31, 0.24, -0.11]
gains = [value if value >= 0 else float("nan") for value in change]
pullbacks = [value if value < 0 else float("nan") for value in change]

# --- chart ---
import reflex_xy
import xy


def monthly_balance():
    chart = xy.column_chart(
        xy.column(
            months,
            gains,
            name="Gain",
            color="#2b7fff",
            corner_radius=4,
        ),
        xy.column(
            months,
            pullbacks,
            name="Pullback",
            color="#8e51ff",
            corner_radius=4,
        ),
        xy.hline(0, color="#cbd5e1", width=1),
        xy.tooltip(title="{x}", format={"y": ".0f%"}),
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
            domain=(-0.25, 0.35),
            style={
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        width="100%",
        height=410,
        padding=(16, 20, 20, 20),
    )
    return reflex_xy.chart(chart, height="410px")
~~~

## Responsive combo chart

Combine columns and a line on one shared production scale when two related
signals need different visual emphasis. Blue bars, an amber line, a compact
legend, and horizontal guides keep the two measures visually distinct;
the tooltip keeps the two named measures distinct.

~~~python demo exec toggle preview-code id=responsive-combo-chart-demo
months = [
    "Jan 23", "Feb 23", "Mar 23", "Apr 23", "May 23", "Jun 23",
    "Jul 23", "Aug 23", "Sep 23", "Oct 23", "Nov 23", "Dec 23",
]
solar_panels = [2890, 2756, 3322, 3470, 3475, 3129, 3490, 2903, 2643, 2837, 2954, 3239]
inverters = [2338, 2103, 2194, 2108, 1812, 1726, 1982, 2012, 2342, 2473, 3848, 3736]

# --- chart ---
import reflex_xy
import xy

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
    ),
    xy.legend(show=False),
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
        "tooltip": "rounded-lg bg-zinc-950 px-3 py-2 text-white shadow-xl",
    },
    width="100%",
    height=280,
    padding=[16, 20, 20, 20],
)


def responsive_combo_chart():
    return reflex_xy.chart(dashboard_combo, height="280px")
~~~

## Product constellation

Compare product adoption and retention without turning the chart into a table.
Bubble size signals account reach, while six categorical colors keep product
segments distinct in the custom legend and hover readout.

~~~python demo exec toggle preview-code id=product-constellation-demo
products = [
    ("Atlas · Platform · 18k accounts", "#2b7fff", 72, 84, 20),
    ("Forge · Platform · 11k accounts", "#2b7fff", 64, 79, 15),
    ("Harbor · Platform · 7k accounts", "#2b7fff", 53, 73, 12),
    ("Pulse · Growth · 12k accounts", "#00bc7d", 61, 76, 16),
    ("Spark · Growth · 9k accounts", "#00bc7d", 69, 81, 14),
    ("Lift · Growth · 6k accounts", "#00bc7d", 58, 68, 11),
    ("Orbit · Intelligence · 15k accounts", "#8e51ff", 82, 69, 18),
    ("Lens · Intelligence · 10k accounts", "#8e51ff", 77, 76, 15),
    ("Signal · Intelligence · 5k accounts", "#8e51ff", 86, 63, 10),
    ("Relay · Operations · 8k accounts", "#fe9a00", 47, 88, 13),
    ("Beacon · Operations · 6k accounts", "#fe9a00", 54, 92, 11),
    ("Route · Operations · 4k accounts", "#fe9a00", 43, 80, 9),
    ("Vault · Security · 10k accounts", "#6a7282", 56, 63, 15),
    ("Shield · Security · 7k accounts", "#6a7282", 63, 66, 12),
    ("Gate · Security · 5k accounts", "#6a7282", 49, 59, 10),
    ("Flow · Collaboration · 14k accounts", "#00b8db", 76, 92, 17),
    ("Canvas · Collaboration · 9k accounts", "#00b8db", 69, 88, 14),
    ("Loop · Collaboration · 6k accounts", "#00b8db", 83, 96, 11),
]

# --- chart ---
import reflex_xy
import xy


def product_constellation():
    bubbles = [
        xy.scatter(
            x="adoption",
            y="retention",
            data={"adoption": [adoption], "retention": [retention]},
            name=name,
            color=color,
            size=size,
            opacity=0.86,
            density=False,
            stroke="#ffffff",
            stroke_width=2,
        )
        for name, color, adoption, retention, size in products
    ]

    chart = xy.scatter_chart(
        *bubbles,
        xy.legend(show=False),
        xy.tooltip(
            fields=["adoption", "retention"],
            format={"adoption": ".0f%", "retention": ".0f%"},
        ),
        xy.modebar(show=False),
        xy.x_axis(
            domain=(35, 90),
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
            domain=(55, 100),
            tick_label_strategy="off",
            style={
                "grid_color": "var(--constellation-grid, #e5e7eb)",
                "grid_width": 1,
                "grid_opacity": 0.7,
                "axis_width": 0,
                "axis_color": "#00000000",
                "tick_width": 0,
                "tick_color": "#00000000",
                "tick_label_color": "#00000000",
                "label_color": "#00000000",
            },
        ),
        xy.theme(
            plot_background="var(--constellation-surface, #ffffff)",
            grid_color="var(--constellation-grid, #e5e7eb)",
            text_color="var(--constellation-text, #6a7282)",
        ),
        class_name=(
            "bg-[#ffffff] [--constellation-surface:#ffffff] "
            "[--constellation-grid:#e5e7eb] [--constellation-text:#6a7282] "
            "dark:bg-[#000000] dark:[--constellation-surface:#000000] "
            "dark:[--constellation-grid:#27272a] dark:[--constellation-text:#99a1af]"
        ),
        width="100%",
        height=380,
        padding=[16, 24, 24, 24],
    )
    return reflex_xy.chart(chart, height="380px")
~~~

## Release velocity

Lollipop stems make release cadence easy to scan without adding another bar
chart. Violet tracks the stable channel and cyan highlights the faster preview
channel, with release names and deploy counts available on hover.

~~~python demo exec toggle preview-code id=release-velocity-demo
stable = {
    "release": ["v1.8", "v2.0", "v2.2", "v2.4"],
    "velocity": [18, 26, 31, 38],
}
preview = {
    "release": ["v1.9", "v2.1", "v2.3", "v2.5"],
    "velocity": [23, 34, 29, 45],
}

# --- chart ---
import reflex_xy
import xy


def release_velocity():
    chart = xy.stem_chart(
        xy.stem(
            x="release",
            y="velocity",
            data=stable,
            name="Stable",
            color="#8e51ff",
            width=2,
            marker_size=8,
        ),
        xy.stem(
            x="release",
            y="velocity",
            data=preview,
            name="Preview",
            color="#00b8db",
            width=2,
            marker_size=8,
        ),
        xy.legend(show=False),
        xy.tooltip(
            fields=["velocity"],
            title="{release}",
            format={"velocity": ".0f"},
        ),
        xy.modebar(show=False),
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
            domain=(0, 50),
            tick_label_strategy="off",
            style={
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
            plot_background="var(--velocity-surface, #ffffff)",
            grid_color="var(--velocity-grid, #e5e7eb)",
            text_color="var(--velocity-text, #6a7282)",
        ),
        class_name=(
            "bg-[#ffffff] [--velocity-surface:#ffffff] "
            "[--velocity-grid:#e5e7eb] [--velocity-text:#6a7282] "
            "dark:bg-[#000000] dark:[--velocity-surface:#000000] "
            "dark:[--velocity-grid:#27272a] dark:[--velocity-text:#99a1af]"
        ),
        width="100%",
        height=360,
        padding=[16, 24, 24, 24],
    )
    return reflex_xy.chart(chart, height="360px")
~~~

## Palette playground

Choose a preset to recolor a responsive grid of area and bar charts in real
time. Copy any card when the palette and chart treatment fit your product.

~~~python exec
from xy_docs.playground import chart_playground
~~~

~~~python eval
chart_playground()
~~~

## Build your own

These examples use the same public composition model as the rest of XY. Start
from the closest pattern, replace the data, then tune the mark colors, axes,
tooltip, and theme. For the full option surface, continue to
[Line](/docs/xy/charts/line-chart/),
[Bar](/docs/xy/charts/bar-chart/), or the broader
[Styling Gallery](/docs/xy/styling/gallery/).
