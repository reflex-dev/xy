# Benchmark Methodology — Defensible Numbers

**Status:** methodology spec. Extends the shipped harness (`benchmarks/
bench_vs.py` adapters, `categories.py` registry, `_browser.py` chart-ready
TTFR probe, `bench_scatter_native.py`, `bench_transport.py`, the CodSpeed simulation
modules under `benchmarks/test_codspeed_*.py`, CI `benchmark` job feeding
`docs/benchmark_ci.md`). Written to survive a hostile Hacker News thread: every
number is mode-scoped, reproducible, oracle-checked, and the cases we *lose*
are published.

## 0. The three rules

1. **Mode-scoped claims only** (§2 of the dossier, already policy): "10M
   density in X ms" is a different claim from "10M individually-styled
   markers." Output labels every row `direct | decimated | density | sampled`
   — a reader can never mistake an aggregate result for a raw-marker result.
2. **Same-work comparisons.** Each competitor renders the *same visual
   contract*, not the same API call: if XY aggregates at 10M, the
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
| loopback transport | `channel.handle_message()` dispatch → HTTP envelope → client decode; raw/gzip bytes, Python allocation, p50/p95, browser heap, next frame | `benchmarks/bench_transport.py`; binary arm uses the production versioned frame and shipped JS decoder |
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

Shipped adapters: xy, Plotly, matplotlib, seaborn, Bokeh, Altair,
Datashader, hvPlot/HoloViews, and **plotly-resampler** ✅ (`bench_line.py` —
the honest line competitor, same decimation thesis, so comparing against
vanilla Plotly alone on lines would be a strawman; both run, with the M4
extrema oracle on the xy row). Still to add: **PyGWalker** (adapter:
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
  machine" — pre-empt by publishing both. `benchmarks/README.md` is the shipped
  runbook for both tiers: exact dependency pins against
  `benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro` (`pyproject.toml`,
  `uv.lock`, `environment.json`), copy-paste repro commands, and the prescribed
  `reference hardware` vs `CI (software GL)` table labels.
- Every table header carries: timestamp, python version/implementation,
  platform system/machine, and harness commit + dirty state
  (`bench_vs.to_markdown`). Library versions, executables, CPU count, xy
  backend, and browser renderer are recorded in the JSON `environment` block
  (`benchmarks/environment.py`) but are not yet rendered into the markdown
  header. `benchmark.json` (emitted by the CI `benchmark` job) is the canonical
  artifact; `docs/benchmark_ci.md` is rendered from it and
  `spec/benchmarks/metrics.md` is emitted by `scripts/check_regressions.py
  --emit-md`. `spec/benchmarks/results.md` is hand-maintained and must only quote rows
  present in those artifacts — numbers in prose that don't exist in the
  artifact are banned (existing policy, kept).
- **Warm/cold discipline:** every timing reports which it is; first-run
  (cold cache) and steady-state are separate rows for TTFR and import.
- **Losses ship.** The report has a standing "where XY loses" table
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
   and composed/layered `xy.chart(...)` payload prep;
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
   streaming refresh/incremental pyramid update, and HTML/SVG/native-PNG/Chromium-PNG export independently.

## 6. Remaining implementation plan

1. Extend the shipped count-conservation and per-pixel line extrema oracles with
   channel-aggregation and cross-library pixel-dropout oracles.
2. Add the final widget/comm and Reflex request-to-pixels probes. The shipped
   loopback transport diagnostic now covers `channel.handle_message()` through
   real HTTP plus browser decode/next-frame — including the production
   versioned binary frame on both sides of the wire — but deliberately excludes
   real widget comm transport (the widget arm stubs `_send`), GPU upload, and
   visible-pixel readback.
3. PyGWalker adapter and Plotly/Bokeh equivalents for the
   `dashboard_20` scenario.
4. Record the dataset generator and its seed in the emitted reports (seeds are
   currently hardcoded per harness and never captured), and render the JSON
   `environment` library versions into the markdown table headers, so §4's
   disclosure protocol holds end to end.

Timing regression policy is two-level: movement beyond 2x is advisory on shared
runners, while movement beyond 8x is a hard failure. Interaction and visual
budgets are capped in the report verifier so a benchmark change cannot silently
make its own gate easier.

## 7. Regression-gate inputs

The regression-gate step lives in the `test` job of `.github/workflows/ci.yml`,
which carries no `continue-on-error`. It runs three harnesses and feeds all
three to `scripts/check_regressions.py`:

| Input | Harness | Artifact |
|---|---|---|
| scatter | `benchmarks/bench_scatter_native.py --sizes 1e5,1e6,1e7 --production` | `scatter.json` |
| kernel | `scripts/bench_native.py --sizes 1e6,1e7` | `kernel.json` |
| transport | `benchmarks/bench_transport.py --n 1e6 --reps 15 --browser-reps 12 --chromium <playwright chromium> --require-browser` | `transport.json` |

Each artifact is schema-checked by `scripts/verify_benchmark_report.py`
(`--kind scatter-native`, `kernel-native`, `transport-loopback`) before the gate
reads it, and `check_regressions.py` independently rejects a transport input
whose `measurement_scope` is not `loopback-channel-transport-diagnostic` — a
different harness cannot be substituted for the third input. The same run
emits `spec/benchmarks/metrics.md` via `--emit-md`.

`bench_transport.py` is the third input and the only one whose CI invocation
hard-gates a browser:

- **Fixture.** A scatter `Figure` over `n` points (`numpy.random.default_rng(42)`,
  uniform x, normal y) plus one `density_view` message. The CLI rejects
  `--n` below 250000, so the gated fixture always exercises the density
  transport path rather than a direct-tier payload.
- **Same-work arms.** Both arms dispatch the identical message through
  `xy.channel.handle_message`; only the response encoding differs. `binary-frame-v1`
  is the production versioned frame (`encode_frame`); `base64-json-prototype` is
  the current Reflex prototype shape, base64 buffers inside JSON. This is rule 2
  of §0 applied to a wire format instead of a competitor library.
- **Three layers.** In-process envelope encode (wire bytes, gzip bytes at level 6
  with `mtime=0`, encode p50/p95, `tracemalloc` peak, and an explicit count of
  payload re-encodes — a count of format transformations, not a claim about
  hidden interpreter or socket copies); Python loopback through a real
  `ThreadingHTTPServer` (request → decode p50/p95, first two iterations
  discarded); and an optional Chromium probe that fetches both endpoints,
  decodes with the shipped JS `decodeFrame`, and awaits the next animation
  frame. `--require-browser` makes a skipped or failed probe a nonzero exit, so
  the browser arm is not silently optional in CI.
- **Append diagnostics.** Widget binary transmission count and bytes (measured
  with `FigureWidget._send` stubbed) plus the wire cost an unaffected second
  trace adds to a single-trace append.

Only deterministic byte counts reach the gate. `flatten()` lifts `wire_bytes`,
`gzip_bytes`, and `wire_to_payload_ratio` per envelope mode, plus the five
`append_diagnostics` counters: 11 rows in `spec/benchmarks/metrics.md`, all
prefixed `transport.`. Every one of the 11 gates **hard** under `policy()` —
byte counts and the ratio at 2% tolerance, `widget_binary_transmissions` at zero
tolerance. The harness's measured timings (encode p50/p95, HTTP p50/p95, browser
request-to-next-frame, JS heap delta) are reported and uploaded but deliberately
ungated: they are wall-clock numbers from a shared runner, and §4's warm/cold
and tier discipline applies to them rather than a threshold.

## 8. CodSpeed simulation modules

`.github/workflows/codspeed.yml` runs `pytest benchmarks/test_codspeed_*.py
--codspeed` under `CodSpeedHQ/action` in `simulation` mode, after asserting
`xy.kernels.BACKEND == "native"`. Simulation counts instructions rather than
wall time, so browser, install, and cross-library process benchmarks stay out of
it — those live in `benchmark-refresh.yml`, and the workflow says so inline.

The glob collects three modules — `test_codspeed_kernels.py`,
`test_codspeed_pyplot.py`, and `test_codspeed_transport.py` — for 94 rows
total. These are trend-tracked in CodSpeed, not gated: none of them feed
`scripts/check_regressions.py`, whose three inputs are §7's.

**`benchmarks/test_codspeed_pyplot.py` — 14 rows, seven paired arms.** Each pair
expresses one chart twice over the same input arrays: once through the
declarative API (`xy.chart` + marks) and once through the identical
matplotlib-style calls in `xy.pyplot`. Both arms end at the same terminal work —
`build_payload_split(2048)`, or PNG bytes for the export pair — so the gap
between a `*_pyplot` row and its `*_raw` twin is exactly what the shim adds:
matplotlib-call translation, fmt-string parsing, and figure-lifecycle
bookkeeping. The pyplot arm includes `plt.close("all")` because figure-registry
bookkeeping is part of the shim's per-figure cost. The pairs are a 10k line, a
1M line, a 100k scatter, a 100k-value/200-bin histogram, a 1k-category bar, a
5k-point three-series styled panel (title, axis labels, legend — the shim's
worst honest case, where translation is largest relative to data), and a
100k-point PNG export.

Fairness pins, all asserted in the module rather than assumed:

- Both arms build the same 640x480 canvas (`plt.subplots()`'s 6.4x4.8in at
  dpi=100), and the raw arm declares the explicit axes the shim adds implicitly,
  so chrome layout work is identical on both sides.
- The export pair uses `scale=2.0` to match `savefig`'s fixed 2x supersampling —
  both emit a 1280x960 canvas. A smaller raw canvas would overstate the gap.
- Every pair except the histogram asserts byte-identical payload sizes across
  arms, so a row cannot get faster by shipping a different chart. This is §2's
  oracle discipline applied to a shim-overhead measurement.
- The histogram pair is exempt and documents why: `ax.hist` pre-bins with NumPy
  because it must return matplotlib's `(n, bins, patches)` tuple and then ships
  bar geometry, while `xy.histogram` bins natively and ships rect columns. Its
  assertion is instead that the payload stays bounded by bin count, never by
  observation count.
- A session fixture warms both arms' lazily imported submodules (marks,
  `_payload`, the export stack, the shim's translation tables) before any
  measured region. Without it the first benchmark of each arm tracks package
  source size instead of its own workload.

**`benchmarks/test_codspeed_transport.py` — 7 rows.** These isolate the Python
envelope codec and deliberately exclude what `bench_transport.py` covers:
sockets, compression, JS heap, and animation frames are wall-clock/browser
measurements and are not meaningful under simulation. Fixtures are a 128 KiB
density buffer and an 800 KiB two-buffer direct payload. The rows are
`encode_frame` on both fixtures; `encode_frame_parts` on the direct fixture,
asserting the parts sum to the single-body length and that the buffer parts stay
zero-copy `memoryview`s; `decode_frame` on both fixtures, asserting the decoded
buffers alias the original body rather than copying it; and base64-JSON
encode/decode comparators on the direct fixture, so the codec's advantage stays
a continuously tracked ratio rather than a remembered one.

**`benchmarks/test_codspeed_kernels.py` — 73 rows** (70 functions; two are
parametrized, over 2 ingest flavors and 3 `bin_2d` thread-cap regimes). This is
the bulk of the suite and covers the native compute core the rest of the engine
sits on: decimation tiers, f32 encoding, and zone maps (`spec/design-dossier.md`
§5, §4/§16, and §22 respectively), plus the end-to-end figure → wire-payload
path. Sizes are pinned at three scales — 10k, 100k, and 1M — so a regression is
attributable to a regime (normal dashboard chart, exact WebGL workload,
screen-bounded large-data path) rather than to one arbitrary N. Seventeen rows
are `first_payload_*`, one per chart kind, which makes this the per-kind guard
that §7's scatter-only gate does not provide. Its module docstring carries the same backend rule the workflow
asserts: fallback timings are correctness smoke data, not production
performance data.

## 9. Shim gates and CI coverage

Two `make` targets bound the `xy.pyplot` shim from opposite sides. Both appear
in the focused-gate table of `spec/process/production-readiness.md`.

- **`make check-pyplot`** → `pytest tests/pyplot -q`. The correctness side: shim
  behavior, matplotlib interoperability, and the reference corpus. It also
  carries the *relative* speed gate, `tests/pyplot/test_perf_guardrail.py`,
  which asserts the pyplot build stays within 1.6x the declarative build at 10k
  points and 1.5x at 100k (best-of-N, plus a 100us absolute allowance for CI
  timer jitter) and that theme/axis components come from the component cache
  instead of being rebuilt. Its own docstring scopes it: a structural-regression
  gate for an O(n) copy or per-build revalidation sneaking into the shim, not a
  re-measurement of the margin.
- **`make check-pyplot-speed`** → `benchmarks/bench_pyplot_vs_matplotlib.py
  --profile standard --reps 21 --warmups 3 --target-speedup 10 --require-target`
  (needs the `.[bench]` extra). The *absolute* side: figure construction through
  a completed, compressed PNG at a shared 1800x840 target against
  matplotlib/Agg, reported per family — line, scatter, histogram, bar,
  pcolormesh, contour. `--require-target` exits nonzero unless every family
  reaches the 10x total-time target. The run alternates library order to reduce
  drift bias, excludes data generation, imports, and the first warm-up render,
  retains raw timing samples in its JSON artifact, and fails a case whose PNG
  comes back blank for either library.

The CodSpeed pyplot pairs of §8 track the same promise continuously, so a
structural regression surfaces attributed to the `*_pyplot` arm instead of as an
unexplained engine slowdown.

**CI coverage, verified against `.github/workflows/ci.yml`.** The jobs carrying
no `continue-on-error` are `matplotlib_reference`, `test`, `browser_conformance`,
`python_floor`, `sdist`, `wheels`, and `install_without_rust`; only
`benchmark_vs`, `benchmark_methodology`, and `benchmark` are non-blocking.
`matplotlib_reference` is **not** absent from the Release-Blocking Gates table in
`spec/process/production-readiness.md`: it is the "Matplotlib reference" row, whose
evidence column names exactly the job's two halves,
`python scripts/sync_matplotlib_compat.py --check` and `pytest tests/pyplot`.
What the job adds beyond that row's wording is the pin and the environment — it
installs `matplotlib==3.11.0` into a fresh uv venv and asserts the resolved
version before checking the reviewed snapshot, then runs
`test_launch_compat.py`, `test_reference_corpus.py`, and
`test_reference_semantics.py` under `MPLBACKEND=Agg`.

The real coverage gap is narrower and is on the speed side: no workflow invokes
`bench_pyplot_vs_matplotlib.py`. The per-family 10x PNG target is therefore
enforced by `make check-pyplot-speed` locally and watched by the CodSpeed pyplot
rows' trend, but no blocking CI job asserts it.
