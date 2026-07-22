---
title: Display and Export
description: Display live charts and export PNG, JPEG, WebP, SVG, PDF, HTML, or image batches.
---

# Display and Export

The same composed chart can display as a live notebook widget or export
through one unified static API covering PNG, JPEG, WebP, SVG, PDF, and
standalone interactive HTML.

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

## Unified Image Export

`to_image()` returns bytes; `write_image()` writes a file atomically and
infers the format from the extension:

~~~python
data = chart.to_image("pdf", width=1200, height=800, scale=2)

chart.write_image("reports/revenue.webp")   # format inferred from .webp
chart.write_image("reports/revenue.bin", format="png")  # explicit override
~~~

### Format and engine matrix

| Format | Native (browser-free) | Chromium | Notes |
| --- | --- | --- | --- |
| `png` | yes (default) | yes | transparency supported |
| `jpeg` / `jpg` | yes (default) | yes | no alpha; flattens onto `background` (default white); `quality` 1-100 (default 90) |
| `webp` | yes (default) | yes | native output is **lossless** with alpha; Chromium output is lossy and honors `quality` |
| `svg` | yes (always) | — | vector, browser-free; SVG cannot be produced by a screenshotting browser |
| `pdf` | yes (default) | yes | native output keeps text/axes/marks as vectors; density/heatmap layers embed as bounded rasters (hybrid-vector policy). Chromium prints the page instead |
| `html` | yes | — | via `to_html()`; `write_image("chart.html")` routes there |

`engine="auto"` (the default) is deterministic: every format uses the native
path unless `custom_css` is passed, which forces Chromium because utility-class
CSS needs a real CSS engine. `engine=Engine.chromium` opts into browser CSS,
font, and WebGL fidelity for any format except SVG. Native exports never
install or launch a browser; when Chromium is requested but not found, the
error names `XY_BROWSER` and the supported browsers.

### Background policy

`background` accepts `"auto"` (each renderer's default backdrop: opaque white
for raster/browser output, transparent for SVG), any CSS color, or
`"transparent"`:

~~~python
chart.to_image("png", background="transparent")   # alpha-0 backdrop
chart.to_image("webp", background="#0f172a")      # explicit backdrop
chart.to_image("jpeg")                            # flattened onto white
~~~

JPEG has no alpha channel, so `background="transparent"` is rejected there
rather than silently flattened. An explicit color (or `"transparent"`)
**replaces** the chart's theme backgrounds — both `theme(background=...)` and
`theme(plot_background=...)` — painting one backdrop consistently in every
format (raster canvas, SVG/PDF rect, browser page); `"auto"` keeps the theme
paints untouched.

`scale` is the device-pixel-ratio for raster formats and is ignored by
SVG/PDF, which are resolution-independent. A 300×200 chart at `scale=2`
produces a 600×400 raster.

## Declarative Export Defaults

`xy.export_config` describes export behavior as part of the chart — no I/O
happens at build time. It governs the modebar's download menu and provides
defaults for the Python export calls:

~~~python
xy.chart(
    xy.line("date", "revenue", data=frame),
    xy.export_config(
        formats=["png", "webp", "svg", "csv"],  # menu availability + order
        filename="revenue",
        width=1200,
        height=800,
        scale=2,
        background="auto",
    ),
)
~~~

The browser modebar shows the client-safe subset (`png`, `jpeg`, `webp`,
`svg`, `csv`) with the same filename, scale, background, and quality semantics
as the Python exporters; `pdf`/`html` entries affect Python-side defaults
only. `formats=[]` hides the download menu entirely. Standalone HTML exports
keep the full download menu working without any Python kernel attached, and
Reflex charts inherit the same spec-driven configuration. Explicit arguments
to `to_image()`/`write_image()` always override the declarative defaults.

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

## Compatibility Conveniences

`to_png()`, `to_svg()`, and `to_html()` remain supported with their existing
signatures:

~~~python
from xy import Engine

chart.to_png("chart.png", width=1200, height=630, scale=2)
chart.to_png(
    "browser-chart.png",
    engine=Engine.chromium,
    custom_css=".xy { font-family: Inter, sans-serif; }",
)
svg = chart.to_svg(width=1200, height=630)
~~~

The default PNG engine is XY's browser-free native rasterizer; set
`optimize=True` to spend more time producing a smaller native PNG. SVG export
is browser-free and screen-bounded: long lines are decimated before vector
generation, while density and heatmap representations embed compact raster
data where appropriate. For Chromium exports, XY searches for Chrome,
Chromium, Edge, or `chrome-headless-shell`; set `XY_BROWSER` to select an
executable explicitly. The browser sandbox is enabled by default; disable it
only for trusted input in an environment where the caller accepts that risk.

## Batch Export

Use one batch call instead of exporting in a loop — formats can be mixed, and
every Chromium-resolved file in the batch shares a single browser session:

~~~python
import xy

xy.write_images(
    figures=[overview, detail],
    files=["overview.svg", "detail.pdf"],
)
~~~

Per-file formats come from the extensions (`formats=` overrides them), and
writes are atomic per file. With the native engine the same call loops the
millisecond-fast browser-free renderers.

## Facets

Facet grids support the same format matrix as single charts:

~~~python
grid = xy.facet_chart(xy.scatter("x", "y"), data=frame, by="region")
grid.write_image("regions.pdf")   # vector panels, composed natively
grid.to_image("webp", background="transparent")
~~~

Native raster output composes the browser-free panel renders (the grid title
strip is omitted there — the native rasterizer has no free-standing text
path); SVG/PDF compose the vector panels, title included; Chromium renders
the full HTML grid.

## Migrating from Plotly

| Plotly | XY |
| --- | --- |
| `fig.to_image(format="png", scale=2)` | `chart.to_image("png", scale=2)` |
| `fig.write_image("out.webp")` | `chart.write_image("out.webp")` |
| `fig.write_html("out.html")` | `chart.to_html("out.html")` |
| `pio.write_images(figs, files)` | `xy.write_images(figures=..., files=...)` |
| Kaleido/Chrome required for static export | browser-free by default; `Engine.chromium` opt-in |
| EPS | not supported (dropped by modern Plotly/Kaleido as well) |

## Deterministic Dimensions

Interactive chart `width` and `height` accept positive pixel integers.
Ordinary charts also accept percentages such as `width="100%"`; the parent
must define a height when using `height="100%"`. Static raster and facet
output should use explicit dimensions for deterministic results; fluid
(`"100%"`) charts fall back to 800×500 at export time. Exports are
deterministic byte-for-byte for identical figures and options — no
timestamps, transient hover chrome, or nondeterministic ids are embedded.
