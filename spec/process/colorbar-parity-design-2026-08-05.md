# Colorbar parity: shared-layout design (P5)

Produced by an 8-agent design workflow (4 surveys, 1 synthesis, 3 adversarial
refutations) against the tree at the legend merge. Every load-bearing claim was
verified empirically before the design was written; the refutations follow the
design and are part of the contract.

I verified every load-bearing claim against the checkout before designing. Confirmed empirically: the bar math is byte-identical; horizontal tick baseline 296 (SVG) vs 297 (raster); horizontal title 306 vs 310; discrete extension defaults `rgb(253,231,37)`/`rgb(68,1,84)` vs `rgb(189,223,38)`/`rgb(72,36,117)`; `currentColor` line `#202020` vs `(76,120,168)`; `_Cmd.text` emits opcode 17 with anchor byte `1` when `bold=True` (rotation bit 128 dropped); `SLOT_BOX_PROPS` shadowed so `slot_box_declaration({'border':...}, 'colorbar')` returns `{}`.

---

# P5 shared colorbar layout — implementation-ready design

## 1. Signatures and the returned record

### 1.1 The pattern this mirrors

Three existing shared-layout precedents in `python/xy/_svg.py`, all consumed by `_raster.py` through its `from ._svg import (...)` block (`python/xy/_raster.py:27-93`):

| Precedent | Shape | Anchor |
|---|---|---|
| `layout(spec) -> (w, h, compact, plot)` | plain dict of floats | `_svg.py:3048`; called once per render at `_svg.py:4723` / `_raster.py:1017` |
| `title_placement(...) -> TitlePlacement` | `NamedTuple(style, size, block, x, baseline, anchor)` | `_svg.py:2915` (class), `2924` (producer) |
| `title_box(placement) -> Optional[ChromeBox]` | declaration-gated box **derived from the placement record** | `_svg.py:2975` |
| `axis_chrome_boxes(spec, slots) -> list[ChromeBox]` | one producer, three consumers (SVG, raster, `styling/declared.py`) | `_svg.py:4413` |

The colorbar follows `title_placement`/`title_box` exactly: **a geometry record first, a declaration-gated box producer second, derived from that record.** This split is what keeps the byte gate mechanical — the geometry producer has no declaration input that can move a coordinate.

### 1.2 Records (new, in `_svg.py` immediately above `_colorbar`, currently `_svg.py:8098`)

```python
class ColorbarTick(NamedTuple):
    value: float
    fraction: float          # 0..1 along the bar, already log/linear-mapped
    text: str                # formatted, or the paired explicit label
    x: float                 # text anchor x
    baseline: float          # first-line baseline y
    anchor: str              # "start" (vertical) | "middle" (horizontal)
    block: _textblock.TextBlock   # measured at tick_size; box producer only

class ColorbarMinorTick(NamedTuple):
    value: float
    fraction: float
    x1: float; y1: float; x2: float; y2: float   # the 3px mark, centred stroke

class ColorbarBand(NamedTuple):
    lower: float; upper: float                   # band fractions
    color: tuple[int, int, int]
    x: float; y: float; w: float; h: float       # seam ALREADY applied
    seam: float                                  # 0.5, or 0.0 when clamped

class ColorbarExtension(NamedTuple):
    side: str                                    # "min" | "max"
    points: tuple[tuple[float, float], ...]      # 3 vertices, writer order
    fill: tuple[int, int, int]                   # resolved default or payload
    outlined: bool                               # line_only -> white + stroke

class ColorbarLineMark(NamedTuple):
    value: float; fraction: float
    x1: float; y1: float; x2: float; y2: float
    color: str                                   # already through _css
    width: float
    dash: Optional[tuple[float, float]]

class ColorbarTitlePose(NamedTuple):
    text: str
    x: float; baseline: float
    anchor: str                                  # always "middle"
    angle: float                                 # 270.0 vertical CCW, 0.0 horizontal
    cx: float; cy: float                         # rotation origin == (x, baseline)
    block: _textblock.TextBlock

class ColorbarLayout(NamedTuple):
    orientation: str
    horizontal: bool
    axes_placement: bool
    # --- bar rect: the historical x/y/width/height, verbatim ---
    x: float; y: float; w: float; h: float
    # --- container: the browser mirror, new to Python ---
    cx0: float; cy0: float; cw: float; ch: float
    # --- painted content ---
    continuous: bool          # SVG takes the single gradient rect; raster bands
    gradient_id: str
    gradient_attrs: str
    bands: tuple[ColorbarBand, ...]
    extensions: tuple[ColorbarExtension, ...]
    lines: tuple[ColorbarLineMark, ...]
    ticks: tuple[ColorbarTick, ...]
    minor_ticks: tuple[ColorbarMinorTick, ...]
    title: Optional[ColorbarTitlePose]
    line_only: bool
    outline_paint: str        # text_color; line_only frame + extension strokes
```

### 1.3 Producers

```python
def colorbar_layout(
    options: dict[str, Any],
    plot: dict[str, float],
    right_axis_room: float = 0.0,
    *,
    text_color: str = _TEXT,
    tick_size: float = COLORBAR_FONT_SIZE,
    title_size: float = COLORBAR_FONT_SIZE,
    bar_inset: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
) -> ColorbarLayout:
    """The colorbar family's one geometry source (plan §7 item 1)."""
```

- `tick_size`/`title_size` are the callers' already-resolved `slot_font_size(...)` values. **They feed only `block` measurement, never a coordinate** — every current offset (`+4`, `+12`, `+22`, `+38`) is a literal independent of font size, so passing them cannot move unstyled text. This is the property that makes the byte gate mechanical.
- `bar_inset` is the container's `box_room` (§4.1). Defaults to zeros, so an unstyled render is bit-identical to today.
- `right_axis_room` stays positional-3rd to match both existing call sites (`_svg.py:5247`, `_raster.py:1823`).

```python
def colorbar_chrome_boxes(
    layout: ColorbarLayout,
    slots: dict[str, dict[str, Any]],
) -> list[ChromeBox]:
    """ChromeBoxes for colorbar / colorbar_bar / colorbar_tick / colorbar_title,
    in paint order. [] unless one of those slots declares box properties —
    the `axis_chrome_boxes` gate (_svg.py:4413), so unstyled bytes are untouched."""

class SlotStroke(NamedTuple):
    fill: Optional[str]
    stroke: Optional[str]
    width: float
    dash: Optional[tuple[float, ...]]
    opacity: float

def colorbar_slot_strokes(
    layout: ColorbarLayout,
    slots: dict[str, dict[str, Any]],
) -> dict[str, SlotStroke]:
    """Resolved paints for the three non-rect slots (colorbar_extension,
    colorbar_line, colorbar_minor_tick). ChromeBox is rect-only (x/y/w/h +
    angle, _chromebox.py:81-120); a triangle and a segment need paint without
    geometry. Reuses `_chromebox._border_width`/`_border_dash` so the
    browser's border-* vocabulary maps identically in both writers."""
```

Both writers import all four names alongside `_colorbar_right_axis_room` in `_raster.py:27-93`. `_colorbar`/`_emit_colorbar` become pure emitters over the record.

### 1.4 Container geometry (the part that exists nowhere in Python)

Mirrors `js/src/50_chartview.ts:3704-3709`, expressed as the bar rect grown by a gutter so the two stay reconcilable:

| Case | container origin | width | height |
|---|---|---|---|
| vertical, non-axes | bar x/y | `w + 48` (= 66) | `max(24, h)` |
| vertical, `placement="axes"` | bar x/y | `w + 44` | `max(24, h)` |
| horizontal, non-axes | bar x/y | `w` | `h + 32` (= 50) |
| horizontal, `placement="axes"` | bar x/y | `w` | `h + 24` |

The container **does not** union the 9 px extension triangles: the browser's extension `<svg>` is appended to `bar` with `overflow:visible` (`js/src/50_chartview.ts:3546-3551`) and the container sets no `overflow`, so extensions paint outside the container box live too. Matching that keeps the box a mirror rather than an invention.

---

## 2. Shared truth per disagreement

Browser parity is the tiebreak. The browser's per-child offsets are CSS **box tops**; the writers' are **baselines**. Converting uses the repo's own metrics (`src/font.rs:10,18` — ASCENT 15/16, DESCENT 4/16), so at the 10 px colorbar font a span whose top is at `T` has its baseline at ≈ `T + 9.4`.

| # | Disagreement | SVG | Raster | **Shared truth** | Justification |
|---|---|---|---|---|---|
| 1 | Horizontal tick baseline | `y+h+12` | `y+h+13` | **+12** | Browser tick span top = `barThickness + 2` (`js:3630`) → baseline ≈ bar_bottom + 11.4. SVG is 0.6 off, raster 1.6. Raster moves up 1 px. |
| 2 | Horizontal title baseline | `y+h+22` | `y+h+26` | **+26** | Browser title span top = `barThickness + 18` (`js:3665`) → baseline ≈ bar_bottom + 27.4. Raster is 1.4 off, SVG 5.4. SVG moves down 4 px. **These two pull opposite ways — neither writer wins wholesale**, which is exactly why the plan says "resolve to one number, don't copy". |
| 3 | Discrete extension default fill | ramp endpoints `stops[-1]`/`stops[0]` | end-band centres `colors[-1]`/`colors[0]` | **SVG (ramp endpoints)** | Matplotlib semantics: default over/under = `cmap(1.0)`/`cmap(0.0)`. Browser has no non-`line_only` extension to arbitrate, so the upstream contract decides. `_colormap_stops` is already imported into the raster (`_raster.py:46`). Measured delta: ΔR=64, ΔG=35. |
| 4 | `lines[].color = "currentColor"` / `var(...)` | `_css(color, text_color)` → `#202020` | `_parse_color(str(...))` → `(76,120,168)` palette fallback | **SVG (`_css` normalization)** | Browser default for this field IS `currentColor` (`js:3586`) resolving to `--chart-text`. `_css` is already imported into the raster (`_raster.py:50`) — an oversight, not a capability gap. |
| 5 | Line vs extension paint order | body → **lines** → extensions | body → **extensions** → lines | **Raster (line over extension)** | Browser appends the extension `<svg>` to `bar` (`js:3540-3565`) before the line `<i>` markers (`js:3574-3593`). SVG is the outlier. Becomes visible the moment either slot takes a background. |
| 6 | Explicit `tick_labels` pairing | index-paired list (`_svg.py:8185-8200`) | value-keyed dict (`_raster.py:3661-3670`) | **SVG (index pairing)** | A duplicated tick value collapses to the last label in the dict; index pairing is lossless and is what the browser does (parallel arrays, `js:3603-3622`). |
| 7 | `line_only` outline closure | `<rect>` miter join | `[*outline, outline[0]]` with default round cap (`_raster.py:288` → `src/raster.rs:761-763`) | **`closed=True`** | `_emit_slot_box` already uses `closed=True` (`_raster.py:820-826`); the colorbar is the only caller hand-closing. ~0.2 px at one corner. |
| 8 | Raster 64-band sample position | n/a | edges `i/63` painted over intervals `[i/64,(i+1)/64]` | **centres `(arange(64)+0.5)/64`** | Removes a 2.34 px positional error on a 300 px bar at zero cost; SVG and browser have none. |
| 9 | Rotation dropped under emphasis | always `transform="rotate(-90 …)"` | `cmd.text` styled branch writes `anchor & 0x03` and leaves `angle=0.0` (`_raster.py:686-701`) — **verified: opcode 17, anchor byte 1** | **rotate always** | `spec/api/styling.md:840-846` names `bar_x + bar_width + 38` as a pinned three-renderer contract, and `spec/api/capability-matrix.md:136` already claims raster honors font-weight/font-style here. Fix by routing the colorbar title through `_emit_text_block` (`_raster.py:712-747`), which passes the real `angle` and already handles the quarter-turn/emphasis split correctly. |
| 10 | `border` shorthand filtered out | — | — | **delete the second `SLOT_BOX_PROPS`** (`_svg.py:1529-1546`) | Shadowing bug: `SLOT_BOX_PROPS_BY_SLOT` (`_svg.py:1496-1501`) closed over the *first* object, so `title` honors `border` and every other box slot does not. Second set = first set − `{"border"}`. Deleting it restores one vocabulary. Blocking: without it, all 7 colorbar slots would bake in the inconsistency, and `_has_box_declaration` would gate a border-shorthand-only declaration closed while preflight reports it LOST. |

**Not unified (writers already agree, keep verbatim):** vertical tick `+4`, vertical title `+38`, minor-tick length 3, the `fraction()` closure, `_colorbar_tick_target`, the discrete band fractions and the five-part proportional guard, extension vertex order, dash rhythm `3.7w`/`1.6w`, the `+0.5` seam, bar thickness 18, the `max(2, min(8, …))` tick budget.

---

## 3. Divergences that must SURVIVE as recorded, not unified

Each becomes a `RendererDivergence` in `python/xy/styling/capabilities.py:257` (shape at `:108-124`: `id / what / webgl / svg / native / visible_when / tracked_by`).

| id | What | Why it must not be unified |
|---|---|---|
| `colorbar_compact_vertical` | Browser collapses a vertical colorbar to an 18 px bar with endpoint-only ticks and no title below 520 px fluid width (`js:661-671`, `3706-3748`) | The gate is `this.fluid` = `spec.width === "100%"` (`js:530`). A static export has already concretized its width — **the writers structurally cannot have the signal.** Pin the non-compact form; this is forced by the code, not a preference. |
| `colorbar_extension_existence` | Writers draw extension triangles for any `extend`; browser only when `line_only` (`js:3540`) | Settling it either way is a visible product change: dropping them makes `over_color`/`under_color` (`pyplot/_mplfig.py:1341-1347`) dead in every renderer; adding them live changes every mounted contour chart. Out of P5's scope; record and move on. |
| `colorbar_bar_default_border` | Browser `colorbar_bar` ships `border:1px solid currentColor; box-sizing:border-box` (`js/src/20_theme.ts:133`); writers draw none | Adopting it changes **every unstyled export** — a 1 px ring plus a 2 px ramp compression (border-box shrinks the padding box the gradient fills). Plan §7 item 4 calls this an explicit default-parity decision, "never a silent flip". Record; do not adopt in P5. |
| `colorbar_horizontal_gap` | Writers: `plot["bottom_axis_room"] or 10`; browser: constant `COLORBAR_GAP` 24 (`js:3684-3688`) | The writers' value is *measured* (42 with a bottom axis, 0→10 with `tick_label_strategy="none"`), so the offset swings across a 32 px range. Unifying to 24 would collide the bar with x tick labels in the writers, which have no DOM overflow to absorb it. |
| `colorbar_pad_zero_bottom_room` | Python reserves `18` for `pad==0` horizontal (`_svg.py:3097-3098`, `pyplot/_axes.py:8298`); browser always 38 (`js:673-675`) | 20 px. Two Python copies agree with each other and are byte-pinned through the pyplot layout path; the vertical `pad==0` cell agrees in all three. Record the one asymmetric cell. |
| `colorbar_axes_placement_shrink` | Writers ignore `shrink`/`anchor` under `placement="axes"`; browser applies them to container height and tick budget (`js:3693-3709`, `3594-3597`) | The writers are **right** for the pyplot `cax=` path — the cax rect already encodes shrink (`pyplot/_mplfig.py:1359-1381`), so the browser double-applies. Record rather than adopt the browser's bug. |
| `colorbar_shrink_clamp` | Browser clamps `shrink` to `[0.01,1]`, floors the vertical container at 24 px, and defaults `anchor[i] ?? 0.5`; writers take raw floats | Already recorded at `spec/api/styling.md:578-582`. Keep — but the shared layout **should** adopt the `max(24, …)` floor for the **container** only (never the bar), since the container is a new mirror with no byte history. |
| `colorbar_raster_band_gradient` | SVG/browser paint a true interpolated ramp; raster paints 64 solid bands | Already marked deliberate in code (`_raster.py:3600-3601`) but **absent from the registry**. Measured: viridis max ΔE 10/255; `flag` (256 stops) max 250/255, mean 40.7 — a different image. Custom resampled ramps ship 256 stops, so every custom colormap hits the `flag` class. A `cmd.grad` opcode exists (`_raster.py:258-279`), so this is a *choice*; record it now, fix it outside P5. |
| `colorbar_automatic_linear_tick_format` | Writers `f"{value:g}"` for every linear tick; browser uses `fmtLinear(value, tickStep)` for automatic ladders and `fmtGeneral` only for explicit ones (`js/src/30_ticks.ts:178-188`) | `0 / 0.2 / 0.4` native vs `0.0 / 0.2 / 0.4` live. The `%g` unification was deliberate for explicit ticks (comment at `30_ticks.ts:186-188` names the SVG/native exporters) and simply never extended. Record; the fix belongs with the tick-format contract, not the layout hoist. |
| `colorbar_minor_tick_half_pixel` | Writers centre a 1 px stroke on the fraction; browser lays a 1 px CSS border outward from it (`20_theme.ts:136-137`) | 0.5 px, and matching the browser would move every existing minor tick. |

---

## 4. Per-slot box plan

Paint order, one sequence for both writers (SVG: prepend to the returned concat at `_svg.py:8326-8331`; raster: emit before `_emit_colorbar`'s band loop at `_raster.py:3633`):

```
container box → bar box(shadow,fill) → ramp/bands → bar box(border) →
extensions → lines → minor ticks → tick pills → tick text →
title box → title text
```

The colorbar is already the last chrome in both writers and unclipped in both (`_svg.py:5595-5613` joins `*chrome` last; `_raster.py:1816-1817` resets the clip to the full canvas), so a container emitted first lands above the plot and below every child with **zero ordering work**.

### 4.1 `colorbar` — container

- **Geometry:** `(cx0, cy0, cw, ch)` from §1.4. Single source; a second computation reintroduces the 1 px-class divergences.
- **Honored:** full `SLOT_BOX_PROPS` (post-de-shadow, so `border` shorthand included).
- **Padding:** honored as an **inset of the bar inside the container** — the browser's bar is `inset:0 auto 0 0` (`js:3528-3533`), i.e. relative to the padding box, so padding moves the bar live. Fed back as `bar_inset` in `colorbar_layout`. Room grows via `_chromebox.box_room` (`_chromebox.py:192-201`) in **both** Python room copies: `_svg.layout` (`_svg.py:3091-3100`) and `pyplot/_axes._colorbar_outside_room` (`pyplot/_axes.py:8289-8301`). The browser's own reservation has no padding term (`js:665-675`) → new registry entry `colorbar_container_padding_room`.
- **Unrepresentable:** none in SVG/PDF. Raster: `border-radius` and `opacity` need rounded clipping / group compositing — but the container box is a plain filled rect, so both are drawable here; nothing to record.
- **Cascade:** the container declaration must **stop at the container**. Today's `slots.get("colorbar_title") or slots.get("colorbar") or {}` (`_svg.py:5249-5250`, `_raster.py:1825-1826`) is a whole-declaration replacement that already drops text props: verified that `styles={'colorbar':{'color':'#ff0000'}, 'colorbar_title':{'font_size':14}}` renders the title `font-size="14" fill="rgba(32,32,32,0.85)"` — the red is gone, while the browser paints it red because `_applySlot(box,'colorbar')` sets `color` on the container and the `<span>` inherits. Replace with a per-property cascade over the parent edges already declared in `python/xy/styling/cascade.py:56-62` (every colorbar sub-slot's parent is `colorbar`), restricted to the **inherited** properties (`color`, `font-*`, `letter-spacing`). Box props never inherit.

### 4.2 `colorbar_bar`

- **Geometry:** the bar rect `(x, y, w, h)` — post-`bar_inset`.
- **Honored:** `background`/`background-color` (**replaces the ramp entirely**, matching the browser where `background:red` overrides `background:var(--xy-colorbar-gradient)`), `border-*`, `border-radius`, `box-shadow`, `opacity`, `fill-opacity`. Padding is meaningless (no content) → recorded unrepresentable.
- **Seam:** the `+0.5` overhang (`_svg.py:8388,8396` / `_raster.py:3638,3642`) overhangs one orientation-dependent edge — vertical bottom, horizontal right. When a border or radius is present, clamp the final band's far edge to the bar rect (`ColorbarBand.seam = 0.0` for the last band). Otherwise seams paint over the border.
- **`lower_box` hazard:** `_chromebox.py:480-482` rejects gradient backgrounds. Any snapshot-fed `colorbar_bar` declaration normally *carries* `var(--xy-colorbar-gradient)`. The bar's ramp must keep being painted by colorbar code; only a **non-gradient user override** becomes a box fill — otherwise every styled colorbar reports a spurious unrepresentable entry.
- **Unrepresentable — SVG/PDF:** nothing. Rounded corners on the discrete band stack lower to `<g clip-path="url(#…)">` — PDF-legal (`_pdf.py:206-211`: `g` accepts `clip-path`, `clipPath` accepts `id`, `clip-path-shape` accepts `d`/`clip-rule`). **This requires `_colorbar` to receive the `_Svg` instance for `svg.uid()` (`_svg.py:1833-1835`) — it currently gets none, unlike `_legend`, which is handed `clip_id`.** Signature widening, step 6.
- **Unrepresentable — raster:** `border-radius`. `cmd.clip` is rectangle-only (`_raster.py:226-231`) and there is no group compositing, so a rounded discrete stack is *unrepresentable, not merely unimplemented*. Add `SLOT_BOX_RASTER_UNSUPPORTED["colorbar_bar"] = frozenset({"border-radius"})` (`_svg.py:1509-1511`), matching the existing `canvas` entry. A rounded **continuous** raster bar is drawable (one `_round_rect_pts` fill), so the loss is discrete-only — record it as such rather than blanket.
- **Gradient id:** leave `f"xy-colorbar-{_colormap_key(cmap)}"` (`_svg.py:8123`) **untouched** in P5. It bypasses `svg.uid()` so it ignores `id_prefix`, and it encodes the colormap but not the orientation while the direction lives in `gradient_attrs` — two facet panels sharing a cmap at different orientations emit conflicting `<linearGradient id=…>` and the second bar's ramp runs backwards. Real defect, but changing the id string breaks the `"xy-colorbar-viridis" in svg` and `rfind('<defs><linearGradient id="xy-colorbar-inferno"')` pins (§5). File separately.

### 4.3 `colorbar_extension`

- **Geometry:** the two 3-vertex polygons, verbatim (identical in both writers today, confirmed vertex-for-vertex).
- **Honored:** via `SlotStroke` — `background`/`background-color` → polygon `fill`; `border-color`/`border-width`/`border-style` → `stroke`/`stroke-width`/dash; `opacity`.
- **Precedence:** **slot declaration wins over payload.** The browser sets `fill="white" stroke="currentColor"` as *presentation attributes* then `_applySlot` adds *inline style* (`js:3556-3562`), and inline style beats presentation attributes in CSS. So `styles={'colorbar_extension':{'background':'#f00'}}` overrides `over_color`.
- **Unrepresentable (both writers):** `border-radius`, `box-shadow`, `padding` — a triangle has no `rx`, and `_slot_box_svg`/`_emit_slot_box` draw rects/rotated rects only.

### 4.4 `colorbar_line`

- **Geometry:** the segments across the bar's full cross-section.
- **Honored:** `border-color`/`border-width`/`border-style` → stroke paint/width/dash (the browser expresses these exactly as `border-left`/`border-top`, `20_theme.ts:134-135`), plus `opacity`.
- **Precedence:** slot wins — the browser's payload values land on `--xy-colorbar-line-*` custom properties (`js:3589-3591`) and `_applySlot` overwrites the longhand.
- **Dash:** the writers' `3.7w`/`1.6w` matches `_chromebox._border_dash` (`_chromebox.py:317-322`), so folding onto the shared vocabulary does not move the unstyled dash. `dotted` → dash approximation recorded (§28). The browser uses the UA `border-style:dashed` rhythm — new registry entry `colorbar_line_dash_rhythm`.
- **Unrepresentable:** `background`, `border-radius`, `box-shadow`, `padding`.
- Applies the §2 case 4 fix (`_css` in the raster).

### 4.5 `colorbar_minor_tick`

- **Geometry:** the 3 px marks, 1 px stroke.
- **Honored:** `border-color`/`border-width`/`border-style` → stroke; `opacity`. Length stays 3 px (`width`/`height` are not in the box vocabulary).
- **Spec correction required:** `spec/api/styling.md:596-600` states minor ticks "deliberately carry no slot". False — the slot is in `python/xy/dom.py:24`, has theme rules (`20_theme.ts:136-137`), gets `_applySlot` (`js:3656`), and is byte-pinned at `tests/test_static_client_security.py:325`.
- **Unrepresentable:** `background`, `border-radius`, `box-shadow`, `padding`.

### 4.6 `colorbar_tick` — pills

- **Geometry:** `_chromebox.text_box(template, pads, x=tick.x, y=tick.baseline, anchor=tick.anchor, block=tick.block, qualifiers=(orientation, str(index)))` (`_chromebox.py:253-294`). This is the family's **first** use of `_textblock.measure` — every other chrome family already routes through it; the colorbar bypasses it entirely today.
- **Honored:** text subset ∪ `SLOT_BOX_PROPS` (the `tick_label`/`axis_title` routing in `styling/preflight.py:219-227`).
- **Overflow hazard, must be stated in preflight:** no room function measures colorbar text. On a 500×320 chart ticks start at x=434 with the canvas at 500; a default-size `-1234.5` (38.1 px) already ends at 472.1, and at `font_size:24` it ends at 525.5 — 25 px off canvas. Padding on a tick pill spends canvas that was never reserved. Worse than the `tick_label` case (plan §4 item 5), where `_y_tick_label_room` at least measures.
- **Unrepresentable:** raster `opacity` reaches the box but not the glyphs (existing atlas limitation, already recorded for `tick_label`).

### 4.7 `colorbar_title`

- **Geometry:** `text_box(..., angle=layout.title.angle)`, which rotates about the text anchor — for the vertical title that is exactly `(x + w + 38, y + h/2)`, **the point both writers already rotate about**, so consuming it preserves the pinned baseline.
- **Consumes flag E, does not re-lower:** `_chromebox.rotate_points` (`:56-70`), `ChromeBox.angle/cx/cy` (`:117-120`), `_svg._rotated_box_shape` (`_svg.py:1981-2020`), `_slot_box_svg`'s shadow-in-element-space-then-rotate (`_svg.py:2023-2080`), `_emit_slot_box`'s `_chromebox_rotate` (`_raster.py:800-808`). The PDF subset backs the split exactly: `<text>` accepts `transform` (`_pdf.py:212-227`) so the title **text** keeps `rotate(-90 …)`, while `<rect>` does not (`_pdf.py:206`) so the title **box** must go through `_rotated_box_shape`.
- **Honored:** text subset ∪ `SLOT_BOX_PROPS`.
- **Blocked on §2 case 9:** without the rotation fix, a bold title's box would rotate (via `ChromeBox.angle`) while its glyphs run horizontally.

---

## 5. Byte-stability risk list

The standing gate is `tests/test_export_style_survival.py:159-165` (`test_unstyled_output_is_untouched`) plus the seven colorbar pins below. **The discipline: the hoist must be provably inert, and every number change lands in its own reviewed commit with regenerated goldens.**

### 5.1 Existing pins the family sits on

| Pin | Location | What breaks it |
|---|---|---|
| P1 | `tests/pyplot/test_gallery_log_colorbar_blockers.py:138-139` — slices from `rfind('<defs><linearGradient id="xy-colorbar-inferno"')` to EOF, asserts text nodes are exactly `["1","10","100","counts"]` | Any new `<text>` after the title. The colorbar is the last element before `</svg>` (`_svg.py:5610-5611`), so this is a real trap. New `<rect>`/`<polygon>` are safe (the regex matches `</text>` only), **including a container box emitted before the `<defs>`**. |
| P2 | same file `:177-179` — samples `pixels[48:432, 544:592]` of a 480×640 PNG | Any change to the `placement="axes"` bar rect. |
| P3 | same file `:94-97` — `_plot_box_px[2] == allocated_width - 80.0`, "pad=0 vertical chrome (62) + label (18)" | Any change to the room constants **through the pyplot path**, i.e. `pyplot/_axes.py:8300-8301`. |
| P4 | `tests/pyplot/test_gallery_colorbar_options.py:71-85`; `tests/test_color_pipeline_fixes.py:118-121` (`_colorbar_tick_target(360)==8`, `(140)==3`) | Any change to how bar length feeds the tick budget. |
| P5 | `tests/test_svg_export.py:517-531` — monkeypatches `_raster._Cmd.text`, asserts the raster vertical-title `(x,y)` equals the SVG label's `(x,y)` and `anchor == 1 \| _TEXT_ROT_CCW` | **The model for the whole design** — the one place the writers are already forced to share a pose. Must keep passing verbatim. |
| P6 | `tests/test_png_export.py:633-644` — no ink on any canvas border row/column | A container **shadow** offset. Measured headroom on that 560×320 chart: bar at x=466..484, container right edge 532, canvas 560 → 28 px titled, 10 px untitled. Background safe; shadow not automatically. |
| P7 | `tests/test_svg_export.py:458-479`, `:534-575`; `tests/test_polar_charts.py:663-678` | Geometry relations on the placed rect (bar.x past the right-axis title; `bar.y >= plot.y + plot.h + bottom_axis_room`; max `<rect y> < 500` on polar). |

### 5.2 What changes, and the containment rule

| Change | Output moved | Containment |
|---|---|---|
| Hoist bar math into `colorbar_layout` | **none** — 24 of 24 lines byte-identical; only the `domain` hoist and `gradient_attrs` differ, neither geometric | Step 2 must be provably byte-identical: golden-diff SVG **and** PNG bytes across an orientation × placement × extend × levels × line_only matrix before and after. |
| Tick baseline → +12 | **raster PNG only**, ticks up 1 px | Own commit. P4/P6 unaffected (P6 checks canvas borders; 1 px up increases headroom). |
| Title baseline → +26 | **SVG only**, title down 4 px | Own commit. P1 survives (node *order* preserved). `tests/test_png_export.py:647-670` asserts only `label_y > plot.y + plot.h` — safe. |
| Extension default fill | SVG + PNG, discrete + `extend` only | Blast radius small: the pyplot contour path always writes explicit `over_color`/`under_color` (`pyplot/_mplfig.py:1340-1347`), so only hand-built specs move. |
| `_css` on raster line color | PNG, `currentColor`/`var()` lines only | Effectively zero: `lines` is unreachable from the composition API (`xy.colorbar()` accepts only `show/render/title/orientation/ticks/class_name/style`) and the only producer sets explicit colors. |
| SVG line/extension order swap | SVG **node order**, not coordinates | Safe against P1 (text-node regex) and against every ElementTree-based pin. |
| Delete duplicate `SLOT_BOX_PROPS` | **styled output only** — `border` shorthand starts working on `axis_line`/`tick_mark`/`legend`… | No unstyled change. Own commit + capability-matrix regeneration, because preflight's `_honored_props` (`styling/preflight.py:219-227`) reads the same constant. |
| Cascade split | styled only, and only when `colorbar` **and** a child are both declared | Fixes a live loss (verified above). No unstyled change. |
| 64-band centre sampling | PNG, continuous bars, ≤2.34 px | Genuinely a bug fix; land with the reconciliation commit and regenerate raster goldens. |

**Rules that keep unstyled bytes identical by construction:**
1. `bar_inset` defaults to `(0,0,0,0)`; `tick_size`/`title_size` feed only `TextBlock` measurement, never a coordinate.
2. `colorbar_chrome_boxes` / `colorbar_slot_strokes` return empty unless `_has_box_declaration` is true for the slot — the `axis_chrome_boxes` gate (`_svg.py:4413-4467`).
3. The `<defs><linearGradient>` block stays **unconditional** (it is dead weight for `levels`/`line_only` — 256 unused `<stop>`s for a custom ramp — but making it conditional changes SVG bytes; file separately).
4. The gradient id string is not touched.
5. SVG serialization artifact preserved: `tick_attrs` is spliced after an already-trailing space, so every colorbar tick `<text>` carries a **double space** before `font-size` (`y="362"  font-size="10"`). The shared emitter must reproduce it or the byte pin breaks. Attribute order inside `slot_text_attrs` is a fixed tuple iteration (`_svg.py:1615-1636`) and is already deterministic.

---

## 6. Ordered edit list

Every anchor is current-checkout. **Plan §7's own citations are all stale** (`_svg.py` off by ≈ +1290 lines, `_raster.py` by ≈ +255; spot-checked `_svg.py:6906` → `alpha_same = …`, `_raster.py:3459` → `def _emit_legend_marker`). §8 flag C is stale the same way — it claims `_raster.py:52` imports `_estimated_text_width`; line 52 is `_density_column` and the import block does not contain it. Re-anchor §7 before starting.

---

**Step 0 — De-shadow `SLOT_BOX_PROPS`.**
Delete the second assignment and its comment block, `python/xy/_svg.py:1521-1546`; fold its docstring into the first at `:1455-1481`.
*Accept:* `'border' in _svg.SLOT_BOX_PROPS`; `_has_box_declaration({'border':'1px solid red'})` is True; `slot_box_declaration({'border':'1px solid red'}, 'colorbar_bar') == {'border': '1px solid red'}`. Unstyled SVG+PNG byte-identical. Regenerate `spec/api/capability-matrix.md` via `scripts/gen_capability_matrix.py` (`tests/test_capability_registry.py:161` forces same-commit regeneration).

**Step 1 — Add the records and `colorbar_layout`.** New code above `python/xy/_svg.py:8098`. Pure hoist of `_svg.py:8130-8331` + `_svg.py:8339-8399` (`_colorbar_body`). Add per-writer offset parameters `h_tick_offset: float = 12.0`, `h_title_offset: float = 22.0` **temporarily**, so both writers keep their current numbers.
*Accept:* new unit test asserting `colorbar_layout` reproduces, field by field, the coordinates the two writers compute today, over the matrix {vertical, horizontal} × {default, `placement="axes"`} × {continuous, `levels=5`, `levels=5 + proportional`} × {`extend` ∈ neither/min/max/both} × {`line_only`} × {`pad=None`, `pad=0`, `pad=0.05`} × {`shrink=1`, `0.5`} × {`anchor` default, `[0.2,0.8]`}.

**Step 2 — Rewire both writers as pure emitters.** `_colorbar` (`_svg.py:8098-8331`) and `_emit_colorbar` (`_raster.py:3547-3806`) consume the record; add `colorbar_layout`, `colorbar_chrome_boxes`, `colorbar_slot_strokes`, `SlotStroke` to `_raster.py:27-93`; drop the late `from ._svg import …` at `_raster.py:3574`.
*Accept:* **the byte gate.** SVG string equality and PNG bytes equality across the full step-1 matrix, before vs after. Plus all of P1-P7 green.

**Step 3 — Reconcile the numbers (own commit).** Set `h_tick_offset=12.0` for both and `h_title_offset=26.0` for both, then delete the parameters. Extension defaults → `_colormap_stops` endpoints in the raster (`_raster.py:3677,3690`). Line color → `_css(line.get("color"), text_color)` (`_raster.py:3704`). Order swap in the SVG concat (`_svg.py:8326-8331`) → `body, extend_nodes, line_nodes, minor_nodes, tick_nodes, label_node`. `closed=True` on the `line_only` outline (`_raster.py:3632`). Band centres `(arange(64)+0.5)/64` (`_raster.py:3617`). Index-paired explicit labels in the raster (`_raster.py:3661-3670`).
*Accept:* one new cross-writer test in the shape of `tests/test_svg_export.py:517-531`, extended to the **horizontal** orientation, asserting the raster's tick and title `(x, y)` equal the SVG's exactly. Plus a `colorbar_extension_default_matches_matplotlib` test (`levels=5, extend="both"` → both writers emit `rgb(253,231,37)`/`rgb(68,1,84)`), and a `currentColor` line test asserting both writers resolve to the chart text color. Regenerate raster goldens; P1-P7 re-verified.

**Step 4 — Fix the raster rotation drop.** Route the colorbar title through `_emit_text_block` (`python/xy/_raster.py:712-747`) instead of the hand-rolled `cmd.text(x, y, 1 | _TEXT_ROT_CCW, …, italic=, bold=)` at `_raster.py:3796-3806`.
*Accept:* a test asserting that with `styles={'colorbar_title': {'font_weight': 700}}` the raster title still carries the quarter-turn (ink bbox is a vertical ribbon, ~10×43, not ~43×11) and that the SVG still emits `transform="rotate(-90 …)"`. Keeps `spec/api/styling.md:840-846` and `spec/api/capability-matrix.md:136` truthful.

**Step 5 — Cascade split.** Replace the `or`-fallback at `_svg.py:5249-5250` and `_raster.py:1825-1826` with a per-property inherited cascade over `python/xy/styling/cascade.py:56-62`; widen both call sites to pass the whole slots map (`_svg.py:5242-5252`, `_raster.py:1818-1827`) and both signatures (`_svg.py:8098-8105`, `_raster.py:3547-3555`). Add the `_Svg` instance to `_colorbar`'s signature at the same time (needed in step 7).
*Accept:* `styles={'colorbar':{'color':'#ff0000'}, 'colorbar_title':{'font_size':14}}` renders the title `font-size="14" fill="#ff0000"` in both writers — matching `js:3485` + `js:3665-3667`. Unstyled bytes untouched.

**Step 6 — Container box.** `colorbar_chrome_boxes` emits the `colorbar` box first; `_svg._slot_box_svg` prepended in `_colorbar`'s return concat, `_raster._emit_slot_box` before the band loop. `box_room` folded into `_svg.py:3091-3100` **and** `pyplot/_axes.py:8289-8301`.
*Accept:* container renders under bar/ticks/text and over the plot in both writers; a container `background` does **not** leak into per-text backgrounds (the step-5 cascade test); container padding moves the bar identically in SVG, PNG, and the pyplot reservation (three-consumer test, the `legend` P4 pattern); PDF round-trip; `tests/test_png_export.py:633-644` still passes.

**Step 7 — `colorbar_bar` box.** Rect at `_svg.py:8357-8362`/`8363-8399`, raster at `_raster.py:3633-3642`. Rounded discrete stack → `<g clip-path>` using `svg.uid()` (available from step 5). Seam clamp when border/radius present. `SLOT_BOX_RASTER_UNSUPPORTED["colorbar_bar"] = {"border-radius"}` at `_svg.py:1509-1511`.
*Accept:* border+radius on continuous **and** discrete bars in SVG/PDF; band seams stay inside the border; raster discrete radius reported partial in preflight rather than half-drawn; the browser's default 1 px border is **not** adopted (golden asserts unstyled bars carry no stroke); gradient-id dedup unchanged.

**Step 8 — `colorbar_extension` / `colorbar_line` / `colorbar_minor_tick` paints.** `colorbar_slot_strokes` consumed at `_svg.py:8272-8298`/`8299-8325`/`8252-8268` and `_raster.py:3672-3698`/`3699-3712`/`3729-3733`+`3762-3776`.
*Accept:* slot declaration overrides payload `over_color`/`under_color` and per-line `color`/`width`/`dash` in both writers (browser-precedence test, mirroring `_applySlot` inline-style-over-attribute); `dotted` → dash approximation recorded in §28; the live headless-Chrome probe at `tests/test_tailwind_root_customization.py:274-302` re-used as the browser reference.

**Step 9 — `colorbar_tick` pills and `colorbar_title` box.** `text_box` consumption; per-tick `SlotInstance` qualifiers + geometry into `python/xy/styling/declared.py`.
*Accept:* rotated title box geometry byte-identical across SVG / PDF / raster from the single pose (extend the P5 pin to the box); tick pill widths recorded as metrics-divergent (§28, the DejaVu-vs-authored-family misfit already noted in `text_box`'s docstring); tick-overflow note surfaced by preflight.

**Step 10 — Registry, matrix, docs.** Add `colorbar_bar`, `colorbar_extension`, `colorbar_line`, `colorbar_minor_tick` to `STATIC_STYLED_SLOTS` (`_svg.py:1383-1401`); add their `_SLOT_PAINT_PROPERTY` entries (`tests/test_export_style_survival.py:60-76`) — all four take `background` except `colorbar_line`/`colorbar_minor_tick`, which take `border-color`; extend `styling/preflight.py:_honored_props` (`:191-250`) with the three stroke-only slots; add the ten `RendererDivergence` entries from §3 at `capabilities.py:257`; rerun `scripts/gen_capability_matrix.py`.
*Accept:* `tests/test_export_style_survival.py:79-97` green for all four new slots; `tests/test_capability_registry.py:161` and `:91` green; hand-written counts corrected — `spec/api/export.md:251` ("17 slots" → 21), the enumerations at `spec/api/export.md:326` and `spec/api/styling.md:1327`, the false minor-tick claim at `spec/api/styling.md:596-600`, and `spec/api/export.md:255`, which wrongly says `xy.colorbar(style=...)` is dropped by both writers — verified false: it lands in `spec['dom']['styles']['colorbar']`, which is exactly the map `slot_styles` returns.

---

### Out of scope, file separately (found while verifying)

- `pyplot`'s figure-level shared colorbar (`fig.colorbar(ax=[list])`) reaches only the PNG stitcher (`pyplot/_grid.py:587-611`, an ad-hoc 52 px band, no ticks/title/extensions/styling); `compose_svg` (`pyplot/_grid.py:379-390`) takes no colorbar argument, so the same figure exports a colorbar to PNG and **silently omits it from SVG and HTML**. Predates P5, sits on the shared-layout seam — decide explicitly whether the shared module claims it or it gets a §28 entry.
- Gradient `<defs>` emitted unconditionally for `levels`/`line_only`; gradient id ignores `id_prefix` and omits orientation from the key (facet collision).
- `_frame_padding` returns `None` outright when a colorbar exists and `_plot_box_px` is None (`pyplot/_axes.py:8321-8325`, "Reconciling the two is colorbar-placement work, not framing work") — a documented hole the shared layout could now close.
- The static bar carries almost no queryable identity: only the `line_only` rect has a marker (`_svg.py:8353`); normal/discrete bar rects and extension polygons have none, where the live DOM exposes `data-xy-slot="colorbar_bar"` and `data-xy-colorbar-extend`. Three existing tests locate the bar by `fill="url(#xy-colorbar-"`, so a `colorbar_bar` background override that replaces the gradient url makes them find nothing.

---

# Adversarial refutations

## Refutation 1

## Verdict: the design breaks 6 existing tests. Two are structurally unfixable as written, one is a preflight contract the design silently inverts.

All findings re-verified against the **post-P4 tree** (the checkout moved under me at 18:17 while I worked — P4 legend parity landed and invalidated several of the design's anchors; see §D). Method: a byte-identical snapshot of `python/`, `tests/`, `js/`, `docs/`, `spec/`, `src/` + the prebuilt `libxy_core.dylib` at `/private/tmp/claude-501/-Users-alek-Desktop/fb4772f2-e6f7-4750-95ee-9c2b1fe6a5e2/scratchpad/xy-exp2`, with the design's steps applied and `pytest tests` run (3880 passed / 111 skipped baseline). The read-only checkout was never touched.

---

### A. CONFIRMED BREAK — `test_styles_on_a_slot_with_no_native_path_are_named_lost`

`/Users/alek/Desktop/xy-compat/tests/test_style_compatibility_report.py:110-119`

```python
report = _chart(styles={"colorbar_bar": {"border-radius": "2px"}})
report = report.style_compatibility_report("png")
finding = _finding(report, "colorbar_bar", "styles")
assert finding.route == pf.ROUTE_BROWSER_ONLY      # <- breaks
assert finding.lost == ("border-radius",)
assert not report.lossless
```

Adding `colorbar_bar` to `STATIC_STYLED_SLOTS` (step 10) — **on its own, before any writer code** — flips `capabilities.CHART_SLOTS["colorbar_bar"].support["native_raster"]` from `none` to `partial`, so `preflight._styles_finding` (`python/xy/styling/preflight.py:335`) no longer takes the `ROUTE_BROWSER_ONLY` branch. Observed: `AssertionError: assert 'native-subset' == 'browser-only'`.

The test's own comment names P5 as the thing that will break it ("`colorbar_bar` is static chrome whose writers arrive with the colorbar family (plan §7)") — the design's step-10 acceptance list cites `test_export_style_survival.py:79-97`, `test_capability_registry.py:161` and `:91`, and never this file.

**This one cannot be fixed by moving the example to another slot.** After P5 adds all four, the set of static slots with no native writer is empty:

```
static slots with no writer after P5: []
```

So `_styles_finding`'s `ROUTE_BROWSER_ONLY` branch becomes unreachable from `source="styles"` entirely (it survives only for `class_names` and state-gated slots). The test has to be rewritten or deleted, and that is a published-contract decision, not a rename. Nothing in the design mentions it.

---

### B. CONFIRMED BREAK — three `test_every_static_slot_carries_its_paint_into_svg` params are unsatisfiable

`/Users/alek/Desktop/xy-compat/tests/test_export_style_survival.py:65,83-99`

```python
_SLOT_PAINT_PROPERTY = {slot: "fill" for slot in STATIC_STYLED_SLOTS} | {...}
@pytest.mark.parametrize("slot", STATIC_STYLED_SLOTS)
def test_every_static_slot_carries_its_paint_into_svg(slot):
    chart = xy.scatter_chart(..., xy.colorbar(title="Colorbar title"), ..., styles={slot: {_SLOT_PAINT_PROPERTY[slot]: "#123456"}})
    assert "#123456" in chart.figure().to_svg()
```

Observed failures after step 10 (with the design's own `_SLOT_PAINT_PROPERTY` additions applied):

```
FAILED ...[colorbar_bar]        FAILED ...[colorbar_extension]
FAILED ...[colorbar_line]       FAILED ...[colorbar_minor_tick]
```

`colorbar_bar` is merely unimplemented (step 7 would fix it). The other three are **structurally impossible**: the parametrized chart is built through the composition API, and `xy.colorbar()` (`python/xy/components.py:3105-3114`) accepts only `show/render/title/orientation/ticks/class_name/style` — no `extend`, no `lines`, no `minor_ticks`. Measured on that exact chart:

```
minor markers: 0   line markers: 0   polygons: 0
colorbar options: {'domain': [0.0, 1.0], 'colormap': 'viridis', 'label': 'Colorbar title', 'orientation': 'vertical'}
```

There is no chrome for the paint to land on, so no writer change can make `#123456` appear. The design's step-10 acceptance ("green for all four new slots") is unachievable without either widening the public `xy.colorbar()` surface — an API change guarded by `_validated_colorbar_fields` (`components.py:3141`) and `test_declarative_colorbar.py::test_colorbar_rejects_invalid_public_options` — or replacing the shared chart builder with per-slot hand-built specs. The design contradicts itself here: §5.2 states "`lines` is unreachable from the composition API," yet §10 assumes the parametrized test will go green.

---

### C. CONFIRMED BREAK — step 5's cascade split drops `fill` on the `colorbar` slot

`tests/test_export_style_survival.py::test_every_static_slot_carries_its_paint_into_svg[colorbar]`

`_SLOT_PAINT_PROPERTY["colorbar"]` resolves to `"fill"` (line 65 default; `colorbar` is not in the `background` override list at 67-81). Today `styles={"colorbar": {"fill": "#123456"}}` reaches the tick/title `<text>` through the whole-declaration fallback at `_svg.py:5274` / `_raster.py:1831`. §4.1 replaces that with a cascade "restricted to the **inherited** properties (`color`, `font-*`, `letter-spacing`)". `fill` is not in that list, and the container box honors `SLOT_BOX_PROPS`, which has no `fill` (only `fill-opacity`). I implemented exactly the design's rule and got:

```
FAILED tests/test_export_style_survival.py::test_every_static_slot_carries_its_paint_into_svg[colorbar]
AssertionError: styles={'colorbar': ...} was dropped
```

**The worse half is untested and therefore silent.** Preflight today reports:

```python
{'slot': 'colorbar', 'source': 'styles', 'route': 'survives', 'kept': ('fill',), 'lost': ()}
```

because `_honored_props` falls through to the text subset for `colorbar` (`preflight.py:285`). Step 10 only extends `_honored_props` "with the three stroke-only slots" — it never re-routes `colorbar` from text slot to box slot. So after step 5 the writers drop `fill` while the report still says `survives` and `strict` mode still passes. That is precisely the writer/report drift `preflight.py:196-199` exists to prevent.

Same applies to `opacity`, which `SLOT_TEXT_PROPS` (`_svg.py:1346-1355`) honors on text and which CSS does not inherit.

---

### D. The design's premises have already gone stale (it complains about exactly this in §6)

| Design claim | Current tree |
|---|---|
| §2 case 10 / **Step 0 "Blocking": `SLOT_BOX_PROPS` is shadowed, delete `_svg.py:1521-1546`** | **Already done.** One definition only, at `_svg.py:1492`; `'border' in SLOT_BOX_PROPS` is `True`; `SLOT_BOX_PROPS_BY_SLOT` now also carries `legend_item`/`legend_swatch`. Step 0 is a no-op. |
| §10 "`spec/api/export.md:251` (\"17 slots\" → 21)" | Reads **19 slots**; the target is 23. `export.md:326` / `styling.md:1327` already enumerate `legend_item`/`legend_swatch`. |
| §4.2 `SLOT_BOX_RASTER_UNSUPPORTED` at `_svg.py:1509-1511` | now `1542`; `_colorbar` at `8563`, the slot fallbacks at `_svg.py:5274` / `_raster.py:1831`. |

Every `_svg.py`/`_raster.py`/test line number in the design needs re-anchoring, not just §7's.

---

### E. One containment claim in §5.2 is factually wrong

> "Extension default fill … Blast radius small: the pyplot contour path always writes explicit `over_color`/`under_color` (`pyplot/_mplfig.py:1340-1347`), so only hand-built specs move."

`_mplfig.py:1329-1347` writes them **only when `color_table` is an ndarray**. With a named/default colormap it does not:

```
contourf(..., extend="both")  -> {'extend': 'both', 'levels': 4}   # no over_color/under_color
contourf(..., extend="min")   -> {'extend': 'min',  'levels': 4}
```

So the change moves real shim output for ordinary `contourf(..., extend=...)`, which `tests/pyplot/test_frame_geometry.py::test_constrained_colorbar_grid_keeps_balanced_cells_across_static_exports` renders in all four extend modes and `tests/pyplot/test_pdsh_gap_features.py::test_colorbar_ticks_and_extend_reach_both_exports` renders too. Neither asserts the triangle color, so neither fails — but "only hand-built specs move" is wrong and the today-divergence is larger than stated:

```
SVG default over/under:            (253,231,37) / (68,1,84)
raster levels=4 over/under:        (172,220,49) / (70,44,122)   # ΔR=81, ΔG=11 / ΔG=43, ΔB=38
```

Related ordering hazard the design does not name: change (g) (64-band centres) **alone** also moves the *continuous* raster extension default, `(253,231,37)/(68,1,84)` → `(248,230,37)/(68,4,87)`, because the raster reads `colors[0]`/`colors[-1]` off the same LUT. §5.2 describes (c) as "discrete + `extend` only", which is true only because (c) and (g) are bundled in step 3. Split them and step 3 introduces a fresh SVG/PNG divergence.

---

### F. What I checked and found genuinely byte-safe

I applied the design's steps 3 and 4 verbatim and ran the whole suite (`3880 passed`, only the failures above):

- SVG horizontal title `+22 → +26` (verified moved: `y=306 → y=310`, canvas 320, descent-safe). **No test pins it.**
- Raster horizontal tick baseline `+13 → +12`. **No test pins it.**
- SVG line/extension node-order swap. **No test pins it** — `test_hexbin_demo_log_colorbar_keeps_counts_and_covers_svg_cell_seams` (`tests/pyplot/test_gallery_log_colorbar_blockers.py:138-139`) matches `</text>` only, and its `<polygon>` sweep at `:143-146` never sees an extension because that chart has no `extend`.
- `closed=True` on the `line_only` outline; `_css` on the raster line color; 64-band centre sampling. **Unpinned.**
- Step 4's `_emit_text_block(..., angle=270.0)` reroute: the quarter-turn branch (`_raster.py:730-740`) emits `cmd.text(x, y, anchor | _TEXT_ROT_CCW, size, color, line)` positionally, identical bytes, so the P5 cross-writer pin (`tests/test_svg_export.py:517-531`, `assert anchor == 1 | _raster._TEXT_ROT_CCW`), `test_png_export.py:596-631`, and `tests/pyplot/test_pdsh_gap_features.py:312-342` all stay green. `src/raster.rs:1800-1880` `styled_text` applies a full affine (`transform(u,v) = (x + u·cosθ − v·sinθ, …)`), so the bold path really does rotate glyphs — step 4's acceptance is achievable.
- `test_gallery_log_colorbar_blockers.py` P1-P3, `test_png_export.py:633-644` (P6), `test_polar_charts.py:663-678`, `test_pdf_text_subset.py`, `test_declarative_colorbar.py`, `test_custom_ramps_and_palette.py`, `test_static_client_security.py`, `test_text_weight_defaults.py`, `test_type_surface.py` — all unaffected.

Two consequences worth stating plainly: the design's elaborate byte-gate ceremony in §5 is guarding numbers that **no test currently pins**, so the gate has to be written from scratch as part of step 1/2 rather than "kept green"; and the design's own §5.1 pin table is not where the risk actually lives — it lives in `test_style_compatibility_report.py` and `test_export_style_survival.py`, neither of which §5.1 lists.

Two smaller confirmations for the design: `xy.colorbar(style={"fill": "#123456"})` does reach both writers today (so `spec/api/export.md:255` is wrong, as claimed), and `spec/api/styling.md:597-600` ("Minor ticks … deliberately carry **no slot**") does contradict `spec/api/styling.md:698`, which lists `colorbar_minor_tick` as a slot in the same document. Also verified feasible: `_colorbar_outside_room` (`pyplot/_axes.py:8289`) is a method on an object that already holds `self._chrome_styles` (`_axes.py:1503`), so step 6's room fold is implementable there.

---

## Refutation 2

Verified against the checkout (Chrome 560×320/640×360 renders, live CSS probe, both writers driven directly). **The design has real geometry defects.** Ranked:

---

## 1. BLOCKING — the container's horizontal height (50) lands 12 px off-canvas in the default configuration

§1.4 imports the browser's container box wholesale (`js/src/50_chartview.ts:3707-3709`: horizontal non-axes `height = 50`) while §3 deliberately *keeps* the writers' divergent gap (`colorbar_horizontal_gap`: `plot["bottom_axis_room"] or 10` at `python/xy/_svg.py:8148` / `python/xy/_raster.py:3588`, vs the browser's constant `COLORBAR_GAP = 24` at `js/src/50_chartview.ts:152,3686`). Those two decisions are individually defensible and **jointly inconsistent**: the browser's reservation (`38 + label?16`, `js:3532-3534`) is sized for a 24 px gap; `layout()` reuses the same `38` (`_svg.py:3097-3098`) under a gap that is *measured* and typically 42.

Worked, from the actual layout:

```
xy.heatmap_chart(xy.heatmap([[0,1],[2,3]], colormap="viridis", domain=(0,3)),
                 xy.colorbar(orientation="horizontal"), width=560, height=320)

layout()  -> plot = (62, 10, 484, 230),  bottom_axis_room = 42,  reserved below plot = 80 (42 base + 38)
bar        = (62, 282, 484, 18)
container  = (62, 282, 484, 50)  -> bottom = 332      canvas H = 320   OVERFLOW = +12.0 px
```

General condition: `overflow = bottom_axis_room + 50 − (base_bottom + 38)`. With any bottom axis `bottom_axis_room ≈ base_bottom`, so it is **structurally +12 px** for every horizontal colorbar without a title. With a title it is −4 px (reserved becomes 96), and vertical is −10/−28 px. So the failing case is exactly `xy.colorbar(orientation="horizontal")` with no title — the plainest spelling.

The design's own guard is blind to it: step 6 cites `tests/test_png_export.py:633-644`, which is `test_native_vertical_colorbar_label_leaves_the_canvas_edges_unpainted` — a **vertical, titled** chart, i.e. the configuration with the *most* slack (28 px, exactly the number §5.1 P6 quotes). A container background/border in the failing case is clipped at the canvas and paints the bottom border row, which is precisely what that test forbids for its own orientation.

The container must be sized against the writers' reservation, not copied from a browser whose origin differs by 18 px.

---

## 2. BLOCKING — §4.1's padding model is wrong in kind and in sign; the browser does not move the bar at all

§4.1: *"the browser's bar is `inset:0 auto 0 0` (`js:3528-3533`), i.e. relative to the padding box, so padding moves the bar live."* An absolutely positioned child's containing block **is** the padding box, which means padding does **not** translate it. Measured in Chrome (headless, `getBoundingClientRect`):

```
box  {position:absolute; left:100; top:50; width:66; height:200; padding:8px}
  bar {position:absolute; inset:0 auto 0 0; width:18}   -> x=100  y=50   h=216
  tick{position:absolute; left:23px}                    -> x=123
box2 {left:300; width:66; height:200; border:4px solid}
  bar2{position:absolute; inset:0 auto 0 0; width:18}   -> x=304  y=54   h=200
```

Live behaviour of `styles={'colorbar': {'padding':'8px'}}`: the bar **does not move**; it *stretches* by 16 px (its `inset:0 … 0` resolves against the padding box). Only `border-width` translates children (bar2 shifted by exactly 4).

The design's mechanism does the opposite, and in the opposite direction. `box_room` (`_chromebox.py:191-200`) grows `right` in `layout()`, and `bar.x = plot.x + plot.w + right_axis_room + gap = width − right + …`, so growing `right` moves the bar **left**. Net with `bar_inset.left`:

```
bar.x' = bar.x − (pad_l + pad_r + 2·border) + pad_l = bar.x − pad_r − 2·border
```

Concrete (560×320 vertical, untitled, `padding:8px`): static bar goes 484 → 476 (−8 px, unchanged length); live bar stays at 484 and grows 268 → 284 px long. A 8 px position gap plus a 16 px length gap, on the one property §4.1 singles out as the browser-parity justification. The design also never gives `border-width` its child-shifting term, which is the *only* box property that legitimately moves the bar live.

---

## 3. The seam clamp names the wrong band in the vertical (default) orientation

§4.2: *"clamp the final band's far edge to the bar rect (`ColorbarBand.seam = 0.0` for the last band). Otherwise seams paint over the border."* The `+0.5` (`_svg.py:8388,8396`; `_raster.py:3638,3642`) extends **height** downward / **width** rightward, so which band crosses the bar rect depends on orientation. Emitted rects, bar `y ∈ [10, 310]`, `levels=5`:

```
vertical  (loop order = emission order)      horizontal
  idx0: y=250.00 h=60.5 -> 310.50  <== overhangs bar bottom (310)
  idx1: y=190.00 h=60.5 -> 250.50            idx0: x= 60 w=80.5 -> 140.5
  idx2: y=130.00 h=60.5 -> 190.50            ...
  idx3: y= 70.00 h=60.5 -> 130.50            idx4: x=380 w=80.5 -> 460.5  <== overhangs bar right (460)
  idx4: y= 10.00 h=60.5 ->  70.50
```

Vertical: the overhanging band is **index 0** (lowest fraction, first emitted). Horizontal: index n−1. Setting `seam = 0.0` on "the last band" therefore (a) leaves the 0.5 px overhang past the bar's *bottom* border untouched in the default orientation — the stated failure still happens — and (b) removes an *interior* 0.5 px overlap between the top band and its neighbour, reintroducing exactly the antialias hairline the `+0.5` exists to suppress. `ColorbarBand.seam: float` also carries no side, so the record as specified cannot express the correct rule.

---

## 4. §2 case 8 (64-band centre resampling) is not "zero cost" — it moves the bar off the ramp's endpoints and opens a cap/band seam

Today `_lut(cmap, linspace(0,1,64))` makes the raster's extreme bands **exactly** the SVG gradient's and the browser's endpoints. Measured:

```
cmap     stops[-1]        today[-1]        proposed[-1]      stops[0]        today[0]        proposed[0]
viridis  (253,231,37)     (253,231,37)     (248,230,37)      (68,1,84)       (68,1,84)       (68,4,87)
turbo    (122,4,3)        (122,4,3)        (128,7,3)         (48,18,59)      (48,18,59)      (50,24,70)
flag     (0,0,0)          (0,0,0)          (0,0,124)         (255,0,0)       (255,0,0)       (255,177,124)
```

The centre form is exact at band centres and now *wrong at both ends* by 0.5/64 of ramp space — Δ124 and Δ177 on `flag`, i.e. the same 256-stop class §3 says every custom resampled ramp falls into. Worse, it interacts with §2 case 3: after the cap fill becomes `stops[±1]` and the end band becomes `_lut(cmap, 63.5/64)`, the raster paints an extension triangle whose colour no longer matches the band it abuts — a seam present in neither writer today nor in the browser (whose `linear-gradient` reaches `stops[0]`/`stops[-1]` at 0 %/100 %, `js:3524-3527`).

---

## 5. §2 case 3 resolves against the repo's own stated contract when `band_colors` is present

The justification (*"Matplotlib semantics: default over/under = `cmap(1.0)`/`cmap(0.0)`"*) silently assumes `options["colormap"]` is the effective ramp. When `band_colors` is set it is not — `pyplot/_mplfig.py:1322-1324` says so in as many words: *"Listed contour fills already carry their exact per-band RGBA table. Keep that table on the colorbar instead of replacing it with samples from the nominal fallback colormap. Extended rows own the cap colors."* Driving both writers with a `band_colors` spec that carries no `over_color`/`under_color` (the `_mplfig.py:1326-1328` branch, which sets `band_colors` alone):

```
band_colors = [[255,0,0],[0,255,0],[0,0,255]], extend="both", colormap="viridis"
SVG   caps: rgb(253,231,37) / rgb(68,1,84)      # viridis — appears nowhere on the bar
RASTER caps: (0,0,255) / (255,0,0)              # the actual end bands
```

The design picks SVG, so the caps become viridis on a red/green/blue bar. The measured "ΔR=64, ΔG=35" in §2 was taken on the sampled-colormap case only; with `band_colors` the delta is unbounded (255 here). The correct rule is `band_colors[±1]` when a band table is present, `stops[±1]` otherwise. (I confirmed the divergence is discrete-only: for a continuous bar `_lut(cmap,1.0) == stops[-1]`, so the writers already agree.)

---

## 6. §2 cases 1 and 2 cannot both be "browser parity" — the browser's delta is 16, the design picks 14

Both spans carry the same 10 px font, so whatever top→baseline constant you use, the browser's title-minus-tick baseline gap is exactly `18 − 2 = 16` (`js:3630` vs `js:3665`). SVG today is 10, raster 13, the design's (12, 26) is 14. Applying the design's own stated tiebreak consistently gives (12, 28) or (11, 27). Choosing 12 because "SVG is 0.6 off" and 26 because "raster is 1.4 off" is per-row nearest-neighbour copying — the thing plan §7 says not to do — and it leaves an unexplained 2 px in a family whose whole point is one derived number.

---

## 7. `line_only` already draws the 1 px bar border the design says the writers never draw

`colorbar_bar_default_border` (§3) states *"Browser `colorbar_bar` ships `border:1px solid currentColor` (`20_theme.ts:133`); writers draw none."* False for `line_only`: `_svg.py:8353-8356` emits `fill="white" stroke=text_color stroke-width="1"` and `_raster.py:3630-3632` strokes the same outline — the writers' emulation of that exact theme rule (the browser's `line_only` bar is `linear-gradient(white,white)` + the theme border, `js:3519`). §4.2 never mentions `line_only`, so step 7 would stack a declared `colorbar_bar` border box on top of the built-in stroke: `styles={'colorbar_bar':{'border':'2px solid red'}}` renders a 2 px red box *and* a 1 px `rgba(32,32,32,0.85)` stroke.

---

## 8. Tick/title offsets are font-size-independent, so §4.6's pills will be drawn over the bar

§1.3 correctly notes `+4/+12/+22/+38` carry no font-size term — but then §2 derives them from a browser whose offsets are box tops that *do* scale, at "the 10 px colorbar font". Verified with `styles={'colorbar_tick': {'font-size': '24px'}}`, horizontal:

```
size=10: baseline = bar_bottom + 12, ascent 9.38  -> glyph top = bar_bottom + 2.6  (below the bar)
size=24: baseline = bar_bottom + 12, ascent 22.50 -> glyph top = bar_bottom − 10.5 (10.5 px INSIDE the bar)
browser at 24: baseline = bar_bottom + 2 + 22.50 = bar_bottom + 24.5
```

Today this only mis-places glyphs; §4.6 adds a filled `text_box` pill at that baseline, which becomes an opaque rect painted across the bar. The vertical `+4` centring hack has the same defect (correct only near 10 px; the browser uses `translateY(-50%)`, exact at any size). Neither is in §3's divergence list nor in §4.6's hazard note, which flags only horizontal overflow.

---

## 9. Step 4's `_emit_text_block` reroute is not byte-inert for multi-line titles

`_emit_text_block` (`_raster.py:713-747`) splits on lines and emits one `cmd.text` per line; the current colorbar call (`_raster.py:3796-3806`) passes the whole string in one command. Single-line unstyled titles do stay byte-identical (the `quarter_flag and not italic and not bold` branch at `:742-743` reproduces the current call exactly), but a multi-line title changes the PNG. Step 4's acceptance criterion covers only the styled/rotation case.

---

### Checked and found correct (no defect)

Bar-rect math is byte-identical across `_svg.py:8134-8161` / `_raster.py:3579-3599` (all three branches, `pad`, `shrink`, `anchor`, `right_axis_room`); the §1.4 container table does faithfully mirror `js:3704-3709` for all four cases; axes-placement and `pad=0` container edges fit their reservations (+base slack); the `SLOT_BOX_PROPS` shadowing is real and gates as described (`_svg.py:1462-1481` vs `:1527-1546`; `title` keeps `border`, nothing else does); case 4 is real (`_css("currentColor", _TEXT) = rgba(32,32,32,0.85)` vs `_parse_color("currentColor") = (76,120,168)`); case 6's index-vs-dict pairing matches the browser's parallel arrays; case 7 (`closed=False`, `cap="round"` at `_raster.py:286-288`); case 9 (`_Cmd.text` styled branch masks `anchor & 0x03` and passes `angle=0.0`, `_raster.py:687-702`); extension vertex order, the proportional guard, `_colorbar_tick_target`, minor-tick length, dash rhythm, and the `levels < 1` edge cases all genuinely agree between the writers; the colorbar really is last in both chrome orders (`_svg.py:5242-5252` + the final `*chrome`; `_raster.py:1816-1827` after the clip reset); `compose_svg` (`pyplot/_grid.py:379-390`) really does take no colorbar argument.

---

## Refutation 3

I read `_pdf.py`, `_chromebox.py`, both writers' colorbar paths, and the live client, and probed the PDF converter with the exact constructs the design implies.

## Verdict: the design does not name a construct `_pdf.py` rejects — but its paint order is wrong in five places, and one of them breaks PDF specifically.

What I probed and confirmed **legal**: rotated polygon/path boxes with shadow + dash + radius, `<rect rx>` with a gradient fill, `<g clip-path>` over a rounded `<path>` clip, `<g clip-path opacity>`, `<clipPath>` emitted outside `<defs>`, `<polygon>`/`<line>` carrying the whole `SlotStroke` vocabulary, and today's unstyled colorbar SVG.

---

### F1 — The §4 bar order is not expressible; both achievable orders are wrong

`_svg._slot_box_svg` (`/Users/alek/Desktop/xy-compat/python/xy/_svg.py:2023-2081`) emits shadow (`:2050-2065`) then **one** shape carrying `fill` *and* `stroke` (`:2066-2079`). `_raster._emit_slot_box` (`/Users/alek/Desktop/xy-compat/python/xy/_raster.py:783-826`) is identical in structure. There is no split entry point, and step 7 adds none.

So `container box → bar box(shadow,fill) → ramp/bands → bar box(border)` cannot be emitted. Both single-call placements fail:

- **Box before ramp** — the ramp rect is *exactly coincident* with the bar rect (`_svg.py:8358-8361`, `_raster.py:3635-3643`), so the inner half of the centered stroke is erased. `border-width: 4px` renders a 2px ring pushed 2px outward. The `canvas` precedent (`_svg.py:5561` emitted inside `canvas_group_open` at `:5600`) survives border-under-content only because marks are sparse; a colorbar ramp is 100% coverage.
- **Box after ramp** — `_slot_box_svg` writes the shadow rect immediately *before* the box shape, so `box-shadow: 3px 3px` paints a solid offset rect **on top of** the ramp instead of behind it. Same at `_raster.py:811-813`.

Compounding: `colorbar_chrome_boxes(layout, slots) -> list[ChromeBox]` "in paint order" cannot express an interleave with non-`ChromeBox` content, so both writers must re-implement the ordering — the duplication P5 exists to delete.

### F2 — PDF has no transparency group; `<g opacity>` over the band stack produces 63 stripes the SVG doesn't have

§4.2 claims "Unrepresentable — SVG/PDF: nothing" while honoring `opacity`. `_pdf._render_g` (`_pdf.py:1228-1265`) does `child.opacity = state.opacity * …` and each shape consumes it as its own `/ca` (`_pdf.py:1044-1049`). Verified on a real conversion — the content stream is:

```
1 0 0 rg  /G1 gs  10 10 m … f      # /G1 = << /ExtGState /ca 0.5 /CA 1 >>
0 0 1 rg           50 10 m … f
```

No `/Group << /S /Transparency >>`. The bands overlap by exactly 0.5px at every boundary (`_svg.py:8388`, `:8396`; `_raster.py:3639`, `:3643`). At `opacity:0.5` the seam is `0.5·Cᵢ + 0.5·W` in SVG (group flattens first) and `0.5·Cᵢ + 0.25·Cᵢ₋₁ + 0.25·W` in the PDF converted *from that same SVG*. For the viridis dark end `Cᵢ₋₁=(68,1,84)` that is a **(−47, −64, −43)/255** stripe, 63 times. `SLOT_BOX_RASTER_UNSUPPORTED["colorbar_bar"]` also needs `opacity` for the reason `canvas` has it (`_svg.py:1508-1511`, `_raster.py:1185-1196`), and §4.2 scopes it to `{"border-radius"}`.

### F3 — "A rounded continuous raster bar is drawable (one `_round_rect_pts` fill)" is false

`/Users/alek/Desktop/xy-compat/python/xy/_raster.py:3614-3616`:

```python
    else:
        n_seg = 64
        colors = _lut(options.get("colormap", "viridis"), np.linspace(0.0, 1.0, n_seg))
```

The continuous raster bar is **64 solid band rects**, not one fill. `cmd.clip` is rectangle-only (`_raster.py:226-231`), so `border-radius` on `colorbar_bar` is unrepresentable in the raster for continuous *and* discrete. Scoping the record to "discrete-only" (§4.2) and accepting on "raster discrete radius reported partial" (step 7) ships a silently square-cornered continuous PNG bar with no §28 entry. Two more gaps in the same seam: `preflight.py:243-247` only reaches `SLOT_BOX_RASTER_UNSUPPORTED` for slots present in `SLOT_BOX_PROPS_BY_SLOT` (`_svg.py:1489-1494` — title/root/canvas/chrome only), and the raster needs a `canvas`-style strip (`_raster.py:1190-1196`). Neither is in the edit list.

### F4 — `background-color` must paint UNDER the ramp, not replace it

`js/src/20_theme.ts:133` sets the ramp with the `background` **shorthand** → a background-*image*. `_applyStyle` writes the author's key as a longhand (`js/src/50_chartview.ts:1705-1714`, `el.style.setProperty(property, cssValue)`). CSS paints background-color beneath background-image, so live `colorbar_bar {background-color:#f00}` is completely hidden by the opaque gradient; only the `background` shorthand replaces it. `_chromebox.lower_box` collapses the two (`_chromebox.py:476-479`) and §4.2 states them as one rule — static would show a solid red bar where every browser shows the ramp. `colorbar_bar` is the first slot in this program whose stylesheet default is a background-image, so no earlier family caught it.

### F5 — the `line_only` frame double-paints under a declared border

`_svg.py:8352-8357` hard-codes `fill="white" stroke="{text_color}" stroke-width="1"` on the bar rect; `_raster.py:3630-3632` the same. §4.2 never reconciles that frame with a declared `colorbar_bar` border, so `{'border-color':'red','border-width':'3px'}` paints two concentric strokes on the same edge — whichever order you pick, one shows through. The browser has exactly one (`_applySlot` overwrites the theme's `border:1px solid currentColor`). Same hazard for `line_only` + `background`.

### F6 — `box-sizing: border-box` is only applied to the *default* border

`20_theme.ts:133` ends `box-sizing:border-box`. Live, a declared border draws entirely **inside** the 18px box and the gradient fills the shrunken padding box. `_slot_box_svg` centers the stroke on the geometry edge and the ramp is not inset. `border-width: 6px` → live: 6px ring + 6px ramp; static: 3px outside the bar, 3px over the ramp, ramp still 18px. §3's `colorbar_bar_default_border` applies this reasoning to the 1px default and then drops it.

### F7 — raster round caps overhang the newly-honored `border-width`

`_Cmd.stroke` defaults `cap="round"` (`_raster.py:287`) and `_emit_colorbar` never overrides it (`_raster.py:3709`, `:3721-3725`, `:3762-3766`). SVG `<line>` emits no `stroke-linecap` → butt, and `_pdf` maps the default to butt (`_pdf.py:1050-1053`). Measured on the native rasterizer:

```
1px wide, 3px long: ink x 19..23 (len 5)     # SVG/PDF: 3
6px wide, 6px long: ink x 17..28 (len 12)    # SVG/PDF: 6
```

§4.4/§4.5 make `border-width` reachable for the first time, so `colorbar_line {border-width:6px}` overhangs both bar ends by 3px in PNG and sits flush in SVG/PDF **and** the browser (the live marker is a `border-top` on an `inset-inline:0` element, `js/src/50_chartview.ts:3585-3587`). §2's "Not unified (writers already agree)" list wrongly includes "minor-tick length 3" — it is 3 in SVG and 4 in the raster today.

### F8 — PDF trap: the obvious rounded-clip spelling is rejected

Probed: `<clipPath id="c"><rect x=… rx="6"/></clipPath>` → `ValueError: unsupported SVG feature: <clipPath rect> attribute 'rx'`. `_ALLOWED_ATTRS["clip-rect"]` is `{x, y, width, height}` (`_pdf.py:202`) and `_collect_defs` stores only those four (`_pdf.py:900-908`), so even a permitted `rx` would silently square the clip. §4.2 says "`<g clip-path="url(#…)">`" without pinning the `<path d=…>` spelling; the canvas precedent does pin it (`_svg.py:5563-5573` via `_rounded_rect_path`). The path spelling converts fine — pin it in the design.

### F9 — seam-clamp off-by-one

§4.2 says "clamp the final band's far edge … `seam = 0.0` for the last band". In the vertical branch (`_svg.py:8393-8397`) `by1 = y + height * (1.0 - lower)`, so the band whose far edge overhangs to `y+h+0.5` is index **0** (the bottom band); index n−1 is flush at `y`. §4.2's own prose ("vertical bottom, horizontal right") contradicts the rule stated one sentence later.

---

### Adjacent, outside this lens but verified

§4.1's padding semantics are backwards. `bar.style.cssText` is `position:absolute;inset:0 auto 0 0` (`js/src/50_chartview.ts:3533`); an absolutely-positioned child's containing block is its ancestor's **padding box**, so `inset:0` places the bar at the padding edge and container `padding` does **not** move it live — only border width does. The design's `bar_inset = box_room` (padding + border, `_chromebox.py:192-201`) and step 6's three-consumer acceptance test ("container padding moves the bar identically in SVG, PNG, and the pyplot reservation") would pin a behavior the browser does not have.

Also checked and clean: chrome ordering (colorbar is last in both writers — `_svg.py:5586-5612`, `_raster.py:1817-1827`; the raster clip is reset to full canvas at `_raster.py:1285`), so the container-first claim holds; and z-order vs. the legend matches (`colorbar` box carries `z-index:4` at `js/src/50_chartview.ts:3484`, the legend none, and it is built after — `js/src/50_chartview.ts:2572-2573`).