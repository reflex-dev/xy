# Core Declarative Chart Grammar

**Status:** API design proposal. Goal: fix the composition model **before**
the catalog grows to 40 kinds, so nothing here forces a public-API rewrite
later. Grounded in what ships today (`components.py`: `Chart` + `Mark` +
`Axis` + `Legend`, `_MARK_APPLIERS` registry; `figure.py`: fluent builders +
`_emit_<kind>` dispatch) — the proposal is an *extension* of that shape, not
a replacement.

Related: `reflex-shaped-api.md` covers the public API/styling proposal for a
Reflex-like component surface without making Reflex a core dependency.

## 1. The model in one paragraph

A **Figure** is a grid of **Panels** (1×1 today; faceting/subplots later).
A Panel owns **Scales** (x, y, and later y2) and a z-ordered list of
**Marks**. A Mark = kind + data bindings + style props + optional channel
encodings. Axes, legend, and title are Panel/Figure chrome that *read* scales
and marks — they never own data. Everything is a plain declarative node
(dataclass), composable as children, and compiles to the existing internal
engine figure + wire spec. One public front door over that engine:

- **Compositional (Reflex-flavored):** `fc.chart(fc.scatter(...), fc.line(...),
  fc.x_axis(...))` — declarative, component-tree shaped, what a Reflex wrapper
  serializes naturally. (The internal `_figure.Figure` fluent methods share the
  same mark implementations, so the vocabulary cannot fork.)

Rule G0: **the public composition API and the internal mark core are the same
vocabulary** (same mark names, same prop names, same defaults — one
implementation in `marks.py`). This is already true and is the thing we must
not break.

## 2. The layering/overlay rules (what makes composition sound)

- **G1 — Marks layer by order.** Children render in listed order (painter's
  model). No z-index prop until a real need appears.
- **G2 — One shared coordinate space per panel.** All marks in a panel share
  x and y scales; autorange is the union of every mark's `range_for(axis)`
  contribution (already the per-kind hook in `Trace.range_for`). A mark never
  gets a private scale — the escape hatch is a second *panel*, or (later,
  explicit) `y_axis(secondary=True)` creating a named y2 scale that marks
  opt into with `axis="y2"`. Silent dual axes are how charts lie; y2 must be
  loud.
- **G3 — Scale type is a panel decision** (`linear | time | log | category`),
  auto-inferred from marks (time columns → time; bar categories → category)
  but overridable on the axis node. Mixing marks whose natural scales
  conflict (bar-category + scatter-linear x) is a build-time error with a
  fix-it message, not a coercion.
- **G4 — Chrome reads, never owns.** Legend derives entries from mark
  channel modes (already true); axes derive from scales; tooltips derive
  from the hovered mark's readout row. Adding a mark kind never edits chrome
  code (contract already enforces this via capabilities).
- **G5 — Declarative all the way down.** Every node is data (kind + props).
  No callbacks in the tree except the event props (`on_hover`, `on_select`,
  later `on_view_change`), which is exactly what a Reflex component can
  serialize + wire to server events without escape hatches.

## 3. The 10 common charts (all expressible today or with planned nodes)

```python
import fastcharts as fc

# 1. line
fc.chart(fc.line(x="date", y="close", data=df), title="Price")
# 2. multi-series line (wide → long handled by repeated marks)
fc.chart(fc.line(x="date", y="aapl", data=df, name="AAPL"),
         fc.line(x="date", y="msft", data=df, name="MSFT"), fc.legend())
# 3. scatter with channels
fc.chart(fc.scatter(x="gdp", y="life", color="continent", size="pop", data=df))
# 4. big scatter (auto density tier — same call, no special API)
fc.chart(fc.scatter(x="x", y="y", data=ten_million_rows))
# 5. area
fc.chart(fc.area(x="date", y="active_users", data=df))
# 6. histogram
fc.chart(fc.histogram(values="latency_ms", bins=256, data=df))
# 7. bar
fc.chart(fc.bar(x="region", y="revenue", data=df))
# 8. horizontal bar
fc.chart(fc.bar(y="region", x="revenue", data=df, orientation="h"))
# 9. heatmap
fc.chart(fc.heatmap(z=matrix, colormap="viridis"))
# 10. time series with unit-scale y
fc.chart(fc.line(x="ts", y="value", data=df), fc.y_axis(label="watts"))
```

(`fc.chart` is the kind-neutral container; the existing `scatter_chart`/
`line_chart`/… wrappers remain as readable aliases — they already just tag
`Chart(kind_str, children)`.)

## 4. The 5 complex overlays (the composition stress tests)

```python
# A. line-on-scatter (regression overlay) — shared scales, order = layering
fc.chart(
    fc.scatter(x="x", y="y", data=df, opacity=0.4),
    fc.line(x=xs_fit, y=ys_fit, color="var(--accent)", width=2),
)

# B. area-under-line (band + emphasis line)
fc.chart(
    fc.area(x="date", y="p95", base="p5", data=df, opacity=0.25, name="p5-p95"),
    fc.line(x="date", y="median", data=df, name="median"),
)

# C. histogram + KDE-style line
fc.chart(
    fc.histogram(values="dur", bins=200, density=True, data=df),
    fc.line(x=kde_x, y=kde_y, width=2),
)

# D. volume-under-candles (finance pane pair) — PANELS, not one panel:
fc.figure(
    fc.panel(fc.candlestick(x="t", open="o", high="h", low="l", close="c", data=df),
             height=3),
    fc.panel(fc.bar(x="t", y="volume", data=df), height=1),
    link_x=True,   # shared x scale + synced pan/zoom across panels
)

# E. threshold rule + annotated scatter
fc.chart(
    fc.scatter(x="x", y="y", color="cluster", data=df),
    fc.rule(y=0.8, color="#ef5350", dash=True),      # planned: rule mark
    fc.label(x=3.2, y=0.85, text="SLA"),             # planned: label mark
)
```

D is the deliberate boundary case: volume-under-candles is **not** an overlay
(different y meaning) — the grammar answers it with linked panels, matching
the "chart owns rendering, app owns chrome" decision already taken. `link_x`
is the chart-level primitive (one shared x scale + view sync); arranging the
panes is layout the Figure grid owns.

## 5. Node vocabulary (target; ★ = exists today)

- Containers: `figure` (grid of panels; today implicit 1×1), `panel`
  (planned), `chart` ★ (sugar: figure with one panel).
- Marks ★: `scatter, line, area, histogram, bar/column, heatmap` (+ every
  future kind — one `Mark` node each, registry-dispatched).
- Annotation marks (planned, same Mark machinery, tiny data): `rule`,
  `band`, `label`.
- Chrome: `x_axis`/`y_axis` ★ (grows `type_="log"|"category"` ★partial,
  `secondary=True` later), `legend` ★, `title` (prop today, node later
  if styling demands).
- Events ★: `on_hover`, `on_select`; planned `on_view_change` (viewport for
  server-driven cross-filtering in Reflex apps).

## 6. Reflex integration (no escape hatches)

The tree above is precisely a Reflex component tree's shape: snake_case
props, children composition, `data=` + column-name resolution (`data_key`
idiom), event props. It remains a FastCharts-owned tree, not a Reflex object,
so the core package keeps zero Reflex dependencies. A future Reflex wrapper is
therefore a *thin* codegen layer:

1. Each `fc.*` factory maps 1:1 to a Reflex component; props serialize as-is
   (they're plain scalars/strings/arrays).
2. Data flows as the existing binary payload through a Reflex asset/endpoint
   (the 100M live-drilldown demo already proves the comm shape: a `comm`
   object with `send`/`onMessage` over any transport).
3. Events (`on_hover/on_select/on_view_change`) map to Reflex event handlers;
   payloads are the same dicts the widget path already emits.
4. State-driven restyle = re-render with new props; data identity is kept by
   the column-store handles so unchanged columns don't re-ship (buffer-diff
   updates, dossier §6 — planned, and this is the API that needs it).

Anti-goals, stated so they stay out: no `raw_plotly_json`-style passthrough
node, no per-mark imperative `draw(ctx)` callback, no CSS-in-props for mark
geometry (theming stays on the `--chart-*` token path).

## 7. Migration & compatibility

- Everything shipped keeps working: `chart(...)` is additive sugar;
  `panel`/`figure` introduce multi-pane without touching single-pane specs
  (spec gains `panels: [...]` only when >1 — protocol bump at that point,
  bundled with the view-message unification the contract already schedules).
- The wire spec keeps its current per-trace shape; panels reference traces by
  id. Scales become explicit spec objects (`scales: {x: {...}, y: {...}}`)
  in the same bump — currently implicit in `x_axis/y_axis` ranges.
- The `Chart(kind_str, ...)` wrappers never encoded behavior (kind string is
  cosmetic) — safe to keep forever.

## 8. Implementation order

1. `fc.chart` neutral container + `rule`/`band`/`label` annotation marks
   (small, high leverage for real dashboards).
2. Explicit scale objects in the spec + `category`/`log` axis completion.
3. `panel`/`figure` grid + `link_x` view sync (enables finance pair, subplot
   grids; carries the protocol bump).
4. `y2` secondary scale (loud opt-in).
5. Faceting sugar (`facet(col="…")`) compiling to the panel grid.
