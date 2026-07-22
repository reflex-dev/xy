# Testing Gap Register

This is the stable, prioritized implementation register for XY testing and
enforcement. IDs are never removed or renumbered when work closes. Incomplete
entries are `NOT IMPLEMENTED`; an entry becomes `IMPLEMENTED` only after all of
its completion criteria are automated, explicit evidence is recorded here, and
[`current.md`](current.md) is updated. Supporting scripts alone do not qualify.

Priority means:

- P0: required before a green check can be treated as a release certificate;
- P1: material product, platform, oracle, or integration coverage; and
- P2: reliability, maintainability, observability, and longer-horizon depth.

Implementation pull requests should add an owner or issue, exact environment,
independent oracle and negative control, command/job, gate tier, skip policy,
and retained artifact to the relevant entry before changing its status.

## P0 — Release confidence

### TST-NI-001 — Required hard-CI aggregate and repository rule

- Status: `NOT IMPLEMENTED`
- Owner: unassigned — file a tracking issue before implementation starts
- Current gap: `required_ci` now evaluates every declared hard dependency on
  every pull-request path and rejects failed, cancelled, skipped, missing, or
  unexpected jobs. `main` still has no rule requiring the stable `Required CI`
  result, so the protection can be bypassed until the repository ruleset is
  updated.
- Implemented when: one `required-ci` job uses `if: always()`, runs on every pull
  request path, fails for failed/cancelled/unexpectedly skipped hard jobs, excludes
  advisory timing, and is required by the repository ruleset.

### TST-NI-002 — Strict dashboard 10/20/50 health gate

- Status: `IMPLEMENTED`
- Owner: unassigned — file a tracking issue before implementation starts
- Evidence: `benchmarks/bench_dashboard.py`, `scripts/verify_benchmark_report.py`, `tests/test_verify_benchmark_report.py`, and the hard-CI `test` job's `dashboard-health-evidence` artifact.
- Current gap: closed; hard CI selects the strict profile, and the context
  governor now completes the 10/20/50 visit matrix without unexplained loss.
- Implemented when: a strict profile requires one healthy row for every requested
  count; governed charts must all be created and nonblank when visited; missing,
  failed, partial, or unexplained-loss rows exit nonzero; mutation tests prove
  rejection; and hard CI explicitly selects that profile.

### TST-NI-003 — Exact-SHA release, deployment, and provenance preflight

- Status: `NOT IMPLEMENTED`
- Owner: unassigned — file a tracking issue before implementation starts
- Current gap: publication and deployment do not prove that their exact source
  SHA passed the hard suite; manual production publication can bypass the
  push-only version gate, and dev deployment can race CI.
- Implemented when: every publish or promotion path verifies tag/version/
  changelog, tag SHA, `main` ancestry, exact-SHA hard-test success, and artifact
  hashes/provenance; manual dispatch cannot bypass it; dev/stage/production wait
  for it; and the same immutable artifacts are promoted.

### TST-NI-004 — Required Reflex adapter and browser E2E lane

- Status: `NOT IMPLEMENTED`
- Owner: unassigned — file a tracking issue before implementation starts
- Current gap: root CI does not install `reflex` or `reflex_xy`, so one collection
  skip hides the adapter suite; the real `reflex_ws_smoke.py` is unwired.
- Implemented when: a dedicated job installs root XY and
  `python/reflex-xy[dev]`, allows zero dependency skips, runs all adapter cases,
  compiles/starts the real example, and proves socket, binary paint, drill,
  state, streaming, and teardown behavior at the supported Reflex floor/latest.

### TST-NI-005 — Specification and testing-catalog validation

- Status: `IMPLEMENTED`
- Owner: unassigned — file a tracking issue before implementation starts
- Evidence: `scripts/check_testing_spec.py::main`, `tests/test_check_testing_spec.py`, `scripts/check_claim_guardrails.py`, `make check-testing-spec`, and the all-path `required_ci` job.
- Current gap: closed; the whole specification tree and its public claims are
  checked, and specification-only pull requests receive the stable hard result.
- Implemented when: spec-only pull requests receive the stable required result
  and validation extends across `spec/` — Markdown links, commands, referenced
  files/symbols/jobs, status vocabulary, evidence rows, claim guardrails, and
  dead or duplicate gap IDs.

## P1 — Product and integration coverage

### TST-NI-006 — All-public-builder property and transaction matrix

- Status: `NOT IMPLEMENTED`
- Current gap: property tests cover six of 20 public Figure builders and do not
  prove seeded rollback for every late failure.
- Implemented when: all builders have valid strategies that must succeed,
  classified invalid strategies, injected late failures on nonempty state, and
  exact pre/post snapshots of traces, columns/dedup keys, axes/categories,
  annotations, caches, pyramids, and drill state.

### TST-NI-007 — First-class JavaScript semantic unit suite

- Status: `NOT IMPLEMENTED`
- Current gap: JavaScript has build/parse and browser evidence but no unit test
  command.
- Implemented when: a pinned `node --test` or equivalent hard lane covers frame
  decode, ticks/formatters, transforms/bounds, theme/style normalization, mark
  registry, LOD choice, ChartView state, and worker protocol with malformed
  cases, negative controls, and coverage output.

### TST-NI-008 — Rendered-label and formatter oracle

- Status: `NOT IMPLEMENTED`
- Current gap: several tests assert serialized specs or source markers rather
  than labels a user sees; unsupported formatting can silently fall back.
- Implemented when: policy explicitly supports or rejects each format and unit/
  DOM tests assert numeric, grouping, currency-or-error, percent, time, log,
  category, named-axis, tooltip, and colorbar labels under at least two locales
  and non-UTC host time zones, with UTC output invariant and a broken-formatter
  negative control.

### TST-NI-009 — Registry-driven every-chart-kind render matrix

- Status: `NOT IMPLEMENTED`
- Current gap: the chart-kind contract requires a render probe per kind, while
  the core smoke covers only common families.
- Implemented when: a fixture catalog keyed to the public mark registry requires
  payload/tier and nonblank semantic geometry/pixel evidence for every primitive,
  including error, step/stem/segment, box/violin, contour/hexbin, and triangle
  mesh families; adding a kind without evidence fails.

### TST-NI-010 — Cross-renderer semantic parity catalog

- Status: `NOT IMPLEMENTED`
- Current gap: strong spot checks do not guarantee equivalent geometry/style
  across WebGL, SVG, native raster, and PDF for every claimed feature.
- Implemented when: each mark/feature declares applicable renderers and an
  independent coordinate/count/label oracle; exact buffers match where identity
  is claimed, pixels use reviewed tolerances, and each primitive has a negative
  control.

### TST-NI-011 — Pan/zoom acceptance matrix

- Status: `NOT IMPLEMENTED`
- Current gap: focused linear-scatter evidence does not implement the specified
  action matrix across axis classes and hosts.
- Implemented when: data-driven browser cases cover drag, wheel, box, toolbar
  zoom, and reset across linear/log/reversed/category/dual/named axes, bounds,
  limits, linking, reduced motion, no-op event/LOD semantics, and live/static
  Reflex, with Chromium hard and a focused three-engine subset.

### TST-NI-012 — Pick-boundary browser gate

- Status: `NOT IMPLEMENTED`
- Current gap: `scripts/pick_boundary_smoke.py` exists but is absent from CI,
  Makefile, local verification, and the release contract.
- Implemented when: it is a named hard check for 256 trace slots including 255,
  large indices, global/local mapping, and pick-cache reuse/invalidation, with
  catalog wiring and retained failure evidence.

### TST-NI-013 — Animation browser gate

- Status: `NOT IMPLEMENTED`
- Current gap: `scripts/animation_smoke.py` is documented but unwired and used a
  stale hard-coded renderer protocol.
- Implemented when: fixtures derive the shared protocol, the smoke runs in local
  browser checks and hard CI, and it asserts keyed interpolation, fallback,
  ghost-free pixels, allocation bounds, replacement, balanced lifecycle,
  representative marks, reduced motion, and frozen export. Browser startup
  failure must fail rather than skip.

### TST-NI-014 — Reviewed visual regression baselines

- Status: `NOT IMPLEMENTED`
- Current gap: the current visual smoke detects health/occupancy failures but
  does not compare visual identity.
- Implemented when: the health smoke is retained and honestly named, while a
  small versioned baseline set uses pinned browser/font/viewport/DPR, semantic
  plus perceptual diff, explicit tolerances, corrupted-data/color/label/geometry
  negative controls, reviewed update policy, and expected/actual/diff artifacts.

### TST-NI-015 — Broader cross-browser, DPR, and motion conformance

- Status: `NOT IMPLEMENTED`
- Current gap: the hard three-engine fixture is one direct linear scatter at a
  narrow configuration.
- Implemented when: a bounded matrix spans direct/decimated/density and
  representative line/bar/heatmap/mesh, DPR 1/2, reduced/no-preference motion,
  and linear/log/category/named axes in Chromium, Firefox, and WebKit, while
  preserving semantic/layout checks and tolerant pixel comparison.

### TST-NI-016 — Required standalone-worker evidence

- Status: `NOT IMPLEMENTED`
- Current gap: the configured interaction smoke can report its worker probe as
  skipped.
- Implemented when: required CI proves worker creation, message/re-bin result,
  nonblank paint, and teardown; unavailable/skipped/failed is blocking in that
  environment, while explicitly optional local use may skip.

### TST-NI-017 — Normative accessibility behavior matrix

- Status: `NOT IMPLEMENTED`
- Current gap: source assertions and one scatter fixture do not define the full
  accessibility contract.
- Implemented when: a normative API spec covers roles/names, summaries/live
  regions, focus order, keyboard behavior, aggregate-bin semantics, toolbar
  state, reduced motion, forced colors, and table-alternative policy; browser
  tests inspect DOM/accessibility behavior for direct and aggregate charts and
  explicitly state the supported engine/OS/assistive-technology scope.

### TST-NI-018 — Real anywidget/Jupyter frontend E2E

- Status: `NOT IMPLEMENTED`
- Current gap: Python widget behavior is tested, but no supported notebook
  frontend mounts the shipped ESM widget.
- Implemented when: a pinned frontend/anywidget environment mounts the widget,
  receives split binary buffers, paints, sends pick/view/select, applies append/
  tier updates, and unmounts without listener, worker, GL, or socket leaks.

### TST-NI-019 — Host-integration version matrix

- Status: `NOT IMPLEMENTED`
- Current gap: supported anywidget, Reflex, FastAPI/Starlette, and related host
  floors/latest versions are not a declared executable matrix.
- Implemented when: the supported ranges are documented and focused compile,
  mount, transport, and browser tests run at floor/latest versions with zero
  hidden dependency skips.

### TST-NI-020 — Rust release tests

- Status: `NOT IMPLEMENTED`
- Current gap: main CI runs debug `cargo test`; at least one regression is
  compiled only without debug assertions.
- Implemented when: `cargo test --locked --release` is a hard job, workflow
  validation requires it, and release-only test coverage cannot silently drop.

### TST-NI-021 — Native fuzzing, sanitizers, and Miri

- Status: `NOT IMPLEMENTED`
- Current gap: fixed-seed randomized loops are useful regressions, not
  coverage-guided fuzzing; unsafe FFI and raster/parser boundaries lack dynamic
  hardening lanes.
- Implemented when: committed cargo-fuzz targets/corpora cover pointer/length and
  command-buffer inputs, scheduled ASan/UBSan/Miri-compatible jobs run with
  bounded budgets, and crashes/reproducers are retained. Deterministic randomized
  tests remain in the normal suite and are named accurately.

### TST-NI-022 — Multi-ecosystem dependency vulnerability policy

- Status: `NOT IMPLEMENTED`
- Current gap: CodeQL and a dated audit do not continuously audit the actual
  root, docs, adapter, Rust, and JavaScript dependency environments.
- Implemented when: supported scanners audit the relevant Python locks/
  environments, `Cargo.lock`, and `package-lock.json`; reviewed severities fail;
  scanner/database timestamps and machine-readable findings are retained; and
  exceptions have owners, reasons, and expirations.

### TST-NI-023 — SIMD and native artifact runtime parity

- Status: `NOT IMPLEMENTED`
- Current gap: AVX2 can be absent without explicit capability evidence and many
  ARM/Windows/macOS/cross-built artifacts receive import or structural smoke only.
- Implemented when: scalar/AVX2/aarch64 capability is reported and exercised;
  focused kernel/FFI/raster parity runs on native Linux x64/ARM64, Windows x64,
  and macOS ARM64; and selected manylinux/musllinux release artifacts run under
  appropriate native or emulated environments.

### TST-NI-024 — Runtime DOM-XSS, CSP, and network-isolation tests

- Status: `NOT IMPLEMENTED`
- Current gap: text-boundary security is strong, but much of the client sink
  contract is source-based rather than observed in a browser.
- Implemented when: hostile strings flow through every public text surface;
  tests assert literal text, no executable nodes/dialogs, and no network request
  under standalone CSP; hostile CSS is exercised; and fixed internal icon sinks
  are structurally allowlisted.

### TST-NI-025 — Observable or opt-in Chromium sandbox downgrade

- Status: `NOT IMPLEMENTED`
- Current gap: public export can retry unsandboxed after a sandboxed launch
  failure without a product-level policy assertion.
- Implemented when: policy chooses explicit opt-in or an observable warning,
  launch-failure tests assert exact arguments and diagnostics, no silent downgrade
  occurs, and trusted CI requests `sandbox=False` explicitly when necessary.

### TST-NI-026 — Stronger Matplotlib semantic and perceptual oracles

- Status: `NOT IMPLEMENTED`
- Current gap: the broad corpus can accept incorrect or empty data in some
  cases, and contour/vector/transform/tick semantics have known weak spots.
- Implemented when: high-risk scripts gain independent contour geometry/levels,
  quiver magnitude/direction, transform, tick, category, and axis-content
  comparisons plus reviewed perceptual fixtures and wrong-data negative controls.

### TST-NI-027 — Sound pyplot unused-option detector

- Status: `NOT IMPLEMENTED`
- Current gap: the current scan can miss named-but-never-read or assigned-unused
  options, while compatibility no-ops are free text.
- Implemented when: AST/dataflow or runtime instrumentation proves each supported
  option affects state/geometry or maps to a structured, reviewed no-op with a
  rationale and test; adding an accepted unused option fails.

### TST-NI-028 — Catalog-driven protocol conformance and byte mutation

- Status: `NOT IMPLEMENTED`
- Current gap: framing tests are strong, but request coverage is handwritten and
  the property suite focuses on valid round trips.
- Implemented when: one protocol catalog generates valid, missing, wrong-type,
  bounds, and callback cases for every request/reply; shared golden frames run in
  Python and JavaScript; and property mutations of headers, lengths, counts,
  padding, and metadata always reject safely or preserve parity.

### TST-NI-029 — Branch and diff-coverage ratchet

- Status: `NOT IMPLEMENTED`
- Current gap: branch coverage can be measured locally but is neither published
  nor governed across core, pyplot, adapter, and browser-script environments.
- Implemented when: branch-aware artifacts are uploaded, reviewed package/module
  baselines cannot regress, executable changed lines meet a concrete threshold,
  and exclusions are explicit. Rust/JavaScript reports precede ratchets for those
  languages.

### TST-NI-030 — Targeted mutation testing

- Status: `NOT IMPLEMENTED`
- Current gap: there is no mutation score or survivor review for high-risk
  validators, protocols, or report verifiers.
- Implemented when: scheduled or changed-path mutation lanes cover Python
  validators/protocol/report policy, JavaScript frame/format/bounds logic, and
  safe Rust kernel/raster parsers; a baseline and justified survivors are
  recorded; and seeded known mutants prove the lane detects weak oracles.

## P2 — Test-system reliability and depth

### TST-NI-031 — Strict marker, skip, and xfail policy

- Status: `NOT IMPLEMENTED`
- Current gap: a single dependency skip can hide a suite and configured browser
  failures can become skips without an enforced per-job budget.
- Implemented when: registered markers describe all layers; each job declares its
  selection and allowed skips; skip reasons/budgets are enforced; required
  dependency/browser skips fail; and strict xfails carry an issue and expiry.

### TST-NI-032 — Classified retry and flake provenance

- Status: `NOT IMPLEMENTED`
- Current gap: browser helpers retry broad failures and do not retain complete
  attempt history.
- Implemented when: only enumerated launch/GPU infrastructure failures retry,
  semantic assertions never retry, every attempt/status/duration is retained in
  JSON/JUnit and job summaries, and flaky-pass thresholds require quarantine or
  repair with an issue.

### TST-NI-033 — Event-driven asynchronous adapter tests

- Status: `NOT IMPLEMENTED`
- Current gap: several adapter/socket assertions depend on fixed sleeps.
- Implemented when: positive paths use events, queues, acknowledgements, and
  bounded waits; unsubscribe is acknowledged before a documented no-delivery
  window; and arbitrary sleep is not load-bearing.

### TST-NI-034 — Resource-leak and soak evidence

- Status: `NOT IMPLEMENTED`
- Current gap: lifecycle smokes check successful teardown but do not quantify
  repeated listener/context/worker/socket/temp-file/FD/heap growth.
- Implemented when: short hard loops and longer scheduled soaks repeatedly create,
  update, and destroy ChartView, worker, GL context, adapter subscription,
  streaming, and persistent browser export resources with published bounds.

### TST-NI-035 — Failure evidence artifacts

- Status: `NOT IMPLEMENTED`
- Current gap: benchmarks and packages retain artifacts, but hard tests do not
  consistently retain JUnit, coverage, browser screenshots, console output,
  traces, or retry history.
- Implemented when: every hard job emits a structured result; browser failures
  upload expected/actual/diff images plus console/page/CDP evidence; coverage,
  skip, and retry summaries are visible; and uploads use `if: always()`.

### TST-NI-036 — Reproducible hard environment and support matrix

- Status: `NOT IMPLEMENTED`
- Current gap: root hard CI floats `.[dev]` and tool versions, Python versions are
  partly incidental, and the floor lane omits relevant optional test dependencies.
- Implemented when: the hard baseline uses a frozen lock and pinned uv/Python/
  Node/Rust/browser versions; full floor and newest claimed Python lanes plus
  focused middle versions run; a genuine minimum-dependency lane exists; and a
  separate latest-dependency canary exposes ecosystem drift.

### TST-NI-037 — Honest local and release suite aggregation

- Status: `NOT IMPLEMENTED`
- Current gap: `make check-full` excludes browser conformance, dashboard,
  packaging, animation, pick-boundary, and Reflex evidence.
- Implemented when: it is renamed to `check-full-nonbrowser` everywhere or a
  manifest-driven `check-release` runs all locally possible hard gates, prints
  the exact CI-only remainder, and is kept coherent with Makefile, workflows,
  docs, and this catalog.

### TST-NI-038 — Semantic workflow and gate-manifest validation

- Status: `NOT IMPLEMENTED`
- Current gap: the bespoke workflow checker relies on strings/regexes and does
  not validate dependency dominance across all workflows.
- Implemented when: actionlint and real YAML parsing cover CI, CodSpeed, docs,
  deploy, reusable, benchmark-refresh, and release workflows; a declarative
  manifest defines job tier/dependencies/outcome/skips/artifacts; and redundant
  exact-step tests are retired after semantic parity exists.

### TST-NI-039 — Source-substring test reduction

- Status: `NOT IMPLEMENTED`
- Current gap: many tests inspect exact source snippets for behavior, creating
  false failures and false confidence; the stale Reflex assertion is one example.
- Implemented when: source checks are limited to freshness, generated boundaries,
  and forbidden constructs; runtime/DOM units own semantics; shipped bundles are
  exercised; and duplicate CI/local/docs command strings derive from the gate
  manifest.

### TST-NI-040 — Positive Rust-enabled sdist installation

- Status: `NOT IMPLEMENTED`
- Current gap: sdist validation proves structure and the expected no-Rust failure,
  not a fresh successful native build from the produced archive.
- Implemented when: the exact sdist installs in a clean Rust-enabled environment,
  loads the native core, runs ABI plus representative kernel/export smoke, and is
  retained as an artifact. The clear no-Rust failure lane remains.

### TST-NI-041 — Regular Pyodide regression lane

- Status: `NOT IMPLEMENTED`
- Current gap: the real WASM build/runtime probe runs only in the release workflow.
- Implemented when: relevant Rust/build/package changes trigger a pull-request or
  scheduled build and runtime kernel probe using the pinned toolchain tuple, while
  release continues to test the exact artifact it publishes.

### TST-NI-042 — Benchmark availability and integrity mode

- Status: `NOT IMPLEMENTED`
- Current gap: expected rivals or rows can be unavailable, skipped, timed out, or
  failed while schema verification and the advisory job remain green.
- Implemented when: expected competitors have import smokes with retained error
  details and version metadata; required scenarios/sizes have an allowlisted
  status policy; integrity failures are internally nonzero; report summaries
  separate integrity from advisory speed; and ordinary timing stays non-blocking.

### TST-NI-043 — Generated native-font freshness

- Status: `NOT IMPLEMENTED`
- Current gap: `src/font.rs` says it is generated by `scripts/gen_font.py`, but no
  deterministic check mode compares regenerated output.
- Implemented when: pinned font/tool inputs regenerate to a temporary location,
  byte-for-byte comparison is a relevant hard gate, and a stale committed font
  fails without rewriting the tree.

### TST-NI-044 — Type and static-analysis ratchets

- Status: `NOT IMPLEMENTED`
- Current gap: `ty` accepts an unbounded diagnostic count, JavaScript has syntax
  checks but no lint/static semantic policy, and workflow syntax uses a bespoke
  checker.
- Implemented when: core and adapter type checks run in correctly provisioned
  environments against reviewed baselines and reject new findings; JavaScript
  lint/static sink rules are hard; actionlint covers workflows; and existing
  Ruff/format/clippy gates remain hard.

### TST-NI-045 — Independent PDF and browser-export oracle policy

- Status: `NOT IMPLEMENTED`
- Current gap: local PDF checks can omit external tools, and public persistent
  Chromium batch behavior is not exercised through all formats in CI.
- Implemented when: at least one required job guarantees an independent PDF
  parser/renderer and asserts pages, dimensions, content, and nonblank semantics;
  PNG/JPEG/WebP/PDF browser fixtures use independent decode where applicable;
  and session reuse, mixed formats, failure cleanup, and sandbox policy run E2E.

### TST-NI-046 — Protocol/version documentation coherence

- Status: `NOT IMPLEMENTED`
- Current gap: Python and JavaScript runtime protocol constants are 4, while
  documentation and an unwired animation fixture retained protocol 3.
- Implemented when: a machine-readable source or checker keeps Python, JavaScript
  source/bundles, wire-protocol docs, examples, browser fixtures, and mismatch
  tests aligned; a protocol bump updates compatibility/changelog evidence in the
  same pull request; and hard-coded fixture versions are rejected.

### TST-NI-047 — Required pandas interoperability lane

- Status: `NOT IMPLEMENTED`
- Current gap: pandas Series/Period compatibility tests use
  `pytest.importorskip("pandas")`, while normal CI does not install pandas.
- Implemented when: a focused optional-integration job runs at the documented
  pandas floor/latest with zero pandas skips and verifies Period/datetime
  converter semantics plus rendered output. If pandas is unsupported, the tests
  and public boundary must say so explicitly instead.

### TST-NI-048 — Real-browser animation measurement lane

- Status: `NOT IMPLEMENTED`
- Current gap: `benchmarks/bench_animation.py` measures Chrome frame pacing,
  memory, and scratch allocation but is absent from CI, Makefile, benchmark
  refresh, and report verification.
- Implemented when: an advisory browser/scheduled lane emits the standard
  environment/category/status schema, validates lifecycle and bounded scratch/
  heap as integrity separate from timing, uploads JSON, and has verifier negative
  tests. Existing Python-only CodSpeed animation microbenchmarks remain distinct.

### TST-NI-049 — Cross-platform behavioral test matrix

- Status: `NOT IMPLEMENTED`
- Current gap: Python/Rust behavior suites run primarily on Ubuntu; Windows,
  Linux ARM64, and macOS lanes mostly prove wheel build/install/import.
- Implemented when: supported host classes install the actual built wheel and run
  one documented public API, kernel, encoding/framing, and export parity subset
  with identical fixture digests and zero unapproved skips. Keep this distinct
  from artifact structure and import smoke.

### TST-NI-050 — Machine-checkable claim-to-test traceability

- Status: `NOT IMPLEMENTED`
- Current gap: broad risk-surface rows do not yet map every material normative
  claim to a stable ID and exact evidence record.
- Implemented when: material requirements have stable IDs and a checked registry
  records authoritative spec, current/target gate, environment, evidence, status,
  oracle, skips, artifacts, and owner; validation rejects orphan claims, dead
  references, duplicate IDs, and `IMPLEMENTED` evidence that can silently skip.

### TST-NI-051 — Bounded execution and timeout policy

- Status: `NOT IMPLEMENTED`
- Current gap: several hard jobs and hang-prone subprocess/browser paths rely on
  runner ceilings rather than reviewed bounds.
- Implemented when: every hard/release job has `timeout-minutes`, subprocess and
  browser waits are explicit and clean up, targeted per-test timeout enforcement
  covers hang risks, timeout failures retain diagnostics, and workflow tests
  reject removing the bounds.

### TST-NI-052 — Hardware GPU and driver validation

- Status: `NOT IMPLEMENTED`
- Current gap: deterministic headless lanes primarily exercise CI software
  rendering, not representative hardware WebGL2 drivers.
- Implemented when: a scheduled or release lane runs a high-risk render,
  interaction, and context-loss subset on declared hardware-backed macOS,
  Windows, and/or Linux environments; records renderer/driver metadata; rejects
  software fallback for that lane; and retains semantic/golden evidence.

### TST-NI-053 — Browser renderer failure-mode E2E

- Status: `NOT IMPLEMENTED`
- Current gap: real-browser tests prove successful context restoration, while
  WebGL2 acquisition, shader/program, and permanent-restore failures are mostly
  protected by source markers.
- Implemented when: browser fixtures force each failure and assert one documented
  user-visible error/lifecycle event, host callback propagation, no uncaught
  exception/retry loop/resource leak, and retained logs/traces.

### TST-NI-054 — Browser compatibility policy and floor/latest matrix

- Status: `NOT IMPLEMENTED`
- Current gap: Playwright-pinned current engines run, but no browser-version
  support floor or latest-only policy is normative.
- Implemented when: product specs state engine/version ranges and WebGL2
  prerequisites; CI tests current plus oldest claimed versions where feasible;
  actual browser/renderer versions are recorded; and docs, dependency locks, and
  the test catalog cannot drift independently.

### TST-NI-055 — Fixture and golden provenance policy

- Status: `NOT IMPLEMENTED`
- Current gap: protocol bytes, benchmark baselines, reference corpora, generated
  snapshots, and future visual goldens do not share one provenance/review policy.
- Implemented when: every durable fixture declares source/oracle, seed/version/
  license, update command, reviewer rule, checksum/freshness method, and tolerance
  rationale; deterministic artifacts regenerate in check mode; and a corrupted
  fixture negative control proves the comparator fails.

## Recommended implementation order

1. Complete TST-NI-001 through TST-NI-005 so automation can be trusted to report
   the state of the existing suite.
2. Wire strict dashboard, Reflex, animation, pick-boundary, skip policy, and
   release/deploy qualification before expanding broad matrices.
3. Add the JavaScript unit layer, all-builder properties, protocol catalog,
   rendered-label/accessibility behavior, and coverage artifacts as fast oracle
   foundations.
4. Expand chart/axis/browser/platform matrices and packaging runtime evidence.
5. Add scheduled mutation, fuzz/sanitizer, GPU, visual, security, and soak depth.

No entry is complete merely because work started. Remove it from this file only
after its exact protection appears as `IMPLEMENTED` in [`current.md`](current.md)
with executable evidence and the intended gate wiring.
