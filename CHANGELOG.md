# Changelog

All notable changes to **xy** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/) once `1.0.0` ships;
pre-1.0, minor versions may contain breaking changes (see the stability table
in the README).

## [Unreleased]

## [0.0.6] - 2026-08-07

### Added
- The primary data-bound Reflex component API is now available. `@reflex_xy.data`
  publishes typed column sets through `DataHandle[Schema]`; validated,
  content-addressed plans keep chart structure in page code and bind live or
  concrete data without routing arrays through Reflex state. Typed figure
  handles, flat factories for every standalone mark kind,
  `reflex_xy.chart(*nodes, data=...)` composition, reconnect/rebuild and
  republish fan-out, compile-time figure probes, and a complete demo make the
  new tier usable end to end.
- Funnel charts joined the core declarative API (protocol v13):
  `xy.funnel_chart(stages, values)` / `xy.funnel(...)` draw one centered
  segment per stage in declared order — never sorted — with explicit
  `geometry="area"|"bar"` modes, `neck="rect"|"taper"`, per-geometry segment
  gaps, and a `min_width` floor that keeps zero/tiny stages visible without
  touching their reported values. Conversion arithmetic (value, prior, overall
  share, previous-stage conversion, drop-off; `None` over zero denominators)
  rides labels with a documented inside/outside/hidden collision ladder,
  hover tooltips, click events, and ordered keyboard traversal with
  screen-reader announcements. Per-stage colors are a categorical channel over
  the stage names (theme `palette={...}` mappings pin by stage name; legend
  rows opt in via `xy.legend(...)`), and per-trace `stroke`/`stroke-width`/
  opacity style compiles to all three renderers. The client draws
  antialiased quads through a dedicated funnel program sharing the ribbon
  fragment stage; SVG/PNG/PDF exports emit the same `_scene.funnel_quad`
  geometry, pinned by golden tests.
- A production document-scoped WebGL host lets charts share one WebGL2 context
  and compiled shaders while preserving chart-owned buffers, picking, and view
  state. Canvas2D presentation keeps normal layout and clipping; governed
  per-chart fallback and host-wide context-loss recovery protect browsers and
  dashboards with many charts.
- The stable CSS, `class_names`, `styles`, and Tailwind chart-chrome surface
  expanded from 29 to 48 slots, adding modebar internals, Cartesian axes and
  gesture bands, colorbar details, and the annotation layer.
- A reproducible dark-mode benchmark image and theme-aware README selection
  now accompany the published benchmark evidence.

### Changed
- Reflex figure state vars, `register()`, and `inline()` now return typed
  `FigureHandle`s, and live components accept `Var[FigureHandle]` so invalid
  vars and raw strings fail during page evaluation. Positional live
  `chart(var)` / `chart(token)` calls warn in favor of `figure=`; positional
  static `chart(Chart)` remains supported, and legacy token strings remain
  accepted by helper APIs for one release cycle.
- The lazy `xy` root now has a complete PEP 561 type surface, including
  `xy.__version__`. Source, external-consumer, and installed-wheel type checks
  are release gates.
- Polar charts disable zoom by default, except for wind roses. Authors can opt
  in with `interaction_config(zoom=True)`; otherwise wheel events remain
  available for page scrolling and inert zoom/history controls stay hidden.
  Polar `default_drag_action` now accepts only `"auto"` and `"none"`, rejecting
  drag tools that the renderer cannot execute.
- Native raster exports now resolve categorical palettes through the same
  indexed fallback as SVG and density rendering. Browser-only or otherwise
  unresolvable entries in hand-authored payloads emit a `RuntimeWarning` and
  fall back to the built-in color at the same index, preserving distinct
  categories instead of silently collapsing them onto one shared color.
- Release verification now drives standalone Chromium smokes through CDP,
  parses built ESM exports structurally instead of matching minifier-dependent
  strings, and uses stable-Rust-compatible chunk APIs so the floating stable
  toolchain remains clean under Clippy.

### Fixed
- Log axes with an explicit margin no longer underflow their lower bound to
  zero on very wide positive domains.
- Invalid mark-fill mappings with incomparable key types now raise the intended
  unknown-key `ValueError` instead of an internal sorting `TypeError`. Reflex
  event-handler annotations also remain valid to static type checkers after the
  dependency updates.
- Static annotation labels now honor chart annotation/text theme tokens, and a
  scene/SVG import-order cycle no longer breaks capability generation.
- Documentation code-copy controls have accessible names, visible keyboard
  focus, and announced copied/failed states. Route-wide checks now prevent
  public documentation heading outlines from skipping levels.

### Security
- The active root environment now resolves `aiohttp==3.14.3`, patched for
  CVE-2026-69244. Dependabot alert #12 names a lockfile from the
  retired `python/reflex-xy` project, which is deleted from the repository and
  excluded from the distribution. Other documentation and application
  dependencies, including PostCSS, were updated to patched versions, with the
  associated Python and JavaScript lockfiles refreshed.

## [0.0.5] - 2026-07-31

### Added
- Reflex integration is now bundled in the `xy` distribution and installed as
  `xy[reflex]`. The `reflex_xy` import namespace and JSX wrapper ship in every
  wheel and sdist, while the extra adds the supported `reflex>=0.9.6` floor;
  plain `xy` still has no Reflex dependency. The separate `reflex-xy`
  distribution, version line, and release workflow have been removed.
- Completed the phase-6/7 polar depth surface: `xy.polar_chart` now admits
  heatmap, contour, and error-bar traces alongside line/scatter/area/bar; the
  heatmap uses a fragment-stage polar inverse in the browser and the matching
  bounded inverse raster for static export. Polar axes add partial-sector
  layout, `hole`/radial origin, categorical theta, log/symlog radius, and
  polygonal `grid_shape="linear"` rings. `xy.pyplot` exposes degree-based
  `set/get_thetamin`, `set/get_thetamax`, and radial
  `set/get_rorigin`. Generic segment/mesh marks, polar rule/band annotations,
  LOD, facets/animation, and angular navigation/selection remain deferred.
- CodSpeed coverage for the polar coordinate system
  (`benchmarks/test_codspeed_polar.py`, a new `polar_coordinate_system` benchmark
  category): payload prep for a polar line, a wind rose and a pie, plus SVG,
  native-PNG and polar-heatmap export. The polar increment previously moved no
  benchmark at all, so the wedge-flattening cost and the polar payload path were
  invisible to CI. The collected row count is now gated against
  `spec/benchmarks/methodology.md` §8, so a renamed or deleted benchmark cannot
  silently leave a stale row in the CodSpeed dashboard.

### Fixed
- Source-distribution CI and release validation now exercise both installation
  contracts independently: a forced Cargo build must load the native backend,
  while a cache-isolated coreless build must still import `reflex_xy`, report
  the installed version, and raise the documented error only when compute is
  requested.
- Polar customization now stays consistent across the browser, SVG, and native
  raster renderers: point-anchored annotations use the joint `(theta, r)`
  projection, explicit chart padding survives the polar layout pass, gradient
  fills reach native raster wedges, and annular sectors honor rounded corners
  and strokes.
- `radar_chart(fill=False)` now renders area children as styled outlines,
  translating their line color, width, opacity, curve, and dash props instead
  of passing incompatible area props to the line renderer.
- Repeated data updates no longer leak GPU buffers. Trace teardown walked a
  hand-kept list of geometry buffer names, so every rebuilt trace — each
  state-driven update, each append that could not patch in place, each animated
  spec swap — orphaned its style, direct-RGBA colour, stroke, corner-radius,
  LOD-blend and dashed-line-length buffers. All three teardown paths (trace,
  drill window, sample overlay) now read one shared `TRACE_GPU_BUFFERS` list,
  pinned against the build paths by a test so a new channel cannot reintroduce
  the leak.
- Chart titles reserve the lines they actually wrap into. The browser wrapped a
  long title while layout measured one line, so a compact Wind Rose title lost
  about 10 px off the top of the canvas. Titles now wrap at one shared width in
  all three renderers, and the browser caps the title element at that same width.
  Single-line titles are unchanged.
- A polar figure with a legend reserves a gutter for it and places it there,
  instead of overlaying the disc. A default `upper right` legend covered a wind
  rose's north-east sectors and its outer radial tick label; a disc inscribed in
  its rect has no free corner to overlay. The gutter is 22% of the canvas width,
  clamped to 120-200 px — derived from the canvas so all three renderers reserve
  the identical box, and wide enough to hold an ordinary row rather than
  ellipsize it. Compact widths take a 64 px band beneath the disc instead. An
  authored `anchor` or four-tuple `padding` still wins. Both static exporters
  bound the legend to the plot rect unioned with that gutter (`legend_clip_rect`,
  shared so they cannot drift): the raster bounded it to the plot rect alone,
  which is outside the gutter by construction, so a native PNG of any polar
  figure lost its legend entirely while the SVG kept one.
- Compact vertical colorbars keep their two extreme tick labels, restacked above
  and below the gradient. Collapsing them hid every number, leaving an unlabelled
  gradient; only the interior ladder, the rotated title and the text-free minor
  ticks drop now, and the box's own `title`/ARIA text still names the scale.
  Stacking is what makes it free: a side gutter wide enough for `0.25` would cost
  36 px of the plot width the compact collapse exists to protect.
- A time-valued radial axis autoranges from its data instead of from epoch zero,
  which had squeezed every modern instant into a hairline ring at the rim. An
  explicit `r_axis(margin=)` restores the outer pad it used to discard.
- `theta_axis(format=...)` now wins over the built-in degree/radian tick text in
  every renderer, instead of shipping and being overwritten.
- A zero-width bar is legal and draws nothing, like `line_width=0`. A 0% progress
  ring, an empty category in aggregated data, and a hand-rolled wedge at zero all
  produce one, and each used to fail with "bar width must be positive". Negative
  and non-finite widths are still refused.
- Data animations no longer rebuild the whole tick-label DOM on every frame; they
  use the same 80 ms cadence view animations use, and force one settled rebuild
  when the transition ends.
- A device-pixel-ratio change (browser zoom, or a window moving between displays)
  now rescales the per-instance stroke widths and corner radii that are baked in
  device pixels, so authored strokes and wedge corners keep their intended size
  across a zoom. The DPR handler stays synchronous: a DPR change with no container
  resize has no later event to piggyback on. A trace whose CPU style/radius mirror
  no longer spans every row on the GPU — which is what a streaming tail append
  leaves behind — is skipped rather than repaired in place, so the existing
  append-time rebuild still does the renormalizing for it.
- `xy.pie_chart` appears in the generated chart-factory API reference alongside
  the other polar compositions.
- A legend row too wide for its box wraps instead of growing a horizontal
  scrollbar. The box is capped at `--xy-legend-max-width`, but its grid columns
  were `max-content` and refused to shrink, so an over-wide row overflowed and
  `overflow:auto` answered sideways — hiding the label it was meant to show.
  Columns are now `minmax(0, max-content)` and the inline axis never scrolls.
  Vertical scrolling is unchanged, and rows carry their full name in
  `title`/ARIA for the ones the height cap clips.
- `xy.pie_chart` no longer prints the same number twice. Values that already sum
  to 100 — how most pie data arrives — made `show_values` and `show_percent`
  collide, so `[40, 30, 20, 10]` rendered `Direct  40  (40%)`: a legend row that
  reads as repeated text, and long enough to overflow the box. The share keeps
  the unit and the bare value is dropped, decided once for the whole pie so rows
  stay uniform.

### Changed
- Default tooltips now lead with the hovered series name, and the radial row of
  a polar readout is labelled `r` rather than presented as a Cartesian `y`. The
  numeric angle row is gone from polar readouts: on most polar charts the angle
  is where layout put the mark and the cursor is already on it, so it answered a
  question nobody asked. Two things survive because they are not numeric angles
  — an authored spoke label (a radar category reads `power`) and any row named
  explicitly through `labels={"x": ...}`, which opts the angle back in formatted
  through the theta axis's own text function. Compositions whose bearing *is*
  data say so themselves: a wind rose band still reads its direction, and a pie
  slice reads its category and value.
- Polar wedge subdivision is span-proportional: `segments(span) =
  clamp(ceil(96 · |span| / turn), 2, 96)` in every renderer, over the *authored*
  angular width. Sagitta is quadratic in the per-segment angle, so this holds the
  flattening bound while a 16-sector wind-rose bar costs 14 vertices instead of
  194 — the fixed full-turn count made ~50k polar bars build ~9.7M vertices a
  frame. A full-turn wedge still uses 96.
- `xy.theta_axis`/`xy.r_axis` now refuse the Cartesian axis keywords no polar
  renderer implements — `minor_tick_values`, `minor_style`,
  `tick_label_min_gap`, `tick_label_anchor`, and the collision spellings of
  `tick_label_strategy` (`auto`, `hide`, `rotate`, `stagger`, `preserve`) — each
  with a pointer to the control that does work. They previously rode the wire and
  were dropped by all three renderers, so the documented axis surface advertised
  options that did nothing. `off` and `none` remain honoured. `xy.pyplot`'s
  `projection="polar"` drops the same keywords instead of refusing, because every
  matplotlib Axes carries an rcParam-derived minor style it never authored; that
  drop is recorded in `spec/matplotlib/compat.md`.
- The renderer/spec protocol is now v12. Angular axes resolve
  `sector`/`grid_shape` and radial axes resolve `hole` plus optional
  `r_origin`; a cached v11 client would silently draw full-circle,
  centre-origin Cartesian grid/segment fallbacks, so the protocol mismatch
  rejects it before rendering. The native renderer ABI is now v47 for the
  annular-sector display-list clip opcode.
- Contributor-only test, lint, type-check, and CodSpeed packages now live in
  PEP 735 dependency groups instead of published package extras. The unused
  Plotly-only `bench` extra was removed; cross-library benchmark environments
  continue to install their pinned external baselines explicitly. Published
  `xy` metadata now advertises only its two runtime dependencies.
- Pyplot's sub-millisecond relative timing check is no longer a blocking
  pytest test, where shared-runner jitter made it flaky. Deterministic
  structural invariants remain hard gates, while the paired CodSpeed rows
  continue to track shim overhead.

### Fixed
- `Axes.add_patch` rendered every patch as a hollow outline and dropped both
  rotation and curvature. Patches now fill in their own face color, and their
  geometry comes from `Path.to_polygons` with the patch transform applied, so
  `Rectangle(angle=...)` keeps its rotation and `Circle`/`Ellipse`/`Wedge` use
  the curve rather than its cubic Bézier control points. The curve is flattened at
  the figure's pixel size rather than in data units, so a `Circle(radius=1)`
  is as round as the same circle drawn as `radius=1000`. Unfilled patches stay
  edge-only, the axes color cycle is untouched, and a degenerate patch draws
  its edge instead of raising. A patch whose path has nested rings draws its
  outlines and skips the fill, since hole triangulation is not implemented and
  filling every ring would paint the hole solid. A ring that has a body but no
  triangulation, self-intersecting or past the triangulator's vertex cap,
  draws its outline and warns rather than going quietly hollow.
- Patch outlines were stroked at a fixed one pixel that ignored both the
  patch's line width and the figure DPI. They now use the patch's own
  `linewidth`, converted from Matplotlib points into output pixels like every
  other stroke in the shim, and a patch whose edge paints nothing — the
  Matplotlib default on a filled patch — no longer emits an invisible outline
  mark per ring.
- The handle `add_patch` returns now owns every mark the patch produced, so
  `remove`, `set_zorder`, `set_visible`, `set_alpha`, `set_color` and
  `set_transform` move the whole patch. Previously they reached only the fill,
  and a hidden patch still drew its outline.

## [0.0.4] - 2026-07-27

### Added
- Notebook display-host resolution (`spec/design/reflex-shaped-api.md` §3.3):
  `show(display=...)` on charts, facet charts, and the internal figure objects
  accepts `"auto"` (default), `"widget"`, or `"html"`, with the
  `XY_NOTEBOOK_DISPLAY` environment variable as the process-wide override. On
  Emscripten/WASM kernels (JupyterLite, Pyodide) `"auto"` now displays through
  the standalone-HTML iframe host instead of the anywidget comm, so charts
  render on hosted JupyterLite deployments (for example try-jupyter) whose
  prebuilt frontends cannot load the anywidget extension `%pip` installs
  kernel-side ("Failed to load model class 'AnyModel' from module
  'anywidget'"). Marimo's WASM build keeps the live widget host, and
  `show(display="html")` returns an `xy.export.HtmlView` rich-repr handle.
- `xy.box(...)` exposes its four visible parts without a parallel styling
  language: the main `style=` now controls body fill and border, while
  `whisker_style=`, `median_style=`, and `outlier_style=` reuse the validated
  segment/scatter CSS vocabularies. Contrasting borders, emphasized medians,
  muted whiskers, and independently shaped/bordered outliers survive WebGL,
  SVG/PDF, and native raster output.
- `xy.tooltip(labels={...})` gives source columns readable display names
  without changing lookup, formatting keys, title placeholders, or hover-event
  payloads; without `fields=`, labels rename matching default channel rows.
  Built-in tooltips now expose `tooltip_title`, `tooltip_row`,
  `tooltip_label`, and `tooltip_value` DOM slots for independent typography
  and layout; legends likewise expose `legend_title` and `legend_label`.
  User-provided labels remain text-only and are never parsed as HTML.
- `xy.theme(palette=...)` also accepts a **`{category: color}` mapping**, which
  pins colors to category *labels* rather than positions. A positional cycle can
  only ever say "the first category is blue", so the same category changes color
  whenever the set of categories does — most visibly across facet panels, where
  a panel missing one species silently repaints the other two. The mapping
  survives that. Categories the map does not name take the next default color it
  has not already spent, with a warning; unnamed series cycle the map's values
  in order.
- `colormap=` accepts a **custom ramp** built from your own colors, not only one
  of the twenty built-in names: a sequence of 2–256 CSS colors, `(position,
  color)` pairs, or a CSS `linear-gradient(...)`. Every form resolves once, in
  Python, to evenly spaced 8-bit RGB stops — the shape the built-in tables
  already use — so the WebGL client, the SVG writer, and the native rasterizer
  build byte-identical LUTs, and the colorbar follows the ramp automatically.
  Positioned stops resample at the LUT's own 256 texels, making the round trip
  exact. Stops must be colors resolvable without a browser (hex, `rgb()`,
  `hsl()`, named) and must be opaque; `var()`/`oklch()`/`color-mix()` and
  translucent stops raise with that reason rather than painting one ramp on
  screen and a different one in `to_png()`.
- `xy.theme(palette=[...])` sets a chart's **categorical color cycle** — the
  colors unnamed series take in order, and the colors a categorical `color=`
  channel assigns to its categories. Previously the built-in eight-slot palette
  was the only option for a categorical channel. Entries follow the same
  literal-color rule as colormap stops — a palette is indexed and has to resolve
  without a DOM for density surfaces and static export, where several `var()`
  entries would collapse onto one color. Entries are normalized to hex on the
  wire so every renderer decodes them without a cascade. Short palettes repeat
  with a warning, as the built-in one already did.
- `x_axis`/`y_axis` take `show`, `line`, `ticks`, `grid`, and `text` switches.
  Hiding axis chrome no longer needs seven transparent-color and zero-width
  style properties per axis: `xy.x_axis(show=False)` is the whole edit, and
  `xy.y_axis(show=False, grid=True)` leaves only the grid. They compile to the
  same validated style properties, so an explicit `style=` still wins and specs
  that don't use them are byte-identical.

### Fixed
- Improved Matplotlib compatibility for pie and vector-field plots, multiline
  layout, authored styles, axes helpers/autoscaling, and browser Y-axis titles.
- A mark-level `animation=xy.animation(...)` no longer resets the chart-level
  policy fields it does not mention. It was a complete spec spread over the
  chart's, so `xy.animation(duration=90)` on a mark silently reset `match`,
  `easing`, `enter`, `update`, and `interpolate` to their defaults — turning
  off a chart-level `match="key"` with no error and no fallback, and
  suppressing the `match='key' requires key=` validation entirely. Mark
  overrides now cascade field by field, and passing a field explicitly counts
  as setting it even when the value equals the default. A trace that carries an
  override ships the complete resolved policy, so the browser's merge is no
  longer a second, defaults-clobbering one.

### Changed
- The Rust core's release profile now uses fat LTO and strips symbol tables,
  shrinking the shipped cdylib ~15% (1.51 → 1.29 MB) with no measured runtime
  change on the native scatter bench (`spec/design/rust-engine.md` §2 records
  the profile and why `panic` stays unwinding).
- Stable animation `key=` identity planes are now retained and shipped only
  when the resolved animation spec can actually key-match. `match` defaults to
  `"index"`, so `key=` combined with a bare `xy.animation(...)`, with
  `enabled=False`, or with no animation at all previously put two dead `u32`
  columns in the payload — 8 B/row held for the widget lifetime and 8 B/row on
  the wire (400 KB at 50k rows) that no client code read. Encoding still runs
  in every case: duplicate-key and row-count errors are construction contract,
  not animation policy, and are unchanged. Payloads that do key-match are
  byte-identical.
- Stable animation `key=` identity encoding now uses one native Rust row scan
  for homogeneous fixed-width strings, bytes, booleans, and signed or unsigned
  integers, plus finite floating arrays, including non-native-endian NumPy
  arrays. Float16/32 values widen exactly to the f64 token contract. It
  preserves the existing 64-bit identities and duplicate-row errors; mixed
  objects, dates, and non-finite row diagnostics stay on the conservative
  Python reference path. Highly padded Python string/bytes sequences also stay
  there to bound fixed-width temporary memory. Fixed-width NumPy strings retain
  their exact embedded-NUL semantics natively.
  Routing follows the values rather than the container, so a key column passed
  as a pandas Series or as homogeneous object storage — what `data=df,
  key="id"` actually resolves to — takes the same path as an ndarray instead of
  falling back. Only keys that *end* in NUL stay on the reference encoder,
  where fixed-width padding would otherwise absorb them; interior NULs are
  encoded natively.
  This adds the C ABI v44 transition-key kernel.
- Host theme changes made through an ancestor `data-theme` attribute now
  refresh canvas/SVG paint just like `.dark` class and inline-style changes;
  DOM chrome continues to follow the cascade automatically.
- Peak memory cut on four paths, with byte-identical output everywhere (89
  payload/export/view fingerprints pinned before and after):
  - The indexed-palette PNG encoder stages one scanline buffer and hands it to
    zlib directly instead of building a per-row `bytes` list, joining it, and
    narrowing an `intp`-per-pixel `np.unique` inverse. A 1800×840 export peaks
    at 6 MB instead of 50 MB (33 MB instead of 274 MB at 4K) and encodes ~1.8x
    faster; the truecolor branch drops ~17%.
  - Full-column color quantization (density mean-color planes, `direct_rgba`
    channels, u8 live-wire channels) runs chunk-bounded and in place. Its chunk
    was 4M rows, so every real column still paid the one-shot peak: a 2.1M-row
    continuous color channel resolved in 44 MB and now resolves in 7 MB, taking
    a colored 2.1M-point first paint from 181 MB to 147 MB of RSS.
  - Direct-tier scatter/line/area payloads skip the all-visible row mask. Zone
    maps already count NaN *and* ±inf as null, so on linear axes with no nulls
    the mask is provably all-true; it was three O(N) passes and two N-byte
    temporaries per build. Emit is 16–35% faster, and area no longer allocates
    an identity index vector (nor gathers animation keys through it).
  - SVG documents assemble in one flat join with block-buffered markers, and the
    native rasterizer borrows the display list instead of freezing a `bytes`
    copy. A 100k-point SVG export peaks at 27 MB instead of 39 MB.
  - The JPEG encoder streams instead of exploding: the entropy packer works in
    bounded bit passes (it cost 17 bytes per output *bit*, so a 2.8 MB stream
    peaked over 1.5 GB), the YCbCr planes are released as they are consumed, the
    quantize chain rounds in place via `trunc(x + copysign(0.5, x))`, and the
    per-component token fields are freed as they are gathered. A 1800x840 export
    peaks at 48 MB instead of 108 (photographic: **400 MB instead of 1516 MB**)
    and is 5-19% faster.
  - Standalone HTML export joins the document once from parts, with every large
    string — the client bundle, the spec, each base64 chunk — as its own part, so
    the join copies it exactly once. Previously the chunks were folded through a
    `"\n".join(...)` and then into an f-string, duplicating 4/3 of the payload. A
    1M-point export peaks at 33 MB instead of 41; a small export (where the
    ~330 KB client bundle is the document) is ~2% faster.
  - The native rasterizer's serial point and segment passes no longer
    materialize an `0..n` index vector to read back in order (4 bytes per mark),
    and the per-point density quantizer keeps one temporary instead of three.
  - The JPEG token pipeline carries every field at its natural width. It held
    ~20 parallel `int64` arrays over the nonzero coefficients — positions that
    top out at 62, categories at 12, symbols that are a byte by definition —
    while the coefficients themselves fit `int16`, because an orthonormal 8×8
    DCT of level-shifted 8-bit samples is bounded by 1024 and quantizers are
    ≥ 1. The RGB→YCbCr transform also promoted the whole frame to interleaved
    float before splitting it into planes. A 3200×2400 photographic encode now
    peaks at **200 MB instead of 731 MB** and is ~3% faster; the chart-shaped
    export in the memory suite drops 418 MB → 205 MB.
  - The lossless WebP packer scatters bits in bounded entry blocks instead of
    one masked pass per bit position over the whole token stream (five machine
    words per entry, per position), and the header now rides in the token
    buffer rather than being concatenated onto the front of it. A 3200×2400
    export peaks at 135 MB instead of 216 MB at unchanged speed.
- `memory_report()` reports `capacity_bytes` per column and
  `canonical_capacity_bytes` per store, and builds `resident_array_bytes` from
  the capacity total. A streamed column's `values` is a prefix view of its
  capacity-doubling buffer, so up to half of what it holds was invisible to the
  report (§27: if a number isn't in the report, it isn't real). Figures that
  never appended report exactly what they did before.

### Fixed
- **The native raster exporter silently deleted every character outside its
  glyph atlas.** No glyph and no advance, so `Zürich` came out of `to_png()` as
  `Zrich`, a `format="€,.0f"` axis lost its symbol on every tick, and a CJK tick
  label exported as blank space — while the same figure's SVG rendered all of
  them correctly. The atlas now carries Latin-1 Supplement and Latin Extended-A
  (every Latin-script language) plus non-ASCII currency, and anything still
  unbaked — CJK, Cyrillic, emoji — renders as the U+FFFD replacement box with
  its advance reserved, so the limitation is visible rather than silent (§28).
  Costs ~48 KB of baked coverage (+4% on the core dylib).
- **The categorical palette cycled per trace instead of per series.** A box is
  four traces and a stem is two, so four box series under a four-color
  `xy.theme(palette=...)` all wore `palette[0]`, and eight box series drew two
  colors out of the built-in eight. Adding an outlier to one series repainted a
  different one, because it changed the trace count. Marks now take one slot per
  logical series (`Figure.next_series_color`), a mark given an explicit `color=`
  takes none — matching matplotlib's property cycle — and a multi-trace mark no
  longer shifts every series after it.
- **`x_axis(format=...)` / `y_axis(format=...)` were dropped by every static
  exporter.** `format="$,.0f"` read `$1,000,000` in the browser and `1.0e6` in
  the PNG exported from the same figure; `".1%"` read `15.0%` and `0.15`. The
  SVG/raster path now shares the client's grammar, including the strftime subset
  on time axes, and the left gutter grows for labels that need it instead of
  running them off the canvas.
- **A categorical `color=` channel produced no legend in any static export.**
  One trace carries N categories, and the exporters listed rows per *named
  trace*, so `color="species"` drew a single row bearing the trace's name and
  the trace's constant color — a legend that misdescribed the three colors
  printed beside it. Both exporters now expand categories the way the client
  does.
- **`text=` on `hline`/`vline`/bands/`threshold`/`arrow` was silently dropped by
  the static exporters, and `xy.marker()` drew nothing at all.** Labels were
  emitted for `text`/`callout` annotations only, and `marker` had no geometry
  branch. Placement is now one shared helper ported from the client's
  `_drawAnnotationLabels`, so the badge lands in the same place in all three
  renderers.
- **Log-axis decades below 1.0 all rendered as `0`.** Tick precision came from
  the tick *step*, which is meaningless on a multiplicative axis: `0.001` and
  `0.01` became two identical, wrong labels in the client and both exporters.
  Sub-unit decades are now labeled from their own magnitude.
- **A list of CSS colors was re-encoded as categories.**
  `color=["#ff0000", "#00ff00", "#0000ff"]` factorized the three hex strings,
  sorted them alphabetically, and repainted them from the palette, so the marks
  came out in palette colors in the wrong order. `#rrggbb`/`rgb()`/`hsl()` lists
  now paint the colors asked for. Named colors stay categorical on purpose: a
  column of `["red", "green", "blue"]` is ordinary category data, and guessing
  wrong there would turn an encoding into a paint.
- The colorbar stringified its colormap, so a custom ramp reached it as an
  unparseable name and silently painted viridis while the marks beside it
  painted the ramp correctly.
- The client's categorical LUT builders decoded palette entries as hex only and
  would throw on any other CSS color; they now resolve through one helper.
- The density mean-color plane, the SVG writer, and the native rasterizer each
  resolved categorical palettes differently — one of them mapping every
  unresolvable entry to a single shared fallback, merging distinct categories.
  All three now share `channels.palette_rows_rgba8`, which substitutes per
  index and warns.
- `_svg._lut` indexed colormap stops through `uint8`, which was safe only while
  every colormap had ≤ 11 stops; a 256-stop ramp sits exactly at that limit, so
  the index is now `int32`.

## [0.0.3] - 2026-07-24

### Changed
- The runtime-verified WebAssembly wheel now targets the standardized PEP 783
  `pyemscripten_2026_0_wasm32` platform with Pyodide 314, Emscripten 5.0.3,
  and cibuildwheel 4.1.0. It is published directly to PyPI through the existing
  trusted-publishing release job, so browser users can install `xy` by package
  name with `micropip` instead of downloading a GitHub Release asset URL.

### Fixed
- Emscripten cross-builds always package the Rust side module as
  `libxy_core.so`, the filename Pyodide's dynamic loader expects, even when
  cibuildwheel runs on a macOS host.

## [0.0.2] - 2026-07-24

### Changed
- The distribution version is derived from git tags (uv-dynamic-versioning)
  rather than written in `pyproject.toml`. Tagging `vX.Y.Z` is now the whole
  release action; the two numbers can no longer drift, as they had (pyproject
  sat at `0.0.1` while `v0.0.2` was live). Builds between tags are versioned
  `<next>.devN+<commit>`, which PyPI rejects by design — only a tag produces an
  uploadable version. The docs-deploy CalVer tags (`2026.WW.N`) are excluded by
  the `v` prefix the derivation matches on.
- `xy.__version__` now reports the installed distribution's version instead of a
  hardcoded string, resolved lazily on first access so `import xy` keeps its
  import-time budget. An uninstalled source tree reports `0.0.0`.
- The release gate (`scripts/check_release_version.py`) checks the tag against
  `CHANGELOG.md` only; the tag-vs-pyproject leg is gone with the drift it
  existed to catch. Building a release now requires an unshallow checkout —
  `make check-ci` fails any workflow whose `actions/checkout` omits
  `fetch-depth: 0`, since a tagless clone would silently build `0.0.0`.

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

### Fixed
- **Streaming appends no longer draw a stroke-width step after browser zoom.**
  The tail-only GPU upload path bakes `stroke_width` in device pixels, and a
  dpr change (browser zoom, monitor swap) updates `dpr` without rebuilding
  traces — so points appended after the change rendered their outline at a
  different scale than the points already on screen. Such an append now falls
  back to the full rebuild, which renormalizes every row.

### Changed
- **Colored huge-scatter builds are peak-memory-bounded (LOD doc §4.4).**
  The mean-color feature's one-time costs no longer scale peak RSS with N ×
  temporaries: the full-column color-source quantize now runs chunked
  (bitwise-identical math, transient temporaries bounded by
  `channels._QUANTIZE_CHUNK` instead of several × N — ~20 GB at 1e9 rows
  before), the colored pyramid's build scan sheds workers so its 40 B/cell
  accumulators stay inside a 1 GiB budget (an adaptive 8192² base level
  builds serial: one 2.7 GB accumulator, not four), and no-rescan traces
  (huge or out-of-core) resolve without retaining the per-row idx — after
  the pyramid exists, every interactive reply composes prebuilt color
  planes, so retention was resident cost with no consumer. Measured at 205M
  rows: the first colored `density_view` now adds 0.96 GB of peak RSS over
  the canonical columns instead of 3.96 GB, and builds ~35% faster; a
  colored 1e9-point build's transient peak drops to at-or-below the
  count-only build's own fan-out, restoring 1B-point capability wherever
  count-only main could run.
- **Bin-color resolution is resolved once per trace, never per request
  (LOD doc §2).** `density_view` used to quantize the *entire* color column
  into the kernel's LUT-index/RGBA source on every reply — an O(N) NumPy pass
  with multi-GB temporaries that cost the 100M-point FastAPI drilldown demo
  1.3–7 s per request, ~10–100× the actual tier work, even for pyramid and
  points-band replies that never consume it. The resolution is now cached on
  the trace (`interaction.trace_bin_colors`; a rebuildable §27 derived buffer,
  itemized as `memory_report()["bin_color_bytes"]`, invalidated by appends)
  and materialized only by the branches that feed `bin_2d_mean_color`. On the
  demo host every drilldown request now completes in 0.02–0.45 s with
  byte-identical replies; `test_adaptive_drilldown_cycle_mean_color` guards
  the contract in CodSpeed.
- **No sampled points above the resolution of the graph (#225).** Interactive
  `density_view` replies no longer ship a point-sample overlay: a fixed-size
  sample above the drill budget reads as individual data points at a zoom
  where real points are sub-pixel, misrepresenting the dataset — the
  mean-color density surface stands alone there. The retained first-payload
  sample (also the standalone re-bin worker's CPU source) now draws only when
  the view's estimated in-view count fits the direct point budget, i.e. when
  individual points are actually resolvable; real points still ship the
  moment a window fits the budget, so drilldown behavior is unchanged.
- **Mean-color density surfaces composite like the points they aggregate
  (LOD doc §2).** A channel-bearing cell's displayed alpha is now the
  physical compositing of its own points — `1 − (1 − ā)^count` for mean
  point alpha ā — instead of a per-window log-count tone curve. Lightness
  no longer swings between windows or across the texture↔points boundary
  (the aggregate is exactly as saturated as overplotted real marks), the
  texture upload is normalization-free (no exposure re-uploads), and
  mean-color drills swap at native opacity with no intensity handoff.
  Count-only (constant-color) surfaces keep the log ramp — count is their
  only structure. Same law in the client, the SVG/PNG exporters, and the
  standalone re-bin worker.
- **The aggregate tier no longer refines; density requests only probe the
  points band (LOD doc T13).** Whatever density texture already covers the
  view stands — however blurry — until the estimated in-view count comes
  within `LOD_POINTS_REQUEST_BAND ×` the direct budget; only then does a
  `density_view` go out, and the kernel answers with exact points once the
  count fits. The estimate takes the lower of an area-scaled cached-window
  count and the retained first-payload sample counted in-view — the sample
  follows the data's actual distribution, so sparse regions reach their
  points without being stranded in blur by uniform-density assumptions.
  Display-side, the aggregate sharpens in QUANTIZED ladder steps between
  home and points (`LOD_AGG_STEP_FACTOR`/`LOD_AGG_STEP_MAX`: the view
  snapped outward to a power-of-4 block grid over the extent, at most two
  steps) — pan-stable, dedupable windows, so a zoom sees at most two
  smooth-to-smooth texture swaps and worst-case softness is bounded at
  ~4× stretch per axis. A step reply is the only density reply that may
  repaint a covered view; mid-band probe replies (the band's exact grids
  have a speckled character that read as zoom-level jumping against the
  smooth standing surface) land as facts-only cache entries for the gate.
  Replies for uncovered views still apply, and standalone clients keep
  applying everything. A 100M-scatter field capture had shipped a ~2.7 MB full-screen
  grid on every pan/zoom step (including sub-pixel window twins, now deduped
  within half an output texel) for what was the same aggregate with
  marginally different blur; intermediate-zoom blur is the accepted,
  recorded cost. Transition-band replies that do go out are clamped to the
  pyramid's source resolution — never more cells than the finest level
  resolves under the window. Kernel-attached clients also no longer draw the
  retained first-payload sample at any zoom (resolvable views get real
  points, not retained sample rows); it remains the standalone client's
  fallback, gated by resolvability. A tried fine-over-broad texture layering
  was reverted (recorded): density textures alpha-composite, so overlaps
  double-count opacity, and per-window normalization makes the seam a
  brightness step.
- **Full-point windows are padded, aligned, cached, and never re-requested
  (LOD doc T13).** A points-tier reply now ships the largest aligned window
  around the view whose exact count still fits the budget (bounds snapped to
  a power-of-two grid over the trace's extent, per dimension), so consecutive
  pans resolve to the same window; the client retires replaced exact windows
  into a bounded per-trace cache and promotes them back — pan ping-pong and
  zoom-out/zoom-in render entirely from the GPU with zero round-trips. Picks
  against a promoted (older) window still resolve exactly through a bounded
  kernel-side subset history. Identical `density_view` requests (same window,
  same screen, unchanged data) are suppressed client-side, and a suppressed
  duplicate's in-flight reply is accepted instead of dying to the seq race.
- **Density surfaces now wear the data's own colors (LOD doc §2).** A Tier-2
  scatter's aggregated view colors each cell with the alpha-weighted **mean of
  its binned points' resolved colors** (continuous colormap, categorical
  palette, and direct-RGBA channels alike; averaged in linear light through a
  deterministic integer pipeline), while the binned **count now drives only
  the alpha channel** — more points, deeper color; fewer points, lighter.
  Previously the count itself was colormapped, so a colored scatter's density
  view matched neither its points nor its legend and every density⇄points
  zoom transition recolored the chart. The wire ships a per-cell RGBA plane
  (`density.rgba`, recorded as `color_agg: "mean"`); constant-color traces
  keep the compact count-only grid and a client-side tint. The count pyramid
  gained matching mean-color planes (`xy_pyramid_build_color` /
  `xy_pyramid_compose_color`; colored pyramids refuse in-place appends and
  rebuild lazily, and their base scan fans out ≤4 workers so a 100M-point
  build lands in about a quarter of the time), the SVG/PNG exporters and the
  standalone `to_html` re-bin worker follow the same law, and the drill
  handoff is now intensity-only — drilled points arrive in their native
  colors (`density_colormap` left the points wire), and the aggregate
  backdrop retires once a drill settles inside its window (T10), returning
  the moment the view leaves it or a refinement goes pending. The color
  channel is no longer listed in `dropped_channels` at Tier 2, and a
  continuous-channel density scatter renders its colorbar again. C ABI v40
  (`xy_bin_2d_mean_color` + pyramid color entry points).
- **The FastAPI live-drilldown example is a thin transport over the engine.**
  Every window is served through `Figure.density_view` (mean-color pyramid
  warmed at startup); the demo's pre-pyramid density machinery — an
  integral-image overview server-side and ~350 lines of page JS (local
  re-bins, request parking, per-client staleness maps), all count-only — is
  gone, and the page JS is a POST transport plus a status badge. Round-trip
  replies ship as `XYBF` binary frames (wire-protocol §7) instead of
  base64-in-JSON.
- **Zooms inside an exact drill window skip the kernel round-trip (T12).**
  Once a points reply has shipped its window exactly (`reduction: "none"`),
  the client answers any contained view from the marks it already holds and
  sends no `density_view` request, until the view leaves the window, the
  drill dies, or the zoom is deep enough (1/256 of the window span) to need
  a §16 re-centered f32 encoding.

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
