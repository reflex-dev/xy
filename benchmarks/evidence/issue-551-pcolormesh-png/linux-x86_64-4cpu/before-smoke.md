# xy.pyplot vs Matplotlib performance

Profile: `smoke`; repetitions: `21`; warm-ups: `3`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 20,000 samples | decimated | 12.40 ms | 100.5 ms | 8.11x | **FAIL** | xy.pyplot | 146.7 KiB | 91.9 KiB |
| scatter | 25,000 points | direct | 18.86 ms | 236.8 ms | 12.55x | pass | xy.pyplot | 428.5 KiB | 309.8 KiB |
| histogram | 50,000 values / 100 bins | direct | 14.47 ms | 132.2 ms | 9.14x | **FAIL** | xy.pyplot | 83.2 KiB | 33.1 KiB |
| bar | 200 bars | direct | 14.96 ms | 182.2 ms | 12.18x | pass | xy.pyplot | 80.0 KiB | 27.8 KiB |
| pcolormesh | 80 x 120 cells | direct | 30.86 ms | 110.8 ms | 3.59x | **FAIL** | xy.pyplot | 269.9 KiB | 56.4 KiB |
| contour | 80 x 100 / 8 levels | direct | 14.83 ms | 119.2 ms | 8.03x | **FAIL** | xy.pyplot | 307.3 KiB | 234.8 KiB |

Geometric-mean xy total speedup: **8.30x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
