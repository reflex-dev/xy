"""Arrow-annotation path geometry shared by the SVG and raster exporters.

Mirrors ``xyArrowGeometry`` in ``js/src/51_annotations.js`` — keep the two in
sync. Style keys: ``curve`` (matplotlib arc3 rad — quadratic bulge as a
fraction of chord length), ``angle_a``/``angle_b`` (matplotlib angle3/angle
departure/arrival angles, degrees, y-up screen space — the control point is
the ray intersection), ``gap_start``/``gap_end`` (px trims along the path
tangents for label/point clearance), ``start_offset`` (an "x,y" px shift of
the start point — matplotlib's relpos: the arrow leaves the label's box
CENTER, not its anchor), ``label_clear`` (a "left,right,up,down" px
rectangle around the shifted start — the label's extents in y-down screen
space; the start trims to where the departure tangent exits it,
matplotlib's text-patch clipping), ``head_style``/``tail_style``
(``triangle``/``v``/``bar``/``none``) and ``head_size``.
"""

from __future__ import annotations

import math
from typing import Any, Optional


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _label_clear_exit(style: dict[str, Any], tangent: tuple[float, float]) -> float:
    """Distance from the start point to the ``label_clear`` rectangle's edge
    along the departure tangent (0 when absent or leaving immediately)."""
    raw = style.get("label_clear")
    if not isinstance(raw, str):
        return 0.0
    parts = [_number(part) for part in raw.split(",")]
    extents = [part for part in parts if part is not None and part >= 0]
    if len(parts) != 4 or len(extents) != 4:
        return 0.0
    left, right, up, down = extents
    tx, ty = tangent
    exit_x = right / tx if tx > 1e-9 else (left / -tx if tx < -1e-9 else math.inf)
    exit_y = down / ty if ty > 1e-9 else (up / -ty if ty < -1e-9 else math.inf)
    exit_distance = min(exit_x, exit_y)
    return exit_distance if math.isfinite(exit_distance) else 0.0


def arrow_geometry(
    x0: float, y0: float, x1: float, y1: float, style: dict[str, Any]
) -> dict[str, Any]:
    raw_offset = style.get("start_offset")
    if isinstance(raw_offset, str):
        offset = [_number(part) for part in raw_offset.split(",")]
        if len(offset) == 2 and None not in offset:
            x0 += offset[0] or 0.0
            y0 += offset[1] or 0.0
    angle_a = _number(style.get("angle_a"))
    angle_b = _number(style.get("angle_b"))
    curve = _number(style.get("curve"))
    control: Optional[tuple[float, float]] = None
    if angle_a is not None and angle_b is not None:
        a = -angle_a * math.pi / 180  # spec angles are y-up; pixels are y-down
        b = -angle_b * math.pi / 180
        denom = math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b)
        if abs(denom) > 1e-6:
            t = ((x1 - x0) * math.sin(b) - (y1 - y0) * math.cos(b)) / denom
            control = (x0 + t * math.cos(a), y0 + t * math.sin(a))
    elif curve:
        dx, dy = x1 - x0, y1 - y0
        # arc3 rad > 0 bulges to the chord's left in matplotlib's y-up plane.
        control = ((x0 + x1) / 2 + curve * dy, (y0 + y1) / 2 - curve * dx)

    def toward(px: float, py: float, qx: float, qy: float) -> tuple[float, float]:
        d = math.hypot(qx - px, qy - py) or 1.0
        return ((qx - px) / d, (qy - py) / d)

    t0 = toward(x0, y0, *control) if control else toward(x0, y0, x1, y1)
    t1 = toward(x1, y1, *control) if control else toward(x1, y1, x0, y0)
    gap_start = max(0.0, _number(style.get("gap_start")) or 0.0, _label_clear_exit(style, t0))
    gap_end = max(0.0, _number(style.get("gap_end")) or 0.0)
    trim = gap_start + gap_end < math.hypot(x1 - x0, y1 - y0) * 0.9
    p0 = (x0 + gap_start * t0[0], y0 + gap_start * t0[1]) if trim else (x0, y0)
    p1 = (x1 + gap_end * t1[0], y1 + gap_end * t1[1]) if trim else (x1, y1)
    # Tangent INTO each endpoint (head/tail orientation).
    dir1 = toward(*control, *p1) if control else toward(*p0, *p1)
    dir0 = toward(*control, *p0) if control else toward(*p1, *p0)
    return {"p0": p0, "p1": p1, "control": control, "dir0": dir0, "dir1": dir1}


def shaft_points(geom: dict[str, Any], samples: int = 24) -> list[tuple[float, float]]:
    """The shaft as a polyline (quadratic Bézier sampled when curved)."""
    (x0, y0), (x1, y1) = geom["p0"], geom["p1"]
    control = geom["control"]
    if control is None:
        return [(x0, y0), (x1, y1)]
    cx, cy = control
    points = []
    for index in range(samples + 1):
        t = index / samples
        u = 1.0 - t
        points.append(
            (
                u * u * x0 + 2 * u * t * cx + t * t * x1,
                u * u * y0 + 2 * u * t * cy + t * t * y1,
            )
        )
    return points


def end_decoration(
    point: tuple[float, float],
    direction: tuple[float, float],
    end_style: str,
    head: float,
) -> Optional[dict[str, Any]]:
    """One endpoint decoration: {'kind': 'fill'|'stroke', 'points': [...]}.

    ``direction`` is the unit tangent INTO the point; styles mirror matplotlib
    arrowstyles: triangle (filled, "-|>"/fancy), v (open stroke, "->"),
    bar ("|-|" caps), none.
    """
    if end_style == "none":
        return None
    px, py = point
    angle = math.atan2(direction[1], direction[0])
    if end_style == "bar":
        return {
            "kind": "stroke",
            "points": [
                (px - (head / 2) * math.sin(angle), py + (head / 2) * math.cos(angle)),
                (px + (head / 2) * math.sin(angle), py - (head / 2) * math.cos(angle)),
            ],
        }
    wings = [
        (
            px - head * math.cos(angle - side * math.pi / 6),
            py - head * math.sin(angle - side * math.pi / 6),
        )
        for side in (1, -1)
    ]
    if end_style == "v":
        return {"kind": "stroke", "points": [wings[0], (px, py), wings[1]]}
    return {"kind": "fill", "points": [(px, py), wings[0], wings[1]]}


def taper_polygon(
    points: list[tuple[float, float]], width_start: float, width_end: float
) -> list[tuple[float, float]]:
    """The shaft polyline as a filled polygon whose width interpolates from
    ``width_start`` to ``width_end`` (matplotlib's fancy/simple/wedge
    arrowstyles are filled tapered shafts, not stroked lines)."""
    count = len(points)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for index, (px, py) in enumerate(points):
        ax, ay = points[max(0, index - 1)]
        bx, by = points[min(count - 1, index + 1)]
        d = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / d, (bx - ax) / d
        half = (width_start + (width_end - width_start) * (index / max(1, count - 1))) / 2
        left.append((px + half * nx, py + half * ny))
        right.append((px - half * nx, py - half * ny))
    return left + right[::-1]


def trim_polyline_end(points: list[tuple[float, float]], trim: float) -> list[tuple[float, float]]:
    """The polyline with ``trim`` px of arclength removed from its end."""
    if trim <= 0 or len(points) < 2:
        return points
    remaining = trim
    out = list(points)
    while len(out) >= 2:
        (ax, ay), (bx, by) = out[-2], out[-1]
        seg = math.hypot(bx - ax, by - ay)
        if seg > remaining:
            t = 1.0 - remaining / seg
            out[-1] = (ax + t * (bx - ax), ay + t * (by - ay))
            return out
        remaining -= seg
        out.pop()
    return out[:2] if len(out) >= 2 else points[:1] * 2


def arrow_shapes(
    x0: float, y0: float, x1: float, y1: float, style: dict[str, Any]
) -> dict[str, Any]:
    """Shaft polyline (or taper polygon) + endpoint decorations for one
    arrow/callout spec."""
    geom = arrow_geometry(x0, y0, x1, y1, style)
    head = max(4.0, _number(style.get("head_size")) or 8.0)
    head_style = str(style.get("head_style") or "triangle")
    shaft = shaft_points(geom)
    width_start = _number(style.get("shaft_width_start"))
    width_end = _number(style.get("shaft_width_end"))
    taper = None
    if width_start is not None or width_end is not None:
        if head_style == "triangle":
            # matplotlib construction: the shaft ends at the head BASE and the
            # head spans base→tip — a full-length shaft would swallow the head.
            shaft = trim_polyline_end(shaft, head * math.cos(math.pi / 6))
        taper = taper_polygon(shaft, width_start or 1.0, width_end or 1.0)
    return {
        "shaft": None if taper else shaft,
        "taper": taper,
        "head": end_decoration(geom["p1"], geom["dir1"], head_style, head),
        "tail": end_decoration(
            geom["p0"], geom["dir0"], str(style.get("tail_style") or "none"), head
        ),
    }
