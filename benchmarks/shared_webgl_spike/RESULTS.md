# Browser results

Run on 2026-08-02 in the Codex in-app browser (Chrome 150.0.0.0) at a 1164 × 655
CSS-pixel viewport and device-pixel ratio 1.100000023841858. WebGL2 used ANGLE's Metal
renderer on an Apple M5 Pro. These numbers are machine/browser-specific; rerun the harness
for decisions about a target deployment.

The machine-readable capture is
[`results/chromium-2026-08-02.json`](./results/chromium-2026-08-02.json).
The charts in this run use the spike's synthetic renderer, not production xy `ChartView`.

This capture was produced from the clean worktree at
`81d9e4bfac173d2b8fe8cdef4a6eda9027e38847` on `agent/shared-webgl-spike`; the artifact records
that exact revision with `environment.git.dirty: false`. The benchmark code used for the run is
therefore reconstructible from Git.

## Outcome

| | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Requested charts | 50 | 50 |
| Live charts | **50** | **16** |
| Live WebGL contexts | **1** | **16 / 50** |
| Full-set correctness | **PASS** | **FAIL: 34 unavailable** |
| Canary checks | 50 / 50 | 16 / 16 surviving |
| Exact pick checks | 150 / 150 | 48 / 48 surviving |
| Productive chart presentations / second | **2,877** | **960** |

The native path created all 50 contexts, but only 16 remained live when measured. The harness
did not capture the identities or creation order of the 34 unavailable contexts. The shared path
kept every chart live through one context. Native's smaller 0.5 ms CPU batch p95 is not an
apples-to-apples win: that batch only rendered 16 charts, while the shared batch rendered all 50
and produced about 3.0× as many useful chart presentations per second.

## Correctness and recovery

- Shared mode passed 50 asymmetric frame canaries under deliberately poisoned WebGL state,
  150 exact encoded-ID pick checks, and a forced 17-pixel non-zero source crop.
- A deliberate shared `WEBGL_lose_context` cycle rebuilt the programs and all 50 per-chart GPU
  object sets, restored 1/1 lost context, and passed the full 50-chart checks again.
- Native mode's full-set check failed only on availability: all 16 surviving charts passed their
  canaries and 48 pick checks. A deliberate loss/restore cycle then restored 1/1 targeted native
  context and passed recovery checks for the same 16-chart pre-cycle live set.
- Native recovery does not claim to resurrect the 34 contexts already unavailable before the
  cycle. Both profiles record `visible_frames_during_loss_checked: false`; this run did not
  inspect visible canvases during the loss windows.

## Three-second production-profile benchmarks

Both timing runs used the dense viewport with 1,024 points per chart and an identical 180-batch
duration identity. Both profiles record `correctness.state_stress: true` but
`benchmark.state_stress: false`. The timed runs therefore omitted the deliberate poisoned-prime
stress workload used by correctness, while every timed render still executed its backend's
normal `beginPass` GL resets. The shared throughput and its roughly 3.0× ratio over native are
feasibility-harness measurements, not production estimates.

| Metric | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Duration | 3.007 s | 3.001 s |
| Productive batches | 173 / 180 | 180 / 180 |
| Observed batch rate | 57.54 fps | 59.98 fps |
| Chart presentations | 8,650 | 2,880 |
| Chart presentations / second | 2,876.81 | 959.62 |
| CPU batch p50 | 16.70 ms | 0.30 ms |
| CPU batch p95 | 18.90 ms | 0.50 ms |
| Shared 2D copy p95 / chart | 0.10 ms | n/a |

These are JavaScript CPU submission timings, not completed GPU execution timings.

## Recommendation

Proceed to a small in-tree `GLHost` integration prototype rather than adding `virtual-webgl` as
a dependency. Keep one document-level WebGL context; give each chart its own geometry and lazy
pick framebuffer; serialize rendering with an explicit state reset; synchronously copy the host
frame into each chart's visible 2D canvas; and rebuild every client resource after context
restoration.

Before production integration, validate the same contract with the actual xy renderer,
especially renderer cache invalidation, resize/DPR changes, interaction semantics, visible-frame
preservation during loss, and performance at real plot sizes.
