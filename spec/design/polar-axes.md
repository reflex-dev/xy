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
| θ scale | linear only | A non-linear angle has no coherent projection; `type_="log"`/`"symlog"` on the angular axis is rejected at payload build. |
| r scale | linear, log, or symlog | Radius normalization happens in scale-coordinate space. |
| r range | `[r_lo, r_hi]` | Linear/symlog autorange retains the centre-origin default; log autorange starts at its positive minimum. Three exemptions in §2.1. |
| inner shape | `hole ∈ [0, 1)` or a data-space `r_origin` | Mutually exclusive authored controls. An omitted origin resolves to visible `r_lo`. |
| signed r | a position, never a direction | §2.2. |

The compass composition — `zero="N"`, `direction="clockwise"` — makes θ = 90°
point East, 180° South, 270° West. Wind roses depend on exactly this; §4 pins it
with fixtures.

### 2.1 Radial autorange (normative)

A linear or symlog radius starts at the **centre** (matplotlib's `rmin = 0`) and
ends at the data maximum with **no outer pad**, so the outermost ring *is* the
largest datum. A radius padded away from zero puts the smallest datum at the
centre and makes a 5%-variation series read as radiating from nothing.

Three exemptions, each because the centre-origin rule is vacuous there:

- **Log radius** — has no zero; it resolves its own strictly positive extent.
- **Data below zero** — zero is no longer an end of the range, so the ordinary
  padded extent is kept on both sides and stays symmetric about the data.
- **A time radius** — its zero is 1 January 1970. Pinning a modern instant's
  origin there squeezes the whole series into a hairline ring at the rim
  (twelve consecutive days out of ~1.7e12 ms occupy 0.0006% of the radius), so
  a time radius keeps the ordinary padded extent. A time *angular* axis remains
  refused outright (§9): an instant has no angle, but it does have a distance.

An authored `margin=` restores the outer pad — it is a request for exactly the
pad this rule otherwise drops, and honouring it is what keeps `r_axis(margin=)`
from being another accepted-and-ignored keyword. An authored `domain=`/`bounds=`
overrides autorange entirely.

### 2.2 Signed radii (normative)

A negative radius is **a position on a range that includes it**, not a direction.
`r = -5` therefore draws *nearer the centre* than `r = 0`, on an axis whose
autoranged floor is below both. It is **not** reflected through the centre the
way matplotlib reflects it — reflection would put two different data values at
the same pixel, and the §3.2 inverse could not name which one a hover found.

A radius outside the visible interval is culled for points and line vertices,
and clamped for fills and annular sectors (§8). That is the only place a
radius's sign changes what is drawn rather than where.

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

Eight properties this pins down, each of which has matching coverage:

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
- **A legend gets a gutter, not a corner.** A Cartesian legend overlays the plot
  because data rarely reaches a corner. A disc inscribed in its rect leaves no
  corner at all, so an inside legend lands on the marks — a default `upper right`
  box covered a wind rose's whole north-east quadrant and the outer radial label
  under it. `_polar_legend_reserve` (`_svg.py`, mirrored by `_polarLegendReserve`)
  therefore takes a gutter off the canvas edge **before** the disc is fitted, and
  records it as `plot["legend_box_*"]` / `view._legendBox`; the legend places and
  bounds itself in that box, and `loc` chooses where within it.
  `_polar_legend_room` (22% of the canvas width, clamped to 120–200 px) on the
  side `loc` names, or `_POLAR_LEGEND_BAND` (64 px) beneath the disc at compact
  widths, where a side gutter would leave a disc too small to read. Derived from
  the canvas width rather than measured from the label set, for the same reason
  the subdivision count is a shared formula: every renderer knows the canvas to
  the pixel, while a measured reservation would drift with each renderer's font
  metrics. A label wider than the gutter wraps in the browser and ellipsizes in
  the static exporters, which have no scroll axis to fall back on; either way the
  full text stays in `title`/ARIA. Nothing is reserved when the author supplied an
  `anchor` (an explicit plot-relative placement they own, still resolved against
  the plot) or a four-tuple `padding` (which already states the box the plot
  should occupy, and remains the way to hand-reserve a caption band), and nothing
  is reserved for a figure whose angular axis is `tick_label_strategy="none"` —
  that early return skips the whole recut, and it is the donut/gauge case whose
  chrome the author has already taken over. Both static exporters bound their
  legend so an oversized one ellipsizes instead of escaping the file, and that
  bound is `legend_clip_rect` — the plot rect **unioned** with the gutter, shared
  so the SVG `clipPath` and the raster clip command cannot drift. Clipping to the
  plot rect alone is not a smaller legend but no legend: the gutter is outside it
  by construction, so the whole box falls away.
- **A title reserves the lines it will wrap into.** `_title_wrap_width` — the
  canvas minus the *authored/default* horizontal gutters, mirrored by
  `_titleWrapWidth` in the client — is resolved before the title band, and both
  the reservation and the drawing wrap at it. Wrapping at the final plot width
  would be circular (the measured left gutter depends on the plot height, which
  depends on the title band). The client also caps the title element at that
  width, so the DOM cannot wrap into more lines than layout reserved; measuring
  one line and painting two lifted a compact Wind Rose title ~10 px off the top
  of the canvas.
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
list always, and the GPU bar sweep by construction. SVG needs no count: it draws
real `A` arcs (`_polar_wedge_path`), and `polar_wedge_points` is the flattened
twin the raster path consumes.

The subdivision count is **span-proportional and recorded as a formula**
(`config.polar_bar_segments`, mirrored by `xyPolarBarSegments` in
`js/src/50_chartview.ts`):

```
segments(span) = clamp(ceil(POLAR_BAR_SEGMENTS · |span| / turn),
                       POLAR_BAR_SEGMENTS_MIN, POLAR_BAR_SEGMENTS)
```

`POLAR_BAR_SEGMENTS` (96) is the count for a wedge sweeping a **full turn**,
sized so the chord sagitta stays inside the client's `XY_POLAR_AA` expansion up
to a ~1400-device-px disc. Sagitta is quadratic in the per-segment angle, so
holding `span / n` fixed holds the flattening error fixed: proportional
subdivision preserves that bound for every narrower wedge instead of paying the
worst case for all of them. A 16-sector wind rose sector needs six segments, not
96 — 14 vertices per bar instead of 194.

This is **not** the view-adaptive count §28 would require a recording for. The
input is the *authored* angular width — the scalar `width` on the compact bar
path, and the widest `x1 − x0` in the trace on the four-edge path (measured once
at build, cached on the trace) — so zoom, resize and export cannot change it, and
all three renderers reach the same count for the same figure. A single instanced
draw shares one count, hence "widest in the trace": every narrower wedge in it is
then over-subdivided, never under.

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
| `BAR_VS` | — | compact bars | yes — sweeps `segments(span)`+1 vertex pairs per instance (§5): an annular sector, not a quad |
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
| Sector layout | `theta_axis(sector=...)` (or compatibility `domain=...`) controls clipping, tick trimming, chrome, and a sector-bounding-box layout. Pyplot `set_thetamin`/`set_thetamax` use degrees. Tick trimming is **modular**, matching mark culling: a sector spanning the 0/turn seam (`(300, 420)`, or the compass-natural `(-30, 30)`) keeps the authored ticks on the far side of the seam, because a data point at that same angle plots inside the sector. |
| Hole / r-origin | `r_axis(hole=...)` and `r_axis(origin=...)` implement the §3 scale-coordinate formula and inverse; authored together they fail validation. |
| Categorical θ axis | Category-index coordinates stay on the wire and are mapped evenly across the full turn or authored sector. |
| Log / symlog radial scale | Radius normalization, inverse hit testing, chrome, and static export operate in scale-coordinate space; log autorange remains strictly positive. |
| Polygonal grid | `theta_axis(grid_shape="linear")` joins spoke intersections into polygonal radial rings. |
| Polar error bars | The `errorbar` trace schema uses the polar segment branch with joint radial clipping. Generic segment/mesh support did not ship. |
| pyplot `projection="polar"` | Factories plus theta/r controls and the allowlisted mark families route into the same core polar figure. |
| Angular tick text | `theta_axis(format=...)` wins over the built-in degree/radian text in all three renderers. It used to lose — the angular branch ran first and overwrote the authored spec — so a `format=` on a polar angular axis was accepted and ignored. Authored `tick_labels` still win over both, and a categorical θ axis keeps its category names. |
| Legend beside the disc | A polar figure with a legend reserves a gutter and places the legend in it (§3, layout). Zero-width wedges are legal at the mark layer, so a 0% pie/gauge slice draws nothing instead of raising. |

The remaining work stays explicitly disabled or direct-only:

| Deferred feature | Notes |
|---|---|
| Polar `rule` / `band` annotations | Point-anchored annotations (`text`, `label`, `marker`, `arrow`, `callout`) project jointly through the transform in all three renderers (`_dataPxPoint` in the client). A rule/band is genuinely different geometry on a disc — a θ rule is a spoke, an r rule is a ring, and a band is an annulus or sector — so payload build rejects them rather than drawing a Cartesian bar. |
| Secondary θ / r axes | A polar figure carries exactly one angular and one radial axis. A second axis bound and validated like a Cartesian one while the transform read only the primary pair, so an overlapping secondary range drew *pixel-identical* to the primary and a disjoint one was culled away — with a straight Cartesian spine still drawn in the gutter of a disc. Payload build rejects any axis id outside `{"x", "y"}` under `coords="polar"`. |
| Non-linear θ scale | The angle must be linear. `theta_axis(type_="log"/"symlog")` was accepted and honoured by exactly one renderer — the client scaled θ before projecting while the static exporters ignored the scale outright — so one figure pointed the same datum at opposite sides of the disc depending on where it was drawn. A log or symlog **radial** scale is supported (§3) and unaffected. |
| `reverse` on the angular axis | The Cartesian flip switch has no polar meaning; the angular axis spells direction of travel as `theta_axis(direction=...)`. `reverse=True` rode the wire and every renderer ignored it, so payload build rejects it. `r_axis(reverse=True)` is honoured. |
| Time angular axis | An instant has no angle. Datetime theta was pinned to a fixed 0..2pi range regardless of the data, so consecutive days wrapped the disc billions of times under radian spoke labels. Payload build refuses on the *resolved* column kind, not just a declared `type_="time"`. A time **radial** axis is supported, and autoranges per §2.1 rather than from epoch zero. |
| Minor ticks (`minor_tick_values`, `minor_style`) | Neither axis draws minor rings or minor spokes: the client skips the whole minor pass under polar (`!hideX && !polarGeom`) and so do both exporters (`if polar is not None: break`). The values and their style rode the wire and were dropped by all three. `xy.theta_axis`/`xy.r_axis` refuse them and point at `tick_values`. Finer rings are real geometry work, not a formatting toggle. |
| Rim label collision controls (`tick_label_min_gap`, `tick_label_strategy` in `auto`/`hide`/`rotate`/`stagger`/`preserve`) | The collision pass is edge-relative — it thins a ladder of labels along one side — and a rim has no side. Angular labels ring the disc and radial labels are stride-thinned to what the `POLAR_RLABEL_DEG` spoke holds, so a minimum gap and a collision strategy had nothing to feed. Refused; `off` (hide the labels) and `none` (hide the axis) are honoured, and `tick_count`/`tick_values` remain the deliberate way to thin. |
| `tick_label_anchor` | Polar labels anchor radially: outward around the rim, outward along the label spoke. An edge-relative anchor had nothing to act on. Refused; `tick_label_angle` rotates the text and is honoured. |

The four rows above are refused **on the documented polar surface**
(`xy.theta_axis` / `xy.r_axis`), not at payload build, and that placement is
deliberate. `xy.pyplot`'s polar projection assembles its axis out of a property
bag it does not fully own: every Axes carries an rcParam-derived `minor_style`,
and `minorticks_on()` / `tick_params(ha=)` add more. Refusing at payload build
would turn `projection="polar"` into an error over defaults nobody authored, so
`components._polar_axis_kwargs` **drops** them for that adapter — the same thing
all three renderers already do with the values — and
[`../matplotlib/compat.md`](../matplotlib/compat.md) records the drop. A
hand-authored polar axis is the case that must hear about it, and does.
| Cartesian `coords` on a polar helper | `coords` is the only thing making `polar_chart`, `pie_chart`, `radar_chart`, `polar_bar_chart` and `wind_rose` polar, so an explicit `coords="cartesian"` silently returned an axis-less cartesian figure *and* re-opened every refusal in this table (`_validate_coords` returns early for a non-polar figure). The helpers now refuse it. |
| Polar LOD | §7. Exit criterion for `scatterpolargl`-scale claims. Point traces remain direct and capped. |
| Polar facets / animation | Untouched by this increment; no support claim is made. |
| Angular navigation / sector selection | Authored sector limits ship; interactive θ pan, sector zoom, annulus/sector selection, and rectangular box select remain disabled per §8. |
