---
title: Annotations
description: Add data-aligned rules, bands, labels, markers, arrows, and callouts.
---

# Annotations

## When to Use

Annotations explain important coordinates without changing the underlying data
marks. They remain aligned as users pan and zoom. Use the
[component guide](/docs/xy/components/annotations/) for the full option surface.

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

## Variants

- `hline` and `vline` draw rules at one coordinate.
- `x_band`, `y_band`, and `threshold_zone` shade intervals.
- `text` and `label` place DOM labels at data coordinates.
- `marker`, `arrow`, and `callout` emphasize individual observations.

## Expected Data Shape

Annotations take scalar coordinates or categories expressed in the same axis
space as the chart. Bands take two endpoints; arrows take a start and end
point. They do not require a separate table.

## Key Options

Rules expose `color`, `width`, `opacity`, and optional text. Labels and markers
add screen-space offsets, anchors, symbols, and class/style hooks. Callouts add
a pointer from an offset label back to the selected coordinate.
