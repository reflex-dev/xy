---
title: Tooltips
description: Configure hover fields, title templates, numeric formats, and replacements.
---

# Tooltips

XY shows a built-in hover tooltip by default. With no tooltip component it
reports the available x/y values and encoded color or size values. Add
`tooltip()` to choose fields, format values, supply a title template, hide the
tooltip, or register framework-rendered content.

## Choose Fields and Formats

Named source columns that feed x, y, color, size, or heatmap-value channels can
be used as tooltip fields:

~~~python
import xy

data = {
    "month": [1, 2, 3, 4],
    "revenue": [42_000, 47_000, 45_000, 53_000],
    "growth": [0.04, 0.12, 0.01, 0.18],
}

chart = xy.scatter_chart(
    xy.scatter(
        x="month",
        y="revenue",
        size="growth",
        data=data,
    ),
    xy.tooltip(
        fields=["revenue", "growth"],
        title="Month {month}",
        format={"revenue": ",.0f", "growth": ".1%"},
    ),
)
~~~

Braced field names in `title` are replaced from the hovered row. `format` maps
field names to the client's numeric format strings. A source column that is not
bound to a rendered channel is not shipped merely because its name appears in
`fields`.

## Exact and Resident Readout

Standalone HTML composes tooltips from the values resident in its payload.
With a live notebook or framework transport, an immediate client readout can be
replaced by exact canonical f64 values from Python. The `on_hover` callback
receives that exact row rather than tooltip text.

## Hide, Style, or Replace

Use `show=False` to disable built-in tooltips. `class_name` and `style` target
the tooltip container; chart-level slot styling can target `tooltip` as well.
The last tooltip component supplies the effective configuration.

Like legends, a positional child or `render=` object is kept opaque for an
adapter and can be retrieved through `chart.chrome_components()`. It is not
embedded into standalone HTML, and the shipped `reflex_xy.chart` adapter does
not mount it. With that adapter, disable the built-in tooltip, handle
`on_point_hover` in Reflex state, and render the framework-owned tooltip beside
or over the chart. See [Customize Each Part](/docs/xy/styling/customize/#tooltip)
for the complete integration boundary.

See [Events and callbacks](/docs/xy/api-reference/events-and-callbacks/) for
hover payloads and [Marks and components reference](/docs/xy/api-reference/marks-and-components/)
for the exact tooltip signature.
