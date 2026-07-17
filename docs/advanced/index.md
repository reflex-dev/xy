---
title: XY Architecture
description: Follow a chart from the declarative Python API through native reduction, binary transport, browser rendering, interaction, and export.
---

# XY Architecture

XY separates canonical data, derived render data, and presentation. Python
owns the chart definition and exact source columns, the native Rust core does
data-dependent compute, and the browser draws a representation sized for the
visible result. Notebook and Reflex integrations add a live channel back to
Python; standalone exports deliberately do not.

This separation lets the same chart object serve interactive applications,
notebooks, self-contained HTML, and static image exports without making the
browser retain every source row.

## System overview

~~~text
Declarative Python API
        |
        v
Chart compiler -----> ColumnStore (canonical f64 columns)
        |                         |
        |                         v
        |                Native Rust compute core
        |                statistics, binning, M4,
        |                range queries, rasterization
        |                         |
        +-------------------------+
        |
        v
Small JSON spec + typed binary buffers
        |
        +--------------+----------------+
        |              |                |
        v              v                v
  WebGL2 marks    2D canvas chrome    DOM chrome
  and textures    grid and axes       text, legend,
                                     tooltip, controls
        |
        v
Interaction controller -- live host channel --> Python figure
                        (notebook or Reflex)
~~~

The wire spec describes traces, axes, styles, interactions, and references to
columns. Numeric data travels beside it in typed binary buffers, not as JSON
number arrays or base64 strings.

## 1. Declarative API and figure compilation

Factories such as `xy.scatter()`, `xy.line()`, and `xy.x_axis()` create a
framework-independent component tree. A chart compiles that tree into an
internal `Figure`; the core `xy` package does not depend on Reflex, a notebook
runtime, or a browser.

Compilation performs four jobs:

1. It validates component props, data bindings, axes, styles, and interaction
   settings.
2. It normalizes numeric and time data into typed columns.
3. It registers traces that reference those columns instead of embedding data
   in the chart spec.
4. It chooses the initial rendered representation for each trace.

The public component tree is the durable authoring model. `Chart.figure()` is
an advanced escape hatch into the compiled figure and its host-specific
methods.

## 2. Canonical columns and native compute

Each figure owns a `ColumnStore`. Canonical numeric and time columns are kept
as contiguous `float64` arrays, deduplicated within the figure when traces
share the same underlying array. Chunk-level zone maps cache statistics used
for autorange and range queries. Derived render buffers are rebuildable caches;
they are not the source of truth.

Published wheels include a required native Rust core behind a narrow C ABI.
Python keeps validation, policy, column ownership, chart composition, and host
integration. Rust handles measured data-path work such as statistics, range
queries, M4 line reduction, density binning, selection, and native
rasterization. Unsupported platforms fail clearly instead of silently
switching to a slower compute implementation.

See [Data and Columns](/docs/xy/core-concepts/data/) for accepted inputs and
[Large Data and Performance](/docs/xy/core-concepts/large-data-and-performance/)
for the representation ladder.

## 3. Screen-bounded payloads

The payload compiler emits two coordinated pieces:

- a small JSON-compatible spec containing structure, metadata, and column
  references;
- typed binary columns containing geometry, channels, density grids, and
  selection data.

Geometry is offset-encoded to `float32` for transport and GPU upload. The
offset and scale remain in metadata so large values such as millisecond epoch
timestamps do not lose their visible differences through a naive `float32`
cast.

The payload depends on the active representation:

| Tier | Typical use | Browser payload |
| --- | --- | --- |
| Direct | Small visible traces | Exact visible marks |
| Decimated | Long ordered lines and areas | M4-preserved extrema at viewport resolution |
| Density | Dense scatter overviews | Fixed-size count grid plus a deterministic sample |
| Refined | A narrower live view | Recomputed aggregate or exact visible points when they fit |

Every reduction is recorded in the trace spec. Tier selection changes visible
geometry, not the canonical source columns.

## 4. Why XY can outperform conventional chart libraries

The important difference is not simply that XY uses Rust or WebGL. It is that
XY avoids letting source-row count determine every later stage of the render
pipeline.

A conventional Python-to-browser chart path often pays a sequence of
data-sized costs: turn every value into JSON, copy the text across the host
boundary, parse it back into JavaScript values, create or upload one mark per
row, and revisit that full representation during interaction. SVG-based
renderers can also create one DOM node per mark. A WebGL renderer removes the
DOM-node cost, but it can still upload and draw every point if it has no
level-of-detail policy.

XY changes the cost model:

~~~text
Conventional path: O(N) encode + O(N) transfer + O(N) parse + O(N) draw
XY tiered path:    O(N) ingest/reduce + O(P) transfer + O(P) draw

N = source rows
P = marks, segments, or cells useful at the current pixel resolution
~~~

The initial ingest or reduction still has to inspect source data. XY's
advantage is that those rows do not automatically become an equally large
browser payload and draw workload.

| Architectural choice | Work it avoids |
| --- | --- |
| Typed binary buffers | Decimal formatting, large JSON text, JavaScript number-array parsing, and base64 expansion |
| Native columnar kernels | Python object loops for statistics, binning, range queries, and line reduction |
| M4 line reduction | Uploading and drawing line vertices the viewport cannot distinguish while retaining bucket extrema |
| Density grids for large scatter | Uploading and drawing every overlapping marker; the browser draws a screen-sized texture instead |
| Offset-encoded `float32` geometry | Double-width GPU geometry without giving up the visible precision of large-magnitude source values |
| Retained GPU buffers and uniform-based pan/zoom | Rebuilding geometry on every pointer movement |
| Batched and instanced WebGL2 marks | Per-mark DOM/SVG nodes and repeated JavaScript draw calls |
| Local browser interaction | Python round-trips for immediate pan/zoom feedback and chrome updates; live refinement can follow asynchronously |
| Native PNG renderer | Browser startup, DOM layout, and GPU setup when browser fidelity is not requested |

These choices reinforce one another. Native reduction would help less if its
result were expanded back into JSON. Binary transport would help less if the
browser still drew every invisible overlap. WebGL would help less if pan and
zoom rebuilt every vertex buffer. XY keeps the reduced representation compact
through compute, transport, GPU upload, and drawing.

This is not a claim that XY wins every chart workload. Small charts may be
dominated by fixed initialization cost, some other libraries also provide
binary transport or GPU aggregation, and exact unreduced output necessarily
does more work. Compare like-for-like output contracts and environments. The
[benchmark snapshot](/docs/xy/overview/benchmarks/) reports native static,
interactive GPU, and CPU-fallback results separately and records when XY uses
a density representation instead of individual markers.

## 5. Browser rendering surfaces

The browser client uses three coordinated surfaces, each chosen for the work
it does best:

| Surface | Responsibility |
| --- | --- |
| WebGL2 canvas | Marks, instanced geometry, density textures, and GPU picking |
| 2D canvas | Grid lines and axis rules |
| DOM | Labels, legends, tooltips, controls, annotations, and accessibility-oriented chrome |

Pan and zoom primarily update view-transform uniforms. Geometry is uploaded
again only when a new level of detail is needed. A mark registry keeps the
main render loop independent of individual chart kinds, while the
level-of-detail module owns tier changes, caches, and crossfades.

This split also defines the styling boundary: normal CSS and Tailwind apply to
DOM chrome, while mark styles are compiled into WebGL, native raster, and SVG
renderer values. See [Chrome Slots](/docs/xy/styling/chrome-slots/) and
[Mark Styles](/docs/xy/styling/mark-styles/).

## 6. Interaction and live refinement

Pointer input first resolves against the currently rendered representation.
When a live Python host is available, the client sends compact semantic
messages for view changes, picking, or selection. The shared Python dispatcher
validates the request against the canonical figure and returns a small reply
plus binary buffers when new geometry is required.

View and drill requests carry sequence numbers. The client ignores stale
replies, keeps drawing the previous representation while refinement is in
flight, and swaps tiers only when the matching update arrives. Exact hover and
selection callbacks resolve canonical row indices rather than presenting a
density cell as if it were an individual point.

The transport changes by host, but the figure protocol does not. Notebook
widgets use binary comm frames, state-backed Reflex charts use the app's
websocket, and standalone HTML uses no live Python transport. The runtime
and deployment mode determines which refinement and callback paths are
available. See [Runtime and Deployment](/docs/xy/advanced/runtime-and-deployment/)
for the complete decision guide.

## 7. Static export paths

Static outputs reuse the compiled chart contract but choose a renderer for the
requested fidelity:

- native PNG uses the Rust raster path and does not require a browser;
- Chromium PNG captures the browser renderer when browser CSS and WebGL
  fidelity matter;
- SVG walks the scene into vector output for supported marks and chrome;
- standalone HTML packages the browser client and first-paint payload.

The chart definition therefore stays the same while the final renderer and
interaction capabilities change.

## Architectural invariants

When extending XY or diagnosing a chart, preserve these boundaries:

- Canonical columns are authoritative; GPU and level-of-detail buffers are
  disposable.
- Data columns use binary transport; JSON describes structure and metadata.
- Reductions are explicit in the spec and must not imply exact marks.
- Render work is bounded by visible output, while ingest and reduction can
  still depend on source-data size.
- Python owns product policy and host semantics; Rust owns the native compute
  path; the browser owns drawing and immediate interaction.
- Stale live replies never replace newer view state.
- The core chart API remains independent of host frameworks.

For callback payloads and selection semantics, continue to
[Events and Callbacks](/docs/xy/api-reference/events-and-callbacks/). For
contracts that are still changing before 1.0, see
[Limitations and Alpha Status](/docs/xy/api-reference/limitations-and-alpha-status/).
