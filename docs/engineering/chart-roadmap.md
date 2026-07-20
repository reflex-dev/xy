# Chart Type Roadmap

This is the single chart-type roadmap for xy. It is intentionally
**2D-first**: the library should become broad enough for Plotly-class analytics,
finance, science, operations, and dashboard use cases before spending product
energy on 3D/volume rendering. Nothing in this section implies immediate
implementation; it is the coverage backlog we will pull from as the primitives
land.

The roadmap prioritizes chart types by two signals:

1. **Popularity signal:** chart types that appear prominently across mainstream
   plotting libraries and galleries.
2. **xy fit:** chart types where the engine can win on large data,
   binary transport, WebGL rendering, and screen-bounded aggregation.

The near-term wedge is large data, but the long-term product goal is broader:
xy should become a **Plotly-class general-purpose charting library** for
analytics, science, finance, operations, and dashboards. Performance is the
entry point, not the boundary of the product.

The current implemented surface is **line**, **scatter**, **area**,
**histogram**, **bar/column**, **heatmap**, **error bars/bands**,
**box/violin/ECDF**, **hexbin/contour**, **step/stairs/stem**, **pie/donut**,
**scientific vector fields**, **irregular triangular meshes**, and **faceted
small multiples**. The last three families are exposed through the
Matplotlib-flavoured shim over shared xy primitives. Scatter already covers direct
points, color/size channels, GPU picking, selection, and Tier-2 density
aggregation. Line and area cover direct and M4-decimated time series. Histogram
and bar/column share the instanced rectangle renderer; heatmap ships a compact
grid texture.

Beyond the mark set, four capability layers now ship on `main`:

- **Mark-level styling (§ "Styling & Theming" below):** CSS `linear-gradient`
  fills, rounded (`corner_radius`, independent tip/base) and stroked bars,
  line/area dashes, smooth (monotone-cubic) curves, scatter symbols + strokes,
  and mark colors — all resolved from CSS so the marks obey
  the same theme tokens as the chrome. Every styling input is validated at
  build time by the native CSS grammar (`src/css.rs`, ABI v9): closed grammars
  (hex/`rgb()`/`hsl()`/named colors, lengths, numbers) parse strictly,
  browser-resolved forms (`var()`/`oklch()`/`calc()`) pass through, and a
  malformed value raises instead of rendering a silently wrong chart (see
  `docs/engineering/styling.md` § Validation).
- **Static export:** `fig.to_svg(...)` (pure-Python, screen-bounded vector —
  a 10M-point line exports in ~4 ms / ~58 KB) and `fig.to_png(...)` (a
  browser-free native Rust rasterizer by default, ~50× faster than the
  `engine=Engine.chromium` screenshot). Both consume the same decimated payload, so
  export cost scales with pixels, not points.
- **Standalone LOD without a kernel:** `to_html` exports now re-bin the
  retained density sample in a bundled Web Worker on zoom (off the main
  thread), so a kernel-less page refines instead of stretching the overview.
- **Reflex-first reactive API (`python/reflex-xy/`):** xy figures as
  first-class Reflex components (PR #55). Chart data multiplexes onto the
  app's existing websocket as a second socket.io namespace (`/_xy`) with
  binary column attachments (§29 — no JSON numbers, no sidecar HTTP
  endpoints); the only chart state in Reflex is a token string. The
  `@reflex_xy.figure` computed-var decorator binds figure builders to Reflex
  state so dependency tracking drives rebuilds and republishes, and a static
  payload tier compiles zero-backend charts to asset files. See
  `docs/integrations/reflex.md` and `docs/engineering/design/reflex-integration.md`.

**Prototyped (not on `main`):** candlestick + OHLC marks and a finance
overlay/indicator layer (volume pane, SMA, VWAP, Bollinger, RSI, MACD,
drawings) were built on the `codex/finance-charting-surface` exploration PR,
which is now **closed unmerged** ("[Don't Merge]"). The design and code exist
on that branch; landing finance on `main` needs a fresh PR that re-bases the
surface onto current primitives — see rank 9 and rank 35 below.

## Source Signals

These sources are used as popularity proxies, not as exact usage telemetry:

| Source | Prominent chart types represented |
|---|---|
| [Plotly Python docs](https://plotly.com/python/) and [figure reference](https://plotly.com/python/reference/) | scatter, scattergl, line, area, bar, pie, bubble, error bars, box, violin, histogram, 2D histogram, heatmap, contour, image, time series, candlestick, OHLC, waterfall, funnel, treemap, sunburst, icicle, Sankey, parallel categories, parallel coordinates, scatter matrix, table, ternary, polar |
| [Matplotlib plot types](https://matplotlib.org/stable/plot_types/index.html) | line, scatter, bar, fill/area, stackplot, stairs, histogram, boxplot, violin, hist2d, hexbin, pie, imshow, contour |
| [Chart.js chart docs](https://www.chartjs.org/docs/latest/charts/bar.html) | area, bar, bubble, doughnut/pie, line, mixed, polar area, radar, scatter |
| [Highcharts demos](https://www.highcharts.com/demo) | line, area, column/bar, pie, scatter/bubble, heatmaps, treemaps, stock charts, maps |
| [Vega-Altair gallery](https://altair-viz.github.io/gallery/index.html) | bar, line, area, scatter, histogram, heatmap, distributions, maps, interactive selections |
| [Apache ECharts examples](https://echarts.apache.org/examples/en/index.html) | line, bar, pie, scatter, effect scatter, radar, heatmap, candlestick, boxplot, parallel, Sankey, funnel, gauge, tree, treemap, sunburst, graph, theme river, pictorial bar, calendar, custom series |
| [Seaborn gallery](https://seaborn.pydata.org/examples/index.html) | scatter, line, histogram, KDE, ECDF, box, violin, boxen, strip, swarm, heatmap, clustermap, pair/joint plots, regression/residual plots |
| [Bokeh gallery](https://docs.bokeh.org/en/latest/docs/gallery.html) | line, scatter, bar, patches, image, heatmap, contour, candlestick, maps, network, linked brushing, streaming |
| Internal design dossier, section 28 and 24 | bar/histogram, heatmap, box/violin, candlestick/OHLC as important compatibility targets |

## 2D-First Priority Roadmap

### P0 - Already in place

| Chart | Status | Notes |
|---|---|---|
| Line | Implemented | Direct and M4-decimated line rendering. |
| Scatter | Implemented | Direct, color/size channels, density tier, hover, box select. |
| Bubble | Mostly covered | Scatter with `size=` already covers the core bubble use case; add a named alias later. |
| Area | Implemented core | Filled time-series area with scalar/array baselines and optional line overlay. |
| Histogram | Implemented core | Python-side binning plus shared rectangle renderer. |
| Bar / column | Implemented core | Category/numeric axes, grouped, stacked, vertical, horizontal. |
| Heatmap | Implemented core | 2D matrix to compact colored grid texture with numeric or categorical axes. |

### Ranked 2D coverage backlog

This list is ordered from most common/user-expected to most specialized or
compatibility-oriented. Some rows are chart families so the obscure variants do
not fall out of sight.

| Rank | Chart family | Includes / aliases | Status | Why it matters |
|---:|---|---|---|---|
| 1 | Line and time series | line, step line, spline, markers+line, multi-line, streaming line | Implemented core | Most universal analytical chart; core for finance, monitoring, science, product metrics. |
| 2 | Scatter / marker plots | scatter, scattergl-style, bubble, colored scatter, sized scatter | Implemented core | Large-point interactivity is the xy wedge; basis for drilldown, selection, and density. |
| 3 | Bar / column | vertical bar, horizontal bar, grouped, stacked, normalized stacked, diverging bar | Implemented core | `xy.bar(...)` / `xy.column(...)` ship categorical/numeric vertical and horizontal bars, grouped bars, stacked bars, and normalized stacked bars (`mode="normalized"`) through the shared rectangle renderer. Follow-up: labels. |
| 4 | Area | filled line, stacked area, streamgraph, ridgeline-lite area bands | Implemented core | `xy.area(...)` ships a filled area with scalar/array baseline and optional line overlay. Follow-ups: stacked area helpers and streamgraph offsets. |
| 5 | Histogram | count, probability, density, cumulative histogram | Implemented core | Python-side binning plus the shared rectangle renderer; `cumulative=True` (count CDF and, with `density=True`, empirical CDF) is implemented. Follow-up: viewport-aware re-binning for huge streamed distributions. |
| 6 | Pie / donut | pie, donut, nested donut, variable-radius pie | Implemented in `xy.pyplot` | Native pie/donut tessellation with Matplotlib-style containers and labels; richer nested/variable-radius composition remains future depth. |
| 7 | Heatmap / image / matrix | heatmap, image, annotated matrix, correlation matrix, cohort heatmap | Implemented core | `xy.heatmap(...)` renders matrix cells through a compact grid texture with continuous colormaps and categorical/numeric axes. Native static export borrows canonical f64 spans and normalizes only sampled pixels in Rust, verified through 4.29B cells without a derived grid or RGBA expansion. Follow-ups: annotation and tiled huge-image browser transport. |
| 8 | Box plot | box, grouped box, notched box, outlier points | Implemented core | Tukey quartiles, whiskers, median, deterministic outliers, numeric or categorical groups. |
| 9 | Candlestick / OHLC | candlestick, OHLC bars, volume overlay, range selector | Prototyped (PR closed unmerged) | `xy.candlestick(...)`/`xy.ohlc(...)` + `xy.candlestick_chart(...)` on the closed `codex/finance-charting-surface` exploration branch: OHLC decimation, shared-y f32 frame, time axes, hover, and a volume pane. Critical finance surface; inherits LOD and time-axis work from core primitives. |
| 10 | Error and interval charts | error bars, error bands, confidence intervals, line range, bar range, whisker, rule | Implemented core | Instanced segment error bars and M4-reduced filled error bands. |
| 11 | 2D density charts | 2D histogram, hexbin, density heatmap, KDE contours | Implemented core | Native-kernel occupied-bin hexbin plus bounded density payloads. |
| 12 | Violin and distribution shapes | violin, split violin, KDE plot, density ridge | Implemented core | Bounded-resolution smoothed distribution bands through the rectangle renderer. |
| 13 | Contour | contour, filled contour, isolines | Implemented core | Marching-squares isolines over regular grids, optionally layered on heatmap fill. |
| 14 | Waterfall | waterfall, bridge chart | Planned | Business reporting and finance expectation; mostly categorical bars plus running baseline. |
| 15 | Funnel | funnel, funnel area, conversion funnel | Planned | Product analytics and sales/ops dashboard expectation. |
| 16 | Treemap | treemap, squarified treemap | Planned | Common BI hierarchy chart; requires layout and label polish. |
| 17 | Sunburst / icicle | sunburst, icicle, radial hierarchy | Planned | Plotly/Highcharts/ECharts compatibility for hierarchical data. |
| 18 | Radar / polar | radar, spider, polar area, radial bar | Planned | Common in Chart.js/Highcharts; needs polar axes and interaction semantics. |
| 19 | Gauge / indicator | gauge, bullet, KPI indicator | Planned | Dashboard compatibility; mostly DOM/SVG/canvas chrome rather than large-data rendering. |
| 20 | Small multiples | facet grid, repeat chart, trellis chart, pair grid | Implemented core | `xy.facet_chart(...)` builds per-panel screen-bounded Figures with optional shared domains. |
| 21 | Scatter matrix / pair plots | SPLOM, pairplot, corner plot | Planned | High-value exploratory data analysis; should reuse scatter kernels across many panels. |
| 22 | Joint/distribution composites | joint plot, marginal histogram, marginal rug, scatter+hist combo | Planned | Common Seaborn/Plotly workflow; depends on clean chart composition. |
| 23 | Regression diagnostics | trendline, regression line, residual plot, QQ plot, PP plot | Planned | Data-science compatibility and model-evaluation workflows. |
| 24 | Categorical distributions | strip, swarm, beeswarm, boxen, rug | Planned | Seaborn-style stats breadth; requires jitter/packing and distribution summaries. |
| 25 | Step/stairs/stem/lollipop | stairs, step area, stem, lollipop | Implemented core | Step/stairs remain compact line inputs; stems reuse instanced segments and points. |
| 26 | Slope/bump/dumbbell | slopegraph, bump chart, dumbbell, connected dot plot | Planned | Popular editorial/business comparisons; composition of line + point + labels. |
| 27 | Timeline/Gantt/event charts | event timeline, bar range, Gantt, milestone chart | Planned later | Useful for operations/product; more UI/axis polish than rendering complexity. |
| 28 | Calendar charts | calendar heatmap, contribution graph, daily cohort grid | Planned later | Product analytics and ops compatibility; grid + date-axis specialization. |
| 29 | Parallel coordinate/category | parallel coordinates, parallel categories, alluvial-lite | Planned later | Present in Plotly/ECharts; useful for high-dimensional EDA. |
| 30 | Sankey / alluvial | Sankey, alluvial, dependency wheel | Planned later | Important flow chart, but requires layout and interaction work. |
| 31 | Network/tree/org | network graph, force graph, tree, dendrogram, org chart, arc diagram | Planned later | Valuable but layout-heavy; should follow core 2D marks. |
| 32 | Scientific vector fields | quiver, barbs, streamplot, wind rose | Implemented in `xy.pyplot` | Quiver, barbs, and bounded streamlines feed shared instanced segments; wind rose remains tied to future polar axes. |
| 33 | Irregular grid science | pcolormesh, tricontour, tripcolor, triangular mesh | Implemented in `xy.pyplot` | Curvilinear quads and explicit/native triangulations route through indexed meshes and marching-triangle kernels. |
| 34 | Specialist coordinate systems | ternary, Smith chart, carpet plot, polar scatter/line/bar | Planned later | Plotly/science compatibility; axis systems are the main work. |
| 35 | Finance advanced | VWAP, moving averages, Bollinger bands, RSI, MACD, depth chart, order book heatmap, market profile, Renko, Heikin-Ashi, Kagi, point-and-figure | Prototyped (PR closed unmerged) | The closed `codex/finance-charting-surface` exploration branch has a `FinanceChart`/`FinanceLayer` system with volume bars, SMA, VWAP, Bollinger bands, RSI, and MACD as overlay/pane layers plus drawings. Remaining: depth/order-book, market profile, Renko/Heikin-Ashi/Kagi/P&F. |
| 36 | Maps and geo | choropleth, tile choropleth, point map, bubble map, density map, route map, filled-area map | Deferred 2D domain | 2D, but requires projection/tile/geography stack; do after core chart breadth. |
| 37 | Statistical evaluation | ROC, precision-recall, lift, calibration, Manhattan, volcano | Planned later | Mostly composed line/scatter variants with domain helpers. |
| 38 | Composition/part-to-whole extras | waffle, mosaic/Mekko, variwide, packed bubble, Venn/Euler | Planned later | Useful compatibility charts; mostly layout algorithms plus rectangles/circles. |
| 39 | Decorative/compatibility series | pictorial bar, item chart, text marks, image markers, custom symbol scatter | Planned later | ECharts/Highcharts-style polish and compatibility after core performance work. |
| 40 | Tables and table-adjacent views | table, pivot-like summary, annotated table | Deferred dashboard surface | Plotly includes tables, but they are dashboard UI, not core chart rendering. |

### P1 - Add next

| Rank | Chart | Why it is popular | Why it fits xy | Suggested API |
|---:|---|---|---|---|
| 1 | Histogram | Core statistical chart in Plotly, Matplotlib, Altair; common first chart for distributions. | Implemented core: Python-side binning + shared instanced rectangle renderer, incl. `density` and `cumulative` modes. Follow-up: viewport-aware re-binning for very large streamed distributions. | `xy.histogram_chart(xy.hist(values, bins=512, cumulative=True))` |
| 2 | Bar / column | Present in every major library; expected for categorical comparison. | Implemented core: category axis + shared instanced rectangle renderer for basic, grouped, stacked, normalized stacked, and horizontal bars. Follow-up: labels. | `xy.bar_chart(xy.bar(x, y))` |
| 3 | Area / filled line | Common extension of line charts in Plotly, Chart.js, Highcharts, Altair. | Implemented core: sorted x, M4 first payload, and filled WebGL segment strips. Follow-up: stacked area helper. | `xy.area_chart(xy.area(x, y))` |
| 4 | Heatmap / image | Common in scientific and BI tools; Matplotlib, Plotly, Altair, Highcharts all surface it. | Implemented core: matrix-to-grid texture path with color channel reuse. Follow-up: image/raster tiling for huge grids. | `xy.heatmap_chart(xy.heatmap(z, x=None, y=None))` |

P1 and the first statistical breadth block are now implemented at the core
primitive level. The next implementation block can focus on compatibility
depth: strip/swarm/boxen/rug distributions, regression diagnostics, richer
2D-density hover/readout semantics, and scatter-matrix/joint-plot composition.

### P2 - Statistical and analytical breadth

| Rank | Chart | Why it matters | Implementation shape |
|---:|---|---|---|
| 5 | Box plot | Standard distribution summary in Plotly, Matplotlib, Altair, and many dashboards. | Implemented: quartiles/outliers plus compact rectangle/segment geometry. |
| 6 | Violin plot | Common in data science, especially alongside box plots. | Implemented: bounded smoothed density bands. |
| 7 | Error bars / bands | Popular for scientific charts and uncertainty displays. | Implemented: instanced line segments and filled area bands. |
| 8 | ECDF / cumulative histogram | Common distribution diagnostic and cheap to render. | Implemented: exact unique-value mode and native histogram approximation. |
| 9 | 2D histogram / hexbin | Popular for dense scatter analysis and present in Matplotlib/Plotly/Altair. | Implemented hexbin; future work is richer hover/readout and 2D histogram aliases. |
| 10 | Contour / filled contour | Common scientific chart and Plotly/Matplotlib compatibility target. | Implemented regular-grid marching-squares isolines and optional fill. |
| 11 | Strip / swarm / boxen / rug | Seaborn-style categorical distribution charts. | Reuse points plus jitter/packing and compact summaries. |
| 12 | Regression and diagnostics | Trendlines, residuals, QQ/PP, ROC/PR/lift/calibration. | Mostly composed line/scatter helpers plus optional stats kernels. |

### P3 - Composition, overlays, and domain charts

| Rank | Chart | Why it matters | Caveat |
|---:|---|---|---|
| 13 | Composed / mixed charts | Overlay line, scatter, bars, bands, candlesticks, and secondary axes cleanly. | API and spec work comes before many chart families. |
| 14 | Pie / donut | Very popular in basic chart libraries and user expectations. | Implemented through `xy.pyplot`; future work is composition and styling depth. |
| 15 | Candlestick / OHLC | Important for finance users and appears in Plotly/Highcharts stock tooling. | **Prototyped (PR closed unmerged):** candlestick/OHLC marks with date axes, gaps, and hover format on the closed finance exploration branch. Remaining polish: range selectors. |
| 16 | Finance overlays | Volume bars, VWAP, moving averages, Bollinger bands, depth/order-book heatmap, market profile, Renko, Heikin-Ashi, Kagi, point-and-figure. | **Prototyped (PR closed unmerged):** volume pane, SMA, VWAP, Bollinger, RSI, MACD as `FinanceLayer`s reusing composed charts + time axes. Remaining: depth/order-book, market profile, Renko/Heikin-Ashi/Kagi/P&F. |
| 17 | Waterfall | Common in business reporting and Plotly/Highcharts. | Mostly categorical bars plus running baseline. |
| 18 | Funnel / funnel area | Common sales/product analytics chart. | Mostly categorical geometry plus labels. |
| 19 | Calendar/cohort heatmap | Common product analytics and retention surface. | Grid plus date semantics. |
| 20 | Gantt/timeline/event charts | Product/project/ops domain chart. | High UI polish and interaction expectations. |

### P4 - Hierarchy, flow, graph, and dashboard breadth

| Rank | Chart family | Why it matters | Caveat |
|---:|---|---|---|
| 21 | Treemap | Common BI hierarchy chart. | Requires layout algorithm, labels, and color scale polish. |
| 22 | Sunburst / icicle | Plotly/ECharts hierarchy compatibility. | Requires hierarchy layout and radial/rectangular variants. |
| 23 | Sankey / alluvial / dependency wheel | Common flow visualization in BI and systems analysis. | Layout and interaction are the hard parts. |
| 24 | Network / tree / org / dendrogram / arc | Graph and hierarchy compatibility. | Requires graph layout algorithms and selection semantics. |
| 25 | Gauge / bullet / indicator | Dashboard/KPI compatibility. | Mostly chrome and layout, not large-array rendering. |
| 26 | Table-adjacent views | Table, pivot-like summary, annotated table. | Useful in dashboards, but not a chart-rendering primitive. |

### P5 - Scientific, coordinate-system, and obscure compatibility

| Rank | Chart family | Why it matters | Caveat |
|---:|---|---|---|
| 27 | Radar / polar / radial bar | Common in Chart.js/Highcharts and dashboards. | Needs polar axes and interaction semantics. |
| 28 | Ternary / Smith / carpet | Plotly/scientific compatibility. | New coordinate systems, not new mark primitives. |
| 29 | Quiver / barbs / streamplot / wind rose | Scientific and engineering vector fields. | Quiver, barbs, and streamplot are implemented through `xy.pyplot`; wind rose awaits polar support. |
| 30 | Pcolormesh / tricontour / tripcolor | Matplotlib-style irregular grid science. | Implemented through `xy.pyplot` with native quad/triangle geometry. |
| 31 | Waffle / mosaic / Mekko / variwide | Business/category compatibility. | Mostly rectangle layout algorithms. |
| 32 | Packed bubble / Venn / Euler | Compatibility and presentation charts. | Layout algorithms and label placement dominate. |
| 33 | Pictorial bar / item chart / image markers / text marks | ECharts/Highcharts compatibility polish. | Symbol systems and asset handling. |

### P6 - 2D domains to defer until core breadth is strong

| Chart family | Reason to defer |
|---|---|
| Maps / choropleth / geo scatter / routes / density maps | 2D, but requires projection, tile, geography data, and viewport semantics; valuable as a later domain package. |
| 3D scatter / surface / volume | Explicitly outside the 2D-first roadmap; different rendering and interaction model. |

### P7 - Long-term breadth target

The long-term target is not only "fast large scatter." It is an expansive
library with enough chart breadth to be used across industries the way Plotly is
used today, while keeping xy' transport and rendering model underneath.

| Industry / use case | Chart coverage needed |
|---|---|
| Business intelligence and operations | bar, stacked bar, waterfall, funnel, treemap, table-adjacent summaries, dashboards |
| Data science and statistics | histogram, box, violin, ECDF, density, hexbin, scatter matrix, regression/error bands |
| Science and engineering | heatmap, image, contour, error bars, uncertainty bands, streaming time series |
| Finance | candlestick, OHLC, volume bars, indicators, range selectors, multi-axis time series |
| Geography and logistics | point maps, choropleth, density maps, lines/routes, projected scatter |
| Product analytics | cohort heatmaps, retention curves, funnels, event timelines, linked cross-filters |

Breadth should arrive after the core primitives are solid:

1. rectangle marks for bar/histogram/waterfall/funnel,
2. filled polygons for area/bands/violin,
3. grid textures for heatmap/image/density,
4. domain-specific axes and hover formatting,
5. small-multiple and dashboard composition,
6. accessibility, export, theming, and Plotly-compatibility coverage.

## Cross-Cutting: Adaptive Scatter LOD

How xy answers "density is too blunt — zooming in should reveal real
points." The dossier already prescribes this (§5: `tier = f(visible_count, …)`,
not total count; transitions hysteresis-guarded), and the literature agrees on
the shape: imMens/Nanocubes bound work by *screen* resolution via tiles and
hierarchical aggregates; datashader rasterizes; plotly-resampler re-aggregates
per view; deck.gl documents why 10M visible markers die on fill-rate/overdraw.

**Where the machinery lives (reuse seams for new chart kinds):** the tier
logic is chart-agnostic and factored out on both sides of the wire —
`python/xy/lod.py` (visible-window mask, hysteresis drill decision,
drilled-subset bookkeeping incl. `drill_seq`, §16 window-centered encoding,
screen-derived grid shape, per-point local log-density, wire-buffer packing)
and `js/src/45_lod.js` (drill lifecycle with entry/exit fades and the dying
state, density-source cache, texture crossfades, eased exposure
normalization). `interaction.density_view` and ChartView are thin scatter
wiring over these; a heatmap or histogram tier should reuse them with a
different aggregate kernel rather than copy the logic (§28 per-kind rules).
Channel shipping is shared too (`channels.ship_channels`) — the build path
and drill updates emit the same wire shape.

**Implemented — drill-in/drill-out (the §5 visible-count rule):**

- Zoomed out, a Tier-2 scatter renders as the density texture (screen-bounded).
- Every pan/zoom already round-trips `density_view`; the kernel now counts the
  points in the window and, when they fit the direct budget (200k), ships the
  *actual visible points* — color/size channels restored, normalized over their
  global domain so styling is stable across views — instead of a grid. Hover
  picking and box-select work on the drilled points (shipped→canonical index
  translation). Zooming back out returns to density. Enter/exit is
  hysteresis-guarded (1.15×) so the boundary doesn't thrash. Every decision
  rides the update as `mode` + `visible` (§28, never silent).

**Partially built / not yet built (the rest of the §5 ladder, in rough order of value):**

- *Hybrid overlay* — exact-scan density views now render a density background
  plus a deterministic stratified sample of real points, with an explicit
  "sampled n of N" badge. Pyramid-served views retain and viewport-clip that
  deterministic overlay instead of dropping it on the first interaction.
  Remaining work: make pyramid-served density views produce tile-aware sampled
  overlays without rescanning raw rows.
- *Standalone (kernel-less) refinement* — **shipped.** A `to_html` export used
  to stretch the overview texture on zoom; it now re-bins the retained sample
  in a bundled Web Worker (off the main thread, `worker-src blob:` CSP),
  swapping in a view-fitted grid with a "zoom re-binned from sample" badge and
  restoring the full overview at the home view.
- *Data-space tile pyramid* — today zoom-out re-bins the visible window
  (O(visible points)); the pyramid makes pan pure tile reuse and zoom a level
  step, O(visible tiles) per frame after a one-pass build (~1.33× cost).
- *Progressive refinement* (§17) — bin a 1-in-k sample first so a coarse
  density appears <100 ms, refine over subsequent frames.
- *Per-bin channel aggregation* (§5-F5) — mean/max color per density cell, so
  a zoomed-out colored scatter keeps *some* channel signal instead of
  `channels_dropped`.

## Cross-Cutting: Styling & Theming

These are not chart types but engine-wide styling capabilities. They are tracked
here so breadth work (item 6 above) has a concrete backlog.

### Mark-level styling (shipped)

The marks themselves speak CSS. `fill=` accepts a real CSS
`linear-gradient(...)` (mark-space or plot-space); bars/rects take
`corner_radius` (scalar or independent `(tip, base)`), `stroke`, and
`stroke_width`; lines and area outlines take `dash` (presets or an on/off
pattern); line/area take `curve="smooth"` (monotone-cubic); scatter takes 17
renderer-backed `symbol` glyphs plus point strokes. Mark colors
flow through the same `--chart-*` tokens as the chrome, so a theme change
re-resolves marks and chrome together. The full matrix and per-mark support
table live in [`docs/engineering/styling.md`](styling.md). Static SVG export reproduces all
of it (gradients → `<linearGradient>`, smooth curves → exact cubic Béziers,
etc.) with two documented approximations (area mark-space gradient uses the
bbox; `var()` colors fall back to the mark color — no DOM).

### Tailwind / utility-class styling (shipped)

Today the client already resolves colors *through the DOM* (§36): `currentColor`
and the `--chart-*` custom properties (`--chart-bg`, `--chart-grid`,
`--chart-axis`, `--chart-text`) feed axis/grid/label/mark colors, and mark
colors accept any CSS expression (`var(--brand-500)`, named colors, etc.). So
Tailwind can already drive the chart's **theme** by setting a text color or those
variables on the container, and can style the wrapper freely.

**Status: shipped.** Every DOM chrome element now carries a `data-xy-slot`
attribute and takes per-slot `class_names` / `chrome_styles`, and its *visual*
defaults live in a single low-priority `base` cascade layer with
zero-specificity `:where([data-xy-slot="…"])` selectors, injected once per
document. Tailwind's later utility layer, unlayered author CSS, and inline
`chrome_styles` therefore win over the built-in look **without `!important`** —
verified in a real browser (a `.bg-*` class on the tooltip changes its computed
background). The
elements keep only *structural* inline styles (position/size/z-index/state), so
nothing themeable competes with a user class. The full slot list (including
`legend_swatch`, `tick_label`, `axis_title`, and the class-driven modebar
active state via `--chart-modebar-active`) is `xy.CHART_DOM_SLOTS`.

For a fixed chart, the Reflex adapter also mirrors embedded class strings into
generated JSX for Tailwind's compile-time scan. Runtime token/Var charts must
put their complete names in ordinary host source or a safelist. For the
standalone `to_html(...)` export — which has no host page to inherit Tailwind
from — pass `custom_css="…"` to inject the stylesheet defining those utility
classes.

Explicitly **out of scope** (browser limit, not a backlog item): the plotted
marks are WebGL2 canvas pixels — no CSS, Tailwind or otherwise, can style them.
Mark appearance stays driven by the spec and resolved CSS colors.

**Performance:** the `:where()` defaults are one static stylesheet injected
once per document (not per frame, not per hover), so the class hook adds no
draw-loop cost; the pre-existing `resolveCssColor` note below still applies only
to the theme-token read path.

**Performance guardrail (why this stays bounded):** CSS-color
resolution goes through `resolveCssColor`, which appends a probe element and calls
`getComputedStyle` — a style/layout flush. That is acceptable today because it
runs only at theme-read time and is effectively cached, never in the draw loop.
Any broadening of class-driven styling must keep resolution out of the hot
path (cache resolved colors; re-resolve only on explicit theme change, not per
frame or per hover) and must not reintroduce layout thrash on the tooltip's
per-hover repositioning — backed by a `scripts/bench.py` TTFR /
interaction-latency comparison, not assumed.

## Recommended Sequence

The first breadth milestone — **histogram, bar/column, area, heatmap** — and
the first statistical block — **box, violin, ECDF, error bars/bands, hexbin,
contour, steps/stairs/stems, and facets** — are done. The first alpha
(`v0.0.1`) is launched with a live docs site and the reflex-xy adapter on
`main`; the next sequence is therefore stabilization and compatibility depth,
not re-implementing shipped primitives.

1. **Stabilize the launched `v0.0.1` alpha.** `v0.0.1` is released on PyPI;
   its Pyodide wheel is runtime-verified but is not yet publicly distributed
   as a durable release asset (#97). The docs site is live, and the reflex-xy
   adapter is on `main` — so release/distribution correctness and the
   post-launch bug backlog are the current gate, not shipping. The interaction
   correctness issues (heatmap hover kernel crash, box-zoom view collapse,
   double-click blanking a dense Reflex scatter, reflex-xy static chart crash,
   FacetChart CSS leak) come before any new chart family.
2. **Reflex-first reactive API — shipped** (PR #55, `python/reflex-xy/`; see
   the capability-layer summary near the top of this doc). Remaining depth is
   adapter polish: install/packaging docs from a clean environment, linked
   facet interactions, and first-class pan/zoom controls surfaced through the
   component API.
3. **Statistical compatibility depth.** Add strip/swarm/boxen/rug,
   regression/diagnostic helpers, richer density hover/readout, and
   scatter-matrix/joint-plot composition on the shipped primitives.
4. **Pie / donut in the composition API.** Implemented in `xy.pyplot` today;
   promote to a core `xy.pie_chart(xy.pie(...))` surface with bounded arc
   geometry and label placement.
5. **Re-land the finance surface.** Open a fresh PR from the closed exploration
   branch, rebased onto current composition/LOD primitives, then extend the
   `FinanceLayer` system with depth charts, Heikin-Ashi, and Renko.

Parallel, non-chart-type tracks:

- **Native PNG rasterizer** (perf) — **shipped** (dossier Phase 3).
  `Chart.to_png(engine=Engine.default)`, now the default, paints the decimated
  payload with an AA rasterizer in the Rust core (introduced in ABI v8,
  `xy_rasterize`) — no browser, ~50× faster than the Chromium screenshot,
  fast truecolor PNGs, and a baked bitmap font for text. `optimize=True`
  retains the slower indexed-palette path for smaller files;
  `engine=Engine.chromium` stays for an installed-browser CSS/WebGL screenshot.
- **Reflex-first reactive API** — **shipped** (PR #55): the reflex-xy adapter
  described in step 2 above, with websocket-multiplexed binary transport and
  computed-var figure binding.

## Near-Term API Sketch

```python
import xy

# shipped
xy.histogram_chart(xy.hist(values, bins=512, density=False, cumulative=False))
xy.bar_chart(xy.bar(categories, values, mode="grouped", orientation="vertical"))
xy.area_chart(xy.area(x, y, base=0.0))     # + fill=linear-gradient, curve, dash
xy.heatmap_chart(xy.heatmap(z, x=None, y=None, colormap="viridis"))
xy.box_chart(xy.box(values, group=None))
xy.violin_chart(xy.violin(values, group=None, bandwidth="auto"))
xy.chart(xy.errorbar(x, y, yerr=..., xerr=...))
xy.chart(xy.hexbin(x, y, gridsize=50, color_scale="log"))
xy.candlestick_chart(xy.candlestick(x, open, high, low, close))  # prototyped (closed finance PR)

# next
xy.pie_chart(xy.pie(values, labels=..., donut=0.0))
```

New chart kinds land as composition marks plus a family container
(`xy.box_chart(xy.box(...))`, `xy.pie_chart(xy.pie(...))`, …).

## Decision Summary

The rectangle/polygon/grid-texture foundations, statistical breadth block,
full mark styling, native PNG rasterizer, and the **Reflex-first reactive API**
(reflex-xy adapter) are in place, and `v0.0.1` is launched with a live docs
site. The next product track is **post-launch stabilization** (the open
interaction/adapter bug backlog), followed by statistical compatibility depth
and **pie/donut** in the composition API. Finance (candlestick plus
indicators) remains prototyped on a closed exploration branch awaiting a fresh
landing.
