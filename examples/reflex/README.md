# reflex-xy showcase

A [Reflex](https://reflex.dev) app built on the
[`reflex-xy`](../../python/reflex-xy) adapter. One page walks through the ways
to link chart data into a Reflex app, and each section carries a **Code**
accordion showing its source via `inspect.getsource`.

Chart data rides the app's own websocket as a second socket.io namespace of
binary columns; Reflex state holds only a token string per chart.

## What it shows

1. **Live figure var + events** — a 1M-point drillable scatter from an
   `@reflex_xy.figure` method, with `on_point_hover` / `on_point_click` /
   `on_select_end` handlers.
2. **A chart driven by state vars** — a histogram whose bin count is a slider
   and whose data is cross-filtered by the selection above; changing either
   recomputes and re-publishes the figure under a stable token.
3. **A dynamically updating chart** — a line grown by a background task via
   `reflex_xy.append`.
4. **Data computed from `on_view_change`** — pan/zoom an overview and a detail
   histogram recomputes from the points in the reported window.
5. **Fixed data, two ways** — a `xy.Chart` passed straight to `reflex_xy.chart`
   (static payload tier) and a `reflex_xy.inline` token (fixed data served
   through the kernel).

## Run

```bash
cd examples/reflex
uv run reflex run
```

`uv run` resolves this directory's [`pyproject.toml`](pyproject.toml) (xy,
reflex-xy) into a local environment. Open the URL Reflex prints (usually
<http://localhost:3000>). Zoom into the cloud to drill density into exact
points; box-select to cross-filter the histogram; press **go live** to stream.

The adapter is wired in one line — `plugins=[reflex_xy.XYPlugin()]` in
[`rxconfig.py`](rxconfig.py).
