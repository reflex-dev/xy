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
snapshot differs from the pinned Matplotlib checkout or if the generated matrix
is stale.

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
| `plt.plot` / `ax.plot` | format strings (`'r--o'`), multiple series per call, implicit x, `label=`, `lw=`, `ls=`, `alpha=`, marker face/edge styling and `markevery`; unsupported transforms, partial fill styles, and cap/join policies fail loudly |
| `scatter(x, y, s=, c=, cmap=, vmin=, vmax=, alpha=, marker=, edgecolors=, plotnonfinite=)` | `s` (pt², area) maps to pixel diameter; array `c` becomes a color encoding and explicit paired color bounds are retained; custom norms/marker paths fail loudly |
| `bar`, `barh`, `grouped_bar`, `bar_label` | string categories, stacking bases, Matplotlib 3.11 grouped-bar containers and labels |
| `hist(bins=, range=, density=, cumulative=, weights=, orientation=, stacked=)` | Returns computed counts/edges and supports bar/step histogram families |
| `hist2d`, `hexbin`, `ecdf` | 2D uniform binning uses the native Rust kernel; ECDF/hexbin use the corresponding core marks |
| `boxplot`, `violinplot`, `bxp`, `violin`, `errorbar` | Raw samples use bounded core distribution marks; precomputed statistics use exact generic mesh/segment geometry |
| `fill_between(x, y1, y2, where=, step=)` / `fill_betweenx` | Masks are split into finite contiguous polygons; step geometry is expanded exactly |
| `stackplot` | All four baselines are computed by the native stacked-bounds kernel |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | `imshow` defaults to `rcParams['image.origin']`; nearest stays cell-exact and Matplotlib's smoothing mode names all collapse to the shim's single bounded gradient upsampling (a visual approximation, not per-mode kernels) and apply to scalar data only — RGB(A) truecolor arrays render unresampled — while unsupported stages/transforms fail loudly. Uniform meshes retain the texture fast path; nonuniform and curvilinear grids use native quad-to-triangle expansion |
| `step`, `stairs`, `stem`, `eventplot` | Compact step/stem/segment marks; no Python-side vertex expansion |
| `contour` / `contourf` / `clabel` | Native marching squares over rectilinear grids; warped grids route through native Delaunay/marching-triangle kernels |
| `quiver`, `barbs`, `streamplot` | Native vector endpoint/arrowhead and bounded streamline kernels feeding one instanced segment mark. Barbs are a visual approximation: magnitude maps to a bounded tick count, not WMO 50/10/5 increments. Streamplot always uses the shim's own bounded fixed-step integrator (identical output with or without Matplotlib installed, but paths approximate Matplotlib's adaptive ones); `start_points`, `integration_direction`, array widths/colors and `num_arrows` are honored, and remaining non-default integration options fail loudly |
| `tripcolor`, `triplot`, `tricontour`, `tricontourf` | Explicit topology or native dependency-free Delaunay triangulation; indexed geometry and isolines stay in Rust |
| `pie` / `pie_label` | Native pie/donut tessellation and the Matplotlib 3.11 `PieContainer` (`values`, `fracs`, grouped text labels) |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate`, `table` | Fractional span bounds plus data/axes/figure text coordinates are supported; `arrowprops` is approximated as callout text |
| `xlabel` / `ylabel` / `title` / `suptitle` | Suptitles are retained in HTML and multi-panel PNG/SVG |
| `legend()` | `loc`/`fontsize` accepted; placement is the chart's own |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, axis scales, `invert_xaxis/yaxis` | linear/log are native; symlog/logit/asinh fail loudly until their transforms are implemented |
| datetime, timedelta, and string coordinates | datetime inputs use the engine's automatic date ticks, timedeltas are bounded to elapsed seconds, and common strings use categorical ticks; the general Matplotlib units registry is intentionally out of scope |
| `xticks(positions, labels, rotation=)` / `tick_params(labelrotation=)` | Exact positions and strings render in browser, PNG, and SVG |
| `twinx()` | second y-axis (right side) |
| `fig, ax = plt.subplots()`; `plt.subplots(n, m, figsize=, dpi=, squeeze=, sharex=, sharey=)` | Grid renders as CSS-grid HTML and stitched PNG/SVG; shared axes use common domains and live linked pan/zoom |
| `fig.add_subplot(2, 2, 1)` / `add_subplot(221)` | |
| `gca` / `gcf` / `sca` / `figure(num)` / `close(...)` | matplotlib's implicit-state semantics |
| `savefig('x.png' / '.svg' / '.html', dpi=)` | Browser-free PNG/SVG supports both single and multi-panel figures; file-like targets require an explicit `format=` and unsupported metadata/layout/export formats fail loudly |
| `plt.show()` | notebooks: inline HTML display; scripts: opens the default browser |
| Artists: `set_data` / `set_ydata` / `set_color` / `set_label` / `set_linewidth` / `remove` | mutating a handle rebuilds the chart on next render |
| Colors | single letters, `C0`–`C9`, `tab:*`, gray `'0.5'`, RGB(A) tuples, any CSS color |
| `plt.cm.*` / `plt.colormaps[...]` / `cmap=` names | viridis, plasma, inferno, magma, cividis, gray, turbo, coolwarm, Blues, RdYlGn, rainbow, Spectral, aliases, and true `*_r` reversal |
| `rcParams` | Figure size/DPI, line width/marker size, image cmap/origin, and the axes color cycle affect every exporter. The chrome keys (axes face/edge/label/title styles, font family/size, tick colors/sizes, legend defaults, figure facecolor) reach the HTML renderer and multi-panel PNG stitching; single-chart PNG and SVG export currently render their own fixed chrome and ignore them. Unknown keys warn once |
| `plt.style.use(...)` | `"default"`, `"xy"`, bounded rcParam dictionaries, and ordered lists of those forms are supported; named third-party style sheets fail precisely |

## Outside 2-D chart-method compatibility

Polar/3D projections, `FuncAnimation`, secondary-axis layout, arbitrary
third-party Artist graphs, general transform composition, and blitting are not
part of this 2-D chart-method target. Bounded shim-owned `Axes` Artist views,
children, containers, removal, identity/affine transforms, and coordinate
spaces are supported.

Unknown keyword arguments on supported calls raise `TypeError` naming the
offending keyword. Known material options that the native marks cannot honor
raise `NotImplementedError`, with these documented exceptions that are accepted
as visual approximations rather than rejected: the barbs glyph and imshow
smoothing collapse above, `annotate(arrowprops=...)` reduced to callout text,
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
