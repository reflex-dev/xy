---
title: Tooltips in Python
description: Configure hover fields, title templates, numeric formats, and replacements.
components:
  - xy.tooltip
---

# Tooltips in Python

XY shows a built-in hover tooltip by default. With no tooltip component it
leads with the hovered series name when one is available, then reports the
available x/y values and encoded color or size values. Polar charts label the
radial row `r` and drop the numeric angle, which is layout rather than data.
Add `tooltip()` to choose fields, give source columns
readable labels, format values, supply a title template, hide the tooltip, or
register framework-rendered content.

## Default Hover Tooltip

With a bare `xy.tooltip()` (or none at all), hovering a point reports its x and
y values without any further configuration. A named mark uses its series name
as the tooltip title. On a polar chart the readout reports the values — series
name, radial value, and any color or size encoding — and leaves the numeric
angle out, since the cursor is already sitting on it. An authored spoke label
survives, so a radar category reads `power` rather than a number, and
`labels={"x": ...}` opts the angle back in formatted through the theta axis.
Explicit `title=` and `fields=` continue to control a customized readout.

~~~python demo exec
import reflex_xy
import xy

default_tooltip_chart = xy.scatter_chart(
    xy.scatter(
        [1, 2, 3, 4, 5, 6],
        [3.2, 4.1, 2.8, 5.0, 4.4, 5.6],
        color="#6e56cf",
        size=8,
    ),
    xy.tooltip(),
    xy.x_axis(label="trial"),
    xy.y_axis(label="score"),
    title="Hover any point",
)


def default_tooltip_demo():
    return reflex_xy.chart(default_tooltip_chart, height="320px")
~~~

## Choose Fields and Formats

Named source columns that feed x, y, color, size, or heatmap-value channels can
be used as tooltip fields:

~~~python demo exec
import reflex_xy
import xy

tooltip_fields_data = {
    "month": [1, 2, 3, 4],
    "revenue": [42_000, 47_000, 45_000, 53_000],
    "growth": [0.04, 0.12, 0.01, 0.18],
}

tooltip_fields_chart = xy.scatter_chart(
    xy.scatter(
        x="month",
        y="revenue",
        size="growth",
        data=tooltip_fields_data,
    ),
    xy.tooltip(
        fields=["revenue", "growth"],
        title="Month {month}",
        format={"revenue": ",.0f", "growth": ".1%"},
        labels={"revenue": "Revenue", "growth": "Growth"},
    ),
)


def tooltip_fields_demo():
    return reflex_xy.chart(tooltip_fields_chart, height="320px")
~~~

Braced field names in `title` are replaced from the hovered row. `format` maps
source field names to the client's numeric format strings, while `labels` maps
those same source names to presentation text. Labels never change title
placeholder lookup or the event payload. When `fields` is omitted, `labels`
renames the matching default x/y/color/size rows; direct array channels can use
the channel names `"x"`, `"y"`, `"color"`, and `"size"`. A source column that
is not bound to a rendered channel is not shipped merely because its name
appears in `fields`.

### Title Templates Across Multiple Series

One tooltip configuration serves every mark in the chart: the braced `{day}`
title, the field selection, and the per-field number formats apply to both the
dashed forecast line and the margin-sized revenue points below.

~~~python demo exec
import reflex_xy
import xy

tooltip_title_data = {
    "day": [1, 2, 3, 4, 5],
    "revenue": [1450, 1720, 1610, 1980, 2240],
    "forecast": [1500, 1650, 1750, 1900, 2100],
    "margin": [0.21, 0.24, 0.19, 0.27, 0.31],
}

tooltip_title_chart = xy.line_chart(
    xy.line(
        x="day",
        y="forecast",
        data=tooltip_title_data,
        name="Forecast",
        color="#94a3b8",
        dash="dashed",
    ),
    xy.scatter(
        x="day",
        y="revenue",
        size="margin",
        data=tooltip_title_data,
        name="Revenue",
        color="#6e56cf",
    ),
    xy.tooltip(
        title="Day {day}",
        fields=["revenue", "forecast", "margin"],
        format={"revenue": ",.0f", "forecast": ",.0f", "margin": ".1%"},
    ),
    xy.legend(loc="upper left"),
    title="Daily revenue vs forecast",
)


def tooltip_title_demo():
    return reflex_xy.chart(tooltip_title_chart, height="320px")
~~~

## Exact and Resident Readout

Standalone HTML composes tooltips from the values resident in its payload.
With a live notebook or framework transport, an immediate client readout can be
replaced by exact canonical f64 values from Python. The `on_hover` callback
receives that exact row rather than tooltip text.

## Hide, Style, or Replace

Use `show=False` to disable built-in tooltips. `class_name` and `style` target
the tooltip container. Chart-level `class_names` and `styles` can target the
container plus `tooltip_title`, `tooltip_row`, `tooltip_label`, and
`tooltip_value`, so field labels and values can be aligned or styled
independently:

~~~python
chart = xy.scatter_chart(
    xy.scatter(x="month", y="revenue", data=tooltip_fields_data),
    xy.tooltip(
        fields=["revenue"],
        labels={"revenue": "Revenue"},
        format={"revenue": "$,.0f"},
    ),
    styles={
        "tooltip_row": {
            "display": "grid",
            "grid_template_columns": "7rem 1fr",
            "gap": 8,
        },
        "tooltip_label": {"color": "#94a3b8"},
        "tooltip_value": {"font_weight": 700, "text_align": "right"},
    },
)
~~~

All label and value strings are inserted as text, never parsed as HTML. The
last tooltip component supplies the effective configuration.

A positional child or `render=` object is kept opaque to the core renderer and
can be retrieved through `chart.chrome_components()`. It is not embedded into
standalone HTML. For a Chart source, the shipped `reflex_xy.chart` adapter
mounts `xy.tooltip(render=...)` automatically in the renderer-owned tooltip
slot; for a live figure token, pass the Reflex component through
`reflex_xy.chart(..., tooltip=...)`. The adapter suppresses the built-in
tooltip while the component is mounted and supplies hover data through the
normal event path. See
[Customize Each Part](/docs/xy/styling/customize/#tooltip) for the complete
integration boundary.

See [Events and callbacks](/docs/xy/api-reference/events-and-callbacks/) for
hover payloads and [Marks and components reference](/docs/xy/api-reference/marks-and-components/)
for the exact tooltip signature.

## FAQ

### How do I show values on hover in a Python chart?

XY shows a built-in hover tooltip by default — with no configuration it reports
the available x/y values plus any encoded color or size values. Add
`xy.tooltip()` as a chart child only when you want to choose fields, formats,
or a title template.

### How do I customize which fields a tooltip shows and how numbers are formatted?

Pass `fields=` and `format=` to `xy.tooltip()`, e.g.
`xy.tooltip(fields=["revenue", "growth"], labels={"revenue": "Revenue", "growth": "Growth"}, format={"revenue": ",.0f", "growth": ".1%"})`.
Only source columns bound to a rendered channel (x, y, color, size, or
heatmap value) can be used as tooltip fields.

### How do I put data values in the tooltip title?

Use braced field names in `title=`, e.g. `xy.tooltip(title="Month {month}")` —
each placeholder is replaced with the value from the hovered row.

### How do I disable tooltips on a chart?

Add `xy.tooltip(show=False)` to the chart. When several tooltip components are
present, the last one supplies the effective configuration, so a final
`show=False` wins.
