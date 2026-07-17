---
title: Chart Gallery
description: Choose the XY mark and container that match your data.
---

# Chart Gallery

XY chart families share one composition model and one output interface. Start
with a family container for a single mark type, or combine marks with `chart()`.

| Family | Components |
| --- | --- |
| Line and area | `line`, `area`, `step`, `stairs` |
| Scatter | `scatter` |
| Bar and column | `bar`, `column` |
| Distributions | `histogram`, `ecdf`, `box`, `violin` |
| Density and grids | `hexbin`, `heatmap`, `contour` |
| Uncertainty | `error_band`, `errorbar` |
| Specialized | `stem`, `segments`, `threshold`, `triangle_mesh` |
| Annotations | `hline`, `vline`, bands, `callout`, `arrow`, `marker`, `label`, `text`, `threshold_zone` |
| Facets and layers | `facet_chart`, `chart` |

The gallery covers XY's declarative chart families. The separate
[`xy.pyplot` integration](/docs/xy/integrations/matplotlib/) includes additional
Matplotlib-shaped methods that compile into these same rendering primitives.

Each family page follows the same path: when to use it, a live demo, common
variants, the expected data shape, and the options that matter most.

[Open the visual gallery](/docs/xy/overview/gallery/) or choose a family from
the table above.
