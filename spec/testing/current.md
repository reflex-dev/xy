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
| Documentation examples and public claims | `tests/test_docs_examples.py`; `tests/test_claim_guardrails.py`; `scripts/check_claim_guardrails.py` scans every specification and public document | Hard all-path CI / `make check-docs` | `IMPLEMENTED` | Public examples and broad benchmark wording are checked, including specification-only changes. See TST-NI-005. |
| Generated JavaScript bundle freshness | `node js/build.mjs --check`; main-CI ESM/IIFE parse; release freshness check and rebuild | Hard CI and release | `IMPLEMENTED` | This proves source-to-bundle freshness and parseability; the dedicated semantic suite below tests the same committed ESM artifact. |
| Default CodeQL analysis | GitHub default setup for Actions, JavaScript/TypeScript, Python, and Rust | Separate GitHub code-scanning workflow; not required by the main ruleset | `IMPLEMENTED` | This status applies to code scanning, not dependency-vulnerability auditing. |
| Generated native font freshness | `scripts/gen_font.py`; committed `src/font.rs` | No check mode or comparison gate | `NOT IMPLEMENTED` | The generator relationship is documented in source but cannot fail CI when stale. See TST-NI-043. |
| Matplotlib compatibility snapshot freshness | `scripts/sync_matplotlib_compat.py --check` | Hard Matplotlib reference job | `IMPLEMENTED` | The generated method inventory is current for the pinned reference. Semantic gaps are separate. |
| Workflow contract checking | `scripts/verify_ci_workflow.py`; `tests/test_verify_ci_workflow.py` | Hard CI / `make check-ci` | `PARTIALLY IMPLEMENTED` | Checks CI, CodSpeed, release, docs deployment, and reusable image/Helm text and wiring with negative controls. It remains a string checker rather than a semantic dependency validator and does not cover every workflow. See TST-NI-038. |
| Specification contract checking | Whole-tree link/anchor, command, path/symbol/job, status/evidence-row, gap-ID, and public-claim validation in `scripts/check_testing_spec.py` and `scripts/check_claim_guardrails.py` | Hard all-path CI / `make check-testing-spec` and `make check-docs` | `IMPLEMENTED` | Stable completed gap IDs remain checkable and require explicit evidence; generated artifact paths require a workflow producer. See TST-NI-005. |
| Type checking | `ty check python` | Advisory; current CI permits diagnostics | `PARTIALLY IMPLEMENTED` | The latest audit observed 25 accepted diagnostics and an unprovisioned adapter surface. No baseline ratchet exists. See TST-NI-044. |

## Python API, data, and protocol

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Core Python behavior | Repository-wide `pytest -q`, recursively including root tests and `tests/pyplot/`; adapter tests are package-owned below | Hard main and Python 3.11 jobs | `PARTIALLY IMPLEMENTED` | Broad native-backed coverage exists, but optional root dependencies can still skip without a per-job allowlist. See TST-NI-031 and TST-NI-036. |
| Figure grammar and builder parity | `tests/test_figure.py`; `tests/test_components.py`; `tests/test_api_parity.py`; `tests/test_property_figure.py`; plot-family tests | Hard root suite | `IMPLEMENTED` | Public composition methods, appliers, signatures, defaults, representative payloads, and valid/invalid strategies for all 20 public builders are exercised. |
| Validation and transactional rollback | `tests/test_components.py`; `tests/test_figure.py`; `tests/test_property_figure.py`; focused error/LOD/cache tests; `make check-errors` | Hard root suite | `IMPLEMENTED` | Every public builder is injected with a failure after trace insertion on nonempty seeded state and must restore exact traces, columns/dedup keys, axes/categories, annotations, caches, pyramids, and drill state. See TST-NI-006. |
| Property-based figure tests | `tests/test_property_figure.py`; `tests/test_framing_property.py` | Hard root suite; Hypothesis is a required development dependency | `PARTIALLY IMPLEMENTED` | All 20 figure builders have must-succeed valid strategies and classified invalid strategies; the remaining partial scope is framing byte mutation. See TST-NI-006 and TST-NI-028. |
| Column ingestion and geometry | `tests/test_arrow_ingest.py`; `tests/test_arrowgeom.py`; scatter, matrix, facets, and plot-family tests | Hard root suite when optional dependencies are present | `PARTIALLY IMPLEMENTED` | Lists, NumPy, Arrow, geometry, and selected null/copy paths have evidence. A catalog for dtype/shape/stride/endian/null/pandas/Arrow and cross-renderer semantics is not enforced. See TST-NI-010 and TST-NI-047. |
| LOD, precision, streaming, and cache behavior | `tests/test_lod.py`; `tests/test_streaming.py`; density, zoom-precision, bounds, tier-update, and pan/zoom no-op tests | Hard root suite plus browser matrices | `PARTIALLY IMPLEMENTED` | Core direct/decimated/density and mutation paths are covered, and TST-NI-011 now proves that clamped navigation schedules no LOD work; the broader drill/stream/resource matrix and soak bounds are not. See TST-NI-034. |
| Wire framing | `tests/test_framing.py`; `tests/test_framing_property.py`; Python-to-JavaScript golden decoding | Hard root suite | `IMPLEMENTED` | Truncation, corrupt headers, padding, metadata, zero-copy, and valid round trips are substantive. A catalog-generated request matrix and property byte mutation remain missing. See TST-NI-028. |
| Widget/channel dispatch | `tests/test_channel.py`; `tests/test_widget.py`; `tests/test_html_transport.py` | Hard root suite | `IMPLEMENTED` | Valid/malformed dispatch, callbacks, payload splitting, and Python widget behavior are covered. A real notebook frontend mount is not. See TST-NI-018. |
| Governed branch and diff coverage | `scripts/coverage_ratchet.py`; `spec/testing/coverage-policy.json`; core, pyplot, and zero-skip adapter branch runs | Hard `python_coverage` job with retained raw/JSON/XML/ratchet evidence | `IMPLEMENTED` | Reviewed package and critical-module line/branch floors, exact shipped-file inventory, and a 90% changed-executable-line threshold fail closed. JavaScript retains its independent V8 report; Rust is explicitly not ratcheted before a pinned report. See TST-NI-029. |
| Mutation score | No mutation lane | None | `NOT IMPLEMENTED` | Oracle strength is inferred from tests and selected negative cases. See TST-NI-030. |

## Native Rust and JavaScript client

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Rust debug correctness | `cargo test` | Hard main CI / `make rust-check` | `IMPLEMENTED` | Includes deterministic randomized kernel and scalar/native parity cases. |
| Hard Rust release-test gate | `cargo test --locked --release`; release-test inventory requires `compose_window_astronomically_past_domain_is_empty_not_panic` | Hard `rust_release` job and `required_ci` dependency | `IMPLEMENTED` | The optimized suite cannot pass by silently compiling out the known release-only regression. See TST-NI-020. |
| Rust lint | `cargo clippy --all-targets -- -D warnings` | Hard main CI | `IMPLEMENTED` | Covers configured targets on the main Linux host. |
| Native C ABI | `scripts/abi_smoke.py` | Hard main CI / `make abi-smoke` | `IMPLEMENTED` | Loads the built core and checks the exported ABI surface. |
| SIMD and architecture parity | `xy_runtime_capabilities`; `scripts/native_parity.py`; fixed-seed Rust parity tests | Hard native Linux x64/ARM64, Windows x64, and macOS ARM64 matrix plus selected release-artifact runtimes | `IMPLEMENTED` | Default and forced-scalar subprocesses compare an exact kernel, invalid-pointer FFI, and framebuffer oracle; x64 requires AVX2 and ARM64 reports its baseline. See TST-NI-023. |
| Native sanitizers, Miri, and coverage-guided fuzzing | Deterministic randomized tests only | None | `NOT IMPLEMENTED` | There is no sanitizer, Miri, or cargo-fuzz lane. See TST-NI-021. |
| Native dependency audit | Point-in-time security review | None in regular automation | `NOT IMPLEMENTED` | No `cargo audit` or `cargo deny` policy is enforced. See TST-NI-022. |
| JavaScript build and syntax | `node js/build.mjs`; main-CI ESM import and IIFE parse checks; release rebuild | Hard main CI plus release build | `IMPLEMENTED` | Main CI proves parseability; release rebuilds the exact artifact after the freshness check. |
| JavaScript semantic units | `js/test/frame.test.mjs`; `js/test/semantics.test.mjs`; `js/test/worker.test.mjs`; `make js-test` | Hard Node 22 `javascript_semantics` job and `required_ci` dependency | `IMPLEMENTED` | The dependency-free suite exercises the exact fresh ESM bundle across frame decode, ticks/formatters, transforms/bounds, theme/style normalization, the 18-kind registry, LOD selection, ChartView state, and the standalone worker protocol. Malformed cases and real mutation controls fail closed; line/branch/function floors gate retained JUnit, coverage text, and raw V8 coverage. |
| Protocol-version implementation coherence | Python and JavaScript runtime constants currently agree | Indirect tests | `PARTIALLY IMPLEMENTED` | Some specification and smoke fixtures can drift; the animation smoke used protocol 3 while runtime uses 4. See TST-NI-046. |

## Rendering, interaction, and host integration

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| Dependency-light WebGL render | `scripts/render_smoke_nonumpy.py <chromium>` | Hard main CI | `IMPLEMENTED` | Exercises representative marks, interaction, context loss, and nonblank pixels without NumPy. It is not an every-kind registry. |
| Real Figure browser render | `scripts/smoke_render.py <chromium>` | Hard main CI | `IMPLEMENTED` | A composed Figure reaches nonblank Chromium pixels. |
| Native and browser export | PNG/JPEG/WebP/SVG/PDF unit tests; `scripts/png_export_smoke.py`; image and batch-export tests | Hard root/browser lanes, with optional external PDF tooling | `PARTIALLY IMPLEMENTED` | Broad byte/pixel validation exists. Public persistent browser batch reuse, mixed-format cleanup, and a guaranteed independent PDF oracle are incomplete. See TST-NI-045. |
| Standalone HTML and text security | `tests/test_static_client_security.py`; `scripts/runtime_security_smoke.py`; HTML transport/CSS and sandbox-policy tests; `make check-security`; `make check-browser` | Hard root and Chromium CI/browser lanes with retained runtime JSON | `IMPLEMENTED` | Static escaping/sink constraints and real-browser literal text across 16 public surfaces, hostile CSS, CSP blocking, zero executable user nodes/dialogs, and zero loopback requests are enforced (TST-NI-024). Browser launch never silently downgrades its process sandbox (the distinct TST-NI-025 policy). |
| FastAPI gallery lifecycle | `scripts/reflex_lifecycle_smoke.py` | Hard Chromium CI/browser lane | `IMPLEMENTED` | Exercises gallery routes, resize, visibility, context loss/restore, drilldown, and embedded iframes. The filename is misleading: it serves `examples/fastapi`, not Reflex. |
| Visual health | `scripts/visual_health_smoke.py` | Hard Chromium CI/browser lane | `IMPLEMENTED` | Honestly scoped broad-gallery protection for blank/collapsed output, occupancy, regions, and label overlap; it does not claim identity comparison. |
| Reviewed visual identity | `scripts/visual_baseline.py`; `spec/visual-baselines/v1.json` | Hard pinned-Chromium CI/browser lane with retained artifacts | `IMPLEMENTED` | Bounded TST-NI-014 evidence pins browser/font/viewport/DPR, compares semantics plus tolerant pixels, and rejects real data/color/label/geometry mutations. Baseline proposals require independent review. |
| Rendered labels and value formats | `js/tests/rendered_labels.test.mjs`; `tests/test_rendered_label_formats.py`; normative `spec/testing/rendered-label-policy.md` | Hard main-CI `test` job / `npm run test:labels` / `make check-labels`; retained JSON | `IMPLEMENTED` | Exact numeric, grouping, literal currency, percent, UTC time, log, category, named-axis, tooltip, and colorbar DOM labels run under two non-UTC locale/time-zone contexts; malformed raw formats and a corrupted DOM label are negative controls. TST-NI-008 is complete. |
| Step tier replacement | `scripts/step_tier_smoke.py` | Hard Chromium CI/browser lane | `IMPLEMENTED` | Protects step risers across a synthetic tier-buffer replacement. |
| Interaction stress | `scripts/interaction_stress_smoke.py`; `scripts/pan_zoom_matrix.mjs`; focused wheel/pan/zoom/pick tests | Hard Chromium CI/browser lane with retained worker and matrix JSON | `PARTIALLY IMPLEMENTED` | TST-NI-011, TST-NI-012, and TST-NI-016 jointly hard-gate the bounded action/axis/host matrix, core interaction budgets, pick boundaries, and standalone worker re-bin/paint/teardown; long-duration and compound-gesture stress remain outside this bounded evidence. See TST-NI-034. |
| Focused cross-browser conformance | `node scripts/browser_conformance.mjs`; focused `node scripts/pan_zoom_matrix.mjs --profile focused` in Chromium, Firefox, and WebKit | Hard CI / `make check-conformance` | `IMPLEMENTED` | The shared fixture checks direct-linear semantics, accessibility, layout, and tolerant raster equality; the focused pan/zoom subset additionally drives linear drag, log wheel/linking, and reversed box zoom with reduced motion in all three engines. Broader kinds, tiers, DPRs, and axes are not covered. See TST-NI-015. |
| Browser version support policy | Playwright-pinned current Chromium, Firefox, and WebKit | Hard CI for the pinned versions only | `NOT IMPLEMENTED` | No normative engine/version floor, WebGL2 prerequisite statement, or oldest-claimed-version lane exists, and recorded renderer versions can drift from the docs. See TST-NI-054. |
| GPU and driver realism | Headless CI lanes running software rendering | Hard Chromium CI on software rasterization | `NOT IMPLEMENTED` | No lane exercises representative hardware WebGL2 drivers or rejects software fallback, so driver-specific defects are invisible. See TST-NI-052. |
| Renderer failure-mode behavior | Successful context loss/restore paths plus source-marker assertions | Mixed | `PARTIALLY IMPLEMENTED` | Restoration is proved in a real browser, but WebGL2 acquisition, shader/program, and permanent-restore failures are not forced and their user-visible contract is unasserted. See TST-NI-053. |
| Chart-kind render contract | `scripts/chart_kind_matrix.py`; `tests/test_chart_kind_matrix.py` | Hard Chromium CI/browser lane with retained JSON | `IMPLEMENTED` | Sixteen public-builder fixtures exactly cover all 18 shipped registry kinds with payload tier/count, live GPU geometry, and independently measured nonblank pixels. Adding a registry kind without a fixture fails (TST-NI-009); cross-renderer parity remains TST-NI-010. |
| Axes, layout, styling, chrome, and facets | Axis/viewport, facets, CSS mark styles, export, legend-resize, rendered-label oracle, pan/zoom matrix, and gallery browser tests | Mixed hard evidence | `PARTIALLY IMPLEMENTED` | Formatter semantics and linear/log/reversed/category/dual/named-axis pan/zoom are hard-gated; the broader collision, renderer-parity, and general axis-catalog contracts remain open. See TST-NI-010 and TST-NI-014. |
| Pan/zoom contract | `scripts/pan_zoom_matrix.mjs`; `tests/test_pan_zoom_matrix.py`; workflow negative controls | Hard full Chromium, focused Chromium/Firefox/WebKit, and Reflex floor/latest CI with retained JSON; `make check-pan-zoom` | `IMPLEMENTED` | Five bounded standalone cases drive drag, wheel, box, toolbar zoom, and reset over linear/log/reversed/category/dual/named axes; assert bounds, default/finite/partial limits, actual changed axes, exact nonparticipants, link/no-echo, reduced motion, clamped no-op event/LOD silence, and semantic/layout health. Two real-host cases prove JSON-safe live Reflex view/LOD transport and kernel-less static Reflex navigation. |
| Animation Python contract | `tests/test_animation.py`; Python-only CodSpeed microbenchmarks | Hard root suite / advisory CodSpeed | `IMPLEMENTED` | Validation, payload, and deterministic static behavior have evidence. |
| Required animation browser gate | `scripts/animation_smoke.py`; `tests/test_animation_smoke.py` | Hard Chromium CI/browser lane with retained JSON evidence | `IMPLEMENTED` | Protocol-derived fixtures prove keyed/fallback interpolation, representative marks, ghost-free pixels, allocation, replacement, lifecycle, reduced motion, frozen capture, and teardown. TST-NI-013 records the completed gate; real-browser performance measurement remains TST-NI-048. |
| Dashboard context governance | `benchmarks/bench_dashboard.py` at 10/20/50 plus strict outcome validation and mutation negatives in `tests/test_verify_benchmark_report.py` | Hard CI selects `--profile strict` and retains `dashboard-health-evidence`; timing reports remain advisory | `IMPLEMENTED` | Every requested row must be complete or governed, create and visit-paint every chart, and contain no unexplained context loss. See TST-NI-002. |
| Accessibility | Source contracts plus the focused three-engine semantic fixture | Mixed hard evidence | `PARTIALLY IMPLEMENTED` | Roles and selected keyboard/live behavior have evidence, but there is no normative rendered matrix for direct/aggregate charts, focus, forced colors, or a table alternative. See TST-NI-017 and TST-NI-039. |
| Anywidget/Jupyter | Python widget and transport tests | Hard root suite | `PARTIALLY IMPLEMENTED` | No supported notebook frontend mounts the shipped widget and drives bidirectional behavior. See TST-NI-018 and TST-NI-019. |
| Reflex adapter | `python/reflex-xy/tests/`; `scripts/reflex_ws_smoke.py` | Hard dedicated Reflex floor/latest job with zero skips and retained logs/screenshots | `IMPLEMENTED` | Package-owned dependencies make missing test requirements fail collection; the production example proves one shared socket, binary paint, drill/hover state, streaming, renderer teardown, and host transport close. This supplies TST-NI-004; the broader cross-host matrix remains TST-NI-019. |
| FastAPI and host versions | Example tests and the gallery browser app | Mixed | `PARTIALLY IMPLEMENTED` | Supported host floors/latest versions are not exercised as a declared matrix. See TST-NI-019. |

## Matplotlib compatibility and documentation application

| Surface | Current executable evidence | Enforcement | Status | Current boundary / gap |
|---|---|---|---|---|
| `xy.pyplot` API and state | `tests/pyplot/`; compatibility snapshot; public annotations and state/artist/options tests | Hard dedicated Matplotlib 3.11 and root suites | `IMPLEMENTED` | The declared compatibility inventory and broad behavioral corpus are substantial. |
| Matplotlib semantic/perceptual parity | Pinned reference subsets and a 54-case corpus | Hard dedicated lane | `PARTIALLY IMPLEMENTED` | The tolerant corpus can accept wrong or empty data for some cases; contour, vector magnitude, transforms, and tick semantics need stronger independent oracles. See TST-NI-026. |
| Pyplot accepted-option use | `scripts/check_pyplot_options.py`; `spec/testing/pyplot-noops.json`; behavioral no-op contracts and detector mutation tests | Hard root CI with retained JSON | `IMPLEMENTED` | Unread named options and discarded literal option pops fail unless the exact function/option is reviewed with a substantive rationale and executable invariant test. TST-NI-027 records the completed gate. |
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
| CI wheel runtime | Linux x86, Linux ARM64, and Windows x64 build/install/native import jobs; common native parity matrix also covers macOS ARM64 | Hard CI | `IMPLEMENTED` | The focused native contract runs on all four host classes; broader installed-wheel public behavior remains separate. See TST-NI-023 and TST-NI-049. |
| Release wheel matrix | Eleven native platform wheels with structural verification; selected host-native imports; x64 manylinux 2.17 and musllinux 1.2 run the common native parity oracle in pinned containers | Release workflow | `PARTIALLY IMPLEMENTED` | Selected glibc/musl artifacts execute before publish, while the remaining cross-built artifacts are structurally checked. Broader artifact behavior is tracked by TST-NI-049. |
| Pyodide artifact | Pinned Rust/Emscripten/Pyodide build and runtime load probe | Release workflow | `IMPLEMENTED` | This status applies only to the exact release job; no regular PR/scheduled regression lane builds and runs the WASM artifact. See TST-NI-041. |
| Supported Python matrix | Explicit Python 3.11 plus the main runner's incidental Python | Hard CI | `PARTIALLY IMPLEMENTED` | The project declares Python 3.11+ without explicitly testing every currently claimed version or newest supported interpreter. See TST-NI-036. |
| Cross-platform behavioral parity | Focused kernel/FFI/raster parity runs on native Linux x64/ARM64, Windows x64, and macOS ARM64; wheel jobs install/import selected hosts | Hard CI for the focused native contract | `NOT IMPLEMENTED` | Public Python, framing, and export behavior still run primarily on Ubuntu; the focused native parity closure does not substitute for the broader matrix. See TST-NI-049. |
| Dependency reproducibility | Benchmark lock and docs lock; floating root `.[dev]` hard job | Mixed | `PARTIALLY IMPLEMENTED` | The hard root gate is not frozen; there is no separate latest-dependency canary or true minimum-dependency lane. See TST-NI-036. |
| Required merge gate | `required_ci` evaluates the complete hard-job result map with negative controls for failure, cancellation, skip, omission, and accidental advisory inclusion | Stable all-path result exists; repository ruleset does not yet require it | `PARTIALLY IMPLEMENTED` | The aggregate is executable, but `main` is not protected until the repository ruleset requires `Required CI`. See TST-NI-001. |
| Exact-SHA release qualification | `scripts/verify_source_qualification.py`; exact-tag/main ancestry; newest exact-SHA `Required CI`; package tag/version/dated-changelog agreement | Unconditional release `qualify` dependency before every build or publish job | `IMPLEMENTED` | A dry run may defer nonexistent tag metadata because it cannot publish; a tag push or manual real publication cannot bypass it. See TST-NI-003. |
| Exact-SHA deployment qualification | The same source qualifier in dev and stage/production; exact deploy-tag check for tagged promotion | Required `qualify` dependency before docs image builds | `IMPLEMENTED` | Dev is intentionally SHA-addressed rather than tagged; tagged stage/production promotion verifies the CalVer tag and reuses the qualified SHA. See TST-NI-003. |
| Release provenance | `scripts/release_provenance.py`; exact-set SHA-256 manifest; BuildKit max-provenance image builds; ECR digest comparison and `tag@sha256` Helm pins | Required release `provenance` job plus staging/production digest gates | `IMPLEMENTED` | Package publishers verify the complete downloaded artifact set; docs promotion reuses the same image digests. This is artifact provenance, not a general dependency SBOM. See TST-NI-003. |
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
| `make check-browser CHROMIUM=...` | Configured Chromium smokes including runtime page-content security, animation, and pick-boundary but except dashboard; does not include Reflex or cross-engine conformance |
| `make check-labels` | Strict authored-source formatter units plus shipped-bundle DOM labels in two locale/time-zone contexts |
| `make check-pan-zoom CHROMIUM=...` | Complete five-case standalone pan/zoom matrix in the configured Chromium; writes validated JSON evidence under `/tmp` |
| `make check-conformance` | Focused accessibility/raster fixture plus the drag/wheel/box pan/zoom subset in Chromium, Firefox, and WebKit |
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
| `make check-coverage` | Validate a branch-aware report against reviewed package/module floors and the configured Git diff |
| `make check-pyplot` | Structured accepted-option audit plus the full `tests/pyplot` suite in the active environment |
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
| `make js-test` | Dependency-free JavaScript semantic units with coverage floors |
| `make rust-check` | Rust debug tests and clippy |
| `make abi-smoke` | Direct C ABI smoke |

The target replacement for the ambiguous `make check-full` contract is tracked
as TST-NI-037.

## Test suite and executable-helper registry

This registry makes dormant or optional evidence visible. `Wired` describes
automation, not whether the helper is valuable.

| Suite or helper | Scope | Wiring / status |
|---|---|---|
| Repository `pytest -q` | Root tests plus recursively collected pyplot tests | Hard main/Python-floor jobs; `PARTIALLY IMPLEMENTED` because optional dependencies can skip |
| `tests/pyplot/` | Matplotlib API/state/artist/options/corpus/reference behavior | Root collection plus dedicated hard Matplotlib reference job; `IMPLEMENTED` for its documented scope |
| `python/reflex-xy/tests/` | Adapter assets, components, vars, socket plane, state bridge, and tokens | Package-owned dev environment plus zero-skip Reflex floor/latest job; `IMPLEMENTED` |
| `docs/app/tests` | Documentation application unit/route/content behavior | Docs quality job; `IMPLEMENTED` |
| `benchmarks/test_codspeed_*.py` | Kernel, transport, pyplot, and Python animation microbenchmarks | Advisory CodSpeed job; `IMPLEMENTED` |
| Rust tests in `src/` | Native kernels, encoding, raster, tiles, SIMD, module invariants, and a release-only extreme-window regression | Debug and locked release-profile hard CI |
| `js/test/*.test.mjs` | Exact-bundle frame, tick/formatter, transform/bounds, theme/style, mark-registry, LOD, ChartView-state, worker-protocol, malformed-input, and mutation-control semantics | Hard Node 22 `javascript_semantics` job with retained JUnit and coverage; `IMPLEMENTED` for TST-NI-007 |
| `scripts/coverage_ratchet.py` | Exact shipped-file inventory, reviewed core/pyplot/adapter line and branch floors, critical modules, and 90% changed executable lines | Hard `python_coverage` job with retained raw/JSON/XML/ratchet evidence; `IMPLEMENTED` for TST-NI-029 |
| `scripts/abi_smoke.py` | Exported native C ABI | Hard main CI |
| `scripts/render_smoke_nonumpy.py` | Dependency-light WebGL marks, pixels, interaction, and context recovery | Hard Chromium CI |
| `scripts/png_export_smoke.py` | Native and Chromium PNG health | Hard Chromium CI |
| `scripts/smoke_render.py` | Real composed Figure to Chromium pixels | Hard Chromium CI |
| `scripts/runtime_security_smoke.py` | Production standalone DOM-XSS, CSP, hostile-CSS, dialog, and wire-level network-isolation behavior | Hard Chromium CI/browser lane with retained JSON evidence; `IMPLEMENTED` for TST-NI-024 |
| `scripts/reflex_lifecycle_smoke.py` | FastAPI gallery lifecycle, drilldown, resize, visibility, context recovery, and iframes | Hard Chromium CI; misleading historical filename |
| `scripts/visual_health_smoke.py` | Broad gallery visual-health invariants | Hard Chromium CI |
| `scripts/visual_baseline.py` | Reviewed semantic/perceptual identity plus real negative controls | Hard pinned-Chromium CI; expected/actual/diff artifacts retained |
| `scripts/step_tier_smoke.py` | Step geometry after tier-buffer replacement | Hard Chromium CI |
| `scripts/interaction_stress_smoke.py` | Wheel/pan/hover/crosshair/box/brush behavior, budgets, and standalone density worker re-bin/paint/teardown | Hard Chromium CI with retained JSON; worker skips are blocking; `IMPLEMENTED` for TST-NI-016 |
| `scripts/pan_zoom_matrix.mjs` / `tests/test_pan_zoom_matrix.py` | Catalog-validated action/axis/host matrix; semantic/layout, link, bounds/limits, no-op LOD/event, cross-engine, and live/static Reflex assertions | Hard full Chromium, focused three-engine, and Reflex floor/latest CI with failure-retaining JSON; `IMPLEMENTED` for TST-NI-011 |
| `scripts/browser_conformance.mjs` | Focused semantic/accessibility/layout/raster comparison | Hard Chromium/Firefox/WebKit CI |
| `js/tests/rendered_labels.test.mjs` | Formatter units plus exact rendered numeric/time/category/named-axis/tooltip/colorbar DOM labels and independent negatives | Hard Chromium main CI with retained JSON; `IMPLEMENTED` for TST-NI-008 |
| `scripts/pick_boundary_smoke.py` | Large trace/index picking limits | Hard Chromium CI/browser lane with retained JSON evidence; `IMPLEMENTED` |
| `scripts/animation_smoke.py` | Real-browser animation lifecycle/pixels/allocation | Hard Chromium CI/browser lane with retained JSON evidence; `IMPLEMENTED` |
| `scripts/reflex_ws_smoke.py` | Real Reflex websocket/browser path: shared socket, binary paint, drill/pick state, streaming, renderer teardown, and transport close | Hard dedicated Reflex floor/latest CI with retained log/screenshot evidence; `IMPLEMENTED` for TST-NI-004 |
| `scripts/pyodide_load_smoke.py` | Built WASM wheel runtime load | Release-only exact-artifact evidence |
| `scripts/native_parity.py` | Scalar/AVX2/aarch64 capability plus exact kernel/FFI/raster parity | Hard native host matrix and selected manylinux/musllinux artifact runtimes; `IMPLEMENTED` |
| `scripts/verify_released_docs_quickstart.py` | Public quickstarts against the published wheel | Docs released-quickstart job |
| `scripts/check_release_version.py` and its tests | Tag, project version, and changelog coherence | Reused by exact-SHA release qualification for tag and manual real publication |
| `scripts/verify_source_qualification.py` and its tests | Exact commit, `main` ancestry, exact tag, newest exact-SHA `Required CI`, and release metadata | Required release/dev/stage-production preflight; `IMPLEMENTED` |
| `scripts/release_provenance.py` and its tests | Exact artifact-set names, sizes, SHA-256 hashes, source SHA, and duplicate-record rejection | Required before package publication; `IMPLEMENTED` |
| `scripts/verify_sdist.py` / `scripts/verify_wheel.py` and tests | Package contents, metadata, tags, hashes, and native/pure expectations | Hard CI/release structural gates |
| `scripts/verify_benchmark_report.py`, merge/regression scripts, and tests | Benchmark schema, coherence, merge, and deterministic regression policy | Hard harness tests; outcome-integrity mode `NOT IMPLEMENTED` |
| `scripts/verify_local.py` and tests | Named local-suite composition and execution | Current local command router; release-equivalent aggregation `NOT IMPLEMENTED` |
| `scripts/check_testing_spec.py` and its tests | Whole-spec links, anchors, commands, repository paths/symbols/jobs, evidence rows, status vocabulary, and stable gap-ID integrity | Hard all-path suite via `make check-testing-spec` and `make check-docs`; `IMPLEMENTED` |
| Hatch build-hook tests | Native build/no-toolchain build behavior | Repository pytest and packaging jobs |

## Workflow and job registry

| Workflow | Current jobs | Testing role |
|---|---|---|
| `ci.yml` | `rust_release`, `native_parity`, `javascript_semantics`, `matplotlib_reference`, `test`, `reflex_adapter`, `browser_conformance`, `python_floor`, `benchmark_vs`, `benchmark_methodology`, `benchmark`, `sdist`, `wheels`, `install_without_rust`, `required_ci` | Main hard and advisory code/package evidence; stable hard aggregate includes optimized Rust, four-host native parity, dependency-free JavaScript semantics, full Chromium plus focused three-engine pan/zoom, and live/static Reflex floor/latest evidence on every pull-request path |
| `codspeed.yml` | `benchmarks` | Advisory microbenchmark evidence |
| `docs.yml` | `released-quickstart`, `quality`, `production` | Published-wheel quickstart, docs tests/lint, and production-route matrix |
| `benchmark-refresh.yml` | `cross-library` | Manual scatter and core-2D refresh evidence |
| `release.yml` | `qualify`, `wheels`, `wasm`, `sdist`, `provenance`, `publish`, `publish-pyodide` | Exact-source qualification, artifact build/verification/provenance, and publication |
| `_build-docs-images.yml` | `build-and-push` | Reusable provenance-attested docs-image build with immutable digest outputs |
| `_helm-docs-pr.yml` | `open-helm-pr` | Reusable deployment PR automation that validates and pins tag-at-digest image references |
| `deploy-docs-dev.yml` | `prepare`, `qualify`, `build`, `helm-pr`, `update-last-sha` | Development deployment waits for exact-SHA hard CI and promotes built digests |
| `deploy-docs-stg.yml` | `prepare`, `qualify`, `build`, `helm-pr-stg`, `await-prod-approval`, `verify-prod-artifacts`, `release`, `helm-pr-prod` | Stage/production promotion qualifies the tag and verifies the same digests after approval |
| GitHub default CodeQL | Dynamic Actions, JavaScript/TypeScript, Python, and Rust analyses | Implemented code scanning; not a required merge check or dependency audit |
