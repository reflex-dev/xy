---
title: Histogram in Python
description: Histogram Python charts with xy — bin large datasets into a fast, interactive frequency distribution that pans, zooms, and refines smoothly at millions of values.
components:
  - xy.histogram_chart
---

# Histograms in Python

A **histogram** (also called a histogram chart, histogram plot, or histogram
graph) bins continuous values into intervals and draws a bar for the count in
each bin, showing the shape of a distribution. With `xy` you build a
python histogram that stays interactive at scale: bin hundreds of thousands of
values, then pan, zoom, and hover without lag.

Jump to [creating a histogram](#create-a-histogram),
[density and cumulative modes](#density-and-cumulative-histograms), or
[options](#histogram-options).

## Create a Histogram

Pass a 1-D array of samples to `histogram` and choose the number of `bins`.
This is the minimal Python histogram:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(3)
latency = rng.gamma(shape=2.0, scale=40.0, size=100_000)

chart = xy.histogram_chart(
    xy.histogram(latency, bins=120, color="#6e56cf"),
    xy.x_axis(label="latency (ms)"),
    xy.y_axis(label="requests"),
    title="Request latency",
)


def latency_histogram():
    return reflex_xy.chart(chart, height="320px")
~~~

## Density and Cumulative Histograms

By default a histogram plots raw counts. Set `density=True` to normalize the
bars into a probability density that integrates to 1, which is useful when
comparing distributions with different sample sizes. Set `cumulative=True` to
accumulate counts from left to right and read off how much of the data falls
below any value — a close cousin of the [ECDF](/docs/xy/charts/ecdf/).

### Probability Density with Styled Bars

Set `density=True` to normalize the bars, clamp binning to a `(min, max)`
window with `range`, and soften the bars with `corner_radius` and `opacity`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

density_rng = np.random.default_rng(9)
response_times = density_rng.lognormal(mean=3.4, sigma=0.45, size=60_000)

density_hist_chart = xy.histogram_chart(
    xy.histogram(
        response_times,
        bins=80,
        range=(0.0, 120.0),
        density=True,
        color="#0ea5e9",
        opacity=0.75,
        corner_radius=3.0,
    ),
    xy.x_axis(label="response time (ms)"),
    xy.y_axis(label="probability density"),
    title="Response time density (0-120 ms window)",
)


def density_histogram_demo():
    return reflex_xy.chart(density_hist_chart, height="320px")
~~~

### Overlay Two Distributions

Stack two `histogram` marks in one chart with shared `bins` and `range`, name
each with `name=`, lower `opacity` so both stay readable, and add `xy.legend()`.

~~~python demo exec
import numpy as np
import reflex_xy
import xy

overlay_rng = np.random.default_rng(17)
baseline_scores = overlay_rng.normal(64, 11, 40_000)
variant_scores = overlay_rng.normal(71, 8, 40_000)

overlay_hist_chart = xy.histogram_chart(
    xy.histogram(
        baseline_scores,
        bins=90,
        range=(20.0, 110.0),
        name="Baseline",
        color="#6e56cf",
        opacity=0.55,
    ),
    xy.histogram(
        variant_scores,
        bins=90,
        range=(20.0, 110.0),
        name="Variant",
        color="#e5484d",
        opacity=0.55,
    ),
    xy.x_axis(label="score"),
    xy.y_axis(label="samples"),
    xy.legend(),
    title="Baseline vs variant scores",
)


def overlay_histogram_demo():
    return reflex_xy.chart(overlay_hist_chart, height="320px")
~~~

## Large Histograms

`xy` computes bins over the raw f64 samples and draws only the bin bars, so the
cost scales with the bin count, not the sample count. Binning hundreds of
thousands of values stays fast, and the chart pans and zooms without
recomputing the whole distribution.

## Histogram Options

| Option | Purpose |
| --- | --- |
| `bins` | Number of equal-width bins, or explicit bin edges. |
| `range` | `(min, max)` limits for binning; values outside are ignored. |
| `density` | Normalize bars into a probability density that integrates to 1. |
| `cumulative` | Accumulate counts from left to right. |
| `color` | Bar color (any CSS color). |
| `opacity` | Bar opacity from 0 to 1. |

Pass a column name with `data=` instead of an array when your data is a table.

## Related Charts

- [ECDF plots](/docs/xy/charts/ecdf/) — the cumulative distribution without
  binning.
- [Box plots](/docs/xy/charts/box-plot/) — summarize a distribution with
  quartiles.
- [Violin plots](/docs/xy/charts/violin-plot/) — show the full density shape.

## FAQ

### How do I make a histogram in Python?

Call `xy.histogram(values, bins=...)` inside `xy.histogram_chart(...)` and
render it. Binning, axes, pan, zoom, and hover are handled automatically.

### How many bins should a histogram use?

It depends on your data, but more bins reveal finer structure at the cost of
noisier bars. Start around 30–120 and adjust `bins` until the shape reads
clearly.

### What is the difference between a histogram and a density plot?

A raw histogram shows counts per bin. Set `density=True` to normalize the bars
into a probability density that integrates to 1, so distributions with
different sample sizes become comparable.

### Can a histogram handle large datasets?

Yes. `xy` bins the raw samples and draws only the bin bars, so hundreds of
thousands of values stay interactive with smooth pan and zoom.
