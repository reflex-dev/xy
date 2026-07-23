---
title: Marks in Python
description: Bind data to XY marks, channels, axes, styles, and layers.
components:
  - xy.line
  - xy.scatter
  - xy.area
  - xy.bar
  - xy.column
  - xy.histogram
  - xy.box
  - xy.violin
  - xy.ecdf
  - xy.heatmap
  - xy.hexbin
  - xy.contour
  - xy.errorbar
  - xy.error_band
  - xy.step
  - xy.stairs
  - xy.stem
  - xy.segments
  - xy.triangle_mesh
---

# Marks in Python

A mark describes data geometry inside a chart. Factories such as `line()`,
`scatter()`, and `histogram()` return lightweight `Mark` objects; the chart
container resolves their data and compiles them into one figure.

## Bind Arrays or Columns

Pass arrays directly for small, local examples:

~~~python demo exec
import reflex_xy
import xy

signal_chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [2, 5, 3, 8], name="signal"),
)


def marks_array_demo():
    return reflex_xy.chart(signal_chart, height="320px")
~~~

For table-shaped data, pass column names and provide `data=` on the mark or once
on the chart:

~~~python
data = {
    "month": [1, 2, 3, 4],
    "actual": [42, 47, 45, 53],
    "plan": [40, 44, 48, 52],
}

chart = xy.line_chart(
    xy.line("month", "actual", name="Actual"),
    xy.line("month", "plan", name="Plan"),
    data=data,
)
~~~

A mark-level data source overrides the chart-level source. Column-name
resolution works with pandas, NumPy-compatible mappings, and Arrow-backed
tables described in [Data and columns](/docs/xy/core-concepts/data/).
XY validates missing columns and incompatible channel lengths when the chart is
built.

## Choose a Mark Family

| Geometry | Factories |
| --- | --- |
| Trends and ranges | `line`, `area`, `step`, `stairs` |
| Points | `scatter` |
| Categories | `bar`, `column` |
| Distributions | `histogram`/`hist`, `ecdf`, `box`, `violin` |
| Density and grids | `hexbin`, `heatmap`, `contour` |
| Uncertainty | `errorbar`, `error_band` |
| Explicit geometry | `stem`, `segments`, `triangle_mesh` |

The [Chart Gallery](/docs/xy/overview/gallery/) explains expected data shapes and
family-specific choices.

## Layer Marks in Declaration Order

Families mix freely inside one neutral `xy.chart(...)`; children draw in
declaration order, so the bars below come first and the trend line paints over
them:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

layer_month = np.arange(1, 9)
layer_volume = np.array([32, 38, 35, 44, 41, 52, 49, 57])
layer_trend = np.array([30, 34, 37, 41, 44, 48, 51, 55])

layered_chart = xy.chart(
    xy.bar(layer_month, layer_volume, name="Volume", color="#c4b5fd", opacity=0.7),
    xy.line(layer_month, layer_trend, name="Trend", color="#6e56cf", width=2.5),
    xy.x_axis(label="month"),
    xy.y_axis(label="orders"),
    xy.legend(),
    title="Bars first, line on top",
)


def marks_layer_demo():
    return reflex_xy.chart(layered_chart, height="320px")
~~~

## Shared Mark Behavior

- `name=` gives a rendered series its legend label.
- `x_axis=` and `y_axis=` bind a mark to primary or named axes.
- Data-driven `color` and `size` channels are available where the mark supports
  them. Their domains and palettes remain mark configuration, not colorbar
  configuration.
- `style=` is compiled for WebGL, SVG, and native raster output. Supported CSS
  declarations depend on the mark kind and invalid declarations fail early.
- Children draw in declaration order, so broad fills normally come before
  lines and points.
- `key=` supplies stable row identity for keyed browser data transitions, and
  mark-level `animation=` overrides or disables the chart's `xy.animation()`
  policy. See [Animations and data transitions](/docs/xy/styling/animations/).

Canvas and WebGL marks are not DOM elements. CSS selectors and Tailwind classes
cannot paint their geometry; use `style=` or the mark's paint props. In
particular, `class_name=` is adapter-only trace metadata, not a mark-painting
hook in the shipped browser, Reflex, SVG, or native renderers. See
[Customize Each Part](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients)
for the compiled CSS subset.

This example drives one scatter's `color=` and `size=` from a data column-like
array (with `colormap=` and `size_range=` as mark configuration) while a second
mark uses plain paint options — `name=`, `color=`, `dash=`, and `opacity=`:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

style_rng = np.random.default_rng(7)
style_x = style_rng.uniform(0, 10, 60)
style_y = style_x * 0.8 + style_rng.normal(0, 1.2, 60)
style_depth = style_rng.uniform(0, 1, 60)

styled_chart = xy.chart(
    xy.scatter(
        style_x,
        style_y,
        color=style_depth,
        size=style_depth,
        colormap="viridis",
        size_range=(3.0, 12.0),
        name="Samples",
        opacity=0.85,
    ),
    xy.line(
        [0, 10], [0, 8], name="Fit", color="#f43f5e", dash="dashed", width=2, opacity=0.9
    ),
    xy.x_axis(label="input"),
    xy.y_axis(label="response"),
    xy.legend(),
    title="Per-mark channels and paint",
)


def marks_styling_demo():
    return reflex_xy.chart(styled_chart, height="320px")
~~~

## Compose a Multi-Mark Figure

Everything above composes: an uncertainty band drawn with `area(..., base=)`
goes first, the line and points layer over it, and a scatter of conversion
rates binds to a named right-hand axis:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

compose_rng = np.random.default_rng(11)
compose_day = np.arange(1, 31)
compose_sessions = 120 + compose_day * 4 + compose_rng.normal(0, 9, 30).round(1)
compose_band = compose_sessions * 0.15
compose_conv = 0.032 + 0.0009 * compose_day + compose_rng.normal(0, 0.002, 30)

composed_chart = xy.chart(
    xy.area(
        compose_day,
        compose_sessions + compose_band,
        base=compose_sessions - compose_band,
        name="Session range",
        color="#93c5fd",
        opacity=0.3,
    ),
    xy.line(compose_day, compose_sessions, name="Sessions", color="#2563eb", width=2.2),
    xy.scatter(
        compose_day, compose_conv, y_axis="y2", name="Conversion", color="#f59e0b", size=5
    ),
    xy.x_axis(label="day"),
    xy.y_axis(label="sessions"),
    xy.y_axis(id="y2", side="right", label="conversion", domain=(0, 0.08), format=".1%"),
    xy.legend(),
    title="Composite figure with a named axis",
)


def marks_composed_demo():
    return reflex_xy.chart(composed_chart, height="320px")
~~~

## Representation Does Not Change the Mark

Large marks can be transported as decimated lines or density summaries. That
changes the screen representation, not the declarative mark or the canonical
Python columns. Exact row callbacks require a live notebook or framework
transport; a standalone export can only inspect its resident representation.

See [Large data and performance](/docs/xy/core-concepts/large-data-and-performance/)
for the tiering contract and [Marks and components reference](/docs/xy/api-reference/marks-and-components/)
for signatures and defaults.

## FAQ

### How do I combine multiple marks in one chart in Python?

Pass several mark factories as children of one chart container, e.g.
`xy.line_chart(xy.area(...), xy.line(...), xy.scatter(...))`. Give each mark a
`name=` for the legend, and pass `data=` once on the chart to share a table
across marks (a mark-level `data=` overrides it).

### How do I control which mark draws on top of another?

Marks render in declaration order: later children paint over earlier ones. Put
broad fills such as `xy.area()` first and overlays such as `xy.line()` or
`xy.scatter()` after them.

### How do I style each series differently in one chart?

Every mark takes its own paint options — for example `xy.line(..., color=...)`
or a `style=` dict of CSS declarations compiled for WebGL, SVG, and native
raster output. CSS selectors, Tailwind classes, and `class_name=` cannot paint
canvas or WebGL geometry, so per-series styling always goes through the mark
itself.

### Can I plot a mark against a second y-axis?

Yes — bind the mark with `y_axis="y2"` (or `x_axis=` for x) and add a matching
`xy.y_axis(id="y2", side="right")` component to the chart. X-axis identifiers
must start with `x` and y-axis identifiers with `y`, and every named binding
needs a matching axis component.
