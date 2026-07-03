# fastcharts Reflex Example

A small Reflex dashboard that embeds standalone fastcharts charts.

The app uses fastcharts' `Figure.to_html()` export as the bridge: generated HTML
charts live under `assets/charts/`, and the Reflex UI displays them in iframes.
This keeps the example pure Python while exercising the same WebGL2 renderer
used by notebooks and standalone exports.

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
| Decimated line | `assets/charts/line_walk.html` | 120k-point time-series line |
| Colored scatter | `assets/charts/colored_scatter.html` | 60k points with color and size channels |
| Density scatter | `assets/charts/density_scatter.html` | 250k points rendered as a density surface |

Regenerate the chart assets any time with:

```bash
python scripts/build_charts.py
```
