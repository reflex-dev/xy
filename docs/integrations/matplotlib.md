---
title: Matplotlib (xy.pyplot)
description: Migrate common Matplotlib workflows through XY's pyplot compatibility layer.
---

# Matplotlib (`xy.pyplot`)

For common 2D plotting code, import `xy.pyplot` in place of
`matplotlib.pyplot`.

~~~python
import numpy as np
import xy.pyplot as plt

x = np.linspace(0, 10, 200)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), "r--", label="signal")
ax.set_xlabel("time")
ax.set_ylabel("value")
ax.legend()
plt.show()
~~~

The compatibility layer translates calls onto XY's declarative chart API. It
does not require Matplotlib at runtime and uses the same native compute,
screen-bounded representations, notebook widget, and exporters as ordinary XY
charts.

## What Is Covered

The shim includes every method in Matplotlib 3.11.0's 2-D `Axes` **Plotting**
inventory. A reviewed snapshot locks that surface, and CI checks it against the
released `matplotlib==3.11.0` package. The shim also covers common stateful
pyplot, multi-panel, ticks, scales, legends, colorbars, styles, and export
workflows, plus XY-owned locator, formatter, date, colormap, `GridSpec`, and
`FacetGrid` helpers.

Coverage means that a plotting entry point exists and its supported contract
is tested. Depending on the feature, output can have exact geometry,
equivalent semantics, or a documented visual approximation. It is not a claim
to reproduce Matplotlib's renderer or complete Artist graph.

## Polar Plots

Create a polar axes with `plt.subplot()` or `Figure.add_subplot()`:

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

The shim supports `projection="polar"` through `plt.subplot()`,
`Figure.add_subplot()`, `plt.axes()`, and `plt.subplots(subplot_kw=...)`.
`polar=True` is accepted by the first three factories or inside `subplot_kw`;
it is not a direct `plt.subplots(polar=True)` argument. Ordinary `plot`,
`scatter`, `fill`, `bar`, regular-grid heatmap/image, contour, and `errorbar`
calls route through the core polar renderer in HTML, PNG, and SVG. `fill()` is
a documented approximation: it creates a radial area against `r=0`, which is
correct for a full-turn filled profile but does not retain the closing chord of
every arbitrary Matplotlib polygon.

Polar axes preserve `set_theta_zero_location()`, `set_theta_direction()`,
`set_theta_offset()`, `set_thetagrids()`, radial limits/ticks/grids, categorical
theta, and log/symlog radial scales. Degree-based
`set_thetamin()`/`set_thetamax()` and their getters share the same sector state
as radian `set_xlim()`/`get_xlim()`; the latest call wins.
`set_rorigin()`/`get_rorigin()` expose the data-space radial origin.

Polar rules/spans, generic mesh or segment artists, LOD, facets/animation, and
angular navigation/selection remain outside this surface. Use axes methods
rather than the not-yet-exposed stateful `plt.polar()`, `plt.thetagrids()`, and
`plt.rgrids()` convenience wrappers. Keep the returned axes handle instead of
passing `projection="polar"` again to reactivate an existing `plt.subplot()`.

The declarative [polar chart overview](/docs/xy/charts/polar-chart/) documents
the shared coordinate system. Focused guides cover
[radar charts](/docs/xy/charts/radar-chart/),
[radial bars and donuts](/docs/xy/charts/radial-bar-chart/), and
[wind roses](/docs/xy/charts/wind-rose/).

## Compatibility Boundary

Three-dimensional, geographic, ternary, and custom projections; animations;
GUI backends; arbitrary third-party Artist graphs; clipping/transform graphs;
and material options that XY cannot honor fail with an actionable error
instead of being silently ignored. Polar is the supported non-Cartesian
projection, with the limits above.

Consult the repository's
[generated compatibility matrix](https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/compat-matrix.md)
when a workflow depends on a specific option. Compatibility shims remain
experimental and can change before XY 1.0.

## Migration Path

1. Change the pyplot import and run the existing plotting workflow.
2. Resolve every explicit warning or unsupported-option error instead of
   assuming it is cosmetic.
3. Compare the output contract that matters to the application: interactive
   HTML, notebook display, PNG, or SVG.
4. For new or performance-sensitive code, move incrementally to `xy` chart
   containers and marks. The declarative API exposes data binding,
   interactions, and CSS/Tailwind hooks without pyplot's implicit state.

Use `xy.pyplot` for migration and familiar scientific scripts; prefer the
declarative API for new applications.
