---
title: Figure Methods
description: Reference display, export, streaming, readout, and advanced figure access.
---

# Figure Methods (the Public Chart API)

`Chart` is the public declarative object returned by ordinary chart factories.
The older fluent `Figure` builder is no longer public. `Chart.figure()` remains
an advanced escape hatch to the cached internal engine figure, but application
code should build charts through components and call the public methods below.

## Display

| Method | Contract |
| --- | --- |
| `chart.widget()` | Build or return the cached live AnyWidget. |
| `chart.show()` | Return the same widget; it does not open a desktop browser. |
| `chart.figure()` | Build or return the cached internal engine figure. |

In a compatible notebook, leaving a chart as the final cell expression invokes
its display hook automatically. Python callbacks require the live widget or a
framework adapter.

## HTML and Static Export

~~~python
html: str = chart.to_html(
    path=None,
    custom_css=None,
    animation_progress=None,
)
html_alias: str = chart.html(
    path=None,
    custom_css=None,
    animation_progress=None,
)
svg: str = chart.to_svg(path=None, width=None, height=None)
png: bytes = chart.to_png(
    path=None,
    width=None,
    height=None,
    scale=2.0,
    engine=xy.Engine.default,
    optimize=False,
    custom_css=None,
    sandbox=True,
    gl="software",
)
~~~

`html()` is an alias of `to_html()`. Without a path, exporters return the
document string or PNG bytes; with a path, they also write the result.
`animation_progress` freezes an entrance animation at a deterministic point
from `0.0` through `1.0`; leave it unset for normal live standalone HTML.

`Engine.default` uses the browser-free native PNG renderer.
`Engine.chromium` uses an automatically discovered Chromium-family browser for
browser CSS/WebGL fidelity. `custom_css` works for HTML and Chromium PNG;
native PNG rejects author CSS because it has no browser cascade.

## Unified Image Export

~~~python
image: bytes = chart.to_image(
    format="png",              # png | jpeg/jpg | webp | svg | pdf
    width=None,
    height=None,
    scale=None,                # device-pixel-ratio for raster formats
    background=None,           # "auto" | CSS color | "transparent"
    engine=xy.Engine.auto,
    quality=None,              # JPEG / Chromium-WebP, 1-100 (default 90)
    optimize=False,
    custom_css=None,
    sandbox=True,
    gl="software",
)
written: bytes = chart.write_image("chart.png", format=None)  # accepts the same options
~~~

`write_image()` infers the format from the file extension (`.png`, `.jpg`,
`.jpeg`, `.webp`, `.svg`, `.pdf`; `.html` routes to `to_html()`), writes
atomically, and returns the written bytes. `Engine.auto` deterministically
selects the native path per format, switching to Chromium only when
`custom_css` is passed. Omitted width/height/scale/background/quality fall
back to the chart's `export_config()` defaults. Module-level batch export is
`xy.write_images(figures=..., files=...)` — mixed formats, one shared browser
session for Chromium-resolved files, atomic per-file writes.

## Data Readout and Mutation

~~~python
report: dict = chart.memory_report()
chart.append(trace_id, x, y, color=None, size=None)
row: dict | None = chart.pick(trace_id, index)
selection: xy.Selection = chart.select_range(x0, x1, y0, y1, trace_id=None)
~~~

- `memory_report()` describes canonical, derived, and payload allocations.
- `append()` extends supported scatter or line traces. It mutates chart data,
  not structure; already-exported HTML files remain snapshots.
- `pick()` translates a shipped vertex index to an exact canonical row when
  possible and returns `None` for an invalid index.
- `select_range()` performs a Python-side box selection over scatter traces.

Streaming has additional channel and monotonic-line constraints documented in
[Real-time and streaming data](/docs/xy/guides/real-time-and-streaming-data/).

## Framework Chrome

~~~python
chrome: dict[str, object] = chart.chrome_components()
reflex_chrome: dict[str, object] = chart.reflex_components()
~~~

These methods return the exact opaque replacement objects passed to
`legend()`, `tooltip()`, or `colorbar()`. Core XY does not serialize those
objects. `reflex_components()` is an alias retained for adapter code.

## FacetChart Methods

`FacetChart` provides `figure()`, `widget()`, `show()`, `to_html()`/`html()`,
`to_svg()`, `to_png()`, `to_image()`, `write_image()`, and `memory_report()`.
Its widget methods return one
widget per panel, and its figure escape hatch returns an internal facet grid.
Grid dimensions come from `facet_chart()`, so the facet SVG/PNG methods do not
accept per-call width or height. Facets do not expose append, pick, or
Python-side range selection methods.

See [Display and export](/docs/xy/guides/display-and-export/) for output
workflows and [Public types](/docs/xy/api-reference/public-types/) for
`Engine` and `Selection`.
