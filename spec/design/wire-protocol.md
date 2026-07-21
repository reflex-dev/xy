# Wire protocol — client ↔ Python

Status: **shipped**. This document specifies the message catalog dispatched by
`xy.channel.handle_message` (`python/xy/channel.py`) and consumed by
`js/src/54_kernel.js`, plus the first-paint buffer layouts and the version
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

`ChannelCallbacks` carries five optional hooks: `on_hover`, `on_click`,
`on_brush`, `on_select`, `on_view_change`. A host with none still gets every
wire reply.

## 2. Requests (client → Python)

Every request is a dict with a `type`. Coordinate fields are JSON numbers in
**data space**, not pixels.

| `type` | Fields | Reply |
| --- | --- | --- |
| `view` | `x0`, `x1`, `px?`, `seq?` | `tier_update`, or nothing |
| `density_view` | `trace`, `x0`, `x1`, `y0`, `y1`, `w?`, `h?`, `seq?` | `density_update`, or nothing |
| `pick` | `trace`, `index`, `drill_seq?`, `seq?` | `pick_result` |
| `click` | `trace`, `index`, `drill_seq?` | none (`on_click`) |
| `view_change` | `x0`, `x1`, `y0`, `y1`, `source?` | none (`on_view_change`) |
| `select` | `x0`, `x1`, `y0`, `y1` | `selection` |
| `select_polygon` | `points` | `selection` |
| `select_clear` | — | `selection` (empty) |

**`view`** — sent by `_scheduleViewRequest` when the chart holds any trace at
`tier === "decimated"` and a pan/zoom crossed what the shipped decimation can
serve. `x0`/`x1` are coerced with `float()` and must satisfy `x1 > x0`; `px`
defaults to `2048` and the client passes the rounded plot width. Only `line`
and `area` traces above `DECIMATION_THRESHOLD` are re-decimated; if that
produces no traces, there is no reply at all (silence, not an empty message).

**`density_view`** — one request per density-tier trace, each naming its
`trace` id. `w` defaults to `512`, `h` to `384`; the client sends the rounded
plot width and height. A trace that is not in density mode yields
`{"traces": []}`, which is dropped rather than sent.

**`pick`** — `trace` and `index` pass through `_integer_id`. `index` is a
*shipped-vertex* index, translated kernel-side to a canonical row when the
shipped copy dropped non-finite rows. `drill_seq`, when present, is the drill
subset version the client picked against; a mismatch resolves to `row: null`
rather than to a row in a dead index space.

**`click`** — same fields and same `fig.pick` resolution as `pick`, minus
`seq`; it fires `on_click` and returns nothing.

**`view_change`** — the four view edges plus a `source` string (default
`"view"`, stringified kernel-side). The client sends it rAF-coalesced and only
while the `view_change` interaction flag is set; the kernel returns
immediately when no `on_view_change` callback is wired. This is the one request
type a host may withhold: on the Reflex host it never reaches the kernel,
because `XYChart.jsx` intercepts the outgoing message and invokes the
`on_view_change` prop directly
(`python/reflex-xy/reflex_xy/assets/XYChart.jsx:164-169`) — that namespace
registers no Python-side view callback.

**`select`** — box select. Edges are ordered by `lod.normalize_window` with
`require_area=False`, so a flipped or zero-area drag is still well-formed.

**`select_polygon`** — `points` is a sequence of at least two-element
sequences; each is coerced to `[float, float]` for the `on_brush` payload.

**`select_clear`** — no fields. Fires `on_select` with an empty `Selection`
and replies with the empty selection message.

`px`, `w`, and `h` are untrusted: they pass through `lod.screen_shape`, which
rejects non-finite values and clamps to `[16, MAX_SCREEN_DIM]`.

## 3. Replies (Python → client)

**`tier_update`** — `{type, seq, traces}` plus one f32 buffer per column ref.
Each entry is `{id, x, y, base?}`, where each column ref is
`{buf, len, offset, scale}`: `buf` indexes the attachment list, and the client
recovers data space as `value * scale + offset`. The `x` offset re-centers on
the requested window midpoint so f32 precision follows the viewport. The
client drops the message unless `msg.seq === this.seq`.

**`density_update`** — `{type, seq, traces}`. Each entry carries a `mode` that
states which representation this view resolved to:

- `mode: "density"` — `{id, mode, tier, visible, reduction, binning, density}`.
  `density` is `{buf, w, h, max, enc: "log-u8", x_range, y_range}` plus
  optional `color` (a constant-channel color) and `sample` (the retained
  point-sample overlay). `binning` is `"exact"` or `"pyramid-L<level>"`.
- `mode: "points"` — the deep-zoom drill:
  `{id, mode, tier: "direct", visible, reduction: "none", x_range, y_range,
  x, y, color, size, density_val, lod_blend, density_colormap, drill_seq,
  style}`. `x_range`/`y_range` are the window these points cover; the client
  falls back to the density overview the moment the view leaves it.

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

**`append`** — `{type: "append", affected: [trace_id], spec}` with a single
packed blob attachment. The kernel re-emits a complete fresh payload rather
than a delta, because every tier's payload is screen-bounded by construction.
The client swaps `spec` and the retained payload together, rebuilds only the
GPU traces named in `affected`, then re-requests its current view with
`delay: 0`. The widget also re-syncs its `spec`/`buffers` traits so a
re-rendered output shows the streamed state.

## 5. First-paint buffer layout: packed vs split

The first-paint payload is a data-less JSON spec plus encoded columns. The
spec's `columns` table is the addressing scheme, and it comes in two layouts:

- **Packed** (`build_payload`) — one blob. Column entries carry a global
  `byte_offset` into it. `u8` columns are followed by padding to the next
  4-byte boundary so later f32 columns stay aligned. This is the layout used
  by static HTML export and by streaming-refresh reopen state.
- **Split** (`build_payload_split`) — one wire buffer per column. The spec
  sets `buffer_layout: "split"`, and every column entry carries `buf` (its
  index into the buffer list) with `byte_offset: 0`. The alignment padding for
  a `u8` column is folded into that column's own buffer, and `len` still
  counts only real values, so split is a byte-identical repack of packed. This
  is what both live hosts ship at first paint — `FigureWidget`
  (`python/xy/widget.py:76`) and the `/_xy` namespace
  (`python/reflex-xy/reflex_xy/namespace.py:135`, `:197`) — with no join copy.

Column entries otherwise carry `len`, an optional `dtype` (`"u8"`; absent
means f32), and, for offset-encoded geometry, `offset`/`scale`/`kind`.

The client picks the layout from the spec, never from the shape of what
arrived, and **a disagreement is a fatal error, not a fallback**.
`payloadBuffers` throws when the spec says `split` and the transport delivered
one buffer, and equally when a buffer list arrives without split layout.
`_columnView` throws again per column when `Number.isInteger(meta.buf)`
disagrees with `Array.isArray(buffer)`, and rejects non-safe-integer or
negative `byte_offset`/`len`, a column extending past the payload, and a
misaligned start. Aligned spans stay zero-copy; only a legacy view whose
`byteOffset` is not a multiple of 4 pays one view-sized copy.

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

- **Renderer/spec protocol.** `PROTOCOL_VERSION = 3` (`python/xy/config.py`)
  rides every first-paint spec as `spec["protocol"]`; the client's
  `PROTOCOL = 3` (`js/src/00_header.js`) is checked in the `ChartView`
  constructor. A mismatch replaces the chart element with "update the xy
  package and restart the kernel" and throws. Requests and replies carry no
  version of their own — the handshake happens once, at first paint, before
  any request is possible.
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
