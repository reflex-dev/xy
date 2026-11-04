# Contour PNG export vs Matplotlib/Agg — issue #552 evidence (2026-11-04)

Raw, verifier-checked reports behind the contour PNG export fix recorded in
[`results.md`](../../results.md#contour-png-export-issue-552). Each profile ran
the unmodified-`main` arm and this branch's arm back to back, interleaved
profile by profile, on the same machine and in the same environment.

| file | what |
|---|---|
| `pyplot-vs-matplotlib-<profile>-main.{json,md}` | audited source `5e58b12` (native core and `python/xy` from that commit) |
| `pyplot-vs-matplotlib-<profile>-branch.{json,md}` | this branch (`farhan/issue-552-contour-png-export-perf`) |

Both arms ran the same harness file — this branch's
`benchmarks/bench_pyplot_vs_matplotlib.py`, which carries the one-line export
DPI correction (`fig.savefig(out, format="png", dpi=EXPORT_DPI)`) the issue
names as a prerequisite. Without it the xy arm emits 900×420 and fails the
1800×840 dimension oracle, so `main` cannot be measured with its own copy.
The JSON `environment.git` block therefore reports `5e58b12 dirty` for both arms; the
arm is identified by the file name.

## Environment

- Linux x86_64 cloud VM, 4 logical CPUs (Intel Xeon @ 2.80 GHz), shared tenancy
- CPython 3.13.18, NumPy 2.5.1, Matplotlib 3.11.1 (Agg), native XY core
- rustc 1.97.0, release profile (`lto = "fat"`, `codegen-units = 1`)
- Full metadata, including package versions, is in each JSON's `environment`

This is not the issue's 12-CPU workstation (Python 3.14, Matplotlib 3.11.0),
and its absolute times are slower. Compare ratios within one machine. On this
VM `main`'s smoke contour row measured 7.15× against the issue's 8.50×.

## Reproduce

```bash
cargo build --release
uv sync --extra matplotlib --group dev
H=benchmarks/bench_pyplot_vs_matplotlib.py
MPLBACKEND=Agg uv run --no-sync python $H --profile smoke    --reps 9  --warmups 2 --target-speedup 10 --json smoke.json    --out smoke.md
MPLBACKEND=Agg uv run --no-sync python $H --profile standard --reps 21 --warmups 3 --target-speedup 10 --json standard.json --out standard.md
MPLBACKEND=Agg uv run --no-sync python $H --profile huge     --reps 11 --warmups 2 --target-speedup 10 --json huge.json     --out huge.md
python scripts/verify_benchmark_report.py standard.json --kind pyplot-vs-matplotlib
```

The `main` arm reran the same commands with `PYTHONPATH=<main worktree>/python`
and `XY_NATIVE_LIB=<main build>/libxy_core.so`. Add `--require-target` to gate.
That exits nonzero here because pcolormesh misses 10× in every profile. That gap
predates this change and is not part of #552.

## Contour rows (medians; p95 in the JSON)

| profile | workload | arm | xy build | xy render | xy total | Matplotlib total | speedup | xy PNG bytes |
|---|---|---|---:|---:|---:|---:|---:|---:|
| smoke | 80×100 / 8 levels | main | 0.65 ms | 17.70 ms | 18.32 ms | 130.9 ms | 7.15× | 314,653 |
| smoke | 80×100 / 8 levels | branch | 0.61 ms | 9.99 ms | 10.61 ms | 128.5 ms | **12.11×** | 314,653 |
| standard | 150×200 / 12 levels | main | 0.71 ms | 19.68 ms | 20.41 ms | 136.7 ms | 6.69× | 377,687 |
| standard | 150×200 / 12 levels | branch | 0.71 ms | 12.11 ms | 12.84 ms | 139.8 ms | **10.88×** | 377,687 |
| huge | 250×320 / 12 levels | main | 0.92 ms | 21.83 ms | 22.71 ms | 145.0 ms | 6.38× | 374,133 |
| huge | 250×320 / 12 levels | branch | 0.94 ms | 14.46 ms | 15.35 ms | 143.1 ms | 9.32× | 374,133 |

Every row is the `direct` tier: all segments are painted, with no decimation.
Both arms emit 1800×840 PNGs with identical byte counts and lit-pixel counts.
Byte-for-byte identity of all 18 family×profile PNGs was checked separately
against `main`; see `results.md`.
