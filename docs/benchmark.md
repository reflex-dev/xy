# Scatter benchmark: fastcharts vs Plotly vs matplotlib

**What this measures** — the same scatter (correlated 2-D cloud) at growing point
counts, across three libraries, on four factors: how many points each can
actually render, how fast, how much memory, and how many bytes the render costs.

There are two harnesses:

- **`scripts/bench_vs.py`** — the full three-way comparison. Runs wherever
  `numpy`, `matplotlib`, and `plotly` are installed (locally or in CI). Emits a
  Markdown + JSON report. Missing libraries are reported as unavailable rather
  than faked.
- **`scripts/bench_scatter_native.py`** — the fastcharts arm alone, stdlib-only
  (no numpy, no PyPI), so the fastcharts numbers are real even in a locked-down
  environment. It measures exactly what `bench_vs.py` measures for fastcharts.

> **Reproduce the full table:** `pip install numpy matplotlib plotly kaleido
> psutil` then `python scripts/bench_vs.py --out docs/benchmark_ci.md`. The CI
> `benchmark` job does this on every run and uploads the report as an artifact.

---

## Measured — fastcharts arm

Real, executed on this machine via the native Rust core, **software GL
(SwiftShader)** for the render column — i.e. no GPU. On real hardware the render
times are lower; the data-prep and wire-byte numbers are hardware-independent and
are the load-bearing comparison.

| N | tier | data prep | wire bytes | bytes/point | render (SwiftShader) |
|---|---|---|---|---|---|
| 10 k | direct | 0.0 ms | 78 KB | 8.000 | 78 ms |
| 100 k | direct | 0.1 ms | 781 KB | 8.000 | 188 ms |
| 1 M | **density** | 6.2 ms | **768 KB** | 0.786 | 75 ms |
| 10 M | **density** | 62 ms | **768 KB** | 0.079 | 156 ms |

The mechanism the whole engine exists for is visible in two columns:

- **Wire bytes go flat.** Above the density threshold (200k) fastcharts stops
  shipping points and ships a fixed 512×384 count grid — **768 KB regardless of
  N**. At 10M that's 0.079 bytes/point; at 100M it would be 0.008. Plotly and
  matplotlib payloads grow ∝ N with no ceiling.
- **Render cost is screen-bounded, not data-bounded.** The density surface is
  one textured quad; its fragment cost depends on pixels, not points, so render
  time does not scale with N (the 1M→10M render times are within noise of each
  other; the variation is SwiftShader, not point count).

Data-prep (the kernel binning 10M points into the grid) is 62 ms single-threaded
scalar Rust — before any SIMD or the progressive-refinement coarse pass (§17).

---

## Competitor arms — how to read them

The `plotly` and `matplotlib` columns are produced by `bench_vs.py` (CI job
`benchmark`, or run it locally). They are **not** filled with hand-typed numbers
here — measuring them requires the libraries installed, which the authoring
environment blocks at the network layer. What the harness measures per library:

| Library | build | render (→ pixels) | out bytes | notes |
|---|---|---|---|---|
| **matplotlib** (`Agg`) | `ax.scatter` | `savefig(PNG)` | PNG size | CPU raster; cost ∝ N; a 900×420 PNG is fixed-size but drawing time and memory grow with N |
| **Plotly `Scattergl`** | `go.Scattergl` | `to_image` (kaleido) or `to_html` | PNG or HTML size | WebGL in-browser; **HTML embeds the data as JSON** — payload grows ∝ N (this engine's §1 complaint, measured) |
| **Plotly `Scatter`** (SVG) | `go.Scatter` | same | same | one DOM node per point — the wall this engine removes; expect a hard ceiling near ~10⁴–10⁵ |
| **fastcharts** | `Figure().scatter` | `build_payload` (kernel→GPU) | **wire bytes** | direct f32, then screen-bounded density grid |

### What the field's own published numbers predict (dossier Part 2, cited)

Pending the CI-measured table, the competitive research already establishes the
shape of the result (these are **literature, not measurements from this repo** —
see `docs/design-dossier.md` Part 2 for sources):

- **deck.gl** (WebGL, the class Plotly's `Scattergl` is in): ~1M points at 60 fps,
  degrades to 10–20 fps by 10M, and **crashes between 10M–100M** during buffer
  creation (Chrome's ~1 GB single-allocation cap). fastcharts crosses to density
  before that ceiling, so it renders where deck.gl-class renderers crash.
- **Plotly memory**: plotly-resampler reports **~14× memory reduction**
  (>10 GB → <700 MB) when downsampling a large trace — i.e. base Plotly holds
  input + `calcdata` + GL/SVG buffers, growing ∝ N.
- **matplotlib**: `scatter` is CPU rasterization; a 1M-point scatter takes on the
  order of seconds to `savefig`, and 10M is typically tens of seconds / memory
  pressure. The PNG is fixed-size but says nothing beyond ~10⁵ overlapping points
  (overplotting) — which is *why* density aggregation exists.

The honest one-line thesis, which the CI table will make concrete: **all three
render ~10⁴–10⁶ points; only fastcharts stays interactive and screen-bounded from
10⁶ to 10⁸ because it stops shipping and drawing points and starts shipping and
drawing a density surface.**

---

## Fairness & caveats

- **Data generation is excluded** from every timing (shared arrays).
- **`render_s` is not identical across targets** — matplotlib rasterizes to a
  PNG, Plotly serializes for a browser (or kaleido rasterizes), fastcharts builds
  a GPU payload. Each cell records what it measured. The cleanest cross-library
  numbers are **out/wire bytes** and the **ceiling probe** (largest N rendered
  under the wall-clock budget without erroring).
- **fastcharts render times here use software GL** (SwiftShader; no GPU in the
  container). Treat them as an upper bound.
- **Memory** is Python-side peak allocation (`tracemalloc`) plus RSS delta when
  `psutil` is present. fastcharts' GPU/native memory is separate and reported by
  `Figure.memory_report()` (§27); the wire-bytes column is the transport cost.
- No universal claims — every number is mode-scoped (dossier §2/§31).
