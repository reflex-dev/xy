# Reference-hardware browser results

Captured on 2026-08-02 with three complete cold-browser-process repetitions per profile
(six fresh Chromium processes total). Structural fields agreed across every repetition. The
tables below publish fieldwise medians for floating-point measurements and observed integer
medians for counts; expected intervals, dropped intervals, stable presentation totals, and rates
were then derived from those values. Every raw attempt was retained and all six completed
without capture errors or unexpected browser diagnostics.

The reference machine was an AC-powered MacBook Pro (Mac17,8) with an Apple M5 Pro
(18 CPU cores and 20 GPU cores), 64 GB RAM, Low Power Mode disabled, and macOS 26.5.2
(25F84). The static server ran under CPython 3.12.13. The capture runner used Node 22.23.2,
the repository-locked Playwright 1.61.1, and Chrome for Testing 149.0.7827.55 at a
1280 × 720 CSS-pixel viewport and device-pixel ratio 1. The installed Rust tools were
`rustc 1.96.1 (31fca3adb 2026-06-26)` and `cargo 1.96.1 (356927216 2026-06-26)`.
WebGL2 used ANGLE's Metal renderer on the Apple M5 Pro. This was an ordinary developer
workstation with no intentional competing benchmark workload and no process isolation, so
rerun the harness for target-deployment decisions.

The machine-readable median summary is
[`results/chromium-2026-08-02.json`](./results/chromium-2026-08-02.json). The
[`raw capture set`](./results/raw/chromium-2026-08-02/) contains all six profile runs and the
generated [`summary-input.json`](./results/raw/chromium-2026-08-02/summary-input.json).
The charts use the spike's synthetic renderer, not production xy `ChartView`.

The capture utility and schema came from the clean worktree at
`98dc105395221608f0e54d5d744965fb1f57c574` on `agent/shared-webgl-spike`. Every raw file
records that revision with `runnerEnvironment.git.dirty: false`. Repetition order alternated
between shared-first and native-first (`shared/native`, `native/shared`, `shared/native`) to
limit systematic order bias. The capture also verified the served harness bytes against the
local `index.html`, `experiment.js`, and `styles.css`; their SHA-256 hashes are published in the
machine-readable summary. All 150 shared readback warnings and 102 native context-limit warnings
matched narrow expected-diagnostic policies; zero unexpected diagnostics were observed.

## Outcome

| | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Requested charts | 50 | 50 |
| Live charts | **50** | **16** |
| Live WebGL contexts | **1** | **16 / 50** |
| Full-set correctness | **PASS** | **FAIL: 34 unavailable** |
| Canary checks | 50 / 50 | 16 / 16 surviving |
| Exact pick checks | 150 / 150 | 48 / 48 surviving |
| Median productive chart presentations / second | **2,999** | **960** |

The native path created all 50 contexts, but only 16 remained live in every repetition. The
harness did not capture the identities or creation order of the 34 unavailable contexts. The
shared path kept every chart live through one context. Native's smaller 0.6 ms median CPU batch
p95 is not an apples-to-apples win: that batch rendered only 16 charts, while the shared batch
rendered all 50 and produced 3.125× as many useful chart presentations per second.

## Correctness and recovery

- In every repetition, shared mode passed 50 asymmetric frame canaries under deliberately
  poisoned WebGL state, 150 exact encoded-ID pick checks, and a forced 17-pixel non-zero source
  crop.
- Each deliberate shared `WEBGL_lose_context` cycle rebuilt the programs and all 50 per-chart
  GPU object sets. The post-minus-pre recovery deltas were 1 context loss and 1 restoration,
  with all 50 expected charts live and correct afterward.
- Native mode's full-set check failed only on availability in every repetition: all 16 surviving
  charts passed their canaries and 48 pick checks. Each recovery cycle targeted the same
  16-chart pre-cycle live set; its post-minus-pre deltas were also 1 loss and 1 restoration,
  with all 16 expected charts live and correct afterward.
- Native recovery does not claim to resurrect the 34 contexts already unavailable before the
  cycle. Both profiles record `visible_frames_during_loss_checked: false`; these runs did not
  inspect visible canvases during the loss windows.

## Three-second production-profile medians

Both profiles used the same configured 3,000 ms duration, dense viewport, 1,024 points per
chart, and 60 fps target. The configured `requested_duration_ms` is the cross-profile workload
identity; `duration_ms` and its derived `expected_batches` describe each observed run and may
differ. Both profiles record `correctness.state_stress: true` but
`benchmark.state_stress: false`. The timed runs therefore omitted the deliberate poisoned-prime
stress workload used by correctness, while every render still executed its backend's normal
`beginPass` GL resets.

| Metric | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Configured duration | 3.000 s | 3.000 s |
| Median observed duration | 3.0009 s | 3.0009 s |
| Productive batches | 180 | 180 |
| Expected intervals | 180 | 180 |
| Dropped intervals | 0 | 0 |
| Observed batch rate | 59.98 fps | 59.98 fps |
| Chart presentations | 9,000 | 2,880 |
| Chart presentations / second | 2,999.10 | 959.71 |
| CPU batch p50 | 1.20 ms | 0.40 ms |
| CPU batch p95 | 1.30 ms | 0.60 ms |
| CPU batch p99 | 1.40 ms | 0.70 ms |
| Shared 2D copy p95 / chart | 0.10 ms | n/a |

These are aggregate values from the three successful runs per profile, not a synthetic median
run. Structural fields had to agree; floating measurements use fieldwise medians, count fields
use an observed integer median, and presentation totals are derived from productive batches and
the stable live-chart count. Presentation and frame rates are recomputed from those values and
duration so the summary remains internally consistent. The timings measure JavaScript CPU
submission, not completed GPU execution. The shared throughput and its 3.125× ratio over native
are feasibility-harness measurements, not production estimates.

## Recommendation

Proceed to a small in-tree `GLHost` integration prototype rather than adding `virtual-webgl` as
a dependency. Keep one document-level WebGL context; give each chart its own geometry and lazy
pick framebuffer; serialize rendering with an explicit state reset; synchronously copy the host
frame into each chart's visible 2D canvas; and rebuild every client resource after context
restoration.

Before production integration, validate the same contract with the actual xy renderer,
especially renderer cache invalidation, resize/DPR changes, interaction semantics, visible-frame
preservation during loss, and performance at real plot sizes.
