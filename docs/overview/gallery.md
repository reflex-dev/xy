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

- [Line and area](/docs/xy/charts/line-and-area/) for trends and ranges
- [Scatter](/docs/xy/charts/scatter/) for relationships and encoded channels
- [Bar and column](/docs/xy/charts/bar-and-column/) for category comparisons
- [Distributions](/docs/xy/charts/distributions/) for histograms, ECDFs, boxes,
  and violins
- [Density and grids](/docs/xy/charts/density-and-grids/) for heatmaps,
  hexbins, and contours
- [Uncertainty](/docs/xy/charts/uncertainty/) for error bars and bands
- [Specialized charts](/docs/xy/charts/specialized/) for stems, segments,
  and triangle meshes
- [Annotations](/docs/xy/components/annotations/) for rules, bands, labels, arrows,
  callouts, and threshold zones
- [Facets and layers](/docs/xy/charts/facets-and-layers/) for small multiples
  and composed overlays
