# fastcharts Reflex Example

A small Reflex dashboard that embeds standalone fastcharts charts plus a live
10M-point drilldown chart.

The app uses fastcharts' `Figure.to_html()` export as the bridge: generated HTML
charts live under `assets/charts/`, and the Reflex UI displays them in iframes.
This keeps the example pure Python while exercising the same WebGL2 renderer
used by notebooks and standalone exports.

The live drilldown chart adds one Reflex backend route at
`/api/fastcharts/drilldown`. Its iframe starts from a 10M-point density payload
and requests exact visible points from Python after zooming into a small region.

## Run

```bash
cd reflex_fastcharts_app
uv venv
uv pip install -r requirements.txt
python scripts/build_charts.py
reflex run
```

Then open the URL printed by Reflex, usually `http://localhost:3000`.

## Charts Included

| Chart | File | What it shows |
|---|---|---|
| Live drilldown scatter | `assets/charts/live_drilldown_10m.html` | 10M-point adaptive LOD through the Reflex backend |
| Decimated line | `assets/charts/line_walk.html` | 120k-point time-series line |
| Colored scatter | `assets/charts/colored_scatter.html` | 10M points with color and size channels, aggregated for export |
| Plotly Scattergl | `assets/charts/plotly_colored_scatter.html` | 100k sampled points from the colored scatter distribution |
| Density scatter | `assets/charts/density_scatter.html` | 10M points rendered as a responsive density surface |

Regenerate the chart assets any time with:

```bash
python scripts/build_charts.py
```
