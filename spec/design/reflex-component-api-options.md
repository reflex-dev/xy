# A component-shaped, compile-checked API for `reflex_xy` — options

**Status: decided — Option 6 adopted (with Options 1 and 2 as its subsumed
parts), implemented.** See the decision record at the end of this document.
This document records the design space for that revision of the `reflex_xy`
public API. The shipped integration is specified in
[`reflex-integration.md`](reflex-integration.md) (the adopted tier: §3.6),
and the framework-agnostic composition contract in
[`reflex-shaped-api.md`](reflex-shaped-api.md). The file-level work plan
that guided the implementation lives in
[`reflex-component-api-implementation.md`](reflex-component-api-implementation.md).

It is written to be self-contained: §1 gives a new engineer everything they
need about Reflex, xy, and the current integration; §2 states the problem;
§3 the constraints; §4 the verified framework facts the designs build on;
§5 the six candidate designs (§5.6, the synthesis, is the recommended one);
§6 the comparison; §7 the recommendation.

---

## 1. Background: the three systems involved

### 1.1 What xy is

xy is a high-performance charting engine for Python (this repository). Three
layers matter here:

- **The composition API** (`python/xy/components.py`) — the only public
  chart-building surface. Users compose charts declaratively:

  ```python
  import xy
  chart = xy.scatter_chart(
      xy.scatter(x, y, color=mag, colormap="viridis"),
      xy.x_axis(label="σ"),
      width="100%", height=460,
  )
  ```

  `xy.scatter(...)` returns a `Mark` — a plain dataclass holding whatever you
  passed (arrays, lists, or **column-name strings** resolved later against a
  `data=` table). `xy.scatter_chart(...)` returns a `Chart` — a lightweight
  tree of these dataclass nodes. **Nothing heavy happens at construction**:
  no copies, no shape checks, no rendering.

- **The figure compiler** — `Chart.figure()` compiles the tree into the
  internal `Figure` (canonical f64 columns, trace state, the wire spec).
  **This is where almost all validation fires**: shape mismatches, bad
  colormaps/enums, unresolvable column names, missing axis ids. The split is
  bimodal and worth memorizing:

  | fails at construction (eager) | fails at `.figure()` (lazy) |
  |---|---|
  | unknown kwargs (`TypeError` — no `**kwargs` sinks anywhere) | data shape/length mismatches |
  | chrome nodes: `x_axis`, `legend`, `theme`, … validate every field | mark config: `colormap=`, `symbol=`, `bins=`, `mode=`, … |
  | unknown attribute on the lazy `xy` module (`AttributeError`) | column-name resolution against `data=` |
  | chart-level `class_names` slot allowlist | axis-id references (`y_axis="y2"`) |

  A useful verified fact: `xy.scatter_chart(xy.scatter([], [])).figure()`
  builds a valid empty figure — so **binding zero-row columns and calling
  `.figure()` exercises the full validation gate without any real data**.

- **The render client** (`js/src/`, bundled into `python/xy/static/`) — a
  WebGL2 client that renders a binary payload (spec JSON + raw f32 buffers,
  never JSON numbers) and talks to a Python-side kernel for drilldown,
  picking, and selection. The same client serves notebooks, static HTML
  export, and Reflex.

### 1.2 What Reflex is

[Reflex](https://reflex.dev) is a Python full-stack web framework. You write
Python; it compiles a React frontend and runs a Python backend. The concepts
this document leans on:

- **State** — a class with typed fields; lives on the backend, synced to the
  browser as JSON deltas over one websocket:

  ```python
  class Dash(rx.State):
      points: int = 200_000          # a base var

      @rx.var
      def label(self) -> str:        # a computed var: re-derived when deps change
          return f"{self.points:,} points"

      @rx.event
      def more(self):                # an event handler: called from the browser
          self.points *= 2
  ```

- **Components** — Python classes that compile to React/JSX. A page is a
  Python function returning a component tree; props are typed class fields:

  ```python
  def index() -> rx.Component:
      return rx.vstack(
          rx.heading(Dash.label),                    # a Var in the tree → reactive text
          rx.button("more", on_click=Dash.more),     # event prop → handler
      )
  ```

- **Vars** — `Dash.label` accessed on the *class* is not a value; it is a
  `Var` object: a typed reference (`_var_type=str`) that compiles to a JS
  expression. Components accept Vars as props and children; that is what
  makes the tree reactive.

- **`rx.cond` / `rx.foreach`** — conditionals and loops over state, resolved
  in the browser. Crucially, `rx.foreach(Dash.items, render_fn)` calls
  `render_fn` **exactly once at compile** with a *placeholder* Var (typed
  from the list annotation); the browser instantiates it per row. You cannot
  branch in Python on the item's value inside `render_fn` — only `rx.cond`.

- **The compile timeline.** "Compile" is when `reflex run`/`reflex export`
  evaluates your app. What runs when (verified against reflex 0.9.6):

  | phase | what executes | what can fail here |
  |---|---|---|
  | **import** | module bodies; state classes are built | invalid state var types; anything at module scope |
  | **compile** | every page function runs; every `Component.create()` runs; **the default state is instantiated and computed vars are evaluated** (unless `initial_value=` opts out) | prop type errors; event-handler arity/type errors; child whitelist errors; computed-var exceptions |
  | **hydrate** | browser loads; real session state is created; deltas flow | everything else |

  Two facts from `Component._post_init` shape every design below:
  1. **Prop type checking happens only for props annotated `Var[T]`** — the
     incoming Var's `_var_type` is checked structurally at `create()` (i.e.
     at compile). A bare `T` annotation gets no check at all.
  2. **Unknown kwargs are silently absorbed into `style`** — a typo'd prop
     becomes a CSS property, not an error.

  Custom Python types become legal state-var values and prop types by
  registering an `@rx.serializer` (dataclasses work even without one).

### 1.3 What reflex_xy is, and how it works today

`python/reflex_xy/` (import name `reflex_xy`) is the bundled integration.
Its central problem: **chart data can be huge, and Reflex state sync is JSON
diffing** — putting a million rows in state (as e.g. recharts integrations
do) would be catastrophic. The design (full detail:
[`reflex-integration.md`](reflex-integration.md)) splits every chart into two
planes:

- **Control plane** (Reflex-native): which figure a component shows, style
  props, and small semantic events (`on_point_click`, `on_select_end`, …) —
  ordinary Reflex state and event handlers. Never data buffers.
- **Data plane** (xy-native): binary payloads, drilldown round-trips, and
  streaming appends on a second socket.io namespace (`/_xy`) **multiplexed
  onto the app's existing websocket**. Reflex state never sees a data byte.

The pieces, end to end:

```python
class Dash(rx.State):
    points: int = 200_000

    @reflex_xy.figure                 # ← a computed var in disguise
    def cloud(self) -> xy.Chart:
        x, y = load(self.points)
        return xy.scatter_chart(xy.scatter(x, y))

def index():
    return reflex_xy.chart(Dash.cloud, height="460px")   # ← the wrapper call
```

1. **`@reflex_xy.figure`** wraps the method in a `FigureVar` (a Reflex
   computed var). Its *value* is only a token string —
   `xyv1|<client_token>|<state_name>|<var_name>` — and **evaluating the var
   is what builds the chart**: the builder runs, the resulting `Figure` is
   published into a **per-process registry** under the token, and the token
   goes into state. Reflex's dependency tracking re-runs the builder when
   state it reads changes; subscribers get a fresh payload pushed over the
   data plane. The token is stable, so the DOM never re-renders — pixels
   move, DOM doesn't.
2. **The registry** (`registry.py`) is deliberately process-local and *not*
   a distributed store. A registry miss (worker restart, reconnect landing
   on another node) is recovered by **re-running the builder against session
   state** (`state_bridge.py`) — Reflex state is the durable source of
   truth; every registered figure is a rebuildable cache. The token *is* the
   rebuild recipe.
3. **`reflex_xy.chart(source)`** (`component.py`) is a factory that builds a
   private `rx.Component` (`XYChart`). A token/Var source lands in the
   `token` prop and rides the socket; an `xy.Chart` passed directly is
   compiled to a static payload asset (`src` prop) rendered kernel-less —
   works under `reflex export` with no backend.
4. At **hydrate**, the JSX wrapper subscribes (`sub {fig: token}`) on the
   `/_xy` namespace; the backend serves the registered figure's binary
   payload (or rebuilds it from state on a miss), and interaction messages
   round-trip to the kernel.

One accidental property matters enormously for this document: at compile,
Reflex evaluates computed vars against a default state — but `FigureVar`'s
getter first tries to mint a token from the session's `client_token`, finds
none (no session at compile), and returns `""` **without ever executing the
builder body**. That is why the current design does no data work at compile
(good) — and also why nothing in the builder body is ever checked at compile
(the problem).

---

## 2. The problem

Two complaints, one root cause (the chart-building code executes at hydrate,
not at compile, and the component seam is untyped):

### Problem 1 — it doesn't feel like a Reflex component

Every other Reflex component composes in the tree, takes typed props, and
works inside `rx.cond`/`rx.foreach` with a uniform mental model.
`reflex_xy.chart(State.cloud)` is a special wrapper call around a state var —
a different mental model, and the component class itself is private (built
lazily, no importable type, props not part of the public surface).

### Problem 2 — no compile-time validation

If code references a chart API that doesn't exist — say an LLM agent
hallucinates `xy.polar_scatter(...)` inside a builder — **nothing fails at
compile**. The builder body is dead code until a browser session hydrates and
the var evaluates; only then does the `AttributeError` fire, surfacing as an
`err` frame on the data plane and an empty mount. Wrong kwargs, invalid
colormaps, bad axis references: all the same. For a human iterating with
`reflex run` this is slow feedback; for an agent loop (write → compile →
check) it is invisible — the compile is green and the page is silently blank.

Additionally, the component seam itself is unchecked: passing the wrong var
(`Dash.points`) or a garbage string as the chart source is accepted at
compile, because the `token` prop is `Var[str]` and unknown kwargs become CSS.

---

## 3. Constraints (what must not regress)

1. **State stays lean.** Chart data must never be serialized into Reflex
   state. The registry + token indirection is the whole point of the
   integration — every design keeps figures (and their columns) in the
   per-process registry, with only a small token/handle in state.
2. **No data ingestion at compile.** Reflex evaluates computed vars at
   compile against default state; today the figure var deliberately
   short-circuits (returns `""`) so no chart is built just to render a dead
   placeholder. Designs that execute anything at compile must bound what
   runs (structure-only, zero-row, or explicit opt-in/out).
3. **Rebuildability.** Any worker must be able to recover a figure from
   session state alone (the multi-worker/reconnect story). Whatever a design
   puts between state and figure must remain a deterministic recipe.
4. **`reflex-shaped-api.md` boundaries.** xy must not grow a parallel
   reactive DSL (no xy-owned `field()`/`condition()`); Reflex owns Vars,
   conditionals, events, layout. The core `python/xy` package never imports
   Reflex.

---

## 4. What the frameworks give us to build on

Facts verified against reflex 0.9.6 and the current xy codebase, load-bearing
for the designs:

- **R1.** Prop type checks fire at `create()` (= page evaluation = compile),
  but only for `Var[T]`-annotated props; the Var's `_var_type` is compared
  structurally. This is how `rx.plotly(data=State.fig)` gets a typed seam.
- **R2.** `@rx.serializer` (or being a dataclass) makes a custom type legal
  as a state-var value and usable as `Var[MyType]`.
- **R3.** Computed vars execute at compile against default state unless
  `initial_value=` is set. `FigureVar` currently dodges this via the missing
  client token — the builder body never runs before hydrate.
- **R4.** `rx.foreach` builds its child once with a placeholder Var typed
  from the list annotation; an untyped iterable is a hard compile error.
  `rx.cond` builds (and therefore validates) both branches eagerly.
  `rx.ComponentState` is explicitly unsupported inside `foreach`.
- **R5.** Custom compile-time validation belongs in a `create()` override
  (the pattern reflex's own recharts wrapper uses); there is no post-init
  validation hook.
- **R6.** A bare Var as a *child* (`rx.card(State.cloud)`) always renders as
  a text node; Reflex has no Var-type→component coercion hook in child
  normalization. "No call at all" is not implementable from outside the
  framework.
- **X1.** The xy tree is cheap to build without data; string channels are
  late-bound column refs; unknown kwargs `TypeError` at call; chrome nodes
  validate eagerly; marks validate at `.figure()`.
- **X2.** Zero-row columns compile: binding empty placeholder columns for
  every named channel and calling `.figure()` runs the full mark/config
  validation gate in milliseconds, with no real data.
- **X3.** `Chart.figure()` memoizes and is never invalidated — rebinding
  data means constructing a fresh `Chart`, never mutating one.
- **X4.** Prod backend workers re-evaluate page bodies (the static payload
  tier already relies on this) — anything registered during page evaluation
  exists in every worker.

Three more facts were verified empirically for Option 6 — on **both** the
released reflex 0.9.6.post1 and the framework's development checkout
(0.9.7.post41.dev0, `~/code/reflex`), with identical results (a probe
script exercising each; pin these as adapter tests before building on
them):

- **R7.** A computed var may return a **parametrized generic dataclass** —
  `DataHandle[CloudData]` — and the full alias survives as the Var's
  `_var_type`: `get_args(...)` recovers the `TypedDict`, `get_type_hints`
  on it yields the column names. This holds for base vars too
  (`list[DataHandle[CloudData]]`), **and the element Var inside
  `rx.foreach` keeps the parametrized type** — so schema-aware compile
  checks work per-item inside loops. A prop annotated `Var[DataHandle]`
  accepts the parametrized var and rejects an `int` var or a raw string
  with a compile-time `TypeError`.
- **R8.** An unknown `on_*` kwarg **already fails at compile** with a
  framework `ValueError` listing valid triggers (so "did you mean
  `on_select_end`" only needs a better message, not new machinery). An
  unknown *non-event* kwarg (`colormapp=`) is still silently absorbed into
  `style` — factories must partition kwargs themselves to catch config
  typos.
- **R9.** Attribute access on a Var whose `_var_type` is a *parametrized*
  generic (`Dash.cloud.token`) currently raises `VarAttributeError` —
  reflex's attribute-type resolver does not unwrap generic origins. Root
  cause located in the reflex monorepo: `get_attribute_access_type`
  (`packages/reflex-base/src/reflex_base/utils/types.py`, the function at
  ~:436) ends with an `isinstance(cls, type)` bare-class branch; a
  parametrized alias is not a `type`, falls through, and returns `None`.
  The fix is a `get_origin()` unwrap (ideally with TypeVar substitution
  from `get_args`) before that branch. Typed column *references*
  (`x=Dash.cloud.x`) therefore need that upstream fix and are correctly
  deferred; nothing in Option 6's v1 reads attributes off the handle Var.

The design space then reduces to two questions: **when does the
chart-building expression execute** (import / compile / hydrate), and **how
much of the chart's identity is a typed Var** at the component seam?

---

## 5. The options

### Option 1 — Typed figure handle + first-class component (the plotly pattern)

Make the chart component a real, exported, prop-typed `rx.Component`, and
make the figure var's value a typed handle instead of a bare `str`.

```python
class Dash(rx.State):
    points: int = 200_000

    @reflex_xy.figure
    def cloud(self) -> xy.Chart:
        x, y, mag = load(self.points)
        return xy.scatter_chart(xy.scatter(x, y, color=mag))

def index():
    return rx.card(
        reflex_xy.chart(                # a real component, like rx.plotly
            figure=Dash.cloud,          # Var[FigureHandle] — typed prop
            on_select_end=Dash.on_select,
            height="460px",
        ),
    )
```

**Compile-time validation.** `FigureVar` gets
`return_type=FigureHandle` — a frozen dataclass `{token: str}` with a
serializer (R2). The component declares `figure: rx.Var[FigureHandle]`
(R1), so at compile:

- `reflex_xy.chart(figure=Dash.points)` → `TypeError: Invalid var passed for
  prop XYChart.figure, expected FigureHandle, got int`.
- A raw string → compile `TypeError`; `register()`/`inline()` return
  `FigureHandle` too, so legitimate paths keep working.
- A `create()` override (R5) rejects semantic-event props on static sources
  and malformed options with real errors, instead of the silent
  absorb-into-style behavior.

**Not checked:** the builder body. `xy.polar_scatter` inside `cloud()` still
fails at hydrate. This option fixes the component feel and the seam, not the
builder — pair with Option 2.

**Plumbing.** Unchanged. The handle serializes to `{"token": "xyv1|..."}` in
deltas; the wrapper reads `.token`. Registry, namespace, rebuild: untouched.

**cond/foreach.** `rx.cond` works as today. `rx.foreach(Dash.handles,
lambda h: reflex_xy.chart(figure=h))` works and is now type-safe: with
`handles: list[FigureHandle]` the item Var is typed (R4).

**Migration.** Non-breaking. The positional `chart(source)` form stays as a
deprecated shim; strings accepted one release via `Var[FigureHandle | str]`,
then tightened (the union weakens the check — keep it temporary).

**Variant 1b (upstream).** The literal "pass `State.cloud` bare into any
slot" needs a Var-type→component coercion hook in Reflex's child
normalization (R6). Both repos live under reflex-dev, so a small framework
hook is proposable — but it is a framework feature, not something the
adapter can fake, and should not gate anything here.

---

### Option 2 — Compile-time builder probe (a gate, not an API)

Make the builder body execute once at compile. Orthogonal to every other
option.

```python
@reflex_xy.figure                      # probed at compile by default
def cloud(self) -> xy.Chart: ...

@reflex_xy.figure(probe=False)         # opt out: builder needs a live session
def heavy(self) -> xy.Chart: ...
```

**Mechanics.** `XYPlugin`'s compile hook walks state classes, finds
`FigureVar`s, constructs a default state instance (Reflex already does this
for `initialState`), and calls the builder directly — bypassing the
token-minting short-circuit that currently keeps it dead (R3). Three levels:

- `probe="build"` (default): run the body only. Catches hallucinated `xy.*`
  names (`AttributeError`), wrong kwargs (`TypeError`), eager chrome-node
  errors (X1). Cost = the builder's own cost against *default* state.
- `probe="figure"`: additionally call `.figure()` — full config/shape
  validation, at the price of compiling one real figure per var at compile.
- `probe=False`: today's behavior. The default for `async def` builders
  (compile is sync; awaiting a DB at compile is what constraint 2 forbids).

Errors re-raise wrapped with state class, var name, and source location, so
the failure reads like a native Reflex compile error. Builders that touch
`self.router` (session-dependent) degrade to a warning, not a compile
failure.

**The tension, stated plainly:** the probe runs user code that may generate
`self.points = 200_000` rows at compile. That is bounded by *default* state,
happens once per compile, and mirrors the cost Reflex already accepts for
ordinary computed vars — but it is a behavior change, hence the escape
hatch and the session-access downgrade.

**Plumbing / cond / foreach / migration:** no changes anywhere; additive.
The only decision with teeth is defaulting `probe="build"` on.

---

### Option 3 — Chart components: structure in the tree, data by reference

*Kept for the record; subsumed by Option 6, which realizes this grammar as
its Level 2 with marks as plain xy nodes instead of components.*

The maximal option, anticipated by [`reflex-shaped-api.md`](reflex-shaped-api.md)
§6 ("a thin codegen layer... each factory maps 1:1 to a component"). Split
the chart into **structure** (built and validated at page evaluation, as real
Reflex components) and **data** (a state-backed source resolved at hydrate
through the existing registry).

```python
class Dash(rx.State):
    points: int = 200_000

    @reflex_xy.data                    # columns only — no chart API to hallucinate
    def cloud(self) -> dict[str, Any]:
        rng = np.random.default_rng(7)
        xs = rng.normal(size=self.points)
        return {"x": xs, "y": xs * 0.6 + rng.normal(scale=0.6, size=self.points),
                "mag": abs(xs)}

def index():
    return reflex_xy.scatter_chart(        # real components, mirroring xy 1:1
        reflex_xy.scatter(x="x", y="y", color="mag", colormap="viridis"),
        reflex_xy.x_axis(label="σ"),
        data=Dash.cloud,                   # Var[DataHandle] — the only reactive input
        on_select_end=Dash.on_select,
        height="460px",
    )
```

**Compile-time validation — the strongest of any option, all of it existing
xy validation moved to page-evaluation time:**

- `reflex_xy.polar_scatter(...)` → `AttributeError` at import of the page
  module. Hallucinations die where they are written.
- Wrong kwargs → `TypeError` from the real `xy.scatter(...)` factory, which
  each component factory calls underneath to build the actual dataclass tree
  (string channels, no data — X1).
- Bad enums/colormaps/axis refs → the factory binds zero-row placeholder
  columns for every named channel and calls `.figure()` once (X2): the full
  mark validation gate runs at compile, in milliseconds, with no data.
- **Cannot be checked without data:** whether the named columns exist in the
  runtime table, and real shapes/dtypes. Those surface at first publish with
  a spec-aware error ("mark `scatter` binds column `'mag'`; data var
  `Dash.cloud` produced columns {x, y}") — a far better hydrate failure than
  today's, because the spec is known.

**Plumbing.** The factory serializes the validated tree (dataclass nodes →
canonical data-free JSON) and content-addresses it: `spec_digest`. Because
prod workers re-evaluate page bodies (X4), every worker's spec registry is
populated at startup by the same evaluation. The token becomes
`xysp1|<client>|<state>|<data_var>|<spec_digest>`. On `sub`: look up the
spec by digest, run the data var against session state (the existing
`state_bridge` machinery, fetching columns instead of a Chart), bind columns
into a fresh Chart (X3), `figure()`, register under the token. Data lives in
the registry exactly as today; state holds only the small handle. The
rebuild recipe = spec (deterministic from source, present in every worker) +
data var (state) — strictly *more* recoverable than an opaque builder.

**cond/foreach.** These *are* components: composition is native, and eager
`rx.cond` branches mean both structures get validated. In `rx.foreach`, the
structure is fixed per render function (built once with the placeholder Var
— R4) and the `data` prop is the typed item Var. Structure *varying per
item* is impossible — but that is Reflex's universal foreach contract, not a
chart limitation; `rx.cond`/`rx.match` inside the render fn covers discrete
cases.

**Side benefits.** Live charts get automatic Tailwind class discovery
(class strings are structure, not data — today live sources need the manual
`tailwind_classes=` inventory). Later, scalar config props could accept Vars
compiled into a small spec-patch channel (Reflex-owned reactivity, no data
in state) without changing the transport.

**Migration.** Additive: `@reflex_xy.figure` + the Option-1 component remain
as the "full-Python tier" for charts whose *structure* genuinely depends on
state (dynamic mark counts, data-driven annotations). Cost is real: a
generated factory layer (~90 factories mirroring `components.py`), a spec
serialization format that must track the grammar, and a second token family
in the namespace.

---

### Option 4 — `ChartState`: a ComponentState fusion

A chart as a self-contained, instantiable component with its own state — the
Reflex-native answer to "a chart is a thing I drop into a page".

```python
class Cloud(reflex_xy.ChartState):
    points: int = 200_000

    def build(self) -> xy.Chart:
        x, y = make(self.points)
        return xy.scatter_chart(xy.scatter(x, y))

    @rx.event
    def more(self):
        self.points *= 2

def index():
    return rx.vstack(
        Cloud.create(height="460px"),
        Cloud.create(height="200px"),   # an independent second instance
        rx.button("more", on_click=Cloud.more),
    )
```

**Mechanics.** `ChartState` subclasses `rx.ComponentState`; `get_component`
wires the Option-1 typed component to a figure var auto-derived from
`build`. Each `.create()` mints a fresh state class (`Cloud_n1`, `Cloud_n2`)
at compile — Reflex's own per-instance mechanism — so the token
(`xyv1|client|Cloud_n1|cloud`) resolves through the existing rebuild path
(minted classes are registered for pickling; resolution needs a test, not
new machinery). Uniquely, this gives **per-mount isolation**: today all
mounts of one figure var share kernel drill state.

**Compile-time validation.** Class creation checks `build`'s signature and
return annotation; the body is still deferred — pair with Option 2's probe.
Prop checks come from the underlying Option-1 component.

**cond/foreach.** `rx.cond`: fine. `rx.foreach`: **hard-blocked by Reflex**
(R4) — the framework cannot mint N state classes for a runtime-length list.
That hole disqualifies this as the primary API; it is sugar for the
dashboard-widget case.

**Migration.** Pure sugar over Options 1+2; nothing breaks.

---

### Option 5 — Eager spec on the state class (structure at import, data by method)

*Kept for the record; subsumed by Option 6, which keeps this option's
structure/data split but moves the declaration into the page tree and hides
the spec object entirely.*

Option 3's structure/data split, but keeping the declaration on the state
class — and moving execution from hydrate to **import**.

```python
class Dash(rx.State):
    points: int = 200_000

    cloud = reflex_xy.figure_spec(
        xy.scatter_chart(                  # ← real xy call, executes AT IMPORT
            xy.scatter(x="x", y="y", color="mag"),
            width="100%",
        )
    )

    @cloud.data                            # columns only, resolved at hydrate
    def _cloud_data(self) -> dict[str, Any]:
        ...

def index():
    return reflex_xy.chart(figure=Dash.cloud, height="460px")   # Option-1 component
```

**Compile-time validation.** The spec expression is module-level Python:
`xy.polar_scatter` → `AttributeError` **at import**, before Reflex even
starts compiling — the earliest failure any option achieves, and the
friendliest to agent loops (`python -c "import app"` catches it).
`figure_spec` runs the zero-row `.figure()` probe (X2) at construction, so
config errors are import errors too. The uncheckable remainder matches
Option 3: column existence and shapes in real data, which fail at publish
with spec-aware messages.

**Plumbing.** `figure_spec` is a descriptor that installs a `FigureVar`
whose builder is *derived*: run the data method, bind the columns into a
fresh copy of the spec tree (fresh `Chart`, never mutation — X3),
`figure()`, publish under the standard `xyv1|...` token. No new token
family, no spec-distribution question — the spec is a module-level object
present in every worker by definition. Registry, namespace, rebuild:
byte-identical to today.

**cond/foreach.** Identical to Option 1 (the tree side *is* the Option-1
component). No new composition power — the trade against Option 3.

**Migration.** Additive. `@reflex_xy.figure` keeps covering
structure-from-state charts; `figure_spec` becomes the recommended default
for the majority case where only data is reactive.

---

### Option 6 — Data-bound chart components (the synthesis; recommended)

Review feedback on Options 3 and 5 converged on a sharper shape: the chart
should be declared **exactly once, where it is rendered**, with state
supplying only reactive data. No figure method for the common case, no
spec/template object in user code, no manual handle. Two user-visible
levels, plus the existing builder as escape hatch.

**Level 1 — flat, single-mark (the common case):**

```python
from typing import TypedDict
import numpy as np
import reflex as rx
import reflex_xy as rxy

class CloudData(TypedDict):
    x: np.ndarray
    y: np.ndarray
    mag: np.ndarray

class Dash(rx.State):
    points: int = 200_000

    @rxy.data                          # columns only — no chart API to hallucinate
    def cloud(self) -> CloudData:
        rng = np.random.default_rng(7)
        x = rng.normal(size=self.points)
        return {"x": x, "y": x * 0.6 + rng.normal(scale=0.6, size=self.points),
                "mag": np.abs(x)}

def index() -> rx.Component:
    return rxy.scatter_chart(
        data=Dash.cloud,
        x="x", y="y", color="mag", colormap="viridis",
        x_axis=rxy.x_axis(label="σ"),
        height="460px",
        on_select_end=Dash.select,
    )
```

**Level 2 — composed, multi-mark:**

```python
def index() -> rx.Component:
    return rxy.chart(
        rxy.scatter(x="x", y="y", color="mag", colormap="viridis"),
        rxy.line(x="x", y="trend", width=2),
        rxy.x_axis(label="Time"),
        rxy.y_axis(label="Value"),
        data=Dash.cloud,
        height="460px",
    )
```

**Level 3 — escape hatch (unchanged, structure genuinely from state):**

```python
class Dash(rx.State):
    @rxy.figure
    def dynamic(self) -> xy.Chart:
        return xy.scatter_chart(...) if self.mode == "scatter" else xy.line_chart(...)

def index():
    return rxy.chart(figure=Dash.dynamic)      # Option 1's typed component
```

**`@rxy.data` and the handle.** The decorator produces a `DataVar` — a
computed var in the exact mold of today's `FigureVar` — whose *value* is a
tiny `DataHandle` (`{"token": "xyd1|<client>|Dash|cloud"}`; frozen
dataclass with a one-line `@rx.serializer` → dict for the delta path).
Evaluating the var runs the data method and publishes the **columns** into
the per-process registry under the token; dependency tracking points at the
method body, so a state change republishes columns and pushes fresh
payloads to every chart bound to that data. Like `FigureVar`, the getter
short-circuits before a session exists — **user data code never executes at
compile** (constraint 2 holds by the same mechanism that holds today).

The generic annotation is the schema channel (R7, verified): the class-level
`Dash.cloud` Var carries `_var_type = DataHandle[CloudData]`; the factory
recovers `CloudData` via `get_args` and its column names via
`get_type_hints` — *without executing anything*. A data method annotated
plain `dict[str, np.ndarray]` degrades gracefully: no compile-time column
check, validated on first execution with a spec-aware error.

**Compile-time validation timeline** (each mechanism labeled):

| failure | fires at | mechanism |
|---|---|---|
| `rxy.polar_scatter_chart(...)` | **import** | explicit export surface (`AttributeError`) |
| unknown mark/chart kwarg, near-miss typo (`colormapp=`, `on_selection_end=`) | **compile** | factory kwarg partition + difflib suggestion (R8: events already error; others need the partition) |
| `colormap="virids"`, bad enums, bad axis refs | **compile** | build the real xy tree, bind zero-row placeholder columns, `.figure()` once (X1/X2) |
| `x="timestamp"` against a `TypedDict`-annotated data var | **compile** | schema from `_var_type` (R7): *Unknown column "timestamp" for Dash.cloud. Available: x, y, mag* |
| `data=Dash.points` / `data="raw string"` | **compile** | `Var[DataHandle]` prop check (R1/R7, verified) |
| column existence (untyped data), lengths, shapes, dtypes | **hydrate/publish** | inherent — requires real data; error names the spec's bindings vs the produced columns |

**Plumbing.** The factory compiles kwargs → real xy tree → validated,
data-free plan → canonical JSON → `spec_digest`, registered in a
process-local spec registry during page evaluation (every worker evaluates
pages — X4). The component carries two props: `spec` (literal digest, baked
into the JSX at compile) and `data` (the handle Var, resolved from state at
runtime). On `sub {spec, data_token}`: look up the plan by digest, resolve
columns (registry hit, or rebuild via the state bridge running the data
method against session state), bind columns into a fresh `Chart` (X3),
`figure()`, cache per `(spec_digest, data_token)`, serve binary payload.
Rebuild recipe = plan (deterministic from source, present in every worker) +
data method (state) — the same two-plane, registry-as-cache architecture as
today, with the figure split into its two independently-cacheable halves.
Users never see `ChartPlan`, digests, or the spec registry.

**cond/foreach.** Both levels return ordinary components: `rx.cond` between
two charts works (and eagerly validates both). `rx.foreach(Dash.handles,
lambda h: rxy.scatter_chart(data=h, x="x", y="y"))` type-checks per item —
the element Var keeps `DataHandle[CloudData]` (R7), so even column names
are compile-checked inside the loop.

**Design decisions the review forced, recorded:**

1. **Marks are xy nodes, not Reflex components.** Reflex child validation
   rejects arbitrary dataclasses (`ChildrenTypeError`), so `rxy.chart(...)`
   is a *factory* that consumes mark/chrome nodes before any component is
   created — they never enter the Reflex tree. `rxy.scatter` can literally
   re-export `xy.scatter` (zero duplication; hallucinated names still die
   at import). Consequence: `rx.cond` cannot switch marks *inside* one
   chart — the spec is server-compiled, so conditional structure is
   `rx.cond` between two chart calls, or Level 3. Same boundary as
   Option 3, now explicit.
2. **The flat form needs a kwarg partition rule.** `scatter` is clean, but
   the collision set is real and small: `width` (chart size vs `line`
   stroke), `opacity`, `style`, `class_name`, `key`, `animation` exist at
   both mark and component level. Rule: component/chart level wins;
   colliding mark options get flat-form aliases (`stroke_width=` — hence
   the Level-2 example) or use the composed form. The partition table is
   part of the public contract and must be generated, not hand-listed.
3. **Generate the flat layer from signatures, not a new registry.** xy's
   own convention — positional params are data channels, keyword-only are
   options, uniformly across every mark — means `inspect.signature`
   mechanically yields the flat form's accepted kwargs, and the zero-row
   probe reuses the real validators in `marks.py` (no parallel enum
   tables to drift). A full `ScatterDefinition`-style metadata registry in
   core xy (also generating stubs and docs) remains attractive, but it is
   a separate core investment, not a prerequisite — this defuses the
   "~90 handwritten parallel factories" objection to Option 3 without it.
4. **Typed column references (`x=Dash.cloud.x`) are deferred.** Verified
   broken today (R9: attribute access on a parametrized-generic Var raises
   `VarAttributeError`); needs an upstream reflex fix. Strings + TypedDict
   give nearly the same validation with none of the machinery.

**Open questions (tracked, not hand-waved):**

- **Dynamic dataset collections.** `foreach` over charts works when a
  `list[DataHandle[...]]` exists in state — but handles are minted by
  computed vars (one var = one dataset). A runtime-length *collection* of
  datasets needs either a keyed-dataset extension (a data var returning a
  dict of tables, charts binding `(handle, key)`) or N declared vars.
  Design before implementing; do not ship an accidental contract.
- **Per-mark `data=`** (two marks, two sources, one chart): the xy grammar
  allows it; v1 binds one chart-level data var. Extend the spec format
  only when a real use case lands.
- **Static tier symmetry**: `data=` accepting concrete arrays (not a Var)
  could route to the existing static payload asset tier, mirroring
  `chart(xy.Chart)` today. Cheap, optional.

**Migration.** Additive: today's `chart(source)` and `@rxy.figure` keep
working (Level 3 *is* the current model behind Option 1's typed seam).
Options 3 and 5 are subsumed — 3's grammar survives as Level 2 with marks
as re-exports instead of components; 5's structure/data split survives as
the plan/data-var split, minus the user-visible spec object.

---

## 6. Comparison

| | 1 · Typed handle | 2 · Compile probe | 3 · Chart components | 4 · ChartState | 5 · Eager spec | 6 · Data-bound |
|---|---|---|---|---|---|---|
| Feels like a Reflex component | ✅ (plotly-style) | — (no API change) | ✅✅ (is the tree) | ✅✅ per-instance | ✅ (via 1) | ✅✅ (declared where rendered) |
| Hallucinated chart API fails at | hydrate ✗ | **compile** | **import/compile** | hydrate (compile w/ 2) | **import** | **import/compile** |
| Wrong kwargs / bad config fails at | hydrate ✗ | compile | **compile** (zero-row probe) | via 2 | **import** (zero-row probe) | **compile** (partition + zero-row probe) |
| Wrong var into chart slot | **compile** ✅ | — | **compile** ✅ | **compile** ✅ | **compile** ✅ | **compile** ✅ (verified) |
| Column names | hydrate | via `probe="figure"` | hydrate, spec-aware error | hydrate | hydrate, spec-aware error | **compile** (TypedDict, R7) |
| Data shapes / lengths / dtypes | hydrate (inherent) | via `probe="figure"` | hydrate | hydrate | hydrate | hydrate (inherent) |
| Constraint 1 (no data in state) | ✅ unchanged | ✅ unchanged | ✅ (data registry) | ✅ unchanged | ✅ unchanged | ✅ (data registry) |
| Constraint 2 (no compile ingestion) | ✅ | ⚠️ builder runs on default state (opt-out) | ✅ zero-row only | ✅/⚠️ with 2 | ✅ zero-row only | ✅ zero-row only |
| `rx.cond` | ✅ | — | ✅ | ✅ | ✅ | ✅ (between charts) |
| `rx.foreach` | ✅ typed item | — | ✅ (fixed structure per item) | ❌ framework-blocked | ✅ typed item | ✅ schema-checked per item (R7) |
| Structure reactive to state | ✅ (builder) | ✅ | ❌ (data/cond only) | ✅ | ❌ (data only) | ❌ (Level 3 escape hatch) |
| Breaking changes | none (deprecations) | none | none (additive tier) | none | none | none (additive; old forms become Level 3) |
| Implementation cost | small | small | **large** (factory layer + spec format + token family) | medium | medium | medium-large (signature-derived flat layer + plan format + data vars) |

*"Compile" = page evaluation during `reflex run`/`export`; "import" = plain
`import app`, even earlier.*

## 7. Recommendation

**Build Option 6 as the primary API. It subsumes the others**: Option 1's
typed component seam becomes Level 3's rendering path, Option 5's
structure/data split becomes the internal plan/data-var split (minus the
user-visible spec object), and Option 3's grammar becomes Level 2 with
marks as plain xy re-exports instead of components. Option 2's probe
remains valuable for exactly one tier — the Level 3 `@rxy.figure` escape
hatch, the only place left where chart-building user code is deferred to
hydrate. Option 4 stays on the shelf as later sugar for self-contained
dashboard widgets.

Phasing that keeps every step shippable:

1. **Seam first** (Option 1 mechanics): typed `DataHandle`/`FigureHandle`,
   the public component, compile-time prop rejection. Small, non-breaking,
   immediately kills the wrong-var-in-the-slot class.
2. **`@rxy.data` + Level 1 flat factories** for the top few chart kinds
   (scatter, line, histogram, bar), generated from `inspect.signature`,
   with the kwarg partition, zero-row probe, and TypedDict column checks.
   This is the DX headline and proves the plan/data split end to end.
3. **Level 2 composed `rxy.chart(...)`** + the remaining chart kinds +
   spec-format stabilization.
4. **Probe for Level 3** (Option 2), so the escape hatch fails at compile
   too.
5. Revisit: keyed dataset collections for `foreach`, per-mark `data=`,
   the core-xy metadata registry (stubs/docs), upstream reflex fixes.
   Both upstream sites are located in the reflex monorepo: generic
   attribute access (R9) in `get_attribute_access_type`
   (`packages/reflex-base/src/reflex_base/utils/types.py` ~:436 — add a
   `get_origin()` unwrap before the bare-class branch), and Var-type
   child coercion (R6) in `Component.create`'s child normalization
   (`packages/reflex-base/src/reflex_base/components/component.py`
   ~:1314, where a Var child currently becomes
   `Bare.create(contents=...)` — a `_var_type` → component-factory
   registry consulted just before that fallback would make
   `rx.card(State.cloud)` render a chart).

**The "pass it directly in the component tree" instinct** is Option 6
literally: the chart is declared once, in the tree, and the state var
passes directly into its `data=` slot — the `rx.plotly(data=State.fig)`
shape generalized. The only unimplementable reading remains the bare
`rx.card(State.cloud)` with no call at all (R6); the upstream coercion
hook is worth proposing but gates nothing.

**Implementation cautions.** Option 6 rests on verified-but-unpinned
behavior in two systems: reflex carrying parametrized generics through
vars, foreach element inference, and `Var[T]` prop rejection (R7); xy
compiling zero-row figures and validating marks only at `.figure()`
(X1/X2). Pin all of it as adapter tests *before* building, so a reflex or
grammar upgrade fails loudly. `DataHandle` needs its one-line serializer
registered. The flat-form kwarg partition table is public contract:
generate it and test it. When any option ships,
[`reflex-integration.md`](reflex-integration.md) §5 must record the new
API tiers and the validation-timing table, per the spec-first rule.

---

## 8. Decision record (2026-08)

**Adopted: Option 6 — data-bound chart components — as the primary API**,
with Option 1's typed seam as the rendering path of every tier and
Option 2's compile probe for the Level 3 escape hatch. Options 3 and 5 are
subsumed as anticipated in §7; Option 4 stays on the shelf.

Implementation notes recorded against the plan (deviations are deliberate
and small):

- The `@reflex_xy.data` module is **`data_vars.py`**, not `data.py`: a
  `reflex_xy.data` submodule shadows the `reflex_xy.data` function export
  the moment any sibling imports it (Python submodule-attribute collision).
  The public name is unchanged.
- The flat-form collision aliases are generated as `mark_<name>`, with one
  natural special case: a mark `width` becomes `stroke_width` when the mark
  hasn't already claimed that name (so `line`'s width is `stroke_width=`,
  `bar`'s is `mark_width=` — `bar` natively owns `stroke_width`). The table
  is pinned in `tests/reflex_adapter/test_factories.py`.
- `x_axis=`/`y_axis=` in the flat form are type-dispatched: an Axis node is
  chrome, a string is the mark's axis-id option; `legend=` takes a Legend
  node or bool, `theme=` a Theme node. Other chrome composes via
  `reflex_xy.chart(*nodes, ...)`.
- The positional `chart(source)` shim warns only for live sources
  (vars/handles/token strings). The positional **static** Chart/Figure form
  is not deprecated — it remains the only route for arbitrary Charts (e.g.
  facet grids) and predates no replacement.
- The client bounds consecutive server-initiated `err {resync}` retries
  (5 per mount without an intervening payload), so a permanently stale
  plan digest or failing bind degrades to a visible console error, not a
  subscribe loop.
- Kernel-only event props on a static source now fail `create()` with a
  `ValueError` (previously silent no-ops), completing the §5.6 error
  catalog; every row of that catalog is reproduced by the adapter tests at
  the stated phase.
- **Fact X4 needed narrowing.** "Page bodies run in every worker" is true
  of workers that run the frontend compile, but backend-only workers (dev
  backend subprocess, prod workers) import the app without evaluating
  pages — verified live when the first data-bound app served nothing but
  plan-miss errs from a dev backend. The adapter now evaluates the app's
  unevaluated pages in its startup lifespan, making the plan-distribution
  property a guarantee of the integration rather than an observed Reflex
  behavior.
- **The aggregating-kind exclusion was revised (2026-08, twice).** The
  plan tier originally refused box, violin, hexbin, contour, heatmap,
  stairs, and ecdf because their validators need at least one finite
  value and a synthetic probe "would validate against made-up data". A
  first revision recorded fixed synthetic shapes per (kind, channel);
  review proved the original objection right after all — shared columns
  and value-dependent config (hexbin `range=`/`mincnt=`) failed on the
  invented values, and large grids aggregated at page evaluation. The
  final design moves the fix into the core instead of the data:
  `xy.structural_probe()` mode, under which an all-empty mark validates
  configuration and skips aggregation, so every kind probes zero-row with
  no synthetic data at all. Every standalone mark kind now has a flat
  factory and composes; only the data-taking composite factories
  (pie, radar, wind_rose, sankey) stay on the static/escape-hatch routes.
  Details: reflex-integration.md §3.6 "Kind coverage",
  spec/api/chart-kind-contract.md "Structural probe", and the
  implementation doc's post-landing revision record.
