# xy.pyplot vs Matplotlib performance

Profile: `standard`; repetitions: `21`; warm-ups: `3`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 200,000 samples | decimated | 19.37 ms | 128.8 ms | 6.65x | **FAIL** | xy.pyplot | 146.6 KiB | 91.6 KiB |
| scatter | 200,000 points | direct | 50.12 ms | 1162.8 ms | 23.20x | pass | xy.pyplot | 378.9 KiB | 255.3 KiB |
| histogram | 1,000,000 values / 200 bins | direct | 27.10 ms | 216.6 ms | 7.99x | **FAIL** | xy.pyplot | 84.3 KiB | 37.1 KiB |
| bar | 1,000 bars | direct | 26.51 ms | 637.1 ms | 24.03x | pass | xy.pyplot | 85.1 KiB | 29.7 KiB |
| pcolormesh | 200 x 300 cells | direct | 35.65 ms | 148.6 ms | 4.17x | **FAIL** | xy.pyplot | 428.9 KiB | 100.9 KiB |
| contour | 150 x 200 / 12 levels | direct | 20.41 ms | 136.7 ms | 6.69x | **FAIL** | xy.pyplot | 368.8 KiB | 287.3 KiB |

Geometric-mean xy total speedup: **9.69x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
