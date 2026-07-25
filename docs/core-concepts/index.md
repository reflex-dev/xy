---
title: Composition Model
description: Understand how XY containers, children, shared props, and chart methods fit together.
---

# Composition Model

An XY chart starts with one container and a set of small Python specifications.
The container creates the plotting surface. Marks turn data into visible
geometry, while axes, annotations, legends, tooltips, themes, and interaction
policies describe how that surface should behave.

Shared values such as `data`, `title`, dimensions, and callbacks are container
props. Methods such as `show()`, `to_html()`, and `write_image()` operate on the
composed chart after it has been built.

## Compose one chart

This interactive example combines bars, a line, an annotation, axes, a legend,
a shared tooltip, and crosshair behavior in one panel:

~~~python demo exec
import xy

pipeline_data = {
    "month": [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ],
    "actual_k": [118, 132, 145, 151, 168, 174, 192, 205, 214, 238, 246, 268],
    "target_k": [125, 135, 145, 155, 165, 175, 190, 205, 220, 235, 250, 265],
}

composition_chart = xy.chart(
    xy.bar(
        x="month",
        y="actual_k",
        name="Actual",
        color="#c4b5fd",
        opacity=0.82,
        corner_radius=4,
    ),
    xy.line(
        x="month",
        y="target_k",
        name="Target",
        color="#6e56cf",
        width=2.5,
    ),
    xy.vline("Oct", text="Product launch", color="#0ea5e9", width=2),
    xy.x_axis(label="month"),
    xy.y_axis(
        label="qualified pipeline",
        domain=(0, 300),
        format="$,.0fK",
        tick_count=6,
    ),
    xy.legend(loc="upper center", ncols=2),
    xy.tooltip(
        title="{month}",
        fields=["actual_k", "target_k"],
        format={"actual_k": "$,.0fK", "target_k": "$,.0fK"},
    ),
    xy.interaction_config(hover=True, crosshair=True),
    data=pipeline_data,
    title="Qualified pipeline vs target",
    padding=(10, 14, 42, 84),
)


# This documentation site uses Reflex to render the chart above.
def composition_model_demo():
    import reflex_xy

    return reflex_xy.chart(composition_chart, height="380px")
~~~

The `xy` chart is independent of Reflex; `reflex_xy.chart(...)` is only the
adapter used to mount this documentation preview.

## Anatomy of the chart

| API role | In the example | Responsibility |
| --- | --- | --- |
| Container | `xy.chart(...)` | Creates one panel and allows mixed mark families |
| Container props | `data=`, `title=` | Supply shared data and layout metadata |
| Marks | `bar()`, `line()` | Turn columns into geometry, in declaration order |
| Axes | `x_axis()`, `y_axis()` | Define scales, domains, ticks, labels, and formatting |
| Annotation | `vline()` | Places a data-aligned event marker |
| Presentation | `legend()`, `tooltip()` | Adds a series key and hover readout |
| Behavior | `interaction_config()` | Configures hover, selection, and navigation policy |
| Chart methods | `show()`, `to_html()`, `write_image()` | Display or export the finished composition |

## Three composition rules

1. **Shared data flows down.** A chart-level `data=` supplies every mark that
   uses named columns. A mark-level `data=` overrides it for that mark.
2. **Declaration order controls layering.** Marks render in order, so the
   target line above is painted after the bars.
3. **Settings resolve by family.** Singleton configuration nodes—such as
   legends, tooltips, colorbars, modebars, export settings, and animation
   settings—use the last node of their family. Themes and
   `interaction_config()` nodes merge in declaration order; later explicit
   values win only where they overlap.

## Choose a container

The container communicates intent; it does not select a different rendering
engine.

| What you are building | Container |
| --- | --- |
| One primary mark family | `line_chart()`, `scatter_chart()`, `bar_chart()`, and peers |
| Different mark kinds in one panel | Neutral `chart()` |
| One template repeated by group | `facet_chart()` |

Here every rendered observation is a point, so `scatter_chart()` is the clearest
container:

~~~python demo exec
import random

import xy

campaign_rng = random.Random(11)
campaign_spend_k = [round(campaign_rng.uniform(8, 80), 1) for _ in range(60)]
campaign_leads = [
    max(12, round(4.2 * spend + campaign_rng.uniform(-40, 40)))
    for spend in campaign_spend_k
]
campaign_data = {
    "spend_k": campaign_spend_k,
    "qualified_leads": campaign_leads,
}

family_container_chart = xy.scatter_chart(
    xy.scatter(
        x="spend_k",
        y="qualified_leads",
        color="#6e56cf",
        size=8,
        opacity=0.72,
        stroke="#ffffff",
        stroke_width=1,
    ),
    xy.x_axis(label="campaign spend ($k)", domain=(0, 85), tick_count=6),
    xy.y_axis(label="qualified leads", domain=(0, 380), tick_count=6),
    xy.tooltip(
        fields=["spend_k", "qualified_leads"],
        format={"spend_k": "$,.1fK", "qualified_leads": ",.0f"},
    ),
    data=campaign_data,
    title="Campaign spend and qualified leads",
)


def family_container_demo():
    import reflex_xy

    return reflex_xy.chart(family_container_chart, height="360px")
~~~

Family containers such as `scatter_chart()` return the same `Chart` interface
as neutral `chart()`. `facet_chart()` repeats a composition over groups and
returns a `FacetChart` with grid-aware output methods.

## Keep application state outside the chart

`interaction_config()` describes browser behavior; the host connects chart
events to Python application state. Core callbacks are for a live notebook
widget, while Reflex events are configured on `reflex_xy.chart(...)`.
A chart rendered without a Python event bridge still pans, zooms, and resolves
tooltips locally.

See [Interactions and Selections](/docs/xy/core-concepts/interactions/) for the
interaction model and [Reflex integration](/docs/xy/integrations/reflex/) for
server callback examples.

## Declarative structure, live data

Adding or removing marks means composing a new chart. Live APIs can append
points to line and scatter traces, inspect rendered points, or select a range
from scatter data; Reflex server-driven updates require a registered live
chart. See [Large Data and Performance](/docs/xy/core-concepts/large-data-and-performance/)
for representation choices and
[Reflex integration](/docs/xy/integrations/reflex/) for live updates.

For output, use `show()` or `widget()` in notebooks, `to_html()` for a
standalone document, `to_image()` for bytes, and `write_image()` for a file.

## Learn the core concepts

| Goal | Continue with |
| --- | --- |
| Bind arrays, tables, dates, and categories | [Data and Columns](/docs/xy/core-concepts/data/) |
| Control domains, scales, ticks, and named axes | [Axes and Scales](/docs/xy/core-concepts/axes-and-scales/) |
| Add navigation, callbacks, and exact selection | [Interactions and Selections](/docs/xy/core-concepts/interactions/) |
| Scale from direct points to large-data representations | [Large Data and Performance](/docs/xy/core-concepts/large-data-and-performance/) |
| Set chart-local behavior and export defaults | [Configuration](/docs/xy/core-concepts/configuration/) |

For finished examples, browse the [Gallery](/docs/xy/overview/gallery/). For
browser entrance and data-update motion, continue with
[Animations and data transitions](/docs/xy/styling/animations/).
