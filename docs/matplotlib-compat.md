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
| `scatter(x, y, s=, c=, cmap=, alpha=, marker=, edgecolors=)` | `s` (pt², area) maps to engine diameter (`√s`); array `c` becomes a color encoding |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories, stacking bases, Matplotlib 3.11 grouped-bar containers and labels |
| `hist(bins=, range=, density=, cumulative=)` | `histtype` variants all render as bars |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel; ECDF/hexbin use the corresponding core marks |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Raw samples use bounded core distribution marks; precomputed statistics use exact generic mesh/segment geometry |
| `fill_between(x, y1, y2)` | → area mark |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | Uniform grids retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels |
| `quiver`, `barbs`, `streamplot` | Native vector endpoint/arrowhead and bounded streamline kernels feeding one instanced segment mark |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels) |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Tables compose generic triangle, segment, and text marks; `arrowprops` renders as plain callout text |
| `xlabel` / `ylabel` / `title` / `suptitle` | suptitle not yet drawn in stitched multi-panel PNGs (warns) |
| `legend()` | `loc`/`fontsize` accepted; placement is the chart's own |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, axis scales, `invert_xaxis/yaxis` | linear/log are native; symlog/logit/asinh fail loudly until their transforms are implemented |
| `xticks(rotation=)` / `tick_params(labelrotation=)` | arbitrary tick *positions/labels* are approximated by count |
| `twinx()` | second y-axis (right side) |
| `fig, ax = plt.subplots()`; `plt.subplots(n, m, figsize=, dpi=, squeeze=)` | grid renders as a CSS-grid HTML document; PNG export stitches panels via the native rasterizer |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` | |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | PNG is browser-free (native rasterizer); multi-panel SVG not supported (use HTML/PNG) |
| `plt.show()` | notebooks: inline HTML display; scripts: opens the default browser |
| Artists: `set_data` / `set_ydata` / `set_color` / `set_label` / `set_linewidth` / `remove` | mutating a handle rebuilds the chart on next render |
| Colors | single letters, `C0`–`C9`, `tab:*`, gray `'0.5'`, RGB(A) tuples, any CSS color |
| `plt.cm.*` / `cmap=` names | viridis, plasma, inferno, magma, cividis, gray, turbo, coolwarm (+ aliases; `*_r` renders unreversed) |
| `rcParams` | `figure.figsize`, `figure.dpi`, `lines.linewidth`, `lines.markersize`, `axes.grid`; unknown keys warn once and are ignored |
| `plt.style.use("xy")` | switches from the matplotlib-flavored default theme to the engine-native look |

## Outside 2-D chart-method compatibility

Polar/3D projections, `FuncAnimation`, inset/secondary-axis layout, and
arbitrary artist-graph access (`fig.artists`, transforms, blitting) are not
part of this 2-D chart-method target.

Unknown keyword arguments on supported calls raise `TypeError` naming the
offending keyword. Renderer-only properties that do not alter data geometry
may be accepted as visual approximations by the adapter.

## Sharp edges

- `sharex`/`sharey` apply shared static domains and warn; live linked
  zooming across panels is an engine roadmap item.
- Tick label *strings* (`xticks(pos, labels)`) are not placeable yet;
  rotation and count map.
- Reversed colormaps (`viridis_r`) render unreversed.
- The shim's figure/axes bookkeeping adds ~10µs per figure over the
  declarative API (measured: +9% at 10k points, +2% at 100k, +0.6% at 1M);
  `tests/pyplot/test_perf_guardrail.py` gates this relationship in CI.

## Boundaries (enforced by `tests/pyplot/test_boundaries.py`)

The shim lives entirely in `python/xy/pyplot/`; no engine module
imports it, importing `xy` never loads it, and importing the shim
never loads the widget stack or real matplotlib.
