"""Static SVG export — a pure-Python renderer over the same wire payload the
browser client consumes.

The decimation tiers make static export *screen-bounded*: `build_payload`
hands this module ≤4 line points per pixel column (M4) or a fixed density
grid, so a 100M-point figure exports as a few-hundred-KB, resolution-
independent SVG in milliseconds — no browser, no extra dependencies.

Layout, tick math, colormaps, and mark styling mirror the JS client
(`30_ticks.ts`, `10_colormaps.ts`, `50_chartview.ts`); tests assert the
ported tables stay in sync with the JS parts. Known static-export
approximations, documented in spec/api/styling.md: area mark-space gradients use
the area's bounding box (SVG has no per-column gradient); complete chart color
tokens resolve statically, while nested browser-only expressions remain
browser-dependent in SVG and use the native PNG fallback.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from os import PathLike
from typing import Any, NamedTuple, Optional, cast

import numpy as np

from . import _fontmetrics, _native, _paint, _png, _textblock
from ._arrowgeom import arrow_shapes as _arrow_shapes
from .config import DEFAULT_PALETTE, polar_bar_segments


def escape(data: str, entities: dict[str, str] | None = None) -> str:
    """Escape ``&``, ``<`` and ``>`` in a string of data.

    Byte-for-byte equivalent to :func:`xml.sax.saxutils.escape`, vendored so a
    static export does not import it. That one function costs ~7.5 ms of cold
    start: ``xml.sax.saxutils`` pulls in ``urllib.request``, which pulls in
    ``http.client``, ``ssl``, ``socket`` and the whole ``email`` package — 35+
    modules for three ``str.replace`` calls. Nothing else in xy needs them, and
    a cold ``to_png`` at 10M points spent more time on that import than on
    binning ten million points.

    ``tests/test_svg_escape.py`` differentially fuzzes this against the stdlib
    so it cannot drift.
    """
    # must do ampersand first
    data = data.replace("&", "&amp;")
    data = data.replace(">", "&gt;")
    data = data.replace("<", "&lt;")
    if entities:
        for key, value in entities.items():
            data = data.replace(key, value)
    return data


def _escape_attr(data: Any) -> str:
    """Escape arbitrary text for a double-quoted XML attribute."""
    return escape(str(data), {'"': "&quot;"})


def _fill_opacity(style: dict[str, Any], default: float = 1.0) -> float:
    """CSS whole-mark opacity multiplied by the fill-only channel."""
    return float(style.get("opacity", default)) * float(style.get("fill_opacity", 1.0))


def _stroke_opacity(style: dict[str, Any], default: float = 1.0) -> float:
    """CSS whole-mark opacity multiplied by the stroke-only channel."""
    return float(style.get("opacity", default)) * float(style.get("stroke_opacity", 1.0))


def _flag_stops() -> list[tuple[int, int, int]]:
    """Matplotlib's high-frequency ``flag`` map at the native 256 LUT positions."""
    x = np.linspace(0.0, 1.0, 256)
    channels = np.column_stack(
        (
            0.75 * np.sin((x * 31.5 + 0.25) * np.pi) + 0.5,
            np.sin(x * 31.5 * np.pi),
            0.75 * np.sin((x * 31.5 - 0.25) * np.pi) + 0.5,
        )
    )
    # Match Matplotlib's ``bytes=True`` conversion, which truncates rather than
    # rounds each clipped channel after scaling it to the uint8 range.
    rgb = (np.clip(channels, 0.0, 1.0) * 255.0).astype(np.uint8)
    return [(int(row[0]), int(row[1]), int(row[2])) for row in rgb]


# Mirrors js/src/10_colormaps.ts COLORMAP_STOPS (§36) — test-guarded.
COLORMAP_STOPS: dict[str, list[tuple[int, int, int]]] = {
    "binary": [(255, 255, 255), (0, 0, 0)],
    "flag": _flag_stops(),
    "reds": [
        (255, 245, 240),
        (254, 229, 216),
        (253, 202, 181),
        (252, 171, 143),
        (252, 138, 106),
        (251, 105, 74),
        (241, 68, 50),
        (217, 37, 35),
        (188, 20, 26),
        (152, 12, 19),
        (103, 0, 13),
    ],
    "bone": [
        (0, 0, 0),
        (22, 22, 30),
        (45, 45, 62),
        (66, 66, 93),
        (89, 92, 121),
        (112, 123, 144),
        (134, 154, 166),
        (157, 185, 188),
        (185, 210, 210),
        (221, 233, 233),
        (255, 255, 255),
    ],
    "autumn": [
        (255, 0, 0),
        (255, 25, 0),
        (255, 51, 0),
        (255, 76, 0),
        (255, 102, 0),
        (255, 128, 0),
        (255, 153, 0),
        (255, 179, 0),
        (255, 204, 0),
        (255, 230, 0),
        (255, 255, 0),
    ],
    "winter": [
        (0, 0, 255),
        (0, 25, 242),
        (0, 51, 230),
        (0, 76, 217),
        (0, 102, 204),
        (0, 128, 191),
        (0, 153, 178),
        (0, 179, 166),
        (0, 204, 153),
        (0, 230, 140),
        (0, 255, 128),
    ],
    "bupu": [
        (247, 252, 253),
        (229, 239, 246),
        (204, 221, 236),
        (178, 202, 225),
        (154, 180, 214),
        (140, 149, 198),
        (140, 116, 181),
        (138, 81, 165),
        (133, 45, 144),
        (118, 12, 113),
        (77, 0, 75),
    ],
    "gray": [
        (0, 0, 0),
        (25, 25, 25),
        (51, 51, 51),
        (76, 76, 76),
        (102, 102, 102),
        (128, 128, 128),
        (153, 153, 153),
        (179, 179, 179),
        (204, 204, 204),
        (230, 230, 230),
        (255, 255, 255),
    ],
    "viridis": [
        (68, 1, 84),
        (72, 36, 117),
        (65, 68, 135),
        (53, 95, 141),
        (42, 120, 142),
        (33, 145, 140),
        (34, 168, 132),
        (68, 191, 112),
        (122, 209, 81),
        (189, 223, 38),
        (253, 231, 37),
    ],
    "plasma": [
        (13, 8, 135),
        (65, 4, 157),
        (106, 0, 168),
        (143, 13, 164),
        (177, 42, 144),
        (204, 71, 120),
        (225, 100, 98),
        (242, 132, 75),
        (252, 166, 54),
        (252, 206, 37),
        (240, 249, 33),
    ],
    "inferno": [
        (0, 0, 4),
        (22, 11, 57),
        (66, 10, 104),
        (106, 23, 110),
        (147, 38, 103),
        (188, 55, 84),
        (221, 81, 58),
        (243, 120, 25),
        (252, 165, 10),
        (246, 215, 70),
        (252, 255, 164),
    ],
    "magma": [
        (0, 0, 4),
        (20, 14, 54),
        (59, 15, 112),
        (100, 26, 128),
        (140, 41, 129),
        (183, 55, 121),
        (222, 73, 104),
        (247, 112, 92),
        (254, 159, 109),
        (254, 207, 146),
        (252, 253, 191),
    ],
    "cividis": [
        (0, 34, 78),
        (8, 51, 112),
        (53, 69, 108),
        (79, 87, 108),
        (102, 105, 112),
        (125, 124, 120),
        (148, 142, 119),
        (174, 163, 113),
        (200, 184, 102),
        (229, 207, 82),
        (254, 232, 56),
    ],
    "coolwarm": [
        (59, 76, 192),
        (89, 119, 227),
        (123, 159, 249),
        (158, 190, 255),
        (192, 212, 245),
        (221, 220, 220),
        (242, 203, 183),
        (247, 172, 142),
        (238, 132, 104),
        (214, 82, 68),
        (180, 4, 38),
    ],
    "turbo": [
        (48, 18, 59),
        (69, 89, 203),
        (62, 155, 254),
        (25, 213, 205),
        (70, 248, 132),
        (164, 252, 60),
        (225, 221, 55),
        (254, 164, 49),
        (240, 91, 18),
        (195, 37, 3),
        (122, 4, 3),
    ],
    "rainbow": [
        (128, 0, 255),
        (78, 77, 252),
        (25, 150, 243),
        (24, 205, 228),
        (77, 243, 206),
        (128, 255, 180),
        (178, 243, 150),
        (230, 205, 115),
        (255, 150, 79),
        (255, 77, 39),
        (255, 0, 0),
    ],
    "jet": [
        (0, 0, 128),
        (0, 0, 241),
        (0, 76, 255),
        (0, 176, 255),
        (41, 255, 206),
        (125, 255, 122),
        (206, 255, 41),
        (255, 196, 0),
        (255, 104, 0),
        (241, 8, 0),
        (128, 0, 0),
    ],
    "rdgy": [
        (103, 0, 31),
        (177, 24, 43),
        (214, 96, 77),
        (243, 164, 129),
        (253, 219, 199),
        (254, 254, 254),
        (224, 224, 224),
        (185, 185, 185),
        (135, 135, 135),
        (76, 76, 76),
        (26, 26, 26),
    ],
    "rdbu": [
        (103, 0, 31),
        (177, 24, 43),
        (214, 96, 77),
        (243, 164, 129),
        (253, 219, 199),
        (246, 247, 247),
        (209, 229, 240),
        (144, 196, 221),
        (67, 147, 195),
        (32, 101, 171),
        (5, 48, 97),
    ],
    "blues": [
        (247, 251, 255),
        (227, 238, 249),
        (208, 225, 242),
        (183, 212, 234),
        (148, 196, 223),
        (106, 174, 214),
        (74, 152, 201),
        (46, 126, 188),
        (23, 100, 171),
        (8, 74, 145),
        (8, 48, 107),
    ],
    "purples": [
        (252, 251, 253),
        (242, 240, 247),
        (226, 226, 239),
        (206, 207, 229),
        (182, 182, 216),
        (158, 154, 200),
        (134, 131, 189),
        (114, 98, 172),
        (97, 64, 155),
        (79, 31, 139),
        (63, 0, 125),
    ],
    "pubu": [
        (255, 247, 251),
        (240, 234, 244),
        (219, 218, 235),
        (192, 201, 226),
        (156, 185, 217),
        (115, 169, 207),
        (66, 149, 195),
        (24, 124, 182),
        (5, 103, 162),
        (4, 83, 130),
        (2, 56, 88),
    ],
    "piyg": [
        (142, 1, 82),
        (196, 26, 124),
        (222, 119, 174),
        (241, 181, 217),
        (253, 224, 239),
        (247, 247, 246),
        (230, 245, 208),
        (183, 224, 133),
        (127, 188, 65),
        (76, 145, 33),
        (39, 100, 25),
    ],
    "prgn": [
        (64, 0, 75),
        (117, 41, 130),
        (153, 112, 171),
        (193, 164, 206),
        (231, 212, 232),
        (246, 247, 246),
        (217, 240, 211),
        (165, 218, 159),
        (90, 174, 97),
        (26, 119, 54),
        (0, 68, 27),
    ],
    "rdylgn": [
        (165, 0, 38),
        (214, 47, 39),
        (244, 109, 67),
        (253, 173, 96),
        (254, 224, 139),
        (254, 255, 190),
        (217, 239, 139),
        (165, 216, 106),
        (102, 189, 99),
        (25, 151, 80),
        (0, 104, 55),
    ],
    "rdylbu": [
        (165, 0, 38),
        (214, 47, 38),
        (244, 109, 67),
        (252, 172, 96),
        (254, 224, 144),
        (254, 254, 192),
        (224, 243, 247),
        (169, 216, 232),
        (116, 173, 209),
        (68, 115, 179),
        (49, 54, 149),
    ],
    "ylgn": [
        (255, 255, 229),
        (248, 252, 194),
        (229, 244, 171),
        (200, 232, 154),
        (162, 216, 137),
        (119, 197, 120),
        (75, 176, 98),
        (46, 146, 76),
        (21, 120, 62),
        (0, 96, 51),
        (0, 69, 41),
    ],
    "wistia": [
        (228, 255, 122),
        (238, 245, 84),
        (249, 236, 45),
        (255, 223, 21),
        (255, 206, 10),
        (255, 188, 0),
        (255, 177, 0),
        (255, 165, 0),
        (254, 153, 0),
        (253, 139, 0),
        (252, 127, 0),
    ],
    "puor": [
        (127, 59, 8),
        (177, 87, 6),
        (224, 130, 20),
        (252, 182, 97),
        (254, 224, 182),
        (246, 246, 246),
        (216, 218, 235),
        (177, 169, 209),
        (128, 115, 172),
        (83, 38, 134),
        (45, 0, 75),
    ],
    "spectral": [
        (158, 1, 66),
        (212, 61, 79),
        (244, 109, 67),
        (253, 173, 96),
        (254, 224, 139),
        (255, 255, 190),
        (230, 245, 152),
        (170, 220, 164),
        (102, 194, 165),
        (51, 135, 188),
        (94, 79, 162),
    ],
}

# Light-theme chrome colors (the client derives these from currentColor).
_TEXT = "rgba(32,32,32,0.85)"
_GRID = "rgba(32,32,32,0.14)"
_AXIS = "rgba(32,32,32,0.55)"
_FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"
_MS = {"s": 1e3, "m": 6e4, "h": 36e5, "d": 864e5}
_STATIC_COLOR_FALLBACK = (0.3, 0.47, 0.66, 1.0)
_AXIS_GRID_DASHES = {
    "solid": None,
    "dashed": [6.0, 4.0],
    "dotted": [1.0, 3.0],
    "dashdot": [6.0, 3.0, 1.0, 3.0],
}


# ---------------------------------------------------------------------------
# Tick math — ports of 30_ticks.ts (f64 throughout, §16)
# ---------------------------------------------------------------------------


def _nice_step(rough: float) -> float:
    rough = abs(rough)
    if not np.isfinite(rough) or rough <= 0:
        return 1.0
    mag = 10.0 ** np.floor(np.log10(rough))
    for m in (1, 2, 2.5, 5, 10):
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


# Angular tick ladders. `_nice_step`'s [1, 2, 2.5, 5, 10] cannot produce 15,
# 30, 45 or 90, so feeding it degrees yields 0/50/100/150 — a grid nobody reads
# angles on. Fixed ladders instead, in the style of the time-tick steps.
# Mirrored by DEGREE_STEPS/RADIAN_STEPS in js/src/30_ticks.ts.
_DEGREE_STEPS = (1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 360.0)
_RADIAN_STEPS = tuple(
    math.pi * f for f in (1 / 12, 1 / 8, 1 / 6, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 1.0, 2.0)
)


def _angular_ticks(lo: float, hi: float, unit: str, target: int = 6) -> tuple[list[float], float]:
    """Ticks for an angular axis, on a ladder humans read angles on.

    Mirrors `angularTicks` in js/src/30_ticks.ts.
    """
    a, b = min(lo, hi), max(lo, hi)
    if not (np.isfinite(a) and np.isfinite(b)):
        return [], 1.0
    if a == b:
        return [a], 1.0
    ladder = _DEGREE_STEPS if unit == "degrees" else _RADIAN_STEPS
    rough = (b - a) / max(1, target)
    step = next((s for s in ladder if s >= rough * (1 - 1e-12)), ladder[-1])
    v = math.ceil(a / step) * step
    out: list[float] = []
    while v <= b + step * 1e-9 and len(out) < 200:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    # A full turn puts a tick at both ends of the seam; they are the same
    # spoke, so the duplicate label is dropped rather than overdrawn.
    turn = 360.0 if unit == "degrees" else 2.0 * math.pi
    if len(out) > 1 and abs((out[-1] - out[0]) - turn) < step * 1e-9:
        out.pop()
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
_MONTHS_LONG = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


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
    av = abs(v)
    if av >= 1e6 or (av != 0 and av < 1e-4):
        return f"{v:.1e}".replace("e+0", "e").replace("e-0", "e-").replace("e+", "e")
    dec = max(0, int(np.ceil(-np.log10(abs(step))))) if step else 0
    # A non-nice step (pi/2, 0.3333…) needs enough decimals to keep adjacent
    # ticks distinct; widen until the step itself round-trips at that precision.
    while dec < 8 and abs(round(step, dec) - step) > abs(step) / 1000.0:
        dec += 1
    # ScalarFormatter uses one precision for the whole tick set. Retaining
    # those zeros (0.00 beside ±0.25) makes magnitude and spacing legible and
    # matches Matplotlib's default formatter.
    return f"{v:.{min(dec, 8)}f}"


# `<prefix>(,).N[f|%]<suffix>` — the numeric format grammar of
# spec/api/styling.md. Deliberately the same regex as `fmtNumberSpec` in
# js/src/30_ticks.ts: an axis must not read "$1,000,000" in the browser and
# "1.0e6" in the PNG someone pastes into a report.
_NUMBER_SPEC = re.compile(r"^([^,.%]*)(,)?\.([0-9]+)(f?)(%?)([^,.%]*)$")

# The client's strftime subset (`fmtTimeSpec`). Kept narrow on purpose: a token
# Python's strftime knows and the browser's formatter does not would render one
# way live and another way exported.
_TIME_SPEC = re.compile(r"%[YmdHMSbB]")


def _fmt_number_spec(v: float, spec: Any) -> Optional[str]:
    """Apply a numeric format string, or None when it does not apply."""
    if not isinstance(spec, str) or not np.isfinite(v):
        return None
    match = _NUMBER_SPEC.match(spec)
    if match is None:
        return None
    prefix, group, digits_text, f, pct, suffix = match.groups()
    # The bare `.N` core takes no affixes, so the historical grammar parses
    # identically to how it always did.
    if not f and not pct and (prefix or suffix):
        return None
    digits = int(digits_text)
    value = v * 100.0 if pct else v
    text = f"{value:,.{digits}f}" if group else f"{value:.{digits}f}"
    return f"{prefix}{text}{'%' if pct else ''}{suffix}"


def _fmt_time_spec(ms: float, spec: Any) -> Optional[str]:
    """Apply a strftime-subset format string, or None when it does not apply."""
    if not isinstance(spec, str) or not np.isfinite(ms):
        return None
    try:
        d = datetime.fromtimestamp(ms / 1e3, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    tokens = {
        "%Y": str(d.year),
        "%m": f"{d.month:02d}",
        "%d": f"{d.day:02d}",
        "%H": f"{d.hour:02d}",
        "%M": f"{d.minute:02d}",
        "%S": f"{d.second:02d}",
        "%b": _MONTHS[d.month - 1],
        "%B": _MONTHS_LONG[d.month - 1],
    }
    return _TIME_SPEC.sub(lambda m: tokens[m.group(0)], spec)


def _fmt_log(v: float) -> str:
    """Label a log-scale tick from its own magnitude.

    Decade ticks are multiplicative, so the linear formatter's
    step-derived precision rounds every decade under 1.0 to a bare "0" —
    0.001 and 0.01 became two identical, wrong labels."""
    av = abs(v)
    if av >= 1e6 or (av != 0 and av < 1e-4):
        return f"{v:.1e}".replace("e+0", "e").replace("e-0", "e-").replace("e+", "e")
    dec = max(0, int(np.ceil(-np.log10(av)))) if av and av < 1 else 0
    return f"{v:.{min(dec, 8)}f}"


# Everything a formatted number can carry that is not part of its value:
# the affixes the spec grammar allows ("$", "K", "%") and the group separators.
_NON_NUMERIC = re.compile(r"[^0-9eE+.\-]")


def _collapsed_to_zero(formatted: Optional[str]) -> bool:
    """Whether a formatted label has lost the value it was meant to show.

    Tests the numeric CORE, not the whole label: the grammar allows prefixes
    and suffixes, so a `"$,.0f"` axis produces `"$0"` for a sub-unit decade.
    Comparing the affixed string against zero read `float("$0")`, which raises
    and took the entire render down with it — and `Number("$0")` on the client
    is `NaN`, so that side shipped the collapsed label instead. Two different
    wrong answers from the layer that exists to keep them identical."""
    if formatted is None:
        return True
    core = _NON_NUMERIC.sub("", formatted)
    if not core:
        return True
    try:
        return float(core) == 0.0
    except ValueError:
        return False


def _fmt_angle(value: float, unit: str, step: float = 1.0) -> str:
    """Angular tick text. Mirrors `fmtAngle` in js/src/30_ticks.ts.

    Degrees get a degree sign; radians are written as multiples of pi, because
    "2.094" is not a readable angle and "2pi/3" is. `step` sets the degree
    precision: the generated ladder is all integers, but authored fractional
    tick_values (a 22.5° compass grid) mislabel under a hardcoded step of 1.
    """
    if unit == "degrees":
        return f"{_fmt_linear(value, step or 1.0)}°"
    if abs(value) < 1e-12:
        return "0"
    frac = value / math.pi
    for denominator in (1, 2, 3, 4, 6, 8, 12):
        scaled = frac * denominator
        nearest = round(scaled)
        # 1e-6, not 1e-9 — mirrors fmtAngle in js/src/30_ticks.ts: hover
        # values arrive f32-decoded, and pi/2 misses its f64 self by ~2e-8.
        if nearest and abs(scaled - nearest) < 1e-6:
            numerator = "" if abs(nearest) == 1 else str(abs(nearest))
            sign = "-" if nearest < 0 else ""
            body = f"{sign}{numerator}π"
            return body if denominator == 1 else f"{body}/{denominator}"
    return _fmt_linear(value, 0.01)


def _fmt_axis(axis: dict[str, Any], v: float, step: float) -> str:
    # Mirrors the same first branch in `fmtAxis` (js/src/30_ticks.ts).
    kind = axis.get("kind")
    if kind == "category":
        cats = axis.get("categories") or []
        i = round(v)
        return str(cats[i]) if 0 <= i < len(cats) else ""
    if axis.get("theta_unit"):
        # An authored `format` wins over the angular default. It used to lose:
        # this branch ran first, so `theta_axis(format="{:.0f} deg")` shipped, was
        # accepted, and was then overwritten by the built-in degree/radian text in
        # every renderer. The default only applies when nothing was authored.
        authored = _fmt_number_spec(v, axis.get("format"))
        return authored if authored is not None else _fmt_angle(v, axis["theta_unit"], step)
    if kind == "time":
        return _fmt_time_spec(v, axis.get("format")) or _fmt_time(v, step)
    formatted = _fmt_number_spec(v, axis.get("format"))
    # A fixed-decimal spec collapses sub-unit decades ("0.001" at `.0f`), and so
    # does the linear fallback; the magnitude-derived label is the useful one
    # either way. Mirrors `fmtAxis`.
    if axis.get("scale") == "log" and 0 < v < 1 and _collapsed_to_zero(formatted):
        return _fmt_log(v)
    return formatted if formatted is not None else _fmt_linear(v, step)


def _tick_text(axis: dict[str, Any], value: float, step: float) -> str:
    values = axis.get("tick_values")
    labels = axis.get("tick_labels")
    if values is not None and labels is not None:
        for index, candidate in enumerate(values):
            if float(candidate) == value and index < len(labels):
                return str(labels[index])
    return _fmt_axis(axis, value, step)


# ---------------------------------------------------------------------------
# Payload decode + scales
# ---------------------------------------------------------------------------


def _column(blob: bytes, meta: dict[str, Any]) -> np.ndarray:
    dtype = np.uint8 if meta.get("dtype") == "u8" else np.float32
    raw = np.frombuffer(blob, dtype=dtype, count=meta["len"], offset=meta["byte_offset"])
    return raw.astype(np.float64) / (meta.get("scale") or 1.0) + meta.get("offset", 0.0)


def _density_column(blob: bytes, meta: dict[str, Any], density: dict[str, Any]) -> np.ndarray:
    """Decode either legacy f32 counts or the compact log-u8 density wire."""
    if density.get("enc") != "log-u8":
        return _column(blob, meta)
    values = np.frombuffer(
        blob, dtype=np.uint8, count=meta["len"], offset=meta["byte_offset"]
    ).astype(np.float64)
    maximum = float(density.get("max") or 0.0)
    if maximum <= 0.0:
        return np.zeros(len(values), dtype=np.float64)
    return np.expm1((values / 255.0) * np.log1p(maximum))


class _Scale:
    """value -> px for one axis (linear / time-in-ms / log / category)."""

    def __init__(self, axis: dict[str, Any], px0: float, px1: float) -> None:
        self.kind = axis.get("kind", "linear")
        lo, hi = axis["range"]
        # ``kind`` describes the data domain (linear/time/category), while the
        # public axis option is serialized separately as ``scale``. Accept the
        # historical kind form too for old payloads.
        self.log = axis.get("scale") == "log" or self.kind == "log"
        self.nonpositive = axis.get("nonpositive", "clip")
        self.symlog = axis.get("scale") == "symlog"
        self.constant = float(axis.get("constant", 1.0))
        if self.log:
            lo, hi = np.log10(max(lo, 1e-300)), np.log10(max(hi, 1e-300))
        elif self.symlog:
            lo, hi = self._symlog(lo), self._symlog(hi)
        self.lo, self.hi = float(lo), float(hi)
        self.px0, self.px1 = px0, px1

    def coord(self, v: Any) -> Any:
        if self.log:
            values = np.asarray(v)
            if self.nonpositive == "mask":
                with np.errstate(divide="ignore", invalid="ignore"):
                    return np.where(values > 0, np.log10(values), np.nan)
            return np.log10(np.maximum(values, 1e-300))
        return self._symlog(v) if self.symlog else v

    def _symlog(self, v: Any) -> Any:
        value = np.asarray(v)
        return np.sign(value) * np.log1p(np.abs(value) / self.constant)

    def __call__(self, v: Any) -> Any:
        c = self.coord(v)
        span = (self.hi - self.lo) or 1.0
        return self.px0 + (c - self.lo) / span * (self.px1 - self.px0)

    def value(self, c: Any) -> Any:
        """Inverse of `coord`: scale coordinate back to a data value."""
        if self.log:
            return np.power(10.0, c)
        if self.symlog:
            c = np.asarray(c)
            return np.sign(c) * self.constant * np.expm1(np.abs(c))
        return c

    @property
    def affine(self) -> bool:
        return not (self.log or self.symlog)


# Direction that theta=0 points, as an angle in radians measured
# counterclockwise from due East. Mirrored by THETA_ZERO in
# js/src/50_chartview.ts.
THETA_ZERO = {"E": 0.0, "N": math.pi / 2.0, "W": math.pi, "S": -math.pi / 2.0}


class _PolarProjection:
    """(theta, r) -> px for a polar chart — spec/design/polar-axes.md §3.

    The joint replacement for the separable `_Scale` pair: polar position needs
    both coordinates at once, so this is *not* two 1-D maps. `theta` and `r`
    still arrive in scaled data space (a `_Scale.coord` has already applied any
    log/symlog), and this class only performs the final placement.

    Screen space grows downward, so the y term is a **subtraction**. The GLSL
    twin in `xyPolar` (js/src/40_gl.ts) adds instead, because clip space grows
    upward. `tests/test_polar_transform.py` binds both to the same fixtures.
    """

    def __init__(
        self,
        theta_axis: dict[str, Any],
        r_axis: dict[str, Any],
        plot: dict[str, float],
    ) -> None:
        self.plot = plot
        self.theta_axis = theta_axis
        self.r_axis = r_axis
        self.unit = theta_axis.get("theta_unit", "radians")
        self.unit_scale = math.pi / 180.0 if self.unit == "degrees" else 1.0
        self.turn = 360.0 if self.unit == "degrees" else 2.0 * math.pi
        zero = theta_axis.get("theta_zero", "E")
        self.zero = THETA_ZERO[zero] if isinstance(zero, str) else float(zero)
        self.direction = theta_axis.get("theta_direction", "counterclockwise")
        self.dir = -1.0 if self.direction == "clockwise" else 1.0
        sector = theta_axis.get("sector") or (0.0, self.turn)
        self.sector_start, self.sector_end = (float(sector[0]), float(sector[1]))
        self.sector_span = self.sector_end - self.sector_start
        self.full_sector = self.sector_span >= self.turn * (1.0 - 1e-9)
        self.sector_a0 = self.zero + self.dir * self.unit_scale * self.sector_start
        self.sector_a1 = self.zero + self.dir * self.unit_scale * self.sector_end
        self.grid_shape = theta_axis.get("grid_shape", "circular")
        self.categories = tuple(theta_axis.get("categories") or ())
        self.category_count = len(self.categories)

        r_lo, r_hi = r_axis["range"]
        self.r_lo, self.r_hi = float(r_lo), float(r_hi)
        self.r_scale = _Scale(r_axis, 0.0, 1.0)
        self.r_lo_coord = float(self.r_scale.coord(self.r_lo))
        self.r_hi_coord = float(self.r_scale.coord(self.r_hi))
        origin = r_axis.get("r_origin")
        self.r_origin = self.r_lo if origin is None else float(origin)
        self.r_origin_coord = float(self.r_scale.coord(self.r_origin))
        self.hole = float(r_axis.get("hole") or 0.0)

        # Full turns retain the original normative layout exactly. A partial
        # sector instead fills the plot with its own bounding box: a gauge must
        # not reserve dead space for the missing part of the circle.
        if self.full_sector:
            self.radius = min(plot["w"], plot["h"]) / 2.0
            self.cx = plot["x"] + plot["w"] / 2.0
            self.cy = plot["y"] + plot["h"] / 2.0
        else:
            lo_angle = min(self.sector_a0, self.sector_a1)
            hi_angle = max(self.sector_a0, self.sector_a1)
            angles = [self.sector_a0, self.sector_a1]
            for cardinal in (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0):
                first = math.ceil((lo_angle - cardinal) / (2.0 * math.pi))
                last = math.floor((hi_angle - cardinal) / (2.0 * math.pi))
                angles.extend(
                    cardinal + turn_index * 2.0 * math.pi for turn_index in range(first, last + 1)
                )
            angles_array = np.asarray(angles, dtype=np.float64)
            inner = max(0.0, min(1.0, float(self.norm_radius(self.r_lo))))
            xs = np.concatenate((np.cos(angles_array), inner * np.cos(angles_array)))
            ys = np.concatenate((-np.sin(angles_array), -inner * np.sin(angles_array)))
            if inner <= 1e-12:
                xs = np.append(xs, 0.0)
                ys = np.append(ys, 0.0)
            xmin, xmax = float(np.min(xs)), float(np.max(xs))
            ymin, ymax = float(np.min(ys)), float(np.max(ys))
            xspan = max(xmax - xmin, 1e-12)
            yspan = max(ymax - ymin, 1e-12)
            self.radius = min(plot["w"] / xspan, plot["h"] / yspan)
            left = plot["x"] + (plot["w"] - self.radius * xspan) / 2.0
            top = plot["y"] + (plot["h"] - self.radius * yspan) / 2.0
            self.cx = left - self.radius * xmin
            self.cy = top - self.radius * ymin

    def theta_value(self, theta: Any) -> Any:
        """Category code or numeric theta -> angular value in declared units."""
        th = np.asarray(theta, dtype=np.float64)
        if not self.category_count:
            return th
        divisor = (
            float(self.category_count)
            if self.full_sector
            else float(max(self.category_count - 1, 1))
        )
        return self.sector_start + th * self.sector_span / divisor

    def angle(self, theta: Any) -> Any:
        """Data theta -> screen angle in radians, ccw from East."""
        th = self.theta_value(theta) * self.unit_scale
        return self.zero + self.dir * th

    def theta_from_angle(self, angle: Any, *, near: Optional[float] = None) -> Any:
        """Screen angle -> numeric theta/category code.

        The result is wrapped relative to the authored sector. ``near`` is a
        heatmap range start and selects the equivalent full-turn value nearest
        that grid, matching the fragment shader at the angular seam.
        """
        raw = (np.asarray(angle, dtype=np.float64) - self.zero) / (self.dir * self.unit_scale)
        anchor = self.sector_start if near is None else float(near)
        raw = anchor + np.mod(raw - anchor, self.turn)
        if not self.category_count:
            return raw
        divisor = (
            float(self.category_count)
            if self.full_sector
            else float(max(self.category_count - 1, 1))
        )
        return (raw - self.sector_start) * divisor / (self.sector_span or 1.0)

    def theta_visible_mask(self, theta: Any) -> np.ndarray:
        """Which angular values fall in the authored sector."""
        raw = np.asarray(self.theta_value(theta), dtype=np.float64)
        return self._angular_value_visible_mask(raw)

    def _angular_value_visible_mask(self, raw: Any) -> np.ndarray:
        raw = np.asarray(raw, dtype=np.float64)
        if self.full_sector:
            return np.isfinite(raw)
        offset = np.mod(raw - self.sector_start, self.turn)
        return np.isfinite(raw) & (offset <= self.sector_span + self.turn * 1e-9)

    def angle_visible(self, angle: float) -> bool:
        raw = (float(angle) - self.zero) / (self.dir * self.unit_scale)
        return bool(self._angular_value_visible_mask(raw))

    def filter_theta_values(self, values: Sequence[float]) -> list[float]:
        if not values:
            return []
        mask = self.theta_visible_mask(values)
        return [float(value) for value, keep in zip(values, mask, strict=True) if bool(keep)]

    def norm_radius(self, r: Any) -> Any:
        coord = np.asarray(self.r_scale.coord(r), dtype=np.float64)
        span = self.r_hi_coord - self.r_origin_coord
        if abs(span) <= 1e-30:
            return np.full_like(coord, np.nan, dtype=np.float64)
        base = (coord - self.r_origin_coord) / span
        return self.hole + (1.0 - self.hole) * base

    def radius_value(self, normalized: Any) -> Any:
        """Inverse of ``norm_radius`` back to radial data space."""
        normalized = np.asarray(normalized, dtype=np.float64)
        base = (normalized - self.hole) / max(1.0 - self.hole, 1e-30)
        coord = self.r_origin_coord + base * (self.r_hi_coord - self.r_origin_coord)
        return self.r_scale.value(coord)

    @property
    def inner_fraction(self) -> float:
        return max(0.0, min(1.0, float(self.norm_radius(self.r_lo))))

    @property
    def inner_radius(self) -> float:
        return self.inner_fraction * self.radius

    def visible_mask(self, r: Any) -> np.ndarray:
        """Which radii have an honest polar position — `xyPolarPos`'s cull.

        Below the radial minimum a point would mirror through the centre into
        the opposite quadrant (still *inside* the disc, so no clip saves it);
        above the maximum it lands past the outer ring. Even though both static
        exporters now have a shaped mark clip, invalid data vertices must still
        split paths consistently with the client's shader NaN cull
        (`rn < 0 || rn > 1 + 1e-6` in js/src/40_gl.ts). Same epsilon, so the
        outermost home-view point survives everywhere.
        """
        coord = np.asarray(self.r_scale.coord(r), dtype=np.float64)
        lo = min(self.r_lo_coord, self.r_hi_coord)
        hi = max(self.r_lo_coord, self.r_hi_coord)
        return np.isfinite(coord) & (coord >= lo - 1e-6) & (coord <= hi + 1e-6)

    def position_mask(self, theta: Any, r: Any) -> np.ndarray:
        return self.theta_visible_mask(theta) & self.visible_mask(r)

    def __call__(self, theta: Any, r: Any) -> tuple[Any, Any]:
        a = self.angle(theta)
        rn = self.norm_radius(r) * self.radius
        return self.cx + rn * np.cos(a), self.cy - rn * np.sin(a)

    def ring(self, r: float, steps: int = 180) -> list[tuple[float, float]]:
        """A constant-r sector arc (a closed circle for a full turn).

        The raster display list has no arc, wedge or circle opcode — every
        curve is a pre-flattened polygon (`_round_rect_pts` is the existing
        precedent) — so grid rings flatten here and both exporters consume the
        same points.
        """
        rn = float(self.norm_radius(r)) * self.radius
        count = steps if self.full_sector else steps + 1
        return [
            (
                self.cx
                + rn * math.cos(self.sector_a0 + (self.sector_a1 - self.sector_a0) * i / steps),
                self.cy
                - rn * math.sin(self.sector_a0 + (self.sector_a1 - self.sector_a0) * i / steps),
            )
            for i in range(count)
        ]

    def polygon_ring(self, r: float, theta_values: Sequence[float]) -> list[tuple[float, float]]:
        values = self.filter_theta_values(theta_values)
        if not values:
            return []
        values.sort(
            key=lambda value: float(
                np.mod(float(self.theta_value(value)) - self.sector_start, self.turn)
            )
        )
        values = [
            value
            for index, value in enumerate(values)
            if index == 0
            or not math.isclose(
                float(
                    np.mod(
                        float(self.theta_value(value)) - float(self.theta_value(values[index - 1])),
                        self.turn,
                    )
                ),
                0.0,
                rel_tol=0,
                abs_tol=self.turn * 1e-10,
            )
        ]
        if not self.full_sector:
            if not math.isclose(
                float(self.theta_value(values[0])), self.sector_start, rel_tol=0, abs_tol=1e-9
            ):
                values.insert(0, self._theta_data_for_sector(self.sector_start))
            if not math.isclose(
                float(self.theta_value(values[-1])), self.sector_end, rel_tol=0, abs_tol=1e-9
            ):
                values.append(self._theta_data_for_sector(self.sector_end))
        x, y = self(values, np.full(len(values), r, dtype=np.float64))
        return list(zip(np.asarray(x, dtype=float), np.asarray(y, dtype=float), strict=True))

    def _theta_data_for_sector(self, value: float) -> float:
        if not self.category_count:
            return value
        divisor = (
            float(self.category_count)
            if self.full_sector
            else float(max(self.category_count - 1, 1))
        )
        return (value - self.sector_start) * divisor / (self.sector_span or 1.0)

    def wedge_angles(self, theta0: float, theta1: float) -> Optional[tuple[float, float]]:
        """Visible screen-angle interval for an authored angular band."""
        raw0 = float(self.theta_value(theta0))
        raw1 = float(self.theta_value(theta1))
        if not (math.isfinite(raw0) and math.isfinite(raw1)):
            return None
        if self.full_sector:
            return (
                self.zero + self.dir * self.unit_scale * raw0,
                self.zero + self.dir * self.unit_scale * raw1,
            )

        low, high = min(raw0, raw1), max(raw0, raw1)
        midpoint = (low + high) / 2.0
        sector_midpoint = (self.sector_start + self.sector_end) / 2.0
        nearest_turn = round((sector_midpoint - midpoint) / self.turn)
        best: Optional[tuple[float, float]] = None
        best_span = -1.0
        for turn_index in (nearest_turn - 1, nearest_turn, nearest_turn + 1):
            shifted_low = low + turn_index * self.turn
            shifted_high = high + turn_index * self.turn
            clipped_low = max(self.sector_start, shifted_low)
            clipped_high = min(self.sector_end, shifted_high)
            span = clipped_high - clipped_low
            if span > best_span and span > 1e-12:
                best = (clipped_low, clipped_high)
                best_span = span
        if best is None:
            return None
        clipped0, clipped1 = best if raw0 <= raw1 else (best[1], best[0])
        return (
            self.zero + self.dir * self.unit_scale * clipped0,
            self.zero + self.dir * self.unit_scale * clipped1,
        )

    def frame_points(
        self, theta_values: Sequence[float] = (), steps: int = 180
    ) -> list[tuple[float, float]]:
        if self.grid_shape == "linear" and theta_values:
            return self.polygon_ring(self.r_hi, theta_values)
        return self.ring(self.r_hi, steps)

    @property
    def affine(self) -> bool:
        """Never affine — see `affine_fast_path`."""
        return False


def affine_fast_path(
    sx: "_Scale", sy: "_Scale", polar: "Optional[_PolarProjection]" = None
) -> bool:
    """May an emitter bake a straight-line data->pixel map into Rust?

    Several emitters hand Rust two affine scales and let it project while
    painting. A polar chart on linear axes satisfies `sx.affine and sy.affine`
    while being emphatically non-affine, so every such gate must ask this
    instead — one predicate rather than a `polar is None` conjunct repeated at
    each site, which is how one gate got missed and shipped a colormapped polar
    scatter projected as cartesian (§6).
    """
    return polar is None and sx.affine and sy.affine


def _colormap_key(colormap: Any) -> str:
    """A stable, document-unique id fragment for a colormap — a built-in name,
    or the digest of a custom ramp's stops (two colorbars in one document must
    not share a `<linearGradient>` id unless they are the same ramp)."""
    if isinstance(colormap, str):
        return colormap
    return "custom-" + hashlib.sha256(repr(_colormap_stops(colormap)).encode()).hexdigest()[:12]


def _colormap_stops(colormap: Any) -> list[tuple[int, int, int]]:
    """Evenly spaced RGB stops for a shipped colormap.

    Mirrors `colormapStops` in js/src/10_colormaps.ts: a string names a
    built-in table (`_r` reverses it), while a sequence is an already-resolved
    custom ramp (`channels.resolve_colormap`) and is used verbatim."""
    if not isinstance(colormap, str):
        return [(int(r), int(g), int(b)) for r, g, b in colormap]
    reversed_map = colormap.endswith("_r")
    base = colormap[:-2] if reversed_map else colormap
    stops = COLORMAP_STOPS.get(base) or COLORMAP_STOPS["viridis"]
    return list(reversed(stops)) if reversed_map else stops


def _lut(colormap: Any, t: np.ndarray) -> np.ndarray:
    """Vectorized colormap sample: t in [0,1] -> (n,3) uint8, matching the
    client's 256-texel LUT interpolation."""
    stops = np.array(_colormap_stops(colormap), dtype=np.float64)
    pos = np.clip(t, 0.0, 1.0) * (len(stops) - 1)
    # int32, not uint8: a resampled custom ramp ships 256 stops, whose top
    # index is exactly 255 -- one more stop would wrap to 0 and paint the
    # ramp's dark end at its bright end.
    lo = np.floor(pos).astype(np.int32)
    hi = np.minimum(lo + 1, len(stops) - 1)
    fraction = pos - lo
    out = np.empty((len(pos), 3), dtype=np.uint8)
    # Channel-wise interpolation is numerically identical to the broadcasted
    # `(n, 3)` expression but avoids three multi-megabyte float temporaries.
    for channel in range(3):
        start = stops[lo, channel]
        out[:, channel] = np.round(start + (stops[hi, channel] - start) * fraction).astype(np.uint8)
    return out


def _paint_rgba8(css: Any) -> tuple[int, int, int, int]:
    """Resolve a validated CSS paint for static density images."""
    from . import kernels

    _status, rgba = kernels.css_check(kernels.CSS_COLOR, str(css))
    if rgba is None:
        rgba = _STATIC_COLOR_FALLBACK
    red, green, blue, alpha = rgba
    return (
        int(round(red * 255)),
        int(round(green * 255)),
        int(round(blue * 255)),
        int(round(alpha * 255)),
    )


def _css(c: Any, fallback: str) -> str:
    """Resolve static colors after chart-level tokens have been expanded."""
    s = str(c or "").strip()
    if not s or s.lower() == "currentcolor" or s.lower().startswith("var("):
        return fallback
    return s


_TEXT_ANCHORS = {"start": "start", "center": "middle", "end": "end"}


def _tick_label_anchor(axis: dict[str, Any], style: dict[str, Any], default: str) -> str:
    """Canonical tick-label anchor (``start``/``center``/``end``) from the
    axis spec or its style — validators normalize the mpl aliases upstream —
    with ``default`` (the classic layout) when unset."""
    raw = axis.get("tick_label_anchor") or style.get("tick_label_anchor")
    return raw if raw in ("start", "center", "end") else default


def _px_size(value: Any, default: float) -> float:
    """Tolerant CSS px length — `15` or `"15px"` — matching the browser, where
    annotation styles land as CSS declarations; `default` on anything else."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().removesuffix("px"))
        except ValueError:
            return default
    return default


#: Text properties the VECTOR writers honor on a chrome slot (SVG, and PDF via
#: the same markup). Each maps one-to-one onto an SVG presentation attribute.
SLOT_TEXT_PROPS: tuple[str, ...] = (
    "font-size",
    "font-weight",
    "font-style",
    "font-family",
    "letter-spacing",
    "fill",
    "color",
    "opacity",
)

#: What the RASTER writer honors. The baked atlas carries a regular, a bold and
#: an italic face, so weight and style survive — a weight >= 600 rounds up to
#: the bold face (`_raster._native_font_emphasis`). It has no family axis and no
#: per-glyph advance control, so `font-family` and `letter-spacing` are
#: vector-only, and `opacity` is not read rather than being silently
#: approximated (§28). `SLOT_TEXT_PROPS` minus this tuple is the vector-only set.
SLOT_RASTER_PROPS: tuple[str, ...] = (
    "font-size",
    "font-weight",
    "font-style",
    "fill",
    "color",
)

#: The `colorbar` slot's own font size, from its stylesheet rule in
#: `js/src/20_theme.ts`. Every writer names it so none of them inherits a
#: different one from its document root.
COLORBAR_FONT_SIZE = 10.0

#: Slots the native writers style. Every one names chrome that a static file
#: actually contains; the rest of `CHART_DOM_SLOTS` is live-only chrome
#: (tooltip, modebar, crosshair, selection, badge) or a container with no
#: painted text of its own, and stays browser-only.
STATIC_STYLED_SLOTS: tuple[str, ...] = (
    "title",
    "axis_title",
    "tick_label",
    "legend",
    "legend_title",
    "legend_label",
    "colorbar",
    "colorbar_title",
    "colorbar_tick",
)


def slot_styles(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """`styles={slot: {...}}` from the payload, normalized to kebab-case CSS.

    `chrome_styles` keeps whatever spelling the caller used (`font_size` and
    `font-size` both reach the browser, which sees the same declaration); the
    static writers match on property names, so they need one spelling.
    """
    raw = (spec.get("dom") or {}).get("styles") or {}
    out: dict[str, dict[str, Any]] = {}
    for slot, decls in raw.items():
        if not isinstance(decls, dict):
            continue
        out[str(slot)] = {
            (k if str(k).startswith("--") else str(k).replace("_", "-")): v
            for k, v in decls.items()
        }
    return out


#: `styles={"legend": ...}` is CSS; `xy.legend(style=...)` reaches the writers
#: under the browser's camelCase property spelling. Same declaration, two
#: spellings — the writers key on the second, so the first is translated.
_LEGEND_SLOT_ALIASES: dict[str, str] = {
    "background-color": "background",
    "box-shadow": "boxShadow",
    "border-radius": "borderRadius",
    "row-gap": "rowGap",
}


def legend_options_with_slot(spec: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Fold the chart-level legend styling into a legend's own options, so every
    spelling that agrees in the browser also agrees in a file.

    Three sources, widest first: the `--chart-legend-bg` theme token, the
    `styles={"legend": ...}` slot, then `xy.legend(style=...)` — the narrowest
    selector and the winner.
    """
    slot = slot_styles(spec).get("legend") or {}
    token = (spec.get("dom") or {}).get("style", {}).get("--chart-legend-bg")
    own = options.get("style") or {}
    if not slot and token is None and not own:
        return options

    def canonical(style: dict[str, Any]) -> dict[str, Any]:
        return {_LEGEND_SLOT_ALIASES.get(str(key), str(key)): value for key, value in style.items()}

    folded: dict[str, Any] = {}
    if token is not None:
        # The browser's rule is `background:var(--chart-legend-bg, <default>)`,
        # so the token is the frame's paint, at full strength.
        folded["background"] = token
    folded.update(canonical(slot))
    # `xy.legend(style=...)` is canonicalized too. It happens to reach the
    # writers through `chrome_styles` as well today, but a legend built without
    # that mirror — an extra legend, or an adapter — would otherwise lose its
    # kebab-case declarations here.
    folded.update(canonical(own))
    return {**options, "style": folded}


def slot_text_color(style: dict[str, Any], fallback: str) -> str:
    """A slot's resolved text paint. `fill` is the SVG spelling and wins; CSS
    authors reach for `color`, so both are accepted."""
    for prop in ("fill", "color"):
        value = style.get(prop)
        if value is not None:
            resolved = _css(value, "")
            if resolved:
                return resolved
    return fallback


def _slot_size_attr(style: dict[str, Any]) -> str:
    """` font-size="N"` only when the slot asks for one. Text that inherits the
    root `font-size` must keep inheriting it when unstyled, so that existing
    output stays byte-identical."""
    if "font-size" not in style:
        return ""
    return f' font-size="{_num(_px_size(style["font-size"], 11.0))}"'


def slot_font_size(style: dict[str, Any], default: float) -> float:
    """A slot's resolved font size in px, or `default`."""
    return _px_size(style.get("font-size"), default) if "font-size" in style else default


def slot_text_attrs(style: dict[str, Any], **defaults: Any) -> str:
    """Extra SVG `<text>` attributes for a slot's non-paint text properties.

    `font-size` and the paint are resolved by the caller (they have per-slot
    defaults and feed the raster writer too); this covers the rest, which map
    one-to-one onto SVG presentation attributes. `defaults` carries the
    writer's own values under their Python spelling (`font_weight="600"`) and
    each is emitted exactly once — a repeated attribute is malformed XML, and
    the parser would keep the first, silently discarding the author's.
    """
    parts: list[str] = []
    for prop in ("font-weight", "font-style", "font-family", "letter-spacing", "opacity"):
        value = style.get(prop, defaults.get(prop.replace("-", "_")))
        if value is None:
            continue
        if prop == "letter-spacing" and not isinstance(value, str):
            value = _num(_px_size(value, 0.0))
        # `_escape_attr`, not `escape`: a font-family stack quotes any name with
        # a space (`"Times New Roman", serif`), and a bare `"` closes the
        # attribute and breaks the document.
        parts.append(f' {prop}="{_escape_attr(value)}"')
    return "".join(parts)


def apply_export_background(spec: dict[str, Any], background: Optional[str]) -> None:
    """Apply the unified export API's `background=` override to a payload spec.

    An explicit export background replaces the ENTIRE painted backdrop — the
    canvas underlay, the theme figure patch (`theme(background=)`), and the
    plot-rect fill (`--chart-bg`) — so the requested color (or transparency)
    is what actually shows regardless of chart theme, instead of being buried
    under the theme paints. The plot token becomes "transparent" rather than
    the override color so translucent backgrounds composite exactly once.
    Shared by the raster exporter and (via SVG) the PDF exporter."""
    if background is None:
        return
    spec["canvas_background"] = background
    dom = spec.setdefault("dom", {})
    if isinstance(dom, dict):
        style = dom.setdefault("style", {})
        if isinstance(style, dict):
            style.pop("background", None)
            style["--chart-bg"] = "transparent"


def _solid_paint(css: Any) -> Optional[str]:
    """A parseable solid CSS color string, or None when unset/unpaintable
    (var(), gradients) — for background rects that must be omitted rather
    than fallback-painted. Fully transparent colors (alpha 0, e.g. the
    export background override's plot token) are pure no-op fills and are
    omitted as well."""
    from . import kernels

    s = _css(css, "")
    if not s:
        return None
    _status, rgba = kernels.css_check(kernels.CSS_COLOR, s)
    if rgba is None or rgba[3] == 0:
        return None
    return s


_CSS_VAR_RE = re.compile(
    r"^var\(\s*(--[A-Za-z_][A-Za-z0-9_-]*)\s*(?:,\s*(.+))?\)$",
    re.DOTALL | re.IGNORECASE,
)
_STATIC_PAINT_KEYS = frozenset(
    {
        "axis_color",
        "background",
        "canvas_background",
        "color",
        "fill",
        "grid_color",
        "label_color",
        "line_color",
        "stroke",
        "stroke_color",
        "tick_color",
    }
)


def _resolve_css_var(value: Any, variables: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    """Resolve a complete ``var(--token[, fallback])`` static paint value."""
    if not isinstance(value, str):
        return value
    match = _CSS_VAR_RE.fullmatch(value.strip())
    if match is None:
        return value
    name, fallback = match.groups()
    if name in seen:
        return fallback.strip() if fallback is not None else value
    replacement = variables.get(name, fallback)
    if replacement is None:
        return value
    if isinstance(replacement, str):
        replacement = replacement.strip()
    return _resolve_css_var(replacement, variables, (*seen, name))


def _resolve_static_css_vars(spec: dict[str, Any]) -> dict[str, Any]:
    """Resolve chart-level color tokens with a copy-on-write spec traversal.

    This deliberately handles complete color-token references only. Browser
    expressions containing variables, such as ``color-mix(...)``, retain the
    documented native fallback instead of approximating the browser CSS engine.
    """
    dom_style = (spec.get("dom") or {}).get("style") or {}
    variables = {key: value for key, value in dom_style.items() if key.startswith("--")}

    def resolve_stops(value: Any) -> Any:
        if not isinstance(value, list):
            return value
        changed = False
        out: list[Any] = []
        for stop in value:
            if isinstance(stop, (list, tuple)) and len(stop) >= 2:
                paint = _resolve_css_var(stop[1], variables)
                if paint != stop[1]:
                    changed = True
                    copied = list(stop)
                    copied[1] = paint
                    out.append(copied if isinstance(stop, list) else tuple(copied))
                    continue
            out.append(stop)
        return out if changed else value

    def rewrite(value: Any) -> Any:
        if isinstance(value, dict):
            changed = False
            out: dict[Any, Any] = {}
            for key, item in value.items():
                if key == "stops":
                    resolved = resolve_stops(item)
                elif isinstance(item, str) and (
                    key in _STATIC_PAINT_KEYS
                    or (isinstance(key, str) and (key.startswith("--") or key.endswith("_color")))
                ):
                    resolved = _resolve_css_var(item, variables)
                else:
                    resolved = rewrite(item)
                changed = changed or resolved is not item
                out[key] = resolved
            return out if changed else value
        if isinstance(value, list):
            out = [rewrite(item) for item in value]
            return (
                out if any(new is not old for new, old in zip(out, value, strict=True)) else value
            )
        return value

    return rewrite(spec)


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _axis_grid_attrs(style: dict[str, Any]) -> str:
    opacity = float(style.get("grid_opacity", 1.0))
    dash = _AXIS_GRID_DASHES.get(str(style.get("grid_dash", "solid")))
    return (f' stroke-opacity="{_num(opacity)}"' if opacity < 1 else "") + (
        f' stroke-dasharray="{",".join(_num(value) for value in dash)}"' if dash else ""
    )


# Embedded heatmap/density rasters use the shared truecolor PNG encoder.
_png_rgba = _png.png_truecolor


def _monotone_tangents(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fritsch–Carlson tangents — the same construction as xySmoothResample."""
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
        raw_stops = fill.get("stops", [])
        resolved = [_css(c, mark_color) for _t, c in raw_stops]
        stops_out: list[str] = []
        for index, ((t, raw_color), color) in enumerate(zip(raw_stops, resolved, strict=True)):
            offset = _num(t * 100)
            if str(raw_color).strip().lower() != "transparent":
                escaped = escape(color, {chr(34): "&quot;"})
                stops_out.append(f'<stop offset="{offset}%" stop-color="{escaped}"/>')
                continue

            # SVG interpolates stop RGB independently from stop opacity. A
            # literal `transparent` stop is transparent black, which makes a
            # colored fade pass through a muddy gray fringe. Give the zero-
            # opacity stop the adjacent visible hue instead, matching the
            # browser renderer's premultiplied-alpha interpolation. When a
            # transparent stop sits between two different colors, duplicate
            # it at the same offset; the invisible color switch preserves the
            # hue on both segments.
            previous = next(
                (
                    resolved[i]
                    for i in range(index - 1, -1, -1)
                    if str(raw_stops[i][1]).strip().lower() != "transparent"
                ),
                None,
            )
            following = next(
                (
                    resolved[i]
                    for i in range(index + 1, len(raw_stops))
                    if str(raw_stops[i][1]).strip().lower() != "transparent"
                ),
                None,
            )
            transparent_colors = [previous or following or mark_color]
            if previous and following and previous != following:
                transparent_colors.append(following)
            for transparent_color in transparent_colors:
                escaped = escape(transparent_color, {chr(34): "&quot;"})
                stops_out.append(
                    f'<stop offset="{offset}%" stop-color="{escaped}" stop-opacity="0"/>'
                )
        stops = "".join(stops_out)
        self.defs.append(f'<linearGradient id="{gid}" {units}>{stops}</linearGradient>')
        return f"url(#{gid})"

    def gradient_vector(
        self, x0: float, y0: float, x1: float, y1: float, stops: list[tuple[float, str, float]]
    ) -> str:
        """Register a two-point <linearGradient> in user space; returns url(#id).

        `gradient()` above is closed over four axis-aligned directions, which is
        the right vocabulary for a bar or an area but cannot express a ribbon's
        gradient — that one runs along the flow, from one face to the other, and
        every band in a diagram has its own. Hence an explicit endpoint pair.
        Each stop is ``(offset, color, opacity)``: per-stop opacity is how the
        alpha channel interpolates along the vector, exactly as the raster's
        RGBA stops and the client's `mix` do. `userSpaceOnUse` and
        `stop-opacity` are both in the PDF converter's allowlist, so this
        survives PDF export unchanged.
        """
        gid = self.uid("g")
        units = (
            f'gradientUnits="userSpaceOnUse" x1="{_num(x0)}" y1="{_num(y0)}" '
            f'x2="{_num(x1)}" y2="{_num(y1)}"'
        )
        parts = []
        for offset, color, opacity in stops:
            escaped = escape(color, {chr(34): "&quot;"})
            alpha = f' stop-opacity="{_num(opacity)}"' if opacity < 1 else ""
            parts.append(f'<stop offset="{_num(offset * 100)}%" stop-color="{escaped}"{alpha}/>')
        self.defs.append(f'<linearGradient id="{gid}" {units}>{"".join(parts)}</linearGradient>')
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
    return _native.svg_poly_path(px, py)


def _polar_visible_runs(
    xv: np.ndarray, yv: np.ndarray, polar: "_PolarProjection"
) -> list[np.ndarray]:
    """Index runs of consecutive vertices the polar transform keeps.

    The same split `_curve_path` performs, exposed so a filled area can close
    each run against its own base instead of stitching every run to one base.
    """
    visible = polar.position_mask(xv, yv)
    if visible.size == 0:
        return []
    idx = np.flatnonzero(visible)
    if idx.size == 0:
        return []
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    return [run for run in runs if len(run) >= 2]


def _area_fill_path(
    xv: np.ndarray,
    yv: np.ndarray,
    bv: np.ndarray,
    sx: _Scale,
    sy: _Scale,
    smooth: bool,
    polar: "Optional[_PolarProjection]" = None,
) -> str:
    """Closed fill path between a top curve and its base, or "" if nothing is
    visible. Under polar each visible run closes separately."""
    if polar is None:
        top = _curve_path(xv, yv, sx, sy, smooth, None)
        base = _curve_path(xv[::-1], bv[::-1], sx, sy, smooth, None)
        return f"{top} L {base[2:]} Z" if top and base else ""
    parts = []
    for run in _polar_visible_runs(xv, yv, polar):
        top = _curve_path(xv[run], yv[run], sx, sy, smooth, polar)
        base = _curve_path(xv[run][::-1], bv[run][::-1], sx, sy, smooth, polar)
        if top and base:
            parts.append(f"{top} L {base[2:]} Z")
    return " ".join(parts)


def _curve_path(
    xv: np.ndarray,
    yv: np.ndarray,
    sx: _Scale,
    sy: _Scale,
    smooth: bool,
    polar: "Optional[_PolarProjection]" = None,
) -> str:
    """Pixel-space path for a polyline; smooth -> exact cubic Béziers of the
    monotone-cubic Hermite (affine axes), else polyline. The Bézier control
    points of a Hermite segment are P0 + h/3·(1, m0) and P1 - h/3·(1, m1),
    and affine axis maps carry control points exactly.

    Under `polar` the separable (sx, sy) pair is replaced by the joint
    projection and the result is always a polyline: consecutive data points are
    joined by straight **chords**, which is Plotly's polar semantics and what
    makes radar/spider edges come out straight (polar-axes.md §5). Vertices
    outside the radial range are culled like the client shader culls them —
    the path splits into visible runs, dropping any chord with a culled
    endpoint whole (§8)."""
    if len(xv) == 0:
        # `visible.all()` is vacuously true on an empty array, so this fell
        # through to the native poly-path builder, which rejects a zero-length
        # buffer. A log radial axis annihilating every row, or an all-NaN
        # series, therefore crashed the export instead of drawing nothing.
        return ""
    if polar is not None:
        px, py = polar(xv, yv)
        visible = polar.position_mask(xv, yv)
        if bool(visible.all()):
            return _poly_path(px, py)
        runs = np.split(
            np.flatnonzero(visible),
            np.flatnonzero(np.diff(np.flatnonzero(visible)) > 1) + 1,
        )
        return " ".join(_poly_path(px[run], py[run]) for run in runs if len(run) >= 2)
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
    "pixel": lambda cx, cy, r: (
        f'<rect x="{_num(cx - r)}" y="{_num(cy - r)}" width="{_num(2 * r)}" height="{_num(2 * r)}"'
    ),
    "square": lambda cx, cy, r: (
        f'<rect x="{_num(cx - r)}" y="{_num(cy - r)}" width="{_num(2 * r)}" height="{_num(2 * r)}"'
    ),
    "diamond": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy - 2**0.5 * r)} '
        f"L {_num(cx + 2**0.5 * r)} {_num(cy)} "
        f"L {_num(cx)} {_num(cy + 2**0.5 * r)} "
        f'L {_num(cx - 2**0.5 * r)} {_num(cy)} Z"'
    ),
    "thin_diamond": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy - 2**0.5 * r)} '
        f"L {_num(cx + 0.6 * 2**0.5 * r)} {_num(cy)} "
        f"L {_num(cx)} {_num(cy + 2**0.5 * r)} "
        f'L {_num(cx - 0.6 * 2**0.5 * r)} {_num(cy)} Z"'
    ),
    "triangle": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy - r)} L {_num(cx + r)} {_num(cy + r)} L {_num(cx - r)} {_num(cy + r)} Z"'
    ),
    "triangle_down": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy + r)} L {_num(cx + r)} {_num(cy - r)} L {_num(cx - r)} {_num(cy - r)} Z"'
    ),
    "triangle_left": lambda cx, cy, r: (
        f'<path d="M {_num(cx - r)} {_num(cy)} L {_num(cx + r)} {_num(cy - r)} L {_num(cx + r)} {_num(cy + r)} Z"'
    ),
    "triangle_right": lambda cx, cy, r: (
        f'<path d="M {_num(cx + r)} {_num(cy)} L {_num(cx - r)} {_num(cy - r)} L {_num(cx - r)} {_num(cy + r)} Z"'
    ),
    "cross": lambda cx, cy, r: (
        f'<path d="M {_num(cx - 0.34 * r)} {_num(cy - r)} H {_num(cx + 0.34 * r)} V {_num(cy - 0.34 * r)} '
        f"H {_num(cx + r)} V {_num(cy + 0.34 * r)} H {_num(cx + 0.34 * r)} V {_num(cy + r)} "
        f"H {_num(cx - 0.34 * r)} V {_num(cy + 0.34 * r)} H {_num(cx - r)} V {_num(cy - 0.34 * r)} "
        f'H {_num(cx - 0.34 * r)} Z"'
    ),
    "x": lambda cx, cy, r: (
        f'<path d="M {_num(cx - 0.72 * r)} {_num(cy - r)} L {_num(cx)} {_num(cy - 0.28 * r)} '
        f"L {_num(cx + 0.72 * r)} {_num(cy - r)} L {_num(cx + r)} {_num(cy - 0.72 * r)} "
        f"L {_num(cx + 0.28 * r)} {_num(cy)} L {_num(cx + r)} {_num(cy + 0.72 * r)} "
        f"L {_num(cx + 0.72 * r)} {_num(cy + r)} L {_num(cx)} {_num(cy + 0.28 * r)} "
        f"L {_num(cx - 0.72 * r)} {_num(cy + r)} L {_num(cx - r)} {_num(cy + 0.72 * r)} "
        f'L {_num(cx - 0.28 * r)} {_num(cy)} L {_num(cx - r)} {_num(cy - 0.72 * r)} Z"'
    ),
    "plus_line": lambda cx, cy, r: (
        f'<path d="M {_num(cx - r)} {_num(cy)} H {_num(cx + r)} M {_num(cx)} {_num(cy - r)} V {_num(cy + r)}" fill="none"'
    ),
    "x_line": lambda cx, cy, r: (
        f'<path d="M {_num(cx - 0.707 * r)} {_num(cy - 0.707 * r)} L {_num(cx + 0.707 * r)} {_num(cy + 0.707 * r)} '
        f'M {_num(cx + 0.707 * r)} {_num(cy - 0.707 * r)} L {_num(cx - 0.707 * r)} {_num(cy + 0.707 * r)}" fill="none"'
    ),
    "horizontal_line": lambda cx, cy, r: (
        f'<path d="M {_num(cx - r)} {_num(cy)} H {_num(cx + r)}" fill="none"'
    ),
    "vertical_line": lambda cx, cy, r: (
        f'<path d="M {_num(cx)} {_num(cy - r)} V {_num(cy + r)}" fill="none"'
    ),
    "pentagon": lambda cx, cy, r: _regular_polygon_path(cx, cy, r, 5, -90.0),
    "hexagon": lambda cx, cy, r: _regular_polygon_path(cx, cy, r, 6, -90.0),
    "star": lambda cx, cy, r: _star_path(cx, cy, r, 5, 0.45, -90.0),
}


def _regular_polygon_path(cx: float, cy: float, r: float, n: int, start_deg: float) -> str:
    pts = []
    for i in range(n):
        theta = np.radians(start_deg + i * 360.0 / n)
        pts.append((cx + r * np.cos(theta), cy + r * np.sin(theta)))
    d = "M " + " L ".join(f"{_num(px)} {_num(py)}" for px, py in pts)
    return f'<path d="{d} Z"'


def _star_path(cx: float, cy: float, r: float, points: int, inner: float, start_deg: float) -> str:
    pts = []
    for i in range(points * 2):
        radius = r if i % 2 == 0 else r * inner
        theta = np.radians(start_deg + i * 180.0 / points)
        pts.append((cx + radius * np.cos(theta), cy + radius * np.sin(theta)))
    d = "M " + " L ".join(f"{_num(px)} {_num(py)}" for px, py in pts)
    return f'<path d="{d} Z"'


def _cap_join_attrs(style: dict[str, Any], *, join: bool = True) -> str:
    """Polyline stroke geometry, always written out rather than inherited.

    SVG's initial values are `butt`/`miter`; XY's are `round`/`round`, and the
    trace only carries `linecap` when it differs (`marks._stroke_geometry`).
    The join is not selectable, but it is still named on every stroked path:
    leaving it out let the format's `miter` default through, and `_pdf` reads
    these attributes straight back out of this markup, so an unnamed join meant
    SVG and PDF disagreeing with the rasterizer for free.
    """
    cap = style.get("linecap", "round")
    attrs = f' stroke-linecap="{escape(str(cap))}"'
    if join:
        attrs = ' stroke-linejoin="round"' + attrs
    return attrs


def _dash_attr(style: dict[str, Any]) -> str:
    dash = style.get("dash")
    if not dash:
        return ""
    if isinstance(dash, str):
        dash = dash.split(",")
    return f' stroke-dasharray="{",".join(_num(float(v)) for v in dash)}"'


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def _axes_by_id(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return every configured axis keyed by its wire id.

    Older payloads only carried the primary ``x_axis``/``y_axis`` fields;
    current payloads additionally carry an ``axes`` mapping for named axes.
    Static exporters accept both shapes and let the primary compatibility
    fields win, matching the browser client's normalization.
    """
    axes = dict(spec.get("axes") or {})
    axes["x"] = spec["x_axis"]
    axes["y"] = spec["y_axis"]
    return axes


def _axis_scales(
    spec: dict[str, Any], plot: dict[str, float]
) -> tuple[
    dict[str, _Scale],
    dict[str, _Scale],
    _Scale,
    _Scale,
    list[tuple[str, dict[str, Any], _Scale]],
    list[tuple[str, dict[str, Any], _Scale]],
]:
    """Pixel scales for every configured axis plus the named-axis lists —
    shared by the SVG and native exporters so their geometry stays identical.

    Returns ``(x_scales, y_scales, sx, sy, extra_x_axes, extra_y_axes)``.
    """
    axes = _axes_by_id(spec)
    x_scales = {
        axis_id: _Scale(axis, plot["x"], plot["x"] + plot["w"])
        for axis_id, axis in axes.items()
        if axis_id.startswith("x")
    }
    y_scales = {
        axis_id: _Scale(axis, plot["y"] + plot["h"], plot["y"])
        for axis_id, axis in axes.items()
        if axis_id.startswith("y")
    }
    sx = x_scales["x"]
    sy = y_scales["y"]  # y grows downward in raster space
    extra_x_axes = [
        (axis_id, axis, x_scales[axis_id])
        for axis_id, axis in axes.items()
        if axis_id != "x" and axis_id.startswith("x")
    ]
    extra_y_axes = [
        (axis_id, axis, y_scales[axis_id])
        for axis_id, axis in axes.items()
        if axis_id != "y" and axis_id.startswith("y")
    ]
    return x_scales, y_scales, sx, sy, extra_x_axes, extra_y_axes


def _colorbar_right_axis_room(
    y_axis: dict[str, Any],
    extra_y_axes: list[tuple[str, dict[str, Any], _Scale]],
    compact: bool,
) -> float:
    """Gutter layout() reserves for visible right-side named y axes.

    The vertical colorbar shifts right by this amount so its bar/ticks/label
    clear the axis tick labels (plot-right+8) and rotated axis title
    (plot-right+40); the JS client applies the identical rule."""
    axes = [y_axis, *(axis for _axis_id, axis, _axis_scale in extra_y_axes)]
    if any(
        (axis.get("side", "left") == "right" or "right" in _axis_tick_label_sides(axis, is_x=False))
        and _axis_tick_label_strategy(axis) != "none"
        for axis in axes
    ):
        return 42.0 if compact else 54.0
    return 0.0


# Smallest gap between the canvas edge and the outermost axis ink.
# Antialiased leading glyphs must not land on the export boundary.
_AXIS_TEXT_EDGE_PAD = 4.0
# Gap between the y title's ink and the nearest tick label's ink, as a fraction
# of the title's font size. Matplotlib leaves 5.6 px at its 13.89 px (10 pt at
# 100 dpi) default — measured with `Text.get_window_extent` on 3.11.1.
_Y_TITLE_TICK_GAP = 0.4


def _text_cell(font_size: float) -> tuple[float, float]:
    """(ascent, descent) in px of the core's DejaVu face at `font_size`."""
    return (
        font_size * _fontmetrics.ASCENT / _fontmetrics.BASE_PX,
        font_size * _fontmetrics.DESCENT / _fontmetrics.BASE_PX,
    )


def _text_block_content(text: object, x: float, line_step: float) -> str:
    """SVG text children for the shared newline-delimited block geometry."""
    split = _textblock.split_lines(text)
    if len(split) == 1:
        # Keep ordinary text as a direct text node.  Besides producing the
        # smallest SVG, the PDF exporter consumes these nodes as vector text
        # and existing callers intentionally inspect ``Element.text``.
        return escape(split[0])
    lines = []
    for index, line in enumerate(split):
        dy = f' dy="{_num(line_step)}"' if index else ""
        lines.append(f'<tspan x="{_num(x)}"{dy}>{escape(line)}</tspan>')
    return "".join(lines)


def _has_outside_y_title(axis: dict[str, Any]) -> bool:
    """Whether a y-axis title needs space outside the plot rectangle."""
    if not axis.get("label"):
        return False
    raw_position = axis.get("label_position")
    position = raw_position if isinstance(raw_position, str) else "center"
    return not position.replace("-", "_").startswith("inside_")


def _axis_text_paint_visible(
    axis: dict[str, Any],
    key: str,
    fallback_key: Optional[str] = None,
) -> bool:
    """Whether an axis text paint can contribute visible ink.

    Axis visibility shorthands are compiled to transparent CSS colors. Layout
    must not measure that invisible text back into an explicit zero padding,
    or ``show=False`` cannot produce the documented edge-to-edge sparkline.
    Unknown/browser-only paints stay conservative and reserve their room.
    """
    style = axis.get("style") or {}
    paint = style.get(key)
    if paint is None and fallback_key is not None:
        paint = style.get(fallback_key)
    if paint is None:
        return True
    return _paint_rgba8(_css(paint, _TEXT))[3] != 0


def _y_title_baseline(
    axis: dict[str, Any],
    plot: dict[str, float],
) -> Optional[float]:
    """Baseline x of a quarter-turned y-axis title, or None when it has none.

    Matplotlib positions a y title from the outer edge of the tick-label union,
    not from the canvas edge. A static exporter emits a baseline while the
    browser positions a centered line box; the returned coordinate includes
    that box-to-baseline correction.
    """
    if not _has_outside_y_title(axis):
        return None  # absent or drawn over the plot; it needs no gutter
    style = axis.get("style") or {}
    font_size = float(style.get("label_size", 12))
    side = axis.get("side", "left")
    block = _textblock.measure(axis["label"], font_size)
    ascent, descent = block.ascent, block.descent
    if side == "right":
        # Right-side axes still use the existing fixed 42/54 px reservation.
        # Keep their plot-relative placement unchanged; this repair only
        # measures the left gutter that can otherwise clip against x=0.
        angle = float(axis.get("label_angle", 90.0))
        shift = (ascent - descent) / 2 if abs(abs(angle) - 90.0) < 0.5 else 0.0
        return plot["x"] + plot["w"] + 40.0 - shift + float(axis.get("label_offset", 0.0))
    tick_offset, tick_room = (
        _y_tick_label_room(axis, plot["h"])
        if "left" in _axis_tick_label_sides(axis, is_x=False)
        else (0.0, 0.0)
    )
    gap = float(axis.get("label_offset", _Y_TITLE_TICK_GAP * font_size))
    # For a -90 degree title, later lines move toward the plot. Pin the first
    # baseline so the whole block, not only line one, remains outside ticks.
    title_depth = descent + (block.line_count - 1) * block.line_step
    return plot["x"] - tick_offset - tick_room - gap - title_depth


def _y_tick_label_room(axis: dict[str, Any], plot_h: float) -> tuple[float, float]:
    """(offset from the spine, widest tick-label extent) for a y axis, in px.

    Measured from the advance widths of the strings that will actually be drawn,
    using the same DejaVu metrics the Rust rasterizer blits (`src/font.rs`) —
    which is also Matplotlib's default face, so an advance measured here is the
    advance Matplotlib lays out.
    """
    if _axis_tick_label_strategy(axis) in {"none", "off"} or not _axis_text_paint_visible(
        axis, "tick_label_color", "tick_color"
    ):
        return 0.0, 0.0
    font_size = _axis_tick_font_size(axis)
    raw_angle = axis.get("tick_label_angle")
    angle = float(raw_angle or 0.0)
    _values, labels, step = axis_ticks(axis, plot_h, False)
    room = 0.0
    for value in labels:
        block = _textblock.measure(_tick_text(axis, value, step), font_size)
        # A rotated block trades its measured width for its full line-box
        # height about the pinned edge.
        room = max(room, _textblock.rotated_extent(block, angle)[0])
    # Match the SVG y-label placement below.  A y label's anchored edge is
    # already the glyph-side edge, so unlike an x-label baseline it needs no
    # extra font-room term.
    return _axis_tick_label_offset(axis, 8.0), room


def _y_axis_left_room(spec: dict[str, Any], plot_h: float) -> float:
    """Left gutter the y-axis text needs, measured rather than assumed.

    `layout()`'s fixed 46/62 px default fits ordinary numeric ticks under a
    12 px title. Matplotlib's rcParam fonts (13.89 px at 100 dpi), long category
    names, and authored tick labels all exceed it, and the shortfall lands as a
    title drawn on top of the tick labels — or off the canvas — instead of as a
    wider gutter.

    Right-side y axes deliberately keep the flat 42/54 px reservation above:
    ChartView pins a right title plot-relative (`plot-right+40`) rather than to
    a canvas inset, so widening only the static exporters' right gutter would
    move their title away from the browser's. That asymmetry is recorded in
    `spec/api/styling.md`, not silently fixed here.
    """
    room = 0.0
    for axis_id, axis in _axes_by_id(spec).items():
        if not axis_id.startswith("y"):
            continue
        left_labels = "left" in _axis_tick_label_sides(axis, is_x=False)
        left_title = axis.get("side", "left") != "right"
        if not left_labels and not left_title:
            continue
        tick_offset, tick_room = _y_tick_label_room(axis, plot_h) if left_labels else (0.0, 0.0)
        title_visible = (
            left_title
            and _has_outside_y_title(axis)
            and _axis_text_paint_visible(axis, "label_color")
        )
        if not title_visible:
            if tick_offset == 0.0 and tick_room == 0.0:
                continue
            room = max(room, _AXIS_TEXT_EDGE_PAD + tick_offset + tick_room)
            continue
        label_size = float((axis.get("style") or {}).get("label_size", 12))
        block = _textblock.measure(axis["label"], label_size)
        gap = float(axis.get("label_offset", _Y_TITLE_TICK_GAP * label_size))
        room = max(
            room,
            _AXIS_TEXT_EDGE_PAD
            + block.ascent
            + block.descent
            + (block.line_count - 1) * block.line_step
            + gap
            + tick_offset
            + tick_room,
        )
    return room


def _x_axis_title_room(axis: dict[str, Any]) -> float:
    """Outward room needed by an outside x-axis title.

    ``_axis_label_geometry()`` positions x titles from their line-box top and
    converts that top to a static-text baseline.  Measure the corresponding
    outer glyph edge here so tight/constrained layout does not stop at the
    historical 36/42 px band while the title itself extends past the canvas.
    """
    if not axis.get("label") or not _axis_text_paint_visible(axis, "label_color"):
        return 0.0
    raw_position = axis.get("label_position")
    position = raw_position if isinstance(raw_position, str) else "center"
    if position.replace("-", "_").startswith("inside_"):
        return 0.0
    style = axis.get("style") or {}
    font_size = float(style.get("label_size", 12))
    block = _textblock.measure(axis["label"], font_size)
    offset = float(axis.get("label_offset", 0.0))
    if axis.get("side", "bottom") == "top":
        # outside_top = plot-top - 34; the baseline conversion then moves
        # 0.82em back toward the plot.
        return _AXIS_TEXT_EDGE_PAD + 34.0 + offset - font_size * 0.82 + block.ascent
    # outside_bottom = plot-bottom + 24; later lines move farther outward.
    return (
        _AXIS_TEXT_EDGE_PAD
        + 24.0
        + offset
        + font_size * 0.82
        + (block.line_count - 1) * block.line_step
        + block.descent
    )


def _x_tick_label_room(axis: dict[str, Any], plot_w: float) -> float:
    """Outward room needed by the x axis's final tick-label set and title.

    The old 32/42 px bands only fit horizontal labels. Measure the strings and
    project their DejaVu advance plus line box through the authored angle; this
    is deliberately evaluated *after* collision policy, so ``auto`` reserves
    only labels it will draw while pyplot's ``preserve`` reserves all fixed
    locations. The same value is used by SVG and native PNG layout.
    """
    strategy = _axis_tick_label_strategy(axis)
    if strategy == "none":
        return 0.0
    title_room = _x_axis_title_room(axis)
    if strategy == "off" or not _axis_text_paint_visible(axis, "tick_label_color", "tick_color"):
        return title_room
    if (
        strategy == "auto"
        and axis.get("tick_label_angle") is None
        and axis.get("tick_values") is None
        and axis.get("kind") != "category"
    ):
        # Numeric auto ticks are selected from the plot width and remain in the
        # established horizontal band. Only authored/category locations can
        # force rotation or staggering; avoid building and measuring the full
        # label layout merely to rediscover the ordinary zero-extra case. The
        # independently measured title can still exceed that fixed band.
        return title_room
    _ticks, values, step = axis_ticks(axis, plot_w, True)
    scale = _Scale(axis, 0.0, max(1.0, plot_w))
    items = _axis_tick_label_layout(axis, values, step, scale, True)
    if not items:
        return title_room
    has_adaptive_layout = any(float(item["angle"]) or int(item.get("row", 0)) for item in items)
    font_size = _axis_tick_font_size(axis)
    has_multiline_ticks = any(len(_textblock.split_lines(item["text"])) > 1 for item in items)
    if (
        not has_adaptive_layout
        and not has_multiline_ticks
        and strategy == "auto"
        and axis.get("tick_label_angle") is None
    ):
        # Preserve the long-standing flat band for ordinary horizontal text.
        # Measured bands are reserved for rotation, staggering, or multiline
        # chrome; ordinary auto ticks retain their historical geometry.
        return title_room
    extent = 0.0
    for item in items:
        block = _textblock.measure(item["text"], font_size)
        extent = max(extent, _textblock.rotated_extent(block, float(item["angle"]))[1])
    side = axis.get("side", "bottom")
    label_offset = (
        _axis_tick_label_offset(axis, 7.0, 0.2)
        if side == "top"
        else _axis_tick_label_offset(axis, 16.0, 0.8)
    )
    rows = max(int(item.get("row", 0)) for item in items)
    tick_room = _AXIS_TEXT_EDGE_PAD + label_offset + rows * (font_size + 4.0) + extent
    return max(title_room, tick_room)


def _x_tick_label_edge_rooms(axes: dict[str, dict[str, Any]], plot_w: float) -> tuple[float, float]:
    """Canvas-edge room needed by x tick labels that overhang the plot.

    A terminal tick label is centered on the end of the spine by default, so
    half its ink lives outside the plot rectangle. Matplotlib includes every
    visible tick-label bbox in ``Axes.get_tightbbox``; mirror that horizontal
    union here instead of relying on the compact layout's flat right gutter.
    """
    left = right = 0.0
    for axis_id, axis in axes.items():
        if (
            not axis_id.startswith("x")
            or _axis_tick_label_strategy(axis) in {"none", "off"}
            or not _axis_text_paint_visible(axis, "tick_label_color", "tick_color")
        ):
            continue
        _ticks, values, step = axis_ticks(axis, plot_w, True)
        scale = _Scale(axis, 0.0, max(1.0, plot_w))
        style = axis.get("style") or {}
        font_size = _axis_tick_font_size(axis)
        explicit_anchor = _tick_label_anchor(axis, style, "")
        for side in _axis_tick_label_sides(axis, is_x=True):
            side_axis = {**axis, "side": side}
            if (
                _axis_tick_label_strategy(axis) == "auto"
                and axis.get("tick_label_angle") is None
                and axis.get("tick_values") is None
                and axis.get("kind") != "category"
            ):
                items = [
                    {
                        "pos": float(scale(value)),
                        "text": _tick_text(axis, value, step),
                        "angle": 0.0,
                    }
                    for value in values
                ]
            else:
                items = _axis_tick_label_layout(side_axis, values, step, scale, True)
            for item in items:
                angle = float(item["angle"])
                anchor = explicit_anchor
                if not anchor:
                    if angle == 0:
                        anchor = "center"
                    elif (side == "bottom" and angle < 0) or (side == "top" and angle > 0):
                        anchor = "end"
                    else:
                        anchor = "start"
                block = _textblock.measure(item["text"], font_size)
                if anchor == "end":
                    x0, x1 = -block.width, 0.0
                elif anchor == "center":
                    x0, x1 = -block.width / 2, block.width / 2
                else:
                    x0, x1 = 0.0, block.width
                y0 = -block.ascent
                y1 = block.descent + (block.line_count - 1) * block.line_step
                radians = math.radians(angle)
                cosine, sine = math.cos(radians), math.sin(radians)
                rotated_x = [x * cosine - y * sine for x in (x0, x1) for y in (y0, y1)]
                position = float(item["pos"])
                left = max(left, _AXIS_TEXT_EDGE_PAD - position - min(rotated_x))
                right = max(
                    right,
                    _AXIS_TEXT_EDGE_PAD + position + max(rotated_x) - plot_w,
                )
    return float(math.ceil(max(0.0, left))), float(math.ceil(max(0.0, right)))


def _x_axis_rooms(
    axes: dict[str, dict[str, Any]], plot_w: float, compact: bool
) -> tuple[float, float, float]:
    """Shared ``(top, bottom, measured_bottom)`` x-axis bands.

    The fixed bottom band is metadata for colorbar placement.  It must not
    override an explicit figure ``padding`` authored by pyplot unless rotated
    or staggered labels actually require more room.
    """
    top = 0.0
    bottom = 0.0
    measured_bottom = 0.0
    for axis_id, axis in axes.items():
        if not axis_id.startswith("x") or _axis_tick_label_strategy(axis) == "none":
            continue
        title_side = axis.get("side", "bottom")
        room_sides = set(_axis_tick_label_sides(axis, is_x=True))
        if _axis_tick_label_strategy(axis) == "off" or axis.get("label"):
            room_sides.add(title_side)
        for side in room_sides:
            side_axis = {**axis, "side": side}
            if side != title_side:
                side_axis.pop("label", None)
            measured = _x_tick_label_room(side_axis, plot_w)
            if side == "top":
                top = max(top, 26.0 if compact else 32.0, measured)
            else:
                bottom = max(bottom, 36.0 if compact else 42.0, measured)
                measured_bottom = max(measured_bottom, measured)
    return top, bottom, measured_bottom


def _title_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized independent axes-title slots, with legacy-title fallback."""
    authored = spec.get("title_options")
    if isinstance(authored, list) and authored:
        return [entry for entry in authored if isinstance(entry, dict) and entry.get("text")]
    if spec.get("title"):
        return [
            {
                "text": spec["title"],
                "loc": "center",
                "y": 1.0,
                "pad": 8.0,
                "automatic_y": True,
                "style": {},
            }
        ]
    return []


def _decode_title_geometry(spec: dict[str, Any], blob: bytes) -> dict[str, Any]:
    """Hydrate title placement from its raw-f32 wire column for static layout."""
    authored = spec.get("title_options")
    if not isinstance(authored, list) or not authored:
        return spec
    decoded = []
    changed = False
    for entry in authored:
        if not isinstance(entry, dict) or "geometry" not in entry:
            decoded.append(entry)
            continue
        values = _column(blob, spec["columns"][entry["geometry"]])
        hydrated = {**entry, "y": float(values[0]), "pad": float(values[1])}
        decoded.append(hydrated)
        changed = True
    return {**spec, "title_options": decoded} if changed else spec


def _title_wrap_width(width: float, left: float, right: float) -> float:
    """Width a chart title wraps at, in CSS px.

    Deliberately derived from the *authored/default* horizontal gutters rather
    than the final plot rect: the measured left gutter depends on the plot
    height, which depends on the title band, so wrapping at the final width
    would be circular. `_recut_polar_plot` and the measured gutters may narrow
    the plot afterwards; the title keeps this width so what layout reserved is
    what gets drawn. Mirrored by `_titleWrapWidth` in js/src/50_chartview.ts.
    """
    return max(40.0, float(width) - float(left) - float(right))


def _title_metrics(
    spec: dict[str, Any],
    entry: dict[str, Any],
    wrap_width: float | None = None,
) -> tuple[dict[str, Any], float, _textblock.TextBlock]:
    base = slot_styles(spec).get("title") or {}
    style = {**base, **(entry.get("style") or {})}
    size = _px_size(style.get("font-size"), 14.0)
    return style, size, _textblock.measure(entry["text"], size, max_width=wrap_width)


def _title_room(spec: dict[str, Any], compact: bool, wrap_width: float | None = None) -> float:
    room = 0.0
    for entry in _title_entries(spec):
        _style, _size, block = _title_metrics(spec, entry, wrap_width)
        pad = float(entry.get("pad", 8.0))
        if entry.get("automatic_y", True):
            candidate = max(26.0 if compact else 30.0, block.height + pad)
        else:
            candidate = block.height + pad if float(entry.get("y", 1.0)) >= 1.0 else 0.0
        room = max(room, max(0.0, candidate))
    return room


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
    axes = _axes_by_id(spec)
    # The first pass uses the authored/default horizontal allocation. A second
    # pass after the measured left gutter catches an auto-collision decision
    # whose final plot width changes the chosen label set.
    provisional_w = max(40.0, width - left - right)
    # Resolved before the title band, because the band's height now depends on
    # how many lines the title wraps into at this width.
    title_wrap_width = _title_wrap_width(width, left, right)
    title_room = _title_room(spec, compact, title_wrap_width)
    top_axis_room, bottom_axis_room, measured_bottom_room = _x_axis_rooms(
        axes, provisional_w, compact
    )
    top += title_room
    top += top_axis_room
    if measured_bottom_room:
        bottom = max(bottom, measured_bottom_room)
    colorbar = spec.get("colorbar") or {}
    if colorbar.get("placement") == "axes":
        if colorbar.get("orientation") == "horizontal":
            bottom += 24 + (16 if colorbar.get("label") else 0)
        else:
            right += 44 + (18 if colorbar.get("label") else 0)
    elif colorbar.get("orientation") == "horizontal":
        bottom += (18 if colorbar.get("pad") == 0 else 38) + (16 if colorbar.get("label") else 0)
    elif colorbar:
        right += (62 if colorbar.get("pad") == 0 else 86) + (18 if colorbar.get("label") else 0)
    if any(
        axis_id.startswith("y")
        and (
            axis.get("side", "right") == "right"
            or "right" in _axis_tick_label_sides(axis, is_x=False)
        )
        and _axis_tick_label_strategy(axis) != "none"
        for axis_id, axis in axes.items()
    ):
        # Match ChartView._layout(): one shared right-side gutter contains the
        # secondary-y tick labels/title. Multiple right axes intentionally
        # overlay in both renderers until offset axes become part of the API.
        right += 42 if compact else 54
    # Measured y-axis text room, applied last. The vertical extent is already
    # final (only top/bottom feed it), so the tick density the reservation
    # measures is the density that will be drawn. This raises a *floor*: an
    # authored `padding` and the 46/62 default both stand whenever they already
    # fit, exactly as the colorbar/right-axis room above is additive rather
    # than authoritative. Reserving less than the ink is not an option — a
    # static export has no ellipsis to fall back on the way the DOM does.
    left = max(left, _y_axis_left_room(spec, max(40, height - top - bottom)))
    # Include terminal x tick-label ink that overhangs either end of the
    # spine. Two passes cover a tick-density change caused by the new room.
    for _pass in range(2):
        edge_left, edge_right = _x_tick_label_edge_rooms(
            axes,
            max(40.0, width - left - right),
        )
        widened_left = max(left, edge_left)
        widened_right = max(right, edge_right)
        if widened_left == left and widened_right == right:
            break
        left, right = widened_left, widened_right
    final_w = max(40.0, width - left - right)
    if final_w == provisional_w:
        measured_top = top_axis_room
        measured_bottom = bottom_axis_room
        final_measured_bottom = measured_bottom_room
    else:
        measured_top, measured_bottom, final_measured_bottom = _x_axis_rooms(axes, final_w, compact)
    if measured_top > top_axis_room:
        top += measured_top - top_axis_room
        top_axis_room = measured_top
    if final_measured_bottom > measured_bottom_room:
        bottom = max(bottom, final_measured_bottom)
        measured_bottom_room = final_measured_bottom
    bottom_axis_room = max(bottom_axis_room, measured_bottom)
    plot = {
        "x": left,
        "y": top,
        "w": max(40, width - left - right),
        "h": max(40, height - top - bottom),
        # Emitters place the figure title above this gutter; recording it here
        # keeps layout() the single source of the top-axis reservation.
        "title_room": title_room,
        # The width the title band was measured at. Emitters must wrap at the
        # same width or they draw more lines than `title_room` reserved.
        "title_wrap_width": title_wrap_width,
        "top_axis_room": top_axis_room,
        "bottom_axis_room": bottom_axis_room,
    }
    if spec.get("coords") == "polar":
        _recut_polar_plot(spec, plot, width, height, compact)
    return width, height, compact, plot


# Room reserved outside the outer ring for angular tick labels. Cartesian
# gutters are per-side because labels hug two edges; a polar chart carries them
# all the way around, so the allowance is uniform.
# Mirrored by POLAR_LABEL_ROOM in js/src/50_chartview.ts.
_POLAR_LABEL_ROOM = 30.0
# Ceiling on the measured allowance: past this a long label shrinks the disc
# more than it helps, so it truncates against the canvas instead.
_POLAR_LABEL_ROOM_MAX = 90.0

# Angle of the spoke the radial tick labels run along, in degrees off the theta
# zero direction. Matplotlib's default `rlabel_position`; keeping the labels off
# the zero spoke stops them colliding with the theta=0 angular label. Shared by
# both exporters so they cannot drift apart.
# Mirrored by POLAR_RLABEL_DEG in js/src/50_chartview.ts.
_POLAR_RLABEL_DEG = 22.5

# Gap in px between the outer ring and the angular tick labels.
# Mirrored by POLAR_TICK_GAP in js/src/50_chartview.ts.
_POLAR_TICK_GAP = 8.0

# Gutter reserved for a legend beside a disc. A Cartesian legend overlays the
# plot because data rarely reaches a corner; a disc inscribed in its rect leaves
# no corner at all, so an inside legend lands on the marks — an `upper right` box
# covered a wind rose's whole north-east quadrant and the outer radial label
# under it. Both incumbents' answer is to move it out (Plotly puts polar legends
# in the figure margin), which needs room the disc gives back.
#
# A FRACTION OF THE CANVAS, clamped, rather than a measurement of the label set:
# every renderer knows the canvas width to the pixel, so all three reserve the
# identical box, while a measured reservation would drift with each renderer's
# font metrics (DejaVu here, system-ui in the browser). A flat constant was tried
# first and is the wrong shape — 96 px ellipsized `Partner  (30%)`, an ordinary
# pie slice's default name, while being a fifth of a phone canvas and a
# fifteenth of a wide one.
#
# The floor keeps a narrow chart's legend readable; the ceiling stops a wide one
# from spending 300 px on four short rows. A label still wider than the gutter
# ellipsizes with its full text in `title`/ARIA, exactly as the static exporters
# already ellipsize against the plot width.
# Mirrored by xyPolarLegendRoom in js/src/50_chartview.ts.
_POLAR_LEGEND_ROOM_FRACTION = 0.22
_POLAR_LEGEND_ROOM_MIN = 120.0
_POLAR_LEGEND_ROOM_MAX = 200.0


def _polar_legend_room(width: float) -> float:
    """Side-gutter width for a polar legend on a `width`-px canvas.

    `floor`, not `round`: Python and JavaScript disagree about half-way cases
    (banker's rounding versus round-half-up) and the two must land on the same
    integer pixel.
    """
    scaled = math.floor(float(width) * _POLAR_LEGEND_ROOM_FRACTION)
    return min(_POLAR_LEGEND_ROOM_MAX, max(_POLAR_LEGEND_ROOM_MIN, float(scaled)))


_POLAR_LEGEND_BAND = 64.0


def _polar_legend_reserve(spec: dict[str, Any], compact: bool, width: float) -> tuple[str, float]:
    """Side and px a polar legend gutter claims: ``("right", 158.0)`` etc.

    ``("", 0.0)`` when nothing is reserved — a non-polar figure, no legend rows,
    an authored ``anchor`` (an explicit plot-relative placement the author owns),
    or an authored 4-tuple ``padding`` (which already states the box the plot
    should occupy, and is the documented way to hand-reserve a caption band).

    Mirrored by `_polarLegendReserve` in js/src/50_chartview.ts.
    """
    if spec.get("coords") != "polar" or not spec.get("show_legend", True):
        return "", 0.0
    padding = spec.get("padding")
    if isinstance(padding, list) and len(padding) == 4:
        return "", 0.0
    options = spec.get("legend") or {}
    anchor = options.get("anchor")
    if anchor and len(anchor) in (2, 4):
        return "", 0.0
    rows = options.get("items") or legend_items(spec.get("traces") or [])
    if not rows and not (spec.get("extra_legends") or []):
        return "", 0.0
    if compact:
        return "bottom", _POLAR_LEGEND_BAND
    loc = str(options.get("loc") or "upper right")
    return ("left" if "left" in loc else "right"), _polar_legend_room(width)


def _polar_label_room(theta_axis: dict[str, Any]) -> float:
    """Room outside the ring for the angular tick labels.

    Measured, not fixed: authored category names ("EAST-NORTH-EAST") are far
    wider than an angle, and a constant allowance hard-clipped them at the
    canvas edge. Only the widest AUTHORED label is measured — generated angle
    text is bounded and already fits the floor — and the result is capped so a
    pathological label shrinks the disc rather than erasing it.

    Mirrored by `polarLabelRoom` in js/src/50_chartview.ts.
    """
    room = _POLAR_LABEL_ROOM
    # A category axis carries its authored names in `categories` and usually has
    # no `tick_labels` at all (`axis_ticks` hands the categories straight to
    # `_category_ticks`), so measuring only `tick_labels` fell back to the
    # uniform default and long names spilled over the disc.
    labels = theta_axis.get("tick_labels")
    if not labels and theta_axis.get("kind") == "category":
        labels = theta_axis.get("categories")
    if not labels:
        return room
    size = _axis_tick_font_size(theta_axis)
    widest = max((_textblock.measure(str(text), size).width for text in labels), default=0.0)
    return min(_POLAR_LABEL_ROOM_MAX, max(room, widest + _POLAR_TICK_GAP + _AXIS_TEXT_EDGE_PAD))


def _recut_polar_plot(
    spec: dict[str, Any],
    plot: dict[str, float],
    width: float,
    height: float,
    compact: bool = False,
) -> None:
    """Re-cut the plot rect for a disc, in place.

    Mirrored by `_recutPolarPlot` in js/src/50_chartview.ts — the two must agree
    or the same chart renders at a different size and centre in the browser than
    in an export.

    Two things happen here, both after the cartesian gutter passes have
    converged so they cannot perturb that fixed point.

    First, the cartesian tick-label gutters are given back. They exist to hold
    labels hugging the left and bottom edges; a polar chart carries its labels
    all the way around the rim instead, so leaving them reserved pushed the disc
    right and up (a 400x400 chart centred its circle at x=219) and shrank it for
    no reason. The horizontal and vertical reservations are symmetrised rather
    than simply zeroed, so a colorbar or right-side axis that genuinely claimed
    space still keeps it.

    Second, a uniform allowance is reserved all the way around for the angular
    tick labels. The radius is `min(w, h) / 2` with no fill factor
    (polar-axes.md §3), so that room has to come out of the rect rather than out
    of the transform — otherwise every renderer would need the same fudge factor
    and they would eventually disagree about it.

    Third, a legend gutter (`_polar_legend_reserve`) is taken off the rect and
    recorded as `plot["legend_box"]`, so the legend sits beside the disc instead
    of on top of it. `_legend_layout` places and bounds itself in that box.
    """
    theta_axis = spec.get("x_axis") or {}
    # Hiding the angular tick labels removes the LABEL inset, not the legend
    # gutter. Returning here skipped `_polar_legend_reserve` outright, so the
    # legend fell back to the plain plot rect and drew on top of the marks —
    # and the disc kept the cartesian gutters it should have given back. Track
    # it and skip only the inset.
    labels_hidden = theta_axis.get("tick_label_strategy") == "none"
    # The legend gutter is taken off the canvas edge FIRST, before the disc is
    # fitted to what is left, so the disc never occupies the gutter and the
    # legend never occupies the disc. Recorded as four floats rather than a
    # nested rect so `plot` stays a flat float map.
    canvas_x0 = 0.0
    legend_side, legend_room = _polar_legend_reserve(spec, compact, width)
    if legend_room:
        if legend_side == "left":
            box = (0.0, plot["y"], legend_room, plot["h"])
            canvas_x0 = legend_room
            plot["x"] = max(plot["x"], legend_room)
        elif legend_side == "right":
            width -= legend_room
            box = (width, plot["y"], legend_room, plot["h"])
        else:
            height -= legend_room
            box = (plot["x"], height, plot["w"], legend_room)
        plot["legend_box_x"], plot["legend_box_y"] = box[0], box[1]
        plot["legend_box_w"], plot["legend_box_h"] = box[2], box[3]
        plot["w"] = max(40.0, min(plot["w"], width - plot["x"]))
        plot["h"] = max(40.0, min(plot["h"], height - plot["y"]))
    # The top gutter also holds the figure title, which emitters place at
    # `plot.y - top_axis_room - pad`; it is a floor, never given back.
    reserved_top = plot["y"]
    reserved_right = width - plot["x"] - plot["w"]
    reserved_bottom = height - plot["y"] - plot["h"]

    room = 0.0 if labels_hidden else _polar_label_room(theta_axis)
    authored_pad = spec.get("padding")
    if isinstance(authored_pad, list) and len(authored_pad) == 4:
        # An explicit `padding` states the box the author wants the plot to
        # occupy — most often to reserve a band under the disc for a legend or
        # caption, which is what every donut composition needs. Reclaiming the
        # gutters below would throw that away (a chart authored with
        # `padding=[0, 0, 140, 0]` came out with its disc filling the canvas,
        # the reserved band gone). So an authored box is only inset by the
        # uniform label room, and the disc centres in what is left.
        left = plot["x"] + room
        right = plot["x"] + plot["w"] - room
        top = plot["y"] + room
        bottom = plot["y"] + plot["h"] - room
        box_w, box_h = right - left, bottom - top
        if box_w >= 40.0 and box_h >= 40.0:
            plot["x"], plot["y"], plot["w"], plot["h"] = left, top, box_w, box_h
            plot["top_axis_room"] = plot["top_axis_room"] + room
            return
    side = max(room, reserved_right)
    # A radial-axis title is still drawn in the left gutter — a disc gives it no
    # natural home — and `_axis_label_geometry` positions it outward from the
    # plot edge past the tick-label room. So when one is set, the original
    # gutter is kept whole rather than part-reclaimed: shaving it put the title
    # at x = -10, off the canvas. Charts with no radial title (the common case)
    # still get the full reclaim.
    y_axis = spec.get("y_axis") or {}
    titled = bool(y_axis.get("label")) and _axis_text_paint_visible(y_axis, "label_color")
    # `canvas_x0` is a left legend gutter; the label room still applies inside it.
    # With no gutter it is 0 and `side >= room`, so this is the previous value.
    left = max(max(side, plot["x"]) if titled else side, canvas_x0 + room)
    right = width - side
    # Vertically the title side is fixed, so only the bottom can be
    # symmetrised — and only when the theta axis has no title of its own,
    # because that title is drawn in the bottom gutter and reclaiming the band
    # pushed it below the canvas edge.
    x_axis = spec.get("x_axis") or {}
    x_titled = bool(x_axis.get("label")) and _axis_text_paint_visible(x_axis, "label_color")
    # A horizontal colorbar is placed relative to the plot's BOTTOM edge, so
    # extending the rect downward walks it off the canvas. Its gutter is real
    # chrome, not a tick-label gutter: keep it whole, like a theta title.
    colorbar = spec.get("colorbar") or {}
    keeps_bottom = x_titled or colorbar.get("orientation") == "horizontal"
    bottom_reserve = reserved_bottom if keeps_bottom else min(reserved_bottom, reserved_top)
    bottom = height - max(room, bottom_reserve)
    top = reserved_top + room

    # Measure BEFORE clamping: clamping first made the guard below unreachable,
    # so a chart too small for the label room silently got a 40px floor rect
    # instead of keeping its circle. Mirrored by _recutPolarPlot's early return.
    box_w = right - left
    box_h = bottom - top
    if box_w < 40.0 or box_h < 40.0:
        # Too small for the label room. Do NOT fall back to the cartesian rect:
        # its own 40px floor can be wider than the canvas, and a disc centred
        # in it leaves the page (an 80x80 chart drew its circle out to x=86).
        # Take the largest centred box the canvas itself allows instead.
        margin = min(4.0, width / 8.0, height / 8.0)
        plot["x"] = margin
        plot["y"] = max(margin, min(reserved_top, height / 4.0))
        plot["w"] = max(8.0, width - 2 * margin)
        plot["h"] = max(8.0, height - plot["y"] - margin)
        return
    plot["x"] = left
    plot["y"] = top
    plot["w"] = box_w
    plot["h"] = box_h
    # The top slice is angular-label room, so it belongs to the axis
    # reservation: without this the title would ride the rect down and the
    # topmost angular label would land on top of it.
    plot["top_axis_room"] = plot["top_axis_room"] + room
    # Re-square the legend gutter against the FINAL rect so the box tracks the
    # disc it sits beside rather than the pre-recut rect it was cut from.
    if legend_room:
        if legend_side in ("left", "right"):
            plot["legend_box_y"], plot["legend_box_h"] = plot["y"], plot["h"]
        else:
            plot["legend_box_x"], plot["legend_box_w"] = plot["x"], plot["w"]


def _tick_window(axis: dict[str, Any]) -> tuple[float, float]:
    """The value window ticks are drawn in — the sector for an angular axis."""
    lo, hi = axis["range"]
    if axis.get("theta_unit") is not None:
        if axis.get("kind") == "category":
            lo, hi = 0.0, float(max(0, len(axis.get("categories") or []) - 1))
        else:
            lo, hi = axis.get("sector") or (lo, hi)
    return float(lo), float(hi)


def _tick_window_filter(axis: dict[str, Any], lo: float, hi: float) -> Callable[[float], bool]:
    """Predicate keeping the tick values that fall inside the axis window.

    An angular window may cross the 0/turn seam — ``sector=(300, 420)``, or the
    compass-natural ``(-30, 30)``. The plain ``low <= v <= high`` test throws
    away every tick authored on the far side of that seam (0, 30 and 60 for the
    first; 330, 340, 350 for the second) while a *data point* at the very same
    angle plots inside the sector, because mark culling is modular. Ticks now
    use the same modular containment as
    `_PolarProjection._angular_value_visible_mask`, so the spokes and the marks
    agree about what the sector contains.
    """
    low, high = min(lo, hi), max(lo, hi)
    unit = axis.get("theta_unit")
    if unit is None or axis.get("kind") == "category":
        return lambda value: low <= value <= high
    turn = 360.0 if unit == "degrees" else 2.0 * math.pi
    span = high - low
    # NaN falls out of both branches: np.mod propagates it and the comparison
    # is False, matching the linear test it replaces.
    return lambda value: bool(np.mod(value - low, turn) <= span + turn * 1e-9)


def axis_ticks(
    axis: dict[str, Any], length_px: float, is_x: bool
) -> tuple[list[float], list[float], float]:
    """(ticks, labeled ticks, step) for an axis at a given pixel length — shared
    tick density so SVG and PNG label the same values."""
    kind = axis.get("kind")
    lo, hi = _tick_window(axis)
    if axis.get("tick_values") is not None:
        keep = _tick_window_filter(axis, lo, hi)
        ticks = [float(v) for v in axis["tick_values"] if keep(float(v))]
        step = abs(ticks[1] - ticks[0]) if len(ticks) > 1 else 1.0
        return ticks, ticks, step
    requested = axis.get("tick_count")
    if isinstance(requested, (int, float)) and not isinstance(requested, bool) and requested > 0:
        target = max(1, min(200, int(requested)))
    else:
        target = max(3, int(length_px / 80)) if is_x else max(3, int(length_px / 45))
    # Category theta is category-index space, even though it also carries the
    # angular descriptors. Its labels and tick positions must win over angle
    # formatting/generation; the projection maps the codes into the sector.
    # Each category is also one spoke/polygon vertex, so the default must not
    # thin them by pixel density. An explicit tick_count remains the opt-in
    # control for authors who want fewer spokes.
    if kind == "category":
        categories = axis.get("categories") or []
        if axis.get("theta_unit") is not None and requested is None:
            target = len(categories)
        t = [float(v) for v in _category_ticks(lo, hi, len(axis.get("categories") or []), target)]
        return t, t, 1.0
    if axis.get("theta_unit") is not None:
        t, step = _angular_ticks(lo, hi, axis["theta_unit"], target)
        return t, t, step
    if axis.get("scale") == "log" or kind == "log":
        return _log_ticks(lo, hi, target)
    if axis.get("scale") == "symlog":
        constant = float(axis.get("constant", 1.0))

        def transform(value: float) -> float:
            return float(np.sign(value) * np.log1p(abs(value) / constant))

        def inverse(value: float) -> float:
            return float(np.sign(value) * constant * np.expm1(abs(value)))

        coords, step = _linear_ticks(float(transform(lo)), float(transform(hi)), target)
        ticks = [float(inverse(v)) for v in coords]
        if min(lo, hi) <= 0 <= max(lo, hi) and not any(abs(v) < 1e-12 for v in ticks):
            ticks.append(0.0)
            ticks.sort(reverse=lo > hi)
        return ticks, ticks, abs(float(inverse(step)))
    if kind == "time":
        t, step = _time_ticks(lo, hi, target)
        return t, t, step
    t, step = _linear_ticks(lo, hi, target)
    return t, t, step


def minor_axis_ticks(axis: dict[str, Any]) -> list[float]:
    values = axis.get("minor_tick_values")
    if values is None:
        return []
    keep = _tick_window_filter(axis, *_tick_window(axis))
    return [float(value) for value in values if np.isfinite(float(value)) and keep(float(value))]


def _axis_tick_label_strategy(axis: dict[str, Any]) -> str:
    value = str(axis.get("tick_label_strategy") or "auto").replace("-", "_")
    return (
        value
        if value in {"auto", "hide", "rotate", "stagger", "preserve", "none", "off"}
        else "auto"
    )


def _axis_tick_font_size(axis: dict[str, Any]) -> float:
    style = axis.get("style") or {}
    return max(8.0, float(style.get("tick_label_size", style.get("tick_size", 11))))


def _axis_tick_geometry_authored(axis: dict[str, Any]) -> bool:
    """True when the axis authored tick geometry (label pad or mark length).

    Core's default ``tick_length`` is 0 and it has no default ``tick_padding``,
    so deriving the spine-to-label distance from tick geometry unconditionally
    would move the tick labels of *every* chart that styles no ticks. Charts
    that author neither key therefore keep the historical placement, and only
    authored geometry — an explicit ``tick_length``/``tick_padding``, or
    pyplot's rc-supplied ``{x,y}tick.major.pad`` — opts into matplotlib's rule.
    The visibility shorthand's exact ``tick_length=0, tick_width=0`` sentinel
    only suppresses paint and therefore keeps the historical label placement.
    """
    style = axis.get("style") or {}
    if "tick_padding" in style:
        return True
    if "tick_length" not in style:
        return False
    return not (
        float(style.get("tick_length", 0)) == 0.0 and float(style.get("tick_width", 1)) == 0.0
    )


def _axis_tick_sides(axis: dict[str, Any], *, is_x: bool) -> list[str]:
    """Sides that paint tick marks, independent of the label-bearing side."""
    allowed = ("bottom", "top") if is_x else ("left", "right")
    authored = axis.get("tick_sides")
    if not isinstance(authored, list):
        return [axis.get("side", allowed[0])]
    return [side for side in allowed if side in authored]


def _axis_tick_label_sides(axis: dict[str, Any], *, is_x: bool) -> list[str]:
    """Sides that paint tick labels, independent of tick marks and titles."""
    allowed = ("bottom", "top") if is_x else ("left", "right")
    authored = axis.get("tick_label_sides")
    if not isinstance(authored, list):
        return [axis.get("side", allowed[0])]
    return [side for side in allowed if side in authored]


def _axis_tick_label_offset(axis: dict[str, Any], unstyled: float, font_room: float = 0.0) -> float:
    """Distance from the axis spine to a tick label's anchor point, in px.

    Matplotlib measures tick padding from the outward end of the tick mark
    rather than from the spine, and the anchor then sits ``font_room`` times the
    tick font size further out (the SVG/raster anchor is the text baseline, so
    an x label below the plot must clear the ascent). Axes that author no tick
    geometry keep `unstyled`, the caller's historical gap for that side — see
    `_axis_tick_geometry_authored`. Those gaps were already asymmetric per side
    (16/7/8 px for bottom/top/y here), so per-side defaults reproduce the
    existing contract rather than approximate it.
    """
    if not _axis_tick_geometry_authored(axis):
        return unstyled
    style = axis.get("style") or {}
    length = max(0.0, float(style.get("tick_length", 0)))
    direction = str(style.get("tick_direction", "out"))
    outward = 0.0 if direction == "in" else length / 2 if direction == "inout" else length
    pad = outward + float(style.get("tick_padding", 4))
    return pad + _axis_tick_font_size(axis) * font_room


def _axis_tick_label_baseline_shift(axis: dict[str, Any]) -> float:
    """Baseline nudge that centers a y tick label on its tick, in px.

    Font-proportional once tick geometry is authored (matplotlib centers the
    label on its cap height); unstyled axes keep the historical flat 4 px so
    core charts do not shift. See `_axis_tick_geometry_authored`.
    """
    if not _axis_tick_geometry_authored(axis):
        return 4.0
    return _axis_tick_font_size(axis) * 0.35


def _axis_tick_label_layout(
    axis: dict[str, Any],
    values: list[float],
    step: float,
    scale: _Scale,
    is_x: bool,
) -> list[dict[str, Any]]:
    """Port ChartView._layoutTickLabels for deterministic static chrome."""
    strategy = _axis_tick_label_strategy(axis)
    if strategy in {"none", "off"}:
        return []

    font_size = _axis_tick_font_size(axis)
    min_gap = float(axis.get("tick_label_min_gap", 8 if is_x else 4))
    raw_angle = axis.get("tick_label_angle")
    explicit_angle = float(raw_angle) if raw_angle is not None else None
    base_angle = explicit_angle or 0.0
    # y collision keeps the centered extent model: every label on an axis
    # shares one anchor+angle, so an anchored y layout shifts all boxes by
    # the same offset and pairwise gaps are unchanged.  Mirror JS exactly.
    axis_style = axis.get("style") or {}
    anchor = _tick_label_anchor(axis, axis_style, "center") if is_x else "center"
    labels = [
        {
            "value": value,
            "pos": float(scale(value)),
            "text": _tick_text(axis, value, step),
            "angle": base_angle,
            "row": 0,
        }
        for value in values
    ]
    if len(labels) <= 1:
        return labels
    # Explicit locators and categorical unit conversion in the Matplotlib shim
    # author ``preserve`` because Matplotlib draws every located tick, even
    # when the result is intentionally dense. Core axes remain on ``auto`` and
    # retain their normal collision thinning.
    if strategy == "preserve":
        return labels

    def extent(label: dict[str, Any]) -> float:
        block = _textblock.measure(label["text"], font_size)
        width = max(font_size * 0.7, block.width)
        height = block.height
        angle = abs(float(label.get("angle", 0.0))) * math.pi / 180.0
        if is_x:
            return abs(math.cos(angle)) * width + abs(math.sin(angle)) * height
        return abs(math.sin(angle)) * width + abs(math.cos(angle)) * height

    def collide(items: list[dict[str, Any]]) -> bool:
        rows: dict[int, list[dict[str, Any]]] = {}
        for item in items:
            rows.setdefault(int(item.get("row", 0)), []).append(item)
        for row in rows.values():
            sorted_row = sorted(row, key=lambda candidate: float(candidate["pos"]))
            if is_x and anchor != "center":
                # Edge-anchored labels all run the same direction from their
                # tick.  Rotated ones are parallel lines: they clear each other
                # when the perpendicular gap between adjacent anchors exceeds
                # the line height, regardless of horizontal bounding-box overlap.
                # Mirror JS _tickLabelsCollide exactly.
                for i in range(1, len(sorted_row)):
                    prev = sorted_row[i - 1]
                    curr = sorted_row[i]
                    spacing = float(curr["pos"]) - float(prev["pos"])
                    angle = abs(float(curr.get("angle", 0.0))) * math.pi / 180.0
                    if angle:
                        if spacing * math.sin(angle) < font_size * 1.2 + min_gap:
                            return True
                    else:
                        lead = curr if anchor == "end" else prev
                        w = max(
                            font_size * 0.7,
                            _textblock.measure(lead["text"], font_size).width,
                        )
                        if spacing < w + min_gap:
                            return True
            else:
                last_end = -math.inf
                for item in sorted_row:
                    half = extent(item) / 2.0
                    start = float(item["pos"]) - half
                    if start < last_end + min_gap:
                        return True
                    last_end = float(item["pos"]) + half
        return False

    if strategy == "auto":
        if not collide(labels):
            return labels
        if is_x and axis.get("kind") == "category" and len(labels) <= 16:
            strategy = "rotate"
        elif is_x and len(labels) <= 24:
            strategy = "stagger"
        else:
            strategy = "hide"

    if strategy == "rotate" and is_x:
        angle = (
            explicit_angle
            if explicit_angle is not None
            else (35.0 if axis.get("side") == "top" else -35.0)
        )
        labels = [{**label, "angle": angle, "row": 0} for label in labels]
    elif strategy == "stagger" and is_x:
        labels = [{**label, "row": index % 2} for index, label in enumerate(labels)]

    # "hide" is a collision-handling strategy: the stride loop engages only
    # when the full label set actually overlaps, so relayouts that force
    # strategy="hide" (native diagonal-angle fallback) keep fitting labels.
    if collide(labels):
        for stride in range(2, len(labels) + 1):
            reduced = labels[::stride]
            if not collide(reduced):
                return reduced
        return labels[:1]
    return labels


def _axis_label_geometry(
    axis: dict[str, Any],
    plot: dict[str, float],
    *,
    is_x: bool,
) -> dict[str, Any]:
    """Resolve named axis-title placement shared by SVG and native output.

    Named positions, offsets, and angles mirror ChartView. Structured CSS
    dictionaries remain a browser-only escape hatch because native exporters
    do not have a CSS layout engine.
    """
    style = axis.get("style") or {}
    font_size = float(style.get("label_size", 12))
    raw_position = axis.get("label_position")
    position = raw_position if isinstance(raw_position, str) else "center"
    position = position.replace("-", "_")
    inside = position.startswith("inside_")
    anchor = position.removeprefix("inside_") if inside else position
    anchor_fraction = 0.0 if anchor == "start" else 1.0 if anchor == "end" else 0.5
    offset = float(axis.get("label_offset", 0.0))
    side = axis.get("side", "bottom" if is_x else "left")

    if is_x:
        x = plot["x"] + plot["w"] * anchor_fraction
        outside_top = plot["y"] - 34
        outside_bottom = plot["y"] + plot["h"] + 24
        inside_top = plot["y"] + 12
        inside_bottom = plot["y"] + plot["h"] - 12
        y = (
            (inside_top if side == "top" else inside_bottom)
            if inside
            else (outside_top if side == "top" else outside_bottom)
        )
        y += (
            (-offset if not inside else offset)
            if side == "top"
            else (offset if not inside else -offset)
        )
        # DOM labels use top positioning; static text commands use a baseline.
        y += font_size * 0.82
        text_anchor = "start" if anchor == "start" else "end" if anchor == "end" else "middle"
        angle = float(axis.get("label_angle", 0.0))
    else:
        if inside:
            inside_x = plot["x"] + plot["w"] - 12 if side == "right" else plot["x"] + 12
            x = inside_x + (-offset if side == "right" else offset)
        else:
            # The rotated title's *line box* is centered on ChartView's inset
            # (`left:10px` / `plot-right+40px`); a static exporter emits a
            # baseline. `_y_title_baseline` applies that half-line-box
            # correction and the axis's own `label_offset`, and is the same
            # function `layout()` reserves the gutter from.
            baseline = _y_title_baseline(axis, plot)
            x = (
                baseline
                if baseline is not None
                else (plot["x"] + plot["w"] + 40 + offset if side == "right" else 10 - offset)
            )
        y = plot["y"] + plot["h"] * (1.0 - anchor_fraction)
        text_anchor = "middle"
        angle = float(axis.get("label_angle", 90.0 if side == "right" else -90.0))

    return {
        "x": x,
        "y": y,
        "anchor": text_anchor,
        "angle": angle,
        "font_size": font_size,
    }


def polar_wedge_points(
    polar: "_PolarProjection",
    theta0: float,
    theta1: float,
    r0: float,
    r1: float,
    steps: Optional[int] = None,
    corner_radius: float = 0.0,
    wedge_gap: float = 0.0,
) -> list[tuple[float, float]]:
    """An annular sector as a closed polygon — the flattened twin of
    `_polar_wedge_path`, for the raster display list (no arc opcode).

    Both are driven by the same angles and radii, so the two exports agree to
    within the flattening. `steps` defaults to `config.polar_bar_segments` over
    this wedge's own sweep — a 22.5-degree wind-rose sector is flattened with six
    segments rather than the full-turn worst case of 96, at the same sagitta
    bound. Pass an explicit count only to pin one.
    """
    # Clamp both radii into the visible radial interval: a bar crossing r_lo or
    # r_hi retains the visible part instead of becoming an invalid endpoint.
    # The client clamps identically in BAR_VS; the static shaped clips then
    # contain stroke antialiasing at the exact annular-sector boundary.
    floor = polar.inner_fraction
    # Order the NORMALIZED fractions before clamping: on a reversed radial
    # axis `norm_radius` is decreasing, so norm(r1) < norm(r0) for r1 > r0 and
    # taking them positionally dropped every wedge from both static exports
    # while the shader (which min/maxes u_rrange) kept drawing them.
    lo_frac, hi_frac = sorted((float(polar.norm_radius(r0)), float(polar.norm_radius(r1))))
    outer = min(1.0, max(floor, hi_frac)) * polar.radius
    inner = min(1.0, max(floor, lo_frac)) * polar.radius
    if outer <= 0.0 or outer <= inner:
        return []
    angles = polar.wedge_angles(theta0, theta1)
    if angles is None:
        return []
    a0, a1 = angles
    if steps is None:
        steps = polar_bar_segments(a1 - a0, 2.0 * math.pi)

    if corner_radius > 0.0 and inner > 0.0:
        return _rounded_wedge_points(polar, a0, a1, inner, outer, corner_radius, steps, wedge_gap)

    # A constant ANGULAR pad makes the gap between neighbours `r · dtheta` wide,
    # so it tapers to nothing at the hole and is widest at the rim — the seam
    # between two pie slices visibly converges toward the centre. A constant
    # gap in px needs an angular inset that grows as the radius shrinks; the
    # two radial edges then become straight lines a fixed distance apart, which
    # is what d3's padAngle/padRadius pair and every pie in the wild produce.
    inset = _wedge_edge_inset(wedge_gap, a0, a1)

    def arc(radius: float, reverse: bool) -> list[tuple[float, float]]:
        d = inset(radius)
        start, end = (a1 - d, a0 + d) if reverse else (a0 + d, a1 - d)
        out = []
        for i in range(steps + 1):
            angle = start + (end - start) * (i / steps)
            out.append((polar.cx + radius * math.cos(angle), polar.cy - radius * math.sin(angle)))
        return out

    if inner <= 0.0:
        return [(polar.cx, polar.cy), *arc(outer, False)]
    return [*arc(outer, False), *arc(inner, True)]


def _wedge_edge_inset(wedge_gap: float, a0: float, a1: float):
    """Per-radius angular inset that realises a constant px gap between wedges.

    Half the gap is taken off each side, and `gap / (2r)` radians at radius `r`
    is `gap / 2` px of arc — so neighbouring slices end up separated by the same
    number of pixels from the hole to the rim. Clamped so a gap wider than the
    slice collapses it rather than inverting the edges.
    """
    half = max(0.0, float(wedge_gap)) / 2.0
    sign = 1.0 if a1 >= a0 else -1.0
    span = abs(a1 - a0)

    def inset(radius: float) -> float:
        if half <= 0.0 or radius <= 1e-9:
            return 0.0
        return sign * min(half / radius, span / 2.0)

    return inset


def _rounded_wedge_points(
    polar: "_PolarProjection",
    a0: float,
    a1: float,
    inner: float,
    outer: float,
    corner_radius: float,
    steps: int,
    wedge_gap: float = 0.0,
) -> list[tuple[float, float]]:
    """An annular sector with rounded corners, as a closed polygon.

    `corner_radius` on a slice is what every donut, progress ring and gauge
    design in the wild asks for, and it has no rectangle to hang off. The
    definition used here is the one the client's fragment SDF uses, so the
    three renderers agree: unroll the wedge into an (arc, radial) frame — where
    it *is* a rectangle, of half-height `hr` and half-width `sweep/2 · dist` at
    each radius — round it there with the standard rounded-rect profile, and
    roll it back. The corners then follow the arc instead of being chorded off.

    Sampled rather than expressed as SVG arcs: the rounded profile is not a
    circular arc once rolled back (its angular inset varies with radius), so a
    polyline is the honest shape rather than an approximation of one. Plain
    wedges keep their exact `A` arcs — this path is only taken when a radius is
    actually asked for.
    """
    r_mid = (inner + outer) / 2.0
    hr = (outer - inner) / 2.0
    sweep = abs(a1 - a0)
    mid = (a0 + a1) / 2.0
    sign = 1.0 if a1 >= a0 else -1.0

    def half_angle(lr: float) -> float:
        dist = r_mid + lr
        if dist <= 1e-9:
            return 0.0
        # Taking a constant number of px off the arc half-width at every
        # radius is exactly the constant-width gap (see `_wedge_edge_inset`);
        # the corner radius then clamps against the reduced width.
        ha_px = max(sweep * 0.5 * dist - max(0.0, wedge_gap) / 2.0, 0.0)
        rad = min(corner_radius, hr, ha_px)
        over = abs(lr) - (hr - rad)
        if over <= 0.0:
            half_px = ha_px
        else:
            half_px = (ha_px - rad) + math.sqrt(max(0.0, rad * rad - over * over))
        return half_px / dist

    def at(dist: float, angle: float) -> tuple[float, float]:
        return polar.cx + dist * math.cos(angle), polar.cy - dist * math.sin(angle)

    out: list[tuple[float, float]] = []
    # Outer rim, then the trailing edge inward, then the inner rim back, then
    # the leading edge outward. Each edge samples the rounded profile, so the
    # corner arcs fall out of the same walk rather than being spliced in.
    for i in range(steps + 1):
        t = i / steps
        out.append(at(outer, mid - sign * half_angle(hr) + sign * half_angle(hr) * 2.0 * t))
    for i in range(1, steps + 1):
        lr = hr - 2.0 * hr * (i / steps)
        out.append(at(r_mid + lr, mid + sign * half_angle(lr)))
    for i in range(1, steps + 1):
        t = i / steps
        out.append(at(inner, mid + sign * half_angle(-hr) - sign * half_angle(-hr) * 2.0 * t))
    for i in range(1, steps):
        lr = -hr + 2.0 * hr * (i / steps)
        out.append(at(r_mid + lr, mid - sign * half_angle(lr)))
    return out


def _polar_wedge_path(
    polar: "_PolarProjection",
    theta0: float,
    theta1: float,
    r0: float,
    r1: float,
    corner_radius: float = 0.0,
    wedge_gap: float = 0.0,
) -> str:
    """An annular sector as an SVG path: outer arc, inner arc reversed, closed.

    A polar bar is a wedge, not a rectangle — a 180-degree bar with chorded ends
    would read as a triangle. SVG expresses the two arcs exactly with `A`; the
    raster exporter flattens the same sector because its display list has no arc
    opcode (polar-axes.md §5/§6).
    """
    floor = polar.inner_fraction
    # Order the NORMALIZED fractions before clamping: on a reversed radial
    # axis `norm_radius` is decreasing, so norm(r1) < norm(r0) for r1 > r0 and
    # taking them positionally dropped every wedge from both static exports
    # while the shader (which min/maxes u_rrange) kept drawing them.
    lo_frac, hi_frac = sorted((float(polar.norm_radius(r0)), float(polar.norm_radius(r1))))
    outer = min(1.0, max(floor, hi_frac)) * polar.radius
    inner = min(1.0, max(floor, lo_frac)) * polar.radius
    if outer <= 0.0 or outer <= inner:
        return ""
    angles = polar.wedge_angles(theta0, theta1)
    if angles is None:
        return ""
    a0, a1 = angles
    if corner_radius > 0.0 and inner > 0.0:
        # Rounded corners are not circular arcs once rolled back out of the
        # unrolled frame, so the shared polygon is the honest shape here too.
        pts = _rounded_wedge_points(
            polar,
            a0,
            a1,
            inner,
            outer,
            corner_radius,
            # Same span-proportional count `polar_wedge_points` flattens with, so
            # a rounded wedge and its raster twin sample the identical profile.
            polar_bar_segments(a1 - a0, 2.0 * math.pi),
            wedge_gap,
        )
        if len(pts) < 3:
            return ""
        head = f"M {_num(pts[0][0])} {_num(pts[0][1])}"
        rest = " ".join(f"L {_num(x)} {_num(y)}" for x, y in pts[1:])
        return f"{head} {rest} Z"
    # `sweep` is in SVG's screen sense: y grows downward, so a counterclockwise
    # data sweep draws as a clockwise-negative arc.
    sweep = 0 if a1 > a0 else 1
    large = 1 if abs(a1 - a0) > math.pi else 0

    def at(radius: float, angle: float) -> tuple[float, float]:
        return polar.cx + radius * math.cos(angle), polar.cy - radius * math.sin(angle)

    if abs(a1 - a0) >= 2.0 * math.pi * (1.0 - 1e-9):
        # A full turn makes the arc endpoints coincide, and SVG omits such an
        # arc segment entirely — a 100% donut slice rendered as nothing. Each
        # circle is drawn as two half-turn arcs instead; the inner ring winds
        # the opposite way so the default nonzero fill leaves the hole open.
        def full_circle(radius: float, sweep_flag: int) -> str:
            x0, y0 = at(radius, a0)
            xm, ym = at(radius, a0 + math.pi)
            arc = f"A {_num(radius)} {_num(radius)} 0 1 {sweep_flag}"
            return (
                f"M {_num(x0)} {_num(y0)} {arc} {_num(xm)} {_num(ym)} {arc} {_num(x0)} {_num(y0)} Z"
            )

        if inner <= 0.0:
            return full_circle(outer, sweep)
        return f"{full_circle(outer, sweep)} {full_circle(inner, 1 - sweep)}"

    # The gap is a constant number of PIXELS, so its angular cost grows as the
    # radius shrinks (`_wedge_edge_inset`). Both arcs stay exact `A` commands —
    # only their endpoints move inward — and the radial edges become straight
    # lines a fixed distance apart, which `L` already draws.
    inset = _wedge_edge_inset(wedge_gap, a0, a1)
    d_out, d_in = inset(outer), inset(max(inner, 1e-9))
    ox0, oy0 = at(outer, a0 + d_out)
    ox1, oy1 = at(outer, a1 - d_out)
    if inner <= 0.0:
        return (
            f"M {_num(polar.cx)} {_num(polar.cy)} L {_num(ox0)} {_num(oy0)} "
            f"A {_num(outer)} {_num(outer)} 0 {large} {sweep} {_num(ox1)} {_num(oy1)} Z"
        )
    ix1, iy1 = at(inner, a1 - d_in)
    ix0, iy0 = at(inner, a0 + d_in)
    return (
        f"M {_num(ox0)} {_num(oy0)} "
        f"A {_num(outer)} {_num(outer)} 0 {large} {sweep} {_num(ox1)} {_num(oy1)} "
        f"L {_num(ix1)} {_num(iy1)} "
        f"A {_num(inner)} {_num(inner)} 0 {large} {1 - sweep} {_num(ix0)} {_num(iy0)} Z"
    )


def _polar_radial_tick_length(polar: "_PolarProjection") -> float:
    """Label-density length for the radial axis under polar.

    Radial labels march along a `_POLAR_RLABEL_DEG` spoke, so their usable run
    is the annulus width projected onto that spoke — about a fifth of the plot
    at the default 22.5 degrees. Mirrored by _radialTickLength in
    js/src/50_chartview.ts.
    """
    span = polar.radius * (1.0 - polar.inner_fraction)
    return max(1.0, span * abs(math.sin(math.radians(_POLAR_RLABEL_DEG))))


def _polar_thin_radial_labels(labels: list[float], length_px: float) -> list[float]:
    """Stride-thin radial tick LABELS to what the spoke can hold.

    The grid rings and the labels come from one tick list, so sizing the whole
    list to the spoke thinned the rings too — a 520px disc dropped from three
    rings to two. Ring density stays tied to the plot; only the labels, which
    are the things that actually collide, are thinned. Endpoints are kept so
    the radial extent stays readable.
    """
    capacity = max(2, int(length_px / 45))
    if len(labels) <= capacity:
        return labels
    stride = math.ceil(len(labels) / capacity)
    thinned = labels[::stride]
    if labels and labels[-1] not in thinned:
        thinned.append(labels[-1])
    return thinned


def _polar_frame_path(polar: "_PolarProjection") -> str:
    """SVG path for the visible annular sector, shared by clip and frame."""
    return _polar_wedge_path(
        polar,
        polar._theta_data_for_sector(polar.sector_start),
        polar._theta_data_for_sector(polar.sector_end),
        polar.r_lo,
        polar.r_hi,
    )


def _polar_linear_frame_path(polar: "_PolarProjection", theta_values: Sequence[float]) -> str:
    """Polygon-grid counterpart of ``_polar_frame_path``."""
    outer = polar.polygon_ring(polar.r_hi, theta_values)
    if len(outer) < 2:
        return _polar_frame_path(polar)

    def polyline(points: Sequence[tuple[float, float]], close: bool = False) -> str:
        commands = [f"M {_num(points[0][0])} {_num(points[0][1])}"]
        commands.extend(f"L {_num(x)} {_num(y)}" for x, y in points[1:])
        if close:
            commands.append("Z")
        return " ".join(commands)

    parts = [polyline(outer, polar.full_sector)]
    if polar.inner_radius > 0.0:
        inner = polar.polygon_ring(polar.r_lo, theta_values)
        if inner:
            parts.append(polyline(inner, polar.full_sector))
    else:
        inner = [(polar.cx, polar.cy)]
    if not polar.full_sector:
        parts.append(polyline([outer[0], inner[0]]))
        parts.append(polyline([outer[-1], inner[-1]]))
    return " ".join(parts)


def _polar_grid(
    grid: list[str],
    polar: "_PolarProjection",
    theta_ticks: list[float],
    r_ticks: list[float],
    theta_style: dict[str, Any],
    r_style: dict[str, Any],
    default_grid: str,
    hide_theta: bool,
    hide_r: bool,
) -> None:
    """Concentric rings for the radial ticks, spokes for the angular ones.

    SVG has `<circle>`, so rings are exact here rather than flattened; the
    raster exporter has no arc opcode and consumes `_PolarProjection.ring`
    instead. Both read the same tick lists, so the two outputs agree on *which*
    rings exist even though they differ in how the curve is expressed.
    """
    theta_ticks = polar.filter_theta_values(theta_ticks)
    r_ticks = [value for value in r_ticks if bool(polar.visible_mask(value))]
    r_grid = escape(_css(r_style.get("grid_color"), default_grid))
    r_width = _num(float(r_style.get("grid_width", 1)))
    r_attrs = _axis_grid_attrs(r_style)
    if not hide_r:
        for v in r_ticks:
            radius = float(polar.norm_radius(v)) * polar.radius
            if radius <= 0.0:
                continue  # the r=0 ring is a point at the centre
            if polar.grid_shape == "linear":
                points = polar.polygon_ring(v, theta_ticks)
                if len(points) < 2:
                    continue
                commands = " ".join(f"{_num(x)},{_num(y)}" for x, y in points)
                tag = "polygon" if polar.full_sector else "polyline"
                grid.append(
                    f'<{tag} data-xy-grid="ring" points="{commands}" fill="none" '
                    f'stroke="{r_grid}" stroke-width="{r_width}"{r_attrs}/>'
                )
            elif polar.full_sector:
                grid.append(
                    f'<circle data-xy-grid="ring" cx="{_num(polar.cx)}" cy="{_num(polar.cy)}" '
                    f'r="{_num(radius)}" fill="none" stroke="{r_grid}" '
                    f'stroke-width="{r_width}"{r_attrs}/>'
                )
            else:
                a0, a1 = polar.sector_a0, polar.sector_a1
                x0 = polar.cx + radius * math.cos(a0)
                y0 = polar.cy - radius * math.sin(a0)
                x1 = polar.cx + radius * math.cos(a1)
                y1 = polar.cy - radius * math.sin(a1)
                large = 1 if abs(a1 - a0) > math.pi else 0
                sweep = 0 if a1 > a0 else 1
                grid.append(
                    f'<path data-xy-grid="ring" d="M {_num(x0)} {_num(y0)} '
                    f"A {_num(radius)} {_num(radius)} 0 {large} {sweep} "
                    f'{_num(x1)} {_num(y1)}" fill="none" stroke="{r_grid}" '
                    f'stroke-width="{r_width}"{r_attrs}/>'
                )
    if hide_theta:
        return
    t_grid = escape(_css(theta_style.get("grid_color"), default_grid))
    t_width = _num(float(theta_style.get("grid_width", 1)))
    t_attrs = _axis_grid_attrs(theta_style)
    for v in theta_ticks:
        angle = float(polar.angle(v))
        inner = polar.inner_radius
        x0 = polar.cx + inner * math.cos(angle)
        y0 = polar.cy - inner * math.sin(angle)
        x1 = polar.cx + polar.radius * math.cos(angle)
        y1 = polar.cy - polar.radius * math.sin(angle)
        grid.append(
            f'<line data-xy-grid="spoke" x1="{_num(x0)}" y1="{_num(y0)}" '
            f'x2="{_num(x1)}" y2="{_num(y1)}" stroke="{t_grid}" '
            f'stroke-width="{t_width}"{t_attrs}/>'
        )


class PolarTickLabel(NamedTuple):
    """One placed polar tick label, in renderer-neutral terms.

    `anchor` is the SVG vocabulary ("start"/"middle"/"end"); the raster
    exporter maps it to its own enum at the call site. `dy` is already folded
    into `y`; it is carried separately only so a caller can re-derive the
    unshifted anchor point if it ever needs one.
    """

    x: float
    y: float
    anchor: str
    size: float
    text: str
    spin: float


def polar_tick_label_layout(
    polar: "_PolarProjection",
    theta_values: list[float],
    r_values: list[float],
    theta_step: float,
    r_step: float,
    theta_axis: dict[str, Any],
    r_axis: dict[str, Any],
    theta_size: float,
    r_size: float,
    hide_theta: bool,
    hide_r: bool,
) -> "tuple[list[PolarTickLabel], list[PolarTickLabel]]":
    """Where every polar tick label goes: (angular, radial).

    The placement — rim offset, quadrant anchor, baseline nudge, the 22.5-degree
    radial spoke — lives here once so the two exporters cannot drift on it; each
    keeps only its own sink loop. The cartesian label machinery is
    edge-relative (a side in {top, bottom, left, right} plus a 1-D collision
    axis) and neither concept survives a disc, so polar places its own rather
    than bending that code.

    Mirrored by the polar label loop in js/src/50_chartview.ts, which places DOM
    nodes with CSS translate percentages instead of anchors.
    """
    angular: list[PolarTickLabel] = []
    radial: list[PolarTickLabel] = []
    theta_spin = float(theta_axis.get("tick_label_angle") or 0.0)
    r_spin = float(r_axis.get("tick_label_angle") or 0.0)
    if not hide_theta:
        for v in polar.filter_theta_values(theta_values):
            angle = float(polar.angle(v))
            # Just outside the rim, nudged along the outward normal so the
            # glyph box clears the ring rather than straddling it.
            x = polar.cx + (polar.radius + _POLAR_TICK_GAP) * math.cos(angle)
            y = polar.cy - (polar.radius + _POLAR_TICK_GAP) * math.sin(angle)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            anchor = "middle" if abs(cos_a) < 0.3 else ("start" if cos_a > 0 else "end")
            # The baseline sits at the glyph bottom, so a label above the circle
            # needs no shift while one below needs close to a full ascent.
            dy = 0.0 if abs(sin_a) < 0.3 else (-0.1 * theta_size if sin_a > 0 else 0.8 * theta_size)
            # _tick_text, not _fmt_angle: authored tick_labels (the category
            # names on a radar chart) must win over the angle.
            angular.append(
                PolarTickLabel(
                    x, y + dy, anchor, theta_size, _tick_text(theta_axis, v, theta_step), theta_spin
                )
            )
    if not hide_r:
        # Matplotlib's default rlabel_position: off the zero spoke, so the
        # radial labels do not pile onto the theta=0 angular label.
        angle = polar.zero + polar.dir * math.radians(_POLAR_RLABEL_DEG)
        if not polar.angle_visible(angle):
            angle = (polar.sector_a0 + polar.sector_a1) / 2.0
        for v in r_values:
            if not bool(polar.visible_mask(v)):
                continue
            radius = float(polar.norm_radius(v)) * polar.radius
            if radius <= 0.0:
                continue
            radial.append(
                PolarTickLabel(
                    polar.cx + radius * math.cos(angle) + 3.0,
                    polar.cy - radius * math.sin(angle) - 3.0,
                    "start",
                    r_size,
                    _tick_text(r_axis, v, r_step),
                    r_spin,
                )
            )
    return angular, radial


def _polar_tick_labels(
    labels: list[str],
    polar: "_PolarProjection",
    theta_values: list[float],
    r_values: list[float],
    theta_step: float,
    r_step: float,
    theta_axis: dict[str, Any],
    r_axis: dict[str, Any],
    slots: dict[str, Any],
    default_text: str,
    hide_theta: bool,
    hide_r: bool,
) -> None:
    """Emit polar tick labels as SVG text, from the shared placement."""
    slot = slots.get("tick_label") or {}
    attrs = slot_text_attrs(slot)

    def tick_color(axis: dict[str, Any]) -> str:
        """Axis tick_label_color/tick_color first, chart slot second.

        Same precedence the cartesian labels use: the axis's own setting is the
        narrower selector and wins. Reading only the slot made the `text=False`
        and `show=False` shorthands — which work by setting tick_label_color to
        a transparent value — silently do nothing on a polar chart.
        """
        axis_style = axis.get("style") or {}
        own = _css(axis_style.get("tick_label_color", axis_style.get("tick_color")), "")
        return escape(own or slot_text_color(slot, default_text))

    angular, radial = polar_tick_label_layout(
        polar,
        theta_values,
        r_values,
        theta_step,
        r_step,
        theta_axis,
        r_axis,
        slot_font_size(slot, _axis_tick_font_size(theta_axis)),
        slot_font_size(slot, _axis_tick_font_size(r_axis)),
        hide_theta,
        hide_r,
    )
    for kind, placed, axis in (("theta", angular, theta_axis), ("r", radial, r_axis)):
        color = tick_color(axis)
        for item in placed:
            spin = (
                f' transform="rotate({_num(item.spin)} {_num(item.x)} {_num(item.y)})"'
                if item.spin
                else ""
            )
            labels.append(
                f'<text data-xy-tick="{kind}" x="{_num(item.x)}" y="{_num(item.y)}" '
                f'fill="{color}" font-size="{_num(item.size)}" '
                f'text-anchor="{item.anchor}"{attrs}{spin}>{escape(item.text)}</text>'
            )


def render_svg(spec: dict[str, Any], blob: bytes, *, id_prefix: str = "") -> str:
    spec = _decode_title_geometry(spec, blob)
    spec = _resolve_static_css_vars(spec)
    width, height, compact, plot = layout(spec)
    xa, ya = spec["x_axis"], spec["y_axis"]
    x_scales, y_scales, sx, sy, extra_x_axes, extra_y_axes = _axis_scales(spec, plot)
    svg = _Svg(id_prefix)
    cols = spec["columns"]
    # Polar reinterprets the same two axes: x carries theta, y carries r.
    polar = _PolarProjection(xa, ya, plot) if spec.get("coords") == "polar" else None
    # One plot-rect clipPath serves the marks group and every legend. Polar
    # clips to the disc instead, so nothing bleeds into the corners outside the
    # outer ring.
    clip_id = svg.uid("clip")
    # A polar legend lives in its own gutter OUTSIDE the plot rect, so the shared
    # clip has to cover the union of the two boxes or the legend is clipped away
    # entirely (`legend_clip_rect`, shared with the raster exporter).
    clip_x, clip_y, clip_w, clip_h = legend_clip_rect(plot)
    svg.defs.append(
        f'<clipPath id="{clip_id}"><rect x="{_num(clip_x)}" y="{_num(clip_y)}" '
        f'width="{_num(clip_w)}" height="{_num(clip_h)}"/></clipPath>'
    )
    # Marks clip to the disc under polar so nothing bleeds into the corners the
    # outer ring does not cover. This is a SECOND id: `clip_id` also bounds
    # every legend, and a legend sitting outside the circle would vanish.
    marks_clip_id = clip_id
    if polar is not None:
        marks_clip_id = svg.uid("clip")
        if polar.full_sector and polar.inner_fraction <= 0.0:
            svg.defs.append(
                f'<clipPath id="{marks_clip_id}"><circle cx="{_num(polar.cx)}" '
                f'cy="{_num(polar.cy)}" r="{_num(polar.radius)}"/></clipPath>'
            )
        else:
            svg.defs.append(
                f'<clipPath id="{marks_clip_id}"><path d="{_polar_frame_path(polar)}" '
                f'clip-rule="nonzero"/></clipPath>'
            )

    def ticks_for(axis: dict[str, Any], length_px: float) -> tuple[list[float], list[float], float]:
        return axis_ticks(axis, length_px, axis is xa)

    # -- grid + tick labels + baselines ------------------------------------
    xt, xlab, xstep = ticks_for(xa, plot["w"])
    yt, ylab, ystep = ticks_for(ya, plot["h"])
    if polar is not None:
        # Rings keep full density; only the labels ride the spoke.
        ylab = _polar_thin_radial_labels(ylab, _polar_radial_tick_length(polar))
    xmt, ymt = minor_axis_ticks(xa), minor_axis_ticks(ya)
    dom_style = (spec.get("dom") or {}).get("style") or {}
    xstyle, ystyle = xa.get("style") or {}, ya.get("style") or {}
    xmstyle, ymstyle = xa.get("minor_style") or {}, ya.get("minor_style") or {}
    default_grid = _css(dom_style.get("--chart-grid"), _GRID)
    default_axis = _css(dom_style.get("--chart-axis"), _AXIS)
    default_text = _css(dom_style.get("--chart-text"), _TEXT)
    slots = slot_styles(spec)
    grid: list[str] = []
    labels: list[str] = []
    # "none" silences the whole axis chrome (sparklines); "off" hides only the
    # label text and keeps grid, baselines and the axis title (mpl shared axes).
    hide_x = xa.get("tick_label_strategy") == "none"
    hide_y = ya.get("tick_label_strategy") == "none"
    if polar is not None:
        _polar_grid(grid, polar, xt, yt, xstyle, ystyle, default_grid, hide_x, hide_y)
    for v in xmt:
        if polar is not None:
            break
        if hide_x:
            break
        px = float(sx(v))
        grid.append(
            f'<line data-xy-grid="minor" x1="{_num(px)}" y1="{_num(plot["y"])}" '
            f'x2="{_num(px)}" y2="{_num(plot["y"] + plot["h"])}" '
            f'stroke="{escape(_css(xmstyle.get("grid_color"), "transparent"))}" '
            f'stroke-width="{_num(float(xmstyle.get("grid_width", 1)))}"'
            f"{_axis_grid_attrs(xmstyle)}/>"
        )
    for v in ymt:
        if polar is not None:
            break
        if hide_y:
            break
        py = float(sy(v))
        grid.append(
            f'<line data-xy-grid="minor" x1="{_num(plot["x"])}" y1="{_num(py)}" '
            f'x2="{_num(plot["x"] + plot["w"])}" y2="{_num(py)}" '
            f'stroke="{escape(_css(ymstyle.get("grid_color"), "transparent"))}" '
            f'stroke-width="{_num(float(ymstyle.get("grid_width", 1)))}"'
            f"{_axis_grid_attrs(ymstyle)}/>"
        )
    for v in xt:
        if polar is not None:
            break
        if hide_x:
            break
        px = float(sx(v))
        grid.append(
            f'<line x1="{_num(px)}" y1="{_num(plot["y"])}" x2="{_num(px)}" '
            f'y2="{_num(plot["y"] + plot["h"])}" '
            f'stroke="{escape(_css(xstyle.get("grid_color"), default_grid))}" '
            f'stroke-width="{_num(float(xstyle.get("grid_width", 1)))}"'
            f"{_axis_grid_attrs(xstyle)}/>"
        )
    for v in yt:
        if polar is not None:
            break
        if hide_y:
            break
        py = float(sy(v))
        grid.append(
            f'<line x1="{_num(plot["x"])}" y1="{_num(py)}" x2="{_num(plot["x"] + plot["w"])}" '
            f'y2="{_num(py)}" stroke="{escape(_css(ystyle.get("grid_color"), default_grid))}" '
            f'stroke-width="{_num(float(ystyle.get("grid_width", 1)))}"'
            f"{_axis_grid_attrs(ystyle)}/>"
        )

    def append_tick_labels(
        axis: dict[str, Any],
        values: list[float],
        step: float,
        axis_scale: _Scale,
        *,
        is_x: bool,
    ) -> None:
        axis_style = axis.get("style") or {}
        slot = slots.get("tick_label") or {}
        # The axis's own tick_label_color/tick_color is the narrower selector
        # and wins; the chart-wide slot fills in when the axis says nothing.
        color = escape(
            _css(
                axis_style.get("tick_label_color", axis_style.get("tick_color")),
                "",
            )
            or slot_text_color(slot, default_text)
        )
        font_size = slot_font_size(slot, _axis_tick_font_size(axis))
        slot_attrs = slot_text_attrs(slot)
        baseline_shift = _axis_tick_label_baseline_shift(axis)
        # An explicit tick_label_anchor (axis spec or style) overrides the
        # angle/side-derived default. Anchored labels rotate about the tick
        # point (the rotate() pivot below), so anchor and rotation compose —
        # matching the browser client.
        explicit_anchor = _tick_label_anchor(axis, axis_style, "")
        for side in _axis_tick_label_sides(axis, is_x=is_x):
            side_axis = {**axis, "side": side}
            # Unstyled defaults reproduce the pre-`tick_label_pad` placement exactly.
            if is_x:
                label_offset = (
                    _axis_tick_label_offset(axis, 7.0, 0.2)
                    if side == "top"
                    else _axis_tick_label_offset(axis, 16.0, 0.8)
                )
            else:
                label_offset = _axis_tick_label_offset(axis, 8.0)
            for item in _axis_tick_label_layout(side_axis, values, step, axis_scale, is_x):
                angle = float(item["angle"])
                block = _textblock.measure(item["text"], font_size)
                if is_x:
                    row_offset = float(item["row"]) * (font_size + 4)
                    x = float(item["pos"])
                    y = (
                        plot["y"] - label_offset - row_offset
                        if side == "top"
                        else plot["y"] + plot["h"] + label_offset + row_offset
                    )
                    if explicit_anchor:
                        anchor = _TEXT_ANCHORS[explicit_anchor]
                    elif angle == 0:
                        anchor = "middle"
                    elif (side == "bottom" and angle < 0) or (side == "top" and angle > 0):
                        anchor = "end"
                    else:
                        anchor = "start"
                else:
                    x = (
                        plot["x"] + plot["w"] + label_offset
                        if side == "right"
                        else plot["x"] - label_offset
                    )
                    y = (
                        float(item["pos"])
                        + baseline_shift
                        - (block.line_count - 1) * block.line_step / 2.0
                    )
                    if explicit_anchor:
                        anchor = _TEXT_ANCHORS[explicit_anchor]
                    else:
                        anchor = "start" if side == "right" else "end"
                transform = (
                    f' transform="rotate({_num(angle)} {_num(x)} {_num(y)})"' if angle else ""
                )
                labels.append(
                    f'<text x="{_num(x)}" y="{_num(y)}" fill="{color}" '
                    f'font-size="{_num(font_size)}" text-anchor="{anchor}"'
                    f"{slot_attrs}{transform}>"
                    f"{_text_block_content(item['text'], x, block.line_step)}</text>"
                )

    if polar is not None:
        # "off" hides only the label text (cartesian keeps grid and titles);
        # "none" — folded into hide_x/hide_y — silences the whole axis chrome.
        _polar_tick_labels(
            labels,
            polar,
            xlab,
            ylab,
            xstep,
            ystep,
            xa,
            ya,
            slots,
            default_text,
            hide_x or xa.get("tick_label_strategy") == "off",
            hide_y or ya.get("tick_label_strategy") == "off",
        )
    else:
        append_tick_labels(xa, xlab, xstep, sx, is_x=True)
        append_tick_labels(ya, ylab, ystep, sy, is_x=False)
    extra_x_ticks: dict[str, tuple[list[float], list[float], float]] = {}
    for axis_id, axis, axis_scale in extra_x_axes:
        ticks, tick_labels, step = axis_ticks(axis, plot["w"], True)
        extra_x_ticks[axis_id] = (ticks, tick_labels, step)
        append_tick_labels(axis, tick_labels, step, axis_scale, is_x=True)
    extra_y_ticks: dict[str, tuple[list[float], list[float], float]] = {}
    for axis_id, axis, axis_scale in extra_y_axes:
        ticks, tick_labels, step = axis_ticks(axis, plot["h"], False)
        extra_y_ticks[axis_id] = (ticks, tick_labels, step)
        append_tick_labels(axis, tick_labels, step, axis_scale, is_x=False)

    # -- marks --------------------------------------------------------------
    marks: list[str] = []
    # The chart's categorical cycle (`xy.theme(palette=...)`), else the
    # built-in default. Traces normally carry a baked style color; this is the
    # fallback for specs that do not.
    spec_palette: Sequence[str] = spec.get("palette") or DEFAULT_PALETTE
    palette_cycle = 0

    def line_attrs(style: dict[str, Any], color: str) -> str:
        w = float(style.get("width", 1.5))
        op = _stroke_opacity(style)
        return (
            f'stroke="{escape(color)}" stroke-width="{_num(w)}" fill="none" '
            + _cap_join_attrs(style)
            + (f' stroke-opacity="{_num(op)}"' if op < 1 else "")
            + _dash_attr(style)
        )

    for t in spec["traces"]:
        style = t.get("style") or {}
        kind = t["kind"]
        tier = t.get("tier")
        color = _css(style.get("color"), spec_palette[palette_cycle % len(spec_palette)])
        palette_cycle += 1
        trace_sx = x_scales.get(t.get("x_axis", "x"), sx)
        trace_sy = y_scales.get(t.get("y_axis", "y"), sy)

        if tier == "density" and t.get("density"):
            marks.append(_density_image(t["density"], blob, cols, trace_sx, trace_sy, style, svg))
            continue

        if kind == "line":
            xv = _column(blob, cols[t["x"]])
            yv = _column(blob, cols[t["y"]])
            if style.get("step"):
                xv, yv = _step_arrays(xv, yv, style["step"])
            d = _curve_path(xv, yv, trace_sx, trace_sy, style.get("curve") == "smooth", polar)
            marks.append(f'<path d="{d}" {line_attrs(style, color)}/>')

        elif kind in ("area", "error_band"):
            xv = _column(blob, cols[t["x"]])
            yv = _column(blob, cols[t["y"]])
            bv = _column(blob, cols[t["base"]])
            smooth = style.get("curve") == "smooth"
            if polar is not None:
                radial_min, radial_max = sorted((polar.r_lo, polar.r_hi))
                yv = np.clip(yv, radial_min, radial_max)
                bv = np.clip(bv, radial_min, radial_max)
            # Still needed for the (non-perimeter) outline below; the fill
            # builds its own paired paths so each visible run can close alone.
            top_path = _curve_path(xv, yv, trace_sx, trace_sy, smooth, polar)
            fill_spec = style.get("fill")
            fill = (
                svg.gradient(fill_spec, color, plot)
                if isinstance(fill_spec, dict)
                else escape(color)
            )
            op = _fill_opacity(style, 0.35)
            # A polar area can be culled away entirely — every vertex outside
            # the authored sector, or a log radial axis annihilating each row —
            # or split into several visible runs. The flat join then produced
            # " L  Z", malformed path data that also reached the PDF
            # converter's _parse_path, or stitched the first top run onto the
            # base with a stray L. Close each visible run on its own.
            joined = _area_fill_path(xv, yv, bv, trace_sx, trace_sy, smooth, polar)
            if joined:
                marks.append(f'<path d="{joined}" fill="{fill}" fill-opacity="{_num(op)}"/>')
            lw = float(style.get("line_width", 1.2))
            if lw > 0 and (joined or top_path):
                lop = _stroke_opacity(style, 0.35) * float(style.get("line_opacity", 1.0))
                line_color = style.get("line_color") or color
                outline_path = joined if style.get("stroke_perimeter") else top_path
                marks.append(
                    f'<path d="{outline_path}" stroke="{escape(line_color)}" stroke-width="{_num(lw)}" '
                    'fill="none"'
                    # The area outline named its join but inherited SVG's `butt`
                    # cap, while the native rasterizer capped it round. Naming
                    # both settles that on the rasterizer's answer.
                    + _cap_join_attrs(style)
                    + (f' stroke-opacity="{_num(lop)}"' if lop < 1 else "")
                    + _dash_attr(style)
                    + "/>"
                )

        elif kind == "scatter":
            marks.extend(_scatter_marks(t, blob, cols, trace_sx, trace_sy, style, color, polar))

        elif kind == "hexbin":
            marks.append(_hexbin_marks(t, blob, cols, trace_sx, trace_sy, style, color))

        elif kind in {"errorbar", "stem", "box_whisker", "box_median", "contour", "segments"}:
            marks.append(_segment_marks(t, blob, cols, trace_sx, trace_sy, style, color, polar))

        elif kind in ("bar", "column") and t.get("bar"):
            marks.append(
                _bar_marks(t, blob, cols, trace_sx, trace_sy, style, color, svg, plot, polar)
            )

        elif kind == "heatmap" and t.get("heatmap"):
            marks.append(_heatmap_image(t["heatmap"], blob, cols, trace_sx, trace_sy, style, polar))

        elif kind == "triangle_mesh":
            marks.append(_triangle_mesh_marks(t, blob, cols, trace_sx, trace_sy, style, color))

        elif kind == "ribbon":
            # MUST precede the rect fall-through below: a ribbon ships
            # x0/x1/y0/y1 too, so a later branch would silently draw every
            # flow band as a rectangle.
            marks.append(_ribbon_marks(t, blob, cols, trace_sx, trace_sy, style, color, svg))

        elif kind == "funnel":
            marks.append(_funnel_marks(t, blob, cols, trace_sx, trace_sy, style, color))

        elif all(k in t for k in ("x0", "x1", "y0", "y1")):  # histogram / rect family
            marks.append(
                _rect_marks(t, blob, cols, trace_sx, trace_sy, style, color, svg, plot, polar)
            )

    # -- chrome text ----------------------------------------------------------
    chrome: list[str] = []
    legacy_title = spec.get("title") if not spec.get("title_options") else None
    title_wrap_width = plot.get("title_wrap_width")
    if legacy_title:
        title_slot = slots.get("title") or {}
        legacy_size = slot_font_size(title_slot, 14.0)
        legacy_block = _textblock.measure(legacy_title, legacy_size, max_width=title_wrap_width)
        # Wrapped lines run downward from the baseline, so lift the block by its
        # trailing lines: the LAST line keeps the historical single-line baseline
        # and the extra lines fill the room `_title_room` reserved above it. A
        # one-line title has no trailing lines and is byte-identical to before.
        legacy_trailing = (legacy_block.line_count - 1) * legacy_block.line_step
        legacy_y = plot["y"] - plot["top_axis_room"] - (10 if compact else 12) - legacy_trailing
        legacy_x = width / 2
        legacy_text = "\n".join(legacy_block.lines)
        legacy_content = _text_block_content(legacy_text, legacy_x, legacy_block.line_step)
        chrome.append(
            f'<text x="{_num(legacy_x)}" '
            f'y="{_num(legacy_y)}" '
            f'text-anchor="middle" font-size="{_num(legacy_size)}"'
            f"{slot_text_attrs(title_slot, font_weight='400')} "
            f'fill="{escape(slot_text_color(title_slot, default_text))}">'
            f"{legacy_content}</text>"
        )
    for title_entry in [] if legacy_title else _title_entries(spec):
        title_style, title_size, title_block = _title_metrics(spec, title_entry, title_wrap_width)
        # Matplotlib's `axes.titleweight`/`axes.labelweight` both default to
        # "normal", so chrome text stays at 400 unless a style or rcParam asks
        # for more. Keep this in step with the `title`/`axis_title` slot rules
        # in js/src/20_theme.ts and the raster defaults in _raster.py.
        title_font_attrs = slot_text_attrs(title_style, font_weight="400")
        trailing = (title_block.line_count - 1) * title_block.line_step
        if title_entry.get("automatic_y", True):
            title_anchor_y = plot["y"] - plot["top_axis_room"]
        else:
            title_anchor_y = plot["y"] + (1.0 - float(title_entry.get("y", 1.0))) * plot["h"]
        title_y = (
            title_anchor_y - float(title_entry.get("pad", 8.0)) - title_block.descent - trailing
        )
        loc = str(title_entry.get("loc", "center"))
        title_x = {
            "left": plot["x"],
            "center": plot["x"] + plot["w"] / 2.0,
            "right": plot["x"] + plot["w"],
        }.get(loc, plot["x"] + plot["w"] / 2.0)
        anchor = {"left": "start", "center": "middle", "right": "end"}.get(loc, "middle")
        # `title_block.lines` is the wrapped set — drawing `entry["text"]` here
        # would put the whole title on one line inside a band reserved for two.
        title_content = _text_block_content(
            "\n".join(title_block.lines), title_x, title_block.line_step
        )
        chrome.append(
            f'<text x="{_num(title_x)}" '
            f'y="{_num(title_y)}" '
            f'text-anchor="{anchor}" font-size="{_num(title_size)}" '
            f"{title_font_attrs.lstrip()} "
            f'fill="{escape(slot_text_color(title_style, default_text))}">'
            f"{title_content}</text>"
        )

    def append_axis_title(axis: dict[str, Any], *, is_x: bool) -> None:
        if not axis.get("label") or _axis_tick_label_strategy(axis) == "none":
            return
        axis_style = axis.get("style") or {}
        slot = slots.get("axis_title") or {}
        geometry = _axis_label_geometry(axis, plot, is_x=is_x)
        x, y = float(geometry["x"]), float(geometry["y"])
        angle = float(geometry["angle"])
        transform = f' transform="rotate({_num(angle)} {_num(x)} {_num(y)})"' if angle else ""
        # The axis's own label_* keys are the narrower selector, so they win
        # over the chart-wide slot; the slot supplies whatever they leave unset.
        family = axis_style.get("label_font_family")
        font_style = axis_style.get("label_font_style")
        weight = axis_style.get("label_font_weight", 400)
        paint = _css(axis_style.get("label_color"), "") or slot_text_color(slot, default_text)
        font_attrs = (f' font-family="{_escape_attr(family)}"' if family is not None else "") + (
            f' font-style="{_escape_attr(font_style)}"' if font_style is not None else ""
        )
        if not font_attrs:
            font_attrs = slot_text_attrs(slot, font_weight=weight)
        else:
            font_attrs = f' font-weight="{_escape_attr(weight)}"' + font_attrs
        font_size = slot_font_size(slot, float(geometry["font_size"]))
        block = _textblock.measure(axis["label"], font_size)
        chrome.append(
            f'<text x="{_num(x)}" y="{_num(y)}" text-anchor="{geometry["anchor"]}" '
            f'font-size="{_num(font_size)}"'
            f"{font_attrs} "
            f'fill="{escape(paint)}"{transform}>'
            f"{_text_block_content(axis['label'], x, block.line_step)}</text>"
        )

    append_axis_title(xa, is_x=True)
    append_axis_title(ya, is_x=False)
    for _axis_id, axis, _axis_scale in extra_x_axes:
        append_axis_title(axis, is_x=True)
    for _axis_id, axis, _axis_scale in extra_y_axes:
        append_axis_title(axis, is_x=False)
    named = legend_items(spec["traces"], spec_palette)
    legend_label_slot = slots.get("legend_label") or {}
    legend_title_slot = slots.get("legend_title") or {}
    main_legend = spec.get("legend") or {}
    main_items = main_legend.get("items") or named
    if spec.get("show_legend", True) and main_items:
        chrome.append(
            _legend(
                main_items,
                plot,
                legend_options_with_slot(spec, main_legend),
                clip_id,
                default_text,
                spec_palette,
                legend_label_slot,
                legend_title_slot,
            )
        )
    for extra in spec.get("extra_legends") or []:
        items = extra.get("items") or []
        if items:
            chrome.append(
                _legend(
                    items,
                    plot,
                    legend_options_with_slot(spec, extra),
                    clip_id,
                    default_text,
                    spec_palette,
                    legend_label_slot,
                    legend_title_slot,
                )
            )
    if spec.get("colorbar"):
        chrome.append(
            _colorbar(
                spec["colorbar"],
                plot,
                _colorbar_right_axis_room(ya, extra_y_axes, compact),
                default_text,
                slots.get("colorbar_title") or slots.get("colorbar") or {},
                slots.get("colorbar_tick") or slots.get("colorbar") or {},
            )
        )

    annotation_marks, unclipped_annotation_marks, annotation_labels = _annotation_svg(
        spec.get("annotations") or [],
        sx,
        sy,
        plot,
        width,
        height,
        polar,
        # The live client resolves an annotation label through
        # var(--chart-annotation-text, var(--chart-text, inherit)); the
        # exporters must reach the same colour or a themed chart's labels
        # print in the light-mode default (parity is identity).
        _css(dom_style.get("--chart-annotation-text"), "")
        or _css(dom_style.get("--chart-text"), "")
        or "#667085",
    )
    marks.extend(annotation_marks)
    labels.extend(annotation_labels)

    # baselines above the marks, matching the client's overlay rules
    baselines = ""
    frame_sides = spec.get("frame_sides")
    explicit_frame_sides = frame_sides is not None
    if frame_sides is None:
        frame_sides = [xa.get("side", "bottom"), ya.get("side", "left")]
    if polar is not None:
        # One annular-sector outline replaces the four straight spines; "side"
        # has no polar meaning, so frame_sides is deliberately not consulted.
        frame_sides = []
        if not hide_x:
            frame_paint = escape(_css(xstyle.get("axis_color"), default_axis))
            frame_width = _num(float(xstyle.get("axis_width", 1)))
            if polar.full_sector and polar.inner_fraction <= 0.0 and polar.grid_shape != "linear":
                baselines += (
                    f'<circle data-xy-frame="polar" cx="{_num(polar.cx)}" '
                    f'cy="{_num(polar.cy)}" r="{_num(polar.radius)}" fill="none" '
                    f'stroke="{frame_paint}" stroke-width="{frame_width}"/>'
                )
            else:
                frame_path = (
                    _polar_linear_frame_path(polar, xt)
                    if polar.grid_shape == "linear"
                    else _polar_frame_path(polar)
                )
                baselines += (
                    f'<path data-xy-frame="polar" d="{frame_path}" fill="none" '
                    f'stroke="{frame_paint}" stroke-width="{frame_width}"/>'
                )
    if not hide_y or explicit_frame_sides:
        for side, x in (("left", plot["x"]), ("right", plot["x"] + plot["w"])):
            if side in frame_sides:
                baselines += (
                    f'<line x1="{_num(x)}" y1="{_num(plot["y"])}" x2="{_num(x)}" '
                    f'y2="{_num(plot["y"] + plot["h"])}" '
                    f'stroke="{escape(_css(ystyle.get("axis_color"), default_axis))}" '
                    f'stroke-width="{_num(float(ystyle.get("axis_width", 1)))}"/>'
                )
    if not hide_x or explicit_frame_sides:
        for side, y in (("top", plot["y"]), ("bottom", plot["y"] + plot["h"])):
            if side in frame_sides:
                baselines += (
                    f'<line x1="{_num(plot["x"])}" y1="{_num(y)}" '
                    f'x2="{_num(plot["x"] + plot["w"])}" y2="{_num(y)}" '
                    f'stroke="{escape(_css(xstyle.get("axis_color"), default_axis))}" '
                    f'stroke-width="{_num(float(xstyle.get("axis_width", 1)))}"/>'
                )
    for _axis_id, axis, _axis_scale in extra_x_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        edge = plot["y"] if axis.get("side", "bottom") == "top" else plot["y"] + plot["h"]
        baselines += (
            f'<line x1="{_num(plot["x"])}" y1="{_num(edge)}" '
            f'x2="{_num(plot["x"] + plot["w"])}" y2="{_num(edge)}" '
            f'stroke="{escape(_css(axis_style.get("axis_color"), default_axis))}" '
            f'stroke-width="{_num(float(axis_style.get("axis_width", 1)))}"/>'
        )
    for _axis_id, axis, _axis_scale in extra_y_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        edge = plot["x"] + plot["w"] if axis.get("side", "right") == "right" else plot["x"]
        baselines += (
            f'<line x1="{_num(edge)}" y1="{_num(plot["y"])}" x2="{_num(edge)}" '
            f'y2="{_num(plot["y"] + plot["h"])}" '
            f'stroke="{escape(_css(axis_style.get("axis_color"), default_axis))}" '
            f'stroke-width="{_num(float(axis_style.get("axis_width", 1)))}"/>'
        )

    def tick_span(style: dict[str, Any]) -> tuple[float, float, float]:
        length = max(0.0, float(style.get("tick_length", 0)))
        direction = str(style.get("tick_direction", "out"))
        if direction == "in":
            return length, 0.0, float(style.get("tick_width", 1))
        if direction == "inout":
            return length / 2, length / 2, float(style.get("tick_width", 1))
        return 0.0, length, float(style.get("tick_width", 1))

    if not hide_x and polar is None:
        inward, outward, tick_width = tick_span(xmstyle)
        side = xa.get("side", "bottom")
        edge = plot["y"] if side == "top" else plot["y"] + plot["h"]
        for value in xmt:
            x = float(sx(value))
            y1, y2 = (
                (edge - outward, edge + inward)
                if side == "top"
                else (edge - inward, edge + outward)
            )
            baselines += (
                f'<line data-xy-tick="minor" x1="{_num(x)}" y1="{_num(y1)}" '
                f'x2="{_num(x)}" y2="{_num(y2)}" '
                f'stroke="{escape(_css(xmstyle.get("tick_color"), default_axis))}" '
                f'stroke-width="{_num(tick_width)}"/>'
            )
        inward, outward, tick_width = tick_span(xstyle)
        for side in _axis_tick_sides(xa, is_x=True):
            edge = plot["y"] if side == "top" else plot["y"] + plot["h"]
            for value in xt:
                x = float(sx(value))
                y1, y2 = (
                    (edge - outward, edge + inward)
                    if side == "top"
                    else (edge - inward, edge + outward)
                )
                baselines += (
                    f'<line x1="{_num(x)}" y1="{_num(y1)}" '
                    f'x2="{_num(x)}" y2="{_num(y2)}" '
                    f'stroke="{escape(_css(xstyle.get("tick_color"), default_axis))}" '
                    f'stroke-width="{_num(tick_width)}"/>'
                )
    if not hide_y and polar is None:
        inward, outward, tick_width = tick_span(ymstyle)
        side = ya.get("side", "left")
        edge = plot["x"] + plot["w"] if side == "right" else plot["x"]
        for value in ymt:
            y = float(sy(value))
            x1, x2 = (
                (edge - inward, edge + outward)
                if side == "right"
                else (edge - outward, edge + inward)
            )
            baselines += (
                f'<line data-xy-tick="minor" x1="{_num(x1)}" y1="{_num(y)}" '
                f'x2="{_num(x2)}" y2="{_num(y)}" '
                f'stroke="{escape(_css(ymstyle.get("tick_color"), default_axis))}" '
                f'stroke-width="{_num(tick_width)}"/>'
            )
        inward, outward, tick_width = tick_span(ystyle)
        for side in _axis_tick_sides(ya, is_x=False):
            edge = plot["x"] + plot["w"] if side == "right" else plot["x"]
            for value in yt:
                y = float(sy(value))
                x1, x2 = (
                    (edge - inward, edge + outward)
                    if side == "right"
                    else (edge - outward, edge + inward)
                )
                baselines += (
                    f'<line x1="{_num(x1)}" y1="{_num(y)}" '
                    f'x2="{_num(x2)}" y2="{_num(y)}" '
                    f'stroke="{escape(_css(ystyle.get("tick_color"), default_axis))}" '
                    f'stroke-width="{_num(tick_width)}"/>'
                )
    for axis_id, axis, axis_scale in extra_x_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        inward, outward, tick_width = tick_span(axis_style)
        for side in _axis_tick_sides(axis, is_x=True):
            edge = plot["y"] if side == "top" else plot["y"] + plot["h"]
            for value in extra_x_ticks[axis_id][0]:
                x = float(axis_scale(value))
                y1, y2 = (
                    (edge - outward, edge + inward)
                    if side == "top"
                    else (edge - inward, edge + outward)
                )
                baselines += (
                    f'<line x1="{_num(x)}" y1="{_num(y1)}" '
                    f'x2="{_num(x)}" y2="{_num(y2)}" '
                    f'stroke="{escape(_css(axis_style.get("tick_color"), default_axis))}" '
                    f'stroke-width="{_num(tick_width)}"/>'
                )
    for axis_id, axis, axis_scale in extra_y_axes:
        if _axis_tick_label_strategy(axis) == "none":
            continue
        axis_style = axis.get("style") or {}
        inward, outward, tick_width = tick_span(axis_style)
        for side in _axis_tick_sides(axis, is_x=False):
            edge = plot["x"] + plot["w"] if side == "right" else plot["x"]
            for value in extra_y_ticks[axis_id][0]:
                y = float(axis_scale(value))
                x1, x2 = (
                    (edge - inward, edge + outward)
                    if side == "right"
                    else (edge - outward, edge + inward)
                )
                baselines += (
                    f'<line x1="{_num(x1)}" y1="{_num(y)}" '
                    f'x2="{_num(x2)}" y2="{_num(y)}" '
                    f'stroke="{escape(_css(axis_style.get("tick_color"), default_axis))}" '
                    f'stroke-width="{_num(tick_width)}"/>'
                )

    defs = f"<defs>{''.join(svg.defs)}</defs>" if svg.defs else ""
    # Figure patch + plot-rect backgrounds, mirroring the browser: the root
    # element's CSS `background` (theme(background=)) behind everything, then
    # the --chart-bg token over the plot rect only. Solid colors only —
    # gradients stay browser-only, and an unset token stays transparent.
    backgrounds = ""
    # Export-time canvas override (unified export API `background=`): one
    # backdrop rect behind the figure patch. "transparent"/"none" mean "no
    # backdrop", which is already SVG's default — nothing to paint.
    canvas_paint = spec.get("canvas_background")
    if canvas_paint and canvas_paint not in ("transparent", "none"):
        backgrounds += f'<rect width="{width}" height="{height}" fill="{escape(canvas_paint)}"/>'
    figure_background = _solid_paint(dom_style.get("background"))
    if figure_background is not None:
        backgrounds += (
            f'<rect width="{width}" height="{height}" fill="{escape(figure_background)}"/>'
        )
    plot_paint = _solid_paint(dom_style.get("--chart-bg"))
    if plot_paint is not None:
        backgrounds += (
            f'<rect x="{_num(plot["x"])}" y="{_num(plot["y"])}" width="{_num(plot["w"])}" '
            f'height="{_num(plot["h"])}" fill="{escape(plot_paint)}"/>'
        )
    # One flat join over the pieces rather than nested `join`s inside an
    # f-string: the mark list is the whole document for a per-point chart (tens
    # of MB at 100k markers), and joining it separately would materialize a
    # second full copy of it before the result string is built.
    return "".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{_FONT}" font-size="11">',
            defs,
            backgrounds,
            "<g>",
            *grid,
            "</g>",
            f'<g clip-path="url(#{marks_clip_id})">',
            *marks,
            "</g>",
            *unclipped_annotation_marks,
            baselines,
            f'<g fill="{escape(default_text)}">',
            *labels,
            "</g>",
            *chrome,
            "</svg>",
        ]
    )


def annotation_label_placement(
    ann: dict[str, Any],
    style: dict[str, Any],
    sx: Callable[[float], float],
    sy: Callable[[float], float],
    plot: dict[str, float],
    width: float,
    height: float,
    polar: "Optional[_PolarProjection]" = None,
) -> tuple[float, float, Optional[str], Optional[str]]:
    """Where an annotation's `text=` hangs, as `(x, y, anchor, vertical_align)`.

    Ported from `_drawAnnotationLabels` (js/src/51_annotations.ts) and shared by
    both static exporters, which previously drew labels for `text`/`callout`
    only — a `hline(text="target")` was silently label-less in every SVG, PNG
    and PDF while the browser drew it.

    Rules and bands carry no anchor of their own, so the returned defaults are
    the ones that keep the badge inside the plot rect."""
    px0, py0 = plot["x"], plot["y"]
    kind = ann.get("kind")
    anchor = ann.get("anchor")
    vertical_align = style.get("vertical_align")
    if kind in ("rule", "band"):
        if ann.get("axis") == "x":
            if kind == "rule":
                x = float(sx(float(ann["value"])))
            else:
                x = (float(sx(float(ann["start"]))) + float(sx(float(ann["end"])))) / 2
                anchor = anchor or "middle"
            return x, py0 + 6.0, anchor, vertical_align or "top"
        x = px0 + plot["w"] - 6.0
        if kind == "rule":
            y = float(sy(float(ann["value"])))
        else:
            y = (float(sy(float(ann["start"]))) + float(sy(float(ann["end"])))) / 2
            vertical_align = vertical_align or "middle"
        return x, y, anchor or "end", vertical_align
    if kind == "arrow":
        if polar is not None:
            x0, y0 = polar(float(ann["x0"]), float(ann["y0"]))
            x1, y1 = polar(float(ann["x1"]), float(ann["y1"]))
            x = (float(x0) + float(x1)) / 2
            y = (float(y0) + float(y1)) / 2
        else:
            x = (float(sx(float(ann["x0"]))) + float(sx(float(ann["x1"])))) / 2
            y = (float(sy(float(ann["y0"]))) + float(sy(float(ann["y1"])))) / 2
        return x, y, anchor or "middle", vertical_align or "middle"
    if kind == "marker":
        if polar is not None:
            # (theta, r) projects jointly; the separable pair would read the
            # disc centre (r = 0, any angle) as the bottom-left corner.
            ax, ay = polar(float(ann["x"]), float(ann["y"]))
            return float(ax), float(ay), anchor, vertical_align
        return float(sx(float(ann["x"]))), float(sy(float(ann["y"]))), anchor, vertical_align
    x, y = float(ann.get("x", 0.0)), float(ann.get("y", 0.0))
    space = style.get("coordinate_space")
    if space == "axes_fraction":
        return px0 + x * plot["w"], py0 + (1.0 - y) * plot["h"], anchor, vertical_align
    if space == "figure_fraction":
        return x * width, (1.0 - y) * height, anchor, vertical_align
    if space == "yaxis_transform":
        return px0 + x * plot["w"], float(sy(y)), anchor, vertical_align
    if space == "xaxis_transform":
        return float(sx(x)), py0 + (1.0 - y) * plot["h"], anchor, vertical_align
    if polar is not None:
        # Data-space (theta, r) projects jointly; the separable pair would read
        # the disc centre (r = 0, at any angle) as the bottom-left corner. The
        # fraction-space branches above are already renderer-neutral.
        ax, ay = polar(x, y)
        return float(ax), float(ay), anchor, vertical_align
    return float(sx(x)), float(sy(y)), anchor, vertical_align


def _annotation_first_baseline(
    anchor_y: float,
    line_count: int,
    line_height: float,
    font_size: float,
    vertical_align: Any,
) -> float:
    """Approximate Matplotlib's multiline vertical-alignment box.

    Matplotlib aligns ``top`` and ``bottom`` against the full multiline text
    extent, not against a block that has first been centered on the anchor.
    Its default ``baseline`` alignment pins the final line's baseline at the
    supplied position, so preceding lines grow upward from that anchor.
    With screen-space y increasing downwards, the first baseline therefore
    sits one ascent below a top anchor, or all later baselines plus one descent
    above a bottom anchor.  Center retains the established exporter
    approximation.
    """
    line_span = max(0, int(line_count) - 1) * line_height
    if vertical_align == "top":
        return anchor_y + font_size * 0.8
    if vertical_align == "bottom":
        return anchor_y - line_span - font_size * 0.2
    if vertical_align in (None, "", "baseline"):
        return anchor_y - line_span
    first_baseline = anchor_y - line_span / 2
    if vertical_align in ("center", "middle"):
        first_baseline += font_size * 0.35
    return first_baseline


def _annotation_connector_unclipped(
    ann: dict[str, Any],
    sx: Callable[[float], float],
    sy: Callable[[float], float],
    plot: dict[str, float],
    polar: "Optional[_PolarProjection]" = None,
) -> bool:
    """Whether an arrow may leave the axes because its target is in bounds.

    Matplotlib's default ``annotation_clip=None`` clips based on the annotated
    point, not the text/connector path.  A label may therefore sit outside the
    axes while its connector remains visible back to an in-bounds target.
    """
    kind = ann.get("kind")
    if kind == "arrow":
        target = ann.get("x1"), ann.get("y1")
    elif kind == "callout":
        target = ann.get("x"), ann.get("y")
    else:
        return False
    try:
        x, y = float(cast(Any, target[0])), float(cast(Any, target[1]))
        if polar is not None:
            if not bool(polar.position_mask(x, y)):
                return False
            px, py = polar(x, y)
            px, py = float(px), float(py)
        else:
            px, py = float(sx(x)), float(sy(y))
    except (TypeError, ValueError):
        return False
    return (
        np.isfinite(px)
        and np.isfinite(py)
        and plot["x"] <= px <= plot["x"] + plot["w"]
        and plot["y"] <= py <= plot["y"] + plot["h"]
    )


def _annotation_svg(
    annotations: Sequence[dict[str, Any]],
    sx: Callable[[float], float],
    sy: Callable[[float], float],
    plot: dict[str, float],
    width: float,
    height: float,
    polar: "Optional[_PolarProjection]" = None,
    default_text: str = "#667085",
) -> tuple[list[str], list[str], list[str]]:
    marks: list[str] = []
    unclipped_marks: list[str] = []
    labels: list[str] = []
    px0, py0 = plot["x"], plot["y"]

    def point(x: float, y: float) -> tuple[float, float]:
        """A point-anchored annotation's position.

        Under polar the pair is (theta, r) and must project jointly — the
        separable sx/sy would read them as cartesian, putting `(0, 0)` (the
        disc centre, at any angle) in the bottom-left corner instead.

        Only point-anchored kinds route through here. `rule` and `band` are
        genuinely different geometry on a disc — a theta rule is a spoke, an r
        rule is a ring, a band is an annulus or a sector — and stay deferred
        (polar-axes.md §9) rather than being drawn as straight cartesian bars.
        """
        if polar is not None:
            px, py = polar(x, y)
            return float(px), float(py)
        return float(sx(x)), float(sy(y))

    for ann in annotations:
        style = ann.get("style") or {}
        # SHAPE paint (rule strokes, band fills, arrows, markers) keeps its own
        # neutral default — only the LABEL falls back to the theme text colour,
        # which is what the client's
        # var(--chart-annotation-text, var(--chart-text, inherit)) governs.
        # Widening this to shapes diverged SVG from the raster and the client.
        color = escape(_css(style.get("color"), "#667085"))
        opacity = float(style.get("opacity", 1.0))
        start = max(0.0, min(1.0, float(style.get("span_start", 0.0))))
        end = max(start, min(1.0, float(style.get("span_end", 1.0))))
        kind = ann.get("kind")
        if kind == "rule":
            if ann.get("axis") == "x":
                pos = float(sx(float(ann["value"])))
                coords = (pos, py0 + (1 - end) * plot["h"], pos, py0 + (1 - start) * plot["h"])
            else:
                pos = float(sy(float(ann["value"])))
                coords = (px0 + start * plot["w"], pos, px0 + end * plot["w"], pos)
            marks.append(
                f'<line x1="{_num(coords[0])}" y1="{_num(coords[1])}" '
                f'x2="{_num(coords[2])}" y2="{_num(coords[3])}" stroke="{color}" '
                f'stroke-width="{_num(float(style.get("width", 1.5)))}" stroke-opacity="{_num(opacity)}"'
                f"{_dash_attr(style)}/>"
            )
        elif kind == "band":
            a, b = float(ann["start"]), float(ann["end"])
            if ann.get("axis") == "x":
                x0, x1 = sorted((float(sx(a)), float(sx(b))))
                y0, y1 = py0 + (1 - end) * plot["h"], py0 + (1 - start) * plot["h"]
            else:
                y0, y1 = sorted((float(sy(a)), float(sy(b))))
                x0, x1 = px0 + start * plot["w"], px0 + end * plot["w"]
            marks.append(
                f'<rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(x1 - x0)}" '
                f'height="{_num(y1 - y0)}" fill="{color}" fill-opacity="{_num(float(style.get("opacity", 0.14)))}"/>'
            )
        elif kind in ("arrow", "callout"):
            connector_marks = (
                unclipped_marks
                if _annotation_connector_unclipped(ann, sx, sy, plot, polar)
                else marks
            )
            if kind == "arrow":
                x0, y0 = point(float(ann["x0"]), float(ann["y0"]))
                x1, y1 = point(float(ann["x1"]), float(ann["y1"]))
            else:  # pointer from the offset label back to the data point
                x1, y1 = point(float(ann["x"]), float(ann["y"]))
                x0, y0 = x1 + float(ann.get("dx", 0.0)), y1 + float(ann.get("dy", 0.0))
            if all(np.isfinite(v) for v in (x0, y0, x1, y1)):
                shapes = _arrow_shapes(x0, y0, x1, y1, style)
                stroke_width = _num(max(0.5, float(style.get("width", 1.5))))
                if shapes["taper"] is not None:
                    taper = " ".join(f"{_num(px)},{_num(py)}" for px, py in shapes["taper"])
                    connector_marks.append(
                        f'<polygon points="{taper}" fill="{color}" fill-opacity="{_num(opacity)}"/>'
                    )
                else:
                    shaft = " ".join(f"{_num(px)},{_num(py)}" for px, py in shapes["shaft"])
                    connector_marks.append(
                        f'<polyline points="{shaft}" fill="none" '
                        f'stroke="{color}" stroke-width="{stroke_width}" '
                        f'stroke-opacity="{_num(opacity)}"{_dash_attr(style)}/>'
                    )
                for decoration in (shapes["head"], shapes["tail"]):
                    if decoration is None:
                        continue
                    points = " ".join(f"{_num(px)},{_num(py)}" for px, py in decoration["points"])
                    if decoration["kind"] == "fill":
                        connector_marks.append(
                            f'<polygon points="{points}" fill="{color}" '
                            f'fill-opacity="{_num(opacity)}"/>'
                        )
                    else:
                        connector_marks.append(
                            f'<polyline points="{points}" fill="none" stroke="{color}" '
                            f'stroke-width="{stroke_width}" stroke-opacity="{_num(opacity)}"/>'
                        )
        elif kind == "marker":
            mx, my = point(float(ann["x"]), float(ann["y"]))
            if all(np.isfinite(v) for v in (mx, my)):
                radius = max(0.5, float(ann.get("size", 8.0)) / 2.0)
                builder = _SYMBOL_BUILDERS.get(str(ann.get("symbol", "circle")))
                stroke_w = float(style.get("stroke_width", 0.0))
                stroke_attr = (
                    f' stroke="{escape(_css(style.get("stroke_color"), color))}"'
                    f' stroke-width="{_num(stroke_w)}"'
                    + (f' stroke-opacity="{_num(opacity)}"' if opacity < 1 else "")
                    if stroke_w
                    else ""
                )
                fill = escape(_css(style.get("color"), "#2563eb"))
                shape = (
                    f'<circle cx="{_num(mx)}" cy="{_num(my)}" r="{_num(radius)}"'
                    if builder is None
                    else builder(mx, my, radius)
                )
                marks.append(f'{shape} fill="{fill}" fill-opacity="{_num(opacity)}"{stroke_attr}/>')
        if ann.get("text"):
            tx, ty, label_anchor, vertical_align = annotation_label_placement(
                ann, style, sx, sy, plot, width, height, polar
            )
            if not (np.isfinite(tx) and np.isfinite(ty)):
                continue
            style = {**style, "vertical_align": vertical_align} if vertical_align else style
            anchor = {"start": "start", "middle": "middle", "end": "end"}.get(label_anchor, "start")
            font_size = _px_size(style.get("font_size"), 11.0)
            lines = str(ann["text"]).splitlines() or [""]
            line_height = font_size * 1.2
            rotation = float(style.get("rotation", 0.0)) % 360.0
            if rotation in (90.0, 270.0):
                # Vertical text, mirroring the native rasterizer's geometry:
                # vertical_align anchors along the reading axis, the horizontal
                # anchor shifts the baseline across the post-rotation box.
                cw = rotation == 270.0
                va = str(style.get("vertical_align", ""))
                along = {
                    "center": "middle",
                    "top": "start" if cw else "end",
                    "bottom": "end" if cw else "start",
                }.get(va, "start")
                ascent, descent = font_size * 0.78, font_size * 0.22
                if cw:
                    base = {"middle": (descent - ascent) / 2, "end": -ascent}.get(anchor, descent)
                else:
                    base = {"middle": (ascent - descent) / 2, "end": -descent}.get(anchor, ascent)
                stack = -line_height if cw else line_height  # later lines: glyph-down
                by = ty + float(ann.get("dy", 0))
                text_opacity = float(
                    style.get(
                        "label_opacity",
                        style.get("opacity", 1.0) if kind == "text" else 1.0,
                    )
                )
                line_offset = 0
                for index, line in enumerate(lines):
                    bx = tx + float(ann.get("dx", 0)) + base + index * stack
                    styled_line = _svg_mathtext_spans(line, style, line_offset)
                    labels.append(
                        f'<text text-anchor="{along}" font-size="{_num(font_size)}" '
                        f'transform="rotate({90 if cw else -90} {_num(bx)} {_num(by)})" '
                        f'x="{_num(bx)}" y="{_num(by)}" '
                        + (f'fill-opacity="{_num(text_opacity)}" ' if text_opacity < 1 else "")
                        + f'fill="{color}">{styled_line}</text>'
                    )
                    line_offset += len(line) + 1
                continue
            x_text = tx + float(ann.get("dx", 0))
            vertical_align = style.get("vertical_align")
            y_text = _annotation_first_baseline(
                ty + float(ann.get("dy", 0)),
                len(lines),
                line_height,
                font_size,
                vertical_align,
            )
            line_offset = 0
            tspan_parts = []
            for index, line in enumerate(lines):
                styled_line = _svg_mathtext_spans(line, style, line_offset)
                tspan_parts.append(
                    f'<tspan x="{_num(x_text)}" y="{_num(y_text + index * line_height)}">'
                    f"{styled_line}</tspan>"
                )
                line_offset += len(line) + 1
            tspans = "".join(tspan_parts)
            text_opacity = float(
                style.get(
                    "label_opacity",
                    style.get("opacity", 1.0) if kind == "text" else 1.0,
                )
            )
            # A callout's `color` paints its arrow; the label prefers its own,
            # then the theme text colour (the client resolves the same chain
            # through var(--chart-annotation-text, var(--chart-text, …))).
            label_color = (
                escape(_css(style.get("label_color"), ""))
                or (escape(_css(style.get("color"), "")) if style.get("color") else "")
                or escape(default_text)
            )
            labels.extend(
                _svg_text_box(style, lines, x_text, y_text, line_height, font_size, anchor)
            )
            font_attrs = _svg_font_attrs(style)
            rotation_attr = (
                f' transform="rotate({_num(-rotation)} {_num(x_text)} {_num(y_text)})"'
                if rotation
                else ""
            )
            labels.append(
                f'<text text-anchor="{anchor}" font-size="{_num(font_size)}"{font_attrs}'
                f"{rotation_attr} "
                + (f'fill-opacity="{_num(text_opacity)}" ' if text_opacity < 1 else "")
                + f'fill="{label_color}">{tspans}</text>'
            )
    return marks, unclipped_marks, labels


def _svg_font_attrs(style: dict[str, Any]) -> str:
    attrs = []
    for key, attribute in (
        ("font_family", "font-family"),
        ("font_weight", "font-weight"),
        ("font_style", "font-style"),
    ):
        if style.get(key) is not None:
            attrs.append(f' {attribute}="{escape(str(style[key]))}"')
    return "".join(attrs)


def _svg_mathtext_spans(line: str, style: dict[str, Any], offset: int) -> str:
    ranges: list[tuple[int, int]] = []
    for item in str(style.get("math_italic_ranges", "")).split(","):
        try:
            start, end = (int(value) for value in item.split(":", 1))
        except ValueError:
            continue
        start, end = max(0, start - offset), min(len(line), end - offset)
        if start < end:
            ranges.append((start, end))
    if not ranges:
        return escape(line)
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = previous_start, max(previous_end, end)
        else:
            merged.append((start, end))
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        start = max(start, cursor)
        if start >= end:
            continue
        if cursor < start:
            out.append(escape(line[cursor:start]))
        out.append(f'<tspan font-style="italic">{escape(line[start:end])}</tspan>')
        cursor = end
    out.append(escape(line[cursor:]))
    return "".join(out)


def _svg_text_box(
    style: dict[str, Any],
    lines: list[str],
    x: float,
    first_y: float,
    line_height: float,
    font_size: float,
    anchor: str,
) -> list[str]:
    """SVG counterpart of the pyplot text-bbox CSS approximation."""
    background = style.get("background")
    border = str(style.get("border", ""))
    if background is None and not border:
        return []
    pad_parts = str(style.get("padding", "0")).split()

    def px(value: str) -> float:
        try:
            return max(0.0, float(value.removesuffix("px")))
        except ValueError:
            return 0.0

    pad_y = px(pad_parts[0]) if pad_parts else 0.0
    pad_x = px(pad_parts[1]) if len(pad_parts) > 1 else pad_y
    text_width = _estimated_text_width(lines, font_size)
    left = (
        x
        - (text_width / 2 if anchor == "middle" else text_width if anchor == "end" else 0.0)
        - pad_x
    )
    top = first_y - font_size * 0.8 - pad_y
    height = font_size + (len(lines) - 1) * line_height + pad_y * 2
    fill = "none" if background is None else escape(str(background))
    stroke = "none"
    stroke_width = 0.0
    if border:
        parts = border.split()
        stroke = escape(parts[-1])
        try:
            stroke_width = max(0.0, float(parts[0].removesuffix("px")))
        except (IndexError, ValueError):
            stroke_width = 1.0
    # `boxstyle="round"`/`round4` set border_radius; the browser gets it as CSS
    # border-radius, so the exporters have to round the same corners or an
    # exported box is square where the live one is not.
    radius = _box_corner_radius(style, text_width + pad_x * 2, height)
    radius_attr = f' rx="{_num(radius)}"' if radius > 0 else ""
    return [
        f'<rect x="{_num(left)}" y="{_num(top)}" '
        f'width="{_num(text_width + pad_x * 2)}" height="{_num(height)}"{radius_attr} '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{_num(stroke_width)}"/>'
    ]


def _box_corner_radius(style: dict[str, Any], width: float, height: float) -> float:
    """`border_radius` in px, clamped to the box like CSS does.

    Shared by the SVG and native raster text-box emitters so an exported
    ``boxstyle="round"`` bbox is rounded exactly once, the same way.
    """
    try:
        radius = float(str(style.get("border_radius", 0) or 0).removesuffix("px"))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(radius, width / 2.0, height / 2.0))


def _fontmetrics_text_width(
    value: Any,
    font_size: float,
    *,
    missing_advance: float,
) -> float:
    """Embedded-face advance with a conservative fallback for unknown glyphs."""
    text = str(value)
    missing = sum(
        1
        for char in text
        if not (
            _fontmetrics.FIRST <= ord(char) <= _fontmetrics.LAST
            or ord(char) in _fontmetrics.EXTRA_ADVANCES
        )
    )
    embedded_fallback = font_size * _fontmetrics.EXTRA_ADVANCES[0xFFFD] / _fontmetrics.BASE_PX
    # The generated metrics now include the visible U+FFFD replacement advance
    # for every unknown codepoint. Only add room when a caller deliberately
    # requests a wider fallback; adding the full fallback again would double
    # count every unsupported glyph.
    extra = max(0.0, float(missing_advance) - embedded_fallback)
    return _fontmetrics.advance(text, font_size) + missing * extra


def _estimated_text_width(lines: list[str], font_size: float) -> float:
    """Measured label-box width using the embedded DejaVu face.

    The native rasterizer blits the same generated face metrics, and DejaVu is
    also the default SVG/Matplotlib face. The generated metrics reserve the
    visible U+FFFD replacement advance for each unsupported codepoint.
    """
    return max(
        (_fontmetrics_text_width(line, font_size, missing_advance=font_size) for line in lines),
        default=0.0,
    )


def _segment_marks(
    t: dict[str, Any],
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    color: str,
    polar: "Optional[_PolarProjection]" = None,
) -> str:
    x0 = _column(blob, cols[t["x0"]])
    x1 = _column(blob, cols[t["x1"]])
    y0 = _column(blob, cols[t["y0"]])
    y1 = _column(blob, cols[t["y1"]])
    n = len(x0)

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    intrinsic = _trace_paint_rgba(t, "color", n, color, read)
    colors = _paint.effective_rgba(intrinsic, t, read, component="stroke", default_opacity=1.0)
    widths = _paint.style_values(t, "width", n, read, float(style.get("width", 1.2)))
    paint = t.get("color") or {}
    plain_css = _css(paint.get("color"), color)
    # Only an opaque constant color may pass through verbatim: a translucent
    # CSS constant already contributes its alpha to stroke-opacity through
    # effective_rgba, so repeating it inside stroke= would apply it twice.
    constant_paint = paint.get("mode") in {None, "constant"} and _paint_rgba8(plain_css)[3] == 255
    css_paint = escape(plain_css)
    if polar is None:
        px0, py0 = sx(x0), sy(y0)
        px1, py1 = sx(x1), sy(y1)
        keep = np.ones(n, dtype=bool)
    else:
        # Clip each independent segment jointly in radial *scale coordinates*.
        # Clamping endpoints independently bends a diagonal error bar along the
        # ring; interpolating theta at the two intersections preserves its
        # authored chord and mirrors SEGMENT_VS.
        c0 = np.asarray(polar.r_scale.coord(y0), dtype=np.float64)
        c1 = np.asarray(polar.r_scale.coord(y1), dtype=np.float64)
        lo = min(polar.r_lo_coord, polar.r_hi_coord)
        hi = max(polar.r_lo_coord, polar.r_hi_coord)
        finite = np.isfinite(x0) & np.isfinite(x1) & np.isfinite(c0) & np.isfinite(c1)
        keep = finite & (np.maximum(c0, c1) >= lo) & (np.minimum(c0, c1) <= hi)
        dr = c1 - c0
        ta = np.zeros(n, dtype=np.float64)
        tb = np.ones(n, dtype=np.float64)
        moving = np.abs(dr) > 1e-30
        ta[moving] = (lo - c0[moving]) / dr[moving]
        tb[moving] = (hi - c0[moving]) / dr[moving]
        t0 = np.maximum(0.0, np.minimum(ta, tb))
        t1 = np.minimum(1.0, np.maximum(ta, tb))
        clipped_x0 = x0 + (x1 - x0) * t0
        clipped_x1 = x0 + (x1 - x0) * t1
        clipped_c0 = np.clip(c0 + dr * t0, lo, hi)
        clipped_c1 = np.clip(c0 + dr * t1, lo, hi)
        clipped_y0 = polar.r_scale.value(clipped_c0)
        clipped_y1 = polar.r_scale.value(clipped_c1)
        keep &= polar.theta_visible_mask(clipped_x0)
        keep &= polar.theta_visible_mask(clipped_x1)
        px0, py0 = polar(clipped_x0, clipped_y0)
        px1, py1 = polar(clipped_x1, clipped_y1)
    return "".join(
        f'<line x1="{_num(float(px0[i]))}" y1="{_num(float(py0[i]))}" '
        f'x2="{_num(float(px1[i]))}" y2="{_num(float(py1[i]))}" '
        f'stroke="{css_paint if constant_paint else f"rgb({round(colors[i, 0] * 255)},{round(colors[i, 1] * 255)},{round(colors[i, 2] * 255)})"}" '
        f'stroke-opacity="{_num(float(colors[i, 3]))}" '
        f'stroke-width="{_num(float(widths[i]))}" fill="none" stroke-linecap="round"'
        f"{_dash_attr(style)}/>"
        for i in range(len(x0))
        if keep[i]
    )


#: Markers per emitted string block. One SVG element per point means the mark
#: list is the document, and a list of N short strings costs ~50 bytes of object
#: header each on top of the markup — 40% overhead at 100k points, live at the
#: same time as the joined result. Collapsing every block keeps the per-object
#: overhead bounded while staying a single linear pass (byte-identical output:
#: concatenation is associative).
_SVG_MARK_BLOCK = 4096


def _authored_marker_path_d(
    marker_path: dict[str, Any], cx: float, cy: float, diameter: float
) -> str:
    parts: list[str] = []
    for contour in marker_path.get("contours") or ():
        values = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
        if not len(values):
            continue
        points = [(cx + diameter * float(x), cy - diameter * float(y)) for x, y in values]
        parts.append(f"M {_num(points[0][0])} {_num(points[0][1])}")
        parts.extend(f"L {_num(x)} {_num(y)}" for x, y in points[1:])
        if bool(marker_path.get("filled", True)):
            parts.append("Z")
    return " ".join(parts)


def _scatter_marks(
    t: dict,
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    fallback: str,
    polar: "Optional[_PolarProjection]" = None,
) -> list[str]:
    xv = _column(blob, cols[t["x"]])
    yv = _column(blob, cols[t["y"]])
    # Only the centres move under polar; the marker glyphs are pixel-space
    # around each centre and stay round. Out-of-range radii are culled like
    # the client shader culls them — below r_lo a point mirrors through the
    # centre INSIDE the disc, where no clip can save it.
    px, py = polar(xv, yv) if polar is not None else (sx(xv), sy(yv))
    visible = polar.position_mask(xv, yv) if polar is not None else None
    n = len(xv)

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    face_intrinsic = _trace_paint_rgba(t, "color", n, fallback, read)
    scalar_artist = style.get("artist_alpha")
    grouped_alpha = scalar_artist is not None and not (t.get("channels") or {}).get("artist_alpha")
    effective_trace = t
    if grouped_alpha:
        face_intrinsic[:, 3] = 1.0
        effective_trace = dict(t)
        effective_style = dict(style)
        effective_style.pop("artist_alpha", None)
        effective_style["opacity"] = 1.0
        effective_style["fill_opacity"] = 1.0
        effective_style["stroke_opacity"] = 1.0
        effective_trace["style"] = effective_style
    face_rgba = _paint.effective_rgba(
        face_intrinsic, effective_trace, read, component="fill", default_opacity=0.8
    )
    face_channel = t.get("color") or {}
    face_css = _css(face_channel.get("color"), fallback)
    face_css_constant = (
        face_channel.get("mode") in {None, "constant"} and _paint_rgba8(face_css)[3] == 255
    )

    size_ch = t.get("size") or {}
    if size_ch.get("mode") == "continuous":
        sv = _column(blob, cols[size_ch["buf"]])
        r0, r1 = size_ch.get("range_px", [2, 18])
        radii = (r0 + (r1 - r0) * np.clip(sv, 0, 1)) / 2
    else:
        radii = np.full(n, float(size_ch.get("size", 4.0)) / 2)

    stroke_widths = _paint.style_values(t, "stroke_width", n, read, 0.0)
    symbols = _symbol_names(t, n, read, str(style.get("symbol", "circle")))
    if (t.get("stroke") or {}).get("mode") == "match_fill":
        stroke_source = face_intrinsic.copy()
        stroke_css = face_css
        stroke_css_constant = face_css_constant
    elif t.get("stroke") is not None:
        stroke_source = _trace_paint_rgba(t, "stroke", n, fallback, read)
        stroke_css = _css((t.get("stroke") or {}).get("color"), style.get("stroke") or face_css)
        stroke_css_constant = (t.get("stroke") or {}).get("mode") in {
            None,
            "constant",
        } and _paint_rgba8(stroke_css)[3] == 255
    elif style.get("stroke") is not None:
        stroke_css = _css(style.get("stroke"), face_css)
        stroke_source = np.tile(
            np.asarray(_paint_rgba8(stroke_css), dtype=np.float64) / 255.0, (n, 1)
        )
        stroke_css_constant = _paint_rgba8(stroke_css)[3] == 255
    else:
        stroke_source = face_intrinsic.copy()
        stroke_css = face_css
        stroke_css_constant = face_css_constant
    stroke_rgba = _paint.effective_rgba(
        stroke_source, effective_trace, read, component="stroke", default_opacity=0.8
    )
    marker_path = style.get("marker_path")
    marker_glyph = style.get("marker_glyph")
    if grouped_alpha:
        fill_group = float(scalar_artist) * _fill_opacity(style, 1.0)
        stroke_group = float(scalar_artist) * _stroke_opacity(style, 1.0)
        blocks = [f'<g fill-opacity="{_num(fill_group)}" stroke-opacity="{_num(stroke_group)}">']
    else:
        blocks = ["<g>"]
    out: list[str] = []
    for i in range(n):
        if visible is not None and not visible[i]:
            continue
        fill = face_rgba[i]
        fill_value = (
            escape(face_css)
            if face_css_constant
            else f"rgb({round(fill[0] * 255)},{round(fill[1] * 255)},{round(fill[2] * 255)})"
        )
        fill_attr = f' fill="{fill_value}"' + (
            f' fill-opacity="{_num(float(fill[3]))}"' if float(fill[3]) < 1.0 else ""
        )
        symbol = symbols[i]
        builder = _SYMBOL_BUILDERS.get(symbol)
        authored_line = bool(marker_path) and not bool(marker_path.get("filled", True))
        line_symbol = (
            symbol
            in {
                "plus_line",
                "x_line",
                "horizontal_line",
                "vertical_line",
            }
            or authored_line
        )
        stroke_w = float(stroke_widths[i])
        if line_symbol and stroke_w <= 0:
            stroke_w = 1.0
        stroke_color = stroke_rgba[i]
        stroke_value = (
            fill_value
            if authored_line
            else escape(stroke_css)
            if stroke_css_constant
            else f"rgb({round(stroke_color[0] * 255)},{round(stroke_color[1] * 255)},{round(stroke_color[2] * 255)})"
        )
        stroke_attr = (
            f' stroke="{stroke_value}"'
            + (
                f' stroke-opacity="{_num(float(stroke_color[3]))}"'
                if float(stroke_color[3]) < 1.0
                else ""
            )
            + f' stroke-width="{_num(stroke_w)}"'
            if stroke_w > 0 or line_symbol
            else ""
        )
        # `size` includes the edge; SVG strokes are centered on the path.
        marker_radius = max(0.0, float(radii[i]) - stroke_w / 2)
        if marker_glyph:
            out.append(
                f'<text x="{_num(px[i])}" y="{_num(py[i])}" '
                f'font-family="DejaVu Sans" font-size="{_num(2 * marker_radius)}" '
                f'text-anchor="middle" dominant-baseline="central"'
                f"{fill_attr}{stroke_attr}>{escape(str(marker_glyph))}</text>"
            )
        elif marker_path:
            d = _authored_marker_path_d(marker_path, float(px[i]), float(py[i]), 2 * marker_radius)
            authored_fill = fill_attr if bool(marker_path.get("filled", True)) else ' fill="none"'
            out.append(f'<path d="{d}"{authored_fill}{stroke_attr}/>')
        elif builder is None:
            out.append(
                f'<circle cx="{_num(px[i])}" cy="{_num(py[i])}" r="{_num(marker_radius)}"'
                f"{fill_attr}{stroke_attr}/>"
            )
        else:
            out.append(
                builder(float(px[i]), float(py[i]), marker_radius) + f"{fill_attr}{stroke_attr}/>"
            )
        if len(out) >= _SVG_MARK_BLOCK:
            blocks.append("".join(out))
            out.clear()
    if out:
        blocks.append("".join(out))
    blocks.append("</g>")
    return blocks


_SYMBOL_NAMES = (
    "circle",
    "square",
    "diamond",
    "triangle",
    "cross",
    "hexagon",
    "pentagon",
    "star",
    "triangle_down",
    "triangle_left",
    "triangle_right",
    "x",
    "point",
    "pixel",
    "thin_diamond",
    "plus_line",
    "x_line",
    "horizontal_line",
    "vertical_line",
)


def _symbol_names(
    trace: dict[str, Any], n: int, read: _paint.ColumnReader, fallback: str
) -> list[str]:
    channel = (trace.get("channels") or {}).get("symbol")
    if channel is None:
        return [fallback] * n
    codes = np.asarray(read(int(channel["buf"])), dtype=np.uint8)[:n]
    return [
        _SYMBOL_NAMES[int(code)] if int(code) < len(_SYMBOL_NAMES) else fallback for code in codes
    ]


def _trace_paint_rgba(
    trace: dict[str, Any],
    key: str,
    n: int,
    fallback: str,
    read: _paint.ColumnReader,
) -> np.ndarray:
    """Resolve one payload paint channel to intrinsic float RGBA."""
    channel = trace.get(key) or {}
    direct = _paint.direct_rgba(channel, n, read)
    if direct is not None:
        return direct
    rgba = np.empty((n, 4), dtype=np.float64)
    rgba[:, 3] = 1.0
    mode = channel.get("mode")
    if mode == "continuous":
        rgba[:, :3] = _lut(channel.get("colormap", "viridis"), read(channel["buf"])[:n]) / 255.0
    elif mode == "categorical":
        codes = np.asarray(read(channel["buf"]), dtype=np.int64)[:n]
        palette = channel.get("palette") or DEFAULT_PALETTE
        # Per-index resolution (channels.palette_rows_rgba8), not _paint_rgba8
        # per entry: browser-only entries must degrade to DISTINCT built-in
        # colors, or every var() category exports as the same fallback blue.
        from . import channels as _channels

        table = _channels.palette_rows_rgba8(palette, len(palette)).astype(np.float64) / 255.0
        rgba[:] = table[codes % len(table)]
    else:
        rgba[:] = (
            np.asarray(_paint_rgba8(_css(channel.get("color"), fallback)), dtype=np.float64) / 255.0
        )
    return rgba


# The hexagon ring around a hexbin cell center, as fractions of the cell
# pitch (style hex_dx/hex_dy). Shared by the SVG and raster exporters; the JS
# client mirrors it in _buildHexbinMark (js/src/50_chartview.ts) — keep them
# in sync.
HEX_RING = (
    (0.0, -1.0 / 3.0),
    (0.5, -1.0 / 6.0),
    (0.5, 1.0 / 6.0),
    (0.0, 1.0 / 3.0),
    (-0.5, 1.0 / 6.0),
    (-0.5, -1.0 / 6.0),
)


def hexbin_ring(style: dict) -> tuple[np.ndarray, np.ndarray]:
    """Data-space hexagon vertex offsets (6) for a hexbin trace's cell pitch."""
    ring = np.asarray(HEX_RING, dtype=np.float64)
    return ring[:, 0] * float(style.get("hex_dx", 0.0)), ring[:, 1] * float(
        style.get("hex_dy", 0.0)
    )


def _mesh_fills(t: dict, blob: bytes, cols: list, n: int, fallback: str) -> list[str]:
    """Per-mark CSS fill colors from a trace's color channel (n marks)."""
    color_ch = t.get("color") or {}
    mode = color_ch.get("mode")
    if mode == "continuous":
        values = _column(blob, cols[color_ch["buf"]])[:n]
        rgb = _lut(color_ch.get("colormap", "viridis"), values)
        return [f"rgb({r},{g},{b})" for r, g, b in rgb]
    if mode == "categorical":
        codes = _column(blob, cols[color_ch["buf"]])[:n].astype(int)
        palette = color_ch.get("palette") or DEFAULT_PALETTE
        return [palette[code % len(palette)] for code in codes]
    return [_css(color_ch.get("color"), fallback)] * n


def _hexbin_marks(
    t: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, fallback: str
) -> str:
    """One hexagon polygon per cell, expanded locally from shipped centers."""
    cx = _column(blob, cols[t["x"]])
    cy = _column(blob, cols[t["y"]])
    n = min(len(cx), len(cy))
    fills = _mesh_fills(t, blob, cols, n, fallback)
    ring_x, ring_y = hexbin_ring(style)
    xs = np.asarray(sx(cx[:n, None] + ring_x[None, :]), dtype=np.float64)
    ys = np.asarray(sy(cy[:n, None] + ring_y[None, :]), dtype=np.float64)
    fill_op = _fill_opacity(style)
    group_attr = (
        f' fill-opacity="{_num(fill_op)}" stroke-opacity="{_num(fill_op)}"' if fill_op < 1 else ""
    )
    out = [f"<g{group_attr}>"]
    for i in range(n):
        points = " ".join(
            f"{_num(float(x))},{_num(float(y))}" for x, y in zip(xs[i], ys[i], strict=True)
        )
        paint = escape(fills[i])
        # Matplotlib's default ``edgecolors="face"`` covers antialiasing
        # cracks where adjacent hexagons meet. A same-color hairline preserves
        # the face color while preventing white striping in vector viewers.
        out.append(
            f'<polygon points="{points}" fill="{paint}" stroke="{paint}" '
            'stroke-width="0.5" stroke-linejoin="round"/>'
        )
    out.append("</g>")
    return "".join(out)


def _ribbon_marks(
    t: dict,
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    fallback: str,
    svg: "_Svg",
) -> str:
    """Flow bands as one `<path>` each: exact cubics, gradient along the flow.

    A single path per band, never a mesh — the seam-free mesh route requires one
    uniform colour, which is exactly what a two-ended ribbon is not (see the
    ribbon geometry contract). When both ends resolve to the same paint the
    band gets a plain `fill=` rather than a one-colour gradient, so an ordinary
    Sankey stays small.
    """
    x0v = _column(blob, cols[t["x0"]])
    x1v = _column(blob, cols[t["x1"]])
    slo = _column(blob, cols[t["y0"]])
    shi = _column(blob, cols[t["y1"]])
    tlo = _column(blob, cols[t["target_y0"]])
    thi = _column(blob, cols[t["target_y1"]])
    n = len(x0v)

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    source_rgba = _trace_paint_rgba(t, "color", n, fallback, read)
    fills = _paint.effective_rgba(source_rgba, t, read, component="fill", default_opacity=1.0)
    if t.get("color_target"):
        target_rgba = _trace_paint_rgba(t, "color_target", n, fallback, read)
        fills2 = _paint.effective_rgba(target_rgba, t, read, component="fill", default_opacity=1.0)
    else:
        fills2 = fills
    stroke_css = style.get("stroke")
    stroke_width = float(style.get("stroke_width", 0.0) or 0.0)
    stroke_op = _stroke_opacity(style)
    # An omitted stroke colour matches the band's own fill per band
    # (edgecolors="face"), so a per-band ribbon does not outline every flow in
    # one arbitrary colour. Explicit strokes stay a single declared paint.
    stroke_paint = None if stroke_css is None else escape(_css(stroke_css, fallback))

    def rgb(paint: Any) -> str:
        return f"rgb({round(paint[0] * 255)},{round(paint[1] * 255)},{round(paint[2] * 255)})"

    out: list[str] = []
    for i in range(n):
        px0, px1 = float(sx(x0v[i])), float(sx(x1v[i]))
        y_slo, y_shi = float(sy(slo[i])), float(sy(shi[i]))
        y_tlo, y_thi = float(sy(tlo[i])), float(sy(thi[i]))
        if not all(math.isfinite(v) for v in (px0, px1, y_slo, y_shi, y_tlo, y_thi)):
            continue
        # Control points at the horizontal midpoint holding each end's own y:
        # the band leaves and arrives horizontally (ribbon geometry contract).
        mid = (px0 + px1) / 2.0
        d = (
            f"M {_num(px0)} {_num(y_shi)} "
            f"C {_num(mid)} {_num(y_shi)} {_num(mid)} {_num(y_thi)} {_num(px1)} {_num(y_thi)} "
            f"L {_num(px1)} {_num(y_tlo)} "
            f"C {_num(mid)} {_num(y_tlo)} {_num(mid)} {_num(y_slo)} {_num(px0)} {_num(y_slo)} Z"
        )
        a, b = fills[i], fills2[i]
        rgb_same = all(abs(float(a[k]) - float(b[k])) < 1e-9 for k in range(3))
        # effective_rgba already folded the trace opacity into the channel
        # alpha; folding _fill_opacity in again squared it (0.4 -> 0.16).
        alpha_a, alpha_b = float(a[3]), float(b[3])
        alpha_same = abs(alpha_a - alpha_b) < 1e-9
        if rgb_same and alpha_same:
            paint = f'fill="{rgb(a)}"'
            attrs = paint + (f' fill-opacity="{_num(alpha_a)}"' if alpha_a < 1 else "")
        elif alpha_same:
            ramp = svg.gradient_vector(px0, 0.0, px1, 0.0, [(0.0, rgb(a), 1.0), (1.0, rgb(b), 1.0)])
            attrs = f'fill="{ramp}"' + (f' fill-opacity="{_num(alpha_a)}"' if alpha_a < 1 else "")
        else:
            # Differing endpoint alphas ride per-stop stop-opacity so the
            # alpha channel interpolates along the flow like the RGB channels
            # (the raster and the client already do); a path-level
            # fill-opacity would flatten both ends to the source's alpha.
            ramp = svg.gradient_vector(
                px0, 0.0, px1, 0.0, [(0.0, rgb(a), alpha_a), (1.0, rgb(b), alpha_b)]
            )
            attrs = f'fill="{ramp}"'
        if stroke_width > 0:
            paint_css = stroke_paint if stroke_paint is not None else rgb(source_rgba[i])
            # The band paint's own alpha rides the stroke stack, exactly as
            # `effective_rgba` folds it into the fill.
            edge_op = stroke_op * (1.0 if stroke_paint is not None else float(source_rgba[i][3]))
            attrs += f' stroke="{paint_css}" stroke-width="{_num(stroke_width)}" '
            if edge_op < 1:
                attrs += f'stroke-opacity="{_num(edge_op)}" '
        out.append(f'<path d="{d}" {attrs}/>')
    return "".join(out)


def _funnel_marks(
    t: dict,
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    fallback: str,
) -> str:
    """Funnel segments as one closed 4-corner `<path>` each, flat per-stage
    fill. Geometry comes from `_scene.funnel_quad` — the same reference the
    raster consumes and the golden test pins — built from the axis-mapped
    edges, so log/symlog cross axes keep the straight-in-transformed-space
    edges the client's strip draws."""
    # Deferred import: _scene itself imports the column readers from this
    # module, so a module-level import here is a load-order cycle.
    from . import _scene

    pos0 = _column(blob, cols[t["pos0"]])
    pos1 = _column(blob, cols[t["pos1"]])
    lo0 = _column(blob, cols[t["lo0"]])
    hi0 = _column(blob, cols[t["hi0"]])
    lo1 = _column(blob, cols[t["lo1"]])
    hi1 = _column(blob, cols[t["hi1"]])
    horizontal = t.get("orientation") == "horizontal"
    spos, scross = (sx, sy) if horizontal else (sy, sx)
    n = min(len(pos0), len(pos1), len(lo0), len(hi0), len(lo1), len(hi1))

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    intrinsic = _trace_paint_rgba(t, "color", n, fallback, read)
    fills = _paint.effective_rgba(intrinsic, t, read, component="fill", default_opacity=1.0)
    stroke_css = style.get("stroke")
    stroke_width = float(style.get("stroke_width", 0.0) or 0.0)
    stroke_op = _stroke_opacity(style)
    # An omitted stroke colour matches each segment's own fill
    # (edgecolors="face"), the ribbon rule: a per-stage funnel has no single
    # trace colour to outline with.
    stroke_paint = None if stroke_css is None else escape(_css(stroke_css, fallback))

    def rgb(paint: Any) -> str:
        return f"rgb({round(paint[0] * 255)},{round(paint[1] * 255)},{round(paint[2] * 255)})"

    out: list[str] = []
    for i in range(n):
        mapped = (
            float(spos(pos0[i])),
            float(spos(pos1[i])),
            float(scross(lo0[i])),
            float(scross(hi0[i])),
            float(scross(lo1[i])),
            float(scross(hi1[i])),
        )
        if not all(math.isfinite(v) for v in mapped):
            continue
        quad = _scene.funnel_quad(*mapped, horizontal)
        d = (
            f"M {_num(quad[0, 0])} {_num(quad[0, 1])} "
            f"L {_num(quad[1, 0])} {_num(quad[1, 1])} "
            f"L {_num(quad[2, 0])} {_num(quad[2, 1])} "
            f"L {_num(quad[3, 0])} {_num(quad[3, 1])} Z"
        )
        paint = fills[i]
        alpha = float(paint[3])
        attrs = f'fill="{rgb(paint)}"' + (f' fill-opacity="{_num(alpha)}"' if alpha < 1 else "")
        if stroke_width > 0:
            paint_css = stroke_paint if stroke_paint is not None else rgb(intrinsic[i])
            edge_op = stroke_op * (1.0 if stroke_paint is not None else float(intrinsic[i][3]))
            # round joins: the native rasterizer's stroke is a distance field
            # with round caps/joins by construction (src/raster.rs), so an SVG
            # miter would spike where a taper meets its neck while the PNG
            # stayed round — parity is identity, so say it explicitly.
            attrs += (
                f' stroke="{paint_css}" stroke-width="{_num(stroke_width)}"'
                ' stroke-linejoin="round" '
            )
            if edge_op < 1:
                attrs += f'stroke-opacity="{_num(edge_op)}" '
        out.append(f'<path d="{d}" {attrs}/>')
    return "".join(out)


def _triangle_mesh_marks(
    t: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, fallback: str
) -> str:
    vertices = [_column(blob, cols[t[name]]) for name in ("x0", "y0", "x1", "y1", "x2", "y2")]
    n = min(len(values) for values in vertices)

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    face = _trace_paint_rgba(t, "color", n, fallback, read)
    fills = _paint.effective_rgba(face, t, read, component="fill", default_opacity=1.0)
    if (t.get("stroke") or {}).get("mode") == "match_fill":
        stroke_face = face
    elif t.get("stroke") is not None:
        stroke_face = _trace_paint_rgba(t, "stroke", n, fallback, read)
    elif style.get("stroke") is not None:
        stroke_face = np.tile(
            np.asarray(_paint_rgba8(_css(style.get("stroke"), fallback)), dtype=np.float64) / 255.0,
            (n, 1),
        )
    else:
        stroke_face = face
    strokes = _paint.effective_rgba(stroke_face, t, read, component="stroke", default_opacity=1.0)
    stroke_widths = _paint.style_values(
        t, "stroke_width", n, read, float(style.get("stroke_width", 0.0))
    )
    x0, y0, x1, y1, x2, y2 = vertices
    if (
        style.get("joined_fill")
        and n
        and np.all(fills == fills[0])
        and np.all(stroke_widths == 0.0)
    ):
        boundary = _paint.triangle_mesh_boundary(x0, y0, x1, y1, x2, y2)
        if boundary is not None:
            points = " ".join(f"{_num(float(sx(x)))},{_num(float(sy(y)))}" for x, y in boundary)
            fill = fills[0]
            return (
                f'<polygon points="{points}" fill="rgb({round(fill[0] * 255)},'
                f'{round(fill[1] * 255)},{round(fill[2] * 255)})" '
                f'fill-opacity="{_num(float(fill[3]))}"/>'
            )
    out = ["<g>"]
    for i in range(n):
        points = " ".join(
            f"{_num(float(sx(x)))},{_num(float(sy(y)))}"
            for x, y in ((x0[i], y0[i]), (x1[i], y1[i]), (x2[i], y2[i]))
        )
        fill = fills[i]
        attrs = (
            f' fill="rgb({round(fill[0] * 255)},{round(fill[1] * 255)},'
            f'{round(fill[2] * 255)})" fill-opacity="{_num(float(fill[3]))}"'
        )
        if stroke_widths[i] > 0:
            stroke = strokes[i]
            attrs += (
                f' stroke="rgb({round(stroke[0] * 255)},{round(stroke[1] * 255)},'
                f'{round(stroke[2] * 255)})" stroke-opacity="{_num(float(stroke[3]))}" '
                f'stroke-width="{_num(float(stroke_widths[i]))}"'
            )
        out.append(f'<polygon points="{points}"{attrs}/>')
    out.append("</g>")
    return "".join(out)


def _bar_fill(style: dict, color: str, svg: _Svg, plot: dict) -> tuple[str, str]:
    fill_spec = style.get("fill")
    fill = svg.gradient(fill_spec, color, plot) if isinstance(fill_spec, dict) else escape(color)
    fill_op = _fill_opacity(style, 0.85)
    stroke_op = _stroke_opacity(style, 0.85)
    stroke_w = float(style.get("stroke_width", 0.0))
    stroke = _css(style.get("stroke"), color) if stroke_w else None
    extra = f' fill-opacity="{_num(fill_op)}"' if fill_op < 1 else ""
    if stroke:
        extra += f' stroke="{escape(stroke)}" stroke-width="{_num(stroke_w)}"'
        if stroke_op < 1:
            extra += f' stroke-opacity="{_num(stroke_op)}"'
    return fill, extra


def _corner_radii(style: dict) -> tuple[float, float]:
    cr = style.get("corner_radius", 0)
    if isinstance(cr, (list, tuple)):
        return float(cr[0]), float(cr[1])
    return float(cr or 0), float(cr or 0)


def _rect_svg_styles(
    trace: dict[str, Any],
    n: int,
    fallback: str,
    read: _paint.ColumnReader,
    style: dict[str, Any],
    svg: _Svg,
    plot: dict[str, Any],
) -> tuple[list[str], list[str], np.ndarray]:
    """Resolve per-rectangle SVG fill/stroke attributes and radii."""
    radius_channel = _paint.style_matrix(trace, "corner_radius", n, read)
    if radius_channel is None:
        tip, base = _corner_radii(style)
        radii = np.tile(np.asarray([[tip, base]], dtype=np.float64), (n, 1))
    elif radius_channel.shape[1] == 1:
        radii = np.repeat(radius_channel, 2, axis=1)
    else:
        radii = radius_channel
    if isinstance(style.get("fill"), dict):
        fill, extra = _bar_fill(style, fallback, svg, plot)
        return [fill] * n, [extra] * n, radii

    face = _trace_paint_rgba(trace, "color", n, fallback, read)
    fills_rgba = _paint.effective_rgba(face, trace, read, component="fill", default_opacity=0.85)
    if (trace.get("stroke") or {}).get("mode") == "match_fill":
        stroke_face = face
    elif trace.get("stroke") is not None:
        stroke_face = _trace_paint_rgba(trace, "stroke", n, fallback, read)
    elif style.get("stroke") is not None:
        stroke_face = np.tile(
            np.asarray(_paint_rgba8(_css(style.get("stroke"), fallback)), dtype=np.float64) / 255.0,
            (n, 1),
        )
    else:
        stroke_face = face
    strokes = _paint.effective_rgba(
        stroke_face, trace, read, component="stroke", default_opacity=0.85
    )
    widths = _paint.style_values(
        trace, "stroke_width", n, read, float(style.get("stroke_width", 0.0))
    )
    fills: list[str] = []
    extras: list[str] = []
    for fill, stroke, width in zip(fills_rgba, strokes, widths, strict=True):
        fills.append(f"rgb({round(fill[0] * 255)},{round(fill[1] * 255)},{round(fill[2] * 255)})")
        extra = f' fill-opacity="{_num(float(fill[3]))}"'
        if width > 0:
            extra += (
                f' stroke="rgb({round(stroke[0] * 255)},{round(stroke[1] * 255)},'
                f'{round(stroke[2] * 255)})" stroke-opacity="{_num(float(stroke[3]))}" '
                f'stroke-width="{_num(float(width))}"'
            )
        extras.append(extra)
    return fills, extras, radii


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
    polar: "Optional[_PolarProjection]" = None,
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

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    fills, extras, radii = _rect_svg_styles(t, len(pos), color, read, style, svg, plot)
    out = []
    if polar is not None:
        # Annular sectors. SVG has real arcs, so these are exact `A` commands
        # rather than the flattened polygons the raster path needs.
        for i in range(len(pos)):
            d = _polar_wedge_path(
                polar,
                float(pos[i]) - half,
                float(pos[i]) + half,
                float(min(v0[i], v1[i])),
                float(max(v0[i], v1[i])),
                float(np.max(radii[i])) if radii is not None and len(radii) else 0.0,
                float(style.get("wedge_gap", 0.0) or 0.0),
            )
            if d:
                out.append(f'<path d="{d}" fill="{fills[i]}"{extras[i]}/>')
        return "".join(out)
    for i in range(len(pos)):
        if horizontal:
            x0, x1 = float(sx(min(v0[i], v1[i]))), float(sx(max(v0[i], v1[i])))
            y0, y1 = float(sy(pos[i] + half)), float(sy(pos[i] - half))
        else:
            x0, x1 = float(sx(pos[i] - half)), float(sx(pos[i] + half))
            y0, y1 = float(sy(max(v0[i], v1[i]))), float(sy(min(v0[i], v1[i])))
        w, h = abs(x1 - x0), abs(y1 - y0)
        x, y = min(x0, x1), min(y0, y1)
        r_tip, r_base = radii[i]
        if r_tip or r_base:
            tip_top = not horizontal and v1[i] >= v0[i]
            d = _rounded_rect_path(x, y, w, h, r_tip, r_base, tip_top or horizontal)
            out.append(f'<path d="{d}" fill="{fills[i]}"{extras[i]}/>')
        else:
            out.append(
                f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
                f'fill="{fills[i]}"{extras[i]}/>'
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
    polar: "Optional[_PolarProjection]" = None,
) -> str:
    x0v = _column(blob, cols[t["x0"]])
    x1v = _column(blob, cols[t["x1"]])
    y0v = _column(blob, cols[t["y0"]])
    y1v = _column(blob, cols[t["y1"]])

    def read(index: int) -> np.ndarray:
        return _column(blob, cols[index])

    fills, extras, radii = _rect_svg_styles(t, len(x0v), color, read, style, svg, plot)
    out = []
    if polar is not None:
        # Four edge columns are an annular sector: (x0, x1) is the angular span
        # and (y0, y1) the radial one. This is the path unequal-width slices (a
        # pie or donut) take, since the compact bar path ships one scalar width.
        out = []
        for i in range(len(x0v)):
            d = _polar_wedge_path(
                polar,
                float(x0v[i]),
                float(x1v[i]),
                float(min(y0v[i], y1v[i])),
                float(max(y0v[i], y1v[i])),
                float(np.max(radii[i])) if radii is not None and len(radii) else 0.0,
                float(style.get("wedge_gap", 0.0) or 0.0),
            )
            if d:
                out.append(f'<path d="{d}" fill="{fills[i]}"{extras[i]}/>')
        return "".join(out)
    for i in range(len(x0v)):
        xa_, xb = float(sx(x0v[i])), float(sx(x1v[i]))
        ya_, yb = float(sy(y0v[i])), float(sy(y1v[i]))
        x, y = min(xa_, xb), min(ya_, yb)
        w, h = abs(xb - xa_), abs(yb - ya_)
        r_tip, r_base = radii[i]
        if r_tip or r_base:
            d = _rounded_rect_path(x, y, w, h, r_tip, r_base, y1v[i] >= y0v[i])
            out.append(f'<path d="{d}" fill="{fills[i]}"{extras[i]}/>')
        else:
            out.append(
                f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
                f'fill="{fills[i]}"{extras[i]}/>'
            )
    return "".join(out)


def warp_axis_indices(scale: _Scale, lo: float, hi: float, n_src: int) -> Optional[np.ndarray]:
    """Source-cell index per output cell for a *data-uniform* grid shown on a
    nonlinear axis, or None when no warp is needed (affine axis).

    A data-uniform grid (heatmap) stretched linearly between its transformed
    endpoints places every internal cell edge wrong on a log/symlog axis; the
    fix is to resample it into a grid that is uniform in scale coordinates
    (== uniform on screen), nearest-neighbor so cells stay crisp. Output
    resolution is at least the source's and at most the pixel span (capped),
    so no cell is lost and no image explodes. Shared by the SVG and native
    raster exporters. Density grids are already uniform in scale coordinates
    (§28) and must NOT be warped."""
    if scale.affine:
        return None
    c0, c1 = float(scale.coord(lo)), float(scale.coord(hi))
    if not (np.isfinite(c0) and np.isfinite(c1)) or c0 == c1:
        return None
    px_span = abs(float(scale(hi)) - float(scale(lo)))
    n_out = int(np.clip(round(px_span), n_src, 4096))
    centers = c0 + (np.arange(n_out, dtype=np.float64) + 0.5) * ((c1 - c0) / n_out)
    values = np.asarray(scale.value(centers), dtype=np.float64)
    idx = np.floor((values - lo) / (hi - lo) * n_src).astype(np.int64)
    return np.clip(idx, 0, n_src - 1)


def warp_grid_rgba(
    rgba: np.ndarray, x_range: list, y_range: list, sx: _Scale, sy: _Scale
) -> np.ndarray:
    """Resample a data-uniform (h, w, 4) grid so it is uniform in scale
    coordinates; identity on affine axes. Row 0 stays the y_range bottom."""
    h, w = rgba.shape[:2]
    cols = warp_axis_indices(sx, float(x_range[0]), float(x_range[1]), w)
    rows = warp_axis_indices(sy, float(y_range[0]), float(y_range[1]), h)
    if cols is not None:
        rgba = rgba[:, cols]
    if rows is not None:
        rgba = rgba[rows, :]
    return rgba


def _heatmap_rgba_grid(
    hm: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    style: dict[str, Any],
    borrowed: tuple[np.ndarray, ...] = (),
) -> np.ndarray:
    """Decode a heatmap as an `(h, w, 4)` uint8 grid, row 0 at the bottom."""
    w, h = int(hm["w"]), int(hm["h"])
    if "rgba_bufs" in hm:
        channels = [_column(blob, cols[index]) for index in hm["rgba_bufs"]]
        rgba = np.clip(np.column_stack(channels) * 255.0, 0, 255).astype(np.uint8)
        rgba[:, 3] = (rgba[:, 3].astype(np.float64) * _fill_opacity(style)).astype(np.uint8)
        return rgba.reshape(h, w, 4)

    meta = cols[hm["buf"]]
    if hm.get("enc") == "canonical-f64":
        values = np.asarray(borrowed[int(meta["span"]) - 1], dtype=np.float64)[: int(meta["len"])]
        d0, d1 = (float(value) for value in hm["domain"])
        values = (values - d0) / ((d1 - d0) or 1.0)
    else:
        values = _column(blob, meta)
    raw = values.reshape(h, w)
    finite = np.isfinite(raw)
    t = np.clip(np.where(finite, raw, 0.0), 0.0, 1.0)
    rgb = _lut(hm.get("colormap", "viridis"), t.reshape(-1)).reshape(h, w, 3)
    alpha = np.full((h, w), int(255 * _fill_opacity(style, 0.95)), dtype=np.uint8)
    alpha[~finite] = 0
    return np.dstack([rgb, alpha])


_POLAR_HEATMAP_MAX_DIMENSION = 4096
# Keep inverse-projection scratch well below the returned RGBA image. At the
# maximum output width this is 64 rows, so the one dense float tile is 2 MiB
# instead of the old implementation's many 128 MiB full-frame arrays.
_POLAR_HEATMAP_TILE_PIXELS = 256 * 1024


def _heatmap_sample_column(
    meta: dict[str, Any],
    indices: np.ndarray,
    blob: bytes,
    borrowed: tuple[np.ndarray, ...],
) -> np.ndarray:
    """Decode only selected rows from one heatmap source column.

    Polar inverse-raster output is screen-bounded. Expanding a source grid
    before sampling defeats that contract (and the raster payload's borrowed
    canonical-f64 path), so this helper indexes the wire/canonical storage
    first and widens only the selected values.
    """
    dtype_name = str(meta.get("dtype", "f32"))
    dtype = {"u8": np.uint8, "f32": np.dtype("<f4"), "f64": np.dtype("<f8")}.get(dtype_name)
    if dtype is None:
        raise ValueError(f"unsupported heatmap column dtype {dtype_name!r}")
    span = int(meta.get("span", 0))
    if span:
        # Do not pass dtype= here: a defensive metadata/array mismatch would
        # cast the *entire* borrowed source before we sample it, defeating the
        # source-bounded contract. Index first, then cast only selected cells.
        values = np.asarray(borrowed[span - 1]).reshape(-1)[: int(meta["len"])]
        selected = values[indices].astype(dtype, copy=False)
    else:
        values = np.frombuffer(
            blob,
            dtype=dtype,
            count=int(meta["len"]),
            offset=int(meta.get("byte_offset", 0)),
        )
        selected = values[indices]
    selected = selected.astype(np.float64, copy=False)
    return selected / (meta.get("scale") or 1.0) + meta.get("offset", 0.0)


def _heatmap_rgba_samples(
    hm: dict[str, Any],
    indices: np.ndarray,
    blob: bytes,
    cols: list[dict[str, Any]],
    style: dict[str, Any],
    borrowed: tuple[np.ndarray, ...],
) -> np.ndarray:
    """Color selected flat heatmap cells without expanding the source grid."""
    count = len(indices)
    if "rgba_bufs" in hm:
        rgba = np.empty((count, 4), dtype=np.uint8)
        for channel, column_index in enumerate(hm["rgba_bufs"]):
            values = _heatmap_sample_column(cols[column_index], indices, blob, borrowed)
            rgba[:, channel] = np.clip(values * 255.0, 0.0, 255.0).astype(np.uint8)
        rgba[:, 3] = (rgba[:, 3].astype(np.float64) * _fill_opacity(style)).astype(np.uint8)
        return rgba

    values = _heatmap_sample_column(cols[hm["buf"]], indices, blob, borrowed)
    finite = np.isfinite(values)
    if hm.get("enc") == "canonical-f64":
        d0, d1 = (float(value) for value in hm["domain"])
        # Browser payload normalization and the native Cartesian heatmap opcode
        # both round each normalized canonical value to f32 before LUT lookup.
        # Preserve that exact seam while touching only sampled source cells.
        t = np.zeros(count, dtype=np.float64)
        normalized = np.clip((values[finite] - d0) / ((d1 - d0) or 1.0), 0.0, 1.0)
        t[finite] = normalized.astype(np.float32).astype(np.float64)
    else:
        t = np.clip(np.where(finite, values, 0.0), 0.0, 1.0)
    rgb = _lut(hm.get("colormap", "viridis"), t)
    alpha = np.full(count, int(255 * _fill_opacity(style, 0.95)), dtype=np.uint8)
    alpha[~finite] = 0
    return np.column_stack((rgb, alpha))


def polar_heatmap_rgba(
    hm: dict[str, Any],
    blob: bytes,
    cols: list[dict[str, Any]],
    style: dict[str, Any],
    polar: _PolarProjection,
    borrowed: tuple[np.ndarray, ...] = (),
    *,
    output_scale: float = 1.0,
) -> np.ndarray:
    """Inverse-raster a regular heatmap into the visible annular sector.

    The returned image is top-first RGBA and covers ``polar.plot``. Each output
    pixel is inverted through the joint polar transform, then nearest-samples
    the source cell grid (whose row 0 is the radial-range bottom). This is the
    CPU twin of ``HEATMAP_FS`` and is shared by SVG and native raster export.

    Work is bounded by output pixels, not source cells: source values are
    gathered only after inverse mapping, and projection scratch is tiled.
    ``output_scale`` lets native raster export sample once per device pixel;
    SVG uses the default one sample per logical pixel.
    """
    source_w, source_h = int(hm["w"]), int(hm["h"])
    if source_w <= 0 or source_h <= 0:
        raise ValueError("polar heatmap dimensions must be positive")
    plot = polar.plot
    output_scale = float(output_scale)
    if not math.isfinite(output_scale) or output_scale <= 0.0:
        raise ValueError("polar heatmap output_scale must be positive and finite")
    out_w = max(
        1,
        min(
            _POLAR_HEATMAP_MAX_DIMENSION,
            int(math.ceil(float(plot["w"]) * output_scale)),
        ),
    )
    out_h = max(
        1,
        min(
            _POLAR_HEATMAP_MAX_DIMENSION,
            int(math.ceil(float(plot["h"]) * output_scale)),
        ),
    )
    xs = float(plot["x"]) + (np.arange(out_w, dtype=np.float64) + 0.5) * (float(plot["w"]) / out_w)
    dx = xs - polar.cx
    xr = hm["x_range"]
    yr = hm["y_range"]
    out = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    tile_rows = max(1, min(out_h, _POLAR_HEATMAP_TILE_PIXELS // out_w))
    near = float(polar.theta_value(float(xr[0])))
    inner = polar.inner_fraction
    radius = max(polar.radius, 1e-30)
    x_span = (float(xr[1]) - float(xr[0])) or 1.0
    y_span = (float(yr[1]) - float(yr[0])) or 1.0

    for row_start in range(0, out_h, tile_rows):
        row_stop = min(out_h, row_start + tile_rows)
        rows = np.arange(row_start, row_stop, dtype=np.float64)
        ys = float(plot["y"]) + (rows + 0.5) * (float(plot["h"]) / out_h)
        dy = polar.cy - ys
        normalized = np.hypot(dy[:, None], dx[None, :]) / radius
        candidate_rows, candidate_cols = np.nonzero(
            (normalized >= inner - 1e-9) & (normalized <= 1.0 + 1e-9)
        )
        if not len(candidate_rows):
            continue

        candidate_norm = normalized[candidate_rows, candidate_cols]
        angles = np.arctan2(dy[candidate_rows], dx[candidate_cols])
        theta = np.asarray(polar.theta_from_angle(angles, near=near), dtype=np.float64)
        radial = np.asarray(polar.radius_value(candidate_norm), dtype=np.float64)
        fx = (theta - float(xr[0])) / x_span
        fy = (radial - float(yr[0])) / y_span
        raw_theta = np.asarray(polar.theta_value(theta), dtype=np.float64)
        visible = (
            np.isfinite(fx)
            & np.isfinite(fy)
            & polar._angular_value_visible_mask(raw_theta)
            & (fx >= 0.0)
            & (fx <= 1.0)
            & (fy >= 0.0)
            & (fy <= 1.0)
        )
        if not bool(visible.any()):
            continue
        target_rows = candidate_rows[visible]
        target_cols = candidate_cols[visible]
        source_x = np.clip(
            np.floor(fx[visible] * source_w).astype(np.int64),
            0,
            source_w - 1,
        )
        source_y = np.clip(
            np.floor(fy[visible] * source_h).astype(np.int64),
            0,
            source_h - 1,
        )
        source_indices = source_y * source_w + source_x
        out[row_start + target_rows, target_cols] = _heatmap_rgba_samples(
            hm,
            source_indices,
            blob,
            cols,
            style,
            borrowed,
        )
    return out


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


def _physical_density_alpha(counts: Any, mean_alpha_u8: Any, style_opacity: float) -> Any:
    """Displayed alpha of a mean-color density cell (LOD doc §2 rule 1).

    The physical compositing of the cell's own points — ``1 − (1 − a_pt)^k``
    for k points whose drawn per-point alpha is ``a_pt = channel alpha ×
    style opacity`` — so the surface and real marks agree on lightness at
    every zoom. Style opacity folds INSIDE the exponent: dense cells
    saturate past it exactly like overplotted marks do. The same law as the
    client's texture upload (``lodWriteGridTexture``); shared by the SVG and
    native-raster exporters. Returns u8; empty or all-invisible cells are 0.
    """
    counts = np.asarray(counts, dtype=np.float64)
    a8 = np.asarray(mean_alpha_u8)
    a_pt = np.clip((a8.astype(np.float64) / 255.0) * float(style_opacity), 0.0, 1.0)
    coverage = np.zeros(a_pt.shape, dtype=np.float64)
    saturated = a_pt >= 1.0
    partial = ~saturated & (a_pt > 0.0)
    coverage[partial] = -np.expm1(counts[partial] * np.log1p(-a_pt[partial]))
    coverage[saturated] = 1.0
    alpha = (np.clip(coverage, 0.0, 1.0) * 255.0).astype(np.uint8)
    alpha[(counts <= 0) | (a8 == 0)] = 0
    return alpha


def _density_image(
    d: dict, blob: bytes, cols: list, sx: _Scale, sy: _Scale, style: dict, svg: _Svg
) -> str:
    w, h = int(d["w"]), int(d["h"])
    grid = _density_column(blob, cols[d["buf"]], d).reshape(h, w)
    gmax = float(d.get("max") or 1.0) or 1.0
    tnorm = np.clip(grid / gmax, 0.0, 1.0)
    if d.get("rgba") is not None:
        # Mean point color per cell (LOD doc §2): rgb from the shipped plane;
        # displayed alpha is the PHYSICAL compositing of the cell's points —
        # 1 − (1 − a_pt)^count for drawn per-point alpha a_pt = channel alpha
        # × style opacity (folded INSIDE the exponent: dense cells saturate
        # past the style opacity exactly like overplotted marks). Same law as
        # the client's texture upload.
        meta = cols[d["rgba"]]
        mean = np.frombuffer(
            blob, dtype=np.uint8, count=meta["len"], offset=meta["byte_offset"]
        ).reshape(h, w, 4)
        rgb = mean[..., :3]
        alpha = _physical_density_alpha(grid, mean[..., 3], _fill_opacity(style, 0.85))
        rgba = np.dstack([rgb, alpha])[::-1].tobytes()  # flip: PNG rows are top-first
        return _grid_image(w, h, rgba, d["x_range"], d["y_range"], sx, sy)
    paint_alpha: float = 1.0
    if d.get("color") is not None:
        red, green, blue, alpha8 = _paint_rgba8(d["color"])
        rgb = np.empty((h, w, 3), dtype=np.uint8)
        rgb[:] = (red, green, blue)
        paint_alpha = alpha8 / 255.0
    else:
        rgb = _lut(d.get("colormap", "viridis"), tnorm.reshape(-1)).reshape(h, w, 3)
    alpha = (np.clip(tnorm * 1.35, 0, 1) * 255 * _fill_opacity(style, 0.85) * paint_alpha).astype(
        np.uint8
    )
    alpha[tnorm <= 0] = 0
    rgba = np.dstack([rgb, alpha])[::-1].tobytes()  # flip: PNG rows are top-first
    return _grid_image(w, h, rgba, d["x_range"], d["y_range"], sx, sy)


def _heatmap_image(
    hm: dict,
    blob: bytes,
    cols: list,
    sx: _Scale,
    sy: _Scale,
    style: dict,
    polar: "Optional[_PolarProjection]" = None,
) -> str:
    if polar is not None:
        grid_rgba = polar_heatmap_rgba(hm, blob, cols, style, polar)
        out_h, out_w = grid_rgba.shape[:2]
        b64 = base64.b64encode(_png_rgba(out_w, out_h, grid_rgba.tobytes())).decode("ascii")
        plot = polar.plot
        return (
            f'<image data-xy-polar-heatmap="true" x="{_num(plot["x"])}" '
            f'y="{_num(plot["y"])}" width="{_num(plot["w"])}" height="{_num(plot["h"])}" '
            f'preserveAspectRatio="none" style="image-rendering:pixelated" '
            f'href="data:image/png;base64,{b64}"/>'
        )
    grid_rgba = _heatmap_rgba_grid(hm, blob, cols, style)
    # Heatmap cells are uniform in *data* space; on a nonlinear axis the image
    # must be resampled so internal cell edges land at their transformed
    # positions, not on a linear stretch between the endpoints.
    grid_rgba = warp_grid_rgba(grid_rgba, hm["x_range"], hm["y_range"], sx, sy)
    out_h, out_w = grid_rgba.shape[:2]
    rgba = grid_rgba[::-1].tobytes()
    return _grid_image(out_w, out_h, rgba, hm["x_range"], hm["y_range"], sx, sy)


# Trace kinds whose legend entry is a short line sample rather than a marker
# glyph or filled patch (mirrors _raster._LEGEND_LINE_KINDS).
_LEGEND_LINE_KINDS = frozenset({"line", "segments", "step", "stairs", "errorbar"})


_LEGEND_CHAR_WIDTH = 6.2
#: Font size the legend emitters set labels at, and the size at which
#: ``_LEGEND_CHAR_WIDTH`` is the nominal *average* advance.
_LEGEND_FONT_PX = 11.0
#: Exact-fit comparisons are made against a measured float sum, so absorb the
#: binary-float underflow at the boundary rather than ellipsizing a label that
#: fits to the last subpixel.
_LEGEND_FIT_EPS = 1e-9


def _legend_font_size(style: dict[str, Any]) -> float:
    """Resolve the bounded pixel font size used by static legend geometry."""
    value = str(style.get("fontSize", "")).strip()
    if value.endswith("px"):
        try:
            return max(1.0, float(value[:-2]))
        except ValueError:
            pass
    return 11.0


def _legend_em(style: dict[str, Any], key: str, default: float) -> float:
    value = str(style.get(key, "")).strip()
    if value.endswith("em"):
        try:
            return max(0.0, float(value[:-2]))
        except ValueError:
            pass
    return default


def _legend_text_width(value: Any, char_width: float = _LEGEND_CHAR_WIDTH) -> float:
    """Measured advance width, in pixels, of a static legend string.

    Legend columns used to be sized as ``len(text) * _LEGEND_CHAR_WIDTH``. A
    flat average cannot bound a proportional face — DejaVu's ``m`` is over
    three times the width of its ``l`` — so ``"gamma"`` really sets 42.6 px at
    11 px against a 31.0 px estimate, and a frame sized from the estimate was
    narrower than its own labels. Advances come from the same face the native
    rasterizer blits (``_fontmetrics``, generated beside ``src/font.rs`` by
    ``scripts/gen_font.py``), which is what makes a frame sized from this
    actually contain the text the SVG and raster emitters draw. It is also what
    the browser does natively, sizing each legend column to ``max-content``.

    ``char_width`` carries the nominal average advance, so scaling the legend
    font scales the measurement with it.

    A codepoint the atlas lacks reserves the nominal ``char_width`` instead of
    the rasterizer's zero advance: SVG resolves it against the viewer's own
    fonts and does paint it, and over-reserving only widens the frame, which
    can never spill a label.
    """
    font_size = char_width * (_LEGEND_FONT_PX / _LEGEND_CHAR_WIDTH)
    return _fontmetrics_text_width(value, font_size, missing_advance=char_width)


def _legend_text(value: Any, max_width: float, char_width: float = _LEGEND_CHAR_WIDTH) -> str:
    """Conservatively ellipsize a static legend string to a pixel budget.

    The budget is measured, not counted, so the returned string's own advance
    width is ``<= max_width`` and therefore fits the column it was sized for.
    """
    text = str(value)
    if _legend_text_width(text, char_width) <= max_width + _LEGEND_FIT_EPS:
        return text
    # Longest prefix that still leaves room for the ellipsis.
    keep = 0
    for index in range(1, len(text)):
        if _legend_text_width(f"{text[:index]}...", char_width) > max_width + _LEGEND_FIT_EPS:
            break
        keep = index
    if keep:
        return f"{text[:keep]}..."
    # Too narrow for even one glyph plus an ellipsis: emit the dots that fit.
    for count in (3, 2, 1):
        if _legend_text_width("." * count, char_width) <= max_width + _LEGEND_FIT_EPS:
            return "." * count
    return ""


def legend_items(traces: list[dict], palette: Sequence[str] = DEFAULT_PALETTE) -> list[dict]:
    """Legend rows for a trace list — shared by the SVG and raster exporters.

    A categorical `color=` channel is ONE trace carrying N categories, so the
    old `[t for t in traces if t.get("name")]` drew a single row bearing the
    trace's name and the trace's constant color: a legend that actively
    misdescribed the picture beside it. Expand those into one row per category,
    exactly as `ChartView._legend` does for the live client."""
    items: list[dict] = []
    for trace in traces:
        style = dict(trace.get("style") or {})
        use_trace_size = bool(style.pop("_legend_trace_size", False))
        size = trace.get("size") or {}
        if trace.get("kind") == "scatter" and use_trace_size and size.get("mode") == "constant":
            style["size"] = float(size.get("size", 8.0))
        color = trace.get("color") or {}
        if color.get("mode") == "categorical":
            categories = color.get("categories") or []
            entry_palette = list(color.get("palette") or palette) or list(palette)
            for index, category in enumerate(categories):
                item_style = dict(style)
                item_style["color"] = entry_palette[index % len(entry_palette)]
                items.append(
                    {"name": str(category), "kind": trace.get("kind"), "style": item_style}
                )
        elif trace.get("name"):
            item = dict(trace)
            item["style"] = style
            items.append(item)
    return items


def legend_clip_rect(plot: dict) -> tuple[float, float, float, float]:
    """Rect that bounds a static legend: the plot, union any polar gutter.

    A polar legend lives in a `legend_box_*` gutter OUTSIDE the plot rect
    (`_recut_polar_plot`), so clipping a legend to the plot rect alone erases it
    entirely. Union, not replacement: the same rect still bounds in-plot chrome.
    Shared so the SVG clipPath and the raster clip command cannot drift.
    """
    x0, y0 = float(plot["x"]), float(plot["y"])
    x1, y1 = x0 + float(plot["w"]), y0 + float(plot["h"])
    if "legend_box_w" in plot:
        x0 = min(x0, float(plot["legend_box_x"]))
        y0 = min(y0, float(plot["legend_box_y"]))
        x1 = max(x1, float(plot["legend_box_x"]) + float(plot["legend_box_w"]))
        y1 = max(y1, float(plot["legend_box_y"]) + float(plot["legend_box_h"]))
    return x0, y0, x1 - x0, y1 - y0


def _legend_layout(named: list[dict], plot: dict, options: dict) -> dict[str, Any]:
    """Shared bounded legend geometry for SVG and native raster exports.

    Static files cannot offer the browser legend's scrollbar, so an oversized
    legend is kept inside the plot and its labels are visibly ellipsized. A
    Columns follow Matplotlib's handle/text/column spacing and size to their
    own labels rather than inheriting the width of the longest label.

    A polar chart hands over a `legend_box_*` gutter beside the disc
    (`_recut_polar_plot`); everything below then bounds and places the legend in
    that box instead of over the marks, and `loc` chooses where within it.
    """
    if "legend_box_w" in plot:
        plot = {
            **plot,
            "x": plot["legend_box_x"],
            "y": plot["legend_box_y"],
            "w": plot["legend_box_w"],
            "h": plot["legend_box_h"],
        }
    style_opts = options.get("style") or {}
    font_size = _legend_font_size(style_opts)
    char_width = font_size * (_LEGEND_CHAR_WIDTH / 11.0)
    text_h = font_size * 1.03
    borderpad = _legend_em(style_opts, "padding", 0.4)
    labelspacing = _legend_em(style_opts, "rowGap", 0.5)
    # Matplotlib's legend dimensions are expressed in font-size units:
    # borderpad is applied on both sides, handlelength=2, handletextpad=.8,
    # columnspacing=2, and labelspacing=.5 by default.
    pad = 2.0 * borderpad * font_size
    handle = max(0.0, float(options.get("handlelength", 2.0))) * font_size
    gap = max(0.0, float(options.get("handletextpad", 0.8))) * font_size
    column_gap = 2.0 * font_size
    row_gap = labelspacing * font_size
    line_h = text_h + row_gap
    requested_handleheight = options.get("handleheight")
    swatch_h = 8.0
    if requested_handleheight is not None:
        swatch_h = max(8.0, 11.0 * float(requested_handleheight))
        line_h = max(line_h, swatch_h + 2.0)

    requested_cols = min(len(named), max(1, int(options.get("ncols", 1))))
    title = options.get("title")
    title_h = line_h if title else 0.0
    inset = 6.0
    anchor = options.get("anchor")
    # An anchored legend is positioned from ``bbox_to_anchor`` rather than
    # inset from both plot edges.  Charging it the unanchored 6 px inset on
    # both sides unnecessarily shortened otherwise fitting labels.  The
    # Matplotlib survey-gallery legend is the boundary case: its measured
    # five-column box fits the axes width, but not ``axes width - 12 px``.
    # Keep the plot-width cap so genuinely oversized static legends still
    # ellipsize instead of escaping the bounded export.
    available_w = max(
        1.0,
        float(plot["w"]) if anchor and len(anchor) in (2, 4) else float(plot["w"]) - 2 * inset,
    )
    ncols = requested_cols
    min_column_w = handle + gap + 4 * char_width
    if ncols * min_column_w + (ncols - 1) * column_gap + pad > available_w:
        # A column must at least retain its handle and a visible ellipsis.
        max_fit_cols = max(
            1,
            int(max(0.0, available_w - pad + column_gap) // (min_column_w + column_gap)),
        )
        ncols = min(ncols, max_fit_cols)

    natural_text_widths = [
        max(
            _legend_text_width(named[index].get("name", ""), char_width)
            for index in range(column, len(named), ncols)
        )
        for column in range(ncols)
    ]
    available_text_w = max(
        0.0,
        available_w - pad - ncols * (handle + gap) - (ncols - 1) * column_gap,
    )
    minimum_text_w = 4 * char_width
    text_widths = [min(width, minimum_text_w) for width in natural_text_widths]
    remaining = max(0.0, available_text_w - sum(text_widths))
    needs = [
        max(0.0, width - current)
        for width, current in zip(natural_text_widths, text_widths, strict=True)
    ]
    needed = sum(needs)
    if needed:
        scale = min(1.0, remaining / needed)
        text_widths = [
            current + need * scale for current, need in zip(text_widths, needs, strict=True)
        ]
    column_widths = [handle + gap + width for width in text_widths]
    box_w = min(available_w, sum(column_widths) + (ncols - 1) * column_gap + pad)
    if title:
        # ``pad`` is the sum of the two side pads. The previous one-sided
        # calculation expanded the box to the title's glyph width but then
        # ellipsized against ``box_w - 2 * pad`` (e.g. "Classes" -> "Cl...").
        title_w = _legend_text_width(title, char_width) + pad
        if title_w > box_w:
            extra = min(available_w - box_w, title_w - box_w)
            column_widths = [width + extra / ncols for width in column_widths]
            text_widths = [width + extra / ncols for width in text_widths]
            box_w += extra
    column_offsets = []
    cursor = pad / 2
    for width in column_widths:
        column_offsets.append(cursor)
        cursor += width + column_gap

    nrows = (len(named) + ncols - 1) // ncols
    available_h = max(1.0, float(plot["h"]) - 2 * inset)
    visible_rows = nrows
    content_rows = nrows + (1 if title else 0)
    natural_box_h = content_rows * text_h + max(0, content_rows - 1) * row_gap + pad
    if natural_box_h > available_h:
        title_room = text_h + row_gap if title else 0.0
        available_entries_h = max(0.0, available_h - pad - title_room)
        visible_rows = max(0, int((available_entries_h + row_gap) // line_h))
    visible_count = min(len(named), visible_rows * ncols)
    visible_content_rows = visible_rows + (1 if title else 0)
    box_h = min(
        available_h,
        visible_content_rows * text_h + max(0, visible_content_rows - 1) * row_gap + pad,
    )

    loc = options.get("loc") or "upper right"
    loc_tokens = set(re.split(r"[\s_-]+", loc))
    loc_is_upper = "upper" in loc or "top" in loc_tokens
    loc_is_lower = "lower" in loc or "bottom" in loc_tokens
    if anchor and len(anchor) in (2, 4):
        ax, ay = float(anchor[0]), float(anchor[1])
        aw, ah = (0.0, 0.0) if len(anchor) == 2 else (float(anchor[2]), float(anchor[3]))
        hx = 0.0 if "left" in loc else 1.0 if "right" in loc else 0.5
        vy = 0.0 if loc_is_lower else 1.0 if loc_is_upper else 0.5
        target_x = float(plot["x"]) + (ax + hx * aw) * float(plot["w"])
        target_y = float(plot["y"]) + (1.0 - ay - vy * ah) * float(plot["h"])
        x = target_x - hx * box_w
        y = target_y - (1.0 - vy) * box_h
        border_axes_pad = max(0.0, float(options.get("border_pad", 0.0)))
        x += border_axes_pad if hx == 0.0 else -border_axes_pad if hx == 1.0 else 0.0
        # SVG/raster coordinates increase downward, so a "lower" legend is
        # moved upward from its anchor and an "upper" legend moves downward.
        y += border_axes_pad if vy == 1.0 else -border_axes_pad if vy == 0.0 else 0.0
    else:
        if "left" in loc:
            x = float(plot["x"]) + inset
        elif "right" in loc:
            x = float(plot["x"]) + float(plot["w"]) - box_w - inset
        else:
            x = float(plot["x"]) + (float(plot["w"]) - box_w) / 2
        if loc_is_upper:
            y = float(plot["y"]) + inset
        elif loc_is_lower:
            y = float(plot["y"]) + float(plot["h"]) - box_h - inset
        else:
            y = float(plot["y"]) + (float(plot["h"]) - box_h) / 2
        x = min(
            max(x, float(plot["x"]) + inset),
            float(plot["x"]) + float(plot["w"]) - box_w - inset,
        )
        y = min(
            max(y, float(plot["y"]) + inset),
            float(plot["y"]) + float(plot["h"]) - box_h - inset,
        )

    return {
        "style": style_opts,
        "pad": pad,
        "handle": handle,
        "gap": gap,
        "column_gap": column_gap,
        "row_gap": row_gap,
        "font_size": font_size,
        "text_h": text_h,
        "line_h": line_h,
        "swatch_h": swatch_h,
        "ncols": ncols,
        "title": _legend_text(title, max(0.0, box_w - pad), char_width) if title else None,
        "title_h": title_h,
        "cell_w": max(column_widths),
        "column_widths": column_widths,
        "column_offsets": column_offsets,
        "box_w": box_w,
        "box_h": box_h,
        "x": x,
        "y": y,
        "visible_count": visible_count,
        "names": [
            _legend_text(t.get("name", ""), text_widths[index % ncols], char_width)
            for index, t in enumerate(named[:visible_count])
        ],
    }


def _legend(
    named: list[dict],
    plot: dict,
    options: dict,
    clip_id: str,
    text_color: str = _TEXT,
    palette: Sequence[str] = DEFAULT_PALETTE,
    label_slot: Optional[dict[str, Any]] = None,
    title_slot: Optional[dict[str, Any]] = None,
) -> str:
    label_slot = label_slot or {}
    title_slot = title_slot or {}
    legend = _legend_layout(named, plot, options)
    if not legend["visible_count"]:
        # A plot too short for even one entry: no floating frame/title either.
        return ""
    rows = []
    style_opts = legend["style"]
    pad, handle, gap = legend["pad"], legend["handle"], legend["gap"]
    line_h, ncols = legend["line_h"], legend["ncols"]
    swatch_h = legend["swatch_h"]
    title, title_h = legend["title"], legend["title_h"]
    font_size, text_h = legend["font_size"], legend["text_h"]
    column_offsets = legend["column_offsets"]
    box_w, box_h = legend["box_w"], legend["box_h"]
    x, y = legend["x"], legend["y"]
    if style_opts.get("background") != "transparent":
        if style_opts.get("boxShadow"):
            rows.append(
                f'<rect x="{_num(x + 2)}" y="{_num(y + 2)}" width="{_num(box_w)}" '
                f'height="{_num(box_h)}" rx="4" fill="black" fill-opacity="0.22"/>'
            )
        radius = "4" if style_opts.get("borderRadius") else "0"
        background_value = style_opts.get("background")
        # An explicit background is a paint, not a tint. The browser renders
        # `background:#fef3c7` opaque, so the writers must too; the
        # frame-alpha token stays the knob for the default grey frame.
        frame_alpha = style_opts.get("--xy-legend-frame-alpha")
        if frame_alpha is not None:
            alpha = float(frame_alpha)
        else:
            alpha = 0.08 if background_value is None else 1.0
        if background_value is None and alpha == 0.08:
            fill_attrs = 'fill="rgba(128,128,128,0.08)"'
        else:
            background = _css(background_value, "#808080")
            fill_attrs = f'fill="{escape(background)}" fill-opacity="{_num(alpha)}"'
        border = _css(style_opts.get("borderColor"), "#cccccc")
        rows.append(
            f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(box_w)}" height="{_num(box_h)}" '
            f'rx="{radius}" {fill_attrs} stroke="{escape(border)}" '
            f'stroke-opacity="{_num(alpha)}" stroke-width="1"/>'
        )
    if title:
        # The layout's measured size is the default; a slot may override it.
        title_size_attr = _slot_size_attr(title_slot) or f' font-size="{_num(font_size)}"'
        rows.append(
            f'<text x="{_num(x + box_w / 2)}" '
            f'y="{_num(y + pad / 2 + font_size * 0.82)}" text-anchor="middle"'
            f"{title_size_attr}"
            f"{slot_text_attrs(title_slot, font_weight='400')} "
            f'fill="{escape(slot_text_color(title_slot, text_color))}">'
            f"{escape(str(title))}</text>"
        )
    label_size_attr = _slot_size_attr(label_slot) or f' font-size="{_num(font_size)}"'
    for i, t in enumerate(named[: legend["visible_count"]]):
        style = t.get("style") or {}
        color = _css(
            style.get("color") or (t.get("color") or {}).get("color"),
            palette[i % len(palette)],
        )
        col, row = i % ncols, i // ncols
        rx, ry = x + column_offsets[col], y + pad / 2 + title_h + row * line_h
        hx0, hx1, cy = rx, rx + handle, ry + text_h / 2
        kind = t.get("kind")
        if kind == "scatter":
            rows.append(_legend_marker_svg(style, (hx0 + hx1) / 2, cy, color))
        elif kind in _LEGEND_LINE_KINDS:
            width = float(style.get("width", 1.5))
            gap_color = style.get("legend_gap_color")
            if gap_color is not None and style.get("dash"):
                rows.append(
                    f'<line x1="{_num(hx0)}" y1="{_num(cy)}" '
                    f'x2="{_num(hx1)}" y2="{_num(cy)}" '
                    f'stroke="{escape(_css(gap_color, color))}" '
                    f'stroke-width="{_num(width)}"/>'
                )
            rows.append(
                f'<line x1="{_num(hx0)}" y1="{_num(cy)}" x2="{_num(hx1)}" y2="{_num(cy)}" '
                f'stroke="{escape(color)}" stroke-width="{_num(width)}"'
                f"{_dash_attr(style)}/>"
            )
            marker = style.get("legend_marker")
            if isinstance(marker, dict):
                rows.append(_legend_marker_svg(marker, (hx0 + hx1) / 2, cy, color))
        else:
            stroke_width = max(0.0, float(style.get("stroke_width", 0.0)))
            stroke = style.get("stroke")
            stroke_attr = (
                f' stroke="{escape(_css(stroke, color))}" stroke-width="{_num(stroke_width)}"'
                if stroke is not None and stroke_width > 0.0
                else ""
            )
            rows.append(
                f'<rect x="{_num(hx0)}" y="{_num(cy - swatch_h / 2)}" '
                f'width="{handle}" height="{_num(swatch_h)}" '
                f'rx="2" fill="{escape(color)}"{stroke_attr}/>'
            )
            if style.get("hatch"):
                rows.append(
                    _legend_hatch_svg(
                        hx0,
                        hx1,
                        cy - swatch_h / 2,
                        cy + swatch_h / 2,
                        str(style["hatch"]),
                        _css(style.get("hatch_color"), "#222222"),
                    )
                )
        rows.append(
            f'<text x="{_num(hx1 + gap)}" y="{_num(ry + font_size * 0.82)}"'
            f"{label_size_attr}"
            f"{slot_text_attrs(label_slot)} "
            f'fill="{escape(slot_text_color(label_slot, text_color))}">'
            f"{escape(legend['names'][i])}</text>"
        )
    clip = "" if options.get("anchor") else f' clip-path="url(#{clip_id})"'
    return f"<g{clip}>{''.join(rows)}</g>"


def _legend_marker_svg(style: dict[str, Any], x: float, y: float, default_color: str) -> str:
    """Render one Matplotlib legend marker at the center of its line handle."""
    symbol = str(style.get("symbol", "circle"))
    builder = _SYMBOL_BUILDERS.get(symbol)
    marker_path = style.get("marker_path")
    marker_glyph = style.get("marker_glyph")
    radius = max(0.5, float(style.get("size", 8.0)) / 2.0)
    color = _css(style.get("color"), default_color)
    stroke_w = float(style.get("stroke_width", 0.0))
    line_symbol = symbol in {
        "plus_line",
        "x_line",
        "horizontal_line",
        "vertical_line",
    } or (bool(marker_path) and not bool(marker_path.get("filled", True)))
    if line_symbol and stroke_w <= 0:
        stroke_w = 1.0
    stroke = _css(style.get("stroke"), color) if stroke_w or line_symbol else None
    stroke_attr = f' stroke="{escape(stroke)}" stroke-width="{_num(stroke_w)}"' if stroke else ""
    if marker_glyph:
        return (
            f'<text x="{_num(x)}" y="{_num(y)}" '
            f'font-family="DejaVu Sans" font-size="{_num(2 * radius)}" '
            f'text-anchor="middle" dominant-baseline="central" '
            f'fill="{escape(color)}"{stroke_attr}>{escape(str(marker_glyph))}</text>'
        )
    if marker_path:
        d = _authored_marker_path_d(marker_path, float(x), float(y), 2 * radius)
        fill = escape(color) if bool(marker_path.get("filled", True)) else "none"
        return f'<path d="{d}" fill="{fill}"{stroke_attr}/>'
    if builder is None:
        return (
            f'<circle cx="{_num(x)}" cy="{_num(y)}" r="{_num(radius)}" '
            f'fill="{escape(color)}"{stroke_attr}/>'
        )
    return builder(float(x), float(y), radius) + f' fill="{escape(color)}"{stroke_attr}/>'


def _legend_hatch_svg(x0: float, x1: float, y0: float, y1: float, hatch: str, color: str) -> str:
    """Small, bounded hatch sample for explicit patch legend handles."""
    paths: list[str] = []
    shapes: list[str] = []
    mid_y = (y0 + y1) / 2
    if "-" in hatch:
        paths.append(f"M{_num(x0)},{_num(mid_y)} L{_num(x1)},{_num(mid_y)}")
    for char, direction in (("/", 1), ("\\", -1)):
        count = min(3, hatch.count(char))
        for index in range(count):
            center = x0 + (index + 1) * (x1 - x0) / (count + 1)
            half = min((x1 - x0) / 4, (y1 - y0) / 2)
            paths.append(
                f"M{_num(center - half)},{_num(mid_y + direction * half)} "
                f"L{_num(center + half)},{_num(mid_y - direction * half)}"
            )
    if "." in hatch:
        radius = min(1.1, (y1 - y0) * 0.09)
        for fraction in (0.3, 0.7):
            shapes.append(
                f'<circle cx="{_num(x0 + fraction * (x1 - x0))}" cy="{_num(mid_y)}" '
                f'r="{_num(radius)}" fill="{escape(color)}"/>'
            )
    if "*" in hatch:
        radius = min(x1 - x0, y1 - y0) * 0.28
        shapes.append(
            _star_path((x0 + x1) / 2, mid_y, radius, 5, 0.45, -90.0) + f' fill="{escape(color)}"/>'
        )
    if paths:
        shapes.insert(
            0,
            f'<path d="{" ".join(paths)}" fill="none" stroke="{escape(color)}" stroke-width="1"/>',
        )
    return "".join(shapes)


def _colorbar(
    options: dict,
    plot: dict,
    right_axis_room: float = 0.0,
    text_color: str = _TEXT,
    title_slot: Optional[dict[str, Any]] = None,
    tick_slot: Optional[dict[str, Any]] = None,
) -> str:
    title_slot = title_slot or {}
    tick_slot = tick_slot or {}
    # The `colorbar` slot's stylesheet rule is `font-size:10px`, and the raster
    # writer passes 10 explicitly. The SVG writer used to emit no size at all
    # and inherit the root <svg>'s 11px, which made it the odd renderer out on
    # every unstyled colorbar. Name the size instead of inheriting it.
    title_attrs = (
        f' font-size="{_num(slot_font_size(title_slot, COLORBAR_FONT_SIZE))}"'
        + slot_text_attrs(title_slot)
    )
    title_paint = escape(slot_text_color(title_slot, text_color))
    tick_attrs = (
        f' font-size="{_num(slot_font_size(tick_slot, COLORBAR_FONT_SIZE))}"'
        + slot_text_attrs(tick_slot)
    )
    tick_paint = escape(slot_text_color(tick_slot, text_color))
    cmap = options.get("colormap", "viridis")
    gradient_id = f"xy-colorbar-{_colormap_key(cmap)}"
    stops = _colormap_stops(cmap)
    stop_nodes = "".join(
        f'<stop offset="{100 * index / max(1, len(stops) - 1):.2f}%" '
        f'stop-color="rgb({r},{g},{b})"/>'
        for index, (r, g, b) in enumerate(stops)
    )
    orientation = options.get("orientation", "vertical")
    shrink = float(options.get("shrink", 1.0))
    anchor = options.get("anchor") or [0.5, 0.5]
    domain = options.get("domain", [0.0, 1.0])
    placement = options.get("placement")
    if placement == "axes":
        x, y, width, height = plot["x"], plot["y"], plot["w"], plot["h"]
        gradient_attrs = (
            'x1="0" y1="0" x2="100%" y2="0"'
            if orientation == "horizontal"
            else 'x1="0" y1="100%" x2="0" y2="0"'
        )
    elif orientation == "horizontal":
        width = plot["w"] * shrink
        x = plot["x"] + (plot["w"] - width) * float(anchor[0])
        gap = (
            float(options["pad"]) * plot["h"]
            if options.get("pad") is not None
            else (plot["bottom_axis_room"] or 10)
        )
        y = plot["y"] + plot["h"] + gap
        height = 18
        gradient_attrs = 'x1="0" y1="0" x2="100%" y2="0"'
    else:
        # right_axis_room shifts the whole colorbar clear of right-side named
        # y-axis chrome (layout() reserves room for both additively).
        gap = float(options["pad"]) * plot["w"] if options.get("pad") is not None else 24.0
        x = plot["x"] + plot["w"] + right_axis_room + gap
        height = plot["h"] * shrink
        y = plot["y"] + (plot["h"] - height) * (1.0 - float(anchor[1]))
        width = 18
        gradient_attrs = 'x1="0" y1="100%" x2="0" y2="0"'
    label = str(options.get("label") or "")
    label_node = (
        f'<text x="{_num(x + width + 38)}" y="{_num(y + height / 2)}" '
        f'text-anchor="middle" transform="rotate(-90 {_num(x + width + 38)} '
        f'{_num(y + height / 2)})"{title_attrs} fill="{title_paint}">{escape(label)}</text>'
        if label and orientation != "horizontal"
        else (
            f'<text x="{_num(x + width / 2)}" y="{_num(y + height + 22)}" '
            f'text-anchor="middle"{title_attrs} fill="{title_paint}">{escape(label)}</text>'
            if label
            else ""
        )
    )
    lo, hi = float(domain[0]), float(domain[1])
    log_scale = options.get("scale") == "log"

    def fraction(value: float) -> float:
        if log_scale:
            return np.log(value / lo) / np.log(hi / lo) if hi != lo else 0.0
        return (value - lo) / ((hi - lo) or 1.0)

    ticks = options.get("ticks")
    supplied_labels = options.get("tick_labels")
    paired_labels = (
        supplied_labels
        if isinstance(supplied_labels, list)
        and isinstance(ticks, list)
        and len(supplied_labels) == len(ticks)
        else None
    )
    if ticks is not None:
        tick_pairs = [
            (
                float(value),
                None if paired_labels is None else str(paired_labels[index]),
            )
            for index, value in enumerate(ticks)
            if lo <= float(value) <= hi
        ]
    else:
        automatic_positions = (
            _log_ticks(
                lo,
                hi,
                _colorbar_tick_target(width if orientation == "horizontal" else height),
            )[1]
            if log_scale
            else _linear_ticks(
                lo,
                hi,
                _colorbar_tick_target(width if orientation == "horizontal" else height),
            )[0]
        ) or [lo, hi]
        tick_pairs = [(float(value), None) for value in automatic_positions]
    tick_positions = [value for value, _label in tick_pairs]
    format_tick = _fmt_log if log_scale else lambda value: f"{value:g}"
    tick_nodes = (
        "".join(
            f'<text x="{_num(x + width + 4)}" '
            f'y="{_num(y + height * (1 - fraction(value)) + 4)}" '
            f'{tick_attrs} fill="{tick_paint}">'
            f"{escape(label if label is not None else format_tick(value))}</text>"
            for value, label in tick_pairs
        )
        if orientation != "horizontal"
        else "".join(
            f'<text x="{_num(x + width * fraction(value))}" '
            f'y="{_num(y + height + 12)}" text-anchor="middle" '
            f'{tick_attrs} fill="{tick_paint}">'
            f"{escape(label if label is not None else format_tick(value))}</text>"
            for value, label in tick_pairs
        )
    )
    minor_nodes = ""
    if options.get("minor_ticks") and len(tick_positions) >= 2:
        ordered = sorted(set(tick_positions))
        minor_positions = (
            [
                10 ** (np.log10(left) + (np.log10(right) - np.log10(left)) * step / 5.0)
                for left, right in pairwise(ordered)
                for step in range(1, 5)
            ]
            if log_scale
            else [
                left + (right - left) * step / 5.0
                for left, right in pairwise(ordered)
                for step in range(1, 5)
            ]
        )
        if orientation != "horizontal":
            minor_nodes = "".join(
                f'<line data-xy-colorbar-minor="true" x1="{_num(x + width)}" '
                f'x2="{_num(x + width + 3)}" '
                f'y1="{_num(y + height * (1 - fraction(value)))}" '
                f'y2="{_num(y + height * (1 - fraction(value)))}" '
                f'stroke="{escape(text_color)}"/>'
                for value in minor_positions
            )
        else:
            minor_nodes = "".join(
                f'<line data-xy-colorbar-minor="true" '
                f'x1="{_num(x + width * fraction(value))}" '
                f'x2="{_num(x + width * fraction(value))}" '
                f'y1="{_num(y + height)}" y2="{_num(y + height + 3)}" '
                f'stroke="{escape(text_color)}"/>'
                for value in minor_positions
            )
    extend = options.get("extend")
    extend_nodes = ""
    line_only = bool(options.get("line_only"))
    if extend in ("max", "both"):
        r, g, b = options.get("over_color", stops[-1])
        points = (
            f"{_num(x)},{_num(y)} {_num(x + width)},{_num(y)} {_num(x + width / 2)},{_num(y - 9)}"
            if orientation != "horizontal"
            else f"{_num(x + width)},{_num(y)} {_num(x + width)},{_num(y + height)} "
            f"{_num(x + width + 9)},{_num(y + height / 2)}"
        )
        extend_nodes += (
            f'<polygon points="{points}" fill="white" stroke="{escape(text_color)}"/>'
            if line_only
            else f'<polygon points="{points}" fill="rgb({r},{g},{b})"/>'
        )
    if extend in ("min", "both"):
        r, g, b = options.get("under_color", stops[0])
        points = (
            f"{_num(x)},{_num(y + height)} {_num(x + width)},{_num(y + height)} "
            f"{_num(x + width / 2)},{_num(y + height + 9)}"
            if orientation != "horizontal"
            else f"{_num(x)},{_num(y)} {_num(x)},{_num(y + height)} "
            f"{_num(x - 9)},{_num(y + height / 2)}"
        )
        extend_nodes += (
            f'<polygon points="{points}" fill="white" stroke="{escape(text_color)}"/>'
            if line_only
            else f'<polygon points="{points}" fill="rgb({r},{g},{b})"/>'
        )
    line_nodes = ""
    for line in options.get("lines") or []:
        value = float(line.get("value", np.nan))
        if not np.isfinite(value) or value < min(lo, hi) or value > max(lo, hi):
            continue
        line_fraction = fraction(value)
        color = escape(_css(line.get("color"), text_color))
        line_width = _num(max(0.5, float(line.get("width", 1.0))))
        dash = (
            f' stroke-dasharray="{_num(3.7 * float(line_width))} {_num(1.6 * float(line_width))}"'
            if line.get("dash") == "dashed"
            else ""
        )
        if orientation == "horizontal":
            position = x + width * line_fraction
            line_nodes += (
                f'<line data-xy-colorbar-line="true" x1="{_num(position)}" '
                f'x2="{_num(position)}" y1="{_num(y)}" y2="{_num(y + height)}" '
                f'stroke="{color}" stroke-width="{line_width}"{dash}/>'
            )
        else:
            position = y + height * (1.0 - line_fraction)
            line_nodes += (
                f'<line data-xy-colorbar-line="true" x1="{_num(x)}" '
                f'x2="{_num(x + width)}" y1="{_num(position)}" y2="{_num(position)}" '
                f'stroke="{color}" stroke-width="{line_width}"{dash}/>'
            )
    return (
        f'<defs><linearGradient id="{gradient_id}" {gradient_attrs}>'
        f"{stop_nodes}</linearGradient></defs>"
        f"{_colorbar_body(options, x, y, width, height, orientation, gradient_id, text_color)}"
        f"{line_nodes}{extend_nodes}{minor_nodes}{tick_nodes}{label_node}"
    )


def _colorbar_tick_target(length: float) -> int:
    """Major-tick budget for the rendered colorbar length in CSS pixels."""
    return max(2, min(8, int(max(0.0, float(length)) // 48.0) + 1))


def _colorbar_body(
    options: dict,
    x: float,
    y: float,
    width: float,
    height: float,
    orientation: str,
    gradient_id: str,
    text_color: str,
) -> str:
    """Colorbar bar fill: a smooth gradient, or N solid bands for a discrete
    (resampled) colormap so it reads like Matplotlib's segmented colorbar."""
    if options.get("line_only"):
        return (
            f'<rect data-xy-colorbar-line-only="true" x="{_num(x)}" y="{_num(y)}" '
            f'width="{_num(width)}" height="{_num(height)}" fill="white" '
            f'stroke="{escape(text_color)}" stroke-width="1"/>'
        )
    levels = options.get("levels")
    if not levels or int(levels) < 1:
        return (
            f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(width)}" '
            f'height="{_num(height)}" fill="url(#{gradient_id})"/>'
        )
    n = int(levels)
    exact_colors = options.get("band_colors")
    if isinstance(exact_colors, list) and len(exact_colors) == n:
        colors = np.asarray(exact_colors, dtype=np.uint8)
    else:
        cmap = options.get("colormap", "viridis")
        positions = (np.arange(n, dtype=np.float64) + 0.5) / n
        colors = _lut(cmap, positions)
    fractions = np.linspace(0.0, 1.0, n + 1)
    boundaries = np.asarray(options.get("boundaries", []), dtype=np.float64).reshape(-1)
    if (
        options.get("spacing") == "proportional"
        and len(boundaries) == n + 1
        and np.isfinite(boundaries).all()
        and boundaries[-1] > boundaries[0]
        and np.all(np.diff(boundaries) > 0.0)
    ):
        fractions = (boundaries - boundaries[0]) / (boundaries[-1] - boundaries[0])
    rects = []
    for index, (r, g, b) in enumerate(colors):
        lower, upper = float(fractions[index]), float(fractions[index + 1])
        if orientation == "horizontal":
            bx0 = x + width * lower
            bx1 = x + width * upper
            rects.append(
                f'<rect x="{_num(bx0)}" y="{_num(y)}" width="{_num(bx1 - bx0 + 0.5)}" '
                f'height="{_num(height)}" fill="rgb({int(r)},{int(g)},{int(b)})"/>'
            )
        else:
            by0 = y + height * (1.0 - upper)
            by1 = y + height * (1.0 - lower)
            rects.append(
                f'<rect x="{_num(x)}" y="{_num(by0)}" width="{_num(width)}" '
                f'height="{_num(by1 - by0 + 0.5)}" fill="rgb({int(r)},{int(g)},{int(b)})"/>'
            )
    return "".join(rects)


def _resolve_auto_legend_locations(
    fig: Any,
    spec: dict[str, Any],
    rendered_columns: Any,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> dict[str, Any]:
    """Re-resolve automatic legends only when an export changes dimensions.

    Payload construction has to choose an initial concrete location before the
    export-only width/height overrides are known. Static writers still have the
    exact emitted columns at this point, so score those columns against the
    final layout when an override actually changes it. Keeping that trigger in
    this shared helper prevents SVG and raster export semantics from drifting;
    in particular, a same-size export must retain pyplot's richer initial
    decision. Copy on write matters for ``extra_legends``: their payload list
    is allowed to share dictionaries with the source Figure.
    """
    dimensions_changed = (width is not None and int(width) != getattr(fig, "width", None)) or (
        height is not None and int(height) != getattr(fig, "height", None)
    )
    if not dimensions_changed:
        return spec

    from ._legendfit import resolve_for_figure

    updated: Optional[dict[str, Any]] = None

    def resolved(options: Any) -> Any:
        if (
            not isinstance(options, dict)
            or options.get("auto_loc") != "best"
            or options.get("anchor") is not None
            or spec.get("coords", "cartesian") != "cartesian"
        ):
            return options
        concrete = dict(options)
        concrete["loc"] = resolve_for_figure(
            fig,
            spec,
            concrete,
            rendered_columns=rendered_columns,
        )
        return concrete

    legend = spec.get("legend")
    concrete_legend = resolved(legend)
    if concrete_legend is not legend:
        updated = dict(spec)
        updated["legend"] = concrete_legend

    extra_legends = spec.get("extra_legends")
    if isinstance(extra_legends, (list, tuple)):
        concrete_extras = [resolved(extra) for extra in extra_legends]
        if any(
            concrete is not original
            for concrete, original in zip(concrete_extras, extra_legends, strict=True)
        ):
            if updated is None:
                updated = dict(spec)
            updated["extra_legends"] = concrete_extras

    return spec if updated is None else updated


def to_svg(
    fig: Any,
    path: Optional[str | PathLike[str]] = None,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
    id_prefix: str = "",
    background: Optional[str] = None,
) -> str:
    """Render `fig` to a standalone SVG string (optionally saved to `path`).

    `width`/`height` override the figure's pixel size (useful for fluid "100%"
    figures). Decimation runs at the export width, so output stays
    screen-bounded no matter the source size. `id_prefix` namespaces generated
    element ids for composers that inline several exports in one document.
    `background` overrides the figure canvas color ("transparent" omits the
    opaque backdrop, matching the raster exporters' alpha behavior)."""
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
    spec = _resolve_auto_legend_locations(
        fig,
        spec,
        blob,
        width=width,
        height=height,
    )
    apply_export_background(spec, background)
    out = render_svg(spec, blob, id_prefix=id_prefix)
    if path is not None:
        from .export import _atomic_write_text

        _atomic_write_text(path, out)
    return out
