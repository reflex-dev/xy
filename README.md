# fastcharts

**fastcharts** is an experimental Python charting engine for very large,
interactive line and scatter plots. Its core idea is simple: chart cost should
scale with the pixels on screen, not with every point in the dataset.

It combines a native Rust compute core, binary columnar transport, WebGL2
rendering, and level-of-detail tiers so notebooks and standalone HTML exports
can stay interactive well past the point where JSON/SVG-heavy chart stacks run
out of room.

**Status:** Phase 0 is complete: lines, scatter, direct rendering, M4 line
decimation, Tier-2 scatter density, hover, box select, and standalone HTML
export all exist. See the full design dossier in
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

Python 3.9+ and `uv` (or plain `pip`) are the only hard requirements:

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
  regenerate the bundle with `node js/build.mjs`.

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
  dashboard that embeds generated fastcharts line, scatter, and density charts.

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

Run the expanded comparison:

```bash
uv pip install matplotlib seaborn plotly kaleido bokeh altair datashader hvplot psutil
uv run python benchmarks/bench_vs.py --sizes 1e3,1e4,1e5,1e6 --budget 45
```

Run the fastcharts kernel/payload benchmarks:

```bash
uv run python benchmarks/bench.py --sizes 1e5,1e6,1e7
python benchmarks/bench_scatter_native.py --sizes 1e5,1e6,1e7 --render
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

### Expanded adapter benchmark

Measured locally with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_vs.py \
  --sizes 1e3,1e4,1e5 --budget 20
```

Environment note: this machine did not have Cargo available, so the fastcharts
row below uses the NumPy fallback backend. The table is still useful for showing
that all expanded adapters run and for comparing payload styles at 100k points.

| Library | Render target | 100k total | Peak memory | Output bytes | Points/sec |
|---|---|---:|---:|---:|---:|
| fastcharts | binary payload, NumPy fallback | **1 ms** | **2 MB** | 781 KB | 156,985,881 |
| matplotlib | Agg PNG | 49 ms | 6 MB | 46 KB | 2,055,087 |
| seaborn | matplotlib PNG | 71 ms | 11 MB | 37 KB | 1,399,835 |
| Plotly `Scattergl` | Kaleido PNG | 2,018 ms | 22 MB | 61 KB | 49,558 |
| Plotly `Scatter` | Kaleido PNG | 2,835 ms | 22 MB | 107 KB | 35,269 |
| Bokeh canvas | standalone HTML | 75 ms | 14 MB | 2 MB | 1,327,770 |
| Bokeh WebGL | standalone HTML | 73 ms | 14 MB | 2 MB | 1,360,995 |
| Altair / Vega-Lite | standalone HTML | 1,846 ms | 35 MB | 5 MB | 54,171 |
| Datashader | PNG raster | 13 ms | 15 MB | 58 KB | 7,502,931 |
| hvPlot / HoloViews | Bokeh HTML | 95 ms | 17 MB | 2 MB | 1,052,353 |

## What Exists

| Piece | Where |
|---|---|
| Rust core: zone maps, offset-f32 encode, M4 decimation, 2-D binning | [`src/`](src/) |
| ctypes native binding and NumPy fallback | [`python/fastcharts/_native.py`](python/fastcharts/_native.py), [`python/fastcharts/_fallback.py`](python/fastcharts/_fallback.py) |
| Column store, autorange, memory accounting | [`python/fastcharts/column.py`](python/fastcharts/column.py) |
| Figure API, payload builder, line/scatter traces | [`python/fastcharts/figure.py`](python/fastcharts/figure.py) |
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

For chart-type ordering, see the detailed
[`docs/chart-roadmap.md`](docs/chart-roadmap.md). Short version: add histogram
next, then bar/column, area, heatmap, box/violin, and finance traces. Long term,
the goal is Plotly-class chart breadth across BI, data science, finance,
science/engineering, product analytics, and dashboards.

- **Phase 1:** worker-side compute, SharedArrayBuffer where available, gap
  semantics, accessibility layer, filter Tier A.
- **Phase 2:** density pyramid, progressive refinement, fill-rate-aware tier
  heuristic, filter Tier B.
- **Phase 3:** CPU reference rasterizer, perceptual-diff CI, native export.
- **Phase 4:** out-of-core tiling, shared-context dashboards, filter Tier C.
- **Phase 5:** Plotly compatibility shim and generated conformance suite.
