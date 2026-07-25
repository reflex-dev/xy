---
title: Box Plot in Python
description: Box plot Python charts with xy — compare distributions across groups with quartiles, whiskers, and outliers in a fast, interactive boxplot that pans and zooms.
components:
  - xy.box_chart
---

# Box Plots in Python

A **box plot** (also called a box-and-whisker plot) summarizes a distribution with its median, quartiles, and
whiskers, and marks points beyond the whiskers as outliers. With `xy` you build
a boxplot in Python that compares several groups side by side and stays
interactive — pan, zoom, and hover to inspect every summary value.

Jump to [creating a box plot](#create-a-box-plot),
[outliers and orientation](#outliers-and-orientation), or
[options](#box-plot-options).

## Create a Box Plot

Pass a list of arrays — one per group — to `box`, and label each group with
`x`. This is the minimal Python box plot:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

box_rng = np.random.default_rng(23)
box_groups = [
    box_rng.normal(48, 7, 800),
    box_rng.normal(57, 9, 800),
]

box_detail_chart = xy.box_chart(
    xy.box(
        box_groups,
        x=["Control", "Treatment"],
        color="#6e56cf",
        width=0.5,
        show_outliers=True,
    ),
    xy.x_axis(label="cohort"),
    xy.y_axis(label="score"),
    title="Cohort score distribution",
)


def box_demo():
    return reflex_xy.chart(box_detail_chart, height="320px")
~~~

## Outliers and Orientation

Set `show_outliers=True` to draw individual points beyond the whiskers and tune
their marker with `outlier_size`. Switch `orientation` to `"horizontal"` when
group labels are long or when you want to read distributions left to right, and
use `width` to control how wide each box sits within its slot.

### Horizontal Boxes with Outlier Markers

Flip the chart with `orientation="horizontal"`, slim each box with `width`, and
enlarge the flagged points with `show_outliers` plus `outlier_size`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

latency_rng = np.random.default_rng(5)
service_latency = [
    np.concatenate(
        [latency_rng.gamma(4.0, 9.0, 700), latency_rng.uniform(160, 240, 12)]
    ),
    np.concatenate(
        [latency_rng.gamma(5.5, 8.0, 700), latency_rng.uniform(170, 260, 9)]
    ),
    np.concatenate(
        [latency_rng.gamma(3.2, 12.0, 700), latency_rng.uniform(190, 300, 15)]
    ),
]

horizontal_box_chart = xy.box_chart(
    xy.box(
        service_latency,
        x=["checkout", "search", "payments"],
        orientation="horizontal",
        width=0.45,
        color="#0ea5e9",
        show_outliers=True,
        outlier_size=6.0,
    ),
    xy.x_axis(label="latency (ms)"),
    xy.y_axis(label="service"),
    title="Service latency, outliers highlighted",
)


def horizontal_box_demo():
    return reflex_xy.chart(horizontal_box_chart, height="320px")
~~~

## Comparing Groups

Box plots shine when comparing many groups at a glance. Add one entry per group
to the list of arrays and give each a label through `x`; the medians and
quartiles line up on a shared axis so shifts in center and spread are easy to
compare.

### Grouping from Long-Form Records

When observations arrive as one long array, pass a matching label array to
`group=` and `box` splits the values into per-group boxes automatically.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

plant_rng = np.random.default_rng(77)
site_names = ["North", "East", "South", "West", "Central"]
yield_values = np.concatenate(
    [plant_rng.normal(52 + 4 * i, 5 + 0.8 * i, 300) for i in range(len(site_names))]
)
site_labels = np.repeat(site_names, 300)

grouped_box_chart = xy.box_chart(
    xy.box(
        yield_values,
        group=site_labels,
        color="#6e56cf",
        width=0.55,
        show_outliers=True,
        outlier_size=4.5,
    ),
    xy.x_axis(label="site"),
    xy.y_axis(label="yield (bushels)"),
    title="Yield by site from long-form records",
)


def grouped_box_demo():
    return reflex_xy.chart(grouped_box_chart, height="320px")
~~~

## Box Plot Options

| Option | Purpose |
| --- | --- |
| `show_outliers` | Draw individual points beyond the whiskers. |
| `outlier_size` | Marker size for outlier points. |
| `orientation` | `"vertical"` (default) or `"horizontal"`. |
| `width` | Width of each box within its slot. |
| `color` | Box color (any CSS color). |
| `opacity` | Box opacity from 0 to 1. |

Pass column names with `data=` instead of arrays when your data is a table.

## Related Charts

- [Violin plots](/docs/xy/charts/violin-plot/) — show the full density shape,
  not just quartiles.
- [Histograms](/docs/xy/charts/histogram/) — bin one distribution into bars.
- [ECDF plots](/docs/xy/charts/ecdf/) — the cumulative distribution without
  binning.

## FAQ

### How do I make a box plot in Python?

Pass a list of arrays to `xy.box(...)`, one per group, inside
`xy.box_chart(...)` and render it. Quartiles, whiskers, and axes are computed
for the whole box chart automatically.

### How do I show outliers on a box plot?

Set `show_outliers=True` on `box`. Points beyond the whiskers are drawn
individually, and `outlier_size` controls their marker size.

### How do I make a horizontal box plot?

Set `orientation="horizontal"` on `box` to turn the box graph on its side:
groups run down the y-axis and values spread along the x-axis.

### What is the difference between a box plot and a violin plot?

A box plot shows summary statistics — median, quartiles, and whiskers — while a
[violin plot](/docs/xy/charts/violin-plot/) shows the full estimated density, so
it reveals multi-modal shapes a box plot hides.
