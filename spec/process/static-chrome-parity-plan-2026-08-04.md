# Static-Chrome Parity: Unified Implementation Plan (SVG + raster writers)

## 0. Family order and rationale

Primary key: how much geometry/measurement machinery the two writers already share (more shared = earlier, because the family needs only recording points and emitters, not new layout code). Secondary key: blast radius of the change.

| Phase | Family | Shared machinery today | Dominant risk |
|---|---|---|---|
| P0 | Cross-cutting prerequisites | — | PDF whitelist is a live-bug fix, must land first |
| P1 | root / title / chrome / canvas | `layout()` shared (`_svg.py:2574-2681`, imported `_raster.py:71`); root/chrome/canvas boxes derivable with zero new measurement | fast_png white-init trap; 3-way background precedence |
| P2 | axis chrome (axis_band, axis_line, tick_mark, tick_label, axis_title) | ALL geometry helpers imported by raster (`_raster.py:38-80`); only emission loops duplicated | layout-room coupling; per-instance volume; rotated-box PDF lowering |
| P3 | annotation chrome (annotation_label, annotation_layer, labels; badge/badge_item excluded) | placement/baseline/radius/text-width helpers imported (`_raster.py:28-83`); full box code already exists per writer (`_svg_text_box` / `_emit_text_box`) — the template the shared primitive is extracted from | two-vocabulary collision; labels-container stacking (verified conflict, flag D) |
| P4 | legend (legend, legend_title, legend_item, legend_swatch, legend_label) | `_legend_layout` shared (`_raster.py:54`) but must be widened; frame box already drawn in both writers | em-residue contract retirement; any box-size change moves legends everywhere (pyplot `_axes.py:8472-8486`, `_legendfit.py:74-79`) |
| P5 | colorbar (all 7 slots) | LEAST shared: bar geometry duplicated verbatim (`_svg.py:6811-6838` vs `_raster.py:3292-3312`), container geometry exists nowhere in Python, deliberate off-by-N placement divergences | must build new shared layout before any box work; default-border and extension-existence decisions |

Legend is deliberately after annotation despite good sharing: it is the only family whose change moves layout in three downstream consumers and retires a pinned residue contract (`declared.py:18-26`, `tests/test_declared_snapshot.py`). Colorbar is last because it is the only family where consolidation (new shared machinery) is a prerequisite to parity work.

---

## 1. The shared primitives

### 1.1 Shared chrome-layout record (`ChromeBox`)

One dataclass/dict shape, produced once per slot instance by the family's layout resolver, consumed by (a) the SVG box emitter, (b) the raster box rasterizer, (c) `SnapshotBuilder.add(geometry=...)` (`styling/resolved.py:199-214, 306-334` — the `SlotInstance.geometry` field that `declared.py:97` currently leaves `None` on every declaration, all four surveys agree it is dead weight today):

```
ChromeBox:
  slot: str
  qualifiers: tuple            # (axis_id, side, major|minor, tick index, row, col) — SlotInstance.qualifiers carrier
  x, y, w, h: float            # CSS px, pre-scale — the SlotInstance.geometry 4-float
  angle: float; cx, cy: float  # rotation pose (axis y-title, vertical colorbar title); 0 for most slots
  fill: RGBA | None            # resolved solid paint; gradients recorded separately
  fill_opacity: float
  border: (RGBA, width, dash_pattern | None) | None   # border-style lowered to dasharray; dotted/double = recorded approximation (§28)
  radius: float                # single symmetric rx, clamped ≤ min(w,h)/2 (PDF accepts rx only, never ry — all four surveys, probe-verified)
  shadow: (dx, dy, RGBA) | None  # offset-rect approximation; blur/spread recorded unrepresentable (no blur primitive in raster opcodes _raster.py:85-106, no <filter> in _pdf.py:1236-1253)
  padding: (t, r, b, l)        # consumed by layout/room functions, NOT by the emitters
  clip: none | rect | rounded  # rounded = SVG/PDF path clip only; raster partial until new opcode
```

Value source: the resolved per-slot declaration via `resolve_declared` (`styling/declared.py:56-105`), read at `slot_styles` (`_svg.py:1380-1396`; call sites `_svg.py:3924`, `_raster.py:1315`). Shorthand expansion (`padding`, `row-gap`, `border`) happens in `resolve_declared` (`declared.py:89-99`) because schema v1 carries only longhands (`resolved.py:77-89`). Px only — em/relative values stay `writer_domain` (`resolved.py:119-133`); the legend em-multiplier geometry must not be copied into any new family (family-1 and family-2 surveys agree).

### 1.2 SVG rect emitter — one function

`_slot_box_svg(box: ChromeBox) -> str` in `_svg.py`, placed next to `_rounded_rect_path` (`_svg.py:1795-1817`). Emits, in order: shadow rect, background rect (`x y width height rx fill fill-opacity stroke stroke-width stroke-opacity stroke-dasharray`), nothing else. Rules baked in:

- every attribute exactly once (the duplicate-attr XML trap, `_svg.py:1494-1498` — parser keeps first value silently);
- always an explicit `fill` (rects inside the labels `<g fill=default_text>` at `_svg.py:4590` inherit otherwise);
- all numbers through `_num` (`_svg.py:1644`);
- asymmetric per-corner radii lowered to a `<path>` via `_rounded_rect_path`, never `ry` (PDF rejects `ry`, probe-verified);
- rotated boxes: see flag E below — one lowering must be pinned repo-wide;
- stays inside the PDF closed subset: `<rect>` accepts x/y/width/height/rx + fill/fill-opacity/opacity/stroke/stroke-width/stroke-opacity/stroke-dasharray/stroke-linecap/stroke-linejoin (`_pdf.py:174-186, 198`, rx lowered `386-402`), rejects transform/filter/ry.

### 1.3 Raster box rasterizer — one function

`_emit_slot_box(cmd, box: ChromeBox)` in `_raster.py`, placed next to `_round_rect_pts` (`_raster.py:744-772`). Emits: shadow `cmd.fill(_round_rect_pts(offset...), rgba)`, background `cmd.fill(_round_rect_pts(...))`, border `cmd.stroke(pts, width, rgba, closed=True, dash=...)`. Rules:

- slot opacity folded into every RGBA (no group compositing exists in the display list `_raster.py:193-700`); double-blend on overlapping translucent children recorded per §28;
- rotated boxes: corners pre-rotated in Python (cmd.fill takes any quad; no transform primitive);
- rounded CLIPPING is not representable (cmd.clip is rect-only, `_raster.py:216-221`; `_POLAR_CLIP` `223-236`) — record unrepresentable until a new opcode lands in `src/raster.rs` + ABI bump in `src/lib.rs` AND `python/xy/_native.py` together.

### 1.4 Refactor targets that fold onto the pair

The three existing duplicated box sites, converted per phase (not up front): legend frame (`_svg.py:6597-6623` / `_raster.py:3088-3111`, P4), annotation text box (`_svg.py:5007-5058` / `_raster.py:1875-1920`, P3), background composition (`_svg.py:4554-4571` / `_raster.py:951-986`, P1 — preserving the deliberate raster white-plot-fill fallback at `_raster.py:978-979`).

---

## 2. Phase 0 — cross-cutting prerequisites (blocking)

**0.1 PDF text-subset extension (live-bug fix).** All four surveys independently probe-verified: `_pdf._ALLOWED_ATTRS['text']` (`_pdf.py:204-206`) rejects `font-style`, `font-family`, `letter-spacing`, `opacity`, so `to_image(format='pdf')` RAISES today for an italic title, a letter-spaced legend_label, an italic tick_label/colorbar_tick, and mathtext annotations (nested tspan, `_pdf.py:1099-1100`). The `SLOT_TEXT_PROPS` docstring claim that PDF honors the vector subset (`_svg.py:1331-1332`) is false; the capability-matrix tick_label PDF note is also wrong.
Edits: `_ALLOWED_ATTRS['text']` + `_render_text` (`_pdf.py:1062-1141`); Helvetica-Oblique/BoldOblique into `_font()` (`_pdf.py:681-691`, today regular/bold only, bold cutoff weight>=600 at `1065`); letter-spacing via `Tc`; text opacity multiplied into `ca` ExtGState; nested-tspan mathtext either supported or explicitly fenced. `font-family` beyond base-14 is policy-refused, not guessed.
Acceptance: `styles={'title':{'font_style':'italic'}}`, `{'legend_label':{'letter_spacing':'2px'}}`, `{'tick_label':{'font_style':'italic'}}`, `{'colorbar_tick':{'font_style':'italic'}}` each round-trip `to_svg -> svg_to_pdf` without ValueError; a mathtext annotation exports to PDF (or raises a documented, tested policy error). Closed-subset contract note (`_pdf.py:7-10, 63-64`) updated in the same change.

**0.2 Raster emphasis-routing gap fix (contract violation).** `SLOT_RASTER_PROPS` (`_svg.py:1350-1356`) claims font-weight/font-style are honored, but only `title` (`_raster.py:1431-1436`) and `axis_title` (`1497-1505`) route through `_native_font_emphasis` (`_raster.py:1645-1655`). Wire it into: legend_title (`_raster.py:3113-3120`), legend_label (`3174-3181`), tick_label (`1388-1397`), colorbar_tick (`3447-3455`, `3486-3494`), colorbar_title (`3456-3464`, `3503-3511`). `cmd.text` already supports italic/bold (`_raster.py:662-700`).
Acceptance per slot: `font_weight: 700` selects the bold atlas face, `font_style: italic` the italic face, in raster PNG; the pinned vector-minus-raster property set `{font-family, letter-spacing, opacity}` in `tests/test_export_style_survival.py:209-220` and `capabilities.py:267-274` updated in the same commit.

**0.3 Shared primitives** (§1 above): `ChromeBox` lowering + `_slot_box_svg` + `_emit_slot_box` + shorthand expansion in `resolve_declared` (`declared.py:89-99`). Resolve the legend shadow constants while extracting, don't copy them (flag A/I below).
Acceptance: unit tests on the lowering (border shorthand, per-side padding, radius clamp, shadow parse); golden SVG/PNG for one synthetic box exercising every field; PDF round-trip of the emitted rect.

**0.4 Registry/preflight plumbing pattern.** Every slot added to writers must, in the same commit: join `STATIC_STYLED_SLOTS` (`_svg.py:1367-1377`); update `capabilities.py` (`264-296`, `332-345`) and `tests/test_capability_registry.py`; update preflight honored-props (`preflight.py:185-203, 197, 253-262`). Add a shared `SLOT_BOX_PROPS` constant (pattern: `LEGEND_BOX_PROPS`, `_svg.py:1416-1429`) so writers/registry/preflight cannot drift.

**0.5 Standing gate:** unstyled output stays byte-identical (`tests/test_export_style_survival.py:140-146`). Every phase's emission is strictly conditional on a declaration being present. This gate is the acceptance floor for every edit below.

---

## 3. Phase 1 — root / title / chrome / canvas

Geometry is free: root = chrome = (0,0,width,height); canvas = plot rect from `layout()` (`_svg.py:2665-2678`). Only the title needs a new helper.

**Edits, in order:**

1. **`title_box(entry, plot, wrap_width) -> ChromeBox`** next to `_title_metrics` (`_svg.py:2550-2558`), replacing the anchor math duplicated at `_svg.py:4245-4258` / `_raster.py:1465-1479` (entry titles) and `_svg.py:4226-4227` / `_raster.py:1443-1453` (legacy), mirrored a third time in JS (`50_chartview.ts:940-963`). Hoist BEFORE drawing boxes — the survey is explicit that adding box extents in each copy independently will drift. Box width = measured `TextBlock` width + padding (`_textblock.py:31-43`), NOT `title_wrap_width` (browser box is the shrink-to-fit div, `50_chartview.ts:2455-2468`).
2. **`_title_room` grows** for padding/border (`_svg.py:2561-2571`) with the JS mirror (`50_chartview.ts:709-720`) in the same change, or native and browser disagree on `plot.y`.
3. **Title box emission**: SVG rects appended to `chrome` immediately before the `<text>` at `_svg.py:4230` and `4265`; raster `_emit_slot_box` before `_emit_text_block` at `_raster.py:1443-1453` and `1476-1488` (chrome phase already unclipped, clip reset at `_raster.py:1108`). Populate `SlotInstance.geometry` at `declared.py:97`.
4. **root slot**: SVG in the backgrounds assembly `_svg.py:4554-4571` (stays first-painted content per browser CSS border-below-descendants; the alternative post-chrome anchor at `4593` rejected); raster extends `_raster.py:949-986` (fill, then border stroke, before plot fill at `982-986`). Fix the fast_png skip condition (`_raster.py:956-965`) to account for border-radius breaking full-coverage. Define the three-source precedence ONCE: `styles.root.background` vs `dom.style['background']` vs `apply_export_background` override (`_svg.py:1513-1531` — root must join the override contract or `background='transparent'` exports keep a painted root box). Registry/preflight flip (`capabilities.py:289-296`, `preflight.py:253-254`).
5. **chrome slot** (recommend the survey's own hedge: background/opacity only, rest recorded unrepresentable §28): SVG rect between `backgrounds` and the grid `<g>` (`_svg.py:4576-4584`, seam at 4581/4582); raster after plot fill `982-986`, BEFORE `cmd.clip` at `_raster.py:1008`. Record the title-stacking divergence (DOM appends chrome canvas after title divs, `50_chartview.ts:2455-2474`) in `KNOWN_RENDERER_DIVERGENCES` (`capabilities.py:249-259`).
6. **canvas slot**: background at the ABOVE-grid seam — SVG after grid `</g>` (`4584`) before the clipped marks `<g>` (`4585`); raster `_raster.py:1056-1063` (after grid loops, before traces, inside the plot clip). Do NOT hook the existing `--chart-bg` anchor (below-grid): the paint-order divergence is the family's central trap. Border composes with spines (`_svg.py:4392-4407` / `_raster.py:1158-1183`). Radius = a THIRD clipPath id in the SVG defs (`_svg.py:3882-3906`) — never mutate `clip_id`/`marks_clip_id` (polar legends vanish, comment `3883-3893`); raster radius recorded unrepresentable until the new opcode. Opacity = group opacity on the marks `<g>` (PDF-legal on `<g>`, `_pdf.py:197`); unrepresentable per-command in raster. `apply_export_background` must also override a canvas-slot background.

**Per-slot acceptance:**
- root: styled bg+border+radius renders in both writers; radius corners show underlay (not native-white) on transparent fast_png export; `background='transparent'` kills the root paint; root shadow/outset border recorded unrepresentable (outside viewBox `_svg.py:4578-4579` / canvas `_raster.py:1582`), never grows the canvas; unstyled bytes identical; PDF round-trip.
- title: box under text above all other chrome; `title_room` grows so the box clears `top_axis_room`; box width = block width + padding; entry-style-over-slot merge follows `_title_metrics` (`_svg.py:2556`); per-entry background divergence vs the browser's per-entry allowlist (`50_chartview.ts:2462-2466`) recorded; italic-title PDF passes (P0.1).
- chrome: rgba background composites above root bg, below grid, in both writers; divergence entry present; unstyled bytes identical.
- canvas: styled background HIDES the grid (browser parity); rounded clip works in SVG+PDF (path clip, `_pdf.py:836-875`), preflight reports raster radius partial; canvas opacity gated strictly on declaration (large PDF byte diff otherwise); transparent-export override honored.

---

## 4. Phase 2 — axis chrome

**Edits, in order:**

1. **Extract shared `tick_span`** — literal near-duplicate (`_svg.py:4433-4440` returns (in,out,width) vs `_raster.py:1205-1212` returns (in,out)). The survey calls it the obvious first extraction; unify on the 3-tuple.
2. **Per-instance ChromeBox production** with qualifiers (axis_id, major|minor, side, tick index) filling `SlotInstance.qualifiers` (`resolved.py:209-211`, empty today).
3. **axis_line**: read the slot at the existing `slot_styles` sites (`_svg.py:3924` / `_raster.py:1315`); convert `<line>`/`cmd.stroke` to box emission at `_svg.py:4392-4431` (paint-order slot `4589`) and `_raster.py:1158-1203`, GATED on box styling present (browser insets right/bottom spines — `50_chartview.ts:7008, 7028` — writers center on the edge; matching the browser unstyled would break the byte pin). Polar keeps stroke semantics (browser has the same limit, `50_chartview.ts:6991-6993` — verified: "spines are background-coloured DIVs and cannot express a circle"); recorded. Axis-level `axis_color` stays the narrower selector.
4. **tick_mark**: box conversion in the loops `_svg.py:4442-4547` / `_raster.py:1214-1313`; intern the attribute string once per declaration (`resolved.py:14-19` design); explicit rule: no shadow on zero-area boxes (`tick_length` defaults 0, `_svg.py:4434`); do not invent a length — preflight note instead. Geometry parity here is exact (browser centers rect at x−width/2, same pixels as centered stroke).
5. **tick_label boxes**: SVG rect immediately before its `<text>` in the labels list at `_svg.py:4060-4065` (explicit fill mandatory — group fill at `4590`); inputs already in scope at `4025-4059`; polar hook `_svg.py:3811-3868`; raster box before `_emit_text_block` at `_raster.py:1388-1397`, polar `874-923`. Room functions learn the box model in the SAME change: `_y_tick_label_room` (`_svg.py:2227-2252`), `_x_tick_label_room` (`2338-2396`) — both measure at axis font size only today while emitters draw at slot size (`4004` / `1339`), a pre-existing overflow the box work must not worsen. Letter-spacing folded into width estimation or qualified (§28).
6. **axis_title boxes**: compute the real box in `_axis_label_geometry` (`_svg.py:3251-3320`, already shared via `_raster.py:57`); SVG emission into chrome before the `<text>` at `_svg.py:4296-4304`; raster at `_raster.py:1506-1521` with Python-side corner rotation. Rooms `_x_axis_title_room` (`2305-2337`) / `_y_title_baseline` (`2190-2226`) learn padding/border. Fix the `4289-4295` branch that drops slot letter-spacing/opacity wholesale when the axis authors family/style — per-property merge, with precedence documented (note the existing knot: paint is narrower-wins but font-size runs the other way, `_svg.py:4296` / `_raster.py:1511`).
7. **axis_band** (last — pure policy): existence decision first (browser creates it only when navigable, `57_viewstate.ts:295, 272-279`; see flag F), z-order decision pinned (band z-index:2 paints ABOVE labels live, `57_viewstate.ts:299` — copy it or record "never obscure text"), OUT=24/IN=6 mirrored via generated constant or spec pin (`57_viewstate.ts:314-315`), polar: no bands, recorded.

**Per-slot acceptance:**
- axis_line: box renders only when box props declared; unstyled bytes identical; edge-inset choice pinned by golden; polar divergence recorded; `axis_color`-narrower test still green.
- tick_mark: styled marks with `tick_length>0` render boxes; `tick_length=0` renders nothing (+preflight note test); dense-axis (200 ticks) SVG size and display-list length within budget; qualifiers land in snapshot.
- tick_label: padded boxes don't clip at canvas edge (room growth test both orientations); rotated label boxes rotate with text and pass PDF (flag E lowering); the 15-vs-16px SVG/raster bottom-gap offset (`_raster.py:1347-1349`) documented as pre-existing in the parity test tolerance; interned attrs (one declaration string, N instances).
- axis_title: rotated y-title box passes PDF; slot letter-spacing survives axis `label_font_family` being authored; precedence table test; DejaVu-measured box vs authored-family text misfit qualified (§28).

---

## 5. Phase 3 — annotation chrome

**Edits, in order:**

1. **Wire the dead slot channel**: thread `slots` (in scope since `_svg.py:3924`) into `_annotation_svg`'s signature at `_svg.py:4357-4361`; raster: hoist `slot_styles(spec)` from `_raster.py:1315` above both `_emit_annotations` calls (`1105`, `1111`).
2. **Merge point**: fold the slot declaration UNDER `ann['style']` at `_svg.py:4867-4875` and `_raster.py:1786-1803` (narrower-wins, patterns: tick_label `_svg.py:3994-4005`, `legend_options_with_slot` `1432-1460`). Define the two-vocabulary translation ONCE (per-annotation shorthand `border`/`padding`/`border_radius`/`font_size` vs snapshot kebab longhands, `resolved.py:49-100`).
3. **Converge the box pair onto the shared primitive**: `_svg_text_box` (`_svg.py:5007-5058`) and `_emit_text_box` (`_raster.py:1875-1920`) become adapters over `ChromeBox`; in the process fix per-side padding (both parsers read tokens [0]/[1] only — 4-value CSS silently misreads, `_svg.py:5021-5030` / `_raster.py:1890-1899`), add border-style→dasharray, box opacity, shadow. Text attrs at `_svg.py:4952-4956` must MERGE with `_svg_font_attrs` (`4961-4970`) and the always-emitted font-size (`4953`) — each attribute exactly once (the PR #325 lesson).
4. **annotation_layer**: wrap annotation marks in their own `<g>` at `_svg.py:4357-4361` (contiguous tail of marks — pure wrap) for group opacity (PDF-legal); layer background geometry decision pinned BEFORE implementation (full-bleed vs plot-clipped — the browser canvas is inset:0 but SVG's clipped shapes live inside the marks clip group); raster: fold layer alpha per-primitive at `_raster.py:1696`, temporary full-canvas clip pattern from `1731-1733`/`1781-1784`; double-blend divergence recorded (§28). Do not conflate slot opacity with the per-annotation shape-alpha rule (`_svg.py:4897-4901`, `51_annotations.ts:860-875`).
5. **labels container**: slot color/opacity ride the `<g>` at `_svg.py:4590` (PDF `<g>` accepts fill/fill-opacity/opacity, NOT font-* — probe-verified); container background rect at the `4589`/`4590` seam SUBJECT TO flag D below; typography materialized per-`<text>` at each emission site with cascade labels-slot < specific slot < axis/annotation style; raster `default_text` takeover at `_raster.py:1001` / `1315-1320` with byte-exact fallback.
6. **badge / badge_item**: NO writer work — view-gated by the applicability partition (`capabilities.py:327-328`, `299-329`); any change is a spec decision first. Only requirement: keep the shared box primitive annotation-agnostic, since badge_item's default rendering is a full box model and would need it if ever exported.

**Per-slot acceptance:**
- annotation_label: `styles={'annotation_label': {...}}` now leaves a trace (today verified zero-trace); slot-under-ann-style precedence tested both directions; 4-value padding correct; border-style dashed renders dasharray in SVG and dash in raster; mathtext-annotation PDF passes or raises the documented fence (P0.1); em-valued slot declarations either honored via the merged view or explicitly refused — never silently dropped by a snapshot-only path.
- annotation_layer: group opacity in SVG/PDF; raster per-primitive fold with an overlapping-shapes test documenting the double-blend delta; geometry decision golden.
- labels: container color changes every label's default in both writers with byte-exact unstyled fallback; stacking decision from flag D pinned by golden; per-text typography cascade test (labels < tick_label < axis style).
- badge/badge_item: preflight reports view-gated, no writer emission; capability partition test unchanged.

---

## 6. Phase 4 — legend

**Edits, in order:**

1. **`_legend_layout` returns per-slot ChromeBoxes** (frame, title row, item[i], swatch[i], label[i] — formulas in the survey, all terms already in the return dict `_svg.py:6542-6568`); signature widened to accept title_slot/label_slot font sizes + letter-spacing (`6377`; callers `_svg.py:6583`, `_raster.py:3074`, `pyplot/_axes.py:8486`); `_legendfit.legend_footprint` (`74-79`) tracks any size change.
2. **Retire the em residue**: px `padding`/per-side padding, px `row-gap`/`gap`, kebab `font-size` honored via resolved declarations; `declared.py:18-26` and `tests/test_declared_snapshot.py` enumeration updated in the same change; shorthand expansion per P0.3. em spellings keep working through the writer view.
3. **Frame onto the shared primitive** (`_svg.py:6597-6623` / `_raster.py:3088-3111`): honor the authored border-radius VALUE (both writers pin 4 today — probe-verified `border-radius:12px` still emits rx="4"), border-width/style, kebab `border-color` (today camelCase-only, and absent from `LEGEND_BOX_PROPS` `1416-1429` so preflight misreports), parsed box-shadow (offset/color; blur recorded), whole-slot opacity (raster: premultiplied, divergence recorded). Preserve `background=="transparent"` dropping the frame entirely (frameon=False parity, `_svg.py:6597` / `_raster.py:3087-3088`). Resolve — do not copy — the shadow divergences (flags A, I).
4. **legend_title / legend_label**: boxes via the per-row records (SVG hooks: after `6623` for the title row, before the `<text>` at `6690` for labels; raster: `3111`/`3112` and before `3174`); measurement integrity — feed slot font-size and letter-spacing into `_legend_layout`'s char_width/text_widths (`6398-6400`, `6444-6467`) so drawn size == measured size (today an oversized slot title/label escapes the frame); text-align honored using the row-box width.
5. **legend_item / legend_swatch — new slots**: `STATIC_STYLED_SLOTS` + threading through `_legend`/`_emit_legend` signatures (`_svg.py:6571-6580`, `_raster.py:3062-3071`) + read beside `legend_label_slot` (`_svg.py:4313-4314`, `_raster.py:1566-1567`). Row box: SVG inside the item loop after `6642-6644` before the kind branches at `6645`; raster after `3128-3130` before `3131`. Swatch box: before the kind branches (`6645` / `3132`); authored radius replaces the literal `rx="2"` at `6677` (raster patch branch `3152-3162` via `_round_rect_pts`). Precedence: slot overrides win over trace paint (browser `_applySlot` runs after paint vars, `50_chartview.ts:2881`). Swatch clips only if authored (browser keeps overflow visible for oversized markers).

**Per-slot acceptance:**
- legend: `border-radius:12px` → rx=12 both writers (regression vs today's pinned 4); px padding moves the frame identically in render, pyplot reservation, and best-loc scoring (three-consumer test); `background:'transparent'` still drops the frame; kebab `border-color` honored and preflight truthful; whole-slot opacity raster-premultiply divergence documented; unstyled bytes identical; PDF round-trip (frame rects fully in-subset).
- legend_title / legend_label: raster emphasis (P0.2 regression test); box under text over frame; oversized slot font no longer escapes the frame (measurement test); text-align left/right; letter-spacing feeds advances; glyph-marker `<text font-family dominant-baseline>` PDF breakage (`_svg.py:6720-6726`) fenced or fixed — pre-existing.
- legend_item: row background under that row's swatch/label, over frame and title; row padding changes pitch consistently everywhere; O(rows) instances within snapshot budget (`resolved.py:14-19`).
- legend_swatch: slot background/stroke wins over trace color (browser-precedence test); radius honored on patch swatches; dash on swatch border in both writers.

---

## 7. Phase 5 — colorbar

**Edits, in order:**

1. **New shared `_colorbar_layout`** in `_svg.py`, folding: the verbatim-duplicated bar box (`_svg.py:6811-6838` / `_raster.py:3292-3312`), tick/title placement, discrete band fractions (`_svg.py:7040-7057` / `_raster.py:3315-3340`), extension polygons (`6949-6975` / `3385-3411`), line markers (`6976-7002` / `3412-3425`), minor ticks (`6913-6945` / `3432-3446`, `3471-3485`), title pose — AND the container box, which exists nowhere in Python (mirror `50_chartview.ts:3631-3648`; PIN the non-compact form — writers have no container-width signal for the compact mode at `3621, 3649-3687`). Reconcile the deliberate off-by-N divergences (SVG tick baseline +12 vs raster +13, `_svg.py:6906` / `_raster.py:3450`; title +22 vs +26, `6846` / `3459`) — resolve to one number, don't copy. Returns ChromeBoxes for all 7 slots. No em blockers in this family (survey-confirmed).
2. **Split the `or`-fallback into a cascade** at `_svg.py:4352-4353` / `_raster.py:1578-1579`: box props stay on the container, text props (color/font-size, per `20_theme.ts:132`) inherit into title/tick — otherwise a container `background` wrongly paints per-text backgrounds once box props are honored. Widen the call sites (`_svg.py:4345-4355`, `_raster.py:1571-1580`) to pass the whole slots map.
3. **Container box** via the shared primitive: first node of the returned string (`_svg.py:7003-7008`); raster before band fills (`3341-3355`); geometry from `_colorbar_layout` only (a second computation reintroduces the 1px-class divergences).
4. **colorbar_bar**: border/radius/opacity on the rects at `_svg.py:7016-7039`/`7058-7075` and `_raster.py:3341-3355`; rounded discrete bar = `<g clip-path>` in SVG/PDF, raster partial (rect-clip-only); the +0.5px seam overlap (`7065`/`7073`, `3351`/`3355`) must be inset from border/radius edges; the browser's DEFAULT 1px `currentColor` border (`20_theme.ts:133`) vs writers' none is an explicit default-parity decision, never a silent flip (byte pin); background override must not disturb gradient-id dedup (`_colormap_key` `_svg.py:1240-1246`).
5. **colorbar_extension / colorbar_line / colorbar_minor_tick**: paint-level overrides at `_svg.py:6949-6975`/`6976-7002`/`6928-6945` and `_raster.py:3385-3411`/`3412-3425`/`3441-3446`+`3480-3485`. State the resolved-paints precedence rule (payload over/under-color and per-line color/width/dash vs slot declaration) to match the browser (payload sets vars, slot overrides). Extension existence divergence settled first (browser creates them only for line_only, `50_chartview.ts:3479`; writers always). border-style dotted→dash approximation recorded (§28). Map the browser's border-* vocabulary onto stroke attrs consistently for line + minor_tick.
6. **colorbar_tick / colorbar_title boxes** (emphasis already fixed in P0.2): tick pills need text width (`_textblock.measure`/`_estimated_text_width`); per-tick SlotInstances with qualifiers+geometry (`resolved.py:306-334`). Rotated vertical-title box: see flag E — the colorbar survey prescribes pre-rotated `<polygon>`; unify with the axis-family lowering. Three rotation implementations (`50_chartview.ts:3605`, `_svg.py:6842`, `_raster.py:3507`) must consume the one shared pose from `_colorbar_layout`.

**Per-slot acceptance:**
- colorbar: container box renders under bar/ticks/text, over the plot; container background does NOT leak into per-text backgrounds (cascade test); non-compact pin documented; PDF round-trip.
- colorbar_bar: border/radius on continuous and discrete bars; band seams stay inside the border; raster radius reported partial; default-border decision golden; two-colorbar gradient dedup unchanged.
- colorbar_extension: slot fill/stroke override with payload-precedence test; existence-policy golden.
- colorbar_line / colorbar_minor_tick: width/style/color overrides in both writers; dotted approximation recorded and tested.
- colorbar_tick / colorbar_title: emphasis (P0.2); boxes in both writers; rotated title box byte-identical geometry across SVG/PDF/raster (single pose source); metrics-divergent pill widths recorded (§28: AFM vs atlas vs browser font).

---

## 8. Survey disagreements (flagged, not papered over)

Three I verified against the code in this pass; the rest need a look before the affected phase.

- **A. Legend shadow radius (RESOLVED BY CODE — family-2 correct, family-1 wrong).** Family-1 says both writers hard-code radius 4 for the legend shadow+frame. Code: SVG shadow is `rx="4"` unconditional (`_svg.py:6600-6601`), while the raster shadow radius is `4.0 if borderRadius else 0.0` (`_raster.py:3089-3092`) — conditional. The frame is 4-or-0 in both. P4.3 must unify the shadow rule.
- **B. Legend border "hard-coded 1px #cccccc" (RESOLVED BY CODE — family-1 overstates).** Family-1 calls the frame border hard-coded; family-2 says camelCase `borderColor` IS honored with #cccccc default. Code confirms family-2: `_svg.py:6618`, `_raster.py:3108`. Only width (1px) and style (solid) are hard-coded. Additional nuance neither survey states: the SVG frame stroke rides `stroke-opacity=alpha` from the frame-alpha logic (`_svg.py:6622`) and the raster folds the same alpha into the border RGBA (`3108`) — the border dims with the frame; the new lowering must decide whether that coupling survives.
- **C. What the annotation box pair shares (RESOLVED BY CODE — family-1 undercounts).** Family-1: they share "only `_box_corner_radius`". Family-4: `_estimated_text_width` is also shared. Code: `_raster.py:52` imports `_estimated_text_width`. Family-4 correct.
- **D. Labels/baselines stacking (REAL CONFLICT, both surveys partially right — must be resolved before P3.5).** The axis family asserts the writers' order (baselines above marks, below the labels group) "matches the browser" (`50_chartview.ts:6948-6952`). The annotation family asserts the browser keeps spine/rule DIVs INSIDE the labels container so a labels-slot background cannot sit under baselines and above marks without reordering. Code (verified): `rule()` appends spine/tick DIVs to `this.labels` (`50_chartview.ts:6988-6989`). Both claims describe the same DOM: relative z of rules-vs-marks matches, but a labels-container BACKGROUND paints under the rules live and above them in the writers. The axis family's "matches the browser" is true only for slot ink, not for the container box. Decide and record before implementing the labels background.
- **E. Rotated-box PDF lowering (CONFLICTING PRESCRIPTIONS).** Axis family: `<polygon>` (loses radius) OR `<path>` with arcs (keeps it), leaning toward pinning path-with-arcs since rotated y-titles are the common case. Colorbar family: pre-rotated `<polygon>` "so SVG, PDF and raster share one geometry" — no radius. Pick ONE repo-wide lowering in P0.3 (recommendation: pre-rotated polygon when radius==0, path-with-arcs when radius>0) and make both families consume it.
- **F. axis_band applicability policy (CROSS-FAMILY PRINCIPLE CONFLICT).** The axis family plans full box support for axis_band and notes `capability-matrix.md:116` claims it applicable in clean static. The annotation family's badge rationale (`capabilities.py:299-329`: clean static exports contain no state-gated chrome) argues the opposite for interaction-gated chrome — and the band exists live ONLY when the axis is navigable (`57_viewstate.ts:295, 272-279`), i.e., it is interaction-gated. Either the band is deemed structural chrome (draw it, full support) or interaction chrome (view-gate it like badge). Spec decision before P2.7; the surveys point different directions.
- **G. chrome-slot scope (SELF-HEDGED, needs a call).** Family-1 lists full box-model gaps for `chrome`, then recommends background/opacity-only with the rest unrepresentable. Its proposed static anchor (below grid) matches live compositing per its own analysis but contradicts DOM order for titles (chrome canvas appended after title divs). The plan adopts the hedge (P1.5) — that adoption is a decision, not a survey consensus.
- **H. Shadow alpha constants (framing conflict).** Family-1 presents SVG 0.22 / raster 55/255 as one policy ("alpha 0.22/55"); family-2 flags them as a divergence to resolve, not copy (0.22 vs ≈0.2157). The plan follows family-2 (P0.3/P4.3 unify).
- **I. Raster `_raster.py` import-line citations vary across surveys** (25-45, 28-83, 38-80, 52, 54, 65, 71) — not contradictory (different subsets of the same import block), no action.
- **J. Root geometry producers (recorded risk, not a survey conflict, but only family-1 raises it):** browser capture reports root geometry including host padding; native snapshot uses spec width/height (`declared.py:100-103`). Two producers must agree or capture-diff tooling flags every chart — needs a stated normalization rule when snapshot geometry starts being populated (P1.3+).

---

## 9. Cross-phase invariants (every edit above is subject to)

1. Unstyled output byte-identical (`tests/test_export_style_survival.py:140-146`) — all emission strictly declaration-gated.
2. Any new SVG attribute reaching PDF extends `_pdf._ALLOWED_ATTRS` in the same change (closed-subset contract, `_pdf.py:7-10`), or export goes from silently-unstyled to raising.
3. Every attribute emitted exactly once per element (`_svg.py:1494-1498`).
4. `_num` for all SVG numbers; `_Cmd` fixed-point for raster; stable attribute order (PDF determinism, `_pdf.py:35-36`).
5. Radius is single symmetric rx (or path lowering); never `ry`.
6. Box-shadow = deterministic offset-rect; blur/spread recorded unrepresentable (§28).
7. Every approximation or renderer divergence recorded (§28 / `KNOWN_RENDERER_DIVERGENCES`), never silent.
8. `STATIC_STYLED_SLOTS` growth moves `capabilities.py` + `preflight.py` + their tests in the same commit.
9. Raster rounded clipping and group compositing stay recorded-unrepresentable until a `src/raster.rs` opcode lands with the dual ABI bump (`src/lib.rs` + `python/xy/_native.py`).
10. em/relative units: snapshot rejects, writer view carries; no new slot may silently drop them (the legend-residue lesson).