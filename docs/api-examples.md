# API Examples

These examples cover the currently implemented 2D chart families. They are
short on purpose: each one should be copyable into a notebook or script after
`pip install fastcharts`. The Python snippets in this file are executed by
`tests/test_docs_examples.py`, so docs changes should fail fast if the public
API drifts.

The library is optimized for large data, but ordinary charts should stay boring
to build. The first section below is intentionally small business-style data;
the later per-chart examples show the same APIs scaling up.

## API Stability Notes

Use the fluent `Figure` API for the most stable alpha surface today. It is the
direct path for implemented chart families, standalone HTML export, PNG export,
notebook display, and memory reporting.

Use the composition API when you want Reflex-shaped, declarative chart children,
column-name resolution through `data=`, or `on_hover` / `on_select` callbacks.
The core composition contract is now stabilizing around lightweight Python
children, layered marks, axes, annotations, built-in or custom legend/tooltip
chrome, CSS/Tailwind-friendly DOM hooks, and the same notebook/static export
methods as `Figure`. Callback payload details and future adapter packages may
still evolve before 1.0.

Both APIs accept `width="100%"` and/or `height="100%"` for responsive charts.
Standalone `to_html(...)` needs no browser dependency; `to_png(...)` needs a
local Chrome/Chromium executable because it screenshots the same standalone
HTML document.

## Chart Family Quick Reference

| Chart family | Fluent API | Composition API |
|---|---|---|
| Line | `Figure().line(x, y)` | `fc.line_chart(fc.line(...))` |
| Scatter | `Figure().scatter(x, y)` | `fc.scatter_chart(fc.scatter(...))` |
| Area | `Figure().area(x, y, base=0.0)` | `fc.area_chart(fc.area(...))` |
| Histogram | `Figure().histogram(values, bins=...)` or `Figure().hist(...)` | `fc.histogram_chart(fc.histogram(...))` |
| Bar | `Figure().bar(categories, values)` | `fc.bar_chart(fc.bar(...))` |
| Column | `Figure().column(categories, values)` | `fc.column_chart(fc.column(...))` |
| Grouped bars | `Figure().bar(categories, matrix, mode="grouped")` | `fc.bar_chart(fc.bar(..., mode="grouped"))` |
| Stacked bars | `Figure().bar(categories, matrix, mode="stacked")` | `fc.bar_chart(fc.bar(..., mode="stacked"))` |
| Normalized bars | `Figure().bar(categories, matrix, mode="normalized")` | `fc.bar_chart(fc.bar(..., mode="normalized"))` |
| Horizontal bars | `Figure().bar(categories, values, orientation="horizontal")` | `fc.bar_chart(fc.bar(..., orientation="horizontal"))` |
| Heatmap | `Figure().heatmap(z, x=x, y=y)` | `fc.heatmap_chart(fc.heatmap(...))` |
| Candlestick | `Figure().candlestick(x, open, high, low, close)` | `fc.candlestick_chart(fc.candlestick(...))` |
| OHLC | `Figure().ohlc(x, open, high, low, close)` | `fc.ohlc_chart(fc.ohlc(...))` |

## Axes And Scales

```python
import numpy as np
import fastcharts as fc

x = np.logspace(0, 6, 240)
rank = 96 - np.log10(x) * 11.5
conversion = 0.08 + np.log10(x) * 0.035

chart = fc.chart(
    fc.line(x=x, y=rank, name="rank", color="#2563eb"),
    fc.line(x=x, y=conversion, y_axis="y2", name="conversion", color="#dc2626"),
    fc.x_axis(label="request volume", type_="log", domain=(1, 1_000_000), format=",.0f"),
    fc.y_axis(label="rank (reversed)", domain=(0, 100), reverse=True, format=".0f"),
    fc.y_axis(id="y2", label="conversion", side="right", domain=(0, 0.35), format=".0%"),
    title="Axes and scales",
)
chart
```

## Small Business Chart

```python
from fastcharts import Figure

month_number = [1, 2, 3, 4, 5, 6]
revenue = [42, 45, 48, 51, 55, 59]
pipeline = [35, 38, 42, 40, 46, 50]

fig = Figure(title="Revenue vs pipeline", x_label="month number", y_label="USD thousands")
fig.line(month_number, revenue, name="revenue", color="#2563eb", width=2.0)
fig.line(month_number, pipeline, name="pipeline", color="#16a34a", width=2.0)
fig
```

## Line

```python
import numpy as np
from fastcharts import Figure

rng = np.random.default_rng(0)
x = np.arange(1_000_000, dtype=np.float64)
y = np.cumsum(rng.normal(size=len(x)))

fig = Figure(title="Random walk", x_label="sample", y_label="value")
fig.line(x, y, name="walk")
fig
```

## Scatter

```python
import numpy as np
from fastcharts import Figure

rng = np.random.default_rng(1)
x = rng.normal(size=500_000)
y = 0.5 * x + rng.normal(scale=0.6, size=len(x))

Figure(title="Correlated scatter").scatter(
    x,
    y,
    color=y,
    size=np.abs(y),
    colormap="viridis",
    size_range=(2, 14),
)
```

## Area

```python
import numpy as np
from fastcharts import Figure

x = np.linspace(0, 10, 100_000)
y = np.sin(x) + 0.15 * x

Figure(title="Area").area(x, y, base=0.0, name="signal", opacity=0.35)
```

## Histogram

```python
import numpy as np
from fastcharts import Figure

rng = np.random.default_rng(2)
values = np.concatenate(
    [rng.normal(-1.2, 0.45, 300_000), rng.normal(1.4, 0.6, 200_000)]
)

Figure(title="Distribution").histogram(values, bins=240, name="samples")
```

Pass `cumulative=True` to accumulate bins left-to-right. Combined with
`density=True` this is the empirical CDF, whose last bin is ~1.0:

```python
import numpy as np
from fastcharts import Figure

rng = np.random.default_rng(3)
latency_ms = rng.gamma(shape=2.0, scale=40.0, size=100_000)

Figure(title="Latency CDF", x_label="ms", y_label="fraction").hist(
    latency_ms, bins=200, density=True, cumulative=True, name="p(x)"
)
```

## Bar

```python
from fastcharts import Figure

channels = ["Search", "Ads", "Email", "Direct", "Partner", "Social"]
conversions = [120, 94, 72, 66, 43, 31]

Figure(title="Conversions", x_label="channel", y_label="count").bar(
    channels,
    conversions,
    name="Desktop",
)
```

## Column

```python
from fastcharts import Figure

quarters = ["Q1", "Q2", "Q3", "Q4"]
revenue = [42, 47, 51, 58]

Figure(title="Quarterly revenue", x_label="quarter", y_label="revenue").column(
    quarters,
    revenue,
    name="Revenue",
)
```

## Grouped Bars

```python
import numpy as np
from fastcharts import Figure

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

Figure(title="Grouped channels").bar(
    channels,
    values,
    mode="grouped",
    series=["Desktop", "Mobile", "Tablet"],
)
```

## Stacked Bars

```python
import numpy as np
from fastcharts import Figure

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

Figure(title="Stacked revenue").bar(
    quarters,
    values,
    mode="stacked",
    series=["Product", "Services", "Partners"],
)
```

## Normalized Stacked Bars

`mode="normalized"` divides every stack by its per-category total, so each
category renders the series' share of the whole (segments sum to 1):

```python
import numpy as np
from fastcharts import Figure

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

Figure(title="Revenue mix", y_label="share").bar(
    quarters,
    values,
    mode="normalized",
    series=["Product", "Services", "Partners"],
)
```

## Horizontal Bars

```python
from fastcharts import Figure

teams = ["Platform", "Growth", "Data", "Support"]
latency_ms = [42, 56, 31, 73]

Figure(title="Median latency").bar(
    teams,
    latency_ms,
    orientation="horizontal",
    name="latency",
)
```

## Heatmap

```python
import numpy as np
from fastcharts import Figure

x = np.linspace(-3, 3, 160)
y = np.linspace(-2, 2, 120)
xx, yy = np.meshgrid(x, y)
z = np.exp(-(xx**2 + yy**2)) + 0.3 * np.exp(-((xx - 1.5) ** 2 + (yy + 0.8) ** 2))

Figure(title="Heatmap", x_label="x", y_label="y").heatmap(z, x=x, y=y)
```

## Composition API

```python
import fastcharts as fc

data = {
    "channel": ["Search", "Ads", "Email", "Direct"],
    "desktop": [120, 94, 72, 66],
}

chart = fc.bar_chart(
    fc.bar(x="channel", y="desktop", data=data, name="Desktop"),
    fc.x_axis(label="channel"),
    fc.y_axis(label="conversions"),
    fc.legend(),
    title="Composed bar chart",
)
chart
```

Composed `Chart` objects expose the same `to_html(...)`, `html(...)`,
`_repr_html_()`, `to_png(...)`, `widget()`, `show()`, and `memory_report()`
readout methods as `Figure`.

## Layered Composition And Annotations

Use the neutral `fc.chart(...)` container when marks need to share a panel.
Children are painted in order, and rules, bands, and text annotations live in
the chart chrome instead of becoming data traces.

```python
import fastcharts as fc

data = {
    "month": ["Jan", "Feb", "Mar", "Apr"],
    "actual": [12, 18, 16, 22],
    "target": [14, 15, 17, 20],
    "sample": [13, 19, 15, 23],
}

chart = fc.chart(
    fc.bar(x="month", y="actual", data=data, name="actual", color="#f59e0b"),
    fc.scatter(x="month", y="sample", data=data, name="samples", color="#2563eb", size=8),
    fc.line(x="month", y="target", data=data, name="target", color="#dc2626", width=2),
    fc.x_band("Feb", "Apr", text="campaign", color="#7c3aed", opacity=0.12),
    fc.vline("Mar", text="release", color="#7c3aed"),
    fc.x_axis(label="month"),
    fc.y_axis(label="pipeline"),
    fc.tooltip(
        fields=["month", "actual", "sample", "target"],
        title="{month}",
        format={"actual": ".1f", "sample": ".1f", "target": ".1f"},
    ),
    fc.legend(),
    title="Layered pipeline",
)
chart
```

```python
import fastcharts as fc

z = [
    [0.2, 0.4, 0.5],
    [0.5, 0.7, 0.9],
]

chart = fc.chart(
    fc.heatmap(z=z, x=["Mon", "Tue", "Wed"], y=["AM", "PM"], name="load"),
    fc.hline("PM", text="busy threshold", color="#dc2626", width=2),
    fc.text("Wed", "PM", "peak", dx=8, dy=-8, color="#111827"),
    fc.arrow("Mon", "AM", "Tue", "PM", text="ramp", color="#7c3aed"),
    fc.callout("Wed", "PM", "ops review", dx=-72, dy=-26, color="#0f172a"),
    fc.x_axis(label="day"),
    fc.y_axis(label="shift"),
    title="Annotated heatmap",
)
chart
```

## Framework Chrome Hooks

Legend and tooltip nodes can carry opaque framework components for adapters
without making `fastcharts` depend on that framework. The objects are kept on
the Python `Chart` and never serialized into standalone HTML.

```python
import fastcharts as fc

# In a Reflex app these could be rx.box(...), rx.vstack(...), etc.
class FrameworkComponent:
    pass


data = {"x": [1.0, 2.0], "y": [2.0, 3.0], "segment": ["enterprise", "growth"]}
custom_legend = FrameworkComponent()
custom_tooltip = FrameworkComponent()

chart = fc.chart(
    fc.scatter(x="x", y="y", color="segment", data=data),
    fc.legend(custom_legend, show=False),
    fc.tooltip(custom_tooltip, show=False, fields=["x", "y", "segment"]),
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
