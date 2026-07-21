---
title: Line and Area Charts
description: Render trends, ranges, baselines, smooth curves, and layered series.
---

# Line and Area Charts

## When to Use

Use `line` for trends and `area` when the magnitude relative to a baseline is
important. Both support smooth curves, screen-space dash patterns, opacity, and
named axes.

Use `step` for state changes attached to samples and `stairs` when you already
have bin edges. For isolated impulses, use the
[specialized chart guide](/docs/xy/charts/specialized/).

## Live Demo

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.linspace(0, 12, 240)
plan = 48 + 1.8 * x
actual = plan + 7 * np.sin(x * 0.9)

chart = xy.chart(
    xy.area(
        x,
        actual,
        name="Actual",
        color="#6e56cf",
        fill="linear-gradient(currentColor, transparent)",
        opacity=0.42,
        curve="smooth",
    ),
    xy.line(x, plan, name="Plan", color="#2563eb", dash="dashed"),
    xy.x_axis(label="month"),
    xy.y_axis(label="revenue"),
    xy.legend(),
)


def plan_and_actual():
    return reflex_xy.chart(chart, height="320px")
~~~

## Chart Types

### Line

Use `line` for continuous trends, ordered observations, and comparisons between
series. Add `curve="smooth"` when interpolation is appropriate, or keep the
default straight segments when each observation should remain explicit.

### Area

Use `area` when the magnitude relative to a baseline matters. Its `base` can be
a scalar, array, or named column, and an optional perimeter line can keep the
upper boundary readable.

### Step and Stairs

Use `step` when each x/y observation defines a piecewise-constant state. Use
`stairs` when the values describe bins and you have explicit bin edges. Both
support `where="pre"`, `"mid"`, or `"post"` to control where transitions occur.

~~~python demo exec
import reflex_xy
import xy

chart = xy.chart(
    xy.step(
        [0, 1, 2, 3, 4, 5],
        [3.0, 4.5, 3.8, 5.4, 4.7, 6.2],
        where="post",
        name="Sampled state",
        color="#6e56cf",
        width=2.5,
    ),
    xy.stairs(
        values=[1.0, 2.2, 1.5, 2.8, 2.1],
        edges=[0, 1, 2, 3, 4, 5],
        name="Binned level",
        color="#2563eb",
        width=2.5,
        dash="dashed",
    ),
    xy.x_axis(label="time"),
    xy.y_axis(label="value"),
    xy.legend(),
    title="Step and stairs",
)


def step_and_stairs_demo():
    return reflex_xy.chart(chart, height="320px")
~~~

## Variants

- Layer several named `line` or `area` marks and add `legend()`.
- Use `curve="smooth"` for interpolation or `dash` for plan/actual comparisons.
- Set `where="pre"`, `"mid"`, or `"post"` on `step` and `stairs` for
  discrete signals.
- Bind marks to named axes for series with different units.

## Expected Data Shape

Pass one-dimensional x and y arrays of equal length, or pass column names with
`data=`. `area` also accepts a scalar, array, or named-column `base`. Missing
numeric values create line gaps. `step` uses the same x/y shape. `stairs` takes
one value per bin and, when supplied, one more edge than values.

## Key Options

`line` uses `color`, `width`, `opacity`, `curve`, and `dash`. `area` adds
`fill`, `base`, `stroke_perimeter`, `line_width`, and `line_opacity`.
`step` and `stairs` add `where="pre"`, `"mid"`, or `"post"`; `stairs` also
accepts `edges` and otherwise generates integer edges.

For very long lines, XY decimates to the visible resolution and refines again
when the viewport changes.
