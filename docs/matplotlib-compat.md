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
namespace. `test_official_matplotlib_311_2d_plotting_surface_is_complete`
locks that inventory to the upstream list, while the executable compatibility
corpus in [`tests/pyplot/corpus/`](../tests/pyplot/corpus/) covers representative
calls from every family. This is 100% 2-D *chart-method* coverage; it is not a
claim to reproduce Matplotlib's renderer, transforms, or full Artist graph.

## Supported surface

| matplotlib | notes |
|---|---|
| `plt.plot` / `ax.plot` | format strings (`'r--o'`), multiple series per call, implicit x, `label=`, `lw=`, `ls=`, `alpha=`, `marker=` |
| `scatter(x, y, s=, c=, cmap=, alpha=, marker=, edgecolors=, plotnonfinite=)` | `s` (pt², area) maps to pixel diameter; array `c` becomes a color encoding |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories, stacking bases, Matplotlib 3.11 grouped-bar containers and labels |
| `hist(bins=, range=, density=, cumulative=, weights=, orientation=, stacked=)` | Returns computed counts/edges and supports bar/step histogram families |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel; ECDF/hexbin use the corresponding core marks |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Raw samples use bounded core distribution marks; precomputed statistics use exact generic mesh/segment geometry |
| `fill_between(x, y1, y2, where=, step=)` / `fill_betweenx` | Masks are split into finite contiguous polygons; step geometry is expanded exactly |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | Uniform grids retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels |
| `quiver`, `barbs`, `streamplot` | Native vector endpoint/arrowhead and bounded streamline kernels feeding one instanced segment mark |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels) |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Fractional span bounds plus data/axes/figure text coordinates are supported; `arrowprops` is approximated as callout text |
| `xlabel` / `ylabel` / `title` / `suptitle` | Suptitles are retained in HTML and multi-panel PNG/SVG |
| `legend()` | `loc`/`fontsize` accepted; placement is the chart's own |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, axis scales, `invert_xaxis/yaxis` | linear/log are native; symlog/logit/asinh fail loudly until their transforms are implemented |
| `xticks(positions, labels, rotation=)` / `tick_params(labelrotation=)` | Exact positions and strings render in browser, PNG, and SVG |
| `twinx()` | second y-axis (right side) |
| `fig, ax = plt.subplots()`; `plt.subplots(n, m, figsize=, dpi=, squeeze=, sharex=, sharey=)` | Grid renders as CSS-grid HTML and stitched PNG/SVG; shared axes use common domains and live linked pan/zoom |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` | |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | Browser-free PNG/SVG supports both single and multi-panel figures |
| `plt.show()` | notebooks: inline HTML display; scripts: opens the default browser |
| Artists: `set_data` / `set_ydata` / `set_color` / `set_label` / `set_linewidth` / `remove` | mutating a handle rebuilds the chart on next render |
| Colors | single letters, `C0`–`C9`, `tab:*`, gray `'0.5'`, RGB(A) tuples, any CSS color |
| `plt.cm.*` / `plt.colormaps[...]` / `cmap=` names | viridis, plasma, inferno, magma, cividis, gray, turbo, coolwarm, Blues, RdYlGn, rainbow, Spectral, aliases, and true `*_r` reversal |
| `rcParams` | `figure.figsize`, `figure.dpi`, `lines.linewidth`, `lines.markersize`, `axes.grid`; unknown keys warn once and are ignored |
| `plt.style.use("xy")` | switches from the matplotlib-flavored default theme to the engine-native look |

## Outside 2-D chart-method compatibility

Polar/3D projections, `FuncAnimation`, secondary-axis layout, and arbitrary
artist-graph access (`fig.artists`, general transforms, blitting) are not
part of this 2-D chart-method target.

Unknown keyword arguments on supported calls raise `TypeError` naming the
offending keyword. Renderer-only properties that do not alter data geometry
may be accepted as visual approximations by the adapter.

## Sharp edges

- Grid `which=`/`axis=` selectors currently map to the chart-wide grid switch;
  major/minor grid styling is an approximation.
- Custom Matplotlib marker paths and collection color gradients fall back to
  the closest native primitive; their data geometry is retained.
- The shim's figure/axes bookkeeping adds ~10µs per figure over the
  declarative API (measured: +9% at 10k points, +2% at 100k, +0.6% at 1M);
  `tests/pyplot/test_perf_guardrail.py` gates this relationship in CI.

## Boundaries (enforced by `tests/pyplot/test_boundaries.py`)

The shim lives entirely in `python/xy/pyplot/`; no engine module
imports it, importing `xy` never loads it, and importing the shim
never loads the widget stack or real matplotlib.
