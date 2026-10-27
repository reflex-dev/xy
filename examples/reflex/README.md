# XY Reflex showcase

A [Reflex](https://reflex.dev) app built with the `xy[reflex]` integration.
One page walks through the ways to link chart data into a Reflex app, and each
section carries a **Code** accordion showing its source via
`inspect.getsource`.

Chart data rides the app's own websocket as a second socket.io namespace of
binary columns; Reflex state holds only a tiny handle per chart. Charts use
the data-bound component API — structure declared in the page, compiled to a
validated plan at `reflex run`, columns supplied by `@reflex_xy.data` —
except where a section demonstrates the tier its behavior genuinely needs.

## What it shows

1. **The flagship, data-bound** — a 1M-point drillable scatter composed in
   the page (`reflex_xy.chart(xy.scatter("x", "y", ...), data=Demo.cloud)`)
   with `on_point_hover` / `on_point_click` / `on_select_end` handlers;
   `@reflex_xy.data` supplies only the columns.
2. **The escape hatch: structure from state** — a histogram whose bin count
   is a slider. Bins are chart *structure*, not columns, so this is an
   `@reflex_xy.figure` method; its data is also cross-filtered by the
   selection above, and changing either re-publishes the figure under a
   stable token.
3. **A dynamically updating chart** — a line grown by a background task via
   `reflex_xy.append`.
4. **Data computed from `on_view_change`** — pan/zoom a data-bound overview;
   a second data var reads the reported window from state and republishes
   only the in-view column into the detail histogram's fixed plan.
5. **Fixed data, two ways** — concrete columns passed as `data=` to a
   composed chart (compiled to a static payload asset, no kernel) and a
   `reflex_xy.inline` token (fixed data served through the kernel).
6. **The 100M drilldown, adapter-native** — the live drilldown scatter
   from [`examples/fastapi`](../fastapi) (identical seed-11 data and mark
   config, a density surface that drills into exact points on zoom) as a
   single `reflex_xy.inline` token. The FastAPI app hand-rolls its transport
   for this chart (a Starlette endpoint plus an HTTP comm bridge); here the
   adapter's websocket namespace and the kernel's density tiers do all of it,
   so behavioral differences between the two apps isolate what that custom
   code adds.
7. **Legend hover-highlight and click-to-toggle** — named series on the
   direct-Chart tier (hover dims, click hides client-side) beside a
   categorical density scatter on an `inline()` token whose category clicks
   re-bin kernel-side with the category masked out.
8. **Column republish under a stable handle** — the flat form of the same
   API as §1 (`reflex_xy.scatter_chart(data=Demo.bound_cloud, x="x", ...)`);
   a slider republishes only the columns while the compile-validated plan,
   viewport, and selection stay put.
9. **`rx.cond` + `rx.foreach`** — a toggle conditionally swaps a composed
   three-series board for `rx.foreach` small multiples over a
   `list[DataHandle[SensorCols]]` var: one plan mounted once per handle,
   column names compile-checked inside the loop, both cond branches
   validated at `reflex run`.

## Run

```bash
cd examples/reflex
uv run reflex run
```

`uv run` resolves this directory's [`pyproject.toml`](pyproject.toml)
(`xy[reflex]`) into a local environment. Open the URL Reflex prints (usually
<http://localhost:3000>). Zoom into the cloud to drill density into exact
points; box-select to cross-filter the histogram; press **go live** to stream.

`XY_LIVE_POINTS` sets §6's point count — the same override the FastAPI app
honors, so both apps build the identical dataset at any size. Unlike the
FastAPI app (lazy, on first use) the columns are built at import, because
`inline()` registers at module scope; the default 100M costs a few gigabytes
of RAM and some startup seconds, so dial it down on small machines:

```bash
XY_LIVE_POINTS=1000000 uv run reflex run
```

The adapter is wired in one line — `plugins=[reflex_xy.XYPlugin()]` in
[`rxconfig.py`](rxconfig.py).

## Interaction contract checks

Section 1's badges are event counters, §2's histogram republishes on every
box-selection (the cross-filter), and §8's slider republishes columns under a
stable handle. Together they make the integration's restore contract manually
verifiable:

1. Box-select a large area of the cloud. The `select` readout shows the exact
   total, the bounded JSON row count, and `truncated`; the §2 histogram
   cross-filters. The cloud must keep both its viewport and its selection
   highlight, and the selection counter must increment exactly once.
2. Zoom until density drills into exact points, then click one. The `click`
   readout shows its canonical row ID, f64 data coordinates, and active
   keyboard modifiers; the click counter must increment exactly once.
3. Focus a point and press Enter or Space. Keyboard activation must produce
   the same click readout contract as pointer activation.
4. Clear the selection. The histogram returns to all points and the select
   counter increments exactly once again.
5. Drag the §8 slider. The bound scatter repaints at the new point count
   while keeping its viewport — the plan (and the chart's identity) never
   changes, only the columns.

A runaway counter or a viewport/selection reset after any of these reveals an
event feedback loop or a restore regression.
