# Declarative animation and data transitions

Status: **shipped** for the browser renderer, notebook widget, standalone HTML,
and Reflex full-payload refreshes. Static SVG/native raster output remains
motion-free by definition.

## 1. Public grammar

Animation is a normal chart child. The last chart-level `Animation` child is
the default policy; a mark-level `animation=` value overrides it. `False`
disables that mark without disabling its siblings.

```python
xy.chart(
    xy.scatter("x", "y", key="id"),
    xy.line("x", "trend", animation=xy.animation(duration=180)),
    xy.animation(
        enabled="auto",
        delay=0,
        duration=400,
        easing="ease-out",
        match="key",
        enter="auto",
        update="interpolate",
    ),
    data=data,
)
```

`xy.animation()` validates and serializes these fields:

| Field | Values / meaning |
| --- | --- |
| `enabled` | `False`, `True`, or `"auto"`; auto honors reduced motion, explicit true is an opt-in override |
| `delay`, `duration` | finite non-negative milliseconds |
| `easing` | `linear`, `ease`, `ease-in`, `ease-out`, `ease-in-out`, a cubic Bézier `(x1,y1,x2,y2)`, or `xy.spring(...)` |
| `match` | `index`, `append`, or `key` |
| `enter` | `auto`, `none`, `scale`, `grow`, or `reveal` |
| `update` | `none` or `interpolate` |
| `interpolate` | an ordered subset of `position`, `size`, `color`, `domain` |
| `on_start`, `on_end` | Python-only lifecycle callbacks for live hosts; never serialized |

Default entrances are semantic: line, area, and error-band paths reveal;
bars/columns grow from their baseline; scatter scales from zero; error bars
grow from their centers.
Updates interpolate position on direct scatter and unsmoothed line geometry,
interpolate the domain/view, and snap unsupported layouts to the new
representation without opacity animation. This avoids a mark-specific CPU
frame loop and never cross-fades between old and new data.

A positional update draws the new trace once at its interpolated position and
suppresses the retained old trace. Partial line/scatter matches interpolate
the retained points; added points appear at their target position and removed
points are dropped. Layouts that cannot share positional buffers record a
`snap:*` diagnostic and switch without an opacity fade.

## 2. Stable identity

`key=` is accepted by line, area, bar, column, scatter, error-band, and
errorbar marks. It may be an array or a column name resolved through `data=`.
`match="key"` requires a key on every effectively keyed mark.

Keys are canonicalized type-sensitively and hashed once in Python to a stable
64-bit identity, shipped as two binary `u32` columns. Strings, finite numbers,
booleans, bytes, dates, datetimes, and NumPy equivalents are supported.
Missing, unsupported, wrong-length, or duplicate values fail during figure
construction. Line-like keys follow the same stable geometry sort as their
coordinates. Errorbar point keys are role-qualified after expansion so the
main segment and caps remain unique and stable.

The browser builds a bounded key→old-index map. `append` instead matches the
old/new x identity and `index` pairs equal positions. Above
`MAX_ANIMATION_MATCH_ROWS` (200,000), or when an aggregate/decimated
representation has no one-row-per-mark identity, the transition records an
`animation_fallback` and snaps to the new screen-bounded representation. It
never builds an unbounded browser map to preserve a cosmetic effect.
Python-side key-count mismatches record `index:key-count-mismatch`. Runtime
fallbacks such as missing key buffers, append limits, and partial layouts are
written back to the mounted trace spec and exposed on
`data-xy-animation-fallback` for diagnostics; fallback is never silent.

## 3. Runtime state machine

There is one `requestAnimationFrame` controller per chart. A transition retains
at most the current endpoint plus one previous GPU trace set. Each mark has its
own delay, duration, easing, and phase record, but all records advance from the
same monotonic chart clock. Python is not called per frame.

Full payload refreshes call `ChartView.updatePayload(spec, buffers)`:

1. Decode/build the next screen representation.
2. Match it to the currently displayed trace state.
3. Retain the previous GPU set and optional start-position buffers.
4. Interpolate the view/domain and draw previous then next.
5. Free previous/scratch resources when the longest record completes.

Rapid updates are latest-wins. The active request is cancelled, emits
`animation_end(cancelled=True)`, and the next transition samples the currently
displayed interpolated coordinates—not the stale prior endpoint. The older
retained set is freed before the new endpoint is built, preserving the
two-scene bound.

Notebook `append` pushes and Reflex state rebuilds use this same controller
when an animation policy is present. Append keeps its existing follow policy:
home refits, a live-edge window slides, and a user inspecting history stays
put. Without animation configuration the optimized affected-trace append path
remains unchanged.

## 4. Interaction and accessibility

The visible next scene remains canonical for row IDs, selection masks, and
callbacks throughout a data transition. The GPU pick pass uses the same
previous-position buffers and progress uniform as visible scatter geometry, so
hover follows moving points instead of being disabled. View-animation and LOD
handoff frames still suppress picking because their resident row space or
screen mapping is temporarily changing. Keyboard traversal follows the current
canonical scene during data motion and waits only for those view/LOD handoffs.

`animation_start` and `animation_end` are DOM/Reflex/notebook lifecycle events.
DOM and Reflex payloads include `phase` (`enter` or `update`) and the current
view; the notebook comm sends the phase only. Interrupted transitions add
`cancelled: true` to the end event. Standalone HTML dispatches local DOM events
but has no Python callback transport.

With `enabled="auto"`, `prefers-reduced-motion: reduce` resolves motion off and
renders the final state immediately. `enabled=True` is an explicit application
choice and overrides that preference. No timer or old GPU scene is retained
when motion resolves off.

## 5. LOD, density, and boundedness

Declarative data motion composes with the existing LOD transition laws in
`lod-architecture.md`: stale covering representations remain until a finer
one arrives, tier changes blend, normalization eases, and stale replies
die. Density grids and decimated paths snap between data-animation endpoints;
their independent LOD handoffs may still blend screen-bounded representations.
They never materialize all canonical rows for key matching.

Direct keyed transition overhead is two `u32` columns (8 bytes per shipped
mark), one bounded JavaScript map during matching, and—only for positional
scatter/line interpolation—two temporary f32 start buffers. The normal
non-animated payload and draw path carries none of these allocations.

## 6. Export determinism

SVG and native raster exports always render the final state and do not encode
motion. Browser PNG/JPEG/WebP/PDF export freezes animation progress at `1.0`
before capture. Standalone HTML remains live by default; tests and screenshot
tools may call `to_html(animation_progress=0.0..1.0)` to freeze an entrance at
an exact deterministic progress without starting a frame loop.

## 7. Verification and performance gates

- `tests/test_animation.py` owns validation, serialization, identity, wire,
  sorting, errorbar expansion, and deterministic-export contracts.
- `scripts/animation_smoke.py` exercises pixel-checked, ghost-free keyed interpolation,
  explicit partial-match fallback, GPU scratch buffers, rapid replacement,
  bounded lifetime, lifecycle balance (including destroy), and reduced motion
  in headless Chrome.
- `benchmarks/test_codspeed_animation.py` attributes key encoding and animated
  payload build overhead separately from the plain payload path.
- Browser frame/allocation measurements belong to the real-Chrome benchmark
  lane, not CodSpeed simulation; the animation smoke asserts the hard
  previous+next allocation bound.
