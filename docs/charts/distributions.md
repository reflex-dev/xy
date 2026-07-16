---
title: Distribution Charts
description: Explore distributions with histograms, box plots, violins, and ECDFs.
---

# Distribution Charts

XY includes four complementary distribution marks:

- `histogram` or its `hist` alias bins values into bars.
- `box` summarizes quartiles, whiskers, and optional outliers.
- `violin` estimates a bounded density profile.
- `ecdf` shows the cumulative fraction at or below each value.

## Histograms and ECDFs

~~~python
import numpy as np
import xy as fc

rng = np.random.default_rng(3)
latency = rng.gamma(shape=2.0, scale=40.0, size=100_000)

histogram = fc.histogram_chart(
    fc.histogram(latency, bins=120, color="#6e56cf"),
    fc.x_axis(label="latency (ms)"),
)

cdf = fc.ecdf_chart(
    fc.ecdf(latency, bins=256, color="#2563eb"),
    fc.x_axis(label="latency (ms)"),
    fc.y_axis(label="fraction"),
)
~~~

Histograms support `range`, `density`, and `cumulative`. With both
`density=True` and `cumulative=True`, the final bin approaches `1.0`.

## Compare Groups

~~~python
groups = [rng.normal(48, 7, 2_000), rng.normal(57, 9, 2_000)]
labels = ["Control", "Treatment"]

chart = fc.chart(
    fc.violin(groups, x=labels, color="#c4b5fd", opacity=0.5),
    fc.box(groups, x=labels, color="#6e56cf", width=0.35),
    fc.x_axis(label="cohort"),
    fc.y_axis(label="score"),
)
~~~

## Live Reflex Preview

~~~python demo-only exec
import reflex_xy
import xy as fc


def latency_distribution():
    latency = [18, 22, 24, 27, 31, 34, 37, 39, 43, 46, 52, 58, 67, 79, 96]
    return reflex_xy.chart(
        fc.histogram_chart(
            fc.histogram(latency, bins=8, color="#6e56cf"),
            fc.x_axis(label="latency (ms)"),
            fc.y_axis(label="requests"),
            title="Request latency",
        ),
        height="320px",
    )
~~~
