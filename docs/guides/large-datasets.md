---
title: Large Datasets
description: Understand decimation, density aggregation, drilldown, and memory reporting.
---

# Large Datasets

XY keeps canonical columns in the Python process and selects a representation
appropriate for the visible result. Rendering cost is intended to track screen
resolution rather than raw row count.

## Representation Tiers

- Direct points and segments for small visible sets.
- Decimated line geometry for long ordered series.
- Density surfaces for point clouds whose markers would be sub-pixel.
- View-specific refinement after zooming or drilling into a smaller window.

~~~python
import numpy as np
import xy as fc

rng = np.random.default_rng(9)
x = rng.normal(size=1_000_000)
y = 0.4 * x + rng.normal(size=x.size)

chart = fc.scatter_chart(
    fc.scatter(x, y, density=None),
    width=1000,
    height=500,
)
~~~

Leave `density=None` for automatic selection. `True` forces a density overview;
`False` requests point rendering.

## Exact Readout

Aggregation changes visible geometry, not the canonical source store. Hover,
selection, `pick`, and `Selection` results can still resolve original rows.

## Inspect Memory

Call `chart.memory_report()` to inspect retained columns, shipped buffers, and
other chart allocations. This is useful when tuning many-chart dashboards or
long-running streaming sessions.

~~~md alert info
### Benchmark Claims

Performance depends on data shape, output dimensions, platform, and render
contract. Use XY's committed benchmark harness when making comparisons rather
than extrapolating from a single chart.
~~~
