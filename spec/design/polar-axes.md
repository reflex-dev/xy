# Polar axes

How `xy` renders a chart in polar coordinates. This document is **normative**
for the (θ, r) → pixel transform, the angular conventions, the wire shape, and
which marks are legal under `coords="polar"`. Where an implementation and this
document disagree, this document is right and the implementation is a bug.

Roadmap context: item 18 (radar/polar), items 29/32 (wind rose "awaits polar
support"), item 34 (specialist coordinate systems) in
[`../api/chart-roadmap.md`](../api/chart-roadmap.md).

## 1. The shape of the problem

Polar is **one coordinate system**, not a family of chart types. Both incumbents
work this way: matplotlib has a `PolarAxes` projection that ordinary `plot` /
`scatter` / `bar` / `fill` calls render into, and Plotly has three polar trace
types (`scatterpolar`, `scatterpolargl`, `barpolar`) from which radar, spider,
bubble and wind-rose charts are composed. Neither ships a "radar renderer".

So `xy` adds a coordinate system and lets the existing mark registry render
through it. `MARK_KINDS` (`js/src/55_marks.ts`) gains no entries, and no
`_emit_<K>` in `python/xy/_payload.py` is rewritten. This follows the standing
rule in [`../api/chart-kind-contract.md`](../api/chart-kind-contract.md):
organize by primitive, not by chart name.

## 2. Conventions

| Concept | Value | Notes |
|---|---|---|
| θ unit | `"radians"` (default) or `"degrees"` | Affects input data and tick labels together. |
| θ zero location | `"E"` (default), `"N"`, `"W"`, `"S"`, or a float in radians | Direction that θ = 0 points. `"E"` = math convention. |
| θ direction | `"counterclockwise"` (default) or `"clockwise"` | Math convention default; compass work sets `"N"` + `"clockwise"`. |
| r scale | linear (this increment) | log/symlog deferred — §9. |
| r range | `[r_lo, r_hi]`, default `[0, max(r)]` | `r_lo = 0` matches matplotlib's default `rmin`. |

The compass composition — `zero="N"`, `direction="clockwise"` — makes θ = 90°
point East, 180° South, 270° West. Wind roses depend on exactly this; §4 pins it
with fixtures.

## 3. The transform (normative)

Given θ and r in data space, a radial range `[r_lo, r_hi]`, and a plot rect
`(x, y, w, h)` in CSS pixels:

```
th  = θ · (π/180)  if unit == "degrees" else θ
a   = zero + dir · th                        # dir = +1 ccw, −1 cw
rn  = (r − r_lo) / (r_hi − r_lo)             # normalized radius
R   = min(w, h) / 2                          # px radius of the unit circle
cx  = x + w/2 ,  cy = y + h/2                # centre of the plot rect

px  = cx + rn · R · cos(a)
py  = cy − rn · R · sin(a)                   # screen space: y grows DOWN
```

Three properties this pins down, each of which has a matching fixture:

- **The circle is round in a non-square rect.** `R` uses `min(w, h)`, and the
  circle is centred in the rect rather than stretched to fill it.
- **`R` carries no fill factor.** Room for angular tick labels is reserved by
  *shrinking the plot rect during layout*, not by scaling the radius. The
  transform stays pure; layout owns the gutters. Concretely, after the
  cartesian gutter passes converge, `_recut_polar_plot` (`_svg.py`, mirrored by
  `_recutPolarPlot` in the client) gives back the cartesian tick-label gutters
  — polar labels ring the disc instead of hugging two edges — and reserves a
  uniform `_POLAR_LABEL_ROOM` all round. Reservations that still mean something
  survive: the title band, a colorbar's gutter, and the left gutter when the
  radial axis has a title (which is drawn there and would otherwise leave the
  canvas).
- **The y term is a subtraction.** This is the single most likely parity bug in
  the codebase. Screen/SVG/raster space has y growing **down**, so upward angles
  must *decrease* py. GL clip space has y growing **up**, so the GLSL form is
  `+` on the y component. An implementation that copies `cy − r·sin(a)` into a
  shader, or `+` into the exporters, renders vertically mirrored and every
  fixture in §4 catches it.

### 3.1 Where it sits in the existing pipeline

The Cartesian pipeline is two independent 1-D maps. On the client
(`AXIS_GLSL`, `js/src/40_gl.ts:80`):

```
xyDecode(encoded, meta)   →  undo §16 offset encoding, back to data space
xyAxisCoord(...)          →  apply the scale (log / symlog / linear)
· map.x + map.y           →  affine to clip space
```

and in Python, `_Scale.coord()` then `_Scale.__call__()`
(`python/xy/_svg.py:814`, `:827`) do the same two steps.

**Polar replaces only the last step**, and replaces it with a *joint* map over
both axes. Decode and scale are untouched, which is why log radial scales are a
later increment rather than a rewrite. Concretely: after `xyAxisCoord` yields θ
and r in scaled data space, the joint polar map produces a position directly,
and the per-axis `u_xmap`/`u_ymap` affine is bypassed.

Because the WebGL canvas is positioned and sized to exactly the plot rect
(`js/src/50_chartview.ts:1833`), clip space `[-1, 1]²` **is** the plot rect. So
the GLSL form needs no plot-rect uniforms at all — only the centre, the radius
in clip units per axis, and the radial range:

```glsl
vec2 xyPolar(float thC, float rC, vec4 pol, vec2 rr, vec2 zdir) {
  float rn = (rC - rr.x) / max(rr.y - rr.x, 1e-30);
  float a  = zdir.x + zdir.y * thC;
  return vec2(pol.x + rn * pol.z * cos(a),
              pol.y + rn * pol.w * sin(a));   // '+': clip-space y grows UP
}
```

`pol.zw` is a **vec2** radius, not a scalar: clip space is square while the plot
rect generally is not, so a round circle needs `2R/w` clip units horizontally
and `2R/h` vertically.

Radial zoom is therefore a change to `rr` alone — a uniform update, exactly like
Cartesian pan/zoom. This is the reason the transform lives in the shader rather
than being pre-projected into (x, y) in the kernel: pre-projection would make
every zoom a full re-transform and re-upload, and would break streaming append.

### 3.2 Inverse (screen → data)

Hover, tooltips and drag gestures need the inverse. With `dx = px − cx` and
`dy = cy − py` (note the flip again):

```
rn = hypot(dx, dy) / R
r  = r_lo + rn · (r_hi − r_lo)
a  = atan2(dy, dx)
th = (a − zero) / dir            # then wrapped into the θ domain
```

θ is wrapped modulo a full turn: **θ = 0 and θ = 2π are the same location**, and
any angular distance metric must wrap across that seam. A naïve `|θ₁ − θ₂|`
reports points at 1° and 359° as maximally distant; they are 2° apart.

## 4. Parity fixtures

The transform above is implemented twice — once in GLSL, once in Python (shared
by both exporters). Prose does not bind them. `tests/fixtures/polar_transform.json`
does, and it is authored from the definition in §3, not generated from either
implementation.

Fixture cases are chosen so a human can check them by inspection:

| Config | θ, r | Expected | Pins |
|---|---|---|---|
| default | 0, 1 | due right | zero location |
| default | π/2, 1 | due up (py smaller) | the y flip |
| default | 0, 0 | dead centre | radial origin |
| `zero="N"` | 0, 1 | due up | zero rotation |
| `zero="N"`, cw, degrees | 90, 1 | due right (compass E) | direction sign |
| `zero="N"`, cw, degrees | 180, 1 | due down (compass S) | compass composition |
| non-square rect | 0/π/2/π, 1 | round, centred | `min(w,h)` and centring |

Three consumers must agree with that file:

1. **Python** — a unit test over `_polar_project`. Fast, always runs.
2. **GLSL** — `scripts/polar_parity_smoke.py` renders one scatter point per
   fixture sample in headless Chrome and compares each colour's lit-pixel
   centroid to the fixture value. This binds the *actual shader* in the shipped
   bundle, not a JS mirror of it, which is the only version that can drift
   silently. It runs in the stdlib-only CI lane beside the other smokes.
3. **Exporters** — SVG and raster inherit (1) because they share the Python
   projection, so their obligation is a rendered-output check, not a second
   transform test.

This is deliberately stronger than the existing tick-math arrangement, where
`js/src/30_ticks.ts` and its hand port in `python/xy/_svg.py:477-767` are bound
by **nothing executable** — a gap that has already allowed a live divergence in
the tick-count target between client and exporters. Polar does not repeat it.

## 5. Chord versus arc

A straight line in (θ, r) space is a curve on screen. Whether to draw the curve
or the chord is a **semantic** choice, not a rendering detail, and the two
incumbents differ: Plotly draws straight chords between polar data points;
matplotlib arc-interpolates paths.

| Geometry | Rendering | Why |
|---|---|---|
| Data lines, fill boundaries | **chord** | Plotly semantics. Radar/spider edges *must* be straight or the polygon is wrong. |
| Grid rings, outer frame | **true arc** | Axis chrome must be round. |
| Bar edges (annular sectors) | **true arc** | A wide bar with chorded ends reads as a triangle. |
| Heatmap / contour cells | **true arc** | Scientific fidelity (later increment). |

Chords need no subdivision, which is why line, scatter and area are cheap. Arcs
flatten to polylines wherever the medium lacks a real arc: the raster display
list always, and the GPU bar sweep by construction. The subdivision count is
`POLAR_BAR_SEGMENTS` (`python/xy/config.py`, mirrored in
`js/src/50_chartview.ts`) — fixed rather than view-adaptive, because bar counts
are small and a view-dependent count would have to be recorded per §28 rather
than chosen silently. SVG needs no count: it draws real `A` arcs
(`_polar_wedge_path`), and `polar_wedge_points` is the flattened twin the
raster path consumes.

On the client the flattening never reaches the screen: the GL context runs
with `antialias: false`, so wedge edges are fragment-shader coverage like
every other mark. `POLAR_WEDGE_GLSL` expands the strip `XY_POLAR_AA` px
outward and `RECT_FS` trims it against the true annular-sector SDF — the AA
fringe gets room to ramp on both sides of each edge, and because the expanded
chords stay outside the true outer arc (the segment count is sized for that up
to a ~1400-device-px disc), the trimmed arc is exactly round rather than
faceted. The raster's coverage-scanline polygon fill antialiases the same
flattened wedge; SVG antialiases its real arcs natively.

### Rounded corners

`corner_radius` on a slice has no rectangle to hang off, and every donut,
progress ring and gauge design in the wild asks for one. It is defined in the
**unrolled** (arc, radial) frame: at each radius the wedge is a rectangle of
half-height `hr` and half-width `sweep/2 · dist`, so the standard rounded-rect
profile applies there and rolls back out to corners that follow the arc. The
client evaluates that profile per fragment (the annular-sector SDF in
`RECT_FS`); the exporters sample the same profile into a polygon
(`_rounded_wedge_points`), which is why a rounded wedge ships as a polyline
while a plain one keeps its exact `A` arcs — the rounded boundary is not a
circular arc once rolled back, so a polyline is the honest shape rather than an
approximation of one.

An opt-in arc-interpolated line mode (matplotlib's behaviour) is a possible
later flag. It is not in this increment, and the default does not change.

## 6. Renderer seams

Polar must be implemented at every seam below. Missing one does not fail
loudly — it renders something plausible and wrong.

### Client (`js/src/40_gl.ts`)

There are **eight** vertex shaders, each with its own copy of the data→clip
math. Three of them draw points:

| Shader | Line | Draws | This increment |
|---|---|---|---|
| `POINT_VS` | 107 | scatter (full) | yes |
| `POINT_SIMPLE_VS` | 311 | scatter (fast path) | yes |
| `PICK_VS` | 348 | hover id-pick buffer | yes |
| `LINE_VS` | 486 | line | yes |
| `SEGMENT_VS` | 588 | error bars, stems, contour | no — §7 |
| `MESH_VS` | 653 | hexbin, triangle mesh | no — §7 |
| `AREA_VS` | 738 | area, error bands | yes — interpolates in data space, then projects, so radial edges are true radii and fill boundaries are chords |
| `BAR_VS` | — | compact bars | yes — sweeps `POLAR_BAR_SEGMENTS`+1 vertex pairs per instance: an annular sector, not a quad |
| `RECT_VS` | 796 | histogram, box, violin (four-edge rects) | no — §7 |

`POINT_SIMPLE_VS` and `PICK_VS` are the traps. Scatter silently switches to the
simple program whenever `_canDrawSimplePoints` holds, so transforming only
`POINT_VS` leaves a fast path that draws Cartesian. And `PICK_VS` feeds the
GPU hit-test: untransformed, the picture is right while hover reports the wrong
row.

`GRID_VS` (heatmap/density) is a different shape entirely — it draws one
fullscreen quad and inverts screen→data **in the fragment stage**, so it cannot
follow a vertex-stage transform. Polar heatmaps are a later increment for this
reason, not an oversight.

### Client chrome (`js/src/50_chartview.ts`)

Four stacked surfaces. Grid lines are canvas-2D (`ctx.arc` gives rings and
`moveTo`/`lineTo` gives spokes — both cheap), but **axis spines and tick marks
are DOM `<div>`s with a background colour**, which can express a rectangle and
nothing else. The polar frame circle and its radial ticks therefore move to the
2D chrome canvas.

### Exporters (`python/xy/_svg.py`, `python/xy/_raster.py`)

The raster exporter imports ~45 symbols from `_svg` — including `_Scale`,
`_axis_scales`, `layout` and `axis_ticks` — precisely so the two static outputs
share geometry. So the Python projection is written **once** in `_svg.py` and
both exporters inherit it. Two consequences:

- SVG can express rings as `<circle>` and sectors as `A` path commands.
- The raster path has **no arc, wedge, annulus or disc-clip primitive at all**.
  Its entire vocabulary is polygon fill, capsule strokes, SDF point symbols and
  image blits. Every curve is a pre-flattened polyline, and the only precedent
  is `_round_rect_pts` (`python/xy/_raster.py:722`) flattening corner arcs. Polar
  rings are flattened the same way.

**The affine fast-path trap.** Several emitters bake an affine data→pixel map
into Rust, gated on `sx.affine and sy.affine`. A polar chart on linear axes
satisfies that predicate while being emphatically non-affine. Any polar scale
object must therefore report `affine = False`, or scatter, line smoothing and
grid blits will silently project through a straight-line map.

## 7. Scope

**Legal under `coords="polar"`:** `line`, `scatter`, `area`, `bar`, `column`
(`POLAR_MARK_KINDS`, `python/xy/config.py`).

A bar's angular width may vary per bar. Equal widths ship through the compact
bar path (one scalar width, `BAR_VS`); unequal widths ship four edge columns,
which under polar *are* an annular sector — `(x0, x1)` is the angular span and
`(y0, y1)` the radial one. That is what makes pie and donut charts a
composition rather than a chart type: a slice is one bar carrying its own
width, and `RECT_VS` sweeps it exactly as `BAR_VS` does.

Everything else is **rejected at payload build** with an error naming the
supported set. This is not a limitation to be discovered at render time: a
histogram drawn through the four-edge rect shader would come out chord-edged,
and §28 of the dossier requires that such a decision ship as a recorded refusal
rather than a silent approximation.

On top of the mark kinds, three compositions are public API rather than
renderers: `xy.radar_chart(categories, ...)` (evenly spaced spokes labelled
with the categories; each series closed at a **full turn**, never by repeating
the first angle, which would sweep the closing segment backwards through the
whole circle), `xy.polar_bar_chart(...)`, and `xy.wind_rose(directions,
speeds)` (Python-side binning like `hist`, stacked bars, compass convention
`zero="N"` + clockwise).

The pyplot `projection="polar"` increment is landed and corpus-bound: ordinary
`plot`, `scatter`, `fill`, and `bar` calls route through the polar coordinate
system from `subplot`, `add_subplot`, `axes`, and
`subplots(subplot_kw={"projection": "polar"})`. The next increment is polar
heatmap and contour — the latter being the differentiator, since Plotly has no
native polar heatmap, contour or error-bar trace.

### Tier policy

Polar traces ship `tier: "direct"` and are point-capped by validation. The LOD
tiers do not transfer unmodified and must not be silently reused:

- **M4 decimation** assumes a monotonic x→screen-x column. A spiral is not
  monotonic in θ, and multi-turn data revisits the same screen columns.
- **Density binning** in (θ, r) has an area-distortion problem: equal
  data-space bins near the origin cover far fewer pixels, so genuinely uniform
  density renders as centre-concentrated.

Both need their own design work in
[`lod-architecture.md`](lod-architecture.md). Until then the cap is explicit and
reported, per §28.

## 8. Interaction

MVP surface, deliberately small:

- **Hover** — screen-space nearest-point test, seam-aware per §3.2, with the
  readout reporting (θ, r) in the axis's declared unit.
- **Radial zoom** — wheel scales the radial maximum about a **fixed** radial
  minimum (Plotly's radial semantics), serialized through the existing
  view-state machinery. Anchoring at the cursor's radius was tried first and
  rejected from interactive testing: an interior anchor lifts `r_lo` and carves
  a hole in the middle of the disc — an annulus view that reads as broken, not
  as zoom.
  Marks outside the radial range are **culled in the shader** (NaN position,
  the same gap semantics NaN data gets): below `r_lo` a mark would reflect
  through the centre, and above `r_hi` it would draw past the outer ring into
  the rect corners — the GL canvas is the plot rect, so the shader cull is the
  client's equivalent of the SVG exporter's disc `clipPath`. The exporters'
  line and scatter paths apply the same cull (`_PolarProjection.visible_mask`)
  rather than relying on that clip: a below-range point mirrors through the
  centre to a position *inside* the disc, and the raster path has no disc clip
  at all. A chord with a culled endpoint is therefore dropped whole in every
  renderer; at data resolution the gap is under one segment. Fills and bars
  **clamp** their radial span to `[r_lo, r_hi]` instead of culling: their
  visible extent at an angle is `[base, top] ∩ [r_lo, r_hi]`, and culling one
  endpoint made a radar fill vanish the moment zoom lifted `r_lo` above its
  baseline. A span fully outside collapses to zero and draws nothing.
- **Reset** — existing modebar, no change.

Deferred and explicitly disabled rather than half-working: θ pan (rotation),
sector zoom, and box select. Box select's rectangle has no polar meaning; the
right answer is an annulus/sector select, and shipping a rectangle over a disc
in the meantime would be a wrong affordance rather than a partial one. For
reference, Plotly never solved polar wheel zoom at all — it offers radial-axis
drag only — so a small, deliberate model is already ahead of the field.

## 9. Deferred

Each row lands as its own change and updates this table when it does.

| Feature | Notes |
|---|---|
| Sector layout | Still the largest visible gap: a 240-degree gauge rebuilt from polar bars gets a full-circle plot rect, so ~40% of the canvas is dead space and the centre readout sits low. `sector`/`thetamin`/`thetamax` limits AND the layout that should follow: a gauge drawn as a partial arc still gets a full-circle plot rect, so the unused portion is dead space. The disc should shrink to the sector's bounding box. |
| Polar `rule` / `band` annotations | Point-anchored annotations (`text`, `label`, `marker`, `arrow`) project through the transform in **all three** renderers — `_annotation_svg`/`annotation_label_placement` in the exporters, `_dataPxPoint` in the client. A rule/band is genuinely different geometry on a disc — a θ rule is a spoke, an r rule is a ring, a band is an annulus or a sector — and still draws as a straight cartesian bar. |
| pyplot `projection="polar"` | Landed and corpus-bound. `subplot`, `add_subplot`, `axes`, and `subplots(subplot_kw=...)` route ordinary `plot`, `scatter`, `fill`, and `bar` calls into polar coordinates; `set_theta_zero_location`, `set_theta_direction`, `set_theta_offset`, `set_thetagrids`, `set_rlim`, `set_rticks`, and the r-limit accessors reach the built chart. |
| Polar heatmap / contour | Beyond Plotly parity. Needs the fragment-stage inverse (§6). |
| Partial sector (`thetamin`/`thetamax`) | Layout, clipping and tick trimming. |
| Hole / r-origin | `rn` gains a floor; touches every hit test. |
| Categorical θ axis | Finishes radar; band semantics for bars. |
| Log / symlog radial scale | `xyAxisCoord` already supports it; needs ticks and layout. |
| Polygonal grid | Chrome-only; Plotly's `gridshape="linear"`. |
| Polar error bars | `SEGMENT_VS`; matplotlib has it, Plotly does not. |
| Polar LOD | §7. Exit criterion for `scatterpolargl`-scale claims. |
| Polar facets / animation | Untouched by this design; no known blocker. |
