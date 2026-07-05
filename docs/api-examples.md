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
The composition layer delegates to the same `Figure` engine, but its component
names, event payloads, and future overlay grammar are still experimental before
1.0.

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
| Horizontal bars | `Figure().bar(categories, values, orientation="horizontal")` | `fc.bar_chart(fc.bar(..., orientation="horizontal"))` |
| Heatmap | `Figure().heatmap(z, x=x, y=y)` | `fc.heatmap_chart(fc.heatmap(...))` |

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

Composed `Chart` objects expose the same `to_html(...)`, `to_png(...)`,
`widget()`, `show()`, and `memory_report()` readout methods as `Figure`.
