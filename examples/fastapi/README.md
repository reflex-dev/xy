# xy FastAPI example

A [FastAPI](https://fastapi.tiangolo.com/) app that serves xy charts, showing
how the library is used from a Python web stack other than Reflex.

Each chart is generated on request with `chart.to_html()`, and the **Code**
accordion under each chart shows the builder's source via `inspect.getsource`.

Two integration surfaces:

- **Static export tier** — `GET /chart/{id}` renders a builder from
  [`charts.py`](charts.py) to standalone HTML. Pan, zoom, and hover resolve in
  the browser.
- **Server drilldown tier** — `GET /drilldown` serves a 100M-point scatter
  whose density surface refines into exact points on zoom, using
  `POST /api/xy/drilldown` (a Starlette endpoint in
  [`live_drilldown.py`](live_drilldown.py)) for the view round-trips. Each
  reply is an `XYBF` binary frame — compact JSON metadata plus raw f32/u8
  buffers — decoded in the browser with the bundled `xy.decodeFrame`, so the
  density grids and point buffers that dominate a drill never pay a base64
  encode/decode or its ~33% inflation.

## Run

```bash
cd examples/fastapi
uv run uvicorn app:app --reload
```

`uv run` resolves this directory's [`pyproject.toml`](pyproject.toml) (xy,
FastAPI, uvicorn) into a local environment. Open the printed URL (usually
<http://127.0.0.1:8000>).

`XY_LIVE_POINTS` sets the drilldown demo's point count, which is built lazily
on first use:

```bash
XY_LIVE_POINTS=1000000 uv run uvicorn app:app
```

Drill-to-points works at any count. Below the engine's no-rescan bound
(`xy.config.PYRAMID_NO_RESCAN_ROWS`, 200M) each drill finds its rows with an
O(N) window scan; above it that scan is forbidden (LOD doc §28), so at
startup the demo builds the Tier-3 **drill index** (`fig.ensure_drill_index`)
— cell-sorted positions, canonical row ids, and wire-quantized channel
planes, ~14 B/point in a temp directory — and deep zooms keep resolving into
exact points (identical replies, exact hover) at O(window) cost. If a view is
ever served past the pyramid's resolution without an index (for example, an
out-of-band figure without one), the badge reads `… density · aggregate
floor`.

## Layout

| File | Role |
|---|---|
| `app.py` | FastAPI routes: index, `/chart/{id}`, `/drilldown`, `/api/xy/drilldown` |
| `charts.py` | `() -> xy.Chart` builders for the gallery |
| `live_drilldown.py` | The drilldown engine and its Starlette callback endpoint |
