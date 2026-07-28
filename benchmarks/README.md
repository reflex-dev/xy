# Benchmark Runbook

Benchmark artifacts are environment-scoped. Never merge SwiftShader CI rows and
hardware-GPU rows into one table.

## Setup

Use Python 3.12, the repository Rust toolchain, Node 22, and Playwright 1.48:

```bash
cargo build --release
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python \
  --constraint benchmarks/requirements-ci.lock -e . --group dev --group codspeed
uv pip install -p .venv/bin/python \
  --constraint benchmarks/requirements-ci.lock \
  matplotlib seaborn plotly kaleido bokeh altair datashader hvplot \
  plotly-resampler psutil
npm ci
npx playwright install chromium
CHROME=$(node -e "console.log(require('playwright').chromium.executablePath())")
```

Run from a clean worktree. Keep the generated JSON files together; every report
contains package versions, executable versions, backend, commit, and dirty state.
The CI comparison dependencies and their transitives are pinned in
`benchmarks/requirements-ci.lock`; refresh it only with the command documented
at the top of `benchmarks/requirements-ci.in`.

## Core Launch Scatter Benchmarks

The launch suite tracks three fixed scatter contracts across 10k, 100k, 1M,
10M, and 1B points: CPU static PNG, default interactive first render, and
interactive CPU fallback through SwiftShader. Each successful cell is the mean
of three complete cold-process runs; interactive samples also use a fresh
browser. Terminal 1B failures are attempted once and are not averaged.

Reproduce the launch environment with its exact dependency versions. Both
baseline directories carry the same competitor pins, so either one reproduces
the comparison environment; use the newest for a fresh run:

```bash
BASELINE=benchmarks/launch_baselines/xy-main-2026-07-26/macos-arm64-m5-pro
uv sync --project "$BASELINE" --frozen --python 3.14.5
```

Run these commands from the repository revision containing the baseline. The
same directory contains `environment.json` with the exact source commit, Python,
Rust, Cargo, Node, Chrome, OS, and hardware versions used for the recorded run.

```bash
# Static CPU + default interactive paths.
uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --chrome "$CHROME" \
  --out launch-scatter-default.json

# Interactive browser CPU fallback.
uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --interactive-only --software --chrome "$CHROME" \
  --out launch-scatter-cpu-fallback.json
```

The immutable 0.1.0 launch baseline, report, and raw results live under
`benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/`. The 2026-07-26 rerun
that the README and public benchmarks page quote lives under
`benchmarks/launch_baselines/xy-main-2026-07-26/macos-arm64-m5-pro/`; it repeats
the same contracts against the same pinned competitor versions on the same
machine. Add a new version/environment directory for later launches; never
overwrite an earlier launch baseline or mix hardware and SwiftShader rows.

Warm the checkout before a measured run. A first invocation in a fresh worktree
pays for cold bytecode caches, Matplotlib's font cache, and Kaleido's browser
download, which inflate every library's first row by an amount that is not part
of any output contract. Run the suite once and discard it; publish the run after
it.

## Interactive Ceiling and Peak Memory

`bench_ceiling.py` answers a different question from the launch suite: not how
fast a fixed size renders, but **how many rows each library still lets a user
interact with, and what peak resident memory that costs**. It sweeps 10 through
100M rows and stops each arm where it actually breaks.

```bash
export CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
python benchmarks/bench_ceiling.py \
  --repetitions 3 --timeout 300 --memory-gib 36 \
  --chrome "$CHROME" --out ceiling-results.json
python benchmarks/summarize_ceiling.py ceiling-results.json
```

`summarize_ceiling.py` re-derives every published table and chart value from
the raw JSON; do not hand-type a number into the docs.

Six arms, and the differences between them are the point:

| Arm | Contract | What reaches the renderer |
| --- | --- | --- |
| `xy` | interactive-webgl | density grid above 200k rows, plus an 8,192-row retained sample |
| `xy-exact` | interactive-webgl | `density=False`; one marker per row |
| `plotly` | interactive-webgl | `px.scatter` default; `scattergl` above ~1k rows, one marker per row |
| `matplotlib` | interactive-server | WebAgg; server-side Agg raster, one marker per row |
| `datashader` | static-image | `Canvas.points` aggregation; **no** client-side interaction without a live holoviews/bokeh server |
| `plotly-resampler` | interactive-server | not applicable to unordered scatter — see below |

Rules this suite holds itself to:

- **No arm receives pre-thinned input.** Every arm is handed all N rows. What
  each library then does with them is recorded in `mode` and `points_rendered`,
  never assumed.
- **Aggregation is proven, not claimed.** Density arms carry a count oracle:
  datashader must sum to exactly N, and xy must report all N rows visible with
  its quantized grid preserving occupancy and maximum. The oracle used is in
  every row's `oracle` field.
- **The clock stops when every point is on screen.** `ttfr_ms` is Python build
  plus `visible_complete_ms`: the last canvas change before the full drawing
  buffer goes pixel-stable for 10 consecutive frames. Progressive renderers
  (Plotly's scattergl draws large scatters in chunks across frames) therefore
  get charged until their final chunk lands, not until their first paint —
  `first_frame_ms` records the first paint separately. A canvas still mutating
  after 30 s is `render_unstable`, a failure. The WebAgg arm pushes one
  complete server-rendered raster, so its first nonblank frame is already
  all-points-visible by construction.
- **Interactive has teeth.** A cell counts only if it reaches visible-complete,
  completes all 24 scripted zoom/pan steps, and is still nonblank at the
  restored home view. Intermediate gesture frames may legitimately be empty —
  a deep zoom can land on blank space, and at n=10 it usually does.
- **The two memory pools stay separate.** Plotly dies in the browser and
  Matplotlib/WebAgg dies in Python; one summed number would hide which.
- **Read browser memory against the n=10 row.** A headless Chrome with an empty
  profile already resides ~1 GiB before drawing anything. That is why the ladder
  starts at 10: it measures the floor so the chart-attributable part can be
  separated from it.
- **Sizes above a failure are `not_attempted`, not silently absent.** The row
  states which smaller size failed and how.

Two coverage limits are recorded rather than papered over. The WebAgg arm's
interaction is a server round trip this harness does not drive, so its ceiling
reflects first render alone (`gesture_measured: false`). And `plotly-resampler`
cannot express this workload at all: `FigureResampler` asserts monotonically
increasing x for every aggregator it ships, so an unordered scatter is rejected
before any downsampling happens. It is kept as an explicit `not_applicable` row
so the omission is visible; it belongs in a sorted time-series ladder instead.

## Interactive UX Benchmark

`bench_ux.py` measures what a user actually experiences on a **live
interactive chart**: how long until every point is on screen, how the chart
behaves during a zoom, and how long after the gesture until the picture is
final. Five arms, every one a real interactive deployment driven through its
own input path — no synthetic API calls:

| Arm | What runs | Zoom input |
| --- | --- | --- |
| `xy` | production `ChartView` over a WebSocket bridging `channel.handle_message` (deep zoom drills to exact rows) | real `WheelEvent` |
| `xy-exact` | same host, `density=False` | real `WheelEvent` |
| `plotly` | `px.scatter` HTML, `scrollZoom` enabled | real `WheelEvent` |
| `matplotlib` | WebAgg server + `mpl.js` | Zoom-tool rubber-band drags |
| `datashader` | hvPlot/HoloViews on a Bokeh server, `datashade=True` + `resample_when` | real `WheelEvent` |

```bash
export CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
python benchmarks/bench_ux.py \
  --sizes 100000 --arms xy,xy-exact,plotly,matplotlib,datashader \
  --chrome "$CHROME" --out ux-100k.json
```

### Every run records video

Recording is **on by default for every arm** — a benchmark that cannot be
watched cannot be checked. Each run produces:

| Artifact | What it is |
| --- | --- |
| `<out-stem>-video/<arm>-<n>/` | every frame the page presented, `NNNNNN_<offset_ms>.jpg`, offset measured from navigation |
| `<out-stem>-grid-<n>.mp4` | all arms replayed against one shared clock, assembled automatically |
| `<out-stem>-shots/` | the exact frames the clock stopped on (`visible-complete`, `settle-complete`) |

**The video is the load race: recording starts at navigation and stops the
moment that arm's chart is rendered** (`visible-complete`). So a panel ending
*is* that library finishing, and the gesture and settle clocks never carry
screencast cost at all.

In the grid, video time T is T ms after page load **for every panel
simultaneously** — each arm's frames carry offsets from its own navigation,
so replaying them on one clock makes the panels directly comparable. Panels
show black before their first frame and hold their last frame once done.

**Each panel is a stopwatch.** Its timer runs blue while that chart is
loading, then **freezes green on the arm's measured `visible_complete_ms`**
the moment it renders. The frozen figure is read from the run's own JSON
(`--report`), not inferred from the video, so what the panel displays is the
number the benchmark recorded — the video and the measurement cannot drift
apart.

Screencast cost is measured, not assumed: across three recorded and three
unrecorded runs of all five arms at 100k, the difference in
`visible_complete_ms` ranged **−5.9 ms to +5.7 ms** — smaller than each arm's
own run-to-run spread. Recording is therefore always on; `--no-record`
(and `--no-grid`) exist for debugging, not for measurement hygiene.

Frames are JPEG at whatever rate Chrome chose to present, while the
measurement clock reads the raw drawing buffer every animation frame. The
video is for verification; the JSON remains the measurement. The two agree:
on a recorded 100k run, four of five arms placed the probe's
`visible_complete_ms` inside the bracket between the last blank captured
frame and the first fully-drawn one — an independent check, since frame
timestamps come from the driver's clock and the probe's from
`performance.now()`.

Assemble a grid by hand from any recording:

```bash
python benchmarks/make_ux_grid.py <out-stem>-video --out grid.mp4
```

### The measurement contract

- **The clock stops only on a frame that is correct AND stable.** Correct =
  the scripted target domain plus **sentinel points** — rows planted at known
  coordinates during data generation — verified lit at their projected screen
  positions. Stable = the full readback surface byte-identical for 10
  consecutive frames. Stability alone would pass a stale raster while a
  server is still computing; correctness alone would pass a frame still being
  painted. Failures separate the two: `render_incorrect` / `render_unstable`.
- **Inputs replay on a fixed wall-clock schedule** (42 inputs at 33 ms), never
  paced by the library's frame rate, so a slow arm falls behind honestly. 42
  is a multiple of 6 so drag-based arms end on a completed box.
- **Load and interaction are separate clocks.** `visible_complete_ms` (load),
  then during-gesture statistics (frame p50/p95/max, dropped-frame %, achieved
  fps), then `settle_ms` — last input to correct-and-stable again.
  `zoom_to_final_ms` is the single end-to-end span, measured directly rather
  than summed: a p95 is one frame, not a duration, and adding it to settle
  would double-count the last gesture frame.
- **Both memory pools, both peaks.** Each host's process tree is polled every
  50 ms from spawn (`TreePeakPoller`), so build transients count; the browser
  tree is polled across the whole probe. Plotly's `to_html` build runs in its
  own child so its peak is attributable rather than charged to the harness.
- **`first_frame_ms` is published beside `visible_complete_ms`.** For
  single-pass renderers they agree to ~1 frame; for progressive renderers the
  gap measures how much a naive first-paint benchmark would have flattered
  them.

### Upstream behaviors worth knowing

Each cost a debugging cycle and is load-bearing for the numbers:

- **WebAgg**: `mpl.js` assigns to the read-only `button.classList` (silent
  no-op), so toolbar buttons have no classes — find the Zoom tool by its icon
  `img.alt`. A drag with any corner outside the axes bbox is **silently
  discarded**, so boxes are clamped inside `ax.bbox`. The client knows no axis
  limits, so the host serves server-side truth (`/state`: limits, projected
  sentinels, axes bbox). At large N a new drag waits for the previous redraw —
  a human cannot draw a box on a frame they have not seen.
- **Bokeh/datashader**: the websocket origin allowlist rejects `127.0.0.1`
  when it expects `localhost` (403, blank page, no server-side error). Bokeh 3
  renders into shadow DOM, so `document.querySelectorAll("canvas")` finds
  nothing — reach the raster through the plot view's `canvas_view.primary.el`
  and dispatch input at `events_el`. With `resample_when`, holoviews 1.23
  renders nothing until a **client** range event arrives; the adapter nudges
  once with a self-inverse wheel pair, which is what a human does to a blank
  plot.
- **Plotly**: `px.scatter` does not wheel-zoom without
  `config={"scrollZoom": True}`; at ≤1k rows it emits SVG (no canvas), so the
  probe counts `.scatterlayer .point` nodes instead.

## CI Software GL

These commands match the non-blocking GitHub Actions measurement lane:

```bash
.venv/bin/python benchmarks/bench_vs.py \
  --sizes 1e3,1e4,1e5,1e6,3e6,1e7 --budget 45 \
  --ttfr --ttfr-max-n 1e5 --chromium "$CHROME" --json benchmark.json
.venv/bin/python benchmarks/bench_line.py --sizes 1e5,1e6,1e7 \
  --ttfr --ttfr-max-n 1e5 --chromium "$CHROME" --json line.json
.venv/bin/python benchmarks/bench_2d_charts.py --profile standard \
  --ttfr --chromium "$CHROME" --json core-2d.json
.venv/bin/python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile standard --reps 21 --warmups 3 --target-speedup 10 \
  --require-target \
  --json pyplot-vs-matplotlib.json --out pyplot-vs-matplotlib.md
# `--profile huge` runs the same families at 1M+ points, where Matplotlib/Agg
# scales with N and xy's disclosed tiers (see the report's `xy tier` column)
# stay screen-bounded.
.venv/bin/python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile huge --reps 11 --warmups 2 \
  --json pyplot-vs-matplotlib-huge.json --out pyplot-vs-matplotlib-huge.md
# Opt-in high-memory production ceiling; fixture construction is untimed.
.venv/bin/python benchmarks/bench_scatter_native.py --sizes 1e9 --production \
  --large-numpy-generator --native-png --json scatter-1b.json
# Same production ceiling with 24 compact categorical groups.
.venv/bin/python benchmarks/bench_scatter_native.py --sizes 1e9 --production \
  --large-numpy-generator --categorical-groups 24 --native-png \
  --json scatter-categorical-1b.json
# Opt-in native static-heatmap ceiling; a 32768 side is 1,073,741,824 cells.
.venv/bin/python benchmarks/bench_heatmap_native.py --sides 32768 --reps 1 \
  --json heatmap-1b.json
# 64 GiB high-water probe; crosses the u32 total-count boundary.
.venv/bin/python benchmarks/bench_heatmap_native.py --sides 65536 --reps 1 \
  --json heatmap-4b.json
.venv/bin/python benchmarks/bench_interaction.py --sizes 1e4,2.5e5 \
  --reps 24 --chromium "$CHROME" --json interaction.json
.venv/bin/python benchmarks/bench_transport.py --n 1e6 --reps 15 \
  --browser-reps 12 --chromium "$CHROME" --require-browser \
  --json transport.json
.venv/bin/python benchmarks/bench_dashboard.py --chart-counts 10,20,50 \
  --chromium "$CHROME" --json dashboard.json
.venv/bin/python benchmarks/bench_workflows.py --profile standard --reps 5 \
  --chromium "$CHROME" --json workflows.json
.venv/bin/python benchmarks/bench_install.py --packages xy,plotly \
  --repeat 3 --fresh-venv --json install-fresh.json
```

For `bench_vs.py`, `--budget` is a hard wall-clock deadline for each
library/size row, including the untimed memory pass and any in-scope browser
TTFR work. A timed-out row and every larger size for that library remain
explicitly present as skipped rows. Browser artifact serialization is only
performed through `--ttfr-max-n`; larger rows do not build HTML that will not
be painted.

The browser helpers force SwiftShader themselves. Validate every artifact before
publication with `scripts/verify_benchmark_report.py --kind ...`.

`bench_transport.py` is a loopback transport diagnostic: both HTTP response
formats dispatch through `channel.handle_message()`. Its binary arm uses xy's
production versioned frame and the shipped JavaScript decoder. Browser rows
measure request through decode and the next animation frame; they do not claim
request-to-pixels or GPU-upload latency. The report also records current widget
append retransmission and unaffected-trace bytes so later fixes have an explicit
before/after baseline.

The CodSpeed suite is the reproducible backend/per-payload gate. Every
module named `test_codspeed_*.py` is collected, so adding a dedicated CodSpeed
test module automatically adds its benchmarks to the CI run:

```bash
cargo build --release
uv run --group dev --group codspeed python -m pytest \
  benchmarks/test_codspeed_*.py --codspeed
```

The kernel/payload module requires the native Rust backend; the transport codec
module is dependency-free Python but runs in the same job. The GitHub Actions
workflow runs the suite in CodSpeed simulation mode. The browser interaction, dashboard,
cross-library, and fresh-install workloads remain in the benchmark-refresh
workflow because they need a real browser, separate processes/virtual
environments, or wall-clock timing. They are still measured in CI, but are not
reported as CodSpeed simulation benchmarks.

The suite includes the million-row fixed-width categorical factorizer and the
allocation-bounded implicit-row stratified sampler as standalone kernel rows,
alongside the complete categorical first-payload row. Together they distinguish
native encoding/sampling regressions from payload-policy or transport
regressions.

`test_codspeed_pyplot.py` tracks the `xy.pyplot` shim's overhead against the
raw declarative API: each workload (line 10k/1M, scatter 100k, histogram,
categorical bars, a chrome-heavy styled panel, and static PNG export) is built
twice from the same arrays — once with `xy.chart` + marks and once with the
identical Matplotlib-style calls — ending in the same split wire payload or
PNG bytes. The `*_pyplot` minus `*_raw` gap is the shim; both rows moving
together is the shared engine. `tests/pyplot/test_perf_guardrail.py` remains
the hard relative gate; these rows exist so a shim regression is attributed
to the shim arm in CodSpeed instead of surfacing as an engine slowdown.

`test_codspeed_transport.py` separately tracks production frame encode,
scatter/gather part construction, and zero-copy decode at representative density
and direct-payload sizes, with base64 JSON encode/decode comparator rows. The
loopback/browser harness remains authoritative for HTTP, compression, JS heap,
and request-to-next-frame measurements.

`test_codspeed_animation.py` attributes the animation data plane separately:
100k stable-key encoding, the plain 100k scatter payload, and the same payload
with keyed transition columns — both payload rows through the widget's
production split transport. Run `bench_animation.py` for real-Chrome
`updatePayload` time, animation-frame pacing, heap delta, and the hard
previous+next scene bound; browser clocks and GPU work do not belong in
CodSpeed simulation.

`test_codspeed_selection.py` covers the backend handlers the client's gesture
messages resolve to: hover pick readout with a categorical channel, zone-pruned
and full-scan box select at 1M points, and the cross-filter
rows-to-shipped-mask encoding over a NaN-dropped trace so the
canonical-to-shipped translation is the path measured. `bench_interaction.py`
stays authoritative for client input-to-pixel latency; these rows attribute a
selection regression to the Python/kernel handler that caused it.

## Reference Hardware

Set `XY_BENCH_HARDWARE_GL=1` to disable the benchmark helpers' SwiftShader
flags. Artifacts record `environment.browser_renderer=hardware`.
The workflow benchmark measures native Rust PNG separately from the opt-in
`engine=Engine.chromium` screenshot row. The Chromium adapter remains
`software-gl` because it forces SwiftShader; keep it out of hardware-GPU comparisons.
Record CPU model/core count, RAM, GPU and driver, OS build, power mode, browser
version, Python, Rust, Node, package versions, commit, and ambient workload.

Run at least three complete process-level repetitions. Publish medians and raw
JSON artifacts, retain failed/over-budget rows, and label the table
`reference hardware` rather than `CI (software GL)`.

## Interpretation

- Static target rows (`binary-spec`, HTML, Agg PNG, Kaleido PNG) are not direct
  speedup comparisons.
- `bench_pyplot_vs_matplotlib.py` is the exception by construction: both arms
  use the same Matplotlib-style calls and emit validated, nonblank 1800×840
  PNGs. Use its `total_median_ms` for chart-to-pixels comparisons; its build
  stage is diagnostic because xy defers work until export.
- Interactive TTFR is build + HTML serialization + chart-ready time.
- Interaction browser rows are standalone client input-to-pixel-readback;
  backend LOD and selection-handler work is in CodSpeed and workflow rows.
- Dashboard rows attempt 10/20/50 charts, retain timings for partial dashboards,
  record per-chart context loss/restoration plus initial/scrolled nonblank IDs,
  and publish the largest stable loss-free count.
- Density rows must include a count-conservation oracle and explicit aggregate
  dimensions. A density result is not an exact-marker result.
