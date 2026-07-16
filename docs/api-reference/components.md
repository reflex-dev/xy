---
title: Components API
description: Generated reference for XY containers, marks, annotations, and chart chrome.
---

# Components API

The tables on this page are generated from XY's public Python signatures. They
use the same shared API-table component as the official Reflex component docs,
so defaults and annotations stay aligned with the installed XY package.

## Chart Containers

Chart containers compose marks, axes, annotations, and chart chrome into a
renderable `Chart`. Regular containers accept shared chart props through
`**props`; `facet_chart` exposes its grid controls directly.

| Factory | Primary composition |
| --- | --- |
| `chart` | Mixed marks and overlays |
| `line_chart`, `area_chart` | Lines and filled areas |
| `scatter_chart` | Point marks and density views |
| `bar_chart`, `column_chart` | Horizontal and vertical bars |
| `histogram_chart`, `box_chart`, `violin_chart`, `ecdf_chart` | Distributions |
| `heatmap_chart`, `hexbin_chart`, `contour_chart` | Grids and density |
| `errorbar_chart`, `error_band_chart` | Uncertainty |
| `step_chart`, `stairs_chart`, `stem_chart` | Discrete series |
| `segments_chart`, `triangle_mesh_chart` | Explicit geometry |
| `facet_chart` | Small multiples |

~~~python exec
from xy_docs.api_reference import chart_containers_api
~~~

~~~python eval
chart_containers_api()
~~~

## Marks

Marks describe data geometry. The factories accept arrays directly or column
names resolved through `data=`.

~~~python exec
from xy_docs.api_reference import marks_api
~~~

~~~python eval
marks_api()
~~~

`hist` remains an alias of `histogram`.

## Axes and Annotations

Axes control scale presentation. Annotation factories add rules, bands, text,
markers, arrows, and callouts without changing the underlying data.

~~~python exec
from xy_docs.api_reference import axes_and_annotations_api
~~~

~~~python eval
axes_and_annotations_api()
~~~

## Chrome and Behavior

Chart chrome and interaction components configure legends, tooltips, color
scales, controls, themes, and input behavior.

~~~python exec
from xy_docs.api_reference import chrome_and_behavior_api
~~~

~~~python eval
chrome_and_behavior_api()
~~~

## Chart Methods

| Method | Result |
| --- | --- |
| `figure()` | Cached compiled engine figure |
| `show()`, `widget()` | Live notebook widget |
| `to_html(path=None, custom_css=None)` | Standalone interactive HTML |
| `html(...)` | Alias for `to_html` |
| `to_png(...)` | Native or Chromium PNG bytes/file |
| `to_svg(...)` | SVG string/file |
| `memory_report()` | Allocation and payload summary |
| `append(trace_id, x, y, ...)` | Extend an existing trace |
| `pick(trace_id, index)` | Exact canonical source row |
| `select_range(...)` | Python-side `Selection` |
| `chrome_components()` | Opaque framework chrome objects |
| `reflex_components()` | Alias for framework adapters |

## Public Types

`Chart`, `FacetChart`, `Component`, `Mark`, `Annotation`, `Axis`, `Legend`,
`Tooltip`, `Colorbar`, `Modebar`, `Theme`, `Interaction`, `Selection`, and
`Engine` describe the declarative and output surface. `Column`, `ColumnStore`,
and `ZoneMaps` expose the advanced canonical column storage types.
