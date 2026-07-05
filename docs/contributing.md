# Contributing

fastcharts is still alpha, so the contribution bar is mostly about not losing
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
`WHEEL_EXPECT=--expect-pure` for an intentional fallback artifact.

When CI, a release job, or a local build has already produced artifacts, verify
those exact files with:

```bash
make check-artifacts SDIST=/path/to/fastcharts.tar.gz WHEEL=/path/to/fastcharts.whl
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

When you edit README snippets, `docs/api-examples.md`, or the Reflex example
dashboard registry/assets, run:

```bash
make check-examples
```

When you touch standalone HTML export, user-facing text surfaces, tooltips,
legends, or the browser client DOM code, run:

```bash
make check-security
```

When you change validation, public errors, builder rollback behavior, or chart
composition caching, run:

```bash
make check-errors
```

When you add, remove, rename, or re-type a public export, run:

```bash
make check-api
```

When you change `fastcharts.__init__`, lazy imports, widget/export boundaries,
or backend import setup, run:

```bash
make check-import
```

For browser render smoke checks, pass a local Chrome/Chromium executable:

```bash
make check-browser CHROMIUM=/path/to/chrome
```

On macOS, pass the executable inside the app bundle, for example
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, not the
`.app` directory.

Use `make list-checks` to see check names, or
`python scripts/verify_local.py --dry-run --full` to print commands without
running them. Browser checks are listed even before a Chrome path is configured;
dry-run output uses `<CHROMIUM>` until you pass `--chromium` or `CHROMIUM=...`.

## Pull Request Checklist

- Public errors are actionable and name the bad parameter.
- Failed public builder calls leave `Figure.traces`, `ColumnStore`, and category
  axes unchanged.
- `import fastcharts` stays lazy and under budget in fresh interpreters; no
  NumPy/native-core import on package import, including with
  `FASTCHARTS_FORCE_FALLBACK=1`.
- Standalone HTML handles hostile user strings in every text surface touched by
  the patch; run `make check-security` for export/client text-sink changes.
- Benchmarks label mode truthfully: `direct`, `decimated`, `density`, `sampled`,
  or `adaptive`.
- README/docs examples still match the current public API.
- New public exports appear in `fastcharts.__all__`, lazy `_EXPORTS`, and tests;
  run `make check-api` after public export or annotation changes.
- Lazy import boundaries still keep package import light; run
  `make check-import` after changing `fastcharts.__init__`, export helpers,
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

When in doubt, phrase it as a measured row from `docs/benchmark.md`, not as a
universal product claim, and run `make check-claims` before publishing.
