---
title: Colorbars
description: Author, orient, and style built-in continuous-scale colorbars or replace them in a custom adapter.
components:
  - xy.colorbar
---

# Colorbars

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
