---
title: Composition Model
description: Build XY charts by composing marks, axes, annotations, chrome, and behavior.
---

# Composition Model

XY charts are lightweight Python component trees. A container owns the chart's
layout, data default, interactions, styling hooks, and output methods. Its
children describe rendered marks, axes, annotations, chrome, appearance, and
behavior.

## Compose a chart from children

~~~python
import xy

data = {
    "month": ["Jan", "Feb", "Mar", "Apr"],
    "actual": [12, 18, 16, 22],
    "target": [14, 15, 17, 20],
}

chart = xy.chart(
    xy.bar(x="month", y="actual", name="Actual", color="#c4b5fd"),
    xy.line(x="month", y="target", name="Target", color="#6e56cf"),
    xy.vline("Mar", text="Release", color="#7c3aed"),
    xy.x_axis(label="month"),
    xy.y_axis(label="pipeline"),
    xy.legend(),
    xy.tooltip(fields=["month", "actual", "target"]),
    data=data,
    title="Layered pipeline",
)
~~~

Rendered marks keep their declaration order, so the line is painted after the
bars. Axes and chrome configure the panel rather than becoming data traces.
When more than one legend, tooltip, colorbar, modebar, theme, or interaction
node is present, the last node of that family supplies the effective settings.

## Choose a container

Family containers make a single-family chart easy to scan:

~~~python
chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [4, 2, 7]),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
)
~~~

Use neutral `chart()` when different mark kinds share one panel. Containers
such as `line_chart()`, `scatter_chart()`, and `bar_chart()` are compositional
conveniences, not separate rendering systems; all return the same `Chart`
interface. `facet_chart()` repeats a template over groups and returns a
`FacetChart` with grid-aware output methods.

## Component families

| Family | Responsibility |
| --- | --- |
| Containers | Layout, shared `data`, dimensions, callbacks, and output |
| Marks | Data geometry such as lines, points, bars, distributions, and grids |
| Axes | Scale type, domain, ticks, labels, side, and named-axis binding |
| Annotations | Rules, bands, thresholds, text, labels, arrows, and callouts |
| Chrome | Legends, tooltips, colorbars, and the modebar |
| Appearance | Themes, CSS/Tailwind slots, and rendered-mark styles |
| Behavior | `interaction_config()` and Reflex-shaped `on_*` callback props |

## Application behavior stays outside the tree

Callbacks use familiar `on_*` names—`on_hover`, `on_click`, `on_brush`,
`on_select`, and `on_view_change`—but XY does not define an application-state
system. A notebook widget can call Python; a host adapter such as Reflex maps
chart events into that framework's event model. Standalone HTML keeps local
browser interactions but has no Python process to call.

## Structure is declarative; data can be live

Adding or removing marks means composing a new chart. Existing trace data can
be extended with `chart.append(...)`, and `pick()` or `select_range()` can read
exact canonical rows. A live widget refreshes after an append; an already
exported HTML file remains a snapshot.

Every composed chart exposes `show()`, `widget()`, `to_html()`, `to_png()`,
`to_svg()`, and `memory_report()`. Continue with
[Data and columns](/docs/xy/core-concepts/data/) or browse the
[Gallery](/docs/xy/overview/gallery/).
