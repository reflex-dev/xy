---
title: Wind Rose Charts in Python
description: Create wind rose charts in Python with xy. Bin compass bearings into sectors and stack directional frequencies by speed band.
components:
  - xy.wind_rose
---

# Wind Rose Charts in Python

A **wind rose** summarizes how often observations arrive from each compass
direction and how those observations are distributed across speed bands. XY
bins the raw direction/speed pairs in Python and renders the result as stacked
polar bars.

Use `wind_rose()` when you have one bearing and one magnitude per observation.
If the directional counts are already aggregated, use a
[radial bar chart](/docs/xy/charts/radial-bar-chart/) instead.

## Create a Wind Rose

Directions are compass bearings in degrees: 0° is north and values increase
clockwise. The helper applies that convention automatically:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng = np.random.default_rng(14)
wind_direction = np.mod(
    np.concatenate(
        [
            rng.normal(35.0, 28.0, 260),
            rng.normal(225.0, 38.0, 180),
        ]
    ),
    360.0,
)
wind_speed = np.clip(rng.gamma(shape=2.4, scale=2.1, size=440), 0.2, 11.8)

rose = xy.wind_rose(
    wind_direction,
    wind_speed,
    sectors=16,
    speed_bins=(2, 4, 6, 8, 12),
    title="Wind frequency by direction and speed",
)


def wind_rose_demo():
    return reflex_xy.chart(rose, height="440px")
~~~

Each stacked color band counts observations whose speed is above the previous
edge and at or below the current edge. The legend labels show those inclusive
upper edges.

## Choose Directional Sectors

`sectors=` controls the number of equally sized angular bins and must be at
least 3. Each bin is centered on its compass bearing, so a value of exactly 0°
belongs to the sector centered on north. Bearings outside `0..360` wrap around
the circle.

More sectors reveal directional detail but need more observations to keep each
bin stable. Common choices are 8, 12, 16, or 36 sectors, depending on sample
size and the directional resolution of the source.

## Configure Speed Bands

Pass increasing upper edges through `speed_bins=`:

~~~python
rose = xy.wind_rose(
    directions,
    speeds,
    sectors=16,
    speed_bins=(2, 4, 6, 8, 12),
)
~~~

The final edge should cover the fastest observation; values above it do not
belong to a displayed band. XY removes duplicate edges and orders the remaining
values. When `speed_bins` is omitted, it derives up to four readable bands from
the speed quartiles and rounds the top edge upward so every finite observation
is covered.

## Follow the Input Contract

- `directions` and `speeds` must have the same length.
- Each pair describes one observation.
- Non-finite pairs are dropped together.
- At least one finite pair must remain.
- `sectors` must be 3 or greater.
- `speed_bins` must contain at least one edge when supplied.

XY raises `ValueError` for mismatched arrays, an empty finite dataset, too few
sectors, or an empty band definition.

## Read and Style the Result

The radial value is a count, not a speed. Each speed band becomes one stacked
bar series and takes the next chart palette color. Pass chart keyword props
such as `title`, `width`, `height`, `padding`, `class_names`, and `styles` through
`wind_rose()`.

The helper authors a degree-based theta axis with north at zero and clockwise
rotation, plus an r axis labeled `count`. Build the equivalent sectors manually
with `polar_bar_chart()` when you need custom pre-binning, non-count radial
values, a different angular convention, or component children such as
`xy.theme()`, `xy.legend()`, and `xy.modebar()`.

## Interaction and Export

Wind roses support hover, fixed-minimum radial zoom, reset, and browser/static
export through the shared polar renderer. Theta rotation, box zoom, selection,
brushing, and crosshairs are not available.

See the [polar overview](/docs/xy/charts/polar-chart/) for the full interaction,
renderer, annotation, and large-data boundary.

## Related Polar Charts

- [Polar overview](/docs/xy/charts/polar-chart/) — numeric theta/r data and
  shared polar axes.
- [Radial bar charts](/docs/xy/charts/radial-bar-chart/) — pre-aggregated
  annular sectors.
- [Pie and donut charts](/docs/xy/charts/pie-chart/) — share, progress-ring,
  revenue-mix, and gauge blocks.
- [Radar charts](/docs/xy/charts/radar-chart/) — category profiles rather than
  directional frequencies.

## FAQ

### Are wind directions radians or degrees?

`wind_rose()` always accepts compass bearings in degrees. It applies north-zero,
clockwise theta settings automatically.

### What happens when I omit `speed_bins`?

XY derives up to four bands from the finite speed quartiles and rounds the final
edge upward to include the maximum observation.

### Why are some observations missing?

Non-finite direction/speed pairs are dropped. With authored `speed_bins`, make
sure the final upper edge covers the fastest finite observation.
