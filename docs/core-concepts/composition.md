---
title: Composition
description: Compose marks, axes, annotations, and chart chrome.
---

# Composition

Every XY chart is a lightweight Python tree. Children are applied in declaration
order, which makes layering explicit and keeps configuration close to the data
it affects.

## Marks Inside a Chart

~~~python
import xy as fc

data = {
    "month": ["Jan", "Feb", "Mar", "Apr"],
    "actual": [12, 18, 16, 22],
    "target": [14, 15, 17, 20],
}

chart = fc.chart(
    fc.bar(x="month", y="actual", data=data, name="Actual", color="#c4b5fd"),
    fc.line(x="month", y="target", data=data, name="Target", color="#6e56cf"),
    fc.x_axis(label="month"),
    fc.y_axis(label="pipeline"),
    fc.legend(),
    fc.tooltip(fields=["month", "actual", "target"]),
    title="Layered pipeline",
)
~~~

Use a family container when the intent is clearer:

~~~python
chart = fc.scatter_chart(
    fc.scatter([1, 2, 3], [4, 2, 7]),
    fc.x_axis(label="x"),
    fc.y_axis(label="y"),
)
~~~

## Component Families

| Family | Components |
| --- | --- |
| Containers | `chart`, `line_chart`, `scatter_chart`, and other family containers |
| Marks | `line`, `scatter`, `area`, `bar`, `heatmap`, and statistical/specialized marks |
| Axes | `x_axis`, `y_axis`, including additional named axes |
| Annotations | Rules, bands, labels, markers, arrows, thresholds, and callouts |
| Chrome | `legend`, `tooltip`, `colorbar`, and `modebar` |
| Behavior | `interaction_config` and `on_*` callbacks |
| Appearance | `theme`, chart styles, slot styles, and mark props |

## Chart Methods

Composed charts expose `show()`, `widget()`, `to_html()`, `to_png()`,
`to_svg()`, and `memory_report()`. Advanced code can call `figure()` to inspect
the compiled engine figure, but it is not required for normal chart building.
