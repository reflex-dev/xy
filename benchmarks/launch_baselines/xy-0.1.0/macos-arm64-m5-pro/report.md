# Launch scatter benchmark baseline: static and interactive comparisons

**Status:** canonical launch baseline for `xy` 0.1.0. Future launch/release
comparisons should preserve these contracts and compare against the raw JSON
from this run; they should not silently replace it.

Run on 2026-07-13 using the same seeded `float32` x/y arrays at **10k, 100k,
1M, 10M, and 1B points**. “10” in the requested size list is interpreted as
10k, matching the preceding benchmark series.

The benchmark is split by output contract:

1. **Static:** validated 900×420 PNG from every library.
2. **Interactive:** validated first browser render from every library.

No static result is mixed into the interactive table.

## Metrics tracked for launch

| Benchmark | Tracked result | Render path |
|---|---|---|
| A | Static PNG time and peak process-tree RSS | CPU: `xy` native, Kaleido default, Matplotlib Agg |
| B | Interactive TTFR and Python/browser peak RSS | Default hardware WebGL; Matplotlib WebAgg |
| B-CPU | Interactive TTFR under browser CPU fallback | Forced ANGLE SwiftShader; Matplotlib remains Agg/WebAgg |

The fixed launch sizes are 10k, 100k, 1M, 10M, and 1B points. Successful
cells use three complete cold runs. Launch comparisons must retain the same
900×420 viewport, seeded float32 data, nonblank render oracle, 180-second limit,
36 GiB process-tree limit, and default library behavior. Any changed contract
must be reported as a new benchmark rather than appended to these tables.

## Benchmark A: static 900×420 PNG (CPU-rendered)

Percentage faster is calculated as `(competitor time / xy time - 1) × 100`.
Times are arithmetic mean ± sample standard deviation across three complete,
isolated cold runs.

| Points | `xy` native PNG | Plotly/Kaleido PNG | `xy` faster vs Plotly | Matplotlib/Agg PNG | `xy` faster vs Matplotlib | `xy` mode |
|---:|---:|---:|---:|---:|---:|---|
| 10k | **0.0085 ± 0.0002 s** | 1.8830 ± 0.0105 s | **222.63× (22,162.8%)** | 0.0234 ± 0.0001 s | **2.77× (176.6%)** | direct |
| 100k | **0.0108 ± 0.0004 s** | 1.9496 ± 0.0074 s | **181.33× (18,032.9%)** | 0.0475 ± 0.0003 s | **4.42× (341.5%)** | direct |
| 1M | **0.0114 ± 0.0013 s** | 2.6490 ± 0.0054 s | **232.18× (23,117.8%)** | 0.2946 ± 0.0006 s | **25.82× (2,482.2%)** | density |
| 10M | **0.0232 ± 0.0023 s** | 9.5834 ± 0.0094 s | **412.60× (41,160.3%)** | 2.7842 ± 0.0064 s | **119.87× (11,887.1%)** | density |
| 1B | **1.1452 ± 0.0389 s** | **failed on first guarded attempt** | — | **memory limit** | — | density |

### Static peak process-tree RSS

Plotly includes the Kaleido/Chrome processes required for its static export.

| Points | `xy` | Plotly/Kaleido | Matplotlib/Agg |
|---:|---:|---:|---:|
| 10k | 0.048 GiB | 1.410 GiB | 0.079 GiB |
| 100k | 0.051 GiB | 1.460 GiB | 0.078 GiB |
| 1M | 0.069 GiB | 1.799 GiB | 0.147 GiB |
| 10M | 0.283 GiB | 5.671 GiB | 0.834 GiB |
| 1B | 22.414 GiB | failed | >36 GiB; terminated |

RSS values are arithmetic means of successful runs. Failure cells have no
successful-run mean.

### Static interpretation

- Matplotlib/Agg rasterizes every scatter offset. It does not sample this
  `PathCollection`.
- Plotly Express chooses `scattergl`, then Kaleido starts Chrome and renders the
  complete trace to PNG. The cold Chrome startup dominates small rows.
- `xy` switches to a density representation at 1M and its native rasterizer
  paints that bounded representation. The 1B row does **not** draw one billion
  individual markers; it ingests one billion rows and produces a density image.
- All successful files decoded to exactly 900×420 and passed a nonblank-pixel
  oracle.

At 1B, Plotly reached 35.10 GiB observed RSS and Kaleido raised its internal
render timeout after about 119 seconds. Matplotlib crossed the 36 GiB safety
ceiling. Neither produced a PNG.

## Benchmark B: interactive first render (default GPU path)

Times are arithmetic mean ± sample standard deviation across three complete,
isolated cold Python + fresh-browser runs.

| Points | `xy` standalone | Plotly standalone | `xy` faster vs Plotly | Matplotlib WebAgg | `xy` faster vs Matplotlib | `xy` mode |
|---:|---:|---:|---:|---:|---:|---|
| 10k | **0.1533 ± 0.0079 s** | 0.5306 ± 0.0351 s | **3.46× (246.0%)** | 0.2095 ± 0.0177 s | **1.37× (36.6%)** | direct |
| 100k | **0.1742 ± 0.0029 s** | 0.5368 ± 0.0031 s | **3.08× (208.2%)** | 0.2383 ± 0.0007 s | **1.37× (36.8%)** | direct |
| 1M | **0.1688 ± 0.0081 s** | 0.7856 ± 0.0030 s | **4.65× (365.4%)** | 0.4769 ± 0.0052 s | **2.83× (182.5%)** | density + sample |
| 10M | **0.1797 ± 0.0007 s** | 3.6434 ± 0.1543 s | **20.28× (1,927.7%)** | 3.0029 ± 0.0210 s | **16.71× (1,571.3%)** | density + sample |
| 1B | **1.2530 ± 0.0018 s** | **memory limit** | — | **memory limit** | — | density + sample |

Interactive TTFR definitions:

- **`xy`:** figure construction + standalone HTML + fresh Chrome + WebGL draw
  + two animation frames + GPU fence + nonblank readback.
- **Plotly:** figure construction + standalone HTML + fresh Chrome + Plotly
  ready + two animation frames + GPU fence + nonblank readback.
- **Matplotlib WebAgg:** figure construction + built-in live WebAgg server +
  fresh Chrome + Python Agg draw + WebSocket image delivery + nonblank
  900×420 browser canvas.

### Interactive peak RSS

Python and browser process trees are separate columns. Chrome has an observed
baseline near 0.97 GiB on this machine.

| Points | `xy` Python | `xy` browser | Plotly Python | Plotly browser | WebAgg Python | WebAgg browser |
|---:|---:|---:|---:|---:|---:|---:|
| 10k | 0.045 | 0.973 | 0.171 | 1.067 | 0.087 | 0.967 |
| 100k | 0.051 | 0.998 | 0.183 | 1.104 | 0.091 | 0.991 |
| 1M | 0.048 | 0.990 | 0.311 | 1.376 | 0.157 | 0.997 |
| 10M | 0.278 | 0.988 | 1.819 | 3.792 | 0.842 | 1.333 |
| 1B | 22.415 | 0.989 | >36 observed | — | >36 observed | — |

Values are GiB. Failure-row values are the highest observed before termination,
not successful steady-state peaks. Successful values are means across runs.

## Benchmark B-CPU: interactive first render with software rendering

Chrome was forced to ANGLE SwiftShader (`--use-angle=swiftshader` and
`--enable-unsafe-swiftshader`). This is the interactive CPU-fallback test; it
still starts a fresh browser for every sample.

| Points | `xy` software | Plotly software | `xy` faster vs Plotly | Matplotlib WebAgg software-browser | `xy` faster vs Matplotlib | `xy` mode |
|---:|---:|---:|---:|---:|---:|---|
| 10k | **0.9580 ± 0.0103 s** | 1.3693 ± 0.0312 s | **1.43× (42.9%)** | 1.2121 ± 0.0258 s | **1.27× (26.5%)** | direct |
| 100k | **0.9752 ± 0.0048 s** | 1.4639 ± 0.0047 s | **1.50× (50.1%)** | 1.2102 ± 0.0305 s | **1.24× (24.1%)** | direct |
| 1M | **0.9678 ± 0.0039 s** | 2.0416 ± 0.0250 s | **2.11× (111.0%)** | 1.2780 ± 0.0351 s | **1.32× (32.1%)** | density + sample |
| 10M | **0.9920 ± 0.0078 s** | 8.2152 ± 0.0707 s | **8.28× (728.1%)** | 3.6735 ± 0.0099 s | **3.70× (270.3%)** | density + sample |
| 1B | **2.0877 ± 0.0063 s** | **memory limit** | — | **memory limit** | — | density + sample |

There is no separate static CPU-fallback table because Benchmark A already is
the CPU path: `xy` uses its native CPU rasterizer, Matplotlib uses Agg, and the
installed Kaleido/Choreographer configuration disables GPU by default. Repeating
it under another “CPU” label would duplicate Benchmark A.

### Interactive interpretation

- Matplotlib really is interactive here: the built-in WebAgg backend supplies
  pan/zoom controls through a live Python server and browser canvas.
- WebAgg still retains every point. At 1B, its `PathCollection` oracle confirmed
  exactly 1,000,000,000 offsets. It started the browser but did not deliver a
  nonblank first frame within the total 180-second budget.
- Plotly sends all points into its browser figure. It completed through 10M; its
  1B Python process exited via SIGKILL at 32.64 GiB observed RSS before the
  browser phase.
- `xy` keeps exact source data in Python, but its overview browser payload is
  density + a stable sample. At deep zoom it can request exact visible points.
  This changes the scaling regime and is the default feature under test.

## What “default” means here

| Library | Static path | Interactive path | Large-scatter reduction |
|---|---|---|---|
| `xy` | Native `to_png()` | Standalone WebGL | Automatic density + stable overlay + exact drilldown |
| Plotly | `to_image()` through Kaleido | Standalone Plotly HTML | None; `px.scatter` auto-selects WebGL but retains all rows |
| Matplotlib | Agg `savefig()` | Built-in WebAgg | None; rerenders the full `PathCollection` |

Plotly documents that `px.scatter(render_mode="auto")` automatically selects
WebGL above 1,000 rows; this changes the renderer, not the number of rows.
[Plotly performance guide](https://plotly.com/python/performance/)

Matplotlib documents WebAgg as an interactive browser backend built on Agg.
[Matplotlib WebAgg documentation](https://matplotlib.org/stable/api/backend_webagg_core_api.html)

## Shared methodology

- Input: identical seeded correlated-Gaussian `float32` x/y arrays; 8 bytes per
  source row.
- Data generation and library imports excluded from elapsed render time; their
  resident memory remains included.
- Chart target: 900×420 pixels/CSS pixels.
- Three complete isolated cold runs per successful library/size cell; each
  interactive run also starts a fresh browser.
- Tables report arithmetic mean ± sample standard deviation. Memory tables
  report arithmetic mean peak RSS across successful runs.
- A terminal 1B failure is attempted once and not averaged; repeating an
  OOM/timeout cannot produce a successful timing distribution.
- Guardrail: 180 seconds and 36 GiB per process tree.
- RSS sampled from complete process trees every 50 ms; very brief peaks may be
  missed.
- Successful static rows require a decodable, nonblank 900×420 PNG.
- Successful interactive rows require a visible, nonblank 900×420 chart surface
  in fresh Chrome.

## Environment

- Apple M5 Pro: 18-core CPU, 20-core GPU, 64 GB RAM
- macOS 26.5.2 arm64
- Google Chrome 150.0.7871.115
- Python 3.14.5
- NumPy 2.5.1
- `xy` 0.1.0, commit `7228f99fd1bdefdb8026d146b5f6d32d685f8e30`
- Plotly 6.9.0
- Kaleido 1.3.0
- Matplotlib 3.11.0
- Tornado 6.5.7 for WebAgg
- Seed `20260713`

## Conclusions

Static and interactive workloads lead to different decisions:

- **Static:** Matplotlib is a strong exact brute-force baseline, but `xy`'s
  native density-aware export scales much further. Plotly's cold Kaleido path
  carries a large browser-startup cost.
- **Interactive through 10M:** all three complete. `xy` remains near browser
  startup cost because its automatic LOD bounds the representation; Plotly and
  WebAgg scale with the complete point count.
- **Interactive at 1B:** only `xy` reaches first render within the limits, by
  rendering an aggregate overview while retaining source data for drilldown.
- **CPU fallback:** forcing SwiftShader adds roughly 0.8 seconds of cold-browser
  overhead to `xy`, but its bounded large-data representation still keeps 1M
  and 10M near one second. Plotly's software path rises to 8.22 seconds at 10M;
  WebAgg reaches 3.67 seconds.

The defensible headline is not “`xy` draws 1B markers.” It is:

> `xy` ingested 1B points and produced both a validated static density PNG in
> 1.145 s mean and a validated interactive density overview in 1.253 s mean,
> while the
> default exact-point Plotly and Matplotlib paths did not complete at that size
> within the 36 GiB/180-second limits.

## Limitations

- One machine, platform, and browser; three runs quantify local repeatability
  but do not establish cross-machine performance.
- `xy` aggregate output and Plotly/Matplotlib exact-point rendering are
  intentionally different default product semantics.
- WebAgg requires a live Python/Tornado server and is not self-contained HTML.
- Plotly/Kaleido startup can be amortized in a persistent export service; these
  are isolated cold exports.
- Browser RSS includes Chrome overhead and does not measure GPU memory.
- Plotly's 1B SIGKILL is likely memory pressure, but the OS supplied no explicit
  OOM diagnosis.
- Timeout/memory-limit results are local guarded outcomes, not universal hard
  limits.

## Reproduce

```bash
BASELINE=benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro
uv sync --project "$BASELINE" --frozen --python 3.14.5

# Repeated static + default interactive benchmarks
uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --out launch-scatter-default.json

# Repeated interactive CPU/software fallback
uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --interactive-only --software \
  --out launch-scatter-cpu-fallback.json
```
