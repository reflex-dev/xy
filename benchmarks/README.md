# Benchmark Runbook

Benchmark artifacts are environment-scoped. Never merge SwiftShader CI rows and
hardware-GPU rows into one table.

## Setup

Use Python 3.12, the repository Rust toolchain, Node 22, and Playwright 1.48:

```bash
cargo build --release
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python -e ".[dev,codspeed]"
uv pip install -p .venv/bin/python matplotlib seaborn plotly kaleido bokeh \
  altair datashader hvplot plotly-resampler psutil
npm i --no-save playwright@1.48
npx playwright install chromium
CHROME=$(node -e "console.log(require('playwright').chromium.executablePath())")
```

Run from a clean worktree. Keep the generated JSON files together; every report
contains package versions, executable versions, backend, commit, and dirty state.

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
.venv/bin/python benchmarks/bench_dashboard.py --chart-counts 10,20,50 \
  --chromium "$CHROME" --json dashboard.json
.venv/bin/python benchmarks/bench_workflows.py --profile standard --reps 5 \
  --chromium "$CHROME" --json workflows.json
.venv/bin/python benchmarks/bench_install.py --packages xy,plotly \
  --repeat 3 --fresh-venv --json install-fresh.json
```

The browser helpers force SwiftShader themselves. Validate every artifact before
publication with `scripts/verify_benchmark_report.py --kind ...`.

The native CodSpeed suite is the reproducible backend/per-payload gate. Every
module named `test_codspeed_*.py` is collected, so adding a dedicated CodSpeed
test module automatically adds its benchmarks to the CI run:

```bash
cargo build --release
uv run --extra dev --extra codspeed python -m pytest \
  benchmarks/test_codspeed_*.py --codspeed
```

It requires the native Rust backend. The GitHub Actions workflow runs the same
suite in CodSpeed simulation mode. The browser interaction, dashboard,
cross-library, and fresh-install workloads remain in the benchmark-refresh
workflow because they need a real browser, separate processes/virtual
environments, or wall-clock timing. They are still measured in CI, but are not
reported as CodSpeed simulation benchmarks.

The suite includes the million-row fixed-width categorical factorizer and the
allocation-bounded implicit-row stratified sampler as standalone kernel rows,
alongside the complete categorical first-payload row. Together they distinguish
native encoding/sampling regressions from payload-policy or transport
regressions.

## Reference Hardware

Set `XY_BENCH_HARDWARE_GL=1` to disable the benchmark helpers' SwiftShader
flags. Artifacts record `environment.browser_renderer=hardware`.
The workflow benchmark measures native Rust PNG separately from the opt-in
`engine="chromium"` screenshot row. The latter remains `software-gl` because
the Chromium exporter forces SwiftShader; keep it out of hardware-GPU comparisons.
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
