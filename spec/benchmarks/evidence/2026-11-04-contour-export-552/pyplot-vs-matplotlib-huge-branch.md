# xy.pyplot vs Matplotlib performance

Profile: `huge`; repetitions: `11`; warm-ups: `2`; target: `1800 x 840 PNG`.

| family | workload | xy tier | xy total | Matplotlib total | xy total speedup | target | winner | xy PNG | Matplotlib PNG |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| line | 1,000,000 samples | decimated | 19.69 ms | 208.1 ms | 10.57x | pass | xy.pyplot | 146.6 KiB | 90.3 KiB |
| scatter | 1,000,000 points | density | 32.46 ms | 5359.3 ms | 165.10x | pass | xy.pyplot | 289.1 KiB | 224.9 KiB |
| histogram | 5,000,000 values / 200 bins | direct | 55.26 ms | 274.6 ms | 4.97x | **FAIL** | xy.pyplot | 87.8 KiB | 43.0 KiB |
| bar | 5,000 bars | direct | 50.36 ms | 3001.3 ms | 59.60x | pass | xy.pyplot | 108.8 KiB | 30.7 KiB |
| pcolormesh | 400 x 600 cells | direct | 27.29 ms | 261.4 ms | 9.58x | **FAIL** | xy.pyplot | 622.4 KiB | 207.3 KiB |
| contour | 250 x 320 / 12 levels | direct | 15.35 ms | 143.1 ms | 9.32x | **FAIL** | xy.pyplot | 365.4 KiB | 288.3 KiB |

Geometric-mean xy total speedup: **18.94x**.
Per-family 10.00x target: **FAIL**.

Method:

- Both libraries receive the same pre-generated arrays and Matplotlib-style calls.
- Both outputs are validated as nonblank PNGs with identical pixel dimensions.
- `total` is the comparable chart-to-compressed-pixels metric. `build` alone is not a headline metric because xy defers work until export.
- The `xy tier` column discloses every render-tier decision (`direct` paints all marks, `decimated` is the M4-reduced series, `density` is a screen-bounded aggregate) — aggregation is never silent. Matplotlib always paints every mark.
- Imports, data generation, and warm-up renders are outside the timed samples; raw samples remain in the JSON report.
- This measures static notebook/report output. Interactive WebGL zoom/pan is covered separately by `bench_interaction.py`; Matplotlib/Agg has no equivalent client-side interaction path.
