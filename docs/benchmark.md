# Scatter benchmark: fastcharts vs Python charting libraries

The same scatter (a correlated 2-D cloud) at growing point counts, across
popular Python charting libraries, on four factors: **how many points each can
render, how fast, how much memory, and the render payload size.**

The cross-library harness lives in `benchmarks/bench_vs.py` and includes
optional adapters for fastcharts, matplotlib, seaborn, Plotly, Bokeh, Altair,
Datashader, and hvPlot/HoloViews. Missing libraries are reported as
`unavailable` rather than failing the run.

The 10M headline and full original tables below are **measured**, not cited —
produced by the CI `benchmark` job before the expanded adapter set landed
(Ubuntu, Python 3.12; fastcharts native core; Plotly via kaleido→PNG;
matplotlib `Agg`→PNG; memory via `tracemalloc` + `psutil`). The expanded adapter
table is a local benchmark run that validates the new adapters at 100k points.

Reproduce the current harness with:

```bash
pip install numpy matplotlib seaborn plotly kaleido bokeh altair datashader hvplot psutil
python benchmarks/bench_vs.py
```

The fastcharts-only arm also runs with no dependencies via
`benchmarks/bench_scatter_native.py`.

## Benchmark categories and goals

The performance story should be measured by mode, not with one blanket
"fastest charting library" number. A small exact scatter, a 10M density view, a
large line, and a 30-chart dashboard stress different parts of the system. These
are the categories we track or plan to add to CI.

The stable category IDs live in `benchmarks/categories.py`. CI's benchmark JSON
artifacts (`benchmark.json`, `line.json`, `install.json`, `interaction.json`,
`dashboard.json`, `scatter.json`, and `kernel.json`) use schema version 2:
they include the full registry,
`tracked_categories`, and a machine-readable `environment` block with Python,
platform, package, executable, git commit, and dirty-worktree metadata. The
fastcharts-only benchmark rows include `benchmark_categories` so future
dashboards can group results by these goals. The core 2D, native scatter, and
native kernel JSON reports carry the same top-level registry;
`scripts/verify_benchmark_report.py` rejects artifacts that drop it. The
verifier also requires finite numbers, positive problem sizes, and non-negative
timings, payload sizes, and rates. On success it prints a compact summary of
the report kind, row count, statuses/tiers, category counts, backend, and git
commit so CI artifacts are quick to inspect from logs.

| ID | Category | Status | Why it matters | Primary metrics | Current / planned harness | Goal |
|---|---|---|---|---|---|---|
| `small_data_startup` | Small-data startup | tracked | Everyday charts should feel instant; a performance library cannot only win at 10M rows. | time-to-first-render, JS payload, Python overhead | `benchmarks/bench_vs.py --ttfr` at 1k-100k; `test_first_payload_scatter_small` | Beat Plotly/Bokeh/Altair on first interactive paint for common charts. |
| `install_footprint_import_budget` | Install footprint and import budget | tracked | Notebook, CI, and serverless users feel package weight and cold import time before the first chart exists. | cold import time, installed distribution bytes, file count | `benchmarks/bench_install.py` | Keep fastcharts lightweight at import and smaller to install than broad plotting stacks. |
| `medium_direct_scatter` | Medium direct scatter | tracked | Proves exact marker rendering, hover, color, and size channels before aggregation kicks in. | FPS, TTFR, memory, payload bytes/point, hover latency | `benchmarks/bench_vs.py` at 100k-200k; `benchmarks/bench_interaction.py`; `test_first_payload_scatter_medium` | Smooth exact WebGL scatter with bounded bytes/point and no JSON-number payload cliff. |
| `huge_scatter_overview` | Huge scatter overview | tracked | Proves screen-bounded rendering for datasets larger than the browser should draw point-for-point. | ingest/bin time, density payload size, peak memory, TTFR | `bench_scatter_native.py`, `bench_vs.py`, `test_first_payload_density_large`, example app assets | Keep resident/render payload flat in N while showing truthful density summaries. |
| `adaptive_scatter_drilldown` | Adaptive scatter drilldown | tracked | The large-data claim needs a credible path from overview to exact visible points. | visible-query latency, tier-switch latency, exact-point recovery, badge accuracy | `benchmarks/test_codspeed_kernels.py::test_adaptive_drilldown_cycle` | Exact points when visible count is under budget; sampled/density with explicit counts otherwise. |
| `huge_line_time_series` | Huge line / time series | tracked | Common observability and finance workload; Plotly-resampler sets the bar here. | decimation time, zoom re-decimation latency, TTFR, extrema preservation | `benchmarks/bench.py`, `bench_native.py`, `bench_interaction.py`, `test_decimate_view` | Screen-bounded line payloads with extrema-preserving decimation and fast zoom refresh. |
| `many_chart_dashboards` | Many-chart dashboards | tracked | Plotly-class apps often fail from total page weight and many live canvases, not one chart. | total TTFR, memory, CPU after idle, number of charts before degradation | `benchmarks/bench_dashboard.py` | Load 10-50 interactive charts with lower total memory and faster first usable dashboard than Plotly/Bokeh. |
| `interaction_smoothness` | Interaction smoothness | tracked | Users judge performance by pan/zoom/hover, not just export time. | pan/zoom FPS, wheel latency, hover latency, tooltip stability, selection latency, frame color delta | `benchmarks/bench_interaction.py` | Stay responsive during interaction, avoid blank/flickering frames, then refine view after interaction settles. |
| `payload_export_size` | Payload/export size | tracked | Notebooks, static HTML, docs, and dashboards pay for every byte shipped. | standalone HTML bytes, binary payload bytes, bundle bytes | `bench_vs.py`, `bench_scatter_native.py`, `test_first_payload_density_large`, `test_memory_report_density_medium`, example app asset sizes | Keep data payloads binary and screen-bounded where possible; warn when exact export would be huge. |
| `core_2d_chart_breadth` | Core 2D chart breadth | tracked | The library needs to stay fast beyond the scatter wedge: bars, histograms, areas, and heatmaps are everyday chart workloads. | payload-prep time, payload bytes, standalone HTML bytes, TTFR | `benchmarks/bench_2d_charts.py` smoke/standard profiles vs Plotly and Seaborn; `bench_interaction.py`; CodSpeed core-2D payload rows | Beat Plotly on user-visible first paint for common 2D charts while tracking Seaborn raster baselines where applicable. |

Mode labels in benchmark output should stay explicit: `direct`, `decimated`,
`density`, `sampled`, or `adaptive`. A 10M density result is a real large-data
visualization result, but it is not the same claim as 10M individually styled
markers. The benchmark reports should make that distinction impossible to miss.

## Interaction, drilldown, and dashboard probes

CodSpeed is native-only and intentionally focused on hot paths that should not
regress between commits. The suite asserts `fastcharts.kernels.BACKEND ==
"native"` before timing anything. It tracks:

- Rust kernels for f32 encoding, zone maps, M4 decimation, density binning,
  histograms, normalization, and viewport range scans.
- Small/medium/large first-payload prep rows:
  `test_first_payload_scatter_small`,
  `test_first_payload_scatter_medium`,
  `test_first_payload_line_large`, and
  `test_first_payload_density_large`.
- Core 2D payload-prep rows:
  `test_first_payload_histogram_core_2d`,
  `test_first_payload_area_core_2d`,
  `test_first_payload_bar_core_2d`,
  `test_first_payload_heatmap_core_2d`, and
  `test_first_payload_composed_layered_core_2d` for the public
  `fc.chart(...)` layered API.
- Zoom refresh with `test_m4_indices_zoom` and `test_decimate_view`.
- Memory/payload accounting with `test_memory_report_density_medium`.
- The native adaptive drilldown cycle with
  `test_adaptive_drilldown_cycle`: a warmed large scatter viewport moves from
  density overview, to exact visible points, and back out to density.

That keeps CodSpeed focused on native range queries, pyramid composition,
tier-switch payload generation, payload prep, zoom latency, and memory-report
accounting instead of browser startup noise. Browser TTFR, payload bytes, peak
RSS, and cross-library comparisons remain in the schema-verified JSON reports
described below.

The JSON verifier treats `scatter-native` and `kernel-native` reports as
native-only artifacts: if their environment metadata says
`fastcharts_backend` is anything other than `native`, verification fails. That
keeps any non-native measurement from being mixed into native performance
claims.

The browser-heavy probes are opt-in scripts:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_interaction.py \
  --sizes 1e4,1e5,1e6 --json interaction.json

PYTHONPATH=python .venv/bin/python benchmarks/bench_dashboard.py \
  --chart-counts 20 --json dashboard.json
```

`bench_interaction.py` dispatches through the real `ChartView` zoom, pan, hover,
crosshair, box-zoom, and brush-select paths. It warms first-use GPU/DOM work,
records gesture percentiles, checks WebGL nonblank pixels, and emits an
`interaction_budgets_ms` block for p95 limits. The scatter rows sweep the
requested dataset sizes; the fixed core-family rows cover line, histogram, bar,
and heatmap so interaction regressions are not scatter-only. The benchmark
verifier rejects blank canvases, missing view changes, hidden crosshair chrome,
box zoom that does not narrow and restore the viewport, brush select that does
not select and clear eligible marks, blank interaction frames, tick-label
overlaps after gesture churn, unstable tooltips on pickable traces, tooltip
probes that fail to keep every repeated hover sample visible, oversized
frame-to-frame color jumps during zoom, missing budget metadata, and successful
rows whose p95 values exceed the declared budgets. It also rejects reports that
do not include successful direct scatter,
density scatter, line, histogram, bar, and heatmap interaction rows, and it
requires every per-gesture repetition count to match the report-level `reps`
value so short probes cannot masquerade as the configured budget run. The report
also declares `tooltip_sample_count`, and eligible rows must report that exact
`tooltip_visible_samples` count so a tooltip that appears once and then flickers
away fails verification.
`bench_dashboard.py` renders a mixed line/scatter/histogram/bar/heatmap
dashboard on one page and reports total chart-to-pixels startup time. Both
scripts emit schema-versioned JSON with environment metadata and benchmark
category IDs; `scripts/verify_benchmark_report.py` accepts them as
`interaction-browser` and `dashboard-browser` reports.

## Copyable claim taxonomy

Use these shapes when turning benchmark rows into README text, release notes, or
posts. The goal is to make every public claim reproducible from a row in this
document or from a verified JSON artifact.

| Claim shape | Safe wording pattern | Required context |
|---|---|---|
| Payload/prep comparison | "In the native backend smoke benchmark, histogram payload prep for 100k values / 200 bins was 303x faster than Plotly." | chart type, workload, backend, compared library, metric |
| Browser first paint | "For the measured Chrome TTFR row, the 100k-value histogram first painted 5.89x faster than Plotly." | browser/render target, workload, chart type, TTFR included |
| Large scatter overview | "The 10M scatter overview uses density mode with a 768 KB payload; it is not drawing 10M exact markers." | mode, point count, payload, exact-vs-aggregate wording |
| Line decimation | "The 10M line benchmark ships an M4-decimated ~60 KB payload while preserving the extrema oracle." | mode, point count, payload, correctness oracle |
| Install/import footprint | "In the install-footprint benchmark, cold import was 6.4 ms for the measured distribution." | benchmark name, metric, measured distribution |

Do not shorten those into broad slogans such as "fastcharts is faster than
Plotly" or "renders 10M points" without the row context. If a sentence does not
name the chart type, workload, mode, backend, metric, and render target where
they matter, it is not ready to publish.

## Time to first render (data → pixels)

Byte counts and serialize time are **not** pixels. For the browser-rendered
libraries (fastcharts, Plotly-HTML, Bokeh, Altair, hvPlot) the static-export size
says nothing about how long the browser takes to parse the embedded JS, build the
scene, and paint — often the dominant cost (Bokeh/Altair ship megabytes of JS +
data the browser must execute). So the harness measures **time-to-first-render**
directly: `benchmarks/bench_vs.py --ttfr` loads each library's output in headless
Chromium and reads First Contentful Paint (`navigationStart → first paint`, JS
inlined, no CDN, via `benchmarks/_browser.py`). Raster libraries
(matplotlib/seaborn/datashader/Plotly-kaleido) already produced pixels at render,
so their TTFR = build + render.

This closes the biggest fairness gap: previously fastcharts' number excluded the
WebGL draw while the HTML libraries' numbers excluded the browser entirely — both
stopped before pixels existed. The CI `benchmark` job now runs the TTFR pass
(capped at 100k points, since each row launches a browser) and the numbers land
in `docs/benchmark_ci.md` / the `benchmark-report` artifact. Locally, fastcharts'
standalone-export TTFR under software GL (SwiftShader) is ~180 ms for a density
page; on real GPU hardware it is lower.

## Expanded adapter benchmark — 100k points

Measured locally with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_vs.py \
  --sizes 1e3,1e4,1e5 --budget 20
```

Environment note: these fastcharts rows were captured in a shell without Cargo,
before the native core became required, so they are stale and pending a native
refresh from the non-blocking CI benchmark job. Treat them as illustrative, not
as native performance claims.

| Library | Render target | 100k total | Peak memory | Output bytes | Points/sec |
|---|---|---:|---:|---:|---:|
| fastcharts | binary payload (pending native refresh) | **1 ms** | **2 MB** | 781 KB | 156,985,881 |
| matplotlib | Agg PNG | 49 ms | 6 MB | 46 KB | 2,055,087 |
| seaborn | matplotlib PNG | 71 ms | 11 MB | 37 KB | 1,399,835 |
| Plotly `Scattergl` | Kaleido PNG | 2,018 ms | 22 MB | 61 KB | 49,558 |
| Plotly `Scatter` | Kaleido PNG | 2,835 ms | 22 MB | 107 KB | 35,269 |
| Bokeh canvas | standalone HTML | 75 ms | 14 MB | 2 MB | 1,327,770 |
| Bokeh WebGL | standalone HTML | 73 ms | 14 MB | 2 MB | 1,360,995 |
| Altair / Vega-Lite | standalone HTML | 1,846 ms | 35 MB | 5 MB | 54,171 |
| Datashader | PNG raster | 13 ms | 15 MB | 58 KB | 7,502,931 |
| hvPlot / HoloViews | Bokeh HTML | 95 ms | 17 MB | 2 MB | 1,052,353 |

---

## Core 2D chart benchmark — fastcharts vs Plotly and Seaborn

The regular 2D chart harness lives in `benchmarks/bench_2d_charts.py`. It
compares the new core chart families against Plotly and emits Seaborn rows
where Seaborn has natural primitives: histogram, simple bar, grouped bar, and
heatmap. Plotly remains the primary interactive verdict baseline for histogram,
area, simple bar, grouped bar, stacked bar, and heatmap. The harness reports
payload-prep time, payload bytes (excluding JS runtime), standalone HTML bytes,
and optional headless-Chromium TTFR.

Measured locally on July 4, 2026 with the native Rust backend
(`fastcharts backend: native`, Rust 1.96.1):

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_2d_charts.py \
  --profile smoke --ttfr --ttfr-max-work-units 200000

PYTHONPATH=python .venv/bin/python benchmarks/bench_2d_charts.py \
  --profile standard --ttfr --ttfr-max-work-units 50000
```

Environment note: TTFR probes require launching local headless Chrome; under the
Codex sandbox the probe returns `None`, so local TTFR runs need browser-launch
permission.

Seaborn rows render through matplotlib/Agg PNG. For those static raster rows,
TTFR is treated as total chart-to-pixels time because the image already exists
after payload generation. Unsupported Seaborn chart shapes, such as filled area
and stacked bars, are reported as unavailable rather than approximated with raw
matplotlib calls.

### Smoke profile with browser TTFR

| Chart | Workload | Payload-prep vs Plotly | Payload reduction | TTFR speedup | Verdict |
|---|---:|---:|---:|---:|---|
| Histogram | 100k values / 200 bins | 303x faster | 348x smaller | 5.89x faster | pass |
| Area | 100k samples | 10.5x faster | 26.1x smaller | 3.19x faster | pass |
| Bar | 1k categories | 13.4x faster | 1.53x smaller | 3.23x faster | pass |
| Grouped bar | 1k categories x 4 | 10.3x faster | 2.06x smaller | 3.73x faster | pass |
| Stacked bar | 1k categories x 4 | 9.17x faster | 1.60x smaller | 2.91x faster | pass |
| Heatmap | 120 x 120 cells | 19.4x faster | 3.45x smaller | 3.06x faster | pass |

The heatmap result uses the compact grid-texture path: one normalized scalar
grid instead of four rectangle geometry columns per cell.

### Standard profile scaling notes

The larger profile extends to 1M histogram/area samples, 10k simple bars, and a
500 x 500 heatmap. Results stayed strong:

- Histogram: 1M values produced a 4 KB fastcharts payload vs 13 MB Plotly JSON,
  with 18.6x faster payload prep on the native backend.
- Heatmap: 500 x 500 cells produced a 984 KB fastcharts payload vs 3 MB Plotly
  JSON, with 9.74x faster payload prep.
- Area: 1M samples produced an 89 KB fastcharts payload vs 21 MB Plotly JSON,
  with 4.96x faster payload prep.
- Bars: the compact bar primitive removed the previous 10k-category `watch`
  item. Simple 10k bars now ship 167 KB vs Plotly's 205 KB and prepare 4.35x
  faster; grouped 1k bars ship 42 KB vs Plotly's 86 KB.

### Native kernel microbench

The Rust core benchmark (`benchmarks/bench_native.py`) now includes the v3 chart
prep kernels: fixed-bin histogram, normalization, range selection, and
local-density lookup.

| points | histogram | normalize | range scan | bin_2d | local density |
|---:|---:|---:|---:|---:|---:|
| 100k | 0.31 ms | 3,093 Mpt/s | 0.05 ms | <1 ms | 0.55 ms / 100k |
| 1M | 3.05 ms | 3,187 Mpt/s | 0.48 ms | 3 ms | 1.11 ms / 200k |
| 10M | 29.93 ms | 3,184 Mpt/s | 4.76 ms | 30 ms | 1.14 ms / 200k |

The large scatter harness (`benchmarks/bench_scatter_native.py`) reported:

| points | tier | data prep | wire bytes | browser render |
|---:|---|---:|---:|---:|
| 100k | direct | <0.1 ms | 781 KB | 78.5 ms |
| 1M | density | 1.0 ms | 768 KB | 72.2 ms |
| 10M | density | 10.6 ms | 768 KB | not remeasured; same density payload shape as 1M |

> The kernel microbench numbers above predate the kernel-parallelization pass:
> `bin_2d`, `histogram`, `m4`, `zone_maps`, `range_indices`, `normalize` now fan
> out across cores above 512k rows (bitwise-deterministic; see `src/kernels.rs`).
> On a 4-core runner the 10M `bin_2d`/`histogram`/`m4` costs drop ~3–4× vs the
> single-threaded figures here; CI regenerates the live numbers into
> `benchmark_ci.md` each run. These committed rows stay as the conservative
> single-threaded floor until refreshed from a CI artifact.

### Line / time-series decimation — vs plotly-resampler

fastcharts' M4 decimation (Tier 1) against vanilla Plotly and plotly-resampler
(the same-thesis rival). `benchmarks/bench_line.py`; random-walk series;
aggregating libraries target ~2000 on-screen points. **Measured** by the CI
benchmark job (run 28724006099, commit `7de68f8`, Ubuntu, Python 3.12).

| N | fastcharts | plotly (vanilla) | plotly-resampler |
|---:|---:|---:|---:|
| 100k | 3.1 ms / **55.6 KB** · oracle ✅ | 412 ms / 2.1 MB | unavailable¹ |
| 1M | 6.3 ms / **58.9 KB** · oracle ✅ | 84 ms / 21.1 MB | unavailable¹ |
| 10M | 47 ms / **60.1 KB** · oracle ✅ | 816 ms / **211.2 MB** | unavailable¹ |

Payload is flat (~60 KB) regardless of N — the M4-decimated f32 blob is
screen-bounded — and the extrema oracle (methodology §2) confirms the global
y min/max survive decimation at every size. Vanilla Plotly ships the whole
series (211 MB at 10M).

¹ plotly-resampler 0.11.0 installs but fails to *import* under the CI's
Plotly 6.8 (a library-version incompatibility); the adapter degrades to an
honest `unavailable` row rather than a fabricated number. Lighting up this
comparison needs a compatible Plotly/​resampler version pin — tracked.

### Install footprint & cold import

What a `pip install` costs before the first chart draws. `benchmarks/
bench_install.py`; best-of-5 fresh-interpreter import; distribution files only
(excludes transitive deps — a lower bound). **Measured** by the same CI run.

| library | cold import | dist size |
|---|---:|---:|
| **fastcharts** | **6.4 ms** | **566 KB** |
| plotly | 39 ms | 41.2 MB |
| bokeh | 54 ms | 23.8 MB |
| matplotlib | 181 ms | 24.4 MB |
| holoviews | 259 ms | 16.8 MB |
| altair | 526 ms | 5.6 MB |
| datashader | 606 ms | 16.8 MB |
| seaborn | 1.50 s | 1.0 MB |
| hvplot | 4.65 s | 685 KB |

fastcharts imports 6–730× faster and is 40–75× smaller on disk than the
mainstream libraries (the §33 import-budget goal, made comparative).

### Regression gate (auto-generated, CI-enforced)

`scripts/check_regressions.py` runs every CI build against a committed baseline
(`benchmarks/baseline.json`) and splits metrics by how they behave on shared
runners:

- **Deterministic** — wire-payload bytes, bytes/point, and the density/direct
  tier decision are pure functions of N and the grid, byte-identical on every
  machine. These gate **hard**: a regression (the screen-bounded-payload
  invariant breaking, or a tier flipping) **fails CI**.
- **Timing** — kernel throughput / elapsed ms vary with the runner, so they're
  **advisory**: surfaced as a `::warning::` and only flagged past a 2× band, so
  a real algorithmic regression (e.g. losing the parallel path) is loud while
  noise never breaks the build.

The current metric table is regenerated (never hand-typed) into
[`docs/benchmark_metrics.md`](benchmark_metrics.md). CI uploads that table plus
the raw `scatter.json` and `kernel.json` inputs as the
`regression-benchmark-report` artifact, even when the hard regression gate
fails. Re-bless the baseline from a CI run with
`check_regressions.py --update-baseline`.

### Static image export

`Figure.to_png()` renders the standalone HTML in headless Chromium and
screenshots it — the raster matches the live WebGL chart, with no matplotlib/
kaleido-class native dependency (Chromium discovered via env/PATH/Playwright
cache). Verified by `scripts/png_export_smoke.py` (stdlib-only CI gate) and the
`Figure.to_png` tests. HTML export (`to_html`) needs nothing extra.

---

## Headline — 10 M points

Measured by the `benchmark-refresh` CI workflow on 2026-07-08 (Ubuntu, native
Rust backend), all libraries in one consistent `benchmarks/bench_vs.py` run.

| library | total time | peak memory | resident Δ | render payload | points/sec |
|---|---|---|---|---|---|
| **fastcharts** | **274 ms** | 269 MB | **+15 MB** | **832 KB** | 36,500,000 |
| matplotlib (Agg→PNG) | 3,339 ms | 553 MB | +225 MB | 42 KB PNG | 3,000,000 |
| Seaborn (Agg→PNG) | 8,452 ms | 1,088 MB | +695 MB | 32 KB PNG | 1,180,000 |
| Plotly `Scattergl` (→PNG) | 55,469 ms | 1,584 MB | +376 MB | 49 KB PNG | 180,000 |
| Plotly `Scatter` (SVG) | — over budget above 1 M | | | | |

At 10 M points fastcharts is **~12× faster than matplotlib**, **~31× faster than
Seaborn**, and **~200× faster than Plotly's WebGL path**, at **2–6× lower peak
memory**. Plotly's SVG path never reached 10 M (over budget above 1 M).

> Scope note (important): every column above is the same full-pipeline
> measurement — `total` is build + static/kernel render, and `peak memory` is the
> tracemalloc peak across it. For fastcharts that peak (269 MB) is dominated by
> the transient f64 copy of the raw 10 M points into the canonical store — a cost
> every library pays to hold the data. fastcharts' *own* screen-bounded output is
> far smaller: a fixed 832 KB density payload and ~15 MB of lasting resident
> growth. The payload-only native benchmark below measures that screen-bounded
> allocation in isolation (~2 MB, flat in N) — a different, narrower scope than
> this cross-library table. fastcharts' "total" is prepare-the-GPU-payload
> (encode/bin kernel-side) while the raster libraries' "total" is to-pixels
> (a PNG), so the cleanest apples-to-apples columns are **peak memory**,
> **payload size**, and the **ceiling**.

### Ceiling — largest N rendered under a 45 s budget

| library | max points |
|---|---|
| fastcharts | 10,000,000 (screen-bounded; not the real ceiling) |
| matplotlib | 10,000,000 |
| Plotly `Scattergl` | 10,000,000 |
| Plotly `Scatter` (SVG) | 3,000,000 |

fastcharts' 10 M here is just the largest N the harness generated; its render
cost is flat in N (density surface), so the practical ceiling is data *ingest*,
not draw — the design targets 100 M–1 B (dossier §2).

---

## Full measured tables

### fastcharts (native core; "render" = build GPU payload)

| N | build | render | total | peak mem | payload | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 1 ms | 1 ms | 1 ms | 0 MB | 8 KB | 772,927 |
| 10,000 | 1 ms | 1 ms | 1 ms | 0 MB | 78 KB | 8,803,220 |
| 100,000 | 1 ms | 1 ms | 2 ms | 2 MB | 781 KB | 63,485,614 |
| 1,000,000 | 4 ms | 6 ms | 10 ms | 2 MB | **768 KB** | 102,397,515 |
| 3,000,000 | 11 ms | 20 ms | 31 ms | 2 MB | **768 KB** | 96,223,689 |
| 10,000,000 | 35 ms | 51 ms | 86 ms | 2 MB | **768 KB** | 116,889,352 |

The payload flips from 8 B/pt (direct) to a **constant 768 KB** at the density
threshold (200 k) — 0.08 B/pt at 10 M. This table's scope is fastcharts'
payload-build allocation only, which stays near 2 MB regardless of N; the
cross-library **Headline** table above measures the full pipeline (build +
render, and the transient f64 ingest of the raw points), where fastcharts' peak
is 269 MB at 10 M and total is 274 ms — the same-harness figures to compare
against matplotlib/Seaborn/Plotly.

### matplotlib (`Agg`, `savefig` PNG)

| N | build | render | total | peak mem | PNG | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 41 ms | 197 ms | 238 ms | 4 MB | 19 KB | 4,206 |
| 10,000 | 20 ms | 128 ms | 148 ms | 1 MB | 61 KB | 67,681 |
| 100,000 | 23 ms | 139 ms | 162 ms | 6 MB | 53 KB | 618,438 |
| 1,000,000 | 56 ms | 413 ms | 469 ms | 56 MB | 43 KB | 2,132,624 |
| 3,000,000 | 103 ms | 974 ms | 1,076 ms | 166 MB | 43 KB | 2,787,179 |
| 10,000,000 | 287 ms | 2,943 ms | 3,230 ms | 553 MB | 41 KB | 3,096,100 |

Correct and robust to 10 M, but time and memory grow ∝ N; the fixed-size PNG
also means dense regions are overplotted (why density aggregation exists).

### Plotly `Scattergl` (WebGL; kaleido → PNG)

| N | build | render | total | peak mem | PNG | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 269 ms | 9,761 ms | 10,030 ms | 19 MB | 59 KB | 100 |
| 10,000 | 5 ms | 2,257 ms | 2,262 ms | 2 MB | 84 KB | 4,421 |
| 100,000 | 5 ms | 2,627 ms | 2,632 ms | 22 MB | 61 KB | 37,994 |
| 1,000,000 | 11 ms | 5,881 ms | 5,892 ms | 184 MB | 51 KB | 169,722 |
| 3,000,000 | 24 ms | 12,223 ms | 12,247 ms | 680 MB | 50 KB | 244,967 |
| 10,000,000 | 63 ms | 33,844 ms | 33,907 ms | 1,584 MB | 49 KB | 294,923 |

(The first row's 10 s is kaleido/Chromium cold-start.) Memory grows ∝ N and
crosses 1.5 GB at 10 M — consistent with the dossier's §1 multi-copy analysis.

### Plotly `Scatter` (SVG — one node per point)

| N | build | render | total | peak mem | out | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 15 ms | 2,040 ms | 2,055 ms | 1 MB | 60 KB | 487 |
| 10,000 | 5 ms | 2,559 ms | 2,564 ms | 2 MB | 106 KB | 3,901 |
| 100,000 | 5 ms | 5,858 ms | 5,863 ms | 22 MB | 107 KB | 17,057 |
| 1,000,000 | 14 ms | 43,867 ms | 43,880 ms | 184 MB | 106 KB | 22,789 |
| 3,000,000 | 23 ms | 113,400 ms | 113,423 ms | 804 MB | 78 MB | 26,450 |
| 10,000,000 | — | — | — | — | — | over budget |

The one-node-per-point wall (dossier §1): 44 s at 1 M, 113 s at 3 M, then it
falls over. This is the path fastcharts exists to replace.

---

## What the numbers show

1. **fastcharts is the only one flat in N on the output side.** Above the
   density threshold its render payload (768–832 KB) and payload-build allocation
   (~2 MB) do not grow with point count; total time grows only with the linear
   ingest/bin pass. matplotlib grows ∝ N in time *and* memory; both Plotly paths
   grow ∝ N in memory and render time.
2. **Memory is the starkest axis.** At 10 M the full-pipeline peak is fastcharts
   269 MB vs matplotlib 553 MB vs Seaborn 1.09 GB vs Plotly-GL 1.58 GB — and
   fastcharts' *lasting* resident growth is only ~15 MB (its screen-bounded
   representation) vs +225–695 MB for the raster libraries, which hold every
   point and its copies resident. Most of fastcharts' peak is the transient f64
   ingest of the raw points, released once the density surface is built. This is
   the §1/§27 thesis.
3. **The SVG path has a hard ceiling** (~1–3 M, then unusable) exactly as
   predicted; the WebGL path scales further but pays ∝ N memory and seconds of
   render time.

## Caveats

- Data generation is excluded from every timing (shared arrays).
- `render` is not identical across targets (PNG rasterize vs GPU-payload build);
  see the fairness note above. Memory, payload size, and the ceiling are the
  clean cross-library comparisons.
- fastcharts memory is Python-side `tracemalloc` peak; its GPU/native bytes are
  separate and itemized by `Figure.memory_report()` (§27). The payload column is
  the transport cost across the kernel→browser boundary.
- Single CI machine, one run; treat as order-of-magnitude, not a spec. Re-run in
  CI (`benchmark` job) or locally. No universal claims — every number is
  mode-scoped (dossier §2/§31).
