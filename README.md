# fastcharts

**fastcharts** is an experimental Python charting engine for very large,
interactive line and scatter plots. Its core idea is simple: chart cost should
scale with the pixels on screen, not with every point in the dataset.

It combines a native Rust compute core, binary columnar transport, WebGL2
rendering, and level-of-detail tiers so notebooks and standalone HTML exports
can stay interactive well past the point where JSON/SVG-heavy chart stacks run
out of room.

**Status:** early alpha, with the core 2D surface now in place: line, scatter,
area, histogram, bar/column, grouped/stacked bars, heatmap, direct rendering,
M4 line/area decimation, Tier-2 scatter density, adaptive scatter drilldown,
hover, box select/zoom, standalone HTML export, and a Reflex example app all
exist. See the full design dossier in
[`docs/design-dossier.md`](docs/design-dossier.md).

## Why fastcharts

| Problem in large charts | fastcharts approach |
|---|---|
| JSON payloads grow with every point | Binary f32 buffers ship as widget buffers |
| SVG creates one DOM node per mark | WebGL2 draws instanced marks and line segments |
| Precision gets shaky with timestamps | f64 canonical data stays kernel-side; GPU gets recentered f32 offsets |
| Rendering 10M points is visually wasteful | Large scatters aggregate into a fixed-size density grid |
| Benchmark claims get fuzzy | Each mode reports timing, memory, payload, and backend |

## Installation

### From a published wheel (recommended — no toolchain)

```bash
pip install fastcharts
```

That's it. The Rust core ships **as a prebuilt binary inside the wheel** — you
never compile it. Each platform wheel bundles the compiled C-ABI core, the
Python package, **and** the JavaScript client, so there's **no Rust, no Node, no
npm, no CDN** at install time. Wheels are published per platform (manylinux
Linux x86-64/arm64, macOS arm64/x86-64, Windows x86-64) by the release workflow;
because the core is a plain C ABI with no CPython ABI, one wheel per platform
serves every supported Python version.

### From source

Python 3.11+ and `uv` (or plain `pip`) are the only hard requirements:

```bash
git clone https://github.com/Alek99/charts-exp.git
cd charts-exp
uv venv
uv pip install -e ".[dev]"
```

- **Rust is optional.** If a Rust toolchain is present, the install compiles the
  fast native core. **If it isn't, the install still succeeds** as a pure-Python
  package that uses the NumPy fallback (identical results, slower ingest/
  decimation, one loud warning at import). Install is never blocked on a
  toolchain. Install Rust via [rustup](https://rustup.rs) for the fast path.
- **Node is optional too** — the JS client ships as a committed artifact, so you
  only need Node (18+) if you're *editing* the client source under `js/src/` and want to
  regenerate the bundle with `node js/build.mjs`. Use `node js/build.mjs --check`
  to verify the committed bundles are fresh.

CI (`install_without_rust` job) builds and imports a wheel on a runner with no
Rust and no Node to keep this promise honest.

## Getting Started

Create a line chart:

```python
import numpy as np
from fastcharts import Figure

n = 1_000_000
x = np.arange(n, dtype=np.float64)
y = np.cumsum(np.random.default_rng(0).normal(size=n))

fig = Figure(title="Random walk", x_label="sample", y_label="value")
fig.line(x, y, name="walk")
fig
```

Create a colored, sized scatter plot:

```python
import numpy as np
from fastcharts import Figure

rng = np.random.default_rng(1)
x = rng.normal(size=500_000)
y = x * 0.5 + rng.normal(scale=0.6, size=len(x))

Figure(title="Correlated cloud").scatter(
    x,
    y,
    color=y,
    size=np.abs(y),
    colormap="viridis",
    size_range=(2, 14),
)
```

Export a standalone HTML file:

```python
fig = Figure(title="Standalone").scatter(x, y)
fig.to_html("chart.html")
```

## Example Apps

- [`reflex_fastcharts_app/`](reflex_fastcharts_app/) is a standalone Reflex
  dashboard that embeds generated fastcharts line, scatter, density, histogram,
  area, bar, and heatmap charts, including large-data drilldown examples.

## API Styles

Use the fluent API when you want quick imperative chart construction:

```python
from fastcharts import Figure

Figure(title="Telemetry").line(timestamps, values, name="sensor A")
```

Use the composition API when you prefer declarative chart children and event
props:

```python
import fastcharts as fc

fc.scatter_chart(
    fc.scatter(x="gdp", y="life", color="continent", size="pop", data=df),
    fc.x_axis(label="GDP per capita"),
    fc.y_axis(label="life expectancy"),
    fc.legend(),
    title="Gapminder",
    on_hover=lambda row: print(row),
    on_select=lambda sel: print(len(sel), "points"),
)
```

Both APIs render in Jupyter, VS Code, Colab, Marimo, and standalone HTML through
the same engine.

## Benchmark Snapshot

Benchmarks live in [`benchmarks/`](benchmarks/). The cross-library harness now
compares fastcharts with matplotlib, seaborn, Plotly, Bokeh, Altair,
Datashader, and hvPlot/HoloViews.

The benchmark program tracks separate performance categories rather than one
blurry "fastest" number: small-data startup, medium exact scatter, huge scatter
overview, adaptive scatter drilldown, huge line/time-series, many-chart
dashboards, interaction smoothness, and payload/export size. See
[`docs/benchmark.md`](docs/benchmark.md) for the category goals and fairness
notes. The stable category IDs are emitted in `benchmark.json` and attached to
the fastcharts-only benchmark rows as `benchmark_categories`.

Run the expanded comparison:

```bash
uv pip install matplotlib seaborn plotly kaleido bokeh altair datashader hvplot psutil
uv run python benchmarks/bench_vs.py --sizes 1e3,1e4,1e5,1e6 --budget 45
```

Run the fastcharts kernel/payload benchmarks:

```bash
uv run python benchmarks/bench.py --sizes 1e5,1e6,1e7
uv run python benchmarks/bench_native.py --sizes 1e5,1e6,1e7
python benchmarks/bench_scatter_native.py --sizes 1e5,1e6,1e7 --render
PYTHONPATH=python uv run python benchmarks/bench_2d_charts.py --profile smoke --ttfr
```

### 10M-point native benchmark

These CI numbers use the native Rust backend on Ubuntu. See
[`docs/benchmark.md`](docs/benchmark.md) for the full tables and fairness notes.

| Library | Target | Total | Peak memory | Payload / output |
|---|---|---:|---:|---:|
| fastcharts | GPU binary payload | **86 ms** | **2 MB** | **768 KB** |
| matplotlib | Agg PNG | 3,230 ms | 553 MB | 41 KB |
| Plotly `Scattergl` | Kaleido PNG | 33,907 ms | 1,584 MB | 49 KB |
| Plotly `Scatter` | SVG/Kaleido | over budget at 3M | 804 MB at 3M | 78 MB at 3M |

At 10M points, fastcharts stays screen-bounded after density aggregation: the
payload is fixed-size, and peak Python allocation stays near 2 MB.

### Core 2D benchmark

Measured locally on July 4, 2026 with the native Rust backend and headless
Chrome TTFR:

| Chart | Workload | Payload-prep vs Plotly | Payload reduction | TTFR speedup |
|---|---:|---:|---:|---:|
| Histogram | 100k values / 200 bins | 303x faster | 348x smaller | 5.89x faster |
| Area | 100k samples | 10.5x faster | 26.1x smaller | 3.19x faster |
| Bar | 1k categories | 13.4x faster | 1.53x smaller | 3.23x faster |
| Grouped bar | 1k categories x 4 | 10.3x faster | 2.06x smaller | 3.73x faster |
| Stacked bar | 1k categories x 4 | 9.17x faster | 1.60x smaller | 2.91x faster |
| Heatmap | 120 x 120 cells | 19.4x faster | 3.45x smaller | 3.06x faster |

## What Exists

| Piece | Where |
|---|---|
| Rust core: zone maps, offset-f32 encode, M4 decimation, 2-D binning | [`src/`](src/) |
| ctypes native binding and NumPy fallback | [`python/fastcharts/_native.py`](python/fastcharts/_native.py), [`python/fastcharts/_fallback.py`](python/fastcharts/_fallback.py) |
| Column store, autorange, memory accounting | [`python/fastcharts/columns.py`](python/fastcharts/columns.py) |
| Figure API, payload builder, line/scatter/area/histogram/bar/heatmap traces | [`python/fastcharts/figure.py`](python/fastcharts/figure.py) |
| Composition API | [`python/fastcharts/components.py`](python/fastcharts/components.py) |
| anywidget and standalone WebGL2 client | [`js/src/`](js/src/) (parts concatenated by `js/build.mjs`) |
| Benchmarks | [`benchmarks/`](benchmarks/) |
| Tests | [`tests/`](tests/) |

## Architecture

```text
Python process                          Browser
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ Figure / ColumnStore          │ spec   │ anywidget ESM client          │
│ f64 canonical data            │ ─────► │ WebGL2 marks + DOM chrome     │
│        │                      │ raw    │ pan/zoom = uniform update     │
│ Rust core via C ABI           │ f32    │ GPU picking + selection mask  │
│ zone maps, M4, bin_2d         │ ─────► │ density texture for big data  │
│        ▲                      │        │        │                      │
│        └── re-decimate view ◄─────────┘ debounced view changes         │
└──────────────────────────────┘        └──────────────────────────────┘
```

Important properties:

- Wire format is memory format: raw f32 buffers, not JSON arrays.
- Canonical data stays f64 in Python so hover/select can return exact rows.
- Long lines ship M4-decimated points for first paint and re-decimate on zoom.
- Large scatters switch to a fixed-size density surface above the threshold.
- Standalone HTML embeds the same spec and buffers with no Python kernel needed.

## Development

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release

node js/build.mjs
node js/build.mjs --check

uv venv
uv pip install -e ".[dev]"
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

The JavaScript client is dependency-free. `js/build.mjs` copies the ESM client
for anywidget and wraps a standalone IIFE for `Figure.to_html`.

## Roadmap

For chart-type ordering, see the single 2D-first
[`docs/chart-roadmap.md`](docs/chart-roadmap.md). Short version: keep hardening
the common core charts already in place, then add box/violin, pie/donut,
contour, error bars, annotations, and the rest of the Plotly-class 2D breadth
backlog from common charts through obscure compatibility surfaces. Long term,
the goal is Plotly-class chart breadth across BI, data science, finance,
science/engineering, product analytics, and dashboards.

- **Phase 1:** worker-side compute, SharedArrayBuffer where available, gap
  semantics, accessibility layer, filter Tier A.
- **Phase 2:** density pyramid, progressive refinement, fill-rate-aware tier
  heuristic, filter Tier B.
- **Phase 3:** CPU reference rasterizer, perceptual-diff CI, native export.
- **Phase 4:** out-of-core tiling, shared-context dashboards, filter Tier C.
- **Phase 5:** Plotly compatibility shim and generated conformance suite.
