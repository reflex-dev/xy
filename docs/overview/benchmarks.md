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

![A 10-million-point comparison of XY, Matplotlib, and Plotly across static PNG, interactive GPU, and interactive CPU-fallback output.](/docs/xy/launch-benchmark-comparison.svg)

## Snapshot at 10 million points

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

## Inspect and reproduce the evidence

The baseline records its source commit (`7228f99`), exact dependency lock,
hardware, browser, raw samples, failure rows, and render oracles:

- [Launch report](https://github.com/reflex-dev/xy/blob/main/benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/report.md)
- [Environment](https://github.com/reflex-dev/xy/blob/main/benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/environment.json)
- [Raw default-path results](https://github.com/reflex-dev/xy/blob/main/benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/default-results.json)
- [Benchmark runbook](https://github.com/reflex-dev/xy/blob/main/benchmarks/README.md)

One machine and three runs describe that recorded environment, not every
machine or workload. New comparisons should retain chart type, data size,
representation, backend, output target, and browser-TTFR status rather than
shortening these results to a universal “faster than” claim. For the rendering
model behind the numbers, read
[Large data and performance](/docs/xy/core-concepts/large-data-and-performance/).
