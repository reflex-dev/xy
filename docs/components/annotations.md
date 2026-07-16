---
title: Annotations
description: Add rules, bands, labels, markers, arrows, thresholds, and callouts.
---

# Annotations

Annotations are chart children painted above data marks. Their geometry uses
data coordinates, so it stays aligned while users pan and zoom.

## Rules and Bands

| Component | Purpose |
| --- | --- |
| `vline(x)` | Vertical rule at an x value |
| `hline(y)` | Horizontal rule at a y value |
| `x_band(x0, x1)` | Shaded x interval |
| `y_band(y0, y1)` | Shaded y interval |
| `threshold(value, axis=...)` | Semantic rule on either axis |
| `threshold_zone(start, end, axis=...)` | Semantic shaded interval |

## Labels, Markers, and Arrows

`text` and `label` place text at a coordinate. `marker` adds a point symbol and
optional label. `arrow(x0, y0, x1, y1)` connects two points. `callout` pins a
label to a point with configurable screen-space `dx` and `dy` offsets.

~~~python
import xy as fc

chart = fc.line_chart(
    fc.line([0, 1, 2, 3, 4], [38, 41, 43, 46, 52]),
    fc.threshold_zone(45, 60, text="target zone", color="#16a34a"),
    fc.vline(3, text="launch", color="#2563eb"),
    fc.marker(4, 52, text="v1", color="#2563eb"),
    fc.callout(4, 52, "record", dx=-60, dy=-30),
)
~~~

## Live Reflex Preview

~~~python demo-only exec
import reflex_xy
import xy as fc


def annotations_preview():
    figure = fc.line_chart(
        fc.line([0, 1, 2, 3, 4], [38, 41, 43, 46, 52], color="#6e56cf"),
        fc.threshold_zone(45, 60, text="target zone", color="#16a34a"),
        fc.vline(3, text="launch", color="#2563eb"),
        fc.marker(4, 52, text="v1", color="#2563eb"),
        fc.callout(4, 52, "record", dx=-60, dy=-30),
        title="Release progress",
    )
    return reflex_xy.chart(figure, height="360px")
~~~

Annotation shapes use `color`, `width`, `opacity`, and component-specific stroke
props. Annotation labels are DOM elements and also accept `class_name` and
`style`.
