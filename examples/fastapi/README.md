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

A request whose dataset would consume over 75% of the machine's RAM (four
canonical f64 columns, 32 bytes per point) is never materialized in memory:
generation streams each column to a disk memmap (`xy._ooc.MemmapF64Builder`)
and the figure serves those files directly, the kernels paging them through
the OS cache — resident memory stays screen-bounded rather than data-bounded.
`XY_LIVE_POINTS_DIR` picks where the backing files live (default: the system
temp dir — point it at a real disk if your temp dir is a RAM-backed tmpfs);
they are removed at exit. One recorded trade rides along: an out-of-core
trace never pays a whole-file rescan per view, so deep zooms keep serving
the aggregate density surface (upsampled past the pyramid floor) instead of
drilling to exact points.

## Layout

| File | Role |
|---|---|
| `app.py` | FastAPI routes: index, `/chart/{id}`, `/drilldown`, `/api/xy/drilldown` |
| `charts.py` | `() -> xy.Chart` builders for the gallery |
| `live_drilldown.py` | The drilldown engine and its Starlette callback endpoint |
