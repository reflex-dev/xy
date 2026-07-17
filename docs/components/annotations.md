---
title: Annotations
description: Add rules, bands, labels, markers, arrows, thresholds, and callouts.
---

# Annotations

Annotations are chart children painted above data marks. Their anchors use data
coordinates, so they stay aligned while users pan and zoom. Text offsets such
as `dx` and `dy` are screen-space pixels, which keeps a label legible without
changing its data anchor.

## Rules and Bands

| Component | Purpose |
| --- | --- |
| `vline(x)` | Vertical rule at an x value |
| `hline(y)` | Horizontal rule at a y value |
| `x_band(x0, x1)` | Shaded x interval |
| `y_band(y0, y1)` | Shaded y interval |
| `threshold(value, axis=...)` | Semantic rule on either axis |
| `threshold_zone(start, end, axis=...)` | Semantic shaded interval |

`threshold` is an annotation alias for a horizontal or vertical rule; it is
not a data mark. `threshold_zone` similarly selects an x or y band.

## Labels, Markers, and Arrows

`text` and `label` place text at a coordinate. `marker` adds a point symbol and
optional label. `arrow(x0, y0, x1, y1)` connects two points. `callout` pins a
label to a point with configurable screen-space `dx` and `dy` offsets.

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

## Paint and Labels

Annotation geometry uses `color`, `width`, `opacity`, and component-specific
stroke or marker props. These are annotation controls, not the compiled mark
CSS subset.

Annotation labels are browser DOM elements. Their `class_name` and `style`
values can customize the label, and chart-level styling can target the stable
`annotation_label` slot. Keep geometry in the component props when output must
agree across HTML, SVG, and native PNG.

If more than one annotation occupies the same coordinate, declaration order
controls their paint order. For a chart-family view of annotation patterns, see
[Annotations Gallery](/docs/xy/charts/annotations/). Exact signatures and
defaults are in
[Marks and components reference](/docs/xy/api-reference/marks-and-components/).
