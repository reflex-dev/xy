---
title: Fast, Interactive Python Charting Library
description: XY is a fast Python charting library for interactive data visualization. Plot millions of points with pan, zoom, and hover. Style charts with CSS or Tailwind.
---

# What is `xy`?

XY is a Python charting library for interactive 2D visualizations that stay
smooth at millions of points and is completely customizable. Two ideas shape
the library:

- **Fast, even with lots of data.** XY draws the detail you can actually see
  instead of every row at once, so pan, zoom, and hover stay responsive as
  your data grows.
- **Completely customizable.** Style titles, axes, legends, tooltips, and controls
  with CSS or Tailwind, and keep the same look in interactive charts, SVGs, and
  PNGs.

Install it and see for yourself:

```bash
uv add xy
```

[Browse the chart gallery](/docs/xy/overview/gallery/) or jump straight to
[your first chart](/docs/xy/overview/first-chart/).

~~~python demo-only exec
from xy_docs.demos.xy_sdf_plots import xy_sdf_plot_grid

sdf_plots = xy_sdf_plot_grid
~~~

All four interactive charts are live — drag to pan, scroll to zoom, and hover
to inspect exact values. Together they render more than a million points from a
single probability field across four chart families.
[View the customizable Python source](https://github.com/reflex-dev/xy/blob/main/docs/app/xy_docs/demos/xy_sdf_plots.py).

~~~md alert warning
**Early alpha.** XY is pre-1.0. The declarative composition model is stabilizing, but callback
payloads, the Reflex adapter, chart breadth, and adaptive-rendering thresholds
may change. See [Limitations and alpha status](/docs/xy/api-reference/limitations-and-alpha-status/)
before committing to a long-lived integration.
~~~

## Start here

- Browse the [visual gallery](/docs/xy/overview/gallery/) to see the chart
  families available today.
- [Install XY](/docs/xy/overview/installation/) and build
  [your first chart](/docs/xy/overview/first-chart/).
- Learn the [composition model](/docs/xy/core-concepts/) behind every chart.
- Read the [benchmark snapshot](/docs/xy/overview/benchmarks/) with its output
  contracts and measurement caveats.
- Follow the [styling overview](/docs/xy/styling/) for CSS, Tailwind, theme
  tokens, and rendered-mark styles.

## Why XY

Python teams usually face a trade-off: charting libraries that hit an
interactivity ceiling as data grows, or browser-first tools that give up design
control. XY is built for the workflows where that trade-off bites. Compose
marks, axes, legends, and controls in Python; brand them with CSS, Tailwind,
and theme tokens; and ship the same chart to notebooks, applications, and
standalone HTML, PNG, or SVG exports.

Performance is part of the architecture, not an option flag. Native Rust
kernels aggregate data before display, binary transport keeps numbers out of
JSON, and the WebGL2 client bounds browser work by what the screen can show,
while exact source data stays in Python for hover and selection.

The numbers back this up. In the recorded 10-million-point launch benchmark, XY
produced a static PNG in 0.023 s, while Matplotlib took 2.8 s and Plotly
9.6 s. XY reached first interactive render 16–20× sooner, peaking at a
third of Matplotlib's memory and a twentieth of Plotly's.

~~~python demo-only exec
from xy_docs.demos.benchmark_charts import launch_snapshot_demo

benchmark_launch_snapshot = launch_snapshot_demo
~~~

The benchmark also tested one billion points. At that size XY switches to a
density view, a heatmap-like summary of where the points fall, and still
delivered a working interactive chart in just over a second. The default
Matplotlib and Plotly approach of drawing every single point did not finish
within the run's memory and time limits.
[Inspect the benchmark evidence](/docs/xy/overview/benchmarks/) or
[browse the chart gallery](/docs/xy/overview/gallery/).
