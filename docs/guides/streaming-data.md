---
title: Streaming Data
description: Append points, read exact rows, and select data from Python.
---

# Streaming Data

A composed chart's data plane can change without rebuilding its component
structure. Marks and axes remain declarative; appended rows extend an existing
trace.

~~~python
import xy as fc

chart = fc.scatter_chart(
    fc.scatter([0.0, 1.0, 2.0], [0.0, 2.0, 4.0], name="stream"),
    fc.x_axis(label="time"),
    fc.y_axis(label="value"),
)

chart.append(0, [3.0, 4.0], [6.0, 8.0])

row = chart.pick(0, 4)
assert row["x"] == 4.0

selection = chart.select_range(0.5, 3.5, 0.0, 10.0)
xs, ys = selection.xy(0)
~~~

Trace IDs follow rendered mark order. Appending validates the mark kind,
coordinate ordering, and any color or size channel tails. A live widget updates
its browser client; without a widget, the next `widget()` or export uses the
mutated state.

Already-exported standalone HTML is a snapshot and does not receive later
Python appends.

`Selection` stores canonical row indices per trace, supports `len(selection)`,
and exposes selected coordinates through `xy(trace_id)`.
