---
title: Exporting
description: Export interactive HTML, native or browser PNG, and vector SVG.
---

# Exporting

The same composed chart supports notebook display and three standalone output
families.

## Standalone HTML

~~~python
import xy as fc

chart = fc.line_chart(fc.line([0, 1, 2], [2, 5, 3]))

html = chart.to_html()
chart.to_html("chart.html")
~~~

HTML export is self-contained and keeps zoom, pan, hover, selection, and the
built-in chart chrome. It does not require a browser at export time.

## PNG

~~~python
from xy import Engine

chart.to_png("chart.png", width=1200, height=630, scale=2)
chart.to_png(
    "browser-chart.png",
    engine=Engine.chromium,
    custom_css=".xy { font-family: Inter, sans-serif; }",
)
~~~

The default engine is XY's browser-free native rasterizer. Use
`Engine.chromium` when browser fonts, CSS, or WebGL fidelity matter. XY searches
for Chrome, Chromium, Edge, or `chrome-headless-shell`; set `XY_BROWSER` to
override discovery. `optimize=True` trades additional work for smaller native
PNG files.

## SVG

~~~python
svg = chart.to_svg(width=1200, height=630)
chart.to_svg("chart.svg")
~~~

SVG export is browser-free and screen-bounded. Long lines are decimated before
vector generation, while density and heatmap representations embed compact
raster data where appropriate.

## Responsive Dimensions

Chart `width` and `height` accept positive pixel integers. Ordinary charts also
accept percentages such as `width="100%"`; the parent must define a height when
using `height="100%"`. Fixed dimensions are recommended for deterministic
static export and facet grids.
