---
title: Benchmarks
description: Inspect XY's recorded launch benchmark with its exact output contracts and caveats.
---

# Benchmarks

XY's large-data claim is about the representation sent to a fixed-size output,
not about drawing every source row as an individual marker. The committed 0.1.0
launch baseline measures identical seeded scatter data at 900×420 pixels on an
Apple M5 Pro with 64 GiB RAM. Each successful cell below is the mean of three
isolated cold runs. The machine name and memory are copied verbatim from the
committed environment record.

> **How to read this comparison.** XY switches dense scatter output to a
> screen-bounded density representation, while the default Plotly and
> Matplotlib paths retain every marker. These results compare each library's
> default user-visible outcome at the same output size; they do not claim that
> the libraries send identical geometry to the renderer.

## Snapshot at 10 million points

~~~python demo-only exec
from xy_docs.demos.benchmark_charts import launch_snapshot_demo

benchmark_launch_snapshot = launch_snapshot_demo
~~~

| 900×420 output contract | XY | Matplotlib | Plotly | XY representation |
| --- | ---: | ---: | ---: | --- |
| Static CPU PNG | 0.0232 s | 2.7842 s | 9.5834 s | density |
| Interactive first render, default GPU | 0.1797 s | 3.0029 s | 3.6434 s | density + sample |
| Interactive first render, CPU fallback | 0.9920 s | 3.6735 s | 8.2152 s | density + sample |

These summary tables show means only; the linked launch report publishes the
sample standard deviation for every successful timing cell. Small reversals in
adjacent means, such as 100k versus 1M on the default interactive path, are
within the observed three-run variation and should not be read as evidence that
more rows are inherently faster.

The output contracts are intentionally separate. Static PNG rows compare
validated CPU-rendered images. Interactive rows include figure construction,
standalone HTML, a fresh browser, readiness, GPU completion, and a nonblank
pixel check. Hardware-WebGL and SwiftShader results are never merged.

## Time and memory across scale

The 10-million-point snapshot is one point on a larger curve. Static render
time stays close to the output cost after XY switches to density, while the
exact-marker paths continue to grow with the number of rows. Peak process-tree
RSS tells the same practical story from a different angle.

~~~python demo-only exec
from xy_docs.demos.benchmark_charts import scaling_and_memory_demo

benchmark_scaling_and_memory = scaling_and_memory_demo
~~~

At 10 million points, the static CPU output contract recorded:

| Peak process-tree RSS | XY | Matplotlib | Plotly / Kaleido |
| --- | ---: | ---: | ---: |
| Static 900×420 PNG | 0.283 GiB | 0.834 GiB | 5.671 GiB |

Plotly's static value includes the Kaleido and Chrome processes used by
`to_image()`. RSS was sampled across each complete process tree every 50 ms, so
very brief peaks may be missed. At one billion points, XY's successful static
row peaked at 22.414 GiB; Matplotlib crossed the 36 GiB guardrail and Plotly did
not produce a PNG on its first guarded attempt.

## What scales with rows—and what does not

XY keeps exact source columns in Python. Ingest, range scans, binning, and line
decimation still perform work that depends on the number of source rows. Once a
large scatter has been reduced, however, the density grid and retained sample
are bounded by the viewport rather than growing one marker per row. Long line
output is similarly bounded after decimation.

That distinction is visible in the recorded sweep:

| Points | Native static PNG | Interactive, default GPU | XY representation |
| ---: | ---: | ---: | --- |
| 10k | 0.0085 s | 0.1533 s | direct |
| 100k | 0.0108 s | 0.1742 s | direct |
| 1M | 0.0114 s | 0.1688 s | density; density + sample interactive |
| 10M | 0.0232 s | 0.1797 s | density; density + sample interactive |
| 1B | 1.1452 s | 1.2530 s | density; density + sample interactive |

At one billion points, XY ingested the rows and produced a validated density
PNG and interactive density overview. It did **not** draw one billion markers.
The exact-point Plotly and Matplotlib paths did not complete at that size within
this run's 36 GiB process-tree and 180-second limits; those are local guarded
outcomes, not universal limits.

## What this benchmark does—and does not show

| The recorded baseline shows | It does not establish |
| --- | --- |
| Cold time to a validated, nonblank 900×420 output | Warm-service throughput after browser or Kaleido startup is amortized |
| Peak process-tree RSS on one reference machine | GPU memory or performance on every platform |
| Default large-scatter behavior for each library | Equivalent rendered geometry after XY enters density mode |
| The effect of a screen-bounded representation at large sizes | Performance for every chart family, dashboard, or interaction |

The result is strongest as an end-to-end product comparison: what a user gets
from the default API under a fixed output contract. A separate like-for-like
representation study is still useful when the question is about the cost of
aggregation itself.

## Next benchmark coverage

The repository already has harnesses for more than the launch scatter. Results
will be published separately as their contracts and reference artifacts are
frozen:

- **Adaptive peers:** dense scatter against Datashader / HoloViews and long
  lines against Plotly Resampler, kept separate from exact-marker baselines.
- **Interaction and applications:** pan and zoom refinement, selection,
  append/streaming updates, transport, and 10/20/50-chart dashboards.
- **More chart families:** long lines and heatmaps, where decimation and
  fixed-resolution aggregation exercise different kernels.
- **Release and hardware tracking:** immutable release directories plus
  clearly separated macOS hardware-WebGL and CI SwiftShader results.

Until those artifacts are published, this page intentionally keeps its
headline claims scoped to the committed launch scatter.

## Inspect and reproduce the evidence

The baseline records its source commit (`7228f99`), exact dependency lock,
hardware, browser, raw samples, failure rows, and render oracles:

- [Launch report](https://github.com/reflex-dev/xy/blob/main/benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/report.md)
- [Environment](https://github.com/reflex-dev/xy/blob/main/benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/environment.json)
- [Raw default-path results](https://github.com/reflex-dev/xy/blob/main/benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/default-results.json)
- [Benchmark runbook](https://github.com/reflex-dev/xy/blob/main/benchmarks/README.md)

After completing the runbook setup, reproduce the frozen default-path sweep
from the source revision recorded in the environment file:

```bash
BASELINE=benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro
uv sync --project "$BASELINE" --frozen --python 3.14.5
CHROME=$(node -e "console.log(require('playwright').chromium.executablePath())")

uv run --project "$BASELINE" --frozen python benchmarks/bench_launch_scatter.py \
  --sizes 10000,100000,1000000,10000000,1000000000 \
  --repetitions 3 --timeout 180 --memory-gib 36 \
  --chrome "$CHROME" --out launch-scatter-default.json
```

One machine and three runs describe that recorded environment, not every
machine or workload. New comparisons should retain chart type, data size,
representation, backend, output target, and browser-TTFR status rather than
shortening these results to a universal “faster than” claim. For the rendering
model behind the numbers, read
[Large data and performance](/docs/xy/core-concepts/large-data-and-performance/).
