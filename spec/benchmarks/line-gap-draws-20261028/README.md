# Finite-run live draw submission

Baseline is exact `4dffbc76`, built in an isolated checkout. The candidate changes
only the live line renderer and its buffer lifecycle; native ABI 48, renderer
protocol 14, payloads and source-row identity are unchanged. Input is deterministic
synthetic data: one million x values and `sin(x*.01)`, either all finite, one
missing row, or a missing row every 100 samples starting at 50.

## Measurement and limits

The final sequential baseline/candidate run used the quiet task window
2026-10-28 05:40:47–05:42:15 UTC. Other task workers paused; the host remains a
shared cloud machine. Raw samples are `baseline.json` and `candidate.json`;
`environment.json` records source/bundle/native hashes and conditions.

Actual renderer: Chromium 151.0.7922.173, ANGLE Vulkan SwiftShader Subzero, DPR 1.
Each page contains one real chart fully inside a 900×600 viewport. Legend and
modebar are explicitly off; every case reports GL 0 and no page errors. Fixtures
compile at 720×320 and are measured at 720 and380 CSS-pixel widths, retaining the
same initial payload when resized.

| Fixture / width | Instanced draws before→after | Median CPU draw ms | Median rAF interval ms | Median hover wall ms |
|---|---:|---:|---:|---:|
| Finite / 720 | 1 → 1 | 0.80 → 0.50 | 66.75 → 83.25 | 148 → 87 |
| Finite / 380 | 1 → 1 | 0.80 → 0.65 | 66.70 → 75.00 | 111 → 134 |
| One gap / 720 | 2 → 1 | 0.65 → 0.60 | 66.70 → 83.30 | 95 → 66 |
| One gap / 380 | 2 → 1 | 0.60 → 0.50 | 83.30 → 66.65 | 52 → 79 |
| Fragmented / 720 | 10,001 → 1 | 62.85 → 0.60 | 216.65 → 200.00 | 792 → 298 |
| Fragmented / 380 | 10,001 → 1 | 62.75 → 0.65 | 225.00 → 183.35 | 826 → 204 |

CPU draw includes chart chrome and presentation; each of eight timed samples
follows three warmups. Raw `finishedMs` additionally calls `gl.finish()`.
rAF uses 25 redraw callbacks and discards the initial four intervals. Hover wall
time includes Playwright/CDP input and readout roundtrips while a redraw pump
runs; raw browser-only handler times are separate. These standalone fixtures
do not measure server exact-pick roundtrips. Raw `expectedSource` means the
client index in the declared `indexSpace`; the baseline finite decimated line
still uses emitted indices, addressed by separate identity work.

The result demonstrates a large local draw-submission reduction, not smooth
frame delivery: fragmented rAF intervals remain 183–200ms under this software
backend. Finite/one-gap cases vary and show no general frame-rate improvement.
No hardware FPS or peak-memory claim is made. Before/after real-renderer
captures are `spec/assets/line-gap-draw-{before,after}-{720,380}.png`; each pair
is byte-identical, including the hovered readout.

## Implementation boundary

The client derives four finite endpoint planes and a byte of run-cap flags
per drawn edge after existing smooth/step expansion. One instanced draw uses
the existing coordinate projection, line fragment shader and dash values.
The original x/y buffers and canonical source-row map remain available for
hover. Partial reveal and position interpolation use the existing per-run
path to preserve its arithmetic exactly. More than 2^24 edges also use that
fallback so float32 instance/reveal integers stay exact.

This adds derived buffers and an edge-start index cache. Buffer teardown and
retained-home ownership are covered, but peak memory remains unmeasured.
Area fills/outlines, native exporters and statistical smoothing are unchanged.

## Reproduction

Build each checkout's client independently. Use the matching ABI 48 native
library without replacing another checkout's binaries. In each checkout:

```bash
CARGO_HOME=/workspace/.cargo RUSTUP_HOME=/workspace/.rustup \
  PATH=/workspace/.cargo/bin:$PATH cargo build --release --offline
node js/build.mjs
UV_CACHE_DIR=/workspace/.cache/uv PYTHONPATH="$PWD/python" \
  XY_NATIVE_LIB="$PWD/target/release/libxy_core.so" \
  uv run --no-sync python scripts/bench_line_gap_draws.py /tmp/line-gap-fixtures
XY_CHROMIUM=/usr/bin/chromium node scripts/bench_line_gap_draws.mjs \
  /tmp/line-gap-fixtures /tmp/line-gap-draw-results.json
```

When measuring the baseline, run the same candidate benchmark scripts with its
source on `PYTHONPATH`. These scripts render actual XY fixtures over loopback;
they neither reconstruct charts nor change browser URL policy.

## Validation

- Two initial packed-draw regressions failed before the implementation
  (two draws instead of one), then passed after it.
- Final local packed-pixel/lifetime suite: 41 passed. Existing gap/lifecycle
  suite: 26 passed. Client TypeScript/shader build passed.
- Fresh independent audit: 1,944 exact toggle pixel comparisons, 108 exact
  baseline/candidate framebuffer hashes and 45 actual-pointer row/x/y matches.
- Independent twelve-cycle refinement/home test retained exact pixels and
  source IDs with 21 stable tracked buffers. Real context loss/restoration
  rebuilt finite edges with GL 0. Destroy left zero tracked live buffers and
  no double deletes.
- A broader local subset had 221 passes, 5 optional-pandas skips and 2 stale static
  interaction-marker failures. The exact baseline fails the same two tests;
  they expect pre-canonical-mapping source text and are separately tracked.

The independent audit and timing run used the frozen bundle identified in
`environment.json`. The final bundle adds a LINE-kind eligibility check for
protocol 15 area integration; targeted DPR1/2 line parity cases passed after
that guard. Area outlines retain their per-run path and require a combined
integration check when the independent area change is brought in.
