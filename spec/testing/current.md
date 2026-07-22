# Current Testing Inventory

This document describes evidence that exists in the repository today. Status
uses the vocabulary in [`README.md`](README.md). The scope column is important:
`IMPLEMENTED` applies only to the exact behavior stated, not to a broader
product area with a similar name.

The inventory groups tests by risk surface rather than listing every test
function. Test locations, stable commands, and workflow jobs are the executable
index. Missing additions are tracked by ID in [`gaps.md`](gaps.md).

## Repository contracts and static quality

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Python lint and formatting | `ruff check .`; `ruff format --check .`; repository pre-commit hooks | Hard CI and required before push by contributor policy | `IMPLEMENTED` | Covers the configured Python source set. |
| Public API and annotations | `scripts/check_public_api.py`; `tests/test_public_api.py`; `tests/test_type_surface.py`; `tests/test_api_parity.py` | Hard CI / `make check-api` | `IMPLEMENTED` | Dynamic inventories cover exports, lazy mappings, builder/applier identity, defaults, and the `py.typed` surface. |
| Python floor syntax and imports | `scripts/check_python_floor.py`; `tests/test_python_floor.py`; `tests/test_import.py`; `tests/test_dependencies.py` | Hard CI / `make python-floor` / `make check-import` | `IMPLEMENTED` | The syntax/import contract is distinct from a full supported-version and minimum-dependency matrix. See TST-NI-036. |
| Documentation examples and public claims | `tests/test_docs_examples.py`; `tests/test_claim_guardrails.py`; `scripts/check_claim_guardrails.py` | Hard CI / `make check-docs` | `IMPLEMENTED` | Public examples and broad benchmark wording are checked. Specification-only pull requests are excluded by workflow paths. See TST-NI-005. |
| Generated JavaScript bundle freshness | `node js/build.mjs --check`; main-CI ESM/IIFE parse; release freshness check and rebuild | Hard CI and release | `IMPLEMENTED` | This proves source-to-bundle freshness and parseability in main CI, not JavaScript semantics. See TST-NI-007. |
| Default CodeQL analysis | GitHub default setup for Actions, JavaScript/TypeScript, Python, and Rust | Separate GitHub code-scanning workflow; not required by the main ruleset | `IMPLEMENTED` | This status applies to code scanning, not dependency-vulnerability auditing. |
| Generated native font freshness | `scripts/gen_font.py`; committed `src/font.rs` | No check mode or comparison gate | `NOT IMPLEMENTED` | The generator relationship is documented in source but cannot fail CI when stale. See TST-NI-043. |
| Matplotlib compatibility snapshot freshness | `scripts/sync_matplotlib_compat.py --check` | Hard Matplotlib reference job | `IMPLEMENTED` | The generated method inventory is current for the pinned reference. Semantic gaps are separate. |
| Workflow contract checking | `scripts/verify_ci_workflow.py`; `tests/test_verify_ci_workflow.py` | Hard CI / `make check-ci` | `PARTIALLY IMPLEMENTED` | Checks CI, CodSpeed, and release text/wiring. It is not a semantic dependency validator and omits docs/deploy/reusable workflows. See TST-NI-038. |
| Specification contract checking | Claim guardrails; `scripts/check_testing_spec.py`; `tests/test_check_testing_spec.py` | Hard root suite / `make check-testing-spec` and `make check-docs` | `PARTIALLY IMPLEMENTED` | The testing catalog's links, anchors, status vocabulary, gap-ID integrity, `make` targets, referenced paths, and workflow jobs are enforced whenever the root suite runs. Because CI and CodSpeed ignore `spec/**`, a specification-only pull request still receives no lane, and the rest of `spec/` is unchecked. See TST-NI-005. |
| Type checking | `ty check python` | Advisory; current CI permits diagnostics | `PARTIALLY IMPLEMENTED` | The latest audit observed 25 accepted diagnostics and an unprovisioned adapter surface. No baseline ratchet exists. See TST-NI-044. |

## Python API, data, and protocol

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Core Python behavior | Repository-wide `pytest -q`, recursively including root tests, `tests/pyplot/`, and `tests/reflex_adapter/` | Hard main and Python 3.11 jobs | `PARTIALLY IMPLEMENTED` | Broad native-backed coverage exists, but optional dependency and adapter tests can skip without a per-job allowlist. See TST-NI-031 and TST-NI-036. |
| Figure grammar and builder parity | `tests/test_figure.py`; `tests/test_components.py`; `tests/test_api_parity.py`; plot-family tests | Hard root suite | `IMPLEMENTED` | Public composition methods, appliers, signatures, defaults, and representative payloads are exercised. The stronger all-builder property/rollback claim is partial below. |
| Validation and transactional rollback | `tests/test_components.py`; `tests/test_figure.py`; focused error/LOD/cache tests; `make check-errors` | Hard root suite | `PARTIALLY IMPLEMENTED` | Targeted rollback exists, but no injected late-failure matrix covers all 20 public builders on seeded state. See TST-NI-006. |
| Property-based figure tests | `tests/test_property_figure.py`; `tests/test_framing_property.py` | Hard when Hypothesis is installed | `PARTIALLY IMPLEMENTED` | Figure strategies cover six core builders, and the framing property is valid-input focused. See TST-NI-006 and TST-NI-028. |
| Column ingestion and geometry | `tests/test_arrow_ingest.py`; `tests/test_arrowgeom.py`; scatter, matrix, facets, and plot-family tests | Hard root suite when optional dependencies are present | `PARTIALLY IMPLEMENTED` | Lists, NumPy, Arrow, geometry, and selected null/copy paths have evidence. A catalog for dtype/shape/stride/endian/null/pandas/Arrow and cross-renderer semantics is not enforced. See TST-NI-010 and TST-NI-047. |
| LOD, precision, streaming, and cache behavior | `tests/test_lod.py`; `tests/test_streaming.py`; density, zoom-precision, bounds, and tier-update tests | Hard root suite plus focused browser smoke | `PARTIALLY IMPLEMENTED` | Core direct/decimated/density and mutation paths are covered; the full axis/action/drill/stream/resource matrix and soak bounds are not. See TST-NI-011 and TST-NI-034. |
| Wire framing | `tests/test_framing.py`; `tests/test_framing_property.py`; Python-to-JavaScript golden decoding | Hard root suite | `IMPLEMENTED` | Truncation, corrupt headers, padding, metadata, zero-copy, and valid round trips are substantive. A catalog-generated request matrix and property byte mutation remain missing. See TST-NI-028. |
| Widget/channel dispatch | `tests/test_channel.py`; `tests/test_widget.py`; `tests/test_html_transport.py` | Hard root suite | `IMPLEMENTED` | Valid/malformed dispatch, callbacks, payload splitting, and Python widget behavior are covered. A real notebook frontend mount is not. See TST-NI-018. |
| Governed branch and diff coverage | Local branch-aware measurement from the root suite is supporting evidence | Not uploaded or governed in CI | `NOT IMPLEMENTED` | The audited aggregate was 82%; no package floor, diff ratchet, or combined core/pyplot/adapter view exists. See TST-NI-029. |
| Mutation score | No mutation lane | None | `NOT IMPLEMENTED` | Oracle strength is inferred from tests and selected negative cases. See TST-NI-030. |

## Native Rust and JavaScript client

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Rust debug correctness | `cargo test` | Hard main CI / `make rust-check` | `IMPLEMENTED` | Includes deterministic randomized kernel and scalar/native parity cases. |
| Hard Rust release-test gate | `cargo test --release` can run locally and includes a release-only regression | Not in the main gate | `NOT IMPLEMENTED` | The executable local test is supporting evidence; the required automated protection is absent. See TST-NI-020. |
| Rust lint | `cargo clippy --all-targets -- -D warnings` | Hard main CI | `IMPLEMENTED` | Covers configured targets on the main Linux host. |
| Native C ABI | `scripts/abi_smoke.py` | Hard main CI / `make abi-smoke` | `IMPLEMENTED` | Loads the built core and checks the exported ABI surface. |
| SIMD and architecture parity | Fixed-seed parity tests, host wheel import probes | Mixed | `PARTIALLY IMPLEMENTED` | AVX2 can be unavailable without explicit capability evidence; ARM, Windows, and macOS do not run a common kernel/FFI matrix. See TST-NI-023. |
| Native sanitizers, Miri, and coverage-guided fuzzing | Deterministic randomized tests only | None | `NOT IMPLEMENTED` | There is no sanitizer, Miri, or cargo-fuzz lane. See TST-NI-021. |
| Native dependency audit | Point-in-time security review | None in regular automation | `NOT IMPLEMENTED` | No `cargo audit` or `cargo deny` policy is enforced. See TST-NI-022. |
| JavaScript build and syntax | `node js/build.mjs`; main-CI ESM import and IIFE parse checks; release rebuild | Hard main CI plus release build | `IMPLEMENTED` | Main CI proves parseability; release rebuilds the exact artifact after the freshness check. |
| JavaScript semantic units | Behavior is reached through Python-driven Node checks and browser scripts | No first-class unit command | `NOT IMPLEMENTED` | There is no `node --test` or equivalent suite for frames, ticks, formatters, bounds, registry, LOD, or worker state. See TST-NI-007. |
| Protocol-version implementation coherence | Python and JavaScript runtime constants currently agree | Indirect tests | `PARTIALLY IMPLEMENTED` | Some specification and smoke fixtures can drift; the animation smoke used protocol 3 while runtime uses 4. See TST-NI-046. |

## Rendering, interaction, and host integration

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Dependency-light WebGL render | `scripts/render_smoke_nonumpy.py <chromium>` | Hard main CI | `IMPLEMENTED` | Exercises representative marks, interaction, context loss, and nonblank pixels without NumPy. It is not an every-kind registry. |
| Real Figure browser render | `scripts/smoke_render.py <chromium>` | Hard main CI | `IMPLEMENTED` | A composed Figure reaches nonblank Chromium pixels. |
| Native and browser export | PNG/JPEG/WebP/SVG/PDF unit tests; `scripts/png_export_smoke.py`; image and batch-export tests | Hard root/browser lanes, with optional external PDF tooling | `PARTIALLY IMPLEMENTED` | Broad byte/pixel validation exists. Public persistent browser batch reuse, mixed-format cleanup, and a guaranteed independent PDF oracle are incomplete. See TST-NI-045. |
| Standalone HTML and text security | `tests/test_static_client_security.py`; HTML transport/CSS tests; `make check-security` | Hard root suite | `IMPLEMENTED` | Escaping, CSP, hostile strings, atomic writes, and static sink constraints are strong. Runtime DOM/network isolation and sandbox downgrade policy are separate gaps. See TST-NI-024 and TST-NI-025. |
| FastAPI gallery lifecycle | `scripts/reflex_lifecycle_smoke.py` | Hard Chromium CI/browser lane | `IMPLEMENTED` | Exercises gallery routes, resize, visibility, context loss/restore, drilldown, and embedded iframes. The filename is misleading: it serves `examples/fastapi`, not Reflex. |
| Visual health | `scripts/visual_regression_smoke.py` | Hard Chromium CI/browser lane | `IMPLEMENTED` | Detects blank/collapsed output, occupancy, region, and label-overlap failures. It is not a reviewed image-baseline regression suite. See TST-NI-014. |
| Step tier replacement | `scripts/step_tier_smoke.py` | Hard Chromium CI/browser lane | `IMPLEMENTED` | Protects step risers across a synthetic tier-buffer replacement. |
| Interaction stress | `scripts/interaction_stress_smoke.py`; focused wheel/pan/zoom/pick tests | Hard Chromium CI/browser lane | `PARTIALLY IMPLEMENTED` | Core wheel, pan, hover, crosshair, box zoom, and brush paths have budgets and visual invariants. The full axis/action matrix, required worker evidence, and pick limits are not wired. See TST-NI-011, TST-NI-012, and TST-NI-016. |
| Focused cross-browser conformance | `node scripts/browser_conformance.mjs` in Chromium, Firefox, and WebKit | Hard CI / `make check-conformance` | `IMPLEMENTED` | The shared fixture checks one direct linear scatter for semantics, accessibility, layout, and tolerant raster equality. Broader kinds, tiers, DPRs, motion, and axes are not covered. See TST-NI-015. |
| Browser version support policy | Playwright-pinned current Chromium, Firefox, and WebKit | Hard CI for the pinned versions only | `NOT IMPLEMENTED` | No normative engine/version floor, WebGL2 prerequisite statement, or oldest-claimed-version lane exists, and recorded renderer versions can drift from the docs. See TST-NI-054. |
| GPU and driver realism | Headless CI lanes running software rendering | Hard Chromium CI on software rasterization | `NOT IMPLEMENTED` | No lane exercises representative hardware WebGL2 drivers or rejects software fallback, so driver-specific defects are invisible. See TST-NI-052. |
| Renderer failure-mode behavior | Successful context loss/restore paths plus source-marker assertions | Mixed | `PARTIALLY IMPLEMENTED` | Restoration is proved in a real browser, but WebGL2 acquisition, shader/program, and permanent-restore failures are not forced and their user-visible contract is unasserted. See TST-NI-053. |
| Chart-kind render contract | Core browser smoke plus examples cover common families | Mixed | `PARTIALLY IMPLEMENTED` | The 18-kind registry is not tied to one required payload/browser/static evidence catalog. See TST-NI-009 and TST-NI-010. |
| Axes, layout, styling, chrome, and facets | Axis/viewport, facets, CSS mark styles, export, legend-resize, and gallery browser tests | Mixed hard evidence | `PARTIALLY IMPLEMENTED` | Representative axes, facets, legends, annotations, colorbars, CSS, and layout behavior are covered, but named/reversed/log/category combinations, formatter semantics, collision behavior, and cross-renderer parity lack one catalog. See TST-NI-008, TST-NI-010, TST-NI-011, and TST-NI-014. |
| Pan/zoom contract | Focused Python regressions and Chromium interaction smoke | Mixed | `PARTIALLY IMPLEMENTED` | The specified linear/log/reversed/category/dual-axis, bounds, links, no-op, reduced-motion, and Reflex matrix is not implemented. See TST-NI-011. |
| Animation Python contract | `tests/test_animation.py`; Python-only CodSpeed microbenchmarks | Hard root suite / advisory CodSpeed | `IMPLEMENTED` | Validation, payload, and deterministic static behavior have evidence. |
| Required animation browser gate | `scripts/animation_smoke.py` exists as supporting evidence | Unwired and stale | `NOT IMPLEMENTED` | It is absent from CI/Makefile/local browser checks and hard-coded protocol 3 at audit time. Real-browser animation measurement is also unwired. See TST-NI-013 and TST-NI-048. |
| Dashboard context governance | `benchmarks/bench_dashboard.py` at 10/20/50 plus report verification | Hard job executes it; benchmark jobs are advisory | `PARTIALLY IMPLEMENTED` | The latest 50-chart row failed while verification remained green. Strict health semantics are not implemented. See TST-NI-002. |
| Accessibility | Source contracts plus the focused three-engine semantic fixture | Mixed hard evidence | `PARTIALLY IMPLEMENTED` | Roles and selected keyboard/live behavior have evidence, but there is no normative rendered matrix for direct/aggregate charts, focus, forced colors, or a table alternative. See TST-NI-017 and TST-NI-039. |
| Anywidget/Jupyter | Python widget and transport tests | Hard root suite | `PARTIALLY IMPLEMENTED` | No supported notebook frontend mounts the shipped widget and drives bidirectional behavior. See TST-NI-018 and TST-NI-019. |
| Reflex adapter | `tests/reflex_adapter/`; `scripts/reflex_ws_smoke.py` | Not provisioned or run by CI | `PARTIALLY IMPLEMENTED` | Valuable adapter/socket tests exist when dependencies are installed, but one import skip hides the suite and the real browser smoke is unwired. The required adapter lane is `NOT IMPLEMENTED`; see TST-NI-004. |
| FastAPI and host versions | Example tests and the gallery browser app | Mixed | `PARTIALLY IMPLEMENTED` | Supported host floors/latest versions are not exercised as a declared matrix. See TST-NI-019. |

## Matplotlib compatibility and documentation application

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| `xy.pyplot` API and state | `tests/pyplot/`; compatibility snapshot; public annotations and state/artist/options tests | Hard dedicated Matplotlib 3.11 and root suites | `IMPLEMENTED` | The declared compatibility inventory and broad behavioral corpus are substantial. |
| Matplotlib semantic/perceptual parity | Pinned reference subsets and a 54-case corpus | Hard dedicated lane | `PARTIALLY IMPLEMENTED` | The tolerant corpus can accept wrong or empty data for some cases; contour, vector magnitude, transforms, and tick semantics need stronger independent oracles. See TST-NI-026. |
| Pyplot accepted-option use | Existing compatibility and silent-drop regressions | Hard tests | `PARTIALLY IMPLEMENTED` | The current scanner can miss named-but-never-read options, and no-op declarations are free text. See TST-NI-027. |
| Required pandas interoperability lane | Tests guarded by `pytest.importorskip("pandas")` are supporting evidence | Dependency absent from normal CI | `NOT IMPLEMENTED` | No supported pandas floor/latest lane enforces Period/Series interoperability. See TST-NI-047. |
| Documentation app | `docs/app/tests`; production app on Python 3.11/3.12; sitemap, Markdown asset, route, and preview checks | Docs workflow | `IMPLEMENTED` | Applies to selected docs paths, not specification-only changes. |
| Published quickstart | Installs the configured released `xy` wheel and executes public quickstarts | Docs workflow | `IMPLEMENTED` | The published version is currently hard-coded and must be maintained deliberately. |

## Performance, packaging, platforms, and delivery

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Benchmark harness and report schema | Benchmark-specific tests; `scripts/verify_benchmark_report.py`; environment/category/status metadata | Hard harness tests; benchmark workflows mostly advisory | `PARTIALLY IMPLEMENTED` | Schema is strong, but unexpected failures, skips, and unavailable rivals can still produce green integrity results. See TST-NI-042. |
| Deterministic hard regressions | Native scatter/kernel/transport metrics and `scripts/check_regressions.py` | Hard main CI | `IMPLEMENTED` | Catastrophic configured regressions block; ordinary shared-runner timing remains advisory. |
| Regular-CI cross-library measurements | Isolated scatter, line, install, workflow, interaction, and dashboard benchmarks | Advisory workflow artifacts | `PARTIALLY IMPLEMENTED` | Expected competitor availability and skip ceilings are not enforced; plotly-resampler was unavailable in the audited run. See TST-NI-042. |
| Manual benchmark refresh | Scatter and core-2D browser measurements in `benchmark-refresh.yml` | Manual workflow | `PARTIALLY IMPLEMENTED` | It produces reviewable measurements but is not part of regular pull-request evidence. See TST-NI-042. |
| Full pyplot-vs-Matplotlib speed comparison | `make check-pyplot-speed` | Local only | `PARTIALLY IMPLEMENTED` | The executable comparison is not automated in CI or benchmark refresh. See TST-NI-042. |
| CodSpeed microbenchmarks | `benchmarks/test_codspeed_*.py --codspeed` | Advisory CodSpeed workflow | `IMPLEMENTED` | Covers kernel, transport, pyplot, and Python animation microbenchmarks. It is not the real-browser animation benchmark. |
| Real-browser animation benchmark | `benchmarks/bench_animation.py` exists | No CI, Makefile, refresh, or report-verifier lane | `NOT IMPLEMENTED` | See TST-NI-048. |
| Source distribution structure | `uv build --sdist`; `scripts/verify_sdist.py`; expected no-Rust error path | Hard CI/release | `IMPLEMENTED` | A clean Rust-enabled install from the built sdist is missing. See TST-NI-040. |
| Native and pure wheel structure | `scripts/verify_wheel.py`; metadata/tags/RECORD/content/native-presence checks; 15 MB budget | Hard CI/release | `IMPLEMENTED` | Structural coverage is strong. Runtime coverage is host-selective. |
| No-toolchain pure-wheel behavior | CI removes Cargo, builds and verifies `py3-none-any`, installs it, imports the top-level package, and requires an actionable compute-layer error | Hard CI | `IMPLEMENTED` | This is the supported negative runtime path; it does not replace positive native sdist installation. |
| CI wheel runtime | Linux x86, Linux ARM64, and Windows x64 build/install/native import jobs | Hard CI | `IMPLEMENTED` | Regular macOS and release-compatible manylinux/musllinux runtime parity are absent. See TST-NI-023. |
| Release wheel matrix | Eleven native platform wheels with structural verification; selected host-native import probes | Release workflow | `PARTIALLY IMPLEMENTED` | Most cross-built artifacts are not run, and no current successful full dry run proves the revised matrix. See TST-NI-023 and TST-NI-003. |
| Pyodide artifact | Pinned Rust/Emscripten/Pyodide build and runtime load probe | Release workflow | `IMPLEMENTED` | This status applies only to the exact release job; no regular PR/scheduled regression lane builds and runs the WASM artifact. See TST-NI-041. |
| Supported Python matrix | Explicit Python 3.11 plus the main runner's incidental Python | Hard CI | `PARTIALLY IMPLEMENTED` | The project declares Python 3.11+ without explicitly testing every currently claimed version or newest supported interpreter. See TST-NI-036. |
| Cross-platform behavioral parity | Windows, Linux ARM64, and macOS jobs build, install, and import the wheel | Hard CI for build/import only | `NOT IMPLEMENTED` | Python and Rust behavior suites run primarily on Ubuntu; other hosts prove artifact structure and import, not public API, kernel, framing, or export parity. See TST-NI-049. |
| Dependency reproducibility | Benchmark lock and docs lock; floating root `.[dev]` hard job | Mixed | `PARTIALLY IMPLEMENTED` | The hard root gate is not frozen; there is no separate latest-dependency canary or true minimum-dependency lane. See TST-NI-036. |
| Required merge gate | `required_ci` evaluates the complete hard-job result map with negative controls for failure, cancellation, skip, omission, and accidental advisory inclusion | Stable all-path result exists; repository ruleset does not yet require it | `PARTIALLY IMPLEMENTED` | The aggregate is executable, but `main` is not protected until the repository ruleset requires `Required CI`. See TST-NI-001. |
| Exact-SHA release qualification | Artifact builds and a push-only tag/version/changelog script | Human/process and partial workflow checks | `NOT IMPLEMENTED` | Publication does not prove the exact SHA passed the hard suite; manual real publication can bypass the version gate. See TST-NI-003. |
| Exact-SHA deployment qualification | Dev and stage/production deploy workflows | Deployment can begin before source CI completes | `NOT IMPLEMENTED` | Human approval does not replace exact-SHA automated qualification. See TST-NI-003. |
| Release provenance | Uploaded artifacts and trusted publishing | No consolidated hash/attestation gate | `NOT IMPLEMENTED` | Immutable promotion evidence, SBOM/attestation, and retry-safe provenance are missing. See TST-NI-003. |
| Continuous dependency-vulnerability auditing | A dated point-in-time security audit is historical evidence | No recurring dependency-audit lane | `NOT IMPLEMENTED` | Python, Rust, and JavaScript dependency audits are not enforced as one policy. See TST-NI-022. |

## Test reliability and evidence

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Suite markers and skip policy | Ad hoc markers, `importorskip`, and environment-dependent skips | No common per-job allowlist or budget | `NOT IMPLEMENTED` | Required dependencies/browsers can disappear into a skip. See TST-NI-031. |
| Retry and flake provenance | Browser launch retries and focused retry tests | Broad retry behavior; incomplete attempt reporting | `PARTIALLY IMPLEMENTED` | Semantic and infrastructure failures are not uniformly classified, and flaky passes are not governed. See TST-NI-032. |
| Async synchronization | Bounded waits plus several fixed sleeps in host-adapter tests | Mixed | `PARTIALLY IMPLEMENTED` | Fixed sleeps remain load-bearing in selected socket/registry cases. See TST-NI-033. |
| Resource-leak and soak testing | Lifecycle teardown assertions and short context/worker paths | No quantitative repeated-lifecycle gate | `NOT IMPLEMENTED` | Listener, GL, worker, socket, file-descriptor, temporary-file, and heap growth are not bounded over repetitions. See TST-NI-034. |
| Failure artifacts | Benchmark/package artifacts and normal job logs | Inconsistent for hard tests | `PARTIALLY IMPLEMENTED` | JUnit, coverage, screenshots/diffs, console/CDP traces, and retry history are not retained consistently. See TST-NI-035. |
| Execution timeouts | Some workflows and scripts have local bounds | No uniform hard/release policy | `PARTIALLY IMPLEMENTED` | Several jobs and hang-prone paths depend on runner ceilings. See TST-NI-051. |
| Fixture/golden provenance | Individual benchmark baselines, protocol vectors, and compatibility corpora | Per-surface conventions | `PARTIALLY IMPLEMENTED` | There is no shared rule for source, seed/version/license, update command, review, checksum, tolerance, and negative controls. See TST-NI-055. |
| Claim-to-test traceability | This risk-surface inventory and product-specific evidence links | Not machine checked claim by claim | `PARTIALLY IMPLEMENTED` | Stable normative claim IDs and orphan/dead-reference validation do not exist. See TST-NI-050. |

## Stable local commands

These commands are useful entry points. Their names do not broaden the scopes
described above.

| Command | Current scope |
|---|---|
| `make check` | Fast local verifier selection |
| `make check-full` | Non-browser Python, JavaScript freshness, Rust debug/clippy, Rust release build, and ABI checks; not a release-equivalent suite |
| `make check-browser CHROMIUM=...` | Configured Chromium smokes except dashboard; does not include animation, pick-boundary, Reflex, or cross-engine conformance |
| `make check-conformance` | Focused Chromium/Firefox/WebKit fixture |
| `make check-docs` | Executable examples and claim guardrails |
| `make check-examples` | README/API examples and Reflex asset-registry checks |
| `make check-security` | Standalone HTML safety and client text-sink checks |
| `make check-errors` | Public validation, rollback, LOD, drill, and cache focus |
| `make check-api` | Public API and type-surface contracts |
| `make check-import` | Import budget and dependency boundaries |
| `make check-ci` | Current workflow text/wiring invariants |
| `make check-claims` | Public performance-claim guardrails |
| `make check-testing-spec` | Validate this catalog's links, gap IDs, commands, paths, and workflow jobs |
| `make check-benchmark-harness` | Benchmark metadata, schema, and regression tests |
| `make check-pyplot` | Full `tests/pyplot` suite in the active environment |
| `make check-pyplot-speed` | Local full pyplot-vs-Matplotlib static-PNG target; requires benchmark dependencies |
| `make check-sdist` | Build and structurally verify a source archive |
| `make check-wheel` | Build and structurally verify a wheel; native expectation is caller-selected |
| `make check-artifacts` | Verify supplied prebuilt sdist and wheel paths |
| `make check-benchmark-report` | Validate one supplied benchmark JSON report and kind |
| `make list-checks` | Print the checks known to `scripts/verify_local.py` |
| `make test` | Repository-wide `pytest -q` in the active environment |
| `make lint` | `ruff check .` |
| `make format` | `ruff format --check .` |
| `make typecheck` | Advisory `ty check python` command; the command itself exits with the type checker result |
| `make public-api` | Direct public API checker |
| `make python-floor` | Direct Python-floor checker |
| `make js-check` | Committed JavaScript bundle freshness |
| `make rust-check` | Rust debug tests and clippy |
| `make abi-smoke` | Direct C ABI smoke |

The target replacement for the ambiguous `make check-full` contract is tracked
as TST-NI-037.

## Test suite and executable-helper registry

This registry makes dormant or optional evidence visible. `Wired` describes
automation, not whether the helper is valuable.

| Suite or helper | Scope | Wiring / status |
|---|---|---|
| Repository `pytest -q` | Root tests plus recursively collected pyplot and Reflex-adapter suites | Hard main/Python-floor jobs; `PARTIALLY IMPLEMENTED` because optional dependencies can skip |
| `tests/pyplot/` | Matplotlib API/state/artist/options/corpus/reference behavior | Root collection plus dedicated hard Matplotlib reference job; `IMPLEMENTED` for its documented scope |
| `tests/reflex_adapter/` | Adapter assets, components, vars, socket plane, state bridge, and tokens | Dormant in CI because dependencies are absent; target lane `NOT IMPLEMENTED` |
| `docs/app/tests` | Documentation application unit/route/content behavior | Docs quality job; `IMPLEMENTED` |
| `benchmarks/test_codspeed_*.py` | Kernel, transport, pyplot, and Python animation microbenchmarks | Advisory CodSpeed job; `IMPLEMENTED` |
| Rust tests in `src/` | Native kernels, encoding, raster, tiles, SIMD, and module invariants | Debug hard CI; release gate `NOT IMPLEMENTED` |
| `scripts/abi_smoke.py` | Exported native C ABI | Hard main CI |
| `scripts/render_smoke_nonumpy.py` | Dependency-light WebGL marks, pixels, interaction, and context recovery | Hard Chromium CI |
| `scripts/png_export_smoke.py` | Native and Chromium PNG health | Hard Chromium CI |
| `scripts/smoke_render.py` | Real composed Figure to Chromium pixels | Hard Chromium CI |
| `scripts/reflex_lifecycle_smoke.py` | FastAPI gallery lifecycle, drilldown, resize, visibility, context recovery, and iframes | Hard Chromium CI; misleading historical filename |
| `scripts/visual_regression_smoke.py` | Gallery visual-health invariants | Hard Chromium CI; not reviewed baseline regression |
| `scripts/step_tier_smoke.py` | Step geometry after tier-buffer replacement | Hard Chromium CI |
| `scripts/interaction_stress_smoke.py` | Wheel/pan/hover/crosshair/box/brush behavior and budgets | Hard Chromium CI; worker may skip |
| `scripts/browser_conformance.mjs` | Focused semantic/accessibility/layout/raster comparison | Hard Chromium/Firefox/WebKit CI |
| `scripts/pick_boundary_smoke.py` | Large trace/index picking limits | Exists locally; required gate `NOT IMPLEMENTED` |
| `scripts/animation_smoke.py` | Real-browser animation lifecycle/pixels/allocation | Exists locally but was stale and unwired; required gate `NOT IMPLEMENTED` |
| `scripts/reflex_ws_smoke.py` | Real Reflex websocket/browser path | Exists locally and is unwired; required gate `NOT IMPLEMENTED` |
| `scripts/pyodide_load_smoke.py` | Built WASM wheel runtime load | Release-only exact-artifact evidence |
| `scripts/verify_released_docs_quickstart.py` | Public quickstarts against the published wheel | Docs released-quickstart job |
| `scripts/check_release_version.py` and its tests | Tag, project version, and changelog coherence | Tag-push publication only; exact-SHA/manual preflight `NOT IMPLEMENTED` |
| `scripts/verify_sdist.py` / `scripts/verify_wheel.py` and tests | Package contents, metadata, tags, hashes, and native/pure expectations | Hard CI/release structural gates |
| `scripts/verify_benchmark_report.py`, merge/regression scripts, and tests | Benchmark schema, coherence, merge, and deterministic regression policy | Hard harness tests; outcome-integrity mode `NOT IMPLEMENTED` |
| `scripts/verify_local.py` and tests | Named local-suite composition and execution | Current local command router; release-equivalent aggregation `NOT IMPLEMENTED` |
| `scripts/check_testing_spec.py` and its tests | This catalog's links, anchors, status vocabulary, gap-ID integrity, and repository references | Hard root suite via `make check-docs`; spec-only pull-request lane `NOT IMPLEMENTED` |
| Hatch build-hook tests | Native build/no-toolchain build behavior | Repository pytest and packaging jobs |

## Workflow and job registry

| Workflow | Current jobs | Testing role |
|---|---|---|
| `ci.yml` | `matplotlib_reference`, `test`, `browser_conformance`, `python_floor`, `benchmark_vs`, `benchmark_methodology`, `benchmark`, `sdist`, `wheels`, `install_without_rust`, `required_ci` | Main hard and advisory code/package evidence; stable hard aggregate runs on every pull-request path |
| `codspeed.yml` | `benchmarks` | Advisory microbenchmark evidence |
| `docs.yml` | `released-quickstart`, `quality`, `production` | Published-wheel quickstart, docs tests/lint, and production-route matrix |
| `benchmark-refresh.yml` | `cross-library` | Manual scatter and core-2D refresh evidence |
| `release.yml` | `wheels`, `wasm`, `sdist`, `publish`, `publish-pyodide` | Artifact build/verification/publication; exact-SHA qualification missing |
| `_build-docs-images.yml` | `build-and-push` | Reusable docs-image build; not a source-test gate |
| `_helm-docs-pr.yml` | `open-helm-pr` | Reusable deployment PR automation; not a source-test gate |
| `deploy-docs-dev.yml` | `prepare`, `build`, `helm-pr`, `update-last-sha` | Development deployment; exact-SHA CI dependency missing |
| `deploy-docs-stg.yml` | `prepare`, `build`, `helm-pr-stg`, `await-prod-approval`, `release`, `helm-pr-prod` | Stage/production promotion; human approval exists, exact-SHA CI dependency missing |
| GitHub default CodeQL | Dynamic Actions, JavaScript/TypeScript, Python, and Rust analyses | Implemented code scanning; not a required merge check or dependency audit |
