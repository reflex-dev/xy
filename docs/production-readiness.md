# Production Readiness

This is the release bar for fastcharts while the core renderer is still moving.
It separates hard gates from advisory measurements so performance claims,
packaging promises, and API stability do not depend on memory or vibes.

## Current Contract

fastcharts is early alpha. The goal is Plotly-class chart breadth with a
screen-bounded performance core, but the stable commitments today are narrower:

- Python 3.11+ only.
- `import fastcharts` stays lightweight and does not import NumPy or load the
  native core, even when `FASTCHARTS_FORCE_FALLBACK=1` is set. The public API
  gate verifies this in fresh interpreters and keeps package import under a
  200 ms budget. Chart-building APIs are the compute import boundary; notebook
  widget dependencies stay deferred until `.widget()`/display, and standalone
  HTML export reads its static bundle without importing the widget stack.
- Published wheels include only the shippable `fastcharts/` package,
  `.dist-info`, static JavaScript bundles, `py.typed`, and, for native wheels,
  the Rust core. End users do not need Rust, Node, npm, or a CDN.
- Source distributions include the release support surface: docs, tests,
  benchmark harnesses/baselines, scripts, Rust/JS source, and the Reflex example
  app source plus generated chart assets.
- Source installs succeed without Rust by using the NumPy fallback with a loud
  warning.
- Standalone HTML exports embed the same render client and data payloads used
  by notebooks.
- Benchmark reports must label rendering modes explicitly: `direct`,
  `decimated`, `density`, `sampled`, or `adaptive`.

The composition API, chart-type set, visual styling surface, and Reflex
integration are still experimental and may change before a 1.0 release.

## Release-Blocking Gates

These must pass before publishing or making a broad performance claim.

| Area | Gate | Command or evidence |
|---|---|---|
| Python floor | `pyproject.toml`, Ruff, docs, syntax, and annotations stay on the Python 3.11+ floor | `python scripts/check_python_floor.py` |
| Public API | `__all__`, lazy exports, `__version__`, the source `py.typed` marker, focused type-surface tests, and fresh-process import-time budget stay coherent | `make check-api` |
| Import-time budget | `fastcharts.__init__`, `dir(fastcharts)`, export helpers, Figure construction, and `.widget()` keep their lazy import boundaries | `make check-import` |
| Claim guardrails | Public docs and package metadata avoid broad, unqualified performance claims | `make check-claims` |
| CI/release workflows | Hard gates, non-blocking benchmarks, best-effort benchmark artifact upload/download, trusted publishing, and fallback jobs stay wired | `make check-ci` |
| HTML export safety | Inline JSON/script escaping, atomic path writes, hostile user strings, and browser client text-node insertion stay protected | `make check-security` |
| Python tests | Native backend and NumPy fallback both pass | `pytest -q` and `FASTCHARTS_FORCE_FALLBACK=1 pytest -q` |
| Python style | Library, tests, scripts, and benchmarks lint clean | `ruff check .` and `ruff format --check .` |
| Type surface | Shippable library is type-checkable and ships a full-package `py.typed` marker | `ty check python` |
| Rust core | Native kernels pass and lint clean | `cargo test` and `cargo clippy --all-targets -- -D warnings` |
| Native ABI | C ABI can be loaded from the built core | `python scripts/abi_smoke.py` |
| JavaScript | Committed bundles match source | `node js/build.mjs --check` |
| Browser render | WebGL smoke reaches real pixels | `python scripts/render_smoke_nonumpy.py <chromium>` |
| Real figure render | A real `Figure` exports and paints in Chromium | `python scripts/smoke_render.py <chromium>` |
| sdist | Source archive contains required source/bundles, benchmark regression harness/baseline, release docs/tests/scripts, the Reflex example app, `PKG-INFO` version/dependencies matching `pyproject.toml`, no duplicate members, and no generated junk | `python scripts/verify_sdist.py dist/*.tar.gz` |
| Native wheel | Platform wheel contains package-only files, exactly one native library, `METADATA` version/dependencies matching `pyproject.toml`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, and is tagged non-pure | `python scripts/verify_wheel.py dist/*.whl --expect-native` |
| Fallback wheel | No-toolchain wheel contains package-only files, `METADATA` version/dependencies matching `pyproject.toml`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, is pure, and contains no native library | `python scripts/verify_wheel.py dist/*.whl --expect-pure` |
| Wheel size | Platform wheel remains small enough for notebook installs | CI budget: 15 MB |
| Benchmark artifact | JSON benchmark reports carry schema, environment, categories, row status, and finite non-negative metrics; `scatter-native` and `kernel-native` reports must declare the native backend | `python scripts/verify_benchmark_report.py benchmark.json --kind scatter-vs`; repeat for `line.json --kind line-decimation`, `install.json --kind install-footprint`, `scatter.json --kind scatter-native`, and `kernel.json --kind kernel-native` |

## Standalone HTML Safety

`Figure.to_html()` produces one self-contained document: inline JavaScript,
inline JSON spec, and a base64 data blob. That shape is convenient for notebooks,
reports, and sharing a single file, but it has a clear security contract:

- User-controlled strings in titles, labels, legends, trace names, categories,
  and series names must be escaped before entering inline JSON or `<title>`.
- The bundled standalone client is escaped before inlining so a literal
  `</script>` inside future client source cannot terminate the script element.
- The export rejects `NaN` and infinity in JSON metadata instead of emitting
  browser-dependent invalid JavaScript.
- Path-based exports write through a same-directory temporary file and only
  replace the target after the full document is flushed, so failed writes do
  not corrupt the previous standalone artifact.
- The standalone file emits a defensive `Content-Security-Policy` meta tag that
  blocks network fetches, workers, objects, forms, and external images while
  allowing the inline scripts/styles required by single-file export.
- The browser client inserts user-facing text with `textContent` or text nodes;
  HTML parser sinks such as `innerHTML` are reserved for fixed internal icons,
  not titles, labels, legends, categories, or tooltips.
- Hosts that need nonce/hash-only strict CSP should serve the JavaScript bundle
  as a separate asset and inject data through a nonce/hash-aware wrapper.
- Static PNG export validates width, height, scale, and timeout options before
  launching Chromium so bad user input produces actionable Python errors, and
  keeps Chromium's sandbox enabled by default. Pass `sandbox=False` only for
  trusted HTML in constrained CI/container environments that cannot launch a
  sandboxed browser.
- Export tests should include weird strings with `</script>`, HTML entities,
  mixed-case tags, and Unicode line/paragraph separators.

## Local Verification Shortcut

Use the focused gates below while iterating, then run the full gate before a
production-facing push:

| Changed surface | Focused gate |
|---|---|
| README/API prose, examples, public benchmark wording | `make check-docs` |
| README snippets, `docs/api-examples.md`, Reflex chart registry/assets | `make check-examples` |
| Public validation, error messages, builder rollback, LOD/drill mutation boundaries, chart/widget caching | `make check-errors` |
| Public exports, lazy import mappings, component factories, public annotations | `make check-api` |
| Import-time budget, `fastcharts.__init__`, dependency boundaries, widget/export/backend import boundaries | `make check-import` |
| Standalone HTML export, path writes, user text, tooltips, legends, browser DOM insertion | `make check-security` |
| Benchmark harness code, environment metadata, report schema, regressions | `make check-benchmark-harness` |
| Generated benchmark JSON artifacts | `make check-benchmark-report BENCHMARK_JSON=benchmark.json BENCHMARK_KIND=scatter-vs` |
| CI/release workflows, artifact upload/download, fallback install jobs | `make check-ci` |
| Source distributions and wheels | `make check-sdist` and `make check-wheel` |
| Existing release artifacts | `make check-artifacts SDIST=/path/to/fastcharts.tar.gz WHEEL=/path/to/fastcharts.whl` |
| Browser render/lifecycle/interaction smoke | `make check-browser CHROMIUM=/path/to/chrome` |
| Production-facing PR | `make check-full` |

Use this before pushing production-facing changes:

```bash
make check-full
```

Use this after editing README/API docs, example snippets, or public benchmark
wording:

```bash
make check-docs
```

The browser gate includes three app-facing checks. The Reflex lifecycle smoke
remounts every committed FastCharts iframe asset, the visual regression smoke
screenshots generated representative chart families plus every committed
FastCharts Reflex gallery asset except the Plotly comparison page, and the
interaction stress smoke enforces real `ChartView` gesture budgets. The
lifecycle smoke also requires every chart to report nonblank pixels
through `initial`, `hash-navigation`, `narrow-resize`, `wide-resize`,
`scroll-bottom`, `fast-scroll`, `visibility-change`, and `restore`, then names
the custom chrome, business overview, and retention cohort assets as critical
and requires each asset/phase pair to report pixels through every iframe shell
phase, including in-place reload and hidden boot/reveal.
The interaction stress smoke validates the real `ChartView` wheel zoom, pan,
hover, crosshair, box zoom, and brush-select paths with p95 budgets plus visual
invariants for blank frames, tick-label overlap, tooltip stability, crosshair
visibility, view changes, box zoom narrow/restore behavior, brush select
count/clear behavior, lit-pixel readback floors, and frame-to-frame color jumps.
The visual regression smoke also validates title, plot, x-axis, and y-axis
regions plus plot-region occupancy so a chart cannot collapse into a corner,
lose axis chrome, or pass merely because some pixels exist somewhere.

Use this after packaging, workflow, or source-distribution changes:

```bash
make check-sdist
make check-wheel
```

Use `make check-wheel WHEEL_EXPECT=--expect-native` when verifying a native
release wheel, or `WHEEL_EXPECT=--expect-pure` when intentionally checking the
fallback artifact.

Use this after editing CI/release workflows, benchmark artifact upload/download
wiring, trusted publishing, or fallback install jobs:

```bash
make check-ci
```

Use this when release automation has already produced artifacts and you need to
verify those exact files rather than rebuilding locally:

```bash
make check-artifacts SDIST=/path/to/fastcharts.tar.gz WHEEL=/path/to/fastcharts.whl
```

Use this after editing README snippets, `docs/api-examples.md`, or the Reflex
dashboard chart registry/assets:

```bash
make check-examples
```

Use this after touching standalone HTML export, path writes, inline JSON/script
escaping, tooltips, legends, category labels, or browser client DOM text
insertion:

```bash
make check-security
```

Use this after changing public validation, error messages, builder rollback
behavior, LOD/drill mutation boundaries, or chart/widget caching:

```bash
make check-errors
```

Use this after changing public exports, lazy import mappings, component
factories, or public type annotations:

```bash
make check-api
```

Use this after changing `fastcharts.__init__`, lazy import boundaries,
dependency boundaries, widget/export boundaries, or backend import setup:

```bash
make check-import
```

Use this before turning a generated benchmark JSON file into docs, release
notes, or a public claim:

```bash
make check-benchmark-report BENCHMARK_JSON=benchmark.json BENCHMARK_KIND=scatter-vs
```

Use this after changing benchmark harness code, report-schema validation,
environment metadata, regression comparison scripts, or benchmark methodology
tests:

```bash
make check-benchmark-harness
```

Use this after editing public docs, README text, package metadata, benchmark
summaries, release notes, or other performance-claim surfaces:

```bash
make check-claims
```

Browser smoke and package artifact verification need a built bundle, Chromium,
and wheel/sdist outputs. They are required in CI and release workflows even if
they are skipped locally.

For browser checks, pass the local Chromium/Chrome binary explicitly:

```bash
make check-browser CHROMIUM=/path/to/chrome
```

The browser gate includes the Reflex demo lifecycle smoke. It loads each
FastCharts iframe asset twice, requires every asset to survive the child-level
`initial`, `hash-navigation`, `narrow-resize`, `wide-resize`, `scroll-bottom`,
`fast-scroll`, `visibility-change`, and `restore` phases, then mounts all assets
in a parent iframe shell and exercises hash navigation, fast scrolling, resize,
visibility changes, full remount, in-place iframe reload, and a
hidden-boot/reveal pass where charts initialize in zero-sized iframe slots
before becoming visible.
Empty canvases, destroyed views, shortened lifecycle reports, missing shell-phase
reports, or missing per-phase critical custom chrome/business/cohort reports
fail the gate.

It also runs `scripts/interaction_stress_smoke.py`, which is a smaller gated
version of `benchmarks/bench_interaction.py`. The smoke validates interaction
budgets for direct scatter, density scatter, line, histogram, bar, and heatmap
rows so performance regressions are not scatter-only and not direct-scatter-only.
For pickable rows, tooltip stability means every declared repeated hover sample
must remain visible, so a tooltip that appears and immediately disappears fails
the gate.

Use `make list-checks` to see the individual check names, or
`python scripts/verify_local.py --dry-run --full` to print commands without
running them. The full local gate expects Node 18+ plus a Rust toolchain with
`cargo`, `rustc`, and clippy (`rustup component add clippy`). Missing Rust,
Node, Chrome, `ruff`, `ty`, or `pytest` produce direct install/skip guidance.

## Release Checklist

Before tagging a release:

- Refresh benchmark reports or explicitly document why the previous report still
  applies.
- Run `make check-full` locally or confirm the equivalent
  CI gates passed on the release commit.
- Run `make check-ci` to confirm CI and release workflow
  gates still include artifact verification, upload/download, and trusted PyPI
  publishing.
- Confirm CI built and verified native wheels for Linux x86-64/arm64, macOS
  arm64/x86-64, and Windows x86-64.
- Confirm the pure fallback/no-Rust install job passed.
- Confirm the sdist verifier passed and the source archive contains the expected
  `PKG-INFO` package name, Python floor, runtime dependencies, docs, tests,
  scripts, benchmark harnesses/baselines, Reflex example app, and no native
  binaries or generated caches.
- Confirm every wheel passes `scripts/verify_wheel.py --expect-native` and the
  install smoke loads `fastcharts.kernels.BACKEND == "native"`. Wheel
  `METADATA` must keep `Name: fastcharts`, `Requires-Python: >=3.11`,
  `anywidget>=0.9`, and `numpy>=1.24`; wheel `RECORD` must list every archive
  file exactly once with matching `sha256` and size fields. Wheels must stay
  package-only: docs, tests, benchmarks, scripts, and `reflex_fastcharts_app/`
  are sdist-only.
- Confirm the wheel size budget is still below 15 MB.
- Confirm README examples and `docs/api-examples.md` run against the tagged API.
- Confirm package metadata uses measured, scoped language rather than broad
  "faster/best" positioning.
- Confirm performance claims mention chart type, mode, backend, data size, and
  browser TTFR status.

## Claim Guardrails

Safe claims:

- fastcharts avoids JSON-number payloads for core chart data.
- Large scatter overview rendering is screen-bounded when using density mode.
- The native backend is substantially faster than pure Python/NumPy for kernel
  work covered by the benchmarks.
- Current 2D core chart benchmarks beat Plotly on the measured payload-prep,
  payload-size, and TTFR rows documented in `docs/benchmark.md`.

Claims that need qualification:

- "Renders 10M points" must say whether the chart is drawing exact markers or a
  density/adaptive representation.
- "Faster than Plotly" must name the chart type, data size, render target,
  backend, and whether browser TTFR is included.
- "Works without Rust" means source or pure fallback install works with NumPy;
  published wheels should still carry the native core.

Not yet safe:

- Plotly-level chart breadth.
- Full accessibility parity.
- Cross-browser/perceptual rendering conformance.
- Exact-marker interaction for every possible 100M-point zoom path.
- Production Reflex state integration as a first-class API.

## Hardening Backlog

Keep pushing these in low-conflict increments:

- Add mutation-safety tests for every public builder: a failed call must leave
  the `Figure` and column store unchanged.
- Keep weird-string export tests covering every text surface added to the
  public API, including titles, labels, legends, categories, and series names.
- Keep benchmark environment metadata and category IDs on every new generated report.
- Automate a PyPI/TestPyPI dry-run check for version bumps, tags, artifacts, and
  refreshed benchmark reports.
- Keep example app pages split between small business charts and large-data
  demos so ordinary usage does not get buried by the 100M stress cases.
- Add first-class docs for native vs fallback behavior, including how to tell
  which backend is active.
- Move advisory type checking to a hard gate once the checker and codebase agree
  on the dynamic `ctypes` and callback surfaces.
