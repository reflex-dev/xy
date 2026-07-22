# Contributing

xy is still alpha, so the contribution bar is mostly about not losing
the hard-won production invariants while the chart surface grows.

## Before You Start

- Work from latest `main`.
- Keep finance/domain-specific experiments on feature branches until the core
  chart surface is ready to absorb them.
- Avoid changing renderer, LOD, Rust kernels, public API, and example assets in
  the same patch unless the behavior genuinely spans those layers.
- For generated example assets, update the source generator first, then refresh
  the asset. Do not patch only the generated HTML unless you are applying an
  emergency local fix and immediately back-porting it to the generator.

## Local Checks

Install the dev environment and build the required native core:

```bash
make setup
```

`make setup` requires a Rust toolchain because it runs `cargo build --release`
after installing the editable Python package. This leaves the checkout ready
to import `xy.kernels` and run the fast gate.

Run the fast local gate:

```bash
make check
```

Before a production-facing PR, run:

```bash
make check-full
```

`make check-full` expects Node 18+ for the JavaScript bundle check and a Rust
toolchain with `cargo`, `rustc`, and clippy for native-core checks. If clippy is
missing, run `rustup component add clippy`. If you are only touching docs or
pure Python shell code, `make check` is the fast non-JS/non-Rust gate.

When README/API prose changes, run the focused docs gate:

```bash
make check-docs
```

When packaging, workflows, or source-distribution/wheel contents change, run:

```bash
make check-sdist
make check-wheel
```

When you edit `.github/workflows/ci.yml`, `.github/workflows/release.yml`, or
release/benchmark artifact wiring, run:

```bash
make check-ci
```

Set `WHEEL_EXPECT=--expect-native` for native release wheels, or
`WHEEL_EXPECT=--expect-pure` for an intentional no-native artifact (which
imports but errors clearly the moment compute is needed).

When CI, a release job, or a local build has already produced artifacts, verify
those exact files with:

```bash
make check-artifacts SDIST=/path/to/xy.tar.gz WHEEL=/path/to/xy.whl
```

When you generate a benchmark JSON artifact locally, validate it before copying
numbers into docs or posts:

```bash
make check-benchmark-report BENCHMARK_JSON=benchmark.json BENCHMARK_KIND=scatter-vs
```

For the dashboard release contract, select outcome enforcement explicitly:

```bash
make check-benchmark-report BENCHMARK_JSON=dashboard.json \
  BENCHMARK_KIND=dashboard-browser BENCHMARK_PROFILE=strict
```

`BENCHMARK_KIND` accepts `auto`, `scatter-vs`, `core-2d`,
`pyplot-vs-matplotlib`, `scatter-native`, `heatmap-native`, `kernel-native`,
`interaction-browser`, `dashboard-browser`, `workflow-native`,
`line-decimation`, `install-footprint`, and `transport-loopback`; the
authoritative list is `KNOWN_KINDS` in `scripts/verify_benchmark_report.py`. The
verifier prints a compact report summary with the detected kind, row count,
statuses, categories, backend, and git commit so CI logs remain self-describing.

When you edit benchmark harness code, benchmark environment metadata,
regression comparison scripts, or report-schema validation, run:

```bash
make check-benchmark-harness
```

When you edit public docs, README text, package metadata, benchmark summaries,
or anything that could become a public performance claim, run:

```bash
make check-claims
```

When you edit README snippets, `spec/api/api-examples.md`, or the Reflex example
dashboard registry/assets, run:

```bash
make check-examples
```

When you touch `python/xy/pyplot/` or the matplotlib compatibility corpus, run:

```bash
make check-pyplot
```

This first rejects newly accepted-but-unused pyplot options against the
reviewed `spec/testing/pyplot-noops.json` contract, then runs the shim suite.

When reviewing coverage evidence or changing a shipped Python branch, validate
the retained report against the exact comparison range:

```bash
make check-coverage COVERAGE_JSON=coverage/python/coverage.json \
  COVERAGE_BASE=origin/main COVERAGE_HEAD=HEAD
```

Package/module floors and exclusions live in
`spec/testing/coverage-policy.json`; they are reviewed policy, not generated
output.

When you change shim rendering performance, run `make check-pyplot-speed`, which
enforces the per-family 10x static-PNG target via
`benchmarks/bench_pyplot_vs_matplotlib.py` and requires the `.[bench]` extra.

When you touch standalone HTML export, path writes, user-facing text surfaces,
tooltips, legends, or the browser client DOM code, run:

```bash
make check-security
```

When you change validation, public errors, builder rollback behavior, chart
composition caching, or LOD/drill mutation boundaries, run:

```bash
make check-errors
```

When you add, remove, rename, or re-type a public export, run:

```bash
make check-api
```

When you change `xy.__init__`, lazy imports, dependency boundaries,
widget/export boundaries, or backend import setup, run:

```bash
make check-import
```

For browser render smoke checks, pass a local Chrome/Chromium executable:

```bash
make check-browser CHROMIUM=/path/to/chrome
```

This runs split browser checks, which CI runs as separate steps:

| Check | CI step name |
| --- | --- |
| `render_smoke_nonumpy` | `Headless render smoke (stdlib + Chromium)` |
| `smoke_render` | `Real-Figure render smoke (numpy + Chromium)` |
| `runtime_security_smoke` | `Runtime standalone security smoke (Chromium)` |
| `reflex_lifecycle_smoke` | `Browser lifecycle smoke (Chromium)` |
| `visual_health_smoke` | `Browser visual health smoke (Chromium)` |
| `visual_baseline` | `Reviewed visual baseline (Chromium)` |
| `chart_kind_matrix` | `Every chart-kind render matrix (Chromium)` |
| `step_tier_smoke` | `Step tier-update smoke (Chromium)` |
| `interaction_stress_smoke` | `Browser interaction stress smoke (Chromium)` |

The stdlib payload gate runs `scripts/render_smoke_nonumpy.py`. It hand-builds a
payload from stdlib `array` and `struct` in exactly the wire shape
`build_payload` emits, drives the standalone JS bundle in Chromium, and reads
back a lit-pixel count via `gl.readPixels`. It needs neither numpy nor PyPI, so
it covers the render client in a locked-down environment.

The real-Figure gate runs `scripts/smoke_render.py`. It builds a standalone page
the same way `Chart.to_html` does from an actual Figure (line decimation plus
scatter), then counts non-transparent pixels via `gl.readPixels`. This is the
end-to-end Figure-to-browser path that the hand-built stdlib smoke cannot reach.

The step tier gate runs `scripts/step_tier_smoke.py`. Step geometry is expanded
client-side after LOD, so both upload paths — the initial build and the
`tier_update` refinement that replaces vertex buffers on zoom — must run the
same expansion. It renders a decimated `step` chart, feeds the view a synthetic
`tier_update` exactly as the kernel would ship it, and asserts the re-uploaded
vertex stream still contains the step risers.

The lifecycle gate runs `scripts/reflex_lifecycle_smoke.py`: it boots the
`examples/fastapi` app under uvicorn and drives Chromium at each gallery chart
route plus `/drilldown`, injecting a probe over CDP before the chart client
loads. Each chart must stay nonblank through the `initial`, `narrow-resize`,
`wide-resize`, `visibility-change`, `context-restore`, and `restore` phases and
keep its runtime DOM slots. The `context-restore` phase forces
`WEBGL_lose_context` loss/restoration and requires the rebuilt chart to remain
nonblank. A final pass loads the index page and confirms its embedded iframes
paint. A blank, destroyed, shortened lifecycle, failed context restore, or
missing DOM slot is a failing browser gate.

The visual-health gate runs `scripts/visual_health_smoke.py`. It boots the same
app and screenshots every gallery chart route plus `/drilldown`, checking
global nonblank/color/unique-color invariants, rejecting collapsed plot
occupancy, and running tick-label overlap probes. It remains broad health
coverage and does not claim image identity.

The reviewed identity gate runs `scripts/visual_baseline.py` against the small
versioned set in `spec/visual-baselines/v1.json`. It pins Playwright Chromium,
the repository Instrument Sans font and its checksum, viewport, DPR,
downsample, and explicit semantic/geometry/perceptual tolerances. Every hard
run also proves that real-browser corrupted-data, wrong-color, wrong-label, and
wrong-geometry controls are rejected, and CI retains expected, actual, and diff
PNGs plus semantic JSON.

Baseline changes are proposals, never self-approval. Generate one only with the
pinned Playwright executable, a named preparer, and a concrete reason:

```bash
CHROMIUM="$(node -e "const {chromium}=require('playwright'); process.stdout.write(chromium.executablePath())")"
python scripts/visual_baseline.py "$CHROMIUM" --update-baselines \
  --prepared-by "Your Name" --reason "intentional renderer change" \
  --artifacts visual-baseline-review
```

Attach `visual-baseline-review/` to the pull request. An independent reviewer
must inspect the expected/actual/diff images, semantic changes, fixture intent,
browser/font pins, and tolerances before approving the manifest. In proposal
artifacts, `expected` is the prior reviewed baseline and `actual` is the new
candidate. CI refuses update mode; do not refresh a baseline merely to make an
unexplained failure green.

The interaction gate runs `scripts/interaction_stress_smoke.py`, a smoke-sized
interaction benchmark that validates p95 budgets and visual invariants for
wheel zoom, pan, hover, crosshair, box zoom, and brush select. The smoke
includes both a direct scatter and a density-tier scatter, plus line, histogram,
bar, and heatmap rows. It fails on blank interaction frames, tick-label
overlaps, tooltip flicker, eligible tooltips that do not stay visible for every
repeated hover sample, missing crosshair chrome, missing view changes, box zoom
that does not narrow/restore the viewport, brush selection that does not
select/clear eligible marks, undersized lit-pixel readbacks, and oversized frame
color jumps.
The same gate launches the standalone density re-bin path with real wall-clock
Playwright, and requires proof that a worker was created, returned a re-binned
nonblank view, changed the requested range, and was terminated and cleared by
`ChartView.destroy()`. Missing Node/Playwright, skipped workers, incomplete
evidence, and failed teardown are blocking by default. Only a direct local
diagnostic run may opt out with `--allow-worker-skip`; `make check-browser` and
CI never pass that flag.

On macOS, pass the executable inside the app bundle, for example
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, not the
`.app` directory.

Use `make list-checks` to see check names, or
`python scripts/verify_local.py --dry-run --full` to print commands without
running them. `--dry-run --full` prints only the quick and full gates; browser
checks are appended only with `--browser`, which requires `--chromium PATH`.
`make list-checks` does show the browser checks before a Chrome path is
configured, marked `[requires chromium]`. To see a browser command rendered with
the `<CHROMIUM>` placeholder, name it explicitly, for example
`python scripts/verify_local.py --dry-run --only reflex_lifecycle_smoke`.

## Pull Request Checklist

- Public errors are actionable and name the bad parameter.
- Failed public builder calls leave the internal `_figure.Figure` traces,
  `ColumnStore`, and category axes unchanged.
- `import xy` stays lazy and under budget in fresh interpreters; no
  NumPy/native-core import on package import.
- Standalone HTML handles hostile user strings in every text surface touched by
  the patch; run `make check-security` for export/client text-sink changes and
  `make check-browser CHROMIUM=/path/to/chrome` for runtime DOM/CSP changes.
- Benchmarks label mode truthfully: `direct`, `decimated`, `density`, `sampled`,
  or `adaptive`.
- README/docs examples still match the current public API.
- New public exports appear in `xy.__all__`, lazy `_EXPORTS`, and tests;
  run `make check-api` after public export or annotation changes.
- Lazy import boundaries still keep package import light; run
  `make check-import` after changing `xy.__init__`, export helpers,
  widget creation, or backend imports.
- Wheel/sdist contents still include JS bundles, an empty full-package
  `py.typed` marker, valid package metadata, and the right native/pure tagging
  behavior.
- Example-app generated assets match their source generator.

## Adding A Chart Type

Start with the smallest reusable primitive surface:

- Python builder validation and mutation-safety tests.
- Column-store ingest path or aggregate kernel.
- Payload emitter with explicit tier/mode metadata.
- Renderer mark path or reuse of an existing mark primitive.
- Standalone HTML/export tests for weird labels, names, and categories.
- Composition API wrapper if the chart is user-facing.
- Example app card with normal-size data, not only a stress demo.
- Benchmark row only when the comparison methodology is honest.

## Performance Claims

Do not write broad claims like "faster than Plotly" without naming:

- chart type
- data size and shape
- backend (always `native`; there is no NumPy fallback)
- render target
- whether browser time-to-first-render is included
- whether the result is exact markers, decimated geometry, density, or adaptive

Numeric multipliers such as "10x faster" or "5x smaller" need the same measured
benchmark context.

When in doubt, phrase it as a measured row from `spec/benchmarks/results.md`, not as a
universal product claim, and run `make check-claims` before publishing.
