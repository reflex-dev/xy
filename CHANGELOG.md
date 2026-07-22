# Changelog

All notable changes to **xy** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/) once `1.0.0` ships;
pre-1.0, minor versions may contain breaking changes (see the stability table
in the README).

## [Unreleased]

### Migration notes
- Mark `style={...}` now uses paint-specific CSS: `stroke` for line-like marks
  and `fill` for filled marks. The legacy `color=` argument remains supported,
  but `color` is not an alias inside `style`.
- `MarkStyle` / `mark_style(...)` are removed. Interaction state styling belongs
  to the host framework (for example, Reflex state, conditions, and event
  handlers), rather than a second XY state system.
- PNG export now defaults to the browser-free native renderer. Use
  `engine=Engine.chromium` for browser CSS/WebGL fidelity; string engine values
  remain temporary deprecated aliases. Browser executable parameters were
  removed in favor of automatic discovery or `XY_BROWSER`.
- Chromium PNG and batch export accept `custom_css=`. Native PNG rejects it,
  while complete chart-level color tokens such as `var(--accent)` resolve in
  native SVG/PNG from the chart's own `style` mapping.

### Removed
- **The fluent `Figure` API is removed from the public surface.**
  `xy.Figure` is no longer exported; `figure.py` is internalized as
  `xy/_figure.py`. The declarative composition API (`xy.chart(...)`,
  `xy.line_chart(...)`, `xy.scatter_chart(...)`, marks, axes, annotations,
  chrome) is now the single public chart-building API. `Selection` stays
  public, composed `Chart` objects keep the full readout surface
  (`to_html`/`to_png`/`to_svg`/`widget`/`show`/`append`/`pick`/`select_range`/
  `memory_report`), and `Chart.figure()` remains as an advanced escape hatch
  to the internal engine object.

### Added
- **Export format parity and a unified export API (ENG-10447).**
  `to_image(format=...)` and extension-inferred, atomic `write_image(path)`
  on charts, facet grids, and the internal figure cover PNG, JPEG/JPG, WebP,
  SVG, and PDF alongside interactive HTML; `to_png`/`to_svg`/`to_html`
  remain as compatibility conveniences. All five image formats export
  browser-free by default: JPEG uses a new pure-numpy baseline encoder
  (4:4:4, quality 1-100), WebP a new bit-exact lossless VP8L encoder with
  alpha, and PDF a new vector backend that converts XY's own SVG output
  (vector text via Helvetica metrics, axial-shading gradients, embedded
  rasters for density/heatmap layers — the documented hybrid-vector
  policy). `engine=Engine.auto` deterministically selects native per
  format and switches to Chromium only for `custom_css`;
  `Engine.chromium` adds browser-fidelity JPEG/WebP (CDP screenshots) and
  PDF (`printToPDF`). A shared background policy spans every format
  ("auto"/CSS color/"transparent", JPEG rejects transparent instead of
  silently flattening). `xy.write_images(figures=..., files=...)` batches
  mixed formats through one reused browser session with atomic per-file
  writes. `xy.export_config()` declares formats/filename/dimensions/
  scale/background/quality on the chart itself, governing both Python
  defaults and the modebar's download menu, which now offers PNG, JPEG,
  WebP, SVG, and CSV (client-safe subset) with the same filename and
  background semantics — including in standalone HTML with no kernel and
  in Reflex apps.
- **Declarative continuous colorbars.** `xy.colorbar()` derives the domain,
  colormap, and default title from the last compatible heatmap, continuous
  scatter, hexbin, contour, segment, or triangle-mesh mark, with explicit
  `title`, `orientation`, and `ticks`. Constant/categorical colors, truecolor
  grids, and density scatter whose source color channel was dropped do not
  advertise a misleading scale.
- **Complete styling atlas and Reflex/Tailwind bridge.** New styling guides and
  live stress examples cover every rendered mark family, all 17 scatter
  symbols, grouped/normalized bars, axes and annotations, both colorbar
  orientations, responsive chrome, custom host components, facets, badges,
  interactions, and export boundaries. Fixed charts passed directly to
  `reflex_xy.chart()` now mirror their embedded class tokens into generated JSX
  so Reflex's Tailwind plugin can discover them at compile time.
- **Compact chart toolbar and editable lasso selection.** The client toolbar
  appears on chart hover or keyboard focus and can be dragged by its
  non-interactive surface, with an adaptive external drag affordance. Back/Next
  history now lives in the zoom menu, alongside the grouped zoom and selection
  controls, and the toolbar exports PNG, SVG, or resident data as CSV.
  Completed lasso selections expose up to 16 adaptive
  RDP handles for range adjustment, and client SVG/PNG export snapshots the
  chart's computed theme tokens and typography so host light/dark themes carry
  into downloaded images.
- `xy.pyplot.FacetGrid`: a seaborn-shaped row/column facet grid running
  entirely on the shim (seaborn's `map` contract: subset → activate panel →
  call the pyplot function), with shared domains, edge-only axis labels,
  top-row column titles, and rotated `margin_titles`. Text annotations are now
  unclipped like matplotlib, axes-fraction text right of the axes box reserves
  right margin in every exporter, and `rotation=90/270` renders vertical text
  in browser, native PNG (new CW glyph path, ABI 34), and SVG. New style
  sheets `seaborn-v0_8-darkgrid` and `seaborn-v0_8-deep` mirror `sns.set()`
  (darkgrid panels, white forced patch edges via the new
  `patch.edgecolor`/`patch.force_edgecolor` rcParams, deep color cycle).
- **Client fixes surfaced by the darkgrid theme.** Re-applied the
  chrome-under-bg stacking fix (423e020) that a later merge clobbered — an
  opaque `--chart-bg` again hid grid lines, rules, bands, and annotation
  shapes in the live client; the render smoke now pixel-probes this stacking
  (`bgocc`) so it cannot regress silently. Modebar icons color from
  `--chart-text` instead of `--chart-axis`, staying visible when a style sets
  white axis edges.
- **Production binary HTTP frame v1.** `xy.channel` now exposes a
  framework-free, little-endian `XYBF` codec with separate transport
  versioning, strict JSON metadata, 8-byte-aligned buffers, zero padding,
  explicit total length, configurable resource caps, scatter/gather encoding,
  and zero-copy Python decode views. The shipped ESM/IIFE client exports the
  matching `decodeFrame()` and rejects unsupported, oversized, truncated,
  misaligned, or otherwise malformed frames. Renderer payload handling now
  preserves aligned `(ArrayBuffer, byteOffset, byteLength)` spans instead of
  slicing normal anywidget/HTTP views before GPU upload, with a one-copy
  compatibility fallback for legacy unaligned views. CodSpeed tracks frame encode,
  scatter/gather construction, zero-copy decode, and base64 comparator rows;
  the loopback Chromium harness retains the real HTTP/browser measurements.
- **Loopback transport measurement gates.** `benchmarks/bench_transport.py`
  drives the transport-neutral `channel.handle_message()` dispatcher through
  real HTTP and compares the current base64-in-JSON prototype with the
  production versioned binary frame. Reports separate raw and
  gzip bytes, Python encode/allocation and loopback p50/p95, Chromium
  decode-to-next-frame latency and heap delta, plus the current duplicate
  widget-append and unaffected-trace retransmission costs. Deterministic byte
  metrics are hard regression gates; the refreshed density baseline reflects
  the current screen-bounded ~264–266 KB payload instead of the stale ~854 KB
  values.
- `xy.pyplot`: a matplotlib-flavored shim over the composition
  API (`import xy.pyplot as plt`). Corpus-defined compatibility —
  see `spec/matplotlib/compat.md`; fully contained in
  `python/xy/pyplot/` with boundary guardrails.
- **Statistical and density chart breadth.** Added first-class `errorbar`/
  `error_band`, `box`, `violin`, `ecdf`, `hexbin`, and `contour` marks plus
  `step`, `stairs`, and `stem` variants. Segment marks share one instanced
  binary geometry path; hexbin uses the native 2-D bin kernel; distribution
  shapes ship bounded geometry rather than one browser object per observation.
   `facet_chart` repeats a declarative chart over a table column with optional
   shared domains and HTML/SVG/native-PNG grid export.
- **Chart live surface (data-live, structure-immutable).** The declarative
  `Chart` gains `append(trace_id, x, y, color=, size=)` (streaming — routed
  through the live widget when one exists, else mutating the built figure
  without touching the widget stack), `pick(trace_id, index)` (exact
  canonical-row readout), and `select_range(...) -> Selection`. Structural
  changes still mean composing a new chart.
- **`xy/channel.py`** — the kernel-side message dispatcher extracted
  from `FigureWidget` (reflex-integration §3.1 build-order step 1):
  `handle_message(fig, content, buffers, callbacks)` serves every transport;
  the anywidget widget is now a thin comm wrapper over it, and a future
  server transport (the planned Reflex adapter) drives the same tested
  contract without importing the widget stack.

### Changed
- **Streaming append ships once, split, per tick (protocol v5).** The
  `append` refresh now uses the same split buffer layout as first paint (no
  packed join copy), and on the notebook widget it rides the single
  `spec`/`buffers` trait update — which doubles as reopen state — instead of
  being transmitted twice (trait re-sync plus a custom message). The client
  applies appends when `spec.append.seq` advances; the Reflex socket push is
  unchanged in shape apart from the split buffers. Halves streaming wire
  bytes and removes two full-payload copies per tick.
- **Responsive, author-defeatable browser chrome.** XY's visual defaults now
  live in a low-priority cascade layer, so Tailwind utilities, ordinary author
  CSS, and slot styles override them without `!important`. Long legends remain
  bounded and correctly anchored after compact-layout resizes; edge tooltips
  wrap, clamp, and flip within the chart; canvas offsets refresh with the plot.
- **Named-axis and static-export parity.** Browser, SVG, and native PNG output
  now render and independently scale named x and y axes, including their
  baseline, ticks, labels, titles, style, reverse ranges, collision strategy,
  and label placement. Static legends are bounded and long labels ellipsize
  instead of escaping small plots.
- Rich tooltips retain resident color/size fields after WebGL context recovery
  and rehydrate shared fields after exact kernel picks instead of collapsing to
  positional x/y values.
- Annotation geometry opacity no longer fades browser DOM labels. Rules,
  bands, markers, arrows, and callouts can stay visually subtle while their
  text remains readable; annotation-style `label_opacity` explicitly controls
  label alpha when desired.
- **`savefig` single-panel PNG export now uses the fused Rust encoder.** A
  one-axes figure with no suptitle/colorbar/tight-bbox and the default white
  facecolor is exactly one native render, so `stitch_png` returns the
  rasterizer's own PNG (the latency-first `Figure.to_png` default) instead of
  round-tripping RGBA through the Python size-oriented encoder — pixel-
  identical output, ~10x faster (119.8ms → 11.7ms on a 100k-point savefig;
  1.2x the raw `to_png` at the same 1280x960 output). Multi-panel and
  tight-bbox exports keep the composed path but now probe a stride sample
  before the full-image palette attempt, skipping a doomed O(n log n) unique
  scan on antialiased charts.
- **`ax.hist` no longer boxes numeric input or copies it to find bin edges.**
  The input-shape sniff skipped its object-dtype round trip for 1-D numeric
  arrays, and fixed-count bins derive their range from the native NaN-skipping
  min/max scan instead of a finite-filtered concatenated copy. Counts still
  come from `np.histogram` against the identical edges — the kernel-based
  shortcut was rejected because it disagrees with numpy by ±1 on values
  exactly at interior bin edges. ~2.3x faster shim histogram builds.
- **`ax.bar`/`ax.barh` label sanitization is vectorized.** Plain string
  category arrays are scanned for TeX markers with one vectorized pass
  instead of a per-label Python loop through the mathtext converter.
- **Legend `loc="best"` scoring subsamples before its finite scan** instead
  of running `isfinite` over every point of every legended series — the
  scoring was already sample-based; the full-array pass was pure O(n)
  per-build cost.
- **`xy.pyplot` no longer pays an O(n) dataless-axis scan on every build.**
  The empty-view pin in `_build_chart` materialized and finite-filtered every
  entry's full data for both axes just to ask "is this axis empty?", adding a
  data-proportional cost to each shim figure build (~3x the raw declarative
  build at 1M points). It now short-circuits on the first finite value via a
  prefix probe; `tests/pyplot/test_perf_guardrail.py` passes again on Linux
  runners and the new CodSpeed pairs track the margin continuously.
- **Payload copy elimination (native ABI v32).** Partial-view density sampling
  now hashes native `u32` row selections without first widening the full array
  to `u64`; exact-full index buffers avoid a trailing-slice copy; and payload
  assembly retains encoded arrays until the final blob join instead of copying
  every column through `tobytes()` first. Payload bytes and sampling decisions
  remain parity-tested and unchanged.
- **Stable hybrid density overlays.** Pyramid-served pan/zoom updates now keep
  the retained deterministic point sample when they omit a replacement,
  instead of making the first-paint overlay disappear on interaction. Exact
  scans still replace it with their view-specific sample.
- **View-change callback windows** now reject non-finite bounds and normalize
  inverted ranges before callbacks receive them, matching selection and
  autorange window semantics.
- **API layering inverted: the declarative layer is now the core.** The nine
  mark-builder implementations moved verbatim from `figure.py` into the new
  `xy/marks.py`; `Figure` binds them as its fluent methods
  (`Figure.scatter is marks.scatter`), so both dialects share one body, one
  signature, and one set of defaults. Payload output is byte-identical (
  verified against a 19-case fluent+declarative fingerprint matrix), the
  parity tests now assert method identity and default-value equality, the
  scatter/heatmap factories read `channels.DEFAULT_COLORMAP` instead of a
  duplicated literal, and `Chart.figure()` no longer re-validates axis fields
  the factories and `Figure.set_axis` already validate (declarative build ~6%
  faster; fluent path unchanged by construction).

### Added
- **CodSpeed shim-overhead pairs** (`benchmarks/test_codspeed_pyplot.py`):
  every workload (10k/1M line, 100k scatter, 200-bin histogram, 1k-category
  bars, a chrome-heavy styled panel, and static PNG export) is built twice
  from the same arrays — once through the raw declarative API and once
  through the identical `xy.pyplot` calls — ending in the same split wire
  payload or PNG bytes, so the `*_pyplot` minus `*_raw` gap in CodSpeed is
  exactly the shim's translation cost. Collected automatically by the
  existing `benchmarks/test_codspeed_*.py` CI glob.
- **Dashboard context governor**: browsers cap live WebGL contexts per page
  (~16 in Chrome) and LRU-evict the oldest on overflow, which permanently
  blanked the earliest charts of a 20+/50-chart dashboard. The render client
  now keeps itself inside a context budget (default 12,
  `window.XY_CONTEXT_BUDGET` to override): at budget, the
  least-recently-visible off-screen chart releases its own context
  (`WEBGL_lose_context`, a controlled loss the existing restore machinery
  undoes) and re-acquires when scrolled back into view — including canvas-swap
  recovery for real browser evictions. Under the budget nothing releases, so
  small pages are unaffected. Every decision is observable: `data-xy-ctx` on
  the canvas reads live/released/lost. The dashboard benchmark now
  settle-waits each scrolled chart (reporting per-visit recovery latency),
  classifies governed releases vs evictions, adds a `governed` health tier,
  and reports a `visible_stable_chart_ceiling`. Measured (Chrome/macOS): the
  10/20/50 sweep goes from 16-of-50 permanently blank to 50-of-50 nonblank
  when visited, recovery p95 ~8 ms, with 10-chart dashboards byte-identical
  in behavior and heap/render times unchanged.
- **Stratified sampling in the native core** (ABI v10,
  `xy_stratified_sample_mask` / `kernels.stratified_sample_mask`).
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
- **CSS value validation in the native core** (ABI v9, `xy_css_check` /
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
  `xy_rasterize`) paints the same decimated payload the SVG exporter consumes,
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
- **Mark-level styling** (both APIs; `spec/api/styling.md#styling-the-marks`):
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
  `:where([data-xy-slot="…"])` stylesheet — so a utility class or inline style
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
  `xy.histogram(cumulative=...)`; combined with `density=True` it yields the
  empirical CDF.
- Normalized stacked bars: `mode="normalized"` on `Figure.bar` / `xy.bar`.
- Fluent/composition API parity guard test, preventing the two public
  surfaces from drifting apart.
- Prebuilt-wheel coverage expanded to a pydantic-class platform matrix:
  Linux glibc **and** musl/Alpine (x86-64, aarch64, armv7), macOS (x86-64,
  Apple Silicon), and Windows (x86, x64, arm64). An experimental
  Pyodide/Emscripten WASM wheel is built but does not yet load in-browser
  (`spec/process/production-readiness.md` documents the exact linker failure and fix
  direction).
- Release workflow `workflow_dispatch` dry-run mode: builds and verifies the
  full artifact matrix without publishing to PyPI (default for manual runs).
- `benchmark-refresh` CI workflow: regenerates the cross-library benchmark
  tables (10M scatter and core-2D) from a consistent Ubuntu run.
- Native fused kernels: `xy_sample_mask` (deterministic density-overlay
  sampling) and `xy_bin_2d_indices` (density grid + visible rows in one pass).
- Pyodide runtime load probe (`scripts/pyodide_load_smoke.py`), run
  non-gating in the wasm release job.

### Changed
- The native Rust core is now **required**: the NumPy fallback backend was
  removed. On platforms with no wheel and no local Rust build, importing the
  compute layer raises a clear, actionable `ImportError` instead of silently
  degrading. `import xy` remains lightweight.
- The example apps were restructured. `examples/reflex/` is now a pure
  `reflex-xy` showcase (figure-var drilldown with hover/click/select events, a
  slider-driven and cross-filtered histogram, a streaming line, an
  `on_view_change`-computed detail chart, and both fixed-data tiers), and a new
  `examples/fastapi/` app serves the same charts plus a live 100M-point
  drilldown from a plain FastAPI app. Both read their own source with
  `inspect.getsource` for the on-page code panels, and neither commits static
  chart HTML (everything is generated live). The old
  `python/reflex-xy/examples/demo_app` was removed.
- 10M scatter payload build is ~3x faster (fused kernels; ABI v6), and the
  published benchmark tables were re-measured with a warmup-corrected,
  tracer-free harness. Benchmark methodology fixes: library warmup before
  timing, timing separated from tracemalloc memory profiling, and RSS
  bracketing corrected.

### Removed
- `XY_FORCE_FALLBACK` environment switch and the pure-NumPy kernel
  backend (`xy/_fallback.py`).

## [0.0.1] — 2026-07-16

Initial development snapshot: line/scatter/area/histogram/bar/heatmap chart
families, binary columnar transport, WebGL2 rendering, M4 decimation, density
tiers with adaptive drilldown, standalone HTML export, anywidget notebook
integration, and the Reflex example dashboard.
