---
title: Radar Charts in Python
description: Create filled or outlined radar and spider charts in Python with xy. Compare several measurements across a shared set of categories.
components:
  - xy.radar_chart
---

# Radar Charts in Python

A **radar chart** (or spider chart) compares several measurements across the
same categorical dimensions. XY places the categories at evenly spaced angles,
draws one spoke for each category, and closes every series across the circular
seam.

Use radar charts for compact profile comparisons such as product capabilities,
model scores, survey dimensions, and operational health. When the angular
position is itself a measured quantity rather than a category, start with the
[polar chart overview](/docs/xy/charts/polar-chart/) instead.

## Create a Radar Chart

Pass the category labels first, followed by one `area` or `line` mark per
series. Each mark supplies exactly one value per category:

~~~python demo exec
import reflex_xy
import xy

capabilities = ["Speed", "Range", "Payload", "Efficiency", "Comfort"]

radar = xy.radar_chart(
    capabilities,
    xy.area(
        [0.92, 0.70, 0.58, 0.82, 0.64],
        name="Model A",
        color="#6e56cf",
        line_color="#6e56cf",
        opacity=0.28,
    ),
    xy.area(
        [0.68, 0.88, 0.76, 0.61, 0.86],
        name="Model B",
        color="#2563eb",
        line_color="#2563eb",
        opacity=0.24,
    ),
    xy.theta_axis(grid_shape="linear"),
    xy.r_axis(domain=(0.0, 1.0)),
    xy.legend(loc="right"),
    title="Vehicle comparison",
)


def radar_demo():
    return reflex_xy.chart(radar, height="440px")
~~~

The helper assigns the category labels to the theta axis and closes the first
and last category with a straight chord. You do not need to repeat the first
value at the end of a series.

## Choose Filled Areas or Outlines

Use `xy.area(values)` for a filled profile or `xy.line(values)` for an outline.
When an existing composition already uses area marks, set `fill=False` on the
chart to turn every area into an outline without rewriting the series:

~~~python demo exec
import reflex_xy
import xy

outline = xy.radar_chart(
    ["Reliability", "Speed", "Efficiency", "Comfort"],
    xy.area(
        [0.90, 0.72, 0.84, 0.66],
        name="Current",
        color="#8b5cf6",
        line_color="#7c3aed",
        line_width=3,
        line_opacity=0.8,
    ),
    xy.area(
        [0.78, 0.88, 0.71, 0.81],
        name="Candidate",
        color="#38bdf8",
        line_color="#0284c7",
        line_width=3,
        line_opacity=0.8,
    ),
    xy.theta_axis(grid_shape="linear"),
    xy.r_axis(domain=(0.0, 1.0)),
    xy.legend(loc="right"),
    fill=False,
    title="Outline comparison",
)


def radar_outline_demo():
    return reflex_xy.chart(outline, height="420px")
~~~

When `fill=False` rebuilds an area as a line, the outline inherits
`line_color`, `line_width`, `line_opacity`, curve, and dash settings. If
`line_color` is omitted, it falls back to the area's `color`.

Filled profiles work best with some transparency so overlapping series remain
readable. Give each series a `name` and add `xy.legend()` when the chart
contains more than one profile.

## Follow the Radar Data Contract

Radar charts have a deliberately narrow input contract:

- Supply at least three categories.
- Every series must contain exactly one value per category.
- Use only `area` and `line` marks.
- Put values directly on the mark. Column-name strings are not resolved because
  the category list supplies the angular positions.

XY raises `ValueError` for a category/value mismatch instead of silently
dropping a dimension or drawing a malformed polygon.

## Configure the Scale

Add `xy.r_axis(domain=(minimum, maximum))` when several charts need a common
comparison scale. The default radial range begins at zero and extends to the
largest value. Use `tick_values=` for exact rings and `label=` when the score
has a named unit.

The category list owns the theta labels. An authored `xy.theta_axis()` can
customize their style; `grid_shape="linear"` joins the spokes into polygonal
rings, as in the live example. General `polar_chart()` compositions also
accept category strings directly. `radar_chart()` additionally validates that
each series matches the shared category count and closes profiles for you.

## Interaction and Export

Radar charts use the shared polar interaction model: hover, radial-only zoom,
and reset are available; rotation, box zoom, selection, brushing, and
crosshairs are disabled. Browser, SVG, PDF, and native raster exports share the
same radar geometry.

See [Polar chart interaction and limits](/docs/xy/charts/polar-chart/#hover-and-zoom)
for the complete coordinate-system contract.

## Related Polar Charts

- [Polar overview](/docs/xy/charts/polar-chart/) — measured theta/r data, axes,
  pyplot compatibility, and shared limits.
- [Radial bar charts](/docs/xy/charts/radial-bar-chart/) — magnitudes encoded as
  annular sectors.
- [Wind rose charts](/docs/xy/charts/wind-rose/) — raw compass observations
  binned by direction and speed.

## FAQ

### What is the difference between a radar chart and a polar line chart?

A radar chart assigns evenly spaced angles to category labels and closes the
profile automatically. A polar line chart expects explicit numeric angles and
radii.

### How do I draw an unfilled spider chart?

Use `xy.line(values)` for each series, or pass `fill=False` to
`xy.radar_chart()` when the children are area marks.

### Why does my radar chart raise a value-count error?

Each series must have the same number of values as the category list. Add or
remove values so every category has one measurement.
