# Data-bound chart components — implementation plan

**Status: implemented — Phases 0–4 landed (2026-08); this document is the
executed work plan plus its completion record (see "Completion record"
at the end).** Design authority:
[`reflex-component-api-options.md`](reflex-component-api-options.md)
(Option 6 + Option 2 for the escape hatch; §7 phasing; decision record in
its §8). The shipped behavior is specified in
[`reflex-integration.md`](reflex-integration.md) — §3.1 (handles + compile
probe), §3.6 (data vars, plans, composite tokens), §5 (component tiers and
deprecations). Each phase was implemented as written unless the completion
record notes otherwise; every phase landed with its spec updates in the
same change (repo rule: a change is incomplete while its spec is stale).

Target DX (recap):

```python
class CloudData(TypedDict):
    x: np.ndarray; y: np.ndarray; mag: np.ndarray

class Dash(rx.State):
    points: int = 200_000

    @rxy.data
    def cloud(self) -> CloudData: ...

def index():
    return rxy.scatter_chart(data=Dash.cloud, x="x", y="y",
                             color="mag", colormap="viridis",
                             height="460px", on_select_end=Dash.select)
```

---

## Phase 0 — pin the ground (tests only)

Everything later rests on behavior verified by probe but not yet pinned.
These tests fail loudly when a Reflex or grammar upgrade moves the ground.

**New: `tests/reflex_adapter/test_framework_contracts.py`**
(runs under the `reflex` extra job, like the rest of `tests/reflex_adapter/`)

- A computed var may return a parametrized generic frozen dataclass
  (`Handle[SomeTypedDict]`); the class-level Var's `_var_type` preserves the
  full alias; `typing.get_args` recovers the TypedDict; `get_type_hints`
  yields its keys (fact R7).
- Same preservation for a base var `list[Handle[Schema]]` and for the
  element Var produced by indexing / `rx.foreach` (R7, foreach half).
- A component prop annotated `rx.Var[Handle]` accepts the parametrized var
  and raises `TypeError` at `create()` for an int var and for a raw string
  (R1).
- An unknown `on_*` kwarg raises `ValueError` at `create()`; an unknown
  non-event kwarg is silently absorbed into `style` (R8 — this test
  *documents the hazard* the factories must compensate for; if Reflex ever
  starts rejecting these, our partition layer gets simpler).

**New core-side test (beside the existing composition-API tests in
`tests/`): validation-timing pins (facts X1–X3)**

- Zero-row construction compiles: for every mark kind Phase 2/3 will cover,
  `xy.<kind>_chart(xy.<mark>([], ...)).figure()` succeeds.
- Mark config validates at `.figure()`, not construction
  (`xy.scatter([1], [1], colormap="bogus")` constructs; `.figure()` raises).
- Chrome nodes validate eagerly (`xy.x_axis(type_="bogus")` raises at call).
- `Chart.figure()` memoizes; data rebinding requires a fresh `Chart`.

**Acceptance:** suite green in CI on the pinned Reflex floor; a comment in
each test names the design fact (R1/R7/R8/X1–X3) it pins.

---

## Phase 1 — typed seam (small, non-breaking)

Make the component a real, exported, prop-typed Reflex component and the
figure var's value a typed handle.

**New: `python/reflex_xy/handles.py`**

- `@dataclass(frozen=True) class FigureHandle: token: str = ""` and
  `class DataHandle(Generic[S]): token: str = ""`.
- One-line `@rx.serializer` each → `dict` (delta-path safety; also makes
  `guess_type` produce an `ObjectVar`).
- Empty token = "not ready / no chart" — the existing `""` sentinel wrapped,
  so the var type stays non-optional.

**`python/reflex_xy/vars.py`**

- `FigureVar` / `AsyncFigureVar`: `return_type=FigureHandle`; `_publish`
  returns `FigureHandle(token)` / `FigureHandle("")`.

**`python/reflex_xy/component.py`**

- Component class gains `figure: rx.Var[FigureHandle]`; the wrapper reads
  `figure.token`. Keep the `token: rx.Var[str]` prop for one deprecation
  cycle (wire/JSX accepts both).
- `chart()` gains keyword form `chart(figure=Dash.cloud, ...)`. The
  positional `chart(source, ...)` stays as a shim: state-var/handle sources
  route to `figure=`, str tokens and Chart/Figure objects keep today's
  behavior; emit a deprecation warning for the positional form.
- `create()`-override validation (recharts pattern): semantic-event props on
  a static (`src`) source → clear error instead of silent no-op; malformed
  `tailwind_classes` keeps its existing eager errors.

**`python/reflex_xy/__init__.py`** — `register()` / `inline()` return
`FigureHandle` (their token remains inside; `.token` documented). The shim
accepts old-style str for one cycle.

**`python/reflex_xy/assets/XYChart.jsx`** — accept `figure` object prop
(`{token}`) alongside legacy `token` string.

**Tests:** extend `tests/reflex_adapter/test_component.py` (typed-prop
rejection cases mirror Phase 0's contract test but through the real
component) and `test_figure_var.py` (handle-valued var; empty-token
sentinel).

**Spec:** `reflex-integration.md` §5 — `figure=` prop, handle type,
deprecation note.

**Acceptance:** existing demo app (`examples/reflex/`) runs unmodified;
`chart(figure=Dash.points)` fails at compile with the framework's
`TypeError`; full gate (`pre-commit`, `ruff`, `ty`, `pytest`) green.

---

## Phase 2 — `@rxy.data` + flat factories (the headline)

### 2.1 `@rxy.data` — new `python/reflex_xy/data.py`

`DataVar` / `AsyncDataVar`, structurally a sibling of `FigureVar` (same
`_deps` builder-targeting, same `iscoroutinefunction` dispatch, same
pre-session short-circuit):

- fget: mint `xyd1|<client>|<state>|<var>` token; run the data method;
  validate the returned mapping (str keys; array-likes; consistent lengths —
  the only checks that need real data); publish **columns** to the registry;
  return `DataHandle(token)`.
- `return_type` set from the method's return annotation:
  `DataHandle[CloudData]` when it's a TypedDict, plain `DataHandle`
  otherwise — this is the schema channel (R7); nothing executes to read it.
- `None` return → release + `DataHandle("")`, mirroring figure vars.
- Underscore names refused at decoration (same reason as figure vars: the
  handle must sync to the client).

**`python/reflex_xy/tokens.py`** — add the `xyd1` grammar
(`xyd1|client|state|var`, same charset rules as `xyv1`); `parse_token`
learns the new prefix; `builder_of` works unchanged (DataVars are computed
vars on the state class).

### 2.2 Plans — new `python/reflex_xy/plan.py`

`ChartPlan`: the validated, data-free chart structure.

- **Build** (at factory call = page evaluation): construct the real xy tree
  (marks with string channels, chrome nodes, chart props); bind zero-row
  placeholder columns for every referenced channel name; call `.figure()`
  once — the full mark/config validation gate at compile (X2). Discard the
  probe figure.
- **Serialize**: dataclass nodes → canonical JSON (sorted keys, versioned
  `plan_version: 1`) → sha256 → `digest`. Register in a process-local
  `{digest: ChartPlan}` map. Page bodies run in every worker (X4 — but see
  the completion record: backend-only workers needed this made true by
  construction), so the map is populated everywhere; a lookup miss
  (hot-reload drift) answers `err {resync}` with a message naming the
  digest.
- **Bind** (at serve time): columns + plan → fresh `Chart` (never reuse — X3)
  → `.figure()` → `Figure`. Column-mismatch errors name both sides:
  *"plan binds column 'mag'; Dash.cloud produced {x, y}"*.
- Bonus wired here: the zero-row probe figure's `dom_class_strings()` gives
  live charts automatic Tailwind discovery — mirror into the existing
  `tailwind_class_tokens` scan prop (today live sources need the manual
  inventory).

### 2.3 Flat factories — new `python/reflex_xy/factories.py`

Phase 2 kinds: `scatter_chart`, `line_chart`, `histogram_chart`,
`bar_chart`. Each flat factory:

1. **Partitions kwargs** — derived from `inspect.signature` of the xy mark
   (positional params = channels, keyword-only = options; the convention is
   uniform across `components.py`) plus chart props, component fields,
   event triggers, and style passthrough.
   - Collision table (component/chart level wins): `width`, `height`,
     `opacity`, `style`, `class_name`, `key`, `animation`. Colliding mark
     options get flat aliases (`stroke_width` for `line.width`); the table
     is *generated* into the docs and pinned by a test — public contract.
   - Unknown kwarg close to a known name (difflib) → error with suggestion;
     far from everything → style passthrough (preserves Reflex's CSS
     convention). The Phase 0 R8 test documents why this layer must exist.
2. **Checks columns** — `get_args(data_var._var_type)` → TypedDict →
   channel strings validated with the *Available columns* error. Untyped
   `dict[str, ...]` → skip; checked at first execution.
3. **Builds the plan** (2.2) and returns the component with props
   `plan` (literal digest, baked into JSX) + `data` (`Var[DataHandle]`).
4. **Static tier:** `data=` given concrete arrays/mapping (not a Var) →
   bind immediately and route to the existing `payload_asset` path
   (`src` prop) — works under `reflex export`.

### 2.4 Transport & registry

Composite figure identity, minimal wire change:

- The wrapper subscribes with `fig = "xyp1|<digest>|<xyd1-token>"`,
  assembled client-side once `data.token` is non-empty. Rooms, `mid`
  addressing, versioning, and the attachment-cap logic in
  `namespace.py` are reused unchanged — one new token prefix to parse.
- **`registry.py`**: column entries (token → columns + version) beside
  figure entries; figure cache keyed by the composite token, plus an index
  `data_token → {digests}` so a data republish rebuilds and broadcasts
  every dependent figure. Figure entries stay derived caches: TTL-sweepable,
  rebuildable from (plan map, data rebuild).
- **`namespace.py`**: `sub`/`msg` on `xyp1|…` → plan lookup; data resolve
  (registry hit, else rebuild); bind → publish → serve. Affinity check uses
  the client token embedded in the `xyd1` half.
- **`state_bridge.py`**: `rebuild_data(app, parsed)` mirroring
  `rebuild_figure` — resolve state class, find the DataVar's method, run it
  (await if async), return columns.
- **`assets/XYChart.jsx`**: accept `plan` + `data` props; compose the
  subscription token; everything downstream (payload epochs, appends,
  view-state) unchanged.

### 2.5 Tests

- `test_data_var.py` — handle value, schema in `_var_type`, pre-session
  short-circuit, `None` release, underscore refusal, async variant.
- `test_plan.py` — digest stability (goldens), zero-row validation catches
  bad colormap/enum/axis-ref at build, bind produces fresh figures,
  version field.
- `test_factories.py` — partition + collision table, did-you-mean,
  TypedDict column errors (including through a foreach item var), untyped
  fallback, static-tier routing.
- Extend `test_socket_data_plane.py` — composite `sub`, payload, pick;
  data republish fans out to all dependent plans; rebuild-on-miss for both
  halves; affinity refusal; plan-miss `err {resync}`.
- Demo app: add one data-bound chart to `examples/reflex/` beside the
  existing figure-var charts (both models exercised by
  `scripts/reflex_ws_smoke.py`).

**Spec:** `reflex-integration.md` — new section for the data plane vars +
plan tier + composite tokens; `wire-protocol.md` touched only if the
envelope grows a field (target: it doesn't — composite token rides `fig`).
Decision record added to `reflex-component-api-options.md`.

**Acceptance:** the target-DX snippet at the top of this file runs; every
row of the error-catalog table in the options doc §5.6 reproduces at the
stated phase (import/compile/hydrate); 100M-point state delta is still just
the handle; full gate green.

---

## Phase 3 — composed `rxy.chart(...)` + remaining kinds

- `factories.py`: `rxy.chart(*nodes, data=..., **props)` consuming xy
  mark/annotation/chrome nodes (plain xy dataclasses — they never enter the
  Reflex tree; the factory builds the plan before any component exists).
- `__init__.py` lazy exports: curated re-exports of mark + chrome
  constructors (`rxy.scatter` *is* `xy.scatter`, etc.) so hallucinated
  names die at import against the explicit export map.
- Remaining `*_chart` kinds via the same signature derivation.
- **Decision point (resolve during this phase):** the data-taking composite
  factories (`pie_chart`, `radar_chart`, `wind_rose`, `sankey`) do eager
  numeric work at call time — they don't fit the plan/zero-row model.
  Options: (a) static-tier / concrete-data only, (b) escape hatch only,
  (c) column-ref variants in core xy. Record the choice in the spec.
- Facets: static facet grid already works; live data-bound facets deferred
  (tracked in the options doc's open questions).
- Plan format frozen: goldens + a compatibility note in the spec.

**Acceptance:** the composed example from the options doc runs; `rx.cond`
between two composed charts compiles and validates both.

---

## Phase 4 — compile probe for the escape hatch

- `vars.py`: `@rxy.figure(probe="build" | "figure" | False)` — default
  `"build"` for sync builders, `False` for async.
- `app.py` (`XYPlugin` compile hook): walk state classes, find FigureVars,
  default-construct the substate, run the builder; `probe="figure"`
  additionally compiles the result. Errors re-raise wrapped with state
  class, var name, and source location. Builders touching
  `self.router`/session degrade to a warning, not a compile failure
  (constraint 2's escape valve).
- Tests: hallucinated-API builder fails compile; session-dependent builder
  downgrades; opt-out honored; async skipped by default.

**Spec:** `reflex-integration.md` §3.1 — probe semantics and defaults.

---

## Deferred (tracked, do not start without a design pass)

- Keyed dataset collections for `foreach` (one data var = one dataset
  today; a runtime-length collection needs a keyed extension).
- Per-mark `data=` (two sources, one chart).
- Core-xy metadata registry (stubs/docs generation) — nice-to-have, not a
  prerequisite; signature derivation covers v1.
- Upstream Reflex PRs, both sites located in the monorepo:
  generic attribute access
  (`packages/reflex-base/src/reflex_base/utils/types.py`,
  `get_attribute_access_type` ~:436 — `get_origin()` unwrap) enabling
  `x=Dash.cloud.x`; Var-type child coercion
  (`packages/reflex-base/src/reflex_base/components/component.py` ~:1314)
  enabling bare `rx.card(State.cloud)`.

## Rollout & deprecation

- Phases 1–4 are additive. Deprecations (positional `chart(source)`, str
  tokens in public returns, legacy `token` JSX prop) warn for one release
  cycle after Phase 2 ships, then tighten. The `@rxy.figure` tier is
  permanent (escape hatch), not deprecated.
- CI order unchanged: `abi_smoke` / `render_smoke_nonumpy` /
  `append_stream_smoke` first (none are affected), adapter suite under the
  `reflex` extra, browser E2E via `scripts/reflex_ws_smoke.py`.
- Every phase: run the full pre-commit + ruff + ty + pytest gate before
  commit (repo rule); spec updates land in the same PR as the code.

## Risks

| risk | mitigation |
|---|---|
| Reflex upgrade changes Var/prop machinery | Phase 0 contract tests fail first, named after the design facts |
| Grammar change alters plan JSON → digest churn | digests are content addresses: old subscribers get `err {resync}` and re-sub against the new plan; goldens catch *accidental* churn |
| Kwarg partition drifts from xy signatures | partition is derived from `inspect.signature` at import, not hand-listed; collision table pinned by test |
| Data republish fan-out amplifies (one data var, many plans) | reuse the existing coalescing broadcast machinery; index bounded by mounted plans; measure in the §12 harness before optimizing |
| Attachment cap on column-heavy payloads | unchanged: the namespace's `_MAX_WIRE_ATTACHMENTS` single-blob fallback applies to bound figures exactly as today |

---

## Completion record (2026-08)

All five phases landed together; the acceptance criteria of each phase hold
(the target-DX snippet at the top runs verbatim; every row of the options
doc §5.6 error catalog reproduces at its stated phase; the demo app runs on
the modern API; the full gate is green). Deviations from the letter of the
plan, all recorded in the options doc §8 decision record:

- **Phase 0** — as written: `tests/reflex_adapter/test_framework_contracts.py`
  (R1/R7/R8) and `tests/test_validation_timing.py` (X1–X3, plus the exact
  zero-row and shaped-synthetic kind lists the factories rely on).
  Verified against reflex 0.9.8.
- **Phase 1** — as written, except the deprecation warning fires only for
  positional *live* sources; the positional static Chart/Figure form stays
  undeprecated (it is the only route for arbitrary Charts, e.g. facet
  grids). Kernel-only events on static sources now fail `create()`.
- **Phase 2** — as written, with `data.py` renamed `data_vars.py`
  (submodule/export shadowing) and one addition beyond the plan: a
  registry→namespace error seam (`err {resync}` room fan-out) so a column
  republish whose bind fails cannot freeze subscribers silently; the
  wrapper bounds consecutive err-driven resyncs.
- **Phase 3** — composed `chart(*nodes, data=...)`, curated re-exports
  (`reflex_xy.scatter` *is* `xy.scatter`), and seven more flat kinds (area,
  step, stem, column, errorbar, error_band, segments). **Decision point
  resolved:** aggregating marks (box, violin, hexbin, contour, heatmap,
  stairs, ecdf) and the data-taking composite factories (pie, radar,
  wind_rose, sankey) were excluded from the plan tier — options (a)+(b):
  static tier or `@reflex_xy.figure` — because their validators need real
  values and a synthetic-row probe would validate against made-up data.
  **The aggregating-marks half of this decision was revised post-landing —
  see "Post-landing revision (kind coverage)" below**; the composite
  factories remain excluded. Plan format frozen: `PLAN_VERSION = 1`,
  golden digest pinned in `test_plan.py`.
- **Phase 4** — as written (`probe="build"`/`"figure"`/`False`, async off
  by default with explicit opt-in via `asyncio.run`); the
  session-dependence downgrade uses a source-text heuristic
  (`self.router`), documented in reflex-integration.md §3.1.

**Post-landing correction (X4).** First real `reflex run` of a data-bound
app surfaced that fact X4 holds only where the frontend compile runs:
backend-only workers (the dev backend subprocess, prod workers) import the
app module but leave pages unevaluated, so their plan maps were empty and
every plan subscription answered `err {resync}` until the bounded retry
gave up. Fixed structurally, not by weakening the model: `setup(app)`'s
startup lifespan evaluates the app's unevaluated page component functions
once per worker (`app.py _ensure_page_plans`, pinned by
`tests/reflex_adapter/test_page_plan_registration.py`), making "the plan
map is populated in every worker" a guarantee of the integration instead
of an assumption about Reflex. Recorded in reflex-integration.md §3.6 and
the options doc §8.

**Post-landing revision (kind coverage, 2026-08, revised again after
review).** The Phase 3 exclusion of the aggregating marks is lifted. The
first lift probed them with fixed synthetic placeholder columns
(`plan._SYNTHETIC_CHANNELS`); review proved synthetic data structurally
unsound — a column shared between an aggregating channel and a zero-row
channel falsely failed on invented lengths, valid hexbin `range=`/
`mincnt=` configurations falsely failed on invented values, and large
`gridsize` ran real aggregation at page evaluation. The final design
replaces synthetic data with a **core structural-validation seam**:
`xy.structural_probe()` (spec/api/chart-kind-contract.md "Structural
probe"), under which an all-empty mark validates configuration and skips
aggregation. Every kind probes zero-row. Landed with it:

- Flat factories for all 20 standalone kinds (`funnel_chart`, `box_chart`,
  `violin_chart`, `ecdf_chart`, `hexbin_chart`, `contour_chart`,
  `heatmap_chart`, `stairs_chart`, `triangle_mesh_chart` beside the
  eleven zero-row-safe kinds).
- `validate_columns` no longer requires one shared length: a data var may
  carry mixed-length and 2-D columns (stairs edges, heatmap grids);
  coupled-shape contracts live with the mark validators at bind.
- Plan callables (hexbin's `reduce_C_function`) are content-addressed:
  import path + code fingerprint for pure-Python functions (an edited
  body changes the digest — rolling deployments fail safe to resync,
  never to divergent behavior), import path + distribution version for
  C-level callables that resolve back to themselves. Bound methods,
  lambdas, closures, and partials are refused. Plan registration is
  last-write-wins so a hot reload replaces stale node objects.
- Pinned by `tests/reflex_adapter/test_plan.py` (zero-row plans per kind,
  the review's shared-column and hexbin-config repros, callable
  addressing incl. bound-method refusal and body-sensitive digests),
  `test_factories.py` (the full 20-kind flat table), and
  `tests/test_validation_timing.py` (the xy half: every kind compiles
  empty under the probe, still refuses empty normally, still raises
  config errors under the probe). Recorded in reflex-integration.md §3.6
  "Kind coverage" and spec/api/chart-kind-contract.md.

Deferred items remain deferred and tracked (keyed dataset collections for
`foreach`, per-mark `data=`, the core-xy metadata registry, both upstream
Reflex PR sites).
