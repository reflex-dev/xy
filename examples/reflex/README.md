# xy Reflex Example

A small Reflex dashboard that embeds standalone xy charts plus a live
100M-point drilldown chart.

The app uses xy' `Figure.to_html()` export as the bridge: generated HTML
charts live under `assets/charts/`, and the Reflex UI displays them in iframes.
This keeps the example pure Python while exercising the same WebGL2 renderer
used by notebooks and standalone exports.

The live drilldown chart adds one Reflex backend route at
`/api/xy/drilldown`. Its iframe starts from a 100M-point density payload
and requests exact visible points from Python after zooming into a small region.

## Run

```bash
cd examples/reflex
uv venv
uv pip install -r requirements.txt
python scripts/build_charts.py
reflex run
```

Then open the URL printed by Reflex, usually `http://localhost:3000`.

## Charts Included

| Chart | File | What it shows |
|---|---|---|
| Live drilldown scatter | `assets/charts/live_drilldown_100m.html` | 100M-point adaptive LOD through the Reflex backend |
| Business overview | `assets/charts/business_overview.html` | Small grouped revenue and pipeline columns for normal dashboard data |
| Retention cohort | `assets/charts/retention_cohort.html` | Small product analytics heatmap for ordinary cohort retention |
| Decimated line | `assets/charts/line_walk.html` | 120k-point time-series line |
| Filled area | `assets/charts/area.html` | 80k-point filled time series with a baseline |
| Colored scatter | `assets/charts/colored_scatter.html` | 10M points with color and size channels, aggregated for export |
| Plotly Scattergl | `assets/charts/plotly_colored_scatter.html` | 100k sampled points from the colored scatter distribution |
| Density scatter | `assets/charts/density_scatter.html` | 10M points rendered as a responsive density surface |
| Histogram | `assets/charts/histogram.html` | 500k values binned into the shared rectangle renderer |
| Histogram with x-only zoom | `assets/charts/histogram_x_zoom.html` | Wheel, toolbar, and box zoom change x while y remains fixed |
| Box zoom drag mode | `assets/charts/box_zoom_drag.html` | Plain drag zooms the histogram x range; double-click resets the view |
| Grouped bars | `assets/charts/bar_column.html` | Category-axis grouped bars using the shared rectangle renderer |
| Stacked bars | `assets/charts/stacked_bar.html` | Stacked column bars using the shared rectangle renderer |
| Horizontal bars | `assets/charts/horizontal_bar.html` | Category-axis horizontal bars using the shared rectangle renderer |
| 100% stacked bars | `assets/charts/normalized_bar.html` | Per-category series normalized to a consistent 100% total |
| Diverging bars | `assets/charts/diverging_bar.html` | Positive and negative change with direct value labels |
| Rounded goal bars | `assets/charts/rounded_goal_bar.html` | Gradient fills, rounded corners, labels, and a target rule |
| Heatmap | `assets/charts/heatmap.html` | Matrix values rendered as colored cells on categorical axes |

Regenerate the chart assets any time with:

```bash
PYTHONPATH=../python uv run python scripts/build_charts.py
```
