# Matplotlib compatibility changelog

This changelog records changes to the upstream compatibility target and to the
meaning of xy's compatibility levels. It complements the project changelog,
which covers user-visible releases across the whole package.

## Patch bodies and geometry — 2026-07-30 (Matplotlib 3.11.1 reference)

- `xy.pyplot.Axes.add_patch` now fills a patch instead of drawing only its
  outline. Each ring gets a triangle mesh in the patch's own face color, with
  triangle joins marked as a single fill so browser, PNG, and SVG output
  suppress internal seams. Patches that report `fill=False`, a `"none"` face
  color, or a fully transparent one stay edge-only, and the patch never
  advances the axes color cycle.
- Patch geometry now comes from `Path.to_polygons`, with the patch transform
  applied. `Rectangle(angle=...)` keeps its rotation, and curved patches use
  the curve rather than its cubic Bézier control points: at the default figure size
  `Circle(radius=1)` covers 3.141 rather than 3.251, and
  `Ellipse(width=2, height=1, angle=20)` covers 1.570 rather than 3.251.
- The flattening is resolved at the figure's pixel size rather than in data
  units. `to_polygons` subdivides until the curve is flat in whatever
  coordinates it is handed, so flattening straight through the patch transform
  would take its tessellation from the numeric magnitude of the data:
  `Circle(radius=1)` came back as sixteen segments overshooting the true
  radius by 2.5%, while the same circle drawn as `radius=1000` came back
  smooth. Matplotlib does not have this problem, because its renderers flatten
  in display space, after the full data-to-pixel transform. xy builds geometry
  when the patch is added, before the view is known, so it flattens as though
  the patch filled the figure — the finest resolution it could need — which
  holds the radial error near 1e-4 at every coordinate scale.
- Outlines take the patch's own line width, converted from Matplotlib points
  into output pixels like every other stroke in the shim, instead of a fixed
  one pixel that did not move with figure DPI. A patch whose edge paints
  nothing — `edgecolor="none"`, which is Matplotlib's default on a filled
  patch, a fully transparent one, or `linewidth=0` — emits no outline mark at
  all, unless it drew no body either. Degenerate rings with no triangulation,
  such as a zero-height `Rectangle`, draw their edge and skip the fill rather
  than raising.
- A ring that has a body but no triangulation — self-intersecting, or past
  `polygon_triangles`' 10,000-vertex cap — draws its outline and raises a
  `RuntimeWarning` naming the reason. Matplotlib fills both, so abstaining
  silently would leave a hollow patch that looks like a deliberate style.
- An artist-level `transform=` on the patch rides along when it is a
  data-space affine — `Rectangle(..., transform=Affine2D().rotate_deg(45))`
  keeps its rotation, and `transform=ax.transData` is accepted as the no-op
  it is. `transform=ax.transAxes`/`transFigure` raise `NotImplementedError`
  like every other data artist, since baked fractions go silently stale on
  the next limit change.
- Holes are not implemented. A patch whose path has nested rings, such as a
  compound `PathPatch` of a square inside a square or a full-circle `Wedge`
  with a `width`, draws its outlines and skips the fill rather than painting
  the hole solid. `polygon_triangles` takes one simple polygon, so filling
  every ring would paint 116 for a square-with-hole whose true area is 84.
  Nesting means every vertex of one ring inside another: rings that merely
  overlap fill ring-by-ring (their union, where Matplotlib's even-odd rule
  leaves the intersection unpainted), rings that sit beside each other still
  fill, and an annular *sector* fills correctly because Matplotlib returns it
  as one ring that traces out along the outer arc and back along the inner
  one.
- `add_patch` returns a `Patch` handle rather than a bare `Artist`. It owns the
  outline marks alongside the fill, so `remove()`, `set_zorder()`,
  `set_visible()`, `set_alpha()`, `set_color()` and `set_transform()` move the
  whole patch instead of only its body. `set_color` paints edge and face
  alike, as `matplotlib.patches.Patch.set_color` does.

## Box and violin default geometry — 2026-07-26 (Matplotlib 3.11.1 reference)

- `xy.pyplot.boxplot` no longer routes its default call through the native
  opinionated box mark. It now draws Matplotlib's unfilled line geometry and
  returns one box, median, and flier handle plus two whisker and cap handles per
  group. Fliers stay centered on their group even when several groups are
  present, and empty groups of fliers still have the expected handle.
- `xy.pyplot.violinplot` now uses the same Gaussian-KDE path for its default
  Scott bandwidth as it does for explicit Scott, Silverman, scalar, and
  callable bandwidths. It returns one body per group, with triangle joins
  marked as a single fill so browser, PNG, and SVG output suppress internal
  seams.
- The public composition API keeps its independent native `box` and `violin`
  marks and their opinionated styling; this compatibility correction is
  contained inside `xy.pyplot`.

## Histogram and spectral numeric semantics — 2026-07-26 (Matplotlib 3.11.1 reference)

- `hist(density=True, stacked=True)` now bins raw per-dataset mass, stacks it,
  and normalizes the combined top envelope once. Unequal bin widths, weights,
  and both cumulative directions match Matplotlib 3.11.1 numeric outputs.
- The native Welch paths behind `psd`, `csd`, `cohere`, and `specgram` no
  longer subtract each segment mean by default. Their omitted/`None`
  `detrend` behavior is Matplotlib's `detrend_none`; unsupported explicit
  detrending modes continue to fail loudly at the pyplot boundary.

## Vector-field gallery corrections — 2026-07-24

- `quiver(units=...)` now converts Matplotlib's width-unit vocabulary without
  changing arrow length semantics; figure-coordinate quiver keys also convert
  their basic MathText labels.
- `barbs` now renders fixed-length WMO-style flag/full/half geometry and honors
  length, pivot, increments, rounding, empty fill, size, color, and flip
  controls.
- `streamplot` now uses an occupancy-aware adaptive Heun integrator for default
  and explicit seeds. `broken_streamlines=False` and both Matplotlib 3.11
  integration scale controls affect the generated trajectories.

## Matplotlib 3.11 development snapshot — 2026-07-13

- Pinned upstream revision `bde111fb4e`
  (`v3.11.0-348-gbde111fb4e`, 2026-07-10).
- Captured the supported 66-method `Axes` Plotting inventory as a generated,
  reviewed snapshot instead of a hard-coded assertion.
- Added `grouped_bar`, `pie_label`, and `violin` from the 3.11 development
  surface.
- Added a dedicated CI environment for optional Matplotlib-object interop and
  isolated dual-engine execution of the full compatibility corpus.
- Published approximation levels and a generated method compatibility matrix.

### Post-review corrections — 2026-07-13

- Downgraded "Unstructured triangles" from *exact geometry* to *equivalent
  semantics*: the family has no cross-engine reference comparison yet.
- Converted the formerly silent option discards into loud rejections: pie
  shadow/frame/rotatelabels/hatch, quiver/barbs/quiverkey head geometry,
  units, increments and styling, contour origin/linestyles/corner_mask,
  table placement, tricontour extend, non-linear norm objects everywhere,
  spy aspect, and pie_label rotate.
- Implemented (rather than rejected) where the marks could honor the value:
  contour `extent`; plain `Normalize` reduced to vmin/vmax for pcolormesh and
  the tri* family; stem/eventplot/triplot dashed linestyles via data-space
  dash segmentation (scales with zoom — not screen-space patterns);
  `bar_label(fontsize=)` and pie/pie_label/table textprops
  fontsize/ha/va; streamplot `start_points`, `integration_direction`,
  array widths/colors, `num_arrows`.
- `streamplot` now always uses the shim's bounded fixed-step integrator;
  results no longer differ between environments with and without Matplotlib
  installed, and paths approximate Matplotlib's adaptive integrator.
- `hist(histtype="stepfilled")` renders a filled step polygon instead of
  silently degrading to the unfilled step outline.
- Documented the accepted visual approximations explicitly (barbs glyph,
  imshow smoothing collapse and truecolor passthrough, annotate arrowprops,
  errorbar limit carets, data-space dashes) and the HTML-only scope of
  chrome rcParams.

### PDSH gap features — 2026-07-13 (Matplotlib 3.11.0 reference)

Driven by the Python Data Science Handbook ch. 4 benchmark (import-swap over
14 notebooks): pass rate 121/171 → 154/171 runnable cells (90%), 147/154
(95%) excluding the out-of-scope 3-D notebook, with zero savefig errors on
passing cells.

- Tick machinery: xy-owned `NullLocator`/`FixedLocator`/`MultipleLocator`/
  `MaxNLocator`/`LinearLocator`/`LogLocator` and `NullFormatter`/
  `FixedFormatter`/`FuncFormatter`/`FormatStrFormatter`/`StrMethodFormatter`/
  `ScalarFormatter`, wired through `set_major_locator`/`set_major_formatter`
  and resolved at build time so ticks track live data limits. `set_xticks`
  and explicit labels displace stored tickers (last call wins). Minor
  locators/formatters are retained but minor ticks still do not render.
- Styles: `plt.style.context(...)` (snapshot/restore incl. theme tokens) and
  the stock sheets fivethirtyeight, ggplot, bmh, dark_background, grayscale,
  seaborn-v0_8-white(grid), reduced to the supported rcParams subset; new
  `grid.color` rcParam wired into the axes chrome; `cycler()` (color only).
- Colormaps: RdGy and jet engine tables (11 anchors sampled from Matplotlib
  3.11) across Python SVG/PNG and the JS client; `LinearSegmentedColormap.
  from_list` / `ListedColormap` as Python-side callables; `cm.get_cmap`.
- Mappables: pyplot wrappers register the current image (`gci`/`sci`);
  `plt.clim` retargets it and any colorbar derived from it; `set_clim` on
  scatter/poly collections; scatter vmin/vmax now flow into a real
  `color_domain` on the engine's color channel (previously they crashed the
  render). `colorbar()` returns its handle from pyplot, falls back to the
  current image, renders `ticks=`/`extend=` in PNG and SVG, and rejects
  unknown kwargs (previously swallowed silently).
- Layout: `plt.GridSpec` with slice spans and wspace/hspace/ratios resolved
  to explicit figure rectangles; `add_subplot(spec, sharex=, sharey=,
  xticklabels=[])`; `subplot(r, c, i)` mixes into figures that already hold
  free-form axes; `subplots(subplot_kw=)`.
- Axes surface: `get_figure`, `get_lines`, `get_shared_x/y_axes`,
  `get_x/yticklabels` (recolorable handles), `set_facecolor` (+ the
  `plt.axes(facecolor=)` route), `set_axisbelow(True)`, spine iteration with
  deferred both-or-loud hiding, `tick_bottom`/`tick_left`, `fig.canvas`
  facade; pandas `Period` coordinates convert to timestamps.
- Fixed en route: `grid(linestyle='solid')` injected an invalid `None` style
  value and crashed every subsequent export of that axes; `plt.subplot()` and
  `plt.axes()` silently dropped their keyword arguments; `projection=` other
  than rectilinear now fails with a clear NotImplementedError.
- Known remaining boundaries measured by the benchmark: pandas' dynamic
  timeseries plotting (its private ordinal-axis locators), legend geometry
  options (`borderpad`, `labelspacing` — still loud), `Legend` handles for
  second legends, markers on axhline, and 3-D axes.

### Second review pass — 2026-07-13

- Silent divergences converted to correct behavior: scatter drops rows masked
  in x/y/s (not just c); `fill_between(interpolate=True)` draws single-point
  `where` regions; `imsave` colormaps original values instead of a
  pre-quantized uint8 copy; `set_cmap` validates names and feeds
  imshow/scatter defaults; boxplot `sym` is honored (empty string suppresses
  fliers) and flierprops colors reach the drawn dots; usermedians no longer
  shift notch CIs; hexbin `mincnt` filtering and `C` aggregation use the same
  bin membership.
- Silent discards converted to loud rejections: bxp component linestyles,
  secondary-axis `set_ticks` extras, axes/figure-fraction transforms on data
  artists, `savefig(format='html', metadata=)`; singular transforms fail at
  `set_transform` time with ValueError.
- Export: SVG/HTML honor `savefig(facecolor=)` (background rect / styled
  container); single-chart SVG includes the suptitle; composed-SVG suptitle
  `y` maps as a figure fraction; non-Latin-1 PNG metadata keys raise
  ValueError.
- Scales: logit masks values at/outside (0, 1) instead of emitting ±inf;
  scale-generated ticks refresh as data arrives and are dropped when the
  scale returns to linear; explicit `set_*ticks` under a nonlinear scale
  label the original data values.

### Visual-parity audit — 2026-07-14 (PDSH ch4, image-level)

The cell pass-rate benchmark (154/171 running) measures *execution*, not
*appearance*. This audit rendered every PDSH cell to PNG under both engines
with per-cell seeded RNG (identical data), and visually graded every image
pair (matplotlib 3.11 reference). Result over the 105 comparable non-3-D
pairs: **38 match (36%), 24 minor divergences (23%), 39 major (37%),
4 missing** — running is far ahead of looking right. The majors cluster
into a dozen root causes, recorded here as known defects until fixed:

1. `legend(['a', 'b'], loc=...)` — an explicit label list renders no legend
   at all (7 cells in the stylesheets notebook alone).
2. `plot(x, y_2d)` does not advance the color cycle; every column draws in
   the first cycle color.
3. Count-based mappables (`hist2d`, `hexbin`, KDE rasters) label their
   colorbar 0–1 instead of the count domain, colorbar tick labels print raw
   floats (`6.01004e-07`) instead of nice steps, and zero-count bins render
   empty where Matplotlib paints the 0-color field.
4. `imshow(..., cmap='RdBu')` + `clim` can leave the raster on the default
   colormap while the attached colorbar correctly shows RdBu — image and
   legend disagree. Discrete colormaps (`get_cmap(name, N)`-style) render
   as continuous gradients.
5. Contours: no dashed-negative convention, auto level count runs 2–3× 
   Matplotlib's, `contourf` bands smooth into gradients.
6. **Mixed-engine measurement artifact (out of scope):** when seaborn —
   which draws through real Matplotlib — owns the current figure,
   module-level `plt.hist`/`axvline`/`axhline` draw onto xy's own figure,
   so three seaborn-notebook cells count as passing while their plt-drawn
   content lands elsewhere. This can only occur in a mixed environment:
   xy replaces Matplotlib, and without Matplotlib installed seaborn fails
   loudly at import. No runtime fallback onto Matplotlib will be added;
   the benchmark's seaborn column is soft evidence only.
7. `annotate` draws no arrow and ignores the `xytext` offset.
8. A free-form `plt.axes([x, y, w, h])` inset next to a default axes
   renders as an equal side-by-side panel even in PNG (contradicting the
   documented free-form-rect exactness); the 04.08 `GridSpec` span pattern
   and `sharex`/`sharey` inner tick-label suppression are also lost.
9. Mathtext (`$...$`) is never rendered; tick/axis labels show the raw
   source text.
10. `MultipleLocator(π/2)` tick labels round to integers; log axes lack
    `10^k` labels and draw gridlines at minor-tick positions.
11. Silent fallbacks: `'p'` pentagon markers render as squares, hexbin as
    sparse dots, `errorbar(fmt='.k')` bars stay the default blue, and
    bubble-chart `alpha` is dropped.

Systematic (graded minor, one deliberate decision pending): open L-frame
instead of Matplotlib's boxed axes, gapped histogram bars, horizontal
top-left y-label instead of rotated, coarser default tick density with
trailing zeros dropped, legend swatches that do not reflect line/marker
style, `frameon=False` ignored.

Method and per-cell ledger: dual-engine PNG dump with ordinal-paired
filenames, 14 independent image-comparison passes, every root cause
re-verified by direct image inspection before recording.

### Visual-parity fix rounds — 2026-07-14 (Matplotlib 3.11.0 reference)

Closed the bulk of the audit above, verified by re-rendering every notebook
and re-grading each image pair. Across the 12 comparable notebooks (84
graded pairs), majors fell **33 → 8** and exact matches rose 25 → 34, with
the audit's biggest single offenders (stylesheet legends, color cycle,
colorbar domains) fully cleared.

- Legends: explicit label lists (`legend(['a','b'], loc=...)`) render;
  entries show line samples (color + dash) or the real marker glyph instead
  of colored squares; `frameon=False` removes the box; handles+labels form
  relabels without phantom traces.
- Color: `plot(x, y_2d)` advances the prop cycle per column. Every colormap
  stop table is now sampled exactly from Matplotlib 3.11 (plasma/inferno/
  magma/rainbow/turbo/cividis/coolwarm had drifted up to 128 channel levels;
  plasma's padded tail merged discrete bands), and `RdBu` is the true
  ColorBrewer table instead of a coolwarm alias. Count-based mappables
  (hist2d/hexbin) label colorbars with real count domains; colorbar ticks
  use nice steps; hist2d zero-count bins paint the colormap floor
  (NaN stays transparent — the ABI smoke expectation moved with it).
  imshow honors reversed/`_r` colormaps and post-hoc `clim`. Discrete
  N-level colormaps quantize both marks and colorbar into N bands.
- Contours: dashed-negative convention for single-color contours,
  Matplotlib's auto level count, piecewise-constant `contourf` bands.
- Markers: real pentagon/hexagon/star SDFs in the native rasterizer +
  SVG/GL equivalents; fmt-string markers keep their shape and fill.
- Errorbars: `fmt`/`color=` reach markers and bars independently of
  `ecolor` (a first-round regression caught by the re-grade and fixed).
- Layout: free-form axes rects survive next to default axes in PNG (insets
  render in place); `subplots(sharex=/sharey=)` accepts 'all'/'col'/'row',
  unions domains per group, and hides inner tick labels via the new
  `tick_label_strategy="off"` (labels only — grid, baselines and axis
  titles stay; `"none"` keeps its silence-everything sparkline meaning).
- Text: tick labels keep locator-step precision (`MultipleLocator(π/2)` →
  1.57/3.14…); log axes label decades as 10ᵏ and grid majors only; a
  bounded TeX-subset → unicode converter (`_mathtext.py`) feeds every shim
  text path (labels, titles, ticks, legends, colorbar labels, annotations);
  the native rasterizer's baked atlas gained greek/super-subscript/math
  glyphs with a UTF-8 text wire (ABI 32 → 33) and rotated y-axis titles.
- Annotate: `xytext` places the text (data coords) and `arrowprops` draws a
  real arrow (straight shaft + filled head, `shrink` honored) in PNG/SVG;
  curved connectionstyles are approximated by the straight shaft.
- scatter `s=` keeps Matplotlib's absolute area semantics (size arrays no
  longer compress into the engine's relative 2–18 px band).

### Visual-fidelity follow-up — 2026-07-14

- Directional triangle markers and diagonal `x` now have distinct SVG,
  native-raster, and WebGL glyphs rather than collapsing into up-triangle and
  plus.
- `clabel` places a bounded set of separated labels along every contour level
  instead of one label per level.
- Hexbin now uses the two offset center grids and nearest-center hex metric,
  emits complete zero-count lattices by default, and renders each occupied
  cell as six data-space triangles. Bin membership and visible tessellation
  now agree across browser, PNG, and SVG.
- Horizontal bar/step/stepfilled histograms put counts on x; the filled form
  uses touching horizontal bins rather than a vertical area primitive.
- `borderpad`, `labelspacing`, `fancybox`, `framealpha`, `shadow`, and legend
  titles reach browser and static renderers, clearing the two loud PDSH
  legend-style cells.
- `subplots_adjust` now raises `NotImplementedError` when given material
  values; use `GridSpec` for supported spacing. This removes the last known
  silent Matplotlib-shim option discard.
- Direct Matplotlib 3.11/xy PNG comparisons of the six affected PDSH cells
  verified usable marker, contour, lattice, legend, and horizontal-histogram
  output.
- The final systematic minors are now closed: automatic ticks include the 2.5
  nice step and keep a shared fixed precision, `loc='best'` chooses the least
  occupied corner from bounded data samples, and pyplot transports an explicit
  four-sided frame with independently controllable spines to browser, PNG, and
  SVG. A follow-up Matplotlib 3.11 comparison verified all three together.
- The non-gating `ty` diagnostics on zone-map min/max folds were removed by
  using typed list reductions; the complete shippable Python package now type
  checks cleanly.

### Free-form layout parity — 2026-07-14 (Matplotlib 3.11.0 reference)

- HTML output now places free-form panels absolutely at their figure
  rectangles on a fixed-size canvas, matching the PNG compositor: `add_axes`
  rects stack and overlap exactly as in Matplotlib (an inset `plt.axes([...])`
  draws on top of a default axes instead of rendering as a side-by-side grid
  panel), with document order providing Matplotlib's draw order. SVG export
  gained the same absolute-placement path.
- `Figure.subplots_adjust(left=, right=, top=, bottom=, wspace=, hspace=)` is
  now implemented instead of raising `NotImplementedError` (which superseded
  the earlier silent discard): the values update the figure's SubplotParams
  frame, subplot grids resolve to per-cell figure rectangles through the
  GridSpec geometry (wspace/hspace as fractions of the average cell size, like
  Matplotlib), and all three exporters position panels at those rectangles.
  Out-of-order frames (`left >= right`, `bottom >= top`) raise `ValueError`
  as in Matplotlib. This clears the two loud PDSH `subplots_adjust` cells
  (04.08 2×3 labeled grid, 04.10 5×5 zero-gap faces).
- The interactive modebar is now off by default, matching Matplotlib's inline
  backend: `rcParams["toolbar"]` defaults to `"none"`, and panels draw the
  on-chart controls only when it holds any other value (`"toolbar2"`,
  `"toolmanager"`). `figure(toolbar=...)` — also reachable through
  `subplots(..., toolbar=...)`, which forwards it to `figure` — overrides
  rcParams for one figure.

### Default colorbar label orientation — 2026-07-24 (Matplotlib 3.11.1 reference)

- `Colorbar.set_label(...)` / `colorbar(label=...)` now render Matplotlib's
  default label geometry in native PNG: rotated 90° counter-clockwise and
  centered beside a vertical bar, outboard of its tick labels. The native exporter had
  instead drawn the label horizontally above the bar at `plot.y - 5`, where the
  glyph ascent overflowed the canvas top edge and the text was clipped — the
  placement was chosen on the since-outdated assumption that the native text
  primitive could not rotate. It rotates in quarter turns
  (`TEXT_ROTATED`/`TEXT_ROTATED_CW`, already used for rotated axis titles), so
  90° is exact here; only arbitrary text angles still fall back to upright
  glyphs. The two static exporters now use the same baseline. Browser and SVG
  output are unchanged — both already had the correct default orientation.
  This clears the three loud-free but visually wrong PDSH ch. 04.05 cells
  (`hist2d`, `hexbin`, and `imshow` colorbars with labels).
- Non-pyplot (composition API) colorbars built with `xy.colorbar(title=...)`
  share the same renderer, so their vertical labels change in PNG export the
  same way. Horizontal colorbar labels are untouched in every renderer.
- Matplotlib's `Colorbar.set_label` customization keywords (`loc`, `labelpad`,
  rotation, and other text properties) remain outside this change and are
  currently accepted and ignored by the shim.

### Mesh and distribution autoscale — 2026-07-24 (Matplotlib 3.11.1 reference)

- The shim's pre-build autoscale scan (`Axes._iter_entry_arrays`) now
  recognizes the `@mark`/`heatmap`, `step`, and `box` entry shapes, which keep
  their coordinates inside `kwargs` or compact factory arguments rather than
  as top-level `x`/`y`. Those
  axes previously scanned as *dataless* and were pinned to the empty `(0, 1)`
  view, clipping the geometry: a 30×30 `hist2d` showed roughly 3×1 of its bins.
  Affects `hist2d` (uniform bins), `pcolormesh` on a uniform grid, `specgram`,
  `ecdf`, `step`, and the compact `boxplot` path. Non-uniform
  `hist2d`/`pcolormesh` meshes now carry their coordinate-grid extent through
  the triangle expansion too, including when every scalar is masked.
  `hexbin`, `contour`/`contourf`, `imshow`, `tripcolor`, `violinplot`, and
  `errorbar` already scanned correctly and are unchanged.
- Sticky edges are now derived for mesh, image, and ECDF entries, so
  `hist2d`/`pcolormesh`/`specgram`/`imshow` view limits are exactly the outer
  cell edges and an ECDF's cumulative axis is exactly `0..1` — matching
  Matplotlib, which gives these artists sticky edges and therefore no margin.
  An axis with sticky edges on *both* ends ships a materialized `domain`
  instead of a `margin`; one-sided rectangle baselines are unchanged and stay
  anchored by the engine.
- `pcolormesh(C)` uses Matplotlib's implicit integer edges `0..N` and `0..M`;
  `specgram` reconstructs its image centers so the frequency view lands on the
  FFT endpoints instead of adding half a frequency bin beyond them.
- `boxplot` autoscales its value axis over the Tukey whiskers plus the flier
  points when `showfliers` is on. Its default category positions are
  Matplotlib's 1-based ordinals, and `manage_ticks=True` reserves a half unit
  around the outer positions regardless of the drawn box width.

Future entries must identify the Matplotlib release/revision, inventory
additions or removals, and any compatibility-level changes.
