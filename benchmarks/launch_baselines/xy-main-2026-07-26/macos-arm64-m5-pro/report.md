# Launch scatter benchmark refresh: static and interactive comparisons

**Status:** current published baseline for the README and the public benchmarks
page. This is a controlled rerun of the canonical `xy` 0.1.0 launch baseline
(`../../xy-0.1.0/macos-arm64-m5-pro/`), which remains committed and unchanged.

Run on 2026-07-26 with the same seeded `float32` x/y arrays at **10k, 100k, 1M,
10M, and 1B points**, the same 900×420 output contracts, the same 180-second
and 36 GiB guardrails, and the same reference machine.

The competitor dependency set is pinned to the 0.1.0 lock file
(`uv.lock`, copied verbatim), so the intended variables between the two runs
are the `xy` revision and a Chrome patch bump:

| | 0.1.0 baseline | this refresh |
|---|---|---|
| `xy` | 0.1.0, commit `7228f99` | `0.0.4.dev27+76047753`, commit `7604775` |
| Chrome | 150.0.7871.115 | 150.0.7871.186 |
| Python / NumPy / Plotly / Kaleido / Matplotlib / Tornado | 3.14.5 / 2.5.1 / 6.9.0 / 1.3.0 / 3.11.0 / 6.5.7 | identical |
| Machine / OS | Apple M5 Pro, macOS 26.5.2 | identical |

Across the 24 successful Plotly and Matplotlib timing cells, reproduction
against the recorded 0.1.0 values has a median absolute deviation of 3.2%, with
16 of 24 within 5% and all 24 within 10%. The largest deviations sit on the rows
dominated by cold browser startup rather than by chart work: Kaleido's small-`N`
static rows are 6–8% slower and the small-`N` SwiftShader rows are 3–10% faster,
both consistent with the Chrome patch bump. The competitor side is therefore
stable enough that the `xy` movement below — up to 2.37× on rows whose
competitors barely moved — is a real change in `xy` rather than machine drift.

The benchmark is split by output contract:

1. **Static:** validated 900×420 PNG from every library.
2. **Interactive:** validated first browser render from every library.

No static result is mixed into the interactive table.

## Metrics tracked

| Benchmark | Tracked result | Render path |
|---|---|---|
| A | Static PNG time and peak process-tree RSS | CPU: `xy` native, Kaleido default, Matplotlib Agg |
| B | Interactive TTFR and Python/browser peak RSS | Default hardware WebGL; Matplotlib WebAgg |
| B-CPU | Interactive TTFR under browser CPU fallback | Forced ANGLE SwiftShader; Matplotlib remains Agg/WebAgg |

Successful cells use three complete cold runs. Comparisons must retain the same
900×420 viewport, seeded float32 data, nonblank render oracle, 180-second limit,
36 GiB process-tree limit, and default library behavior. Any changed contract
must be reported as a new benchmark rather than appended to these tables.

## Benchmark A: static 900×420 PNG (CPU-rendered)

Percentage faster is calculated as `(competitor time / xy time - 1) × 100`.
Times are arithmetic mean ± sample standard deviation across three complete,
isolated cold runs.

| Points | `xy` native PNG | Plotly/Kaleido PNG | `xy` faster vs Plotly | Matplotlib/Agg PNG | `xy` faster vs Matplotlib | `xy` mode |
|---:|---:|---:|---:|---:|---:|---|
| 10k | **0.0036 ± 0.0000 s** | 2.0231 ± 0.0059 s | **566.41× (56,541.2%)** | 0.0224 ± 0.0001 s | **6.27× (526.5%)** | direct |
| 100k | **0.0060 ± 0.0003 s** | 2.1100 ± 0.0005 s | **353.91× (35,291.1%)** | 0.0456 ± 0.0004 s | **7.64× (664.3%)** | direct |
| 1M | **0.0058 ± 0.0001 s** | 2.8086 ± 0.0431 s | **484.85× (48,384.6%)** | 0.2858 ± 0.0006 s | **49.34× (4,834.0%)** | density |
| 10M | **0.0184 ± 0.0000 s** | 9.6433 ± 0.0289 s | **522.88× (52,187.7%)** | 2.7432 ± 0.0063 s | **148.74× (14,774.3%)** | density |
| 1B | **1.1288 ± 0.0932 s** | **failed on first guarded attempt** | — | **memory limit** | — | density |

### Movement against the 0.1.0 baseline

`xy` static render time, same contract, same machine:

| Points | 0.1.0 | 2026-07-26 | change |
|---:|---:|---:|---:|
| 10k | 0.0085 s | 0.0036 s | **2.37× faster** |
| 100k | 0.0108 s | 0.0060 s | **1.80× faster** |
| 1M | 0.0114 s | 0.0058 s | **1.97× faster** |
| 10M | 0.0232 s | 0.0184 s | **1.26× faster** |
| 1B | 1.1452 s | 1.1288 s | 1.01× faster (within run-to-run spread) |

The small-to-medium rows moved the most because they are dominated by
fixed per-call overhead rather than by N-dependent kernel work; the 1B row is
dominated by ingesting eight gigabytes of source columns and did not move.

### Static peak process-tree RSS

Plotly includes the Kaleido/Chrome processes required for its static export.

| Points | `xy` | Plotly/Kaleido | Matplotlib/Agg |
|---:|---:|---:|---:|
| 10k | 0.050 GiB | 1.425 GiB | 0.079 GiB |
| 100k | 0.050 GiB | 1.438 GiB | 0.079 GiB |
| 1M | 0.072 GiB | 1.833 GiB | 0.149 GiB |
| 10M | 0.286 GiB | 5.298 GiB | 0.831 GiB |
| 1B | 22.413 GiB | 26.092 GiB observed; failed | >36 GiB; terminated |

RSS values are arithmetic means of successful runs. Failure cells have no
successful-run mean and report the highest observed value before termination.

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

At 1B, Kaleido raised its internal render timeout after 122.1 seconds with
26.09 GiB observed RSS, and its Python process exited non-zero without writing a
PNG. Matplotlib crossed the 36 GiB safety ceiling. Neither produced an image.

## Benchmark B: interactive first render (default GPU path)

Times are arithmetic mean ± sample standard deviation across three complete,
isolated cold Python + fresh-browser runs. Every successful WebGL sample on this
path recorded the renderer `ANGLE (Apple, ANGLE Metal Renderer: Apple M5 Pro,
Unspecified Version)`, confirming these are hardware-GPU rows and must never be
merged with the SwiftShader table below.

| Points | `xy` standalone | Plotly standalone | `xy` faster vs Plotly | Matplotlib WebAgg | `xy` faster vs Matplotlib | `xy` mode |
|---:|---:|---:|---:|---:|---:|---|
| 10k | **0.1643 ± 0.0042 s** | 0.5307 ± 0.0309 s | **3.23× (223.1%)** | 0.2152 ± 0.0087 s | **1.31× (31.0%)** | direct |
| 100k | **0.1680 ± 0.0045 s** | 0.5390 ± 0.0022 s | **3.21× (220.9%)** | 0.2330 ± 0.0185 s | **1.39× (38.7%)** | direct |
| 1M | **0.1762 ± 0.0012 s** | 0.7710 ± 0.0013 s | **4.38× (337.6%)** | 0.4933 ± 0.0064 s | **2.80× (180.0%)** | density + sample |
| 10M | **0.1875 ± 0.0034 s** | 3.3729 ± 0.0156 s | **17.99× (1,698.8%)** | 2.9842 ± 0.0071 s | **15.91× (1,491.5%)** | density + sample |
| 1B | **1.2419 ± 0.0209 s** | **memory limit** | — | **memory limit** | — | density + sample |

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
| 10k | 0.046 | 0.977 | 0.171 | 1.067 | 0.089 | 0.969 |
| 100k | 0.049 | 0.966 | 0.183 | 1.106 | 0.090 | 0.971 |
| 1M | 0.046 | 0.983 | 0.317 | 1.376 | 0.156 | 0.985 |
| 10M | 0.279 | 0.983 | 1.809 | 3.797 | 0.841 | 1.356 |
| 1B | 22.416 | 0.984 | >36 observed | — | >36 observed | — |

Values are GiB. Failure-row values are the highest observed before termination,
not successful steady-state peaks. Successful values are means across runs.

## Benchmark B-CPU: interactive first render with software rendering

Chrome was forced to ANGLE SwiftShader (`--use-angle=swiftshader` and
`--enable-unsafe-swiftshader`). Every successful `xy` and Plotly sample recorded
the renderer string `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM
10.0.0) (0x0000C0DE)), SwiftShader driver)`, so the fallback is verified per
sample rather than assumed from the flags. Matplotlib WebAgg reports no WebGL
renderer because it delivers a server-rendered image canvas. This is the
interactive CPU-fallback test; it still starts a fresh browser for every sample.

| Points | `xy` software | Plotly software | `xy` faster vs Plotly | Matplotlib WebAgg software-browser | `xy` faster vs Matplotlib | `xy` mode |
|---:|---:|---:|---:|---:|---:|---|
| 10k | **0.9653 ± 0.0119 s** | 1.3280 ± 0.0334 s | **1.38× (37.6%)** | 1.0929 ± 0.0882 s | **1.13× (13.2%)** | direct |
| 100k | **0.9638 ± 0.0045 s** | 1.3501 ± 0.0162 s | **1.40× (40.1%)** | 1.1323 ± 0.0773 s | **1.17× (17.5%)** | direct |
| 1M | **1.0836 ± 0.0105 s** | 1.9317 ± 0.0089 s | **1.78× (78.3%)** | 1.2328 ± 0.0143 s | **1.14× (13.8%)** | density + sample |
| 10M | **1.0352 ± 0.0074 s** | 8.0888 ± 0.0213 s | **7.81× (681.4%)** | 3.6121 ± 0.0127 s | **3.49× (248.9%)** | density + sample |
| 1B | **2.1766 ± 0.0615 s** | **memory limit** | — | **memory limit** | — | density + sample |

### Interactive CPU-fallback peak RSS

| Points | `xy` Python | `xy` browser | Plotly Python | Plotly browser | WebAgg Python | WebAgg browser |
|---:|---:|---:|---:|---:|---:|---:|
| 10k | 0.049 | 1.105 | 0.121 | 1.292 | 0.087 | 1.076 |
| 100k | 0.056 | 1.085 | 0.122 | 1.333 | 0.090 | 1.058 |
| 1M | 0.052 | 1.080 | 0.319 | 1.599 | 0.156 | 1.065 |
| 10M | 0.285 | 1.100 | 1.819 | 4.023 | 0.841 | 1.381 |
| 1B | 22.416 | 1.099 | >36 observed | — | >36 observed | — |

There is no separate static CPU-fallback table because Benchmark A already is
the CPU path: `xy` uses its native CPU rasterizer, Matplotlib uses Agg, and the
installed Kaleido/Choreographer configuration disables GPU by default. Repeating
it under another “CPU” label would duplicate Benchmark A.

### Interactive interpretation

- Matplotlib really is interactive here: the built-in WebAgg backend supplies
  pan/zoom controls through a live Python server and browser canvas.
- WebAgg still retains every point. At 1B it crossed the 36 GiB process-tree
  ceiling before delivering a first frame.
- Plotly sends all points into its browser figure. It completed through 10M; its
  1B Python process crossed the same ceiling at 36.44 GiB observed on the
  default path and 36.83 GiB under software rendering.
- `xy` keeps exact source data in Python, but its overview browser payload is
  density + a stable sample. At deep zoom it can request exact visible points.
  This changes the scaling regime and is the default feature under test.
- Small non-monotonic steps remain visible — the 10M CPU-fallback mean is
  slightly below the 1M mean, a 0.05 s gap against 0.007–0.011 s sample
  deviations. Read those as flat within noise, not as larger data being faster.

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
- The environment was warmed before the measured suites: bytecode caches,
  Matplotlib's font cache, and Kaleido's browser download all inflate a first
  invocation in a fresh checkout and are not part of any published cell.

## Environment

- Apple M5 Pro: 18-core CPU, 20-core GPU, 64 GB RAM
- macOS 26.5.2 arm64
- Google Chrome 150.0.7871.186
- Python 3.14.5
- NumPy 2.5.1
- `xy` 0.0.4.dev27+76047753, commit `7604775372979a7a76188c964c8cc6fb6e7d08db`
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
  and 10M near one second. Plotly's software path rises to 8.09 seconds at 10M;
  WebAgg reaches 3.61 seconds.
- **Against the previous baseline:** the static path is 1.26–2.37× faster on the
  same hardware with unchanged competitor versions; interactive TTFR is
  unchanged within noise, because it is bounded by cold browser startup rather
  than by `xy`.

The defensible headline is not “`xy` draws 1B markers.” It is:

> `xy` ingested 1B points and produced both a validated static density PNG in
> 1.129 s mean and a validated interactive density overview in 1.242 s mean,
> while the default exact-point Plotly and Matplotlib paths did not complete at
> that size within the 36 GiB/180-second limits.

## Limitations

- One machine, platform, and browser; three runs quantify local repeatability
  but do not establish cross-machine performance.
- `xy` aggregate output and Plotly/Matplotlib exact-point rendering are
  intentionally different default product semantics.
- WebAgg requires a live Python/Tornado server and is not self-contained HTML.
- Plotly/Kaleido startup can be amortized in a persistent export service; these
  are isolated cold exports.
- Browser RSS includes Chrome overhead and does not measure GPU memory.
- Timeout/memory-limit results are local guarded outcomes, not universal hard
  limits.
- Chrome moved by one patch release between the two runs; it is held constant
  within this run but is not pinned across runs.

## Reproduce

```bash
BASELINE=benchmarks/launch_baselines/xy-main-2026-07-26/macos-arm64-m5-pro
uv sync --project "$BASELINE" --frozen --python 3.14.5
export CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Repeated static + default interactive benchmarks
uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --chrome "$CHROME" --out launch-scatter-default.json

# Repeated interactive CPU/software fallback
uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --interactive-only --software \
  --chrome "$CHROME" --out launch-scatter-cpu-fallback.json
```

Discard a first invocation made in a fresh checkout: it measures cold bytecode
and font caches, not the contract under test.
