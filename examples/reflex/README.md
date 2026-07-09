# fastcharts Reflex Example

A small Reflex dashboard that embeds standalone fastcharts charts plus live
100M-point and synthetic 1B-point drilldown charts.

The app uses fastcharts' `Figure.to_html()` export as the bridge: generated HTML
charts live under `assets/charts/`, and the Reflex UI displays them in iframes.
This keeps the example pure Python while exercising the same WebGL2 renderer
used by notebooks and standalone exports.

The live drilldown charts add one Reflex backend route at
`/api/fastcharts/drilldown`. Their iframes start from density payloads and
request refined density or visible points from Python after zooming into a small
region.

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
| Live 1B drilldown scatter | `assets/charts/live_drilldown_1b.html` | Synthetic 1B-point adaptive LOD through the Reflex backend |
| Live 100M drilldown scatter | `assets/charts/live_drilldown_100m.html` | 100M-point adaptive LOD through the Reflex backend |
| Business overview | `assets/charts/business_overview.html` | Small grouped revenue and pipeline columns for normal dashboard data |
| Retention cohort | `assets/charts/retention_cohort.html` | Small product analytics heatmap for ordinary cohort retention |
| Finance layer editor | `assets/charts/candlestick_editor.html` | Candlestick chart with a drag/drop palette for finance drawings and studies |
| Candlestick chart | `assets/charts/candlestick.html` | Standalone OHLC export used by the editor demo |
| Decimated line | `assets/charts/line_walk.html` | 120k-point time-series line |
| Filled area | `assets/charts/area.html` | 80k-point filled time series with a baseline |
| Colored scatter | `assets/charts/colored_scatter.html` | 10M points with color and size channels, aggregated for export |
| Plotly Scattergl | `assets/charts/plotly_colored_scatter.html` | 100k sampled points from the colored scatter distribution |
| Density scatter | `assets/charts/density_scatter.html` | 10M points rendered as a responsive density surface |
| Histogram | `assets/charts/histogram.html` | 500k values binned into the shared rectangle renderer |
| Grouped bars | `assets/charts/bar_column.html` | Category-axis grouped bars using the shared rectangle renderer |
| Stacked bars | `assets/charts/stacked_bar.html` | Stacked column bars using the shared rectangle renderer |
| Horizontal bars | `assets/charts/horizontal_bar.html` | Category-axis horizontal bars using the shared rectangle renderer |
| Heatmap | `assets/charts/heatmap.html` | Matrix values rendered as colored cells on categorical axes |
| Candlestick + finance layers | `assets/charts/candlestick.html` | OHLC candles with overlays, volume, and risk drawing layers |

Regenerate the chart assets any time with:

```bash
PYTHONPATH=../python uv run python scripts/build_charts.py
```
