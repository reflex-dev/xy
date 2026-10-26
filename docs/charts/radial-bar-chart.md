---
title: Radial Bar Charts in Python
description: Create radial bar charts in Python with xy. Build radial bar plots, progress rings, gauge charts, and semicircular capacity blocks.
components:
  - xy.polar_bar_chart
---

# Radial Bar Charts in Python

A **radial bar chart** (also called a radial bar plot or radial bar graph)
encodes each value as an annular sector. The bar's first
channel is its center angle, its second is its radial height, `width` controls
the angular span, and `base` controls the inner radius.

Jump to [a basic radial bar chart](#basic-radial-bar-chart),
[inner radius and sector geometry](#inner-radius-and-sector-geometry), or
[partial gauges](#partial-gauges).

The first example keeps that geometry intentionally small. The blocks after it
combine XY's exportable sectors with ordinary Reflex layout for center values,
legends, rails, and summary statistics. This keeps the visualization reusable
without forcing dashboard UI into the chart itself.

~~~python exec
from xy_docs.examples import chart_examples_layout_marker
~~~

~~~python eval
chart_examples_layout_marker()
~~~

## Basic Radial Bar Chart

Start with six named values at evenly spaced angles. Each row also carries one
shade from the purple palette used throughout these docs:

~~~python demo exec
import reflex_xy
import xy

RADIAL_DATA = [
    ("Direct", 0, 6, "#5b3cc4"),
    ("Search", 60, 9, "#6e56cf"),
    ("Email", 120, 7, "#806bd5"),
    ("Partner", 180, 11, "#927edc"),
    ("Social", 240, 8, "#a596e4"),
    ("Other", 300, 5, "#b8afea"),
]

radial_bars = xy.polar_bar_chart(
    *(
        xy.bar(
            [angle],
            [value],
            width=48,
            color=color,
            name=label,
        )
        for label, angle, value, color in RADIAL_DATA
    ),
    xy.theta_axis(
        unit="degrees",
        zero="N",
        direction="clockwise",
        tick_values=[0, 60, 120, 180, 240, 300],
    ),
    xy.r_axis(
        label="value",
        domain=(0, 12),
        tick_values=[0, 4, 8, 12],
    ),
    xy.legend(loc="right"),
    xy.modebar(show=False),
)


def radial_bar_demo():
    return reflex_xy.chart(radial_bars, height="320px")
~~~

`RADIAL_DATA` stays independent of the chart construction, so labels, values,
and colors are easy to replace. The named one-bar marks populate the legend,
while the authored ticks keep the angular and radial axes easy to read. Pass
one scalar `width` for equal angular spans or a same-length sequence for
per-bar spans. Widths must be finite and positive.

## Allocation Overview

Small progress rings work well when several categories share one maximum. Each
ring below is an explicit muted track plus a colored foreground sector; the
table repeats the values for exact lookup:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

ALLOCATION_DATA = [
    ("Platform", 44, 880_000, "#6e56cf"),
    ("Product", 24, 480_000, "#806bd5"),
    ("Growth", 15, 300_000, "#9888dd"),
    ("Operations", 10, 200_000, "#b5aae8"),
    ("Support", 7, 140_000, "#d2cbf1"),
]


def allocation_ring_chart(label, percent, color):
    span = percent / 100 * 360.0
    return xy.polar_bar_chart(
        xy.bar(
            [180.0],
            [0.12],
            base=0.72,
            width=360.0,
            color="#eeecf6",
            opacity=1,
        ),
        xy.bar(
            [span / 2.0],
            [0.12],
            base=0.72,
            width=span,
            color=color,
            opacity=1,
            corner_radius=8,
            name=f"{label} · {percent}%",
        ),
        xy.theta_axis(
            unit="degrees",
            zero="N",
            direction="clockwise",
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
        height=92,
        padding=(0, 0, 0, 0),
    )


def allocation_ring(label, percent, color):
    return rx.el.div(
        rx.el.div(
            reflex_xy.chart(
                allocation_ring_chart(label, percent, color),
                height="92px",
            ),
            rx.el.span(
                f"{percent}%",
                class_name=(
                    "pointer-events-none absolute inset-0 flex items-center "
                    "justify-center text-sm font-semibold tabular-nums text-zinc-950"
                ),
            ),
            class_name="relative aspect-square w-full",
        ),
        rx.el.span(
            label,
            class_name="truncate text-[11px] leading-none text-zinc-500",
        ),
        class_name="min-w-0 text-center",
    )


def allocation_row(label, percent, amount, color):
    return rx.el.div(
        rx.el.div(
            rx.el.span(
                class_name="size-2.5 shrink-0 rounded-[3px]",
                style={"background": color},
            ),
            rx.el.span(
                f"{percent}%",
                class_name="w-9 font-medium tabular-nums text-zinc-950",
            ),
            rx.el.span(label, class_name="text-zinc-500"),
            class_name="flex min-w-0 items-center gap-2",
        ),
        rx.el.span(
            f"${amount:,.0f}",
            class_name="font-medium tabular-nums text-zinc-950",
        ),
        class_name=(
            "flex items-center justify-between rounded-lg px-2.5 py-1.5 "
            "text-xs even:bg-[#fafafa]"
        ),
    )


def allocation_overview_demo():
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "Annual plan",
                    class_name="text-[10px] uppercase tracking-wide text-zinc-500",
                ),
                rx.el.span(
                    "Team allocation",
                    class_name="text-lg font-medium tracking-tight text-zinc-950",
                ),
                class_name="flex flex-col",
            ),
            rx.el.span(
                "$2.0M planned",
                class_name="text-xs font-medium tabular-nums text-zinc-500",
            ),
            class_name="flex items-start justify-between gap-4",
        ),
        rx.el.div(
            *(
                allocation_ring(label, percent, color)
                for label, percent, _amount, color in ALLOCATION_DATA
            ),
            class_name="mt-2 grid grid-cols-5 gap-2",
        ),
        rx.el.div(
            *(
                allocation_row(label, percent, amount, color)
                for label, percent, amount, color in ALLOCATION_DATA
            ),
            class_name="mt-2 grid gap-0.5 border-t border-zinc-100 pt-2",
        ),
        class_name=(
            "mx-auto flex h-[22.5rem] w-full max-w-[630px] flex-col "
            "bg-white p-4"
        ),
    )
~~~

The rings use a common radial domain and thickness. The percentage controls
only the foreground `width`, while the track remains a complete annulus. The
labels and exact dollar values stay in Reflex so the ring geometry can be
exported or reused independently.

## Training Summary

A hero metric can share a card with compact radial KPIs. Here the primary
distance and goal rail lead, while three rings summarize the supporting
measurements and the narrow side column preserves quick operational context:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

TRAINING_METRICS = [
    ("Elevation", 312, "m", 68, "#6e56cf"),
    ("Work", 684, "kJ", 82, "#f59e0b"),
    ("Cadence", 82, "rpm", 74, "#e11d48"),
]
TRAINING_STATS = [
    ("Intervals", "7"),
    ("Recovery", "46 min"),
    ("Avg speed", "28.4 km/h"),
]


def training_ring_chart(label, percent, color):
    span = percent / 100 * 360.0
    return xy.polar_bar_chart(
        xy.bar(
            [180.0],
            [0.13],
            base=0.70,
            width=360.0,
            color="#f0eef7",
            opacity=1,
        ),
        xy.bar(
            [span / 2.0],
            [0.13],
            base=0.70,
            width=span,
            color=color,
            opacity=1,
            corner_radius=9,
            name=f"{label} · {percent}%",
        ),
        xy.theta_axis(
            unit="degrees",
            zero="N",
            direction="clockwise",
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
        height=118,
        padding=(0, 0, 0, 0),
    )


def training_metric(label, value, unit, percent, color):
    return rx.el.div(
        rx.el.div(
            reflex_xy.chart(
                training_ring_chart(label, percent, color),
                height="118px",
            ),
            rx.el.div(
                rx.el.span(
                    str(value),
                    class_name="text-lg font-semibold leading-none tabular-nums text-zinc-950",
                ),
                rx.el.span(
                    unit,
                    class_name="text-[10px] leading-none text-zinc-500",
                ),
                class_name=(
                    "pointer-events-none absolute inset-0 flex items-center "
                    "justify-center gap-1"
                ),
            ),
            class_name="relative aspect-square w-full",
        ),
        rx.el.span(
            label,
            class_name="-mt-1 text-center text-[11px] text-zinc-500",
        ),
        class_name="min-w-0",
    )


def training_summary_demo():
    return rx.el.div(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "Training summary",
                    class_name="text-lg font-medium tracking-tight text-zinc-950",
                ),
                rx.el.span(
                    "Week 28",
                    class_name="text-xs text-zinc-500",
                ),
                class_name="flex items-center justify-between",
            ),
            rx.el.div(
                rx.el.div(
                    rx.el.span(
                        "24.7",
                        class_name=(
                            "text-4xl font-semibold leading-none tracking-tight "
                            "tabular-nums text-zinc-950"
                        ),
                    ),
                    rx.el.span(
                        "km ridden",
                        class_name="pb-0.5 text-sm text-zinc-500",
                    ),
                    class_name="flex items-end gap-2",
                ),
                rx.el.span(
                    "78% of weekly goal",
                    class_name="text-xs font-medium text-[#6e56cf]",
                ),
                class_name="mt-3 flex items-end justify-between gap-4",
            ),
            rx.el.div(
                rx.el.div(
                    class_name="h-full rounded-full bg-[#6e56cf]",
                    style={"width": "78%"},
                ),
                class_name="mt-2 h-1.5 overflow-hidden rounded-full bg-[#eeecf6]",
            ),
            rx.el.div(
                *(
                    training_metric(label, value, unit, percent, color)
                    for label, value, unit, percent, color in TRAINING_METRICS
                ),
                class_name="mt-2 grid grid-cols-3 gap-3",
            ),
            class_name="min-w-0",
        ),
        rx.el.div(
            *(
                rx.el.div(
                    rx.el.span(
                        label,
                        class_name="text-[10px] uppercase tracking-wide text-zinc-400",
                    ),
                    rx.el.span(
                        value,
                        class_name="mt-0.5 text-lg font-medium tabular-nums text-zinc-950",
                    ),
                    class_name="flex flex-col",
                )
                for label, value in TRAINING_STATS
            ),
            class_name=(
                "flex flex-col justify-center gap-5 border-l border-zinc-100 pl-4"
            ),
        ),
        class_name=(
            "mx-auto grid h-[22.5rem] w-full max-w-[630px] "
            "grid-cols-[minmax(0,1fr)_9rem] gap-4 bg-white p-4"
        ),
    )
~~~

The chart helper owns only a track and foreground arc. The headline, horizontal
goal rail, center values, and side statistics are ordinary layout, so they
remain easy to restyle without changing the chart payload.

## Cache Tiers

Nested semicircular bars can compare several capacities without repeating four
separate plots. Every tier starts at the same angle; its foreground width is the
used fraction of the shared 180-degree track:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

CACHE_TIERS = [
    ("Memory", 610, 1_000, "#6e56cf", "#9d8df1"),
    ("Regional", 240, 1_000, "#f59e0b", "#fcd34d"),
    ("Edge", 100, 1_000, "#2563eb", "#60a5fa"),
    ("Origin", 50, 1_000, "#e11d48", "#fb7185"),
]
CACHE_BASES = [0.24, 0.40, 0.56, 0.72]
CACHE_STATS = [
    ("Served warm", "8,420"),
    ("Revalidated", "1,140"),
    ("Evictions", "386"),
    ("Purges", "72"),
]

cache_tiers = xy.polar_bar_chart(
    *(
        xy.bar(
            [0.0],
            [0.09],
            base=base,
            width=180.0,
            color="#eeecf6",
            opacity=1,
            corner_radius=8,
        )
        for base in CACHE_BASES
    ),
    *(
        xy.bar(
            [-90.0 + (used / capacity * 180.0) / 2.0],
            [0.09],
            base=base,
            width=used / capacity * 180.0,
            name=label,
            fill=f"linear-gradient(to top, {start}, {end})",
            opacity=1,
            corner_radius=8,
            stroke="#ffffff",
            stroke_width=1,
        )
        for (label, used, capacity, start, end), base in zip(
            CACHE_TIERS,
            CACHE_BASES,
            strict=True,
        )
    ),
    xy.theta_axis(
        unit="degrees",
        sector=(-90.0, 90.0),
        zero="N",
        direction="clockwise",
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
    height=210,
    padding=(4, 4, 0, 4),
)


def cache_legend_item(label, used, capacity, color):
    percent = used / capacity
    return rx.el.div(
        rx.el.div(
            rx.el.span(
                class_name="size-2.5 shrink-0 rounded-[3px]",
                style={"background": color},
            ),
            rx.el.span(
                label,
                class_name="truncate text-xs font-medium text-zinc-700",
            ),
            class_name="flex items-center gap-2",
        ),
        rx.el.span(
            f"{used:,}/{capacity:,} ({percent:.0%})",
            class_name="mt-1 text-[11px] tabular-nums text-zinc-500",
        ),
        class_name="min-w-0",
    )


def cache_tiers_demo():
    return rx.el.div(
        rx.el.div(
            rx.el.span(
                "Cache tiers",
                class_name="text-lg font-medium tracking-tight text-zinc-950",
            ),
            rx.el.span(
                "Last 24 hours",
                class_name="text-xs text-zinc-500",
            ),
            class_name="flex items-center justify-between",
        ),
        rx.el.div(
            rx.el.div(
                reflex_xy.chart(cache_tiers, height="210px"),
                class_name="min-w-0",
            ),
            rx.el.div(
                *(
                    rx.el.div(
                        rx.el.span(
                            label,
                            class_name="text-xs text-zinc-500",
                        ),
                        rx.el.span(
                            value,
                            class_name=(
                                "mt-0.5 text-xl font-medium tabular-nums "
                                "tracking-tight text-zinc-950"
                            ),
                        ),
                        class_name="flex flex-col",
                    )
                    for label, value in CACHE_STATS
                ),
                class_name="grid grid-cols-2 content-center gap-x-5 gap-y-5",
            ),
            class_name="mt-1 grid min-h-0 flex-1 grid-cols-[1.15fr_0.85fr] gap-4",
        ),
        rx.el.div(
            *(
                cache_legend_item(label, used, capacity, start)
                for label, used, capacity, start, _end in CACHE_TIERS
            ),
            class_name=(
                "grid grid-cols-4 gap-3 border-t border-zinc-100 pt-3"
            ),
        ),
        class_name=(
            "mx-auto flex h-[22.5rem] w-full max-w-[630px] flex-col "
            "bg-white p-4"
        ),
    )
~~~

Separate one-bar marks make it straightforward to give every tier a name,
gradient, and rounded edge. The `sector=(-90.0, 90.0)` axis fits the visible
semicircle to the available plot box instead of reserving space for the missing
half.

## Build Your Own Radial Block

1. Decide whether values control radial height, angular progress, or both.
2. Author a muted track when every category shares a known maximum.
3. Keep the track and foreground on the same `base` and radial height.
4. Convert a percentage to `percentage / 100 × 360` for a full ring, or multiply
   by the declared partial-sector span.
5. Hide axes and the native legend when Reflex supplies the surrounding labels.
6. Keep raw data and derived spans outside the chart construction.

XY does not add a background track or infer a maximum automatically. Explicit
track marks make the maximum, thickness, color, and export behavior unambiguous.

## Inner Radius and Sector Geometry

`base` is the inner radial edge, and the bar value is the height above it. A
scalar base opens the same hole beneath every bar; a sequence can give each bar
its own starting radius:

~~~python
rings = xy.polar_bar_chart(
    xy.bar(
        [0, 90, 180, 270],
        [0.30, 0.42, 0.24, 0.36],
        base=0.40,
        width=72,
    ),
    xy.theta_axis(unit="degrees"),
    xy.r_axis(domain=(0.0, 1.0)),
)
~~~

Filled sectors that cross the visible radial range are clipped at the inner or
outer ring. A sector wholly outside the range disappears instead of reflecting
through the center.

`base=` belongs to the mark and may differ per bar. For one chart-wide opening,
use `r_axis(hole=...)` to reserve a display-space inner fraction or
`r_axis(origin=...)` to set a data-space radial origin. `hole` and `origin` are
mutually exclusive.

A single sector with `width=360` on a degree axis (or a full `2π` width on a
radian axis) and a positive `base` draws a complete annulus. That is the track
used by the progress-ring blocks above.

## Partial Gauges

Use `sector=(start, end)` for a gauge chart whose visible arc should expand to
fill the plot box. Rounded sectors, background-colored strokes, gradients, and
explicit padding work the same way on a partial layout:

~~~python
partial_gauge = xy.polar_bar_chart(
    xy.bar(
        [0.0],
        [0.18],
        base=0.70,
        width=240.0,
        color="#e5e7eb",
        corner_radius=10,
    ),
    xy.bar(
        [-30.0],
        [0.18],
        base=0.70,
        width=180.0,
        fill="linear-gradient(to top, #7c3aed, #34d399)",
        corner_radius=10,
        stroke="#ffffff",
        stroke_width=1.5,
    ),
    xy.theta_axis(
        unit="degrees",
        sector=(-120.0, 120.0),
        zero="N",
        direction="clockwise",
        show=False,
    ),
    xy.r_axis(domain=(0.0, 1.0), show=False),
    padding=(18, 18, 36, 18),
)
~~~

Use a scalar `corner_radius` for symmetric rounding. A gradient applies to the
whole mark and takes priority over a solid color. Use `stroke_width` to control
the separator or outline in screen pixels. Explicit
`padding=(top, right, bottom, left)` is preserved by the polar layout, so a
stable caption or legend band can be reserved without shifting the arc.

## Angular Convention

Use `xy.theta_axis(unit="degrees")` when positions and widths are expressed in
degrees. Add `zero="N", direction="clockwise"` for compass bearings. With the
default radian axis, both the center angles and widths must be radians.

On `theta_axis()`, `domain=` is a compatibility alias for `sector=`; pass only
one. XY clips marks and ticks to that interval and fits the visible arc to its
own bounding box.

## Interaction and Export

All live blocks on this page set `xy.modebar(show=False)` to keep the
presentation quiet. Sector hover and browser/static exports remain available
through the shared polar renderer.

Zoom is off by default, as on every polar chart except the wind rose: these
compositions are laid out against a fixed center and a fixed outer ring, so
zooming crops the sectors rather than revealing detail. With no gesture able to
move the view, reset has nothing to restore either: unless `reset_axes` is
authored, double-click is inert and the reset controls drop out of the modebar. An
authored `reset_axes` grants both back on its own, whatever the zoom switch says.
Add `xy.interaction_config(zoom=True)` to turn radial zoom (and reset) on when the
sector lengths are worth magnifying — see
[why zoom is off by default](/docs/xy/charts/polar-chart/#why-zoom-is-off-by-default).

Reflex-composed center values, rails, statistics, and custom legends are browser
UI. The radial sectors themselves remain part of the XY chart and are preserved
in SVG and native raster exports.

See the [polar overview](/docs/xy/charts/polar-chart/) for shared axes,
interaction, pyplot, large-data, and annotation limits.

## Related Polar Charts

- [Radar charts](/docs/xy/charts/radar-chart/) — compare values across named
  dimensions.
- [Pie and donut charts](/docs/xy/charts/pie-chart/) — polished share,
  progress-ring, and gauge blocks.
- [Wind rose charts](/docs/xy/charts/wind-rose/) — bin raw direction/speed
  observations into stacked radial bars.
- [Bar charts](/docs/xy/charts/bar-chart/) — rectangular bars on Cartesian
  axes.

## FAQ

### How do I add gaps between radial bars?

Place bar centers at the full bin spacing and choose a slightly smaller
`width`. For centers 30° apart, `width=26` leaves a 4° gap.

### How do I create a donut hole?

Set a positive `base` and choose a bar height that reaches the desired outer
radius. Hide both axes for a conventional ring presentation.

### Can each sector have a different angular width?

Yes. Pass a width sequence with one finite, positive value per bar.
