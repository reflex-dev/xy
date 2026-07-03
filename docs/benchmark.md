# Scatter benchmark: fastcharts vs Python charting libraries

The same scatter (a correlated 2-D cloud) at growing point counts, across
popular Python charting libraries, on four factors: **how many points each can
render, how fast, how much memory, and the render payload size.**

The cross-library harness lives in `benchmarks/bench_vs.py` and includes
optional adapters for fastcharts, matplotlib, seaborn, Plotly, Bokeh, Altair,
Datashader, and hvPlot/HoloViews. Missing libraries are reported as
`unavailable` rather than failing the run.

The 10M headline and full original tables below are **measured**, not cited —
produced by the CI `benchmark` job before the expanded adapter set landed
(Ubuntu, Python 3.12; fastcharts native core; Plotly via kaleido→PNG;
matplotlib `Agg`→PNG; memory via `tracemalloc` + `psutil`). The expanded adapter
table is a local benchmark run that validates the new adapters at 100k points.

Reproduce the current harness with:

```bash
pip install numpy matplotlib seaborn plotly kaleido bokeh altair datashader hvplot psutil
python benchmarks/bench_vs.py
```

The fastcharts-only arm also runs with no dependencies via
`benchmarks/bench_scatter_native.py`.

## Time to first render (data → pixels)

Byte counts and serialize time are **not** pixels. For the browser-rendered
libraries (fastcharts, Plotly-HTML, Bokeh, Altair, hvPlot) the static-export size
says nothing about how long the browser takes to parse the embedded JS, build the
scene, and paint — often the dominant cost (Bokeh/Altair ship megabytes of JS +
data the browser must execute). So the harness measures **time-to-first-render**
directly: `benchmarks/bench_vs.py --ttfr` loads each library's output in headless
Chromium and reads First Contentful Paint (`navigationStart → first paint`, JS
inlined, no CDN, via `benchmarks/_browser.py`). Raster libraries
(matplotlib/seaborn/datashader/Plotly-kaleido) already produced pixels at render,
so their TTFR = build + render.

This closes the biggest fairness gap: previously fastcharts' number excluded the
WebGL draw while the HTML libraries' numbers excluded the browser entirely — both
stopped before pixels existed. The CI `benchmark` job now runs the TTFR pass
(capped at 100k points, since each row launches a browser) and the numbers land
in `docs/benchmark_ci.md` / the `benchmark-report` artifact. Locally, fastcharts'
standalone-export TTFR under software GL (SwiftShader) is ~180 ms for a density
page; on real GPU hardware it is lower.

## Expanded adapter benchmark — 100k points

Measured locally with:

```bash
PYTHONPATH=python .venv/bin/python benchmarks/bench_vs.py \
  --sizes 1e3,1e4,1e5 --budget 20
```

Environment note: Cargo was not available in this shell, so the fastcharts row
uses the NumPy fallback backend. CI should regenerate these rows with the native
backend in the non-blocking benchmark job.

| Library | Render target | 100k total | Peak memory | Output bytes | Points/sec |
|---|---|---:|---:|---:|---:|
| fastcharts | binary payload, NumPy fallback | **1 ms** | **2 MB** | 781 KB | 156,985,881 |
| matplotlib | Agg PNG | 49 ms | 6 MB | 46 KB | 2,055,087 |
| seaborn | matplotlib PNG | 71 ms | 11 MB | 37 KB | 1,399,835 |
| Plotly `Scattergl` | Kaleido PNG | 2,018 ms | 22 MB | 61 KB | 49,558 |
| Plotly `Scatter` | Kaleido PNG | 2,835 ms | 22 MB | 107 KB | 35,269 |
| Bokeh canvas | standalone HTML | 75 ms | 14 MB | 2 MB | 1,327,770 |
| Bokeh WebGL | standalone HTML | 73 ms | 14 MB | 2 MB | 1,360,995 |
| Altair / Vega-Lite | standalone HTML | 1,846 ms | 35 MB | 5 MB | 54,171 |
| Datashader | PNG raster | 13 ms | 15 MB | 58 KB | 7,502,931 |
| hvPlot / HoloViews | Bokeh HTML | 95 ms | 17 MB | 2 MB | 1,052,353 |

---

## Headline — 10 M points

| library | total time | peak memory | render payload | points/sec |
|---|---|---|---|---|
| **fastcharts** | **86 ms** | **2 MB** | **768 KB** | 117,000,000 |
| matplotlib (Agg→PNG) | 3,230 ms | 553 MB | 41 KB PNG | 3,096,100 |
| Plotly `Scattergl` (→PNG) | 33,907 ms | 1,584 MB | 49 KB PNG | 294,923 |
| Plotly `Scatter` (SVG) | — did not finish (over budget at 3 M) | | | |

At 10 M points fastcharts is **~37× faster than matplotlib** and **~394× faster
than Plotly's WebGL path**, using **~250×–790× less memory**. Plotly's SVG path
never reached 10 M — it took 113 s at 3 M.

> Fairness note (important): fastcharts' "total" is *prepare-the-GPU-payload*
> (encode/bin kernel-side); matplotlib and Plotly "total" is *to pixels* (a PNG).
> Adding fastcharts' actual browser render — ~150 ms at 10 M under software GL
> (SwiftShader, measured separately by `benchmarks/bench_scatter_native.py --render`) — puts
> it at ~236 ms end-to-end: still ~14× faster than matplotlib and ~140× faster
> than Plotly-GL, at a fraction of the memory. On real GPU hardware the render is
> faster still. The cleanest apples-to-apples columns are **peak memory**,
> **payload size**, and the **ceiling**.

### Ceiling — largest N rendered under a 45 s budget

| library | max points |
|---|---|
| fastcharts | 10,000,000 (screen-bounded; not the real ceiling) |
| matplotlib | 10,000,000 |
| Plotly `Scattergl` | 10,000,000 |
| Plotly `Scatter` (SVG) | 3,000,000 |

fastcharts' 10 M here is just the largest N the harness generated; its render
cost is flat in N (density surface), so the practical ceiling is data *ingest*,
not draw — the design targets 100 M–1 B (dossier §2).

---

## Full measured tables

### fastcharts (native core; "render" = build GPU payload)

| N | build | render | total | peak mem | payload | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 1 ms | 1 ms | 1 ms | 0 MB | 8 KB | 772,927 |
| 10,000 | 1 ms | 1 ms | 1 ms | 0 MB | 78 KB | 8,803,220 |
| 100,000 | 1 ms | 1 ms | 2 ms | 2 MB | 781 KB | 63,485,614 |
| 1,000,000 | 4 ms | 6 ms | 10 ms | 2 MB | **768 KB** | 102,397,515 |
| 3,000,000 | 11 ms | 20 ms | 31 ms | 2 MB | **768 KB** | 96,223,689 |
| 10,000,000 | 35 ms | 51 ms | 86 ms | 2 MB | **768 KB** | 116,889,352 |

The payload flips from 8 B/pt (direct) to a **constant 768 KB** at the density
threshold (200 k) — 0.08 B/pt at 10 M. Peak memory stays at 2 MB regardless of N.

### matplotlib (`Agg`, `savefig` PNG)

| N | build | render | total | peak mem | PNG | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 41 ms | 197 ms | 238 ms | 4 MB | 19 KB | 4,206 |
| 10,000 | 20 ms | 128 ms | 148 ms | 1 MB | 61 KB | 67,681 |
| 100,000 | 23 ms | 139 ms | 162 ms | 6 MB | 53 KB | 618,438 |
| 1,000,000 | 56 ms | 413 ms | 469 ms | 56 MB | 43 KB | 2,132,624 |
| 3,000,000 | 103 ms | 974 ms | 1,076 ms | 166 MB | 43 KB | 2,787,179 |
| 10,000,000 | 287 ms | 2,943 ms | 3,230 ms | 553 MB | 41 KB | 3,096,100 |

Correct and robust to 10 M, but time and memory grow ∝ N; the fixed-size PNG
also means dense regions are overplotted (why density aggregation exists).

### Plotly `Scattergl` (WebGL; kaleido → PNG)

| N | build | render | total | peak mem | PNG | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 269 ms | 9,761 ms | 10,030 ms | 19 MB | 59 KB | 100 |
| 10,000 | 5 ms | 2,257 ms | 2,262 ms | 2 MB | 84 KB | 4,421 |
| 100,000 | 5 ms | 2,627 ms | 2,632 ms | 22 MB | 61 KB | 37,994 |
| 1,000,000 | 11 ms | 5,881 ms | 5,892 ms | 184 MB | 51 KB | 169,722 |
| 3,000,000 | 24 ms | 12,223 ms | 12,247 ms | 680 MB | 50 KB | 244,967 |
| 10,000,000 | 63 ms | 33,844 ms | 33,907 ms | 1,584 MB | 49 KB | 294,923 |

(The first row's 10 s is kaleido/Chromium cold-start.) Memory grows ∝ N and
crosses 1.5 GB at 10 M — consistent with the dossier's §1 multi-copy analysis.

### Plotly `Scatter` (SVG — one node per point)

| N | build | render | total | peak mem | out | points/sec |
|---|---|---|---|---|---|---|
| 1,000 | 15 ms | 2,040 ms | 2,055 ms | 1 MB | 60 KB | 487 |
| 10,000 | 5 ms | 2,559 ms | 2,564 ms | 2 MB | 106 KB | 3,901 |
| 100,000 | 5 ms | 5,858 ms | 5,863 ms | 22 MB | 107 KB | 17,057 |
| 1,000,000 | 14 ms | 43,867 ms | 43,880 ms | 184 MB | 106 KB | 22,789 |
| 3,000,000 | 23 ms | 113,400 ms | 113,423 ms | 804 MB | 78 MB | 26,450 |
| 10,000,000 | — | — | — | — | — | over budget |

The one-node-per-point wall (dossier §1): 44 s at 1 M, 113 s at 3 M, then it
falls over. This is the path fastcharts exists to replace.

---

## What the numbers show

1. **fastcharts is the only one flat in N.** Above the density threshold its
   payload (768 KB) and peak memory (2 MB) do not grow with point count, and
   total time grows only with the linear ingest/bin pass (35 ms to bin 10 M).
   matplotlib grows ∝ N in time *and* memory; both Plotly paths grow ∝ N in
   memory and render time.
2. **Memory is the starkest axis.** At 10 M: fastcharts 2 MB vs matplotlib
   553 MB vs Plotly-GL 1.58 GB. This is the §1/§27 thesis — one screen-bounded
   representation vs holding every point (and its copies) resident.
3. **The SVG path has a hard ceiling** (~1–3 M, then unusable) exactly as
   predicted; the WebGL path scales further but pays ∝ N memory and seconds of
   render time.

## Caveats

- Data generation is excluded from every timing (shared arrays).
- `render` is not identical across targets (PNG rasterize vs GPU-payload build);
  see the fairness note above. Memory, payload size, and the ceiling are the
  clean cross-library comparisons.
- fastcharts memory is Python-side `tracemalloc` peak; its GPU/native bytes are
  separate and itemized by `Figure.memory_report()` (§27). The payload column is
  the transport cost across the kernel→browser boundary.
- Single CI machine, one run; treat as order-of-magnitude, not a spec. Re-run in
  CI (`benchmark` job) or locally. No universal claims — every number is
  mode-scoped (dossier §2/§31).
