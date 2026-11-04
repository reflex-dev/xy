# Issue #550 evidence: line PNG export vs Matplotlib/Agg

Raw `bench_pyplot_vs_matplotlib.py` reports (schema-verified with
`scripts/verify_benchmark_report.py --kind pyplot-vs-matplotlib`) behind the
"Line export at fractional plot edges (#550)" section of
`spec/benchmarks/results.md`, which gives the summary table and the exact
reproduction commands.

- `before-<profile>-<n>.json`: base commit `5e58b12`, meaning its `python/xy`
  package via `PYTHONPATH` and its native library via `XY_NATIVE_LIB`. The
  current harness drove it, so each file's `environment.git` names the
  harness checkout, not the measured package.
- `after-<profile>-<n>.json`: this branch.
- `all-families-standard.{json,md}`: the full six-family standard gate run on
  this branch, for context. Only the line family is in scope for #550; other
  families that miss 10× on this host are tracked separately.

Runs alternate before/after per profile (`--family line`; smoke 3 reps / 1
warm-up, standard 21 / 3, huge 11 / 2). Host: Linux x86_64 Firecracker VM,
4 vCPUs, CPython 3.13.18, NumPy 2.5.1, Matplotlib 3.11.1, Rust 1.97.0. The
host is noisy, so compare speedup ratios within a pair rather than absolute
milliseconds across files.
