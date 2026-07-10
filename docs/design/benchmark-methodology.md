# Benchmark Methodology — Defensible Numbers

**Status:** methodology spec. Extends the shipped harness (`benchmarks/
bench_vs.py` adapters, `categories.py` registry, `_browser.py` FCP-based
TTFR, `bench_scatter_native.py`, CI `benchmark` job feeding
`docs/benchmark.md`). Written to survive a hostile Hacker News thread: every
number is mode-scoped, reproducible, oracle-checked, and the cases we *lose*
are published.

## 0. The three rules

1. **Mode-scoped claims only** (§2 of the dossier, already policy): "10M
   density in X ms" is a different claim from "10M individually-styled
   markers." Output labels every row `direct | decimated | density | sampled`
   — a reader can never mistake an aggregate result for a raw-marker result.
2. **Same-work comparisons.** Each competitor renders the *same visual
   contract*, not the same API call: if FastCharts aggregates at 10M, the
   fair Plotly comparison is Plotly failing/succeeding at raw markers AND
   Plotly+Datashader doing aggregation — both are reported. We never
   benchmark our fast path against a competitor's wrong tool.
3. **Truthfulness is a benchmark axis, not a footnote** (§6). Fast-but-wrong
   fails the suite.

## 1. Metric definitions (each with a precise probe)

| Metric | Definition | Probe |
|---|---|---|
| payload prep | wall time: canonical arrays → wire payload (spec+blob) | `perf_counter` around `build_payload`; competitors: their figure→HTML/JSON serialize |
| wire size | bytes crossing to the client | `len(blob)+len(spec_json)`; competitors: HTML/JSON size |
| browser TTFR | figure build + interactive HTML serialization + navigation → visible chart surface | shipped `_browser.py` chart-ready probe; page FCP is diagnostic only |
| interaction-ready | navigation → first successful synthetic wheel-zoom applied (view actually changes) | extend page probe: dispatch wheel, RAF-poll view/transform change |
| pan/zoom latency | p50/p95/p99 of input→pixels for repeated gestures | dispatched DOM events + draw + WebGL readback in `bench_interaction.py`; standalone-client scope is explicit |
| memory (kernel) | peak RSS delta + tracemalloc peak during prep | shipped psutil/tracemalloc pattern |
| memory (browser) | precise JS heap at chart-ready/dashboard settle; GPU memory remains unavailable | Chromium `performance.memory` with precise-memory flag; GPU numbers are not claimed |
| install size | `pip install` into a fresh venv: total site-packages bytes + wheel bytes + transitive dep count | scripted venv; competitors measured identically (Plotly+kaleido vs plotly alone reported separately) |
| cold import | `python -c "import lib"` best-of-5 fresh interpreters | subprocess timing (already the §33 import-budget concern) |
| small-data | full pipeline at N=1k/10k: prep+TTFR+interaction-ready | the "performance library must not lose the everyday case" check |
| large-data | N=1M/10M/100M per mode ladder | scatter+line+heatmap scenarios |

## 2. Truthfulness/exactness checks (the novel part)

Every performance scenario carries an **oracle assertion**; a run that fails
its oracle produces no number (it produces a bug):

- **Extrema preservation (lines):** decimated polyline's per-pixel-column
  min/max equals NumPy oracle min/max (M4's contract). Global max/min pixels
  are lit within ±1px column.
- **Count conservation (density/histogram):** sum(grid) == in-window row
  count (already the pattern in kernel tests; promoted to the bench harness
  at 10M/100M).
- **Channel honesty (after LOD phase 1):** per-cell mean grid equals NumPy
  groupby-mean oracle within f32 eps; majority cells match; purity ∈ [0,1].
- **Drill exactness:** zoom to ≤ budget ⇒ rendered point count == oracle
  window count; hover row values equal source f64 exactly.
- **Determinism:** two identical runs produce byte-identical payloads and
  (SwiftShader) identical pixel hashes — the anti-shimmer guarantee, and
  it's what makes all other numbers reproducible.
- **Reduction disclosure:** spec records tier/mode/visible for every
  reduced trace (assert present) — "no silent quality changes" as a test.

Competitors get the same oracles where the claim applies (e.g. Datashader
count conservation — it passes; Plotly scattergl marker dropout at high N —
documented finding, with repro).

## 3. Competitor matrix

Shipped adapters: fastcharts, Plotly, matplotlib, seaborn, Bokeh, Altair,
Datashader, hvPlot/HoloViews, and **plotly-resampler** ✅ (`bench_line.py` —
the honest line competitor, same decimation thesis, so comparing against
vanilla Plotly alone on lines would be a strawman; both run, with the M4
extrema oracle on the fastcharts row). Still to add: **PyGWalker** (adapter:
programmatic `walk()` export path; if headless render proves unstable, report
prep+payload only and say so). Every adapter: `unavailable` rows rather than
silent omission (harness behavior). Two adjacent metric harnesses now ship
beside the scatter comparison: `bench_install.py` (cold import + install
footprint, §1) and the PNG-export path (`Figure.to_png`) that makes the
static-export size row a real, non-raster-only comparison.

Per-competitor fairness notes ship in the report: Plotly measured both via
kaleido-PNG (their static path) and browser-HTML (their interactive path);
matplotlib is Agg (it's not interactive — its interaction rows are `n/a`,
not zero); Datashader is prep-only unless embedded in HoloViews (both
reported).

## 4. Environment & disclosure protocol

- **Two tiers of numbers:** (a) CI numbers — GitHub Actions ubuntu runner,
  SwiftShader software GL; reproducible by anyone from the repo, labeled
  "CI (software GL)"; (b) reference-hardware numbers — one pinned desktop
  spec (documented CPU/GPU/driver/browser build), labeled as such. Never mix
  tiers in one table. HN's first attack is "benchmarked on a potato/cherry
  machine" — pre-empt by publishing both.
- Every table header carries: dataset generator + seed, library versions,
  timestamp, harness commit. `benchmark.json` (already emitted by CI) is the
  canonical artifact; `docs/benchmark.md` renders from it — numbers in prose
  that don't exist in the artifact are banned (existing policy, kept).
- **Warm/cold discipline:** every timing reports which it is; first-run
  (cold cache) and steady-state are separate rows for TTFR and import.
- **Losses ship.** The report has a standing "where FastCharts loses" table
  (e.g., tiny-data static PNG export vs matplotlib; ecosystem breadth).
  Nothing buys credibility like published losses.

## 5. Scenario set (the public story)

1. `small_startup`: 1k line + 10k scatter — TTFR/interaction-ready vs all.
2. `line_10M`: decimated line vs plotly-resampler vs Bokeh — extrema oracle.
3. `scatter_10M_plain` and `scatter_10M_channels`: density path vs
   Datashader/HoloViews; channel-honesty oracle; Plotly raw as the
   documented-failure row.
4. `scatter_100M_pan`: pyramid pan/zoom percentiles (post LOD phase 3) —
   the headline; includes never-blank check (frame sampling: no frame
   without chart pixels).
5. `drilldown_truth`: CodSpeed native cycle covers density overview → exact
   points → density zoom-out; the 10M+ exact-hover oracle remains the larger
   browser/widget follow-up.
6. `core_2d_payloads`: CodSpeed tracks native histogram, area, bar, heatmap,
   and composed/layered `fc.chart(...)` payload prep;
   `benchmarks/bench_2d_charts.py` stays the Plotly/Seaborn chart-to-pixels
   comparison.
7. `dashboard_scale`: `benchmarks/bench_dashboard.py` attempts 10/20/50 mixed
   charts, checks every canvas initially and while scrolling, and records payload
   prep, navigation readiness, JS heap, redraw-submission p95, per-chart context
   loss/restoration events, and the stable loss-free chart-count ceiling. Partial
   dashboards remain successful measurement rows rather than losing their metrics.
   CI hard-gates the 10-chart row as loss-free/nonblank and applies deliberately
   loose catastrophic budgets to its render, scroll, and redraw timings.
8. `install_import`: lower-bound distribution size plus opt-in fresh-venv total
   site-packages, transitive distribution count, install time, and cold import.
9. `public_workflows`: `benchmarks/bench_workflows.py` tracks ingestion shapes,
   streaming refresh/pyramid rebuild, and HTML/SVG/native-PNG/Chromium-PNG export independently.

## 6. Remaining implementation plan

1. Extend the shipped count-conservation and per-pixel line extrema oracles with
   channel-aggregation and cross-library pixel-dropout oracles.
2. Add a real widget/comm round-trip interaction probe; current browser rows are
   explicitly standalone client input-to-readback, while backend work is timed
   in CodSpeed/workflow rows.
3. PyGWalker adapter and Plotly/Bokeh equivalents for the
   `dashboard_20` scenario.
4. Reference-hardware runbook (`benchmarks/README`): exact pins + one-command
   repro; publish both tiers on the next README refresh.

Timing regression policy is two-level: movement beyond 2x is advisory on shared
runners, while movement beyond 4x is a hard failure. Interaction and visual
budgets are capped in the report verifier so a benchmark change cannot silently
make its own gate easier.
