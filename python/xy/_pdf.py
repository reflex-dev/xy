"""Native vector PDF export — a converter for xy's OWN generated SVG.

`svg_to_pdf` turns the output of `xy._svg.to_svg` (and the `FacetGrid.to_svg`
composition wrapper) into a single-page vector PDF with no browser and no
external dependencies (stdlib + numpy only).

Because xy controls the SVG generator, the accepted SVG subset is CLOSED: this
module handles exactly the elements/attributes `_svg.py` emits and raises
``ValueError("unsupported SVG feature: ...")`` on anything else, so generator
drift fails loudly instead of rendering wrong.

Mapping decisions:

- 1 CSS px = 0.75 pt (96dpi -> 72dpi). One top-level ``cm`` scales by 0.75 and
  flips the y axis; all path coordinates stay in SVG user space.
- Shapes stay vector: path construction ops with fills/strokes; opacities
  (``fill-opacity``/``stroke-opacity``/``opacity`` and rgba() color alpha)
  become deduplicated ExtGStates (/ca /CA). The generator only ever emits the
  default nonzero winding rule, so even-odd variants are never produced.
- Text stays text: BT/Tf/Tm/Tj/ET with the base-14 Helvetica family
  (weight >= 600 selects Helvetica-Bold) in WinAnsiEncoding, using the
  standard AFM width tables so ``text-anchor="middle"/"end"`` offsets come
  from real metrics. Characters outside WinAnsi are replaced with "?"
  (``cp1252`` + ``errors="replace"``) — a deterministic, locale-independent
  substitution policy.
- ``<linearGradient>`` becomes an axial shading (/ShadingType 2; exponential
  function for 2 stops, stitching for more) painted inside the gradient
  geometry's clip; per-stop alpha becomes a luminosity soft mask.
- ``<clipPath>`` (always a single rect in the subset) becomes ``re W n``
  inside a q/Q scope.
- Embedded ``data:image/png;base64`` rasters (truecolor or indexed+tRNS,
  filters 0-4) are decoded with zlib and re-embedded as FlateDecode
  /DeviceRGB Image XObjects with an /SMask when not fully opaque;
  /Interpolate false preserves the generator's pixelated rendering intent.
- Output is deterministic: no timestamps/ids, stable object numbering, and a
  byte-accurate xref table.
"""

from __future__ import annotations

import base64
import math
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from itertools import pairwise
from typing import Any, NoReturn, Optional

import numpy as np

from . import kernels

__all__ = ["svg_to_pdf"]

_SVG_NS = "http://www.w3.org/2000/svg"
_PX_TO_PT = 0.75
_DEFAULT_FONT_SIZE = 16.0  # CSS "medium" — the root <svg> normally overrides with font-size="11"
_KAPPA = 0.5522847498307936
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _unsupported(what: str) -> NoReturn:
    raise ValueError(f"unsupported SVG feature: {what}")


# ---------------------------------------------------------------------------
# Helvetica metrics (AFM widths for WinAnsi codes 32..255, per mille)
# ---------------------------------------------------------------------------

# fmt: off
_HELV = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 350,
    556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
    350, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 350, 500, 667,
    278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556, 500, 556, 500,
)
_HELV_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 350,
    556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350,
    350, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 350, 500, 667,
    278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333,
    400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611,
    722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
    556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
    611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556,
)
# fmt: on


def _text_width_px(data: bytes, size: float, bold: bool) -> float:
    """String advance in px for WinAnsi bytes at `size` px, from AFM widths."""
    table = _HELV_BOLD if bold else _HELV
    return size * sum(table[b - 32] for b in data if b >= 32) / 1000.0


def _pdf_string(data: bytes) -> str:
    """A PDF literal string: escape ()\\, octal-escape bytes outside 32..126."""
    out: list[str] = []
    for b in data:
        if b in (0x28, 0x29, 0x5C):
            out.append("\\" + chr(b))
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def _f(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _local(tag: Any) -> str:
    if not isinstance(tag, str):  # comments / processing instructions
        _unsupported("non-element XML node")
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        if ns != _SVG_NS:
            _unsupported(f"foreign namespace {ns!r}")
        return name
    return tag


def _check_attrs(el: ET.Element, tag: str, allowed: frozenset[str]) -> None:
    for name in el.attrib:
        if name not in allowed:
            _unsupported(f"<{tag}> attribute {name!r}")


def _float(value: Optional[str], default: float, what: str) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        pass
    _unsupported(f"{what} {value!r}")


def _rgba(css: str) -> tuple[float, float, float, float]:
    _status, rgba = kernels.css_check(kernels.CSS_COLOR, css)
    if rgba is None:
        _unsupported(f"color {css!r}")
    red, green, blue, alpha = rgba
    return float(red), float(green), float(blue), float(alpha)


_URL_RE = re.compile(r"^url\(#([^)]+)\)$")
_ROTATE_RE = re.compile(r"^rotate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+)[\s,]+(-?[\d.]+))?\s*\)$")
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_TOKEN_RE = re.compile(r"[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

_PAINT_ATTRS = frozenset(
    {
        "fill",
        "fill-opacity",
        "opacity",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-dasharray",
        "stroke-linecap",
        "stroke-linejoin",
    }
)
_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "svg": frozenset({"width", "height", "viewBox", "font-family", "font-size"}),
    "svg-nested": frozenset({"x", "y", "width", "height", "viewBox"}),
    "defs": frozenset(),
    "clipPath": frozenset({"id"}),
    "clip-rect": frozenset({"x", "y", "width", "height"}),
    "linearGradient": frozenset({"id", "x1", "y1", "x2", "y2", "gradientUnits"}),
    "stop": frozenset({"offset", "stop-color", "stop-opacity"}),
    "g": frozenset({"clip-path", "fill", "fill-opacity", "stroke-opacity", "opacity"}),
    "rect": frozenset({"x", "y", "width", "height", "rx"}) | _PAINT_ATTRS,
    "circle": frozenset({"cx", "cy", "r"}) | _PAINT_ATTRS,
    "line": frozenset({"x1", "y1", "x2", "y2"}) | _PAINT_ATTRS,
    "path": frozenset({"d"}) | _PAINT_ATTRS,
    "polyline": frozenset({"points"}) | _PAINT_ATTRS,
    "polygon": frozenset({"points"}) | _PAINT_ATTRS,
    "text": frozenset(
        {"x", "y", "transform", "text-anchor", "font-size", "font-weight", "fill", "fill-opacity"}
    ),
    "tspan": frozenset({"x", "y"}),
    "image": frozenset({"x", "y", "width", "height", "preserveAspectRatio", "style", "href"}),
}


# ---------------------------------------------------------------------------
# Path data (M/L/C/A/H/V/Z, absolute — the only commands the generator emits)
# ---------------------------------------------------------------------------


def _arc_cubics(
    x1: float,
    y1: float,
    rx: float,
    ry: float,
    phi_deg: float,
    large: bool,
    sweep: bool,
    x2: float,
    y2: float,
) -> list[tuple[float, ...]]:
    """SVG endpoint arc -> cubic Bézier segments (W3C implementation notes)."""
    if rx == 0 or ry == 0 or (x1 == x2 and y1 == y2):
        return [(x2, y2)]  # degenerate: straight line
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cosp, sinp = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cosp * dx2 + sinp * dy2
    y1p = -sinp * dx2 + cosp * dy2
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = cosp * cxp - sinp * cyp + (x1 + x2) / 2.0
    cy = sinp * cxp + cosp * cyp + (y1 + y2) / 2.0

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        a = math.acos(max(-1.0, min(1.0, dot / norm))) if norm else 0.0
        return -a if ux * vy - uy * vx < 0 else a

    theta1 = angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry) % (
        2 * math.pi
    )
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi

    n = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2))))
    out: list[tuple[float, ...]] = []
    step = dtheta / n
    for i in range(n):
        t0 = theta1 + i * step
        t1 = theta1 + (i + 1) * step
        alpha = 4.0 / 3.0 * math.tan((t1 - t0) / 4.0)

        def point(t: float) -> tuple[float, float]:
            ct, st = math.cos(t), math.sin(t)
            return (
                cx + rx * ct * cosp - ry * st * sinp,
                cy + rx * ct * sinp + ry * st * cosp,
            )

        def deriv(t: float) -> tuple[float, float]:
            ct, st = math.cos(t), math.sin(t)
            return (
                -rx * st * cosp - ry * ct * sinp,
                -rx * st * sinp + ry * ct * cosp,
            )

        p0x, p0y = point(t0)
        p1x, p1y = point(t1)
        d0x, d0y = deriv(t0)
        d1x, d1y = deriv(t1)
        out.append(
            (
                p0x + alpha * d0x,
                p0y + alpha * d0y,
                p1x - alpha * d1x,
                p1y - alpha * d1y,
                p1x,
                p1y,
            )
        )
    return out


def _parse_path(d: str) -> list[tuple]:
    """Parse the generator's absolute path subset into ("M"|"L"|"C"|"Z", ...)."""
    tokens = _PATH_TOKEN_RE.findall(d)
    segs: list[tuple] = []
    i = 0
    cx = cy = 0.0
    cmd: Optional[str] = None

    def take(n: int) -> list[float]:
        nonlocal i
        if i + n > len(tokens) or any(tokens[j].isalpha() for j in range(i, i + n)):
            _unsupported(f"path data {d[:40]!r}")
        vals = [float(t) for t in tokens[i : i + n]]
        i += n
        return vals

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            if tok not in ("M", "L", "C", "A", "H", "V", "Z"):
                _unsupported(f"path command {tok!r}")
            cmd = tok
            i += 1
            if cmd == "Z":
                segs.append(("Z",))
                cmd = None
            continue
        if cmd is None:
            _unsupported(f"path data {d[:40]!r}")
        if cmd == "M":
            cx, cy = take(2)
            segs.append(("M", cx, cy))
            cmd = "L"  # implicit repetition after moveto is lineto (SVG spec)
        elif cmd == "L":
            cx, cy = take(2)
            segs.append(("L", cx, cy))
        elif cmd == "H":
            (cx,) = take(1)
            segs.append(("L", cx, cy))
        elif cmd == "V":
            (cy,) = take(1)
            segs.append(("L", cx, cy))
        elif cmd == "C":
            c1x, c1y, c2x, c2y, cx, cy = take(6)
            segs.append(("C", c1x, c1y, c2x, c2y, cx, cy))
        else:  # A
            rx, ry, rot, large, sweep, ex, ey = take(7)
            for piece in _arc_cubics(cx, cy, rx, ry, rot, bool(large), bool(sweep), ex, ey):
                if len(piece) == 2:
                    segs.append(("L", *piece))
                else:
                    segs.append(("C", *piece))
            cx, cy = ex, ey
    return segs


def _segments_bbox(segs: list[tuple]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    px = py = 0.0
    for seg in segs:
        if seg[0] in ("M", "L"):
            px, py = seg[1], seg[2]
            xs.append(px)
            ys.append(py)
        elif seg[0] == "C":
            x0, y0 = px, py
            c1x, c1y, c2x, c2y, ex, ey = seg[1:]
            for t in (0.25, 0.5, 0.75):  # deterministic samples: tight enough for gradients
                mt = 1 - t
                xs.append(mt**3 * x0 + 3 * mt * mt * t * c1x + 3 * mt * t * t * c2x + t**3 * ex)
                ys.append(mt**3 * y0 + 3 * mt * mt * t * c1y + 3 * mt * t * t * c2y + t**3 * ey)
            xs.append(ex)
            ys.append(ey)
            px, py = ex, ey
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _rect_segments(x: float, y: float, w: float, h: float, rx: float) -> list[tuple]:
    if rx <= 0:
        return [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
    r = min(rx, w / 2.0, h / 2.0)
    k = _KAPPA * r
    return [
        ("M", x + r, y),
        ("L", x + w - r, y),
        ("C", x + w - r + k, y, x + w, y + r - k, x + w, y + r),
        ("L", x + w, y + h - r),
        ("C", x + w, y + h - r + k, x + w - r + k, y + h, x + w - r, y + h),
        ("L", x + r, y + h),
        ("C", x + r - k, y + h, x, y + h - r + k, x, y + h - r),
        ("L", x, y + r),
        ("C", x, y + r - k, x + r - k, y, x + r, y),
        ("Z",),
    ]


def _circle_segments(cx: float, cy: float, r: float) -> list[tuple]:
    k = _KAPPA * r
    return [
        ("M", cx + r, cy),
        ("C", cx + r, cy + k, cx + k, cy + r, cx, cy + r),
        ("C", cx - k, cy + r, cx - r, cy + k, cx - r, cy),
        ("C", cx - r, cy - k, cx - k, cy - r, cx, cy - r),
        ("C", cx + k, cy - r, cx + r, cy - k, cx + r, cy),
        ("Z",),
    ]


def _parse_points(points: str) -> list[tuple[float, float]]:
    values = [float(v) for v in _NUMBER_RE.findall(points)]
    if len(values) % 2:
        _unsupported(f"points list {points[:40]!r}")
    return list(zip(values[0::2], values[1::2], strict=True))


# ---------------------------------------------------------------------------
# Embedded PNG decode (xy._png output: truecolor RGBA8 or indexed+tRNS)
# ---------------------------------------------------------------------------


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(arr: np.ndarray, h: int, stride: int, bpp: int) -> np.ndarray:
    recon = np.empty((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    for r in range(h):
        ftype = int(arr[r * (stride + 1)])
        line = arr[r * (stride + 1) + 1 : (r + 1) * (stride + 1)].astype(np.int32)
        if ftype == 0:
            cur = line
        elif ftype == 2:  # Up
            cur = (line + prev) & 0xFF
        elif ftype == 1:  # Sub
            cur = line
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ftype == 3:  # Average
            cur = line
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            cur = line
            for i in range(stride):
                left = int(cur[i - bpp]) if i >= bpp else 0
                upleft = int(prev[i - bpp]) if i >= bpp else 0
                cur[i] = (cur[i] + _paeth(left, int(prev[i]), upleft)) & 0xFF
        else:
            _unsupported(f"PNG filter type {ftype}")
        recon[r] = cur.astype(np.uint8)
        prev = cur
    return recon


def _decode_png(data: bytes) -> tuple[int, int, bytes, Optional[bytes]]:
    """Decode an embedded PNG to (w, h, rgb_bytes, alpha_bytes_or_None)."""
    if data[:8] != _PNG_SIG:
        _unsupported("embedded image is not a PNG")
    pos = 8
    ihdr = b""
    idat: list[bytes] = []
    plte = b""
    trns = b""
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            ihdr = body
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"PLTE":
            plte = body
        elif tag == b"tRNS":
            trns = body
        elif tag == b"IEND":
            break
    if len(ihdr) != 13:
        _unsupported("embedded PNG missing IHDR")
    w, h, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(">IIBBBBB", ihdr)
    if bit_depth != 8 or interlace != 0 or color_type not in (3, 6):
        _unsupported(f"embedded PNG color type {color_type}/depth {bit_depth}")
    bpp = 4 if color_type == 6 else 1
    stride = w * bpp
    raw = np.frombuffer(zlib.decompress(b"".join(idat)), dtype=np.uint8)
    if len(raw) != h * (stride + 1):
        _unsupported("embedded PNG payload size")
    recon = _unfilter(raw, h, stride, bpp)
    if color_type == 6:
        px = recon.reshape(h, w, 4)
        rgb = np.ascontiguousarray(px[:, :, :3])
        alpha = np.ascontiguousarray(px[:, :, 3])
    else:
        palette = np.frombuffer(plte, dtype=np.uint8).reshape(-1, 3)
        pal_alpha = np.full(len(palette), 255, dtype=np.uint8)
        trns_arr = np.frombuffer(trns, dtype=np.uint8)
        pal_alpha[: len(trns_arr)] = trns_arr[: len(palette)]
        idx = recon.reshape(h, w)
        if int(idx.max(initial=0)) >= len(palette):
            _unsupported("embedded PNG palette index out of range")
        rgb = np.ascontiguousarray(palette[idx])
        alpha = np.ascontiguousarray(pal_alpha[idx])
    alpha_bytes = None if int(alpha.min(initial=255)) == 255 else alpha.tobytes()
    return int(w), int(h), rgb.tobytes(), alpha_bytes


# ---------------------------------------------------------------------------
# PDF object store (deterministic numbering: 1..4 fixed, resources from 5)
# ---------------------------------------------------------------------------


class _Pdf:
    def __init__(self) -> None:
        self.objects: dict[int, bytes] = {}
        self._next = 5

    def reserve(self) -> int:
        num = self._next
        self._next += 1
        return num

    def put(self, num: int, body: str) -> None:
        self.objects[num] = f"{num} 0 obj\n{body}\nendobj\n".encode("ascii")

    def put_stream(self, num: int, extra: str, payload: bytes) -> None:
        data = zlib.compress(payload)
        head = f"{num} 0 obj\n<< {extra}/Length {len(data)} /Filter /FlateDecode >>\nstream\n"
        self.objects[num] = head.encode("ascii") + data + b"\nendstream\nendobj\n"

    def serialize(self) -> bytes:
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        numbers = sorted(self.objects)
        offsets: dict[int, int] = {}
        for num in numbers:
            offsets[num] = len(out)
            out += self.objects[num]
        xref_pos = len(out)
        size = numbers[-1] + 1
        out += f"xref\n0 {size}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for num in range(1, size):
            out += f"{offsets[num]:010d} 00000 n \n".encode("ascii")
        out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
        return bytes(out)


class _State:
    """Inheritable presentation state (override semantics, like CSS)."""

    __slots__ = ("fill", "fill_opacity", "font_size", "font_weight", "opacity", "stroke_opacity")

    def __init__(self) -> None:
        self.fill = "#000000"
        self.fill_opacity = 1.0
        self.stroke_opacity = 1.0
        self.opacity = 1.0
        self.font_size = _DEFAULT_FONT_SIZE
        self.font_weight = 400.0

    def child(self) -> "_State":
        out = _State.__new__(_State)
        for name in _State.__slots__:
            setattr(out, name, getattr(self, name))
        return out


def _weight(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    if value == "bold":
        return 700.0
    if value == "normal":
        return 400.0
    return _float(value, default, "font-weight")


def _grad_fraction(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    v = value.strip()
    if v.endswith("%"):
        return _float(v[:-1], default, "gradient coordinate") / 100.0
    return _float(v, default, "gradient coordinate")


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------


class _Converter:
    def __init__(self) -> None:
        self.pdf = _Pdf()
        self.ops: list[str] = []
        self.clips: dict[str, tuple[float, float, float, float]] = {}
        self.gradients: dict[str, dict[str, Any]] = {}
        self.fonts: dict[str, tuple[str, int]] = {}  # basefont -> (resname, obj)
        self.gstates: dict[tuple, tuple[str, int]] = {}
        self.shadings: dict[tuple, tuple[str, int, bool]] = {}
        self.smask_forms: dict[tuple, int] = {}
        self.images: list[tuple[str, int]] = []
        self._cache_stack: list[dict[str, Any]] = [{}]

    # -- content-stream state cache ---------------------------------------

    @property
    def _cache(self) -> dict[str, Any]:
        return self._cache_stack[-1]

    def _push(self) -> None:
        self.ops.append("q")
        self._cache_stack.append(dict(self._cache))

    def _pop(self) -> None:
        self.ops.append("Q")
        self._cache_stack.pop()

    def _set(self, key: str, value: Any, op: str) -> None:
        if self._cache.get(key) != value:
            self.ops.append(op)
            self._cache[key] = value

    def _set_gs(self, ca: float, CA: float) -> None:  # noqa: N803 — PDF operand name
        name = self._gs_plain(ca, CA)
        self._set("gs", name, f"/{name} gs")

    def _set_fill_rgb(self, rgb: tuple[float, float, float]) -> None:
        key = tuple(round(v, 4) for v in rgb)
        self._set("fill_rgb", key, f"{_f(rgb[0])} {_f(rgb[1])} {_f(rgb[2])} rg")

    def _set_stroke_rgb(self, rgb: tuple[float, float, float]) -> None:
        key = tuple(round(v, 4) for v in rgb)
        self._set("stroke_rgb", key, f"{_f(rgb[0])} {_f(rgb[1])} {_f(rgb[2])} RG")

    def _set_stroke_params(
        self, width: float, cap: int, join: int, dash: Optional[list[float]]
    ) -> None:
        self._set("w", round(width, 4), f"{_f(width)} w")
        self._set("J", cap, f"{cap} J")
        self._set("j", join, f"{join} j")
        dash_key = tuple(round(v, 4) for v in dash) if dash else ()
        dash_op = f"[{' '.join(_f(v) for v in dash)}] 0 d" if dash else "[] 0 d"
        self._set("d", dash_key, dash_op)

    # -- resource registration ---------------------------------------------

    def _font(self, bold: bool) -> str:
        base = "Helvetica-Bold" if bold else "Helvetica"
        if base not in self.fonts:
            num = self.pdf.reserve()
            name = f"F{len(self.fonts) + 1}"
            self.pdf.put(
                num,
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>",
            )
            self.fonts[base] = (name, num)
        return self.fonts[base][0]

    def _gs_plain(self, ca: float, CA: float) -> str:  # noqa: N803
        key = ("plain", round(ca, 4), round(CA, 4))
        if key not in self.gstates:
            num = self.pdf.reserve()
            name = f"G{len(self.gstates) + 1}"
            self.pdf.put(num, f"<< /Type /ExtGState /ca {_f(ca)} /CA {_f(CA)} >>")
            self.gstates[key] = (name, num)
        return self.gstates[key][0]

    @staticmethod
    def _function_dict(stops: list[tuple[float, tuple[float, ...]]]) -> str:
        """Type 2 exponential (2 stops) or Type 3 stitching (>2) function."""

        def vals(v: tuple[float, ...]) -> str:
            return " ".join(_f(c) for c in v)

        if len(stops) == 2:
            return (
                f"<< /FunctionType 2 /Domain [0 1] /C0 [{vals(stops[0][1])}] "
                f"/C1 [{vals(stops[1][1])}] /N 1 >>"
            )
        pieces = [
            f"<< /FunctionType 2 /Domain [0 1] /C0 [{vals(v0)}] /C1 [{vals(v1)}] /N 1 >>"
            for (_t0, v0), (_t1, v1) in pairwise(stops)
        ]
        bounds = " ".join(_f(t) for t, _v in stops[1:-1])
        encode = " ".join(["0 1"] * len(pieces))
        return (
            f"<< /FunctionType 3 /Domain [0 1] /Functions [{' '.join(pieces)}] "
            f"/Bounds [{bounds}] /Encode [{encode}] >>"
        )

    @staticmethod
    def _normalize_stops(
        stops: list[tuple[float, tuple[float, ...]]],
    ) -> list[tuple[float, tuple[float, ...]]]:
        """Clamp to [0,1], enforce strictly increasing offsets, pad the ends."""
        out: list[tuple[float, tuple[float, ...]]] = []
        prev = -1.0
        for t, v in stops:
            t = min(1.0, max(0.0, t))
            if t <= prev:
                t = prev + 1e-4
                if t > 1.0:
                    continue  # cannot nudge past the end: drop (deterministic)
            out.append((t, v))
            prev = t
        if not out:
            out = [(0.0, stops[0][1]), (1.0, stops[-1][1])]
        if out[0][0] > 0.0:
            out.insert(0, (0.0, out[0][1]))
        if out[-1][0] < 1.0:
            out.append((1.0, out[-1][1]))
        if len(out) == 1:
            out.append((1.0, out[0][1]))
        return out

    def _shading(
        self,
        coords: tuple[float, float, float, float],
        stops: list[tuple[float, tuple[float, ...]]],
        gray: bool,
    ) -> tuple[str, int]:
        stops = self._normalize_stops(stops)
        key = (
            gray,
            tuple(round(c, 4) for c in coords),
            tuple((round(t, 6), tuple(round(c, 6) for c in v)) for t, v in stops),
        )
        if key not in self.shadings:
            num = self.pdf.reserve()
            name = f"Sh{len(self.shadings) + 1}"
            space = "/DeviceGray" if gray else "/DeviceRGB"
            coords_s = " ".join(_f(c) for c in coords)
            self.pdf.put(
                num,
                f"<< /ShadingType 2 /ColorSpace {space} /Coords [{coords_s}] "
                f"/Extend [true true] /Function {self._function_dict(stops)} >>",
            )
            self.shadings[key] = (name, num, gray)
        return self.shadings[key][0], self.shadings[key][1]

    def _gs_gradient(
        self,
        coords: tuple[float, float, float, float],
        alpha_stops: list[tuple[float, tuple[float, ...]]],
        bbox: tuple[float, float, float, float],
        ca: float,
    ) -> str:
        """ExtGState with a luminosity soft mask carrying the stop alphas."""
        gray_name, gray_num = self._shading(coords, alpha_stops, gray=True)
        form_key = (gray_num, tuple(round(v, 4) for v in bbox))
        if form_key not in self.smask_forms:
            form_num = self.pdf.reserve()
            bbox_s = " ".join(_f(v) for v in (bbox[0], bbox[1], bbox[2], bbox[3]))
            self.pdf.put_stream(
                form_num,
                f"/Type /XObject /Subtype /Form /BBox [{bbox_s}] "
                f"/Group << /S /Transparency /CS /DeviceGray >> "
                f"/Resources << /Shading << /{gray_name} {gray_num} 0 R >> >> ",
                f"/{gray_name} sh".encode("ascii"),
            )
            self.smask_forms[form_key] = form_num
        form_num = self.smask_forms[form_key]
        key = ("smask", form_num, round(ca, 4))
        if key not in self.gstates:
            num = self.pdf.reserve()
            name = f"G{len(self.gstates) + 1}"
            self.pdf.put(
                num,
                f"<< /Type /ExtGState /ca {_f(ca)} /CA {_f(ca)} "
                f"/SMask << /S /Luminosity /G {form_num} 0 R >> >>",
            )
            self.gstates[key] = (name, num)
        return self.gstates[key][0]

    def _image_xobject(self, w: int, h: int, rgb: bytes, alpha: Optional[bytes]) -> str:
        smask_ref = ""
        if alpha is not None:
            smask_num = self.pdf.reserve()
            self.pdf.put_stream(
                smask_num,
                f"/Type /XObject /Subtype /Image /Width {w} /Height {h} "
                f"/ColorSpace /DeviceGray /BitsPerComponent 8 /Interpolate false ",
                alpha,
            )
            smask_ref = f"/SMask {smask_num} 0 R "
        num = self.pdf.reserve()
        self.pdf.put_stream(
            num,
            f"/Type /XObject /Subtype /Image /Width {w} /Height {h} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Interpolate false {smask_ref}",
            rgb,
        )
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, num))
        return name

    # -- defs collection ----------------------------------------------------

    def _collect_defs(self, root: ET.Element) -> None:
        for el in root.iter():
            tag = _local(el.tag)
            if tag == "clipPath":
                _check_attrs(el, tag, _ALLOWED_ATTRS["clipPath"])
                cid = el.get("id")
                children = list(el)
                if cid is None or len(children) != 1 or _local(children[0].tag) != "rect":
                    _unsupported("<clipPath> without a single <rect>")
                rect = children[0]
                _check_attrs(rect, "clipPath rect", _ALLOWED_ATTRS["clip-rect"])
                self.clips[cid] = (
                    _float(rect.get("x"), 0.0, "clip x"),
                    _float(rect.get("y"), 0.0, "clip y"),
                    _float(rect.get("width"), 0.0, "clip width"),
                    _float(rect.get("height"), 0.0, "clip height"),
                )
            elif tag == "linearGradient":
                _check_attrs(el, tag, _ALLOWED_ATTRS["linearGradient"])
                gid = el.get("id")
                if gid is None:
                    _unsupported("<linearGradient> without id")
                units = el.get("gradientUnits", "objectBoundingBox")
                if units not in ("objectBoundingBox", "userSpaceOnUse"):
                    _unsupported(f"gradientUnits {units!r}")
                stops: list[tuple[float, tuple[float, float, float], float]] = []
                for stop in el:
                    if _local(stop.tag) != "stop":
                        _unsupported(f"<linearGradient> child <{_local(stop.tag)}>")
                    _check_attrs(stop, "stop", _ALLOWED_ATTRS["stop"])
                    offset = _grad_fraction(stop.get("offset"), 0.0)
                    red, green, blue, alpha = _rgba(stop.get("stop-color", "#000000"))
                    alpha *= _float(stop.get("stop-opacity"), 1.0, "stop-opacity")
                    stops.append((offset, (red, green, blue), alpha))
                if not stops:
                    _unsupported("<linearGradient> without stops")
                self.gradients[gid] = {
                    "units": units,
                    "x1": el.get("x1"),
                    "y1": el.get("y1"),
                    "x2": el.get("x2"),
                    "y2": el.get("y2"),
                    "stops": stops,
                }

    # -- painting -----------------------------------------------------------

    def _emit_segments(self, segs: list[tuple]) -> None:
        for seg in segs:
            if seg[0] == "M":
                self.ops.append(f"{_f(seg[1])} {_f(seg[2])} m")
            elif seg[0] == "L":
                self.ops.append(f"{_f(seg[1])} {_f(seg[2])} l")
            elif seg[0] == "C":
                self.ops.append(" ".join(_f(v) for v in seg[1:]) + " c")
            else:
                self.ops.append("h")

    def _resolve_paint(self, raw: Optional[str]) -> Optional[tuple[str, Any]]:
        if raw is None or raw.strip() == "none":
            return None
        m = _URL_RE.match(raw.strip())
        if m:
            gid = m.group(1)
            if gid not in self.gradients:
                _unsupported(f"paint reference {raw!r}")
            return ("gradient", gid)
        return ("solid", _rgba(raw))

    def _gradient_coords(
        self, grad: dict[str, Any], bbox: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        if grad["units"] == "userSpaceOnUse":
            return (
                _float(grad["x1"], 0.0, "gradient x1"),
                _float(grad["y1"], 0.0, "gradient y1"),
                _float(grad["x2"], 1.0, "gradient x2"),
                _float(grad["y2"], 0.0, "gradient y2"),
            )
        x0, y0, x1, y1 = bbox
        fx1 = _grad_fraction(grad["x1"], 0.0)
        fy1 = _grad_fraction(grad["y1"], 0.0)
        fx2 = _grad_fraction(grad["x2"], 1.0)
        fy2 = _grad_fraction(grad["y2"], 0.0)
        return (
            x0 + fx1 * (x1 - x0),
            y0 + fy1 * (y1 - y0),
            x0 + fx2 * (x1 - x0),
            y0 + fy2 * (y1 - y0),
        )

    def _paint_gradient_fill(self, segs: list[tuple], gid: str, ca: float) -> None:
        grad = self.gradients[gid]
        bbox = _segments_bbox(segs)
        coords = self._gradient_coords(grad, bbox)
        color_stops = [(t, rgb) for t, rgb, _a in grad["stops"]]
        name, _num = self._shading(coords, color_stops, gray=False)
        has_alpha = any(a < 1.0 for _t, _rgb, a in grad["stops"])
        self._push()
        self._emit_segments(segs)
        self.ops.append("W n")
        if has_alpha:
            alpha_stops: list[tuple[float, tuple[float, ...]]] = [
                (t, (a,)) for t, _rgb, a in grad["stops"]
            ]
            gs = self._gs_gradient(coords, alpha_stops, bbox, ca)
            self._set("gs", gs, f"/{gs} gs")
        else:
            self._set_gs(ca, ca)
        self.ops.append(f"/{name} sh")
        self._pop()

    def _render_shape(self, el: ET.Element, tag: str, state: _State) -> None:
        _check_attrs(el, tag, _ALLOWED_ATTRS[tag])
        segs: list[tuple]
        if tag == "rect":
            x = _float(el.get("x"), 0.0, "x")
            y = _float(el.get("y"), 0.0, "y")
            w = _float(el.get("width"), 0.0, "width")
            h = _float(el.get("height"), 0.0, "height")
            rx = _float(el.get("rx"), 0.0, "rx")
            segs = _rect_segments(x, y, w, h, rx)
            fillable = True
        elif tag == "circle":
            segs = _circle_segments(
                _float(el.get("cx"), 0.0, "cx"),
                _float(el.get("cy"), 0.0, "cy"),
                _float(el.get("r"), 0.0, "r"),
            )
            fillable = True
        elif tag == "line":
            x1 = _float(el.get("x1"), 0.0, "x1")
            y1 = _float(el.get("y1"), 0.0, "y1")
            x2 = _float(el.get("x2"), 0.0, "x2")
            y2 = _float(el.get("y2"), 0.0, "y2")
            segs = [("M", x1, y1), ("L", x2, y2)]
            fillable = False
        elif tag == "path":
            d = el.get("d")
            if d is None:
                _unsupported("<path> without d")
            segs = _parse_path(d)
            fillable = True
        else:  # polyline / polygon
            points = el.get("points")
            if points is None:
                _unsupported(f"<{tag}> without points")
            pts = _parse_points(points)
            if not pts:
                return
            segs = [("M", *pts[0])] + [("L", *p) for p in pts[1:]]
            if tag == "polygon":
                segs.append(("Z",))
            fillable = True

        opacity = state.opacity * _float(el.get("opacity"), 1.0, "opacity")
        fill_op = opacity * _float(el.get("fill-opacity"), state.fill_opacity, "fill-opacity")
        stroke_op = opacity * _float(
            el.get("stroke-opacity"), state.stroke_opacity, "stroke-opacity"
        )
        fill = self._resolve_paint(el.get("fill", state.fill)) if fillable else None
        stroke = self._resolve_paint(el.get("stroke"))
        stroke_width = _float(el.get("stroke-width"), 1.0, "stroke-width")
        if stroke is not None and stroke[0] == "gradient":
            _unsupported("gradient stroke")
        do_stroke = stroke is not None and stroke_width > 0

        cap_name = el.get("stroke-linecap", "butt")
        join_name = el.get("stroke-linejoin", "miter")
        caps = {"butt": 0, "round": 1, "square": 2}
        joins = {"miter": 0, "round": 1, "bevel": 2}
        if cap_name not in caps:
            _unsupported(f"stroke-linecap {cap_name!r}")
        if join_name not in joins:
            _unsupported(f"stroke-linejoin {join_name!r}")
        dash_raw = el.get("stroke-dasharray")
        dash = [float(v) for v in _NUMBER_RE.findall(dash_raw)] if dash_raw else None
        if dash is not None and not any(v > 0 for v in dash):
            dash = None

        if fill is not None and fill[0] == "gradient":
            self._paint_gradient_fill(segs, fill[1], fill_op)
            fill = None  # gradient already painted; a stroke pass may follow

        if fill is None and not do_stroke:
            return
        ca = 1.0
        if fill is not None:
            red, green, blue, alpha = fill[1]
            ca = fill_op * alpha
            self._set_fill_rgb((red, green, blue))
        CA = 1.0  # noqa: N806 — PDF operand name
        if do_stroke:
            red, green, blue, alpha = stroke[1]
            CA = stroke_op * alpha  # noqa: N806
            self._set_stroke_rgb((red, green, blue))
            self._set_stroke_params(stroke_width, caps[cap_name], joins[join_name], dash)
        self._set_gs(ca, CA)
        self._emit_segments(segs)
        self.ops.append("B" if (fill is not None and do_stroke) else ("f" if fill else "S"))

    # -- text ---------------------------------------------------------------

    def _render_text(self, el: ET.Element, state: _State) -> None:
        _check_attrs(el, "text", _ALLOWED_ATTRS["text"])
        font_size = _float(el.get("font-size"), state.font_size, "font-size")
        bold = _weight(el.get("font-weight"), state.font_weight) >= 600
        anchor = el.get("text-anchor", "start")
        if anchor not in ("start", "middle", "end"):
            _unsupported(f"text-anchor {anchor!r}")
        fill = self._resolve_paint(el.get("fill", state.fill))
        if fill is None or fill[0] != "solid":
            _unsupported("text fill paint")
        red, green, blue, alpha = fill[1]
        ca = (
            state.opacity
            * _float(el.get("fill-opacity"), state.fill_opacity, "fill-opacity")
            * alpha
        )

        angle = 0.0
        center: Optional[tuple[float, float]] = None
        transform = el.get("transform")
        if transform is not None:
            m = _ROTATE_RE.match(transform.strip())
            if m is None:
                _unsupported(f"transform {transform!r}")
            angle = float(m.group(1))
            if m.group(2) is not None:
                center = (float(m.group(2)), float(m.group(3)))

        runs: list[tuple[float, float, str]] = []
        tspans = list(el)
        if tspans:
            if el.text and el.text.strip():
                _unsupported("<text> mixing direct text and <tspan>")
            for ts in tspans:
                if _local(ts.tag) != "tspan":
                    _unsupported(f"<text> child <{_local(ts.tag)}>")
                _check_attrs(ts, "tspan", _ALLOWED_ATTRS["tspan"])
                if list(ts):
                    _unsupported("nested <tspan>")
                runs.append(
                    (
                        _float(ts.get("x"), 0.0, "tspan x"),
                        _float(ts.get("y"), 0.0, "tspan y"),
                        ts.text or "",
                    )
                )
        else:
            runs.append(
                (_float(el.get("x"), 0.0, "x"), _float(el.get("y"), 0.0, "y"), el.text or "")
            )

        font_name = self._font(bold)
        theta = math.radians(angle)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        for x, y, s in runs:
            # Non-WinAnsi characters become "?" — deterministic replacement.
            data = s.encode("cp1252", "replace")
            if not data:
                continue
            if center is not None:
                cx, cy = center
                x, y = (
                    cx + cos_t * (x - cx) - sin_t * (y - cy),
                    cy + sin_t * (x - cx) + cos_t * (y - cy),
                )
            width = _text_width_px(data, font_size, bold)
            dx = -width / 2.0 if anchor == "middle" else (-width if anchor == "end" else 0.0)
            tx = x + dx * cos_t
            ty = y + dx * sin_t
            self._set_gs(ca, ca)
            self._set_fill_rgb((red, green, blue))
            # Tm un-flips the top-level y flip so glyphs render upright; the
            # rotation is the SVG angle (clockwise in screen space).
            self.ops.append("BT")
            self.ops.append(f"/{font_name} {_f(font_size)} Tf")
            self.ops.append(
                f"{_f(cos_t)} {_f(sin_t)} {_f(sin_t)} {_f(-cos_t)} {_f(tx)} {_f(ty)} Tm"
            )
            self.ops.append(f"{_pdf_string(data)} Tj")
            self.ops.append("ET")

    # -- images -------------------------------------------------------------

    def _render_image(self, el: ET.Element, state: _State) -> None:
        _check_attrs(el, "image", _ALLOWED_ATTRS["image"])
        if el.get("preserveAspectRatio", "none") != "none":
            _unsupported(f"preserveAspectRatio {el.get('preserveAspectRatio')!r}")
        style = (el.get("style") or "").strip().rstrip(";")
        if style not in ("", "image-rendering:pixelated"):
            _unsupported(f"<image> style {style!r}")
        href = el.get("href") or ""
        prefix = "data:image/png;base64,"
        if not href.startswith(prefix):
            _unsupported("<image> href (only embedded base64 PNG)")
        w_px, h_px, rgb, alpha = _decode_png(base64.b64decode(href[len(prefix) :]))
        name = self._image_xobject(w_px, h_px, rgb, alpha)
        x = _float(el.get("x"), 0.0, "x")
        y = _float(el.get("y"), 0.0, "y")
        w = _float(el.get("width"), 0.0, "width")
        h = _float(el.get("height"), 0.0, "height")
        self._push()
        ca = state.opacity
        if ca < 1.0:
            self._set_gs(ca, ca)
        # Negative height keeps PNG row 0 at the top under the global y flip.
        self.ops.append(f"{_f(w)} 0 0 {_f(-h)} {_f(x)} {_f(y + h)} cm")
        self.ops.append(f"/{name} Do")
        self._pop()

    # -- structure ----------------------------------------------------------

    def _render_g(self, el: ET.Element, state: _State) -> None:
        _check_attrs(el, "g", _ALLOWED_ATTRS["g"])
        child = state.child()
        fill = el.get("fill")
        if fill is not None:
            child.fill = fill
        child.fill_opacity = _float(el.get("fill-opacity"), state.fill_opacity, "fill-opacity")
        child.stroke_opacity = _float(
            el.get("stroke-opacity"), state.stroke_opacity, "stroke-opacity"
        )
        child.opacity = state.opacity * _float(el.get("opacity"), 1.0, "opacity")
        clip_ref = el.get("clip-path")
        clipped = False
        if clip_ref is not None:
            m = _URL_RE.match(clip_ref.strip())
            if m is None or m.group(1) not in self.clips:
                _unsupported(f"clip-path {clip_ref!r}")
            x, y, w, h = self.clips[m.group(1)]
            self._push()
            self.ops.append(f"{_f(x)} {_f(y)} {_f(w)} {_f(h)} re")
            self.ops.append("W n")
            clipped = True
        self._render_children(el, child)
        if clipped:
            self._pop()

    def _render_nested_svg(self, el: ET.Element, state: _State) -> None:
        _check_attrs(el, "svg", _ALLOWED_ATTRS["svg-nested"])
        x = _float(el.get("x"), 0.0, "x")
        y = _float(el.get("y"), 0.0, "y")
        w = _float(el.get("width"), 0.0, "width")
        h = _float(el.get("height"), 0.0, "height")
        vb = [float(v) for v in _NUMBER_RE.findall(el.get("viewBox") or "")]
        if len(vb) != 4 or vb[0] != 0 or vb[1] != 0 or vb[2] <= 0 or vb[3] <= 0:
            _unsupported(f"viewBox {el.get('viewBox')!r}")
        sx, sy = w / vb[2], h / vb[3]
        self._push()
        self.ops.append(f"{_f(sx)} 0 0 {_f(sy)} {_f(x)} {_f(y)} cm")
        # Nested viewports clip to their bounds (SVG overflow:hidden default).
        self.ops.append(f"0 0 {_f(vb[2])} {_f(vb[3])} re")
        self.ops.append("W n")
        self._render_children(el, state.child())
        self._pop()

    def _render_children(self, el: ET.Element, state: _State) -> None:
        for child in el:
            self._render_element(child, state)
            if child.tail and child.tail.strip():
                _unsupported("stray text content")

    def _render_element(self, el: ET.Element, state: _State) -> None:
        tag = _local(el.tag)
        if tag in ("defs", "clipPath", "linearGradient"):
            return  # definitions were collected up front; never painted
        if tag == "g":
            self._render_g(el, state)
        elif tag in ("rect", "circle", "line", "path", "polyline", "polygon"):
            if el.text and el.text.strip():
                _unsupported("stray text content")
            self._render_shape(el, tag, state)
        elif tag == "text":
            self._render_text(el, state)
        elif tag == "image":
            self._render_image(el, state)
        elif tag == "svg":
            self._render_nested_svg(el, state)
        else:
            _unsupported(f"<{tag}>")
        if tag in ("g", "svg") and el.text and el.text.strip():
            _unsupported("stray text content")

    # -- document assembly ---------------------------------------------------

    def run(self, root: ET.Element) -> bytes:
        if _local(root.tag) != "svg":
            _unsupported(f"root <{_local(root.tag)}>")
        _check_attrs(root, "svg", _ALLOWED_ATTRS["svg"])
        width = _float(root.get("width"), -1.0, "svg width")
        height = _float(root.get("height"), -1.0, "svg height")
        if width <= 0 or height <= 0:
            _unsupported("svg without positive pixel width/height")
        vb = [float(v) for v in _NUMBER_RE.findall(root.get("viewBox") or "")]
        if vb and (len(vb) != 4 or vb != [0.0, 0.0, width, height]):
            _unsupported(f"root viewBox {root.get('viewBox')!r}")

        self._collect_defs(root)

        state = _State()
        state.font_size = _float(root.get("font-size"), _DEFAULT_FONT_SIZE, "font-size")

        page_w = width * _PX_TO_PT
        page_h = height * _PX_TO_PT
        self._push()
        # 1 CSS px = 0.75 pt; the negative d flips SVG y-down to PDF y-up.
        self.ops.append(f"{_f(_PX_TO_PT)} 0 0 {_f(-_PX_TO_PT)} 0 {_f(page_h)} cm")
        if root.text and root.text.strip():
            _unsupported("stray text content")
        self._render_children(root, state)
        self._pop()

        content = "\n".join(self.ops).encode("ascii")
        pdf = self.pdf
        pdf.put(1, "<< /Type /Catalog /Pages 2 0 R >>")
        pdf.put(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        resources: list[str] = []
        if self.fonts:
            entries = " ".join(f"/{name} {num} 0 R" for name, num in self.fonts.values())
            resources.append(f"/Font << {entries} >>")
        if self.gstates:
            entries = " ".join(f"/{name} {num} 0 R" for name, num in self.gstates.values())
            resources.append(f"/ExtGState << {entries} >>")
        color_shadings = [(n, num) for n, num, gray in self.shadings.values() if not gray]
        if color_shadings:
            entries = " ".join(f"/{name} {num} 0 R" for name, num in color_shadings)
            resources.append(f"/Shading << {entries} >>")
        if self.images:
            entries = " ".join(f"/{name} {num} 0 R" for name, num in self.images)
            resources.append(f"/XObject << {entries} >>")
        pdf.put(
            3,
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_f(page_w)} {_f(page_h)}] "
            f"/Resources << {' '.join(resources)} >> /Contents 4 0 R >>",
        )
        pdf.put_stream(4, "", content)
        return pdf.serialize()


def svg_to_pdf(svg: str) -> bytes:
    """Convert an xy-generated SVG document into a single-page vector PDF.

    Raises ``ValueError("unsupported SVG feature: ...")`` for any element,
    attribute, or value outside the closed subset `xy._svg` emits.
    """
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(f"unsupported SVG feature: unparseable XML ({exc})") from None
    return _Converter().run(root)
