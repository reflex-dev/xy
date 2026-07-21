# Capability Gap Contract

This document is the normative backlog for closing the difference between XY's
shipped large-data 2D engine and a general-purpose Python visualization
library. It covers platform behavior, analytical composition, chart breadth,
renderer fidelity, accessibility, and host integration.

This is a **target specification, not an implementation claim**.

> [!IMPORTANT]
> Every requirement in the gap tables below is **NOT IMPLEMENTED** unless a
> future change replaces that status with **Implemented** and lands the code,
> tests, public documentation, and required host/export coverage in the same
> pull request. A prototype, open pull request, pyplot-only translation,
> internal primitive, or partial behavior does not make the capability
> implemented.

The current supported baseline remains the public declarative families and
contracts documented elsewhere: 2D Cartesian line, scatter, area, bar/column,
histogram, heatmap, error/interval, box, violin, ECDF, hexbin, contour,
step/stairs/stem, segments, triangle meshes, annotations, named axes, basic
facets, browser interaction, notebook display, and static export. This document
does not downgrade those shipped primitives. It records the larger workflows
that are still incomplete.

## 1. Status and claim rules

The only allowed capability statuses are:

| Status | Meaning |
|---|---|
| **Implemented** | Public API, implementation, tests, docs, and applicable browser/notebook/Reflex/export behavior have landed on `main`. |
| **NOT IMPLEMENTED — partial support exists** | Some reusable primitives or a narrower workflow ship, but the named capability and its acceptance contract do not. |
| **NOT IMPLEMENTED — prototype only** | Work exists only in an unmerged branch, closed exploration, draft, or experimental artifact. |
| **NOT IMPLEMENTED** | No supported implementation ships on `main`. |

Rules:

1. "Implemented in `xy.pyplot`" does not mean implemented in the declarative
   API. Both surfaces must be named independently.
2. A capability is not implemented merely because it can be manually composed
   from lower-level marks.
3. A browser-only implementation is not complete when the capability is also
   promised for native SVG/PNG/PDF. Unsupported outputs must fail loudly or be
   explicitly excluded from that capability's contract.
4. A host adapter is not complete until its event, custom-chrome, lifecycle,
   and payload behavior is tested against the same public object model.
5. A closed or unmerged PR is evidence for design reuse only. It is never a
   shipped status.
6. Status moves to **Implemented** only with executable acceptance coverage.
   Documentation-only status changes are prohibited.

## 2. Priority and sequencing

| Priority | Meaning |
|---|---|
| **P0** | Trust, correctness, accessibility, or architecture work required before broad production claims or rapid catalog expansion. |
| **P1** | General-purpose analytical and charting table stakes. |
| **P2** | Fidelity, extension, publication, and ecosystem depth. |

The dependency order is normative:

1. trustworthy responsive 2D layout, view state, selection, export, and hosts;
2. general multi-panel composition, scales, transforms, parameters, and data
   mutation;
3. Plotly-class 2D chart breadth;
4. specialist coordinates and 3D.

New chart families must not add one-off layout, selection, scale, or adapter
paths when a shared requirement below is still pending.

## 3. P0 foundation gaps

Every row in this section is **not implemented** as a complete capability.

| ID | Capability | Status | Required result before implementation may be claimed |
|---|---|---|---|
| F-01 | Responsive chart chrome | **NOT IMPLEMENTED — partial support exists** | One measured layout pass keeps ticks, titles, legends, colorbars, and annotations legible and contained across supported widths in browser and static outputs. It handles edge ticks, category labels, collision, wrapping/ellipsis, minimum plot area, and deterministic resize convergence. |
| F-02 | General facet layout parity | **NOT IMPLEMENTED — partial support exists** | Facets use the same Figure/Panel lifecycle as ordinary charts, reflow without overflow, support shared legends and outer axes, preserve static geometry, and work through notebook and Reflex hosts without a separate incompatible object path. |
| F-03 | Unified view state | **NOT IMPLEMENTED — partial support exists** | A typed state owns home/current ranges, source, history, reset, linked changes, and programmatic changes. All gestures use one transactional mutation path and cannot blank, collapse, or corrupt the view. |
| F-04 | Representation-independent selection | **NOT IMPLEMENTED — partial support exists** | Direct, sampled, decimated, density, heatmap, and facet representations define visible feedback, canonical-row resolution, clearing, persistence, and linked-selection behavior. |
| F-05 | Non-blocking multi-chart host loading | **NOT IMPLEMENTED — partial support exists** | Chart publication is lazy/prioritized, cancellable, fair to non-chart state traffic, and presented with atomic scene replacement. A 50-chart page remains interactive while payloads arrive. |
| F-06 | Mounted custom host chrome | **NOT IMPLEMENTED — partial support exists** | Official adapters mount custom tooltip, legend, and colorbar content with cursor/chart coordinates, active state, label, trace identity, structured payload, and deterministic lifecycle. |
| F-07 | Complete chart accessibility | **NOT IMPLEMENTED — partial support exists** | Direct and aggregated representations have keyboard exploration, semantic summaries, a view-as-table/full-data escape hatch, visible focus, forced-colors support, reduced motion, keyboard viewport navigation, touch pinch, and a published assistive-technology test matrix. |
| F-08 | Lossless export text contract | **NOT IMPLEMENTED — partial support exists** | Unsupported glyphs never disappear silently. Export preflight reports text/font/style incompatibilities, strict mode fails on loss, and supported fallback or Chromium routing is deterministic. |
| F-09 | Cross-renderer semantic and perceptual parity gates | **NOT IMPLEMENTED — partial support exists** | Every supported family has semantic oracles and renderer-specific goldens that fail wrong-data, wrong-geometry, missing-chrome, and materially different output across HTML, native PNG, SVG/PDF, and applicable Matplotlib references. |
| F-10 | Hardened display-list parsing | **NOT IMPLEMENTED — partial support exists** | Every count-prefixed command validates encoded length before allocation; malformed input cannot trigger unbounded reserve or wasm abort; fuzz/property tests cover all commands and error paths. |
| F-11 | Versioned stability and capability contract | **NOT IMPLEMENTED** | Public docs and machine-readable metadata distinguish declarative, pyplot, browser, native export, notebook, Reflex, LOD, streaming, picking, and accessibility support for each capability. |

### P0 completion gate

P0 is complete only when:

- no reproducible open correctness defect can blank/collapse a supported chart
  or lose labels/data during ordinary navigation and resize;
- density and heatmap views are keyboard-accessible or provide an equivalent
  table/data path;
- export preflight prevents silent text/style loss;
- facets pass the same host and lifecycle tests as ordinary charts;
- Chromium, Firefox, WebKit, high-DPI, touch, context-loss, and multi-chart
  dashboard tests run as release gates; and
- the capability matrix is generated from executable metadata.

## 4. P1 analytical composition and interaction gaps

| ID | Capability | Status | Required result before implementation may be claimed |
|---|---|---|---|
| C-01 | General multi-panel figure grammar | **NOT IMPLEMENTED — partial support exists** | Nested grids, row/column spans, insets, heterogeneous panels, shared/independent axes, and shared/independent guides use one declarative Figure/Panel model. |
| C-02 | Declarative transform graph | **NOT IMPLEMENTED** | Typed aggregate, bin, calculate, filter, fold, pivot, stack, window, quantile, density, regression/LOESS, lookup, and impute nodes form a validated DAG with explicit execution placement. |
| C-03 | Parameters and conditional encodings | **NOT IMPLEMENTED** | Values, selections, and safe expressions can drive filters and conditional color, size, opacity, symbol, stroke, and visibility without rebuilding the entire chart in Python. |
| C-04 | Chart-native controls | **NOT IMPLEMENTED — partial support exists** | Accessible buttons, dropdowns, sliders, range sliders/selectors, and play controls bind to parameters, view state, or animation state and export with a documented contract. |
| C-05 | Safe standalone actions | **NOT IMPLEMENTED** | Standalone HTML can express documented local actions and cross-filter behavior without arbitrary unsafe code or a live Python kernel. |
| C-06 | Linked selection and cross-filtering | **NOT IMPLEMENTED — partial support exists** | Selection is shared browser state that can highlight, filter, or aggregate related charts; host synchronization is optional and does not require a full payload replacement per pointer move. |
| C-07 | General data mutation | **NOT IMPLEMENTED — partial support exists** | Public append, patch, delete, replace, and rollover operations work on a documented set of marks, validate atomically, and update only affected buffers/aggregates. |
| C-08 | Out-of-core and partitioned sources | **NOT IMPLEMENTED** | A pluggable range-query source can serve Arrow, Polars, Dask, xarray, disk-backed, or remote partitions without requiring all canonical rows in process memory. |
| C-09 | LOD for grids and distributions | **NOT IMPLEMENTED — partial support exists** | Huge heatmaps/images use tiled transport and histograms/distributions can re-aggregate by viewport with the same truthfulness, sequencing, and cancellation guarantees as scatter/line. |
| C-10 | Complete declarative scale system | **NOT IMPLEMENTED — partial support exists** | Core scale objects support linear, time, log, symlog, logit, asinh, power/sqrt, band/point, threshold/quantile, and registered invertible custom scales with ticks, bounds, selection inversion, and static parity. |
| C-11 | Robust category and date semantics | **NOT IMPLEMENTED — partial support exists** | Ordered/multi-level categories, nullable values, timezone-aware datetimes, timedeltas/periods, business calendars, skipped ranges, and responsive label policies have explicit ingest, tick, hover, and selection behavior. |
| C-12 | Interactive/shared guide system | **NOT IMPLEMENTED — partial support exists** | Legends can hide, mute, isolate, and drive selection; multi-panel figures resolve legends/colorbars as shared or independent; custom host guides use the same entries and events. |
| C-13 | Structured hover modes | **NOT IMPLEMENTED — partial support exists** | Point, trace, x/y unified, compare, grid-cell, and aggregate hover produce one versioned payload across standalone, notebook, and host adapters. |
| C-14 | Editable marks and annotations | **NOT IMPLEMENTED** | Optional point, line, box, polygon, and annotation edit tools expose validated edit streams, snapping, undo/redo, and persistent host state. |
| C-15 | Portable figure-spec round trip | **NOT IMPLEMENTED** | A versioned safe spec can serialize and restore data references, marks, layout, guides, interactions, and view defaults while excluding or separately representing trusted Python/host callbacks. |
| C-16 | Explicit source-versus-visible data export | **NOT IMPLEMENTED — partial support exists** | UI and APIs distinguish resident/visible representation export from canonical source-row export, label each clearly, and prevent an aggregate CSV from being mistaken for the source table. |

## 5. P1 chart-family and coordinate gaps

The families below are not implemented in the stable declarative API even when
an internal primitive, pyplot translation, or closed prototype can draw part
of the result.

| ID | Capability | Status | Required result before implementation may be claimed |
|---|---|---|---|
| B-01 | 3D and volume scenes | **NOT IMPLEMENTED** | 3D scatter/line/surface/mesh plus camera, axes, clipping, picking, lighting, and export ship first; volume, isosurface, cone, and streamtube may follow as separately declared sub-capabilities. |
| B-02 | Polar and radial coordinates | **NOT IMPLEMENTED** | Polar scatter/line/area/bar, radar, wind rose, radial axes, wraparound selection, labels, and interaction share a real coordinate-system abstraction. |
| B-03 | Geographic visualization | **NOT IMPLEMENTED** | GeoJSON/GeoPandas shapes, projections, tile layers, point/bubble/density maps, choropleths, routes, spatial selection, attribution, and offline/export behavior are defined. |
| B-04 | Specialist coordinates | **NOT IMPLEMENTED** | Ternary, Smith, carpet, and registered custom projections land as independent capabilities on the shared coordinate contract. |
| B-05 | Finance charts | **NOT IMPLEMENTED — prototype only** | Candlestick/OHLC, volume panes, range slider/selector, hover, drawings, streaming/LOD, and a documented initial indicator set land on `main`; the closed finance exploration is not shipped. |
| B-06 | Waterfall and funnel | **NOT IMPLEMENTED** | Running totals/subtotals, connectors, orientation, labels, funnel/funnel-area geometry, hover, selection, and export are supported. |
| B-07 | Hierarchy charts | **NOT IMPLEMENTED** | Treemap, sunburst, and icicle share hierarchy ingestion, stable keys, deterministic layout, drill/navigation, labels, color, selection, and accessibility. |
| B-08 | Flow, network, and tree charts | **NOT IMPLEMENTED** | Sankey/alluvial, graph, tree, org, dendrogram, and arc views declare layout ownership, node/edge semantics, interaction, and accessible alternatives. Individual families may move status separately. |
| B-09 | Dashboard indicators | **NOT IMPLEMENTED** | Gauge, bullet, KPI/number, delta, and threshold semantics render accessible text first and support responsive layout and export. |
| B-10 | Parallel coordinates/categories | **NOT IMPLEMENTED** | Continuous/categorical axes, brushing, reordering, color, linked selection, and large-row aggregation are supported. |
| B-11 | EDA composites | **NOT IMPLEMENTED** | SPLOM/pairplot/corner, joint plots, and marginal distributions use the general panel grammar, shared data, shared guides, and linked selection. |
| B-12 | Statistical and categorical analysis families | **NOT IMPLEMENTED — partial support exists** | Strip, swarm/beeswarm, boxen, rug, split violin, ridgeline, regression/smoothers, residual, QQ/PP, ROC/PR, lift, calibration, calendar/cohort, and Gantt helpers land as individually tracked capabilities. Existing box/violin/ECDF/event primitives do not satisfy this row. |

### Pyplot-only capability warning

The following current implementations do **not** satisfy stable declarative
coverage and remain **NOT IMPLEMENTED in the declarative API** until promoted:

- pie/donut and richer part-to-whole composition;
- quiver, barbs, and streamplot families;
- `pcolormesh`, `tripcolor`, `tricontour`, and related irregular-grid helpers;
- spectral plotting helpers;
- geometry-rendered tables and table-adjacent views; and
- symlog/logit/asinh scale semantics.

Promotion requires a public component/mark contract, docs, browser/native
rendering, interactions where applicable, accessibility, and adapter tests. A
shim translation alone is not enough.

## 6. P2 fidelity, publication, and ecosystem gaps

| ID | Capability | Status | Required result before implementation may be claimed |
|---|---|---|---|
| E-01 | Stable scene/Artist extension surface | **NOT IMPLEMENTED — partial support exists** | XY defines a bounded public scene extension model for custom geometry, transforms, clipping, ordering, and hit testing without promising Matplotlib's full Artist graph. |
| E-02 | International typography and math | **NOT IMPLEMENTED — partial support exists** | Unicode shaping, font fallback, right-to-left text, CJK, locale-aware labels, math text, and consistent browser/native measurement have explicit support and conformance. |
| E-03 | Publication workflows | **NOT IMPLEMENTED — partial support exists** | Supported document workflows define font embedding/subsetting, accessible PDF, multipage output, print CSS, color-profile expectations, metadata, and exact failure/fallback behavior. |
| E-04 | Color normalization and management | **NOT IMPLEMENTED — partial support exists** | Typed normalizers, categorical/continuous guide rules, perceptual interpolation, missing/under/over values, color-vision-safe defaults, and renderer parity are public contracts. |
| E-05 | Per-state mark styling | **NOT IMPLEMENTED — partial support exists** | Hovered, selected, unselected, muted, disabled, and focused styles work across direct and aggregated representations and all supported renderers. |
| E-06 | Custom symbols, paths, and image marks | **NOT IMPLEMENTED — partial support exists** | Bounded vector paths and image assets define loading/security, sizing, colorization, picking, animation, export, and LOD behavior. |
| E-07 | Frame/player animation | **NOT IMPLEMENTED — partial support exists** | A frame timeline, controls, interpolation matrix, interruption, view-state interaction, deterministic capture, and optional video/movie export complement the existing keyed transition system. |
| E-08 | Versioned plugin registries | **NOT IMPLEMENTED** | Marks, transforms, scales, tooltips, adapters, and optional renderer extensions register through stable versioned contracts rather than private wire structures. |
| E-09 | Broad data interoperability | **NOT IMPLEMENTED — partial support exists** | DataFrame Interchange, chunked/null Arrow, Polars, xarray, Dask, GeoPandas, quantities/units, and partitioned sources have tested copy/zero-copy and semantic behavior. |
| E-10 | Framework-neutral adapter protocol | **NOT IMPLEMENTED — partial support exists** | Core defines the minimum lifecycle, payload, event, custom-chrome, mutation, and capability-negotiation contract; Reflex and at least one independent reference adapter prove it. |
| E-11 | Browser/device/resource and capability discovery contract | **NOT IMPLEMENTED — partial support exists** | Release tests cover touch, high-DPI, memory pressure, context loss, long streaming sessions, repeated mount/unmount, workers, cancellation, and major browsers; adapters can query versioned feature flags instead of guessing from package versions. |

## 7. Cross-cutting semantic requirements

Every future capability above must specify these behaviors rather than inherit
accidental defaults:

- null/NaN masking, line gaps, aggregate denominators, and missing-value
  tooltip text;
- stable identity for updates, selection, animation, and drilldown;
- x/y/color/size/symbol/opacity channel retention or explicit aggregation;
- scale forward/inverse semantics in pan, zoom, selection, linking, and export;
- complete versus visible/resident data semantics;
- responsive minimum size and overflow behavior;
- browser, native SVG/PNG/PDF, notebook, and adapter support or an explicit
  loud exclusion;
- keyboard, screen-reader, forced-colors, reduced-motion, and table fallback;
- cancellation, stale-result rejection, context/worker cleanup, and bounded
  memory; and
- security validation for text, paint, assets, expressions, and serialized
  state.

## 8. Milestones

### Milestone A — trustworthy 2D foundation

Scope: F-01 through F-11.

No Plotly-class or production-complete positioning is allowed before this
milestone. New families may reuse existing primitives, but they must not create
new one-off layout/view/selection systems.

### Milestone B — analytical composition

Scope: C-01 through C-16 plus declarative promotion of the highest-value
pyplot-only families.

Exit condition: common Altair/Seaborn/Bokeh linked-dashboard and EDA workflows
can be expressed without bespoke host code or manual coordinate transforms.

### Milestone C — Plotly-class 2D breadth

Recommended order:

1. B-05 finance;
2. B-06 business charts;
3. B-11 EDA composites and B-12 categorical/statistical helpers;
4. B-07 hierarchy;
5. B-08 flow/network/tree;
6. B-09 indicators and B-10 parallel coordinates;
7. B-03 geography; and
8. B-02 polar/radial.

Individual rows remain **NOT IMPLEMENTED** until their own acceptance contract
lands. Completing one row does not automatically complete the milestone.

### Milestone D — specialist coordinates and 3D

Scope: B-01 and B-04 after the shared coordinate, view-state, picking, layout,
and export contracts are stable.

## 9. Verification requirements

A pull request that changes a row to **Implemented** must include:

1. a public typed API and validation tests;
2. semantic unit/property tests, including hostile and missing data;
3. browser interaction and lifecycle coverage when interactive;
4. native/static output tests for every promised output;
5. notebook and Reflex tests when the public object is accepted by those
   hosts;
6. accessibility tests appropriate to the representation;
7. performance/memory budgets for row-dependent or interactive work;
8. public documentation and copyable examples;
9. updates to `chart-roadmap.md`, this file, and machine-readable capability
   metadata; and
10. a claim review that distinguishes exact marks from aggregated/decimated
    representations.

If any required layer is intentionally excluded, the row must be split into a
narrower capability whose name states that boundary. Do not mark a broad row
implemented and hide exclusions in prose.

## 10. Maintenance

- Review this contract whenever a new chart family, scale, transform, output,
  host adapter, or interaction mode is proposed.
- Link implementation PRs and issue trackers from the relevant row or a nearby
  status note; do not treat an open PR as a status change.
- Prefer splitting a broad row into independently testable capabilities over a
  permanent "mostly implemented" state.
- Keep public marketing claims at or below the generated implemented set.
- Re-run the competitive source review at least once per minor release while
  XY remains pre-1.0.

## 11. Comparison sources

The target set is informed by current primary documentation, not by a promise
to clone every API:

- [Matplotlib plot types](https://matplotlib.org/stable/plot_types/index.html),
  Artists, projections, events, backends, and animation;
- [Plotly Python](https://plotly.com/python/), its figure schema, mixed
  subplots, controls, maps, finance, hierarchy, flow, and 3D traces;
- [Seaborn](https://seaborn.pydata.org/tutorial) statistical, categorical,
  facet, joint, and pairwise workflows;
- [Vega-Altair](https://altair-viz.github.io/user_guide/marks/index.html)
  marks, transforms, parameters, conditions, composition, and guide resolution;
- [Bokeh](https://docs.bokeh.org/en/latest/docs/user_guide/basic.html) data
  sources, tools, linked selections, callbacks, widgets, editing, and server
  apps; and
- [HoloViews](https://holoviews.org/user_guide/) and Datashader large-data,
  streaming, dynamic, linked, and out-of-core workflows.
