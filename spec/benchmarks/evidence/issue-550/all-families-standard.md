# xy.pyplot vs Matplotlib performance

Profile: `standard`; repetitions: `21`; warm-ups: `3`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 200,000 samples | decimated | 10.95 ms | 120.4 ms | 11.00x | pass | xy.pyplot | 146.6 KiB | 91.6 KiB |
| scatter | 200,000 points | direct | 33.21 ms | 1053.1 ms | 31.71x | pass | xy.pyplot | 378.9 KiB | 255.3 KiB |
| histogram | 1,000,000 values / 200 bins | direct | 18.02 ms | 188.5 ms | 10.46x | pass | xy.pyplot | 84.3 KiB | 37.1 KiB |
| bar | 1,000 bars | direct | 24.38 ms | 566.7 ms | 23.25x | pass | xy.pyplot | 85.1 KiB | 29.7 KiB |
| pcolormesh | 200 x 300 cells | direct | 27.26 ms | 139.4 ms | 5.11x | **FAIL** | xy.pyplot | 428.9 KiB | 100.9 KiB |
| contour | 150 x 200 / 12 levels | direct | 12.66 ms | 131.1 ms | 10.36x | pass | xy.pyplot | 368.8 KiB | 287.3 KiB |

Geometric-mean xy total speedup: **12.84x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
