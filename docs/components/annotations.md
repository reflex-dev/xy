---
title: Annotations in Python
description: Add rules, bands, labels, markers, arrows, thresholds, and callouts.
components:
  - xy.vline
  - xy.hline
  - xy.x_band
  - xy.y_band
  - xy.threshold
  - xy.threshold_zone
  - xy.text
  - xy.label
  - xy.marker
  - xy.arrow
  - xy.callout
---

# Annotations in Python

Annotations are chart children painted above data marks. Their anchors use data
coordinates, so they stay aligned while users pan and zoom. Text offsets such
as `dx` and `dy` are screen-space pixels, which keeps a label legible without
changing its data anchor.

## When to Use

Use annotations to explain important coordinates without changing the
underlying data marks. Rules and bands show references or ranges; labels,
markers, arrows, and callouts draw attention to individual observations.

## Live Demo

~~~python demo exec
import reflex_xy
import xy

chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4], [38, 41, 43, 46, 52], color="#6e56cf"),
    xy.threshold_zone(45, 60, text="target zone", color="#16a34a"),
    xy.vline(3, text="launch", color="#2563eb"),
    xy.marker(4, 52, text="v1", color="#2563eb"),
    xy.callout(4, 52, "record", dx=-60, dy=-30),
    title="Release progress",
)


def annotations_preview():
    return reflex_xy.chart(chart, height="360px")
~~~

## Rules and Bands

### Threshold

`threshold(value, axis=...)` adds a semantic, optionally labeled reference
boundary on either axis.

~~~python demo exec
import reflex_xy
import xy

threshold_detail_chart = xy.column_chart(
    xy.column(["A", "B", "C", "D"], [62, 74, 68, 83], color="#6e56cf"),
    xy.threshold(70, axis="y", text="target", color="#16a34a", width=2),
    xy.y_axis(label="score", domain=(0, 100)),
    title="Target threshold",
)


def threshold_demo():
    return reflex_xy.chart(threshold_detail_chart, height="320px")
~~~

### Horizontal Line

`hline(y)` draws a horizontal rule at one y value.

~~~python demo exec
import reflex_xy
import xy

horizontal_line_detail_chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4], [42, 48, 51, 57, 63], color="#6e56cf"),
    xy.hline(55, text="SLO", color="#2563eb", width=2),
    xy.x_axis(label="release"),
    xy.y_axis(label="requests"),
    title="Horizontal reference",
)


def horizontal_line_demo():
    return reflex_xy.chart(horizontal_line_detail_chart, height="320px")
~~~

### Vertical Line

`vline(x)` draws a vertical rule at one x value.

### Bands

`x_band(x0, x1)` and `y_band(y0, y1)` shade an interval on the corresponding
axis.

~~~python demo exec
import reflex_xy
import xy

bands_detail_chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4, 5], [3, 5, 4, 7, 6, 8], color="#6e56cf"),
    xy.x_band(1.5, 3.0, text="launch window", color="#f59e0b", opacity=0.16),
    xy.y_band(6.5, 8.5, text="target range", color="#16a34a", opacity=0.12),
    xy.x_axis(label="week"),
    xy.y_axis(label="value"),
    title="Reference bands",
)


def bands_demo():
    return reflex_xy.chart(bands_detail_chart, height="320px")
~~~

### Threshold Zone

`threshold_zone(start, end, axis=...)` adds a semantic shaded interval on either
axis.

`threshold` is an annotation alias for a horizontal or vertical rule; it is
not a data mark. `threshold_zone` similarly selects an x or y band.

## Labels, Markers, and Arrows

### Callout

`callout` pins explanatory text to a point with configurable screen-space `dx`
and `dy` offsets.

### Arrow

`arrow(x0, y0, x1, y1)` connects two coordinates and points toward the end.

~~~python demo exec
import reflex_xy
import xy

arrow_detail_chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4], [2, 3, 4, 7, 8], color="#94a3b8"),
    xy.arrow(1.5, 4.2, 3, 7, text="inflection", color="#e11d48", width=2),
    xy.x_axis(label="period"),
    xy.y_axis(label="value"),
    title="Directional annotation",
)


def arrow_demo():
    return reflex_xy.chart(arrow_detail_chart, height="320px")
~~~

### Label

`label` attaches concise text to a coordinate with label-oriented positioning.

~~~python demo exec
import reflex_xy
import xy

label_detail_chart = xy.scatter_chart(
    xy.scatter([1, 2, 3, 4], [3, 6, 4, 8], color="#6e56cf", size=8),
    xy.label(4, 8, "peak", dy=-16, anchor="middle", color="#6e56cf"),
    xy.x_axis(label="period"),
    xy.y_axis(label="value"),
    title="Point label",
)


def label_demo():
    return reflex_xy.chart(label_detail_chart, height="320px")
~~~

### Text

`text` places free text at a coordinate. Use it when no marker or connector is
needed.

~~~python demo exec
import reflex_xy
import xy

text_detail_chart = xy.scatter_chart(
    xy.scatter([1, 2, 3, 4], [2, 5, 4, 7], color="#94a3b8", size=7),
    xy.text(2, 5, "review", dx=10, dy=-14, color="#2563eb"),
    xy.text(4, 7, "ship", dx=-8, dy=-16, anchor="end", color="#16a34a"),
    xy.x_axis(label="milestone"),
    xy.y_axis(label="value"),
    title="Free-positioned text",
)


def text_demo():
    return reflex_xy.chart(text_detail_chart, height="320px")
~~~

`marker` adds a point symbol and optional label. It uses the same data-coordinate
and screen-space offset model as the annotations above.

## Data and Coordinates

Annotation coordinates use the chart's axis space. Rules and markers take
scalar coordinates or categories, bands take two endpoints, and arrows take a
start and end point. They do not require a separate data table.

## Styling and Paint Order

Annotation geometry uses `color`, `width`, `opacity`, and component-specific
stroke or marker props. These are annotation controls, not the compiled mark
CSS subset.

Annotation labels are browser DOM elements. Their `class_name` and `style`
values can customize the label, and chart-level styling can target the stable
`annotation_label` slot. Geometry `opacity` is independent from label text;
use annotation-style `label_opacity` only when the label should also fade.
Keep geometry in the component props when output must agree across HTML, SVG,
and native PNG.

If more than one annotation occupies the same coordinate, declaration order
controls their paint order. Exact signatures and defaults are in
[Marks and components reference](/docs/xy/api-reference/marks-and-components/).

## FAQ

### How do I add a horizontal line to a chart in Python?

Add `xy.hline(y)` as a chart child, e.g.
`xy.hline(55, text="SLO", color="#2563eb", width=2)`; `xy.vline(x)` is the
vertical equivalent. For a reference boundary with semantic intent on either
axis, use `xy.threshold(value, axis="y", text="target")` instead.

### How do I shade a region or band on a chart?

Use `xy.x_band(x0, x1)` or `xy.y_band(y0, y1)` to shade an interval on the
corresponding axis, with `text`, `color`, and `opacity` to label and style it.
`xy.threshold_zone(start, end, axis=...)` does the same for a semantic
"acceptable range" style zone on either axis.

### How do I label a data point and draw an arrow to it on a chart?

`xy.callout(x, y, "note", dx=-60, dy=-30)` pins explanatory text to a point
with a connector, while `xy.arrow(x0, y0, x1, y1, text=...)` draws a
free-standing arrow between two coordinates. For text alone use
`xy.label(x, y, "peak", dy=-16)` or `xy.text(x, y, "note")`, and
`xy.marker(x, y, text=...)` adds a point symbol with an optional label.

### Why do my annotations stay aligned when I pan or zoom the chart?

Annotation anchors use data coordinates, so rules, bands, markers, and callouts
track the data as the viewport changes. Only the text offsets `dx` and `dy` are
screen-space pixels, which keeps labels legible without moving their data
anchor.
