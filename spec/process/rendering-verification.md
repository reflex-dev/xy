# Rendering verification — LOD invariants and the visual-regression corpus

**Status: design, not implemented.** This document specifies the two test
surfaces that make renderer churn safe: property-based invariant tests for
the LOD/reduction math, and a golden visual-regression corpus for the
browser client. [`production-readiness.md`](production-readiness.md) gains
the corresponding gates as phases land (§7).

## 1. Why now

The product direction is refine-and-optimize: the renderer, the LOD
kernels, and the interaction layer get touched constantly. The recent
regression history is dominated by one class of bug — **pixels went wrong
silently**: standalone density flicker on pan/zoom-out (#118), scatter
collapsing to a horizontal line after repeated box-zoom (#87), dense
scatter blanking on double-click (#79), styling drift in a shipped example
asset (#60). Every one shipped past the existing gates, because the gates
check "did it render *something*" and "does the API hold", not "is what
rendered still *right*".

The whole product claim rests on one sentence
([`../design/lod-architecture.md`](../design/lod-architecture.md)):
large data stays **truthful** and interactive. Truthfulness is a set of
mathematical statements about reductions. Mathematical statements deserve
property tests against oracles, not just example cases; and the pixels that
statements ultimately become deserve golden baselines, not just
blankness checks.

## 2. What exists today (and the gap)

| Surface | What it covers | What it cannot catch |
| --- | --- | --- |
| `tests/test_lod.py` | plan/contract shape, deterministic-sampling determinism, monotonicity, order-independence — on fixed examples | reduction *values* being wrong on inputs nobody hand-wrote |
| `tests/test_kernels.py` | M4 and kernel behavior on example inputs | adversarial shapes: constant runs, duplicate x, NaN runs, extreme magnitudes |
| `tests/test_framing_property.py` | wire framing round-trip, via Hypothesis (already a dev dependency) | — (this is the pattern §3 extends) |
| `scripts/render_smoke_nonumpy.py`, `scripts/smoke_render.py` | WebGL reaches real pixels; a composed chart paints | whether the pixels are the *right* pixels |
| `scripts/step_tier_smoke.py`, `scripts/interaction_stress_smoke.py`, `scripts/pick_boundary_smoke.py` | targeted probes for past bug classes | the next bug class — each probe was written after its bug shipped |
| `scripts/visual_regression_smoke.py` | statistical screenshot properties (non-blank, colored, region stats) across chart families — self-described "not a pixel-perfect golden suite yet" | any regression that keeps pixel statistics plausible: wrong colors in the right amounts, shifted geometry, missing subsets |
| `scripts/browser_conformance.mjs` (`make check-conformance`) | one focused chart in Chromium/Firefox/WebKit: semantics, interactions, coarse per-channel perceptual signature, DOM layout boxes | per-family coverage; interaction *states*; anything finer than the coarse signature |
| `benchmarks/bench_dashboard.py` nonblank gate | 10/20/50-chart pages stay nonblank | everything except blankness |

Two structural gaps, two workstreams:

- **A. No oracle-differential testing of the reduction math.** The
  invariants are written down (L1/L2/L3 and the "no visual lying" rules in
  lod-architecture.md §1–§3) but nothing exercises them across generated
  input space against an independent reference implementation.
- **B. No golden baselines, and no pixels for interaction states.** First
  paint has statistical checks; the states where the recent bugs actually
  lived (after zoom-out, after repeated box-zoom, after double-click,
  after a tier transition) have no pixel record at all.

## 3. Workstream A — LOD invariant properties

### 3.1 Method

Hypothesis-driven property tests in Python, exercising the **native kernels
through the real ctypes ABI**, checked against brute-force oracles written
in plain NumPy. This is deliberate:

- The Python↔ABI path is the shipped path; testing through it covers the
  Rust kernel, the ABI seam, and the Python plumbing in one bite.
- No new Rust crates. `proptest`/`quickcheck` would need vendoring
  (crates.io is unreachable from the dev sandbox); the Rust side keeps its
  example-based `cargo test` suite, and differential testing from Python
  covers the same code through the real boundary.
- Oracles are O(n) and obvious — a dozen lines of NumPy each. An oracle
  that needs cleverness is a second implementation to debug, not a
  reference.

Every failure must print the Hypothesis seed and a minimal reproduction;
CI runs a bounded profile (§7), local runs may go deeper.

### 3.2 The invariant table

Each row becomes a test module; the *invariant* column is the contract,
quotable in review when an implementation change breaks one.

| # | Invariant | Oracle | Input strategy highlights |
| --- | --- | --- | --- |
| A1 | **M4 extrema-exactness** (Tier-1 line/area): for every pixel column, the decimated output contains exactly the first, last, min, and max of the input points in that column, and nothing outside the input | O(n) NumPy group-by-column min/max/first/last | constant runs, monotone ramps, single-point spikes, duplicate x, NaN runs, magnitudes that stress f32 offset encoding |
| A2 | **Density/hexbin count fidelity** (Tier-2): per-cell / per-occupied-bin counts equal brute-force binning; only occupied bins ship (the centers-only wire contract); channel aggregates match the oracle in f64 | O(n) NumPy `histogram2d` / hex assignment | points exactly on bin edges, all-in-one-bin, uniform spread, counts near the payload bound |
| A3 | **Worker/kernel re-bin equivalence**: the standalone Web Worker re-bin of the retained sample equals the kernel re-bin of the same sample on the same viewport | kernel output *is* the oracle (differential) | zoom-in, zoom-out past home, repeated re-bins (the #118 shape) |
| A4 | **Deterministic sampling** (lod-architecture.md §3): keep-masks are deterministic, monotonic across levels, row-order-independent, and stratified masks preserve rare categories | already specified; existing example tests promoted to generated inputs | pathological category skew, one-row strata, saturation boundaries |
| A5 | **Re-bin count fidelity** (histogram/bar Tier-1): per-bin counts equal the oracle at the *same* edge set, at every generated resolution, and total mass always equals the visible row count. Nested-edge conservation (coarse bin = sum of its children) is checked only on constructed k× subdivisions — independent "nice" edges do not nest, and the property must not reject correct output for that | O(n) NumPy histogram at the implementation's own edges | bin edges vs data ties, empty windows, single-bin windows, deliberately non-nested edge pairs (must pass) |
| A6 | **Heatmap sampled normalization**: normalizing only sampled pixels equals full normalization evaluated at the sampled coordinates | full-grid NumPy normalization | non-uniform value distributions, constant grids, extreme dynamic range |
| A7 | **View round-trips**: zoom-in → zoom-out restores the exact f64 domain; drill-in → drill-out restores tier and recorded metadata; stale `drill_seq` replies are dropped, never applied (L3) | exact f64 equality / state comparison | deep zoom sequences (dossier §16 territory), interleaved stale replies |
| A8 | **NaN containment** (dossier §19): for any input mixing finite, NaN, and ±Inf values, no non-finite value reaches a vertex buffer, and the finite-row count matches the oracle | NumPy `isfinite` masking | NaN runs at head/tail, all-NaN traces, NaN in channel columns only |
| A9 | **Offset-encoding error bound** (dossier §4): with `value = offset₆₄ + f32(value − offset₆₄)`, reconstruction error is bounded by one f32 ULP of the offset-relative magnitude — the contract is `\|reconstructed − original\| ≤ 2⁻²³ × max(window_span, \|value − offset\|)`, which keeps error sub-pixel at any physical zoom (a span never maps to more than 2²³ pixels). Tighter is allowed; looser fails | direct f64 arithmetic against the formula | large offsets + small spans (the classic catastrophic-cancellation shape), timestamps, micro-ranges |
| A10 | **Tier-decision consistency** (L1/L2): crossing the budget boundary in either direction yields `tier`, `mode`, `visible`, `reduction` metadata consistent with what shipped, and `visible ≤ budget` always renders exact marks | recompute `drill_decision` in Python | counts straddling `budget`, hysteresis window edges |

A1, A2, A5, A6 are the truthfulness core — they are the sentences the
README's honesty claims compile down to. A7–A10 pin the seams the recent
bugs actually slipped through.

### 3.3 Placement

`tests/property/` package, one module per row (`test_prop_m4.py`, …),
sharing strategies from `tests/property/strategies.py` (data shapes,
viewports, magnitudes). They run inside the default `pytest -q` gate — no
new CI job, just new tests — under a CI Hypothesis profile bounded to keep
the suite's added wall-clock under 60 s (§7).

## 4. Workstream B — the visual-regression corpus

### 4.1 What a corpus entry is

One **canvas-readback golden** per (chart family × state), rendered
headless in a pinned Chromium:

- **Families:** the implemented set — line, scatter (direct + density),
  area, histogram, bar, heatmap, error bars/bands, box/violin/ECDF,
  hexbin/contour, step/stairs/stem, pie, facet grid — one canonical figure
  each, seeded data, fixed 720×440 @ DPR 1.
- **States are the point.** First paint is the *least* interesting entry;
  the corpus exists for the states where the recent bugs lived:

| State | Regression it guards |
| --- | --- |
| first paint | baseline sanity |
| wheel zoom-in ×3 | tier transitions, re-bin |
| box zoom, then double-click reset | #79 (blank on double-click), reset semantics |
| repeated box-zoom + zoom-out cycle | #87 (scatter collapse) |
| pan at zoomed depth, then zoom-out past home | #118 (density flicker/stretch) |
| selection overlay active (box + lasso) | overlay compositing |
| drill-in past budget, drill-out | density↔direct swap |
| kernel-less standalone after worker re-bin | the `to_html` LOD path |

  Gestures are driven over CDP, reusing the dispatch machinery the staged
  interaction benchmarks and existing probes already use. Each state waits
  on the render-client's settled signal (§4.2a), not on timeouts.

### 4.2a The settled signal is a client deliverable

The client does not expose this today — existing probes force a draw or
wait on frames and timers, which is exactly why they can capture an
intermediate frame. Phase 3 therefore ships, as part of the harness work,
a CDP-observable quiescence marker on the view: a monotonically increasing
**settle counter**, readable through the chart root, that increments only
when the client has no pending kernel round-trip, no queued worker re-bin,
no scheduled animation frame, and the last requested frame has drawn. The
harness reads the counter, dispatches a gesture, and waits for the counter
to advance and then hold for one animation frame. A counter (not an event)
keeps it poll-friendly over CDP, race-free for gestures that coalesce, and
adds nothing to the `xy:` event surface that
[`../api/interaction.md`](../api/interaction.md) §3 enumerates. It ships in
the production client (it is how the corpus observes reality, so it must
not be a test-build divergence), documented as internal/unstable, and the
existing probes migrate to it from their frame/time waits as they are
touched.

### 4.2 Determinism contract (what makes goldens honest)

Golden comparison is only as good as its determinism. The corpus compares
**WebGL canvas readback**, not full-page screenshots — DOM chrome (titles,
ticks, legends) stays under the existing conformance approach of layout
boxes and the coarse signature, because glyph rasterization varies by
platform and font stack. Within the canvas:

- Pinned Chromium build (the CI runner's pinned Playwright Chromium),
  fixed viewport, DPR 1, reduced-motion enabled, seeded data, deterministic
  sampling (already guaranteed by A4).
- Comparison metric: exact match is the target for aggregate surfaces
  (density textures, heatmap grids — they are computed, not rasterized);
  antialiased mark edges get a per-tile tolerance — a tile fails on mean
  channel delta or on a connected cluster of differing pixels above a
  per-family threshold. Thresholds live next to the baselines, in the
  repo, reviewed like code.
- Firefox/WebKit are **not** golden-compared; they keep the tolerant
  conformance signature. One engine produces goldens; three engines prove
  semantics. Cross-OS pixel identity is a non-goal (§8).

### 4.3 Baselines are code

- Stored as PNGs under `tests/visual/baselines/`, committed. Budget:
  ≤ 6 MB total for the initial ~90 entries (charts compress well); the
  check fails if the directory exceeds the budget, so growth is a
  reviewed decision, like the wheel-size gate.
- `make regen-visual` regenerates every baseline locally;
  `make check-visual` compares. A PR that changes rendering **must ship
  its baseline updates in the same PR** — the spec-currency rule applied
  to pixels. A baseline diff in review *is* the visual review.
- On CI failure, the job uploads an expected/actual/diff triptych per
  failing entry as an artifact — the debugging loop starts from images,
  not from a numeric threshold report.

## 5. Fail-first calibration

The acceptance test for this whole design is that it catches the bugs we
already paid for. Before either workstream is declared done:

- Revert the #118 fix (density flicker), the #87 fix (scatter collapse),
  and the #79 fix (double-click blank) each in a scratch branch; the
  corpus must fail the corresponding state, or a state/threshold is added
  until it does.
- Inject a deliberate off-by-one into M4 column assignment and into hexbin
  edge binning in a scratch branch; A1/A2 must fail within the CI
  Hypothesis profile, or the strategies get sharpened.

The same discipline as PR #117's fail-first probes: a test that has never
failed against a real bug is a hypothesis, not a safety net.

## 6. What this does not duplicate

- **CodSpeed / benchmarks** own performance; nothing here measures speed.
- **`make check-conformance`** owns cross-engine semantics and
  accessibility; the corpus adds states and exactness in one engine, it
  does not replace the three-engine tier.
- **`scripts/visual_regression_smoke.py`** keeps its role as the fast
  statistical tripwire during development; once the corpus gates CI, the
  smoke script's per-family statistical checks can fold into it and the
  script can retire (recorded, not silent).
- **Rust `cargo test`** keeps example-based kernel tests; §3 tests the
  same kernels through the shipped ABI with generated inputs.

## 7. CI wiring and rollout

| Phase | Ships | Gate status |
| --- | --- | --- |
| 1 | `tests/property/` A1–A2, A8 (the truthfulness core + NaN), strategies module, CI Hypothesis profile | inside `pytest -q` — hard gate from day one |
| 2 | remaining rows A3–A7, A9–A10 | hard gate |
| 3 | settle counter in the render client (§4.2a), corpus harness + first-paint baselines for all families, `make regen-visual` / `make check-visual`, size budget | **advisory** (like type checking): failures report, don't block |
| 4 | interaction states (the §4.1 table), fail-first calibration (§5) | promoted to **hard gate** once green for two consecutive weeks of normal churn |
| 5 | production-readiness.md gains both gates in the release-blocking table; smoke-script fold-in decision | — |

Budgets, enforced not aspirational: properties add ≤ 60 s to `pytest -q`
(CI profile caps examples per test; local `--hypothesis-profile=deep` goes
wider); `check-visual` completes in ≤ 3 min on the CI runner including
gesture driving.

## 8. Non-goals

- Cross-OS or cross-engine pixel identity — one pinned engine produces
  goldens; the conformance tier owns the rest.
- Full-page screenshot goldens — glyph rasterization is not ours to pin.
- Perceptual-quality scoring (SSIM et al.) — the corpus asks "did it
  change", with tolerances, not "does it look good".
- Accessibility-surface expansion — tracked in production-readiness.md's
  conformance section, separate work.
- Performance regression detection — CodSpeed and the benchmark suites
  own it.
