# Browser results

Run on 2026-07-31 in the Codex in-app browser (Chrome 150.0.0.0) at a 2240 × 1284
CSS-pixel viewport and device-pixel ratio 1.1. WebGL2 used ANGLE's Metal renderer on an
Apple M5 Pro. These numbers are machine/browser-specific; rerun the harness for decisions
about a target deployment.

The machine-readable capture is
[`results/chromium-2026-07-31.json`](./results/chromium-2026-07-31.json).
The charts in this run use the spike's synthetic renderer, not production xy `ChartView`.

This committed capture is not exactly reproducible from Git alone. It records
`environment.git.dirty: true` at
`environment.git.commit: 2e169101f16cfdbe4881a704e3fe095379dc7b9e`, while `base_commit` is `d505ef57`.
Because the run included uncommitted changes, neither revision reconstructs the exact benchmark
code that produced these numbers.

## Outcome

| | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Requested charts | 50 | 50 |
| Live charts | **50** | **16** |
| Live WebGL contexts | **1** | **16 / 50** |
| Full-set correctness | **PASS** | **FAIL: 34 unavailable** |
| Canary checks | 50 / 50 | 16 / 16 surviving |
| Exact pick checks | 150 / 150 | 48 / 48 surviving |
| Productive chart presentations / second | **2,449** | **949** |

The native path created all 50 contexts, but only 16 remained live when measured. The harness
did not capture the identities or creation order of the 34 unavailable contexts. The shared path
kept every chart live through one context. Native's smaller 0.4 ms CPU batch p95 is not an
apples-to-apples win: that batch only rendered 16 charts, while the shared batch rendered all 50
and produced about 2.6× as many useful chart presentations per second.

## Shared correctness and recovery

- 50 asymmetric frame canaries passed under deliberately poisoned WebGL state.
- 150 exact encoded-ID pick checks passed.
- Verification forced a 17-pixel non-zero source crop from the grow-only host canvas.
- A deliberate `WEBGL_lose_context` cycle rebuilt the shared programs and all 50 per-chart GPU
  object sets, then passed the full checks again, verifying restoration of all clients. The
  capture records `recovery.visible_frames_during_loss_checked: false`: it did not inspect the
  visible 2D canvases during the 650 ms loss window, so it does not verify visible-state
  preservation during the loss.

## Three-second production-profile benchmarks

Both timing runs used the dense viewport with 1,024 points per chart. Both profiles record
`correctness.state_stress: true` but `benchmark.state_stress: false`. The timed runs therefore
omitted the deliberate poison/reset stress workload used by correctness, although every timed
render still executed its backend's normal `beginPass` GL resets. The shared throughput and its
roughly 2.6× ratio over native are feasibility-harness measurements, not production estimates.

| Metric | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Duration | 3.001 s | 3.001 s |
| Productive batches | 147 | 178 |
| Observed batch rate | 48.98 fps | 59.32 fps |
| Chart presentations | 7,350 | 2,848 |
| Chart presentations / second | 2,448.94 | 949.14 |
| CPU batch p50 | 1.20 ms | 0.30 ms |
| CPU batch p95 | 1.30 ms | 0.40 ms |
| Shared 2D copy p95 / chart | 0.10 ms | n/a |

These are JavaScript CPU submission timings, not completed GPU execution timings.

## Recommendation

Use this result to proceed to a small in-tree `GLHost` integration prototype rather than adding
`virtual-webgl` as a dependency. Keep one document-level WebGL context; give each chart its own
geometry and lazy pick framebuffer; serialize rendering with an explicit state reset;
synchronously copy the host frame into each chart's visible 2D canvas; and rebuild every client
resource after context restoration.

Before production integration, validate the same contract with the actual xy renderer, especially
renderer cache invalidation, resize/DPR changes, interaction semantics, and performance at real
plot sizes.
