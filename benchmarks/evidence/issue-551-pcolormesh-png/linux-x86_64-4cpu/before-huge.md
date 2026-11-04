# xy.pyplot vs Matplotlib performance

Profile: `huge`; repetitions: `11`; warm-ups: `2`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 1,000,000 samples | decimated | 27.50 ms | 175.0 ms | 6.37x | **FAIL** | xy.pyplot | 146.6 KiB | 90.3 KiB |
| scatter | 1,000,000 points | density | 30.36 ms | 4681.9 ms | 154.20x | pass | xy.pyplot | 289.1 KiB | 224.9 KiB |
| histogram | 5,000,000 values / 200 bins | direct | 51.32 ms | 229.6 ms | 4.47x | **FAIL** | xy.pyplot | 87.8 KiB | 43.0 KiB |
| bar | 5,000 bars | direct | 37.14 ms | 2329.8 ms | 62.73x | pass | xy.pyplot | 108.8 KiB | 30.7 KiB |
| pcolormesh | 400 x 600 cells | direct | 29.78 ms | 229.8 ms | 7.72x | **FAIL** | xy.pyplot | 622.4 KiB | 207.3 KiB |
| contour | 250 x 320 / 12 levels | direct | 16.94 ms | 119.4 ms | 7.05x | **FAIL** | xy.pyplot | 365.4 KiB | 288.3 KiB |

Geometric-mean xy total speedup: **15.70x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
