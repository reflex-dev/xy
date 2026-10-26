"""Least-occupied legend placement — the engine behind ``loc="best"``.

The Python pass resolves an initial concrete location for deterministic static
output and as a safe first-paint fallback. The payload also records
``auto_loc="best"``; the browser can therefore refine the decision from its
bounded rendered geometry on the first settled draw, after a responsive resize,
or after a settled view change. An explicit location has no such flag and is
never reconsidered.

The initial pass scores the measured static legend footprint against the
bounded geometry already emitted for rendering. Lines contribute vertices and
segment crossings, scatter contributes marker extents or density cells, areas
contribute covered fill area, bars contribute their rectangles, and annotations
contribute their visible anchors/boxes. Candidate order is stable and is the
deterministic tie break.

`xy.pyplot._axes.Axes._best_legend_loc` carries a second copy of this scoring
that runs against the shim's own entry arrays. The two are pinned to agree by
`tests/test_legend_best_placement.py`; folding the shim onto this module is a
follow-up held back only because the compat stack is rewriting that method.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional

import numpy as np

#: Every Matplotlib candidate, in Matplotlib's own preference order (corners,
#: then the mid-edges, then dead center) so a tie keeps the first. Each entry is
#: `(name, x_lo, x_hi, y_lo, y_hi)` in the normalized [0, 1] plot box with y up.
#: Including the centered edges is what lets a full-amplitude oscillation park
#: the legend on its sparse zero-crossing band.
_CANDIDATE_ORDER: tuple[str, ...] = (
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "center right",
    "center left",
    "lower center",
    "upper center",
    "center",
)

#: Below this spread in mean occupancy two boxes count as tied. Matplotlib's
#: integer badness makes near-equal boxes exact ties broken by candidate order;
#: a continuous metric would otherwise let a sub-percent sampling difference
#: override that order.
_TIE_BAND = 0.02

_FALLBACK = "upper right"
_PATH_SAMPLE = 1024
_SCATTER_SAMPLE = 4096
_LEGEND_INSET_PX = 6.0
_FALLBACK_PLOT_SIZE = (564.0, 428.0)
# `_svg.layout`'s non-compact default gutters. They define the figure frame
# around `_FALLBACK_PLOT_SIZE` when layout itself cannot resolve a spec.
_FALLBACK_GUTTERS = (10.0, 14.0, 42.0, 62.0)  # top, right, bottom, left


def candidate_boxes(
    box_w: float,
    box_h: float,
    pad_x: float = 0.0,
    pad_y: float = 0.0,
) -> tuple[tuple[str, float, float, float, float], ...]:
    """Candidate rectangles for a normalized legend footprint.

    ``pad_x``/``pad_y`` are normalized plot-edge insets.  The measured scorer
    passes the static renderer's six-pixel inset; the two-argument form stays
    available for the small pure scoring helpers and compatibility tests.
    """
    span_x = max(0.0, 1.0 - 2.0 * pad_x - box_w)
    span_y = max(0.0, 1.0 - 2.0 * pad_y - box_h)
    anchors = {
        "upper right": (1.0, 1.0),
        "upper left": (0.0, 1.0),
        "lower left": (0.0, 0.0),
        "lower right": (1.0, 0.0),
        "center right": (1.0, 0.5),
        "center left": (0.0, 0.5),
        "lower center": (0.5, 0.0),
        "upper center": (0.5, 1.0),
        "center": (0.5, 0.5),
    }
    geometry = {
        name: (
            pad_x + anchors[name][0] * span_x,
            pad_x + anchors[name][0] * span_x + box_w,
            pad_y + anchors[name][1] * span_y,
            pad_y + anchors[name][1] * span_y + box_h,
        )
        for name in _CANDIDATE_ORDER
    }
    return tuple((name, *geometry[name]) for name in _CANDIDATE_ORDER)


def legend_footprint(labels: Sequence[str]) -> tuple[float, float]:
    """Fractional footprint of the legend box, grown by row count and the
    longest label, so a crowded legend guards a larger corner region."""
    rows = max(1, len(labels))
    max_len = max((len(str(text)) for text in labels), default=4)
    return min(0.6, 0.12 + 0.03 * max_len), min(0.6, 0.10 + 0.07 * rows)


def display_transform(
    values: np.ndarray, scale: Optional[str], constant: float = 1.0
) -> np.ndarray:
    """Value -> display position, matching `_svg._Scale`.

    Occupancy has to be measured where the marks are *drawn*, not where their
    values sit on a number line: on a log axis 1..10000 is four evenly spaced
    decades, while raw subtraction crushes all but the last into the first 10%
    of the box and would hand `best` the wrong corner.
    """
    if scale == "log":
        return np.log10(np.maximum(values, 1e-300))
    if scale == "symlog":
        return np.sign(values) * np.log1p(np.abs(values) / (constant or 1.0))
    return values


def normalize(
    xv: np.ndarray,
    yv: np.ndarray,
    x_domain: tuple[float, float],
    y_domain: tuple[float, float],
    *,
    x_reverse: bool = False,
    y_reverse: bool = False,
    x_scale: Optional[str] = None,
    y_scale: Optional[str] = None,
    x_constant: float = 1.0,
    y_constant: float = 1.0,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Sample a series down and project it into the normalized plot box.

    Samples outside the displayed domain are **dropped, not clamped**: the
    renderers clip them away, so folding them onto an edge would invent
    occupancy in a corner that is visibly empty. Returns None when the series
    has no finite, visible pair to score.
    """
    try:
        xv, yv = np.broadcast_arrays(
            np.asarray(xv, dtype=np.float64), np.asarray(yv, dtype=np.float64)
        )
    except (TypeError, ValueError):
        return None
    xv, yv = xv.reshape(-1), yv.reshape(-1)
    if len(xv) > 4096:
        # Stride down before the finite scan: occupancy is already a sampled
        # measure, so a full-array isfinite pass is pure O(n) build cost on a
        # large legended series. Sparse finite points can slip between strides,
        # so a sample with nothing finite falls back to the full array.
        strided = np.linspace(0, len(xv) - 1, 4096, dtype=np.intp)
        sampled_x, sampled_y = xv[strided], yv[strided]
        if (np.isfinite(sampled_x) & np.isfinite(sampled_y)).any():
            xv, yv = sampled_x, sampled_y
    finite = np.flatnonzero(np.isfinite(xv) & np.isfinite(yv))
    if len(finite) > 512:
        finite = finite[np.linspace(0, len(finite) - 1, 512, dtype=np.intp)]
    if not len(finite):
        return None
    xlo, xhi = (float(v) for v in display_transform(np.asarray(x_domain), x_scale, x_constant))
    ylo, yhi = (float(v) for v in display_transform(np.asarray(y_domain), y_scale, y_constant))
    if not (np.isfinite(xlo) and np.isfinite(xhi) and np.isfinite(ylo) and np.isfinite(yhi)):
        return None
    if xhi <= xlo or yhi <= ylo:
        return None
    xn = (display_transform(xv[finite], x_scale, x_constant) - xlo) / (xhi - xlo)
    yn = (display_transform(yv[finite], y_scale, y_constant) - ylo) / (yhi - ylo)
    # Off-plot marks are clipped by every renderer, so they must not count as
    # occupancy. `np.clip` would pile them onto an edge and guard a corner the
    # viewer sees as empty.
    visible = (
        np.isfinite(xn) & np.isfinite(yn) & (xn >= 0.0) & (xn <= 1.0) & (yn >= 0.0) & (yn <= 1.0)
    )
    xn, yn = xn[visible], yn[visible]
    if not len(xn):
        return None
    if x_reverse:
        xn = 1.0 - xn
    if y_reverse:
        yn = 1.0 - yn
    return xn, yn


def best_loc(series: Sequence[tuple[np.ndarray, np.ndarray]], labels: Sequence[str]) -> str:
    """The least occupied candidate location for these normalized series."""
    if not series:
        return _FALLBACK
    box_w, box_h = legend_footprint(labels)
    candidates = candidate_boxes(box_w, box_h)
    scores: dict[str, float] = {name: 0.0 for name, *_ in candidates}
    used = 0
    for xn, yn in series:
        count = float(len(xn))
        if not count:
            continue
        used += 1
        for name, xl, xh, yl, yh in candidates:
            inside = (xn >= xl) & (xn <= xh) & (yn >= yl) & (yn <= yh)
            scores[name] += float(np.count_nonzero(inside)) / count
    if not used:
        return _FALLBACK
    # Normalize to a mean occupancy in [0, 1] so the tie band is independent of
    # how many series were scored.
    for name in scores:
        scores[name] /= used
    floor = min(scores.values())
    return next(name for name, score in scores.items() if score <= floor + _TIE_BAND)


def _path_intersects_boxes(
    x: np.ndarray,
    y: np.ndarray,
    boxes: Sequence[tuple[float, float, float, float]],
) -> list[bool]:
    """Whether a sampled polyline touches each candidate rectangle."""
    boxes = tuple(boxes)
    if x.size < 2 or y.size < 2:
        return [False] * len(boxes)
    x0, y0, x1, y1 = x[:-1], y[:-1], x[1:], y[1:]
    finite = np.isfinite(x0) & np.isfinite(y0) & np.isfinite(x1) & np.isfinite(y1)
    if not finite.any():
        return [False] * len(boxes)
    x0, y0, x1, y1 = x0[finite], y0[finite], x1[finite], y1[finite]
    seg_x0, seg_x1 = np.minimum(x0, x1), np.maximum(x0, x1)
    seg_y0, seg_y1 = np.minimum(y0, y1), np.maximum(y0, y1)
    hits: list[bool] = []
    for xl, xh, yl, yh in boxes:
        possible = (seg_x1 >= xl) & (seg_x0 <= xh) & (seg_y1 >= yl) & (seg_y0 <= yh)
        hit = False
        for index in np.flatnonzero(possible):
            ax, ay, bx, by = x0[index], y0[index], x1[index], y1[index]
            if (xl <= ax <= xh and yl <= ay <= yh) or (xl <= bx <= xh and yl <= by <= yh):
                hit = True
                break
            dx, dy = bx - ax, by - ay
            if dx:
                for edge in (xl, xh):
                    ratio = (edge - ax) / dx
                    if 0.0 <= ratio <= 1.0 and yl <= ay + ratio * dy <= yh:
                        hit = True
                        break
            if hit:
                break
            if dy:
                for edge in (yl, yh):
                    ratio = (edge - ay) / dy
                    if 0.0 <= ratio <= 1.0 and xl <= ax + ratio * dx <= xh:
                        hit = True
                        break
            if hit:
                break
        hits.append(hit)
    return hits


def _polygon_box_coverage(
    px: np.ndarray,
    py: np.ndarray,
    box: tuple[float, float, float, float],
) -> float:
    """Fraction of ``box`` covered by one bounded filled polygon.

    Sutherland-Hodgman clipping keeps the work linear in the already-bounded
    path length and distinguishes a thin intersection from a candidate almost
    completely covered by the fill. A boolean hit made those two cases tie.
    """
    finite = np.isfinite(px) & np.isfinite(py)
    px, py = px[finite], py[finite]
    if len(px) < 3:
        return 0.0
    xl, xh, yl, yh = box
    if xh <= xl or yh <= yl:
        return 0.0
    vertices = list(zip(px.tolist(), py.tolist(), strict=True))

    def clip(
        points: list[tuple[float, float]],
        inside: Any,
        intersect: Any,
    ) -> list[tuple[float, float]]:
        if not points:
            return []
        out: list[tuple[float, float]] = []
        previous = points[-1]
        previous_inside = inside(previous)
        for current in points:
            current_inside = inside(current)
            if current_inside:
                if not previous_inside:
                    out.append(intersect(previous, current))
                out.append(current)
            elif previous_inside:
                out.append(intersect(previous, current))
            previous, previous_inside = current, current_inside
        return out

    def vertical(
        edge: float, a: tuple[float, float], b: tuple[float, float]
    ) -> tuple[float, float]:
        dx = b[0] - a[0]
        ratio = 0.0 if dx == 0.0 else (edge - a[0]) / dx
        return edge, a[1] + ratio * (b[1] - a[1])

    def horizontal(
        edge: float, a: tuple[float, float], b: tuple[float, float]
    ) -> tuple[float, float]:
        dy = b[1] - a[1]
        ratio = 0.0 if dy == 0.0 else (edge - a[1]) / dy
        return a[0] + ratio * (b[0] - a[0]), edge

    vertices = clip(vertices, lambda p: p[0] >= xl, lambda a, b: vertical(xl, a, b))
    vertices = clip(vertices, lambda p: p[0] <= xh, lambda a, b: vertical(xh, a, b))
    vertices = clip(vertices, lambda p: p[1] >= yl, lambda a, b: horizontal(yl, a, b))
    vertices = clip(vertices, lambda p: p[1] <= yh, lambda a, b: horizontal(yh, a, b))
    if len(vertices) < 3:
        return 0.0
    vx = np.asarray([point[0] for point in vertices])
    vy = np.asarray([point[1] for point in vertices])
    area = 0.5 * abs(float(np.dot(vx, np.roll(vy, 1)) - np.dot(vy, np.roll(vx, 1))))
    return min(1.0, area / ((xh - xl) * (yh - yl)))


def _project(
    xv: Any,
    yv: Any,
    x_info: tuple[tuple[float, float], bool, Optional[str], float],
    y_info: tuple[tuple[float, float], bool, Optional[str], float],
    *,
    budget: int,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Boundedly sample and project a pair while retaining off-view vertices."""
    try:
        x, y = np.broadcast_arrays(
            np.asarray(xv, dtype=np.float64), np.asarray(yv, dtype=np.float64)
        )
    except (TypeError, ValueError):
        return None
    x, y = x.reshape(-1), y.reshape(-1)
    if not len(x):
        return None
    if len(x) > budget:
        indices = np.linspace(0, len(x) - 1, budget, dtype=np.intp)
        x, y = x[indices], y[indices]
    (x_domain, x_reverse, x_scale, x_constant) = x_info
    (y_domain, y_reverse, y_scale, y_constant) = y_info
    x_bounds = display_transform(np.asarray(x_domain), x_scale, x_constant)
    y_bounds = display_transform(np.asarray(y_domain), y_scale, y_constant)
    xlo, xhi = float(x_bounds[0]), float(x_bounds[1])
    ylo, yhi = float(y_bounds[0]), float(y_bounds[1])
    if not all(np.isfinite((xlo, xhi, ylo, yhi))) or xhi <= xlo or yhi <= ylo:
        return None
    valid = np.isfinite(x) & np.isfinite(y)
    if x_scale == "log":
        valid &= x > 0.0
    if y_scale == "log":
        valid &= y > 0.0
    # Payload emission removes invalid/log-nonpositive rows and joins the
    # surviving vertices. Drop them here too; retaining a NaN separator would
    # test a different line topology from the one the renderer receives.
    x, y = x[valid], y[valid]
    if not len(x):
        return None
    xn = (display_transform(x, x_scale, x_constant) - xlo) / (xhi - xlo)
    yn = (display_transform(y, y_scale, y_constant) - ylo) / (yhi - ylo)
    if x_reverse:
        xn = 1.0 - xn
    if y_reverse:
        yn = 1.0 - yn
    return xn, yn


def _measured_candidates(
    spec: Optional[dict[str, Any]],
    legend_options: dict[str, Any],
    labels: Sequence[str],
) -> tuple[tuple[tuple[str, float, float, float, float], ...], tuple[float, float]]:
    """Candidates sized by the same legend layout the static writers use."""
    if spec is None:
        width, height = _FALLBACK_PLOT_SIZE
        box_w, box_h = legend_footprint(labels)
        return candidate_boxes(box_w, box_h), (width, height)
    try:
        from ._svg import _legend_layout, layout, legend_items, legend_options_with_slot

        measured_spec = dict(spec)
        if not isinstance(measured_spec.get("width"), (int, float)):
            measured_spec["width"] = 900
        if not isinstance(measured_spec.get("height"), (int, float)):
            measured_spec["height"] = 420
        options = {
            key: value
            for key, value in legend_options.items()
            if key not in {"loc", "anchor", "auto_loc"}
        }
        measured_spec["legend"] = {**options, "loc": _FALLBACK}
        *_, plot = layout(measured_spec)
        options = legend_options_with_slot(measured_spec, options)
        named = options.get("items")
        if not named:
            palette = measured_spec.get("palette")
            named = (
                legend_items(measured_spec.get("traces") or [], palette)
                if palette
                else legend_items(measured_spec.get("traces") or [])
            )
        if not named:
            named = [{"name": str(label)} for label in labels] or [{"name": ""}]
        box = _legend_layout(named, plot, options)
        plot_w, plot_h = float(plot["w"]), float(plot["h"])
        return (
            candidate_boxes(
                min(1.0, float(box["box_w"]) / plot_w),
                min(1.0, float(box["box_h"]) / plot_h),
                _LEGEND_INSET_PX / plot_w,
                _LEGEND_INSET_PX / plot_h,
            ),
            (plot_w, plot_h),
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        box_w, box_h = legend_footprint(labels)
        return candidate_boxes(box_w, box_h), _FALLBACK_PLOT_SIZE


def _score_annotations(
    scores: dict[str, float],
    candidates: Sequence[tuple[str, float, float, float, float]],
    annotations: Sequence[dict[str, Any]],
    x_info: tuple[tuple[float, float], bool, Optional[str], float],
    y_info: tuple[tuple[float, float], bool, Optional[str], float],
    plot_size: tuple[float, float],
    spec: Optional[dict[str, Any]] = None,
) -> bool:
    """Add bounded annotation obstacles; return whether any were usable."""
    used = False
    boxes = tuple((xl, xh, yl, yh) for _, xl, xh, yl, yh in candidates)

    def data_point(x: Any, y: Any) -> Optional[tuple[float, float]]:
        projected = _project([x], [y], x_info, y_info, budget=1)
        if projected is None:
            return None
        px, py = float(projected[0][0]), float(projected[1][0])
        return (px, py) if np.isfinite(px) and np.isfinite(py) else None

    def point(x: Any, y: Any, coordinate_space: Any = None) -> Optional[tuple[float, float]]:
        """Annotation anchor in normalized plot coordinates (y points up)."""
        try:
            px, py = float(x), float(y)
        except (TypeError, ValueError):
            return None
        if not np.isfinite((px, py)).all():
            return None
        if coordinate_space == "axes_fraction":
            return px, py
        if coordinate_space == "yaxis_transform":
            projected = data_point(x_info[0][0], py)
            return None if projected is None else (px, projected[1])
        if coordinate_space == "xaxis_transform":
            projected = data_point(px, y_info[0][0])
            return None if projected is None else (projected[0], py)
        if coordinate_space == "figure_fraction":
            try:
                from ._svg import layout

                measured = dict(spec or {})
                if not isinstance(measured.get("width"), (int, float)):
                    measured["width"] = 900
                if not isinstance(measured.get("height"), (int, float)):
                    measured["height"] = 420
                *_, plot = layout(measured)
                width, height = float(measured["width"]), float(measured["height"])
                bottom = height - float(plot["y"]) - float(plot["h"])
                return (
                    (px * width - float(plot["x"])) / float(plot["w"]),
                    (py * height - bottom) / float(plot["h"]),
                )
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                # Keep the point in the same normalized *plot* coordinates as
                # the candidate fallback above. Its 564x428 plot is the
                # standard 640x480 frame after the 62/14px horizontal and
                # 10/42px vertical gutters. Returning raw figure fractions
                # here silently treated them as axes fractions instead.
                plot_w, plot_h = plot_size
                top, right, bottom, left = _FALLBACK_GUTTERS
                width = left + plot_w + right
                height = top + plot_h + bottom
                return (
                    (px * width - left) / plot_w,
                    (py * height - bottom) / plot_h,
                )
        return data_point(px, py)

    def displayed(style: dict[str, Any]) -> bool:
        return not (
            str(style.get("display", "")).strip().lower() == "none"
            or str(style.get("visibility", "")).strip().lower() in {"hidden", "collapse"}
        )

    def shape_paint_visible(kind: Any, style: dict[str, Any]) -> bool:
        color_visible = _paint_may_be_visible(style.get("color"))
        if kind == "marker":
            stroke_visible = _numeric(
                style.get("stroke_width", 0.0), 0.0
            ) > 0.0 and _paint_may_be_visible(style.get("stroke_color"))
            return color_visible or stroke_visible
        return color_visible

    def label_paint_visible(style: dict[str, Any]) -> bool:
        label_color = style.get("label_color", style.get("color"))
        background = style.get("background")
        border = str(style.get("border", "")).strip()
        return (
            _paint_may_be_visible(label_color)
            or (background is not None and _paint_may_be_visible(background))
            or (
                bool(border)
                and border.lower() != "none"
                and _paint_may_be_visible(border.split()[-1])
            )
        )

    def add_box_hits(
        hits: list[bool],
        anchor: tuple[float, float],
        width_px: float,
        height_px: float,
        anchor_name: Any,
    ) -> None:
        cx, cy = anchor
        rx, ry = width_px / (2.0 * plot_size[0]), height_px / (2.0 * plot_size[1])
        if anchor_name == "start":
            cx += rx
        elif anchor_name == "end":
            cx -= rx
        for index, (xl, xh, yl, yh) in enumerate(boxes):
            hits[index] |= cx + rx >= xl and cx - rx <= xh and cy + ry >= yl and cy - ry <= yh

    for annotation in annotations:
        style = annotation.get("style") or {}
        if not displayed(style):
            continue
        kind = annotation.get("kind")
        hits = [False] * len(candidates)
        shape_visible = (
            kind != "text"
            and _numeric(style.get("opacity", 1.0), 1.0) > 0.0
            and shape_paint_visible(kind, style)
        )
        span_start = max(0.0, min(1.0, _numeric(style.get("span_start", 0.0), 0.0)))
        span_end = max(span_start, min(1.0, _numeric(style.get("span_end", 1.0), 1.0)))

        if shape_visible and kind == "rule":
            axis = annotation.get("axis")
            if axis == "x":
                anchor = data_point(annotation.get("value"), y_info[0][0])
                if anchor is not None:
                    hits = [
                        xl <= anchor[0] <= xh and span_start <= yh and span_end >= yl
                        for xl, xh, yl, yh in boxes
                    ]
            elif axis == "y":
                anchor = data_point(x_info[0][0], annotation.get("value"))
                if anchor is not None:
                    hits = [
                        yl <= anchor[1] <= yh and span_start <= xh and span_end >= xl
                        for xl, xh, yl, yh in boxes
                    ]
        elif shape_visible and kind == "band":
            axis = annotation.get("axis")
            if axis == "x":
                a = data_point(annotation.get("start"), y_info[0][0])
                b = data_point(annotation.get("end"), y_info[0][0])
                if a is not None and b is not None:
                    lo, hi = sorted((a[0], b[0]))
                    hits = [
                        lo <= xh and hi >= xl and span_start <= yh and span_end >= yl
                        for xl, xh, yl, yh in boxes
                    ]
            elif axis == "y":
                a = data_point(x_info[0][0], annotation.get("start"))
                b = data_point(x_info[0][0], annotation.get("end"))
                if a is not None and b is not None:
                    lo, hi = sorted((a[1], b[1]))
                    hits = [
                        lo <= yh and hi >= yl and span_start <= xh and span_end >= xl
                        for xl, xh, yl, yh in boxes
                    ]
        elif shape_visible and kind == "arrow":
            a = data_point(annotation.get("x0"), annotation.get("y0"))
            b = data_point(annotation.get("x1"), annotation.get("y1"))
            if a is not None and b is not None:
                hits = _path_intersects_boxes(
                    np.asarray((a[0], b[0])), np.asarray((a[1], b[1])), boxes
                )
        elif shape_visible and kind in {"marker", "callout"}:
            anchor = data_point(annotation.get("x"), annotation.get("y"))
            if anchor is not None:
                if kind == "marker":
                    diameter = _numeric(annotation.get("size", 8.0), 8.0) + _numeric(
                        style.get("stroke_width", 0.0), 0.0
                    )
                    add_box_hits(hits, anchor, diameter, diameter, "middle")
                else:
                    label_anchor = (
                        anchor[0] + _numeric(annotation.get("dx", 0.0), 0.0) / plot_size[0],
                        anchor[1] - _numeric(annotation.get("dy", 0.0), 0.0) / plot_size[1],
                    )
                    connector = _path_intersects_boxes(
                        np.asarray((anchor[0], label_anchor[0])),
                        np.asarray((anchor[1], label_anchor[1])),
                        boxes,
                    )
                    hits = [a or b for a, b in zip(hits, connector, strict=True)]

        text = annotation.get("text")
        label_opacity = _numeric(
            style.get(
                "label_opacity",
                style.get("opacity", 1.0) if kind == "text" else 1.0,
            ),
            1.0,
        )
        if text and label_opacity > 0.0 and label_paint_visible(style):
            label_anchor: Optional[tuple[float, float]] = None
            anchor_name = annotation.get("anchor")
            axis = annotation.get("axis")
            if kind == "rule":
                if axis == "x":
                    base = data_point(annotation.get("value"), y_info[0][0])
                    label_anchor = None if base is None else (base[0], 1.0 - 6.0 / plot_size[1])
                else:
                    base = data_point(x_info[0][0], annotation.get("value"))
                    label_anchor = None if base is None else (1.0 - 6.0 / plot_size[0], base[1])
                    anchor_name = anchor_name or "end"
            elif kind == "band":
                if axis == "x":
                    a = data_point(annotation.get("start"), y_info[0][0])
                    b = data_point(annotation.get("end"), y_info[0][0])
                    if a is not None and b is not None:
                        label_anchor = ((a[0] + b[0]) / 2.0, 1.0 - 6.0 / plot_size[1])
                        anchor_name = anchor_name or "middle"
                else:
                    a = data_point(x_info[0][0], annotation.get("start"))
                    b = data_point(x_info[0][0], annotation.get("end"))
                    if a is not None and b is not None:
                        label_anchor = (1.0 - 6.0 / plot_size[0], (a[1] + b[1]) / 2.0)
                        anchor_name = anchor_name or "end"
            elif kind == "arrow":
                a = data_point(annotation.get("x0"), annotation.get("y0"))
                b = data_point(annotation.get("x1"), annotation.get("y1"))
                if a is not None and b is not None:
                    label_anchor = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                    anchor_name = anchor_name or "middle"
            else:
                label_anchor = point(
                    annotation.get("x"),
                    annotation.get("y"),
                    style.get("coordinate_space"),
                )
            if label_anchor is not None:
                label_anchor = (
                    label_anchor[0] + _numeric(annotation.get("dx", 0.0), 0.0) / plot_size[0],
                    label_anchor[1] - _numeric(annotation.get("dy", 0.0), 0.0) / plot_size[1],
                )
                font_size = _numeric(style.get("font_size", 11.0), 11.0)
                lines = str(text).splitlines() or [""]
                width_px = max(1.0, font_size * 0.56 * max(map(len, lines)))
                height_px = max(font_size, 1.2 * font_size * len(lines))
                add_box_hits(hits, label_anchor, width_px, height_px, anchor_name or "start")
        if any(hits):
            used = True
            for (name, *_), hit in zip(candidates, hits, strict=True):
                if hit:
                    scores[name] += 1.0
    return used


def _column_index(reference: Any) -> Optional[int]:
    """Column-table index carried by a compact wire reference."""
    if isinstance(reference, dict):
        reference = reference.get("col", reference.get("buf"))
    if isinstance(reference, (int, np.integer)) and not isinstance(reference, bool):
        return int(reference)
    return None


def _rendered_column(
    spec: Optional[dict[str, Any]],
    source: Any,
    reference: Any,
    budget: Optional[int],
) -> Optional[np.ndarray]:
    """Decode one emitted geometry column without consulting canonical rows.

    During payload compilation ``source`` is the writer and can return its
    retained encoded array directly. Static exporters pass the assembled blob,
    which is decoded through the same column metadata. Either route observes
    the exact M4/density/direct representation that is rendered.
    """
    index = _column_index(reference)
    columns = (spec or {}).get("columns") or ()
    if index is None or index < 0 or index >= len(columns):
        return None
    if source is not None and hasattr(source, "decoded_column"):
        try:
            return np.asarray(source.decoded_column(index, budget), dtype=np.float64)
        except (IndexError, TypeError, ValueError):
            return None
    if not isinstance(source, (bytes, bytearray, memoryview)):
        return None
    meta = columns[index]
    if int(meta.get("span", 0) or 0) != 0:
        # Borrowed f64 spans are separate from the owned payload blob. Legend
        # geometry never uses them; returning None keeps the fallback honest.
        return None
    # Local import avoids a module cycle: payload compilation imports this
    # scorer only after its writer and wire helpers have been initialized.
    from ._payload import _decode_emitted_values, _emitted_column_dtype

    try:
        values = np.frombuffer(
            source,
            dtype=_emitted_column_dtype(meta),
            count=int(meta.get("len", 0)),
            offset=int(meta.get("byte_offset", 0)),
        )
    except (TypeError, ValueError):
        return None
    return _decode_emitted_values(values, meta, budget)


def _rendered_column_rows(
    spec: Optional[dict[str, Any]],
    source: Any,
    reference: Any,
    components: int,
    budget: Optional[int],
) -> Optional[np.ndarray]:
    """Decode a row-aligned sample from a multi-component wire column."""
    index = _column_index(reference)
    columns = (spec or {}).get("columns") or ()
    if components <= 0 or index is None or index < 0 or index >= len(columns):
        return None
    if source is not None and hasattr(source, "decoded_column_rows"):
        try:
            return np.asarray(
                source.decoded_column_rows(index, components, budget),
                dtype=np.float64,
            )
        except (IndexError, TypeError, ValueError):
            return None
    if not isinstance(source, (bytes, bytearray, memoryview)):
        return None
    meta = columns[index]
    if int(meta.get("span", 0) or 0) != 0:
        return None
    from ._payload import _decode_emitted_values, _emitted_column_dtype

    length = int(meta.get("len", 0))
    if length % components:
        return None
    try:
        values = np.frombuffer(
            source,
            dtype=_emitted_column_dtype(meta),
            count=length,
            offset=int(meta.get("byte_offset", 0)),
        ).reshape(-1, components)
    except (TypeError, ValueError):
        return None
    return _decode_emitted_values(values, meta, budget)


def _numeric(value: Any, default: float) -> float:
    """A numeric style value; unresolved CSS is conservatively visible."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _bounded_any_positive(values: Any, budget: int = _SCATTER_SAMPLE) -> bool:
    """Whether a deterministic bounded view of a direct channel has ink."""
    try:
        array = np.asarray(values, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return True
    if len(array) > budget:
        array = array[np.linspace(0, len(array) - 1, budget, dtype=np.intp)]
    return bool(np.any(np.isfinite(array) & (array > 0.0)))


def _bounded_any_nonzero(values: Any, budget: int = _SCATTER_SAMPLE) -> bool:
    """Bounded artist-alpha check; -1 is the intrinsic-alpha sentinel."""
    try:
        array = np.asarray(values, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return True
    if len(array) > budget:
        array = array[np.linspace(0, len(array) - 1, budget, dtype=np.intp)]
    return bool(np.any(np.isfinite(array) & (array != 0.0)))


def _paint_may_be_visible(value: Any) -> bool:
    """Known zero-alpha CSS is invisible; unresolved CSS stays conservative."""
    if value is None or isinstance(value, dict):
        return True
    try:
        from . import kernels

        _status, rgba = kernels.css_check(kernels.CSS_COLOR, str(value))
    except (TypeError, ValueError):
        return True
    return rgba is None or float(rgba[3]) > 0.0


def _gradient_may_be_visible(value: Any) -> bool:
    """Whether a validated mark-fill gradient has any nonzero-alpha stop."""
    if not isinstance(value, dict):
        return False
    stops = value.get("stops") or ()
    # A malformed/browser-only fill is kept conservative. Validated mark
    # gradients always carry two to eight ``[offset, paint]`` pairs.
    if not stops:
        return True
    return any(
        not isinstance(stop, (list, tuple)) or len(stop) < 2 or _paint_may_be_visible(stop[1])
        for stop in stops
    )


def _face_may_be_visible(trace: Any, channel: Any, style: dict[str, Any]) -> bool:
    """Visible face paint, accounting for a gradient overriding ``color``."""
    fill = style.get("fill")
    if isinstance(fill, dict):
        return _gradient_may_be_visible(fill)
    return _color_channel_may_be_visible(trace, channel)


def _color_channel_may_be_visible(trace: Any, channel: Any) -> bool:
    """Whether a resolved constant/direct/categorical paint has any alpha."""
    if channel is None:
        return _paint_may_be_visible((getattr(trace, "style", {}) or {}).get("color"))
    mode = getattr(channel, "mode", None)
    if mode == "constant":
        return _paint_may_be_visible(getattr(channel, "constant", None))
    if mode == "direct_rgba":
        # Per-row alpha must use the same emitted selection as geometry; an
        # independent canonical stride can miss the sole visible mark.
        return True
    if mode == "categorical":
        categories = getattr(channel, "categories", None) or ()
        colors = getattr(channel, "colors", None) or ()
        hidden = getattr(trace, "hidden_categories", set()) or set()
        if not categories or not colors:
            return True
        return any(
            index not in hidden and _paint_may_be_visible(colors[index % len(colors)])
            for index in range(len(categories))
        )
    # Continuous colormaps and match-fill are visible unless their shared fill
    # is rejected by the caller. Colormap/CSS expressions may resolve client-side.
    return True


def _trace_has_visible_ink(trace: Any, emitted: Optional[dict[str, Any]]) -> bool:
    """Cheap, bounded rejection of traces that paint no visible pixels."""
    style = (emitted or {}).get("style") or getattr(trace, "style", {}) or {}
    if _numeric(style.get("opacity", 1.0), 1.0) <= 0.0:
        return False

    channels = getattr(trace, "style_channels", {}) or {}
    artist_channel = channels.get("artist_alpha")
    artist_alpha = _numeric(style.get("artist_alpha", -1.0), -1.0)
    if artist_channel is None and artist_alpha == 0.0:
        return False
    artist_override_possible = artist_channel is not None or artist_alpha > 0.0
    if emitted is None:
        # Raw helper fallback only. Production paths always have emitted
        # columns and apply the exact same row selection as geometry below.
        opacity_channel = channels.get("opacity")
        if opacity_channel is not None and not _bounded_any_positive(
            getattr(opacity_channel, "values", opacity_channel)
        ):
            return False
        if artist_channel is not None and not _bounded_any_nonzero(
            getattr(artist_channel, "values", artist_channel)
        ):
            return False
    hidden = getattr(trace, "hidden_categories", set()) or set()
    color = getattr(trace, "color_ch", None)
    categories = getattr(color, "categories", None)
    if categories and len(hidden) >= len(categories):
        return False

    kind = str((emitted or {}).get("kind", getattr(trace, "kind", "")))
    face_visible = _face_may_be_visible(trace, color, style) or artist_override_possible
    if kind == "line":
        return (
            face_visible
            and _numeric(style.get("width", 1.5), 1.5) > 0.0
            and _numeric(style.get("stroke_opacity", 1.0), 1.0) > 0.0
        )
    if kind in {"area", "error_band"}:
        fill_visible = face_visible and _numeric(style.get("fill_opacity", 1.0), 1.0) > 0.0
        line_paint = style.get("line_color", style.get("color"))
        outline_visible = (
            _paint_may_be_visible(line_paint)
            and _numeric(style.get("line_width", 1.2), 1.2) > 0.0
            and _numeric(style.get("line_opacity", 1.0), 1.0) > 0.0
            and _numeric(style.get("stroke_opacity", 1.0), 1.0) > 0.0
        )
        return fill_visible or outline_visible
    if kind in {"scatter", "bar", "column", "histogram"}:
        if kind == "scatter":
            size = getattr(trace, "size_ch", None)
            if (
                getattr(size, "mode", None) == "constant"
                and _numeric(getattr(size, "constant", 0.0), 0.0) <= 0.0
            ):
                return False
            if (
                getattr(size, "mode", None) == "continuous"
                and max(
                    (_numeric(value, 0.0) for value in getattr(size, "range_px", ())),
                    default=0.0,
                )
                <= 0.0
            ):
                return False
        fill_visible = face_visible and _numeric(style.get("fill_opacity", 1.0), 1.0) > 0.0
        stroke_channel = getattr(trace, "stroke_ch", None)
        stroke_width = _numeric(style.get("stroke_width", 0.0), 0.0)
        width_channel = channels.get("stroke_width")
        if width_channel is not None:
            stroke_width = 1.0 if _bounded_any_positive(width_channel.values) else 0.0
        if stroke_channel is not None:
            stroke_visible = (
                _color_channel_may_be_visible(trace, stroke_channel) or artist_override_possible
            )
            if getattr(stroke_channel, "mode", None) == "match_fill":
                stroke_visible = face_visible
        else:
            stroke_visible = (
                _paint_may_be_visible(style.get("stroke", style.get("color")))
                or artist_override_possible
            )
        stroke_visible = (
            stroke_visible
            and stroke_width > 0.0
            and _numeric(style.get("stroke_opacity", 1.0), 1.0) > 0.0
        )
        return fill_visible or stroke_visible
    return face_visible


def _emitted_alpha_mask(
    spec: Optional[dict[str, Any]],
    source: Any,
    emitted: Optional[dict[str, Any]],
    trace: Any,
    length: int,
    budget: int,
) -> np.ndarray:
    """Rows whose emitted fill or stroke has positive effective alpha.

    This is the boolean form of :func:`xy._paint.effective_rgba`: negative
    ``artist_alpha`` (the pyplot ``-1`` sentinel) keeps intrinsic paint alpha,
    while a nonnegative value replaces it. Overall and component opacity remain
    multiplicative. Fill, stroke, and stroke width are evaluated per emitted
    row so a transparent face cannot borrow ink from a different row's border.
    """
    entry = emitted or {}
    style = entry.get("style") or getattr(trace, "style", {}) or {}
    channels = entry.get("channels") or {}

    def style_values(name: str, default: float) -> np.ndarray:
        scalar = _numeric(style.get(name, default), default)
        result = np.full(length, scalar, dtype=np.float64)
        channel = channels.get(name) or {}
        values = _rendered_column(spec, source, channel.get("buf"), budget)
        if values is not None and len(values) == length:
            result = values
        return result

    def paint_alpha(color_spec: Any, fallback: Any = None) -> np.ndarray:
        color_spec = color_spec if isinstance(color_spec, dict) else {}
        mode = color_spec.get("mode")
        if mode == "direct_rgba":
            colors = _rendered_column_rows(
                spec,
                source,
                color_spec.get("buf"),
                int(color_spec.get("components", 4) or 4),
                budget,
            )
            if colors is not None and len(colors) == length and colors.shape[1] >= 4:
                return np.isfinite(colors[:, 3]) & (colors[:, 3] > 0.0)
        elif mode == "categorical":
            codes = _rendered_column(spec, source, color_spec.get("buf"), budget)
            palette = color_spec.get("palette") or ()
            if codes is not None and len(codes) == length and palette:
                lookup = np.asarray([_paint_may_be_visible(color) for color in palette], dtype=bool)
                indices = np.rint(codes).astype(np.int64) % len(lookup)
                return np.isfinite(codes) & lookup[indices]
        elif mode == "constant":
            return np.full(
                length,
                _paint_may_be_visible(color_spec.get("color", fallback)),
                dtype=bool,
            )
        # Continuous colormaps and unresolved/missing browser paints are
        # conservatively visible. Missing stroke is handled explicitly below.
        return np.full(length, _paint_may_be_visible(fallback), dtype=bool)

    opacity = style_values("opacity", 1.0)
    artist = style_values("artist_alpha", -1.0)
    opacity_visible = np.isfinite(opacity) & (opacity > 0.0)

    color_spec = entry.get("color") or {}
    base_fill_alpha = paint_alpha(color_spec, style.get("color"))
    fill_spec = style.get("fill")
    fill_alpha = (
        np.full(length, _gradient_may_be_visible(fill_spec), dtype=bool)
        if isinstance(fill_spec, dict)
        else base_fill_alpha
    )

    # Hidden categorical codes suppress the complete mark, including a
    # separately-authored stroke or gradient face.
    category_visible = np.ones(length, dtype=bool)
    hidden = getattr(trace, "hidden_categories", set()) or set()
    if color_spec.get("mode") == "categorical" and hidden:
        codes = _rendered_column(spec, source, color_spec.get("buf"), budget)
        if codes is not None and len(codes) == length:
            category_visible &= np.isfinite(codes) & ~np.isin(
                np.rint(codes).astype(np.int64), tuple(hidden)
            )

    # ``artist_alpha >= 0`` replaces intrinsic alpha for both components; the
    # -1 sentinel and any other negative value retain the component's alpha.
    artist_override = np.isfinite(artist) & (artist >= 0.0)

    def effective(intrinsic: np.ndarray, component: str) -> np.ndarray:
        base = np.where(artist_override, artist > 0.0, intrinsic)
        component_opacity = _numeric(style.get(f"{component}_opacity", 1.0), 1.0)
        return opacity_visible & base & (component_opacity > 0.0)

    fill_visible = effective(fill_alpha, "fill")

    stroke_spec = entry.get("stroke")
    if isinstance(stroke_spec, dict) and stroke_spec.get("mode") == "match_fill":
        # Match the color channel, not a mark-fill gradient: renderers use the
        # base face paint for outlines while the gradient replaces only fill.
        stroke_alpha = base_fill_alpha
    elif isinstance(stroke_spec, dict):
        stroke_alpha = paint_alpha(stroke_spec, style.get("stroke"))
    elif style.get("stroke") is not None:
        stroke_alpha = np.full(length, _paint_may_be_visible(style.get("stroke")), dtype=bool)
    else:
        # Constant faces implicitly supply the stroke paint when a width exists.
        stroke_alpha = base_fill_alpha

    stroke_width = style_values("stroke_width", 0.0)
    stroke_visible = (
        effective(stroke_alpha, "stroke") & np.isfinite(stroke_width) & (stroke_width > 0.0)
    )
    return category_visible & (fill_visible | stroke_visible)


def _emitted_rect(
    spec: Optional[dict[str, Any]],
    source: Any,
    emitted: Optional[dict[str, Any]],
    *,
    budget: int,
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Exact rectangles from either generic or compact bar wire geometry."""
    if not emitted:
        return None
    if all(key in emitted for key in ("x0", "x1", "y0", "y1")):
        x0 = _rendered_column(spec, source, emitted.get("x0"), budget)
        x1 = _rendered_column(spec, source, emitted.get("x1"), budget)
        y0 = _rendered_column(spec, source, emitted.get("y0"), budget)
        y1 = _rendered_column(spec, source, emitted.get("y1"), budget)
        if x0 is not None and x1 is not None and y0 is not None and y1 is not None:
            return x0, x1, y0, y1

    bar = emitted.get("bar") or {}
    pos = _rendered_column(spec, source, bar.get("pos"), budget)
    value1 = _rendered_column(spec, source, bar.get("value1"), budget)
    if pos is None or value1 is None:
        return None
    value0 = _rendered_column(spec, source, bar.get("value0"), budget)
    if value0 is None:
        try:
            value0 = np.full(len(pos), float(bar["value0_const"]), dtype=np.float64)
        except (KeyError, TypeError, ValueError):
            return None
    n = min(len(pos), len(value0), len(value1))
    pos, value0, value1 = pos[:n], value0[:n], value1[:n]
    width = _numeric(bar.get("width", 0.0), 0.0)
    if width <= 0.0:
        return None
    half = width / 2.0
    if bar.get("orientation", "vertical") == "horizontal":
        return value0, value1, pos - half, pos + half
    return pos - half, pos + half, value0, value1


def _emitted_density_points(
    spec: Optional[dict[str, Any]],
    source: Any,
    emitted: Optional[dict[str, Any]],
    x_info: tuple[tuple[float, float], bool, Optional[str], float],
    y_info: tuple[tuple[float, float], bool, Optional[str], float],
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Occupied density-cell centres, already normalized to the plot box."""
    density = (emitted or {}).get("density") or {}
    try:
        width, height = int(density["w"]), int(density["h"])
        x_range = tuple(float(value) for value in density["x_range"])
        y_range = tuple(float(value) for value in density["y_range"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    grid = _rendered_column(spec, source, density.get("buf"), None)
    if grid is None or len(grid) < width * height:
        return None
    painted = grid[: width * height] > 0.0
    if density.get("rgba") is not None:
        rgba = _rendered_column_rows(
            spec,
            source,
            density.get("rgba"),
            4,
            None,
        )
        if rgba is not None and len(rgba) >= width * height:
            painted &= np.isfinite(rgba[: width * height, 3]) & (rgba[: width * height, 3] > 0.0)
    occupied = np.flatnonzero(painted)
    if not len(occupied):
        empty = np.empty(0, dtype=np.float64)
        return empty, empty
    col = occupied % width
    row = occupied // width
    # Wire ranges stay in data units even though density binning is uniform in
    # scale coordinates. Transform the endpoints first, then interpolate cell
    # centres exactly as the renderers do for log/symlog axes.
    x_edges = display_transform(np.asarray(x_range), x_info[2], x_info[3])
    y_edges = display_transform(np.asarray(y_range), y_info[2], y_info[3])
    x_coord = x_edges[0] + (col + 0.5) * (x_edges[1] - x_edges[0]) / width
    y_coord = y_edges[0] + (row + 0.5) * (y_edges[1] - y_edges[0]) / height

    def normalize_coord(
        values: np.ndarray,
        info: tuple[tuple[float, float], bool, Optional[str], float],
    ) -> Optional[np.ndarray]:
        domain, reverse, scale, constant = info
        bounds = display_transform(np.asarray(domain, dtype=np.float64), scale, constant)
        lo, hi = float(bounds[0]), float(bounds[1])
        if not np.isfinite((lo, hi)).all() or hi <= lo:
            return None
        result = (values - lo) / (hi - lo)
        return 1.0 - result if reverse else result

    xn, yn = normalize_coord(x_coord, x_info), normalize_coord(y_coord, y_info)
    return None if xn is None or yn is None else (xn, yn)


def resolve_for_figure(
    figure: Any,
    spec: Optional[dict[str, Any]] = None,
    legend_options: Optional[dict[str, Any]] = None,
    rendered_columns: Any = None,
) -> str:
    """Resolve the initial best location from bounded visible geometry."""
    traces = [trace for trace in getattr(figure, "traces", ()) if not trace.hidden]
    labels = [str(trace.name) for trace in traces if trace.name]
    options = dict(legend_options or getattr(figure, "legend_options", {}) or {})
    candidates, plot_size = _measured_candidates(spec, options, labels)
    candidate_rects = tuple((xl, xh, yl, yh) for _, xl, xh, yl, yh in candidates)
    scores: dict[str, float] = {name: 0.0 for name, *_ in candidates}
    used = False
    emitted_by_id = {
        int(entry.get("id", index)): entry
        for index, entry in enumerate((spec or {}).get("traces") or ())
    }

    for trace in traces:
        emitted = emitted_by_id.get(int(trace.id))
        if not _trace_has_visible_ink(trace, emitted):
            continue
        domains = _figure_domains(figure, trace)
        if domains is None:
            continue
        x_info, y_info = domains
        kind = getattr(trace, "kind", "")

        if kind in {"bar", "column", "histogram"}:
            emitted_rect = _emitted_rect(spec, rendered_columns, emitted, budget=_SCATTER_SAMPLE)
            if emitted_rect is None:
                x0 = _column_values(getattr(trace, "x0", None))
                x1 = _column_values(getattr(trace, "x1", None))
                y0 = _column_values(getattr(trace, "y0", None))
                y1 = _column_values(getattr(trace, "y1", None))
            else:
                x0, x1, y0, y1 = emitted_rect
            if x0 is not None and x1 is not None and y0 is not None and y1 is not None:
                rect_budget = len(x0) if emitted_rect is not None else _PATH_SAMPLE
                lo = _project(x0, y0, x_info, y_info, budget=rect_budget)
                hi = _project(x1, y1, x_info, y_info, budget=rect_budget)
                if lo is not None and hi is not None:
                    rx0, rx1 = np.minimum(lo[0], hi[0]), np.maximum(lo[0], hi[0])
                    ry0, ry1 = np.minimum(lo[1], hi[1]), np.maximum(lo[1], hi[1])
                    finite = (
                        np.isfinite(rx0) & np.isfinite(rx1) & np.isfinite(ry0) & np.isfinite(ry1)
                    )
                    visible = finite & (rx1 >= 0.0) & (rx0 <= 1.0) & (ry1 >= 0.0) & (ry0 <= 1.0)
                    visible &= _emitted_alpha_mask(
                        spec,
                        rendered_columns,
                        emitted,
                        trace,
                        len(visible),
                        rect_budget,
                    )
                    if visible.any():
                        used = True
                        for name, xl, xh, yl, yh in candidates:
                            overlap_w = np.maximum(0.0, np.minimum(rx1, xh) - np.maximum(rx0, xl))
                            overlap_h = np.maximum(0.0, np.minimum(ry1, yh) - np.maximum(ry0, yl))
                            scores[name] += float(np.sum((overlap_w * overlap_h)[visible])) / max(
                                (xh - xl) * (yh - yl), 1e-12
                            )
                    # Rectangle geometry is authoritative even when every
                    # emitted mark is transparent or clipped. Do not fall
                    # through and reinterpret bar centers/tips as a polyline.
                    continue

        if kind == "scatter" and (emitted or {}).get("tier") == "density":
            density_points = _emitted_density_points(
                spec, rendered_columns, emitted, x_info, y_info
            )
            if density_points is not None:
                xn, yn = density_points
                if len(xn):
                    visible = (
                        np.isfinite(xn)
                        & np.isfinite(yn)
                        & (xn >= 0.0)
                        & (xn <= 1.0)
                        & (yn >= 0.0)
                        & (yn <= 1.0)
                    )
                    count = max(1, int(np.count_nonzero(visible)))
                    if visible.any():
                        used = True
                        for name, xl, xh, yl, yh in candidates:
                            inside = visible & (xn >= xl) & (xn <= xh) & (yn >= yl) & (yn <= yh)
                            scores[name] += float(np.count_nonzero(inside)) / count
                # A valid empty/off-view grid is authoritative rendered
                # geometry; never fall back to canonical scatter rows that the
                # density surface did not paint.
                continue

        xv = _column_values(getattr(trace, "x", None))
        yv = _column_values(getattr(trace, "y", None))
        budget = _SCATTER_SAMPLE if kind == "scatter" else _PATH_SAMPLE
        emitted_budget = budget if kind == "scatter" else None
        emitted_x = _rendered_column(
            spec, rendered_columns, (emitted or {}).get("x"), emitted_budget
        )
        emitted_y = _rendered_column(
            spec, rendered_columns, (emitted or {}).get("y"), emitted_budget
        )
        if emitted_x is not None and emitted_y is not None:
            xv, yv = emitted_x, emitted_y
        if xv is None or yv is None:
            continue
        projection_budget = len(xv) if emitted_x is not None else budget
        projected = _project(xv, yv, x_info, y_info, budget=projection_budget)
        if projected is None:
            continue
        xn, yn = projected
        finite = np.isfinite(xn) & np.isfinite(yn)
        if not finite.any():
            continue
        used = True

        if kind == "area":
            base = _rendered_column(spec, rendered_columns, (emitted or {}).get("base"), None)
            if base is None:
                base = _column_values(getattr(trace, "base", None))
            base_projected = (
                _project(xv, base, x_info, y_info, budget=projection_budget)
                if base is not None
                else None
            )
            if base_projected is not None:
                bx, by = base_projected
                style = (emitted or {}).get("style") or getattr(trace, "style", {}) or {}
                fill_visible = (
                    _face_may_be_visible(trace, getattr(trace, "color_ch", None), style)
                    and _numeric(style.get("fill_opacity", 1.0), 1.0) > 0.0
                )
                if fill_visible:
                    polygon_x = np.concatenate((xn, bx[::-1]))
                    polygon_y = np.concatenate((yn, by[::-1]))
                    for (name, *_), box in zip(candidates, candidate_rects, strict=True):
                        scores[name] += _polygon_box_coverage(polygon_x, polygon_y, box)
                    # Coverage already represents the complete painted area;
                    # adding its outline as a unit crossing would swamp small
                    # but meaningful coverage differences between candidates.
                    continue

                line_paint = style.get("line_color")
                outline_visible = (
                    (
                        _paint_may_be_visible(line_paint)
                        if line_paint is not None
                        else _color_channel_may_be_visible(trace, getattr(trace, "color_ch", None))
                    )
                    and _numeric(style.get("line_width", 1.2), 1.2) > 0.0
                    and _numeric(style.get("line_opacity", 1.0), 1.0) > 0.0
                    and _numeric(style.get("stroke_opacity", 1.0), 1.0) > 0.0
                )
                if not outline_visible:
                    continue
                if style.get("stroke_perimeter"):
                    # The rendered perimeter closes the top against the
                    # reversed baseline, including both vertical sides.
                    xn = np.concatenate((xn, bx[::-1], xn[:1]))
                    yn = np.concatenate((yn, by[::-1], yn[:1]))
                    finite = np.isfinite(xn) & np.isfinite(yn)

        if kind == "scatter":
            size = getattr(trace, "size_ch", None)
            diameter = float(getattr(size, "constant", 4.0) or 0.0)
            if getattr(size, "mode", None) == "continuous":
                diameter = max(map(float, getattr(size, "range_px", (2.0, 18.0))))
            rx = max(0.0, diameter / (2.0 * plot_size[0]))
            ry = max(0.0, diameter / (2.0 * plot_size[1]))
            visible = (
                finite & (xn + rx >= 0.0) & (xn - rx <= 1.0) & (yn + ry >= 0.0) & (yn - ry <= 1.0)
            )
            visible &= _emitted_alpha_mask(
                spec,
                rendered_columns,
                emitted,
                trace,
                len(visible),
                emitted_budget or budget,
            )
            count = max(1, int(np.count_nonzero(visible)))
            for name, xl, xh, yl, yh in candidates:
                overlap = (
                    visible & (xn + rx >= xl) & (xn - rx <= xh) & (yn + ry >= yl) & (yn - ry <= yh)
                )
                scores[name] += float(np.count_nonzero(overlap)) / count
            continue

        style = (emitted or {}).get("style") or getattr(trace, "style", {}) or {}
        width = (
            _numeric(style.get("line_width", 1.2), 1.2)
            if kind == "area"
            else _numeric(style.get("width", 1.5), 1.5)
        )
        radius_x = max(0.0, width / (2.0 * plot_size[0]))
        radius_y = max(0.0, width / (2.0 * plot_size[1]))
        path_boxes = tuple(
            (xl - radius_x, xh + radius_x, yl - radius_y, yh + radius_y)
            for xl, xh, yl, yh in candidate_rects
        )
        visible = (
            finite
            & (xn + radius_x >= 0.0)
            & (xn - radius_x <= 1.0)
            & (yn + radius_y >= 0.0)
            & (yn - radius_y <= 1.0)
        )
        count = max(1, int(np.count_nonzero(finite)))
        crossings = _path_intersects_boxes(xn, yn, path_boxes)
        for (name, *_), (xl, xh, yl, yh), crossing in zip(
            candidates, path_boxes, crossings, strict=True
        ):
            inside = visible & (xn >= xl) & (xn <= xh) & (yn >= yl) & (yn <= yh)
            scores[name] += float(np.count_nonzero(inside)) / count
            if crossing:
                scores[name] += 1.0

    primary_x = _axis_info(figure, "x")
    primary_y = _axis_info(figure, "y")
    annotations = (spec or {}).get("annotations") or ()
    if primary_x is not None and primary_y is not None and annotations:
        used = (
            _score_annotations(
                scores,
                candidates,
                annotations,
                primary_x,
                primary_y,
                plot_size,
                spec,
            )
            or used
        )
    if not used:
        return _FALLBACK
    floor = min(scores.values())
    return next(name for name, score in scores.items() if score <= floor + 1e-12)


def _column_values(column: Any) -> Optional[np.ndarray]:
    """The f64 array behind a canonical `Column`, or a bare array unchanged."""
    if column is None:
        return None
    values = getattr(column, "values", column)
    return values if isinstance(values, np.ndarray) else None


def _figure_domains(
    figure: Any, trace: Any
) -> Optional[
    tuple[
        tuple[tuple[float, float], bool, Optional[str], float],
        tuple[tuple[float, float], bool, Optional[str], float],
    ]
]:
    """The displayed x/y limits a trace is drawn against, or None if unknown.

    `Figure._range` already resolves a fixed `domain=` against autorange and
    encodes `reverse=` by returning the pair descending, so read the direction
    back off the ordering rather than re-deriving it from the axis options.
    """
    axis_ids = (
        getattr(trace, "x_axis", None) or "x",
        getattr(trace, "y_axis", None) or "y",
    )
    x_info = _axis_info(figure, axis_ids[0])
    y_info = _axis_info(figure, axis_ids[1])
    if x_info is None or y_info is None:
        return None
    return x_info, y_info


def _axis_info(
    figure: Any, axis_id: str
) -> Optional[tuple[tuple[float, float], bool, Optional[str], float]]:
    """Displayed domain/direction/transform for one figure axis."""
    try:
        lo, hi = (float(value) for value in figure._range(axis_id))
    except Exception:  # noqa: BLE001 — an unrangeable axis simply is not scored
        return None
    reverse = lo > hi
    if reverse:
        lo, hi = hi, lo
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return None
    options = getattr(figure, "axis_options", {}) or {}
    axis = options.get(axis_id) or {}
    scale = axis.get("type") or axis.get("scale")
    constant = axis.get("constant")
    return (lo, hi), reverse, scale, float(constant) if constant else 1.0
