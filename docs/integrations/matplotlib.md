---
title: Matplotlib (xy.pyplot)
description: Migrate common Matplotlib workflows through XY's pyplot compatibility layer.
---

# Matplotlib (`xy.pyplot`)

`xy.pyplot` supports two deliberately different implementations:

| Mode | Use it for | Dependency and object model |
| --- | --- | --- |
| `native` | Fast, dependency-free 2-D charts and gradual migration to XY's declarative API | XY-owned Figure, Axes, and Artist-shaped objects; explicitly select it to pin the lightweight implementation |
| `compat` | Broad Matplotlib 3.11 script compatibility | Genuine Matplotlib Figure, Axes, and Artist objects with XY's canvas and display-list renderer |
| `auto` | Dependency-aware default policy | Resolves to `compat` when supported Matplotlib 3.11 is installed and to `native` otherwise |

The base `xy` package contains native mode and does not require Matplotlib.
Install the optional extra for compat mode:

~~~bash
python -m pip install "xy[matplotlib]"
~~~

The extra supports `matplotlib>=3.11,<3.12`; the executable compatibility
contract is pinned to Matplotlib 3.11.0 behavior.

## Select a Mode

The configured default is `auto`. With a base install, changing only the import
resolves to native mode:

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

Select compat before creating any figure when the script depends on broader
Matplotlib semantics:

~~~python
import xy.pyplot as plt

plt.set_mode("compat")
fig, ax = plt.subplots(subplot_kw={"projection": "3d"})
~~~

The process-level equivalent is
`XY_PYPLOT_MODE=compat python example.py`. `plt.get_mode()` returns the
configured value, including `auto`. Importing `xy.pyplot`, reading the mode,
and selecting a mode remain lazy and do not themselves import Matplotlib.
Changing modes while either frontend has an open figure raises an error; call
`plt.close("all")` first.

## How Compat Rendering Works

In compat mode, Matplotlib owns user-facing semantics: Figure, Axes, Artists,
units, transforms, layout engines, `mplot3d`, `axes_grid1`, `axisartist`,
widgets, callback registries, and animation setup. The public
`module://xy.backends.backend_xy` backend converts Matplotlib's draw traversal
into an ordered, device-space XY display list containing paths, clipping,
collections, images, outlined text, hatches, meshes, and Gouraud triangles.

Browser, standalone HTML, SVG, and native raster output consume that same
representation. Every result records whether a fallback was used. A gallery
case with `fallback_used=True` fails: Agg, Cairo, or another Matplotlib
renderer may be a developer oracle, but may not supply accepted output.

Native mode remains a different implementation. It translates supported 2-D
calls onto XY's declarative chart API, retaining XY's screen-bounded data paths
and lightweight object model.

## Gallery Compatibility Contract

The permanent gallery contract represents all 507 sources in the exact
supplied stable-gallery snapshot. The source archive is from the Matplotlib
3.11.1 documentation build; the reference runtime is the separately pinned
Matplotlib 3.11.0 wheel:

| Classification | Count | Meaning |
| --- | ---: | --- |
| Standard pyplot profile | 472 | Matplotlib completes in the standard headless environment |
| Extended pyplot profile | 13 | Requires declared TeX, GUI/toolkit, input, argument, PDF, or multiprocessing support |
| Non-pyplot | 22 | Direct backend, font, server, or GUI embedding source with no pyplot binding to replace |

The first two rows are the 485 pyplot-eligible import-swap cases. The 22 other
sources remain hash-locked and explicitly classified, but are never reported
as pyplot successes or failures.

Execution alone is insufficient. The harness compares figure and capture
counts, canvas dimensions, axes and colorbar layout, projections, scales,
labels, legends, limits, Artist families, and major geometry. It then applies
a tolerant full-canvas visual comparison. The goal is a generally matching
chart, not pixel identity; antialiasing and glyph rasterization may differ.
Interactive examples require delivered canvas events, actual widget and
selector callbacks, axes-limit callbacks, draggable-artist movement, and
timers. Coordinate-reporting cases must populate XY's visible live status
line, while navigation cases must change 2-D limits or the 3-D view through
the browser transport. Exact interactive SVG exports have Chromium click,
hover, and hyperlink canaries. Animations require deterministic
initial/middle/final evidence rather than screenshots alone.

The supplied 3.11.1 resampling gallery source uses
`FillBetweenPolyCollection.set_data(..., step="pre")`, while the 3.11.0
oracle method omits `step=` but retains the corresponding collection state.
Compat mode accepts this exact source call so its zoom callback runs unchanged;
the reference harness records the same scoped, manifest-allowlisted
normalization. No other gallery adapter is accepted.

The completed report passes all 472 standard-profile and all 13
extended-profile cases: 485/485 pyplot-eligible examples with no visual,
behavioral, execution, or fallback waivers. The checked-in baseline records
the implementation commit, harness/contract hashes, and the exact promoted
standard and extended report hashes.

## What Native Mode Covers

Native mode includes every method in Matplotlib 3.11.0's 2-D `Axes`
**Plotting** inventory. A reviewed snapshot locks that name-level surface. The
implementation also covers common stateful pyplot, multi-panel, ticks, scales,
legends, colorbars, styles, export workflows, and XY-owned locator, formatter,
date, colormap, `GridSpec`, and `FacetGrid` helpers.

That 2-D inventory is a native-mode API statement, not a full drop-in claim.
Depending on the feature, native output can have exact geometry, equivalent
semantics, or a documented visual approximation.

### Native figure ownership and subfigures

Native figures keep an explicit ownership tree instead of inferring every
relationship from the flat `Figure.axes` draw-order list. `Figure.subfigures`
and `SubFigure.subfigures` create nested containers; axes created from a
subfigure retain that direct owner, while `ax.get_figure(root=True)` returns
the root figure. Insets, twins, explicit colorbar axes, renderer-owned
colorbar chrome, and figure-level text are distinct children in the tree.
Calling `Figure.text` therefore does not create an axes.

`fig.get_figure_tree()` (also available as `fig.figure_tree`) returns an
immutable measured snapshot. Every node has a root-figure-normalized
`viewport` and `clip`, plus `kind`, `parent_id`, `child_ids`, and `rendered`.
The node kinds are `figure`, `subfigure`, `axes`, `inset_axes`, `twin_axes`,
`colorbar_axes`, `colorbar_chrome`, and `figure_text`. Insets remain
independent axes and clip to their nearest figure/subfigure container rather
than to the parent axes' data rectangle. HTML, SVG, and native PNG exporters
share one resolved tree for a given export.

## Native Polar Plots

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

Native mode supports `projection="polar"` through `plt.subplot()`,
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

## Interactions, Animation, Toolkits, and 3-D

In compat mode, browser pointer, keyboard, scroll, resize, and close input is
translated back into Matplotlib event objects on a live Python canvas.
`mpl_connect`, picking, Matplotlib widgets, timers, `draw`, `draw_idle`, and
full-redraw `blit` use Matplotlib's callback machinery. In IPython,
`plt.show()` displays a kernel-connected anywidget. In a Python script it opens
an authenticated, loopback-only live browser host and dispatches queued input
on Matplotlib's event-loop thread. Arbitrary Python callbacks require that
connected Python process; `print_html()` output may contain precomputed frames,
but is static and is not a live Python canvas after the process exits.

Matplotlib's frontend also performs `mplot3d` projection and depth ordering,
toolkit axes location, custom projections, units, and layout. XY renders the
resulting 2-D display operations. These advanced families remain part of the
485-case remediation gate, so their presence in the architecture is not a
claim that every gallery example already passes.

Native mode does not attempt to recreate those systems. Outside its documented
2-D and polar surface, unsupported material options fail with an actionable
error instead of silently changing the chart.

## Compatibility Boundary

Compat mode is pinned to the Matplotlib 3.11 series. Later Matplotlib releases
require a reviewed contract update. The XY backend is not a replacement for
Qt, Tk, GTK, wx, macOS, WebAgg, or native GUI embedding; relevant upstream
files remain classified among the 22 non-pyplot sources. Compat mode provides
a browser/notebook live canvas and headless exporters, not those window-system
hosts.

Consult the repository's
[generated compatibility matrix](https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/compat-matrix.md)
for native option depth and the
[gallery contract](https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/gallery-contract.md)
for full compat acceptance. Both modes remain experimental and can change
before XY 1.0.

## Migration Path

1. Install the Matplotlib extra and select `compat` for an existing script that
   depends on full Matplotlib semantics.
2. Use `native` when the script fits its documented 2-D surface and import
   weight or XY's performance paths matter most.
3. Compare the output contract that matters to the application: structure,
   interactions, HTML/notebook display, PNG, or SVG—not exact pixels.
4. Resolve every explicit warning or unsupported-option error instead of
   assuming it is cosmetic.
5. For new or performance-sensitive code, move incrementally to `xy` chart
   containers and marks. The declarative API exposes data binding,
   interactions, and CSS/Tailwind hooks without pyplot's implicit state.

Use compat mode for drop-in remediation, native mode for the lightweight 2-D
path, and the declarative API for new applications.
