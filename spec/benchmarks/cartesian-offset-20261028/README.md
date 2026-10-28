# Cartesian offset precision, 2026-10-28

Baseline: integration `fbc2e92f` (protocol 15, native ABI 48). This correctness
change restores the intended §16 encoded affine transform for Cartesian linear
axes. It does not change wire buffers, canonical CPU f64 data, selection identity,
LOD selection, curves, native ABI, or the nonlinear/polar transform.

The baseline independently reproduces transparent framebuffer pixels where a
three-point blue line at 1e9+450 and 1e12+450 should cross the CPU projection
at y=29.25 CSS pixels. The zero-offset case passes. With a 1e12 baseline, the
combined line/scatter/area fixture loses all visible geometry; the candidate
restores the same data-space placement as the native renderer (layout/font
metrics differ between native and browser).

The old vertex path decoded small encoded values into absolute f32 coordinates,
then applied two large affine terms with cancellation. The candidate composes
`encoded * mul + add` in CPU f64 separately for every column. Cartesian linear
`*meta` uniforms carry `(add,mul)`; their meaning is selected by the shared
`u_encodedLinear` uniform. Polar and log/symlog retain raw decode metadata and
their existing precision limits. Different endpoint/baseline encoding windows
must never share one column's composed affine.

Reproduce the pixel tests after building the source client:

```sh
node js/build.mjs
PYTHONPATH=python XY_NATIVE_LIB="$PWD/target/release/libxy_core.so" \
  uv run --no-sync pytest -q tests/test_offset_precision.py
```

The managed cloud Chromium policy rejects file URLs; the recorded run substitutes
only the test transport with a loopback HTTP server, retaining all assertions.
30 tests cover offset 0/1e9/1e12 line/scatter/area at DPR1/2, 720/380 CSS widths,
line/area refinement and retained-home fallback, plus numeric and datetime
modern-epoch X over a 100ms span with log Y. The framebuffer is read directly at
CPU-projected mark centers, with GL errors checked. These are bounded correctness
fixtures, not an arbitrary zoom-depth or all-coordinate-system precision claim.

Generate the comparable chart and native export with the chosen checkout on
`PYTHONPATH`:

```sh
PYTHONPATH=python python spec/benchmarks/cartesian-offset-20261028/generate.py /tmp/offset-chart
```

Browser evidence uses Chromium 151, ANGLE SwiftShader, DPR1, viewport740×380,
fixed chart720×360, legends/modebar disabled, deterministic synthetic data.
Assets: `spec/assets/cartesian-offset-{before,after,native}.png`. The before and
after browser sources are separately built checkouts; native data/exports are
unchanged. Large-offset automatic tick labels still repeat their rounded text;
this change fixes mark geometry and makes no tick-label usability claim.
No performance measurement or speed claim accompanies this fix.

Recorded candidate runs: 30 precision cases passed in 94.60s; 75 related cases
passed in 145.11s (`test_zoom_precision.py`, `test_symlog_axis.py`,
`test_polar_client_regressions.py`, `test_line_gap_batch_draw.py`). Source build,
full-worktree Ruff check/format, and repository pre-commit hooks also passed.

Independent frozen-source GPU audit passed 28 broad chart sets plus 8 additional
sets. Zero-offset and polar framebuffers match the baseline exactly. Translated
1e12 segment, triangle, mixed, ribbon, compact/rectangular bar, and secondary
linear-Y2 with primary-log-Y fixtures match their zero-offset geometry at DPR1/2.
Mixed nonlinear compact-bar DPR2 comparisons differ by at most one intensity
level (853 log / 559 symlog channels); DPR1 is exact, without geometry drift.
The audit found no blocking defect. The separate audit artifacts remain in
`/workspace/fresh-gpu-audit`; the parent integration records their final report.
