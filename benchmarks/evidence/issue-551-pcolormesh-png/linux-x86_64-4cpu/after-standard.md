# xy.pyplot vs Matplotlib performance

Profile: `standard`; repetitions: `21`; warm-ups: `3`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 200,000 samples | decimated | 9.50 ms | 111.2 ms | 11.70x | pass | xy.pyplot | 146.6 KiB | 91.6 KiB |
| scatter | 200,000 points | direct | 34.31 ms | 1030.0 ms | 30.02x | pass | xy.pyplot | 378.9 KiB | 255.3 KiB |
| histogram | 1,000,000 values / 200 bins | direct | 17.16 ms | 188.6 ms | 10.99x | pass | xy.pyplot | 84.3 KiB | 37.1 KiB |
| bar | 1,000 bars | direct | 14.08 ms | 549.5 ms | 39.02x | pass | xy.pyplot | 85.1 KiB | 29.7 KiB |
| pcolormesh | 200 x 300 cells | direct | 9.48 ms | 127.2 ms | 13.42x | pass | xy.pyplot | 428.9 KiB | 100.9 KiB |
| contour | 150 x 200 / 12 levels | direct | 10.62 ms | 124.0 ms | 11.67x | pass | xy.pyplot | 368.8 KiB | 287.3 KiB |

Geometric-mean xy total speedup: **16.94x**.
Per-family 10.00x target: **PASS**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
