# Scatter benchmark: xy vs Python charting libraries

The same scatter (a correlated 2-D cloud) at growing point counts, across
popular Python charting libraries, on four factors: **how many points each can
render, how fast, how much memory, and the render payload size.**

The cross-library harness lives in `benchmarks/bench_vs.py` and includes
optional adapters for xy, matplotlib, seaborn, Plotly, Bokeh, Altair,
Datashader, and hvPlot/HoloViews. Missing libraries are reported as
`unavailable` rather than failing the run.

The 10M headline and full original tables below are **measured**, not cited —
produced by the CI `benchmark` job before the expanded adapter set landed
(Ubuntu, Python 3.12; xy native core; Plotly via kaleido→PNG;
matplotlib `Agg`→PNG; memory via `tracemalloc` + `psutil`). The expanded adapter
table is a local benchmark run that validates the new adapters at 100k points.

Reproduce the current harness with:

```bash
pip install numpy matplotlib seaborn plotly kaleido bokeh altair datashader hvplot psutil
python benchmarks/bench_vs.py
```

The xy-only arm also runs with no dependencies via
`benchmarks/bench_scatter_native.py`.

## Benchmark categories and goals

The performance story should be measured by mode, not with one blanket
"fastest charting library" number. A small exact scatter, a 10M density view, a
large line, and a 30-chart dashboard stress different parts of the system. These
are the categories we track or plan to add to CI.

The stable category IDs live in `benchmarks/categories.py`. CI's benchmark JSON
artifacts (`benchmark.json`, `line.json`, `install.json`, `install-fresh.json`,
`interaction.json`, `dashboard.json`, `workflows.json`, `scatter.json`,
`kernel.json`, and `transport.json`) use schema version 2:
they include the full registry,
`tracked_categories`, and a machine-readable `environment` block with Python,
platform, package, executable, git commit, and dirty-worktree metadata. The
xy-only benchmark rows include `benchmark_categories` so future
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
| `install_footprint_import_budget` | Install footprint and import budget | tracked | Notebook, CI, and serverless users feel package weight and cold import time before the first chart exists. | cold import time, installed distribution bytes, file count | `benchmarks/bench_install.py` | Keep xy lightweight at import and smaller to install than broad plotting stacks. |
| `medium_direct_scatter` | Medium direct scatter | tracked | Proves exact marker rendering, hover, color, and size channels before aggregation kicks in. | FPS, TTFR, memory, payload bytes/point, hover latency | `benchmarks/bench_vs.py` at 100k-200k; `benchmarks/bench_interaction.py`; `test_first_payload_scatter_medium` | Smooth exact WebGL scatter with bounded bytes/point and no JSON-number payload cliff. |
| `huge_scatter_overview` | Huge scatter overview | tracked | Proves screen-bounded rendering for datasets larger than the browser should draw point-for-point. | ingest/bin time, density payload size, peak memory, TTFR | `bench_scatter_native.py`, `bench_vs.py`, `test_first_payload_density_large`, example app assets | Keep resident/render payload flat in N while showing truthful density summaries. |
| `adaptive_scatter_drilldown` | Adaptive scatter drilldown | tracked | The large-data claim needs a credible path from overview to exact visible points. | visible-query latency, tier-switch latency, exact-point recovery, badge accuracy | `benchmarks/test_codspeed_kernels.py::test_adaptive_drilldown_cycle` | Exact points when visible count is under budget; sampled/density with explicit counts otherwise. |
| `huge_line_time_series` | Huge line / time series | tracked | Common observability and finance workload; Plotly-resampler sets the bar here. | decimation time, zoom re-decimation latency, TTFR, extrema preservation | `benchmarks/bench.py`, `bench_native.py`, `bench_interaction.py`, `test_decimate_view` | Screen-bounded line payloads with extrema-preserving decimation and fast zoom refresh. |
| `many_chart_dashboards` | Many-chart dashboards | tracked | Plotly-class apps often fail from total page weight and many live canvases, not one chart. | payload prep, navigation readiness, JS heap, redraw submission, scroll visibility, context loss/restore, stable chart-count ceiling | `benchmarks/bench_dashboard.py` | Measure the 10-50 chart scaling curve and expose LRU context eviction without discarding partial-row metrics. |
| `interaction_smoothness` | Interaction smoothness | tracked | Users judge performance by pan/zoom/hover, not just export time. | pan/zoom FPS, wheel latency, hover latency, tooltip stability, selection latency, frame color delta | `benchmarks/bench_interaction.py`; `benchmarks/bench_transport.py` | Stay responsive during interaction, avoid blank/flickering frames, then refine view after interaction settles. |
| `payload_export_size` | Payload/export size | tracked | Notebooks, static HTML, docs, and dashboards pay for every byte shipped. | standalone HTML bytes, binary payload bytes, bundle bytes | `bench_vs.py`, `bench_scatter_native.py`, `bench_heatmap_wire.py`, `bench_transport.py`, `test_codspeed_transport.py`, `test_first_payload_density_large`, `test_memory_report_density_medium`, example app asset sizes | Keep data payloads binary and screen-bounded where possible; warn when exact export would be huge. |
| `core_2d_chart_breadth` | Core 2D chart breadth | tracked | The library needs to stay fast beyond the scatter wedge: bars, histograms, areas, and heatmaps are everyday chart workloads. | payload-prep time, payload bytes, standalone HTML bytes, TTFR | `benchmarks/bench_2d_charts.py` vs Plotly/Seaborn; `benchmarks/bench_pyplot_vs_matplotlib.py`; `bench_interaction.py`; CodSpeed core-2D rows | Beat Plotly on user-visible first paint for common 2D charts while tracking Matplotlib/Seaborn raster baselines where applicable. |
| — (not in `benchmarks/categories.py`) | Core launch scatter baseline | tracked outside the registry | Launch claims need an immutable, apples-to-apples record of default product behavior from small charts through the 1B-point capacity case. | static PNG time/RSS; interactive TTFR and Python/browser RSS; hardware and SwiftShader kept separate | `benchmarks/bench_launch_scatter.py` vs Plotly and Matplotlib at 10k, 100k, 1M, 10M, and 1B | Preserve the fixed launch contracts and add versioned environment baselines rather than overwriting prior results. |
| `input_ingestion` | Input ingestion | tracked | Real applications provide converted, strided, datetime, list, pandas, and Arrow inputs rather than only contiguous f64 arrays. | ingest latency, copies, peak Python memory | `benchmarks/bench_workflows.py` ingestion rows | Keep zero-copy inputs cheap and make unavoidable conversions visible. |
| `streaming_updates` | Streaming updates | tracked | Monitoring and notebook workflows append repeatedly; stable-domain batches should update indexes incrementally while domain growth may rebuild. | append latency, refresh bytes, incremental pyramid update, domain-growth rebuild | `benchmarks/bench_workflows.py` streaming rows; `benchmarks/bench_transport.py` append diagnostics | Keep stable-domain appends proportional to the batch and expose unavoidable rebuild stalls. |
| `log_autorange` | Log autorange | tracked | Large positive/negative and non-finite series are common in monitoring and scientific charts, and log axes must avoid full-data rescans. | range latency, positive-domain correctness, peak Python memory | `benchmarks/bench_workflows.py` log autorange row; `tests/test_figure.py` | Compute correct positive log domains from zone statistics with cost proportional to chunks, not points. |
| `static_export` | Static export | tracked | HTML, SVG, and PNG have distinct serialization and browser costs. | export latency, output bytes, peak Python memory | `benchmarks/bench_workflows.py` export rows; `benchmarks/bench_pyplot_vs_matplotlib.py` matched PNG rows | Track each target independently without mixing browser and payload work. |

The launch scatter baseline has no entry in `BENCHMARK_CATEGORIES`, so it
carries no category ID: `scripts/verify_benchmark_report.py` rejects any row
whose category ID is absent from the registry, and
`benchmarks/bench_launch_scatter.py` reports its fixed launch contracts through
the versioned baselines under `benchmarks/launch_baselines/` instead. Giving it
a registry ID is pending.

Mode labels in benchmark output should stay explicit: `direct`, `decimated`,
`density`, `sampled`, or `adaptive`. A 10M density result is a real large-data
visualization result, but it is not the same claim as 10M individually styled
markers. The benchmark reports should make that distinction impossible to miss.

`bench_heatmap_wire.py` isolates first-paint heatmap payload construction at
1000² and 2000² cells. Its exact byte oracles require scalar grids to fall from
4 bytes/cell to 1 (4x) and truecolor grids from 16 bytes/cell to 4 (4x), while
also checking that packed and split layouts are byte-identical. Fixture and
figure construction are excluded; the timed stage is repeated payload
quantization and assembly.

## Interaction, drilldown, and dashboard probes

CodSpeed is native-only and intentionally focused on hot paths that should not
regress between commits. The CodSpeed job runs
`pytest benchmarks/test_codspeed_*.py --codspeed`
(`.github/workflows/codspeed.yml`), so every `test_codspeed_*` module is in
scope, not the kernels module alone. The suite asserts `xy.kernels.BACKEND ==
"native"` before timing anything. It tracks:

- Rust kernels for f32 encoding, min/max, zone maps, M4 decimation, density
  binning with/without visible indices, deterministic sampling, histograms,
  normalization, viewport scans, density log-u8 wire encoding, fused native
  density-to-RGBA static colormapping, implicit-range sampling, and cold/warm
  pyramid operations.
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
  `xy.chart(...)` layered API.
- Native static export rows include exact and categorical scatter, stroked
  triangle meshes, and heatmaps. The mesh row protects batched fill+stroke;
  the heatmap row protects the direct external arena sampler rather than only
  payload preparation.
- Zoom refresh with `test_m4_indices_zoom` and `test_decimate_view`.
- Memory/payload accounting with `test_memory_report_density_medium`.
- The native adaptive drilldown cycle with
  `test_adaptive_drilldown_cycle`: a warmed large scatter viewport moves from
  density overview, to exact visible points, and back out to density.
- The `xy.pyplot` shim suite (`benchmarks/test_codspeed_pyplot.py`): paired
  raw-versus-shim rows for line, scatter, histogram, categorical bar, and
  styled-panel builds, plus matched PNG export
  (`test_png_export_line_raw` / `test_png_export_line_pyplot`), so shim overhead
  over the native path stays visible.
- The transport frame suite (`benchmarks/test_codspeed_transport.py`):
  `encode_frame` / `decode_frame` rows for density and direct payloads,
  a parts-encode row, and base64 encode/decode comparators standing in for the
  JSON-embedded prototype shape.

That keeps CodSpeed focused on native range queries, pyramid composition,
tier-switch payload generation, payload prep, zoom latency, and memory-report
accounting instead of browser startup noise. Browser TTFR, payload bytes, peak
RSS, and cross-library comparisons remain in the schema-verified JSON reports
described below.

The JSON verifier treats `scatter-native`, `heatmap-native`, and
`kernel-native` reports as
native-only artifacts: if their environment metadata says
`xy_backend` is anything other than `native`, verification fails. That
keeps any non-native measurement from being mixed into native performance
claims.

The browser-heavy probes are opt-in scripts:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_interaction.py \
  --sizes 1e4,1e5,1e6 --json interaction.json

PYTHONPATH=python .venv/bin/python benchmarks/bench_dashboard.py \
  --chart-counts 10,20,50 --json dashboard.json

PYTHONPATH=python .venv/bin/python benchmarks/bench_workflows.py \
  --profile standard --json workflows.json
```

`bench_interaction.py` dispatches DOM wheel/pointer gestures through the real
`ChartView` zoom, pan, hover, crosshair, box-zoom, and brush-select paths. It
warms first-use GPU/DOM work, completes each sample with WebGL readback, records
median/p95/p99/max, checks nonblank pixels, and emits an
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
`bench_dashboard.py` attempts 10/20/50 mixed dashboards and reports payload prep,
navigation readiness, JS heap, redraw-submission p95, per-chart context loss and
restore events (governed releases labeled separately from browser evictions),
initial/scrolled nonblank IDs, per-visit scroll recovery latency, and the
largest stable loss-free
count. Partial rows retain their timing and memory metrics. `bench_workflows.py` covers ingestion, streaming/incremental-pyramid
updates, and separate HTML/SVG/native-PNG/Chromium-PNG export rows. All three emit schema-versioned JSON with
environment metadata and benchmark category IDs.

## Copyable claim taxonomy

Use these shapes when turning benchmark rows into README text, release notes, or
posts. The goal is to make every public claim reproducible from a row in this
document or from a verified JSON artifact.

| Claim shape | Safe wording pattern | Required context |
|---|---|---|
| Payload/prep comparison | "In the native backend benchmark, histogram payload prep for 10k values / 200 bins was 17.3x faster than Plotly." | chart type, workload, backend, compared library, metric |
| Browser first paint | "For the measured Chrome TTFR row, the 10k-value histogram first painted 5.0x faster than Plotly." | browser/render target, workload, chart type, TTFR included |
| Large scatter overview | "The 100M scatter overview uses density mode with a 258 KB wire payload; it is not drawing 100M exact markers." | mode, point count, payload, exact-vs-aggregate wording |
| Line decimation | "The 10M line benchmark ships an M4-decimated ~60 KB payload while preserving the extrema oracle." | mode, point count, payload, correctness oracle |
| Install/import footprint | "In the install-footprint benchmark, cold import was 6.4 ms for the measured distribution." | benchmark name, metric, measured distribution |

Do not shorten those into broad slogans such as "xy is faster than
Plotly" or "renders 10M points" without the row context. If a sentence does not
name the chart type, workload, mode, backend, metric, and render target where
they matter, it is not ready to publish.

## `xy.pyplot` versus Matplotlib/Agg

`benchmarks/bench_pyplot_vs_matplotlib.py` runs the same Matplotlib-style calls
against `xy.pyplot` and Matplotlib, then requires both arms to produce a
nonblank PNG at the same 1800×840 pixel size. Data generation, imports, and
warm-up renders are excluded; library order alternates between repetitions. The
headline metric is median total chart-to-compressed-PNG time. Build time alone
is diagnostic because `xy.pyplot` deliberately defers most work until export.

Every row also discloses the xy render tier (§28: tier decisions are never
silent): `direct` paints every mark exactly as Matplotlib does, `decimated` is
the M4-reduced line series, and `density` is a screen-bounded aggregate. The
report verifier rejects an xy row that omits the tier.

The following is a local diagnostic run from 2026-07-12 (macOS arm64, Python
3.14.5, Matplotlib 3.11.0, xy native Rust backend, dirty worktree), with 21
repetitions per arm and three warm-ups, after the row-band parallel
rasterizer landed. The gate requires every family—not an average—to reach
10×:

| family | workload | xy tier | xy total | Matplotlib total | xy speedup | total-time winner |
|---|---|---|---:|---:|---:|---|
| line | 200,000 samples | decimated | 2.68 ms | 31.57 ms | 11.80× | xy |
| scatter | 200,000 points | direct | 7.40 ms | 420.6 ms | **56.83×** | xy |
| histogram | 1,000,000 values / 200 bins | direct | 2.41 ms | 50.26 ms | 20.90× | xy |
| bar | 1,000 bars | direct | 3.66 ms | 143.3 ms | 39.11× | xy |
| pcolormesh | 200×300 cells | direct | 2.79 ms | 39.54 ms | 14.16× | xy |
| contour | 150×200 cells / 12 levels | direct | 2.59 ms | 35.45 ms | 13.68× | xy |

The geometric-mean result is **21.76× in xy's favor**, and every standard
family clears the explicit 10× gate. This is the scoped claim: warmed
Matplotlib-style construction through a validated 1800×840 PNG for the exact
workloads above. It is not a claim about every Matplotlib API, arbitrary image
sizes, or interactive rendering. xy's latency-oriented PNGs remain larger than
Matplotlib's in every row; the gate measures chart-to-pixels latency, while the
existing balanced encoder remains available where file size is the priority.

The direct-scatter refresh uses private ABI-v26 affine point commands for
constant-style marks. It borrows the existing offset-encoded x/y payload,
performs decode and projection in Rust, and retains the general point command
for log axes and data-driven color or size. On the exact 200,000-point row its
display list fell from **3,200,862 bytes to 998 bytes** (99.97% smaller), with
byte-identical PNG output. An interleaved same-payload diagnostic measured
12.18 ms versus 13.42 ms for the previous expanded command (1.10×); the full
21-repetition gate above improved from the prior published 9.48 ms / 44.20×
row to 7.40 ms / 56.83×. Command-level expanded-path parity, full static
routing tests, non-finite handling, and malformed-span rejection protect the
optimization.

The companion affine-channel command borrows normalized color/size columns
and resolves continuous LUT colors, categorical palettes, and radii in Rust.
On 200,000 exact points it reduced the prior **3,200,690-byte** expanded
display list to **852–898 bytes**, with byte-identical PNGs. Controlled
same-payload medians improved by **1.18×** for continuous color
(17.05→14.42 ms), **1.14×** for categorical color (16.17→14.17 ms), **1.08×**
for continuous size (13.93→12.91 ms), and **1.16×** for combined color+size
(16.64→14.32 ms). Constant style retains the smaller allocation-free command;
log axes retain the fully general expanded path. Parity tests cover large
offset domains, every channel combination, categorical palettes, symbols,
strokes, opacity, malformed modes, and truncated spans.

Categorical channels with at most 256 groups now keep their intrinsic u8
representation from Python payload through WebGL and the borrowed Rust export
command; larger category sets retain the prior f32 behavior and warning. For
the same 200,000-point, seven-group affine scatter, this reduced the exact
browser payload from **2,400,000 to 1,800,000 bytes** (**25% total**, and
**75% for the color channel**) and the color vertex buffer from 800,000 to
200,000 bytes. An interleaved 51-pair same-payload native-raster diagnostic was
pixel-identical and measured **9.846→9.685 ms (1.02×)**; payload compilation
measured **0.191 ms**. Protocol v3 rejects stale clients rather than allowing
them to reinterpret the typed column. CodSpeed now hard-gates the categorical
wire at 9 bytes/point and tracks categorical native PNG export separately.

Fixed-width Unicode, bytes, and boolean color arrays now factorize in one
native hash pass; Python canonicalizes and sorts only the compact unique-label
set. A bounded, array-wide cardinality probe retains the direct label path for
near-unique data, where hashing before materializing every display label would
be redundant. Mixed object arrays keep the original defensive label loop,
including missing values and heterogeneous objects. Category codes also remain compact
in memory: u8 through 256 categories and u32 above it, instead of f64. On a
1,000,000-row / 24-label Unicode scatter, factorization improved
**158.06→11.55 ms (13.69×)** and the retained code array fell from **8.0 MB to
1.0 MB**. Exact direct Figure→payload improved **160.65→12.97 ms (12.39×)**
with the same 9,000,000-byte wire payload; forced-density Figure→payload
improved **185.60→15.82 ms (11.73×)** with a 560,992-byte wire payload.
CodSpeed separately tracks the million-row native factorizer and the complete
categorical first-payload path. `Figure.memory_report()` now exposes derived
`channel_bytes` and the combined `resident_array_bytes`, so the compact-code
gain is visible rather than hidden outside canonical geometry accounting.

The compact factorizer now uses a fixed 512-slot open-addressed codebook rather
than a general allocating SipHash map; exact record equality still resolves
every hash collision and first-seen codes remain unchanged. At 512k rows it
probes a bounded prefix and encodes disjoint chunks in parallel. Labels first
seen later are merged in canonical row order and trigger one deterministic
retry; the common case remains one pass. Controlled 20,000,000-row medians
improved **139.42→13.13 ms (10.62×)** for one-codepoint Unicode,
**131.60→11.55 ms (11.39×)** for four-byte strings, and
**235.70→16.73 ms (14.09×)** for four-codepoint Unicode. Boolean records use a
perfect 256-entry direct table and improved **165.07→8.81 ms (18.73×)**.
The same factorization pass now emits exact per-code u64 counts with effectively
no timing change (**65.56 vs 65.93 ms** at 100M). Full-domain stratified
sampling reuses them instead of recounting the entire code column, improving
the 100M sampler **38.04→12.25 ms (3.10×)** with identical selected rows. The
row-scan fan-out cap now uses all 18 workers on the reference machine; relative
to the former eight-worker cap, 100M factorization improved **66.12→31.51 ms
(2.10×)**, zone maps **17.86→8.50 ms (2.10×)**, binning **18.51→11.13 ms
(1.66×)**, and the counted sampler **12.49→7.22 ms (1.73×)**. The 512k
crossover remains favorable (**2.19→0.34 ms** for compact factorization).
One-byte bool/byte records now use a parallel direct value→code table with the
same late-value first-row merge, improving the 100M case **57.82→3.18 ms
(18.21×)**. Records up to eight bytes use a cheaper exact-record hash while
retaining full byte equality checks. The common NumPy U1 case bypasses hashing
entirely through a bounded Unicode-scalar table, including swapped-endian
arrays: 100M labels improved **30.00→4.14 ms (7.25×)** without regressing wider
records. The direct table is 2.2 MB of transient scratch and is not retained.
New, distinct x/y columns now compute their independent zone maps in one
scoped Rust call. Every field is bit-identical to the two-call path, while the
100M pair improved **17.00→12.64 ms (1.35×)**; existing/shared columns retain
the original deduplication behavior.

Full-domain density first paint now interleaves grid aggregation with the
deterministic overlay sampler in one Rust traversal. Exact grid cells and
selected row IDs are byte-for-byte equal to the former standalone calls,
including compact-u8 rare-category floors. Controlled 100M medians improved
**17.54→15.24 ms (1.15×)** for the uniform overlay and **16.86→15.82 ms
(1.07×)** for 24-category counted stratification. Paired 1B Figure→payload A/B
runs improved **262.0→246.6 ms** after warmup for the plain path and
**331.0→324.9 ms** for the categorical path. The public plain 1B ceiling
refresh completed in **256.2 ms**, plus **0.68 ms** for native PNG.

Multi-column finite/log-validity selection is also native in ABI v31. Rectangle
zone maps remove columns already proven finite; remaining f64 streams are
checked together without NumPy boolean temporaries, returning `None` for the
identity case so no row-index array is retained. Across six 10M-row triangle
coordinate streams, all-valid detection improved **7.60→3.03 ms (2.50×)**.
With 1% rejected rows, the parallel query/write path improved **12.41→8.09 ms
(1.53×)** while returning the same ascending u32 indices.

Full-domain compact categorical density sampling now consumes group codes
directly in Rust with implicit row IDs. It returns ascending selected indices
without materializing the former visible-index array, u64 ID conversion,
category gather, or byte mask. On a controlled 100,000,000-row / 24-label run,
the old and new paths produced identical density grids and the same 40,094
sampled row IDs. Sampling improved **0.284→0.099 s (2.87×)**. Peak process RSS,
with the same 1.6 GB x/y geometry, 400 MB fixed-width label input, and 100 MB
retained codes, fell **3.943→2.146 GB (45.6%)**, with no swapping. With direct
U1 factorization, count reuse, and full-core fan-out, complete production
Figure→payload takes **0.037 s** (**0.017 s** ingest plus **0.020 s** payload),
writes a **557,456-byte binary blob**, and
reports the exact 100,000,000-row visible count. This is a density overview
with a deterministic categorical overlay, not 100,000,000 exact markers.

The schema-verified public benchmark now has `--categorical-groups`. Its 1B-row
/ 24-label production run completed Figure→payload in **0.352 s**, shipped a
**557,320-byte total wire payload** (555,240-byte blob plus spec), retained
39,848 deterministic sample rows, and rendered the prebuilt payload to native
PNG in **0.649 ms** (**0.352 s** source-to-PNG). Peak RSS was **24.04 GB** on
the 64 GiB reference host; payload throughput was **2.84 billion source
rows/s**, with no swap. A separate 2B-row high-water probe also completed with
exact
`visible=2,000,000,000`, a 556,340-byte blob, and no swap, but memory pressure
raised Figure→payload to 11.69 s; 1B is therefore the practical categorical
ceiling on this machine and 2B the verified capacity ceiling.

Stroked triangle meshes now use one structure-of-arrays ABI-v26 command instead
of emitting a fill command and a stroke command from Python for every face.
On 50,000 independently colored triangles with 0.5 px borders, an interleaved
21-pair command-build A/B improved **99.19→1.10 ms (89.87×)** and reduced the
display list from **3,750,839 to 1,400,852 bytes (62.65%)**. An interleaved
11-pair full native-raster A/B improved **116.99→16.15 ms (7.24×)**. Output was
byte-identical to the expanded fill-then-stroke sequence. Native tests also
cover translucent canvases, non-finite compatibility, malformed widths, and
truncated commands; CodSpeed tracks a 163,840-face stroked scientific mesh.

Long polyline strokes now use the rasterizer's disjoint row-band scheduler
while preserving the stroke's single max-combined coverage surface. A
controlled serial/parallel A/B of the exact 200,000-source-sample line command
produced the same PNG SHA-256 and measured **1.025 ms → 0.770 ms (1.33×)**;
the warmed full pyplot export measured **2.286 ms → 2.023 ms (1.13×)**. The
100,000-estimated-pixel crossover left every tested smaller/flatter line on
the serial path, while tested workloads above it improved 17–45%. Forced
serial-versus-banded parity covers solid, dashed, closed, clipped,
translucent, opaque/transparent, and multiple-width strokes. The independent
21-repetition cross-library run remained around 2.7–2.8 ms under system noise,
so the committed matched table above is intentionally not replaced by the
controlled microbenchmark.

The `huge` profile runs the same families at the sizes where static Matplotlib
workflows actually stall (same machine, 11 repetitions, 2 warm-ups). Agg's
cost scales with N; xy's disclosed tiers stay screen-bounded:

| family | workload | xy tier | xy total | Matplotlib total | xy speedup |
|---|---|---|---:|---:|---:|
| line | 1,000,000 samples | decimated | 3.35 ms | 50.32 ms | 15.03× |
| scatter | 1,000,000 points | density | 4.92 ms | 2,017.0 ms | **409.68×** |
| histogram | 5,000,000 values / 200 bins | direct | 3.25 ms | 68.99 ms | 21.23× |
| bar | 5,000 bars | direct | 8.97 ms | 656.8 ms | 73.22× |
| pcolormesh | 400×600 cells | direct | 4.32 ms | 79.92 ms | 18.48× |
| contour | 250×320 cells / 12 levels | direct | 3.19 ms | 38.15 ms | 11.95× |

Geometric mean on the huge profile: **35.82×**; the scatter family — the
workload the density tier exists for — crosses 100×, and every family clears
the 10× gate. The huge-profile scatter row is a tier-disclosed comparison: xy
rasterizes a screen-bounded density surface (the same output a user sees for
1M points) while Matplotlib paints all 1M marks. This refresh includes the
compact native log-u8 density display opcode, 256-entry native color lookup,
and parallel direct sampler used by static PNG export. The 1M-density command
now borrows its existing payload arena and is **759 bytes** instead of an
estimated 787,152-byte expanded RGBA command (99.9% smaller), with exact pixel
parity and no ownership transfer.

The RGBA8 raster rewrite's one known native-API regression is now a win: the
same-machine 100,000-point default-style direct scatter at scale 1 that
measured ~13% slower than `main` before the row-band parallel rasterizer now
measures 14.5–15.1 ms on this branch versus 19.9–20.1 ms on `main` (about 27%
faster), byte-identical output. CodSpeed continues to track the direct tier.

Reproduce and retain the raw samples with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile standard --reps 21 --warmups 3 --target-speedup 10 \
  --require-target --json pyplot-vs-matplotlib.json \
  --out pyplot-vs-matplotlib.md
PYTHONPATH=python .venv/bin/python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile huge --reps 11 --warmups 2 \
  --json pyplot-vs-matplotlib-huge.json --out pyplot-vs-matplotlib-huge.md
python scripts/verify_benchmark_report.py pyplot-vs-matplotlib.json \
  --kind pyplot-vs-matplotlib
```

This is a static notebook/report comparison. It does not imply equivalent
interaction: xy's browser WebGL zoom/pan path is measured by
`benchmarks/bench_interaction.py`, while Matplotlib/Agg produces a completed
raster and has no comparable client-side interaction loop.

## Time to first render (data → pixels)

Byte counts and serialize time are **not** pixels. For the browser-rendered
libraries (xy, Plotly-HTML, Bokeh, Altair, hvPlot) the static-export size
says nothing about how long the browser takes to parse the embedded JS, build the
scene, and paint — often the dominant cost (Bokeh/Altair ship megabytes of JS +
data the browser must execute). So the harness measures **time-to-first-render**
directly: `benchmarks/bench_vs.py --ttfr` loads each library's output in headless
Chromium and reads First Contentful Paint (`navigationStart → first paint`, JS
inlined, no CDN, via `benchmarks/_browser.py`). Raster libraries
(matplotlib/seaborn/datashader/Plotly-kaleido) already produced pixels at render,
so their TTFR = build + render.

This closes the biggest fairness gap: previously xy' number excluded the
WebGL draw while the HTML libraries' numbers excluded the browser entirely — both
stopped before pixels existed. The CI `benchmark` job now runs the TTFR pass
(capped at 100k points, since each row launches a browser) and the numbers land
in `docs/benchmark_ci.md`, which is not committed — CI regenerates it each run
and uploads it as the `benchmark-report` artifact. Locally, xy'
standalone-export TTFR under software GL (SwiftShader) is ~180 ms for a density
page; on real GPU hardware it is lower.

## Expanded adapter benchmark — 100k points

The xy, matplotlib, seaborn, and Plotly rows are refreshed from the
2026-07-09 `benchmark-refresh` CI run (Ubuntu, Python 3.12, native Rust core;
Plotly via kaleido→PNG). The Bokeh, Altair, Datashader, and hvPlot rows (¹) are
carried over from an earlier local expanded run and have not been republished
from a refresh artifact. The `benchmark-refresh` workflow does install those
libraries and passes no `--libraries` filter, so `bench_vs.py` defaults to every
adapter; re-running it and republishing from its `scatter-vs.json` would
supersede these rows. That refresh is pending. Reproduce the refreshed rows
with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_vs.py \
  --sizes 1e3,1e4,1e5 --budget 20
```

| Library | Render target | 100k total ¶ | Peak memory | Output bytes | Points/sec ¶ |
|---|---|---:|---:|---:|---:|
| xy | binary payload (native) * | **2 ms** | **2 MB** | 781 KB | 51,702,966 |
| matplotlib | Agg PNG † | 83 ms | 6 MB | 53 KB | 1,206,226 |
| seaborn | matplotlib PNG † | 152 ms | 11 MB | 39 KB | 657,728 |
| Plotly `Scattergl` | Kaleido PNG † | 2,991 ms | 22 MB | 61 KB | 33,434 |
| Plotly `Scatter` | Kaleido PNG † | 6,281 ms | 22 MB | 107 KB | 15,921 |
| Bokeh canvas ¹ | standalone HTML ‡ | 75 ms | 14 MB | 2 MB | 1,327,770 |
| Bokeh WebGL ¹ | standalone HTML ‡ | 73 ms | 14 MB | 2 MB | 1,360,995 |
| Altair / Vega-Lite ¹ | standalone HTML ‡ | 1,846 ms | 35 MB | 5 MB | 54,171 |
| Datashader ¹ | PNG raster § | 13 ms | 15 MB | 58 KB | 7,502,931 |
| hvPlot / HoloViews ¹ | Bokeh HTML ‡ | 95 ms | 17 MB | 2 MB | 1,052,353 |

¹ Earlier local run, not re-measured in the 2026-07-09 CI refresh.

\* **Exact interactive wire payload.** The xy row counts compact spec
metadata plus the GPU-ready x/y float32 buffers, excluding the JavaScript runtime
and HTML wrapper. At 100k direct points, two 4-byte coordinates account for about
781 KiB (8 bytes/point); exact hover, selection, and view updates remain possible.

† **Static raster output.** These byte counts are compressed finished pixels, not
the source-point transport. The original coordinates cannot be recovered for
exact hover, selection, or client-side re-rendering, so these values should not be
compared directly with `*` or `‡` payload sizes.

‡ **Interactive HTML output.** These artifacts retain chart data/specification and
an HTML wrapper. Adapter resource modes differ (for example, a CDN reference may
exclude the library runtime), so they are the closest interactive comparison to
`*`, but not identical package/bundle measurements.

§ **Aggregated raster output.** Datashader's PNG retains screen-sized density/count
pixels rather than 100k exact points. Its compact size represents aggregation as
well as PNG compression.

¶ `total` and `points/sec` measure production of the target named in each row.
They are useful for scaling within a target class, not as same-render-target
speedups. Compare output bytes only between artifacts with equivalent retained
information and runtime-inclusion rules.

## Expanded adapter benchmark — 10M points

The 10M refresh covers the adapters installed by the `benchmark-refresh` CI run
(Ubuntu, Python 3.12, native Rust core; Plotly via kaleido→PNG). The additional
Bokeh, Altair, Datashader, and hvPlot rows from the 100k local expansion are not
measured at this size, so they are marked explicitly below. Reproduce the
refreshed core rows with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_vs.py \
  --sizes 1e7 --budget 45
```

| Library | Render target | 10M total ¶ | Peak memory | Output bytes | Points/sec ¶ |
|---|---|---:|---:|---:|---:|
| xy | binary payload (native) * | **169 ms** | **126 MB** | **832 KB** | **59,100,000** |
| matplotlib | Agg PNG † | 3,239 ms | 553 MB | 42 KB | 3,090,000 |
| seaborn | matplotlib PNG † | 7,918 ms | 1,088 MB | 32 KB | 1,260,000 |
| Plotly `Scattergl` | Kaleido PNG † | 54,064 ms | 1,584 MB | 49 KB | 185,000 |
| Plotly `Scatter` | SVG/Kaleido † | over budget above 1M | — | — | — |
| Bokeh canvas ¹ | standalone HTML ‡ | not measured | — | — | — |
| Bokeh WebGL ¹ | standalone HTML ‡ | not measured | — | — | — |
| Altair / Vega-Lite ¹ | standalone HTML ‡ | not measured | — | — | — |
| Datashader ¹ | PNG raster § | not measured | — | — | — |
| hvPlot / HoloViews ¹ | Bokeh HTML ‡ | not measured | — | — | — |

¹ No 10M result has been republished for those adapters; the cells are left
explicit rather than filled from an older run. The 100k results above remain the
latest measurements for that group. The refresh workflow does install these
libraries, so a 10M refresh is possible and pending — `bench_vs.py` marks any
adapter exceeding the per-config budget `skipped(over budget)` and stops
climbing to larger N, so some of these rows may resolve to a ceiling rather than
a timing.

At 10M points, xy prepares a fixed-size screen-bounded payload while
the direct-rendering libraries retain work proportional to the input size. This
is a scaling and memory comparison across different render targets, not a claim
that a binary payload and a finished PNG are identical artifacts. The detailed
ceiling and fairness analysis appears in the [Headline — 10 M points](#headline--10-m-points)
section below.

---

## Core 2D chart benchmark — xy vs Plotly and Seaborn

The regular 2D chart harness lives in `benchmarks/bench_2d_charts.py`. It
compares the new core chart families against Plotly and emits Seaborn rows
where Seaborn has natural primitives: histogram, simple bar, grouped bar, and
heatmap. Plotly remains the primary interactive verdict baseline for histogram,
area, simple bar, grouped bar, stacked bar, and heatmap. The harness reports
payload-prep time, payload bytes (excluding JS runtime), standalone HTML bytes,
and optional headless-Chromium TTFR.

Measured by the `benchmark-refresh` CI workflow on 2026-07-08 (Ubuntu, native
Rust backend). The harness warms each library once before timing, so no row is
charged a one-time library cold-start (an unwarmed first Plotly build costs
~1.5 s and would otherwise inflate the first case's speedup into a meaningless
outlier). Reproduce locally with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_2d_charts.py \
  --profile smoke --ttfr --ttfr-max-work-units 200000

PYTHONPATH=python .venv/bin/python benchmarks/bench_2d_charts.py \
  --profile standard --ttfr --ttfr-max-work-units 50000
```

Environment note: TTFR probes require launching local headless Chrome; in a
sandboxed environment without browser-launch permission the probe returns
`None`.

Seaborn rows render through matplotlib/Agg PNG. For those static raster rows,
TTFR is treated as total chart-to-pixels time because the image already exists
after payload generation. Unsupported Seaborn chart shapes, such as filled area
and stacked bars, are reported as unavailable rather than approximated with raw
matplotlib calls.

### Smoke profile with browser TTFR

| Chart | Workload | Speedup vs Plotly | Payload reduction | TTFR speedup | Verdict |
|---|---|---:|---:|---:|---|
| Histogram | 10k values / 200 bins | 17.3x faster | 33.4x smaller | 5.0x faster | pass |
| Area | 10k samples | 17.2x faster | 1.9x smaller | 4.0x faster | pass |
| Bar | 100 categories | 11.3x faster | 2.5x smaller | 3.8x faster | pass |
| Grouped bar | 100 categories x 4 | 4.5x faster | 2.1x smaller | 4.1x faster | pass |
| Stacked bar | 100 categories x 4 | 4.5x faster | 1.7x smaller | 5.1x faster | pass |
| Heatmap | 50 x 50 cells | 32.2x faster | 3.4x smaller | 4.6x faster | pass |

The heatmap result uses the compact grid-texture path: one normalized scalar
grid instead of four rectangle geometry columns per cell.

### Standard profile scaling notes

The larger profile extends to 1M histogram/area samples, 10k simple bars, and a
500 x 500 heatmap. Results stayed strong:

- Histogram: 1M values produced a 4 KB xy payload vs 13 MB Plotly JSON
  (3192x smaller), with 11.2x faster payload prep on the native backend.
- Heatmap: 500 x 500 cells produced a 991 KB xy payload vs 3 MB Plotly
  JSON, with 5.9x faster payload prep.
- Area: 1M samples produced an 89 KB xy payload vs 21 MB Plotly JSON
  (242x smaller), with 6.0x faster payload prep.
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

The `--production` mode of `benchmarks/bench_scatter_native.py`
(`measurement_scope: production-figure-payload`) reports the real Figure
transport payload. The rows below are that mode:

| points | tier | data prep | wire bytes | browser render |
|---:|---|---:|---:|---:|
| 100k | direct | <0.1 ms | 781 KB | 78.5 ms |
| 1M | density | 1.9 ms | 260 KB | not measured in this native-only refresh |
| 10M | density | 10.2 ms | 258 KB | not measured in this native-only refresh |
| 100M | density | 65.7 ms | 258 KB | not measured in this native-only refresh |

The harness's default kernel-shape mode (`measurement_scope:
native-kernel-shape`) is a different scope and does not appear in that table: it
reports the raw f32 grid alone, a constant `GRID_W * GRID_H * 4` = 768 KiB for
every density row (`benchmarks/bench_scatter_native.py:151`).

CI regression gating uses `--production`, which calls the real Figure payload
compiler and includes compact spec metadata plus the sampled point overlay.
The density grid is log-encoded directly into the same one-byte R8 precision
the client uploads, so its 512×384 transport is 192 KiB rather than 768 KiB.
The full deterministic wire payload, including the exact sampled overlay, stays
about 258–260 KiB from 1M through 100M. Exact visible counts remain explicit in
the spec; the quantized grid is display-only.

The opt-in high-memory ceiling probe extends that production contract to
**1,000,000,000 points**. On the same 2026-07-12 macOS arm64 machine (64 GiB
RAM), `--large-numpy-generator --production` measured Figure construction plus
payload compilation at **256.2 ms** with a **258 KiB** wire payload, exact
`visible=1,000,000,000`, 8,220 sampled rows, a valid occupied density grid, and
no swap (**3.90 billion source rows/s**). Rendering that prebuilt payload
through the compact native density opcode took **0.68 ms** (94,680 output
bytes), for **256.9 ms** source-to-PNG.
The two
canonical f64 columns occupy 14.90 GiB; peak process RSS was 24.04 GB. Fixture
generation is explicitly outside the timed region. The schema-verified command
is shown in `benchmarks/README.md`; this is a density overview, not one billion
individually drawn markers.

### Native static heatmap scaling

Static heatmaps now borrow their canonical f64 grid directly. A private ABI-v26
multi-span call normalizes only nearest-sampled destination pixels through the
same f32 rounding helper used by browser-payload compilation, then colormaps in
Rust. It therefore owns no derived grid, performs no full-grid normalization,
and allocates no RGBA expansion. Exact browser-payload and expanded-RGBA parity
covers transparent and opaque canvases, downsampling, NaNs, clipped domains,
alpha, colormap interpolation, multiple spans, and malformed references.

A focused same-process 900×420 PNG diagnostic measured the following prebuilt
payloads; each output was byte-identical to the previous expanded path:

| source grid | previous PNG path | direct arena path | speedup | display command |
|---:|---:|---:|---:|---:|
| 600×400 (240k) | 2.08 ms | 1.51 ms | 1.38× | 895 B |
| 1,000×1,000 (1M) | 4.72 ms | 1.60 ms | 2.95× | 897 B |
| 2,000×2,000 (4M) | 15.91 ms | 1.36 ms | 11.66× | 783 B |

Heatmap ingestion also avoids redundant statistics work: auto-domain grids
reuse their required zone-map pass instead of running a separate min/max scan,
while an explicitly supplied color domain defers zone maps until statistics,
memory reporting, or append logic actually requests them. On the 1B-cell
fixture this reduced Figure construction from 216.93 ms to 7.75 ms without
changing later zone-map results.

The schema-verified ceiling command in `benchmarks/README.md` then rendered a
**32,768×32,768 (1,073,741,824-cell)** regular heatmap. Figure construction
took **7.75 ms**, borrowed-span preparation **0.06 ms**, and the native 900×420
PNG stage **2.91 ms**, for **10.71 ms source-to-PNG** and a 280,229-byte output.
The exact canonical f64 matrix occupied 8.0 GiB; static export owned zero grid
bytes, peak RSS was 8.0 GiB, and the process reported no swap. The 574 ms
deterministic fixture construction was excluded.
This proves local static-export scaling; a 4 GiB browser payload is not a claim
of interactive viability, and tiled huge-image transport remains future work.

The 64 GiB high-water command in the same runbook then reached
**65,536×65,536 = 4,294,967,296 cells**, deliberately crossing the u32
total-count boundary. Figure construction took **18.96 ms**, borrowed-span
preparation **0.07 ms**, and native rendering **17.45 ms**, for **36.49 ms
source-to-PNG** and a 280,701-byte output. The canonical source occupied
32.0 GiB; static export again owned zero grid bytes, maximum resident memory
was 25.3 GiB (32.0 GiB peak process footprint), and the system reported no
swap. Its 3.77 s deterministic allocation fixture was excluded. This is the
current tested local-static ceiling; browser delivery remains separately
bounded by transport and ArrayBuffer limits.

A focused same-process diagnostic on the same 2026-07-11 macOS arm64 worktree
measured the 10M XY density binary spec at **10 ms / 258 KiB**, while Plotly
`Scattergl` produced a direct-marker HTML payload in **920 ms / 259 MiB**.
Those modes and retained information differ, so this is a scaling/payload
comparison—not a same-render-target speedup claim.

> The kernel microbench numbers above predate the kernel-parallelization pass:
> `bin_2d`, `histogram`, `m4`, `range_indices`, and `normalize` now fan out
> across cores above 512k rows. Zone maps have no merge traffic and use an
> earlier, chunk-aware crossover: two complete 65,536-row chunks, with workers
> capped by the number of chunks. All paths are bitwise-deterministic; see
> `src/kernels.rs`.
> On a 4-core runner the 10M `bin_2d`/`histogram`/`m4` costs drop ~3–4× vs the
> single-threaded figures here; CI regenerates the live numbers into
> `benchmark_ci.md` each run. These committed rows stay as the conservative
> single-threaded floor until refreshed from a CI artifact.

A focused 200,000-row zone-map crossover diagnostic on 2026-07-12 measured
**0.269 ms serial → 0.133 ms parallel (2.02×)**, with p95 improving from
0.294 ms to 0.148 ms. The schema-verified stdlib C-ABI harness reported
**1,314 Mrow/s** for the same size. In the matched pyplot line workload, the
zone maps for its two canonical columns dominate `Chart → Figure` construction;
that stage fell from approximately 0.61 ms to 0.35 ms. The full 1800×840 PNG
remains raster/compression-bound at roughly 2.7 ms, so this is recorded as an
ingest/first-payload win rather than overstated as an end-to-end speedup.

### Line / time-series decimation — vs plotly-resampler

xy' M4 decimation (Tier 1) against vanilla Plotly and plotly-resampler
(the same-thesis rival). `benchmarks/bench_line.py`; random-walk series;
aggregating libraries target ~2000 on-screen points. **Measured** by the CI
benchmark job (run 28724006099, commit `7de68f8`, Ubuntu, Python 3.12).

| N | xy | plotly (vanilla) | plotly-resampler |
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
| **xy** | **6.4 ms** | **566 KB** |
| plotly | 39 ms | 41.2 MB |
| bokeh | 54 ms | 23.8 MB |
| matplotlib | 181 ms | 24.4 MB |
| holoviews | 259 ms | 16.8 MB |
| altair | 526 ms | 5.6 MB |
| datashader | 606 ms | 16.8 MB |
| seaborn | 1.50 s | 1.0 MB |
| hvplot | 4.65 s | 685 KB |

Sizes are binary units (`bench_install.py` divides by 1024 and labels the result
KB/MB). On that convention, across the eight comparators above xy imports
6–730× faster and is 1.2–75× smaller on disk; against the heavy stacks (plotly,
matplotlib, bokeh) the disk gap is 43–75× (the §33 import-budget goal, made
comparative).

The harness also has `--fresh-venv`, which installs each requested target into
an isolated `uv` environment and reports total site-packages bytes, file count,
transitive distribution count, install time, and cold import. CI runs this mode
for xy and Plotly alongside the faster distribution-only table above.

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
[`spec/benchmarks/metrics.md`](metrics.md). CI uploads that table plus
the raw `scatter.json`, `kernel.json`, and `transport.json` inputs as the
`regression-benchmark-report` artifact, even when the hard regression gate
fails. Re-bless the baseline from a CI run with
`check_regressions.py --update-baseline`.

### Transport loopback

`benchmarks/bench_transport.py` (report kind `transport-loopback`) is the third
gated input. It measures the transport-neutral channel dispatcher: two HTTP
endpoints both call `xy.channel.handle_message` and differ only in response
encoding — the Reflex prototype shape (base64 buffers inside JSON) versus xy's
production versioned binary frame. It also records append diagnostics
(single-trace, two-trace, and unaffected-trace wire bytes) and an optional
Chromium probe that fetches and decodes both formats from the same loopback
server, waiting for the next animation frame after each decode. That probe does
not claim request-to-pixels or GPU-upload latency.

CI runs it at 1e6 points with `--require-browser`, verifies it, and passes
`--transport transport.json` to `check_regressions.py`. Its `transport.*`
metrics gate **hard**: `wire_bytes`, `gzip_bytes`, and `wire_to_payload_ratio`
are deterministic, and `transmissions` is gated at zero tolerance.

### Static image export

`Figure.to_png()` defaults to `Engine.default`, the browser-free native Rust
rasterizer and its latency-oriented PNG encoder; `optimize=True` selects the
slower, smaller-file path. `engine=Engine.chromium` remains available when
browser CSS/WebGL fidelity is required (Chrome, Chromium, Edge, or
`chrome-headless-shell` discovered via
`XY_BROWSER`, PATH, and common application locations). Both modes are covered
by the PNG tests; HTML export (`to_html`) needs nothing extra.

---

## Headline — 10 M points

Measured by the `benchmark-refresh` CI workflow on 2026-07-08 (Ubuntu, native
Rust backend), all libraries in one consistent `benchmarks/bench_vs.py` run.
The targets differ (binary payload prep versus Agg/Kaleido PNG), so this table
is a scaling/memory comparison, not a same-render-target speedup claim. New
interactive reports separately measure build + HTML serialization + chart-ready
time and label each row's mode and target.

| library | total time | peak memory | resident Δ | render payload | points/sec |
|---|---|---|---|---|---|
| **xy** | **169 ms** | **126 MB** | **+10 MB** | **832 KB** | 59,100,000 |
| matplotlib (Agg→PNG) | 3,239 ms | 553 MB | +223 MB | 42 KB PNG | 3,090,000 |
| Seaborn (Agg→PNG) | 7,918 ms | 1,088 MB | +695 MB | 32 KB PNG | 1,260,000 |
| Plotly `Scattergl` (→PNG) | 54,064 ms | 1,584 MB | +382 MB | 49 KB PNG | 185,000 |
| Plotly `Scatter` (SVG) | — over budget above 1 M | | | | |

At 10 M points xy is **~19× faster than matplotlib**, **~47× faster than
Seaborn**, and **~320× faster than Plotly's WebGL path**, at **4–13× lower peak
memory**. Plotly's SVG path never reached 10 M (over budget above 1 M).

> Scope note (important): every column above comes from the same harness pass
> structure — `total` is build + static/kernel render timed with no memory
> tracer active, and `peak memory` is the tracemalloc peak from a separate,
> untimed pass over the same work. Ingest is zero-copy for well-formed f64
> arrays (the canonical store holds a reference, not a duplicate), so
> xy' 126 MB peak is transient working buffers — visible-row indices,
> sample gathers, encode staging — released after the payload is built. What
> lasts is screen-bounded: a fixed 832 KB density payload and ~10 MB of
> resident growth. The payload-only native benchmark below measures the
> payload-build allocation in isolation (~2 MB, flat in N) — a different,
> narrower scope than this cross-library table. xy' "total" is
> prepare-the-GPU-payload (encode/bin kernel-side) while the raster libraries'
> "total" is to-pixels (a PNG), so the cleanest apples-to-apples columns are
> **peak memory**, **payload size**, and the **ceiling**.

### Ceiling — largest N rendered under a 45 s budget

| library | max points |
|---|---|
| xy | 10,000,000 (screen-bounded; not the real ceiling) |
| matplotlib | 10,000,000 |
| Plotly `Scattergl` | 10,000,000 |
| Plotly `Scatter` (SVG) | 3,000,000 |

xy' 10 M here is just the largest N the harness generated; its render
cost is flat in N (density surface), so the practical ceiling is data *ingest*,
not draw — the design targets 100 M–1 B (dossier §2).

---

## Full measured tables

### xy (native core; "render" = build GPU payload)

These per-N tables are the retained **2026-07-03** cross-library run. They
predate log-u8 density transport *and* the 2026-07-08 refresh that produced the
Headline table above, so their rows are not interchangeable with it — the
Plotly `Scattergl` 10M row here (33,907 ms) is the 07-03 measurement, while the
Headline's 54,064 ms is the later 07-08 re-measurement of the same
configuration. The current production refresh is reported above; these tables
are kept for the per-N scaling shape, not for headline figures.

| N | build | render | total | peak mem | payload | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 1 ms | 1 ms | 1 ms | 0 MB | 8 KB | 772,927 |
| 10,000 | 1 ms | 1 ms | 1 ms | 0 MB | 78 KB | 8,803,220 |
| 100,000 | 1 ms | 1 ms | 2 ms | 2 MB | 781 KB | 63,485,614 |
| 1,000,000 | 4 ms | 6 ms | 10 ms | 2 MB | **768 KB** | 102,397,515 |
| 3,000,000 | 11 ms | 20 ms | 31 ms | 2 MB | **768 KB** | 96,223,689 |
| 10,000,000 | 35 ms | 51 ms | 86 ms | 2 MB | **768 KB** | 116,889,352 |

In this retained run, the payload flips from 8 B/pt (direct) to a **constant 768 KB** at the density
threshold (200 k) — 0.08 B/pt at 10 M. This table's scope is xy'
payload-build allocation only, which stays near 2 MB regardless of N; the
cross-library **Headline** table above measures the full pipeline (build +
render, including transient working buffers for selection, sampling, and
encode staging), where xy' peak is 126 MB at 10 M and total is 169 ms
— the same-harness figures to compare against matplotlib/Seaborn/Plotly.

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
falls over. This is the path xy exists to replace.

---

## What the numbers show

1. **xy is the only one flat in N on the output side.** Above the
   density threshold its current render payload (~258 KB; 768–832 KB in the
   retained pre-quantization artifacts) and payload-build allocation
   (~2 MB) do not grow with point count; total time grows only with the linear
   ingest/bin pass. matplotlib grows ∝ N in time *and* memory; both Plotly paths
   grow ∝ N in memory and render time.
2. **Memory is the starkest axis.** At 10 M the full-pipeline peak is xy
   126 MB vs matplotlib 553 MB vs Seaborn 1.09 GB vs Plotly-GL 1.58 GB — and
   xy' *lasting* resident growth is only ~10 MB (its screen-bounded
   representation) vs +223–695 MB for the raster libraries, which hold every
   point and its copies resident. Ingest is zero-copy for f64 arrays, so
   xy' peak is transient working buffers (selection indices, sample
   gathers, encode staging), released once the density surface is built. This
   is the §1/§27 thesis.
3. **The SVG path has a hard ceiling** (~1–3 M, then unusable) exactly as
   predicted; the WebGL path scales further but pays ∝ N memory and seconds of
   render time.

## Caveats

- Data generation is excluded from every timing (shared arrays).
- `render` is not identical across targets (PNG rasterize vs GPU-payload build);
  see the fairness note above. Memory, payload size, and the ceiling are the
  clean cross-library comparisons.
- xy memory is Python-side `tracemalloc` peak; its GPU/native bytes are
  separate and itemized by `Figure.memory_report()` (§27). The payload column is
  the transport cost across the kernel→browser boundary.
- Single CI machine, one run; treat as order-of-magnitude, not a spec. Re-run in
  CI (`benchmark` job) or locally. No universal claims — every number is
  mode-scoped (dossier §2/§31).
