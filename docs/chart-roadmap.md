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
