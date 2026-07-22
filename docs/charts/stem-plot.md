---
title: Stem Plot in Python
description: Create a stem plot in Python with xy. Draw discrete values and impulses anchored to a baseline, interactive out of the box with pan, zoom, and hover.
components:
  - xy.stem_chart
---

# Stem Plots in Python

A **stem plot** (also called a stem chart or stem graph) draws each value as a
vertical line, or impulse, rising from a
common baseline to a marker at the data point. With `xy` you build a stem plot
in Python for discrete sequences — sample indices, event counts, or signal taps
— where a connecting line would imply continuity that isn't there. Every stem
plot is interactive by default: pan, zoom, and hover work with no configuration.

Jump to [creating a stem plot](#create-a-stem-plot),
[when to use one](#when-to-use-a-stem-plot), or the
[options](#stem-plot-options).

## Create a Stem Plot

Pass equal-length x and value arrays to `stem`. Each point becomes an impulse
anchored to the baseline with a marker at its tip:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

x = np.arange(10)
values = np.array([2, 5, 3, 7, 6, 9, 8, 11, 10, 13])

chart = xy.chart(
    xy.stem(x, values - 1.5, name="Events", color="#2563eb"),
    xy.legend(),
)


def stem_chart_demo():
    return reflex_xy.chart(chart, height="340px")
~~~

## Style Stems and Markers

Values may swing above and below the baseline, and `width`, `opacity`,
`marker_size`, and `symbol` control how each impulse and its tip are drawn:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

n_taps = np.arange(24)
impulse_response = 9.0 * np.sin(n_taps * 0.9) * 0.72**n_taps

styled_stem_chart = xy.chart(
    xy.stem(
        n_taps,
        impulse_response,
        color="#e5484d",
        width=2.5,
        opacity=0.85,
        marker_size=7,
        symbol="diamond",
        name="h[n]",
    ),
    xy.x_axis(label="sample n"),
    xy.y_axis(label="amplitude"),
    xy.legend(),
    title="Damped impulse response",
)


def styled_stem_demo():
    return reflex_xy.chart(styled_stem_chart, height="340px")
~~~

## Compare Stem Series with an Overlay

Layer multiple `stem` marks (offset the x values slightly so stems don't
overlap), disable markers with `marker=False`, and add a dashed `line` envelope
for context:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng_sig = np.random.default_rng(3)
k = np.arange(16)
measured_taps = 6.5 * 0.78**k + rng_sig.normal(0.0, 0.18, k.size)
ideal_taps = 6.5 * 0.78**k
envelope_x = np.linspace(0, 15, 120)
envelope_y = 6.5 * 0.78**envelope_x

stem_overlay_chart = xy.chart(
    xy.line(envelope_x, envelope_y, color="#9ba1a6", width=1.5, dash="dashed", name="Envelope"),
    xy.stem(k, ideal_taps, base=0.0, color="#2563eb", width=1.4, marker=False, name="Ideal"),
    xy.stem(
        k + 0.18,
        measured_taps,
        base=0.0,
        color="#e5484d",
        width=2.0,
        marker_size=5.5,
        name="Measured",
    ),
    xy.x_axis(label="tap k"),
    xy.y_axis(label="coefficient"),
    xy.legend(),
)


def stem_overlay_demo():
    return reflex_xy.chart(stem_overlay_chart, height="340px")
~~~

## When to Use a Stem Plot

Reach for a stem plot when values are discrete or sampled and each observation
should stay anchored to a baseline — impulse responses, counts, or spectral
taps. To mark thresholds or reference levels alongside the stems, use the
[annotations component](/docs/xy/components/annotations/). When observations
form a continuous trend that should be connected instead, use the
[line chart](/docs/xy/charts/line-chart/).

## Stem Plot Options

| Option | Purpose |
| --- | --- |
| `color` | Line and marker color (any CSS color). |
| `name` | Series label shown in the `legend()`. |
| `width` | Stem stroke width in pixels. |
| `opacity` | Stem and marker opacity from 0 to 1. |

Pass column names with `data=` instead of arrays when your values live in a
table.

## Related Charts

- [Line charts](/docs/xy/charts/line-chart/) — connect ordered observations to
  show a continuous trend.
- [Line segments](/docs/xy/charts/segments/) — draw independent start-to-end
  segments with their own endpoints.

## FAQ

### How do I make a stem plot in Python?

Call `xy.stem(x, values)` inside `xy.chart(...)` and render it. Each value is
drawn as an impulse from the baseline to a marker, and pan, zoom, and hover are
enabled automatically.

### When should I use a stem plot instead of a line chart?

Use a stem plot for discrete or sampled values where a connecting line would
falsely imply continuity between points. Use a line chart when the data is a
continuous trend that should be connected.

### How do I add a legend to a stem plot?

Give the `stem` mark a `name` and add `xy.legend()` inside the same
`xy.chart(...)`.

### Can I change the baseline the stems anchor to?

Yes. Offset the values you pass to `stem` so they rise from the level you want,
as the demo does by subtracting a constant from the raw values.
