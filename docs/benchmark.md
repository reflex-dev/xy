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

The stable category IDs live in `benchmarks/categories.py`. CI's
`benchmark.json` includes the full registry plus `tracked_categories`, and the
fastcharts-only benchmark rows include `benchmark_categories` so future
dashboards can group results by these goals.

| ID | Category | Status | Why it matters | Primary metrics | Current / planned harness | Goal |
|---|---|---|---|---|---|---|
| `small_data_startup` | Small-data startup | tracked | Everyday charts should feel instant; a performance library cannot only win at 10M rows. | time-to-first-render, JS payload, Python overhead | `benchmarks/bench_vs.py --ttfr` at 1k-100k | Beat Plotly/Bokeh/Altair on first interactive paint for common charts. |
| `medium_direct_scatter` | Medium direct scatter | partial | Proves exact marker rendering, hover, color, and size channels before aggregation kicks in. | FPS, TTFR, memory, payload bytes/point, hover latency | `benchmarks/bench_vs.py` at 100k-200k; browser interaction probes planned | Smooth exact WebGL scatter with bounded bytes/point and no JSON-number payload cliff. |
| `huge_scatter_overview` | Huge scatter overview | tracked | Proves screen-bounded rendering for datasets larger than the browser should draw point-for-point. | ingest/bin time, density payload size, peak memory, TTFR | `bench_scatter_native.py`, `bench_vs.py`, example app assets | Keep resident/render payload flat in N while showing truthful density summaries. |
| `adaptive_scatter_drilldown` | Adaptive scatter drilldown | planned | The large-data claim needs a credible path from overview to exact visible points. | visible-query latency, tier-switch latency, exact-point recovery, badge accuracy | planned spatial-index/tile benchmark | Exact points when visible count is under budget; sampled/density with explicit counts otherwise. |
| `huge_line_time_series` | Huge line / time series | tracked | Common observability and finance workload; Plotly-resampler sets the bar here. | decimation time, zoom re-decimation latency, TTFR, extrema preservation | `benchmarks/bench.py`, `bench_native.py` | Screen-bounded line payloads with extrema-preserving decimation and fast zoom refresh. |
| `many_chart_dashboards` | Many-chart dashboards | planned | Plotly-class apps often fail from total page weight and many live canvases, not one chart. | total TTFR, memory, CPU after idle, number of charts before degradation | planned dashboard benchmark | Load 10-50 interactive charts with lower total memory and faster first usable dashboard than Plotly/Bokeh. |
| `interaction_smoothness` | Interaction smoothness | planned | Users judge performance by pan/zoom/hover, not just export time. | pan/zoom FPS, wheel latency, hover latency, selection latency | planned browser automation benchmark | Stay responsive during interaction, then refine view after interaction settles. |
| `payload_export_size` | Payload/export size | tracked | Notebooks, static HTML, docs, and dashboards pay for every byte shipped. | standalone HTML bytes, binary payload bytes, bundle bytes | `bench_vs.py`, `bench_scatter_native.py`, example app asset sizes | Keep data payloads binary and screen-bounded where possible; warn when exact export would be huge. |
| `core_2d_chart_breadth` | Core 2D chart breadth | tracked | The library needs to stay fast beyond the scatter wedge: bars, histograms, areas, and heatmaps are everyday chart workloads. | payload-prep time, payload bytes, standalone HTML bytes, TTFR | `benchmarks/bench_2d_charts.py` smoke/standard profiles vs Plotly | Beat Plotly on user-visible first paint for common 2D charts while keeping payloads comparable or smaller. |

Mode labels in benchmark output should stay explicit: `direct`, `decimated`,
`density`, `sampled`, or `adaptive`. A 10M density result is a real large-data
visualization result, but it is not the same claim as 10M individually styled
markers. The benchmark reports should make that distinction impossible to miss.

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

Environment note: Cargo was not available in this shell, so the fastcharts row
uses the NumPy fallback backend. CI should regenerate these rows with the native
backend in the non-blocking benchmark job.

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

---

## Core 2D chart benchmark — fastcharts vs Plotly

The regular 2D chart harness lives in `benchmarks/bench_2d_charts.py`. It
compares the new core chart families against Plotly: histogram, area, simple
bar, grouped bar, stacked bar, and heatmap. It reports payload-prep time,
payload bytes (excluding JS runtime), standalone HTML bytes, and optional
headless-Chromium TTFR.

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

---

## Headline — 10 M points

| library | total time | peak memory | render payload | points/sec |
|---|---|---|---|---|
| **fastcharts** | **86 ms** | **2 MB** | **768 KB** | 117,000,000 |
| matplotlib (Agg→PNG) | 3,230 ms | 553 MB | 41 KB PNG | 3,096,100 |
| Plotly `Scattergl` (→PNG) | 33,907 ms | 1,584 MB | 49 KB PNG | 294,923 |
| Plotly `Scatter` (SVG) | — did not finish (over budget at 3 M) | | | |

At 10 M points fastcharts is **~37× faster than matplotlib** and **~394× faster
than Plotly's WebGL path**, using **~250×–790× less memory**. Plotly's SVG path
never reached 10 M — it took 113 s at 3 M.

> Fairness note (important): fastcharts' "total" is *prepare-the-GPU-payload*
> (encode/bin kernel-side); matplotlib and Plotly "total" is *to pixels* (a PNG).
> Adding fastcharts' actual browser render — ~150 ms at 10 M under software GL
> (SwiftShader, measured separately by `benchmarks/bench_scatter_native.py --render`) — puts
> it at ~236 ms end-to-end: still ~14× faster than matplotlib and ~140× faster
> than Plotly-GL, at a fraction of the memory. On real GPU hardware the render is
> faster still. The cleanest apples-to-apples columns are **peak memory**,
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
threshold (200 k) — 0.08 B/pt at 10 M. Peak memory stays at 2 MB regardless of N.

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

1. **fastcharts is the only one flat in N.** Above the density threshold its
   payload (768 KB) and peak memory (2 MB) do not grow with point count, and
   total time grows only with the linear ingest/bin pass (35 ms to bin 10 M).
   matplotlib grows ∝ N in time *and* memory; both Plotly paths grow ∝ N in
   memory and render time.
2. **Memory is the starkest axis.** At 10 M: fastcharts 2 MB vs matplotlib
   553 MB vs Plotly-GL 1.58 GB. This is the §1/§27 thesis — one screen-bounded
   representation vs holding every point (and its copies) resident.
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
