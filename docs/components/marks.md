---
title: Marks
description: Bind data to XY marks, channels, axes, styles, and layers.
---

# Marks

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

The [Chart Gallery](/docs/xy/charts/) explains expected data shapes and
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

Canvas and WebGL marks are not DOM elements. CSS selectors and Tailwind classes
cannot paint their geometry; use `style=` or the mark's paint props. In
particular, `class_name=` should not be treated as a portable mark-painting
hook. See [Mark styles](/docs/xy/styling/mark-styles/) for the compiled CSS
subset.

## Representation Does Not Change the Mark

Large marks can be transported as decimated lines or density summaries. That
changes the screen representation, not the declarative mark or the canonical
Python columns. Exact row callbacks require a live notebook or framework
transport; a standalone export can only inspect its resident representation.

See [Large data and performance](/docs/xy/core-concepts/large-data-and-performance/)
for the tiering contract and [Marks and components reference](/docs/xy/api-reference/marks-and-components/)
for signatures and defaults.
