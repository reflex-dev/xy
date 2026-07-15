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
[`matplotlib_311_plotting.json`](../tests/pyplot/matplotlib_311_plotting.json)
snapshot locks that inventory to the pinned upstream documentation, while the executable compatibility
corpus in [`tests/pyplot/corpus/`](../tests/pyplot/corpus/) covers representative
calls from every family. This is 100% 2-D *chart-method* coverage; it is not a
claim to reproduce Matplotlib's renderer, transforms, or full Artist graph.

The generated [method-by-method compatibility matrix](matplotlib-compat-matrix.md)
is sourced from that snapshot, executable corpus calls, and
[`compatibility.json`](../tests/pyplot/compatibility.json). CI fails if the
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
| `scatter(x, y, s=, c=, cmap=, vmin=, vmax=, alpha=, marker=, edgecolors=, plotnonfinite=)` | `s` (pt², area) maps to pixel diameter; array `c` becomes a color encoding and explicit paired color bounds are retained; custom norms/marker paths fail loudly |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories, stacking bases, Matplotlib 3.11 grouped-bar containers and labels |
| `hist(bins=, range=, density=, cumulative=, weights=, orientation=, stacked=)` | Returns computed counts/edges; bar, step, and stepfilled families render in both vertical and horizontal orientations |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel; hexbin uses Matplotlib's two-offset-grid nearest-center assignment and six-triangle data-space cells, supports `C`, arbitrary scalar reducers, and `mincnt`, and retains only the bounded lattice rather than source points |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Boxplots support notches, bootstrap/user confidence intervals, median overrides (drawn median only; notch CIs stay data-derived like Matplotlib), percentile/custom whiskers, cap widths, `sym`, and component colors/widths/alpha — dashed component linestyles fail loudly. Violins support Scott/Silverman/scalar/callable Gaussian-KDE bandwidths, quantiles, and low/high sides; the default (bw_method omitted) uses the native histogram violin mark, whose shape differs from the explicit KDE path |
| `fill_between(x, y1, y2, where=, step=)` / `fill_betweenx` | Masks are split into finite contiguous polygons; step geometry is expanded exactly |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | `imshow` defaults to `rcParams['image.origin']`; nearest stays cell-exact and Matplotlib's smoothing mode names all collapse to the shim's single bounded gradient upsampling (a visual approximation, not per-mode kernels) and apply to scalar data only — RGB(A) truecolor arrays render unresampled — while unsupported stages/transforms fail loudly. Uniform meshes retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels; automatic labels repeat at bounded, separated positions along each level (line knockout for `inline=True` remains a visual approximation) |
| `quiver`, `barbs`, `streamplot` | Native vector endpoint/arrowhead and bounded streamline kernels feeding one instanced segment mark. Barbs are a visual approximation: magnitude maps to a bounded tick count, not WMO 50/10/5 increments. Streamplot always uses the shim's own bounded fixed-step integrator (identical output with or without Matplotlib installed, but paths approximate Matplotlib's adaptive ones); `start_points`, `integration_direction`, array widths/colors and `num_arrows` are honored, and remaining non-default integration options fail loudly |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels) |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Fractional span bounds plus data/axes/figure text coordinates are supported. `annotate(arrowprops=)` draws real arrows in every output: offset-point text becomes an engine callout (arrow pinned from label to point across zoom), data-coordinate text an arrow annotation; date-string coordinates convert on datetime axes. Arrowstyles map to head/tail shapes (`->` open V, `-|>` filled, `\|-\|`/brackets bar caps, `fancy`/`simple`/`wedge` filled tapered shafts sized by the text's mutation scale) and `connectionstyle` arc3/angle3/angle become quadratic curves (corner rounding approximated); `alpha` dims the arrow only. `bbox=` becomes label box styles (fill/edge/round corners/`pad`) on the HTML label; static exporters keep the plain label |
| `xlabel` / `ylabel` / `title` / `suptitle` | Suptitles are retained in HTML and multi-panel PNG/SVG |
| `legend()` | `loc`, columns, title/font size/colors, frame styling, `borderpad`, `labelspacing`, `fancybox`, `framealpha`, and `shadow` are retained across browser and static output. `loc='best'` chooses the least occupied corner from bounded samples of the current data |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, axis scales, `invert_xaxis/yaxis` | linear/log are native; symlog/logit/asinh use dependency-free monotone data transforms with inverse limit/tick semantics. Automatic linear ticks include Matplotlib's 2.5 step and use uniform decimal padding across a tick set; locations refresh as data arrives. Artist `get_data()` reflects the transformed space; logit masks values at/outside (0, 1) |
| `set_major_locator` / `set_major_formatter`, `plt.NullLocator/FixedLocator/MultipleLocator/MaxNLocator/LinearLocator/LogLocator`, `plt.NullFormatter/FixedFormatter/FuncFormatter/FormatStrFormatter/StrMethodFormatter/ScalarFormatter` | xy-owned re-implementations resolved at build time against live data limits (Null/Fixed/Multiple/Linear are position-exact; MaxN/Auto port Matplotlib's `MaxNLocator._raw_ticks` — same step tables, edge extension, and offset handling — with `nbins="auto"` budgeted from the estimated plot rect like `Axis.get_tick_space()`; Log remains approximate). Third-party locator objects work if they implement `tick_values(vmin, vmax)`; minor locators/formatters are retained for round-tripping but minor ticks do not render, except that a labeled minor pair under a blanked major formatter (the centered date-label idiom) is promoted to the drawn tick set |
| `plt.dates.MonthLocator/YearLocator/DayLocator/DateFormatter` | xy-owned equivalents of the `matplotlib.dates` classes gallery scripts use; they locate and format in the engine's canonical ms-since-epoch axis unit (not Matplotlib's day floats), and `interval` approximates rrule by epoch-anchored occurrence counting |
| datetime, timedelta, and string coordinates | datetime inputs use the engine's automatic date ticks, timedeltas are bounded to elapsed seconds, and common strings use categorical ticks; the general Matplotlib units registry is intentionally out of scope. pandas datetime plotting (`series.plot(ax=ax)`) works against that contract: `get_{x,y}data(orig=False)` returns ms-since-epoch floats, and pandas' period-ordinal tickers (`TimeSeries_Date*`) are accepted as no-ops so the native date ticks keep rendering |
| `xticks(positions, labels, rotation=)` / `tick_params(labelrotation=)` | Exact positions and strings render in browser, PNG, and SVG |
| `twinx()`, `secondary_xaxis()`, `secondary_yaxis()` | second data axes and linked tick-only secondary axes with callable forward/inverse conversions. Secondary-axis ticks are evenly spaced conversions of the primary domain (not Matplotlib's secondary-unit locators) and currently reach the interactive HTML client only — PNG/SVG export does not draw them yet |
| `fig, ax = plt.subplots()`; `plt.subplots(n, m, figsize=, dpi=, squeeze=, sharex=, sharey=)` | Grid renders as CSS-grid HTML and stitched PNG/SVG; shared axes use common domains and live linked pan/zoom. `Figure.subplots_adjust(left=, right=, top=, bottom=, wspace=, hspace=)` moves the SubplotParams frame: the grid resolves to explicit figure rectangles and every exporter (HTML, PNG, SVG) positions panels at those rectangles |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` | |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | Browser-free PNG/SVG supports both single and multi-panel figures; file-like targets require an explicit `format=` and unsupported metadata/layout/export formats fail loudly |
| `plt.show()` | notebooks: inline HTML display; scripts: opens the default browser |
| Artists: `set_data` / `set_ydata` / `set_color` / `set_label` / `set_linewidth` / `remove` | mutating a handle rebuilds the chart on next render |
| Colors | single letters, `C0`–`C9`, `tab:*`, gray `'0.5'`, RGB(A) tuples, any CSS color |
| `plt.cm.*` / `plt.colormaps[...]` / `cmap=` names | viridis, plasma, inferno, magma, cividis, gray, turbo, coolwarm, Blues, RdYlGn, RdGy, jet, rainbow, Spectral, aliases, and true `*_r` reversal (RdGy/jet render from 11-stop anchor tables sampled from Matplotlib 3.11, linearly interpolated) |
| `LinearSegmentedColormap.from_list` / `ListedColormap` | Python-side callables (`cmap(np.arange(cmap.N))` → RGBA) for scripts that colormap values themselves; they cannot be passed as `cmap=` to plotting calls (no engine table), which fails loudly |
| `plt.colorbar()` / `fig.colorbar()` / `plt.clim()` / `plt.gci()` | Returns a live handle (`set_label`, `set_ticks`); with no mappable it uses the current image the way pyplot does. `ticks=`/`extend=` render in PNG and SVG (the HTML colorbar stays a minimal gradient without tick text); `clim` retargets the mappable's color window and any colorbar derived from it |
| `rcParams` | Figure size/DPI, line width/marker size, image cmap/origin, axes color cycle, and all four `axes.spines.*` switches affect every exporter. Pyplot axes default to Matplotlib's four-sided box and each spine can be hidden independently. The chrome keys (axes face/edge/label/title styles, font family/size, tick colors/sizes, legend defaults, figure facecolor) reach the HTML renderer and multi-panel PNG stitching; single-chart PNG and SVG export currently render their own fixed chrome and ignore them. Unknown keys warn once |
| `plt.style.use(...)` / `plt.style.context(...)` | `"default"`, `"xy"`, bounded rcParam dictionaries, ordered lists, and the stock sheets fivethirtyeight, ggplot, bmh, dark_background, grayscale, and seaborn-v0_8-white(grid) — reduced to the supported rcParams subset (colors, grid, cycle, line width, font size; per-sheet keys outside that subset are not carried). `context()` snapshots and restores. Unknown sheet names fail precisely |
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
as visual approximations rather than rejected: the barbs glyph and imshow
smoothing collapse above, `annotate(arrowprops=...)` connection curves and
fancy/wedge outlines drawn as quadratic-curve tapered fills rather than
Matplotlib's exact patch paths, `bbox=` boxes drawn only by the HTML label,
and errorbar limit flags rendered as one-sided bars without Matplotlib's caret
arrows.

## Sharp edges

- Custom Matplotlib marker paths, arbitrary clipping graphs, and unsupported
  collection gradients are rejected rather than silently approximated.
- The shim's figure/axes bookkeeping adds ~10µs per figure over the
  declarative API (measured: +9% at 10k points, +2% at 100k, +0.6% at 1M);
  `tests/pyplot/test_perf_guardrail.py` gates this relationship in CI.

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
changes are recorded in [the compatibility changelog](matplotlib-compat-changelog.md).
