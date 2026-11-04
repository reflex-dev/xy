# #551 — pcolormesh PNG export versus Matplotlib/Agg

Raw reports from `benchmarks/bench_pyplot_vs_matplotlib.py` before and after
the #551 raster fixes. Each `*.json` carries the full environment block, every
timing sample, output byte counts, and the per-row xy render tier; each `*.md`
is the harness's rendered table. Every report passes
`scripts/verify_benchmark_report.py --kind pyplot-vs-matplotlib`.

- **Machine:** shared cloud container, Linux 6.18 x86_64, 4 logical CPUs.
  This is a noisy runner, not a controlled one; the before/after pairs were
  run back to back on the same container.
- **Software:** CPython 3.13.18, NumPy 2.5.1, Matplotlib 3.11.1, Rust 1.97.0,
  native xy core (`cargo build --release`).
- **Source:** `5e58b12` (`before-*`, the unmodified core loaded through
  `XY_NATIVE_LIB`) and the same commit plus the #551 changes (`after-*`). Both
  use the harness with the explicit `dpi=EXPORT_DPI` xy save call; the Python
  package is identical between the two, only the native core differs.
- **Output contract:** both arms produce nonblank 1800×840 PNGs; every xy row
  is tier `direct` for pcolormesh. xy PNG byte counts are identical before and
  after in every profile (the change is byte-identical by construction and by
  test).

| profile | workload | xy before | xy after | Matplotlib | speedup before | speedup after |
|---|---|---:|---:|---:|---:|---:|
| smoke (21 reps) | 80×120 cells | 30.86 ms | 7.12 ms | 107.4 ms | 3.59× | **15.07×** |
| standard (21 reps) | 200×300 cells | 29.39 ms | 9.48 ms | 127.2 ms | 4.36× | **13.42×** |
| huge (11 reps) | 400×600 cells | 29.78 ms | 16.42 ms | 222.2 ms | 7.72× | **13.53×** |

`after-standard` ran with `--target-speedup 10 --require-target` and exited 0:
every standard family clears 10×. The huge profile's 5M-value histogram row
(5.11×) misses the gate both before and after; it is a separate family and a
separate bottleneck (binning, not rasterization).

Reproduce (from the repository root, after `cargo build --release`):

```bash
MPLBACKEND=Agg uv run --no-sync python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile smoke --reps 21 --warmups 3 --json after-smoke.json --out after-smoke.md
MPLBACKEND=Agg uv run --no-sync python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile standard --reps 21 --warmups 3 --target-speedup 10 --require-target \
  --json after-standard.json --out after-standard.md
MPLBACKEND=Agg uv run --no-sync python benchmarks/bench_pyplot_vs_matplotlib.py \
  --profile huge --reps 11 --warmups 2 --json after-huge.json --out after-huge.md
# "before": build the parent commit's core elsewhere and point at it
XY_NATIVE_LIB=/path/to/base/target/release/libxy_core.so MPLBACKEND=Agg \
  uv run --no-sync python benchmarks/bench_pyplot_vs_matplotlib.py --profile smoke ...
```
