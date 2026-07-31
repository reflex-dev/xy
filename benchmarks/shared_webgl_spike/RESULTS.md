# Browser results

Run on 2026-07-31 in the Codex in-app browser (Chrome 150.0.0.0) at a 2259 × 1294
CSS-pixel viewport and device-pixel ratio 1.1. WebGL2 used ANGLE's Metal renderer on an
Apple M5 Pro. These numbers are machine/browser-specific; rerun the harness for decisions
about a target deployment.

The machine-readable capture is
[`results/chromium-2026-07-31.json`](./results/chromium-2026-07-31.json).
The charts in this run use the spike's synthetic renderer, not production xy `ChartView`.

## Outcome

| | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Requested charts | 50 | 50 |
| Live charts | **50** | **16** |
| Live WebGL contexts | **1** | **16 / 50** |
| Full-set correctness | **PASS** | **FAIL: 34 unavailable** |
| Canary checks | 50 / 50 | 16 / 16 surviving |
| Exact pick checks | 150 / 150 | 48 / 48 surviving |
| Productive chart presentations / second | **2,687** | **960** |

The native path created all 50 contexts, but Chromium evicted the oldest 34 and retained 16.
The shared path kept every chart live through one context. Native's much smaller 0.4 ms CPU
batch p95 is not an apples-to-apples win: that batch only rendered 16 charts, while the shared
batch rendered all 50 and produced about 2.8× as many useful chart presentations per second.

## Shared correctness and recovery

- 50 asymmetric frame canaries passed under deliberately poisoned WebGL state.
- 150 exact encoded-ID pick checks passed.
- Verification forced a 17-pixel non-zero source crop from the grow-only host canvas.
- A deliberate `WEBGL_lose_context` cycle retained the visible 2D frames, rebuilt the shared
  programs and all 50 per-chart GPU object sets, and passed the full checks again.

## Three-second production-profile benchmarks

State poisoning was off for both timing runs; correctness checks always turn it on.

| Metric | Shared GLHost | Native contexts |
| --- | ---: | ---: |
| Duration | 3.014 s | 3.001 s |
| Productive batches | 162 | 180 |
| Observed batch rate | 53.75 fps | 59.97 fps |
| Chart presentations | 8,100 | 2,880 |
| Chart presentations / second | 2,687.46 | 959.55 |
| CPU batch p50 | 1.30 ms | 0.30 ms |
| CPU batch p95 | 16.50 ms | 0.40 ms |
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
