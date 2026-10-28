# Filled-run fidelity draft

Source baseline is `4dffbc763e2416dd8aaab82be6cf264f3229670e` (protocol 14/native ABI 48). The candidate extends connected geometry to areas and error bands under protocol 15, retaining ABI 48 unchanged. Native library SHA256 was `1f3c7f8e56e0356b068292f8bc96401d559c6b99cc210e95be030287c068eb97` in both source checkouts.

## Correctness

Previously, finite compaction joined the observations on either side of an invalid x, upper or baseline value. The candidate ships binary run boundaries and canonical source-row IDs; each finite run closes independently. A composed lower layer remains visible where an explicitly supplied upper layer has a gap. No missing contribution is replaced by zero and no stacking convenience API is added.

For decimated filled traces, M4 selection unions upper, baseline and thickness extrema. The former upper-only selection could remove a lower-bound peak or a width peak even when the upper boundary was flat. Zone metadata proves when a constant boundary makes one score mathematically sufficient. Direct finite geometry keeps its previous path; finite M4 geometry intentionally changes where the former selection lost boundary information.

SVG/native raster fill polygons, smooth upper/base curves, live fill and perimeter outlines, refined/home geometry and canonical hover use the same topology. Appending filled traces, selecting line/area points by brush and polar error bands remain outside the existing API; this patch does not extend those surfaces.

The implementation follows explicit disconnected-region semantics rather than data imputation. Primary comparison references: [Plotly gap controls](https://plotly.com/python/line-charts/#connect-data-gaps) and [Matplotlib fill-between polygon regions](https://matplotlib.org/stable/api/_as_gen/matplotlib.axes.Axes.fill_between.html). No competitor timing claim is made.

## Evidence and reproduction

New tests in `tests/test_area_gaps.py` cover invalid x/y/base, area/error-band payload topology, two independently closed SVG regions, native empty-gap pixels, upper/base/thickness extrema, canonical hover, actual browser DPR1/2 +720→380→720 resizing, log/area-polar rendering and refined→home fallback. The first nine gap tests and the two finite-M4 extrema tests were run red before their respective fixes. Unsupported polar error-band combinations are excluded explicitly.

Actual before/after composed-area source fixtures and captures are under `/workspace/xy-area-gap-evidence`. The native upper-band gap contained 936 blue pixels before and zero after at720px; its finite band retained936. At380px, 960 became zero while the finite band remained960. Both layers' canonical arrays and trace count are retained. `generate.py`, `capture.mjs`, `export-proof.json` and `browser-proof.json` record source paths and measurements.

The saved environment blocks file URLs. `http_pytest.py` and `http_probe.mjs` in that evidence directory serve unchanged browser fixtures over loopback; no browser policy is altered.

```bash
cd /workspace/xy-area-gap-work
export UV_CACHE_DIR=/workspace/.cache/uv
export UV_PROJECT_ENVIRONMENT=/workspace/xy/.venv
export PYTHONPATH="$PWD/python"
export XY_NATIVE_LIB="$PWD/target/release/libxy_core.so"
node js/build.mjs
uv run --no-sync python /workspace/xy-area-gap-evidence/http_pytest.py -q tests/test_area_gaps.py
uv run --no-sync python scripts/bench_area_gaps.py output.json
```

Validation completed: 43 new connected-fill cases passed; the focused existing-plus-new regression selection passed 520 tests with one browser PNG CLI case deselected and one existing NumPy timezone warning. Client build, the six changed Python modules' targeted type check, full Ruff/format and all repository hooks passed. Independent audit evidence is `/workspace/fresh-area-audit/audit-report.md`; no native ABI or Rust implementation changed.

## Measured cost and limits

`benchmark-before.json` and `benchmark-after.json` contain all three raw payload-build samples for nine synthetic cases plus interpreter/platform/NumPy metadata. The benchmark excludes ingest, browser rendering and GPU time. Process peak RSS includes the entire process and is not a measured allocation delta.

For one million rows with both boundaries varying, the recorded median changes from0.98 to11.26ms, selected marks2718→5345 and payload32,616→85,528bytes. At one percent missing observations, the median changes2.29→19.74ms and payload32,616→494,260bytes. The baseline is semantically wrong at gaps and may omit baseline/thickness extrema; this is a correctness cost, not a speed improvement. Direct finite small-data timing is noisy and no general performance claim is supported.

Highly fragmented filled traces still require one draw per nontrivial run. FPS, peak GPU memory, out-of-core data, giant Arrow validity bitmaps and cross-platform/native-wheel coverage remain unmeasured. Current raw benchmarks precede the equivalent constant-boundary fast path; their general varying-boundary cases are unchanged by that optimization. Coordinate protocol15 server/client upgrades before adoption.
