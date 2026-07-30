---
title: Pie and Donut Charts in Python
description: Build polished pie, donut, progress-ring, and gauge blocks in Python with xy and Reflex.
components:
  - xy.pie_chart
---

# Pie and Donut Charts in Python

A pie chart maps each share to an angular span. A donut uses the same sectors
with a positive inner radius, leaving room for a total, status, or supporting
label. In XY, both are compositions of unequal-width bars inside
`polar_bar_chart()`. For the standard composition, use
`xy.pie_chart(labels, values, hole=...)`; the examples below use the lower-level
bars directly to demonstrate custom sector geometry and dashboard layouts.

The first example keeps the chart intentionally small. The examples after it
combine XY's exportable sector geometry with ordinary Reflex layout for center
labels, legends, captions, and summary rows. That separation keeps the data
visualization reusable while the surrounding block remains easy to adapt to a
dashboard.

~~~python exec
from xy_docs.examples import chart_examples_layout_marker
~~~

~~~python eval
chart_examples_layout_marker()
~~~

## Basic Pie Chart

A filled pie starts with simple label-and-value data. The chart converts each
value to an angular width, and `base=0` makes every sector reach the center:

~~~python demo exec
import reflex_xy
import xy

PIE_DATA = [
    ("Direct", 40),
    ("Partner", 30),
    ("Organic", 20),
    ("Other", 10),
]
PURPLE_SHADES = ["#6e56cf", "#806bd5", "#9888dd", "#b5aae8"]

total = sum(value for _label, value in PIE_DATA)
widths = [value / total * 360 for _label, value in PIE_DATA]
angles = [
    sum(widths[:index]) + width / 2
    for index, width in enumerate(widths)
]

pie = xy.polar_bar_chart(
    *(
        xy.bar(
            [angle],
            [1],
            base=0,
            width=width,
            color=color,
            name=f"{label} · {value / total:.0%}",
            opacity=1,
        )
        for (label, value), angle, width, color in zip(
            PIE_DATA,
            angles,
            widths,
            PURPLE_SHADES,
            strict=True,
        )
    ),
    xy.theta_axis(unit="degrees", zero="N", show=False, tick_label_strategy="none"),
    xy.r_axis(show=False, tick_label_strategy="none"),
    xy.legend(loc="left"),
    xy.modebar(show=False),
)


def basic_pie_demo():
    return reflex_xy.chart(pie, height="320px")
~~~

`PIE_DATA` stays independent of the chart geometry, so changing a value updates
both its slice and legend percentage. The separate palette uses the same
`#6e56cf` primary purple used throughout these docs.

## Market Share

Use a high-contrast donut when the whole is meaningful and every slice needs a
compact percentage label. The two-column legend preserves the names and raw
values without crowding the ring:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

MARKET_SERIES = [
    ("Skyline", 27, "#0a0a0a"),
    ("Datawell", 21, "#262626"),
    ("Cloudpeak", 13, "#3d3d3d"),
    ("Taskbridge", 21, "#545454"),
    ("Insightloop", 6, "#6b6b6b"),
    ("Streamforge", 12, "#7d7d7d"),
]


def sector_layout(values):
    spans = [value / sum(values) * 360.0 for value in values]
    centers, cursor = [], 0.0
    for span in spans:
        centers.append(cursor + span / 2.0)
        cursor += span
    return centers, spans


market_angles, market_widths = sector_layout(
    [value for _label, value, _color in reversed(MARKET_SERIES)],
)

market_share = xy.polar_bar_chart(
    *(
        xy.bar(
            [angle],
            [0.42],
            base=0.52,
            width=width,
            name=label,
            color=color,
            opacity=1,
            stroke="#ffffff",
            stroke_width=3,
        )
        for (label, _value, color), angle, width in zip(
            reversed(MARKET_SERIES),
            market_angles,
            market_widths,
            strict=True,
        )
    ),
    *(
        xy.text(
            angle,
            0.73,
            f"{value}%",
            dx=0,
            dy=4,
            anchor="middle",
            color="#ffffff",
            class_name="text-xs font-medium",
        )
        for (_label, value, _color), angle in zip(
            reversed(MARKET_SERIES),
            market_angles,
            strict=True,
        )
    ),
    xy.theta_axis(
        unit="degrees",
        zero="N",
        direction="counterclockwise",
        show=False,
        tick_label_strategy="none",
    ),
    xy.r_axis(
        domain=(0.0, 1.0),
        show=False,
        tick_label_strategy="none",
    ),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.theme(plot_background="#ffffff", text_color="#171717"),
    width="100%",
    height=243,
    padding=(0, 0, 0, 0),
)


def market_legend_item(label, value, color):
    return rx.el.button(
        rx.el.span(
            class_name="size-3 shrink-0 rounded-[3px]",
            style={"background": color},
        ),
        rx.el.span(label, class_name="font-medium text-zinc-950"),
        rx.el.span(f"${value}B", class_name="text-zinc-500"),
        rx.el.span(f"({value}%)", class_name="text-zinc-400"),
        type="button",
        aria_label=f"{label} ${value}B ({value}%)",
        class_name=(
            "flex cursor-default items-center gap-2 border-0 bg-transparent "
            "p-0 text-left text-xs"
        ),
    )


def market_share_demo():
    return rx.el.div(
        rx.el.div(
            reflex_xy.chart(market_share, height="243px"),
            rx.el.div(
                rx.el.span(
                    "$100B",
                    class_name="text-3xl font-semibold tracking-tight text-zinc-950",
                ),
                rx.el.span(
                    "Ecosystem value",
                    class_name="text-xs text-zinc-500",
                ),
                class_name=(
                    "pointer-events-none absolute inset-0 flex flex-col "
                    "items-center justify-center gap-0.5"
                ),
            ),
            class_name="relative min-h-0 w-full flex-1",
        ),
        rx.el.div(
            *(
                market_legend_item(label, value, color)
                for label, value, color in MARKET_SERIES
            ),
            class_name=(
                "mt-3 grid grid-flow-col grid-cols-2 grid-rows-3 "
                "gap-x-6 gap-y-1.5 border-t border-zinc-200 pt-3"
            ),
        ),
        class_name=(
            "mx-auto flex h-[22.5rem] w-full max-w-[630px] flex-col bg-white p-4"
        ),
    )
~~~

The slot width remains proportional to the value. A three-pixel
background-colored stroke creates a constant screen-space separator; unlike an
angular gap, it stays visually even at the inner and outer rim. Text annotations
use `(theta, radius)` coordinates, so their anchors remain attached to the
slices in browser and static output.

## Progress Rings

A thin annulus can behave like a circular progress bar. Splitting it into 40
rounded dashes gives the display a lighter rhythm than one continuous arc:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

PROGRESS_STATS = [
    (48, "Additional support requests from users."),
    (67, "Inaccurate forecasts disrupt planning."),
]


def progress_ring(value):
    dots = 40
    filled = round(dots * value / 100)
    active = [228 / 255, 56 / 255, 97 / 255]
    track = [212 / 255, 212 / 255, 212 / 255]
    return xy.polar_bar_chart(
        xy.bar(
            [index * 9.0 for index in range(dots)],
            [0.07] * dots,
            base=0.85,
            width=4.5,
            color=[
                active if index < filled else track
                for index in range(dots)
            ],
            opacity=1,
            corner_radius=6,
        ),
        xy.theta_axis(
            unit="degrees",
            zero="N",
            direction="counterclockwise",
            show=False,
            tick_label_strategy="none",
        ),
        xy.r_axis(
            domain=(0.0, 1.0),
            show=False,
            tick_label_strategy="none",
        ),
        xy.legend(show=False),
        xy.modebar(show=False),
        xy.theme(plot_background="#ffffff"),
        width="100%",
        height=265,
        padding=(0, 0, 0, 0),
    )


def progress_panel(value, caption):
    return rx.el.div(
        reflex_xy.chart(progress_ring(value), height="265px"),
        rx.el.div(
            rx.el.span(
                f"{value}%",
                class_name="text-4xl leading-none font-medium tracking-tight text-zinc-950",
            ),
            rx.el.span(
                caption,
                class_name="text-balance text-xs leading-snug text-zinc-500",
            ),
            class_name=(
                "pointer-events-none absolute inset-0 flex flex-col items-center "
                "justify-center gap-1 bg-[radial-gradient(circle_closest-side,"
                "rgba(0,0,0,0.04)_0_79%,transparent_79%)] px-[25%] text-center"
            ),
        ),
        class_name="relative min-h-0",
    )


def progress_rings_demo():
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "User research",
                    class_name="text-[10px] uppercase tracking-wide text-zinc-500",
                ),
                rx.el.span(
                    "Where the workday leaks",
                    class_name="text-xl leading-tight font-medium tracking-tight text-zinc-950",
                ),
                class_name="flex flex-col gap-0.5",
            ),
            rx.el.span(
                "1,240 responses",
                class_name="shrink-0 text-xs text-zinc-500",
            ),
            class_name="flex items-start justify-between gap-4",
        ),
        rx.el.div(
            *(
                progress_panel(value, caption)
                for value, caption in PROGRESS_STATS
            ),
            class_name="mt-3 grid min-h-0 flex-1 grid-cols-2 gap-4",
        ),
        class_name=(
            "mx-auto flex h-[22.5rem] w-full max-w-[630px] flex-col bg-white p-4"
        ),
    )
~~~

Each visible dash occupies half of a nine-degree slot. The remaining half is
the gap, so the track stays evenly spaced without creating transparent data
rows.

## Revenue Mix

For a smaller category set, pair a rounded donut with a value list. The center
answers the primary question while the aligned legend supports exact lookup:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

REVENUE_SERIES = [
    ("Direct", 52_400, "#7c3aed", "#a855f7"),
    ("Marketplace", 38_900, "#4f46e5", "#6366f1"),
    ("Wholesale", 24_150, "#0284c7", "#0ea5e9"),
    ("Affiliate", 16_300, "#059669", "#10b981"),
]


def sector_layout(values):
    spans = [value / sum(values) * 360.0 for value in values]
    centers, cursor = [], 0.0
    for span in spans:
        centers.append(cursor + span / 2.0)
        cursor += span
    return centers, spans


revenue_angles, revenue_widths = sector_layout(
    [value for _label, value, _start, _end in REVENUE_SERIES],
)

revenue_mix = xy.polar_bar_chart(
    *(
        xy.bar(
            [angle],
            [0.30],
            base=0.62,
            width=width,
            name=label,
            fill={
                "gradient": f"linear-gradient(to right, {start}, {end})",
                "space": "plot",
            },
            opacity=1,
            corner_radius=12,
            stroke="#ffffff",
            stroke_width=6,
        )
        for (label, _value, start, end), angle, width in zip(
            REVENUE_SERIES,
            revenue_angles,
            revenue_widths,
            strict=True,
        )
    ),
    xy.theta_axis(
        unit="degrees",
        zero="N",
        direction="counterclockwise",
        show=False,
        tick_label_strategy="none",
    ),
    xy.r_axis(
        domain=(0.0, 1.0),
        show=False,
        tick_label_strategy="none",
    ),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.theme(plot_background="#ffffff"),
    width="100%",
    height=280,
    padding=(0, 0, 0, 0),
)


def revenue_row(label, value, color):
    return rx.el.div(
        rx.el.span(
            class_name="size-2.5 shrink-0 rounded-[3px]",
            style={"background": color},
        ),
        rx.el.span(label, class_name="truncate text-xs text-zinc-500"),
        rx.el.span(
            f"${value:,}",
            class_name="ml-auto text-xs font-semibold text-zinc-950",
        ),
        class_name="flex items-center gap-2 py-2",
    )


def revenue_mix_demo():
    return rx.el.div(
        rx.el.div(
            reflex_xy.chart(revenue_mix, height="100%"),
            rx.el.div(
                rx.el.div(
                    rx.el.span(
                        "1,284",
                        class_name="text-2xl leading-none font-semibold tracking-tight text-zinc-950",
                    ),
                    rx.el.span(
                        "Total orders",
                        class_name="mt-1 text-xs text-zinc-500",
                    ),
                    class_name=(
                        "flex aspect-square w-[56%] flex-col items-center "
                        "justify-center rounded-full border border-dashed border-zinc-200"
                    ),
                ),
                class_name=(
                    "pointer-events-none absolute inset-0 flex items-center justify-center"
                ),
            ),
            class_name="relative aspect-square w-[40%] max-w-72 shrink-0",
        ),
        rx.el.div(
            *(
                revenue_row(label, value, start)
                for label, value, start, _end in REVENUE_SERIES
            ),
            class_name="flex min-h-0 min-w-0 flex-1 flex-col justify-center",
        ),
        class_name=(
            "mx-auto flex h-[22.5rem] w-full max-w-[630px] "
            "items-center gap-6 bg-white p-4"
        ),
    )
~~~

Rounded corners are available when `base` is positive. A CSS linear gradient
paints each one-slice mark independently, so every segment can keep its own
two-color ramp.

## Reliability Score

A partial donut becomes a gauge when its angular span represents an ordered
scale. Keep the qualitative bands in the ring and repeat them as a linear key
for exact threshold lookup:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

RELIABILITY_BANDS = [
    ("At risk", 450, "#e11d48"),
    ("Fair", 200, "#f59e0b"),
    ("Good", 170, "#84cc16"),
    ("Excellent", 180, "#059669"),
]
SCORE = 842
GAUGE_SPAN = 240.0
GAUGE_START = -120.0


def gauge_layout(values):
    spans = [value / sum(values) * GAUGE_SPAN for value in values]
    centers, cursor = [], GAUGE_START
    for span in spans:
        centers.append(cursor + span / 2.0)
        cursor += span
    return centers, spans


gauge_angles, gauge_widths = gauge_layout(
    [value for _label, value, _color in reversed(RELIABILITY_BANDS)],
)

reliability_gauge = xy.polar_bar_chart(
    *(
        xy.bar(
            [angle],
            [0.20],
            base=0.74,
            width=width,
            name=label,
            color=color,
            opacity=1,
            corner_radius=10,
            stroke="#ffffff",
            stroke_width=6,
        )
        for (label, _value, color), angle, width in zip(
            reversed(RELIABILITY_BANDS),
            gauge_angles,
            gauge_widths,
            strict=True,
        )
    ),
    xy.theta_axis(
        unit="degrees",
        zero="N",
        direction="counterclockwise",
        show=False,
        tick_label_strategy="none",
    ),
    xy.r_axis(
        domain=(0.0, 1.0),
        show=False,
        tick_label_strategy="none",
    ),
    xy.legend(show=False),
    xy.modebar(show=False),
    xy.theme(plot_background="#ffffff"),
    width="100%",
    height=200,
    padding=(0, 0, 0, 0),
)


def reliability_scale():
    starts = [0, 450, 650, 820]
    return rx.el.div(
        rx.el.div(
            *(
                rx.el.span(
                    str(start),
                    class_name="text-left",
                    style={"flex_grow": value, "flex_basis": 0},
                )
                for start, (_label, value, _color) in zip(
                    starts,
                    RELIABILITY_BANDS,
                    strict=True,
                )
            ),
            rx.el.span("1000"),
            class_name="flex text-[10px] text-zinc-500",
        ),
        rx.el.div(
            *(
                rx.el.span(
                    class_name="h-1.5 rounded-full",
                    style={
                        "background": color,
                        "flex_grow": value,
                        "flex_basis": 0,
                    },
                )
                for _label, value, color in RELIABILITY_BANDS
            ),
            class_name="mt-1 flex gap-1",
        ),
        class_name="mt-auto shrink-0 pt-2",
    )


def reliability_score_demo():
    return rx.el.div(
        rx.el.span(
            "Delivery Reliability",
            class_name="text-lg font-medium tracking-tight text-zinc-950",
        ),
        rx.el.div(
            reflex_xy.chart(reliability_gauge, height="200px"),
            rx.html(
                """
                <svg viewBox="0 0 100 100" aria-hidden="true">
                  <path d="M 23.15 65.5 A 31 31 0 1 1 76.85 65.5"
                    fill="none" stroke="#a1a1aa" stroke-width="1"
                    stroke-linecap="round" stroke-dasharray="0.1 5"/>
                </svg>
                """,
                class_name="pointer-events-none absolute inset-0 opacity-50",
            ),
            rx.el.div(
                rx.el.span(
                    str(SCORE),
                    class_name="text-4xl font-semibold tracking-tight text-zinc-950",
                ),
                class_name=(
                    "pointer-events-none absolute inset-0 flex items-center justify-center"
                ),
            ),
            class_name="relative mx-auto mt-1 aspect-square w-full max-w-50 shrink-0",
        ),
        rx.el.div(
            rx.el.p(
                "Reliability is excellent",
                class_name="text-sm font-medium text-zinc-950",
            ),
            rx.el.p(
                "Updated 12 Mar 2026",
                class_name="text-xs text-zinc-500",
            ),
            class_name="text-center",
        ),
        reliability_scale(),
        class_name=(
            "mx-auto flex h-[22.5rem] w-full max-w-[630px] flex-col bg-white p-4"
        ),
    )
~~~

This example keeps a full circular layout and authors only 240 degrees of
colored bars, matching a conventional dashboard gauge. Use
`theta_axis(sector=(start, end))` instead when the visible arc should expand to
fill the plot box.

## Build Your Own Pie Block

1. Normalize values to a full turn (360 degrees or `2π` radians).
2. Use the cumulative midpoint of each slot as the bar angle.
3. Add a background-colored stroke for a constant-pixel separator, or subtract
   a small angle from each slot when the gap should scale with the ring.
4. Give every slice the same `base` and height.
5. Hide the axes and compose labels or legends around the chart with Reflex.

Set `base=0` for a filled pie. For donuts, a positive base enables rounded
sector corners. Per-slice gradients are easiest to express as one single-slice
bar mark per category.

## Interaction and Export

Pie blocks use the shared polar renderer. These examples set
`xy.modebar(show=False)` to keep the presentation clean. The underlying
interactions and APIs remain intact: sector hover, radial wheel zoom,
double-click reset, and browser/static exports remain available. A hovered slice
reads its own label and value; the layout angle and the constant rim radius stay
out of the readout.
Center labels and legends composed in Reflex are browser UI; annotations placed
with `xy.text()` are part of the chart and are preserved in SVG and native
raster exports.

See [Radial bar charts](/docs/xy/charts/radial-bar-chart/) for width, base,
corner-radius, clipping, and partial-sector details.

## Related Polar Charts

- [Polar overview](/docs/xy/charts/polar-chart/) — shared axes, interaction,
  annotations, pyplot, and renderer limits.
- [Radial bar charts](/docs/xy/charts/radial-bar-chart/) — equal-angle and
  variable-height annular sectors.
- [Radar charts](/docs/xy/charts/radar-chart/) — categorical profile
  comparisons.
- [Wind rose charts](/docs/xy/charts/wind-rose/) — direction and speed
  distributions.

## FAQ

### Does XY have a dedicated pie mark?

No. Pie and donut geometry is composed from `xy.bar()` marks inside
`xy.polar_bar_chart()`. This keeps sector styling and export behavior on the
same renderer as radial bars.

### How do I add space between slices?

For an even screen-space separator, keep the proportional `width` and add a
background-colored `stroke` with `stroke_width=`. For an angular gap, pass a
slightly smaller per-item `width` while keeping each slot midpoint unchanged.

### How do I round donut slices?

Pass `corner_radius=` on bars whose `base` is positive. A filled pie reaches
the center and therefore keeps a sharp center vertex.
