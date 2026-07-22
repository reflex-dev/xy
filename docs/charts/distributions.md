---
title: Distribution Charts
description: Explore distributions with histograms, box plots, violins, and ECDFs.
components:
  - xy.histogram_chart
  - xy.ecdf_chart
  - xy.box_chart
  - xy.violin_chart
---

# Distribution Charts

## When to Use

XY includes four complementary distribution marks:

- `histogram` or its `hist` alias bins values into bars.
- `box` summarizes quartiles, whiskers, and optional outliers.
- `violin` estimates a bounded density profile.
- `ecdf` shows the cumulative fraction at or below each value.

## Live Demo

The preview pairs a count histogram with an ECDF of the same latency samples.
The ECDF answers percentile questions directly: its y-value is the fraction of
requests at or below a given latency.

~~~python demo exec
import numpy as np
import reflex as rx
import reflex_xy
import xy

rng = np.random.default_rng(3)
latency = rng.gamma(shape=2.0, scale=40.0, size=100_000)

histogram = xy.histogram_chart(
    xy.histogram(latency, bins=120, color="#6e56cf"),
    xy.x_axis(label="latency (ms)"),
    xy.y_axis(label="requests"),
    title="Request latency",
)

cdf = xy.ecdf_chart(
    xy.ecdf(latency, bins=256, color="#2563eb"),
    xy.x_axis(label="latency (ms)"),
    xy.y_axis(label="fraction", domain=(0, 1)),
    title="Cumulative request latency",
)


def latency_distribution():
    return rx.vstack(
        reflex_xy.chart(histogram, height="320px"),
        reflex_xy.chart(cdf, height="320px"),
        width="100%",
        spacing="4",
    )
~~~

## Chart Types

### Histogram

Use `histogram` to group numeric observations into intervals and compare their
frequency or density.

### ECDF

Use `ecdf` to read the fraction of observations at or below any value without
choosing fixed bins. Set `bins` only when a bounded approximation is preferable
for very large inputs.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(11)
response_time = rng.lognormal(mean=4.2, sigma=0.38, size=2_000)

ecdf_detail_chart = xy.ecdf_chart(
    xy.ecdf(
        response_time,
        name="Requests",
        color="#6e56cf",
        width=2.5,
    ),
    xy.x_axis(label="response time (ms)"),
    xy.y_axis(label="cumulative fraction", domain=(0, 1)),
    title="Response-time ECDF",
)


def ecdf_demo():
    return reflex_xy.chart(ecdf_detail_chart, height="320px")
~~~

### Box

Use `box` for a compact comparison of medians, quartiles, whiskers, and optional
outliers across one or more groups.

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

### Violin

Use `violin` when the shape and density of each distribution matter in addition
to its center and spread.

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

## Variants

Histograms show frequency or density by interval. An ECDF is exact when `bins`
is omitted; set `bins` for a bounded approximation on large inputs. Box plots
emphasize quartiles and outliers, while violins show the estimated shape of
each group.

### Compare Groups

~~~python
groups = [rng.normal(48, 7, 2_000), rng.normal(57, 9, 2_000)]
labels = ["Control", "Treatment"]

chart = xy.chart(
    xy.violin(groups, x=labels, color="#c4b5fd", opacity=0.5),
    xy.box(groups, x=labels, color="#6e56cf", width=0.35),
    xy.x_axis(label="cohort"),
    xy.y_axis(label="score"),
)
~~~

## Expected Data Shape

`histogram` and `ecdf` take a one-dimensional value array. `box` and `violin`
accept one array per group plus optional category labels; in a two-dimensional
array, each column is a group. Column names may be resolved through `data=`.

## Key Options

Histograms use `bins`, `range`, `density`, and `cumulative`. ECDFs use `bins`
for bounded approximation. Box plots add `show_outliers` and `outlier_size`;
violins add density-resolution `bins`. Both expose `orientation`, `width`,
`color`, and `opacity`.
