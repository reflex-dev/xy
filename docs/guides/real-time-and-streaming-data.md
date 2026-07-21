---
title: Real-Time and Streaming Data
description: Append points, update live widgets, inspect exact rows, and understand snapshots.
---

# Real-Time and Streaming Data

A composed chart's data plane can change without rebuilding its component
structure. Marks and axes remain declarative; appended rows extend an existing
line or scatter trace.

~~~python
import xy

chart = xy.scatter_chart(
    xy.scatter([0.0, 1.0, 2.0], [0.0, 2.0, 4.0], name="stream"),
    xy.animation(match="append", duration=220),
    xy.x_axis(label="time"),
    xy.y_axis(label="value"),
)

chart.append(0, [3.0, 4.0], [6.0, 8.0])

row = chart.pick(0, 4)
assert row["x"] == 4.0

selection = chart.select_range(0.5, 3.5, 0.0, 10.0)
xs, ys = selection.xy(0)
~~~

Trace IDs follow rendered mark order, with one ID per rendered series.
Appending validates the trace kind, coordinate lengths and ordering, and any
per-point color or size channel tails. A failed append raises before committing
a partial update.

When an `animation()` child is present, the live browser matches retained x
values and transitions the appended tail without changing the follow policy.
See [Animations and data transitions](/docs/xy/core-concepts/animations/) for
keyed replacement, interruption, reduced motion, and large-data fallback.

For ordered line traces, new x values must continue the series in ascending
order. Build a new chart when changing component structure, adding marks, or
replacing a dataset rather than extending it.

## Live and Headless Lifecycles

- If a live notebook widget already exists, `chart.append(...)` mutates the
  canonical store, sends a screen-bounded refresh, and synchronizes the widget
  state used by a later display.
- Without a widget, the chart mutates in Python and the next `widget()`,
  `to_html()`, `to_png()`, or `to_svg()` sees the appended rows.
- In Reflex, call `reflex_xy.append(token, ...)` for a registered live chart.
  See the [Reflex integration](/docs/xy/integrations/reflex/).

~~~md alert warning
### Exports Are Snapshots

An HTML, PNG, or SVG file captures the chart state at export time. An already
exported standalone file has no Python process and does not receive later
appends. Export again when a consumer needs a newer snapshot.
~~~

## Exact Readout and Selection

Aggregation changes visible geometry, not the canonical source store.
`pick(trace_id, index)` resolves a shipped point back to its original row.
`Selection` stores canonical row indices per trace, supports
`len(selection)`, and exposes selected coordinates through `xy(trace_id)`.

Long-running streams retain canonical data. Use `chart.memory_report()` to
inspect columns, shipped buffers, and other allocations, and choose an
application-level retention or windowing policy when history is unbounded.
