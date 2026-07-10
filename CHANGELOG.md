# Changelog

All notable changes to **fastcharts** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/) once `1.0.0` ships;
pre-1.0, minor versions may contain breaking changes (see the stability table
in the README).

## [Unreleased]

### Changed
- **API layering inverted: the declarative layer is now the core.** The nine
  mark-builder implementations moved verbatim from `figure.py` into the new
  `fastcharts/marks.py`; `Figure` binds them as its fluent methods
  (`Figure.scatter is marks.scatter`), so both dialects share one body, one
  signature, and one set of defaults. Payload output is byte-identical (
  verified against a 19-case fluent+declarative fingerprint matrix), the
  parity tests now assert method identity and default-value equality, the
  scatter/heatmap factories read `channels.DEFAULT_COLORMAP` instead of a
  duplicated literal, and `Chart.figure()` no longer re-validates axis fields
  the factories and `Figure.set_axis` already validate (declarative build ~6%
  faster; fluent path unchanged by construction).

### Added
- **Dashboard context governor**: browsers cap live WebGL contexts per page
  (~16 in Chrome) and LRU-evict the oldest on overflow, which permanently
  blanked the earliest charts of a 20+/50-chart dashboard. The render client
  now keeps itself inside a context budget (default 12,
  `window.FASTCHARTS_CONTEXT_BUDGET` to override): at budget, the
  least-recently-visible off-screen chart releases its own context
  (`WEBGL_lose_context`, a controlled loss the existing restore machinery
  undoes) and re-acquires when scrolled back into view — including canvas-swap
  recovery for real browser evictions. Under the budget nothing releases, so
  small pages are unaffected. Every decision is observable: `data-fc-ctx` on
  the canvas reads live/released/lost. The dashboard benchmark now
  settle-waits each scrolled chart (reporting per-visit recovery latency),
  classifies governed releases vs evictions, adds a `governed` health tier,
  and reports a `visible_stable_chart_ceiling`. Measured (Chrome/macOS): the
  10/20/50 sweep goes from 16-of-50 permanently blank to 50-of-50 nonblank
  when visited, recovery p95 ~8 ms, with 10-chart dashboards byte-identical
  in behavior and heap/render times unchanged.
- **Stratified sampling in the native core** (ABI v10,
  `fc_stratified_sample_mask` / `kernels.stratified_sample_mask`).
  `lod.stratified_sample_keep_mask` — the category-aware mask behind
  categorical density overlays — now runs as one fused native pass
  (per-category `sqrt`-scaled hash thresholds plus the lowest-hash
  `min_per_category` floor) instead of a per-category NumPy loop whose
  `inverse == group` rescans were O(n · categories). Small non-negative
  integer categories (the channel-codes hot path) skip `np.unique` entirely
  and serve directly as group codes. Bit-identical masks (parity-tested
  against the NumPy reference on both sides of the ABI); ~20× faster on a
  5M-row / 12-category mask (168 ms → 8.5 ms, Apple Silicon dev box).
- **Batched scatter marks in the PNG display list** (`OP_POINTS`,
  `src/raster.rs` / `_raster.py`). Native PNG export now ships scatter marks
  as one struct-of-arrays command — NumPy-packed coordinate/radius/fill
  columns plus a shared symbol/stroke header — replacing the per-point
  `struct.pack` loop and the per-point CSS color re-parse for categorical
  palettes (each palette entry now resolves once). Pixel-identical to the
  per-mark opcode (parity-tested in Rust); display-list build for a
  100k-point categorical scatter drops ~186 ms → ~1 ms, and the command
  buffer shrinks ~40%. The batch skips non-finite marks defensively and
  truncated buffers are rejected like every other opcode.
- **CSS value validation in the native core** (ABI v9, `fc_css_check` /
  `kernels.css_check`). One grammar (`src/css.rs`) now gates every styling
  surface at build time: trace/annotation/series colors, gradient stops,
  `mark_style` states, and `style=` declarations parse strictly where the
  grammar is closed (hex — no more `#3b82zz` accepted as "valid hex" —
  `rgb()`/`hsl()`, the full CSS named-color table, lengths, numbers), while
  browser-resolved forms (`var()`, `oklch()`, `color-mix()`, `calc()`)
  shape-check and pass through, and every value is checked for
  declaration-context safety (no `;`/`{`/`}`/`</`/control characters,
  balanced quotes/parens). Malformed styling raises a `ValueError` naming
  the argument instead of rendering a silently wrong chart. The
  color-vs-column disambiguation for `color=` and the native PNG rasterizer
  resolve colors through this same parser — `color="rebeccapurple"` is a
  constant color now, not a column lookup, and static exports cannot drift
  from the API contract; the render client warns on unresolvable colors in
  hand-written specs instead of silently painting the fallback.
- **Browser-free native PNG export** (`Figure.to_png(engine="native")`, now the
  default). A dependency-free anti-aliased rasterizer in the Rust core (ABI v8,
  `fc_rasterize`) paints the same decimated payload the SVG exporter consumes,
  driven by a Python-built display-list command buffer — no Chromium, ~40 ms for
  a 10M-point line, and indexed-palette PNGs for small files. Carries the full
  mark-styling surface (gradients, dashes, symbols, rounded/stroked bars, smooth
  curves) and density/heatmap rasters; text uses a baked bitmap font atlas
  (`scripts/gen_font.py`). `engine="chromium"` keeps the pixel-exact browser
  screenshot path.
- **Standalone density refinement, off the main thread** (dossier Phase 1):
  kernel-less `to_html` exports now re-bin the recorded density sample in a
  bundled Web Worker on zoom (blob-URL boot under a `worker-src blob:` CSP),
  swapping in a view-fitted grid instead of stretching the overview texture —
  with the reduction badged (§28), the full overview restored at the home
  view, and a graceful fallback where workers are unavailable.
- **Static SVG export**: `Figure.to_svg()` / `Chart.to_svg()` — a pure-Python,
  dependency-free renderer over the same decimated payload the browser client
  consumes. Screen-bounded by construction (a 10M-point line exports in ~4 ms
  as a ~58 KB, resolution-independent SVG); covers every chart kind including
  density/heatmap rasters, and the full mark styling surface (gradients,
  dashes, symbols, rounded bars, smooth curves as exact cubic Béziers).
- **Mark-level styling** (both APIs; `docs/styling.md#styling-the-marks`):
  - `fill="linear-gradient(...)"` on `area`/`bar`/`column`/`histogram` — real
    CSS gradient syntax (2–8 stops, `%` positions, `currentColor` = the mark's
    own resolved color, hue-preserving fades to `transparent`); mark-space by
    default (along each mark's value axis), plot-space opt-in via
    `fill={"gradient": ..., "space": "plot"}`.
  - `corner_radius` / `stroke` / `stroke_width` on the bar family — the CSS
    border analogues, rendered as an antialiased SDF (plain bars stay
    pixel-identical). `corner_radius=(tip, base)` rounds only the value end —
    the classic rounded-top bar — orientation- and sign-aware.
  - `curve="smooth"` on `line`/`area` — monotone cubic (never overshoots),
    re-applied per zoom-refined window; hover keeps reporting source rows.
  - All mark colors (gradient stops and strokes included) resolve as live CSS
    (`var(--accent)`, `oklch(...)`, named colors) and re-resolve on theme
    change.
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
- **Rendering hardening:** context loss now quiesces draw/animation/re-bin work,
  invalidates pre-loss replies, retains streamed canonical payloads, reports
  recovery state, and rebuilds without throwing an unhandled event error. The
  dependency-free browser smoke forces three pixel-identical recovery cycles
  and verifies interaction afterward. CI now hard-gates a loss-free 10-chart
  dashboard, pins interaction/visual budget ceilings in the verifier, and
  fails timing regressions beyond 4x while retaining the 2x advisory band.
- **Native PNG export compression** dropped from zlib level 9 to level 6: a
  1M-point line export goes from ~298 ms to ~64 ms (reference hardware) for
  ~2.65% larger output. Regression tests pin the level for both truecolor
  and indexed encoders.
- **Dashboard benchmark telemetry:** `bench_dashboard.py` no longer discards
  metrics when Chrome evicts WebGL contexts. Partial dashboards stay
  measurement rows with per-chart `webglcontextlost`/`webglcontextrestored`
  events (id, phase, timestamp), creation-failure vs eviction distinction,
  initial and scrolled nonblank chart IDs, live-context redraw submission,
  and a stable loss-free chart-count ceiling; the report verifier
  cross-checks all of it. The interaction benchmark warm-up now completes
  GPU work (draw + readback) before the first timed sample.
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
