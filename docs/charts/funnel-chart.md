---
title: Funnel Chart in Python
description: Create interactive funnel charts in Python with xy. Show stage-based conversion and drop-off with ordered stages, honest geometry modes, and per-stage labels.
components:
  - xy.funnel_chart
---

# Funnel Charts in Python

A **funnel chart** shows how a quantity survives an ordered process — visitors
becoming signups becoming customers, candidates advancing through interviews,
tickets moving toward resolution. Each stage is one centered segment, and the
narrowing silhouette makes conversion and drop-off legible at a glance.

With `xy`, pass stage names and values to `funnel_chart`. Stage order is
**always the declared order** — a funnel is a categorical business process,
and XY never sorts it. Conversion and drop-off arithmetic ship with every
stage: labels, tooltips, and click events all carry the stage name, value,
prior value, overall share, previous-stage conversion, and drop-off.

Jump to [the basic chart](#create-a-funnel-chart),
[geometry modes](#choose-honest-geometry),
[horizontal funnels](#run-the-funnel-horizontally),
[necks, gaps, and floors](#shape-the-silhouette),
[styling](#style-a-funnel), or
[the legend](#add-a-legend).

## Create a Funnel Chart

~~~python demo exec
import reflex_xy
import xy

signup_funnel = xy.funnel_chart(
    ["Visit", "Signup", "Activate", "Trial", "Pay"],
    [9_800, 6_200, 3_100, 2_200, 1_450],
    show_dropoff=True,
    title="Signup funnel",
)


def funnel_chart_demo():
    return reflex_xy.chart(signup_funnel, height="440px")
~~~

Each segment shows its value and overall conversion (`show_conversion`
appends the share of the first stage), and `show_dropoff=True` writes the
signed stage-over-stage change at each boundary. Hovering a segment reads the
full arithmetic: value, overall share, previous-stage conversion, and
drop-off. A label that cannot fit inside its segment moves beside it, and a
stage pitch too short for a text line hides the labels rather than
overlapping them — the tooltip always carries every number.

## Choose Honest Geometry

`geometry` is explicit because the two classic funnel drawings encode
differently:

- `"area"` (default) draws the tapering silhouette — each segment's far edge
  previews the **next** stage's width, so drop-off is visible as slope. The
  painted area of a segment is therefore *not* proportional to its value.
- `"bar"` draws centered constant-width segments whose widths carry the
  values exactly — the faithful-width encoding.

~~~python demo exec
import reflex_xy
import xy

activation_bars = xy.funnel_chart(
    ["Install", "Open", "Signup", "Invite", "Re-engage", "Subscribe"],
    [92_000, 64_000, 30_500, 12_200, 13_300, 5_100],
    geometry="bar",
    gap=0.3,
    show_dropoff=True,
    title="Activation — note the re-engagement bulge",
)


def funnel_geometry_demo():
    return reflex_xy.chart(activation_bars, height="460px")
~~~

Increasing stages are legal and drawn honestly: `Re-engage` is wider than
`Invite`, its conversion is above one, and its boundary label reads `+9%`.
Negative and missing values are refused by stage name. A zero stage draws
nothing and keeps its label and its keyboard stop, but with no drawn area
there is nothing for the pointer to land on — give it `min_width` to make it
hoverable as a floor sliver.

## Run the Funnel Horizontally

~~~python demo exec
import reflex_xy
import xy

ticket_flow = xy.funnel_chart(
    ["Opened", "Triaged", "Escalated", "Eng fix", "Refunded"],
    [48_210, 31_600, 8_200, 0, 1_240],
    orientation="horizontal",
    geometry="bar",
    min_width=0.03,
    value_format="{:,.0f}",
    title="Support ticket flow (30 days)",
)


def funnel_horizontal_demo():
    return reflex_xy.chart(ticket_flow, height="380px")
~~~

`orientation="horizontal"` runs stage 0 from the left; vertical funnels put
stage 0 on top (the stage axis is reversed exactly like a Sankey's). The
cross axis is layout, not data — segments center on zero — so `funnel_chart`
hides it. Here `min_width=0.03` keeps the zero-valued `Eng fix` stage visible
and hoverable as a floor sliver: drawn geometry is clamped, but every label,
tooltip, and event value stays exact.

## Shape the Silhouette

- `gap` separates segments along the stage axis as a fraction of the stage
  pitch. It resolves per geometry when unset: `0` for `"area"` (a continuous
  silhouette), `0.2` for `"bar"` (bar-chart spacing).
- `neck` decides the last area segment's far edge: `"rect"` (default) holds
  the stage's own width; `"taper"` runs it to a point — the classic spout.
- `min_width` floors drawn cross widths at a fraction of the widest stage so
  tiny stages stay visible. The taper spout deliberately ignores the floor.

~~~python demo exec
import reflex_xy
import xy

checkout = xy.funnel_chart(
    ["Cart", "Address", "Payment", "Review", "Placed"],
    [30_400, 21_100, 15_800, 14_100, 13_900],
    xy.theme(
        background="#0b1020",
        plot_background="#0b1020",
        text_color="#e2e8f0",
        grid_color="#1f2a44",
        axis_color="#334155",
    ),
    colors=["#38bdf8", "#22d3ee", "#2dd4bf", "#34d399", "#4ade80"],
    neck="taper",
    show_dropoff=True,
    title="Checkout completion",
)


def funnel_neck_demo():
    return reflex_xy.chart(checkout, height="440px")
~~~

## Style a Funnel

Per-stage paint is a channel, not a style: pass `colors=` for one CSS color
per stage, `color=` for a single constant, or let the theme palette assign
colors in declared stage order. A `xy.theme(palette={...})` mapping pins
colors by stage *name*, so a stage keeps its color across charts. Inside
labels pick a light or dark text color from each segment's own fill.

Trace-level style stays per-trace, the ribbon contract: `opacity`,
`fill-opacity`, `stroke`, `stroke-width`, and `stroke-opacity` (an omitted
stroke color outlines each segment with its own fill). `fill` is deliberately
rejected — per-stage paint rides the channel so every renderer draws it.

~~~python demo exec
import reflex_xy
import xy

recruiting = xy.funnel_chart(
    ["Sourced", "Phone screen", "Onsite", "Offer", "Hired"],
    [1_840, 920, 388, 152, 121],
    xy.theme(
        palette={
            "Sourced": "#6366f1",
            "Phone screen": "#8b5cf6",
            "Onsite": "#a855f7",
            "Offer": "#d946ef",
            "Hired": "#ec4899",
        },
    ),
    stroke="#ffffff",
    stroke_width=2.0,
    gap=0.03,
    show_dropoff=True,
    percent_format="{:.1%}",
    title="Recruiting pipeline — Q3",
)


def funnel_styling_demo():
    return reflex_xy.chart(recruiting, height="460px")
~~~

Chart chrome — title, axis ticks, tooltip, legend, and the funnel's own
value/drop-off labels (`annotation_label`) — styles through the standard
[chrome slots](/docs/xy/styling/chrome-slots/) with CSS classes, Tailwind
utilities, or `styles={...}`:

~~~python
xy.funnel_chart(
    stages,
    values,
    class_names={
        "title": "text-xl font-semibold tracking-tight",
        "annotation_label": "tabular-nums",
        "tooltip": "rounded-xl shadow-lg",
    },
)
~~~

`value_format` and `percent_format` are `str.format` templates, and the
kernel applies them once for every surface — segment labels, hover tooltips,
and static exports all print the same string, because the client is handed
the formatted text rather than re-implementing the format spec.

## Add a Legend

The legend is **off by default** — the stage axis already names every stage,
so a second list of the same names is usually noise. Pass an explicit
`xy.legend(...)` child to bring back one row per stage, drawn from the
categorical stage encoding:

~~~python demo exec
import reflex_xy
import xy

legend_funnel = xy.funnel_chart(
    ["Sourced", "Screen", "Onsite", "Offer", "Hired"],
    [1_840, 920, 388, 152, 121],
    xy.legend(loc="center right", title="Stage"),
    show_dropoff=True,
    percent_format="{:.1%}",
    title="Recruiting — click a legend row to hide a stage",
)


def funnel_legend_demo():
    return reflex_xy.chart(legend_funnel, height="460px")
~~~

Those rows are live. Clicking one hides that stage's segment **and its
labels**, leaving every other stage's geometry and arithmetic untouched — a
funnel's stage values are the data, not a running total to recompute — and
clicking again restores it. Hovering a row emphasizes its stage and dims the
rest. `xy.legend(show=False)` is the default; `loc`, `title`, and `ncols`
place and shape it like any other chart's legend, and the `legend`,
`legend_item`, `legend_swatch`, and `legend_label`
[chrome slots](/docs/xy/styling/chrome-slots/) style it.

Because stage colours come from a categorical channel keyed on the stage
names, a `xy.theme(palette={...})` mapping keeps each legend swatch and its
segment in the same colour across every chart that names that stage.

## Interact With a Funnel

Hover reads the full arithmetic for a stage, and because a segment covers an
area rather than a point, the tooltip follows the cursor within it. Clicking
emits `xy:click` carrying the stage name, value, prior value, overall share,
conversion, and drop-off — the same semantic row the tooltip shows. A ratio
with no meaningful value — a zero denominator, or one that would overflow to
infinity on an extreme dynamic range — arrives as `null` in events and prints
as an em dash (—) in the tooltip, so it reads as "no meaningful number"
rather than as missing data. Box
and lasso selection are deliberately absent rather than approximate.

With `animation=` configured, a funnel enters by growing out of its spine
(the way bars grow from their baseline), and data updates morph each
segment's geometry to its new shape. Stable `key=` identities plus
`xy.animation(match="key")` keep a stage's segment continuous across updates
even when stages are added or removed; without keys, stages match by
position. Keyboard navigation walks the *visible* stages in declared order —
arrow keys move stage to stage, `Home`/`End` jump to the ends, `Enter`
activates, `Escape` dismisses — and the screen-reader announcement reads
"Stage 2 of 5" followed by that stage's conversion arithmetic, so the funnel
is heard as the ordered process it is.
