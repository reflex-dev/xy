---
title: Data and Columns
description: Bind arrays, mappings, DataFrames, Arrow columns, dates, and categories.
---

# Data and Columns

Marks accept values directly or string column names resolved through `data=`.
Put `data` on one mark when it is local to that mark, or on the chart when its
children share a table.

## Direct arrays

~~~python demo exec
import numpy as np
import xy

hours = np.linspace(0, 24, 288, endpoint=False)
temperature = (
    18
    + 5 * np.sin((hours - 7) * 2 * np.pi / 24)
    + 0.7 * np.sin(hours * 6 * np.pi / 24)
)
feels_like = temperature - 1.1 + 0.5 * np.cos(hours * 2 * np.pi / 24)

direct_array_chart = xy.line_chart(
    xy.area(
        hours,
        temperature,
        base=10,
        color="#8b5cf6",
        opacity=0.16,
        line_width=0,
        curve="smooth",
    ),
    xy.line(
        hours,
        temperature,
        name="Temperature",
        color="#7c3aed",
        width=2.5,
        curve="smooth",
    ),
    xy.line(
        hours,
        feels_like,
        name="Feels like",
        color="#0ea5e9",
        width=2,
        dash="dashed",
        curve="smooth",
    ),
    xy.x_axis(label="hour", domain=(0, 24), tick_count=7),
    xy.y_axis(label="temperature (°C)", domain=(10, 26), tick_count=5),
    xy.legend(loc="upper left"),
    title="One day of five-minute readings",
)


def direct_arrays_demo():
    import reflex_xy

    return reflex_xy.chart(direct_array_chart, height="360px")
~~~

Regular Python sequences and one-dimensional NumPy arrays use the same API.
Here, the three arrays bind directly to an area and two line marks; no table or
column lookup is required.
Coordinates must be real numeric, datetime-like, or categorical values that
the mark supports; boolean and complex coordinate columns are rejected rather
than silently coerced.

## Named columns

~~~python demo exec
campaign_data = {
    "spend_k": [
        12, 16, 20, 24, 28, 32, 36, 40, 44,
        48, 52, 56, 60, 64, 68, 72, 76, 80,
    ],
    "qualified_leads": [
        82, 105, 131, 118, 162, 179, 193, 221, 236,
        258, 249, 292, 318, 304, 347, 365, 352, 401,
    ],
    "channel": [
        "Search", "Social", "Partner", "Search", "Social", "Partner",
        "Search", "Social", "Partner", "Search", "Social", "Partner",
        "Search", "Social", "Partner", "Search", "Social", "Partner",
    ],
    "pipeline_k": [
        48, 55, 72, 64, 91, 103, 112, 135, 149,
        166, 158, 192, 211, 205, 238, 254, 246, 281,
    ],
}

# --- chart ---
import xy

named_column_chart = xy.scatter_chart(
    xy.scatter(
        x="spend_k",
        y="qualified_leads",
        color="channel",
        size="pipeline_k",
        size_range=(7, 24),
        opacity=0.78,
        stroke="#ffffff",
        stroke_width=1,
    ),
    xy.x_axis(label="campaign spend ($k)", domain=(8, 84), tick_count=6),
    xy.y_axis(label="qualified leads", domain=(60, 430), tick_count=6),
    xy.tooltip(
        title="{channel} campaign",
        fields=["spend_k", "qualified_leads", "pipeline_k"],
        format={
            "spend_k": "$,.0fK",
            "qualified_leads": ",.0f",
            "pipeline_k": "$,.0fK",
        },
    ),
    xy.legend(title="Channel", loc="upper left"),
    data=campaign_data,
    title="Campaign performance across 18 launches",
)


def named_columns_demo():
    import reflex_xy

    return reflex_xy.chart(named_column_chart, height="380px")
~~~

Dictionaries, pandas DataFrames, and other column-indexable objects work with
this pattern. The example resolves four named columns from one shared chart
table: spend and leads set position, channel sets categorical color, and
pipeline value sets bubble size. A mark-level `data=` overrides the chart
default for that mark. Numeric color values use a continuous colormap;
categorical values use a discrete palette.

## The canonical column store

XY converts numeric coordinates to contiguous float64 canonical columns in the
Python process. Derived float32, index, density, and decimated buffers are
rendering representations—not replacements for the source values. Reusing the
same NumPy array within a figure reuses the canonical column by array identity.

This separation lets `pick()`, hover, and selections map rendered geometry back
to exact source rows even when the visible result is decimated or aggregated.
Call `chart.memory_report()` to inspect canonical bytes, column lengths, null
counts, and copies paid during ingest.

## Arrow input and zero-copy cases

PyArrow is an optional input format, not an XY runtime dependency. Install it
separately (`uv add pyarrow` or `pip install pyarrow`) and pass an Array or
ChunkedArray directly:

~~~python demo exec
import xy

try:
    import pyarrow as pa
except ModuleNotFoundError:
    pa = None

batch_mb_values = [
    1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0,
    16.0, 20.0, 24.0, 32.0, 40.0, 48.0, 56.0, 64.0,
]
throughput_values = [
    95.0, 172.0, 238.0, 296.0, 388.0, 452.0, 501.0, 535.0,
    575.0, 604.0, 621.0, 642.0, 654.0, 660.0, 663.0, 665.0,
]
batch_mb = (
    pa.array(batch_mb_values, type=pa.float64())
    if pa is not None
    else batch_mb_values
)
throughput = (
    pa.array(throughput_values, type=pa.float64())
    if pa is not None
    else throughput_values
)

arrow_chart = xy.line_chart(
    xy.area(
        batch_mb,
        throughput,
        color="#6e56cf",
        opacity=0.18,
        line_width=0,
        curve="smooth",
    ),
    xy.line(
        batch_mb,
        throughput,
        color="#6e56cf",
        width=2.5,
        curve="smooth",
    ),
    xy.scatter(
        batch_mb,
        throughput,
        color="#6e56cf",
        size=7,
        opacity=1,
        stroke="#ffffff",
        stroke_width=1.5,
    ),
    xy.x_axis(label="batch size (MB)", domain=(0, 68), tick_count=7),
    xy.y_axis(label="throughput (MB/s)", domain=(0, 700), tick_count=6),
    title="Throughput by batch size",
)


def arrow_input_demo():
    import reflex_xy

    return reflex_xy.chart(arrow_chart, height="360px")
~~~

A null-free primitive float64 Arrow Array, or a one-chunk column with that
layout, can remain a read-only zero-copy view of its Arrow buffer. Integer
conversion, null materialization, temporal conversion, and combining multiple
chunks require counted copies. “Arrow support” therefore does not mean every
Arrow layout is zero-copy; unsupported string/dictionary coordinate arrays are
rejected by the numeric column store.

## Time handling

Python dates, datetimes, NumPy `datetime64`, and compatible pandas/Arrow time
columns select time-axis behavior automatically. Canonical time coordinates are
float64 milliseconds since the Unix epoch; `NaT` becomes a missing value. The
current contract does not preserve arbitrary nanosecond distinctions end to
end.

~~~python demo exec
import numpy as np
import xy

dates = np.arange("2026-07-01", "2026-07-22", dtype="datetime64[D]")
active_users = np.array(
    [
        1420, 1510, 1585, 1490, 1630, 1725, 1810,
        1760, 1845, np.nan, 1870, 1995, 2070, 2140,
        2055, 2110, 2190, 2260, 2185, 2240, 2325,
    ],
    dtype=float,
)

time_chart = xy.line_chart(
    xy.area(
        dates,
        active_users,
        base=1200,
        color="#0ea5e9",
        opacity=0.18,
        line_width=0,
        curve="smooth",
    ),
    xy.line(
        dates,
        active_users,
        color="#0284c7",
        width=2.5,
        curve="smooth",
    ),
    xy.scatter(
        dates,
        active_users,
        color="#38bdf8",
        size=6,
        stroke="#ffffff",
        stroke_width=1,
    ),
    xy.x_axis(label="day", format="%b %d", tick_count=7),
    xy.y_axis(label="daily active users", domain=(1200, 2400), tick_count=6),
    title="Daily activity with a reporting gap",
)


def time_handling_demo():
    import reflex_xy

    return reflex_xy.chart(time_chart, height="360px")
~~~

The datetime array selects a time scale automatically. The missing tenth value
creates the visible gap in the series without changing later row indices.
Missing numeric values break line/area runs or are omitted from point geometry,
while canonical row indices remain stable.

## Color strings

A valid CSS color such as `"rebeccapurple"`, `"#6e56cf"`, or
`"var(--accent)"` is a constant color. Another string is treated as a column
name and resolved through `data=`. A color-shaped typo raises its CSS validation
error instead of falling through to a misleading missing-column error.

Next, configure [Axes and scales](/docs/xy/core-concepts/axes-and-scales/) or
learn how the stored columns feed
[large-data representations](/docs/xy/core-concepts/large-data-and-performance/).
