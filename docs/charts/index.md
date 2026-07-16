---
title: Charts
description: Choose the XY mark and container that match your data.
---

# Charts

XY chart families share one composition model and one output interface. Start
with a family container for a single mark type, or combine marks with `chart()`.

| Use case | Components |
| --- | --- |
| Trends and ranges | `line`, `area` |
| Point relationships | `scatter` |
| Category comparison | `bar`, `column` |
| Distributions | `histogram`, `box`, `violin`, `ecdf` |
| Gridded and dense data | `heatmap`, `hexbin`, `contour` |
| Uncertainty | `errorbar`, `error_band` |
| Discrete and geometric data | `step`, `stairs`, `stem`, `segments`, `triangle_mesh` |
| Small multiples | `facet_chart` |

Each mark accepts `data`, `class_name`, `style`, and named axis bindings where
applicable. Family-specific pages cover the remaining props and patterns.
