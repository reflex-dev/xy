<h1 align="center">xy</h1>

<p align="center">
  <strong>Interactive Python charts whose cost follows the screen, not the dataset.</strong>
</p>

<p align="center">
  <a href="https://github.com/reflex-dev/xy/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/reflex-dev/xy/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://app.codspeed.io/reflex-dev/xy?utm_source=badge"><img alt="CodSpeed" src="https://img.shields.io/endpoint?url=https://codspeed.io/badge.json"></a>
  <a href="pyproject.toml"><img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white"></a>
  <a href="src/"><img alt="Rust native core" src="https://img.shields.io/badge/Rust-native%20core-b7410e?logo=rust&logoColor=white"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
</p>

<p align="center">
  <a href="#highlights">Highlights</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#getting-started">Getting Started</a> ·
  <a href="#benchmark-snapshot">Benchmarks</a> ·
  <a href="#architecture">Architecture</a>
</p>

![xy CodSpeed benchmark snapshot](docs/assets/benchmark-snapshot.svg)

<p align="center">
  <sub>Latest CodSpeed run on 2026-07-11, covering 36 native benchmarks. See <a href="#benchmark-snapshot">the full benchmark notes</a> for methodology and caveats.</sub>
</p>

**xy** is an experimental Python charting engine for very large,
interactive line, scatter, density, area, histogram, bar, and heatmap charts.
It combines a native Rust compute core, binary columnar transport, WebGL2
rendering, and level-of-detail tiers so notebooks and standalone HTML exports
can stay interactive well past the point where JSON/SVG-heavy chart stacks run
out of room.

**Status:** early alpha. The core 2D surface is now in place: line, scatter,
area, histogram, bar/column, grouped/stacked bars, heatmap, error bars/bands,
box/violin/ECDF distributions, hexbin/contour density, step/stairs/stem
variants, and faceted small multiples. It includes direct rendering,
M4 line/area decimation, Tier-2 scatter density, adaptive scatter drilldown,
hover, box select/zoom, standalone HTML export, and static export (`to_svg` and
a browser-free native `to_png` — both millisecond and screen-bounded; `to_png`
also offers installed-browser fidelity with `engine=fc.Engine.chromium`).
Styling is first-class: every DOM chrome element is a CSS/Tailwind-addressable
slot, and marks take gradient fills, rounded/stroked bars, smooth curves, and
opacity. See [`docs/styling.md`](docs/styling.md) and the full design dossier
in [`docs/design-dossier.md`](docs/design-dossier.md).

## Highlights

- **Screen-bounded by design.** Large scatters aggregate into fixed-size density
  surfaces; long lines use M4 decimation, then refine as you zoom.
- **Native compute, Python ergonomics.** Rust kernels handle binning,
  decimation, and encoding while the public API stays notebook-friendly.
- **Binary payloads, not JSON number soup.** Chart specs stay small and data
  moves as GPU-ready typed buffers: f32 geometry/continuous channels and
  lossless u8 categorical codes.
- **Exact data stays in Python.** `ColumnStore` keeps canonical f64 values so
  hover, selection, and drilldown can return original rows.
- **One engine, many surfaces.** Render in Jupyter, VS Code, Colab, Marimo,
  standalone HTML, PNG/SVG export, and the Reflex example dashboard.
- **Dashboard-grade styling.** CSS/Tailwind chrome slots plus gradient fills,
  stroked/rounded bars, smooth curves, opacity, and edge-to-edge sparklines.

## How It Works

Most chart libraries write every data point out as text (`{"x": 3.14159, "y":
2.71828}`) and draw one shape per point. At ten million points the browser
drowns in parsing and shapes even though the screen only has a couple million
pixels, so most of that work is invisible. xy is built around one idea:
**cost should scale with the pixels on screen, not with how much data you
have.**

```mermaid
flowchart LR
    API["Python API<br/>fc.chart() composition"]
    STORE["ColumnStore<br/>exact f64 source of truth"]
    KERNELS["Native Rust kernels<br/>binning, M4 decimation, encode"]
    PAYLOAD["Payload builder<br/>tiny JSON spec + typed binary buffers"]
    CLIENT["WebGL2 client<br/>GPU marks + DOM chrome"]
    LOD["LOD loop<br/>pan, zoom, hover, select"]

    API --> STORE
    STORE --> KERNELS
    KERNELS --> PAYLOAD
    STORE --> PAYLOAD
    PAYLOAD --> CLIENT
    CLIENT <--> LOD
    LOD --> KERNELS
```

The three ideas that make this fast:

1. **Keep the truth in Python.** Your full-precision data never leaves the
   `ColumnStore`, so hover and selection always return exact original values.
2. **Ship bytes, not text.** Geometry and continuous values travel as raw f32;
   categorical palette codes use one byte when there are at most 256 groups.
   The browser skips number parsing entirely; only settings ride along as JSON.
3. **Draw the screen, not the dataset.** Zoomed out, a huge scatter becomes a
   fixed-size density grid; zoom in and the level-of-detail loop swaps in the
   real points for just the region you're looking at.

Net effect: a ten-million-point chart costs roughly what a few-thousand-point
chart costs, because the amount of work is bounded by your screen. The
[Architecture](#architecture) section below has the full diagram, and
[`docs/design-dossier.md`](docs/design-dossier.md) is the authoritative deep
dive.

## Stable vs. Experimental

Stable enough to build on today:

- Python 3.11+ package import and standalone HTML export.
- Core declarative composition with `fc.chart(...)`, layered marks, axes,
  annotations, legends, tooltips, event props, CSS/Tailwind-friendly DOM hooks,
  and notebook/static export methods on the composed `Chart`.
- Implemented 2D chart families: line, scatter, area, histogram, bar/column,
  grouped/stacked/horizontal bars, heatmap, error bars/bands,
  box/violin/ECDF, hexbin/contour, step/stairs/stem, and faceted small multiples.
- Binary column payloads, committed JavaScript bundles, and native Rust kernels
  bundled in every published platform wheel.

Still experimental and expected to change before 1.0:

- Reflex integration adapters, callback/event payload details, and chart
  breadth beyond the implemented 2D core.
- Large-data adaptive drilldown internals and performance thresholds.
- Compatibility shims for Plotly/Recharts-style APIs.

| Surface | Current status | Notes |
|---|---|---|
| Composition API | Stabilizing alpha | The single public chart-building API: declarative `fc.chart(...children)`, layered marks, axes, annotations, custom legend/tooltip chrome, callbacks, CSS/Tailwind hooks, and notebook/static export methods. |
| Standalone HTML export | Stable alpha | Self-contained output with bundled JS, escaped metadata, and binary payloads. |
| Native Rust backend | Stable alpha; required compute core | Used for fast ingest, binning, and decimation. Bundled in every published wheel; on a platform with no wheel and no local Rust build, the compute layer raises a clear error rather than degrading. |
| Reflex integration | Experimental | Example app exists; core `xy` has no Reflex dependency; any future adapter should use no hard Reflex dependency, or only a supported Reflex core/component package unless full Reflex is proven necessary. |
| Adaptive drilldown internals | Experimental | Thresholds and request protocol may move as the LOD engine evolves. |

## Why xy

| Problem in large charts | xy approach |
|---|---|
| JSON payloads grow with every point | Binary f32 buffers ship as widget buffers |
| SVG creates one DOM node per mark | WebGL2 draws instanced marks and line segments |
| Precision gets shaky with timestamps | f64 canonical data stays kernel-side; GPU gets recentered f32 offsets |
| Rendering 10M points is visually wasteful | Large scatters aggregate into a fixed-size density grid |
| Benchmark claims get fuzzy | Each mode reports timing, memory, payload, and backend |

## Installation

### From a published wheel (recommended — no toolchain)

```bash
pip install xy
```

That's it. The Rust core ships **as a prebuilt binary inside the wheel** — you
never compile it. Each platform wheel bundles the compiled C-ABI core, the
Python package, **and** the JavaScript client, so there's **no Rust, no Node, no
npm, no CDN** at install time. Wheels are published per platform by the release
workflow — Linux glibc **and** musl/Alpine (x86-64, aarch64, armv7), macOS
(x86-64, Apple Silicon), and Windows (x86, x64, arm64). Because the core is a
plain C ABI with no CPython ABI, one wheel per platform serves every supported
Python version. An experimental Pyodide/Emscripten WASM wheel is also built,
but does **not** yet load in-browser — the Rust core's `panic=unwind` emits a
`__cpp_exception` import Pyodide's runtime can't satisfy — so it is not part of
the supported set (see [`docs/production-readiness.md`](docs/production-readiness.md)).

### From source

Python 3.11+, `uv` (or plain `pip`), and a **Rust toolchain** are the
requirements for a source build:

```bash
git clone https://github.com/reflex-dev/xy.git
cd xy
uv venv
uv pip install -e ".[dev]"
```

- **Rust is required from source.** xy computes through a compiled Rust
  core and there is no pure-Python fallback, so a source install compiles that
  core — install [Rust via rustup](https://rustup.rs) first. On a supported
  platform you can skip the toolchain entirely: `pip install xy` pulls a
  prebuilt wheel with the core already inside. If the native core cannot be
  loaded, importing the compute layer raises a clear, actionable error that
  names the supported platforms — never a silent degrade.
- **Node is optional** — the JS client ships as a committed artifact, so you only
  need Node (18+) if you're *editing* the client source under `js/src/` and want
  to regenerate the bundle with `node js/build.mjs`. Use `node js/build.mjs
  --check` to verify the committed bundles are fresh.

CI (`install_without_rust` job) builds a no-toolchain wheel and asserts it fails
loudly on import, keeping the no-wheel behavior a defined, actionable error.

### Install/backend quick matrix

| Path | Command | Toolchain needed | Result |
|---|---|---|---|
| Published wheel | `pip install xy` | none | `native` on supported platform wheels |
| Source with Rust | `uv pip install -e ".[dev]"` | Rust (Node only for JS edits) | `native` |
| Platform/build with no native core | — | — | clear `ImportError` on first compute, naming supported platforms |

Published wheels cover Linux glibc and musl/Alpine (x86-64, aarch64, armv7),
macOS (x86-64, Apple Silicon), and Windows (x86, x64, arm64); the C-ABI core
means one wheel per platform serves every supported Python version. An
experimental Pyodide/Emscripten WASM wheel is built but does not yet load
in-browser (see [`docs/production-readiness.md`](docs/production-readiness.md)).

### Check the active backend

`import xy` is intentionally lightweight: it does not import NumPy or
load the native core. Import `xy.kernels` when you want to initialize and
inspect the compute backend:

```bash
python -c "import xy.kernels as k; print(k.BACKEND)"
```

`BACKEND` is always `native`. On a platform where the native core cannot load,
that import raises `ImportError` with remediation rather than returning a
degraded backend.

Accessing chart-building APIs such as `fc.scatter_chart` is the point
where NumPy and the compute backend may initialize. Notebook widget dependencies
stay deferred until `.widget()`/display; standalone `Chart.to_html()` reads the
bundled static client directly.

## Coming from matplotlib

Change one line and keep your plotting code:

```python
import numpy as np

import xy.pyplot as plt  # instead of: import matplotlib.pyplot as plt

x = np.linspace(0.0, 10.0, 200)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), "r--o", label="trend")
ax.legend()
# fig.savefig("chart.png") writes a browser-free native PNG
fig
```

The shim covers the high-frequency pyplot surface — `plot`/`scatter`/`bar`/
`hist`/`imshow`, format strings, `subplots(n, m)`, `twinx`, `savefig`, the
implicit-state API — and fails loudly on anything it doesn't. Compatibility
is corpus-defined and CI-enforced: see
[docs/matplotlib-compat.md](docs/matplotlib-compat.md).

## Getting Started

Create a small business chart:

```python
import xy as fc

months = [1, 2, 3, 4, 5, 6]
revenue = [42, 45, 48, 51, 55, 59]
pipeline = [35, 38, 42, 40, 46, 50]

chart = fc.line_chart(
    fc.line(months, revenue, name="revenue", color="#2563eb", width=2.0),
    fc.line(months, pipeline, name="pipeline", color="#16a34a", width=2.0),
    fc.x_axis(label="month"),
    fc.y_axis(label="USD thousands"),
    title="Revenue vs pipeline",
)
chart
```

Create a line chart:

```python
import numpy as np
import xy as fc

n = 100_000
x = np.arange(n, dtype=np.float64)
y = np.cumsum(np.random.default_rng(0).normal(size=n))

chart = fc.line_chart(
    fc.line(x, y, name="walk"),
    fc.x_axis(label="sample"),
    fc.y_axis(label="value"),
    title="Random walk",
)
chart
```

Create a colored, sized scatter plot:

```python
import numpy as np
import xy as fc

rng = np.random.default_rng(1)
x = rng.normal(size=50_000)
y = x * 0.5 + rng.normal(scale=0.6, size=len(x))

fc.scatter_chart(
    fc.scatter(
        x,
        y,
        color=y,
        size=np.abs(y),
        colormap="viridis",
        size_range=(2, 14),
    ),
    title="Correlated cloud",
)
```

Export a standalone HTML file:

```python
import numpy as np
import xy as fc

rng = np.random.default_rng(2)
x = rng.normal(size=2_000)
y = 0.35 * x + rng.normal(scale=0.4, size=len(x))

chart = fc.scatter_chart(fc.scatter(x, y), title="Standalone")
chart.to_html("chart.html")
```

### Standalone HTML Safety And CSP

`Chart.to_html()` writes one self-contained document with the JavaScript client,
JSON chart spec, and binary data blob inlined. That makes exports easy to share
from notebooks, docs, and reports with no CDN or Python kernel required.

Because standalone exports intentionally use inline scripts, strict
Content-Security-Policy deployments still need an application wrapper that
serves the JavaScript bundle separately and applies the host's nonce or hash
policy. The single-file export includes a defensive `Content-Security-Policy`
meta tag that blocks network fetches and external images while allowing the
inline scripts/styles required for a portable chart. User strings in titles,
axis labels, trace names, legends, series names, and categories are escaped
before entering inline JSON or `<title>`, and non-finite JSON metadata is
rejected instead of emitted as browser-dependent JavaScript.

`Chart.to_png()` defaults to `engine=fc.Engine.default`: the built-in Rust
rasterizer paints the same decimated payload with no browser — millisecond
export, and it works anywhere the wheel imports (no Chrome needed). Pass
`optimize=True` for the slower size-optimized indexed PNG path. Pass
`engine=fc.Engine.chromium` to screenshot the standalone HTML with an installed
supported browser. XY automatically finds
Chrome, Chromium, Edge, or `chrome-headless-shell`; set `XY_BROWSER` to an
executable path to select one explicitly. The browser sandbox is on by default —
use `sandbox=False` only for trusted HTML in CI/container environments where a
sandboxed browser cannot launch. Legacy string engine values remain deprecated
compatibility aliases.

## Example Apps

- [`examples/reflex/`](examples/reflex/) is a standalone Reflex
  dashboard that embeds generated xy line, scatter, density, histogram,
  area, bar, and heatmap charts, including large-data drilldown examples. Its
  Reflex dependency is app-local; installing `xy` itself must not pull
  in Reflex.
- [`examples/dashboard/site_overview.py`](examples/dashboard/site_overview.py)
  recreates an Ahrefs-style metrics dashboard: five edge-to-edge sparklines
  (`padding=0`, `curve="smooth"`, gradient fills) mounted into HTML cards, the
  client bundle embedded once. Shows the mark-styling + sparkline surface.
- [`docs/styling.md`](docs/styling.md) is the full styling reference — chrome
  slots, `--chart-*` tokens, and the mark-styling matrix (gradients, corners,
  strokes, curves, opacity).
- [`docs/api-examples.md`](docs/api-examples.md) has copyable examples for the
  currently implemented 2D chart families.

## The Composition API

xy has one public chart-building API: declarative composition. Charts
are built from lightweight children — marks, axes, annotations, chrome — and
take event props:

```python
import numpy as np
import xy as fc

timestamps = np.arange("2026-01-01", "2026-01-08", dtype="datetime64[h]")
values = np.sin(np.linspace(0, 12, len(timestamps)))

fc.line_chart(fc.line(timestamps, values, name="sensor A"), title="Telemetry")
```

Column names resolve through `data=`, and `on_*` props receive hover and
selection events:

```python
import xy as fc

data = {
    "gdp": [38_000, 46_000, 58_000, 71_000],
    "life": [76.1, 79.4, 81.2, 83.1],
    "continent": ["Europe", "Americas", "Asia", "Europe"],
    "pop": [12, 33, 21, 8],
}

fc.scatter_chart(
    fc.scatter(x="gdp", y="life", color="continent", size="pop", data=data),
    fc.x_axis(label="GDP per capita"),
    fc.y_axis(label="life expectancy"),
    fc.legend(),
    title="Gapminder",
    on_hover=lambda row: print(row),
    on_select=lambda sel: print(len(sel), "points"),
)
```

The neutral `fc.chart(...)` container overlays mixed marks and annotations on
one panel:

```python
import xy as fc

data = {
    "month": ["Jan", "Feb", "Mar", "Apr"],
    "actual": [12, 18, 16, 22],
    "target": [14, 15, 17, 20],
}

chart = fc.chart(
    fc.bar(x="month", y="actual", data=data, name="actual", color="#f59e0b"),
    fc.line(x="month", y="target", data=data, name="target", color="#dc2626"),
    fc.vline("Mar", text="release", color="#7c3aed"),
    fc.callout("Apr", 22, "best month", dx=-70, dy=-26),
    fc.tooltip(fields=["month", "actual", "target"], title="{month}"),
    fc.x_axis(label="month"),
    fc.y_axis(label="pipeline"),
    fc.legend(),
    title="Layered pipeline",
)
chart
```

Composed charts render in Jupyter, VS Code, Colab, Marimo, and standalone HTML
through the same engine.

The composition contract we are locking is intentionally narrow and durable:
children are lightweight Python specs; `fc.chart(...)` can layer marks,
annotations, axes, legends, tooltips, themes, and interaction config in one
panel; `Chart` exposes `widget()`, `show()`, `to_html(...)`, `html(...)`,
`_repr_html_()`, `to_png(...)`, and `memory_report()` directly;
`class_name`, `class_names`, and `style` reach stable DOM slots for CSS/Tailwind
styling (see [`docs/styling.md`](docs/styling.md) for the full slot + token
reference and the zero-specificity defaults contract); and opaque framework
objects passed to `fc.legend(...)` /
`fc.tooltip(...)` are returned by `chrome_components()` /
`reflex_components()` without being serialized into standalone HTML. Python
`on_*` callbacks stay widget-side: standalone HTML receives only the safe
interaction flags needed for browser hover, click, brush, selection, and
view-change behavior.

`chrome_components()` returns a keyed slot map, for example
`{"legend": my_legend, "tooltip": my_tooltip}`. Adapters should mount those
objects by slot name next to the XY HTML/widget container; it is not an
iterable child list.

### Styling the marks

Beyond the CSS/Tailwind chrome slots, the marks themselves take styling props
that speak CSS — gradient fills, rounded/stroked bars, smooth curves, opacity,
and full CSS-alpha colors (`docs/styling.md`):

```python
import numpy as np
import xy as fc

x = np.arange(24.0)
y = np.abs(np.sin(x / 4.0)) * 10 + 2

# The dashboard-sparkline look: smooth curve + gradient fading to the baseline
fc.area_chart(
    fc.area(
        x, y, color="#3b82f6", curve="smooth", opacity=0.5,
        fill="linear-gradient(currentColor, transparent)",
    ),
    padding=0,
)

# Rounded-top, gradient bars — corner_radius=(tip, base) rounds only the value end
fc.bar_chart(
    fc.bar(
        ["Q1", "Q2", "Q3", "Q4"], [4.0, 7.0, 5.0, 8.0],
        corner_radius=(6, 0), stroke="#1d4ed8", stroke_width=1.5,
        fill="linear-gradient(to top, #1e40af, #93c5fd)",
    ),
)
```

For a chrome-less, edge-to-edge sparkline, `padding=0` fills the box and
`tick_label_strategy="none"` (with transparent grid/axis colors) hides the axes.

## Benchmark Snapshot

Benchmarks live in [`benchmarks/`](benchmarks/). The cross-library harness now
compares xy with matplotlib, seaborn, Plotly, Bokeh, Altair,
Datashader, and hvPlot/HoloViews.

The benchmark program tracks separate performance categories rather than one
blurry "fastest" number: small-data startup, medium exact scatter, huge scatter
overview, adaptive scatter drilldown, huge line/time-series, many-chart
dashboards, interaction smoothness, payload/export size, and core 2D chart
breadth, plus input ingestion, streaming updates, and static export. See
[`docs/benchmark.md`](docs/benchmark.md) for the category goals and fairness
notes. The stable category IDs are emitted in `benchmark.json` and attached to
the xy-only benchmark rows as `benchmark_categories`. JSON benchmark
artifacts also include a schema version and `environment` block with Python,
platform, package, executable, and git metadata so performance claims keep their
run context. The benchmark verifier rejects non-finite, negative, or
non-positive work-size metrics so dashboards cannot publish impossible numbers.

Run the expanded comparison:

```bash
uv pip install matplotlib seaborn plotly kaleido bokeh altair datashader hvplot psutil
uv run python benchmarks/bench_vs.py --sizes 1e3,1e4,1e5,1e6 --budget 45 --json benchmark.json
make check-benchmark-report BENCHMARK_JSON=benchmark.json BENCHMARK_KIND=scatter-vs
```

Run `make check-benchmark-harness` after editing benchmark harness code,
environment metadata, report validation, or regression comparison scripts.

Run `make check-claims` after editing README/docs/package metadata or copying
benchmark numbers into public-facing text.

Run the xy kernel/payload benchmarks:

```bash
uv run python benchmarks/bench.py --sizes 1e5,1e6,1e7
uv run python benchmarks/bench_native.py --sizes 1e5,1e6,1e7
python benchmarks/bench_scatter_native.py --sizes 1e5,1e6,1e7 --production
# High-memory ceiling probe; fixture construction remains outside timing:
python benchmarks/bench_scatter_native.py --sizes 1e9 --production \
  --large-numpy-generator --native-png --json scatter-1b.json
python benchmarks/bench_scatter_native.py --sizes 1e9 --production \
  --large-numpy-generator --categorical-groups 24 --native-png \
  --json scatter-categorical-1b.json
python benchmarks/bench_heatmap_native.py --sides 32768 --reps 1 \
  --json heatmap-1b.json
# 64 GiB high-water probe: 65,536² = 4,294,967,296 cells.
python benchmarks/bench_heatmap_native.py --sides 65536 --reps 1 \
  --json heatmap-4b.json
python benchmarks/bench_scatter_native.py --sizes 1e5,1e6 --render
PYTHONPATH=python uv run python benchmarks/bench_2d_charts.py --profile smoke --ttfr
PYTHONPATH=python uv run python benchmarks/bench_interaction.py --sizes 1e4,2.5e5 --json interaction.json
PYTHONPATH=python uv run python benchmarks/bench_workflows.py --profile standard --json workflows.json
```

The interaction benchmark sweeps the requested scatter sizes. Use at least one
direct size and one density-tier size; the CI/browser smoke defaults do this
with `1e4,2.5e5`. It also always adds fixed line, histogram, bar, and heatmap
rows so pan/zoom/hover/brush budgets are not scatter-only. The report verifier
fails if any of those required interaction rows disappear.

`bench_workflows.py` covers contiguous/converted/strided/datetime/list/Arrow
ingestion, line append, a stable-domain density append that incrementally
updates a real 2M+ native pyramid, and a 1M-point log autorange workload
containing negative and non-finite values.
It also covers HTML/SVG/native-PNG/Chromium-PNG export. The dashboard benchmark attempts 10, 20, and 50 charts,
records per-chart context loss/restoration, initial and scrolled visibility, JS
heap, and redraw submission pacing, then reports the largest loss-free nonblank
count without discarding partial-dashboard metrics.

### 10M-point native benchmark

Measured by the `benchmark-refresh` CI workflow on 2026-07-08 (Ubuntu, native
Rust backend) — every library in one consistent run of `benchmarks/bench_vs.py`.
`Total` is build + static render, timed with no memory tracer active; `Peak`
is the tracemalloc peak from a separate untimed pass over the same pipeline
(transient working buffers included); `Resident Δ` is the lasting RSS growth
across the timed pass. See [`docs/benchmark.md`](docs/benchmark.md) for the
full tables and fairness notes.

| Library | Target | Total | Peak mem | Resident Δ | Payload / output |
|---|---|---:|---:|---:|---:|
| xy | GPU binary payload | **169 ms** | **126 MB** | **+10 MB** | **832 KB** |
| matplotlib | Agg PNG | 3,239 ms | 553 MB | +223 MB | 42 KB |
| Seaborn | matplotlib/Agg PNG | 7,918 ms | 1,088 MB | +695 MB | 32 KB |
| Plotly `Scattergl` | Kaleido PNG | 54,064 ms | 1,584 MB | +382 MB | 49 KB |
| Plotly `Scatter` | SVG/Kaleido | over budget above 1M | 184 MB at 1M | — | 109 KB at 1M |

That cross-library table is the retained 2026-07-08 artifact. A 2026-07-12
native production refresh after fused full-domain binning/sampling measured XY at
**5.4 ms / 258 KB for 10M** and **28.0 ms / 258 KB for 100M**. The large rows
are screen-bounded density overviews, not exact-marker draws.

An opt-in 64 GiB ceiling run additionally verified a **1B-point** production
density overview in **256.2 ms / 258 KB**, followed by a **0.68 ms** native PNG
render through the compact density opcode (**256.9 ms source-to-PNG**;
`visible` remains exactly 1B; 14.90 GiB
canonical f64 input, 24.04 GB peak RSS, no swap). An earlier same-host
24-label categorical overview completed source-to-PNG in
**352.2 ms** with a **544 KiB**
wire payload. Fixture generation is
excluded, and this is explicitly not a billion individual markers.

A separate schema-verified native static-heatmap ceiling reached
**32,768×32,768 = 1,073,741,824 cells**: **10.71 ms source-to-PNG**, including
7.75 ms Figure construction, 0.06 ms borrowed-span preparation, and a
**2.91 ms** native 900×420 PNG stage. Static export owns no grid payload: it
borrows the exact 8.0 GiB canonical f64 matrix for the synchronous Rust call,
peaks at 8.0 GiB RSS with no swap, and excludes its 574 ms deterministic
fixture construction. This is a local
screen-sized static export; shipping a 4 GiB interactive browser payload is
not the recommended huge-heatmap architecture.

The 64 GiB high-water run pushed the same path through
**65,536×65,536 = 4,294,967,296 cells**, crossing the 32-bit total-count
boundary: **36.49 ms source-to-PNG**, including 18.96 ms Figure construction,
0.07 ms span preparation, and 17.45 ms native rendering. It borrowed the
32.0 GiB canonical matrix with zero owned grid payload, reached 25.3 GiB
maximum resident memory / 32.0 GiB peak footprint, and reported no swap.
The 3.77 s deterministic allocation fixture was excluded.

These rows intentionally name different targets: XY binary preparation
versus Agg/Kaleido PNG production. They demonstrate scaling, payload, and memory
behavior, not a same-render-target "x times faster" claim. Ingest is zero-copy
for well-formed f64 arrays (the canonical store holds a reference, not a
duplicate), so the 126 MB peak is transient working buffers. What lasts is
screen-bounded; the current density wire is about 258 KB, while that retained
artifact measured ~10 MB of resident growth,
versus +223–695 MB for the raster libraries. (The payload-only native benchmark in
[`docs/benchmark.md`](docs/benchmark.md) reports the payload-build allocation
in isolation, where it stays near 2 MB regardless of N.)

### Core 2D benchmark

Measured by the `benchmark-refresh` CI workflow on 2026-07-08 (Ubuntu, native
Rust backend, headless-Chrome TTFR). `Speedup` is total payload-prep time
(Plotly's `total` ÷ xy' `total`); the harness warms each library once
before timing so no row is charged a one-time cold-start. Rows are interactive
sizes where a browser TTFR was measured.

| Chart | Workload | Speedup vs Plotly | Payload reduction vs Plotly | TTFR speedup vs Plotly |
|---|---|---:|---:|---:|
| Histogram | 10k values / 200 bins | 17.3x faster | 33.4x smaller | 5.0x faster |
| Area | 10k samples | 17.2x faster | 1.9x smaller | 4.0x faster |
| Bar | 100 categories | 11.3x faster | 2.5x smaller | 3.8x faster |
| Grouped bar | 100 categories x 4 | 4.5x faster | 2.1x smaller | 4.1x faster |
| Stacked bar | 100 categories x 4 | 4.5x faster | 1.7x smaller | 5.1x faster |
| Heatmap | 50 x 50 cells | 32.2x faster | 3.4x smaller | 4.6x faster |

Payload reduction grows sharply with data size, because xy bins
Python-side and ships fixed-size rectangles while Plotly ships raw values: the
histogram payload advantage goes from 33x smaller at 10k values to **321x at
100k and 3192x at 1M**.

The same harness also measures Seaborn/Agg as a static chart-to-pixels baseline
(total-time speedup where a Seaborn-native primitive exists):

| Chart | vs Seaborn/Agg |
|---|---|
| Histogram | 61x–150x faster |
| Area | unavailable; no direct Seaborn-native area primitive |
| Bar | 328x–1329x faster |
| Grouped bar | 202x–1243x faster |
| Stacked bar | unavailable; no direct Seaborn-native stacked bar primitive |
| Heatmap | 31x–62x faster |

## What Exists

| Piece | Where |
|---|---|
| Rust core: zone maps, offset-f32 encode, M4 decimation, 2-D binning | [`src/`](src/) |
| ctypes native binding to the Rust core | [`python/xy/_native.py`](python/xy/_native.py) |
| Column store, autorange, memory accounting | [`python/xy/columns.py`](python/xy/columns.py) |
| Internal scene/engine object, payload builder, line/scatter/area/histogram/bar/heatmap traces, annotations, mark styling (gradient/stroke/radius/curve/opacity) | [`python/xy/_figure.py`](python/xy/_figure.py) |
| Composition API (the public chart-building surface) | [`python/xy/components.py`](python/xy/components.py) |
| anywidget and standalone WebGL2 client | [`js/src/`](js/src/) (parts concatenated by `js/build.mjs`) |
| Benchmarks | [`benchmarks/`](benchmarks/) |
| Tests | [`tests/`](tests/) |

## Architecture

```mermaid
flowchart LR
    subgraph PY["Python kernel / app process"]
        API["User APIs<br/>Composition API<br/>fc.chart() + marks"]
        VALIDATE["Builder validation<br/>shape, dtype, ranges"]
        STORE["ColumnStore<br/>canonical f64 data<br/>strings/categories<br/>rollback checkpoints"]
        KERNELS["Compute core<br/>native Rust C ABI<br/>(required; no fallback)"]
        PAYLOAD["Payload builder<br/>trace specs<br/>offset-f32 columns<br/>tier/mode metadata"]
        EXPORTS["Export surfaces<br/>anywidget buffers<br/>standalone HTML<br/>native or Chromium PNG"]

        API --> VALIDATE --> STORE
        STORE --> KERNELS
        KERNELS --> PAYLOAD
        STORE --> PAYLOAD
        PAYLOAD --> EXPORTS
    end

    subgraph BROWSER["Browser / notebook frontend"]
        CLIENT["xy client<br/>anywidget ESM or standalone IIFE"]
        RENDER["WebGL2 renderer<br/>instanced marks<br/>line/area strips<br/>density textures"]
        DOM["DOM chrome<br/>titles, axes, legend<br/>tooltips, modebar"]
        PICK["Interaction layer<br/>GPU picking<br/>selection masks<br/>box zoom/select"]

        CLIENT --> RENDER
        CLIENT --> DOM
        RENDER --> PICK
        DOM --> PICK
    end

    subgraph LOD["Adaptive large-data loop"]
        VIEW["View change<br/>pan, zoom, box zoom"]
        DECIDE["LOD decision<br/>direct, decimated,<br/>density, adaptive"]
        REFINE["Refine visible window<br/>M4 line decimation<br/>scatter density or exact points"]

        VIEW --> DECIDE --> REFINE
    end

    EXPORTS -- "spec JSON + typed buffers<br/>no JSON number arrays" --> CLIENT
    PICK -- "hover/select rows" --> CLIENT
    PICK -- "debounced view state" --> VIEW
    REFINE -- "new screen-bounded payload" --> PAYLOAD
```

Important properties:

- Wire format is memory format: GPU-ready f32/u8 buffers, not JSON arrays.
- Canonical data stays f64 in Python so hover/select can return exact rows.
- Builder validation uses rollback checkpoints so failed public calls do not
  partially mutate the chart's internal figure or column store.
- Long lines ship M4-decimated points for first paint and re-decimate on zoom.
- Large scatters switch to a fixed-size density surface above the threshold,
  then drill back to exact visible points when the view is small enough.
- The same trace specs feed notebooks, standalone HTML, static PNG screenshots,
  and the Reflex example app.
- Standalone HTML embeds the same spec and buffers with no Python kernel needed.

## Development

```bash
uv venv
uv pip install -e ".[dev]"
make check
```

The JavaScript client is dependency-free. `js/build.mjs` copies the ESM client
for anywidget and wraps a standalone IIFE for `Chart.to_html`.

Use `make check-full` before production-facing changes; it adds fallback tests,
JS bundle checks, Rust tests/lints/build, and the native ABI smoke. That full
gate expects Node 18+ plus `cargo`, `rustc`, and clippy
(`rustup component add clippy`). Use
`make check-sdist` and `make check-wheel` before touching packaging/docs release
surfaces; add `WHEEL_EXPECT=--expect-native` when verifying a native release
wheel. Use `make check-artifacts SDIST=/path/to/xy.tar.gz
WHEEL=/path/to/xy.whl` when CI or a release job has already produced the
artifacts and you want to verify those exact files. Use `make check-ci` after
editing workflow gates, release publishing, or benchmark artifact wiring. Use
`make check-docs` after editing README/API prose or public benchmark wording. Use
`make check-examples` after editing README snippets, `docs/api-examples.md`, or
the Reflex dashboard chart registry. Use `make check-security` after touching
standalone HTML export, tooltips, legends, labels, or browser client text
insertion. Use `make check-errors` after changing validation, public errors,
builder rollback behavior, LOD/drill mutation boundaries, or chart/widget
caching. Use `make check-api` after
changing public exports, lazy import mappings, component factories, or public
annotations. Use `make check-import` after changing `xy.__init__`,
lazy import boundaries, dependency boundaries, widget/export boundaries, or
backend import setup. Use
`make check-browser CHROMIUM=/path/to/chrome` for the split browser hardening
gates: lifecycle, visual regression, and interaction stress. The lifecycle
smoke verifies each XY demo asset across fresh loads, explicit hash
navigation, resize, scroll-bottom, fast-scroll, visibility, restore, and an
all-iframe remount/reload shell so disappearing dashboard panels fail loudly.
The visual smoke screenshots generated core families plus every XY
gallery asset except the Plotly comparison page, and the interaction smoke
budgets zoom, pan, hover, crosshair, box zoom, and brush select. CI runs these
as `Browser lifecycle smoke (Chromium)`, `Browser visual regression smoke
(Chromium)`, and `Browser interaction stress smoke (Chromium)` with Playwright
Chromium; the underlying `scripts/verify_local.py --list/--dry-run` commands
show exactly what will run.

See [`docs/contributing.md`](docs/contributing.md) for the PR checklist and
chart-type contribution guide.

## Roadmap

For chart-type ordering, see the single 2D-first
[`docs/chart-roadmap.md`](docs/chart-roadmap.md). Short version: keep hardening
the common core charts already in place, then add box/violin, pie/donut,
contour, error bars, and the rest of the Plotly-class 2D breadth
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

For release gates and the current alpha stability contract, see
[`docs/production-readiness.md`](docs/production-readiness.md).
