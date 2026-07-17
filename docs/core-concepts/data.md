---
title: Data and Columns
description: Bind arrays, mappings, DataFrames, Arrow columns, dates, and categories.
---

# Data and Columns

Marks accept values directly or string column names resolved through `data=`.
Put `data` on one mark when it is local to that mark, or on the chart when its
children share a table.

## Direct arrays

~~~python
import numpy as np
import xy

x = np.linspace(0, 10, 200)
y = np.sin(x)

chart = xy.line_chart(xy.line(x, y))
~~~

Regular Python sequences and one-dimensional NumPy arrays use the same API.
Coordinates must be real numeric, datetime-like, or categorical values that
the mark supports; boolean and complex coordinate columns are rejected rather
than silently coerced.

## Named columns

~~~python
import xy

data = {
    "x": [1, 2, 3, 4],
    "y": [4, 7, 5, 9],
    "segment": ["A", "A", "B", "B"],
    "weight": [2, 4, 3, 7],
}

chart = xy.scatter_chart(
    xy.scatter(x="x", y="y", color="segment", size="weight"),
    data=data,
)
~~~

Dictionaries, pandas DataFrames, and other column-indexable objects work with
this pattern. A mark-level `data=` overrides the chart default for that mark.
Numeric color values use a continuous colormap; categorical values use a
discrete palette.

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

~~~python
import pyarrow as pa
import xy

x = pa.array([1.0, 2.0, 3.0])
y = pa.array([3.0, 5.0, 4.0])
chart = xy.scatter_chart(xy.scatter(x, y))
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

~~~python
import numpy as np
import xy

time = np.array(
    ["2026-07-01", "2026-07-02", "2026-07-03"],
    dtype="datetime64[D]",
)
chart = xy.line_chart(
    xy.line(time, [12, 18, 15]),
    xy.x_axis(label="day", type_="time"),
)
~~~

Missing numeric values break line/area runs or are omitted from point geometry,
while canonical row indices remain stable.

~~~md alert info
### Color strings

A valid CSS color such as `"rebeccapurple"`, `"#6e56cf"`, or
`"var(--accent)"` is a constant color. Another string is treated as a column
name and resolved through `data=`. A color-shaped typo raises its CSS validation
error instead of falling through to a misleading missing-column error.
~~~

Next, configure [Axes and scales](/docs/xy/core-concepts/axes-and-scales/) or
learn how the stored columns feed
[large-data representations](/docs/xy/core-concepts/large-data-and-performance/).
