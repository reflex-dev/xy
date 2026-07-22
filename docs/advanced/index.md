---
title: XY Architecture
description: See how XY keeps exact data in Python while native compute and screen-bounded rendering keep charts responsive.
---

# XY Architecture

XY separates source data, render data, and presentation. Python owns the chart
definition and exact columns, Rust handles data-heavy work, and the browser
draws only the representation needed for the current view.

That same chart can run in notebooks and applications or export to HTML, PNG,
and SVG.

## System overview

~~~text
Declarative Python chart
        |
        v
Chart compiler + exact columns
        |
        v
Native Rust compute
(exact points, line reduction, density, statistics, PNG)
        |
        v
Small JSON spec + typed binary buffers
        |
        v
WebGL2 marks + canvas axes + DOM labels and controls
        |
        +---- live updates ----> Python host (notebook or Reflex)
~~~

| Layer | Responsibility |
| --- | --- |
| Python | Public API, exact source columns, chart policy, callbacks, and host integration |
| Rust | Statistics, range queries, line reduction, density aggregation, selection, and native PNG |
| Browser | Drawing, picking, pan and zoom, tooltips, controls, and immediate interaction |

Standalone HTML has no live Python connection; notebooks and Reflex charts do.

## From source data to pixels

### 1. Compile and compute

Chart components are validated and compiled into a framework-independent
figure. Exact numeric and time values stay in a figure-owned `ColumnStore` as
contiguous `float64` columns.

Rust then prepares either exact visible points or a smaller render
representation. Long lines use M4 reduction, while dense scatter can use a
density grid plus a deterministic sample. These render buffers are disposable;
the exact columns remain the source of truth.

### 2. Send a compact payload

Chart structure, styles, and column references travel in a small JSON spec.
Numeric data travels separately in typed binary buffers rather than large JSON
number arrays.

| Representation | Used for | Browser receives |
| --- | --- | --- |
| Direct | Small traces | Exact visible marks |
| Decimated | Long lines and areas | Viewport-sized extrema |
| Density | Dense scatter overviews | A fixed-size grid and sample |
| Refined | A narrower live view | A recomputed aggregate or exact points |

Geometry is offset-encoded to `float32` for efficient GPU upload while keeping
visible differences in large values such as timestamps.

### 3. Draw and interact

The browser uses WebGL2 for marks and density textures, a 2D canvas for grid
lines and axis rules, and the DOM for labels, legends, tooltips, controls, and
accessible chart chrome.

Pan and zoom update locally first. When a live host is available, the browser
can request a refined view or resolve selections against exact source rows.
Sequence numbers prevent late replies from replacing a newer view.

CSS and Tailwind style DOM elements; mark styles are compiled consistently for
WebGL, SVG, and native PNG. See
[Customize Each Part](/docs/xy/styling/customize/).

## Why it stays fast

~~~text
Conventional path: O(N) encode + transfer + parse + draw
XY tiered path:    O(N) ingest/reduce + O(P) transfer + draw

N = source rows
P = detail useful at the current pixel resolution
~~~

XY still has to inspect source data. Its advantage is that every source row
does not automatically become a browser object:

- Native columnar kernels avoid Python object loops for data-heavy work.
- Binary buffers avoid formatting and parsing large numeric JSON payloads.
- Line reduction and density grids avoid drawing detail the screen cannot show.
- Retained GPU buffers and local interaction avoid rebuilding the chart on
  every pointer movement.

This is a focused design, not a claim that every chart is faster. Compare the
same data, output, and rendering mode. The
[benchmark snapshot](/docs/xy/overview/benchmarks/) publishes those contracts
and records when XY uses a reduced representation.

## Runtime and output choices

| Target | Behavior |
| --- | --- |
| Notebook or Reflex | Live Python callbacks and view refinement |
| Standalone HTML | Embedded browser client and initial data; no Python server |
| Native PNG | Browser-free Rust rasterization |
| Chromium PNG | Browser rendering when CSS and WebGL fidelity matter |
| SVG | Vector output for supported marks and chart chrome |

The chart definition stays the same; only the renderer and live capabilities
change. See [Runtime and Deployment](/docs/xy/advanced/runtime-and-deployment/)
for the full decision guide.

## Key boundaries

- Exact columns are authoritative; render and GPU buffers are replaceable.
- Numeric columns use binary transport; JSON describes structure and metadata.
- Reduced traces are identified as reduced and never presented as exact marks.
- Render work is bounded by the visible result, but ingest can still scale with
  source-data size.
- Python owns product policy, Rust owns native compute, and the browser owns
  drawing and immediate interaction.
- The core chart API stays independent of notebooks, Reflex, and other hosts.

For public callback contracts, continue to
[Events and Callbacks](/docs/xy/api-reference/events-and-callbacks/). For APIs
still changing before 1.0, see
[Limitations and Alpha Status](/docs/xy/api-reference/limitations-and-alpha-status/).
