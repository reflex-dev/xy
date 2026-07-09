# Benchmark Runbook

Benchmark artifacts are environment-scoped. Never merge SwiftShader CI rows and
hardware-GPU rows into one table.

## Setup

Use Python 3.12, the repository Rust toolchain, Node 22, and Playwright 1.48:

```bash
cargo build --release
uv venv .venv --python 3.12
uv pip install -p .venv/bin/python -e ".[dev]"
uv pip install -p .venv/bin/python matplotlib seaborn plotly kaleido bokeh \
  altair datashader hvplot plotly-resampler psutil pytest-codspeed
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
.venv/bin/python benchmarks/bench_interaction.py --sizes 1e4,2.5e5 \
  --reps 24 --chromium "$CHROME" --json interaction.json
.venv/bin/python benchmarks/bench_dashboard.py --chart-counts 10,20,50 \
  --chromium "$CHROME" --json dashboard.json
.venv/bin/python benchmarks/bench_workflows.py --profile standard --reps 5 \
  --chromium "$CHROME" --json workflows.json
.venv/bin/python benchmarks/bench_install.py --packages fastcharts,plotly \
  --repeat 3 --fresh-venv --json install-fresh.json
```

The browser helpers force SwiftShader themselves. Validate every artifact before
publication with `scripts/verify_benchmark_report.py --kind ...`.

## Reference Hardware

Set `FASTCHARTS_BENCH_HARDWARE_GL=1` to disable the benchmark helpers' SwiftShader
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
- Interactive TTFR is build + HTML serialization + chart-ready time.
- Interaction browser rows are standalone client input-to-pixel-readback;
  backend LOD work is in CodSpeed and workflow rows.
- Dashboard rows attempt 10/20/50 charts and publish the largest fully nonblank
  count, including context-limit failures.
- Density rows must include a count-conservation oracle and explicit aggregate
  dimensions. A density result is not an exact-marker result.
