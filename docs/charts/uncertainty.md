---
title: Error Bar and Band Charts in Python
description: Show uncertainty in Python with xy — draw error bars for point estimates and shaded error bands for confidence and forecast intervals.
components:
  - xy.error_band_chart
  - xy.errorbar_chart
---

# Error Bar and Band Charts in Python

## When to Use

An **error bar chart** (also called an error bar plot) shows the uncertainty of
individual estimates, while an error band shades a continuous interval between
bounds. `errorbar` draws x or y uncertainty around estimates. `error_band` fills
the region between lower and upper bounds and layers naturally with a line.

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

## Horizontal and Asymmetric Error Bars

Pass a `(lower, upper)` pair to `xerr` or `yerr` for asymmetric uncertainty on
either axis, and use `cap_size` to draw end caps:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng_dose = np.random.default_rng(7)
dose = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
response = np.array([12.0, 21.0, 34.0, 46.0, 55.0])
dose_lower = dose * 0.18
dose_upper = dose * 0.42
response_err = 2.0 + rng_dose.uniform(0.0, 2.5, dose.size)

asymmetric_errorbar_chart = xy.chart(
    xy.errorbar(
        dose,
        response,
        xerr=(dose_lower, dose_upper),
        yerr=response_err,
        cap_size=5,
        width=1.6,
        color="#e5484d",
        name="Measured response",
    ),
    xy.x_axis(label="dose (mg)"),
    xy.y_axis(label="response"),
    xy.legend(),
)


def asymmetric_errorbar_demo():
    return reflex_xy.chart(asymmetric_errorbar_chart, height="360px")
~~~

## Forecast Fan with Stacked Bands

Layer two `error_band` marks at different opacities to draw nested forecast
intervals that widen with distance from the last observation:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng_fan = np.random.default_rng(11)
history_x = np.arange(24, dtype=float)
history_y = (
    100 + history_x * 1.4 + rng_fan.normal(0.0, 2.0, history_x.size).cumsum() * 0.4
)
future_x = np.arange(23, 36, dtype=float)
forecast = history_y[-1] + 1.4 * (future_x - future_x[0])
spread = 1.0 + 1.9 * np.sqrt(future_x - future_x[0])

forecast_fan_chart = xy.chart(
    xy.error_band(
        future_x,
        forecast - 2.0 * spread,
        forecast + 2.0 * spread,
        color="#6e56cf",
        opacity=0.14,
        name="90% interval",
    ),
    xy.error_band(
        future_x,
        forecast - spread,
        forecast + spread,
        color="#6e56cf",
        opacity=0.30,
        name="50% interval",
    ),
    xy.line(history_x, history_y, color="#1b212a", width=2, name="History"),
    xy.line(future_x, forecast, color="#6e56cf", width=2, dash="dashed", name="Forecast"),
    xy.x_axis(label="month"),
    xy.y_axis(label="demand"),
    xy.legend(),
)


def forecast_fan_demo():
    return reflex_xy.chart(forecast_fan_chart, height="360px")
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

## FAQ

### How do I add error bars to a chart in Python?

Add an `xy.errorbar(x, y, yerr=...)` mark (use `xerr` for horizontal error) to
turn any chart into an error bar graph; it supports symmetric or asymmetric
values and optional caps.

### What is the difference between an error bar and an error band?

An error bar shows uncertainty at individual points; an error band fills a
continuous lower-to-upper region, usually layered beneath a line for confidence
or forecast intervals.

### How do I draw a confidence interval band in Python?

Use `xy.error_band(x, lower, upper)` and layer `xy.line(x, estimate)` on top so
the shaded interval sits behind the trend line.

### Can error bars be asymmetric?

Yes. Pass separate lower and upper magnitudes to `yerr` (or `xerr`) to draw
different error distances above and below each point.
