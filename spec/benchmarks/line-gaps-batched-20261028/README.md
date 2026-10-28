# Batched line-gap decimation

Baseline: exact integration commit `e74ed8c8`, native ABI 47. Candidate:
`cloud/line-gap-batched-m4`, native ABI 48. Both use renderer protocol 14 and
identical gap topology, canonical source rows and payload format.

The batch removes the Python/FFI call per run. It reuses the existing native M4
selection implementation and obtains the parallelism limit once per batch.
The Python-side finite-run mask remains unchanged. No area semantics or live
draw batching is included.

## Measured payload cost

Each JSON file contains all three samples per case, Python/platform/NumPy
versions and the exact imported source path. `environment.json` records native
library hashes, ABI and compiler/profile details. These are local measurements,
not a portable performance guarantee.

| Rows / fixture | ABI47 baseline median ms | ABI48 candidate median ms | Payload bytes, unchanged |
|---|---:|---:|---:|
| 100,000 / fragmented | 16.53 | 0.60 | 47,520 |
| 1,000,000 / finite | 0.44 | 0.54 | 21,736 |
| 1,000,000 / one gap | 1.84 | 2.35 | 32,616 |
| 1,000,000 / fragmented | 182.14 | 5.93 | 332,568 |

Fragmented means a missing value every 100 rows: 10,001 finite runs at one
million rows. The final emitted point count remains 24,380. Finite/one-gap
timings are noisy or slightly worse in this run; no general speed or
no-regression claim is made. Live draw count remains potentially 10,001 per
frame. Frame rate and peak memory were not measured and remain adoption gates.
`payload-hashes.json` records identical packed-binary and sorted-spec SHA256
values for baseline and candidate across all nine benchmark cases.

## Reproduction

Build the native library in each isolated checkout; do not replace a shared
checkout's library. From the candidate checkout:

```bash
CARGO_HOME=/workspace/.cargo RUSTUP_HOME=/workspace/.rustup \
  PATH=/workspace/.cargo/bin:$PATH cargo build --release --offline
UV_CACHE_DIR=/workspace/.cache/uv PYTHONPATH="$PWD/python" \
  XY_NATIVE_LIB="$PWD/target/release/libxy_core.so" \
  uv run --no-sync python scripts/bench_line_gaps.py --output /tmp/batch-candidate.json
```

For the baseline, use its ABI47 source and native library with the same
benchmark script. Compare every case's emitted count and payload bytes as well
as timing. Exact selected-row parity is checked in `tests/test_m4_runs_batch.py`.

## Validation

- Regression tests were written first: all 13 initial batch tests failed before
  implementation because the entry point did not exist.
- Final focused regression run: 515 passed, 5 optional-pandas skips and one
  browser PNG CLI case deselected due its sandbox profile path.
- Native suite: 145 passed. Existing ABI smoke: 140 checks passed.
- Fresh independent audit found no concrete correctness or native-safety defect;
  its 15,120 ABI47 comparisons and boundary canaries passed, as did 32 Python
  nonbrowser cases and 8 Rust M4 tests.

The ABI canary tests cover disjoint/overlapping/empty/out-of-range bounds,
insufficient output capacity, null pointers and oversized row metadata. Exact
parity cases include ties, duplicate x, empty windows, singleton/many runs,
transformed x, reset domains between runs and parallel-size windows. Existing
live line tests retain DPR1/2, actual hover identity and refined/home fallback.
