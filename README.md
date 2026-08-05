<p align="center">
  <img src="https://raw.githubusercontent.com/reflex-dev/xy/main/spec/assets/xy-sdf-binned-scatter.png" alt="XY-shaped probability field shown as a binned scatter chart." width="521">
</p>

<p align="center">
  <a href="https://github.com/reflex-dev/xy/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/reflex-dev/xy/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://app.codspeed.io/reflex-dev/xy?utm_source=badge"><img alt="CodSpeed" src="https://img.shields.io/endpoint?url=https://codspeed.io/badge.json"></a>
  <a href="pyproject.toml"><img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white"></a>
  <a href="https://reflex.dev/docs/xy/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/docs-reflex.dev-blue" alt="Docs" /></a>
  <a href="https://mybinder.org/v2/gh/reflex-dev/xy/main?urlpath=lab/tree/examples" target="_blank" rel="noopener noreferrer"><img src="https://mybinder.org/badge_logo.svg" alt="Launch the examples on Binder" /></a>
</p>

XY is an extremely fast, interactive, customizable Python charting library for
the web, notebooks, and static exports.

Charts are composed declaratively or through matplotlib conventions. You can
fully customize them with Python, CSS, or Tailwind.

With small charts, every point is sent to the browser. For large charts, the
Rust core computes only what the screen needs to display, based on its
resolution. Pan, zoom, hover, and selection can show full details by running the
same process for the new range, and a selection returns the original rows.

With XY we rendered the entirety of OpenStreetMap — a **10,000,000,000 point** dataset. [See the example →](https://github.com/reflex-dev/xy/tree/main/examples/osm)

> [!IMPORTANT]
> **XY is in alpha** and is receiving frequent enhancements.
> ⭐️ Star the repo to follow the progress.

## Is XY right for me?

XY is for Python users who want one flexible charting library for everything
from everyday plots to custom application visuals and large datasets. Build a
chart once, then use it in notebooks and web apps or export it as HTML, PNG,
SVG, or PDF.

## Installation

```bash
pip install xy

# or, with uv
uv add xy
```

## Getting started

A chart is a container plus the marks inside it. Any sequence works; NumPy is
optional.

```python
import xy

chart = xy.line_chart(xy.line([1, 2, 3, 4, 5], [120, 180, 165, 240, 310]))
# chart.to_html("chart.html")
# chart.to_png("chart.png")
# chart.to_svg("chart.svg")
chart  # notebooks render it
```

The same API scales to a hundred million points as a density surface:

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/reflex-dev/xy/main/spec/assets/xy-density-100m-dark.gif">
    <img src="https://raw.githubusercontent.com/reflex-dev/xy/main/spec/assets/xy-density-100m-light.gif" alt="A hundred-million-point spiral rendered as a density surface, then zoomed until the surface resolves into individual points." width="780">
  </picture>
</p>

```python
import numpy as np

import xy

rng = np.random.default_rng(7)
n = 100_000_000

r = 6.0 * rng.beta(1.2, 3.0, n)
theta = 2.9 * np.log1p(r) + rng.integers(0, 4, n) * (np.pi / 2) + rng.normal(0, 0.045 + 0.016 * r, n)

chart = xy.scatter_chart(
    xy.scatter(
        r * np.cos(theta),
        r * np.sin(theta),
        color=np.exp(-r / 2.2),
        colormap="magma_r",
        density=True,
        opacity=0.85,
        # Grow and solidify markers once a view drills through to real rows.
        size=2.5,
        zoom_size_factor=2.6,
        zoom_opacity=0.95,
    ),
    xy.theme(
        background="#ffffff", plot_background="#ffffff", grid_color="#e6e6e1",
        axis_color="#c3c2b7", text_color="#0b0b0b",
    ),
    title="100 million points",
)
chart
```

### Coming from matplotlib

For common pyplot workflows, change the import and keep the plotting code:

```python
import numpy as np
import xy.pyplot as plt

x = np.linspace(0, 10, 200)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), "r--", label="signal")
ax.legend()
plt.show()
```

See the [compatibility guide](https://github.com/reflex-dev/xy/blob/main/spec/matplotlib/compat.md); not all charts and
functionality are supported yet.

## Customize every layer

Use Python to control the chart, from marks and axes to interactions and layout.

- **Marks:** Control color, size, opacity, symbols, gradients, strokes, curves,
  and colormaps.
- **Guides:** Customize axes, ticks, grids, annotations, legends, colorbars, and
  tooltips.
- **Interaction:** Add pan, zoom, hover, selections, crosshairs, callbacks, and
  linked charts.
- **Layout:** Create layers and facets, set responsive dimensions, and apply
  themes.

```python
chart = xy.line_chart(
    xy.line(x, y, color="#7c3aed", width=3),
    class_name="rounded-xl bg-white",
    class_names={"tooltip": "rounded-lg bg-zinc-900 text-white"},
)
```

See the [styling guide](https://github.com/reflex-dev/xy/blob/main/docs/styling/index.md)
for examples. For a detailed breakdown of what can be customized, see the
[capability matrix](https://github.com/reflex-dev/xy/blob/main/spec/api/capability-matrix.md).

## Benchmarks

Live interactive charts, 10k to 100M points. Every library gets every row and
is driven through its own input path in a real browser. The clock stops only
when the canvas is both correct (planted sentinel points verified lit) and
stable (10 byte-identical frames), so progressive renderers are charged until
their last chunk lands.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/reflex-dev/xy/main/spec/assets/ux-render-time-dark.png">
    <img src="https://raw.githubusercontent.com/reflex-dev/xy/main/spec/assets/ux-render-time.png" alt="Time until every point is on screen, 10k to 100M points, for XY, Matplotlib, and Plotly. Lower is better." width="1200">
  </picture>
</p>

XY holds **0.071 s at 10k and 0.081 s at 100M**, flat across four orders of
magnitude, because above 200k rows it draws a screen-bounded density surface
instead of one marker per row, and zoom drills back to exact rows. Every
exact-marker path scales with N instead: Matplotlib crosses a second at ~3M
and reaches 13.4 s at 50M; Plotly crosses at ~2.5M and reaches 9.8 s at 25M.

The pale line is XY with `density=False`: the same engine drawing one marker
per row, no aggregation credit. It renders 100M exact markers in 1.34 s on
5.26 GiB.

Time until every point is on screen, in seconds. `✕` is a size the library
did not render: Plotly never finishes constructing the figure at 50M, and
Matplotlib draws at 100M but never resolves the zoom that follows.

| Points | 10k | 100k | 500k | 1M | 2.5M | 5M | 10M | 25M | 50M | 100M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| *XY speedup* | *1×* | *2×* | *3×* | *4×* | *9×* | *16×* | *34×* | *89×* | *177×* | *—* |
| **XY** | **0.071** | **0.072** | **0.075** | **0.084** | **0.083** | **0.089** | **0.083** | **0.077** | **0.076** | **0.081** |
| XY (`density=False`) | 0.085 | 0.074 | 0.087 | 0.098 | 0.111 | 0.144 | 0.206 | 0.424 | 0.645 | 1.343 |
| Matplotlib (WebAgg) | 0.086 | 0.115 | 0.224 | 0.357 | 0.758 | 1.424 | 2.804 | 6.838 | 13.385 | ✕ |
| Plotly (scattergl) | 0.341 | 0.373 | 0.477 | 0.614 | 1.033 | 1.785 | 3.367 | 9.794 | ✕ | ✕ |

Peak Python-side resident memory, in GiB. Browser memory is tracked separately
and excluded here, since a headless Chrome resides ~1 GiB before drawing
anything.

| Points | 10k | 100k | 500k | 1M | 2.5M | 5M | 10M | 25M | 50M | 100M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| *XY advantage* | *1.8×* | *1.7×* | *1.9×* | *2.1×* | *2.1×* | *2.4×* | *2.6×* | *2.9×* | *2.8×* | *—* |
| **XY** | **0.05** | **0.05** | **0.06** | **0.07** | **0.13** | **0.19** | **0.32** | **0.70** | **1.36** | **2.58** |
| XY (`density=False`) | 0.05 | 0.05 | 0.07 | 0.10 | 0.18 | 0.31 | 0.57 | 1.35 | 2.66 | 5.26 |
| Matplotlib (WebAgg) | 0.09 | 0.09 | 0.12 | 0.15 | 0.28 | 0.46 | 0.84 | 2.06 | 3.85 | ✕ |
| Plotly (scattergl) | 0.21 | 0.18 | 0.28 | 0.36 | 0.60 | 1.05 | 1.86 | 4.70 | ✕ | ✕ |

One machine (Apple M5 Pro), one run per cell; at the small end the timings
carry roughly ±10 ms of run-to-run spread.

For the environment, methodology, per-size videos, and raw results, see the
[benchmark runbook](https://github.com/reflex-dev/xy/blob/main/benchmarks/README.md) and
[competitive benchmark specification](https://github.com/reflex-dev/xy/blob/main/spec/benchmarks/results.md).

## Embed XY in a Reflex app

The Reflex integration bundled with `xy` turns any XY chart into a regular
Reflex component, with no JavaScript, iframe, or separate chart service.
Install the `reflex` extra to select a compatible framework version:

```bash
pip install "xy[reflex]"

# or, with uv
uv add "xy[reflex]"
```

The import namespace remains `reflex_xy`. Register the integration once:

```python
# rxconfig.py
import reflex as rx
import reflex_xy

config = rx.Config(
    app_name="dashboard",
    plugins=[reflex_xy.XYPlugin()],
)
```

Then add a chart anywhere in the component tree:

```python
import reflex as rx
import reflex_xy
import xy

signups = xy.line_chart(
    xy.line([1, 2, 3, 4, 5], [120, 180, 165, 240, 310]),
    title="Weekly signups",
)


def index() -> rx.Component:
    return rx.card(
        rx.heading("Growth"),
        reflex_xy.chart(signups, height="320px"),
        width="100%",
    )


app = rx.App()
app.add_page(index)
```

For state-driven charts, declare the chart in the page and supply columns from
a `@reflex_xy.data` state method — the structure (channels, colormaps, axes)
is validated when `reflex run` compiles the app, while the columns ride the
app's own websocket as binary buffers, never through Reflex state:

```python
from typing import TypedDict

import numpy as np
import reflex as rx
import reflex_xy


class CloudData(TypedDict):
    x: np.ndarray
    y: np.ndarray
    mag: np.ndarray


class Dash(rx.State):
    points: int = 200_000

    @reflex_xy.data
    def cloud(self) -> CloudData:
        rng = np.random.default_rng(7)
        x = rng.normal(size=self.points)
        y = x * 0.6 + rng.normal(scale=0.6, size=self.points)
        return {"x": x, "y": y, "mag": np.hypot(x, y)}


def dashboard() -> rx.Component:
    return reflex_xy.scatter_chart(
        data=Dash.cloud,
        x="x", y="y", color="mag", colormap="viridis",
        height="460px",
    )
```

Hover, pan, and zoom keep working. For charts driven by Reflex state, events, or
live streams, see the
[Reflex integration guide](https://reflex.dev/docs/xy/integrations/reflex/) and
the [runnable example app](https://github.com/reflex-dev/xy/tree/main/examples/reflex/).

## Examples

Each notebook fetches its rows from the linked public source; no raw datasets
are stored in this repository. Counts describe the featured chart, and the
notebooks scale further. See the
[example guide](https://github.com/reflex-dev/xy/blob/main/examples/real_world/README.md) for sources, workload controls,
and setup.

|  |  |  |
| :---: | :---: | :---: |
| **Gaia DR3 · HR diagram**<br><sub>250,000 plotted stars</sub><br><br>![Gaia DR3 stellar color versus absolute magnitude.](https://raw.githubusercontent.com/reflex-dev/xy/main/examples/real_world/assets/01-gaia-hr-diagram.png)<br><br>[Open notebook](https://github.com/reflex-dev/xy/blob/main/examples/real_world/01_gaia_hr_diagram.ipynb) | **gnomAD v4.1 · allele frequency**<br><sub>164,000 plotted variants</sub><br><br>![gnomAD allele frequency across all autosomes.](https://raw.githubusercontent.com/reflex-dev/xy/main/examples/real_world/assets/02-gnomad-allele-frequency.png)<br><br>[Open notebook](https://github.com/reflex-dev/xy/blob/main/examples/real_world/02_gnomad_allele_frequency.ipynb) | **Pan-UKBB · Manhattan plot**<br><sub>814,294 plotted variants</sub><br><br>![Pan-UKBB standing-height associations across all autosomes.](https://raw.githubusercontent.com/reflex-dev/xy/main/examples/real_world/assets/03-pan-ukbb-manhattan.png)<br><br>[Open notebook](https://github.com/reflex-dev/xy/blob/main/examples/real_world/03_pan_ukbb_manhattan.ipynb) |
| **Dukascopy · EUR/USD ticks**<br><sub>101,427 plotted ticks</sub><br><br>![Dukascopy EUR/USD midpoint quotes.](https://raw.githubusercontent.com/reflex-dev/xy/main/examples/real_world/assets/04-dukascopy-fx-ticks.png)<br><br>[Open notebook](https://github.com/reflex-dev/xy/blob/main/examples/real_world/04_dukascopy_fx_ticks.ipynb) | **LIGO · GW150914 strain**<br><sub>16,777,216 raw · 3,441 shown</sub><br><br>![GWOSC reconstructed Hanford waveform for GW150914.](https://raw.githubusercontent.com/reflex-dev/xy/main/examples/real_world/assets/05-ligo-gw150914-strain.png)<br><br>[Open notebook](https://github.com/reflex-dev/xy/blob/main/examples/real_world/05_ligo_gw150914_strain.ipynb) | **NYC TLC · taxi pickup density**<br><sub>300,000 pickup records</sub><br><br>![Locally projected NYC yellow-taxi pickup hexbin density.](https://raw.githubusercontent.com/reflex-dev/xy/main/examples/real_world/assets/06-nyc-taxi-density.png)<br><br>[Open notebook](https://github.com/reflex-dev/xy/blob/main/examples/real_world/06_nyc_taxi_density.ipynb) |

## How it works

Most chart stacks serialize every value as JSON and ask the browser to draw
every mark. XY keeps exact values in a `ColumnStore`, computes a level of detail
in Rust, and transfers typed binary buffers. Decimated and density views are
bounded by the visible result.

```mermaid
flowchart TB
    API["Python API<br/>Build the chart"]
    STORE["ColumnStore<br/>Keep canonical f64 columns"]
    CORE["Native Rust compute<br/>Direct · decimated · density"]
    PAYLOAD["Compact payload<br/>Data-less JSON spec + typed binary buffers"]
    RENDER["Browser or notebook<br/>WebGL2 marks · Canvas axes · DOM interface"]

    API --> STORE --> CORE --> PAYLOAD --> RENDER
```

So a dense overview can aggregate while a narrow view returns exact points. With
a live host, pan and zoom request a refined payload. Canonical f64 data stays in
Python, so hover and selection still return original rows.

For the full design, see the [design dossier](https://github.com/reflex-dev/xy/blob/main/spec/design-dossier.md).

## Roadmap

Broad 2D coverage first, then geographic, 3D, and volume visualization. Queued
next, no dates implied:

- **Categorical distributions:** strip, swarm, beeswarm, boxen, rug
- **Regression diagnostics:** trendline, residual, QQ, PP
- **Scatter matrix and joint plots:** SPLOM, pair grid, marginal histograms
- **Pie / donut:** `xy.pie_chart(labels, values, hole=...)` ships over
  unequal-width core polar bars, with Matplotlib-shaped helpers in `xy.pyplot`;
  nested donuts and variable-radius composition remain
- **Candlestick / OHLC and finance overlays:** SMA, VWAP, Bollinger, RSI, MACD; prototyped, awaiting a fresh landing
- **Waterfall and funnel**
- **Treemap, sunburst, and icicle**
- **Gauge / indicator:** build on the shipped polar axes and composable radial marks
- **Slope, bump, and dumbbell**
- **3D and volume:** scatter, surfaces, meshes, isosurfaces, and volumetric views

The full ranked backlog is in the [chart roadmap](https://github.com/reflex-dev/xy/blob/main/spec/api/chart-roadmap.md).
Want a chart or feature that isn't listed?
[Open an issue](https://github.com/reflex-dev/xy/issues/new).
