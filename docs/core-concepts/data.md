---
title: Data and Columns
description: Bind arrays, mappings, DataFrames, dates, and categorical values.
---

# Data and Columns

Marks accept arrays directly or string column names resolved through `data`.
Put `data` on an individual mark or once on the chart as a default.

## Direct Arrays

~~~python
import numpy as np
import xy as fc

x = np.linspace(0, 10, 200)
y = np.sin(x)

chart = fc.line_chart(fc.line(x, y))
~~~

## Named Columns

~~~python
import xy as fc

data = {
    "x": [1, 2, 3, 4],
    "y": [4, 7, 5, 9],
    "segment": ["A", "A", "B", "B"],
    "weight": [2, 4, 3, 7],
}

chart = fc.scatter_chart(
    fc.scatter(x="x", y="y", color="segment", size="weight"),
    data=data,
)
~~~

The same pattern works with pandas DataFrames and other objects supporting
column lookup. `color` is auto-typed: numeric values use a continuous colormap,
while categorical values use a discrete palette.

## Supported Coordinate Types

- Numeric sequences and NumPy arrays.
- Date and datetime values, with automatic time axes.
- Strings and other common categories, with stable categorical positions.
- Missing numeric values, which break lines or are omitted from point geometry.

XY stores canonical numeric columns in Python and ships compact typed buffers
to the renderer. Interactive selections can therefore map back to exact source
rows even when the visible representation is decimated or aggregated.

~~~md alert info
### Color Strings

A valid CSS color such as `"rebeccapurple"`, `"#6e56cf"`, or
`"var(--accent)"` is treated as a constant. Other strings are resolved as data
column names.
~~~
