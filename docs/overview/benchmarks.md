---
title: Benchmarks
description: Inspect XY's live interactive benchmark from 10,000 to 100 million points, including its output contract, memory use, and caveats.
---

# Benchmarks

This benchmark measures what a user waits for on a live interactive scatter
chart. Every library receives every source row and runs through its own normal
input path in a real browser. The sweep covers 10,000 to 100 million points on
one Apple M5 Pro.

The clock stops only when the canvas is both correct and stable. Correct means
sentinel points planted at known coordinates are lit in the expected places.
Stable means the full drawing buffer is byte-identical for 10 consecutive
frames. Progressive renderers are therefore charged until their last chunk
lands, not just until their first paint.

~~~python demo-only exec
from xy_docs.demos.benchmark_charts import interactive_ux_demo

benchmark_interactive_ux = interactive_ux_demo
~~~

XY holds **0.071 seconds at 10k and 0.081 seconds at 100M**, nearly flat across
four orders of magnitude. Above 200k rows, the default path draws a
screen-bounded density surface and retains a sample for interaction instead of
drawing one marker per row. Deep zooms request exact source rows.

Every exact-marker path scales with the row count. Matplotlib crosses one
second at about 3M and reaches 13.4 seconds at 50M. Plotly crosses one second
at about 2.5M and reaches 9.8 seconds at 25M.

## Time until every point is on screen

Times are seconds. `✕` marks a size that did not satisfy the full benchmark
contract: Plotly never finished constructing the 50M figure, while Matplotlib
drew 100M points but did not resolve the zoom that followed.

| Points | 10k | 100k | 500k | 1M | 2.5M | 5M | 10M | 25M | 50M | 100M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| *XY speedup* | *1×* | *2×* | *3×* | *4×* | *9×* | *16×* | *34×* | *89×* | *177×* | *—* |
| **XY** | **0.071** | **0.072** | **0.075** | **0.084** | **0.083** | **0.089** | **0.083** | **0.077** | **0.076** | **0.081** |
| XY (`density=False`) | 0.085 | 0.074 | 0.087 | 0.098 | 0.111 | 0.144 | 0.206 | 0.424 | 0.645 | 1.343 |
| Matplotlib (WebAgg) | 0.086 | 0.115 | 0.224 | 0.357 | 0.758 | 1.424 | 2.804 | 6.838 | 13.385 | ✕ |
| Plotly (scattergl) | 0.341 | 0.373 | 0.477 | 0.614 | 1.033 | 1.785 | 3.367 | 9.794 | ✕ | ✕ |

The speedup row compares default XY with the next-fastest other library at each
size. One run was recorded per cell. At the small end, timings carry roughly
±10 ms of run-to-run spread.

## Peak Python-side memory

Peak resident memory is reported in GiB. Browser memory is measured separately
and excluded here because headless Chrome occupies about 1 GiB before it draws
a chart.

| Points | 10k | 100k | 500k | 1M | 2.5M | 5M | 10M | 25M | 50M | 100M |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| *XY advantage* | *1.8×* | *1.7×* | *1.9×* | *2.1×* | *2.1×* | *2.4×* | *2.6×* | *2.9×* | *2.8×* | *—* |
| **XY** | **0.05** | **0.05** | **0.06** | **0.07** | **0.13** | **0.19** | **0.32** | **0.70** | **1.36** | **2.58** |
| XY (`density=False`) | 0.05 | 0.05 | 0.07 | 0.10 | 0.18 | 0.31 | 0.57 | 1.35 | 2.66 | 5.26 |
| Matplotlib (WebAgg) | 0.09 | 0.09 | 0.12 | 0.15 | 0.28 | 0.46 | 0.84 | 2.06 | 3.85 | ✕ |
| Plotly (scattergl) | 0.21 | 0.18 | 0.28 | 0.36 | 0.60 | 1.05 | 1.86 | 4.70 | ✕ | ✕ |

The advantage row compares default XY with the next-lowest Python-side peak
from another library. The exact-marker XY path reaches 100M in 1.343 seconds
and 5.26 GiB, showing the engine's scaling without giving it aggregation
credit.

## Why the density path is a fair product comparison

No benchmark arm receives pre-thinned input. Each library gets all rows, then
uses its normal rendering strategy. XY's density arm proves that all rows were
included with a count oracle, while Matplotlib, Plotly, and `density=False`
draw one marker per row.

That makes the default comparison an end-to-end product question: what does a
user get from the ordinary API at this data size? The pale exact-marker XY
series answers the separate like-for-like question of how the same engine
scales when every row stays an individual marker.

## What this benchmark does and does not show

| The recorded sweep shows | It does not establish |
| --- | --- |
| Navigation to a correct, stable live scatter chart | Performance for every chart family or dashboard layout |
| Default XY and exact-marker XY across the same row ladder | Equivalent rendered geometry after default XY enters density mode |
| Whether the scripted zoom returns a final correct frame | Every interaction pattern or server deployment |
| Python-side peak RSS on one Apple M5 Pro | Browser memory, GPU memory, or performance on every platform |

The benchmark also records first paint, during-gesture frame timing, settle
time, browser memory, screenshots, raw JSON, and a synchronized video for each
size. Those measurements remain separate so a fast first frame cannot hide
unfinished rendering or deferred work.

## Inspect and reproduce the evidence

The methodology and artifact contracts are documented in the repository:

- [README benchmark summary](https://github.com/reflex-dev/xy#benchmarks)
- [Benchmark runbook](https://github.com/reflex-dev/xy/blob/main/benchmarks/README.md)
- [Interactive UX harness](https://github.com/reflex-dev/xy/blob/main/benchmarks/bench_ux.py)
- [Full ladder runner](https://github.com/reflex-dev/xy/blob/main/benchmarks/run_ux_suite.sh)
- [Result summarizer](https://github.com/reflex-dev/xy/blob/main/benchmarks/summarize_ux.py)
- [Competitive benchmark specification](https://github.com/reflex-dev/xy/blob/main/spec/benchmarks/results.md)

After completing the runbook setup, run the same size ladder:

```bash
export CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
./benchmarks/run_ux_suite.sh /path/to/xy-ux-suite

.venv/bin/python benchmarks/summarize_ux.py /path/to/xy-ux-suite
.venv/bin/python benchmarks/plot_ux.py /path/to/xy-ux-suite --out-dir charts
.venv/bin/python benchmarks/plot_ux.py /path/to/xy-ux-suite --out-dir charts \
  --color-scheme dark --suffix=-dark
```

Keep results separated by environment. Hardware WebGL and SwiftShader rows are
not interchangeable. For the rendering model behind XY's flat default curve,
read [Large data and performance](/docs/xy/core-concepts/large-data-and-performance/).
