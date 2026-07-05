"""Static PNG export smoke — stdlib only (no numpy / no PyPI), needs Chromium.

Exercises `export.html_to_png` end-to-end (the mechanism behind `Figure.to_png`)
by rendering a hand-built standalone chart HTML — the committed JS bundle plus a
tiny by-hand spec/blob — through headless Chromium and asserting a real,
correctly-sized, non-trivial PNG comes back. Mirrors render_smoke_nonumpy.py's
no-dependency stance so CI verifies the export path without installing numpy.
"""

from __future__ import annotations

import base64
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))

from fastcharts.export import find_chromium, html_to_png  # noqa: E402

W, H, SCALE = 320, 200, 2


def build_html() -> str:
    bundle = (ROOT / "python/fastcharts/static/standalone.js").read_text()
    # two-point line, f32 offset-encoded (offset 0.5, scale 1) — no numpy.
    blob = struct.pack("<2f", -0.5, 0.5) + struct.pack("<2f", -0.5, 0.5)
    spec = {
        "protocol": 2,
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
        'fastcharts.renderStandalone(document.getElementById("chart"),spec,bytes.buffer);'
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


def main() -> None:
    if find_chromium() is None:
        print("png export smoke SKIPPED (no chromium)")
        return
    png = html_to_png(build_html(), W, H, scale=SCALE, time_budget_ms=3000)
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("not a PNG")
    w, h = struct.unpack(">II", png[16:24])
    if (w, h) != (W * SCALE, H * SCALE):
        raise SystemExit(f"unexpected PNG dims {w}x{h}, want {W * SCALE}x{H * SCALE}")
    if len(png) < 2000 or not png_is_nonblank(png):
        raise SystemExit("PNG looks blank — chart did not render")
    print(f"png export smoke OK: {w}x{h}, {len(png)} bytes, non-blank")


if __name__ == "__main__":
    main()
