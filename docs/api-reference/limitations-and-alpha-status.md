---
title: Limitations and Alpha Status
description: Understand XY's supported contracts, experimental surfaces, and known limits.
---

# Limitations and Alpha Status

XY is early alpha. The declarative API, implemented 2D chart families,
notebook display, standalone HTML, native PNG, and SVG are usable today, but
pre-1.0 releases can make breaking changes with migration notes.

| Surface | Current status |
| --- | --- |
| Declarative composition and 2D marks | Stabilizing alpha |
| Standalone HTML, native PNG, and SVG | Stable alpha |
| Required native Rust compute core | Stable alpha in published platform wheels |
| Reflex adapter | Separate prototype/experimental package |
| `xy.pyplot` compatibility | Experimental compatibility layer |
| Adaptive thresholds and drill protocol | Experimental implementation details |

## Data and Performance Boundaries

- Ingestion, canonical memory, initial scans, binning, and decimation still
  depend on source row count.
- Large-scatter overview rendering is screen-bounded when density mode is used;
  it does not draw one exact marker per source row.
- Long lines use screen-derived decimation. A narrow live view can request a
  new visible-window representation.
- Density is native-binned and GPU-rendered. It is not an all-GPU ingest and
  aggregation pipeline.
- Polar traces do not use Cartesian decimation, density, or refined-view
  tiers. `line`, `scatter`, and `area` render directly and reject more than
  200,000 points per trace. Heatmap and contour grids are not governed by that
  point ceiling.
- Arrow ingest is zero-copy only for compatible, null-free primitive layouts.
  Chunking, nulls, dtype conversion, and datetime conversion can copy.
- Disk-backed/out-of-core residency is not a shipped public tier.

See [Large data and performance](/docs/xy/core-concepts/large-data-and-performance/)
and [Benchmarks](/docs/xy/overview/benchmarks/) for scoped evidence.

## Interaction and Live-Data Boundaries

- Python callbacks require a live widget or framework adapter. Standalone HTML
  cannot call a Python process.
- `append()` supports scatter and line traces, not arbitrary chart structure.
  Line x values must continue monotonically, and encoded channel tails have
  validation constraints.
- Already-exported HTML is a snapshot and does not follow later appends.
- Linked views synchronize viewport axes, not selections or cross-filtering.
- Facets support display/export and shared domains but not `Chart` append,
  pick, or Python-side range-selection methods.
- Polar interaction currently consists of hover plus opt-in radial zoom about a
  fixed radial minimum. Zoom defaults to off (`xy.wind_rose()` excepted) and is
  enabled per chart with `xy.interaction_config(zoom=True)` or a `zoom=True` chart
  prop; reset is hidden unless zoom or an explicit `reset_axes` gives it axes to
  restore. `default_drag_action` accepts only `"auto"`/`"none"` on a polar chart.
  Authored sectors are supported; theta pan/rotation, interactive sector zoom, box
  zoom, selection, brushing, and crosshairs are disabled.
- Point-anchored `text`, `label`, `marker`, `arrow`, and `callout` annotations
  use the joint `(theta, r)` projection consistently on polar charts in the
  browser, SVG, and native raster output. Polar rules and bands remain deferred
  because they require spoke/ring and sector/annulus geometry, and raise at
  payload build instead of using Cartesian geometry.
- Polar histograms, box plots, hexbin/density, generic segments, and meshes
  remain outside the mark allowlist. Polar LOD, facets/animation, and angular
  navigation/selection are also deferred.
- Browser context limits matter on large dashboards. XY's context governor
  defaults to 12 live contexts and reacquires off-screen charts as they return;
  more than that many simultaneously visible charts is not an unbounded
  guarantee.

## Styling and Export Boundaries

The per-renderer inventory of what can be styled, and how far each mechanism
travels, is the [Capability Matrix](/docs/xy/styling/capabilities/) — generated
from `python/xy/styling/capabilities.py` and checked against the
implementation. The bullets below are the boundaries that page's rows imply.

- Browser chrome accepts CSS and Tailwind classes through stable DOM slots.
  WebGL/native marks accept a validated CSS subset through `style=`; arbitrary
  selectors do not paint mark geometry.
- “Your styles win” applies to themeable browser chrome defaults, not every
  structural layout rule, mark renderer, annotation shape, or native export.
- **Styling does not survive every export path equally, and the boundary is
  published rather than left to be discovered.** Mark, axis, and chart-level
  `style=` reach all three renderers. Per-slot `styles={slot: {...}}` reaches
  them for the nine slots that name chrome a static file contains — `title`,
  `axis_title`, `tick_label`, the three legend slots, and the three colorbar
  slots — carrying `font-size`, `font-weight`, `font-style`, `font-family`,
  `letter-spacing`, `opacity`, and the text paint. The remaining slots are live
  chrome (`tooltip*`, `modebar*`, `crosshair_*`, `selection`, `badge*`) with
  nothing in a file to paint, and `class_names={slot: "..."}` cannot apply in a
  file at all: a class selects a rule out of a stylesheet an exported file does
  not have. The native raster's baked atlas is one face, so PNG/JPEG/WebP honor
  a slot's size and paint but not its typeface. `xy.colorbar(style=...)` still
  has no native channel — use the `colorbar_*` slots. The full matrix is
  [Static export §9](https://github.com/reflex-dev/xy/blob/main/spec/api/export.md),
  pinned by `tests/test_export_style_survival.py`.
- Native PNG cannot apply author `custom_css`, and neither can native SVG, PDF,
  JPEG, or WebP. Unlike the per-slot case this one *raises* rather than
  dropping: an author stylesheet has no honest partial application. Use
  `Engine.chromium` for browser CSS fidelity — except for SVG, which rejects
  `custom_css` under every engine because a browser screenshot cannot produce
  vector output.
- Declarative `colorbar()` derives built-in chrome from supported continuous
  marks. It intentionally omits constant/categorical color, truecolor grids,
  and density scatter after that tier drops per-row color values.
- Self-contained HTML blocks network access but requires inline script/style
  and a `blob:` worker under its emitted CSP. A nonce/hash-only host must serve
  the bundle and data through its own wrapper.

## Accessibility and Browser Scope

The browser client ships a semantic chart region, generated trace/axis summary,
a polite live region, direct-point Arrow/Home/End navigation, named toolbar
controls, visible focus styling, reduced-motion behavior, and forced-colors
affordances.

That is not yet full accessibility parity. Current conformance does not cover
aggregated-bin keyboard navigation, a view-as-table escape hatch, every
screen-reader/OS combination, every chart family, or pixel-identical
cross-browser output. Test the actual chart and assistive-technology matrix
required by your application.

## Platform Boundary

XY requires Python 3.11 or newer. Published native wheels include the Rust core
and bundled browser client; source builds require a Rust toolchain. There is no
silent NumPy compute fallback when the native core is unavailable.

Review [Installation](/docs/xy/overview/installation/),
[Serving, CSP, and offline use](/docs/xy/guides/serving-csp-and-offline-use/),
and the [Changelog](/docs/xy/api-reference/changelog/) before shipping an
alpha upgrade.
