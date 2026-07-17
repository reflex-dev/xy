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
- Browser context limits matter on large dashboards. XY's context governor
  defaults to 12 live contexts and reacquires off-screen charts as they return;
  more than that many simultaneously visible charts is not an unbounded
  guarantee.

## Styling and Export Boundaries

- Browser chrome accepts CSS and Tailwind classes through stable DOM slots.
  WebGL/native marks accept a validated CSS subset through `style=`; arbitrary
  selectors do not paint mark geometry.
- “Your styles win” applies to themeable browser chrome defaults, not every
  structural layout rule, mark renderer, annotation shape, or native export.
- Native PNG cannot apply author `custom_css`. Use renderable chart/mark styles
  or `Engine.chromium` for browser CSS fidelity.
- Declarative `colorbar()` is a visibility/style/replacement hook; it does not
  yet build a complete colorbar from a continuous mark channel.
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
