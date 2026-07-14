# Python Data Science Handbook, chapter 4 — on `xy.pyplot`

These notebooks are the matplotlib chapter of Jake VanderPlas's
[Python Data Science Handbook](https://github.com/jakevdp/PythonDataScienceHandbook),
with one systematic change: `import matplotlib.pyplot as plt` became
`import xy.pyplot as plt`. They exist to answer, on popular real-world
code, "can I just change the import?"

## Run the comparison in one notebook

Every checked-in notebook contains both runs in the same file. Each Matplotlib
code cell is immediately followed by the matching `xy.pyplot` code cell, so the
two outputs appear together instead of in separate sections or notebooks. The
paired cells use distinct plotting aliases and are labeled in their first line.
`xy.pyplot` provides the Jupyter end-of-cell figure flush itself, so the example
cells do not need display workarounds.

Open any original notebook, choose **Restart Kernel and Run All Cells**, and
compare each adjacent output pair in place. For example:

```bash
cd examples/pdsh
jupyter lab pdsh_04_02_simple_scatter_plots.ipynb
```

The notebooks remain beside `data/`, so their existing relative data paths work
for both sections. There are no separate Matplotlib-reference notebooks. After
editing an xy example, regenerate its mirrored reference section with:

```bash
.venv/bin/python examples/pdsh/sync_dual_engine_notebooks.py
```

Only the MIT-licensed code cells are included (the book's prose is
CC-BY-NC-ND and is omitted; section headings are kept for navigation).
Besides the import swap, the code carries the same modernizations the
originals need to run on current matplotlib anyway: `seaborn-*` style
names (removed in matplotlib 3.6), `cm.get_cmap` (removed in 3.9), and
pandas `Series.view` (removed in pandas 2).

## Scorecard

Measured 2026-07-13, after the gap-closing pass this experiment
motivated (tick locators/formatters, `style.context`, `GridSpec`,
`clim`, `cycler`, diverging colormaps, colorbar handles). The
matplotlib column is the identical code with the original import, on
matplotlib 3.11 — it passes everything, so the xy column is pure shim
signal. A "cell ok" also implies a non-empty `savefig` PNG export.

| Notebook | matplotlib 3.11 | xy.pyplot |
|---|---:|---:|
| 04.00 Introduction | 8/8 | 8/8 |
| 04.01 Simple Line Plots | 15/15 | 15/15 |
| 04.02 Simple Scatter Plots | 8/8 | 8/8 |
| 04.03 Errorbars | 5/5 | 5/5 |
| 04.04 Density and Contour Plots | 8/8 | 8/8 |
| 04.05 Histograms and Binnings | 10/10 | 10/10 |
| 04.06 Customizing Legends | 11/11 | 10/11 |
| 04.07 Customizing Colorbars | 13/13 | 13/13 |
| 04.08 Multiple Subplots | 10/10 | 10/10 |
| 04.09 Text and Annotation | 9/9 | 6/9 |
| 04.10 Customizing Ticks | 11/11 | 11/11 |
| 04.11 Settings and Stylesheets | 15/15 | 15/15 |
| 04.12 Three-Dimensional Plotting¹ | 17/17 | 7/17 |
| 04.14 Visualization with Seaborn² | 31/31 | 30/31 |
| **Total** | **171/171** | **156/171 (91%)** |

Excluding the out-of-scope 3D notebook: 149/154 (97%). The first
measurement, before the gap-closing pass, was 121/171 (71%). The 04.08
and 04.10 rows reflect the 2026-07-14 `subplots_adjust` implementation:
both formerly rejected cells re-ran and exported (04.10's re-run used
identically shaped stand-in images because the measurement sandbox
cannot download the Olivetti faces; the previously recorded failure was
the `subplots_adjust` rejection itself, raised before any drawing).

¹ 3D projections are outside xy's 2-D chart-method compatibility target
(see [docs/matplotlib-compat.md](../../docs/matplotlib-compat.md));
`plt.axes(projection='3d')` fails loudly rather than silently returning
a 2-D axes, so only this notebook's 2-D cells pass.
² Soft evidence: seaborn draws through real matplotlib internally, so
only the cells calling `plt` directly exercise the shim.

## Visual parity (the honest asterisk on the scorecard)

A cell "passing" means it *ran* and exported a non-empty PNG — not that
the PNG looks like Matplotlib's. A 2026-07-14 image-level audit rendered
every cell under both engines with per-cell seeded RNG (identical data)
and graded every comparable non-3-D image pair against matplotlib 3.11.
The first pass found **39 major divergences** across 105 pairs (legend
label-lists rendering nothing, `plot(x, y_2d)` not cycling colors,
colorbar count-domain defects, drifted colormap tables, contour
conventions, missing annotate arrows, mathtext, layout gaps). After the
fix rounds the same measurement over the 12 comparable notebooks (84
graded pairs) stands at **34 match / 38 minor / 8 major** — majors down
from 33 on those notebooks, with the stylesheet-legend, color-cycle,
colorbar-domain, and colormap-fidelity classes fully cleared. The audit
findings, fixes, and remaining boundaries are recorded in
[docs/matplotlib-compat-changelog.md](../../docs/matplotlib-compat-changelog.md).

One caveat inflates the scorecard above: with seaborn (which draws
through real matplotlib) holding the current figure, module-level
`plt.hist`/`axvline`/`axhline` draw onto xy's own figure — three 04.14
cells count as passing while their plt-drawn content lands elsewhere.
This is a mixed-engine measurement artifact, not an xy code path: xy
replaces matplotlib, and without matplotlib installed seaborn fails
loudly at import, so 04.14 stays soft evidence only (no runtime
fallback onto matplotlib will ever be added).

## Remaining failures

All 15 are one of: 3-D projection cells (10, loud rejections by
design), the second-legend `Legend` class (1, a documented loud rejection),
pandas `Series.plot(ax=ax)` datetime interop (3, a real gap — a dtype error
inside the pandas plotting path), and `axhline(marker=)` via seaborn
(1, loud rejection). The two `subplots_adjust` cells counted here until
2026-07-14 pass now that the shim implements the SubplotParams frame.

The 2026-07-14 fidelity follow-up also compared the affected PDSH cells
directly against Matplotlib 3.11: directional markers and `x`/`+` remain
distinct, contour labels repeat along levels, hexbins form a complete true
lattice, horizontal filled histograms use the correct value axis, and both
formerly rejected legend-style cells render. The final follow-up adds the 2.5
automatic tick step with uniform decimal padding, occupancy-based
`loc='best'`, and Matplotlib's four-sided boxed-axes default across browser and
static exporters.

Data files under `data/` come from the handbook's repository
(`births.csv`, `california_cities.csv`) and
[jakevdp/marathon-data](https://github.com/jakevdp/marathon-data)
(`marathon-data.csv`).
