"""FastAPI live drilldown: a 100M-point scatter served by the engine's own LOD.

The pattern this example demonstrates is deliberately small:

- build one figure (`live_figure`), serve its payload plus the bundled render
  client as a single HTML page;
- wire `ChartView` to a custom transport — a `comm` object whose `send` POSTs
  the client's messages to one endpoint and feeds each reply — an `XYBF`
  binary frame (`spec/design/wire-protocol.md` §7): small JSON metadata plus
  raw f32/u8 buffers, decoded in the browser with `xy.decodeFrame` — back
  through `onMessage`, with no base64 on either side;
- the endpoint dispatches `density_view` / `pick` straight to the figure,
  under one lock.

The LOD ladder itself lives in the engine: `Figure.density_view` picks the
tier per window — mean-color pyramid composition for wide views, exact
re-bins near the drill budget, exact points inside it (LOD doc §2/§4) — and
the render client debounces its requests, drops stale replies by `seq`, and
keeps the best cached density texture drawn until a fresh one lands (§17
stale-while-revalidate), so the host app carries no aggregation or request
bookkeeping of its own.

An over-RAM request is served out-of-core: when ``XY_LIVE_POINTS`` asks for a
dataset over 75% of the machine's RAM (four canonical f64 columns), generation
streams each column to a disk memmap via ``xy._ooc.MemmapF64Builder`` — peak
RAM is one 1M-point chunk — and the figure serves those files directly, the
kernels paging them through the OS cache (dossier §27; LOD doc §4.4).
``XY_LIVE_POINTS_DIR`` picks where the backing files live (default: the
system temp dir; point it at a real disk if yours is a RAM-backed tmpfs).
The recorded trade (LOD doc Phase-3 item 7): an out-of-core trace never pays
an O(N) file rescan per view, so deep zooms keep serving the aggregate
density surface (pyramid, upsampled past its floor) instead of drilling to
exact points.
"""

from __future__ import annotations

import atexit
import base64
import json
import os
import shutil
import sys
import tempfile
import threading
import warnings
from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Union

import numpy as np
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import xy

# The live drilldown server probes the engine directly (density_view, pick),
# so it works on the internal figure compiled from the public composition API
# via `Chart.figure()`.
from xy._figure import Figure

# Over-RAM datasets stream to disk-backed columns (dossier §27 "mmap
# (native)"): the builder writes canonical f64 one chunk at a time and the
# ordinary chart API consumes the finished read-only memmap views unchanged.
from xy._ooc import MemmapF64Builder

# `encode_frame` builds the XYBF binary transport frame (wire-protocol.md §7)
# the browser decodes with the bundled `xy.decodeFrame`; it is re-exported from
# the transport-neutral channel module, the same seam the Reflex adapter uses.
from xy.channel import encode_frame
from xy.widget import bundled_js

_DEFAULT_LIVE_POINTS = 100_000_000


def _live_points() -> int:
    """Point count for the drilldown demo, from ``XY_LIVE_POINTS``.

    A non-integer or non-positive value falls back to the default with a
    warning rather than aborting app import or failing deep in data generation.
    """
    raw = os.environ.get("XY_LIVE_POINTS")
    if raw is None:
        return _DEFAULT_LIVE_POINTS
    try:
        points = int(raw)
    except ValueError:
        points = 0
    if points < 1:
        warnings.warn(
            f"XY_LIVE_POINTS={raw!r} is not a positive integer; using {_DEFAULT_LIVE_POINTS:,}",
            RuntimeWarning,
            stacklevel=2,
        )
        return _DEFAULT_LIVE_POINTS
    return points


# Point count for the drilldown demo; override with XY_LIVE_POINTS.
LIVE_SCATTER_POINTS = _live_points()
LIVE_DRILLDOWN_ROUTE = "/api/xy/drilldown"
# One figure serves every request; density_view mutates its drill bookkeeping,
# so requests (and payload builds) serialize.
_FIGURE_LOCK = threading.Lock()


def _point_label(n: int) -> str:
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n % 1_000 == 0:
        return f"{n // 1_000}k"
    return f"{n:,}"


# The dataset is four canonical f64 columns (x, y, color, size).
_BYTES_PER_POINT = 4 * 8
# Requests whose dataset would consume over this fraction of physical RAM are
# generated out to disk memmaps and served from there (dossier §27).
_MMAP_RAM_FRACTION = 0.75


def _total_ram_bytes() -> int | None:
    """Total physical RAM in bytes, or ``None`` where it can't be read.

    ``SC_PAGE_SIZE``/``SC_PHYS_PAGES`` are POSIX; on a platform without them
    the dataset simply stays in RAM (the pre-mmap behavior).
    """
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        pages = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return None
    if page <= 0 or pages <= 0:
        return None
    return page * pages


def _mmap_needed(n: int) -> bool:
    """True when ``n`` points would consume over 75% of the machine's RAM."""
    ram = _total_ram_bytes()
    return ram is not None and n * _BYTES_PER_POINT > ram * _MMAP_RAM_FRACTION


def _scatter_chunks(n: int) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Yield the seed-11 drilldown cloud as ``(x, y, color, size)`` f64 chunks.

    Both storage paths — in-RAM arrays and disk memmaps — consume this one
    stream, so the dataset is bit-identical wherever it lands (and identical
    to the reflex showcase's §6 chart, which mirrors this generation).
    """
    rng = np.random.default_rng(11)
    chunk = 1_000_000
    for start in range(0, n, chunk):
        m = min(start + chunk, n) - start
        xs = rng.normal(0, 1.0, m)
        ys = rng.normal(0, 0.55, m)
        ys += xs * 0.55
        ss = rng.normal(6, 2.5, m)
        np.abs(ss, out=ss)
        np.clip(ss, 2, 16, out=ss)
        yield xs, ys, np.hypot(xs, ys), ss


def _mmap_scatter_data(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate the cloud straight to disk memmaps (over-RAM requests).

    Each column streams through `xy._ooc.MemmapF64Builder` one chunk at a
    time, and the finished read-only views feed the ordinary chart API: the
    kernels scan them via the OS page cache, so resident memory stays
    screen-bounded, never data-bounded (dossier §27; LOD doc §4.4). The
    backing files live under ``XY_LIVE_POINTS_DIR`` (default: the system temp
    dir) and are removed at interpreter exit.
    """
    root = os.environ.get("XY_LIVE_POINTS_DIR") or None
    if root is not None:
        os.makedirs(root, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="xy-live-drilldown-", dir=root)
    atexit.register(shutil.rmtree, tmpdir, ignore_errors=True)
    ram = _total_ram_bytes() or 0
    print(
        f"xy live drilldown: {n:,} points × 4 f64 columns "
        f"({n * _BYTES_PER_POINT / 2**30:.1f} GiB) exceed "
        f"{_MMAP_RAM_FRACTION:.0%} of {ram / 2**30:.1f} GiB RAM; streaming to "
        f"disk memmaps under {tmpdir} (XY_LIVE_POINTS_DIR overrides the location)",
        file=sys.stderr,
    )
    builders = [
        MemmapF64Builder(os.path.join(tmpdir, f"{name}.f64"), capacity=n)
        for name in ("x", "y", "color", "size")
    ]
    for columns in _scatter_chunks(n):
        for builder, column in zip(builders, columns, strict=True):
            builder.extend(column)
    x, y, color, size = (builder.finalize() for builder in builders)
    return x, y, color, size


def colored_scatter_data(
    n: int = LIVE_SCATTER_POINTS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The drilldown dataset — in RAM, or on disk when RAM can't hold it.

    A request over 75% of physical memory (`_mmap_needed`) is generated out to
    disk memmap files and served from those; anything smaller materializes in
    RAM exactly as before.
    """
    if _mmap_needed(n):
        return _mmap_scatter_data(n)
    x = np.empty(n, dtype=np.float64)
    y = np.empty(n, dtype=np.float64)
    color = np.empty(n, dtype=np.float64)
    size = np.empty(n, dtype=np.float64)
    cursor = 0
    for xs, ys, cs, ss in _scatter_chunks(n):
        end = cursor + xs.shape[0]
        x[cursor:end] = xs
        y[cursor:end] = ys
        color[cursor:end] = cs
        size[cursor:end] = ss
        cursor = end
    return x, y, color, size


def colored_scatter_chart(
    n: int = LIVE_SCATTER_POINTS,
    *,
    title: str | None = None,
    width: Union[str, int] = "100%",
    height: int = 430,
) -> xy.Chart:
    title = title or f"{_point_label(n)} live drilldown scatter"
    x, y, color, size = colored_scatter_data(n)
    return xy.scatter_chart(
        xy.scatter(x, y, color=color, size=size, colormap="viridis", opacity=0.72, density=True),
        xy.x_axis(label="feature A"),
        xy.y_axis(label="feature B"),
        title=title,
        width=width,
        height=height,
    )


def colored_scatter_figure(
    n: int = LIVE_SCATTER_POINTS,
    *,
    title: str | None = None,
    width: Union[str, int] = "100%",
    height: int = 430,
) -> Figure:
    return colored_scatter_chart(n, title=title, width=width, height=height).figure()


@lru_cache(maxsize=1)
def live_figure() -> Figure:
    fig = colored_scatter_figure()
    # Warm the kernel's mean-color pyramid (LOD doc §4) at startup so the
    # first interactive zoom skips the one-time build; the reply itself is
    # discarded.
    x0, x1 = fig.x_range()
    y0, y1 = fig.y_range()
    fig.density_view(0, x0, x1, y0, y1, 512, 384)
    return fig


def _b64(buf: bytes) -> str:
    return base64.b64encode(buf).decode("ascii")


# Round-trip replies travel as XYBF binary frames (wire-protocol.md §7): the
# reply message is the frame's compact JSON metadata and each numeric buffer
# rides raw and 8-byte aligned, so the browser decodes one `xy.decodeFrame`
# and hands the kernel zero-copy views. First paint still embeds its blob as
# base64 in the page below, because inline HTML has no binary channel
# (wire-protocol.md §6).
_FRAME_MEDIA_TYPE = "application/octet-stream"


def _frame_response(message: dict[str, Any], buffers: list[bytes] | None = None) -> Response:
    return Response(encode_frame(message, buffers or []), media_type=_FRAME_MEDIA_TYPE)


async def drilldown_endpoint(request: Request) -> Response:
    """Answer the render client's messages with the engine's own replies.

    `Figure.density_view` owns the whole ladder (mean-color pyramid for wide
    windows, exact re-bins near the budget, drill-in to real points,
    hysteresis, recorded reductions), and the render client discards stale
    replies by `seq`, so this endpoint is one lock and one dispatch. Each
    reply ships as an XYBF binary frame (`_frame_response`); malformed
    requests return a plain JSON error the client rejects on `res.ok` before
    decoding.
    """
    try:
        content = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    kind = content.get("type")
    with _FIGURE_LOCK:
        fig = live_figure()
        if kind == "density_view":
            try:
                update, buffers = fig.density_view(
                    int(content["trace"]),
                    float(content["x0"]),
                    float(content["x1"]),
                    float(content["y0"]),
                    float(content["y1"]),
                    int(content.get("w", 512)),
                    int(content.get("h", 384)),
                )
            except (KeyError, ValueError, IndexError):
                return JSONResponse({"error": "bad density_view request"}, status_code=400)
            return _frame_response(
                {
                    "type": "density_update",
                    "seq": content.get("seq"),
                    "trace": content.get("trace"),
                    **update,
                },
                buffers,
            )

        if kind == "pick":
            dseq = content.get("drill_seq")
            row = fig.pick(
                int(content.get("trace", -1)),
                int(content.get("index", -1)),
                None if dseq is None else int(dseq),
            )
            return _frame_response({"type": "pick_result", "seq": content.get("seq"), "row": row})

        if kind in {"select", "select_clear"}:
            return _frame_response({"type": "selection", "traces": [], "total": 0})

    return JSONResponse({"error": f"unsupported message type {kind!r}"}, status_code=400)


def live_drilldown_html() -> str:
    fig = live_figure()
    with _FIGURE_LOCK:
        spec, blob = fig.build_payload()
    spec_js = json.dumps(spec).replace("</", "<\\/")
    b64 = _b64(blob)
    route = LIVE_DRILLDOWN_ROUTE
    js = bundled_js("standalone")
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{_point_label(LIVE_SCATTER_POINTS)} live drilldown scatter</title>
<style>
html,body{{margin:0;width:100%;height:100%;font-family:system-ui,sans-serif;background:#fff;}}
#chart{{width:100%;height:430px;}}
#status{{position:absolute;right:12px;top:10px;z-index:10;padding:4px 8px;border:1px solid rgba(16,24,40,.14);border-radius:4px;background:rgba(255,255,255,.86);color:#344054;font:12px system-ui,sans-serif;pointer-events:none;}}
</style>
</head>
<body>
<div id="chart"></div>
<div id="status">density</div>
<script>{js}</script>
<script>
const spec = {spec_js};
// First paint is embedded base64 (one-time, inline HTML has no binary channel);
// every interactive round-trip below rides the raw XYBF frame instead.
const initialBytes = Uint8Array.from(atob("{b64}"), c => c.charCodeAt(0));
const statusEl = document.getElementById("status");
const callbacks = [];

// The demo may run behind a proxying sandbox that exposes the API on another
// origin (PING in /env.json); otherwise the route is same-origin.
async function endpointUrl() {{
  try {{
    const env = await fetch("/env.json").then((r) => r.ok ? r.json() : null);
    if (env && env.PING) return new URL("{route}", env.PING).href;
  }} catch (err) {{}}
  return "{route}";
}}
const endpoint = endpointUrl();

// The whole custom transport: POST the render client's message, decode the
// XYBF reply frame, and hand its message and raw buffers back to the view.
// decodeFrame returns the JSON metadata plus zero-copy, 8-byte-aligned
// Uint8Array views straight over the response body — no base64 decode, and the
// kernel reads them in place. Tiering, drill state, the mean-color pyramid,
// request debouncing, stale-reply drops (by seq), and the cached-texture hold
// while a reply is in flight all live in the engine and its render client —
// this page only moves bytes and updates a badge.
async function sendMessage(msg) {{
  try {{
    const res = await fetch(await endpoint, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(msg),
    }});
    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
    const frame = xy.decodeFrame(await res.arrayBuffer());
    const message = frame.message;
    if (!message) return;
    for (const cb of callbacks) cb(message, frame.buffers);
    const trace = message.traces && message.traces[0];
    if (trace && trace.mode && message.seq === view.seq) {{
      const visible = Number(trace.visible || 0).toLocaleString();
      statusEl.textContent = trace.mode === "points" ? `${{visible}} points` : `${{visible}} density`;
    }}
  }} catch (err) {{
    statusEl.textContent = "offline";
    console.error("xy drilldown request failed", err);
  }}
}}

const comm = {{
  send: (msg) => {{
    if (["density_view", "pick", "select", "select_clear"].includes(msg.type)) {{
      void sendMessage(msg);
    }}
  }},
  onMessage: (cb) => callbacks.push(cb),
}};

const view = new xy.ChartView(
  document.getElementById("chart"),
  spec,
  initialBytes.buffer,
  comm,
);
window.xyLiveDrilldown = view;
</script>
</body>
</html>"""
