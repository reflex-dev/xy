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
| `scatter(x, y, s=, c=, cmap=, vmin=, vmax=, alpha=, marker=, edgecolors=, facecolors=, plotnonfinite=)` | `s` (pt², area) maps to pixel diameter; `facecolors=`/`facecolor=` is the fallback face paint when `c` is absent (`facecolors="none"` draws hollow markers, as `c="none"` does); numeric 1-D `c` remains a colormap encoding, while `N×3`/`N×4` face and edge colors, alpha arrays, sizes, and linewidth arrays stay in one collection. Explicit alpha replaces intrinsic RGBA alpha, matching Matplotlib; custom norms/marker paths fail loudly |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories (also with `xerr=`/`yerr=`: the error-bar centres autoscale on the category axis), `tick_label=` on numeric positions (one labeled tick per bar, at the positions the caller passed — `align="edge"` offsets the bar geometry, never the ticks; with string categories it fails loudly), `log=True` (value axis on a log scale), stacking bases, per-bar face/edge color-alpha pairs and linewidths, plus iterable/indexable `BarContainer.patches` views whose setters mutate the parent batched trace and whose `get_x`/`get_y`/`get_width`/`get_height`/`get_xy`/`get_center`/`get_bbox` report Matplotlib's rectangle geometry in data space (category positions resolve to 0, 1, 2, ...), so the `ax.text(r.get_x() + r.get_width() / 2, r.get_height(), ...)` labeling idiom works |
| `hist(bins=, range=, density=, cumulative=, weights=, orientation=, stacked=, bottom=, align=, log=)` | Returns computed counts/edges (raw counts even with `bottom=`); `bottom=` lifts the baseline (scalar or per bin) and seeds the stack, `align="left"`/`"right"` centre bars on the bin edges (step histtypes accept only `"mid"` and fail loudly otherwise), `log=True` puts the count axis on a log scale; stacked density normalizes the combined weighted area once (including unequal bins and either cumulative direction), matching Matplotlib 3.11; bar, step, and stepfilled families render in both vertical and horizontal orientations; unfilled step outlines connect their top envelope to zero or the previous stack at both endpoints |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel. `hist2d` delegates rendering to the pseudocolor-mesh path for both uniform and non-uniform bins, supports linear and logarithmic normalization, defaults to fully opaque cells, and retains the original count domain for logarithmic mappables. Its view limits are the outer bin edges with no margin, matching Matplotlib's sticky mesh edges. Arbitrary custom normalization and `colorizer` remain unsupported. Hexbin uses Matplotlib's two-offset-grid nearest-center assignment and six-triangle data-space cells, supports `C`, arbitrary scalar reducers, and `mincnt`, and retains only the bounded lattice rather than source points. `ecdf` carries the ordinary margin on the sample axis and is sticky at 0 and 1 on the cumulative axis |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Boxplots support notches, bootstrap/user confidence intervals, median overrides (drawn median only; notch CIs stay data-derived like Matplotlib), percentile/custom whiskers, cap widths, `sym`, dashed line-component styles, and component colors/widths/alpha. Default boxes are unfilled outlines and return Matplotlib-shaped per-group component handles (two whiskers/caps and one box/median/flier handle per group). `patch_artist=True` emits mutable filled polygon boxes; statistics labels become category tick labels, while scalar or per-box legend labels bind to boxes for patch plots and medians otherwise. Violins use Gaussian KDE for the default Scott bandwidth and explicit Scott/Silverman/scalar/callable bandwidths, return one seam-free mutable body per group, cycle face and line color sequences, preserve color-alpha pairs, and support quantiles and low/high sides. `boxplot` autoscales its value axis over the Tukey whiskers plus, when `showfliers` is on, the flier points. Its default category positions are 1-based and `manage_ticks=True` reserves half a unit around the outer positions, matching Matplotlib |
| `errorbar(capsize=, capthick=, ecolor=, elinewidth=, fmt=, mfc=, mec=, mew=, ...)` | `capthick` sets the cap stroke (default `lines.markeredgewidth`, as Matplotlib); `markerfacecolor`/`markeredgecolor`/`markeredgewidth` and their `mfc`/`mec`/`mew` aliases style the data markers; `barsabove` and `elinestyle` fail loudly |
| `fill_between(x, y1, y2, where=, step=)` / `fill_betweenx` | Masks are split into finite contiguous polygons; step geometry is expanded exactly. Datetime-like `x` (`fill_betweenx`: `y`) — `datetime`, `date`, `datetime64`, pandas `Timestamp` — takes the same ms-since-epoch conversion `plot()` uses, and the axis stays a date axis even when the fill is the only artist (`fill_between` stores its polygons' x back as `datetime64[ms]`; `fill_betweenx` pins the y axis kind to `time`) |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `psd`, `csd`, `cohere`, `specgram` | Native real-valued Hann-windowed Welch spectra use Matplotlib 3.11's default `detrend_none` semantics. Callable windows/detrending, independent `pad_to`, explicit sides/frequency scaling, and complex/two-sided inputs remain unsupported and fail loudly instead of silently changing the signal; completing these is tracked acceptance debt for `statistics/psd_demo.py` |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | `imshow` defaults to `rcParams['image.origin']`; nearest stays cell-exact, while named smoothing modes use dependency-free per-kernel approximations over a bounded 512–1024 px intermediate for both scalar and RGB(A) data. Filter choice and intermediate size do not yet depend on final display resolution, and explicit `interpolation="auto"` remains unsupported. Unsupported stages/transforms fail loudly. Uniform meshes retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion. Both hug their outer cell edge with no margin, as Matplotlib's sticky image/mesh edges do |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `hlines` / `vlines` | `colors` (a name, one RGB(A) tuple, or a per-line sequence whose first entry wins), `linestyles` and Matplotlib's singular `linestyle`/`ls` spelling (dashes are data-space sub-segments), `linewidth(s)`, `alpha`, `label`, `data`, `transform` |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels; automatic labels repeat at bounded, separated positions along each level (line knockout for `inline=True` remains a visual approximation) |
| `quiver`, `barbs`, `streamplot` | Quiver supports Matplotlib's width-unit vocabulary independently from length scaling. Barbs use fixed-length staffs and Matplotlib's flag/full/half decomposition, including increments, rounding, empty glyphs, colors, sizes, flipping, and pivots. Streamplot uses a dependency-free adaptive Heun integrator with occupancy-aware seeding; `start_points`, `integration_direction`, `broken_streamlines`, integration step/error scales, array widths/colors, and `num_arrows` are honored |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels), including dtype-preserving value formats, radial label rotation/alignment, and common text properties |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Fractional span bounds plus data/axes/figure text coordinates are supported; `text(alpha=)` dims the label the way `Text.set_alpha` does. Rules and spans autoscale exactly as Matplotlib's `dataLim` does: their finite data coordinate extends the axis they are positioned on (an `axhline` widens y, an `axvspan` widens x) and their infinite extent and fractional bounds never touch the perpendicular axis; a NaN position contributes nothing. Those limits reach every exporter: because the engine autoscales from its traces alone and rules/bands are annotations, an axis a rule or span widens ships the autoscaled limits (`get_xlim()`/`get_ylim()`, margins included) as its exact `domain` instead of the engine's `margin`; span-free axes keep the engine's margin-based autoscale byte for byte. `label=` names the artist for the legend and draws no text (Matplotlib draws none either): `get_legend_handles_labels()` lists rules as `Line2D` and spans as patch artists in artist order, and `legend()` ships those rows as explicit legend items — a line sample carrying the rule's color/width/dash, a filled swatch carrying the span's color/alpha — because annotations are not traces the renderers could name. `annotate(arrowprops=)` draws real arrows in every output: offset-point text becomes an engine callout (arrow pinned from label to point across zoom), data-coordinate text an arrow annotation; date-string coordinates convert on datetime axes. Arrowstyles map to head/tail shapes (`->` open V, `-\|>` filled, `\|-\|`/brackets bar caps, `fancy`/`simple`/`wedge` filled tapered shafts sized by the text's mutation scale) and `connectionstyle` arc3/angle3/angle become quadratic curves (corner rounding approximated); `alpha` dims the arrow only. `bbox=` becomes label box styles (fill/edge/round corners/`pad`) in browser and static exports; its `alpha` is the *patch* alpha and dims face and edge together, as Matplotlib's element `opacity` does, and `boxstyle="round"`/`round4` corners are rounded in SVG (`rx`) and native PNG as well as in the browser. An arrow-less `text`/`annotate` label is painted with `rcParams["text.color"]` in all three renderers rather than each renderer's own annotation-label default. Text is unclipped like Matplotlib (`clip_on=False`), and axes-fraction text right of the axes box (x > 1, e.g. seaborn-style row titles) reserves right margin in every exporter. `rotation=90/270` renders vertical text in browser, PNG, and SVG with Matplotlib's rotate-then-align box semantics; other angles rotate in browser and SVG output only (native PNG draws them horizontally). Before/after for span autoscale and legend rows: `spec/assets/pyplot-span-autoscale-before-after.png` |
| `from xy.pyplot import FacetGrid` (seaborn-shaped) | Row/column small multiples with seaborn's `map` contract (subset → activate panel → call the pyplot function), shared domains, edge-only axis labels, top-row column titles, and `margin_titles=True` rotated row titles. `hue=`/`palette=`, `col_wrap=`, `map_dataframe`, and `add_legend` fail loudly |
| `xlabel` / `ylabel` / `title` / `suptitle` | Suptitles are retained in HTML and multi-panel PNG/SVG. `ylabel` sits clear of the y tick labels in every renderer: the left gutter is reserved from the measured advances of the tick labels and the rotated title rather than from a fixed constant, leaving Matplotlib's `0.4 em` (5.6 px at the 10 pt/100 dpi default) title-to-tick gap — see *Measured left gutter and the rotated y-axis title* in `spec/api/styling.md` for the formula and its two documented asymmetries |
| `legend()` | Call forms `legend()`, `legend(labels)`, `legend(handles, labels)`, and the keyword spellings `legend(handles=, labels=)`, `legend(handles=)` (labels read off the handles, underscore labels included, as Matplotlib does) and `legend(labels=)`. `loc` accepts Matplotlib's names, its integer codes 0–10 (`Legend.codes`: 0 best, 1 upper right, ... 10 center), and an `(x, y)` axes-fraction tuple that anchors the legend's lower-left corner there. Proxy handles work: `plt.Line2D([0], [0], color=, linestyle=, linewidth=, marker=, markersize=, mfc=, mec=, mew=, alpha=, label=)`, `plt.Patch(facecolor=, edgecolor=, linewidth=, alpha=, hatch=, fill=, label=)`, and `plt.Rectangle((x, y), w, h, **patch style)` (also accepted by `add_patch`) own no axes and freeze into swatches through the same path as plotted artists (dashes and marker sizes are scaled from points at the owning figure's DPI). `loc`, columns, title/font size/colors, frame styling, `borderpad`, `labelspacing`, `borderaxespad`, `fancybox`, `framealpha`, and `shadow` are retained across browser and static output. `loc='best'` scores the measured displayed legend box in Matplotlib location-code order using path vertices/crossings, collection offsets, and bar-rectangle overlaps. It resolves before the wire; pyplot rejects misspelled Matplotlib locations without narrowing core `xy.legend()`'s independent location vocabulary. Text-box scoring and bounded long-path sampling are documented in `spec/api/styling.md` § Legend placement |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, `set_xmargin` / `set_ymargin`, axis scales, `invert_xaxis/yaxis` | linear/log are native; symlog/logit/asinh use dependency-free monotone data transforms with inverse limit/tick semantics. Automatic linear ticks include Matplotlib's 2.5 step and use uniform decimal padding across a tick set; locations refresh as data arrives. `axes.autolimit_mode="round_numbers"` expands automatic linear limits to the first and last AutoLocator ticks after applying the configured margins. Artist `get_data()` reflects the transformed space; logit masks values at/outside (0, 1). `set_xlim`/`set_ylim` (and `plt.xlim`/`plt.ylim`) and `set_xticks`/`set_yticks` accept every datetime-like `plot()` accepts — `datetime`, `date`, `datetime64`, pandas `Timestamp`, and date strings on a datetime axis — converting them to the engine's ms-since-epoch floats, which is also what `get_xlim()`/`get_xticks()` report on a date axis (not Matplotlib's day floats). Datetime ticks also pin the axis kind to `time`, so ticks authored before any datetime artist (or with none at all) label as dates rather than epoch milliseconds |
| `set_major_locator` / `set_major_formatter`, `plt.NullLocator/FixedLocator/MultipleLocator/MaxNLocator/LinearLocator/LogLocator`, `plt.NullFormatter/FixedFormatter/FuncFormatter/FormatStrFormatter/StrMethodFormatter/ScalarFormatter` | xy-owned re-implementations resolved at build time against live data limits (Null/Fixed/Multiple/Linear are position-exact; MaxN/Auto port Matplotlib's `MaxNLocator._raw_ticks` — same step tables, edge extension, and offset handling — with `nbins="auto"` budgeted from the estimated plot rect like `Axis.get_tick_space()`; Log remains approximate). Third-party locator objects work if they implement `tick_values(vmin, vmax)`; one whose `tick_values` raises `NotImplementedError` (Matplotlib's abstract `Locator` base) is called through Matplotlib's own `__call__` protocol when it is bound to an axis, and otherwise dropped so the axis keeps its kind's default ticks (a date axis keeps its date ticks) instead of failing the build. Minor locators/formatters are retained for round-tripping but minor ticks do not render, except that a labeled minor pair under a blanked major formatter (the centered date-label idiom) is promoted to the drawn tick set. `ticklabel_format(axis=, style=, scilimits=, useOffset=, useMathText=)` configures the axis `ScalarFormatter` exactly as Matplotlib does (installing one when no formatter is set; any other installed formatter raises `AttributeError`): `style="plain"` labels the located ticks with the shared decimal count Matplotlib's `_set_format` derives from the tick spacing, and `style="sci"` switches to mantissas once the ticks' order of magnitude leaves `scilimits` (default `(-5, 6)`, Matplotlib's `axes.formatter.limits`). **Compat-noop:** the shim has no offset-text slot, so `useOffset` never factors an offset out — labels always carry the full value — and the scientific exponent is written on every label (`1.25e6`, or `1.25×10⁶` under `useMathText=True`) rather than once beside the axis. Exponents are clamped to ±300 and labels are limited to 20 decimals (a double carries ~16 significant digits) so extreme axes (`1e300`, `1e-300`) export instead of overflowing; a tick set that would need more decimals falls back to `%g` (`1e-300`) rather than printing value-less zeros. `useLocale=True` raises |
| `plt.dates.MonthLocator/YearLocator/DayLocator/DateFormatter` | xy-owned equivalents of the `matplotlib.dates` classes gallery scripts use; they locate and format in the engine's canonical ms-since-epoch axis unit (not Matplotlib's day floats), and `interval` approximates rrule by epoch-anchored occurrence counting |
| datetime, timedelta, and string coordinates | datetime inputs use the engine's automatic date ticks, timedeltas are bounded to elapsed seconds, and common strings use categorical ticks; the general Matplotlib units registry is intentionally out of scope. pandas datetime plotting (`series.plot(ax=ax)`) works against that contract: `get_{x,y}data(orig=False)` returns ms-since-epoch floats, and pandas' period-ordinal tickers (`TimeSeries_Date*`) are accepted as no-ops on both the major and the minor tier so the native date ticks keep rendering (pandas 3.0.5's minor `TimeSeries_DateLocator` has no `tick_values`; see the locator row above for the general fallback) |
| `xticks(positions, labels, rotation=)` / `tick_params(labelrotation=)` | Exact positions and strings render in browser, PNG, and SVG. The stateful `plt.tick_params`, `plt.margins`, and `plt.locator_params` delegate to the current axes like every other `plt.*` wrapper |
| `twinx()`, `secondary_xaxis()`, `secondary_yaxis()` | second data axes and linked tick-only secondary axes with callable forward/inverse conversions. Secondary-axis ticks are evenly spaced conversions of the primary domain (not Matplotlib's secondary-unit locators) and currently reach the interactive HTML client only — PNG/SVG export does not draw them yet |
| `fig, ax = plt.subplots()`; `plt.subplots(n, m, figsize=, dpi=, squeeze=, sharex=, sharey=)` | Grid renders as CSS-grid HTML and stitched PNG/SVG; shared axes use common domains and live linked pan/zoom. `Figure.subplots_adjust(left=, right=, top=, bottom=, wspace=, hspace=)` moves the SubplotParams frame: the grid resolves to explicit figure rectangles and every exporter (HTML, PNG, SVG) positions panels at those rectangles |
| `subplot(projection="polar")`; `add_subplot(..., polar=True)`; `axes(projection="polar")`; `subplots(subplot_kw={"projection": "polar"})` | Ordinary `plot`, `scatter`, `fill`, `bar`, heatmap/image, contour, and error-bar calls render through the core polar coordinate system in HTML, PNG, and SVG. The PolarAxes controls `set_theta_zero_location`, `set_theta_direction`, `set_theta_offset`, `set_thetagrids`, `set_thetamin`/`set_thetamax` (degrees), `set_rlim`, `set_rticks`, `set_rorigin`, and their theta/r limit accessors route into the same angular/radial axes. Categorical θ and log/symlog radial scales use that core transform as well. Polar `axhline`/`axvline` and span geometry, LOD, facets/animation, angular navigation/selection, and the stateful `plt.polar`/`plt.thetagrids`/`plt.rgrids` convenience wrappers remain outside this surface and fail or remain absent rather than drawing a Cartesian approximation. **Silently dropped on a polar Axes:** minor ticks and their style (`minorticks_on`, `minor` `tick_params`, `set_minor_locator`), tick-label horizontal alignment (`tick_params(ha=)`), and the tick-label collision strategies — no renderer draws minor rings or spokes, and rim labels have no edge-relative collision pass or anchor (`spec/design/polar-axes.md` §9). They are dropped rather than refused because every Axes carries an rcParam-derived `minor_style`, so refusing would break the projection over a default nobody authored; a hand-authored `xy.theta_axis`/`xy.r_axis` refuses them instead. |
| `Axes.get_position(original=False)` and the rendered axes frame | Supported subplot and free-form axes report their live figure rectangle and render on it. `original=True` returns the allocated rectangle before an adjustable-box aspect correction; the default applies the correction and its anchor, matching Matplotlib. Grid cells resolve under the live SubplotParams (`wspace`/`hspace`, width/height ratios), while explicit `add_axes`/`set_position` rectangles take precedence until a later layout adjustment. Titles, top-side x axes (`matshow`), and secondary-y gutters grow the surrounding allocation instead of moving the frame. **Known exception:** an axes carrying a colorbar keeps label-aware margins because xy and Matplotlib currently reserve the colorbar strip through different layout paths |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` / `plt.subplot(n, m, i)` | A numbered cell of a multi-cell grid creates *only* that cell, positioned at its GridSpec rectangle under the live SubplotParams: `subplot(221); plot(); subplot(224); plot()` leaves two axes and two blank cells, and grids of different shapes share one figure (`subplot(2, 2, 1)`, `subplot(2, 2, 2)`, `subplot(2, 1, 2)`) as long as their cells do not overlap — Matplotlib's semantics. `plt.subplot()` returns the existing axes for a cell created before; `Figure.add_subplot()` always adds a new one. Only the whole-figure `111` keeps the uniform single-chart path, and `num` outside `1..n*m` raises Matplotlib's `ValueError`. Before/after: `spec/assets/pyplot-subplot-cells-before-after.png` |
| `plt.subplot_mosaic([['A','B'],['C','C']])` / `Figure.subplot_mosaic` | Row sequences (a list of equal-length label strings, or nested label lists) resolve to a uniform grid; each distinct label, in first-appearance order, binds to the next cell, returning `(fig, {label: Axes})` with `figsize=`/`dpi=` sizing the figure. Repeated labels do not span and `'.'` does not blank a cell — the grid keeps one axes per cell — and Matplotlib's single-string forms (`'AB;CC'`, newline-separated blocks) are not parsed into rows |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | Browser-free PNG/SVG supports both single and multi-panel figures; file-like targets require an explicit `format=` and unsupported metadata/layout/export formats fail loudly |
| `plt.show()` | notebooks: inline HTML display; scripts: opens the default browser |
| Artists: `set_data` / `set_ydata` / `set_color` / `set_label` / `set_linewidth` / `remove` | mutating a handle rebuilds the chart on next render. Scatter collections additionally vectorize facecolors, edgecolors, alpha, linewidths, and sizes; `alpha=None` restores intrinsic paint alpha |
| Colors | single letters, `C0`–`C9`, `tab:*`, gray `'0.5'`, RGB(A) tuples, `(color, alpha)` pairs, per-item RGB(A) arrays, and any CSS color |
| `plt.cm.*` / `plt.colormaps[...]` / `plt.get_cmap` / `cmap=` names | `plt.cm.<name>` and `plt.get_cmap(name, lut=)` return callable colormap objects with `.N` (`lut` resamples: qualitative palettes sample `lut` evenly spaced positions like Matplotlib's `ListedColormap.resampled`) (`plt.cm.viridis(np.linspace(0, 1, 3))` → RGBA rows) that plotting calls accept as `cmap=`; Matplotlib's qualitative palettes tab10, tab20, tab20b, tab20c, Set1–3, Paired, Accent, Dark2, Pastel1, Pastel2 (and their `_r`) come back as callable `ListedColormap`s — indexable by integer or fraction, but not passable as `cmap=` (no engine table; fails loudly). Engine colormaps: viridis, plasma, inferno, magma, cividis, gray, bone, autumn, winter, turbo, coolwarm, Blues, Purples, Reds, PuBu, BuPu, RdBu, RdYlGn, RdGy, PiYG, PRGn, jet, rainbow, Spectral, binary, aliases, and true `*_r` reversal resolved generically for every listed name, including `plt.cm.<name>_r` attribute access (RdGy/jet/Reds/bone/autumn/winter/BuPu render from 11-stop anchor tables sampled from Matplotlib 3.11, linearly interpolated) |
| `LinearSegmentedColormap.from_list` / `ListedColormap` | Python-side callables (`cmap(np.arange(cmap.N))` → RGBA) for scripts that colormap values themselves; they cannot be passed as `cmap=` to plotting calls (no engine table), which fails loudly |
| `plt.colorbar()` / `fig.colorbar()` / `plt.clim()` / `plt.gci()` | Returns a live handle (`set_label`, `set_ticks`); `fraction=` is an accepted no-op (the colorbar strip has a fixed width); with no mappable it uses the current image the way pyplot does. `ticks=`/`extend=` render in PNG and SVG (the HTML colorbar stays a minimal gradient without tick text); `clim` retargets the mappable's color window and any colorbar derived from it |
| `Colorbar.set_label(...)` / `colorbar(label=...)` | Matplotlib's default label geometry in all three renderers: beside a vertical bar rotated 90° counter-clockwise and centered on it, or upright and centered below a horizontal bar. The vertical label is a quarter turn, which the native PNG rasterizer renders exactly (only arbitrary text angles fall back to upright glyphs there), and the reserved right-margin room contains its cross-axis glyph extent. `set_label` ignores Matplotlib's customization kwargs (`loc=`, `labelpad=`, `rotation=`, font properties) rather than failing — the default orientation is derived from the bar |
| `rcParams` | Figure size/DPI, line width/marker size, image cmap/origin, axes color cycle, and all four `axes.spines.*` switches affect every exporter. Pyplot axes default to Matplotlib's four-sided box and each spine can be hidden independently. The chrome keys (axes face/edge/label/title styles, font family/size, tick colors/sizes, legend defaults, figure facecolor) reach the HTML renderer and multi-panel PNG stitching; single-chart PNG and SVG export currently render their own fixed chrome and ignore most of them. `axes.titleweight` and `axes.labelweight` are supported and verified to reach all three renderers (browser, single-chart SVG, single-chart native PNG); both default to `normal`, matching Matplotlib. Unknown keys warn once |
| Text weight | Title, axis-label, tick-label, legend, legend-title, colorbar-title, and annotation text all default to normal (400) weight in every renderer, matching Matplotlib's `axes.titleweight`/`axes.labelweight`/`font.weight` defaults. Heavier text needs an explicit `fontweight=`, `label_font_weight`, `styles[slot]`, or rcParam. Native PNG approximates: the bounded font atlas holds one regular and one bold face, so weights `>= 600` render bold and everything lighter renders regular — intermediate weights are not distinguishable in native PNG, while browser and SVG output pass the requested weight through verbatim. See [styling § Chrome text weight](../api/styling.md#chrome-text-weight) |
| `plt.style.use(...)` / `plt.style.context(...)` | `"default"`, `"xy"`, bounded rcParam dictionaries, ordered lists, and the stock sheets fivethirtyeight, ggplot, bmh, dark_background, grayscale, seaborn-v0_8-white(grid), seaborn-v0_8-darkgrid, and seaborn-v0_8-deep — reduced to the supported rcParams subset (colors, grid, cycle, line width, font size; per-sheet keys outside that subset are not carried). The darkgrid sheet mirrors seaborn's `axes_style` (including `patch.edgecolor: white` + `patch.force_edgecolor`, which give hist/bar patches their white separators); `-deep` installs seaborn's classic color cycle. `context()` snapshots and restores. Unknown sheet names fail precisely |
| `plt.GridSpec(r, c, wspace=, hspace=, width_ratios=)` + slice specs | Spans (`grid[0, 1:]`, `grid[:-1, 0]`) and custom spacing resolve to explicit figure rectangles using Matplotlib's SubplotParams frame; default-geometry single cells keep the uniform grid. Spanning layouts position exactly in HTML, PNG, and SVG: free-form panels (including `add_axes` rects and insets) render absolutely at their figure rectangles in every exporter, with later axes stacked above earlier ones |
| `add_subplot(spec, sharex=, sharey=, xticklabels=[], ...)` | per-axes sharing aliases the axis-property store (static domains, as `twiny` does), not Matplotlib's live Grouper; `get_shared_x_axes()` reflects it |

## Outside 2-D chart-method compatibility

Three-dimensional, ternary, geographic, and custom projections,
`FuncAnimation`, arbitrary third-party Artist graphs, non-affine transform
graphs, and blitting are not part of this 2-D chart-method target. Polar is the
supported non-Cartesian projection with the boundary above. Bounded shim-owned
`Axes` Artist views, children, containers, removal, affine data transforms,
coordinate spaces, and linked secondary axes are supported.

Unknown keyword arguments on supported calls raise `TypeError` naming the
offending keyword. Matplotlib's *Artist-level* keywords are the exception:
every plotting method in the inventory (plus `grid`, `set_title`,
`set_xlabel`, `set_ylabel`) accepts `zorder`, `clip_on`, `clip_box`,
`rasterized`, `antialiased`/`aa`, `snap`, `gid`, `url`, `picker`, `pickradius`,
`in_layout`, `agg_filter`, `sketch_params`, `path_effects`, `mouseover`, and
`animated` as **accepted no-ops** (`ARTIST_NOOP_KWARGS` in `_translate.py`): the
engine has no draw-order override, clipping policy, hit-testing metadata, or
renderer filters for a single mark, so they are ignored rather than rejected
when a script carries them for the real renderer. `visible=False` is not a
no-op — it hides every artist the call returns (`set_visible(False)`,
which on a `Line2D` also hides its marker overlay), and on `set_title` /
`set_xlabel` / `set_ylabel` it clears the chrome text (`get_title()` then
returns `""`; the shim has no hidden-text state). Legend proxies accept
`visible=` too.
Methods that implement one of those names themselves keep it: `annotate` and
`clabel` order by `zorder`, `pcolormesh`/`pcolor`/`pcolorfast` record
`rasterized` on their handle, and `imshow` honors `clip_on`. The setters keep
their stricter contracts (`set_clip_on(False)`, `set_rasterized(True)`, and
`set_zorder` on a plotted handle still raise or reorder as before). Known material options that the native marks cannot honor
raise `NotImplementedError`, with these documented exceptions that are accepted
as visual approximations rather than rejected: imshow smoothing collapse above,
`annotate(arrowprops=...)` connection curves and
fancy/wedge outlines drawn as quadratic-curve tapered fills rather than
Matplotlib's exact patch paths, `bbox=` boxes sized from an estimated text
width with a fixed corner radius per box style (5 px for `round`, 8 px for
`round4`) rather than Matplotlib's `pad × fontsize` box path — measured
against Matplotlib 3.11.1 at 10 pt, `round` is 4.17 px there against 5 px
here — errorbar limit flags rendered as one-sided bars without
Matplotlib's caret arrows, and `add_patch` geometry flattened through
`Path.to_polygons`, which resolves a curved patch into straight segments
rather than an exact analytic curve. Matplotlib's renderers flatten in display
space at draw time; xy builds patch geometry when the patch is added, before
the view is known, so it flattens as though the patch filled the figure — the
finest resolution the patch could need, which holds the error near 1e-4 of the
patch's own size whatever units it is drawn in. That resolution is fixed at
the figure size in effect when the patch is added: enlarging the figure or
its DPI afterwards, or zooming deep into a curve, reuses the tessellation
rather than re-flattening. Rings of one compound path that overlap without
nesting fill ring-by-ring — their union, where Matplotlib's even-odd rule
leaves the intersection unpainted. Two cases `add_patch` declines
rather than approximates: a patch whose path has nested rings draws its
outlines and skips the fill, since hole support is not implemented and filling
every ring would paint the hole solid; and a ring that is self-intersecting or
past the triangulator's 10,000-vertex cap draws its outline and warns.

## Sharp edges

- Custom Matplotlib marker paths, arbitrary clipping graphs, and unsupported
  collection gradients are rejected rather than silently approximated.
- The shim's figure/axes bookkeeping adds ~50µs of fixed per-figure cost over
  the declarative API (measured 2026-07-14, M-series: +60% at 10k points, +26%
  at 100k — fixed cost over an ~85µs baseline, not O(n) work).
  CodSpeed's paired raw/pyplot arms track that relationship at 10k, 100k, and
  1M points. Blocking pytest tests enforce the underlying cache and
  no-materialization invariants without relying on sub-millisecond wall-clock
  comparisons on shared CI runners.

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
