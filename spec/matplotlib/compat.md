# matplotlib compatibility (`xy.pyplot`)

```python
import xy.pyplot as plt   # the one-line change
```

`xy.pyplot` is a shim over the declarative composition API: every
call translates onto `xy.chart(...)` and friends, so shim charts get
the same engine — native Rust compute, binary transport, WebGL2 rendering,
screen-bounded cost — with matplotlib's calling conventions.

**The claim, precisely:** every method in the Matplotlib 3.11 `Axes` **Plotting**
section is present on both `xy.pyplot.Axes` and the stateful `xy.pyplot`
namespace. The reviewed
[`matplotlib_311_plotting.json`](../../tests/pyplot/matplotlib_311_plotting.json)
snapshot locks that inventory to the pinned upstream documentation, while the executable compatibility
corpus in [`tests/pyplot/corpus/`](../../tests/pyplot/corpus/) covers representative
calls from every family. This is 100% 2-D *chart-method* coverage; it is not a
claim to reproduce Matplotlib's renderer, transforms, or full Artist graph.

The generated [method-by-method compatibility matrix](compat-matrix.md)
is sourced from that snapshot, executable corpus calls, and
[`compatibility.json`](../../tests/pyplot/compatibility.json). CI fails if the
generated matrix is stale, installs the released `matplotlib==3.11.0` wheel,
and asserts every snapshot method exists on its `Axes`. The dev revision
recorded in the snapshot is informational: CI no longer compares the snapshot
against an upstream Matplotlib checkout.

The dual-engine runner executes every corpus case in a fresh process. Its
reference harness only normalizes renderer-specific HTML export and xy's
dependency-free `triangles=` shorthand into Matplotlib's equivalent
`Triangulation` positional form; chart data and plotting options are unchanged.

## Approximation levels

- **Exact geometry:** material data-space geometry and returned numeric values
  are intended to match Matplotlib.
- **Equivalent semantics:** user intent and data results match, using xy-owned
  artists, containers, and renderer behavior.
- **Visual approximation:** the visible chart family is retained, but styling,
  layout, or artist details can differ across renderers.
- **Accepted no-op:** a documented option is validated and retained without a
  visible effect; this is used only when a stable output guarantee is tested.
- **Optional interop:** behavior accepts real Matplotlib objects only when
  Matplotlib is installed; it is tested in the dedicated reference CI job.
- **Unsupported:** the shim rejects the call or option with an actionable error
  rather than silently discarding it.

## Supported surface

| matplotlib | notes |
|---|---|
| `plt.plot` / `ax.plot` | format strings (`'r--o'`), multiple series per call, implicit x, `label=`, `lw=`, `ls=`, `alpha=`, marker face/edge styling, directional `^`/`v`/`<`/`>` triangles and distinct `+`/`x` glyphs, `markevery`, and dependency-free affine *data* transforms (`Affine2D + ax.transData`); axes/figure-fraction transforms on data artists, partial fill styles, and cap/join policies fail loudly |
| `scatter(x, y, s=, c=, cmap=, vmin=, vmax=, alpha=, marker=, edgecolors=, plotnonfinite=)` | `s` (pt², area) maps to pixel diameter; numeric 1-D `c` remains a colormap encoding, while `N×3`/`N×4` face and edge colors, alpha arrays, sizes, and linewidth arrays stay in one collection. Explicit alpha replaces intrinsic RGBA alpha, matching Matplotlib; custom norms/marker paths fail loudly |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories, stacking bases, per-bar face/edge color-alpha pairs and linewidths, plus iterable/indexable `BarContainer.patches` views whose setters mutate the parent batched trace |
| `hist(bins=, range=, density=, cumulative=, weights=, orientation=, stacked=)` | Returns computed counts/edges; bar, step, and stepfilled families render in both vertical and horizontal orientations |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel; hexbin uses Matplotlib's two-offset-grid nearest-center assignment and six-triangle data-space cells, supports `C`, arbitrary scalar reducers, and `mincnt`, and retains only the bounded lattice rather than source points. `hist2d` view limits are the outer bin edges with no margin, matching Matplotlib's sticky mesh edges; non-uniform bins delegate to `pcolormesh` and autoscale through the quad-mesh path instead. `ecdf` carries the ordinary margin on the sample axis and is sticky at 0 and 1 on the cumulative axis |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Boxplots support notches, bootstrap/user confidence intervals, median overrides (drawn median only; notch CIs stay data-derived like Matplotlib), percentile/custom whiskers, cap widths, `sym`, and component colors/widths/alpha — dashed component linestyles fail loudly. Violins support Scott/Silverman/scalar/callable Gaussian-KDE bandwidths, quantiles, and low/high sides; the default (bw_method omitted) uses the native histogram violin mark, whose shape differs from the explicit KDE path. `boxplot` autoscales its value axis over the Tukey whiskers plus, when `showfliers` is on, the flier points. Its default category positions are 1-based and `manage_ticks=True` reserves half a unit around the outer positions, matching Matplotlib |
| `fill_between(x, y1, y2, where=, step=)` / `fill_betweenx` | Masks are split into finite contiguous polygons; step geometry is expanded exactly |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | `imshow` defaults to `rcParams['image.origin']`; nearest stays cell-exact, while named smoothing modes use dependency-free per-kernel approximations over a bounded 512–1024 px intermediate for both scalar and RGB(A) data. Filter choice and intermediate size do not yet depend on final display resolution, and explicit `interpolation="auto"` remains unsupported. Unsupported stages/transforms fail loudly. Uniform meshes retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion. Both hug their outer cell edge with no margin, as Matplotlib's sticky image/mesh edges do |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels; automatic labels repeat at bounded, separated positions along each level (line knockout for `inline=True` remains a visual approximation) |
| `quiver`, `barbs`, `streamplot` | Quiver supports Matplotlib's width-unit vocabulary independently from length scaling. Barbs use fixed-length staffs and Matplotlib's flag/full/half decomposition, including increments, rounding, empty glyphs, colors, sizes, flipping, and pivots. Streamplot uses a dependency-free adaptive Heun integrator with occupancy-aware seeding; `start_points`, `integration_direction`, `broken_streamlines`, integration step/error scales, array widths/colors, and `num_arrows` are honored |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels), including dtype-preserving value formats, radial label rotation/alignment, and common text properties |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Fractional span bounds plus data/axes/figure text coordinates are supported. `annotate(arrowprops=)` draws real arrows in every output: offset-point text becomes an engine callout (arrow pinned from label to point across zoom), data-coordinate text an arrow annotation; date-string coordinates convert on datetime axes. Arrowstyles map to head/tail shapes (`->` open V, `-\|>` filled, `\|-\|`/brackets bar caps, `fancy`/`simple`/`wedge` filled tapered shafts sized by the text's mutation scale) and `connectionstyle` arc3/angle3/angle become quadratic curves (corner rounding approximated); `alpha` dims the arrow only. `bbox=` becomes label box styles (fill/edge/round corners/`pad`) in browser and static exports; its `alpha` is the *patch* alpha and dims face and edge together, as Matplotlib's element `opacity` does, and `boxstyle="round"`/`round4` corners are rounded in SVG (`rx`) and native PNG as well as in the browser. An arrow-less `text`/`annotate` label is painted with `rcParams["text.color"]` in all three renderers rather than each renderer's own annotation-label default. Text is unclipped like Matplotlib (`clip_on=False`), and axes-fraction text right of the axes box (x > 1, e.g. seaborn-style row titles) reserves right margin in every exporter. `rotation=90/270` renders vertical text in browser, PNG, and SVG with Matplotlib's rotate-then-align box semantics; other angles rotate in browser and SVG output only (native PNG draws them horizontally) |
| `from xy.pyplot import FacetGrid` (seaborn-shaped) | Row/column small multiples with seaborn's `map` contract (subset → activate panel → call the pyplot function), shared domains, edge-only axis labels, top-row column titles, and `margin_titles=True` rotated row titles. `hue=`/`palette=`, `col_wrap=`, `map_dataframe`, and `add_legend` fail loudly |
| `xlabel` / `ylabel` / `title` / `suptitle` | Suptitles are retained in HTML and multi-panel PNG/SVG. `ylabel` sits clear of the y tick labels in every renderer: the left gutter is reserved from the measured advances of the tick labels and the rotated title rather than from a fixed constant, leaving Matplotlib's `0.4 em` (5.6 px at the 10 pt/100 dpi default) title-to-tick gap — see *Measured left gutter and the rotated y-axis title* in `spec/api/styling.md` for the formula and its two documented asymmetries |
| `legend()` | `loc`, columns, title/font size/colors, frame styling, `borderpad`, `labelspacing`, `borderaxespad`, `fancybox`, `framealpha`, and `shadow` are retained across browser and static output. `loc='best'` scores the measured displayed legend box in Matplotlib location-code order using path vertices/crossings, collection offsets, and bar-rectangle overlaps. It resolves before the wire; pyplot rejects misspelled Matplotlib locations without narrowing core `xy.legend()`'s independent location vocabulary. Text-box scoring and bounded long-path sampling are documented in `spec/api/styling.md` § Legend placement |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, `set_xmargin` / `set_ymargin`, axis scales, `invert_xaxis/yaxis` | linear/log are native; symlog/logit/asinh use dependency-free monotone data transforms with inverse limit/tick semantics. Automatic linear ticks include Matplotlib's 2.5 step and use uniform decimal padding across a tick set; locations refresh as data arrives. `axes.autolimit_mode="round_numbers"` expands automatic linear limits to the first and last AutoLocator ticks after applying the configured margins. Artist `get_data()` reflects the transformed space; logit masks values at/outside (0, 1) |
| `set_major_locator` / `set_major_formatter`, `plt.NullLocator/FixedLocator/MultipleLocator/MaxNLocator/LinearLocator/LogLocator`, `plt.NullFormatter/FixedFormatter/FuncFormatter/FormatStrFormatter/StrMethodFormatter/ScalarFormatter` | xy-owned re-implementations resolved at build time against live data limits (Null/Fixed/Multiple/Linear are position-exact; MaxN/Auto port Matplotlib's `MaxNLocator._raw_ticks` — same step tables, edge extension, and offset handling — with `nbins="auto"` budgeted from the estimated plot rect like `Axis.get_tick_space()`; Log remains approximate). Third-party locator objects work if they implement `tick_values(vmin, vmax)`; minor locators/formatters are retained for round-tripping but minor ticks do not render, except that a labeled minor pair under a blanked major formatter (the centered date-label idiom) is promoted to the drawn tick set |
| `plt.dates.MonthLocator/YearLocator/DayLocator/DateFormatter` | xy-owned equivalents of the `matplotlib.dates` classes gallery scripts use; they locate and format in the engine's canonical ms-since-epoch axis unit (not Matplotlib's day floats), and `interval` approximates rrule by epoch-anchored occurrence counting |
| datetime, timedelta, and string coordinates | datetime inputs use the engine's automatic date ticks, timedeltas are bounded to elapsed seconds, and common strings use categorical ticks; the general Matplotlib units registry is intentionally out of scope. pandas datetime plotting (`series.plot(ax=ax)`) works against that contract: `get_{x,y}data(orig=False)` returns ms-since-epoch floats, and pandas' period-ordinal tickers (`TimeSeries_Date*`) are accepted as no-ops so the native date ticks keep rendering |
| `xticks(positions, labels, rotation=)` / `tick_params(labelrotation=)` | Exact positions and strings render in browser, PNG, and SVG |
| `twinx()`, `secondary_xaxis()`, `secondary_yaxis()` | second data axes and linked tick-only secondary axes with callable forward/inverse conversions. Secondary-axis ticks are evenly spaced conversions of the primary domain (not Matplotlib's secondary-unit locators) and currently reach the interactive HTML client only — PNG/SVG export does not draw them yet |
| `fig, ax = plt.subplots()`; `plt.subplots(n, m, figsize=, dpi=, squeeze=, sharex=, sharey=)` | Grid renders as CSS-grid HTML and stitched PNG/SVG; shared axes use common domains and live linked pan/zoom. `Figure.subplots_adjust(left=, right=, top=, bottom=, wspace=, hspace=)` moves the SubplotParams frame: the grid resolves to explicit figure rectangles and every exporter (HTML, PNG, SVG) positions panels at those rectangles |
| `Axes.get_position(original=False)` and the rendered axes frame | Supported subplot and free-form axes report their live figure rectangle and render on it. `original=True` returns the allocated rectangle before an adjustable-box aspect correction; the default applies the correction and its anchor, matching Matplotlib. Grid cells resolve under the live SubplotParams (`wspace`/`hspace`, width/height ratios), while explicit `add_axes`/`set_position` rectangles take precedence until a later layout adjustment. Titles, top-side x axes (`matshow`), and secondary-y gutters grow the surrounding allocation instead of moving the frame. **Known exception:** an axes carrying a colorbar keeps label-aware margins because xy and Matplotlib currently reserve the colorbar strip through different layout paths |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` | |
| `plt.subplot_mosaic([['A','B'],['C','C']])` / `Figure.subplot_mosaic` | Row sequences (a list of equal-length label strings, or nested label lists) resolve to a uniform grid; each distinct label, in first-appearance order, binds to the next cell, returning `(fig, {label: Axes})` with `figsize=`/`dpi=` sizing the figure. Repeated labels do not span and `'.'` does not blank a cell — the grid keeps one axes per cell — and Matplotlib's single-string forms (`'AB;CC'`, newline-separated blocks) are not parsed into rows |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | Browser-free PNG/SVG supports both single and multi-panel figures; file-like targets require an explicit `format=` and unsupported metadata/layout/export formats fail loudly |
| `plt.show()` | notebooks: inline HTML display; scripts: opens the default browser |
| Artists: `set_data` / `set_ydata` / `set_color` / `set_label` / `set_linewidth` / `remove` | mutating a handle rebuilds the chart on next render. Scatter collections additionally vectorize facecolors, edgecolors, alpha, linewidths, and sizes; `alpha=None` restores intrinsic paint alpha |
| Colors | single letters, `C0`–`C9`, `tab:*`, gray `'0.5'`, RGB(A) tuples, `(color, alpha)` pairs, per-item RGB(A) arrays, and any CSS color |
| `plt.cm.*` / `plt.colormaps[...]` / `cmap=` names | viridis, plasma, inferno, magma, cividis, gray, bone, autumn, winter, turbo, coolwarm, Blues, Purples, Reds, PuBu, BuPu, RdBu, RdYlGn, RdGy, PiYG, PRGn, jet, rainbow, Spectral, binary, aliases, and true `*_r` reversal resolved generically for every listed name, including `plt.cm.<name>_r` attribute access (RdGy/jet/Reds/bone/autumn/winter/BuPu render from 11-stop anchor tables sampled from Matplotlib 3.11, linearly interpolated) |
| `LinearSegmentedColormap.from_list` / `ListedColormap` | Python-side callables (`cmap(np.arange(cmap.N))` → RGBA) for scripts that colormap values themselves; they cannot be passed as `cmap=` to plotting calls (no engine table), which fails loudly |
| `plt.colorbar()` / `fig.colorbar()` / `plt.clim()` / `plt.gci()` | Returns a live handle (`set_label`, `set_ticks`); with no mappable it uses the current image the way pyplot does. `ticks=`/`extend=` render in PNG and SVG (the HTML colorbar stays a minimal gradient without tick text); `clim` retargets the mappable's color window and any colorbar derived from it |
| `Colorbar.set_label(...)` / `colorbar(label=...)` | Matplotlib's default label geometry in all three renderers: beside a vertical bar rotated 90° counter-clockwise and centered on it, or upright and centered below a horizontal bar. The vertical label is a quarter turn, which the native PNG rasterizer renders exactly (only arbitrary text angles fall back to upright glyphs there), and the reserved right-margin room contains its cross-axis glyph extent. `set_label` ignores Matplotlib's customization kwargs (`loc=`, `labelpad=`, `rotation=`, font properties) rather than failing — the default orientation is derived from the bar |
| `rcParams` | Figure size/DPI, line width/marker size, image cmap/origin, axes color cycle, and all four `axes.spines.*` switches affect every exporter. Pyplot axes default to Matplotlib's four-sided box and each spine can be hidden independently. The chrome keys (axes face/edge/label/title styles, font family/size, tick colors/sizes, legend defaults, figure facecolor) reach the HTML renderer and multi-panel PNG stitching; single-chart PNG and SVG export currently render their own fixed chrome and ignore most of them. `axes.titleweight` and `axes.labelweight` are supported and verified to reach all three renderers (browser, single-chart SVG, single-chart native PNG); both default to `normal`, matching Matplotlib. Unknown keys warn once |
| Text weight | Title, axis-label, tick-label, legend, legend-title, colorbar-title, and annotation text all default to normal (400) weight in every renderer, matching Matplotlib's `axes.titleweight`/`axes.labelweight`/`font.weight` defaults. Heavier text needs an explicit `fontweight=`, `label_font_weight`, `styles[slot]`, or rcParam. Native PNG approximates: the bounded font atlas holds one regular and one bold face, so weights `>= 600` render bold and everything lighter renders regular — intermediate weights are not distinguishable in native PNG, while browser and SVG output pass the requested weight through verbatim. See [styling § Chrome text weight](../api/styling.md#chrome-text-weight) |
| `plt.style.use(...)` / `plt.style.context(...)` | `"default"`, `"xy"`, bounded rcParam dictionaries, ordered lists, and the stock sheets fivethirtyeight, ggplot, bmh, dark_background, grayscale, seaborn-v0_8-white(grid), seaborn-v0_8-darkgrid, and seaborn-v0_8-deep — reduced to the supported rcParams subset (colors, grid, cycle, line width, font size; per-sheet keys outside that subset are not carried). The darkgrid sheet mirrors seaborn's `axes_style` (including `patch.edgecolor: white` + `patch.force_edgecolor`, which give hist/bar patches their white separators); `-deep` installs seaborn's classic color cycle. `context()` snapshots and restores. Unknown sheet names fail precisely |
| `plt.GridSpec(r, c, wspace=, hspace=, width_ratios=)` + slice specs | Spans (`grid[0, 1:]`, `grid[:-1, 0]`) and custom spacing resolve to explicit figure rectangles using Matplotlib's SubplotParams frame; default-geometry single cells keep the uniform grid. Spanning layouts position exactly in HTML, PNG, and SVG: free-form panels (including `add_axes` rects and insets) render absolutely at their figure rectangles in every exporter, with later axes stacked above earlier ones |
| `add_subplot(spec, sharex=, sharey=, xticklabels=[], ...)` | per-axes sharing aliases the axis-property store (static domains, as `twiny` does), not Matplotlib's live Grouper; `get_shared_x_axes()` reflects it |

## Outside 2-D chart-method compatibility

Polar/3D projections, `FuncAnimation`, arbitrary third-party Artist graphs,
non-affine transform graphs, and blitting are not part of this 2-D chart-method
target. Bounded shim-owned `Axes` Artist views, children, containers, removal,
affine data transforms, coordinate spaces, and linked secondary axes are
supported.

Unknown keyword arguments on supported calls raise `TypeError` naming the
offending keyword. Known material options that the native marks cannot honor
raise `NotImplementedError`, with these documented exceptions that are accepted
as visual approximations rather than rejected: imshow smoothing collapse above,
`annotate(arrowprops=...)` connection curves and
fancy/wedge outlines drawn as quadratic-curve tapered fills rather than
Matplotlib's exact patch paths, `bbox=` boxes sized from an estimated text
width with a fixed corner radius per box style (5 px for `round`, 8 px for
`round4`) rather than Matplotlib's `pad × fontsize` box path — measured
against Matplotlib 3.11.1 at 10 pt, `round` is 4.17 px there against 5 px
here — and errorbar limit flags rendered as one-sided bars without
Matplotlib's caret arrows.

## Sharp edges

- Custom Matplotlib marker paths, arbitrary clipping graphs, and unsupported
  collection gradients are rejected rather than silently approximated.
- The shim's figure/axes bookkeeping adds ~50µs of fixed per-figure cost over
  the declarative API (measured 2026-07-14, M-series: +60% at 10k points, +26%
  at 100k — fixed cost over an ~85µs baseline, not O(n) work).
  `tests/pyplot/test_perf_guardrail.py` gates the relationship at 10k and 100k
  with generous headroom (1.6x and 1.5x ceilings plus a 100µs absolute
  allowance for CI timer jitter), to catch structural regressions rather than
  to re-measure the margin.

## Boundaries (enforced by `tests/pyplot/test_boundaries.py`)

The shim lives entirely in `python/xy/pyplot/`; no engine module
imports it, importing `xy` never loads it, and importing the shim
never loads the widget stack or real matplotlib.

## Maintenance

The upstream revision and method inventory are updated together. When moving
the pin, check out the proposed Matplotlib revision and run:

```console
python scripts/sync_matplotlib_compat.py --upstream path/to/matplotlib --update-snapshot
python scripts/sync_matplotlib_compat.py
```

Review the snapshot and generated matrix diff as an API change. Release-level
changes are recorded in [the compatibility changelog](compat-changelog.md).
