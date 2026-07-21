# Production Readiness

This is the release bar for xy while the core renderer is still moving.
It separates hard gates from advisory measurements so performance claims,
packaging promises, and API stability do not depend on memory or vibes.

## Current Contract

xy is early alpha. The goal is Plotly-class chart breadth with a
screen-bounded performance core, but the stable commitments today are narrower:

- Python 3.11+ only.
- `import xy` stays lightweight and does not import NumPy or load the
  native core. The public API
  gate verifies this in fresh interpreters and keeps package import under a
  200 ms budget. Chart-building APIs are the compute import boundary; notebook
  widget dependencies stay deferred until `.widget()`/display, and standalone
  HTML export reads its static bundle without importing the widget stack.
- Published wheels include only the shippable `xy/` package,
  `.dist-info`, static JavaScript bundles, `py.typed`, and, for native wheels,
  the Rust core. End users do not need Rust, Node, npm, or a CDN.
- Source distributions include the release support surface: docs, tests,
  benchmark harnesses/baselines, scripts, Rust/JS source, and the example apps'
  source (FastAPI and Reflex). Charts are generated live by the apps, so no
  static chart HTML is committed or packaged.
- Source installs require a Rust toolchain to build the native core. There is no
  NumPy fallback: on a platform with no wheel and no local Rust build, importing
  the compute layer raises a clear, actionable error naming the supported
  platforms.
- Standalone HTML exports embed the same render client and data payloads used
  by notebooks.
- Benchmark reports must label rendering modes explicitly: `direct`,
  `decimated`, `density`, `sampled`, or `adaptive`.

The composition API, chart-type set, visual styling surface, and Reflex
integration are still experimental and may change before a 1.0 release.

## Accessibility and Cross-Browser Conformance Status

The current conformance tier is intentionally narrower than a claim of full
WCAG parity or pixel-identical output across browsers. The browser client now
ships a parallel semantic chart region and generated trace/axis summary, a
polite live region for hover and keyboard readouts, focusable direct-point
navigation with Arrow/Home/End keys, named toolbar controls with toggle state,
visible focus styling, reduced-motion behavior, and forced-colors affordances.

CI runs the same focused chart in Playwright Chromium, Firefox, and WebKit. It
checks those semantics and interactions in every engine, compares WebGL output
with a coarse per-channel perceptual signature, and compares DOM chrome through
layout boxes rather than browser-font glyph pixels. The gate does **not** yet
cover aggregated-bin keyboard navigation, a view-as-table escape hatch,
screen-reader/OS combinations, every chart family, or full-page screenshot
parity. Until those surfaces have dedicated evidence, neither full
accessibility parity nor broad perceptual cross-browser consistency is a safe
public claim. Run the focused tier locally with `make check-conformance` after
installing all three engines with
`npx playwright install chromium firefox webkit`.

## Release-Blocking Gates

These must pass before publishing or making a broad performance claim.

| Area | Gate | Command or evidence |
|---|---|---|
| Python floor | `pyproject.toml`, Ruff, docs, syntax, and annotations stay on the Python 3.11+ floor | `python scripts/check_python_floor.py` |
| Public API | `__all__`, lazy exports, `__version__`, the source `py.typed` marker, focused type-surface tests, and fresh-process import-time budget stay coherent | `make check-api` |
| Import-time budget | `xy.__init__`, `dir(xy)`, export helpers, chart construction, and `.widget()` keep their lazy import boundaries | `make check-import` |
| Claim guardrails | Public docs and package metadata avoid broad, unqualified performance claims | `make check-claims` |
| CI/release workflows | Hard gates, non-blocking benchmarks, best-effort benchmark artifact upload/download, trusted publishing, and no-Rust clear-error jobs stay wired | `make check-ci` |
| HTML export safety | Inline JSON/script escaping, atomic path writes, hostile user strings, and browser client text-node insertion stay protected | `make check-security` |
| Python tests | Native backend passes | `pytest -q` |
| Python style | Library, tests, scripts, and benchmarks lint clean | `ruff check .` and `ruff format --check .` |
| Matplotlib reference | The reviewed compatibility snapshot matches the pinned released matplotlib reference, and the `xy.pyplot` shim passes its interoperability and dual-engine corpus suites | `python scripts/sync_matplotlib_compat.py --check` and `pytest tests/pyplot` |
| Rust core | Native kernels pass and lint clean | `cargo test` and `cargo clippy --all-targets -- -D warnings` |
| Native ABI | C ABI can be loaded from the built core | `python scripts/abi_smoke.py` |
| JavaScript | Committed bundles match source | `node js/build.mjs --check` |
| Browser render | WebGL smoke reaches real pixels | `python scripts/render_smoke_nonumpy.py <chromium>` |
| Accessibility / cross-browser | Semantic interaction checks plus tolerant WebGL/layout comparison pass in Chromium, Firefox, and WebKit | `make check-conformance` |
| Real chart render | A real composed chart exports and paints in Chromium | `python scripts/smoke_render.py <chromium>` |
| Step tier update | A decimated `step` chart keeps its risers after a synthetic kernel `tier_update` replaces the vertex buffers | `python scripts/step_tier_smoke.py <chromium>` |
| Dashboard reliability | 10/20/50-chart dashboards stay nonblank under the render client's context governor | `python benchmarks/bench_dashboard.py --chart-counts 10,20,50 --chromium <chromium> --json dashboard-smoke.json` then `python scripts/verify_benchmark_report.py dashboard-smoke.json --kind dashboard-browser` |
| sdist | Source archive contains required source/bundles, benchmark regression harness/baseline, release docs/tests/scripts, the example apps' source, `PKG-INFO` version/dependencies matching `pyproject.toml`, no duplicate members, and no generated junk | `python scripts/verify_sdist.py dist/*.tar.gz` |
| Native wheel | Platform wheel contains package-only files, exactly one native library, `METADATA` version/dependencies matching `pyproject.toml`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, and is tagged non-pure | `python scripts/verify_wheel.py dist/*.whl --expect-native` |
| Fallback wheel | No-toolchain wheel contains package-only files, `METADATA` version/dependencies matching `pyproject.toml`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, is pure, and contains no native library | `python scripts/verify_wheel.py dist/*.whl --expect-pure` |
| Wheel size | Platform wheel remains small enough for notebook installs | CI budget: 15 MB |
| Benchmark artifact | JSON benchmark reports carry schema, environment, categories, row status, and finite non-negative metrics; native reports must declare the native backend | `python scripts/verify_benchmark_report.py benchmark.json --kind scatter-vs`; repeat for line, install, core-2D, pyplot-vs-matplotlib, native, interaction, dashboard, and workflow artifacts |

Type checking is **advisory, not release-blocking**. CI runs `ty check python`
and reports findings without failing the build, and `scripts/verify_local.py`
registers the same check with `advisory=True`, so `make check-full` prints
warnings for type findings rather than failing. Promoting it to a hard gate is
tracked in the Hardening Backlog. The full-package `py.typed` marker is a hard
gate, but it is enforced by `make check-api`
(`scripts/check_public_api.py`), not by the type checker.

## Standalone HTML Safety

`Chart.to_html()` produces one self-contained document: inline JavaScript,
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
  blocks network fetches, external worker scripts, objects, forms, and external
  images, and pins `base-uri 'none'`, while allowing the inline scripts/styles
  required by single-file export. Workers are restricted to `blob:` URLs so the
  bundled density re-bin worker can boot from its own inlined source; no
  external worker script can load.
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
| README snippets, `spec/api/api-examples.md`, Reflex chart registry/assets | `make check-examples` |
| Public validation, error messages, builder rollback, LOD/drill mutation boundaries, chart/widget caching | `make check-errors` |
| Public exports, lazy import mappings, component factories, public annotations | `make check-api` |
| Import-time budget, `xy.__init__`, dependency boundaries, widget/export/backend import boundaries | `make check-import` |
| `xy.pyplot` shim behavior, matplotlib interoperability, reference corpus | `make check-pyplot` |
| Reviewed matplotlib compatibility snapshot (`spec/matplotlib/compat-matrix.md`) | `python scripts/sync_matplotlib_compat.py --check` |
| `xy.pyplot` speed margin against matplotlib | `make check-pyplot-speed` |
| Standalone HTML export, path writes, user text, tooltips, legends, browser DOM insertion | `make check-security` |
| Benchmark harness code, environment metadata, report schema, regressions | `make check-benchmark-harness` |
| Generated benchmark JSON artifacts | `make check-benchmark-report BENCHMARK_JSON=benchmark.json BENCHMARK_KIND=scatter-vs` |
| CI/release workflows, artifact upload/download, no-Rust clear-error jobs | `make check-ci` |
| Source distributions and wheels | `make check-sdist` and `make check-wheel` |
| Existing release artifacts | `make check-artifacts SDIST=/path/to/xy.tar.gz WHEEL=/path/to/xy.whl` |
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

The browser gates are split into app-facing checks that match the CI step
names: `Browser lifecycle smoke (Chromium)`, `Browser visual regression smoke
(Chromium)`, `Step tier-update smoke (Chromium)`, `Browser interaction stress
smoke (Chromium)`, and `Browser dashboard reliability smoke (Chromium)`.
`make check-browser` runs all of these except the dashboard reliability smoke,
which runs in CI only. The lifecycle and visual smokes both boot the
`examples/fastapi` app under uvicorn and drive Chromium at its live routes (no
committed HTML): the lifecycle smoke loads every gallery chart and the live
drilldown and requires each to report nonblank pixels through `initial`,
`narrow-resize`, `wide-resize`, `visibility-change`, `context-restore`, and
`restore` (and to keep its runtime DOM slots), then confirms the index page's
embedded iframes paint; the visual regression smoke screenshots every gallery
route and checks nonblank/colored/occupancy plus tick-label overlap. The
`context-restore` phase forces `WEBGL_lose_context` loss/restoration and
requires the rebuilt chart to remain nonblank. The interaction stress smoke
validates the real `ChartView` wheel zoom, pan, hover, crosshair, box zoom, and
brush-select paths with p95 budgets plus visual invariants for blank frames,
tick-label overlap, tooltip stability, crosshair visibility, view changes, box
zoom narrow/restore behavior, brush select count/clear behavior, lit-pixel
readback floors, and frame-to-frame color jumps. The visual regression smoke
also validates title, plot, x-axis, and y-axis regions plus plot-region
occupancy, and it screenshots static Reflex-style chrome shells for the custom
legend/tooltip and annotated heatmap examples. A chart cannot collapse into a
corner, lose axis/custom chrome, or pass merely because some pixels exist
somewhere.

Use this after packaging, workflow, or source-distribution changes:

```bash
make check-sdist
make check-wheel
```

Use `make check-wheel WHEEL_EXPECT=--expect-native` when verifying a native
release wheel, or `WHEEL_EXPECT=--expect-pure` when intentionally checking the
no-native artifact (it imports but errors clearly the moment compute is needed).

Use this after editing CI/release workflows, benchmark artifact upload/download
wiring, trusted publishing, or the no-Rust clear-error install jobs:

```bash
make check-ci
```

Use this when release automation has already produced artifacts and you need to
verify those exact files rather than rebuilding locally:

```bash
make check-artifacts SDIST=/path/to/xy.tar.gz WHEEL=/path/to/xy.whl
```

Use this after editing README snippets, `spec/api/api-examples.md`, or the Reflex
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

Use this after changing `xy.__init__`, lazy import boundaries,
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
and wheel/sdist outputs. The interaction gate's real-wall-clock worker probe
also uses the pinned development-only Playwright driver; install it once with
`make setup-browser` (or `npm install`). These gates are required in CI and
release workflows even if they are skipped locally.

For browser checks, pass the local Chromium/Chrome binary explicitly:

```bash
make check-browser CHROMIUM=/path/to/chrome
```

The lifecycle gate runs `scripts/reflex_lifecycle_smoke.py`. It boots the
`examples/fastapi` app under uvicorn and, for every gallery chart route plus
`/drilldown`, injects a probe over CDP (before the chart client loads) and
requires the view to survive the `initial`, `narrow-resize`, `wide-resize`,
`visibility-change`, `context-restore`, and `restore` phases with nonblank
pixels and its runtime DOM slots intact. The `context-restore` phase forces
`WEBGL_lose_context` loss/restoration and requires the rebuilt chart to remain
nonblank. A final pass loads the index page and confirms its embedded iframes
paint. Empty canvases, destroyed views, shortened lifecycle reports, failed
context restores, or missing DOM slots fail the gate.

The visual gate runs `scripts/visual_regression_smoke.py`. It boots the same
app and screenshots every gallery chart route plus `/drilldown`, checking
nonblank, colored, unique-color, plot-occupancy, and tick-label-overlap
invariants so a blank, flat, or collapsed chart fails the gate.

The interaction gate runs `scripts/interaction_stress_smoke.py`, which is a
smaller gated version of `benchmarks/bench_interaction.py`. The smoke validates
interaction budgets for direct scatter, density scatter, line, histogram, bar,
and heatmap rows so performance regressions are not scatter-only and not
direct-scatter-only. For pickable rows, tooltip stability means every declared
repeated hover sample must remain visible, so a tooltip that appears and
immediately disappears fails the gate.

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
- Before the first release after a change to the wheel matrix (new target,
  cross-compile toolchain, or tagging scheme), manually run the release
  workflow (`workflow_dispatch`, `dry_run` defaults to `true`) and confirm
  every leg of the cross-compile matrix — including the newer aarch64/armv7/
  musllinux/win-arm64 targets and the wasm job — actually builds, since a
  target added to the matrix but never exercised in CI is unverified, not
  working.
- Confirm CI built and verified native wheels for Linux glibc and musl/Alpine
  (x86-64, aarch64, armv7), macOS (x86-64, Apple Silicon), and Windows (x86, x64,
  arm64).
- Confirm the Pyodide/Emscripten wheel passes its runtime load gate, not only
  its structural wheel check. The tested toolchain is Rust 1.97.0 with
  `panic=abort`, Emscripten 4.0.9, the `pyodide_2025_0` wheel ABI, and Pyodide
  0.29.4. The abort strategy is required: the previous unwind build imported a
  `__cpp_exception` WebAssembly tag that Pyodide's main module did not provide.
  `scripts/pyodide_load_smoke.py` installs the built artifact with micropip,
  loads the C ABI through `ctypes`, verifies `xy_abi_version`, and calls the
  native `min_max` kernel. PyPI does not accept Pyodide platform tags, so the
  release workflow publishes this wheel as a GitHub Release asset and repeats
  the same runtime smoke against its public HTTPS URL. The wasm job is
  release-blocking so an ABI or toolchain drift cannot silently ship a
  build-only, unloadable artifact.
- Confirm the no-Rust install job passed (it must build, install, and then
  raise a clear ImportError on first compute — never a silent fallback).
- Confirm the sdist verifier passed and the source archive contains the expected
  `PKG-INFO` package name, Python floor, runtime dependencies, docs, tests,
  scripts, benchmark harnesses/baselines, the example apps' source, and no
  native binaries or generated caches.
- Confirm every wheel passes `scripts/verify_wheel.py --expect-native` and the
  install smoke loads `xy.kernels.BACKEND == "native"`. Wheel
  `METADATA` must keep `Name: xy`, `Requires-Python: >=3.11`,
  `anywidget>=0.9`, and `numpy>=1.24`; wheel `RECORD` must list every archive
  file exactly once with matching `sha256` and size fields. Wheels must stay
  package-only: docs, tests, benchmarks, scripts, and the `examples/` apps
  are sdist-only.
- Confirm the wheel size budget is still below 15 MB.
- Confirm README examples and `spec/api/api-examples.md` run against the tagged API.
- Confirm package metadata uses measured, scoped language rather than broad
  "faster/best" positioning.
- Confirm performance claims mention chart type, mode, backend, data size, and
  browser TTFR status.

## Claim Guardrails

Safe claims:

- xy avoids JSON-number payloads for core chart data.
- Large scatter overview rendering is screen-bounded when using density mode.
- The native backend is substantially faster than pure Python/NumPy for kernel
  work covered by the benchmarks.
- Current 2D core chart benchmarks beat Plotly on the measured payload-prep,
  payload-size, and TTFR rows documented in `spec/benchmarks/results.md`.

Claims that need qualification:

- "Renders 10M points" must say whether the chart is drawing exact markers or a
  density/adaptive representation.
- "Faster than Plotly" must name the chart type, data size, render target,
  backend, and whether browser TTFR is included.
- "Install without Rust" means a published wheel (which carries the native core)
  installs with no toolchain; a source build still requires Rust, and a
  platform with no native core raises a clear ImportError rather than degrading.

Not yet safe:

- Plotly-level chart breadth.
- Full accessibility parity.
- Cross-browser/perceptual rendering conformance.
- Exact-marker interaction for every possible 100M-point zoom path.
- Production Reflex state integration as a first-class API.
- More than ~12 charts *simultaneously in view* holding live WebGL contexts.
  Browsers cap live contexts per page (~16 in Chrome); the render client's
  context governor keeps xy inside a budget (default 12) by having
  the least-recently-visible off-screen chart release its context and
  re-acquire on scroll-into-view. Measured (`benchmarks/bench_dashboard.py`,
  2026-07-09, Chrome/macOS): 10/20/50-chart dashboards are all fully usable —
  every chart nonblank when visited, recovery p95 ~8 ms, heap sublinear
  (28 MB at 50 charts) — but a layout keeping more than the budget visible
  at once can still hit browser-side eviction, so do not claim unbounded
  simultaneous live charts.

The complete parity backlog and the rule that partial, shim-only, deferred, or
prototype work remains **NOT IMPLEMENTED** are normative in
[`spec/api/capability-gap-contract.md`](../api/capability-gap-contract.md).
Claims must not outrun the rows marked **Implemented** there.

## Hardening Backlog

Keep pushing these in low-conflict increments:

- Add mutation-safety tests for every public builder: a failed call must leave
  the chart's internal figure and column store unchanged.
- Keep weird-string export tests covering every text surface added to the
  public API, including titles, labels, legends, categories, and series names.
- Styling arguments (colors, gradient stops, `style=` declarations) are gated
  by the native CSS grammar (`src/css.rs`; `tests/test_css_validation.py`) —
  route any new mark/chrome styling prop through `_validate.css_color` or
  `style_mapping` so no styling surface bypasses it.
- Keep benchmark environment metadata and category IDs on every new generated report.
- The release workflow's `workflow_dispatch` `dry_run` input (default `true`)
  now builds and verifies every wheel/sdist/wasm artifact without publishing;
  remaining follow-up is wiring an actual TestPyPI upload into that dry-run
  path (today it only stops short of a real publish, it doesn't yet push to a
  test index), plus tying it to version-bump/tag validation and refreshed
  benchmark reports.
- Keep the two example apps focused: `examples/reflex` on the reflex-xy
  integration surfaces (figure vars, events, state-driven and streaming
  updates, `on_view_change`), and `examples/fastapi` on the framework-neutral
  gallery plus the live 100M drilldown. Neither commits static chart HTML, and
  both surface their own source via `inspect.getsource`.
- Add first-class docs for the supported-platform matrix and the clear-error
  behavior when the native core is unavailable.
- Move advisory type checking to a hard gate once the checker and codebase agree
  on the dynamic `ctypes` and callback surfaces.
