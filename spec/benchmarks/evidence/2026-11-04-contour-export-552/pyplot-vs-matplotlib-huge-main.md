# xy.pyplot vs Matplotlib performance

Profile: `huge`; repetitions: `11`; warm-ups: `2`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 1,000,000 samples | decimated | 27.05 ms | 195.1 ms | 7.21x | **FAIL** | xy.pyplot | 146.6 KiB | 90.3 KiB |
| scatter | 1,000,000 points | density | 41.28 ms | 5278.2 ms | 127.87x | pass | xy.pyplot | 289.1 KiB | 224.9 KiB |
| histogram | 5,000,000 values / 200 bins | direct | 59.59 ms | 263.6 ms | 4.42x | **FAIL** | xy.pyplot | 87.8 KiB | 43.0 KiB |
| bar | 5,000 bars | direct | 58.78 ms | 2957.4 ms | 50.31x | pass | xy.pyplot | 108.8 KiB | 30.7 KiB |
| pcolormesh | 400 x 600 cells | direct | 41.90 ms | 260.8 ms | 6.23x | **FAIL** | xy.pyplot | 622.4 KiB | 207.3 KiB |
| contour | 250 x 320 / 12 levels | direct | 22.71 ms | 145.0 ms | 6.38x | **FAIL** | xy.pyplot | 365.4 KiB | 288.3 KiB |

Geometric-mean xy total speedup: **14.19x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
