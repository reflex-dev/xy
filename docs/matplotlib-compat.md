# matplotlib compatibility (`fastcharts.pyplot`)

```python
import fastcharts.pyplot as plt   # the one-line change
```

`fastcharts.pyplot` is a shim over the declarative composition API: every
call translates onto `fastcharts.chart(...)` and friends, so shim charts get
the same engine — native Rust compute, binary transport, WebGL2 rendering,
screen-bounded cost — with matplotlib's calling conventions.

**The claim, precisely:** the compatibility corpus in
[`tests/pyplot/corpus/`](../tests/pyplot/corpus/) runs unmodified. The corpus
holds the highest-frequency real-world pyplot idioms; anything outside it is
either explicitly unsupported (loud `NotImplementedError` naming this page)
or untested — assume it doesn't work until a corpus snippet proves it does.
CI executes every snippet, so this table cannot drift ahead of reality.

## Supported surface

| matplotlib | notes |
|---|---|
| `plt.plot` / `ax.plot` | format strings (`'r--o'`), multiple series per call, implicit x, `label=`, `lw=`, `ls=`, `alpha=`, `marker=` |
| `scatter(x, y, s=, c=, cmap=, alpha=, marker=, edgecolors=)` | `s` (pt², area) maps to engine diameter (`√s`); array `c` becomes a color encoding |
| `bar` / `barh` (`bottom=`/`left=`, `color=`, `label=`) | string categories work; `align='edge'` approximated as centered |
| `hist(bins=, range=, density=, cumulative=)` | `histtype` variants all render as bars |
| `fill_between(x, y1, y2)` | → area mark |
| `imshow` / `pcolormesh` (`cmap=`, `vmin=`/`vmax=`, `origin=`) | exact-cell heatmap; `interpolation` ignored |
| `step` | rendered as a line |
| `axhline` / `axvline` / `axhspan` / `axvspan`, `text`, `annotate` | `arrowprops` renders as plain callout text |
| `xlabel` / `ylabel` / `title` / `suptitle` | suptitle not yet drawn in stitched multi-panel PNGs (warns) |
| `legend()` | `loc`/`fontsize` accepted; placement is the chart's own |
| `grid(True/False)` | toggles the grid via the theme |
| `xlim` / `ylim`, `xscale('log')` / `yscale('log')`, `invert_xaxis/yaxis` | |
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
| `plt.style.use("fastcharts")` | switches from the matplotlib-flavored default theme to the engine-native look |

## Not supported (raises `NotImplementedError` pointing here)

`pie`, `boxplot`, `violinplot`, `errorbar`, `contour(f)`, `quiver`,
`streamplot`, polar/3D projections, `FuncAnimation`, arbitrary artist-graph
access (`fig.artists`, transforms, blitting). Roadmap candidates: `errorbar`
(composable today as `plot` + `fill_between`), `boxplot`, `pie`.

Unsupported *keyword arguments* on supported calls raise `TypeError`
naming the offending keyword — nothing is silently dropped.

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

The shim lives entirely in `python/fastcharts/pyplot/`; no engine module
imports it, importing `fastcharts` never loads it, and importing the shim
never loads the widget stack or real matplotlib.
