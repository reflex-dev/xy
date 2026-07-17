---
title: What is `xy`?
description: Understand XY's screen-bounded rendering and CSS-first styling model.
---

# What is `xy`?

xy is an experimental Python charting library for responsive, interactive 2D
visualizations. It combines a native Rust compute core, binary column transport,
and a WebGL2 client with a declarative Python API that works in notebooks,
applications, and standalone exports. Two ideas shape the library:

- **Rendered output is bounded by the visible result.** Long ordered series are
  decimated and dense point clouds become fixed-resolution density surfaces,
  then refine as the view narrows. Ingesting and reducing source rows still
  requires data-dependent work; XY avoids asking the browser to retain or draw
  every row when the screen cannot distinguish them.
- **Styling uses familiar web vocabulary.** DOM chrome such as titles, axes,
  legends, tooltips, and controls exposes stable CSS and Tailwind hooks. Canvas
  marks use a validated subset of CSS properties through `style=`, so the same
  intent reaches WebGL, SVG, and native PNG without pretending that CSS
  selectors can target pixels inside a canvas.

~~~python demo-only exec
from xy_docs.demos.xy_sdf_plots import xy_sdf_plot_grid

sdf_plots = xy_sdf_plot_grid
~~~

All four interactive charts come from one cached signed-distance probability
field for lowercase Instrument Sans `xy`. The builder samples one million
points once, reuses the first 50,000 for the binned scatter view and 250,000 for
the final direct scatter, and shares the same PDF with the direct heatmap and
contours. Pillow and SciPy are documentation demo dependencies, not XY runtime
dependencies. [View the customizable Python source](https://github.com/reflex-dev/xy/blob/main/docs/app/xy_docs/demos/xy_sdf_plots.py).

~~~md alert warning
### Early alpha

XY is pre-1.0. The declarative composition model is stabilizing, but callback
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
