# Renderer Architecture — Audit & Target Design

**Status:** audit of the shipped WebGL2 render path + the architecture it
should converge to as chart kinds multiply. Findings below are verified
against the source, not hypothetical.

**Scope.** The client builds from 15 parts, concatenated in filename order into
one bundle by `js/build.mjs`. The audit findings in §2 cover the render path —
`40_gl.js`, `45_lod.js`, `50_chartview.js`, `55_marks.js`, `60_entries.js`.
The module inventory below covers all 15. Ticks and axis label formatting
(`30_ticks.js`) are specified in §6; the gesture contract in `53_interaction.js`
is specified in [interaction.md](../api/interaction.md) §5, and the client half of
the kernel channel (`54_kernel.js`) in [wire-protocol.md](wire-protocol.md).
What remains normatively unspecified is the ARIA/DOM accessibility contract —
see R11.

### Module inventory

Line counts are as of this revision and will drift; they are recorded to show
relative mass, not as a budget (see §3 on why a line count failed as a metric).

| Module | Lines | Responsibility |
| --- | ---: | --- |
| `00_header.js` | 172 | Bundle preamble: the client-wide design comment, the `PROTOCOL` version constant, and the binary frame codec (`XY_FRAME_MAGIC` `"XYBF"`, `decodeFrame`, 8-byte alignment). Every inbound frame is validated here — magic/version, u64 fields, zero-padding, and per-field size limits — before any other module sees it. |
| `10_colormaps.js` | 51 | The `COLORMAP_STOPS` table (§36 CVD-safe defaults) as compact RGB stop lists, and `buildLutData`, which linearly interpolates a stop list into the 256-texel RGBA LUT uploaded once per colormap as a texture. |
| `20_theme.js` | 163 | Resolves chrome and mark colors: arbitrary CSS color expressions and `--chart-*` custom properties are resolved against a live probe element into f32 RGBA for GL, with a fallback on unparseable input. Also owns `XY_CHROME_CSS` and its one-time stylesheet injection. |
| `30_ticks.js` | 224 | CPU-side tick generation in f64 for linear, log, category and time axes, plus every axis/colorbar label formatter (automatic and `format=`-driven). Specified in §6. |
| `40_gl.js` | 829 | WebGL2 primitives: shader compile/link, `makeProgram` with its per-program uniform-location memo (R1), the fixed `ATTR_SLOTS` attribute-slot table bound at link time, and the shader inventory itself. The only module that is GPU-API-specific by design (§4). |
| `45_lod.js` | 567 | View-dependent level-of-detail orchestration, deliberately chart-agnostic: tier selection, drill enter/exit hysteresis (`LOD_DRILL_EXIT_FACTOR`), cross-tier fades, and the retained tier caches. Calls back into `view._draw*` rather than drawing itself, which is the seam tests intercept. |
| `46_worker.js` | 59 | The standalone density re-bin worker: a worker source string carried inside the bundle and booted from a Blob URL. Re-bins the retained sample off the main thread so kernel-less (`to_html`) density charts refine on zoom instead of stretching the overview texture; absence of workers falls back to stretching. |
| `50_chartview.js` | 4175 | The `ChartView` class: the four drawing surfaces, scale/view state, chrome (background, grid, axes, legend, colorbar), GL buffer and VAO management (R2), and pick orchestration. Modules 51–54 extend this same class. |
| `51_annotations.js` | 591 | The 2D overlay canvas above the marks canvas: annotation markers, arrows, shape fills, and collision-nudged labels. Separates canvas shape style keys from label CSS so annotation styling never leaks into the DOM label. |
| `52_tooltip.js` | 321 | Hit → source row → tooltip DOM. Anchors the tooltip at the picked point's data coordinates and reprojects it every draw ([interaction.md](../api/interaction.md) §7). Renders the local f32-decoded row immediately, then replaces it with the kernel's exact f64 row when that reply arrives (sequence- and `drill_seq`-guarded); composes text nodes, never HTML. |
| `53_interaction.js` | 1820 | The entire user-facing interaction surface: pointer/drag/wheel wiring, crosshair, box select, box zoom, lasso, the modebar and its export menu, and the animated pan/zoom view state machine. The gesture→action mapping, the modebar tool inventory and the `interaction_config` switches are specified in [interaction.md](../api/interaction.md) §2 and §5. |
| `54_kernel.js` | 437 | The client half of the kernel channel: debounced density/decimated view-requests, streaming `append` handling, the inbound message dispatcher, and the deep-zoom drill lifecycle (§16). Degrades to `46_worker.js` when there is no comm. The message catalog it consumes is specified in [wire-protocol.md](wire-protocol.md). |
| `55_marks.js` | 220 | The `MARK_KINDS` registry — `build`/`draw` per kind plus the `pointPick`/`retainCpu`/`refreshColor` capability flags — mirroring the kernel's `_emit_<kind>` dispatch so adding a 2D chart is an entry here, not a branch in `ChartView`. |
| `56_animation.js` | — | Declarative entrance/update/exit state machine, easing/spring evaluation, bounded identity matching, full-payload replacement, interruption, reduced-motion resolution, and lifecycle events. Its normative behavior is in [animation.md](animation.md). |
| `60_entries.js` | 76 | Mount/unmount entry points for both hosts (`render` for anywidget, `renderStandalone` for exported HTML) and `payloadBuffers`, which materializes first-paint columns in whichever layout the spec declares. Keeps aligned views zero-copy; a spec/transport disagreement throws. |

## 1. What's structurally right (keep)

- **Mark registry** (`MARK_KINDS` + capabilities `pointPick/retainCpu/
  refreshColor` + `markOf` fallback): the render loop is kind-blind; new
  kinds are entries. This is the load-bearing decision — preserve it.
- **LOD module** (`45_lod.js`): tier orchestration/fades/caches are outside
  ChartView and call back through `view._draw*`, so tests intercept the
  renderer and future kinds can swap mark drawing. Keep the callback seam.
- **Four-surface layering**, bottom to top: 2D chrome canvas (background,
  grid, axes) → GL canvas (marks) → 2D overlay canvas (annotation shapes:
  markers, arrows, shape fills, nudged labels) → DOM (labels/tooltip/
  legend/modebar/crosshair). The overlay sits *above* the marks canvas by
  design: the exporters emit annotation marks after every data trace, and a
  dense opaque mark (heatmap) would otherwise bury them. Crisp text,
  selectable tooltips, zero GL cost for chrome — correct division (§7).
- **Uniform-only pan/zoom**: geometry is static offset-encoded f32; view
  changes touch two vec2 uniforms per mark (`_map`). This is why interaction
  is cheap; nothing below may regress it.
- **Bounded inputs in the aggregated tiers**: decimated ships M4 output
  bounded by the plot's pixel width; density ships a fixed grid. Direct-tier
  traces still ship O(N) columns — the bound there is the tier threshold, not
  the screen: `DECIMATION_THRESHOLD` = 10_000 for lines/areas,
  `SCATTER_DENSITY_THRESHOLD` = 200_000 for scatter, raised to
  `DIRECT_SOFT_CEILING` = 2_000_000 when a per-point color or size channel is
  present (`python/xy/config.py`). Dossier §31 states the same claim
  mode-scoped: 12–24 bytes/point in direct modes, screen-bounded *resident*
  memory in the aggregated ones.
- **Two first-paint wire layouts**, and the renderer branches on the spec, not
  on the transport. *Packed*: one blob, every column carrying a global
  `byte_offset`. *Split*: `buffer_layout: "split"` in the spec and one wire
  buffer per column, each column carrying an integer `buf` index into the
  buffer list — this skips the join copy, the largest allocation of a
  direct-tier build. Split is what both shipping hosts use
  (`build_payload_split` in `python/xy/widget.py` and
  `python/reflex-xy/reflex_xy/namespace.py`); packed remains for standalone
  export and for streaming `append`, which always re-ships packed
  (`python/xy/interaction.py`). `payloadBuffers` (`60_entries.js`) and
  `_columnView` (`50_chartview.js`) treat any spec/transport disagreement as a
  thrown error — fail loud, never a silent fallback.
- **DPR correctness**: backing stores sized `css × devicePixelRatio`
  everywhere including the pick FBO and its lazy resize-realloc; line widths
  and point sizes multiply by dpr. Audited clean. (Gap: DPR *changes* — see
  R7.)

## 2. Audit findings — must-fix-before-20-charts list

Ordered by how much each compounds as kinds multiply.

- **R1 — Per-draw uniform lookups.** ✅ **Done.** `makeProgram` attaches a
  per-program memo and all draw sites go through `uniformOf()`; each name
  hits the driver once at first use. Verified by the pixel-determinism
  smoke probe (bitwise-identical frames through the cached path).
- **R2 — No VAOs.** ✅ **Done.** `_bindVao(g, key, parts, setup)` keeps one
  VAO per (trace × draw-config). The config signature is `parts.join("|")` —
  buffer identity tags (`buf._fcId`, bumped on every `_upload`) plus the
  on/off state of the optional channels — so a replaced buffer (data update,
  drill swap) rebuilds its VAO rather than aliasing a stale one. Attribute
  slots are fixed at link time by `ATTR_SLOTS` + `bindAttribLocation`, so one
  VAO is valid for every program that draws the trace; draw and pick share
  it. This removed the per-frame `getAttribLocation`/enable/pointer/divisor
  churn *and* the leftover-attrib disable loops, including their per-frame
  `getParameter(MAX_VERTEX_ATTRIBS)` driver round-trip. `_deleteVaos` frees
  them on teardown; the grid quad holds its own VAO. Landed ahead of the R9
  rect-pick trigger it was originally sequenced behind. Note the VAO
  utilities live in `50_chartview.js`, next to the GL context they mutate,
  not in `40_gl.js` as §3 originally projected.
- **R3 — Draw-state discipline.** Re-audit: the discipline is currently
  sound — BLEND is enabled once at init and toggled in exactly one place
  (the pick pass, correctly paired), and every texture bind sets its unit
  explicitly. A `withState` helper today would be ~40 lines guarding one
  pair — over-engineering by this codebase's own standard. **Deferred:**
  adopt when a second state-toggling pass lands (e.g. scissored panels or
  an additive-blend mark).
- **R4 — No GL context-loss handling.** ✅ **Done.**
  `_initContextLossRecovery` listens for loss, prevents default eviction
  handling, quiesces draw/animation/re-bin work, and increments the request
  sequence so pre-loss kernel/worker replies cannot mutate the rebuilt state.
  Streaming appends still replace the retained canonical payload while the
  context is down. Restore drops dead handles, re-runs `_initGl` from that
  payload, and re-fires the view request to re-sync live tiers; a failed
  restore remains explicitly failed instead of throwing from the event
  handler. The dependency-free smoke forces three `WEBGL_lose_context`
  cycles, checks pixel-identical frames after each, and zooms after recovery.
- **R5 — Shader source conventions are informal.** ✅ **Done.** `build.mjs`
  lints every shader at build time: `#version 300 es` first line, every FS
  declares `precision highp float;`, every VS references a `u_*map` uniform
  (quad shaders exempted by name), uniforms `u_`-prefixed, attributes
  `a`-prefixed. Violations fail the build (negative-tested).
- **R6 — Instancing is per-mark bespoke.** Line uses 4-corner strip +
  divisor-1 endpoints; rects likewise; points use POINTS. `MARK_KINDS` now
  registers 18 kind names over 9 mark objects (`RECT_MARK`, `BAR_MARK`,
  `SEGMENT_MARK`, `MESH_MARK`, `AREA_MARK`, plus inline hexbin, heatmap,
  scatter and line), so kind growth has so far been absorbed by *reusing*
  mark objects rather than by adding shaders: the corner-expansion preamble
  is duplicated across `RECT_VS` and `BAR_VS`, not once per kind. The
  duplication the finding predicted is therefore real but small, and
  `GLSL_COMMON` does not exist yet. *Fix, still pending:* extract shared VS
  chunks (corner tables, px↔clip helpers) via string includes in `40_gl.js`
  (`GLSL_COMMON`), not a shader framework. Deliberately stop there — a
  "shader graph" is over-engineering at this scale. The original "fine at 5
  kinds" deferral rationale has expired; the trigger is now a third
  corner-expanding VS.
- **R7 — DPR/zoom *changes* aren't observed.** ✅ **Done.** `_armDprWatch`
  re-arms a one-shot `matchMedia('(resolution: Ndppx)')` per dpr value;
  `_resize` re-reads devicePixelRatio so a pure-DPR change re-derives
  backing stores with no container resize. Smoke `dprw` flag covers it.
- **R8 — Lifecycle cleanup.** ✅ **Already complete** (re-audit): `destroy()`
  → `_destroyGlResources` frees per-trace static + drill buffers, density/
  heatmap/LUT textures (dedup via `texSeen`), pick FBO/texture, the quad, and
  all programs, then releases the GL context itself via `WEBGL_lose_context`
  so a torn-down view (including a full-payload republish's destroy+rebuild)
  frees its context slot immediately instead of waiting for GC. The original
  finding is stale. Remaining nicety only: move per-kind buffer-name lists into
  a registry `dispose` hook when a kind arrives whose resources don't fit the
  shared name list.
- **R9 — Picking model won't stretch as-is.** GPU ID pass is point-only
  (`pointPick`); rect-family picking (bars/candles) is planned as a
  registry `pick` step (contract). The ID encoding is a single *global*
  32-bit integer (`u_pick_base + gl_VertexID`) packed across all four RGBA8
  channels — alpha carries id bits 24–31, it is not a per-trace slot. Trace
  ranges are `[pickBase, pickBase + n)`, bases start at 1 so the all-zero
  clear stays the background sentinel, and the hit is resolved by range
  containment. The limit is therefore cumulative *pickable vertices*, not
  trace count; the overflow guard already exists (`base + pg.n > 0x7fffffff`
  marks the trace unpickable rather than aliasing a stale range) and must be
  preserved as rect-family traces start consuming id space. One addition
  when rect picking lands: shared pick-VS chunks per R6, so each mark's ID
  pass reuses its draw geometry.
- **R10 — Tooltip data path**: solid (local approx row → kernel-exact
  replacement, seq-guarded, drill_seq-versioned, XSS-safe text nodes). Only
  gap: the row schema is implicit per kind. Write it down in the chart-kind
  contract (`{x, y?, ohlc?, color_*?}` + `_dist` for non-point hover) so new
  kinds emit compatible rows — doc task, no code.
- **R11 — Client parts are unspecified.** *Mostly closed.* Every module now
  has a one-paragraph contract in the inventory above; `30_ticks.js` has a
  full specification in §6; and the two largest remaining gaps have since been
  written down. `53_interaction.js` is the second-largest module in the bundle
  and defines the entire user-facing gesture and chrome-interaction contract —
  drag pan, wheel zoom, box select and box zoom, lasso, double-click reset,
  the modebar and its export menu, tooltip show/hide, and keyboard point
  navigation — and [interaction.md](../api/interaction.md) now specifies it: §5 is
  the normative gesture→action table (`shift` is the only modifier the
  renderer reads anywhere in `js/src/`) with the per-gesture required
  switches, §5 also carries the modebar tool inventory, §2 is the
  `interaction_config` switch table with defaults, §3 the event payloads, and
  §7 the unconditional behaviors. `54_kernel.js` (the client half of the
  channel protocol) is specified in [wire-protocol.md](wire-protocol.md), as
  are `00_header.js`'s `PROTOCOL` constant and XYBF envelope (§7 there);
  `20_theme.js`'s token resolution is specified in [export.md](../api/export.md)
  §6, and `46_worker.js`'s standalone re-bin role in design-dossier.md §8.
  Only `51_annotations.js`, `52_tooltip.js` and `10_colormaps.js` still have
  no spec reference beyond the inventory above. **Remaining doc task:** the
  ARIA/DOM accessibility contract. interaction.md states *that* keyboard
  traversal and a live-region readout exist and are unconditional. What no
  document states *normatively* is the DOM that implements them: the
  `role="region"` root with its `aria-label`/`aria-describedby` summary, the
  `role="status"` `aria-live="polite"` readout, the `role="img"` focusable
  canvas (`50_chartview.js:1110-1147`, `:1212`), and the modebar's
  toolbar/menu roles and roving `tabIndex` (`53_interaction.js:718-1000`).
  Those citations are accurate but descriptive — dossier §20 sketches the
  intent, production-readiness.md tracks the status, and this paragraph
  inventories the attributes. None of the three binds an implementer, so a
  refactor could change any of them without contradicting a spec. That is the
  open item. No code change — the accessibility contract is still only
  readable as source.

## 3. Target architecture (converged form)

```
60_entries      mount/unmount, comm plumbing         (unchanged)
54_kernel       view-requests, streaming appends,
                inbound messages, drill lifecycle    (extracted from 50)
53_interaction  pointer/drag/wheel, crosshair, box +
                lasso select, modebar, view state    (extracted from 50)
52_tooltip      hit → source row → tooltip DOM       (extracted from 50)
51_annotations  overlay canvas: markers, arrows,
                shape fills, nudged labels           (extracted from 50)
50_chartview    ChartView = surfaces, scales/view
                state, chrome, pick orchestration,
                GL buffer + VAO management           (still growing — see below)
55_marks        MARK_KINDS: build/draw/pick/hover/
                dispose/refreshColor per kind        (grows, stays declarative)
45_lod          tier orchestration (kind-blind)      (unchanged)
40_gl           programs, shader inventory,
                ATTR_SLOTS, uniform location cache   (gained R1/R5; R3/R6 pending)
```

51–54 all extend the same class via `Object.assign(ChartView.prototype, …)`,
so `this.*` is unchanged across the split — the file boundary is an editing
seam, not a module boundary. Two projections in the original table did not
hold: interaction is no longer a `50_chartview` responsibility, and the VAO
utilities landed in `50_chartview.js` (with the GL context) rather than in
`40_gl.js`. `GLSL_COMMON` (R6) is still unwritten.

ChartView's steady-state responsibilities: own the GL context + view rect +
event wiring + chrome; delegate everything mark-shaped to the registry and
everything tier-shaped to lod. It should *lose* lines as kinds are added, not
gain them.

**The line-count form of that metric has failed and is retired.**
`50_chartview.js` was 1707 lines when this document was written and is 4167
today — 2.4× the original figure — and that is *after* the annotations,
tooltip, interaction and kernel extractions moved a further 3062 lines into
51–54. The whole file is one `class ChartView`, so there is no small-class
escape hatch: the ~1500-line ceiling was breached and the number was never
refreshed, which is exactly how a raw line count fails as a metric.

Replacement metric, which does not go stale on every edit: **no per-kind
branches in `ChartView`.** Any `if (kind === …)` or kind-name switch outside
`55_marks.js` is the regression to catch; growth in shared machinery
(buffers, VAOs, pick, chrome) is expected and fine. Track the count of
kind-name literals in `50_chartview.js`, not its length.

## 4. WebGPU migration path

Position: **WebGL2 remains the shipping target** (universal, and our loads
are instancing-friendly); WebGPU is an *additive backend*, attractive for
Tier-2 compute (atomic-add binning in a compute shader, dossier §5) and
storage-buffer picking. The architecture above is deliberately the portable
subset:

1. Everything GPU-API-specific already lives in `40_gl.js` + the `_draw*`/
   `_upload*` methods; marks talk to buffers/uniform-maps, not raw GL, once
   R1-R3 land. That interface (`createProgram/uploadBuffer/draw(markState)`)
   is implementable on WebGPU nearly 1:1 (uniform maps → bind groups,
   VAOs → vertex-buffer layouts).
2. GLSL→WGSL is mechanical for our shader inventory (no derivatives beyond
   fwidth — supported; no geometry tricks). Keep shaders tiny and
   convention-bound (R5) so a one-time port stays a week, not a rewrite.
3. Migration trigger, stated so we don't drift: adopt WebGPU **only when**
   (a) a measured Tier-2/3 client-side re-bin path needs compute, or
   (b) WebGL2 fill-rate demonstrably caps a real workload the pyramid can't
   absorb. Not before — two backends is a tax.

## 5. Sequencing

1. ✅ R1 (`makeProgram` location cache) and R2 (VAO helper) landed as pure
   refactors, byte-identical smoke as expected. R3's state helper is still
   deferred on its own trigger (a second state-toggling pass).
2. R4 context-loss + R8 dispose (one PR: lifecycle) + smoke probes
   (lose/restore renders again; destroy leaves zero live GL objects via
   `WEBGL_debug`-style accounting where available).
3. R5 build-time shader lint + R6 GLSL_COMMON extraction (with the next new
   rect-family kind, not before).
4. R7 dpr watch (fold into `_resize`).
5. R9 pick generalization lands with the first pickable rect mark, per
   contract trigger.
6. R11 interaction/module contracts — done (interaction.md, wire-protocol.md);
   the ARIA/DOM accessibility contract is the residue, doc-only, no trigger.

## 6. Axis ticks and label formatting (`30_ticks.js`)

Ticks are computed on the CPU in f64 and never round-trip through the f32
render path (§16). `ChartView._ticksFor` dispatches on the axis
(`50_chartview.js:395–398`), checking in this order: `kind === "time"` →
`timeTicks`, `kind === "category"` → `categoryTicks`, `scale === "log"` →
`logTicks`, otherwise `linearTicks`. Every generator takes `(lo, hi, target)`
with `target = 6` by default and returns `{ ticks, step }`; `logTicks` adds
`labels` and `log: true`.

### 6.1 Generators

**Linear.** `niceStep` takes the rough step `(hi − lo) / target`, drops to the
decade below it (`10^floor(log10(rough))`), and scales that decade by the first
of `1, 2, 2.5, 5, 10` that reaches the rough step (compared with a `1 + 1e-12`
slack so a step landing exactly on a candidate is not pushed to the next one).
`linearTicks` then emits multiples of that step from `ceil(lo / step) * step`
upward, with a `step * 1e-9` tolerance on the upper bound so the last tick is
not lost to float error, and snaps near-zero values to exactly `0` under the
same tolerance. Degenerate inputs return early: non-finite bounds give no
ticks, `lo === hi` gives a single tick.

**Log.** `logTicks` requires strictly positive bounds — a domain touching zero
or negative values yields no ticks at all, it does not fall back to linear. It
walks integer decades from `floor(log10(lo))` to `ceil(log10(hi))`. When the
decade span is at most `max(2, target)` each decade emits mantissas `1, 2, 5`;
beyond that only `1`. Ticks outside the domain are dropped (again with a
relative `1e-12` slack). Labels are thinned separately from ticks: only
mantissa-1 ticks are labelled, and only every `labelEvery` decade where
`labelEvery = ceil((decades + 1) / target)` — so minor ticks draw unlabelled.
If thinning produces nothing, every tick is labelled.

**Category.** Positions are integer category indices. `categoryTicks` clamps
the visible index range to `[0, categories.length − 1]`, then strides it by
`max(1, ceil(visible / target))`, so labels thin out as more categories come
into view rather than overlapping.

**Time.** Time axes carry epoch milliseconds. `timeTicks` picks the first
member of `TIME_STEPS` — a fixed ladder of 1/2/5/10/20/50/100/200/500 ms, then
second, minute, hour, day multiples up to 14 days — that is at least the rough
step, and emits multiples of it from `ceil(lo / step) * step`. This ladder is
uniform-duration only. Once the rough step exceeds 14 days, `timeTicks` hands
off to `calendarTicks`, which switches to calendar arithmetic: it picks a month
stride from `1, 2, 3, 6, 12, 24, 60, 120` months and emits UTC month starts via
`Date.UTC`, so ticks land on real month and year boundaries rather than drifting
by a fixed 30-day approximation. `calendarTicks` reports `step` back as
`stepM * 30 * MS.d`, an approximation used only to choose a label format.

**Bounds.** Every generator caps output at 200 ticks (`calendarTicks` at 1000)
so a pathological domain cannot produce an unbounded loop or DOM label count.

### 6.2 Automatic label formats

With no `format=` on the axis, labels come from the step:

- `fmtLinear` switches to one-decimal exponential (with `e+` normalized to `e`)
  when `|v| ≥ 1e6` or `0 < |v| < 1e-4`. Otherwise it derives the decimal count
  from the tick step — `ceil(−log10(step))`, then increments while the step is
  not representable at that precision to within a thousandth of itself — and
  caps at 8 decimals. Ticks on one axis therefore share a decimal count.
- `fmtTime` picks the unit from the step: year alone for January on
  month-or-coarser steps, otherwise `Mon YYYY`; `Mon DD` at day steps; `HH:MM`
  at minute steps; `HH:MM:SS` at second steps; `MM:SS.mmm` below. All fields
  are read in UTC.
- `fmtCategory` rounds the position to an index and returns that category, or
  the empty string when the index is out of range.
- `fmtGeneral` reproduces Python's `:g` (default 6 significant digits) and is
  used for *explicit* colorbar ticks, whose precision is authored and must not
  be inferred from an unrelated automatic step. The colorbar itself ticks with
  `linearTicks(lo, hi, 8)` (`50_chartview.js:1467`).

### 6.3 The `format=` mini-language

`fmtAxis` consults the axis's `format` string before falling back to the
automatic formatter. The two accepted grammars are narrow.

**Numeric axes** (`fmtNumberSpec`). One optional trailing `%` is stripped
first; the remainder must match exactly

```
/^(,)?\.([0-9]+)f?$/
```

That is: an optional thousands-separator comma, a literal `.`, one or more
digits of precision, and an optional trailing `f`. The comma selects
`toLocaleString` with fixed fraction digits; without it the value goes through
`toFixed`. A `%` suffix multiplies by 100 and re-appends `%`. So `.2f`,
`,.0f`, `.1%` and `,.2f%` are the entire accepted surface. There is no
currency prefix, no sign flag, no `e`/`g`/`s` type, no explicit width or fill.

**Time axes** (`fmtTimeSpec`). A strftime *subset* substituted by
`/%[YmdHMSbB]/g`: `%Y`, `%m`, `%d`, `%H`, `%M`, `%S`, `%b` (short month name),
`%B` (long month name). All fields are UTC — there is no timezone support and
no `%j`, `%p`, `%I`, `%Z` or literal-`%%` escape. Any other text in the string
passes through verbatim, which means an unrecognized token such as `%y` renders
literally as `%y` rather than falling back.

**Log-axis carve-out.** On a log axis, a value in `(0, 1)` that a numeric
format renders as the string `"0"` is re-rendered with `fmtLinear` instead, so
a low decade is not labelled as a row of zeros.

### 6.4 Sharp edge: silent fallback on unmatched formats

`fmtNumberSpec` returns `null` on anything the regex rejects, and `fmtAxis`
treats that as "no format" — it silently uses the automatic formatter. No
warning is raised anywhere on the path: the Python side stores `format` as free
text with no validation (`python/xy/_figure.py:204` via `_optional_text`), so
an unsupported spec survives the whole pipeline and simply does nothing.

The in-tree example is `tests/test_components.py:555`, which sets
`format="$,.0f"` on a y-axis. The leading `$` cannot match the regex, so the
whole format is discarded and the axis renders with `fmtLinear` — the `$` never
appears. The test does not catch this because it asserts on the emitted spec,
not on rendered labels.

Two consequences to keep in mind when extending this: the failure mode for a
typo'd numeric format is a *plausible-looking wrong label*, not an error; and
the two grammars fail differently, since an unrecognized `%`-token on a time
axis is echoed literally instead of triggering the fallback. Making either loud
is a behavior change, not a doc fix, and is not proposed here.
