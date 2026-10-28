# Line-gap correctness draft: 2026-10-28

Baseline is exact `ec61c2260ba03fa4361ed1420f0ae9a0e2e15383`, independently built
in `/workspace/xy-gap-baseline`. Candidate is `cloud/line-gap-fidelity` in
`/workspace/xy-gap-work`. Both use the existing ABI-47 native library; renderer
protocol changes from 13 to 14. No Rust ABI or data-aggregation change.

## Evidence

The raw SVG path changes from a single `M` followed by a bridging `L`, to two
separate `M` runs. Both SVG files happen to have the same byte size: replacing
`L` with `M` changes topology without changing character count.
`export-proof.json` records native PNG blue ink in the missing sample's center
band: **128 → 0 pixels**, while a finite sample's band stays **104 → 104**.
Images have shape 1440×640 RGBA at scale 2. Actual live renderer captures at
380 CSS pixels, DPR 2, are in `spec/assets/line-gap-before-380.png` and
`line-gap-after-380.png`; source is the deterministic fixture in
`tests/test_line_gaps.py`. Hover at x=4 changes from incorrect source row 3 to
canonical row 4 while preserving x/y values. No screenshot stands in for a chart.

## Payload cost and limits

Raw three-sample timings and environment are `before.json` and `after.json`.
These local payload-only measurements do not establish frame rate, memory or a
performance improvement. At one million rows:

| Input | Baseline median ms | Candidate median ms | Baseline / candidate bytes |
|---|---:|---:|---:|
| All finite | 0.68 | 0.67 | 21,736 / 21,736 |
| One missing row | 1.24 | 2.45 | 21,736 / 32,616 |
| Missing every 100th row | 2.04 | 197.87 | 21,744 / 332,568 |

The fragmented case is a material cost: per-run kernel calls, source identity
buffers and live draw calls preserve topology rather than silently bridging
10,001 runs. Batched gap-aware decimation/drawing is follow-up work. The renderer
issues one GL draw per nontrivial run, potentially 10,001 draws per frame in that
fixture; frame rate and peak memory were not measured. The current Rust M4
implementation already walks only occupied buckets; shrinking each
run's window is not a demonstrated fix for Python/FFI overhead.

Reproduce from either checkout, using its interpreter and source:

```bash
UV_CACHE_DIR=/workspace/.cache/uv PYTHONPATH="$PWD/python" \
  uv run --no-sync python /workspace/xy-gap-work/scripts/bench_line_gaps.py \
  --output /tmp/line-gap-payload.json
```

## Validation and scope

Focused gap suite: 24 passed, including plain/smooth/step/polar/log lines at
DPR 1 and 2, actual pointer hover requests, invalid-x ingest, all-missing and
singleton runs, native raster pixels, append rebuild/interpolation guards,
M4 refinement and retained-home source identity. Before the fix, the first six
regression cases all failed. Broader focused regression run: 520 passed,
5 skipped because optional pandas is absent, 1 browser PNG CLI case deselected
because its profile path is unavailable in this sandbox. Required full hooks,
Ruff check/format and the TypeScript/client build passed.

The cloud harness serves the unchanged HTML fixture on loopback because managed
Chromium rejects file URLs. This changes no chart assertion or browser policy.
The independent audit reran the 24-test suite successfully.

Area/error-band and stack baseline gaps, Arrow validity bitmaps, line brush
selection and many-run acceleration remain outside this line-only draft.
Hover/click identity handling touches files also changed by open PR 509; that is
a merge-conflict surface, not an implementation of its pending shared tooltip.
