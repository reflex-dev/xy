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
| θ sector | one full turn by default, or finite increasing `(start, end)` | At most 2π radians / 360 degrees. `theta_axis(domain=...)` is a compatibility alias when `sector=` is omitted. |
| θ grid shape | `"circular"` (default) or `"linear"` | Linear joins the angular spokes into polygonal radial rings. |
| r scale | linear, log, or symlog | Radius normalization happens in scale-coordinate space. |
| r range | `[r_lo, r_hi]` | Linear/symlog autorange retains the centre-origin default; log autorange starts at its positive minimum. |
| inner shape | `hole ∈ [0, 1)` or a data-space `r_origin` | Mutually exclusive authored controls. An omitted origin resolves to visible `r_lo`. |

The compass composition — `zero="N"`, `direction="clockwise"` — makes θ = 90°
point East, 180° South, 270° West. Wind roses depend on exactly this; §4 pins it
with fixtures.

## 3. The transform (normative)

Given θ and r in data space, an authored angular sector `[θ_lo, θ_hi]`, a
radial range `[r_lo, r_hi]`, radial scale-coordinate function `coord`, radial
origin `r_origin` (default `r_lo`), display-space hole fraction `h` (default
0), and a plot rect `(x, y, w, h_px)` in CSS pixels:

```
th  = θ · (π/180)  if unit == "degrees" else θ
a   = zero + dir · th                        # dir = +1 ccw, −1 cw
c0  = coord(r_origin)
rn  = h + (1 − h) · (coord(r) − c0) / (coord(r_hi) − c0)
R   = min(w, h_px) / 2                       # full-turn radius
cx  = x + w/2 ,  cy = y + h_px/2             # full-turn centre

px  = cx + rn · R · cos(a)
py  = cy − rn · R · sin(a)                   # screen space: y grows DOWN
```

Only values inside the authored θ sector and visible radial interval are
projected. Point and line positions outside either interval are culled; spans
and bars are clipped to the visible interval. The authored radial origin must
be below `r_hi` and no greater than `r_lo`; on a log scale it must also be
positive. An origin below `r_lo` makes the visible lower ring an annulus, while
`hole` assigns that ring the explicit display-space fraction `h`.

Five properties this pins down, each of which has matching coverage:

- **The circle is round in a non-square rect.** `R` uses `min(w, h_px)`, and the
  circle is centred in the rect rather than stretched to fill it.
- **Radius is normalized after scaling.** Linear, log, and symlog radii share
  the same equation; only `coord` changes. Log autorange never reintroduces
  zero.
- **Sector and data range are independent.** Numeric θ remains in angular
  units. Categorical θ remains in category-index coordinates and maps those
  indices evenly over the sector; it is never rewritten into radians/degrees.
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
- **A partial sector owns its bounding box.** Full turns retain the centred
  circle above. For a partial turn, layout finds the bounds of the visible
  outer arc plus inner boundary and scales/translates that shape to the plot
  rect. A gauge therefore does not reserve dead space for a missing arc.
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
both axes. Decode and scale are untouched. After `xyAxisCoord` yields θ and r
in scale-coordinate space, the joint polar map produces a position directly,
and the per-axis `u_xmap`/`u_ymap` affine is bypassed. This is why log and
symlog radius reuse the existing axis-scale implementation.

Because the WebGL canvas is positioned and sized to exactly the plot rect
(`js/src/50_chartview.ts:1833`), clip space `[-1, 1]²` **is** the plot rect. So
the GLSL form needs no plot-rect uniforms at all — only the centre, the radius
in clip units per axis, and the radial range:

```glsl
vec2 xyPolar(float thC, float rC, vec4 pol, vec2 rr, vec2 zdir,
             vec2 trange, float turn, vec2 rshape) {
  if (!thetaVisible(thC, trange, turn) || rC < rr.x || rC > rr.y)
    return vec2(NAN);
  float rn = rshape.y
    + (1.0 - rshape.y) * (rC - rshape.x) / (rr.y - rshape.x);
  float a  = zdir.x + zdir.y * thC;
  return vec2(pol.x + rn * pol.z * cos(a),
              pol.y + rn * pol.w * sin(a));   // '+': clip-space y grows UP
}
```

`pol.zw` is a **vec2** radius, not a scalar: clip space is square while the plot
rect generally is not, so a round circle needs `2R/w` clip units horizontally
and `2R/h` vertically. `trange`/`turn` own authored-sector clipping, while
`rshape = (coord(r_origin), hole)`.

Radial zoom is therefore a change to `rr` alone — a uniform update, exactly like
Cartesian pan/zoom. This is the reason the transform lives in the shader rather
than being pre-projected into (x, y) in the kernel: pre-projection would make
every zoom a full re-transform and re-upload, and would break streaming append.

### 3.2 Inverse (screen → data)

Hover, tooltips, the heatmap fragment shader, and drag gestures need the
inverse. With `dx = px − cx`, `dy = cy − py` (note the flip again), and
`displayed = hypot(dx, dy) / R`:

```
base = (displayed − hole) / (1 − hole)
rc   = coord(r_origin) + base · (coord(r_hi) − coord(r_origin))
r    = coord⁻¹(rc)
a  = atan2(dy, dx)
th = (a − zero) / dir            # then wrapped into the θ domain
```

Pixels inside the hole, outside the outer radius, or outside a partial sector
have no data coordinate. θ is wrapped modulo a full turn: **θ = 0 and θ = 2π
are the same location**, and any angular distance metric must wrap across that
seam. A naïve `|θ₁ − θ₂|` reports points at 1° and 359° as maximally distant;
they are 2° apart.

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
| Heatmap cells | **true arc boundaries** | The fragment-stage inverse samples each screen pixel in (θ, r), so cell edges follow rings/spokes. |
| Contour / error-bar segments | **chord** | They are independent data-space segments projected at their endpoints, with radial clipping before projection. |

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

The vertex shaders below each consume the shared data→clip preamble. Three of
them draw points:

| Shader | Line | Draws | This increment |
|---|---|---|---|
| `POINT_VS` | 107 | scatter (full) | yes |
| `POINT_SIMPLE_VS` | 311 | scatter (fast path) | yes |
| `PICK_VS` | 348 | hover id-pick buffer | yes |
| `LINE_VS` | 486 | line | yes |
| `SEGMENT_VS` | 588 | error bars, stems, contour | **yes for allowlisted `errorbar` and `contour` only** — this does not make generic segment marks polar-legal |
| `MESH_VS` | 653 | hexbin, triangle mesh | no — §7 |
| `AREA_VS` | 738 | area (error bands stay outside the polar allowlist) | yes — interpolates in data space, then projects, so radial edges are true radii and fill boundaries are chords |
| `BAR_VS` | — | compact bars | yes — sweeps `POLAR_BAR_SEGMENTS`+1 vertex pairs per instance: an annular sector, not a quad |
| `RECT_VS` | 796 | four-edge rects: the unequal-width slice path (§7); histogram/box/violin stay refused | yes — sweeps the same annular sector as `BAR_VS` |

`POINT_SIMPLE_VS` and `PICK_VS` are the traps. Scatter silently switches to the
simple program whenever `_canDrawSimplePoints` holds, so transforming only
`POINT_VS` leaves a fast path that draws Cartesian. And `PICK_VS` feeds the
GPU hit-test: untransformed, the picture is right while hover reports the wrong
row.

Vertex projection alone cannot clip the interior of a chord, fill, wide point,
or bar that crosses a hole or a sector boundary. Every legal polar mark
fragment program therefore calls the shared `POLAR_FRAGMENT_CLIP_GLSL`
predicate. It inverts `gl_FragCoord` into normalized polar display space,
rejects the explicit hole and the implicit annulus created by `r_origin`,
rejects the missing angular sector, and applies the same predicate to the pick
framebuffer. Authored Canvas markers and clipped annotation marks use the
matching annular-sector path. In-bounds callout/arrow connectors remain
unclipped, preserving the existing Matplotlib `annotation_clip` semantics.

`GRID_VS`/the heatmap fragment shader are a different shape entirely: they draw
one fullscreen quad and invert screen→data **in the fragment stage**. In polar
mode the fragment shader discards pixels outside the annular sector, applies
the inverse from §3.2, wraps θ into the grid's own edge range, and nearest
samples the source cell. SVG and native raster export share a bounded CPU
inverse-raster twin. It tiles inverse-projection scratch, gathers canonical-f64
or RGBA source cells only after resolving visible output pixels, and never
expands the full source grid. SVG samples at logical plot resolution; native
raster samples at device resolution (`ceil(plot × scale)`), capped at 4096
pixels per output dimension. Work and temporary memory are therefore bounded
by the requested screen/export surface rather than the source matrix. Density
grids remain outside the polar allowlist; landing the heatmap inverse does not
make every grid-backed mark polar-capable.

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
- PDF inherits every polar chart from the SVG: the full-disc clip lowers to
  four Bézier quarter-arcs, and the hole/sector clips — emitted as a single
  `<path>` clipPath — lower to PDF path ops with SVG's `clip-rule` mapped onto
  `W`/`W*`. A clip shape outside that set still fails loudly.
- The raster path still has no arc or wedge paint primitive. Curves are
  pre-flattened polylines/polygons, following the `_round_rect_pts` precedent.
  It does have one analytic annular-sector **mark clip** in the private display
  list: a rectangular outer-radius bbox rejects work cheaply, then the final
  pixel blend applies radial/angular containment with supersampled boundary
  coverage. The state covers every primitive — chord strokes, fills, symbols,
  and heatmap images — so no mark can paint through a hole or missing sector.
  A later rectangular clip resets it for unclipped chrome.

**The affine fast-path trap.** Several emitters bake an affine data→pixel map
into Rust, gated on `sx.affine and sy.affine`. A polar chart on linear axes
satisfies that predicate while being emphatically non-affine. Any polar scale
object must therefore report `affine = False`, or scatter, line smoothing and
grid blits will silently project through a straight-line map.

## 7. Scope

**Legal under `coords="polar"`:** `line`, `scatter`, `area`, `bar`, `column`,
`heatmap`, `contour`, and `errorbar` (`POLAR_MARK_KINDS`,
`python/xy/config.py`).

A bar's angular width may vary per bar. Equal widths ship through the compact
bar path (one scalar width, `BAR_VS`); unequal widths ship four edge columns,
which under polar *are* an annular sector — `(x0, x1)` is the angular span and
`(y0, y1)` the radial one. That is what makes pie and donut charts a
composition rather than a chart type: a slice is one bar carrying its own
width, and `RECT_VS` sweeps it exactly as `BAR_VS` does.

Everything else is **rejected at payload build** with an error naming the
supported set. In particular, the new polar branch in `SEGMENT_VS` exists for
the allowlisted contour and error-bar trace schemas; it does not authorize
`stem`, `segments`, box-whisker internals, or arbitrary segment/mesh marks.
Likewise the heatmap fragment inverse does not authorize density or triangle
meshes. This is not a limitation to be discovered at render time: a histogram
drawn through the four-edge rect shader would come out chord-edged, and §28 of
the dossier requires that such a decision ship as a recorded refusal rather
than a silent approximation.

On top of the mark kinds, three compositions are public API rather than
renderers: `xy.radar_chart(categories, ...)` (evenly spaced spokes labelled
with the categories; each series closed at a **full turn**, never by repeating
the first angle, which would sweep the closing segment backwards through the
whole circle), `xy.polar_bar_chart(...)`, and `xy.wind_rose(directions,
speeds)` (Python-side binning like `hist`, stacked bars, compass convention
`zero="N"` + clockwise).

The pyplot `projection="polar"` surface is landed and corpus-bound: ordinary
`plot`, `scatter`, `fill`, `bar`, heatmap/image, contour, and error-bar calls
route through the polar coordinate system from `subplot`, `add_subplot`,
`axes`, and `subplots(subplot_kw={"projection": "polar"})`.
`set_thetamin`/`set_thetamax` author sector endpoints in degrees, and
`set_rorigin` authors the radial origin. This goes beyond Plotly's native polar
trace set, which has no polar heatmap, contour, or error-bar trace.

### Tier policy

Polar traces ship `tier: "direct"`. Line/scatter/area point primitives are
point-capped by validation; heatmap/contour grids are not rejected merely
because their cell count exceeds that point ceiling. The LOD tiers do not
transfer unmodified and must not be silently reused:

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
  rejected from interactive testing: an interior anchor unexpectedly lifts
  `r_lo`. A deliberate annulus is instead authored through `hole` or
  `r_origin`, so it remains stable across view changes and every renderer uses
  the same inverse.
  Marks outside the radial range are **culled in the shader** (NaN position,
  the same gap semantics NaN data gets): below `r_lo` a mark would reflect
  through the centre, and above `r_hi` it would draw past the outer ring into
  the rect corners — the GL canvas is the plot rect, so the shader cull is the
  client's equivalent of the static exporters' shaped mark clips. Exporter
  line and scatter paths still apply the same cull
  (`_PolarProjection.position_mask`) rather than relying on their clips: a
  below-range point mirrors through the centre to a position *inside* the
  visible annulus, and an invalid vertex must produce a data gap rather than a
  boundary-clipped chord. A chord with a culled endpoint is therefore dropped
  whole in every renderer; at data resolution the gap is under one segment.
  Fills and bars
  **clamp** their radial span to `[r_lo, r_hi]` instead of culling: their
  visible extent at an angle is `[base, top] ∩ [r_lo, r_hi]`, and culling one
  endpoint made a radar fill vanish the moment zoom lifted `r_lo` above its
  baseline. A span fully outside collapses to zero and draws nothing.
- **Reset** — existing modebar, no change.
- The wheel gesture stays live even though polar's resolved default drag tool
  is `none` (pan/box/select are all disabled, so there is nothing to drag).
  Only the *user* choosing the `none` tool releases page scroll — the gate
  distinguishes that from a chart that simply has no drag tools, because
  conflating them made radial zoom dead on arrival.

Deferred and explicitly disabled rather than half-working: θ pan (rotation),
sector zoom, and box select. Box select's rectangle has no polar meaning; the
right answer is an annulus/sector select, and shipping a rectangle over a disc
in the meantime would be a wrong affordance rather than a partial one. For
reference, Plotly never solved polar wheel zoom at all — it offers radial-axis
drag only — so a small, deliberate model is already ahead of the field.

## 9. Phase 6/7 status

The Plotly-parity and axis-depth increments are shipped:

| Feature | Shipped contract |
|---|---|
| Polar heatmap / contour | Heatmap uses the browser fragment-stage inverse and the shared static inverse raster; contour uses allowlisted projected segments. |
| Sector layout | `theta_axis(sector=...)` (or compatibility `domain=...`) controls clipping, tick trimming, chrome, and a sector-bounding-box layout. Pyplot `set_thetamin`/`set_thetamax` use degrees. |
| Hole / r-origin | `r_axis(hole=...)` and `r_axis(origin=...)` implement the §3 scale-coordinate formula and inverse; authored together they fail validation. |
| Categorical θ axis | Category-index coordinates stay on the wire and are mapped evenly across the full turn or authored sector. |
| Log / symlog radial scale | Radius normalization, inverse hit testing, chrome, and static export operate in scale-coordinate space; log autorange remains strictly positive. |
| Polygonal grid | `theta_axis(grid_shape="linear")` joins spoke intersections into polygonal radial rings. |
| Polar error bars | The `errorbar` trace schema uses the polar segment branch with joint radial clipping. Generic segment/mesh support did not ship. |
| pyplot `projection="polar"` | Factories plus theta/r controls and the allowlisted mark families route into the same core polar figure. |

The remaining work stays explicitly disabled or direct-only:

| Deferred feature | Notes |
|---|---|
| Polar `rule` / `band` annotations | Point-anchored annotations (`text`, `label`, `marker`, `arrow`, `callout`) project jointly through the transform in all three renderers (`_dataPxPoint` in the client). A rule/band is genuinely different geometry on a disc — a θ rule is a spoke, an r rule is a ring, and a band is an annulus or sector — so payload build rejects them rather than drawing a Cartesian bar. |
| Polar LOD | §7. Exit criterion for `scatterpolargl`-scale claims. Point traces remain direct and capped. |
| Polar facets / animation | Untouched by this increment; no support claim is made. |
| Angular navigation / sector selection | Authored sector limits ship; interactive θ pan, sector zoom, annulus/sector selection, and rectangular box select remain disabled per §8. |
