# Renderer Architecture — Audit & Target Design

**Status:** audit of the shipped WebGL2 client (`js/src/40_gl.js`,
`45_lod.js`, `50_chartview.js`, `55_marks.js`, `60_entries.js`) + the
architecture it should converge to before ~20 more chart kinds land. Findings
below are verified against the source, not hypothetical.

## 1. What's structurally right (keep)

- **Mark registry** (`MARK_KINDS` + capabilities `pointPick/retainCpu/
  refreshColor` + `markOf` fallback): the render loop is kind-blind; new
  kinds are entries. This is the load-bearing decision — preserve it.
- **LOD module** (`45_lod.js`): tier orchestration/fades/caches are outside
  ChartView and call back through `view._draw*`, so tests intercept the
  renderer and future kinds can swap mark drawing. Keep the callback seam.
- **Three-surface layering**: GL canvas (marks) + 2D chrome canvas
  (grid/axes) + DOM (labels/tooltip/legend/modebar/crosshair). Crisp text,
  selectable tooltips, zero GL cost for chrome — correct division (§7).
- **Uniform-only pan/zoom**: geometry is static offset-encoded f32; view
  changes touch two vec2 uniforms per mark (`_map`). This is why interaction
  is cheap; nothing below may regress it.
- **Screen-bounded inputs**: the client never receives O(N) buffers (§29).
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
- **R2 — No VAOs.** Every draw re-binds attributes via `_bindScalarAttr`
  (verified: zero `createVertexArray` in the bundle). **Deferred with a
  stated trigger:** at ~6 kinds the per-frame rebinding is unmeasurable and
  the refactor risks exactly the stale-attribute bugs it would prevent.
  Adopt together with the first rect-family pick geometry (the R9 trigger),
  when draw+pick sharing VAO layouts pays twice.
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
  divisor-1 endpoints; rects likewise; points use POINTS. Fine at 5 kinds,
  but each new rect-family kind re-writes the same corner-expansion VS
  preamble. *Fix:* extract shared VS chunks (corner tables, px↔clip
  helpers) via string includes in `40_gl.js` (`GLSL_COMMON`), not a shader
  framework. Deliberately stop there — a "shader graph" is over-engineering
  at this scale.
- **R7 — DPR/zoom *changes* aren't observed.** ✅ **Done.** `_armDprWatch`
  re-arms a one-shot `matchMedia('(resolution: Ndppx)')` per dpr value;
  `_resize` re-reads devicePixelRatio so a pure-DPR change re-derives
  backing stores with no container resize. Smoke `dprw` flag covers it.
- **R8 — Lifecycle cleanup.** ✅ **Already complete** (re-audit): `destroy()`
  → `_destroyGlResources` frees per-trace static + drill buffers, density/
  heatmap/LUT textures (dedup via `texSeen`), pick FBO/texture, the quad, and
  all programs. The original finding is stale. Remaining nicety only: move
  per-kind buffer-name lists into a registry `dispose` hook when a kind
  arrives whose resources don't fit the shared name list.
- **R9 — Picking model won't stretch as-is.** GPU ID pass is point-only
  (`pointPick`); rect-family picking (bars/candles) is planned as a
  registry `pick` step (contract). Two additions when that lands:
  slot >255 guard (u8 alpha channel caps 255 pickable traces — assert,
  it's fine) and shared pick-VS chunks per R6 so each mark's ID pass reuses
  its draw geometry.
- **R10 — Tooltip data path**: solid (local approx row → kernel-exact
  replacement, seq-guarded, drill_seq-versioned, XSS-safe text nodes). Only
  gap: the row schema is implicit per kind. Write it down in the chart-kind
  contract (`{x, y?, ohlc?, color_*?}` + `_dist` for non-point hover) so new
  kinds emit compatible rows — doc task, no code.

## 3. Target architecture (converged form)

```
60_entries   mount/unmount, comm plumbing            (unchanged)
50_chartview ChartView = surfaces, scales/view state,
             interaction, chrome, pick orchestration  (shrinks)
55_marks     MARK_KINDS: build/draw/pick/hover/dispose/
             refreshColor per kind                    (grows, stays declarative)
45_lod       tier orchestration (kind-blind)          (unchanged)
40_gl        programs, GLSL_COMMON chunks, state
             helper, VAO + location-cache utilities   (gains R1/R2/R3/R5/R6)
```

ChartView's steady-state responsibilities: own the GL context + view rect +
event wiring + chrome; delegate everything mark-shaped to the registry and
everything tier-shaped to lod. It should *lose* lines as kinds are added, not
gain them — that's the health metric (it's 1707 lines today; the R-fixes and
candle-era extractions should hold it under ~1500 while kinds double).

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

1. R1 + R2 + R3 together (one PR: `makeProgram` location cache, VAO helper,
   state helper) — pure refactor, byte-identical smoke expected.
2. R4 context-loss + R8 dispose (one PR: lifecycle) + smoke probes
   (lose/restore renders again; destroy leaves zero live GL objects via
   `WEBGL_debug`-style accounting where available).
3. R5 build-time shader lint + R6 GLSL_COMMON extraction (with the next new
   rect-family kind, not before).
4. R7 dpr watch (fold into `_resize`).
5. R9 pick generalization lands with the first pickable rect mark, per
   contract trigger.
