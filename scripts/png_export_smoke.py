"""Static PNG export smoke — stdlib only (no numpy / no PyPI).

Two engines, both without installing numpy:

- **native** (always runs): drives the Rust rasterizer `xy_rasterize` directly
  via ctypes with a hand-built display-list command buffer, encodes the returned
  framebuffer to PNG, and asserts a real, correctly-sized, non-blank image — the
  end-to-end browser-free `Chart.to_png(engine=Engine.default)` mechanism.
- **browser** (skipped without a supported browser): renders a hand-built
  standalone chart HTML through the installed Chromium-family adapter
  (`export.html_to_png`), the `Engine.chromium` path.

Mirrors render_smoke_nonumpy.py's no-dependency stance so CI verifies both
export paths without numpy.
"""

from __future__ import annotations

import base64
import ctypes
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for abi_smoke.load

from _protocol import PROTOCOL_VERSION  # noqa: E402
from abi_smoke import load  # noqa: E402
from xy.export import find_chromium, html_to_png  # noqa: E402

W, H, SCALE = 320, 200, 2


def build_html() -> str:
    bundle = (ROOT / "python/xy/static/standalone.js").read_text()
    # two-point line, f32 offset-encoded (offset 0.5, scale 1) — no numpy.
    blob = struct.pack("<2f", -0.5, 0.5) + struct.pack("<2f", -0.5, 0.5)
    spec = {
        "protocol": PROTOCOL_VERSION,
        "width": W,
        "height": H,
        "title": "png-export-smoke",
        "x_axis": {"kind": "linear", "label": "", "range": [0, 1]},
        "y_axis": {"kind": "linear", "label": "", "range": [0, 1]},
        "columns": [
            {"byte_offset": 0, "len": 2, "offset": 0.5, "scale": 1.0},
            {"byte_offset": 8, "len": 2, "offset": 0.5, "scale": 1.0},
        ],
        "traces": [
            {
                "id": 0,
                "kind": "line",
                "name": "l",
                "tier": "direct",
                "style": {"color": "#3b82f6", "opacity": 1, "width": 2, "role": "line"},
                "x": 0,
                "y": 1,
                "n_points": 2,
            }
        ],
        "backend": "none",
        "show_legend": False,
        "show_modebar": False,
    }
    b64 = base64.b64encode(blob).decode()
    return (
        "<!doctype html><html><head><meta charset=utf-8></head><body>"
        "<div id=chart></div>"
        f"<script>{bundle}</script><script>"
        f"const spec={json.dumps(spec)};"
        f'const bytes=Uint8Array.from(atob("{b64}"),c=>c.charCodeAt(0));'
        'xy.renderStandalone(document.getElementById("chart"),spec,bytes.buffer);'
        "</script></body></html>"
    )


def png_is_nonblank(data: bytes) -> bool:
    """Decompress the concatenated IDAT chunks and confirm the image isn't a
    single flat color (a blank canvas screenshot decodes to one repeated
    value). Walks the PNG chunk structure: [len][type][data][crc]."""
    idat = bytearray()
    pos = 8  # skip signature
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        start = pos + 8
        if ctype == b"IDAT":
            idat += data[start : start + length]
        pos = start + length + 4  # + CRC
        if ctype == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    # Sample across the WHOLE image (a strided sample) — the top scanlines are
    # margin whitespace, so checking only the head would false-negative.
    return len(set(raw[:: max(1, len(raw) // 4096)])) > 3


def _encode_truecolor(w: int, h: int, rgba: bytes) -> bytes:
    """Minimal stdlib RGBA8 PNG (mirrors xy._png.png_truecolor, kept
    inline so this smoke stays numpy-free)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    stride = w * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def native_smoke() -> None:
    """Rasterize a hand-built command buffer (bg + rect + text) through
    `xy_rasterize` and validate the encoded PNG — no browser, no numpy."""
    lib = load()
    w, h = 160, 100

    def f(v: float) -> bytes:
        return struct.pack("<f", v)

    def u(v: int) -> bytes:
        return struct.pack("<I", v)

    def poly(pts, rgba: bytes) -> bytes:
        return bytes([1]) + u(len(pts)) + b"".join(f(x) + f(y) for x, y in pts) + rgba

    cmd = bytearray()
    cmd += poly([(0, 0), (w, 0), (w, h), (0, h)], bytes([255, 255, 255, 255]))  # white bg
    cmd += poly([(20, 20), (140, 20), (140, 80), (20, 80)], bytes([37, 99, 235, 255]))  # blue rect
    s = b"PNG"
    cmd += (
        bytes([6])
        + f(80)
        + f(55)
        + bytes([1])
        + f(18)
        + bytes([255, 255, 255, 255])
        + u(len(s))
        + s
    )

    out = (ctypes.c_uint8 * (w * h * 4))()
    cbuf = (ctypes.c_uint8 * len(cmd)).from_buffer_copy(bytes(cmd))
    ok = lib.xy_rasterize(cbuf, len(cmd), out, w, h)
    if ok != 1:
        raise SystemExit("xy_rasterize rejected a valid command buffer")
    png = _encode_truecolor(w, h, bytes(out))
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("native: not a PNG")
    pw, ph = struct.unpack(">II", png[16:24])
    if (pw, ph) != (w, h) or not png_is_nonblank(png):
        raise SystemExit("native PNG looks blank — rasterizer did not paint")
    print(f"native png smoke OK: {pw}x{ph}, {len(png)} bytes, non-blank")


def main() -> None:
    native_smoke()
    if find_chromium() is None:
        print("chromium png export smoke SKIPPED (no chromium)")
        return
    png = html_to_png(build_html(), W, H, scale=SCALE, time_budget_ms=3000)
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("not a PNG")
    w, h = struct.unpack(">II", png[16:24])
    if (w, h) != (W * SCALE, H * SCALE):
        raise SystemExit(f"unexpected PNG dims {w}x{h}, want {W * SCALE}x{H * SCALE}")
    if len(png) < 2000 or not png_is_nonblank(png):
        raise SystemExit("PNG looks blank — chart did not render")
    print(f"chromium png export smoke OK: {w}x{h}, {len(png)} bytes, non-blank")


if __name__ == "__main__":
    main()
