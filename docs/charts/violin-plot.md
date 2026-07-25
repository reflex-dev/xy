---
title: Violin Plot in Python
description: Violin plot Python charts with xy — compare full distribution shapes across groups with mirrored density curves in a fast, interactive plot that pans and zooms.
components:
  - xy.violin_chart
---

# Violin Plots in Python

A **violin plot** (also called a violin chart or violin graph) shows the full
estimated density of a distribution as a mirrored curve, revealing multi-modal
shapes that a box plot hides. With `xy`
you build a violin plot in Python that compares several groups side by side and
stays interactive — pan, zoom, and hover across every curve.

Jump to [creating a violin plot](#create-a-violin-plot),
[density resolution](#density-resolution-and-orientation), or
[options](#violin-plot-options).

## Create a Violin Plot

Pass a list of arrays — one per group — to `violin`, and label each group with
`x`. This is the minimal Python violin plot:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

violin_rng = np.random.default_rng(31)
violin_groups = [
    violin_rng.normal(50, 7, 1_200),
    np.concatenate(
        [
            violin_rng.normal(43, 4, 600),
            violin_rng.normal(59, 5, 600),
        ]
    ),
]

violin_detail_chart = xy.violin_chart(
    xy.violin(
        violin_groups,
        x=["Single peak", "Two peaks"],
        color="#6e56cf",
        opacity=0.65,
        bins=72,
    ),
    xy.x_axis(label="distribution"),
    xy.y_axis(label="score"),
    title="Distribution shape",
)


def violin_demo():
    return reflex_xy.chart(violin_detail_chart, height="320px")
~~~

## Density Resolution and Orientation

The `bins` option sets the resolution of the estimated density: more bins trace
a finer curve, fewer bins smooth it out. Switch `orientation` to
`"horizontal"` when group labels are long, and use `width` to control how wide
each violin sits within its slot. The example above overlays a single-peak
group against a two-peak group so the multi-modal shape is obvious.

### Horizontal Violins at High Resolution

Raise `bins` for a finer density trace, turn the plot sideways with
`orientation="horizontal"`, and tune the fill with `width` and `opacity`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

wind_rng = np.random.default_rng(13)
season_wind = [
    wind_rng.weibull(2.1, 1_500) * 14,
    wind_rng.weibull(1.7, 1_500) * 19,
    wind_rng.weibull(2.4, 1_500) * 11,
]

horizontal_violin_chart = xy.violin_chart(
    xy.violin(
        season_wind,
        x=["Spring", "Autumn", "Summer"],
        orientation="horizontal",
        bins=120,
        width=0.9,
        color="#0ea5e9",
        opacity=0.7,
    ),
    xy.x_axis(label="wind speed (km/h)"),
    xy.y_axis(label="season"),
    title="Seasonal wind speed, fine-grained density",
)


def horizontal_violin_demo():
    return reflex_xy.chart(horizontal_violin_chart, height="320px")
~~~

### Violin and Box Overlay

Compose `violin` and a narrow `box` on the same groups inside a neutral
`xy.chart(...)` so each distribution shows its full density and its quartiles.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

raincloud_rng = np.random.default_rng(101)
model_errors = [
    raincloud_rng.normal(0.0, 1.0, 1_000),
    np.concatenate(
        [raincloud_rng.normal(-1.4, 0.5, 500), raincloud_rng.normal(1.6, 0.7, 500)]
    ),
    raincloud_rng.normal(0.4, 1.8, 1_000),
]
model_names = ["Linear", "Ensemble", "Neural"]

raincloud_chart = xy.chart(
    xy.violin(
        model_errors,
        x=model_names,
        color="#6e56cf",
        opacity=0.45,
        bins=96,
        width=0.85,
    ),
    xy.box(
        model_errors,
        x=model_names,
        color="#1a1a2e",
        width=0.18,
        show_outliers=False,
    ),
    xy.x_axis(label="model"),
    xy.y_axis(label="prediction error"),
    title="Error distribution: density plus quartiles",
)


def raincloud_violin_demo():
    return reflex_xy.chart(raincloud_chart, height="320px")
~~~

## Violin Plot Options

| Option | Purpose |
| --- | --- |
| `bins` | Density resolution — more bins trace a finer curve. |
| `orientation` | `"vertical"` (default) or `"horizontal"`. |
| `width` | Width of each violin within its slot. |
| `color` | Fill color (any CSS color). |
| `opacity` | Fill opacity from 0 to 1. |

Pass column names with `data=` instead of arrays when your data is a table.

## Related Charts

- [Box plots](/docs/xy/charts/box-plot/) — summarize a distribution with
  quartiles instead of a full curve.
- [Histograms](/docs/xy/charts/histogram/) — bin one distribution into bars.

## FAQ

### How do I make a violin plot in Python?

Pass a list of arrays to `xy.violin(...)`, one per group, inside
`xy.violin_chart(...)` and render it. The density curves and axes are computed
automatically.

### What does the width of a violin plot mean?

The width at any level reflects the estimated density of values there — wider
regions have more data. Use the `width` option to scale the whole violin within
its slot.

### How do I control the smoothness of a violin plot?

Set `bins` on `violin`. More bins trace a finer, more detailed density curve;
fewer bins produce a smoother, simpler shape.

### When should I use a violin plot instead of a box plot?

Use a violin plot when the shape matters — especially to reveal multi-modal
distributions. A [box plot](/docs/xy/charts/box-plot/) only shows quartiles, so
it hides multiple peaks.
