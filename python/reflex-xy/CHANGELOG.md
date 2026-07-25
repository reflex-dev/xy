# Changelog

All notable changes to **reflex-xy** (the Reflex adapter for xy) are
documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.0.1] — 2026-07-25

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
