---
title: Error Bars and Bands
description: Show point uncertainty, intervals, and confidence regions.
---

# Error Bars and Bands

`errorbar` draws x or y uncertainty around estimates. `error_band` fills the
region between lower and upper bounds and layers naturally with a line.

~~~python
import numpy as np
import xy as fc

x = np.arange(12, dtype=float)
estimate = 30 + 2.2 * x + 3 * np.sin(x)
error = 1.5 + 0.15 * x

chart = fc.chart(
    fc.error_band(
        x,
        estimate - error,
        estimate + error,
        color="#6e56cf",
        name="95% interval",
    ),
    fc.line(x, estimate, color="#6e56cf", width=2, name="Estimate"),
    fc.errorbar(x[::2], estimate[::2], yerr=error[::2], color="#1b212a"),
    fc.legend(),
)
~~~

`errorbar` accepts `xerr`, `yerr`, `cap_size`, `width`, and `opacity`.
`error_band` accepts array or named-column bounds plus fill styling.

## Live Reflex Preview

~~~python demo-only exec
import reflex_xy
import xy as fc


def uncertainty_preview():
    x = [0, 1, 2, 3, 4, 5, 6]
    estimate = [24, 27, 29, 34, 37, 39, 44]
    error = [2.0, 2.5, 2.0, 3.0, 2.5, 3.0, 2.0]
    lower = [value - spread for value, spread in zip(estimate, error, strict=True)]
    upper = [value + spread for value, spread in zip(estimate, error, strict=True)]
    figure = fc.chart(
        fc.error_band(x, lower, upper, color="#6e56cf", name="95% interval"),
        fc.line(x, estimate, color="#6e56cf", width=2, name="Estimate"),
        fc.errorbar(x[::2], estimate[::2], yerr=error[::2], color="#1b212a"),
        fc.legend(),
        title="Forecast uncertainty",
    )
    return reflex_xy.chart(figure, height="360px")
~~~
