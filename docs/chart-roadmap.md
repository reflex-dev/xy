# Chart Type Roadmap

This roadmap prioritizes chart types by two signals:

1. **Popularity signal:** chart types that appear prominently across mainstream
   plotting libraries and galleries.
2. **fastcharts fit:** chart types where the engine can win on large data,
   binary transport, WebGL rendering, and screen-bounded aggregation.

The near-term wedge is large data, but the long-term product goal is broader:
fastcharts should become a **Plotly-class general-purpose charting library** for
analytics, science, finance, operations, and dashboards. Performance is the
entry point, not the boundary of the product.

The current implemented surface is **line** and **scatter**. Scatter already
covers direct points, color/size channels, GPU picking, selection, and Tier-2
density aggregation. Line already covers direct and M4-decimated time series.

## Source Signals

These sources are used as popularity proxies, not as exact usage telemetry:

| Source | Prominent chart types represented |
|---|---|
| [Plotly Python docs](https://plotly.com/python/) | scatter, line, area, bar, pie, bubble, error bars, box, histogram, 2D histogram, heatmap, time series, candlestick, OHLC |
| [Matplotlib plot types](https://matplotlib.org/stable/plot_types/index.html) | line, scatter, bar, fill/area, stackplot, stairs, histogram, boxplot, violin, hist2d, hexbin, pie, imshow, contour |
| [Chart.js chart docs](https://www.chartjs.org/docs/latest/charts/bar.html) | area, bar, bubble, doughnut/pie, line, mixed, polar area, radar, scatter |
| [Highcharts demos](https://www.highcharts.com/demo) | line, area, column/bar, pie, scatter/bubble, heatmaps, treemaps, stock charts, maps |
| [Vega-Altair gallery](https://altair-viz.github.io/gallery/index.html) | bar, line, area, scatter, histogram, heatmap, distributions, maps, interactive selections |
| Internal design dossier, section 28 and 24 | bar/histogram, heatmap, box/violin, candlestick/OHLC as important compatibility targets |

## Priority Roadmap

### P0 - Already in place

| Chart | Status | Notes |
|---|---|---|
| Line | Implemented | Direct and M4-decimated line rendering. |
| Scatter | Implemented | Direct, color/size channels, density tier, hover, box select. |
| Bubble | Mostly covered | Scatter with `size=` already covers the core bubble use case; add a named alias later. |

### P1 - Add next

| Rank | Chart | Why it is popular | Why it fits fastcharts | Suggested API |
|---:|---|---|---|---|
| 1 | Histogram | Core statistical chart in Plotly, Matplotlib, Altair; common first chart for distributions. | Huge data collapses to fixed bins; 1D binning is cheap and screen-bounded. | `Figure().hist(values, bins=512)` |
| 2 | Bar / column | Present in every major library; expected for categorical comparison. | Bars are bounded by categories; reuse instanced rectangle renderer needed by histograms. | `Figure().bar(x, y)` |
| 3 | Area / filled line | Common extension of line charts in Plotly, Chart.js, Highcharts, Altair. | Reuses sorted x, line decimation, and WebGL segment infrastructure; unlocks stacked area. | `Figure().area(x, y)` |
| 4 | Heatmap / image | Common in scientific and BI tools; Matplotlib, Plotly, Altair, Highcharts all surface it. | Existing scatter density already ships grid textures; this generalizes to user-provided grids. | `Figure().heatmap(z, x=None, y=None)` |

P1 should be the next implementation block. It maximizes user familiarity while
adding engine primitives that many later charts share: rectangles, filled
polygons, and grid textures.

## P2 - Statistical and analytical breadth

| Rank | Chart | Why it matters | Implementation shape |
|---:|---|---|---|
| 5 | Box plot | Standard distribution summary in Plotly, Matplotlib, Altair, and many dashboards. | Compute quartiles/outliers from canonical columns; draw compact geometry. |
| 6 | Violin plot | Common in data science, especially alongside box plots. | Compute KDE or bounded density grid; draw mirrored filled shape. |
| 7 | Error bars / bands | Popular for scientific charts and uncertainty displays. | Error bars as instanced line segments; bands as filled area around line. |
| 8 | ECDF / cumulative histogram | Common distribution diagnostic and cheap to render. | Sort or approximate from histogram bins; line/stairs renderer. |
| 9 | 2D histogram / hexbin | Popular for dense scatter analysis and present in Matplotlib/Plotly/Altair. | Generalize current density path; expose counts, log scaling, and hover readout. |

## P3 - Compatibility and domain charts

| Rank | Chart | Why it matters | Caveat |
|---:|---|---|---|
| 10 | Pie / donut | Very popular in basic chart libraries and user expectations. | Low fastcharts differentiation; implement for completeness, not performance. |
| 11 | Candlestick / OHLC | Important for finance users and appears in Plotly/Highcharts stock tooling. | Domain-specific polish matters: date axes, range selectors, gaps, hover format. |
| 12 | Waterfall | Common in business reporting and Plotly/Highcharts. | Mostly categorical bars plus running baseline. |
| 13 | Treemap | Common BI chart. | Requires layout algorithm, labels, and color scale polish. |
| 14 | Radar / polar | Common in Chart.js/Highcharts, less central to large-data analytics. | Needs polar axes and interaction semantics. |

## P4 - Defer until the engine is broader

| Chart family | Reason to defer |
|---|---|
| Maps / choropleth / geo scatter | Requires projection, tile, and geography stack; valuable but separate product surface. |
| 3D scatter / surface / volume | Different rendering and interaction model; can distract from 2D large-data strength. |
| Sankey / network / graph | Needs layout algorithms and graph-specific interactions. |
| Gantt | Product/project domain chart; high UI polish, not core large-array rendering. |
| Tables | Useful in dashboards, but not a chart-rendering primitive. |

## P5 - Long-term breadth target

The long-term target is not only "fast large scatter." It is an expansive
library with enough chart breadth to be used across industries the way Plotly is
used today, while keeping fastcharts' transport and rendering model underneath.

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

How fastcharts answers "density is too blunt — zooming in should reveal real
points." The dossier already prescribes this (§5: `tier = f(visible_count, …)`,
not total count; transitions hysteresis-guarded), and the literature agrees on
the shape: imMens/Nanocubes bound work by *screen* resolution via tiles and
hierarchical aggregates; datashader rasterizes; plotly-resampler re-aggregates
per view; deck.gl documents why 10M visible markers die on fill-rate/overdraw.

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

**Not yet built (the rest of the §5 ladder, in rough order of value):**

- *Data-space tile pyramid* — today zoom-out re-bins the visible window
  (O(visible points)); the pyramid makes pan pure tile reuse and zoom a level
  step, O(visible tiles) per frame after a one-pass build (~1.33× cost).
- *Progressive refinement* (§17) — bin a 1-in-k sample first so a coarse
  density appears <100 ms, refine over subsequent frames.
- *Hybrid overlay* — density background + a stratified sample of real points
  (rare categories/outliers kept) so zoomed-out views still show markers.
  Requires a sampling pass with an explicit "sampled" badge (§28).
- *Per-bin channel aggregation* (§5-F5) — mean/max color per density cell, so
  a zoomed-out colored scatter keeps *some* channel signal instead of
  `channels_dropped`.

## Cross-Cutting: Styling & Theming

These are not chart types but engine-wide styling capabilities. They are tracked
here so breadth work (item 6 above) has a concrete backlog.

### Tailwind / utility-class styling (candidate — gated on performance)

Today the client already resolves colors *through the DOM* (§36): `currentColor`
and the `--chart-*` custom properties (`--chart-bg`, `--chart-grid`,
`--chart-axis`, `--chart-text`) feed axis/grid/label/mark colors, and mark
colors accept any CSS expression (`var(--brand-500)`, named colors, etc.). So
Tailwind can already drive the chart's **theme** by setting a text color or those
variables on the container, and can style the wrapper freely.

What it does **not** cover, and what fuller Tailwind support would add:

- A `class_name` (and per-element class) passthrough so utility classes reach the
  DOM chrome — the tooltip, legend, and modebar currently use inline `cssText`,
  which beats utility classes on specificity and offers no class hook.
- Documented `--chart-*` theming recipes for Tailwind's arbitrary-property syntax.

Explicitly **out of scope** (browser limit, not a backlog item): the plotted
marks are WebGL2 canvas pixels — no CSS, Tailwind or otherwise, can style them.
Mark appearance stays driven by the spec and resolved CSS colors.

**Performance caveat (why this is a candidate, not a commitment):** CSS-color
resolution goes through `resolveCssColor`, which appends a probe element and calls
`getComputedStyle` — a style/layout flush. That is acceptable today because it
runs only at theme-read time and is effectively cached, never in the draw loop.
Before broadening class-driven styling we must confirm resolution stays out of the
hot path (cache resolved colors; re-resolve only on explicit theme change, not per
frame or per hover), and that classable chrome doesn't reintroduce layout thrash
on the tooltip's per-hover repositioning. If it can't be kept off the render path
without measurable cost, we keep the current `--chart-*` token surface and decline
the broader passthrough. Decision should be backed by a `scripts/bench.py` TTFR /
interaction-latency comparison, not assumed.

## Recommended Sequence

1. **Histogram**
   - Add native 1D binning kernel.
   - Render bins as instanced rectangles.
   - Support count, probability, density, cumulative.
   - Add hover for bin range and count.
   - Benchmark against Matplotlib, Plotly, Altair, Datashader.

2. **Bar / column**
   - Reuse rectangle renderer from histogram.
   - Support vertical, horizontal, grouped, stacked, normalized stacked.
   - Keep category counts bounded and warn above practical category ceilings.

3. **Area / stacked area**
   - Reuse line trace and sorted-x constraints.
   - Support baseline, opacity, stacked series, and gap handling.
   - Add confidence band variant when error bands land.

4. **Heatmap / image**
   - Reuse density texture upload and colormap path.
   - Support user-supplied 2D arrays, x/y ranges, log color scale, and colorbar.
   - Later merge with 2D histogram and hexbin.

5. **Box + violin**
   - Compute stats from canonical columns.
   - Keep rendered geometry tiny.
   - Add distribution benchmarks and exact hover summaries.

6. **Candlestick / OHLC**
   - Add finance-specific trace once bars, time axes, and hover formatting are solid.

## Near-Term API Sketch

```python
from fastcharts import Figure

Figure().hist(values, bins=512, density=False, cumulative=False)
Figure().bar(categories, values, orientation="vertical", stacked=False)
Figure().area(x, y, baseline=0.0, stacked=False)
Figure().heatmap(z, x=None, y=None, colormap="viridis", color_scale="linear")
Figure().box(values, group=None)
Figure().violin(values, group=None, bandwidth="auto")
```

Composition API equivalents should follow the current style:

```python
import fastcharts as fc

fc.histogram_chart(fc.histogram(x="latency_ms", data=df, bins=512))
fc.bar_chart(fc.bar(x="region", y="revenue", data=df))
fc.area_chart(fc.area(x="date", y="active_users", data=df))
fc.heatmap_chart(fc.heatmap(z=matrix))
```

## Decision Summary

The next chart should be **histogram**. It is popular, data-science-native, and
strongly aligned with fastcharts' screen-bounded performance story. After that,
add **bar/column**, **area**, and **heatmap** as the first breadth milestone.
