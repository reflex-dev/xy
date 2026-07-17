---
title: Colorbars
description: Understand continuous-scale colorbar chrome and its current declarative boundary.
---

# Colorbars

A colorbar explains a continuous color scale. XY's public `colorbar()`
component currently has a deliberately small role: it holds an opaque
replacement for a framework adapter and carries visibility or DOM styling for
colorbar metadata supplied by an advanced integration.

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

This is a complete example of storing a Reflex component as opaque replacement
content. Core XY does not mount the component, and the shipped
`reflex_xy.chart` adapter does not currently mount custom chrome either. A
custom adapter must read `chrome_components()` and place the returned component
itself; standalone HTML, SVG, and PNG ignore it.

## Current Declarative Boundary

The core declarative mark factories keep the colormap and numerical domain on
the mark. They do not currently synthesize a complete colorbar specification
from those channels. Consequently, adding `colorbar()` is not itself a request
to create ticks, a title, an orientation, or a domain.

If an advanced integration supplies built-in colorbar metadata, `show=False`
removes it and the style hooks apply to its DOM. The public component does not
expose independent tick, label, or orientation options yet. `xy.pyplot` has its
own colorbar-authoring API; it is not configured by this declarative component.

## Style or Replace It

The chart slots `colorbar`, `colorbar_bar`, `colorbar_tick`, and
`colorbar_title` target built-in browser chrome:

~~~python
chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4], color=[0.2, 0.8, 1.4]),
    class_names={"colorbar_title": "font-semibold"},
    styles={"colorbar_bar": {"border-radius": "4px"}},
)
~~~

For a framework-owned replacement, pass one positional child or `render=` as
in the first example. Core XY keeps that object out of standalone
serialization. See the
[Reflex integration](/docs/xy/integrations/reflex/) for the shipped chart
adapter and [Marks and components reference](/docs/xy/api-reference/marks-and-components/)
for the current minimal signature.
