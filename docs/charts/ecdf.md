---
title: ECDF Plot in Python
description: ECDF Python charts with xy — plot an empirical cumulative distribution function as a fast, interactive step curve that pans, zooms, and reads percentiles directly.
components:
  - xy.ecdf_chart
---

# ECDF Plots in Python

An **ECDF** plot (also called an ECDF graph) shows the empirical cumulative
distribution function of a sample: for each value it shows the fraction of observations at or below it,
rising from 0 to 1. With `xy` you build an empirical cdf in Python that reads
percentiles straight off the curve and stays interactive — pan, zoom, and hover
across thousands of points.

Jump to [creating an ECDF](#create-an-ecdf), [reading percentiles](#reading-percentiles),
or [options](#ecdf-options).

## Create an ECDF

Pass a 1-D array of samples to `ecdf`. This is the minimal Python ECDF:

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

## Compare Two Distributions

Overlay one `ecdf` mark per sample with `name=` labels, a `dash` style to tell
the curves apart, and a `legend()` — a horizontal gap between the curves reads
directly as a shift in that percentile:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(7)
control_latency = rng.gamma(shape=3.0, scale=40.0, size=1_500)
treatment_latency = rng.gamma(shape=3.0, scale=32.0, size=1_500)

ecdf_compare_chart = xy.ecdf_chart(
    xy.ecdf(control_latency, name="Control", color="#6e56cf", width=2.5),
    xy.ecdf(
        treatment_latency,
        name="Treatment",
        color="#30a46c",
        width=2.5,
        dash="dashed",
    ),
    xy.x_axis(label="latency (ms)"),
    xy.y_axis(label="cumulative fraction", domain=(0, 1)),
    xy.legend(),
    title="Control vs. treatment latency",
)


def ecdf_compare_demo():
    return reflex_xy.chart(ecdf_compare_chart, height="320px")
~~~

## Large Samples with Bounded Bins

For very large inputs, set `bins` to draw a bounded approximation instead of an
exact step per observation — here 500,000 points collapse to 512 steps while
`width` and `opacity` style the curve and the y-axis is pinned to `(0, 1)`:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

noise_rng = np.random.default_rng(42)
sensor_noise = np.concatenate(
    [
        noise_rng.normal(loc=-1.2, scale=0.6, size=250_000),
        noise_rng.normal(loc=1.8, scale=0.9, size=250_000),
    ]
)

ecdf_binned_chart = xy.ecdf_chart(
    xy.ecdf(
        sensor_noise,
        bins=512,
        name="Sensor noise",
        color="#e5484d",
        width=3.0,
        opacity=0.85,
    ),
    xy.x_axis(label="reading"),
    xy.y_axis(label="cumulative fraction", domain=(0, 1)),
    title="Bimodal sample, 500k points",
)


def ecdf_binned_demo():
    return reflex_xy.chart(ecdf_binned_chart, height="320px")
~~~

## Reading Percentiles

An ECDF makes percentiles direct to read: find a fraction on the y-axis and
trace across to the curve to get that percentile's value, or start from a value
on the x-axis to see what fraction of the data falls below it. Because the curve
uses every observation, it avoids the binning choices a
[histogram](/docs/xy/charts/histogram/) forces, so the shape never depends on a
bin count.

## ECDF Options

| Option | Purpose |
| --- | --- |
| `bins` | Bounded approximation for very large inputs; omit for an exact ECDF. |
| `color` | Curve color (any CSS color). |
| `width` | Stroke width in pixels. |
| `opacity` | Curve opacity from 0 to 1. |
| `name` | Series label shown in the `legend()`. |

Pass a column name with `data=` instead of an array when your data is a table.

## Related Charts

- [Histograms](/docs/xy/charts/histogram/) — bin the same distribution into
  bars.
- [Box plots](/docs/xy/charts/box-plot/) — summarize a distribution with
  quartiles.

## FAQ

### How do I make an ECDF in Python?

Call `xy.ecdf(values)` inside `xy.ecdf_chart(...)` and render it. The ECDF
chart handles the curve, axes, pan, zoom, and hover automatically.

### What is an ECDF?

An empirical cumulative distribution function shows, for each value, the
fraction of observations at or below it. It rises from 0 to 1 and uses every
data point directly.

### What is the difference between an ECDF and a histogram?

An ECDF is cumulative and bin-free, so its shape never depends on a bin count. A
[histogram](/docs/xy/charts/histogram/) shows counts per interval and depends on
how many bins you choose.

### How do I read percentiles from an ECDF?

Pick a fraction on the y-axis and trace across to the curve to get that
percentile's value, or start from an x value to see the fraction of data below
it.
