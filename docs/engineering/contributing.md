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

Install the dev environment:

```bash
uv venv
uv pip install -e ".[dev]"
```

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

Use `BENCHMARK_KIND=line-decimation`, `install-footprint`, `core-2d`,
`scatter-native`, `kernel-native`, or `auto` for the other report shapes. The
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

When you edit README snippets, `docs/engineering/api-examples.md`, or the Reflex example
dashboard registry/assets, run:

```bash
make check-examples
```

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

This runs the same split browser checks that CI names as `Browser lifecycle
smoke (Chromium)`, `Browser visual regression smoke (Chromium)`, and `Browser
interaction stress smoke (Chromium)`.

The lifecycle gate runs `scripts/reflex_lifecycle_smoke.py`: every committed
XY demo asset is loaded repeatedly, and each child chart must stay
nonblank through the named
`initial`, `hash-navigation`, `narrow-resize`, `wide-resize`, `scroll-bottom`,
`fast-scroll`, `visibility-change`, `context-restore`, and `restore` phases.
The `context-restore` phase forces `WEBGL_lose_context` loss/restoration and
requires the rebuilt chart to remain nonblank. The iframe shell also exercises
hash navigation, fast scrolling, resize and visibility events, a full iframe
remount, an in-place iframe reload, and a hidden-boot/reveal pass where charts
initialize at zero-sized iframe dimensions before becoming visible. The custom
chrome, business overview, and retention cohort assets are tracked as critical
reports in every shell phase. A blank, destroyed, shortened lifecycle, failed
context restore, or missing critical asset/phase pair is a failing browser gate.

The visual gate runs `scripts/visual_regression_smoke.py`. It is layout-aware:
beyond global nonblank/color checks, it verifies title, plot, x-axis, and y-axis
regions, rejects collapsed plot occupancy, and still runs tick-label overlap
probes. It screenshots the generated core-family cases plus every committed
XY Reflex gallery asset; the Plotly comparison page is intentionally
excluded because it does not use XY' DOM or tick-label probes. It also
screenshots static Reflex-style chrome shells for the custom legend/tooltip and
annotated heatmap examples, requiring their external chrome DOM to be present
and visible. This catches charts that render pixels in the wrong place or lose
browser chrome while avoiding a fragile pixel-perfect golden file.

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

On macOS, pass the executable inside the app bundle, for example
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, not the
`.app` directory.

Use `make list-checks` to see check names, or
`python scripts/verify_local.py --dry-run --full` to print commands without
running them. Browser checks are listed even before a Chrome path is configured;
dry-run output uses `<CHROMIUM>` until you pass `--chromium` or `CHROMIUM=...`.

## Pull Request Checklist

- Public errors are actionable and name the bad parameter.
- Failed public builder calls leave the internal `_figure.Figure` traces,
  `ColumnStore`, and category axes unchanged.
- `import xy` stays lazy and under budget in fresh interpreters; no
  NumPy/native-core import on package import.
- Standalone HTML handles hostile user strings in every text surface touched by
  the patch; run `make check-security` for export/client text-sink changes.
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
- backend (`native` or `numpy`)
- render target
- whether browser time-to-first-render is included
- whether the result is exact markers, decimated geometry, density, or adaptive

Numeric multipliers such as "10x faster" or "5x smaller" need the same measured
benchmark context.

When in doubt, phrase it as a measured row from `docs/engineering/benchmark.md`, not as a
universal product claim, and run `make check-claims` before publishing.
