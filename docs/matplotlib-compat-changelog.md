# Matplotlib compatibility changelog

This changelog records changes to the upstream compatibility target and to the
meaning of xy's compatibility levels. It complements the project changelog,
which covers user-visible releases across the whole package.

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

Future entries must identify the Matplotlib release/revision, inventory
additions or removals, and any compatibility-level changes.
