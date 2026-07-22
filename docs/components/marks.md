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

~~~python
import xy

chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [2, 5, 3, 8], name="signal"),
)
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
