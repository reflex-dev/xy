---
title: Public Types
description: Inventory XY's root-exported declarative, output, selection, and column types.
---

# Public Types

The supported root surface is available from `import xy`. Most users
construct lowercase factory results and only name these types in annotations.

## Declarative Types

| Type | Role |
| --- | --- |
| `Component` | Base type for declarative child specifications |
| `Mark` | Data geometry specification returned by mark factories |
| `Annotation` | Rule, band, label, marker, arrow, threshold, or callout |
| `Axis` | X or y scale and tick specification |
| `Legend` | Legend chrome or opaque framework replacement |
| `Tooltip` | Tooltip chrome or opaque framework replacement |
| `Colorbar` | Inferred continuous-scale chrome or opaque framework replacement |
| `Modebar` | Toolbar visibility and DOM styling |
| `Theme` | Validated chart theme tokens |
| `Interaction` | Browser interaction and linked-viewport configuration |
| `Animation` | Browser entrance/update policy and lifecycle callbacks |
| `Spring` | Serializable spring easing policy used by `animation()` |
| `Chart` | Public composed chart with display, export, and readout methods |
| `FacetChart` | Public small-multiple wrapper |

Directly constructing node dataclasses is supported for inspection and typing,
but the lowercase factories perform the intended validation and normalization.

## Output and Interaction Types

| Type | Role |
| --- | --- |
| `Selection` | Canonical selected indices grouped by trace, plus `index` and `xy()` helpers |
| `Engine` | PNG engine choice: `default` or `chromium` |

`Engine.default` currently selects XY's native, browser-free renderer.
`Engine.chromium` selects browser-fidelity export. Use enum members rather than
temporary historical string values.

## Canonical Column Types

| Type | Role |
| --- | --- |
| `Column` | Canonical contiguous f64 values, kind, copy accounting, and zone maps |
| `ColumnStore` | Per-figure canonical column owner with identity deduplication |
| `ZoneMaps` | Chunk statistics used by range and aggregation work |

These types are public for advanced inspection. They are not a separate
high-level data-frame API, and their internals may evolve during alpha.

## Public Constants

- `CHART_DOM_SLOTS` is the tuple of accepted browser chrome slot names.
- `__version__` reports the installed package version.

The old fluent `Figure` class is not root-exported. `Chart.figure()` returns an
internal engine object as an advanced escape hatch; do not import
`xy._figure.Figure` as an application API.

XY ships a package-wide `py.typed` marker. The authoritative runtime inventory
is `xy.__all__`, and [Marks and components](/docs/xy/api-reference/marks-and-components/)
contains generated callable signatures.
