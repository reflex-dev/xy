---
title: Wind Rose Charts in Python
description: Create wind rose charts in Python with xy. Bin compass bearings into sectors and stack directional frequencies by speed band.
components:
  - xy.wind_rose
---

# Wind Rose Charts in Python

A **wind rose** (also called a wind rose chart, wind rose plot, or wind rose
diagram) summarizes
how often observations arrive from each compass direction and how those
observations are distributed across speed bands. XY bins the raw direction/speed
pairs in Python and renders the result as stacked polar bars.

Use `wind_rose()` when you have one bearing and one magnitude per observation.
If the directional counts are already aggregated, use a
[radial bar chart](/docs/xy/charts/radial-bar-chart/) instead.

Jump to [directional sectors](#choose-directional-sectors),
[speed bands](#configure-speed-bands), or
[the input contract](#follow-the-input-contract).

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

## Set Sector Count and Band Edges Together

Lower the sector count when the sample is small or the source records only the
eight principal bearings, and pass matching band edges so each petal stays thick
enough to read:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

coarse_rng = np.random.default_rng(7)
coarse_directions = np.mod(coarse_rng.normal(270.0, 45.0, 500), 360.0)
coarse_speeds = np.clip(coarse_rng.gamma(shape=2.0, scale=3.0, size=500), 0.3, 17.0)

coarse_rose = xy.wind_rose(
    coarse_directions,
    coarse_speeds,
    sectors=8,
    speed_bins=[3, 6, 9, 12, 18],
    title="Eight-sector wind rose",
)


def wind_rose_sectors_demo():
    return reflex_xy.chart(coarse_rose, height="440px")
~~~

## Plot a Full Year of Observations

With thousands of records a high sector count resolves the prevailing wind, and
narrow speed bands separate calm air from gales — add `xy.legend()` to place the
band labels where you want them:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

met_rng = np.random.default_rng(2024)
met_directions = np.mod(
    np.concatenate(
        [
            met_rng.normal(240.0, 22.0, 5200),
            met_rng.normal(60.0, 40.0, 1800),
            met_rng.uniform(0.0, 360.0, 1000),
        ]
    ),
    360.0,
)
met_speeds = np.clip(met_rng.weibull(2.0, 8000) * 7.5, 0.2, 28.0)

annual_rose = xy.wind_rose(
    met_directions,
    met_speeds,
    xy.legend(loc="right", title="speed (m/s)"),
    sectors=32,
    speed_bins=[2, 4, 6, 8, 11, 14, 18, 25],
    title="Wind rose, 8,000 hourly observations",
)


def wind_rose_annual_demo():
    return reflex_xy.chart(annual_rose, height="440px")
~~~

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

A wind rose is the one polar chart that keeps zoom **on** by default. Its radius
is a frequency count, so pulling the outer ring in magnifies the short sectors of
a rose dominated by one prevailing direction; the radial minimum stays pinned at
zero, so the disc never becomes an annulus.

Every other polar chart type defaults to zoom off — not because its radius can
never be data, but because a fixed center means radial zoom crops the rim rather
than navigating the chart, and that is the wrong default for the compositions
built on a constant rim or a fixed frame. A `polar_chart()` carrying measured
radial values is exactly the case to
[opt back in](/docs/xy/charts/polar-chart/#enable-zoom-on-a-polar-chart). Pass
`xy.interaction_config(zoom=False)` to opt a rose out — for instance when it is
embedded in a scrolling page and should not capture the wheel.

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

Non-finite direction/speed pairs are dropped before the wind rose graph is
binned. With authored `speed_bins`, make sure the final upper edge covers the
fastest finite observation.
