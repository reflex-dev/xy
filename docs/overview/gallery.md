---
title: Chart Gallery
description: Browse every chart type and visual pattern available in XY.
---

# Chart Gallery

Start with the visual result you need. Every public chart type is represented
below, grouped to match the Chart Gallery navigation. Each tile opens a focused
family page with guidance on when to use the chart, a live example, its expected
data shape, common variants, and the options that matter most.

~~~python exec
from xy_docs.gallery import chart_gallery_grid
~~~

~~~python eval
chart_gallery_grid()
~~~

Every preview is a code-native inline SVG, keeping this index quick and making
the artwork straightforward to restyle. Every linked family page includes a
full-size live demo.

All chart families use the same [composition model](/docs/xy/core-concepts/),
[data binding](/docs/xy/core-concepts/data/), styling surface, and display/export
methods. A family container such as `scatter_chart()` makes a single-family
chart easy to read; neutral `chart()` layers different marks in one panel.

Looking for a specific family?

- [Line](/docs/xy/charts/line-chart/) for trends, and
  [area, step, and stairs](/docs/xy/charts/area-chart/) for ranges and states
- [Scatter](/docs/xy/charts/scatter/) for relationships and encoded channels
- [Bar and column](/docs/xy/charts/bar-chart/) for category comparisons
- Distributions: [histogram](/docs/xy/charts/histogram/),
  [ECDF](/docs/xy/charts/ecdf/), [box plot](/docs/xy/charts/box-plot/), and
  [violin plot](/docs/xy/charts/violin-plot/)
- Density and grids: [heatmap](/docs/xy/charts/heatmap/),
  [hexbin](/docs/xy/charts/hexbin/), and [contour](/docs/xy/charts/contour-plot/)
- [Uncertainty](/docs/xy/charts/uncertainty/) for error bars and bands
- Specialized: [stem](/docs/xy/charts/stem-plot/),
  [segments](/docs/xy/charts/segments/), and
  [triangle mesh](/docs/xy/components/triangle-mesh/)
- [Annotations](/docs/xy/components/annotations/) for rules, bands, labels, arrows,
  callouts, and threshold zones
- [Facets and layers](/docs/xy/components/facets-and-layers/) for small multiples
  and composed overlays
