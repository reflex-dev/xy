# Production Readiness

This is the release bar for xy while the core renderer is still moving.
It separates hard gates from advisory measurements so packaging promises and
API stability do not depend on memory or vibes.

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
  `.dist-info`, the render-client JavaScript bundles, `py.typed`, and, for native
  wheels, the Rust core. The JS bundles are a generated artifact (not committed to
  git): the build hook builds them into the wheel/sdist, so **end users do not need
  Rust, Node, npm, or a CDN.**
- Source distributions contain only install and build inputs: the `xy` package,
  bundled `reflex_xy` integration, Rust/JS sources, and the prebuilt render
  client. Repository-only docs, tests, benchmarks, scripts, and examples are
  excluded. Installing from an sdist therefore needs no Node.
- Building from a raw source checkout (`pip install` from a clone, or the dev
  workflow) requires a Rust toolchain for the native core and Node/npm for the
  render client — the same two toolchains CI uses. The two differ in strictness:
  the native core degrades gracefully (no Rust → pure-Python wheel, and importing
  the compute layer then raises a clear, actionable error naming the supported
  platforms — there is no NumPy fallback), whereas the render client is **required
  by default** — a from-source build that can neither find nor build the bundle
  fails loudly rather than producing a client-less distribution. `XY_SKIP_NODE=1`
  opts out for a deliberately client-less build (the widget and HTML export then
  raise a clear error on first use).
- Standalone HTML exports embed the same render client and data payloads used
  by notebooks.
- Benchmark reports must label rendering modes explicitly: `direct`,
  `decimated`, `density`, `sampled`, or `adaptive`.

The composition API, chart-type set, visual styling surface, and Reflex
integration are still experimental and may change before a 1.0 release.

## Accessibility and Cross-Browser Conformance Status

The current conformance tier covers a parallel semantic chart region and
generated trace/axis summary, a polite live region for hover and keyboard
readouts, focusable direct-point navigation with Arrow/Home/End keys, named
toolbar controls with toggle state, visible focus styling, reduced-motion
behavior, and forced-colors affordances.

The public documentation keeps code-copy controls visually icon-only while
providing stable accessible names and polite copied/failed announcements. Its
production-DOM check rejects both unnamed controls and shared-theme generated
text that would replace the copy/check icon feedback.

Live chart demos reuse the Reflex Build action from `reflex-site-shared`, and
the documentation navbar uses that package's keyword-only Algolia search. The
production route gate selects either the current flat-HTML/`404.html` layout or
the legacy directory-index/`__spa-fallback.html` layout once for the complete
build, so stale files from the other layout cannot mask missing routes.

CI runs the same focused chart in Playwright Chromium, Firefox, and WebKit. It
checks those semantics and interactions in every engine, compares WebGL output
with a coarse per-channel perceptual signature, and compares DOM chrome through
layout boxes rather than browser-font glyph pixels. The gate does **not** yet
cover aggregated-bin keyboard navigation, a view-as-table escape hatch,
screen-reader/OS combinations, every chart family, or full-page screenshot
parity. Run the focused tier locally with `make check-conformance` after
installing all three engines with
`npx playwright install chromium firefox webkit`.

## Release-Blocking Gates

These must pass before publishing.

| Area | Gate | Command or evidence |
|---|---|---|
| Python floor | `pyproject.toml`, Ruff, docs, syntax, and annotations stay on the Python 3.11+ floor | `python scripts/check_python_floor.py` |
| Public API | `__all__`, lazy exports, `__version__`, the source `py.typed` marker, focused type-surface tests, and fresh-process import-time budget stay coherent | `make check-api` |
| Import-time budget | `xy.__init__`, `dir(xy)`, export helpers, chart construction, and `.widget()` keep their lazy import boundaries | `make check-import` |
| CI/release workflows | Hard gates, non-blocking benchmarks, best-effort benchmark artifact upload/download, trusted publishing, and no-Rust clear-error jobs stay wired | `make check-ci` |
| GitHub Actions token scope | CI, release, and manual benchmark workflows declare an explicit least-privilege `GITHUB_TOKEN` default; privileged jobs use narrow job-level overrides | GitHub code scanning (`actions/missing-workflow-permissions`) |
| HTML export safety | Inline JSON/script escaping, atomic path writes, hostile user strings, and browser client text-node insertion stay protected | `make check-security` |
| Python tests | Native backend passes | `pytest -q` |
| Python style | Library, tests, scripts, and benchmarks lint clean | `ruff check .` and `ruff format --check .` |
| Matplotlib reference | The reviewed compatibility snapshot matches the pinned released matplotlib reference, and the `xy.pyplot` shim passes its interoperability and dual-engine corpus suites | `python scripts/sync_matplotlib_compat.py --check` and `pytest tests/pyplot` |
| Rust core | Native kernels pass and lint clean | `cargo test` and `cargo clippy --all-targets -- -D warnings` |
| Native ABI | C ABI can be loaded from the built core | `python scripts/abi_smoke.py` |
| JavaScript | Render client builds cleanly from source | `node js/build.mjs` |
| Browser render | WebGL smoke reaches real pixels | `python scripts/render_smoke_nonumpy.py <chromium>` |
| Accessibility / cross-browser | Semantic interaction checks plus tolerant WebGL/layout comparison pass in Chromium, Firefox, and WebKit | `make check-conformance` |
| Real chart render | A real composed chart exports and paints in Chromium | `python scripts/smoke_render.py <chromium>` |
| Step tier update | A decimated `step` chart keeps its risers after a synthetic kernel `tier_update` replaces the vertex buffers | `python scripts/step_tier_smoke.py <chromium>` |
| Dashboard reliability | Attempts 10/20/50/60 charts, hard-gates the 10-chart row as loss-free and nonblank, retains partial larger rows, and applies the production shader-cache oracle to a complete, fully nonblank, loss-free 60-chart row | `python benchmarks/bench_dashboard.py --chart-counts 10,20,50,60 --chromium <chromium> --json dashboard-smoke.json` then `python scripts/verify_benchmark_report.py dashboard-smoke.json --kind dashboard-browser` |
| sdist | Build-input-only source archive contains the `xy` and bundled `reflex_xy` packages, JSX/render-client bundles, complete JS/Rust build sources, and `PKG-INFO` version/dependencies (including `Provides-Extra: reflex` and `reflex>=0.9.6` under that marker) matching the archive's own `xy-<version>` root; repository-only material, duplicate/unsafe members, native binaries, and generated junk are absent | `python scripts/verify_sdist.py dist/*.tar.gz` |
| Native wheel | Platform wheel contains package-only `xy` and `reflex_xy` files, exactly one native library, the JSX wrapper but no duplicate render client, `METADATA` version/base dependencies/`reflex` extra matching the wheel's own filename and `.dist-info`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, and is tagged non-pure | `python scripts/verify_wheel.py dist/*.whl --expect-native` |
| Fallback wheel | No-toolchain wheel contains package-only `xy` and `reflex_xy` files, `METADATA` version/base dependencies/`reflex` extra matching the wheel's own filename and `.dist-info`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, is pure, and contains no native library | `python scripts/verify_wheel.py dist/*.whl --expect-pure` |
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
| API prose, examples, public benchmark wording | `make check-docs` |
| `spec/api/api-examples.md`, Reflex chart registry/assets | `make check-examples` |
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

Use this after editing API docs, example snippets, or public benchmark wording:

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

Use this after editing `spec/api/api-examples.md` or the Reflex dashboard chart
registry/assets:

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

Use this to validate generated benchmark JSON before publication or downstream
analysis:

```bash
make check-benchmark-report BENCHMARK_JSON=benchmark.json BENCHMARK_KIND=scatter-vs
```

Use this after changing benchmark harness code, report-schema validation,
environment metadata, regression comparison scripts, or benchmark methodology
tests:

```bash
make check-benchmark-harness
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

The tag *is* the version. `pyproject.toml` declares `dynamic = ["version"]` and
uv-dynamic-versioning derives the distribution version from the latest `v*` git
tag, so cutting a release is `git tag vX.Y.Z && git push --tags` — there is no
number to bump in a file, and no file that can drift from the tag. Two
consequences worth knowing:

- Builds between tags are versioned `<next>.devN+<commit>`, which PyPI rejects
  by design: only a tag can produce an uploadable version.
- Every checkout that builds must be unshallow (`fetch-depth: 0`). A depth-1
  clone fetches no tags and would *silently* build at the `0.0.0` fallback;
  `make check-ci` enforces this.

Pre-releases are tagged the same way with a canonical PEP 440 suffix —
`vX.Y.ZaN` / `bN` / `rcN` (e.g. `v1.0.0rc1`) — and publish through the same
pipeline; pip ignores them unless a pre-release is requested explicitly. Only
the canonical spelling passes the release gate: `-alpha1`-style tags would be
normalized by the version derivation and could never match their own built
artifacts. A pre-release needs its own dated changelog entry, exactly like a
final release.

The repository has one release line: the `xy` distribution, including its
bundled `reflex_xy` integration, ships from `vX.Y.Z` tags through
`release.yml`. The `xy[reflex]` extra is dependency metadata in those same
artifacts, not another package or release.

Before tagging a release:

- Tag as `vX.Y.Z`, optionally with a canonical PEP 440 pre-release suffix
  (`v0.2.0a1`/`b1`/`rc1`). That shape is the whole release gate
  (`scripts/check_release_version.py`), because it is the shape
  uv-dynamic-versioning derives the published version from; `.postN`, `.devN`,
  local (`+…`), and non-canonical (`-alpha1`) spellings are refused before
  anything builds.
- Add a dated `## [X.Y.Z] — YYYY-MM-DD` heading to `CHANGELOG.md` for the
  version being tagged. Deliberately not gated: a missing or undated entry is
  fixed with a follow-up commit, and blocking the publish on it only ever forced
  a tag to be deleted and re-cut over a documentation edit.
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
  `panic=abort`, Emscripten 5.0.3, cibuildwheel 4.1.0, the PEP 783
  `pyemscripten_2026_0` wheel ABI, and Pyodide 314.0.0. The abort strategy keeps
  Rust panics from unwinding across the Python/`ctypes` C ABI boundary.
  `scripts/pyodide_load_smoke.py` installs the exact built artifact with
  micropip, loads the C ABI through `ctypes`, verifies `xy_abi_version`, and
  calls the native `min_max` kernel. PEP 783 platform tags are accepted by
  PyPI, so the runtime-verified wheel joins the same trusted-publishing batch
  as the native wheels and sdist; Pyodide 314 users can install it with
  `await micropip.install("xy")`. The wasm job is release-blocking so an ABI or
  toolchain drift cannot silently ship a build-only, unloadable artifact.
- Confirm the no-Rust install job passed (it must build, install, and then
  raise a clear ImportError on first compute — never a silent fallback).
- Confirm the sdist verifier passed and the build-input-only source archive
  contains `xy`, bundled `reflex_xy`, the JSX/render-client bundles, complete
  JS/Rust build sources, and the expected `PKG-INFO` package name, Python floor,
  runtime dependencies, and Reflex extra. It must exclude repository-only
  docs, tests, scripts, benchmarks, examples, native binaries, and generated
  caches.
- Confirm each platform wheel passes `scripts/verify_wheel.py --expect-native`
  and its install smoke loads `xy.kernels.BACKEND == "native"`. Confirm the
  fallback `py3-none-any` wheel passes `--expect-pure` and fails compute with
  the documented native-core error. Wheel
  `METADATA` must keep `Name: xy`, `Requires-Python: >=3.11`,
  `anywidget>=0.9`, and `numpy>=1.24` as base requirements, plus
  `Provides-Extra: reflex` and `reflex>=0.9.6` guarded by that extra. The wheel
  must contain `reflex_xy` and `XYChart.jsx`, and `RECORD` must list every
  archive file exactly once with matching `sha256` and size fields. Wheels
  and the sdist remain distribution/build-input-only: docs, tests, benchmarks,
  scripts, and the `examples/` apps are repository-only.
- Confirm the wheel size budget is still below 15 MB.
- Confirm `spec/api/api-examples.md` runs against the tagged API.
### Bundled Reflex integration

Every `xy` release carries the `reflex_xy` Python package and JSX wrapper. The
wrapper links to the render client in the same installed distribution, so
client, kernel, and framework bridge share one version. Plain `xy` must not
install Reflex; `xy[reflex]` must install the declared supported floor.
Release smoke tests install Reflex, import `reflex_xy`, and assert that its
reported version matches the `xy` distribution version.

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
- Keep the two example apps focused: `examples/reflex` on the bundled Reflex
  integration surfaces (figure vars, events, state-driven and streaming
  updates, `on_view_change`), and `examples/fastapi` on the framework-neutral
  gallery plus the live 100M drilldown. The one deliberate overlap is that
  drilldown chart itself: `examples/reflex` §6 serves the identical dataset
  adapter-natively (an `inline()` token, no transport code) so cross-host
  behavior can be A/B'd against fastapi's hand-rolled transport; both honor
  `XY_LIVE_POINTS`. Neither commits static chart HTML, and both surface their
  own source via `inspect.getsource`.
- Add first-class docs for the supported-platform matrix and the clear-error
  behavior when the native core is unavailable.
- Move advisory type checking to a hard gate once the checker and codebase agree
  on the dynamic `ctypes` and callback surfaces.
