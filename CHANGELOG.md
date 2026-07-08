# Changelog

All notable changes to **fastcharts** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/) once `1.0.0` ships;
pre-1.0, minor versions may contain breaking changes (see the stability table
in the README).

## [Unreleased]

### Added
- **CSS/Tailwind:** every DOM chrome element now takes per-slot `class_names` /
  `chrome_styles`, and its visual defaults live in one zero-specificity
  `:where([data-fc-slot="…"])` stylesheet — so a utility class or inline style
  overrides the built-in look **without `!important`**. New slots
  `legend_swatch`, `tick_label`, `axis_title`; class-driven modebar active
  state (`--chart-modebar-active`). `Figure.to_html(..., custom_css=...)`
  injects an author stylesheet so those classes resolve in the standalone
  export.
- `LICENSE` (Apache-2.0), `CHANGELOG.md`, `SECURITY.md`, root `CONTRIBUTING.md`.

### Changed
- **Performance:** WebGL client now uses vertex-array objects (no per-frame
  attribute re-binding), lazily compiles shader programs on first use, and
  ships a compacted bundle (193 KB → 154 KB) that every `to_html()` inlines.
- **Robustness:** the native C ABI wraps every entry point in a panic backstop
  (a kernel panic can no longer abort the host interpreter) and converges on
  `i32` status returns; ABI bumped to 7.

### Added
- Cumulative histogram mode: `Figure.histogram(..., cumulative=True)` and
  `fc.histogram(cumulative=...)`; combined with `density=True` it yields the
  empirical CDF.
- Normalized stacked bars: `mode="normalized"` on `Figure.bar` / `fc.bar`.
- Fluent/composition API parity guard test, preventing the two public
  surfaces from drifting apart.
- Prebuilt-wheel coverage expanded to a pydantic-class platform matrix:
  Linux glibc **and** musl/Alpine (x86-64, aarch64, armv7), macOS (x86-64,
  Apple Silicon), and Windows (x86, x64, arm64). An experimental
  Pyodide/Emscripten WASM wheel is built but does not yet load in-browser
  (`docs/production-readiness.md` documents the exact linker failure and fix
  direction).
- Release workflow `workflow_dispatch` dry-run mode: builds and verifies the
  full artifact matrix without publishing to PyPI (default for manual runs).
- `benchmark-refresh` CI workflow: regenerates the cross-library benchmark
  tables (10M scatter and core-2D) from a consistent Ubuntu run.
- Native fused kernels: `fc_sample_mask` (deterministic density-overlay
  sampling) and `fc_bin_2d_indices` (density grid + visible rows in one pass).
- Pyodide runtime load probe (`scripts/pyodide_load_smoke.py`), run
  non-gating in the wasm release job.

### Changed
- The native Rust core is now **required**: the NumPy fallback backend was
  removed. On platforms with no wheel and no local Rust build, importing the
  compute layer raises a clear, actionable `ImportError` instead of silently
  degrading. `import fastcharts` remains lightweight.
- The Reflex example app moved from `reflex_fastcharts_app/` to
  `examples/reflex/`.
- 10M scatter payload build is ~3x faster (fused kernels; ABI v6), and the
  published benchmark tables were re-measured with a warmup-corrected,
  tracer-free harness. Benchmark methodology fixes: library warmup before
  timing, timing separated from tracemalloc memory profiling, and RSS
  bracketing corrected.

### Removed
- `FASTCHARTS_FORCE_FALLBACK` environment switch and the pure-NumPy kernel
  backend (`fastcharts/_fallback.py`).

## [0.1.0] — unreleased development line

Initial development snapshot: line/scatter/area/histogram/bar/heatmap chart
families, binary columnar transport, WebGL2 rendering, M4 decimation, density
tiers with adaptive drilldown, standalone HTML export, anywidget notebook
integration, and the Reflex example dashboard.
