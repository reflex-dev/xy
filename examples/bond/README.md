# 007 — the gun-barrel intro, as one xy chart

A [Reflex](https://reflex.dev) app built with the `xy[reflex]` integration that
renders the James Bond gun-barrel title sequence: the iris opening out of a
travelling dot, rifling spiralling around a lit barrel interior, a silhouette
walking in and turning to fire, a muzzle flash, and blood running down the
frame.

It is a title sequence made of chart marks — six scatter layers on one fixed
plan — and that is the point. It leans on exactly the machinery a live dashboard
leans on (a compile-validated plan, binary columns on the app's own websocket,
the engine's animation interpolation) under a load where any stutter, remount,
or rescale is *immediately* visible. A dropped frame in a dashboard looks like
nothing. A dropped frame here looks like a broken film.

## Run

```bash
cd examples/bond
uv run reflex run
```

Open the URL Reflex prints (usually <http://localhost:3000>) and press **play**.

`XY_BOND_POINTS` sets the starting point budget (default `90000`); the page also
has a menu for it, up to 400k.

```bash
XY_BOND_POINTS=180000 uv run reflex run
```

The adapter is wired in one line — `plugins=[reflex_xy.XYPlugin()]` in
[`rxconfig.py`](rxconfig.py).

## The claim worth checking

**The server publishes ~12 keyframes a second. The 60 fps motion between them is
the engine's.** `xy.animation(match="index", update="interpolate")` tweens every
point's position and color from the previous payload to the new one, so sixty
frames a second of geometry never crosses the wire — twelve do, and the GPU
draws the rest.

That is sound rather than a smear because `scene.py` keeps **row identity
stable**: row `i` is the same rifling sample, the same knee point, in every frame
of the sequence. A straight line between two keyframes is therefore the *correct*
in-between — a groove point sweeps its own arc, a knee point tracks the knee.
The file is split to make that explicit:

- `SceneSpec` is the **identity layer**, built once. It fixes which point is
  which: the `(groove, radial, across)` grid of the rifling, the unit-disc wash
  samples, the local `(along, across)` coordinates filling each limb, the
  muzzle-flash directions, the blood fingers.
- `frame_columns(t)` is the **motion layer**. It maps that fixed identity
  through the frame's barrel geometry and skeleton pose, and returns constant
  length columns.

Every control on the page is a knob on the claim:

| Control | What it shows |
| --- | --- |
| **publish rate → 6 Hz** | Motion stays continuous; the tween duration is matched to the period, so it stretches to fill the wider gap. |
| **engine interpolation → flip-book** | Same feed, now visibly stepped. That gap is what the engine adds. |
| **scrub while paused** | The scene is a pure function of the clock, so any instant renders on demand. |
| **points → 400k** | The plan, the transport, and the tween are unchanged; only the column lengths grow. |
| **RATE readout** | Achieved rate against the requested ceiling. The browser sets the pace, so this is what the pipeline settled on — the page never claims a rate it is not hitting. |

## How it is wired

| Piece | What it does |
| --- | --- |
| [`scene.py`](xy_bond_intro/scene.py) | The geometry. Pure numpy — imports neither `xy` nor `reflex`, so it is unit-testable and reusable as-is. |
| [`charts.py`](xy_bond_intro/charts.py) | The plan: `gun_barrel_marks()` returns the mark and chrome nodes. Framework-neutral `xy` only. |
| [`xy_bond_intro.py`](xy_bond_intro/xy_bond_intro.py) | The app: a clock in state, one `@reflex_xy.data` var, and the page. |

One `@reflex_xy.data` var (`Intro.scene`) supplies all eighteen columns; Reflex
state holds only a tiny handle. The ~90k f32 coordinates per keyframe ride the
app's own websocket as raw binary on the XY namespace — no JSON numbers, no
base64 (dossier §29). The var's `SceneCols` return annotation is the
compile-time schema channel (design fact R7): every column name the marks
reference is checked at `reflex run`, without executing a frame of geometry.

`gun_barrel_marks()` feeds both tiers. The app passes the nodes to
`reflex_xy.chart(..., data=Intro.scene)`; `gun_barrel_chart(data=...)` wraps the
same nodes into a standalone `xy.Chart` so a single frame renders through
`to_png` / `to_html` with no server at all — which is how the artwork is
previewed and how `tests/test_example_apps.py` pixel-checks it.

## Notes from building it

Three things the scene had to work around, all of them recorded in the source:

- **Every mark is a scatter.** A closed circle is not a function of x, so a
  `line` mark spanning each pixel column's min/max paints a filled disc instead
  of a ring. The barrel walls are dense point rings instead — which is also the
  form the position interpolator understands (`scatter` and `line` are the
  interpolating kinds, and only one of them can draw a circle).
- **The stage carries the world's aspect ratio.** There is no engine-level
  "equal aspect" lock on the composition API, so the container's `aspect_ratio`
  plus a `padding=0` plot rect are what keep the barrel round rather than
  elliptical.
- **The browser paces publishing, not a timer.** This was the single biggest
  correctness fix. A free-running timer publishes at whatever rate the *server*
  can manage, which is not the rate the browser can decode, upload and draw —
  and the difference accumulates as a backlog. Measured here on a software
  rasteriser, the server held 10 Hz while the page fell to 0.30× real time with
  every individual frame still looking perfect, which is a confusing way to
  fail. `on_animation_end` publishing the next keyframe caps the work in flight
  at one: the same box went to 0.97× real time at ~3.5 Hz, self-tuned, with no
  queue. The requested rate became a ceiling rather than a metronome, and
  `play`'s loop stayed on only as a watchdog for when no animation ends
  (interpolation off, reduced motion, a hidden tab).
- **The clock follows the wall, not the tick count.** The other half of the same
  problem: with an accumulating clock, publishing slower than requested plays
  the sequence in slow motion — the one failure a title sequence cannot hide.
  Anchored to real time it publishes fewer, wider-spaced keyframes at the
  correct speed instead, and the interpolation covers the gaps.
- **The tween duration is part of the plan, so each rate is its own plan.** A
  duration fixed at one value finishes early and then holds whenever keyframes
  arrive further apart — the exact stutter the interpolation exists to remove.
  `rx.match` over the rate mounts the matching plan; every branch is compiled
  and validated at `reflex run` and all of them bind the same data var.
- **Things that must be invisible are parked, not deleted.** Row counts are
  constant, so the waiting blood sits above the clip rect and the unfired
  muzzle sparks sit at zero radius on the muzzle — which also means the tween
  that reveals them *is* the blood running down and the flash blooming out.
  Both ramps start at pure black so a parked row cannot leave a dot on the
  frame.
