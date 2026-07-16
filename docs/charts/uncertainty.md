---
title: Error Bars and Bands
description: Show point uncertainty, intervals, and confidence regions.
---

# Error Bars and Bands

`errorbar` draws x or y uncertainty around estimates. `error_band` fills the
region between lower and upper bounds and layers naturally with a line.

~~~python demo exec
import numpy as np
import reflex_xy
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


def uncertainty_chart_demo():
    return reflex_xy.chart(chart, height="360px")
~~~

`errorbar` accepts `xerr`, `yerr`, `cap_size`, `width`, and `opacity`.
`error_band` accepts array or named-column bounds plus fill styling.
