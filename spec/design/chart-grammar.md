# Core Declarative Chart Grammar

**Status:** API design proposal. Goal: fix the composition model **before**
the catalog grows to 40 kinds, so nothing here forces a public-API rewrite
later. Grounded in what ships today (`python/xy/components.py`: `Chart` +
`Mark` + `Axis` + `Legend`, `_MARK_APPLIERS` registry; `python/xy/marks.py`:
the mark implementations, bound as `Figure`'s fluent methods at
`python/xy/_figure.py:340-362` so `Figure.scatter is marks.scatter`;
`python/xy/_payload.py:278`: the `_emit_<kind>` dispatch
(`getattr(self, f"_emit_{t.kind}", None)`), reachable on `Figure` through
`PayloadMixin`) — the proposal is an *extension* of that shape, not a
replacement.

Related: `reflex-shaped-api.md` covers the public API/styling proposal for a
Reflex-like component surface without making Reflex a core dependency.

## 1. The model in one paragraph

A **Figure** is a grid of **Panels** (1×1 today; subplots later).
A Panel owns **Scales** (any number of named x/y axis ids) and a z-ordered
list of **Marks**. A Mark = kind + data bindings + style props + optional channel
encodings. Axes, legend, and title are Panel/Figure chrome that *read* scales
and marks — they never own data. Everything is a plain declarative node
(dataclass), composable as children, and compiles to the existing internal
engine figure + wire spec. One public front door over that engine:

- **Compositional (Reflex-flavored):** `xy.chart(xy.scatter(...), xy.line(...),
  xy.x_axis(...))` — declarative, component-tree shaped, what a Reflex wrapper
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
  x and y scales; autorange is the union of every mark's contributing columns.
  The per-kind hook is `Figure._range_columns(trace, axis_id)`
  (`python/xy/_figure.py:1024`), which switches on `trace.kind` — area and
  error_band contribute `[y, base]`, triangle_mesh `[x0, x1, x]`, rect-like
  kinds `[x0, x1]` — and the union, padding, and log clamping happen in
  `Figure._range` (`python/xy/_figure.py:840`). The hook lives on `Figure`,
  not on `Trace`. A mark never gets a private scale — the escape hatch is a
  second *panel*, or an explicit named scale ★: `xy.y_axis(id="y2",
  side="right")` plus `mark(..., y_axis="y2")`. Silent dual axes are how
  charts lie, so y2 is loud by construction: every mark factory takes
  `x_axis`/`y_axis` id strings, and referencing an id with no matching axis
  node is a build error (`… has no matching xy.y_axis(id='y2')`,
  `python/xy/components.py:3828`).
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
  No callbacks in the tree except the event props (`on_hover`, `on_click`,
  `on_brush`, `on_select`, `on_view_change`), which is exactly what a Reflex
  component can serialize + wire to server events without escape hatches.

## 3. The 10 common charts (all expressible today or with planned nodes)

```python
import xy

# 1. line
xy.chart(xy.line(x="date", y="close", data=df), title="Price")
# 2. multi-series line (wide → long handled by repeated marks)
xy.chart(xy.line(x="date", y="aapl", data=df, name="AAPL"),
         xy.line(x="date", y="msft", data=df, name="MSFT"), xy.legend())
# 3. scatter with channels
xy.chart(xy.scatter(x="gdp", y="life", color="continent", size="pop", data=df))
# 4. big scatter (auto density tier — same call, no special API)
xy.chart(xy.scatter(x="x", y="y", data=ten_million_rows))
# 5. area
xy.chart(xy.area(x="date", y="active_users", data=df))
# 6. histogram
xy.chart(xy.histogram(values="latency_ms", bins=256, data=df))
# 7. bar
xy.chart(xy.bar(x="region", y="revenue", data=df))
# 8. horizontal bar (x is always the category arg; orientation moves it to y)
xy.chart(xy.bar(x="region", y="revenue", data=df, orientation="horizontal"))
# 9. heatmap
xy.chart(xy.heatmap(z=matrix, colormap="viridis"))
# 10. time series with unit-scale y
xy.chart(xy.line(x="ts", y="value", data=df), xy.y_axis(label="watts"))
```

(`xy.chart` is the kind-neutral container; the existing `scatter_chart`/
`line_chart`/… wrappers remain as readable aliases — they already just tag
`Chart(kind_str, children)`.)

## 4. The 5 complex overlays (the composition stress tests)

```python
# A. line-on-scatter (regression overlay) — shared scales, order = layering
xy.chart(
    xy.scatter(x="x", y="y", data=df, opacity=0.4),
    xy.line(x=xs_fit, y=ys_fit, color="var(--accent)", width=2),
)

# B. area-under-line (band + emphasis line)
xy.chart(
    xy.area(x="date", y="p95", base="p5", data=df, opacity=0.25, name="p5-p95"),
    xy.line(x="date", y="median", data=df, name="median"),
)

# C. histogram + KDE-style line
xy.chart(
    xy.histogram(values="dur", bins=200, density=True, data=df),
    xy.line(x=kde_x, y=kde_y, width=2),
)

# D. volume-under-candles (finance pane pair) — PANELS, not one panel:
xy.figure(
    xy.panel(xy.candlestick(x="t", open="o", high="h", low="l", close="c", data=df),
             height=3),
    xy.panel(xy.bar(x="t", y="volume", data=df), height=1),
    link_x=True,   # shared x scale + synced pan/zoom across panels
)

# E. threshold rule + annotated scatter
xy.chart(
    xy.scatter(x="x", y="y", color="cluster", data=df),
    xy.hline(0.8, color="#ef5350"),                  # rule annotation
    xy.label(3.2, 0.85, "SLA"),                      # text annotation
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
- Marks ★: `scatter, line, area, histogram, bar/column, heatmap, errorbar,
  error_band, box, violin, ecdf, hexbin, contour, step, stairs, stem` (+ every
  future kind — one `Mark` node each, registry-dispatched).
- Annotations ★ (tiny data): rules `hline`/`vline`/`threshold`, bands
  `x_band`/`y_band`/`threshold_zone`, and `label`/`text`/`marker`/`arrow`/
  `callout`. These are not literally Mark nodes: they compile to an
  `Annotation` node dispatched through `_ANNOTATION_APPLIERS`
  (`python/xy/components.py:4370`), a sibling registry to `_MARK_APPLIERS`
  (`components.py:4347`) with the same kind→applier shape.
- Chrome: `x_axis`/`y_axis` ★ (take `id=`, so named secondary scales are
  already expressible; grows `type_="log"|"category"` ★partial), `legend` ★,
  `title` (prop today, node later if styling demands).
- Events ★: `on_hover`, `on_click`, `on_brush`, `on_select`,
  `on_view_change`. All five are `Chart` constructor params
  (`python/xy/components.py:2559-2563`), fields of `ChannelCallbacks`
  (`python/xy/channel.py:90-94`), and dispatched by the channel layer
  (`handle_message` for hover/click/view_change, `_selection_reply` for
  brush/select);
  `on_view_change` carries the viewport for server-driven cross-filtering
  and is wired in the Reflex wrapper
  (`python/reflex-xy/reflex_xy/component.py:85`).
- Animation ★: `animation` is a chart child supplying the default
  entrance/update/exit policy; mark-level `animation=` overrides it and
  `key=` supplies stable data identity. Lifecycle callbacks are fields of the
  animation child. The full grammar, bounded matching rules, and host behavior
  are specified in [animation.md](animation.md).
- Interaction ★: `interaction_config` — see §5.1.
- Faceting ★: `facet_chart` — see §5.2.

### 5.1 `interaction_config` — the gesture and event switchboard

`xy.interaction_config(...)` (`python/xy/components.py:2424`) builds an
`Interaction` node (`components.py:291`) carrying nine behavioral switches
plus two cross-chart linking props. Every switch defaults to `None`, meaning
"unset"; the renderer resolves an unset switch through
`ChartView._interactionFlag(name, fallback)`
(`js/src/50_chartview.js:436`), which treats only the literal `true` as on:

| Switch | Default when unset | Effect |
| --- | --- | --- |
| `hover` | off | Pointer motion emits hover events and drives the tooltip. |
| `click` | off | Picked marks emit click events. |
| `crosshair` | off | Plot-aligned hover guides are created. |
| `view_change` | off | Pan/zoom/reset emit range events. |
| `select` | on | Shift-drag box selection. |
| `brush` | on | Brush selection (also requires `select`). |
| `pan` | on | Plain-drag pan. |
| `zoom` | on | Wheel, box zoom, double-click reset, modebar zoom. |
| `navigation` | on | Master gate: when off, neither pan nor zoom gestures run. |

`navigation` is checked before `pan` and `zoom` at each gesture site
(`js/src/53_interaction.js:112`, `:240`, `:251`), so it disables pointer
navigation wholesale while leaving `pan`/`zoom` as the finer-grained
switches.

The Python side sets these implicitly from the callbacks a `Chart` was given:
`hover`, `click`, `brush`, `select`, and `view_change` are emitted as `True`
exactly when the matching handler is present (`components.py:2736-2740`).
That pass runs *last* — after the chart-level keywords (`components.py:2708`)
and after any `interaction_config` nodes (`:2722`) — and it overwrites rather
than defaults: `on_hover=` together with `hover=False` yields `hover=True`.
[interaction.md](../api/interaction.md) §1 is the authority on resolution order.

Channel traffic follows `view_change` specifically. `_emitViewChange`
(`js/src/50_chartview.js:460`) coalesces to one `requestAnimationFrame`, and
sends `comm.send({type: "view_change", …})` only when the flag is on — so
disabling it removes the per-viewport server round-trip while leaving local
pan/zoom fully interactive.

**Cross-chart linking.** `link_group` is an opaque identifier; charts sharing
one join the `BroadcastChannel` named `` `xy:${group}` ``
(`js/src/50_chartview.js:487`). `link_axes` defaults to `("x", "y")` and is
filtered to those two names at runtime; only the listed dimensions of the
broadcast view are copied onto the receiving chart. Semantics that matter:

- What propagates is the **view window** (`x0/x1/y0/y1`), not data, selection,
  or scale type. A receiver ignores messages tagged with its own source id, so
  linking does not echo.
- A receiver applies a linked view only if `pan` or `zoom` is enabled
  (`js/src/50_chartview.js:514`); a fully navigation-locked chart broadcasts
  but does not follow.
- Being in a link group makes a chart compute view events even with
  `view_change` off — it broadcasts locally without sending to the server.
- Selections propagate only under the separate `link_select` wire flag
  (range, polygon, or clear — `js/src/50_chartview.js:491`), applied without
  re-dispatching events so linked charts do not feed back. `link_select` is
  public through `Figure.set_interaction(link_select=…)` (`_figure.py:257`,
  applied at `:270`) and through `facet_chart(link_select=True)`
  (`components.py:3679`). It is the one linking switch with no
  `interaction_config` parameter.

### 5.2 `facet_chart` — small multiples

`xy.facet_chart(*children, by, cols=3, share_x=True, share_y=True, link=None,
link_select=False, gap=12)` (`python/xy/components.py:4480`, class at
`:3511`) repeats the child composition once per distinct value of `by`.
`by` is required (`TypeError` when omitted), `cols` must be a positive
integer, and `gap` a non-negative one.

- **Panel derivation and order.** `by` resolves to a column of the
  chart-level data or to a per-row array (`python/xy/facets.py:79`). Rows
  group by their `category_label` display string — matching categorical
  channels — and panels appear in **first-seen row order**, not sorted order;
  the `np.unique` fast path explicitly restores first-seen order
  (`facets.py:108-113`). Each panel is built over its row subset
  (`_subset_data`, `facets.py:24`).
- **Layout.** `cols` is the maximum column count; rows are
  `ceil(n_panels / cols)` and one panel is
  `max(120, (width - (cols - 1) * gap) // cols)` pixels wide
  (`FacetGrid.rows`, `FacetGrid.panel_width`, `facets.py:146-154`). Each
  panel's chart title is its facet label.
- **`share_x` / `share_y` are global, not per-panel.** For each shared axis
  id the grid takes every panel's `_range(axis_id)` and applies the merged
  `(min, max)` to all panels (`components.py:3657-3666`). Categorical axes
  are unioned in first-seen order and the panels are **rebuilt** with that
  order pre-seeded, because category positions commit at ingest
  (`components.py:3646-3656`). An axis that is categorical in some panels and
  numeric in others cannot be shared: it warns and skips sharing for that
  axis only.
- **`link` is runtime sync, `share_*` is initial domain.** `link=True` or
  `"both"` links x and y; `"x"`/`"y"` links one; `False`/`None` disables.
  A linked dimension is force-shared even when its `share_*` is `False`
  (`components.py:3610-3615`), since panels starting from incomparable
  domains would jump on first interaction. `link` and `link_select` assign
  all panels one generated `link_group` (`xy-facet-<hex>`), so propagation is
  exactly the §5.1 BroadcastChannel path; `link_select` additionally echoes
  data-space selections across panels.
- **Decimation budget is per panel.** `FacetGrid` composes N *independent*
  figures rather than one multi-panel spec, and each is built with
  `px_width=panel_width` (`facets.py:185`). LOD therefore targets each
  panel's own narrower width; total decode and draw work scales with panel
  count rather than being budgeted across the grid. A grid-wide budget is
  pending.

## 6. Reflex integration (no escape hatches)

The tree above is precisely a Reflex component tree's shape: snake_case
props, children composition, `data=` + column-name resolution (`data_key`
idiom), event props. It remains a XY-owned tree, not a Reflex object,
so the core package keeps zero Reflex dependencies. A future Reflex wrapper is
therefore a *thin* codegen layer:

1. Each `xy.*` factory maps 1:1 to a Reflex component; props serialize as-is
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
  id. Axes are already explicit spec objects keyed by axis id
  (`"axes": {axis_id: …}`, `python/xy/_payload.py:238`); hoisting scale type
  and domain into a separate `scales` object rides the same bump.
- The `Chart(kind_str, ...)` wrappers never encoded behavior (kind string is
  cosmetic) — safe to keep forever.

## 8. Implementation order

1. ★ Done. `xy.chart` (`python/xy/components.py:4380`) plus the annotation
   set — rules, bands, and text nodes shipped under the names in §5, through
   `_ANNOTATION_APPLIERS` rather than as `Mark` nodes.
2. Partial. Per-axis spec objects ship: `build_payload` emits
   `"axes": {axis_id: …}` over `self.axis_options`
   (`python/xy/_payload.py:238`). Still pending: hoisting scale type and
   domain into a distinct `scales` object, and completing `category`/`log`.
3. Pending. `panel`/`figure` grid + `link_x` view sync (enables the finance
   pair and subplot grids; carries the protocol bump). No `xy.panel` or
   `xy.figure` factory exists yet — §4 example D remains aspirational.
   Cross-chart view sync itself already ships via `link_group` (§5.1), so
   this item is now the *layout* half only.
4. ★ Done. Named secondary scales ship as `xy.y_axis(id="y2", …)` +
   `mark(..., y_axis="y2")`, with the loud opt-in enforced by the
   no-matching-axis build error (§5.1 G2). The `secondary=True` spelling was
   dropped in favor of axis ids.
5. ★ Done, with a different shape than planned: `xy.facet_chart(by=…)`
   (§5.2), not `facet(col=…)`, and it composes N independent figures in a
   `FacetGrid` rather than compiling to a panel grid. Folding it onto the
   item-3 panel grid once that lands is pending, as is a grid-wide
   decimation budget.
