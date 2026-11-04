# xy.pyplot vs Matplotlib performance

Profile: `smoke`; repetitions: `9`; warm-ups: `2`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 20,000 samples | decimated | 8.97 ms | 109.6 ms | 12.22x | pass | xy.pyplot | 146.7 KiB | 91.9 KiB |
| scatter | 25,000 points | direct | 16.34 ms | 257.2 ms | 15.74x | pass | xy.pyplot | 428.5 KiB | 309.8 KiB |
| histogram | 50,000 values / 100 bins | direct | 12.15 ms | 154.1 ms | 12.69x | pass | xy.pyplot | 83.2 KiB | 33.1 KiB |
| bar | 200 bars | direct | 11.42 ms | 214.6 ms | 18.79x | pass | xy.pyplot | 80.0 KiB | 27.8 KiB |
| pcolormesh | 80 x 120 cells | direct | 26.48 ms | 112.9 ms | 4.26x | **FAIL** | xy.pyplot | 269.9 KiB | 56.4 KiB |
| contour | 80 x 100 / 8 levels | direct | 10.61 ms | 128.5 ms | 12.11x | pass | xy.pyplot | 307.3 KiB | 234.8 KiB |

Geometric-mean xy total speedup: **11.54x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
