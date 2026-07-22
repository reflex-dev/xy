# Wire protocol — client ↔ Python

Status: **shipped**. This document specifies the message catalog dispatched by
`xy.channel.handle_message` (`python/xy/channel.py`) and consumed by
`js/src/54_kernel.ts`, plus the first-paint buffer layouts and the version
handshake. The transport envelopes that carry these messages are separate:
the anywidget comm (`python/xy/widget.py`), the `/_xy` socket.io namespace
([reflex-integration.md](reflex-integration.md) §2), and the `XYBF` binary
frame (`python/xy/_framing.py`, versioned in §7 below).

The catalog does not vary by transport: where a host sends a given message, it
has the shape specified here, byte for byte. What varies is *which* messages a
host sends — the Reflex wrapper resolves `view_change` in the browser and never
emits it (§2).

## 1. Dispatch contract

`handle_message(fig, content, buffers=None, callbacks=ChannelCallbacks())`
returns either `None` or `(message, buffers)`, where `buffers` is a list of
binary attachments the reply's spec entries index into by position.

- Non-dict `content`, an unknown `type`, a missing required field, or a value
  that fails coercion returns `None`. Client-supplied data never raises;
  exceptions from *user callbacks* do propagate.
- Replies are return values, not sends. Python-side callbacks therefore fire
  before the reply leaves the process.
- The `buffers` argument is accepted and unused: no inbound message carries
  binary payloads today. It exists so the length-prefixed framing path can
  pass attachments through without a signature break.
- `append` is not a request kind — it is a server push (§4).

`ChannelCallbacks` carries seven optional hooks: `on_hover`, `on_click`,
`on_brush`, `on_select`, `on_view_change`, `on_animation_start`, and
`on_animation_end`. A host with none still gets every wire reply.

## 2. Requests (client → Python)

Every request is a dict with a `type`. Coordinate fields are JSON numbers in
**data space**, not pixels.

| `type` | Fields | Reply |
| --- | --- | --- |
| `view` | `x0`, `x1`, `px?`, `seq?` | `tier_update`, or nothing |
| `density_view` | `trace`, `x0`, `x1`, `y0`, `y1`, `w?`, `h?`, `seq?` | `density_update`, or nothing |
| `pick` | `trace`, `index`, `drill_seq?`, `seq?` | `pick_result` |
| `click` | `trace`, `index`, `drill_seq?` | none (`on_click`) |
| `view_change` | `ranges`, `source?`, `axes?`, `phase?`, `interaction_id?` (legacy `x0`/`x1`/`y0`/`y1` accepted) | none (`on_view_change`) |
| `select` | `x0`, `x1`, `y0`, `y1` | `selection` |
| `select_polygon` | `points` | `selection` |
| `select_clear` | — | `selection` (empty) |
| `animation_start` | `phase` | none (`on_animation_start`) |
| `animation_end` | `phase`, `cancelled?` | none (`on_animation_end`) |

**`view`** — sent by `_scheduleViewRequest` when the chart holds any trace at
`tier === "decimated"` and a pan/zoom crossed what the shipped decimation can
serve. `x0`/`x1` are coerced with `float()` and must satisfy `x1 > x0`; `px`
defaults to `2048` and the client passes the rounded plot width. Only `line`
and `area` traces above `DECIMATION_THRESHOLD` are re-decimated; if that
produces no traces, there is no reply at all (silence, not an empty message).

**`density_view`** — one request per density-tier trace, each naming its
`trace` id. `w` defaults to `512`, `h` to `384`; the client sends the rounded
plot width and height. A trace that is not in density mode yields
`{"traces": []}`, which is dropped rather than sent. Not every view change
produces a request: a view fully contained in an exact shipped window — the
live drill's, or a retired cached point window the client promotes back — is
elided client-side (`reduction: "none"` means the subset already holds every
point of any contained view; LOD doc §5 T12/T13). The elision ends, and one
request goes out purely to re-center the §16 f32 offset encoding, once the
view span drops below 1/256 of the drilled window's span on either axis.
A request within half an output texel per edge of the trace's last sent
request (same screen size) is also suppressed (T13): if that request was
already answered there is nothing to refresh (replies are deterministic for
unchanged data; data changes rebuild the GPU trace and reset the memo), and
if it is still in flight the trace keeps waiting on the original request's
`seq`, whose reply is then accepted per-trace instead of dying to the global
seq race. More fundamentally, the aggregate tier never refines (LOD doc T13,
revised): a `density_view` goes out only when the estimated in-view count —
the smallest cached window containing the view, area-scaled, seeded by the
first payload's recorded count — sits within the points band
(`LOD_DIRECT_POINT_BUDGET × LOD_POINTS_REQUEST_BAND`). Outside that band the
covering texture stands, however blurry; traces with no recorded counts
always request.

**`pick`** — `trace` and `index` pass through `_integer_id`. `index` is a
*shipped-vertex* index, translated kernel-side to a canonical row when the
shipped copy dropped non-finite rows. `drill_seq`, when present, is the drill
subset version the client picked against; a non-current seq translates
through the kernel's bounded subset history when it is still remembered (the
client may be drawing a retired cached point window, LOD doc T13) and
resolves to `row: null` otherwise — never to a row in a dead index space.

**`click`** — same fields and same `fig.pick` resolution as `pick`, minus
`seq`; it fires `on_click` and returns nothing.

**`view_change`** — a per-axis `ranges` map (`{axisId: [lo, hi]}`) plus a
`source` string (default `"view"`, stringified kernel-side), the changed `axes`,
a `phase` (default `"end"`), and an `interaction_id`; a legacy `{x0, x1, y0, y1}`
message with no `ranges` is still accepted and normalized kernel-side. There is
no `view_change` interaction flag: the client sends `phase: "end"` events
unconditionally (rAF-coalesced — one message per gesture; they feed the
kernel's `view_state()` cache, view-state.md §5.1) and streams `"update"`
phases only when an `on_view_change` listener exists. The kernel folds every
well-formed event into the figure's durable-state cache before the callback
gate. This is the one request
type a host may withhold: on the Reflex host it never reaches the kernel,
because `XYChart.jsx` intercepts the outgoing message and invokes the
`on_view_change` prop directly
(`python/reflex-xy/reflex_xy/assets/XYChart.jsx`) — that namespace
registers no Python-side view callback.

**`select`** — box select. Edges are ordered by `lod.normalize_window` with
`require_area=False`, so a flipped or zero-area drag is still well-formed.

**`select_polygon`** — `points` is a sequence of at least two-element
sequences; each is coerced to `[float, float]` for the `on_brush` payload.

**`select_clear`** — no fields. Fires `on_select` with an empty `Selection`
and replies with the empty selection message.

**`animation_start` / `animation_end`** — browser lifecycle notifications,
not per-frame updates. `phase` is `enter` or `update`; an interrupted update
sets `cancelled: true` on its end message. Hosts invoke the corresponding
callback when present and otherwise return silently.

`px`, `w`, and `h` are untrusted: they pass through `lod.screen_shape`, which
rejects non-finite values and clamps to `[16, MAX_SCREEN_DIM]`.

## 3. Replies (Python → client)

**`tier_update`** — `{type, seq, traces}` plus one f32 buffer per column ref.
Each entry is `{id, x, y, base?}`, where each column ref is
`{buf, len, offset, scale}`: `buf` indexes the attachment list, and the client
recovers data space as `value * scale + offset`. The `x` offset re-centers on
the requested window midpoint so f32 precision follows the viewport — except
on log-family axes (log, symlog), where every geometry offset is pinned to
0.0: the shader transforms *after* decoding, and relative f32 precision is
what survives a log-family transform (dossier §16). The client drops the
message unless `msg.seq === this.seq`.

**`density_update`** — `{type, seq, traces}`. Each entry carries a `mode` that
states which representation this view resolved to:

- `mode: "density"` — `{id, mode, tier, visible, reduction, binning, density}`.
  `density` is `{buf, w, h, max, enc: "log-u8", x_range, y_range}` plus, for
  channel-bearing traces, `rgba` (a `w*h*4` straight-alpha RGBA8 plane: each
  occupied cell's alpha-weighted **mean point color**, averaged in linear
  light, plus the cell's mean point alpha) with `color_agg: "mean"` recording
  the aggregation (LOD doc §2); constant-color traces ship `color` (the
  constant) instead and no color plane — the mean of a constant IS the
  constant, so the client tints the count texture. Count always rides `buf`
  as log-u8 and drives only the drawn **alpha**; renderers must never
  colormap counts when either color source is present. Interactive replies
  ship **no `sample`** (#225): the only retained point-sample overlay is the
  first-payload one, and the client draws it solely below the T9
  resolvable-count gate (a client still accepts a legacy reply-borne `sample`
  and gates it the same way). `binning` is `"exact"` or
  `"pyramid-L<level>"`. Pyramid-served grids are **clamped to source
  resolution** — never more cells per axis than the finest level resolves
  under the window (a full-screen grid of upsampled cells is the same
  picture at several times the bytes; the client's texture filtering does
  the upscale). Exact and spatial grids are true full-detail bins at screen
  resolution. `visible` — the window's point count — is the fact the
  client's points-band gate scales to decide whether any later view is
  worth a request at all (LOD doc T13). `x_range`/`y_range` are raw data endpoints, but the
  grid's cells are **uniform in the axis's scale coordinates** (identical to
  raw on a linear axis): on a log/symlog axis the kernel bins transformed
  values so every cell covers the same strip of screen, and renderers
  interpolate cell edges between the *transformed* endpoints (dossier §28).
  The raw-space tile pyramid cannot compose such a grid, so nonlinear-axis
  traces always report `binning: "exact"`.
- `mode: "points"` — the deep-zoom drill:
  `{id, mode, tier: "direct", visible, reduction: "none", x_range, y_range,
  x, y, color, size, density_val, lod_blend, drill_seq, style}`.
  `x_range`/`y_range` are the window these points cover — usually a padded
  ALIGNED superset of the requested view (LOD doc T13; the raw view window on
  nonlinear axes or when no padding fits the budget) — and the client falls
  back to the density overview the moment the view leaves it. `visible`
  counts the points of the SHIPPED window; `lod_blend` stays keyed on the
  requested view's own count. `density_val` (per-point local log-density) and
  `lod_blend` drive the intensity-only handoff: hue is continuous by
  construction because the aggregate surface wears the mean point color, so
  no `density_colormap` field rides this message (clients ignore one if
  present).

  Channel encodings on this (and the sampled-overlay) live wire: `x`/`y` are
  offset-encoded f32 (position precision is load-bearing, dossier §16), but
  every unit-scalar channel — continuous `color` and `size` (LUT/ramp
  coordinates), `density_val` (the handoff weight) — ships quantized to
  **u8** with a `dtype: "u8"` marker (absent means f32; the client accepts
  both), and categorical color ships u8 codes. The quantization is safe precisely because these values are
  never read back into displayed numbers on a live path: hover/pick answers
  come from the kernel's canonical columns (`pick_result` above). The *build*
  payload keeps continuous channels as unit f32 — the client retains those
  columns CPU-side and denormalizes them for tooltip readouts, where 8-bit
  steps would surface as wrong digits (`channels.ship_channels`).

The client enforces `msg.seq` only when it is present, and additionally
accepts `msg.trace` and `msg.stale` for pending-request bookkeeping — no
current kernel path emits either field.

**`pick_result`** — `{type, seq, row}`. `row` is `null` when the index is out
of range or `drill_seq` was stale; the reply ships regardless so the client
clears its hover state. A point row is
`{trace, index, x, y, x_kind, y_kind}` plus `color_value` or `color_category`
and `size_value` when those channels exist. A heatmap row is
`{trace, index, row, col}` plus `color_value` when the cell is finite. Picks
use their own client-side sequence (`_pickSeq`), not the view `seq` — sharing
one counter let a hover invalidate an in-flight `tier_update`.

**`selection`** — `{type, traces, total}` plus one u32 buffer per trace. Each
entry is `{id, count, buf, drill_seq}`. Masks speak **shipped-vertex
positions** (`fig.to_shipped_indices`), so `count` is the wire mask length,
while `total` sums the canonical index counts; Python callbacks receive a
`Selection` over canonical rows. `on_brush` fires before the masks are
assembled and `on_select` after — that order is the invariant. An empty
`traces` list means "clear", and carries no buffers.

## 4. Server push

**`append`** — `{type: "append", affected: [trace_id], spec}` with
split-layout buffers, one per column, exactly like first paint (§5). The spec
additionally carries `append: {seq, affected}` — a monotonic apply signal, so
a host whose transport is the payload itself can detect the refresh without a
message envelope. The kernel re-emits a complete fresh payload rather
than a delta, because every tier's payload is screen-bounded by construction.
Without animation, the client swaps `spec` and the retained payload together
and updates only the GPU traces named in `affected` — in place when it can,
rebuilt otherwise:

- **Tail-only fast path.** A direct scatter/line whose encoding is unchanged
  between the previous and the fresh spec — same per-column
  `offset`/`scale`/`dtype`, same channel shapes (a continuous color/size
  domain that expanded fails this on purpose: its shipped values are
  normalized over the domain), same style, no transition keys, no
  `curve: "smooth"`/`step` vertex expansion — extends its existing GPU
  buffers with a tail-only `bufferSubData`. Buffer *objects* are retained
  (VAO attachments stay valid); data stores grow with doubling capacity,
  mirroring `Column.append` kernel-side, so a steady stream costs O(rows
  appended) GPU upload per tick instead of O(N). The client derives
  prefix-compatibility entirely from the two specs (no extra wire fields);
  the kernel makes it *hold* in the common case by keeping each column's
  encode offset sticky across appends while every value stays within one
  span of it (`Column.suggest_offset`, ≤1 f32 mantissa bit vs a fresh
  midpoint — a right-growing stream never exceeds that bound).
- Any precondition failure falls back to destroy + rebuild of that trace,
  which is always correct.

It then re-requests its current view through the ordinary
stale-while-revalidate path, **coalesced**: `delay: 120` with
`maxWait: 300`, so a single tick refines after the standard debounce while a
continuous stream pays at most one re-decimation/re-bin round-trip per
300 ms instead of one per tick. Parked at home, decimated traces skip the
re-request entirely when the append payload's recorded `decimation_px`
(emitted on every decimated line/area entry, §28's recorded-decision rule)
already covers the plot width — the payload itself was M4-decimated over
exactly that view. With animation configured the client routes the full
payload through `ChartView.updatePayload`, retaining one previous scene for
matching and positional interpolation while preserving append's
home/live-edge/history follow policy. Unsupported layouts snap to the new
representation without an opacity animation.
How the push travels is per-host, and the payload crosses the wire exactly
once per tick. On the anywidget comm the `spec`/`buffers` trait update (one
`hold_sync` message) is both the live push — the client applies an append
when `spec.append.seq` advances — and the notebook-reopen state; no custom
message is sent. Because a host may surface the two trait writes
non-atomically, the client listens to *both* change events, defers a torn
pair — a column that no longer fits its buffer — without consuming the seq,
and keys applied state on (seq, buffers identity), so the write that
completes the pair re-fires the apply and repairs even a same-shape tear.
The `/_xy` namespace has no synced traits, so it wraps the
same spec and buffers in a room-wide `msg` push. In both cases the client
reads the buffer layout from `spec.buffer_layout`, never from the shape of
what arrived (§5).

**`state_patch`** — `{type, state, animate, history}`, no buffers. `state` is
one view-state document (view-state.md §2: `v: 1`, optional partial `ranges`,
optional `selection`) applied by the client as a merge-patch through the same
validate → clamp → commit → emit path as a gesture, with `source: "api"`.
`animate` selects the animated transition; `history: false` opts the write
out of the client's history stack. A document the client cannot validate
(higher `v`, unknown axis or key, non-finite number) is rejected whole and
logged — never partially applied. Built by `Figure.state_patch_message`;
senders are `FigureWidget.set_view`/`select`/`clear_selection` (anywidget
comm) and `reflex_xy.set_view`/`select`/`clear_selection` (room-wide on the
`/_xy` namespace).

**`view_nav`** — `{type, op: "reset", axes?}`, no buffers. Navigation to the
home ranges, well-defined for every receiver because home ranges are
client-known; `axes` (validated against declared axes kernel-side) narrows
the reset, absent means the client's configured `reset_axes`. `"reset"` is
the only `op`: history back/forward have **no wire message** — stacks are
client-local (view-state.md §4/§5.2).

**`selection_rows`** — `{type, traces, total}` plus one u32 buffer per trace,
byte-identical in shape to the `selection` reply (same
`fig.to_shipped_indices` mask space, same `{id, count, buf, drill_seq}`
entries). Kernel-resolved from caller-supplied per-trace row indices
(`Figure.selection_rows_message`), which validates canonical indices
(bounds, integrality) and deduplicates before encoding, so `total` counts
validated unique rows. The client applies the document as a **non-durable**
*replacement* selection — every existing mask deactivates first, so traces
omitted from the message clear; never pushed to history, reported by
`state()`/`view_state()` only as the opaque `{"rows": true}` marker
(view-state.md §5.1).

All three ride the existing `msg` envelope in both transports (anywidget
comm and the `/_xy` socket.io namespace) behind the version handshake.

## 5. First-paint buffer layout: packed vs split

The first-paint payload is a data-less JSON spec plus encoded columns. The
spec's `columns` table is the addressing scheme, and it comes in two layouts:

- **Packed** (`build_payload`) — one blob. Column entries carry a global
  `byte_offset` into it. `u8` columns are followed by padding to the next
  4-byte boundary so later f32/u32 columns stay aligned. This is the layout
  used by static HTML export and the static `.xyf` payload assets; an older
  notebook output saved before appends went split may also hold a packed
  reopen blob, which the client still applies by layout declaration.
- **Split** (`build_payload_split`) — one wire buffer per column. The spec
  sets `buffer_layout: "split"`, and every column entry carries `buf` (its
  index into the buffer list) with `byte_offset: 0`. The alignment padding for
  a `u8` column is folded into that column's own buffer, and `len` still
  counts only real values, so split is a byte-identical repack of packed. This
  is what both live hosts ship at first paint — `FigureWidget`
  (`python/xy/widget.py`) and the `/_xy` namespace
  (`python/reflex-xy/reflex_xy/namespace.py`) — and on streaming append (§4),
  with no join copy anywhere on a live path.

Column entries otherwise carry `len`, an optional `dtype` (`"u8"` or `"u32"`;
absent means f32), and, for offset-encoded geometry,
`offset`/`scale`/`kind`.

Decimated line/area trace entries additionally record `decimation_px`, the px
width their M4 pass was computed for (§28: every decimation decision is
recorded, never silent). The client reads it to skip a redundant at-home
re-request after a streaming append (§4).

The client picks the layout from the spec, never from the shape of what
arrived, and **a disagreement is a fatal error, not a fallback**.
`payloadBuffers` throws when the spec says `split` and the transport delivered
one buffer, and equally when a buffer list arrives without split layout.
`_columnView` throws again per column when `Number.isInteger(meta.buf)`
disagrees with `Array.isArray(buffer)`, and rejects non-safe-integer or
negative `byte_offset`/`len`, a column extending past the payload, and a
misaligned start. Aligned spans stay zero-copy; only a legacy view whose
`byteOffset` is not a multiple of 4 pays one view-sized copy.

Stable animation identity is the second intentional u32 use beside selection
indices. A keyed direct trace carries `keys: {lo, hi}` referring to two u32
columns that form one stable 64-bit identity per shipped mark. Aggregate and
decimated tiers omit keys and record an animation fallback rather than
materializing canonical rows in the browser.

### 5.1 Full-payload data transition

A host receiving a replacement `{spec, buffers}` for the same mounted figure
calls `ChartView.updatePayload`. This is an in-browser operation, not a new
wire message: optional chart/trace `animation` objects and trace `keys`
metadata select the transition specified in [animation.md](animation.md).
The renderer retains at most previous+next GPU state and sends only the two
lifecycle messages above; no frame progress crosses the Python transport.

Standalone deterministic capture may include
`spec.animation_capture_progress` in `[0,1]`. It freezes the initial scene at
that progress and starts no animation clock.

## 6. Chunked base64 (standalone export only)

The comm and socket.io transports carry binary attachments natively and never
base64. Standalone HTML export has no binary channel, so `xy.export` embeds
the packed blob as chunked base64:

- The blob is sliced into `_B64_CHUNK_BYTES` = 48 MiB pieces. That size is
  divisible by 3, so every chunk but the last encodes a multiple of 3 bytes
  and its base64 carries no interior `=` padding — each chunk decodes
  independently into an exact-length region of one preallocated buffer.
- Each chunk is emitted as its own `<script>__xyChunks.push("…")</script>`
  block. A script element's source is itself a JS string, so folding all
  chunks into one block would rebuild the single-string length ceiling the
  chunking removes. Base64 text (`[A-Za-z0-9+/=]`) contains no quote,
  backslash, newline, or `<`, so it is quoted verbatim and can never close the
  element.
- `xyDecodeB64(chunks, total)` allocates `Uint8Array(total)` and prefers
  `setFromBase64`, falling back to an `atob` + `charCodeAt` loop into the
  preallocated array.

The reassembled bytes are identical to the source blob, which is what keeps
`spec.columns[i].byte_offset` valid end to end. Export warns above
`EMBED_WARN_BYTES` = 64 MiB, since base64 adds roughly a third.

## 7. Versioning and compatibility

Two independent version constants:

- **Renderer/spec protocol.** `PROTOCOL_VERSION = 6` (`python/xy/config.py`)
  rides every first-paint spec as `spec["protocol"]`; the client's
  `PROTOCOL = 6` (`js/src/00_header.ts`) is checked in the `ChartView`
  constructor. A mismatch replaces the chart element with "update the xy
  package and restart the kernel" and throws. Requests and replies carry no
  version of their own — the handshake happens once, at first paint, before
  any request is possible. The version bumps whenever a spec the old client
  would *silently misrender* becomes producible (or, as in v5, whenever the
  contract changes out from under a cached bundle). v5 changed the append
  contract (§4: split buffers, trait-ride on the widget host) — a cached
  pre-v5 bundle would otherwise wait forever for a custom append message
  that no longer exists. v6 added the symlog axis scale (`scale: "symlog"`
  + `constant` on an axis spec) and scale-coordinate density grids; a v5
  client would draw both as linear without erroring.
- **Transport frame.** `FRAME_MAGIC` `"XYBF"` with `FRAME_VERSION = 1`
  versions the binary envelope separately, so the transport and the renderer
  can evolve without coupling.

Compatibility is structural rather than negotiated: the client is a committed
artifact (`python/xy/static/index.js`) shipped inside the same distribution as
the Python that produces payloads, and `reflex_xy` deliberately does not
package its own copy — `assets.register()` symlinks the client out of the
installed `xy` distribution, repairing a stale link if the install moved. The
JS that renders a payload is therefore always the build that shipped with the
Python that produced it. The protocol check exists for the case that survives
this: a browser holding a cached bundle against a restarted kernel.
