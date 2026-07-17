---
title: Chart Factories
description: Reference XY chart containers, shared props, and facet construction.
---

# Chart Factories

Chart factories compose marks, axes, annotations, and chrome into a public
`Chart`. The generated inventory below follows the same taxonomy as the
[Chart Gallery](/docs/xy/overview/gallery/). Its names, signatures, and
defaults come directly from XY's public Python callables.

Use `chart()` when different mark kinds share a panel. A family container is
usually clearer when the children represent one chart family.

## Generated Factory API

~~~python exec
from xy_docs.api_reference import chart_containers_api, chart_factories_api
~~~

~~~python eval
chart_factories_api()
~~~

Annotation-only compositions use the neutral `chart()` container, so that
factory appears under Annotations. It also appears beside `facet_chart()` in
Facets and Layers because layered marks use the same neutral container.

## Shared Chart Props

~~~python eval
chart_containers_api()
~~~

The “Shared chart props” table is generated from the public `Chart`
constructor. Every ordinary factory accepts those props through `**props`;
`facet_chart` exposes its grid controls directly in its generated factory
table and forwards the remaining props to each panel.

## Facet Constraints

`facet_chart` requires `by=` values or a column name resolved from chart-level
`data=`. Its width and height must be positive integer pixel counts; panel
columns and gap are integers. Marks that use row-aligned raw channels must use
compatible arrays or column names so each panel can be subset safely.

Shared facet axes coordinate panel domains and browser viewport changes.
`FacetChart` supports display, export, and memory reporting, but does not expose
`Chart.append()`, `pick()`, or `select_range()`.

See [Composition model](/docs/xy/core-concepts/) for usage and
[Chart methods](/docs/xy/api-reference/figure-methods/) for the returned
objects.
