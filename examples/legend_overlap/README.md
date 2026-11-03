# Legend overlap reproduction

Seven typical dashboard charts (the shapes the builder generates) where the
legend covers the data. Case 7 is the chart from the original report: stacked
horizontal bars that reach the axis maximum. Each is rendered with the default
legend (`loc=None`, fixed `upper right`), with `loc="best"` (content-aware
placement, #496), and with `loc="outside top"`, the fix: a band above the plot
that the plot shrinks to make room for (spec: `spec/api/styling.md`, *`loc="outside
top"`*).

![contact sheet](contact_sheet.png)

## Findings

- The Cartesian legend is always drawn inside the plot; no location reserves
  space beside it (`js/src/50_chartview.ts`, the note above
  `POLAR_LEGEND_ROOM_FRACTION`).
- The default is a fixed `upper right`, exactly where rising lines and the
  tallest late bars end (cases 1, 3, 5, 6).
- `loc="best"` fixes those, but cannot help when no empty corner exists:
  stacked/filled areas (case 4) and many series (case 2, a 159 px legend).
- Legend size follows label length while the plot does not shrink (case 3:
  219 px wide on a 520 px chart; case 6: a 320x200 card).
- Separate bug: the 320x200 card's wrapped title is clipped at the top.
- `loc="outside top"` clears every case. Entries wrap into rows (two rows of
  four for case 2) instead of covering the plot.
- `loc="best"` now falls back to that band when no in-plot position is empty:
  cases 2, 4, 6 and 7 resolve to `outside top`, while cases 1, 3 and 5 keep an
  empty in-plot corner (`upper left`). Before the fallback, case 7's `best`
  resolved to `upper right`, on top of the bars.
- Side effect to know about: a shorter plot can thin category tick labels.
  Case 7 drops to every other store because vertical axes target one label per
  45 px of plot height (`plot.h / 45`), which category axes inherit. That rule
  predates this change and affects any short chart.

## Reproduce

From the repo root, after building the core and the JS bundles:

```bash
uv run python examples/legend_overlap/make_cases.py   # writes html/ (git-ignored)
node examples/legend_overlap/shoot.js                 # writes png/ + report.json
```

`report.json` records each legend's resolved location, size and (for the
outside-top band) column count. Rebuild the contact sheet with:

```bash
python3 examples/legend_overlap/make_sheet.py         # writes sheet.html
node examples/legend_overlap/shoot_sheet.js           # writes contact_sheet.png
```

## Compared with matplotlib and TanStack Charts

![xy vs matplotlib vs TanStack Charts](compare/comparison.png)

Same data in every column (`compare/data.json`, dumped by
`compare/dump_data.py`). Matplotlib 3.11.1 uses its default `ax.legend()`
(`loc="best"`) with `layout="constrained"`. `@tanstack/charts` 1.2.1 uses its
default `colorLegend()`, and its SVG comes from the DOM-free `renderChartSvg`.

- **TanStack Charts never draws the legend over the plot.** Its
  `ChartLegendPlacement` is only `'top' | 'bottom'`, and the legend reserves
  its own layout height, so the plot shrinks instead. All six cases are clean,
  including stacked areas and 8 series (which wrap to a second row).
- **matplotlib's `"best"` fails the same way xy's `"best"` does.** It covers
  data on the 8-series, stacked-area and small-card charts, because every
  in-plot position overlaps something.
- TanStack's one weak spot: with long names, the equal-width legend columns
  let labels run into each other. That is with the DOM-free renderer's text
  estimate; its docs say `colorLegendItems({ justify: "start" })` wraps labels
  using the host's text measurer when mounted in a browser.

Reproduce (TanStack needs `npm install @tanstack/charts` in a scratch folder
containing `tanstack_render.mjs` and `data.json`):

```bash
uv run python examples/legend_overlap/compare/dump_data.py examples/legend_overlap/compare/data.json
uv run --with matplotlib python examples/legend_overlap/compare/matplotlib_render.py examples/legend_overlap/compare
node tanstack_render.mjs   # writes svg/; copy into compare/tanstack/
```
