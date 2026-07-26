"""Least-occupied legend placement — the engine behind ``loc="best"``.

`best` is Matplotlib's default `loc`, so it is the spelling users reach for
first. XY resolves it **at payload-build time** into one of the concrete
locations, which is what makes the three renderers agree: the browser client,
the SVG writer and the raster writer all receive a settled `loc` and none of
them needs its own occupancy model. §28 — the choice is recorded on the wire
rather than made three times behind the user's back.

The scoring mirrors Matplotlib's: score every candidate box by the fraction of
sampled marks that land inside it and keep the least occupied, preferring the
earlier candidate on a near-tie so a symmetric series lands where Matplotlib
puts it.

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


def candidate_boxes(
    box_w: float, box_h: float
) -> tuple[tuple[str, float, float, float, float], ...]:
    """The candidate rectangles for a legend of this normalized footprint."""
    cx_lo, cx_hi = 0.5 - box_w / 2.0, 0.5 + box_w / 2.0
    cy_lo, cy_hi = 0.5 - box_h / 2.0, 0.5 + box_h / 2.0
    geometry = {
        "upper right": (1.0 - box_w, 1.0, 1.0 - box_h, 1.0),
        "upper left": (0.0, box_w, 1.0 - box_h, 1.0),
        "lower left": (0.0, box_w, 0.0, box_h),
        "lower right": (1.0 - box_w, 1.0, 0.0, box_h),
        "center right": (1.0 - box_w, 1.0, cy_lo, cy_hi),
        "center left": (0.0, box_w, cy_lo, cy_hi),
        "lower center": (cx_lo, cx_hi, 0.0, box_h),
        "upper center": (cx_lo, cx_hi, 1.0 - box_h, 1.0),
        "center": (cx_lo, cx_hi, cy_lo, cy_hi),
    }
    return tuple((name, *geometry[name]) for name in _CANDIDATE_ORDER)


def legend_footprint(labels: Sequence[str]) -> tuple[float, float]:
    """Fractional footprint of the legend box, grown by row count and the
    longest label, so a crowded legend guards a larger corner region."""
    rows = max(1, len(labels))
    max_len = max((len(str(text)) for text in labels), default=4)
    return min(0.6, 0.12 + 0.03 * max_len), min(0.6, 0.10 + 0.07 * rows)


def normalize(
    xv: np.ndarray,
    yv: np.ndarray,
    x_domain: tuple[float, float],
    y_domain: tuple[float, float],
    *,
    x_reverse: bool = False,
    y_reverse: bool = False,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Sample a series down and project it into the normalized plot box.

    Returns None when the series has no finite pair to score.
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
    xlo, xhi = x_domain
    ylo, yhi = y_domain
    if xhi <= xlo or yhi <= ylo:
        return None
    xn = np.clip((xv[finite] - xlo) / (xhi - xlo), 0.0, 1.0)
    yn = np.clip((yv[finite] - ylo) / (yhi - ylo), 0.0, 1.0)
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


def resolve_for_figure(figure: Any) -> str:
    """Resolve `loc="best"` against a built `Figure`'s own trace arrays."""
    series: list[tuple[np.ndarray, np.ndarray]] = []
    labels: list[str] = []
    for trace in getattr(figure, "traces", ()):
        if getattr(trace, "hidden", False):
            continue
        name = getattr(trace, "name", None)
        if name:
            labels.append(str(name))
        # A trace holds canonical `Column`s, not bare arrays (§27).
        xv, yv = (
            _column_values(getattr(trace, "x", None)),
            _column_values(getattr(trace, "y", None)),
        )
        if xv is None or yv is None:
            continue
        domains = _figure_domains(figure, trace)
        if domains is None:
            continue
        (x_domain, x_reverse), (y_domain, y_reverse) = domains
        projected = normalize(xv, yv, x_domain, y_domain, x_reverse=x_reverse, y_reverse=y_reverse)
        if projected is not None:
            series.append(projected)
    return best_loc(series, labels)


def _column_values(column: Any) -> Optional[np.ndarray]:
    """The f64 array behind a canonical `Column`, or a bare array unchanged."""
    if column is None:
        return None
    values = getattr(column, "values", column)
    return values if isinstance(values, np.ndarray) else None


def _figure_domains(figure: Any, trace: Any) -> Optional[tuple[tuple, tuple]]:
    """The displayed x/y limits a trace is drawn against, or None if unknown.

    `Figure._range` already resolves a fixed `domain=` against autorange and
    encodes `reverse=` by returning the pair descending, so read the direction
    back off the ordering rather than re-deriving it from the axis options.
    """
    axis_ids = (
        getattr(trace, "x_axis", None) or "x",
        getattr(trace, "y_axis", None) or "y",
    )
    out: list[tuple[tuple[float, float], bool]] = []
    for axis_id in axis_ids:
        try:
            lo, hi = (float(v) for v in figure._range(axis_id))
        except Exception:  # noqa: BLE001 — an unrangeable axis simply is not scored
            return None
        reverse = lo > hi
        if reverse:
            lo, hi = hi, lo
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        out.append(((lo, hi), reverse))
    return out[0], out[1]
