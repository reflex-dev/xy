# reflex-xy showcase

A [Reflex](https://reflex.dev) app built on the
[`reflex-xy`](../../python/reflex-xy) adapter. Two pages: `/` walks through
the ways to link chart data into a Reflex app, and `/flights` applies the
same patterns to live real-world data. Each section carries a **Code**
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

## `/flights` — every aircraft on Earth, live

[`xy_reflex_demo/flights.py`](xy_reflex_demo/flights.py) is the same pattern
set as a throughput showcase on real sensor data. By default a background
task polls OpenSky's anonymous `/states/all` for the **whole planet**
(~12–15k aircraft) and republishes a figure var each cycle — positions
colored by altitude (turbo), sized by ground speed, with per-aircraft
trails, over the full Natural Earth 50m coastline + borders (~80k points of
`xy.segments`). Every cycle rebuilds and re-ships the entire figure as
binary columns (a single multi-MB blob on the wire) while pan/zoom stays
smooth. Clicking an aircraft follows it (altitude trail chart); shift-drag
box-selects a region and cross-filters an altitude histogram.

`XY_FLIGHTS_MODE=region` switches to the
[adsb.fi](https://github.com/adsbfi/opendata) open-data API: one 250 nm
circle (default: central Europe, ~900 aircraft), pollable down to 1 s.

If the live API is unreachable the page falls back to bundled real captures
and always opens animated — including fully offline. Region mode cycles ten
recorded frames; world mode dead-reckons a single 14k-aircraft OpenSky
capture forward along each aircraft's track at its ground speed (~270 KB
asset instead of megabytes of frames).
`xy_reflex_demo/data/regenerate.py` (stdlib-only) rebuilds all bundled
assets: `--world` for the global pair, `--center LAT,LON` to re-center the
regional pair (mirrored at runtime by `XY_FLIGHTS_CENTER`).

`XY_FLIGHTS_POLL` sets the live poll cadence in seconds. World default is 15
(OpenSky bills anonymous callers 4 credits per global snapshot from a
400/day budget); region default is 3, floor 1 (adsb.fi's documented limit is
1 request/second and its feed refreshes about once a second):

```bash
XY_FLIGHTS_MODE=region XY_FLIGHTS_POLL=1 uv run reflex run
```

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

## Interaction contract checks

Section 1's badges are event counters, and its click/select handlers
deliberately republish the cloud behind its stable token (the title's
`handler revision`). Together they make the wrapper's restore contract
manually verifiable:

1. Box-select a large area. The `select` readout shows the exact total, the
   bounded JSON row count, and `truncated`; the §2 histogram cross-filters.
   The cloud must keep both its viewport and its selection highlight across
   the republish, and the selection counter must increment exactly once.
2. Zoom until density drills into exact points, then click one. The `click`
   readout shows its canonical row ID, f64 data coordinates, and active
   keyboard modifiers; the click counter must increment exactly once.
3. Focus a point and press Enter or Space. Keyboard activation must produce
   the same click readout contract as pointer activation.
4. Clear the selection. The histogram returns to all points and the select
   counter increments exactly once again.

A runaway counter or a viewport/selection reset after any of these reveals a
republish feedback loop or a restore regression.
