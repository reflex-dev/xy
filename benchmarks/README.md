# Benchmark Runbook

Benchmark artifacts are environment-scoped. Never merge SwiftShader CI rows and
hardware-GPU rows into one table.

## Setup

Use Python 3.12, the repository Rust toolchain, Node 22, and Playwright 1.48:

```bash
cargo build --release
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python \
  --constraint benchmarks/requirements-ci.lock -e ".[dev,codspeed]"
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

Reproduce the 0.1.0 launch environment with its exact dependency versions:

```bash
BASELINE=benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro
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
`benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/`. Add a new
version/environment directory for later launches; never overwrite an earlier
launch baseline or mix hardware and SwiftShader rows.

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
uv run --extra dev --extra codspeed python -m pytest \
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
  backend LOD work is in CodSpeed and workflow rows.
- Dashboard rows attempt 10/20/50 charts, retain timings for partial dashboards,
  record per-chart context loss/restoration plus initial/scrolled nonblank IDs,
  and publish the largest stable loss-free count.
- Density rows must include a count-conservation oracle and explicit aggregate
  dimensions. A density result is not an exact-marker result.
