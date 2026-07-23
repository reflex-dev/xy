---
title: Large Data and Performance
description: Understand direct rendering, M4 decimation, density aggregation, drilldown, and memory.
---

# Large Data and Performance

XY keeps exact canonical columns in Python and chooses a rendered
representation for each trace. The goal is to keep transport and draw work
bounded by what the viewport can distinguish while retaining exact rows for
readout and refinement.

## The representation ladder

| Representation | Used for | What reaches the renderer |
| --- | --- | --- |
| Direct | Small visible traces | One rendered point or segment per retained row |
| M4-decimated | Long ordered lines and areas | A bounded sequence preserving per-bucket extrema |
| Density | Dense scatter overviews | A fixed-resolution count grid wearing the data's own mean point colors; a deterministic point sample overlays it only when the view's estimated count would fit the direct budget (individual points are resolvable) |
| Refined view | A narrower pan/zoom window | A new viewport-specific aggregate, or exact visible points for a padded aligned window when they fit — nearby pans and zooms then render from the cached window with no further requests |

The current defaults begin M4 line decimation above 10,000 rows and automatic
scatter density above 200,000 points. Density grids default to 512×384 cells,
and very large density traces can build a lazy multiresolution pyramid for
viewport queries. These are pre-1.0 policy thresholds, not API guarantees;
write code against the behavior and recorded `tier`, not a hard-coded count.

## Automatic versus explicit density

~~~python demo exec
import numpy as np
import xy

rng = np.random.default_rng(9)
x = rng.normal(size=1_000_000)
y = 0.4 * x + rng.normal(size=x.size)

chart = xy.scatter_chart(
    xy.scatter(x, y, density=None),
    width=1000,
    height=500,
)


def automatic_density_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="420px")
~~~

- `density=None` chooses automatically and is the normal large-data setting.
- `density=True` requests a density overview explicitly.
- `density=False` forces direct points. Above the soft ceiling XY warns about
  fill-rate and allocation risk, but honors the explicit opt-out.

Density aggregation is computed by the native core and rendered as a compact
WebGL texture. Calling it “GPU density” would blur those two stages: the GPU
draws the result, while the source-row binning happens before that draw.

## Exactness under reduction

Reduction changes visible geometry, not the canonical source store. Hover,
selection, `pick()`, and drilldown resolve source rows when the active tier has
an exact mapping. When a dense view cannot support exact per-marker semantics,
XY exposes its aggregate/sample representation rather than pretending that a
bin is an individual row.

Line decimation preserves extrema for the visible buckets, but it does not
claim that every intermediate vertex is drawn. A narrow view is re-decimated
against its own window.

## The performance model

There are two different scaling regimes:

1. Ingest, validation, range scans, binning, and decimation inspect source data
   and therefore retain row-dependent work.
2. The resulting wire payload, WebGL geometry, and static SVG/native-PNG scene
   are bounded by the chosen viewport representation.

This is why a “cost scales with pixels, not points” slogan needs qualification:
it describes the output side after reduction, not the complete data-to-pixels
pipeline.

## Inspect memory and tier decisions

~~~python demo exec
report = chart.memory_report()
print(report["canonical_bytes"])
for column in report["columns"]:
    print(column["len"], column["bytes"], column["ingest_copies"])


def memory_report_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="420px")
~~~

Tier decisions are also recorded in the built payload rather than being
silent. Use the memory report for many-chart dashboards and long-running append
workloads, and use the committed benchmark harness before publishing a
performance comparison.

See the [benchmark snapshot](/docs/xy/overview/benchmarks/) for a measured
example, or [Interactions and selections](/docs/xy/core-concepts/interactions/)
for exact readout behavior.
