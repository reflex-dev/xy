---
title: Display and Export
description: Display live charts and export standalone HTML, PNG, SVG, or image batches.
---

# Display and Export

The same composed chart can display as a live notebook widget or produce three
standalone output families.

## Notebook Display

Leave the chart as the final cell expression, or return its widget explicitly:

~~~python
chart
chart.show()
chart.widget()
~~~

`show()` returns the live notebook widget; it does not launch a desktop window.
See [Notebooks](/docs/xy/integrations/notebooks/) for callbacks, binary comms,
and supported hosts.

## Standalone HTML

~~~python
html = chart.to_html()
chart.to_html("chart.html")
~~~

HTML export is self-contained: it includes the chart spec, binary data, and
bundled render client. It keeps zoom, pan, hover, selection, and built-in chart
chrome and does not need a browser or network connection at export time.

Pass `custom_css=` to include author CSS for chrome classes and tokens in the
exported document. Standalone HTML uses inline scripts and styles by design;
read [Serving, CSP, and offline use](/docs/xy/guides/serving-csp-and-offline-use/)
before placing it inside a stricter application policy.

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

The default engine is XY's browser-free native rasterizer. Set
`optimize=True` to spend more time producing a smaller native PNG. Use
`Engine.chromium` when browser fonts, injected CSS, or WebGL fidelity matters.
XY searches for Chrome, Chromium, Edge, or `chrome-headless-shell`; set
`XY_BROWSER` to select an executable explicitly.

`custom_css` is Chromium-only. The browser sandbox is enabled by default;
disable it only for trusted input in an environment where the caller accepts
that risk.

## SVG

~~~python
svg = chart.to_svg(width=1200, height=630)
chart.to_svg("chart.svg")
~~~

SVG export is browser-free and screen-bounded. Long lines are decimated before
vector generation, while density and heatmap representations embed compact
raster data where appropriate.

## Batch PNG Export

Use one batch call instead of repeatedly starting Chromium:

~~~python
from xy import Engine
from xy.export import write_images

write_images(
    [first.figure(), second.figure()],
    ["first.png", "second.png"],
    engine=Engine.chromium,
)
~~~

Chromium batches reuse one browser session. With the default native engine,
the same function loops over the fast browser-free rasterizer.

## Deterministic Dimensions

Interactive chart `width` and `height` accept positive pixel integers.
Ordinary charts also accept percentages such as `width="100%"`; the parent
must define a height when using `height="100%"`. Static raster and facet output
should use explicit dimensions for deterministic results.
