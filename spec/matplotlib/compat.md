# matplotlib compatibility (`xy.pyplot`)

## Execution modes and claims

`xy.pyplot` is one public namespace with two implementations:

| Mode | Contract |
|---|---|
| `native` | Dependency-free, high-performance XY 2-D implementation with XY-owned Figure, Axes, and Artist-shaped types. Select it explicitly to pin the lightweight implementation. |
| `compat` | Matplotlib 3.11 supplies genuine Figure, Axes, Artist, units, transform, layout, toolkit, widget, animation, and projection semantics. `module://xy.backends.backend_xy` supplies the canvas and renderer. Install with `pip install "xy[matplotlib]"`. |
| `auto` | The configured default. It resolves to `compat` when supported Matplotlib 3.11 is installed and to `native` otherwise. |

Select a mode before creating a figure:

```python
import xy.pyplot as plt

plt.set_mode("compat")
```

`XY_PYPLOT_MODE` is the process-level equivalent. Import and mode selection
remain lazy: they do not import Matplotlib. The first compat-routed call
validates `matplotlib>=3.11,<3.12`, activates the XY backend, and returns
genuine Matplotlib objects. Switching modes while either frontend owns an open
figure is an error; close all figures first.

With a base install, changing only the import resolves to native mode:

```python
import xy.pyplot as plt   # the one-line change
```

In native mode, calls translate onto `xy.chart(...)` and friends, retaining
native Rust compute, binary transport, WebGL2 rendering, and screen-bounded
cost. In compat mode, Matplotlib owns the frontend semantics and traverses its
normal Artist graph into an XY device-space display list. Browser, HTML, SVG,
and native raster consumers use that one representation. An accepted compat
result must report `fallback_used=false`; Agg or another Matplotlib renderer
may be used only as a developer oracle, never as output fallback.

**The native claim, precisely:** every method in the Matplotlib 3.11 `Axes`
**Plotting** section is present on both the native `xy.pyplot.Axes` and the
stateful `xy.pyplot` namespace. The reviewed
[`matplotlib_311_plotting.json`](../../tests/pyplot/matplotlib_311_plotting.json)
snapshot locks that inventory to the pinned upstream documentation, while the
executable compatibility corpus in
[`tests/pyplot/corpus/`](../../tests/pyplot/corpus/) covers representative calls
from every family. This is 100% 2-D *chart-method* name coverage; it is not a
full drop-in or gallery-completion claim.

The generated [method-by-method compatibility matrix](compat-matrix.md)
describes native option depth and is sourced from that snapshot, executable
corpus calls, and
[`compatibility.json`](../../tests/pyplot/compatibility.json). CI fails if the
generated matrix is stale, installs the released `matplotlib==3.11.0` wheel,
and asserts every snapshot method exists on its `Axes`. The dev revision
recorded in the snapshot is informational: CI no longer compares the snapshot
against an upstream Matplotlib checkout.

**The compat completion claim is gallery-defined.** The permanent contract
represents the 507 sources in the supplied Matplotlib 3.11.1 documentation
gallery while using Matplotlib 3.11.0 as the pinned reference oracle:

| Classification | Count | Contract role |
|---|---:|---|
| Standard pyplot profile | 472 | Pyplot-eligible examples reproducible in the standard headless environment |
| Extended pyplot profile | 13 | Pyplot-eligible examples with declared TeX, GUI/toolkit, scripted-input, argument, PDF, or multiprocessing requirements |
| Non-pyplot | 22 | Backend, font, server, or GUI embedding sources with no pyplot import to replace |

The first two rows form the 485 pyplot-eligible denominator. The 22 non-pyplot
sources remain represented and classified but never count as pyplot successes
or failures. The completed compatibility report passes 472/472 standard and
13/13 extended examples: 485/485 pyplot-eligible cases across the execution,
structural, semantic, tolerant visual, behavior, and no-fallback gates, with
no waivers. The checked-in baseline records the exact implementation commit,
harness/manifest hashes, and promoted standard/extended report hashes.

The gallery harness changes only the pyplot binding through an AST-verified,
token-aware rewrite and executes each result as a real temporary file.
Interactions and animations require delivered callback, widget, timer, and
driven-frame evidence—not screenshots alone. See
[`gallery-contract.md`](gallery-contract.md) for the immutable manifest,
extended environment, thresholds, and completed report contract.

## Native-mode approximation levels

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

## Native-mode supported surface

| matplotlib | notes |
|---|---|
| `plt.plot` / `ax.plot` | format strings (`'r--o'`), multiple series per call, implicit x, `label=`, `lw=`, `ls=`, `alpha=`, marker face/edge styling, directional `^`/`v`/`<`/`>` triangles and distinct `+`/`x` glyphs, `markevery`, and dependency-free affine *data* transforms (`Affine2D + ax.transData`); axes/figure-fraction transforms on data artists, partial fill styles, and cap/join policies fail loudly |
| `scatter(x, y, s=, c=, cmap=, vmin=, vmax=, alpha=, marker=, edgecolors=, plotnonfinite=)` | `s` (pt², area) maps to pixel diameter; numeric 1-D `c` remains a colormap encoding, while `N×3`/`N×4` face and edge colors, alpha arrays, sizes, and linewidth arrays stay in one collection. Explicit alpha replaces intrinsic RGBA alpha, matching Matplotlib; custom norms/marker paths fail loudly |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories, stacking bases, per-bar face/edge color-alpha pairs and linewidths, plus iterable/indexable `BarContainer.patches` views whose setters mutate the parent batched trace |
| `hist(bins=, range=, density=, cumulative=, weights=, orientation=, stacked=)` | Returns computed counts/edges; stacked density normalizes the combined weighted area once (including unequal bins and either cumulative direction), matching Matplotlib 3.11; bar, step, and stepfilled families render in both vertical and horizontal orientations; unfilled step outlines connect their top envelope to zero or the previous stack at both endpoints |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel. `hist2d` delegates rendering to the pseudocolor-mesh path for both uniform and non-uniform bins, supports linear and logarithmic normalization, defaults to fully opaque cells, and retains the original count domain for logarithmic mappables. Its view limits are the outer bin edges with no margin, matching Matplotlib's sticky mesh edges. Arbitrary custom normalization and `colorizer` remain unsupported. Hexbin uses Matplotlib's two-offset-grid nearest-center assignment and six-triangle data-space cells, supports `C`, arbitrary scalar reducers, and `mincnt`, and retains only the bounded lattice rather than source points. `ecdf` carries the ordinary margin on the sample axis and is sticky at 0 and 1 on the cumulative axis |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Boxplots support notches, bootstrap/user confidence intervals, median overrides (drawn median only; notch CIs stay data-derived like Matplotlib), percentile/custom whiskers, cap widths, `sym`, dashed line-component styles, and component colors/widths/alpha. Default boxes are unfilled outlines and return Matplotlib-shaped per-group component handles (two whiskers/caps and one box/median/flier handle per group). `patch_artist=True` emits mutable filled polygon boxes; statistics labels become category tick labels, while scalar or per-box legend labels bind to boxes for patch plots and medians otherwise. Violins use Gaussian KDE for the default Scott bandwidth and explicit Scott/Silverman/scalar/callable bandwidths, return one seam-free mutable body per group, cycle face and line color sequences, preserve color-alpha pairs, and support quantiles and low/high sides. `boxplot` autoscales its value axis over the Tukey whiskers plus, when `showfliers` is on, the flier points. Its default category positions are 1-based and `manage_ticks=True` reserves half a unit around the outer positions, matching Matplotlib |
| `fill_between(x, y1, y2, where=, step=)` / `fill_betweenx` | Masks are split into finite contiguous polygons; step geometry is expanded exactly |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `psd`, `csd`, `cohere`, `specgram` | Native real-valued Hann-windowed Welch spectra use Matplotlib 3.11's default `detrend_none` semantics. Callable windows/detrending, independent `pad_to`, explicit sides/frequency scaling, and complex/two-sided inputs remain unsupported and fail loudly instead of silently changing the signal; completing these is tracked acceptance debt for `statistics/psd_demo.py` |
| `imshow` / `matshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | `imshow` defaults to `rcParams['image.origin']`; nearest stays cell-exact, while named smoothing modes use dependency-free per-kernel approximations over a bounded 512–1024 px intermediate for both scalar and RGB(A) data. `plt.matshow(A)` creates a dedicated bounded-`figaspect` figure and top-ticked axes like Matplotlib; `fignum=0` reuses the current axes and an existing numbered figure is not resized. Filter choice and intermediate size do not yet depend on final display resolution, and explicit `interpolation="auto"` remains unsupported. Unsupported stages/transforms fail loudly. Uniform meshes retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion. Both hug their outer cell edge with no margin, as Matplotlib's sticky image/mesh edges do |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels; automatic labels repeat at bounded, separated positions along each level (line knockout for `inline=True` remains a visual approximation) |
| `quiver`, `barbs`, `streamplot` | Quiver supports Matplotlib's width-unit vocabulary independently from length scaling. Barbs use fixed-length staffs and Matplotlib's flag/full/half decomposition, including increments, rounding, empty glyphs, colors, sizes, flipping, and pivots. Streamplot uses a dependency-free adaptive Heun integrator with occupancy-aware seeding; `start_points`, `integration_direction`, `broken_streamlines`, integration step/error scales, array widths/colors, and `num_arrows` are honored |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels), including dtype-preserving value formats, radial label rotation/alignment, and common text properties |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Fractional span bounds plus data/axes/figure text coordinates are supported. `Figure.text` is compositor-owned and can render on a zero-axes figure without changing its structure or canvas dimensions. `annotate(arrowprops=)` draws real arrows in every output: offset-point text becomes an engine callout (arrow pinned from label to point across zoom), data-coordinate text an arrow annotation; date-string coordinates convert like Matplotlib's unit registry. Arrowstyles map to head/tail shapes (`->` open V, `-\|>` filled, `\|-\|`/brackets bar caps, `fancy`/`simple`/`wedge` filled tapered shafts sized by the text's mutation scale) and `connectionstyle` arc3/angle3/angle become quadratic curves (corner rounding approximated); `alpha` dims the arrow only. `bbox=` becomes label box styles (fill/edge/round corners/`pad`) in browser and static exports; its `alpha` is the *patch* alpha and dims face and edge together, as Matplotlib's element `opacity` does, and `boxstyle="round"`/`round4` corners are rounded in SVG (`rx`) and native PNG as well as in the browser. An arrow-less `text`/`annotate` label is painted with `rcParams["text.color"]` in all three renderers rather than each renderer's own annotation-label default. Text is unclipped like Matplotlib (`clip_on=False`), and axes-fraction text right of the axes box (x > 1, e.g. seaborn-style row titles) reserves right margin in every exporter. `rotation=90/270` renders vertical text in browser, PNG, and SVG with Matplotlib's rotate-then-align box semantics; other angles rotate in browser and SVG output only (native PNG draws them horizontally) |
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
| `Figure.subfigures` / `SubFigure.subfigures` / `add_subfigure` | Native subfigures may nest and own their axes directly while the root `Figure.axes` retains global draw order. `Axes.get_figure(root=True)` resolves the root; `SubFigure.get_figure(root=False)` resolves its direct parent. The measured ownership tree gives every figure, subfigure, axes, inset, twin, colorbar axes/chrome, and figure-text node a root-normalized viewport and clip; HTML, SVG, and native PNG consume one immutable resolved snapshot per export. |
| `subplot(projection="polar")`; `add_subplot(..., polar=True)`; `axes(projection="polar")`; `subplots(subplot_kw={"projection": "polar"})` | Ordinary `plot`, `scatter`, `fill`, `bar`, heatmap/image, contour, and error-bar calls render through the core polar coordinate system in HTML, PNG, and SVG. The PolarAxes controls `set_theta_zero_location`, `set_theta_direction`, `set_theta_offset`, `set_thetagrids`, `set_thetamin`/`set_thetamax` (degrees), `set_rlim`, `set_rticks`, `set_rorigin`, and their theta/r limit accessors route into the same angular/radial axes. Categorical θ and log/symlog radial scales use that core transform as well. Polar `axhline`/`axvline` and span geometry, LOD, facets/animation, angular navigation/selection, and the stateful `plt.polar`/`plt.thetagrids`/`plt.rgrids` convenience wrappers remain outside this surface and fail or remain absent rather than drawing a Cartesian approximation. **Silently dropped on a polar Axes:** minor ticks and their style (`minorticks_on`, `minor` `tick_params`, `set_minor_locator`), tick-label horizontal alignment (`tick_params(ha=)`), and the tick-label collision strategies — no renderer draws minor rings or spokes, and rim labels have no edge-relative collision pass or anchor (`spec/design/polar-axes.md` §9). They are dropped rather than refused because every Axes carries an rcParam-derived `minor_style`, so refusing would break the projection over a default nobody authored; a hand-authored `xy.theta_axis`/`xy.r_axis` refuses them instead. |
| `Axes.get_position(original=False)` and the rendered axes frame | Supported subplot and free-form axes report their live figure rectangle and render on it. `original=True` returns the allocated rectangle before an adjustable-box aspect correction; the default applies the correction and its anchor, matching Matplotlib. Grid cells resolve under the live SubplotParams (`wspace`/`hspace`, width/height ratios), while explicit `add_axes`/`set_position` rectangles take precedence until a later layout adjustment. Titles, top-side x axes (`matshow`), and secondary-y gutters grow the surrounding allocation instead of moving the frame. **Known exception:** an axes carrying a colorbar keeps label-aware margins because xy and Matplotlib currently reserve the colorbar strip through different layout paths |
| `Axes.inset_axes([left, bottom, width, height], sharex=, sharey=)` | Bounds are relative to the parent axes and may extend outside it for marginal plots. Insets are independent free-form panels in `Figure.axes`, preserve draw order, and statically share the requested axis property store; they are not flattened into the parent data space. Their tree clip is the nearest figure/subfigure container, not the parent axes' data rectangle. |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` | |
| `plt.subplot_mosaic([['A','B'],['C','C']])` / `Figure.subplot_mosaic` | Row sequences (a list of equal-length label strings, or nested label lists) resolve to a uniform grid; each distinct label, in first-appearance order, binds to the next cell, returning `(fig, {label: Axes})` with `figsize=`/`dpi=` sizing the figure. Repeated labels do not span and `'.'` does not blank a cell — the grid keeps one axes per cell — and Matplotlib's single-string forms (`'AB;CC'`, newline-separated blocks) are not parsed into rows |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | Browser-free PNG/SVG supports both single and multi-panel figures; file-like targets require an explicit `format=` and unsupported metadata/layout/export formats fail loudly |
| `plt.show()` | notebooks: displays the connected anywidget; scripts: opens a token-authenticated `127.0.0.1` live host in the default browser and pumps callbacks/timers on the Python thread. `print_html()` remains a static export |
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

## Native-mode boundary and compat ownership

Native mode does not recreate three-dimensional, ternary, geographic, or
custom projections, Matplotlib's full Artist/transform/layout systems,
`FuncAnimation`, widgets, toolkits, callback registries, or blitting. Polar is
its supported non-Cartesian projection with the boundary above. Bounded
shim-owned `Axes` Artist views, children, containers, removal, affine data
transforms, coordinate spaces, and linked secondary axes are supported.

Those systems are not excluded from compat mode. Matplotlib performs units,
transforms, layout, `mplot3d` projection/depth ordering, `axes_grid1`,
`axisartist`, widget, callback, and animation semantics; XY renders the
resulting paths, collections, images, text outlines, clips, and meshes. The
live canvas maps browser input to Matplotlib event objects and supports timers,
`draw`, `draw_idle`, and full-redraw `blit`. Standalone HTML has no live Python
callback process, although it may contain precomputed animation frames.

The advanced families remain subject to the same 485-case gallery gate.
Architecture support must not be reported as final corpus completion.

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

## Native-mode sharp edges

- Custom Matplotlib marker paths, arbitrary clipping graphs, and unsupported
  collection gradients are rejected rather than silently approximated.
- The shim's figure/axes bookkeeping adds ~50µs of fixed per-figure cost over
  the declarative API (measured 2026-07-14, M-series: +60% at 10k points, +26%
  at 100k — fixed cost over an ~85µs baseline, not O(n) work).
  CodSpeed's paired raw/pyplot arms track that relationship at 10k, 100k, and
  1M points. Blocking pytest tests enforce the underlying cache and
  no-materialization invariants without relying on sub-millisecond wall-clock
  comparisons on shared CI runners.

## Import and package boundaries

The native shim lives in `python/xy/pyplot/`; no core engine module imports it,
and importing `xy` never loads it. A plain `import xy.pyplot` and mode
selection do not load Matplotlib or the widget stack. Compat resolution crosses
the optional dependency boundary only on the first routed call and loads the
public backend from `python/xy/backends/`. The display-list types and consumers
remain Matplotlib-independent.

## Maintenance

The upstream revision and method inventory are updated together. When moving
the pin, check out the proposed Matplotlib revision and run:

```console
python scripts/sync_matplotlib_compat.py --upstream path/to/matplotlib --update-snapshot
python scripts/sync_matplotlib_compat.py
```

Review the snapshot and generated matrix diff as an API change. Release-level
changes are recorded in [the compatibility changelog](compat-changelog.md).
