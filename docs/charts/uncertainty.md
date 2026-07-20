---
title: Error Bars and Bands
description: Show point uncertainty, intervals, and confidence regions.
---

# Error Bars and Bands

## When to Use

`errorbar` draws x or y uncertainty around estimates. `error_band` fills the
region between lower and upper bounds and layers naturally with a line.

## Live Demo

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.arange(12, dtype=float)
estimate = 30 + 2.2 * x + 3 * np.sin(x)
error = 1.5 + 0.15 * x

chart = xy.chart(
    xy.error_band(
        x,
        estimate - error,
        estimate + error,
        color="#6e56cf",
        name="95% interval",
    ),
    xy.line(x, estimate, color="#6e56cf", width=2, name="Estimate"),
    xy.errorbar(x[::2], estimate[::2], yerr=error[::2], color="#1b212a"),
    xy.legend(),
)


def uncertainty_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

## Chart Types

### Error Band

Use `error_band` for a continuous lower-to-upper interval, commonly layered
beneath a line to show confidence or forecast ranges.

### Error Bar

Use `errorbar` for uncertainty attached to individual observations. It supports
x or y uncertainty and symmetric or asymmetric values.

## Variants

Use symmetric or asymmetric error arrays on either axis. Layer a translucent
band beneath a line for intervals that vary continuously, or draw capped error
bars at selected observations.

## Expected Data Shape

`errorbar` takes x/y estimates plus scalar or array `xerr` and `yerr` values.
`error_band` takes x, lower, and upper arrays of equal length. All inputs may be
named columns resolved through `data=`.

## Key Options

`errorbar` uses `xerr`, `yerr`, `cap_size`, `width`, `color`, and `opacity`.
`error_band` uses `color`, `fill`, `opacity`, `line_width`, `line_opacity`, and
`name`.
