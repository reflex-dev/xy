"""Static SVG export — a pure-Python renderer over the same wire payload the
browser client consumes.

The decimation tiers make static export *screen-bounded*: `build_payload`
hands this module ≤4 line points per pixel column (M4) or a fixed density
grid, so a 100M-point figure exports as a few-hundred-KB, resolution-
independent SVG in milliseconds — no browser, no extra dependencies.

Layout, tick math, colormaps, and mark styling mirror the JS client
(`30_ticks.js`, `10_colormaps.js`, `50_chartview.js`); tests assert the
ported tables stay in sync with the JS parts. Known static-export
approximations, documented in docs/styling.md: area mark-space gradients use
the area's bounding box (SVG has no per-column gradient), and `var(--x)`
colors fall back to the mark color (no DOM to resolve against).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from os import PathLike
from typing import Any, Optional
from xml.sax.saxutils import escape

import numpy as np

from . import _png
from .config import DEFAULT_PALETTE

# Mirrors js/src/10_colormaps.js COLORMAP_STOPS (§36) — test-guarded.
COLORMAP_STOPS: dict[str, list[tuple[int, int, int]]] = {
    "viridis": [
        (68, 1, 84),
        (72, 40, 120),
        (62, 74, 137),
        (49, 104, 142),
        (38, 130, 142),
        (31, 158, 137),
        (53, 183, 121),
        (110, 206, 88),
        (181, 222, 43),
        (253, 231, 37),
    ],
    "magma": [
        (0, 0, 4),
        (28, 16, 68),
        (79, 18, 123),
        (129, 37, 129),
        (181, 54, 122),
        (229, 80, 100),
        (251, 135, 97),
        (254, 194, 135),
        (252, 253, 191),
        (252, 253, 191),
    ],
    "plasma": [
        (13, 8, 135),
        (84, 2, 163),
        (139, 10, 165),
        (185, 50, 137),
        (219, 92, 104),
        (244, 136, 73),
        (254, 188, 43),
        (240, 249, 33),
        (240, 249, 33),
        (240, 249, 33),
    ],
    "inferno": [
        (0, 0, 4),
        (31, 12, 72),
        (85, 15, 109),
        (136, 34, 106),
        (186, 54, 85),
        (227, 89, 51),
        (249, 140, 10),
        (249, 201, 50),
        (252, 255, 164),
        (252, 255, 164),
    ],
    "cividis": [
        (0, 32, 76),
        (0, 42, 102),
        (39, 63, 108),
        (72, 85, 115),
        (106, 109, 120),
        (143, 133, 118),
        (181, 159, 105),
        (223, 187, 82),
        (253, 217, 63),
        (255, 233, 69),
    ],
    "gray": [
        (0, 0, 0),
        (28, 28, 28),
        (57, 57, 57),
        (85, 85, 85),
        (113, 113, 113),
        (142, 142, 142),
        (170, 170, 170),
        (198, 198, 198),
        (227, 227, 227),
        (255, 255, 255),
    ],
    "turbo": [
        (48, 18, 59),
        (70, 107, 227),
        (40, 187, 226),
        (61, 242, 148),
        (161, 253, 60),
        (232, 216, 33),
        (253, 149, 35),
        (225, 66, 13),
        (153, 15, 4),
        (122, 4, 3),
    ],
    "coolwarm": [
        (59, 76, 192),
        (87, 117, 211),
        (119, 154, 231),
        (157, 185, 243),
        (197, 209, 246),
        (221, 220, 220),
        (242, 196, 174),
        (237, 158, 130),
        (214, 96, 77),
        (180, 4, 38),
    ],
}

# Light-theme chrome colors (the client derives these from currentColor).
_TEXT = "rgba(32,32,32,0.85)"
_GRID = "rgba(32,32,32,0.14)"
_AXIS = "rgba(32,32,32,0.55)"
_FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
_MS = {"s": 1e3, "m": 6e4, "h": 36e5, "d": 864e5}


# ---------------------------------------------------------------------------
# Tick math — ports of 30_ticks.js (f64 throughout, §16)
# ---------------------------------------------------------------------------


def _nice_step(rough: float) -> float:
    rough = abs(rough)
    if not np.isfinite(rough) or rough <= 0:
        return 1.0
    mag = 10.0 ** np.floor(np.log10(rough))
    for m in (1, 2, 5, 10):
        if rough <= m * mag * (1 + 1e-12):
            return m * mag
    return 10 * mag


def _linear_ticks(lo: float, hi: float, target: int = 6) -> tuple[list[float], float]:
    a, b = min(lo, hi), max(lo, hi)
    if not (np.isfinite(a) and np.isfinite(b)):
        return [], 1.0
    if a == b:
        return [a], 1.0
    step = _nice_step((b - a) / target)
    v = np.ceil(a / step) * step
    out: list[float] = []
    while v <= b + step * 1e-9 and len(out) < 200:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out, step


def _log_ticks(lo: float, hi: float, target: int = 6) -> tuple[list[float], list[float], float]:
    """Returns (ticks, labeled_ticks, step)."""
    a, b = min(lo, hi), max(lo, hi)
    if a <= 0 or b <= 0 or not (np.isfinite(a) and np.isfinite(b)):
        return [], [], 1.0
    e0 = int(np.floor(np.log10(a)))
    e1 = int(np.ceil(np.log10(b)))
    mults = (1, 2, 5) if max(1, e1 - e0) <= max(2, target) else (1,)
    label_every = max(1, int(np.ceil((e1 - e0 + 1) / max(1, target))))
    out: list[float] = []
    labels: list[float] = []
    for e in range(e0, e1 + 1):
        base = 10.0**e
        for m in mults:
            v = m * base
            if a * (1 - 1e-12) <= v <= b * (1 + 1e-12):
                out.append(v)
                if m == 1 and (e - e0) % label_every == 0:
                    labels.append(v)
            if len(out) >= 200:
                break
    return out, (labels or out), 1.0


def _category_ticks(lo: float, hi: float, n_categories: int, target: int = 6) -> list[int]:
    start = max(0, int(np.ceil(min(lo, hi))))
    stop = min(n_categories - 1, int(np.floor(max(lo, hi))))
    if stop < start:
        return []
    step = max(1, int(np.ceil((stop - start + 1) / max(1, target))))
    return list(range(start, stop + 1, step))


_TIME_STEPS = [
    1,
    2,
    5,
    10,
    20,
    50,
    100,
    200,
    500,
    _MS["s"],
    2 * _MS["s"],
    5 * _MS["s"],
    10 * _MS["s"],
    15 * _MS["s"],
    30 * _MS["s"],
    _MS["m"],
    2 * _MS["m"],
    5 * _MS["m"],
    10 * _MS["m"],
    15 * _MS["m"],
    30 * _MS["m"],
    _MS["h"],
    2 * _MS["h"],
    3 * _MS["h"],
    6 * _MS["h"],
    12 * _MS["h"],
    _MS["d"],
    2 * _MS["d"],
    7 * _MS["d"],
    14 * _MS["d"],
]


def _time_ticks(lo: float, hi: float, target: int = 6) -> tuple[list[float], float]:
    a, b = min(lo, hi), max(lo, hi)
    if not (np.isfinite(a) and np.isfinite(b)):
        return [], _MS["d"]
    rough = (b - a) / target
    if rough > 14 * _MS["d"]:
        return _calendar_ticks(a, b, rough)
    step = next((s for s in _TIME_STEPS if s >= rough), _TIME_STEPS[-1])
    v = np.ceil(a / step) * step
    out: list[float] = []
    while v <= b and len(out) < 200:
        out.append(v)
        v += step
    return out, step


def _calendar_ticks(lo: float, hi: float, rough: float) -> tuple[list[float], float]:
    month_steps = (1, 2, 3, 6, 12, 24, 60, 120)
    months_rough = rough / (30 * _MS["d"])
    step_m = next((s for s in month_steps if s >= months_rough), month_steps[-1])
    d = datetime.fromtimestamp(lo / 1e3, tz=UTC)
    y = d.year
    m = int(np.ceil((d.month - 1) / step_m) * step_m)
    out: list[float] = []
    while len(out) <= 1000:
        t = datetime(y + m // 12, m % 12 + 1, 1, tzinfo=UTC).timestamp() * 1e3
        if t > hi:
            break
        if t >= lo:
            out.append(t)
        m += step_m
    return out, step_m * 30 * _MS["d"]


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt_time(ms: float, step: float) -> str:
    d = datetime.fromtimestamp(ms / 1e3, tz=UTC)
    if step >= 28 * _MS["d"]:
        return str(d.year) if d.month == 1 else f"{_MONTHS[d.month - 1]} {d.year}"
    if step >= _MS["d"]:
        return f"{_MONTHS[d.month - 1]} {d.day:02d}"
    if step >= _MS["m"]:
        return f"{d.hour:02d}:{d.minute:02d}"
    if step >= _MS["s"]:
        return f"{d.hour:02d}:{d.minute:02d}:{d.second:02d}"
    return f"{d.minute:02d}:{d.second:02d}.{d.microsecond // 1000:03d}"


def _fmt_linear(v: float, step: float) -> str:
    if v == 0:
        return "0"
    av = abs(v)
    if av >= 1e6 or av < 1e-4:
        return f"{v:.1e}".replace("e+0", "e").replace("e-0", "e-").replace("e+", "e")
    dec = max(0, -int(np.floor(np.log10(step))) + (1 if step < 1 else 0))
    s = f"{v:.{min(dec, 8)}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _fmt_axis(axis: dict[str, Any], v: float, step: float) -> str:
    kind = axis.get("kind")
    if kind == "category":
        cats = axis.get("categories") or []
        i = round(v)
        return str(cats[i]) if 0 <= i < len(cats) else ""
    if kind == "time":
        return _fmt_time(v, step)
    return _fmt_linear(v, step)


# ---------------------------------------------------------------------------
# Payload decode + scales
# ---------------------------------------------------------------------------


def _column(blob: bytes, meta: dict[str, Any]) -> np.ndarray:
    raw = np.frombuffer(blob, dtype=np.float32, count=meta["len"], offset=meta["byte_offset"])
    return raw.astype(np.float64) / (meta.get("scale") or 1.0) + meta.get("offset", 0.0)


class _Scale:
    """value -> px for one axis (linear / time-in-ms / log / category)."""

    def __init__(self, axis: dict[str, Any], px0: float, px1: float) -> None:
        self.kind = axis.get("kind", "linear")
        lo, hi = axis["range"]
        self.log = self.kind == "log"
        if self.log:
            lo, hi = np.log10(max(lo, 1e-300)), np.log10(max(hi, 1e-300))
        self.lo, self.hi = float(lo), float(hi)
        self.px0, self.px1 = px0, px1

    def coord(self, v: Any) -> Any:
        return np.log10(np.maximum(v, 1e-300)) if self.log else v

    def __call__(self, v: Any) -> Any:
        c = self.coord(v)
        span = (self.hi - self.lo) or 1.0
        return self.px0 + (c - self.lo) / span * (self.px1 - self.px0)

    @property
    def affine(self) -> bool:
        return not self.log


def _lut(colormap: str, t: np.ndarray) -> np.ndarray:
    """Vectorized colormap sample: t in [0,1] -> (n,3) uint8, matching the
    client's 256-texel LUT interpolation."""
    stops = np.array(COLORMAP_STOPS.get(colormap) or COLORMAP_STOPS["viridis"], dtype=np.float64)
    pos = np.clip(t, 0.0, 1.0) * (len(stops) - 1)
    lo = np.floor(pos).astype(np.uint8)
    hi = np.minimum(lo + 1, len(stops) - 1)
    fraction = pos - lo
    out = np.empty((len(pos), 3), dtype=np.uint8)
    # Channel-wise interpolation is numerically identical to the broadcasted
    # `(n, 3)` expression but avoids three multi-megabyte float temporaries.
    for channel in range(3):
        start = stops[lo, channel]
        out[:, channel] = np.round(start + (stops[hi, channel] - start) * fraction).astype(np.uint8)
    return out


def _css(c: Any, fallback: str) -> str:
    """Static color resolution: currentColor -> the mark color; var() can't
    resolve without a DOM, so it falls back to the mark color too."""
    s = str(c or "").strip()
    if not s or s.lower() == "currentcolor" or s.startswith("var("):
        return fallback
    return s


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


# Embedded heatmap/density rasters use the shared truecolor PNG encoder.
_png_rgba = _png.png_truecolor


def _monotone_tangents(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fritsch–Carlson tangents — the same construction as fcSmoothResample."""
    n = len(x)
    dx = np.diff(x)
    dy = np.diff(y)
    d = np.where(dx > 0, dy / np.where(dx > 0, dx, 1), 0.0)
    m = np.empty(n)
    m[0], m[-1] = d[0], d[-1]
    m[1:-1] = np.where(d[:-1] * d[1:] <= 0, 0.0, (d[:-1] + d[1:]) * 0.5)
    for i in range(n - 1):
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            t = 3 / np.sqrt(s)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]
    return m


class _Svg:
    """One export pass: collects defs + body elements, then assembles."""

    def __init__(self, id_prefix: str = "") -> None:
        self.defs: list[str] = []
        self.body: list[str] = []
        self._uid = 0
        # Composed documents (facet grids) nest several exports into one SVG;
        # the prefix keeps ids unique so url(#...) refs stay panel-local.
        self._id_prefix = id_prefix

    def uid(self, prefix: str) -> str:
        self._uid += 1
        return f"{self._id_prefix}{prefix}{self._uid}"

    def gradient(self, fill: dict[str, Any], mark_color: str, plot: Optional[dict] = None) -> str:
        """Register a <linearGradient> for a validated fill spec; returns url(#id).

        Mark space maps to each element's bounding box (exact for bars/rects;
        the area approximation is documented). Plot space maps to the plot rect.
        """
        gid = self.uid("g")
        direction = fill.get("dir", "down")
        # Gradient line start/end per CSS: "down" starts at the top.
        ends = {
            "down": (0, 0, 0, 1),
            "up": (0, 1, 0, 0),
            "right": (0, 0, 1, 0),
            "left": (1, 0, 0, 0),
        }[direction if direction in ("down", "up", "left", "right") else "down"]
        if fill.get("space") == "plot" and plot:
            x0 = plot["x"] + ends[0] * plot["w"]
            y0 = plot["y"] + ends[1] * plot["h"]
            x1 = plot["x"] + ends[2] * plot["w"]
            y1 = plot["y"] + ends[3] * plot["h"]
            units = f'gradientUnits="userSpaceOnUse" x1="{_num(x0)}" y1="{_num(y0)}" x2="{_num(x1)}" y2="{_num(y1)}"'
        else:
            units = f'x1="{ends[0]}" y1="{ends[1]}" x2="{ends[2]}" y2="{ends[3]}"'
        stops = "".join(
            f'<stop offset="{_num(t * 100)}%" stop-color="{escape(_css(c, mark_color), {chr(34): "&quot;"})}"/>'
            for t, c in fill.get("stops", [])
        )
        self.defs.append(f'<linearGradient id="{gid}" {units}>{stops}</linearGradient>')
        return f"url(#{gid})"


def _rounded_rect_path(
    x: float, y: float, w: float, h: float, r_tip: float, r_base: float, tip_top: bool
) -> str:
    """Rect path with independent tip/base corner radii (vertical mark space)."""
    rt = min(r_tip, w / 2, h / 2)
    rb = min(r_base, w / 2, h / 2)
    top_r, bot_r = (rt, rb) if tip_top else (rb, rt)
    p = [f"M {_num(x)} {_num(y + top_r)}"]
    p.append(f"A {_num(top_r)} {_num(top_r)} 0 0 1 {_num(x + top_r)} {_num(y)}" if top_r else "")
    p.append(f"L {_num(x + w - top_r)} {_num(y)}")
    p.append(
        f"A {_num(top_r)} {_num(top_r)} 0 0 1 {_num(x + w)} {_num(y + top_r)}" if top_r else ""
    )
    p.append(f"L {_num(x + w)} {_num(y + h - bot_r)}")
    p.append(
        f"A {_num(bot_r)} {_num(bot_r)} 0 0 1 {_num(x + w - bot_r)} {_num(y + h)}" if bot_r else ""
    )
    p.append(f"L {_num(x + bot_r)} {_num(y + h)}")
    p.append(
        f"A {_num(bot_r)} {_num(bot_r)} 0 0 1 {_num(x)} {_num(y + h - bot_r)}" if bot_r else ""
    )
    p.append("Z")
    return " ".join(s for s in p if s)


def _poly_path(px: np.ndarray, py: np.ndarray) -> str:
    parts = [f"M {_num(px[0])} {_num(py[0])}"]
    parts.extend(f"L {_num(px[i])} {_num(py[i])}" for i in range(1, len(px)))
    return " ".join(parts)


def _curve_path(xv: np.ndarray, yv: np.ndarray, sx: _Scale, sy: _Scale, smooth: bool) -> str:
    """Pixel-space path for a polyline; smooth -> exact cubic Béziers of the
    monotone-cubic Hermite (affine axes), else polyline. The Bézier control
    points of a Hermite segment are P0 + h/3·(1, m0) and P1 - h/3·(1, m1),
    and affine axis maps carry control points exactly."""
    px, py = sx(xv), sy(yv)
    if not smooth or len(xv) < 3 or not (sx.affine and sy.affine):
        return _poly_path(px, py)
    m = _monotone_tangents(xv, yv)
    parts = [f"M {_num(px[0])} {_num(py[0])}"]
    for i in range(len(xv) - 1):
        h = xv[i + 1] - xv[i]
        if h <= 0:
            parts.append(f"L {_num(px[i + 1])} {_num(py[i + 1])}")
            continue
        c1x, c1y = sx(xv[i] + h / 3), sy(yv[i] + m[i] * h / 3)
        c2x, c2y = sx(xv[i + 1] - h / 3), sy(yv[i + 1] - m[i + 1] * h / 3)
        parts.append(
            f"C {_num(c1x)} {_num(c1y)} {_num(c2x)} {_num(c2y)} {_num(px[i + 1])} {_num(py[i + 1])}"
        )
    return " ".join(parts)


def _step_arrays(xv: np.ndarray, yv: np.ndarray, where: str) -> tuple[np.ndarray, np.ndarray]:
    if len(xv) < 2:
        return xv, yv
    xs = [float(xv[0])]
    ys = [float(yv[0])]
    for i in range(1, len(xv)):
        if where == "pre":
            xs.extend((xv[i - 1], xv[i]))
            ys.extend((yv[i], yv[i]))
        elif where == "mid":
            mid = (xv[i - 1] + xv[i]) * 0.5
            xs.extend((mid, mid, xv[i]))
            ys.extend((yv[i - 1], yv[i], yv[i]))
        else:
            xs.extend((xv[i], xv[i]))
            ys.extend((yv[i - 1], yv[i]))
    return np.asarray(xs), np.asarray(ys)


_SYMBOL_BUILDERS = {
    "square": lambda cx, cy, r: (
        f'<rect x="{_num(cx - r)}" y="{_num(cy - r)}" width="{_num(2 * r)}" height="{_num(2 * r)}"'
    ),
    "diamond": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy - r)} L {_num(cx + r)} {_num(cy)} L {_num(cx)} {_num(cy + r)} L {_num(cx - r)} {_num(cy)} Z"'
    ),
    "triangle": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy - r)} L {_num(cx + 0.9 * r)} {_num(cy + 0.62 * r)} L {_num(cx - 0.9 * r)} {_num(cy + 0.62 * r)} Z"'
    ),
    "cross": lambda cx, cy, r: (
        f'<path d="M {_num(cx - 0.34 * r)} {_num(cy - r)} H {_num(cx + 0.34 * r)} V {_num(cy - 0.34 * r)} '
        f"H {_num(cx + r)} V {_num(cy + 0.34 * r)} H {_num(cx + 0.34 * r)} V {_num(cy + r)} "
        f"H {_num(cx - 0.34 * r)} V {_num(cy + 0.34 * r)} H {_num(cx - r)} V {_num(cy - 0.34 * r)} "
        f'H {_num(cx - 0.34 * r)} Z"'
    ),
}


def _dash_attr(style: dict[str, Any]) -> str:
    dash = style.get("dash")
    if not dash:
        return ""
    return f' stroke-dasharray="{",".join(_num(float(v)) for v in dash)}"'


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def layout(spec: dict[str, Any]) -> tuple[int, int, bool, dict[str, float]]:
    """Concrete pixel dimensions + plot rect from a spec — shared by the SVG and
    native-PNG exporters so their chrome/plot geometry stays identical."""
    width = spec.get("width")
    height = spec.get("height")
    # Fluid ("100%") figures need concrete export dimensions.
    width = 900 if not isinstance(width, (int, float)) else int(width)
    height = 420 if not isinstance(height, (int, float)) else int(height)

    compact = width < 520
    pad = spec.get("padding")
    if isinstance(pad, list) and len(pad) == 4:
        top, right, bottom, left = (float(v) for v in pad)
    else:
        left = 46 if compact else 62
        right = 8 if compact else 14
        top = 6 if compact else 10
        bottom = 36 if compact else 42
    if spec.get("title"):
        top += 26 if compact else 30
    plot = {
        "x": left,
        "y": top,
        "w": max(40, width - left - right),
        "h": max(40, height - top - bottom),
    }
    return width, height, compact, plot


def axis_ticks(
    axis: dict[str, Any], length_px: float, is_x: bool
) -> tuple[list[float], list[float], float]:
    """(ticks, labeled ticks, step) for an axis at a given pixel length — shared
    tick density so SVG and PNG label the same values."""
    target = max(3, int(length_px / 80)) if is_x else max(3, int(length_px / 45))
    kind = axis.get("kind")
    lo, hi = axis["range"]
    if kind == "log":
        return _log_ticks(lo, hi, target)
    if kind == "category":
        t = [float(v) for v in _category_ticks(lo, hi, len(axis.get("categories") or []), target)]
        return t, t, 1.0
    if kind == "time":
        t, step = _time_ticks(lo, hi, target)
        return t, t, step
    t, step = _linear_ticks(lo, hi, target)
    return t, t, step


def render_svg(spec: dict[str, Any], blob: bytes, *, id_prefix: str = "") -> str:
    width, height, compact, plot = layout(spec)
    xa, ya = spec["x_axis"], spec["y_axis"]
    sx = _Scale(xa, plot["x"], plot["x"] + plot["w"])
    sy = _Scale(ya, plot["y"] + plot["h"], plot["y"])  # y grows downward in SVG
    svg = _Svg(id_prefix)
    cols = spec["columns"]

    def ticks_for(axis: dict[str, Any], length_px: float) -> tuple[list[float], list[float], float]:
        return axis_ticks(axis, length_px, axis is xa)

    # -- grid + tick labels + baselines ------------------------------------
    xt, xlab, xstep = ticks_for(xa, plot["w"])
    yt, ylab, ystep = ticks_for(ya, plot["h"])
    grid: list[str] = []
    labels: list[str] = []
    hide_x = xa.get("tick_label_strategy") == "none"
    hide_y = ya.get("tick_label_strategy") == "none"
    for v in xt:
        px = float(sx(v))
        grid.append(
            f'<line x1="{_num(px)}" y1="{_num(plot["y"])}" x2="{_num(px)}" '
            f'y2="{_num(plot["y"] + plot["h"])}" stroke="{_GRID}"/>'
        )
    for v in yt:
        py = float(sy(v))
        grid.append(
            f'<line x1="{_num(plot["x"])}" y1="{_num(py)}" x2="{_num(plot["x"] + plot["w"])}" '
            f'y2="{_num(py)}" stroke="{_GRID}"/>'
        )
    if not hide_x:
        for v in xlab:
            labels.append(
                f'<text x="{_num(float(sx(v)))}" y="{_num(plot["y"] + plot["h"] + 16)}" '
                f'text-anchor="middle">{escape(_fmt_axis(xa, v, xstep))}</text>'
            )
    if not hide_y:
        for v in ylab:
            labels.append(
                f'<text x="{_num(plot["x"] - 8)}" y="{_num(float(sy(v)) + 4)}" '
                f'text-anchor="end">{escape(_fmt_axis(ya, v, ystep))}</text>'
            )

    # -- marks --------------------------------------------------------------
    marks: list[str] = []
    palette_cycle = 0

    def line_attrs(style: dict[str, Any], color: str) -> str:
        w = float(style.get("width", 1.5))
        op = float(style.get("opacity", 1.0))
        return (
            f'stroke="{escape(color)}" stroke-width="{_num(w)}" fill="none" '
            f'stroke-linejoin="round" stroke-linecap="round"'
            + (f' stroke-opacity="{_num(op)}"' if op < 1 else "")
            + _dash_attr(style)
        )

    for t in spec["traces"]:
        style = t.get("style") or {}
        kind = t["kind"]
        tier = t.get("tier")
        color = _css(style.get("color"), DEFAULT_PALETTE[palette_cycle % len(DEFAULT_PALETTE)])
        palette_cycle += 1

        if tier == "density" and t.get("density"):
            marks.append(_density_image(t["density"], blob, cols, sx, sy, style, svg))
            continue

        if kind == "line":
            xv = _column(blob, cols[t["x"]])
            yv = _column(blob, cols[t["y"]])
            if style.get("step"):
                xv, yv = _step_arrays(xv, yv, style["step"])
            d = _curve_path(xv, yv, sx, sy, style.get("curve") == "smooth")
            marks.append(f'<path d="{d}" {line_attrs(style, color)}/>')

        elif kind in ("area", "error_band"):
            xv = _column(blob, cols[t["x"]])
            yv = _column(blob, cols[t["y"]])
            bv = _column(blob, cols[t["base"]])
            smooth = style.get("curve") == "smooth"
            top_path = _curve_path(xv, yv, sx, sy, smooth)
            base_path = _curve_path(xv[::-1], bv[::-1], sx, sy, smooth)
            fill_spec = style.get("fill")
            fill = (
                svg.gradient(fill_spec, color, plot)
                if isinstance(fill_spec, dict)
                else escape(color)
            )
            op = float(style.get("opacity", 0.35))
            joined = f"{top_path} L {base_path[2:]} Z"  # strip the M of the return path
            marks.append(f'<path d="{joined}" fill="{fill}" fill-opacity="{_num(op)}"/>')
            lw = float(style.get("line_width", 1.2))
            if lw > 0:
                lop = float(style.get("line_opacity", 1.0))
                marks.append(
                    f'<path d="{top_path}" stroke="{escape(color)}" stroke-width="{_num(lw)}" '
                    f'fill="none" stroke-linejoin="round"'
                    + (f' stroke-opacity="{_num(lop)}"' if lop < 1 else "")
                    + _dash_attr(style)
                    + "/>"
                )

        elif kind in ("scatter", "hexbin"):
            marks.append(_scatter_marks(t, blob, cols, sx, sy, style, color))

        elif kind in {"errorbar", "stem", "box_whisker", "box_median", "contour", "segments"}:
            marks.append(_segment_marks(t, blob, cols, sx, sy, style, color))

        elif kind in ("bar", "column") and t.get("bar"):
            marks.append(_bar_marks(t, blob, cols, sx, sy, style, color, svg, plot))

        elif kind == "heatmap" and t.get("heatmap"):
            marks.append(_heatmap_image(t["heatmap"], blob, cols, sx, sy, style))

        elif kind == "triangle_mesh":
            marks.append(_triangle_mesh_marks(t, blob, cols, sx, sy, style, color))

        elif all(k in t for k in ("x0", "x1", "y0", "y1")):  # histogram / rect family
            marks.append(_rect_marks(t, blob, cols, sx, sy, style, color, svg, plot))

    # -- chrome text ----------------------------------------------------------
    chrome: list[str] = []
    if spec.get("title"):
        chrome.append(
            f'<text x="{_num(width / 2)}" y="{_num(plot["y"] - (10 if compact else 12))}" '
            f'text-anchor="middle" font-size="14" font-weight="600" '
            f'fill="{_TEXT}">{escape(str(spec["title"]))}</text>'
        )
    if xa.get("label") and not hide_x:
        chrome.append(
            f'<text x="{_num(plot["x"] + plot["w"] / 2)}" y="{_num(plot["y"] + plot["h"] + 34)}" '
            f'text-anchor="middle" font-size="12" font-weight="500" '
            f'fill="{_TEXT}">{escape(str(xa["label"]))}</text>'
        )
    if ya.get("label") and not hide_y:
        cx, cy = 14, plot["y"] + plot["h"] / 2
        chrome.append(
            f'<text x="{_num(cx)}" y="{_num(cy)}" text-anchor="middle" font-size="12" '
            f'font-weight="500" fill="{_TEXT}" '
            f'transform="rotate(-90 {_num(cx)} {_num(cy)})">{escape(str(ya["label"]))}</text>'
        )
    named = [t for t in spec["traces"] if t.get("name")]
    if spec.get("show_legend", True) and named:
        chrome.append(_legend(named, plot))

    # baselines above the marks, matching the client's overlay rules
    baselines = (
        f'<line x1="{_num(plot["x"])}" y1="{_num(plot["y"])}" x2="{_num(plot["x"])}" '
        f'y2="{_num(plot["y"] + plot["h"])}" stroke="{_AXIS}"/>'
        f'<line x1="{_num(plot["x"])}" y1="{_num(plot["y"] + plot["h"])}" '
        f'x2="{_num(plot["x"] + plot["w"])}" y2="{_num(plot["y"] + plot["h"])}" stroke="{_AXIS}"/>'
    )

    clip_id = svg.uid("clip")
    svg.defs.append(
        f'<clipPath id="{clip_id}"><rect x="{_num(plot["x"])}" y="{_num(plot["y"])}" '
        f'width="{_num(plot["w"])}" height="{_num(plot["h"])}"/></clipPath>'
    )
    defs = f"<defs>{''.join(svg.defs)}</defs>" if svg.defs else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{_FONT}" font-size="11">'
        f"{defs}"
        f"<g>{''.join(grid)}</g>"
        f'<g clip-path="url(#{clip_id})">{"".join(marks)}</g>'
        f"{baselines}"
        f'<g fill="{_TEXT}">{"".join(labels)}</g>'
        f"{''.join(chrome)}"
        f"</svg>"
    )


def _segment_marks(
    t: dict[str, Any], blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, color: str
) -> str:
    x0 = _column(blob, cols[t["x0"]])
    x1 = _column(blob, cols[t["x1"]])
    y0 = _column(blob, cols[t["y0"]])
    y1 = _column(blob, cols[t["y1"]])
    width = float(style.get("width", 1.2))
    op = float(style.get("opacity", 1.0))
    channel = t.get("color") or {}
    if channel.get("mode") == "continuous":
        rgb = _lut(channel.get("colormap", "viridis"), _column(blob, cols[channel["buf"]]))
        colors = [f"rgb({r},{g},{b})" for r, g, b in rgb]
    elif channel.get("mode") == "categorical":
        codes = _column(blob, cols[channel["buf"]]).astype(int)
        palette = channel.get("palette") or DEFAULT_PALETTE
        colors = [palette[code % len(palette)] for code in codes]
    else:
        colors = [color] * len(x0)
    suffix = f'stroke-width="{_num(width)}" fill="none" stroke-linecap="round"' + (
        f' stroke-opacity="{_num(op)}"' if op < 1 else ""
    )
    return "".join(
        f'<line x1="{_num(float(sx(x0[i])))}" y1="{_num(float(sy(y0[i])))}" '
        f'x2="{_num(float(sx(x1[i])))}" y2="{_num(float(sy(y1[i])))}" '
        f'stroke="{escape(colors[i])}" {suffix}/>'
        for i in range(len(x0))
    )


def _scatter_marks(
    t: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, fallback: str
) -> str:
    xv = _column(blob, cols[t["x"]])
    yv = _column(blob, cols[t["y"]])
    px, py = sx(xv), sy(yv)
    n = len(xv)

    color_ch = t.get("color") or {}
    mode = color_ch.get("mode")
    if mode == "continuous":
        vals = _column(blob, cols[color_ch["buf"]])
        rgb = _lut(color_ch.get("colormap", "viridis"), vals)
        fills = [f"rgb({r},{g},{b})" for r, g, b in rgb]
    elif mode == "categorical":
        codes = _column(blob, cols[color_ch["buf"]]).astype(int)
        pal = color_ch.get("palette") or DEFAULT_PALETTE
        fills = [pal[c % len(pal)] for c in codes]
    else:
        fills = [_css(color_ch.get("color"), fallback)] * n

    size_ch = t.get("size") or {}
    if size_ch.get("mode") == "continuous":
        sv = _column(blob, cols[size_ch["buf"]])
        r0, r1 = size_ch.get("range_px", [2, 18])
        radii = (r0 + (r1 - r0) * np.clip(sv, 0, 1)) / 2
    else:
        radii = np.full(n, float(size_ch.get("size", 4.0)) / 2)

    op = float(style.get("opacity", 0.8))
    stroke_w = float(style.get("stroke_width", 0.0))
    stroke = _css(style.get("stroke"), fills[0] if fills else fallback) if stroke_w else None
    stroke_attr = f' stroke="{escape(stroke)}" stroke-width="{_num(stroke_w)}"' if stroke else ""
    symbol = style.get("symbol", "circle")
    builder = _SYMBOL_BUILDERS.get(symbol)

    out = [f'<g fill-opacity="{_num(op)}">' if op < 1 else "<g>"]
    for i in range(n):
        fill_attr = f' fill="{escape(fills[i])}"'
        if builder is None:
            out.append(
                f'<circle cx="{_num(px[i])}" cy="{_num(py[i])}" r="{_num(radii[i])}"'
                f"{fill_attr}{stroke_attr}/>"
            )
        else:
            out.append(
                builder(float(px[i]), float(py[i]), float(radii[i])) + f"{fill_attr}{stroke_attr}/>"
            )
    out.append("</g>")
    return "".join(out)


def _triangle_mesh_marks(
    t: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, fallback: str
) -> str:
    vertices = [_column(blob, cols[t[name]]) for name in ("x0", "y0", "x1", "y1", "x2", "y2")]
    n = min(len(values) for values in vertices)
    color_ch = t.get("color") or {}
    mode = color_ch.get("mode")
    if mode == "continuous":
        values = _column(blob, cols[color_ch["buf"]])[:n]
        rgb = _lut(color_ch.get("colormap", "viridis"), values)
        fills = [f"rgb({r},{g},{b})" for r, g, b in rgb]
    elif mode == "categorical":
        codes = _column(blob, cols[color_ch["buf"]])[:n].astype(int)
        palette = color_ch.get("palette") or DEFAULT_PALETTE
        fills = [palette[code % len(palette)] for code in codes]
    else:
        fills = [_css(color_ch.get("color"), fallback)] * n

    opacity = float(style.get("opacity", 1.0))
    stroke_width = float(style.get("stroke_width", 0.0))
    stroke = _css(style.get("stroke"), fallback) if stroke_width else None
    group_attr = f' fill-opacity="{_num(opacity)}"' if opacity < 1 else ""
    stroke_attr = (
        f' stroke="{escape(stroke)}" stroke-width="{_num(stroke_width)}"'
        if stroke is not None
        else ""
    )
    x0, y0, x1, y1, x2, y2 = vertices
    out = [f"<g{group_attr}>"]
    for i in range(n):
        points = " ".join(
            f"{_num(float(sx(x)))},{_num(float(sy(y)))}"
            for x, y in ((x0[i], y0[i]), (x1[i], y1[i]), (x2[i], y2[i]))
        )
        out.append(f'<polygon points="{points}" fill="{escape(fills[i])}"{stroke_attr}/>')
    out.append("</g>")
    return "".join(out)


def _bar_fill(style: dict, color: str, svg: _Svg, plot: dict) -> tuple[str, str]:
    fill_spec = style.get("fill")
    fill = svg.gradient(fill_spec, color, plot) if isinstance(fill_spec, dict) else escape(color)
    op = float(style.get("opacity", 0.85))
    stroke_w = float(style.get("stroke_width", 0.0))
    stroke = _css(style.get("stroke"), color) if stroke_w else None
    extra = f' fill-opacity="{_num(op)}"' if op < 1 else ""
    if stroke:
        extra += f' stroke="{escape(stroke)}" stroke-width="{_num(stroke_w)}"'
    return fill, extra


def _corner_radii(style: dict) -> tuple[float, float]:
    cr = style.get("corner_radius", 0)
    if isinstance(cr, (list, tuple)):
        return float(cr[0]), float(cr[1])
    return float(cr or 0), float(cr or 0)


def _bar_marks(
    t: dict,
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    color: str,
    svg: _Svg,
    plot: dict,
) -> str:
    b = t["bar"]
    pos = _column(blob, cols[b["pos"]])
    v1 = _column(blob, cols[b["value1"]])
    v0 = (
        _column(blob, cols[b["value0"]])
        if "value0" in b
        else np.full(len(pos), float(b.get("value0_const", 0.0)))
    )
    horizontal = b.get("orientation") == "horizontal"
    half = float(b["width"]) / 2
    r_tip, r_base = _corner_radii(style)
    fill, extra = _bar_fill(style, color, svg, plot)
    out = []
    for i in range(len(pos)):
        if horizontal:
            x0, x1 = float(sx(min(v0[i], v1[i]))), float(sx(max(v0[i], v1[i])))
            y0, y1 = float(sy(pos[i] + half)), float(sy(pos[i] - half))
        else:
            x0, x1 = float(sx(pos[i] - half)), float(sx(pos[i] + half))
            y0, y1 = float(sy(max(v0[i], v1[i]))), float(sy(min(v0[i], v1[i])))
        w, h = abs(x1 - x0), abs(y1 - y0)
        x, y = min(x0, x1), min(y0, y1)
        if r_tip or r_base:
            tip_top = not horizontal and v1[i] >= v0[i]
            d = _rounded_rect_path(x, y, w, h, r_tip, r_base, tip_top or horizontal)
            out.append(f'<path d="{d}" fill="{fill}"{extra}/>')
        else:
            out.append(
                f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
                f'fill="{fill}"{extra}/>'
            )
    return "".join(out)


def _rect_marks(
    t: dict,
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    color: str,
    svg: _Svg,
    plot: dict,
) -> str:
    x0v = _column(blob, cols[t["x0"]])
    x1v = _column(blob, cols[t["x1"]])
    y0v = _column(blob, cols[t["y0"]])
    y1v = _column(blob, cols[t["y1"]])
    r_tip, r_base = _corner_radii(style)
    fill, extra = _bar_fill(style, color, svg, plot)
    out = []
    for i in range(len(x0v)):
        xa_, xb = float(sx(x0v[i])), float(sx(x1v[i]))
        ya_, yb = float(sy(y0v[i])), float(sy(y1v[i]))
        x, y = min(xa_, xb), min(ya_, yb)
        w, h = abs(xb - xa_), abs(yb - ya_)
        if r_tip or r_base:
            d = _rounded_rect_path(x, y, w, h, r_tip, r_base, y1v[i] >= y0v[i])
            out.append(f'<path d="{d}" fill="{fill}"{extra}/>')
        else:
            out.append(
                f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
                f'fill="{fill}"{extra}/>'
            )
    return "".join(out)


def _grid_image(
    w: int, h: int, rgba: bytes, x_range: list, y_range: list, sx: _Scale, sy: _Scale
) -> str:
    px0, px1 = float(sx(x_range[0])), float(sx(x_range[1]))
    py0, py1 = float(sy(y_range[1])), float(sy(y_range[0]))  # grid row 0 = y_range bottom
    b64 = base64.b64encode(_png_rgba(w, h, rgba)).decode("ascii")
    return (
        f'<image x="{_num(min(px0, px1))}" y="{_num(min(py0, py1))}" '
        f'width="{_num(abs(px1 - px0))}" height="{_num(abs(py1 - py0))}" '
        f'preserveAspectRatio="none" style="image-rendering:pixelated" '
        f'href="data:image/png;base64,{b64}"/>'
    )


def _density_image(
    d: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, svg: _Svg
) -> str:
    w, h = int(d["w"]), int(d["h"])
    grid = _column(blob, cols[d["buf"]]).reshape(h, w)
    gmax = float(d.get("max") or 1.0) or 1.0
    tnorm = np.clip(grid / gmax, 0.0, 1.0)
    rgb = _lut(d.get("colormap", "viridis"), tnorm.reshape(-1)).reshape(h, w, 3)
    alpha = (np.clip(tnorm * 1.35, 0, 1) * 255 * float(style.get("opacity", 0.85))).astype(np.uint8)
    alpha[tnorm <= 0] = 0
    rgba = np.dstack([rgb, alpha])[::-1].tobytes()  # flip: PNG rows are top-first
    return _grid_image(w, h, rgba, d["x_range"], d["y_range"], sx, sy)


def _heatmap_image(hm: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict) -> str:
    w, h = int(hm["w"]), int(hm["h"])
    raw = _column(blob, cols[hm["buf"]]).reshape(h, w)
    # Mirrors HEATMAP_FS: byte 0 = missing, 1..255 -> [0,1].
    t = np.clip((raw * 255.0 - 1.0) / 254.0, 0.0, 1.0)
    rgb = _lut(hm.get("colormap", "viridis"), t.reshape(-1)).reshape(h, w, 3)
    alpha = np.full((h, w), int(255 * float(style.get("opacity", 0.95))), dtype=np.uint8)
    alpha[raw <= 0] = 0
    rgba = np.dstack([rgb, alpha])[::-1].tobytes()
    return _grid_image(w, h, rgba, hm["x_range"], hm["y_range"], sx, sy)


def _legend(named: list[dict], plot: dict) -> str:
    rows = []
    pad, swatch, line_h = 8, 10, 16
    box_w = max(len(str(t["name"])) for t in named) * 6.2 + swatch + 3 * pad
    box_h = len(named) * line_h + pad
    x = plot["x"] + plot["w"] - box_w - 6
    y = plot["y"] + 6
    rows.append(
        f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(box_w)}" height="{_num(box_h)}" '
        f'rx="4" fill="rgba(128,128,128,0.08)"/>'
    )
    for i, t in enumerate(named):
        style = t.get("style") or {}
        color = _css(
            style.get("color") or (t.get("color") or {}).get("color"),
            DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
        )
        ry = y + pad / 2 + i * line_h
        rows.append(
            f'<rect x="{_num(x + pad)}" y="{_num(ry + 2)}" width="{swatch}" height="{swatch}" '
            f'rx="2" fill="{escape(color)}"/>'
        )
        rows.append(
            f'<text x="{_num(x + pad + swatch + 5)}" y="{_num(ry + swatch)}" '
            f'fill="{_TEXT}">{escape(str(t["name"]))}</text>'
        )
    return "".join(rows)


def to_svg(
    fig: Any,
    path: Optional[str | PathLike[str]] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    id_prefix: str = "",
) -> str:
    """Render `fig` to a standalone SVG string (optionally saved to `path`).

    `width`/`height` override the figure's pixel size (useful for fluid "100%"
    figures). Decimation runs at the export width, so output stays
    screen-bounded no matter the source size. `id_prefix` namespaces generated
    element ids for composers that inline several exports in one document."""
    eff_w = (
        int(width)
        if width is not None
        else (fig.width if isinstance(fig.width, (int, float)) else 900)
    )
    spec, blob = fig.build_payload(px_width=max(256, int(eff_w)))
    if width is not None:
        spec["width"] = int(width)
    if height is not None:
        spec["height"] = int(height)
    out = render_svg(spec, blob, id_prefix=id_prefix)
    if path is not None:
        from .export import _atomic_write_text

        _atomic_write_text(path, out)
    return out
