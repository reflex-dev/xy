---
title: Polar Charts in Python
description: Create polar charts and polar plots in Python with xy. Configure sectors, categorical angles, holes, log radii, and pyplot polar projections.
components:
  - xy.polar_chart
  - xy.theta_axis
  - xy.r_axis
---

# Polar Charts in Python

A **polar chart** (also called a polar plot or polar graph) places each
observation by an angle (theta, or θ) and a
distance from the center (radius, or r). It is a natural fit for cyclic
measurements, directional observations, antenna patterns, radar comparisons,
and wind distributions.

Jump to [a polar line chart](#create-a-polar-line-chart),
[the angular axis](#configure-the-angular-axis), or
[supported marks and limits](#supported-marks-and-current-limits).

XY uses the same composition model as its Cartesian charts. Put `line`,
`scatter`, `area`, `bar`, `column`, `heatmap`, `contour`, or `errorbar` marks
inside `polar_chart()`. Focused helpers build
[radar](/docs/xy/charts/radar-chart/),
[radial bar](/docs/xy/charts/radial-bar-chart/), and
[wind rose](/docs/xy/charts/wind-rose/) charts on the same coordinate system.

## Create a Polar Line Chart

The first mark channel becomes θ and the second becomes r. Angles use radians
by default:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

theta = np.linspace(0.0, 2.0 * np.pi, 361)
radius = 1.0 + 0.28 * np.cos(5.0 * theta) + 0.12 * np.sin(2.0 * theta)

polar_line = xy.polar_chart(
    xy.line(theta, radius, color="#6e56cf", width=2.5),
    xy.scatter(
        theta[::18],
        radius[::18],
        color="#2563eb",
        size=5,
        stroke="#ffffff",
        stroke_width=1,
    ),
    xy.theta_axis(unit="radians"),
    xy.r_axis(label="relative magnitude", domain=(0.0, 1.5)),
    title="Five-lobe response",
)


def polar_line_demo():
    return reflex_xy.chart(polar_line, height="420px")
~~~

Without an authored sector, `polar_chart()` draws a full circular frame. Its
angular axis defaults to `0..2π`, and a linear radial axis starts at zero and
ends at the largest radius. Pass `domain=` to `r_axis()` when the radial view
must stay fixed.

## Map a Polar Field

Heatmap cells follow rings and spokes rather than stretching a Cartesian image
into a circle. Contours share that projection, so they can be layered over the
field with one colorbar:

~~~python demo exec
import math

import numpy as np
import reflex_xy
import xy

field_theta = np.linspace(0.0, 360.0, 24, endpoint=False)
field_radius = np.geomspace(1.0, 100.0, 8)
field = np.array(
    [
        [
            math.sin(3.0 * math.radians(angle)) + math.cos(1.7 * math.log(radius))
            for angle in field_theta
        ]
        for radius in field_radius
    ]
)

polar_field = xy.polar_chart(
    xy.heatmap(
        field,
        x=field_theta,
        y=field_radius,
        colormap="viridis",
        name="surface",
    ),
    xy.contour(
        field,
        x=field_theta,
        y=field_radius,
        levels=6,
        color="#ffffff",
        width=1.4,
        name="isolines",
    ),
    xy.colorbar(title="surface"),
    xy.theta_axis(unit="degrees"),
    xy.r_axis(type_="log", domain=(1.0, 100.0)),
    title="Polar field with isolines",
)


def polar_field_demo():
    return reflex_xy.chart(polar_field, height="440px")
~~~

The polar heatmap path inverse-samples the source grid at the requested
browser or export resolution. Pixels inside a hole or outside an authored
sector stay transparent. Contours remain projected vector geometry.

## Choose a Polar Chart Type

The overview owns numeric theta/r data and shared coordinate-system behavior.
Use a focused page when the data already matches one of these higher-level
compositions.

### Compare Categories with a Radar Chart

[Radar charts](/docs/xy/charts/radar-chart/) space named dimensions evenly
around the frame and close filled or outlined profiles automatically.

### Draw Radial Bars

[Radial bar charts](/docs/xy/charts/radial-bar-chart/) turn bars into annular
sectors with scalar or per-item angular widths and configurable inner radii.

### Compose a Pie or Donut

The [pie and donut guide](/docs/xy/charts/pie-chart/) turns unequal-width
sectors and `base=` into polished share, progress-ring, revenue-mix, and gauge
blocks.

### Summarize Wind with a Wind Rose

[Wind rose charts](/docs/xy/charts/wind-rose/) bin raw compass bearings into
directional sectors and stack their counts by speed band.

## Configure the Angular Axis

`theta_axis()` accepts the ordinary `x_axis()` options for labels, ticks,
formatting, and styling, plus five polar settings:

| Option | Values | Default |
| --- | --- | --- |
| `unit` | `"radians"` or `"degrees"` | `"radians"` |
| `zero` | `"E"`, `"N"`, `"W"`, `"S"`, or a radian offset | `"E"` |
| `direction` | `"counterclockwise"` or `"clockwise"` | `"counterclockwise"` |
| `sector` | Increasing `(start, end)` no wider than one turn | Full turn |
| `grid_shape` | `"circular"` or `"linear"` | `"circular"` |

The compass combination
`xy.theta_axis(unit="degrees", zero="N", direction="clockwise")` makes 0° point
north, 90° east, 180° south, and 270° west.

A numeric `zero` is always an offset in radians counterclockwise from east,
independent of the data unit. Exact `tick_values` take priority over automatic
angular ticks. When `tick_labels` are omitted, authored fractional degree
values retain their precision (for example, `22.5` renders as 22.5°).

`sector=(start, end)` clips marks and ticks to that angular interval and fits
the chart to the visible arc's bounding box. On `theta_axis()`, `domain=` is a
compatibility alias for `sector=`; pass one or the other, not both. Numeric
theta keeps its independent full-turn data and tick range. Set
`grid_shape="linear"` to join spoke intersections into polygonal radial rings.

Category strings also work as theta coordinates. They are spaced evenly around
a full turn or across an authored sector, and their labels take priority over
numeric angle formatting. `radar_chart()` remains the convenient composition
when every series shares one category list and should close automatically.

## Configure the Radial Axis

`r_axis()` accepts the same options as `y_axis()`. Use `label=` for the measured
quantity, `domain=(minimum, maximum)` for a fixed radial range, and
`tick_values=` when rings must land at exact values. Radial axes support
`type_="linear"`, `"log"`, or `"symlog"`.

The automatic linear range begins at zero so the center keeps its usual
meaning; log autorange remains strictly positive. An explicit domain can choose
a different inner value. `hole=` reserves a shared display-space inner-radius
fraction from 0 up to (but not including) 1. `origin=` places the shared radial
origin in data space, so an origin below the visible minimum creates an
annulus. `hole` and `origin` are mutually exclusive, and a log-axis origin must
be positive.

Filled areas and annular sectors are clipped to the visible radial interval.
For example, a bar extending past the outer ring draws up to that ring instead
of disappearing, and a filled area crossing the radial minimum is trimmed
instead of reflecting through the center. A sector wholly outside the interval
disappears. Scatter points and line vertices outside the interval are culled;
an out-of-range vertex splits a line into visible runs instead of connecting
through its mirrored polar position.

## Combine a Sector, Hole, and Error Bars

Both angular (`xerr`) and radial (`yerr`) uncertainty project through the polar
coordinate system. This example fits the plot to a 220° compass sector and
clips the marks to a shared inner hole:

~~~python demo exec
import reflex_xy
import xy

error_theta = [-90.0, -45.0, 0.0, 45.0, 90.0]
error_radius = [2.0, 3.0, 2.5, 4.0, 3.2]

polar_uncertainty = xy.polar_chart(
    xy.errorbar(
        error_theta,
        error_radius,
        yerr=[0.3, 0.5, 0.4, 0.6, 0.3],
        xerr=[8.0, 6.0, 10.0, 7.0, 8.0],
        color="#dc2626",
        width=2.4,
        cap_size=8,
    ),
    xy.scatter(error_theta, error_radius, color="#111827", size=7),
    xy.theta_axis(
        unit="degrees",
        sector=(-110.0, 110.0),
        zero="N",
        direction="clockwise",
    ),
    xy.r_axis(domain=(0.0, 5.0), hole=0.28),
    title="Directional uncertainty",
)


def polar_uncertainty_demo():
    return reflex_xy.chart(polar_uncertainty, height="390px")
~~~

## Hover and Zoom

Interactive polar charts deliberately expose a smaller gesture set than
Cartesian charts:

- Hover reports the nearest point or field cell: its series name, radial value,
  and any color or size encoding. The numeric angle is left out — the cursor is
  already on it — while an authored spoke label survives and
  `xy.tooltip(labels={"x": ...})` opts the angle back in. A hole or excluded
  part of a sector is not hit-testable.
- **Zoom is off by default.** Polar charts ship without wheel zoom, modebar zoom
  controls, or the zoom percentage indicator. Reset follows by default: with
  nothing to move the view, the derived reset-axis policy is empty, so Fit Data
  and Reset View are absent and double-click has nothing to restore. Wind roses
  are the exception and keep zoom on. Enabling zoom brings the wheel, the whole
  modebar zoom menu, and double-click reset back: zoom scales the radial maximum
  while keeping the radial minimum fixed, and reset restores the original radial
  range. An explicit `reset_axes` also grants reset on its own — controls and
  double-click alike, whatever the zoom switch says — which is what a chart whose
  view moves through linked axes or state-driven updates rather than a gesture
  should use. Its modebar trigger shows a view-controls icon rather than a zoom
  percentage, because with zoom off nothing can move that number.
- Drag does nothing on a disc, and says so: theta pan, box zoom, and
  rectangular/lasso selection have no polar geometry, so `default_drag_action`
  accepts only `"auto"` and `"none"` here and raises on the rest rather than
  resolving to a tool that cannot engage.
- Theta rotation/panning, interactive sector zoom, box zoom, rectangular or lasso
  selection, brushing, and crosshairs are not currently available.

### Why Zoom Is Off by Default

The center of a polar chart is a fixed point: zoom scales the radial maximum
while holding the radial minimum in place. That is well behaved when the radius
is a measured quantity, and misleading when it is not. A pie or donut carries its
value in the *angle* and uses the radius as a constant rim; a radial bar chart,
gauge, or radar sits on a fixed frame. Zooming those crops the rim while the
geometry stays welded to the middle of the disc, which reads as a broken chart
rather than as navigation.

`xy.wind_rose()` keeps zoom enabled because its radius genuinely is data — a
frequency count per direction — so pulling the outer ring in magnifies the short
sectors of a rose dominated by one prevailing direction.

Leaving zoom off also means the chart does not capture the wheel, so a page
scrolls normally when the cursor passes over a pie or gauge.

### Enable Zoom on a Polar Chart

Add an `xy.interaction_config(zoom=True)` child when the radius is a measured
quantity worth magnifying. Because the radial minimum stays pinned, zooming in
enlarges the values nearest the center — which is what you want when a single
large lobe squashes the rest of the pattern against the middle of the disc:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

bearing = np.linspace(0.0, 360.0, 721)
offset = (bearing + 180.0) % 360.0 - 180.0
# Linear radiated power: one dominant main lobe plus side lobes a twentieth its
# size, so the side-lobe structure only becomes readable once the radial axis is
# zoomed in.
power = np.exp(-(offset / 16.0) ** 2) + 0.05 * np.abs(np.cos(np.radians(3.0 * bearing)))

zoomable_polar = xy.polar_chart(
    xy.line(bearing, power, color="#6e56cf", width=2.0),
    xy.theta_axis(unit="degrees", zero="N", direction="clockwise"),
    xy.r_axis(label="radiated power"),
    xy.interaction_config(zoom=True),
    title="Antenna pattern — scroll to magnify the side lobes",
)


def zoomable_polar_demo():
    return reflex_xy.chart(zoomable_polar, height="420px")
~~~

The same flag is available directly on the chart for one-off cases
(`xy.polar_chart(..., zoom=True)`), and `xy.interaction_config(zoom=False)` turns
zoom off on a wind rose. Related switches narrow the gesture further once zoom is
enabled: `wheel_zoom=False` keeps the modebar controls but releases the wheel,
`zoom_buttons=False` does the reverse, and `zoom_limits=(1.0, 8.0)` caps how far
in the radius can go. `box_zoom`, `select`, `brush`, and `crosshair` stay off on
polar charts whatever their flags say — those gestures are rectangles and have no
polar geometry yet.

Radial zoom always keeps the radial minimum fixed, so an ordinary zoom never
turns a disc into an annulus; author a deliberate annulus with `r_axis(hole=...)`
or `r_axis(origin=...)` instead. One consequence is worth knowing before you
enable it: values above the zoomed radial maximum are culled rather than clamped
for lines and points, so zooming in on a chart whose interesting structure sits at
the rim hides it instead of enlarging it. Reach for `r_axis(type_="log")` when a
wide radial range needs to be readable at every scale at once. See
[Interactions and selections](/docs/xy/core-concepts/interactions/) for the
general interaction configuration surface.

## Lay Out and Annotate Polar Charts

Explicit `padding=(top, right, bottom, left)` is preserved by the polar layout.
Increase the bottom or side value to reserve a stable band for a legend,
caption, or other surrounding content; the disc stays centered in the
remaining plot box.

Point-anchored `text`, `label`, `marker`, `arrow`, and `callout` annotations
interpret data coordinates as `(theta, r)` consistently in the browser, SVG,
and native raster output. Their `dx` and `dy` offsets remain screen-space
pixels. Polar rules and bands remain deferred because they require spoke/ring
and sector/annulus geometry instead of Cartesian lines and rectangles; using
one on a polar chart raises at payload build instead of drawing a Cartesian
approximation.

## Use `xy.pyplot`

The Matplotlib-style compatibility layer routes a polar subplot through the
same renderer:

~~~python
import numpy as np
import xy.pyplot as plt

theta = np.linspace(0.0, 2.0 * np.pi, 361)
radius = 1.0 + 0.25 * np.cos(4.0 * theta)

fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
ax.plot(theta, radius, color="#6e56cf")
ax.fill(theta, radius, color="#6e56cf", alpha=0.15)
ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)
ax.set_thetagrids([0, 90, 180, 270], ["N", "E", "S", "W"])
ax.set_thetamin(-120)
ax.set_thetamax(120)
ax.set_rlim(0.0, 1.5)
ax.set_rorigin(-0.25)
ax.set_rticks([0.5, 1.0, 1.5])
plt.show()
~~~

Polar routing works through `plt.subplot(projection="polar")`,
`fig.add_subplot(..., projection="polar")`,
`plt.axes(projection="polar")`, and
`plt.subplots(subplot_kw={"projection": "polar"})`. The `polar=True` alias is
accepted by `subplot()`, `add_subplot()`, and `axes()`, or inside
`subplot_kw`; it is not a direct `plt.subplots(polar=True)` argument. Ordinary
`plot`, `scatter`, `fill`, `bar`, heatmap/image, contour, and `errorbar` calls
share the core polar renderer. `fill()` maps its boundary to a radial area
against `r=0`, which matches a full-turn filled profile but not every arbitrary
closed Matplotlib polygon. The shim preserves theta zero, direction, offset,
and authored theta grids. Degree-based `set_thetamin()`/`set_thetamax()` share
view state with radian `set_xlim()`, while `set_rorigin()` authors the
data-space radial origin. Their corresponding getters, radial limits, ticks,
grids, categorical theta, and log/symlog radial scales use the same core axes.

The stateful `plt.polar()`, `plt.thetagrids()`, and `plt.rgrids()` convenience
wrappers are not part of this increment; call the corresponding methods on the
polar axes. Keep and reuse the returned axes handle: passing
`projection="polar"` again while reactivating an existing `plt.subplot()` is
not supported. See the
[Matplotlib compatibility guide](/docs/xy/integrations/matplotlib/) for the
full boundary.

## Supported Marks and Current Limits

The supported polar primitives are `line`, `scatter`, `area`, `bar`, `column`,
`heatmap`, `contour`, and `errorbar`. The
[radar](/docs/xy/charts/radar-chart/),
[radial bar](/docs/xy/charts/radial-bar-chart/), and
[wind rose](/docs/xy/charts/wind-rose/) helpers compose those primitives; they
do not add separate renderers.

Current limits:

- Histograms, box plots, hexbin, density grids, generic segments, and meshes
  are rejected instead of being drawn with incorrect geometry. Polar
  `errorbar` and contour use narrowly allowlisted projected segments; they do
  not make every segment-backed mark legal.
- Polar lines and filled-area boundaries connect observations with straight
  chords. Repeat the first observation at one full turn when manually closing a
  line; the radar helper handles closure itself.
- Polar traces use direct rendering rather than Cartesian line decimation or
  scatter-density aggregation. `line`, `scatter`, and `area` are limited to
  200,000 points per trace; a larger point trace raises `ValueError`.
  Heatmap/contour grids are not rejected merely because their cell count
  exceeds that point ceiling.
- Polar rules and bands need dedicated spoke, ring, annulus, or sector
  geometry and raise instead of falling back to Cartesian geometry.
- Polar LOD, facets/animation, interactive theta rotation/pan, sector zoom, and
  annulus/sector selection remain deferred.

Supported marks and point-anchored annotations use the same polar projection in
the browser, SVG, PDF, and native raster exporters, so the chart can be
displayed live or exported through the usual chart methods.

## Related Charts

- [Radar charts](/docs/xy/charts/radar-chart/) — compare named dimensions with
  closed profiles.
- [Radial bar charts](/docs/xy/charts/radial-bar-chart/) — annular sectors,
  pies, and donuts.
- [Wind rose charts](/docs/xy/charts/wind-rose/) — directional frequency split
  into magnitude bands.
- [Line charts](/docs/xy/charts/line-chart/) — trends on Cartesian axes.
- [Scatter charts](/docs/xy/charts/scatter/) — relationships and multichannel
  points on Cartesian axes.
- [Bar charts](/docs/xy/charts/bar-chart/) — rectangular categorical and
  numeric bars.
- [Axes and scales](/docs/xy/components/axes/) — shared labels, domains, ticks,
  and styling options.
- [Display and export](/docs/xy/guides/display-and-export/) — notebooks, HTML,
  PNG, SVG, PDF, JPEG, and WebP.

## FAQ

### How do I create a polar chart in Python?

Put a supported mark such as `xy.line(theta, radius)`,
`xy.heatmap(z, x=theta, y=radius)`, or
`xy.errorbar(theta, radius, yerr=...)` inside `xy.polar_chart(...)`. Angles are
radians by default.

### How do I create a radar chart?

See the [radar chart guide](/docs/xy/charts/radar-chart/) for filled and
outlined profiles, the category/value contract, and shared-scale configuration.

### How do I create a wind rose?

See the [wind rose guide](/docs/xy/charts/wind-rose/) for directional bins,
speed bands, input validation, and compass conventions.

### How do I create a pie or donut chart?

See [Pie and Donut Charts](/docs/xy/charts/pie-chart/) for four live
unequal-width sector compositions with center metrics and Reflex legends.

### How do I use degrees instead of radians?

Add `xy.theta_axis(unit="degrees")`. The angle data and generated tick labels
will both use degrees.

### How do I make zero degrees point north?

Use `xy.theta_axis(unit="degrees", zero="N", direction="clockwise")` for the
standard compass convention. The
[wind rose helper](/docs/xy/charts/wind-rose/) applies it automatically.

### Can I migrate a Matplotlib polar plot?

Yes. Create the axes with `plt.subplot(projection="polar")` or
`plt.subplots(subplot_kw={"projection": "polar"})`. Lines, scatter,
radial-to-zero fills, bars, heatmaps/images, contours, and error bars route
through the polar renderer. Theta zero/direction/offset and min/max, authored
theta grids, radial origin, radial limits/ticks/grids, categorical theta, and
log/symlog radius are supported. Arbitrary closed-polygon fills remain a
documented approximation.
