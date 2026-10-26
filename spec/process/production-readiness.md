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
  client. Repository-only docs, tests, gallery evidence, benchmarks, scripts,
  and examples are excluded. Installing from an sdist therefore needs no Node.
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

## Pull-request CI selection and build reuse

`ci.yml` always runs a lightweight selector and the stable `CI result` summary.
The selector uses the complete local Git three-dot PR diff, with rename detection
disabled so a move out of a source directory still checks the removed source.
It does not rely on GitHub's path-filter file limit. Selection failures fail CI;
unknown paths conservatively select the general lanes, excluding pyplot. Pushes
and manual dispatches run all lanes, including documentation-only pushes to main.

| PR changes | Selected main CI lanes |
| --- | --- |
| Only `docs/`, `spec/`, `news/`, README, changelog, contributor instructions or license | Selector and summary; the separate Docs workflow handles its matching paths |
| `python/xy/pyplot/`, `python/xy/backends/`, their tests, gallery inputs or compatibility scripts | Runtime/Python floor, released Matplotlib reference/patch, eight standard gallery shards, extended gallery |
| Other `tests/` or `examples/`, or `.binder/` | Runtime/Python floor; Binder separately selects its own build inputs |
| `benchmarks/` or `scripts/bench*` | Blocking runtime/Python-floor regression checks plus advisory cross-library/methodology benchmarks and their report merge |
| `.github/workflows/`, `.github/actions/`, CI selector/verifier scripts | Runtime/Python floor, packaging and conformance; advisory benchmarks are skipped |
| Shared Python, Rust, JS, dependency/build configuration, or unfamiliar paths | General lanes; pyplot requires a matching compatibility path |

CI and CodSpeed bootstrapping use explicit tool versions, not moving channels:

| Bootstrap input | Pinned value |
| --- | --- |
| Rust toolchain | `1.99.1` (`clippy` explicitly installed for the Rust check lane) |
| Node.js | `22.23.3` |
| uv | `0.13.5` |
| Python floor / CodSpeed interpreter | `3.11.17` |
| Linux wheel repair utility | `auditwheel==6.8.2`, including the execution command |

These versions match the passing CI runs used to review this change. Every
checkout in `ci.yml` and `codspeed.yml` explicitly sets
`persist-credentials: false`; full history remains available for local version
and gallery-baseline queries without retaining Git authentication for later
build/test code. Action code remains SHA-pinned. CodSpeed points directly to
commit `f99becdce5e5d51fd556489ebef684f4ecfd6286`, the verified target of its
previous signed tag object `4bee4eada46987d4607fc208971a36367352b83d`, so this
normalization preserves the action code and its bundled runner version.
For bootstrap actions present in the workflow, the verifier structurally requires
credential isolation, full-SHA references and reviewed action inputs, rejecting
missing, duplicated, ambiguous or comment-only input values. This check validates
existing action steps; it does not require every job to declare a setup action
for every tool it uses. The auditwheel installation and execution pins
are enforced by
`tests/test_ci_scope.py::test_wheel_repair_installs_and_executes_the_pinned_auditwheel`.
Updating the toolchain requires updating the workflow inputs, verifier contract, tests
and this table together, then exercising the hosted gates. These controls cover
CI/CodSpeed bootstrapping; hosted OS images and dependency-range installation
smokes retain their existing update/support-range contracts.

The runtime selection runs four independent blocking jobs:

| Job | Dependencies | Checks |
| --- | --- | --- |
| `rust_checks` — Rust tests + Clippy | Selector only | Rust unit tests and Clippy; starts alongside the shared-wheel build |
| `test` — Python tests + quality | Selector and shared wheel | Locked Reflex dev environment, API, Ruff, types and full selected pytest coverage with required Chromium |
| `browser_smokes` — Browser rendering + integration | Selector and shared wheel | JS parsing, native ABI, stdlib render/append/export probes, real-chart rendering, lifecycle, visuals, stress and dashboard reliability; focused pyplot gate when selected |
| `regression_checks` — Blocking regression checks | Selector and shared wheel | Native/scatter/transport regression reports, deterministic payload gates, report upload and the benchmark smoke harness |

Runtime job and step mappings reject `continue-on-error` structurally, including
quoted and escaped key spellings.
Step conditions are structurally forbidden except the exact pyplot-selection
condition on its focused gate and `always()` on regression-report upload.
These jobs never depend on one another. Python, browser and regression jobs each
restore the same native/client artifacts and run in parallel once the wheel is
ready. Python tests retain their real-browser coverage rather than deferring it
to another job. The shared `setup-ci-chromium` composite restores a browser cache
keyed by OS/architecture/frontend lockfile, installs full Chromium without apt
on the fixed Ubuntu image, and verifies that it launches. Each caller bounds
this setup to five minutes. The `CI result` summary requires all four jobs and
rejects failures/cancellations from each, alongside the existing Python-floor,
conformance and packaging gates. Validation covers their independent dependency
graph, unchanged mandatory checks and failure propagation. Hosted start/end
metadata (`gh run view <run> --json jobs`) supplies evidence of actual overlap;
no elapsed-time improvement is claimed before a fresh hosted run.

Mixed PRs take the union. On pull requests, the reference/patch jobs, both gallery
profiles and the focused pyplot test step require an explicit change under the
compatibility paths above. CI workflow/helper changes, shared implementation
changes, and unknown paths do not enable them by themselves. A mixed PR that
also edits compatibility still runs those gates regardless of file order.
Runtime and floor tests omit `tests/pyplot` and
`tests/backends` when compatibility is unselected; the explicit Chromium pyplot
step follows the same compatibility output. Benchmarks remain advisory; selected
correctness, gallery, browser and packaging lanes remain blocking. `CI result`
rejects failed/cancelled hard dependencies and accepts intentionally skipped
lanes, so it also completes on docs-only PRs. Repositories can require this
stable status instead of individually selected jobs. The verifier protects every
blocking summary dependency, the shared-build selection condition, and its exact
failure/selection assertions, including packaging failures. The summary step must
define one direct `env.RESULTS` assignment equal to `${{ toJSON(needs) }}`;
comments, inherited values and duplicate mappings cannot satisfy that contract.
The Python-floor environment explicitly installs PyYAML for the workflow tests. Workflow changes do not
change repository branch-protection settings automatically.

One `ubuntu-24.04` producer builds and verifies a native Linux x64 wheel at the
implementation SHA. Compatible consumers check out that same SHA and download
only this run's artifact. The gallery, reference, Python-floor and benchmark
consumers that exercise XY install that wheel. Competitor-only benchmark shards
(`matrix.xy: false`) skip both restoration and XY installation. A local composite action also extracts its native
library and JS bundles into source paths for repository tests and stdlib smokes.
The three locked runtime development environments retain editable installs with
`XY_SKIP_CARGO=1`, reusing the verified native library; no consuming lane recompiles
the release core or rebundles JS. Rust unit tests and Clippy still compile their
test/debug targets. The Linux x64 packaging smoke repairs and installs the same
wheel without waiting for the whole runtime suite. ARM64 and Windows builds,
sdist source-build probes, and the deliberately coreless build remain independent.
CodSpeed and Docs retain independent environments/builds across workflows;
CodSpeed PR filters omit backend/gallery-only changes, CI workflows/actions and
selector/verifier scripts, tests, Markdown at any depth, license-only changes,
docs and news. CI-only PRs do not download CodSpeed tooling or run its benchmarks.
Pyplot implementation changes still run its dedicated CodSpeed benchmarks.
Published release build workflows and their full platform coverage are unchanged.

The three-engine conformance job uses the official Playwright image
`mcr.microsoft.com/playwright:v1.61.1-noble@sha256:5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48`.
The image supplies browsers and their OS libraries in one prebuilt, digest-pinned
bundle. Its version must match the exact Playwright devDependency in
`package.json` and `package-lock.json`; update the image digest and verifier
contract together when upgrading Playwright. The job verifies the binary paths
and runs the same Chromium/Firefox/WebKit WebGL and accessibility checks under
Xvfb, with a fifteen-minute total timeout and a five-minute conformance-step timeout.
The job budget covers the five-minute npm setup, one-minute preflight and
five-minute conformance limits, plus four minutes for checkout and other setup.
The verifier checks the preflight's exact active `run` body, so comments or an
empty engine loop cannot satisfy the executable-path checks.
The browser step sets `HOME=/root` to match the container's root user; Firefox
rejects GitHub's mounted `/github/home` because it belongs to a different UID.
It performs no apt or browser-engine installation. Its image pull is still a
network operation; the workflow does not assume hosted runners retain Docker
layers between runs. Other Chromium-only jobs keep their existing lockfile-keyed
browser caches. Reproduce the image metadata/digest through
`https://mcr.microsoft.com/v2/playwright/manifests/v1.61.1-noble` with a Docker
manifest-list Accept header, and verify the manifest body's SHA-256 before
updating the pin. [Playwright documents the preinstalled browser/dependency
contract](https://playwright.dev/docs/docker).

The advisory methodology job keeps the standard workload sizes and repetition
counts. CI-only PRs skip it and the cross-library benchmark/report jobs; mixed
PRs that edit benchmark or shared implementation inputs still select them.
Main pushes and manual dispatches retain all benchmark coverage.
On the fixed `ubuntu-24.04` hosted image, methodology installs the lockfile-pinned
Chromium without `--with-deps`, reusing the system browser libraries already
provided by the [runner image](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md#browsers-and-drivers). Its Chromium cache is keyed by OS, architecture and the
frontend lockfile. Only full Chromium is needed: Python probes invoke its exact
executable path, so the separate headless-shell download is omitted. Browser
installation has a five-minute limit; the complete job has a twenty-minute limit.
A one-minute browser-launch preflight fails on missing Chromium or system
libraries before measurements begin; it never substitutes a different renderer
or silently accepts a missing browser.

The motivating hosted run [40357494239, methodology job](https://github.com/reflex-dev/xy/actions/runs/40357494239/job/121694488499)
spent 9m50s installing Chromium, including 9m17s fetching Ubuntu packages, while
the interaction step took 42s. Reproduce these setup-duration observations with
`gh api repos/reflex-dev/xy/actions/jobs/121694488499` and that job's `/logs`
endpoint. These are hosted step durations, not chart-performance benchmarks;
the speedup of the revised setup still needs a fresh hosted run.

Validation: `python3 scripts/verify_ci_workflow.py` and
`pytest -q tests/test_ci_scope.py tests/test_verify_ci_workflow.py`. The selection
tests cover docs, shim, shared code, mixed/unknown inputs, full manual selection,
and moved/deleted source paths. The workflow tests check dependency wiring and
blocking gates. Inspect `Select CI checks` outputs and `ci-linux-wheel` artifacts
on an Actions run to reproduce the selection/reuse evidence. These changes reduce
duplicate work by construction; elapsed-time improvement still requires a hosted
before/after Actions run and is not claimed as a measured benchmark.

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

The docs app disables the built-with-Reflex badge in its configuration.
Breadcrumb destinations must match discovered documentation pages, including
explicit gallery aliases. Category segments without a page render as text;
leaf links and the mobile sidebar drawer remain available. The mobile drawer
trigger is a named native button with visible keyboard focus. Footer navigation
uses level-two section headings. Installation examples use subsections so code
blocks cannot become invalid direct children of a list.
The docs consume the reusable `reflex-site-shared` base theme and components
directly. XY owns its branding, navigation, project-specific footer content,
and the docs-only brand layer adapted from
[Reflex PR #7549](https://github.com/reflex-dev/reflex/pull/7549). It must not
vendor shared base CSS, search/buttons, or the navbar frame and announcement.
The local layer uses Inter body text, Geist headings, warm neutral light/dark
tokens, pill navigation and demo tabs, compact two-column Back/Next links, and
the opal banner artwork without a white top-edge inset shadow. Fonts ship through
pinned Fontsource packages; the artwork URL preserves the `/docs/xy` mount prefix.
Banner structure and the close event remain shared. Editorial selectors target `docs-*`
hooks, avoiding live chart typography and data-series colors. Mobile navigation,
the named closeable docs drawer, clipboard feedback, keyboard focus, and
reduced-motion behavior remain required validation surfaces.
XY's announcement matches `reflex-marketing`'s current main branch:
"Build vs. Buy for Internal Software" links to
`https://reflex.dev/blog/build-vs-buy-internal-software/`, with five mirrored
opal panels with reduced-motion support, a black New
badge, and a white text-only Read more pill hidden at 640px and below. Its visible
contribution is 44px on desktop and 40px at 960px and below, above the fixed 64px
docs header. A head script restores the same `reflex_announcement_dismissed_release`
storage key and `build-vs-buy-internal-software-v1` release before paint; dismissal persists
across reloads and same-origin marketing/docs navigation, with a working
visit-local fallback when storage is unavailable. Header and sidebar offsets
reserve only the visible announcement. The wrapper retains the shared native
link and close event while adapting its destination, copy, decorative markup,
and accessible name. The message wraps at narrow widths as it does in marketing.
Below 1280px, opening the navigation menu removes both top header corners;
closing it restores the announcement's rounded header. Announcement links open
in a new tab with `noopener noreferrer`, matching their accessible name.
Authored in-page links must
resolve to rendered IDs, including the parentheses retained by the shared
heading slug convention (lowercase text with spaces replaced by hyphens).
Unpublished shared changes are previewed with the editable-package
workflow in `docs/app/README.md`, followed by production compilation and the docs
validators below. The portable Git lock includes the merged design's shared
styling hooks and mobile drawer changes; update all Reflex monorepo packages
together and validate the production app when refreshing it.
`docs/app/tests/test_docs_layout.py` exercises the real shared layout for first,
middle, and last pages, verifying the article styling hook, preserved content,
adjacent link destinations, removal of empty placeholders, and Next's placement
in the second grid column. These contracts must pass after shared-package updates.
Long demo code disclosures fade to the same muted surface as their containing
card in both color modes. The frontend lock must resolve the declared PostCSS
version without an older override shadowing the framework's build dependency.
The desktop XY docs navigation switches to a docs-specific disclosure below
1280px, preserving Overview and Reflex Integration destinations. Desktop links
expose the selected section through `aria-current="page"` and a neutral pill.
Internal navbar destinations use client-side routing so page changes preserve
announcement dismissal without a full document reload. Code blocks share
Reflex docs' light/dark syntax themes and neutral surface tokens while retaining
XY's accessible clipboard feedback. XY footer links and headings use body
typography and compact controls; sidebar links use normal weight, with medium
weight for the active page. Gallery previews, playground controls, API references, Markdown,
and demo UI text and borders use semantic theme tokens in both color modes.
Chart canvases retain explicit white/black backgrounds to match their rendered
plots; data-series colors remain chart-specific.

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
| CI/CodSpeed workflows | Hard gates, non-blocking benchmarks, best-effort benchmark artifact upload/download, and no-Rust clear-error jobs stay wired. The release workflows are `reflex-release`'s and are not re-checked here | `make check-ci` |
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
| sdist | Build-input-only source archive contains the `xy` and bundled `reflex_xy` packages, JSX/render-client bundles, complete JS/Rust build sources, and `PKG-INFO` version/dependencies (including the `matplotlib` and `reflex` extras with their supported ranges) matching the archive's own `xy-<version>` root; repository-only material, duplicate/unsafe members, native binaries, and generated junk are absent | `python scripts/verify_sdist.py dist/*.tar.gz` |
| Native wheel | Platform wheel contains package-only `xy` and `reflex_xy` files, exactly one native library, the JSX wrapper but no duplicate render client, `METADATA` version/base dependencies and `matplotlib`/`reflex` extras matching the wheel's own filename and `.dist-info` (numeric local versions compare without leading zeros), complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, and is tagged non-pure | `python scripts/verify_wheel.py dist/*.whl --expect-native` |
| Fallback wheel | No-toolchain wheel contains package-only `xy` and `reflex_xy` files, `METADATA` version/base dependencies and `matplotlib`/`reflex` extras matching the wheel's own filename and `.dist-info`, complete hash-checked `RECORD`, public export-surface markers, matching filename/`WHEEL` tags, is pure, and contains no native library | `python scripts/verify_wheel.py dist/*.whl --expect-pure` |
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
| CI/CodSpeed workflows, artifact upload/download, no-Rust clear-error jobs | `make check-ci` |
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

Use this after editing the CI or CodSpeed workflows, benchmark artifact upload/download
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

**`CHANGELOG.md` is the release trigger.** A version heading in it with no
matching git tag is what makes the pipeline build and publish that version, and
the tag is pushed only *after* PyPI accepted the artifacts. Releases are driven
by [reflex-release](https://github.com/reflex-dev/reflex/tree/main/packages/reflex-release)
and [towncrier](https://towncrier.readthedocs.io/), configured in
`[tool.reflex-release]` and `[tool.towncrier]`.

The version itself is still derived, never written down: `pyproject.toml`
declares `dynamic = ["version"]` and uv-dynamic-versioning reads the latest `v*`
git tag. Since no tag exists yet while a release builds, each build job tags its
own checkout with the version the changelog asked for — which is what makes the
artifacts carry it. Three consequences worth knowing:

- Builds outside a release are versioned `<next>.devN+<commit>`, which PyPI
  rejects by design: only the pipeline's tag produces an uploadable version.
- Every checkout that builds must be unshallow (`fetch-depth: 0`). A depth-1
  clone fetches no tags and would *silently* build at the `0.0.0` fallback —
  which is why `collect` re-checks that every artifact declares the released
  version before the approval gate, rather than trusting the build.
- A tag records a publish; it can no longer start one. No *publishing* workflow
  has a `push: tags` trigger, so a hand-cut tag cannot bypass the changelog, the
  version gate, or the approval. `deploy-docs-stg.yml` keeps one deliberately: it
  publishes nothing, and a re-tag should redeploy the docs.

### The release workflows

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `changelog.yml` | pull request | Requires a news fragment for source changes, rejects hand-written version headings, and runs `sync --check` so a stale generated workflow fails here. |
| `dispatch_release.yml` | manual | Materializes `news/` fragments into `CHANGELOG.md` at the next version. Final releases land through a pull request; prereleases go straight to an `r/pre-*` branch. |
| `release_from_changelog.yml` | push to `main`, `r/pre-**`, `r/hotfix/**` | Publishes any changelog version that has no git tag, by calling `publish.yml`. |
| `publish.yml` | called by the above, or manual | Validates the request, calls the build workflow below, waits for `pypi` environment approval, uploads, then tags and creates the GitHub release. |
| `build_release_artifacts.yml` | called by `publish.yml`, or manual for a dry run | **This repository's own**: the release matrix — eleven platform wheels, the runtime-verified PyEmscripten wheel, and the sdist. |
| `deploy-docs-stg.yml` | dispatched by `publish.yml` per published tag, or manual | **This repository's own**: builds and deploys the docs site for the version just published. |
| `deploy-docs-site.yml` | manual (`source_ref`, default `main`) | **This repository's own**: builds the docs site from a branch, tag, or commit and promotes the same images through staging and production approval, independently of a library release. |

The first four come from `reflex-release` (pinned at `0.1.0a4` in
`[tool.reflex-release] cli-command`), which owns their invariants and tests them
where the tool lives. This repository deliberately does not re-assert their
contents. The two library release integration workflows are
`build_release_artifacts.yml` and `deploy-docs-stg.yml`: one builds the artifacts,
one runs after the release. `deploy-docs-site.yml` is a separate, manually
dispatched site deployment; it does not participate in the library release
pipeline. See *Upgrading the release tool*, *After a release*, and *Docs-only
deployment* below.

What the approver sees and what the release records is one artifact: before the
`pypi` gate, `collect` writes a `sha256sum` manifest over exactly the files
bound for PyPI, prints it to the job summary the reviewer reads, and the gated
job re-checks it with coreutils only before uploading. `tag-and-release` then
attaches that same manifest to the GitHub release, so what a published version
contained outlives the workflow run.

Repository settings the pipeline depends on, once:

- A `pypi` environment **with required reviewers**. Every upload waits for that
  approval, and `publish.yml` fails closed if it starts without reviewers
  configured. If deployment branches are restricted, allow `main`, `r/pre-*` and
  `r/hotfix/*`.
- PyPI trusted publishing pointed at workflow `publish.yml`, environment `pypi`.
  This *changed* when releases stopped being tag-triggered: a publisher still
  naming `release.yml` will reject the upload.
- *Allow GitHub Actions to create and approve pull requests* (Settings →
  Actions → General), so a release action can open its pull request.
- The `skip-changelog` and `changelog-version-edit` labels.

### Upgrading the release tool

All four generated workflows are `reflex-release`'s output, verbatim. Upgrading is
a pin bump in two places — `cli-command` and the `Makefile`'s `RELEASE_VERSION` —
plus `reflex-release sync`; the generated `changelog.yml` runs `sync --check` on every
pull request, so a stale workflow (or a configuration change made without
re-syncing) is a red PR rather than a surprise at release time.

What this repository owns is `build_release_artifacts.yml`, because `xy` cannot
be built by `uv build` on one runner: eleven cross-compiled platform wheels, a
runtime-verified PyEmscripten wheel and an sdist, each needing its own operating
system or toolchain. `[[tool.reflex-release.custom-build]]` points the pipeline
at it, and `publish.yml` calls it in place of its own build job. Everything
either side is unchanged — same changelog detection, same version, same approval
gate, same tag-after-upload — and the whole matrix runs *before* the gate, so a
reviewer approves a set of files that already exists and has already been
checked.

Four rules make that build workflow correct, all load-bearing:

1. every artifact is named `<artifact-prefix><leg>`; anything else is not
   collected, and therefore not published;
2. upload distribution files only, since every collected file goes to PyPI;
3. tag the checkout with `tag`, which is what makes the artifacts carry the
   released version — `collect` fails the release otherwise;
4. let failures fail. No `continue-on-error`: a lost matrix leg must stop the
   release rather than ship an incomplete set.

`expect-artifacts` in `pyproject.toml` names all thirteen files a release must
contain, because a leg that runs, succeeds and uploads nothing looks exactly
like one never configured — and PyPI accepts a version once. `reflex-release
sync` also fails when the build workflow is missing or declares no
`workflow_call` trigger, so a rename is caught on the pull request.

### After a release

`post-release-workflow` names one workflow of this repository's own to dispatch
per published tag — `deploy-docs-stg.yml` — on the tag itself, so it sees exactly
the tree that was published. It must declare `workflow_dispatch` inputs named
`tag`, `package` and `version`, which is the dispatch contract;
`tests/test_release_process.py` asserts ours does, because GitHub rejects a
dispatch carrying inputs a workflow does not declare and that failure would land
*after* the upload and the tag — the version out, the docs not deployed.

A failure there is loud but harmless: the release is already published, and the
dispatch can be repeated by hand. This release-triggered deployment runs after
`create-release` and builds the published tree. The independent site deployment
described below can build a newer source snapshot without a library release.

Two consequences of where the build sits:

- **No secrets, no OIDC.** The calling job grants `contents: read`, and a called
  workflow cannot hold more privilege than its caller, so this is the same
  unprivileged boundary as the pipeline's own build job.
- Its `workflow_dispatch` trigger is the dry run: it builds and verifies the
  full matrix with no tag and no release. Nothing in that file can publish —
  the upload path is in `publish.yml`, which the dry run never calls — which is
  a stronger guarantee than the boolean `dry_run` gate the old tag-triggered
  `release.yml` used.

Because the release workflows are the tool's output, this repository does not
re-assert their contents: `reflex-release` tests those invariants where it lives,
and `scripts/verify_ci_workflow.py` covers only `ci.yml` and `codspeed.yml`. The
action pins follow the same line — `tests/test_verify_ci_workflow.py` applies
xy's one-SHA-per-action policy to the workflows xy authors, including
`build_release_artifacts.yml`, and leaves the generated four to the tool.

### Docs-only deployment

Use **Deploy XY Docs Only** (`deploy-docs-site.yml`) in the Actions tab to deploy
site changes without publishing a library version. The workflow must first land
on the default branch before it can be manually dispatched. Select `main` as
the workflow ref, and set `source_ref` to the branch, tag, or commit to build;
the input defaults to `main`. The equivalent CLI command is:

```bash
gh workflow run deploy-docs-site.yml --ref main -f source_ref=main
```

The workflow resolves `source_ref` once to a full commit SHA, then builds both
frontend and backend images from that commit with the common tag
`docs-<first 12 SHA characters>-<run_id>-<run_attempt>`. Each new dispatch or
full rerun gets a distinct tag, including when it selects the same commit.
Retries of failed downstream jobs retain the completed preparation's tag.
The image pair is built once, sent to staging, then promoted unchanged after the
existing `production` environment
approval. This path neither checks PyPI availability nor publishes a package,
creates a release tag, or creates a GitHub release. The generated library
release workflows and their two integration workflows keep their existing
contracts.

Deployment reuses `_build-docs-images.yml` and `_helm-docs-pr.yml`. The Helm
workflow updates both XY image tags in `charts/internal/values-stg.yaml` and,
after approval, `charts/internal/values-prod.yaml`, bumps the chart version, and
merges the corresponding helm-charts pull requests. The existing helm-charts
release and infra chart-pin automation then drives Flux reconciliation. Success
of the staging values update does not verify staging cluster health; the
production approval is the operator's opportunity to inspect the staged site
before promoting it.

The site workflow shares concurrency group `deploy-xy-docs-stg` with the
library-triggered `deploy-docs-stg.yml`. Both set `cancel-in-progress: false` and
`queue: max`: one deployment runs at a time and up to 100 pending deployments
are retained. Without `queue: max`, a new dispatch replaces the single pending
run even when cancellation of the active run is disabled. Once the 100-run
pending queue is full, GitHub cancels additional runs; it is not an unbounded
queue. See [GitHub's concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency#example-queueing-multiple-pending-runs).

A run waiting for production approval holds that group, so newer
library-triggered and docs-only deployments cannot advance past it. If that run
is obsolete, explicitly cancel it in Actions before expecting a newer deployment
to proceed; dispatching another run does not cancel the existing approval wait.
The separate dev deployment continues to follow pushes to `main`.

### Landing changes

Every change to `python/`, `src/` or `js/` — the `root-source-dirs` a news
fragment is required for — adds one:

```bash
make news NAME=1234.feature.md   # breaking, deprecation, feature, bugfix,
                                 # performance, docs, misc
```

Write it for someone reading release notes, not for a reviewer reading the diff.
Before you know the PR number, name it `+something.feature.md` and rename it
later. `make news-check` runs the same check CI does. The `skip-changelog` label
waives it for changes that genuinely are not user-facing; nothing waives the
guard against hand-written version headings (`changelog-version-edit` is for
deliberate restructuring of already-published sections, and this repository's
switch to the towncrier heading format needed it once).

### Cutting a release

Run **Dispatch release** from the Actions tab and pick an action:

| Action | Result |
| --- | --- |
| `release-patch` / `-minor` / `-major` | Final version from `main`. Opens a pull request. |
| `release-post` | `X.Y.Z.postN`, for packaging-only fixes. Opens a pull request. |
| `new-prerelease-patch` / `-minor` / `-major` | Starts an alpha train (`X.Y.Za1`) on an `r/pre-<date>` branch; builds immediately, uploads after approval. |
| `continued-prerelease` | Next alpha (`a2`, `a3`, …). Dispatch **on** the train's `r/pre-*` branch. |
| `release-from-prerelease` | Turns the train into its final version and collapses every alpha section into one, so alpha headings never ship in a final changelog. |

Selecting no package auto-selects: pending news fragments, or (for
`release-from-prerelease`) an alpha-topped changelog. **Merging the release pull
request is what publishes.** Pre-releases use canonical PEP 440 suffixes
(`aN`/`bN`/`rcN`); pip ignores them unless asked explicitly. Hotfixes branch
`r/hotfix/X.Y` from the tag and publish directly from there, without stealing the
"Latest" badge from a newer line.

The repository has one release line: the `xy` distribution, including its
bundled `reflex_xy` integration. The `xy[reflex]` extra is dependency metadata in
those same artifacts, not another package or release.

If a publish fails, fix the problem on top of the changelog bump — the tag was
never pushed, so the next push to the branch retries the same version. Nothing
has to be deleted and re-cut.

The documentation site follows automatically: `deploy-docs-stg.yml` is the
configured `post-release-workflow`, so the pipeline dispatches it on each
published tag once the upload, the tag and the GitHub release exist. Its own
`push: tags` trigger cannot see that tag — it is pushed with `GITHUB_TOKEN`,
which fires no on-push workflow — which is exactly the gap the dispatch closes.
It stays hand-dispatchable with a `tag` for a re-deploy.

Before merging a release pull request:

- Review the materialized `CHANGELOG.md` section. It is the release notes, the
  GitHub release body, and the publish authorization in one artifact; the version
  in it is the version that ships. `scripts/check_release_version.py` refuses a
  shape uv-dynamic-versioning cannot derive (`.devN`, local `+…`, or
  non-canonical `-alpha1` spellings) before the matrix builds.
- Refresh benchmark reports or explicitly document why the previous report still
  applies.
- Run `make check-full` locally or confirm the equivalent
  CI gates passed on the release commit.
- Run `make check-ci` to confirm the CI and CodSpeed workflow gates still
  include artifact verification and upload/download. The release workflows are
  not in its scope: `reflex-release sync --check` on every pull request is what
  keeps the generated four honest, and `collect` verifies the artifacts at
  release time.
- Before the first release after a change to the wheel matrix (new target,
  cross-compile toolchain, or tagging scheme), manually run
  `build_release_artifacts.yml` (`workflow_dispatch`) and confirm every leg of
  the cross-compile matrix — including the newer aarch64/armv7/musllinux/
  win-arm64 targets and the wasm job — actually builds, since a target added to
  the matrix but never exercised in CI is unverified, not working. That run
  reaches no publish path at all. Add the new platform to `expect-artifacts` in
  the same change, or a release can ship without it.
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
  runtime dependencies, and Matplotlib/Reflex extras. It must exclude
  repository-only docs, tests, gallery evidence, scripts, benchmarks, examples,
  native binaries, generated caches, unsafe paths, and duplicate members.
- Confirm each platform wheel passes `scripts/verify_wheel.py --expect-native`
  and its install smoke loads `xy.kernels.BACKEND == "native"`. Confirm the
  fallback `py3-none-any` wheel passes `--expect-pure` and fails compute with
  the documented native-core error. Wheel
  `METADATA` must keep `Name: xy`, `Requires-Python: >=3.11`,
  `anywidget>=0.9`, and `numpy>=1.24` as base requirements, plus
  `matplotlib>=3.11,<3.12` and `reflex>=0.9.6` guarded by their respective
  `matplotlib` and `reflex` extras. The wheel
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
- `build_release_artifacts.yml`'s `workflow_dispatch` (leave `tag` empty) builds
  and verifies every wheel/sdist/wasm artifact without publishing; remaining
  follow-up is wiring an actual TestPyPI upload into that dry-run path (today it
  reaches no publish path at all, it doesn't yet push to a test index) plus
  refreshed benchmark reports.
- `reflex-release` is pinned at `0.1.0a4`, an alpha. Track its releases and bump
  the pin as it stabilizes, keeping `cli-command` and the `Makefile`'s
  `RELEASE_VERSION` on the same version — otherwise `make news` and the release
  workflows run different pipelines. `sync --check` on every pull request catches
  the half of a partial bump that reaches the workflows.
- Two review findings land in `reflex-release`'s generated workflows, so they are
  upstream fixes rather than local edits — patching them here would fork a file
  `sync --check` then reports as drift forever, which is the arrangement this
  repository just removed. Both were still open as of `0.1.0a4`, which did pick up
  two job-level `if` fixes in the publish path instead — the second of them
  load-bearing for this repository, since `custom-build` is exactly the shape it
  describes:
  - `publish.yml`'s `publish` and `tag-and-release` jobs now carry explicit
    status functions (`!cancelled() && needs.<job>.result == 'success'`). Without
    one, GitHub evaluates an implicit `success()` over the whole transitive
    dependency closure rather than the direct `needs`, so the build path that
    *doesn't* run — here the tool's own `build` job, replaced by
    `build_release_artifacts.yml` — would pass straight through `collect` and
    the upload would silently never happen.
  - `release_from_changelog.yml`'s health check no longer accepts every
    `skipped` leg: a leg is healthy as `skipped` only when `detect` found no
    packages for it, so a job GitHub skipped despite having work to publish is
    now an error rather than a green run that shipped nothing.
  - `publish.yml`'s approval gate interpolates the captured `gh api` error into a
    `::error::` message. A `gh` error line containing `::` would be re-parsed as a
    workflow command, truncating the diagnostic. It cannot leak anything (the job
    holds no secrets) and only affects a failure message, but it should be
    sanitized before interpolation.
  - `changelog.yml`'s header says "Two guards on every pull request" above three
    numbered guards; the count went stale upstream when the `sync --check` step
    was added.

- `allow-self-review` is left at its default (`true`), so the `pypi`
  environment's reviewer list is the only control over who approves an upload —
  whoever dispatches a release can approve their own. Setting it to `false`
  makes `publish.yml` require that the environment prevents self-review, i.e. a
  real two-person rule. Enable "Prevent self-review" on the environment first;
  the check fails closed if GitHub does not report it.
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
