---
title: Line and Area Charts
description: Render trends, ranges, baselines, smooth curves, and layered series.
---

# Line and Area Charts

Use `line` for trends and `area` when the magnitude relative to a baseline is
important. Both support smooth curves, screen-space dash patterns, opacity, and
named axes.

## Layer Lines and Areas

~~~python
import numpy as np
import xy as fc

x = np.linspace(0, 12, 240)
plan = 48 + 1.8 * x
actual = plan + 7 * np.sin(x * 0.9)

chart = fc.chart(
    fc.area(
        x,
        actual,
        name="Actual",
        color="#6e56cf",
        fill="linear-gradient(currentColor, transparent)",
        opacity=0.42,
        curve="smooth",
    ),
    fc.line(x, plan, name="Plan", color="#2563eb", dash="dashed"),
    fc.x_axis(label="month"),
    fc.y_axis(label="revenue"),
    fc.legend(),
)
~~~

## Live Reflex Preview

~~~python demo-only exec
import reflex_xy
import xy as fc


def plan_and_actual():
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    return reflex_xy.chart(
        fc.chart(
            fc.area(
                months,
                [42, 47, 51, 49, 58, 64],
                name="Actual",
                color="#6e56cf",
                opacity=0.35,
                curve="smooth",
            ),
            fc.line(
                months,
                [40, 44, 48, 52, 56, 60],
                name="Plan",
                color="#2563eb",
                dash="dashed",
            ),
            fc.x_axis(label="month"),
            fc.y_axis(label="revenue"),
            fc.legend(),
        ),
        height="320px",
    )
~~~

`base` on `area` may be a scalar, array, or named column. Set
`stroke_perimeter=True` to outline the full filled polygon. Use `line_width`
and `line_opacity` to tune the area's boundary separately from its fill.

For very long lines, XY decimates to the visible resolution and refines again
when the viewport changes.
