---
title: Colorbars in Python
description: Author, orient, and style built-in continuous-scale colorbars or replace them in a custom adapter.
components:
  - xy.colorbar
---

# Colorbars in Python

A colorbar explains a continuous color scale. Add `xy.colorbar()` after a
compatible continuous-color mark and XY derives the validated domain,
colormap, and a useful title from that mark. The built-in colorbar renders in
the browser, SVG, native PNG, and Chromium PNG.

## Built-in declarative colorbars

The two orientations share the same title and explicit-tick API. Browser DOM
chrome additionally exposes the class and slot styling shown here:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

vertical_scale = xy.heatmap_chart(
    xy.heatmap(
        [[-2.0, 0.0], [2.0, 4.0]],
        name="temperature",
        colormap="coolwarm",
        domain=(-3, 5),
    ),
    xy.colorbar(
        title="Temperature (°C)",
        ticks=[-3, 0, 5],
        class_name="rounded-lg bg-white/90",
    ),
    styles={
        "colorbar_bar": {"border_radius": 5},
        "colorbar_tick": {"color": "#475569"},
        "colorbar_title": {"font_weight": 700},
    },
    title="Vertical scale",
)

horizontal_scale = xy.scatter_chart(
    xy.scatter(
        [0, 1, 2, 3],
        [2, 5, 3, 8],
        color=[0.1, 0.4, 0.7, 1.0],
        colormap="viridis",
        size=12,
    ),
    xy.colorbar(
        title="Confidence",
        orientation="horizontal",
        ticks=[0.1, 0.5, 1.0],
    ),
    title="Horizontal scale",
)


def colorbar_orientation_preview():
    return rx.el.div(
        reflex_xy.chart(vertical_scale, height="330px"),
        reflex_xy.chart(horizontal_scale, height="330px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

The last compatible continuous mark wins when a chart layers several scales. XY
derives colorbars for heatmaps, continuous scatter, hexbin, contour,
continuous segments, and triangle meshes. A field or mark name supplies the
default title; `title=` overrides it, `ticks=` supplies finite tick positions,
and `orientation=` accepts `"vertical"` or `"horizontal"`.

XY deliberately emits no built-in colorbar for constant or categorical color,
RGB(A) heatmaps, or density-tier scatter whose per-row color channel is not
resident in the browser. `colorbar(show=False)` removes an inferred scale.
`xy.pyplot` has its own Matplotlib-shaped colorbar-authoring API.

### Pinning the scale with a fixed domain

Passing an explicit mark `domain=` pins the colorbar to a known range instead
of the data extent, so the scale stays comparable across refreshes:

~~~python demo exec
import numpy as np
import reflex_xy
import xy

rng_load = np.random.default_rng(7)
cpu_load = (rng_load.random((6, 6)) * 60 + 20).round(1)

pinned_scale = xy.heatmap_chart(
    xy.heatmap(cpu_load, name="load", colormap="magma", domain=(0, 100)),
    xy.colorbar(title="Load (%)", ticks=[0, 25, 50, 75, 100]),
    title="Pinned 0–100 scale",
)


def pinned_domain_colorbar():
    return reflex_xy.chart(pinned_scale, height="330px")
~~~

### Derived scales on hexbin and layered marks

A hexbin's aggregated counts feed the colorbar just like any continuous
channel, and when several continuous marks are layered the colorbar derives
from the last compatible one — here the stations scatter (0–50 PPM on
viridis), not the heatmap beneath it:

~~~python demo exec
import numpy as np
import reflex as rx
import reflex_xy
import xy

rng_bins = np.random.default_rng(21)
hexbin_density = xy.hexbin_chart(
    xy.hexbin(
        rng_bins.normal(0.0, 1.0, 400),
        rng_bins.normal(0.0, 1.0, 400),
        gridsize=12,
        colormap="plasma",
    ),
    xy.colorbar(title="Points per bin", orientation="horizontal"),
    title="Horizontal hexbin scale",
)

rng_layers = np.random.default_rng(3)
layered_scales = xy.heatmap_chart(
    xy.heatmap(
        [[4.0, 9.0], [14.0, 22.0]],
        name="model grid",
        colormap="cividis",
        domain=(0, 25),
    ),
    xy.scatter(
        rng_layers.uniform(0.0, 1.0, 12),
        rng_layers.uniform(0.0, 1.0, 12),
        color=(rng_layers.random(12) * 40 + 10).round(1),
        colormap="viridis",
        color_domain=(0, 50),
        size=12,
        name="stations",
    ),
    xy.colorbar(title="Station PPM"),
    title="Last compatible mark wins",
)


def derived_scale_sources():
    return rx.el.div(
        reflex_xy.chart(hexbin_density, height="330px"),
        reflex_xy.chart(layered_scales, height="330px"),
        class_name="grid w-full grid-cols-1 gap-5 xl:grid-cols-2",
    )
~~~

## Framework-owned replacement

`render=` (or one positional child) remains an opaque integration hook:

~~~python
import reflex as rx
import xy

my_color_scale = rx.vstack(
    rx.text("Intensity", weight="bold"),
    rx.box(
        width="8rem",
        height="0.5rem",
        border_radius="999px",
        background="linear-gradient(90deg, #440154, #21918c, #fde725)",
    ),
    rx.hstack(rx.text("0.2"), rx.spacer(), rx.text("1.4"), width="8rem"),
    spacing="1",
)

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4], color=[0.2, 0.8, 1.4]),
    xy.colorbar(render=my_color_scale),
)

replacement = chart.chrome_components()["colorbar"]
assert replacement is my_color_scale
~~~

Core XY stores that object but does not mount it, and the shipped
`reflex_xy.chart` adapter does not currently mount custom chrome either. A
custom adapter must read `chrome_components()` and place the returned component
itself; standalone HTML, SVG, and PNG ignore the opaque replacement.

## Styling slots

The chart slots `colorbar`, `colorbar_bar`, `colorbar_tick`, and
`colorbar_title` target built-in browser chrome:

~~~python
chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4], color=[0.2, 0.8, 1.4]),
    xy.colorbar(title="Intensity"),
    class_names={"colorbar_title": "font-semibold"},
    styles={
        "colorbar_bar": {"border_radius": 4},
        "colorbar_tick": {"font_size": 10},
    },
)
~~~

See the
[Reflex integration](/docs/xy/integrations/reflex/) for the shipped chart
adapter and [Marks and components reference](/docs/xy/api-reference/marks-and-components/)
for the complete signature.

## FAQ

### How do I add a color scale to a chart in Python?

Add `xy.colorbar()` as a chart child after a continuous-color mark such as a
heatmap or a scatter with a numeric `color=` channel. XY derives the validated
domain, colormap, and a default title from that mark, and the built-in colorbar
renders in the browser, SVG, native PNG, and Chromium PNG.

### How do I set custom ticks and a title on a colorbar?

Pass them to the component: `xy.colorbar(title="Temperature (°C)", ticks=[-3, 0, 5])`.
`title=` overrides the default title derived from the field or mark name, and
`ticks=` supplies explicit finite tick positions; both work in either
orientation.

### Can I make the colorbar horizontal instead of vertical?

Yes — `xy.colorbar(orientation="horizontal")`. The `orientation=` option
accepts `"vertical"` (the default) or `"horizontal"`, and both orientations
share the same `title` and `ticks` API.

### Why is no colorbar showing on my chart?

XY only derives colorbars for continuous-color marks: heatmaps, continuous
scatter, hexbin, contour, continuous segments, and triangle meshes. Constant or
categorical color, RGB(A) heatmaps, and density-tier scatter whose per-row
color channel is not resident in the browser deliberately get no built-in
colorbar. When several continuous scales are layered, the last compatible mark
wins, and `xy.colorbar(show=False)` removes an inferred scale you don't want.
