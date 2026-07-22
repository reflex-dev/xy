---
title: What is `xy`?
description: Understand XY's screen-bounded rendering and CSS-first styling model.
---

# What is `xy`?

xy is an experimental Python charting library for responsive, interactive 2D
visualizations. It combines a native Rust compute core, binary column transport,
and a WebGL2 client with a declarative Python API that works in notebooks,
applications, and standalone exports. Two ideas shape the library:

- **Fast, even with lots of data.** XY keeps large charts smooth by showing the
  detail you can actually see instead of drawing every data point at once.
- **Completely customizable.** Style titles, axes, legends, tooltips, and controls
  with CSS or Tailwind, and keep the same look in interactive charts, SVGs, and
  PNGs.

~~~python demo-only exec
from xy_docs.demos.xy_sdf_plots import xy_sdf_plot_grid

sdf_plots = xy_sdf_plot_grid
~~~

All four interactive charts come from one cached signed-distance probability
field for lowercase Instrument Sans `xy`. The builder samples one million
points once, reuses the first 50,000 for the binned scatter view and 250,000 for
the final direct scatter, and shares the same PDF with the direct heatmap and
contours. The demo's only extra dependency is Pillow; its exact Euclidean
distance transform is implemented directly with NumPy. [View the customizable Python source](https://github.com/reflex-dev/xy/blob/main/docs/app/xy_docs/demos/xy_sdf_plots.py).

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

XY is built for Python teams that want **large-data performance without giving
up design control**. Compose marks, axes, legends, annotations, tooltips,
interactions, and controls in Python, then use CSS, Tailwind, themes, and mark
styles to match your product. The same chart works in notebooks and
applications and exports to self-contained HTML, native PNG, or SVG.

### Performance is part of the architecture

- Native Rust kernels reduce and aggregate large datasets before display.
- Binary column transport avoids expanding numeric data into large JSON
  payloads.
- WebGL2, line decimation, and density rendering keep browser work bounded by
  what the screen can show.
- Exact source columns remain in Python for hover, selection, and deeper
  inspection.

In XY's recorded 10-million-point launch benchmark, it completed ahead of
Matplotlib and Plotly across the tested static PNG, interactive GPU, and
CPU-fallback output contracts. At one billion points, XY produced a validated
density PNG and interactive overview within the benchmark limits instead of
attempting to draw one billion markers.

If you need charts that are fast, fully brandable, interactive, and portable,
XY is built for that workflow. [Inspect the benchmark evidence](/docs/xy/overview/benchmarks/)
or [browse the chart gallery](/docs/xy/overview/gallery/).
