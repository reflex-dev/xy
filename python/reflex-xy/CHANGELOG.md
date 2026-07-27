# Changelog

All notable changes to **reflex-xy** (the Reflex adapter for xy) are
documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `reflex_xy.chart(..., tailwind_classes=...)` exposes complete utility names
  for live token/Var charts to Reflex's Tailwind build without leaking a scan
  prop into the DOM. It accepts a string or ordered iterable of strings, rejects
  mappings and unordered sets, merges with automatic static-chart discovery,
  de-duplicates utility tokens, and applies to every facet panel. Scan literals
  preserve quotes, backslashes, and Unicode instead of exposing JSON-escaped
  lookalike candidates to Tailwind.

### Fixed
- Live state-driven payloads rebuild when constructor-owned browser chrome
  changes (including root/slot classes, title, legend, colorbar, badge,
  modebar, or axis-band topology), so runtime Tailwind theme swaps do not
  retain stale nodes. Rebuilds silently restore every named-axis viewport and
  durable box/range/lasso geometry before refreshing the selection mask.
- Chart-root Tailwind typography utilities can override XY's default font,
  which now lives in the low-priority chrome stylesheet rather than an inline
  shorthand.
- Tailwind utilities can override legend-swatch paint and size, custom-tooltip
  chrome, and the default axis-title weight without competing with renderer
  inline defaults. Scatter/line SVG handles inherit defeatable fill, stroke,
  width, and dash paint from the same public swatch slot. Explicit `styles`
  values retain inline precedence.
- The public `selection` slot now reaches completed lasso paths and editable
  handles as well as box/range rectangles, while required handle pointer
  behavior remains intact.

## [0.0.1] — 2026-07-24

### Added
- First packaged release line of the adapter: `reflex_xy.chart()` components,
  `@reflex_xy.figure` state vars with rebuild-from-state recovery,
  `XYPlugin`/`setup()` app wiring, the `/_xy` socket.io data-plane namespace
  (binary columns on the app's own websocket), semantic hover/click/select/
  view events, fixed-data tiers (direct `Chart` + `inline()` tokens), and
  streaming `append`.
- The distribution version is derived from `reflex-xy-vX.Y.Z` git tags
  (uv-dynamic-versioning with `pattern-prefix = "reflex-xy-"`) instead of a
  number in `pyproject.toml`; canonical pre-release tags (`aN`/`bN`/`rcN`)
  publish too, and builds between tags are versioned `<next>.devN+<commit>`,
  which PyPI rejects by design. The adapter and core
  tag namespaces are mutually invisible by pattern anchoring: this derivation
  never sees bare `v*` tags, and the core's never sees `reflex-xy-*` ones.
  Releases publish via the dedicated
  `.github/workflows/release-reflex-xy.yml` workflow — deliberately separate
  from the core's cross-compile pipeline, since the adapter is one pure wheel
  plus one sdist with no build matrix — verified by
  `scripts/verify_reflex_xy_dist.py`, gated on this changelog, published with
  PyPI trusted publishing, and validated alongside the other workflows by
  `make check-ci`. `reflex_xy.__version__` now reports the installed
  distribution's version (an uninstalled tree reports `0.0.0`).
