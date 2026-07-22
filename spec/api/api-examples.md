# API Examples

These examples cover the currently implemented 2D chart families. They are
short on purpose: each one should be copyable into a notebook or script after
`pip install xy`. The Python snippets in this file are executed by
`tests/test_docs_examples.py`, so docs changes should fail fast if the public
API drifts.

The library is optimized for large data, but ordinary charts should stay boring
to build. The first section below is intentionally small business-style data;
the later per-chart examples show the same APIs scaling up.

## API Stability Notes

xy has one public chart-building API: the declarative composition API.
Charts are Reflex-shaped, declarative chart children — marks, axes,
annotations, legend/tooltip chrome — composed inside a family container
(`xy.line_chart(...)`, `xy.bar_chart(...)`, ...) or the neutral layering
container `xy.chart(...)`. Marks accept arrays directly or column-name
resolution through `data=`, and charts take `on_hover` / `on_select` callbacks.
The core composition contract is now stabilizing around lightweight Python
children, layered marks, axes, annotations, built-in or custom legend/tooltip
chrome, and CSS/Tailwind-friendly DOM hooks. Callback payload details and
future adapter packages may still evolve before 1.0.

Composed `Chart` objects handle standalone HTML export, static image export
(PNG/JPEG/WebP/SVG/PDF), notebook display, and memory reporting directly. The
internal engine object a chart compiles to is reachable via `chart.figure()` as
an advanced escape hatch, but it is not part of the public chart-building
surface.

Charts accept `width="100%"` and/or `height="100%"` for responsive layouts.
Standalone `to_html(...)` needs no browser dependency. Every static image
format — PNG, JPEG, WebP, SVG, PDF — is produced natively, without a browser.

`Engine` has three members — `auto`, `default`, `chromium` — and the entry
points split on their default. `to_png(...)` defaults to `Engine.default`, the
browser-free native rasterizer; `to_svg(...)` takes no `engine` argument at all
and is always native. The unified `to_image(...)` / `write_image(...)` entry
points default to `Engine.auto`, which resolves deterministically per request:
native for every format, chromium only when `custom_css=` is passed, since
author CSS needs a real CSS engine. `to_png(..., engine=Engine.chromium)` uses
an installed Chrome, Chromium, Edge, or `chrome-headless-shell` executable
because it screenshots
the same standalone HTML document for browser CSS/WebGL fidelity. Automatic
discovery can be overridden with `XY_BROWSER`. Native raster export
intentionally rejects browser-only stylesheets, and SVG is native-only:
resolving to a browser engine for SVG — by `engine=Engine.chromium` or by
`custom_css=` — raises, because a screenshot cannot emit vector SVG.

## Chart Family Quick Reference

| Chart family | Composition API |
|---|---|
| Line | `xy.line_chart(xy.line(...))` |
| Scatter | `xy.scatter_chart(xy.scatter(...))` |
| Area | `xy.area_chart(xy.area(...))` |
| Histogram | `xy.histogram_chart(xy.histogram(...))` or `xy.hist(...)` |
| Bar | `xy.bar_chart(xy.bar(...))` |
| Column | `xy.column_chart(xy.column(...))` |
| Grouped bars | `xy.bar_chart(xy.bar(..., mode="grouped"))` |
| Stacked bars | `xy.bar_chart(xy.bar(..., mode="stacked"))` |
| Normalized bars | `xy.bar_chart(xy.bar(..., mode="normalized"))` |
| Horizontal bars | `xy.bar_chart(xy.bar(..., orientation="horizontal"))` |
| Heatmap | `xy.heatmap_chart(xy.heatmap(...))` |
| Error bars/bands | `xy.errorbar_chart(xy.errorbar(...))` and `xy.error_band_chart(xy.error_band(...))` |
| Box | `xy.box_chart(xy.box(...))` |
| Violin | `xy.violin_chart(xy.violin(...))` |
| ECDF | `xy.ecdf_chart(xy.ecdf(...))` |
| Hexbin | `xy.hexbin_chart(xy.hexbin(...))` |
| Contour | `xy.contour_chart(xy.contour(...))` |
| Step/stairs/stem | `xy.step_chart(xy.step(...))`, `xy.stairs_chart(xy.stairs(...))`, `xy.stem_chart(xy.stem(...))` |
| Independent segments | `xy.segments_chart(xy.segments(x0=..., y0=..., x1=..., y1=...))` |
| Triangle mesh | `xy.triangle_mesh_chart(xy.triangle_mesh(...))` |
| Facets | `xy.facet_chart(xy.scatter(...), by="group", data=data)` |

## Axes And Scales

```python
import numpy as np
import xy

x = np.logspace(0, 6, 240)
rank = 96 - np.log10(x) * 11.5
conversion = 0.08 + np.log10(x) * 0.035

chart = xy.chart(
    xy.line(x=x, y=rank, name="rank", color="#2563eb"),
    xy.line(x=x, y=conversion, y_axis="y2", name="conversion", color="#dc2626"),
    xy.x_axis(label="request volume", type_="log", domain=(1, 1_000_000), format=",.0f"),
    xy.y_axis(label="rank (reversed)", domain=(0, 100), reverse=True, format=".0f"),
    xy.y_axis(id="y2", label="conversion", side="right", domain=(0, 0.35), format=".0%"),
    title="Axes and scales",
)
chart
```

## Small Business Chart

```python
import xy

month_number = [1, 2, 3, 4, 5, 6]
revenue = [42, 45, 48, 51, 55, 59]
pipeline = [35, 38, 42, 40, 46, 50]

chart = xy.line_chart(
    xy.line(month_number, revenue, name="revenue", color="#2563eb", width=2.0),
    xy.line(month_number, pipeline, name="pipeline", color="#16a34a", width=2.0),
    xy.x_axis(label="month number"),
    xy.y_axis(label="USD thousands"),
    title="Revenue vs pipeline",
)
chart
```

## Line

```python
import numpy as np
import xy

rng = np.random.default_rng(0)
x = np.arange(1_000_000, dtype=np.float64)
y = np.cumsum(rng.normal(size=len(x)))

chart = xy.line_chart(
    xy.line(x, y, name="walk"),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    title="Random walk",
)
chart
```

## Scatter

```python
import numpy as np
import xy

rng = np.random.default_rng(1)
x = rng.normal(size=500_000)
y = 0.5 * x + rng.normal(scale=0.6, size=len(x))

xy.scatter_chart(
    xy.scatter(
        x,
        y,
        color=y,
        size=np.abs(y),
        colormap="viridis",
        size_range=(2, 14),
    ),
    title="Correlated scatter",
)
```

## Area

```python
import numpy as np
import xy

x = np.linspace(0, 10, 100_000)
y = np.sin(x) + 0.15 * x

xy.area_chart(
    xy.area(x, y, base=0.0, name="signal", opacity=0.35),
    title="Area",
)
```

## Histogram

```python
import numpy as np
import xy

rng = np.random.default_rng(2)
values = np.concatenate(
    [rng.normal(-1.2, 0.45, 300_000), rng.normal(1.4, 0.6, 200_000)]
)

xy.histogram_chart(
    xy.histogram(values, bins=240, name="samples"),
    title="Distribution",
)
```

Pass `cumulative=True` to accumulate bins left-to-right. Combined with
`density=True` this is the empirical CDF, whose last bin is ~1.0:

```python
import numpy as np
import xy

rng = np.random.default_rng(3)
latency_ms = rng.gamma(shape=2.0, scale=40.0, size=100_000)

xy.histogram_chart(
    xy.hist(latency_ms, bins=200, density=True, cumulative=True, name="p(x)"),
    xy.x_axis(label="ms"),
    xy.y_axis(label="fraction"),
    title="Latency CDF",
)
```

## Bar

```python
import xy

channels = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
conversions = [120, 94, 72, 66, 43, 31]

xy.bar_chart(
    xy.bar(channels, conversions, name="Desktop"),
    xy.x_axis(label="channel"),
    xy.y_axis(label="count"),
    title="Conversions",
)
```

## Column

```python
import xy

quarters = ["Q1", "Q2", "Q3", "Q4"]
revenue = [42, 47, 51, 58]

xy.column_chart(
    xy.column(quarters, revenue, name="Revenue"),
    xy.x_axis(label="quarter"),
    xy.y_axis(label="revenue"),
    title="Quarterly revenue",
)
```

## Grouped Bars

```python
import numpy as np
import xy

channels = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
values = np.array(
    [
        [120, 88, 42],
        [94, 76, 39],
        [72, 55, 26],
        [66, 48, 31],
        [43, 29, 19],
        [31, 22, 14],
    ],
    dtype=float,
)

xy.bar_chart(
    xy.bar(
        channels,
        values,
        mode="grouped",
        series=["Desktop", "Mobile", "Tablet"],
    ),
    title="Grouped channels",
)
```

## Stacked Bars

```python
import numpy as np
import xy

quarters = ["Q1", "Q2", "Q3", "Q4"]
values = np.array(
    [
        [42, 21, 13],
        [47, 25, 16],
        [51, 29, 18],
        [58, 31, 22],
    ],
    dtype=float,
)

xy.bar_chart(
    xy.bar(
        quarters,
        values,
        mode="stacked",
        series=["Product", "Services", "Partners"],
    ),
    title="Stacked revenue",
)
```

## Normalized Stacked Bars

`mode="normalized"` divides every stack by its per-category total, so each
category renders the series' share of the whole (segments sum to 1):

```python
import numpy as np
import xy

quarters = ["Q1", "Q2", "Q3", "Q4"]
values = np.array(
    [
        [42, 21, 13],
        [47, 25, 16],
        [51, 29, 18],
        [58, 31, 22],
    ],
    dtype=float,
).T

xy.bar_chart(
    xy.bar(
        quarters,
        values,
        mode="normalized",
        series=["Product", "Services", "Partners"],
    ),
    xy.y_axis(label="share"),
    title="Revenue mix",
)
```

## Horizontal Bars

```python
import xy

teams = ["Platform", "Growth", "Data", "Support"]
latency_ms = [42, 56, 31, 73]

xy.bar_chart(
    xy.bar(
        teams,
        latency_ms,
        orientation="horizontal",
        name="latency",
    ),
    title="Median latency",
)
```

## Heatmap

```python
import numpy as np
import xy

x = np.linspace(-3, 3, 160)
y = np.linspace(-2, 2, 120)
xx, yy = np.meshgrid(x, y)
z = np.exp(-(xx**2 + yy**2)) + 0.3 * np.exp(-((xx - 1.5) ** 2 + (yy + 0.8) ** 2))

xy.heatmap_chart(
    xy.heatmap(z, x=x, y=y),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Heatmap",
)
```

## Statistical, Density, And Facet Charts

The statistical marks keep their source arrays in the canonical column store,
then ship compact segment, rectangle, or occupied-bin geometry:

```python
import xy

x = [0, 1, 2, 3]
lower = [0.8, 1.1, 1.4, 1.9]
upper = [1.2, 1.8, 2.1, 2.8]
y = [1.0, 1.4, 1.7, 2.3]
stderr = [0.1, 0.15, 0.12, 0.2]
control = [0.8, 1.0, 1.1, 1.3]
treatment = [1.1, 1.4, 1.6, 1.9]

chart = xy.chart(
    xy.error_band(x, lower, upper, name="confidence"),
    xy.errorbar(x, y, yerr=stderr, name="estimate"),
    xy.box(values=[control, treatment], x=["control", "treatment"]),
    xy.violin(values=[control, treatment], x=["control", "treatment"]),
    xy.ecdf(values=control, bins=256),
    xy.x_axis(label="group"),
    xy.y_axis(label="value"),
)
chart
```

For dense point data, `hexbin` uses the native 2-D bin kernel and `contour`
uses bounded regular-grid marching squares. `step`, `stairs`, and `stem`
provide the common discrete-series variants without changing the line/segment
transport model.

Small multiples repeat a composition over a table column and share domains by
default:

```python
import xy

data = {
    "x": [0, 1, 2, 0, 1, 2],
    "y": [1, 2, 3, 3, 2, 1],
    "region": ["west", "west", "west", "east", "east", "east"],
}

grid = xy.facet_chart(
    xy.scatter(x="x", y="y", density=None),
    by="region",
    data=data,
    cols=3,
    share_x=True,
    share_y=True,
)
grid
```

Each panel retains the normal screen-bounded payload and can also be exported
as SVG or a browser-free native PNG grid.

## Composition API

Marks resolve column names through `data=`, so charts can bind straight to a
dict, DataFrame, or any mapping of columns:

```python
import xy

data = {
    "channel": ["Search", "Ads", "Email", "Direct"],
    "desktop": [120, 94, 72, 66],
}

chart = xy.bar_chart(
    xy.bar(x="channel", y="desktop", data=data, name="Desktop"),
    xy.x_axis(label="channel"),
    xy.y_axis(label="conversions"),
    xy.legend(),
    title="Composed bar chart",
)
chart
```

Composed `Chart` objects expose `to_html(...)`, `html(...)`, `_repr_html_()`,
`to_png(...)`, `to_svg(...)`, `to_image(...)`, `write_image(...)`, `widget()`,
`show()`, and `memory_report()` readout methods directly.
`to_image(format="png", ...)` returns bytes and `write_image(path, ...)` writes
one file atomically with the format inferred from its extension; together they
are the unified export surface across PNG/JPEG/WebP/SVG/PDF (and standalone
HTML for `write_image`). `xy.write_images(figs, paths)` is the batch form: it
accepts composed charts directly and shares one persistent Chromium session
across every browser-resolved file instead of paying browser startup per
figure.

Export defaults travel with the chart. `xy.export_config(...)` is a chart child
taking `formats`, `filename`, `width`, `height`, `scale`, `background`, and
`quality`; it sets the browser modebar's download menu (the client-safe subset
png/jpeg/webp/svg/csv, in the given order — an empty list hides the menu) and
supplies the `width`/`height`/`scale`/`background`/`quality` defaults for any
of those arguments omitted from `to_image`, `write_image`, or that chart's
files in `write_images`. Explicit arguments override them.

## Live Data On A Composed Chart

The data plane of a `Chart` is live — stream new points and read exact rows
or selections from Python. Structure stays declarative: adding marks, axes,
or annotations means composing a new chart.

```python
import xy

chart = xy.scatter_chart(
    xy.scatter(x=[0.0, 1.0, 2.0, 3.0], y=[0.0, 2.0, 4.0, 6.0], name="stream"),
    xy.x_axis(label="t"),
    xy.y_axis(label="value"),
)

# Streaming append: extends the trace in place. With a live widget the
# client refreshes; headless, the next widget()/to_html() ships the
# streamed state (already-exported HTML files are snapshots).
chart.append(0, [4.0], [8.0])

# Exact source-row readout from the canonical f64 store.
row = chart.pick(0, 4)
assert row["x"] == 4.0 and row["y"] == 8.0

# Python-side box select: the same Selection object on_select receives.
selection = chart.select_range(0.5, 3.5, 0.0, 10.0)
assert len(selection) == 3
xs, ys = selection.xy(0)
chart
```

## Layered Composition And Annotations

Use the neutral `xy.chart(...)` container when marks need to share a panel.
Children are painted in order, and rules, bands, and text annotations live in
the chart chrome instead of becoming data traces.

```python
import xy

data = {
    "month": ["Jan", "Feb", "Mar", "Apr"],
    "actual": [12, 18, 16, 22],
    "target": [14, 15, 17, 20],
    "sample": [13, 19, 15, 23],
}

chart = xy.chart(
    xy.bar(x="month", y="actual", data=data, name="actual", color="#f59e0b"),
    xy.scatter(x="month", y="sample", data=data, name="samples", color="#2563eb", size=8),
    xy.line(x="month", y="target", data=data, name="target", color="#dc2626", width=2),
    xy.x_band("Feb", "Apr", text="campaign", color="#7c3aed", opacity=0.12),
    xy.vline("Mar", text="release", color="#7c3aed"),
    xy.x_axis(label="month"),
    xy.y_axis(label="pipeline"),
    xy.tooltip(
        fields=["month", "actual", "sample", "target"],
        title="{month}",
        format={"actual": ".1f", "sample": ".1f", "target": ".1f"},
    ),
    xy.legend(),
    title="Layered pipeline",
)
chart
```

```python
import xy

z = [
    [0.2, 0.4, 0.5],
    [0.5, 0.7, 0.9],
]

chart = xy.chart(
    xy.heatmap(z=z, x=["Mon", "Tue", "Wed"], y=["AM", "PM"], name="load"),
    xy.hline("PM", text="busy threshold", color="#dc2626", width=2),
    xy.text("Wed", "PM", "peak", dx=8, dy=-8, color="#111827"),
    xy.arrow("Mon", "AM", "Tue", "PM", text="ramp", color="#7c3aed"),
    xy.callout("Wed", "PM", "ops review", dx=-72, dy=-26, color="#0f172a"),
    xy.x_axis(label="day"),
    xy.y_axis(label="shift"),
    title="Annotated heatmap",
)
chart
```

## Framework Chrome Hooks

Legend and tooltip nodes can carry opaque framework components for adapters
without making `xy` depend on that framework. The objects are kept on
the Python `Chart` and never serialized into standalone HTML.

```python
import xy

# In a Reflex app these could be rx.box(...), rx.vstack(...), etc.
class FrameworkComponent:
    pass


data = {"x": [1.0, 2.0], "y": [2.0, 3.0], "segment": ["enterprise", "growth"]}
custom_legend = FrameworkComponent()
custom_tooltip = FrameworkComponent()

chart = xy.chart(
    xy.scatter(x="x", y="y", color="segment", data=data),
    xy.legend(custom_legend, show=False),
    xy.tooltip(custom_tooltip, show=False, fields=["x", "y", "segment"]),
)

chrome = chart.chrome_components()
# {"legend": custom_legend, "tooltip": custom_tooltip}
chart
```

`show=False` disables the built-in DOM legend/tooltip for adapter replacement.
Leaving it at the default keeps the safe built-in fallback for notebooks and
standalone `.html` export.
The returned chrome object is a keyed slot map; framework adapters should mount
`chrome["legend"]` and `chrome["tooltip"]` by name beside the chart container.
