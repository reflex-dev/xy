---
title: Chart Chrome
description: Configure legends, tooltips, colorbars, modebars, themes, and controls.
---

# Chart Chrome

Chrome components configure the DOM and controls around the chart's canvas.
When multiple components of the same type are present, the last one supplies
the effective configuration.

## Legend

~~~python
fc.legend(
    show=True,
    loc="upper right",
    ncols=2,
    title="Series",
    class_name="chart-legend",
)
~~~

Series with a `name` participate in the legend. Set `show=False` when a host
framework mounts a custom replacement.

## Tooltip

~~~python
fc.tooltip(
    fields=["month", "revenue", "growth"],
    title="{month}",
    format={"revenue": ",.0f", "growth": ".1%"},
)
~~~

Fields may refer to source columns. Formatting strings use the chart client's
numeric formatting contract.

## Colorbar and Modebar

Add `colorbar()` for continuous color encodings. Add `modebar()` to control the
chart toolbar and style both its container and buttons.

~~~python
chart = fc.scatter_chart(
    fc.scatter([1, 2, 3], [3, 5, 4], color=[0.2, 0.8, 1.4]),
    fc.colorbar(),
    fc.modebar(button_style={"border-radius": 6}),
)
~~~

## Theme and Interaction

`theme()` supplies visual tokens such as plot background, grid, axis, text,
crosshair, and selection colors. `interaction_config()` controls hover, click,
selection, brush, crosshair, view-change, and linked-view behavior.

## Framework Render Slots

`legend`, `tooltip`, and `colorbar` accept an opaque `render` object. XY retains
it on the Python chart without serializing it into standalone HTML. Adapter code
can retrieve exact objects through `chart.chrome_components()` or its
`reflex_components()` alias.
