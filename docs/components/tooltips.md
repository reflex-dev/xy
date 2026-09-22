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
source field names to format strings — numeric specs such as `",.0f"` and
`".1%"`, or strftime patterns such as `"%b %d, %Y"` on date and time values
(see [Time and Date Values](#time-and-date-values)) — while `labels` maps those
same source names to presentation text. Labels never change title
placeholder lookup or the event payload. When `fields` is omitted, `labels`
renames the matching default x/y/color/size rows; direct array channels can use
the channel names `"x"`, `"y"`, `"color"`, and `"size"`. A source column that
is not bound to a rendered channel is not shipped merely because its name
appears in `fields`.

### Time and Date Values

A datetime column formats with a strftime pattern in the same `format=` map.
The tokens are `%Y %m %d %H %M %S %b %B`, the set the axis labels use:

~~~python demo exec
import datetime

import reflex_xy
import xy

tooltip_time_start = datetime.datetime(2026, 9, 17, 10, 0)
tooltip_time_data = {
    "time": [tooltip_time_start + datetime.timedelta(hours=6 * i) for i in range(16)],
    "yes": [0.41, 0.44, 0.43, 0.47, 0.52, 0.55, 0.53, 0.58,
            0.61, 0.59, 0.64, 0.68, 0.66, 0.71, 0.74, 0.72],
}

tooltip_time_chart = xy.line_chart(
    xy.line(x="time", y="yes", data=tooltip_time_data, name="Yes"),
    xy.tooltip(
        mode="x",
        format={"time": "%b %d, %Y, %H:%M", "yes": ".0%"},
        labels={"yes": "Yes"},
    ),
)


def tooltip_time_demo():
    return reflex_xy.chart(tooltip_time_chart, height="320px")
~~~

With no `format=` for a time field, the tooltip does not fall back to a raw
timestamp. It uses the axis's own `format=` when the axis has one, so the
tooltip and the tick labels beneath it read alike; otherwise it picks the
pattern the visible span reads best in — `Sep 17, 2026` for a window of months,
`Sep 17, 10:05` for one of hours or days, `10:05:00` for one of seconds. Zoom
in and the tooltip sharpens with the axis. Below a second the ISO timestamp
stays, because it is the only form that carries milliseconds.

Because the format is chosen per field, one chart can carry a precise
timestamp in the tooltip and short labels on the axis:

~~~python
xy.x_axis(format="%b %d")                       # axis: Sep 17
xy.tooltip(format={"time": "%b %d, %Y, %H:%M"})  # tooltip: Sep 17, 2026, 10:05
~~~

`format=` works on its own — without `fields=` or `title=` — in which case it
formats the default x/y/color/size rows in place.

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

## Shared Tooltip Along an Axis

`xy.tooltip(mode="x")` turns the tooltip into an axis tooltip, the model
Recharts uses by default and Plotly calls `hovermode="x unified"`. The pointer
only has to be inside the plot: its horizontal position snaps to the nearest x
value and every series' point at that x is listed at once, while the vertical
position is ignored. The plot divides into full-height bands with boundaries
halfway between adjacent points, a cursor line marks the selected x, each series
shows an active dot, and the tooltip follows the pointer. Bars join by their
footprint: a grouped bar chart lists every series of the category under the
pointer, with one cursor on the category centre. `mode="y"` does the same along
the y axis for horizontal layouts. The default, `mode="nearest"`,
keeps the 12 px nearest-point behavior.

~~~python demo exec
import reflex_xy
import xy

pages = ["Page A", "Page B", "Page C", "Page D", "Page E", "Page F", "Page G"]
shared_tooltip_chart = xy.line_chart(
    xy.line(pages, [2400, 1398, 9800, 3908, 4800, 3800, 4300], name="pv", color="#8884d8", width=2),
    xy.line(pages, [4000, 3000, 2000, 2780, 1890, 2390, 3490], name="uv", color="#82ca9d", width=2),
    xy.tooltip(mode="x"),
    xy.legend(loc="upper right"),
    title="Hover anywhere above a page",
)


def shared_tooltip_demo():
    return reflex_xy.chart(shared_tooltip_chart, height="320px")
~~~

`fields=`, `format=`, and `title=` keep their meaning: the title template
resolves against the first series' row, and each series row shows the
requested fields (minus the band axis, which is already the title). Style the
cursor line through the `tooltip_cursor` slot or the `--chart-crosshair`
token it shares with the crosshair.

## FAQ

### How do I show values on hover in a Python chart?

XY shows a built-in hover tooltip by default — with no configuration it reports
the available x/y values plus any encoded color or size values. Add
`xy.tooltip()` as a chart child only when you want to choose fields, formats,
or a title template.

### How do I show a formatted date or time in a tooltip?

Pass a strftime pattern for that column, e.g.
`xy.tooltip(format={"time": "%b %d, %Y, %H:%M"})`. It applies wherever the value
appears — a field row, a `title=` placeholder, or the band title under
`mode="x"`. With nothing passed, a time value follows the axis `format=` if
there is one, and otherwise the visible span. See
[Time and Date Values](#time-and-date-values).

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
