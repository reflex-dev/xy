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

~~~python demo exec
import numpy as np
import reflex_xy
import xy as fc

rng = np.random.default_rng(3)
latency = rng.gamma(shape=2.0, scale=40.0, size=100_000)

histogram = fc.histogram_chart(
    fc.histogram(latency, bins=120, color="#6e56cf"),
    fc.x_axis(label="latency (ms)"),
    fc.y_axis(label="requests"),
    title="Request latency",
)

cdf = fc.ecdf_chart(
    fc.ecdf(latency, bins=256, color="#2563eb"),
    fc.x_axis(label="latency (ms)"),
    fc.y_axis(label="fraction"),
)


def latency_distribution():
    return reflex_xy.chart(histogram, height="320px")
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
