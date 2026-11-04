# xy.pyplot vs Matplotlib performance

Profile: `huge`; repetitions: `11`; warm-ups: `2`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 1,000,000 samples | decimated | 15.31 ms | 183.1 ms | 11.96x | pass | xy.pyplot | 146.6 KiB | 90.3 KiB |
| scatter | 1,000,000 points | density | 27.01 ms | 4724.1 ms | 174.91x | pass | xy.pyplot | 289.1 KiB | 224.9 KiB |
| histogram | 5,000,000 values / 200 bins | direct | 44.73 ms | 228.5 ms | 5.11x | **FAIL** | xy.pyplot | 87.8 KiB | 43.0 KiB |
| bar | 5,000 bars | direct | 33.18 ms | 2468.3 ms | 74.39x | pass | xy.pyplot | 108.8 KiB | 30.7 KiB |
| pcolormesh | 400 x 600 cells | direct | 16.42 ms | 222.2 ms | 13.53x | pass | xy.pyplot | 622.4 KiB | 207.3 KiB |
| contour | 250 x 320 / 12 levels | direct | 12.36 ms | 126.2 ms | 10.21x | pass | xy.pyplot | 365.4 KiB | 288.3 KiB |

Geometric-mean xy total speedup: **21.88x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
