# xy.pyplot vs Matplotlib performance

Profile: `smoke`; repetitions: `9`; warm-ups: `2`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 20,000 samples | decimated | 15.92 ms | 113.4 ms | 7.13x | **FAIL** | xy.pyplot | 146.7 KiB | 91.9 KiB |
| scatter | 25,000 points | direct | 23.47 ms | 283.5 ms | 12.07x | pass | xy.pyplot | 428.5 KiB | 309.8 KiB |
| histogram | 50,000 values / 100 bins | direct | 18.63 ms | 153.9 ms | 8.26x | **FAIL** | xy.pyplot | 83.2 KiB | 33.1 KiB |
| bar | 200 bars | direct | 19.70 ms | 217.0 ms | 11.02x | pass | xy.pyplot | 80.0 KiB | 27.8 KiB |
| pcolormesh | 80 x 120 cells | direct | 36.30 ms | 114.0 ms | 3.14x | **FAIL** | xy.pyplot | 269.9 KiB | 56.4 KiB |
| contour | 80 x 100 / 8 levels | direct | 18.32 ms | 130.9 ms | 7.15x | **FAIL** | xy.pyplot | 307.3 KiB | 234.8 KiB |

Geometric-mean xy total speedup: **7.48x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
