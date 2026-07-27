"""Matplotlib plot-type adapters.

This module is deliberately inside :mod:`xy.pyplot`: signatures, return
containers, implicit defaults, and Matplotlib vocabulary never enter the core
package.  Each method emits a small adapter entry that materializes through a
generic public ``xy`` mark.  Expensive 2-D binning is dispatched to the native
Rust kernel rather than NumPy.
"""

from __future__ import annotations

# Runtime imports, not TYPE_CHECKING: `typing.get_type_hints()` on the public
# plotting methods must resolve these annotation names (all stdlib or xy-local).
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from .._typing import ArrayLike, ColorLike, ColorsLike, TableLike
from ._artists import (
    Artist,
    BarContainer,
    ContourSet,
    ErrorbarContainer,
    GroupedBarReturn,
    Line2D,
    PathCollection,
    PieContainer,
    PolyCollection,
    StemContainer,
    StepPatch,
    StreamplotSet,
    Table,
    Text,
    Wedge,
    _contour_legend_colors,
)
from ._colors import (
    PROP_CYCLE,
    cmap_extreme,
    normalize_scalar_grid,
    prepare_boundary_norm,
    resolve_cmap,
    resolve_color,
    resolve_rgba,
    scalar_grid_rgba,
)
from ._fmt import parse_fmt
from ._mathtext import mathtext_to_unicode
from ._rc import rc_figsize_px, rcParams
from ._translate import (
    LINESTYLE_TO_DASH,
    MARKER_TO_SYMBOL,
    check_unsupported,
    line_kwargs,
    not_implemented,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .._typing import ArrayLike, ColorLike, ColorsLike, TableLike


def _from_data(value: Any, data: Any) -> Any:
    if data is not None and isinstance(value, str):
        try:
            return data[value]
        except (KeyError, TypeError):
            pass
    return value


def _line_props(owner: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    props = line_kwargs(kwargs)
    if "color" not in props:
        props["color"] = owner._next_color()
    linestyle = props.pop("linestyle", None)
    if linestyle is not None:
        dash = LINESTYLE_TO_DASH.get(linestyle)
        if dash not in (None, "none"):
            props["dash"] = dash
    return props


def _sequence_param(value: Any, n: int, name: str) -> list[Any]:
    if isinstance(value, str) or np.isscalar(value):
        return [value] * n
    result = list(value)
    if len(result) == 1:
        return result * n
    if len(result) != n:
        raise ValueError(f"{name} must be scalar or have length {n}, got {len(result)}")
    return result


def _cycled_colors(value: Any, n: int, name: str) -> list[str]:
    """Resolve a scalar color or cycle a non-empty color sequence to length ``n``."""
    if n == 0:
        return []
    try:
        scalar = resolve_color(value)
    except (TypeError, ValueError):
        sequence = list(value)
    else:
        if scalar is None:
            raise ValueError(f"{name} must not be None")
        return [scalar] * n
    if not sequence:
        raise ValueError(f"{name} must not be empty")
    resolved: list[str] = []
    for color in sequence:
        item = resolve_color(color)
        if item is None:
            raise ValueError(f"{name} entries must not be None")
        resolved.append(item)
    return [resolved[index % len(resolved)] for index in range(n)]


def _float(value: Any) -> float:
    return float(value)


def _masked_float(value: Any) -> np.ndarray:
    return np.ma.asarray(value, dtype=np.float64).filled(np.nan)


def _reject_spectral_options(where: str, **options: Any) -> None:
    specified = {name: value for name, value in options.items() if value is not None}
    if specified:
        check_unsupported(specified, where)


def _reject_non_default(where: str, option: str, value: Any, *defaults: Any) -> None:
    """Fail loudly on option values the engine cannot honor.

    ``None`` (unspecified) and the exact Matplotlib default pass through.
    """
    if value is None:
        return
    for default in defaults:
        if isinstance(default, bool) or isinstance(value, bool):
            if value is default:
                return
        elif isinstance(default, (int, float)) and isinstance(value, (int, float)):
            if float(value) == float(default):
                return
        else:
            equal = value == default
            if isinstance(equal, bool) and equal:
                return
    raise not_implemented(f"{where}({option}=...)")


def _textprops_kwargs(textprops: Any, where: str) -> dict[str, Any]:
    """Translate a textprops dict onto @text entry kwargs (mirrors text())."""
    source = dict(textprops or {})
    color = source.pop("color", None)
    fontsize = source.pop("fontsize", source.pop("size", None))
    ha = source.pop("ha", source.pop("horizontalalignment", None))
    va = source.pop("va", source.pop("verticalalignment", None))
    weight = source.pop("fontweight", source.pop("weight", None))
    family = source.pop("fontfamily", source.pop("family", None))
    fontstyle = source.pop("fontstyle", source.pop("style", None))
    rotation = source.pop("rotation", None)
    # Axes.pie_label creates unclipped labels before applying textprops.
    # Accepting the matching default keeps that implementation detail from
    # becoming a gallery incompatibility while non-default clipping stays loud.
    _reject_non_default(where, "clip_on", source.pop("clip_on", None), False)
    check_unsupported(source, where)
    out: dict[str, Any] = {}
    if color is not None:
        out["color"] = resolve_color(color)
    if ha is not None:
        out["anchor"] = {"left": "start", "center": "middle", "right": "end"}.get(str(ha), "start")
    style: dict[str, Any] = {}
    if fontsize is not None:
        style["font_size"] = _text_font_size_points(fontsize)
    if va is not None:
        style["vertical_align"] = str(va)
    if weight is not None:
        style["font_weight"] = str(weight)
    if family is not None:
        style["font_family"] = str(family)
    if fontstyle is not None:
        style["font_style"] = _validated_font_style(fontstyle)
    if rotation is not None:
        style["rotation"] = 90.0 if rotation == "vertical" else float(rotation)
    if style:
        out["style"] = style
    return out


def _text_font_size_points(value: Any) -> float:
    """Resolve Matplotlib's named font sizes against the current base size."""
    relative = {
        "xx-small": 0.6,
        "x-small": 0.75,
        "small": 0.85,
        "medium": 1.0,
        "large": 1.2,
        "x-large": 1.45,
        "xx-large": 1.75,
    }
    if isinstance(value, str):
        try:
            return float(rcParams["font.size"]) * relative[value]
        except KeyError as exc:
            raise ValueError(f"unsupported relative font size {value!r}") from exc
    result = float(value)
    if result <= 0:
        raise ValueError("font size must be positive")
    return result


def _validated_font_style(value: Any) -> str:
    result = str(value)
    if result not in {"normal", "italic", "oblique"}:
        raise ValueError("font style must be 'normal', 'italic', or 'oblique'")
    return result


def _bilinear_grid_sample(
    x_coords: np.ndarray, y_coords: np.ndarray, grid: np.ndarray, px: Any, py: Any
) -> np.ndarray:
    """Bilinear samples of a scalar grid; NaN outside the grid bounds."""
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    col = np.clip(np.searchsorted(x_coords, px, side="right") - 1, 0, len(x_coords) - 2)
    row = np.clip(np.searchsorted(y_coords, py, side="right") - 1, 0, len(y_coords) - 2)
    tx = np.clip((px - x_coords[col]) / (x_coords[col + 1] - x_coords[col]), 0.0, 1.0)
    ty = np.clip((py - y_coords[row]) / (y_coords[row + 1] - y_coords[row]), 0.0, 1.0)
    values = (
        grid[row, col] * (1.0 - tx) * (1.0 - ty)
        + grid[row, col + 1] * tx * (1.0 - ty)
        + grid[row + 1, col] * (1.0 - tx) * ty
        + grid[row + 1, col + 1] * tx * ty
    )
    inside = (px >= x_coords[0]) & (px <= x_coords[-1]) & (py >= y_coords[0]) & (py <= y_coords[-1])
    return np.where(inside, values, np.nan)


def _integrate_streamlines(
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    seeds: np.ndarray,
    direction: str,
    max_steps: int,
    max_length: float,
    min_length: float = 0.1,
    broken_streamlines: bool = True,
    density: float | tuple[float, float] = 1.0,
    step_scale: float = 1.0,
    error_scale: float = 1.0,
    skip_occupied_seeds: bool = True,
) -> list[np.ndarray]:
    """Integrate field lines with an adaptive second-order Heun step.

    Matplotlib exposes multipliers for both its maximum integration step and
    accepted local error.  Keeping those controls here (rather than silently
    accepting them at the public API) also gives explicit seeds and unbroken
    streamlines the same accuracy contract.
    """
    x_span = max(float(np.ptp(x_coords)), np.finfo(float).eps)
    y_span = max(float(np.ptp(y_coords)), np.finfo(float).eps)
    density_x, density_y = np.broadcast_to(np.asarray(density, dtype=np.float64), 2)
    mask_width = max(1, int(30 * density_x))
    mask_height = max(1, int(30 * density_y))
    max_step = min(x_span / mask_width, y_span / mask_height) * step_scale
    max_error = 0.003 * error_scale
    occupied: set[tuple[int, int]] = set()

    def mask_cell(px: float, py: float) -> tuple[int, int]:
        mx = int(np.clip(round((px - x_coords[0]) / x_span * (mask_width - 1)), 0, mask_width - 1))
        my = int(
            np.clip(round((py - y_coords[0]) / y_span * (mask_height - 1)), 0, mask_height - 1)
        )
        return mx, my

    signs = {"forward": (1.0,), "backward": (-1.0,), "both": (-1.0, 1.0)}[direction]
    lines: list[np.ndarray] = []
    for seed_x, seed_y in seeds:
        if skip_occupied_seeds and mask_cell(float(seed_x), float(seed_y)) in occupied:
            continue
        trajectory_cells: set[tuple[int, int]] = set()
        branches: list[list[tuple[float, float]]] = []
        for sign in signs:
            px, py = float(seed_x), float(seed_y)
            points = [(px, py)]
            step = max_step
            path_length = 0.0
            for _ in range(max_steps):
                su = float(_bilinear_grid_sample(x_coords, y_coords, u, px, py))
                sv = float(_bilinear_grid_sample(x_coords, y_coords, v, px, py))
                if not (np.isfinite(su) and np.isfinite(sv)):
                    break
                speed = float(np.hypot(su, sv))
                if speed <= np.finfo(float).eps:
                    break
                k1x, k1y = sign * su / speed, sign * sv / speed
                trial_x, trial_y = px + step * k1x, py + step * k1y
                tu = float(_bilinear_grid_sample(x_coords, y_coords, u, trial_x, trial_y))
                tv = float(_bilinear_grid_sample(x_coords, y_coords, v, trial_x, trial_y))
                trial_speed = float(np.hypot(tu, tv))
                if not (np.isfinite(tu) and np.isfinite(tv)) or trial_speed <= np.finfo(float).eps:
                    break
                k2x, k2y = sign * tu / trial_speed, sign * tv / trial_speed
                nx = px + 0.5 * step * (k1x + k2x)
                ny = py + 0.5 * step * (k1y + k2y)
                error = float(
                    np.hypot(
                        (nx - trial_x) / x_span,
                        (ny - trial_y) / y_span,
                    )
                )
                if error >= max_error:
                    step = max(
                        max_step * 1e-4,
                        min(max_step, 0.85 * step * np.sqrt(max_error / error)),
                    )
                    continue
                if not (x_coords[0] <= nx <= x_coords[-1] and y_coords[0] <= ny <= y_coords[-1]):
                    break
                cell = mask_cell(nx, ny)
                if broken_streamlines and cell in occupied and cell not in trajectory_cells:
                    break
                path_length += float(np.hypot((nx - px) / x_span, (ny - py) / y_span))
                px, py = nx, ny
                points.append((px, py))
                trajectory_cells.add(cell)
                if path_length >= max_length:
                    break
                if error == 0.0:
                    step = max_step
                else:
                    step = min(max_step, 0.85 * step * np.sqrt(max_error / error))
            branches.append(points)
        combined = branches[0][::-1] + branches[1][1:] if len(branches) == 2 else branches[0]
        combined_array = np.asarray(combined, dtype=np.float64)
        if len(combined_array) >= 2:
            length = float(
                np.hypot(
                    np.diff(combined_array[:, 0]) / x_span,
                    np.diff(combined_array[:, 1]) / y_span,
                ).sum()
            )
        else:
            length = 0.0
        if length >= min_length:
            lines.append(combined_array)
            occupied.update(trajectory_cells)
    return lines


# On/off spans within one dash cycle; segments marks have no screen-space dash
# primitive, so dash geometry is emitted as data-space sub-segments.
_DASH_SEGMENT_PATTERNS: dict[str, tuple[tuple[float, float], ...]] = {
    "--": ((0.0, 0.62),),
    "-.": ((0.0, 0.5), (0.66, 0.8)),
    ":": ((0.0, 0.18), (0.5, 0.68)),
}

_LINESTYLE_TO_FMT_TOKEN = {"solid": "-", "dashed": "--", "dashdot": "-.", "dotted": ":"}


def _dash_segment_pattern(where: str, linestyle: Any) -> Optional[tuple[tuple[float, float], ...]]:
    """Dash pattern for a linestyle token or name; None means solid."""
    if linestyle is None:
        return None
    key = _LINESTYLE_TO_FMT_TOKEN.get(str(linestyle), str(linestyle))
    if key in ("-", "", " ", "none", "None"):
        return None
    pattern = _DASH_SEGMENT_PATTERNS.get(key)
    if pattern is None:
        raise not_implemented(f"{where}(linestyle={linestyle!r})")
    return pattern


def _dashed_segments(
    x0: np.ndarray,
    y0: np.ndarray,
    x1: np.ndarray,
    y1: np.ndarray,
    pattern: tuple[tuple[float, float], ...],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split segments into dash pieces; the cycle repeats ~8× per longest run."""
    lengths = np.hypot(x1 - x0, y1 - y0)
    finite = lengths[np.isfinite(lengths)]
    longest = float(finite.max()) if len(finite) else 0.0
    if longest <= 0.0:
        return x0, y0, x1, y1
    period = longest / 8.0
    pieces: tuple[list[float], list[float], list[float], list[float]] = ([], [], [], [])
    for ax, ay, bx, by, length in zip(x0, y0, x1, y1, lengths, strict=True):
        if not np.isfinite(length) or length <= 0.0:
            continue
        for cycle in range(int(np.ceil(length / period))):
            for start, stop in pattern:
                t0 = (cycle + start) * period / length
                t1 = min((cycle + stop) * period / length, 1.0)
                if t0 >= 1.0 or t1 <= t0:
                    continue
                pieces[0].append(ax + (bx - ax) * t0)
                pieces[1].append(ay + (by - ay) * t0)
                pieces[2].append(ax + (bx - ax) * t1)
                pieces[3].append(ay + (by - ay) * t1)
    return (
        np.asarray(pieces[0], dtype=np.float64),
        np.asarray(pieces[1], dtype=np.float64),
        np.asarray(pieces[2], dtype=np.float64),
        np.asarray(pieces[3], dtype=np.float64),
    )


def _limit_error(error: Any, lower_limits: Any, upper_limits: Any, size: int) -> Any:
    """Convert limit flags into Matplotlib's two-sided error-array geometry."""
    if error is None or (not np.any(lower_limits) and not np.any(upper_limits)):
        return error
    raw = np.asarray(error, dtype=np.float64)
    if raw.ndim >= 2 and raw.shape[0] == 2:
        low = np.broadcast_to(raw[0], (size,)).copy()
        high = np.broadcast_to(raw[1], (size,)).copy()
    else:
        low = np.broadcast_to(raw, (size,)).copy()
        high = np.broadcast_to(raw, (size,)).copy()
    low[np.broadcast_to(np.asarray(lower_limits, dtype=bool), (size,))] = 0.0
    high[np.broadcast_to(np.asarray(upper_limits, dtype=bool), (size,))] = 0.0
    return np.vstack((low, high))


def _error_sides(error: Any, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Return broadcast lower and upper error magnitudes."""
    raw = np.asarray(error, dtype=np.float64)
    if raw.ndim >= 2 and raw.shape[0] == 2:
        return (
            np.broadcast_to(raw[0], (size,)),
            np.broadcast_to(raw[1], (size,)),
        )
    values = np.broadcast_to(raw, (size,))
    return values, values


def _plain_label(value: Any) -> str:
    text = str(value).replace("$", "")
    for source, target in {
        "\\mathdefault": "",
        "\\leq": "<=",
        "\\%": "%",
    }.items():
        text = text.replace(source, target)
    return text.replace("_{", "").replace("^{", "^").replace("}", "")


def _nice_contour_levels(lo: float, hi: float, count: int) -> np.ndarray:
    """Approximate MaxNLocator's expanded, human-readable contour boundaries."""
    if count < 1 or not np.isfinite([lo, hi]).all() or lo == hi:
        return np.linspace(lo, hi if hi != lo else lo + 1.0, max(2, count + 1))
    raw = abs(hi - lo) / (count + 1)
    power = 10.0 ** np.floor(np.log10(raw))
    scaled = raw / power
    nice = next(
        (step for step in (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0) if step >= scaled),
        10.0,
    )
    step = nice * power
    start = np.floor((lo + step * 1e-9) / step) * step
    stop = np.ceil((hi - step * 1e-9) / step) * step
    levels = np.arange(start, stop + step * 0.5, step)
    return levels if len(levels) >= 2 else np.asarray([lo, hi], dtype=np.float64)


def _joined_contour_paths(
    x0: np.ndarray,
    x1: np.ndarray,
    y0: np.ndarray,
    y1: np.ndarray,
) -> list[np.ndarray]:
    """Join a marching-squares segment soup into deterministic polylines.

    The native contour kernel deliberately returns independent segments: that
    is ideal for the renderers, but Matplotlib's label placement operates on
    connected contour paths.  Quantized endpoint keys absorb only the
    round-off introduced by interpolation; the tolerance is many orders of
    magnitude below a visible data-space displacement.
    """
    segments = np.column_stack((x0, y0, x1, y1)).astype(np.float64, copy=False)
    segments = segments[np.isfinite(segments).all(axis=1)]
    if not len(segments):
        return []
    span = max(float(np.ptp(segments[:, (0, 2)])), float(np.ptp(segments[:, (1, 3)])), 1.0)
    tolerance = span * 1e-10

    def key(x: float, y: float) -> tuple[int, int]:
        return round(x / tolerance), round(y / tolerance)

    endpoints: list[tuple[tuple[int, int], tuple[int, int]]] = []
    positions: dict[tuple[int, int], tuple[float, float]] = {}
    adjacency: dict[tuple[int, int], list[int]] = {}
    for xa, ya, xb, yb in segments:
        ka, kb = key(float(xa), float(ya)), key(float(xb), float(yb))
        if ka == kb:
            continue
        edge_index = len(endpoints)
        endpoints.append((ka, kb))
        positions.setdefault(ka, (float(xa), float(ya)))
        positions.setdefault(kb, (float(xb), float(yb)))
        adjacency.setdefault(ka, []).append(edge_index)
        adjacency.setdefault(kb, []).append(edge_index)
    if not endpoints:
        return []

    unused = set(range(len(endpoints)))
    paths: list[np.ndarray] = []
    while unused:
        seed = min(unused)
        # Discover the whole unused connected component so an open contour
        # starts at its true boundary even when the native segment selected as
        # ``seed`` happens to lie in the middle.
        component = {seed}
        frontier = [seed]
        while frontier:
            edge = frontier.pop()
            for node in endpoints[edge]:
                for neighbor in adjacency.get(node, ()):
                    if neighbor in unused and neighbor not in component:
                        component.add(neighbor)
                        frontier.append(neighbor)
        component_degree: dict[tuple[int, int], int] = {}
        for edge in component:
            for node in endpoints[edge]:
                component_degree[node] = component_degree.get(node, 0) + 1
        a, b = endpoints[seed]
        # Open contours start at an endpoint. Closed contours have degree two
        # everywhere and may start at the first native segment.
        endpoints_of_component = sorted(
            node for node, degree in component_degree.items() if degree != 2
        )
        current = endpoints_of_component[0] if endpoints_of_component else a
        points = [positions[current]]
        previous: tuple[int, int] | None = None
        while True:
            candidates = [edge for edge in adjacency.get(current, ()) if edge in unused]
            if not candidates:
                break
            if len(candidates) == 1 or previous is None:
                edge = min(candidates)
            else:
                # At the rare grid vertex shared by more than two segments,
                # continue as straight as possible instead of arbitrarily
                # switching contour branches.
                px, py = positions[previous]
                cx, cy = positions[current]
                incoming = np.asarray((cx - px, cy - py), dtype=np.float64)
                incoming_norm = float(np.hypot(*incoming))

                def continuation_score(
                    candidate: int,
                    *,
                    _current: tuple[int, int] = current,
                    _cx: float = cx,
                    _cy: float = cy,
                    _incoming: np.ndarray = incoming,
                    _incoming_norm: float = incoming_norm,
                ) -> float:
                    ca, cb = endpoints[candidate]
                    other = cb if ca == _current else ca
                    ox, oy = positions[other]
                    outgoing = np.asarray((ox - _cx, oy - _cy), dtype=np.float64)
                    norm = _incoming_norm * float(np.hypot(*outgoing))
                    return float(np.dot(_incoming, outgoing) / norm) if norm else -2.0

                edge = max(
                    candidates,
                    key=lambda candidate: (continuation_score(candidate), -candidate),
                )
            unused.remove(edge)
            ea, eb = endpoints[edge]
            next_key = eb if ea == current else ea
            previous, current = current, next_key
            points.append(positions[current])
        if len(points) >= 2:
            paths.append(np.asarray(points, dtype=np.float64))
    return paths


def _path_cumulative(screen_path: np.ndarray) -> np.ndarray:
    return np.concatenate(
        ([0.0], np.cumsum(np.hypot(*np.diff(screen_path, axis=0).T), dtype=np.float64))
    )


def _path_interpolate(path: np.ndarray, cumulative: np.ndarray, distance: float) -> np.ndarray:
    """Interpolate one point at a screen-space curvilinear distance."""
    distance = float(np.clip(distance, 0.0, cumulative[-1]))
    index = min(int(np.searchsorted(cumulative, distance, side="right") - 1), len(path) - 2)
    index = max(0, index)
    length = cumulative[index + 1] - cumulative[index]
    fraction = 0.0 if length <= 0 else (distance - cumulative[index]) / length
    return path[index] + (path[index + 1] - path[index]) * fraction


def _contour_label_location(
    path: np.ndarray,
    screen_path: np.ndarray,
    label_width: float,
    font_height: float,
    occupied: list[tuple[float, float, float]],
    *,
    rightside_up: bool,
) -> dict[str, Any] | None:
    """Pick the straightest collision-free label site along one contour."""
    cumulative = _path_cumulative(screen_path)
    total = float(cumulative[-1])
    if total <= 0.0:
        return None
    extent = np.ptp(screen_path, axis=0)
    if total < 1.5 * label_width or not np.any(extent > 1.2 * label_width):
        return None
    half = min(label_width * 0.5, total * 0.45)
    count = max(24, min(64, 2 * int(np.ceil(total / max(label_width, 1.0)))))
    distances = np.linspace(half, total - half, count)
    candidates: list[tuple[float, float, np.ndarray, float]] = []
    for distance in distances:
        before = _path_interpolate(screen_path, cumulative, distance - half)
        after = _path_interpolate(screen_path, cumulative, distance + half)
        direction = after - before
        norm = float(np.hypot(*direction))
        if norm <= np.finfo(float).eps:
            continue
        inside = (cumulative >= distance - half) & (cumulative <= distance + half)
        window = np.vstack((before, screen_path[inside], after))
        deviation = np.abs(
            direction[0] * (before[1] - window[:, 1]) - direction[1] * (before[0] - window[:, 0])
        )
        straightness = float(np.mean(deviation) / norm)
        point = _path_interpolate(screen_path, cumulative, distance)
        angle = float(np.rad2deg(np.arctan2(direction[1], direction[0])))
        if rightside_up:
            angle = (angle + 90.0) % 180.0 - 90.0
        candidates.append((straightness, float(distance), point, angle))
    if not candidates:
        return None
    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    collision_width = max(label_width, 2.4 * font_height)
    clear = [
        candidate
        for candidate in candidates
        if all(
            float(np.hypot(*(candidate[2] - np.asarray(prior[:2]))))
            >= 0.75 * (collision_width + prior[2])
            for prior in occupied
        )
    ]
    if clear:
        selected = clear[0]
    elif occupied:
        # A small nested contour may have no fully clear point. Prefer the
        # candidate with the most display-space breathing room rather than
        # falling back to the straightest point directly under another label.
        selected = max(
            candidates,
            key=lambda candidate: min(
                float(np.hypot(*(candidate[2] - np.asarray(prior[:2]))))
                / max(1.0, 0.5 * (collision_width + prior[2]))
                for prior in occupied
            ),
        )
    else:
        selected = candidates[0]
    _, distance, screen_point, angle = selected
    occupied.append((float(screen_point[0]), float(screen_point[1]), collision_width))
    return {
        "position": _path_interpolate(path, cumulative, distance),
        "screen_position": screen_point,
        "angle": angle,
        "distance": distance,
        "cumulative": cumulative,
    }


def _nearest_contour_location(
    query: tuple[float, float],
    paths: list[tuple[int, np.ndarray, np.ndarray]],
    *,
    rightside_up: bool,
) -> dict[str, Any] | None:
    """Project a manual data-space request onto the nearest contour path."""
    query_point = np.asarray(query, dtype=np.float64)
    best: tuple[float, int, np.ndarray, np.ndarray, float, np.ndarray] | None = None
    for level_index, path, screen_path in paths:
        cumulative = _path_cumulative(screen_path)
        for index, (start, end) in enumerate(pairwise(screen_path)):
            delta = end - start
            norm2 = float(np.dot(delta, delta))
            fraction = (
                0.0
                if norm2 <= np.finfo(float).eps
                else float(np.clip(np.dot(query_point - start, delta) / norm2, 0.0, 1.0))
            )
            projected = start + fraction * delta
            distance2 = float(np.dot(projected - query_point, projected - query_point))
            along = float(
                cumulative[index] + fraction * (cumulative[index + 1] - cumulative[index])
            )
            candidate = (distance2, level_index, path, screen_path, along, delta)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return None
    _, level_index, path, screen_path, distance, direction = best
    cumulative = _path_cumulative(screen_path)
    angle = float(np.rad2deg(np.arctan2(direction[1], direction[0])))
    if rightside_up:
        angle = (angle + 90.0) % 180.0 - 90.0
    return {
        "level_index": level_index,
        "path": path,
        "screen_path": screen_path,
        "position": _path_interpolate(path, cumulative, distance),
        "screen_position": _path_interpolate(screen_path, cumulative, distance),
        "angle": angle,
        "distance": distance,
        "cumulative": cumulative,
    }


def _contour_visible_segments(
    path: np.ndarray,
    cumulative: np.ndarray,
    excluded: list[tuple[float, float]],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return path pieces outside the merged screen-space exclusion windows."""
    intervals: list[tuple[float, float]] = []
    for start, stop in sorted(excluded):
        start = max(0.0, float(start))
        stop = min(float(cumulative[-1]), float(stop))
        if start >= stop:
            continue
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = intervals[-1][0], max(intervals[-1][1], stop)
        else:
            intervals.append((start, stop))
    result: list[tuple[np.ndarray, np.ndarray]] = []
    for start, stop in pairwise(cumulative):
        pieces = [(float(start), float(stop))]
        for excluded_start, excluded_stop in intervals:
            next_pieces: list[tuple[float, float]] = []
            for piece_start, piece_stop in pieces:
                if excluded_stop <= piece_start or excluded_start >= piece_stop:
                    next_pieces.append((piece_start, piece_stop))
                    continue
                if piece_start < excluded_start:
                    next_pieces.append((piece_start, excluded_start))
                if excluded_stop < piece_stop:
                    next_pieces.append((excluded_stop, piece_stop))
            pieces = next_pieces
            if not pieces:
                break
        for piece_start, piece_stop in pieces:
            if piece_stop <= piece_start:
                continue
            a = _path_interpolate(path, cumulative, piece_start)
            b = _path_interpolate(path, cumulative, piece_stop)
            result.append((a, b))
    return result


def _segment_values(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if np.issubdtype(array.dtype, np.datetime64) or (
        array.dtype == object and array.size and isinstance(array.reshape(-1)[0], (date, datetime))
    ):
        return np.asarray(array, dtype="datetime64[ms]").astype(np.int64).astype(np.float64)
    return np.asarray(array, dtype=np.float64)


def _uniform_mesh_axes(
    x: Any, y: Any, shape: tuple[int, int]
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Return heatmap centers when a mesh is uniform and rectilinear."""
    rows, cols = shape
    xa = np.asarray(x)
    ya = np.asarray(y)
    if xa.ndim == 2 and ya.ndim == 2:
        if xa.shape != ya.shape:
            raise ValueError("pcolormesh X and Y must have matching shapes")
        if not np.allclose(xa, xa[:1, :], equal_nan=True) or not np.allclose(
            ya, ya[:, :1], equal_nan=True
        ):
            return None
        xa, ya = xa[0], ya[:, 0]
    if xa.ndim != 1 or ya.ndim != 1:
        raise ValueError("pcolormesh X and Y must be 1-D or rectilinear 2-D arrays")

    def centers(values: np.ndarray, size: int, name: str) -> Optional[np.ndarray]:
        values = values.astype(np.float64, copy=False)
        if len(values) == size:
            result = values
            spacing = np.diff(result)
        elif len(values) == size + 1:
            result = (values[:-1] + values[1:]) * 0.5
            spacing = np.diff(values)
        else:
            raise ValueError(
                f"pcolormesh {name} has length {len(values)}; expected {size} or {size + 1}"
            )
        if len(spacing) > 1 and not np.allclose(spacing, spacing[0]):
            return None
        return result

    x_centers = centers(xa, cols, "X")
    y_centers = centers(ya, rows, "Y")
    if x_centers is None or y_centers is None:
        return None
    return x_centers, y_centers


def _gouraud_rect_axes(
    x: Any, y: Any, shape: tuple[int, int]
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Return same-shape, uniform rectilinear vertices for Gouraud shading."""
    rows, cols = shape
    xa, ya = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if xa.ndim == ya.ndim == 2:
        if xa.shape != shape or ya.shape != shape:
            raise ValueError("pcolormesh Gouraud X, Y, and C must have matching shapes")
        if not np.allclose(xa, xa[:1, :], equal_nan=True) or not np.allclose(
            ya, ya[:, :1], equal_nan=True
        ):
            return None
        xa, ya = xa[0], ya[:, 0]
    elif xa.shape != (cols,) or ya.shape != (rows,):
        raise ValueError("pcolormesh Gouraud X, Y, and C must have matching shapes")
    if (len(xa) > 2 and not np.allclose(np.diff(xa), np.diff(xa)[0])) or (
        len(ya) > 2 and not np.allclose(np.diff(ya), np.diff(ya)[0])
    ):
        return None
    return xa, ya


def _bilinear_grid(grid: np.ndarray, width: int, height: int) -> np.ndarray:
    """Small NumPy-only bilinear expansion used by regular Gouraud meshes."""
    if grid.ndim == 3:
        return np.stack(
            [_bilinear_grid(grid[..., channel], width, height) for channel in range(grid.shape[2])],
            axis=-1,
        )
    source_y = np.linspace(0.0, 1.0, grid.shape[0])
    source_x = np.linspace(0.0, 1.0, grid.shape[1])
    target_y = np.linspace(0.0, 1.0, height)
    target_x = np.linspace(0.0, 1.0, width)
    horizontal = np.vstack([np.interp(target_x, source_x, row) for row in grid])
    return np.vstack(
        [np.interp(target_y, source_y, horizontal[:, column]) for column in range(width)]
    ).T


def _regular_mesh_axes(x: Any, y: Any, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Return axes for a rectilinear grid, including non-uniform spacing."""
    rows, cols = shape
    xa, ya = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if xa.ndim == ya.ndim == 2:
        if xa.shape != shape or ya.shape != shape:
            raise ValueError("grid X and Y must match the data shape")
        if not np.allclose(xa, xa[:1, :], equal_nan=True) or not np.allclose(
            ya, ya[:, :1], equal_nan=True
        ):
            raise ValueError("grid X and Y must be rectilinear")
        xa, ya = xa[0], ya[:, 0]
    if xa.shape != (cols,) or ya.shape != (rows,):
        raise ValueError(f"grid X and Y must have lengths {cols} and {rows}")
    return xa, ya


def _triangulation_inputs(
    args: tuple[Any, ...], triangles: Any, data: Any
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[Any, ...]]:
    """Normalize matplotlib's `(x, y, ...)` or Triangulation-object forms."""
    if args and all(hasattr(args[0], name) for name in ("x", "y", "triangles")):
        triangulation = args[0]
        x = np.asarray(triangulation.x, dtype=np.float64)
        y = np.asarray(triangulation.y, dtype=np.float64)
        topology = np.asarray(triangulation.triangles, dtype=np.int64)
        mask = getattr(triangulation, "mask", None)
        if mask is not None:
            topology = topology[~np.asarray(mask, dtype=bool)]
        rest = args[1:]
    else:
        if len(args) < 2:
            raise TypeError("triangular plot requires x and y coordinates")
        x = np.asarray(_from_data(args[0], data), dtype=np.float64)
        y = np.asarray(_from_data(args[1], data), dtype=np.float64)
        rest = args[2:]
        if triangles is None and rest:
            candidate = np.asarray(rest[0])
            if candidate.ndim == 2 and candidate.shape[1:] == (3,):
                triangles = rest[0]
                rest = rest[1:]
        if triangles is None:
            from xy import kernels

            if len(x) > 10_000:
                raise ValueError(
                    "automatic Delaunay triangulation is limited to 10,000 points; "
                    "pass explicit triangles for larger inputs"
                )
            topology = kernels.delaunay_triangles(x, y)
        else:
            topology = np.asarray(_from_data(triangles, data), dtype=np.int64)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
        raise ValueError("triangular plot x and y must be equal-length 1-D arrays")
    if topology.ndim != 2 or topology.shape[1:] != (3,):
        raise ValueError("triangles must have shape (n, 3)")
    return x, y, np.ascontiguousarray(topology, dtype=np.int64), rest


def _triangle_levels(values: np.ndarray, levels: Any) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        raise ValueError("triangular contour z must contain a finite value")
    if isinstance(levels, (int, np.integer)) and not isinstance(levels, (bool, np.bool_)):
        count = int(levels)
        if count <= 0 or count > 256:
            raise ValueError("levels must be between 1 and 256")
        lo, hi = float(finite.min()), float(finite.max())
        if lo == hi:
            lo, hi = lo - 0.5, hi + 0.5
        return np.linspace(lo, hi, count + 2, dtype=np.float64)[1:-1]
    result = np.asarray(levels, dtype=np.float64).reshape(-1)
    if len(result) == 0 or len(result) > 256 or not np.isfinite(result).all():
        raise ValueError("levels must contain 1 to 256 finite values")
    return np.sort(result)


class PlotTypeMixin:
    """Additional Matplotlib chart methods kept out of the core ``Axes`` type."""

    if TYPE_CHECKING:

        def _add(self, kind: str, entry: dict[str, Any]) -> dict[str, Any]: ...

        def _next_color(self) -> str: ...

        def _mpl_dash(self, dash: Any, linewidth: Any) -> Any: ...

        def _point_scale(self) -> float: ...

        def _entry_extent(self, axis: str) -> tuple[float, float]: ...

        def _categorical_position(self, axis: str, label: Any) -> float: ...

        def _transform_points(
            self, x: Any, y: Any, transform: Any
        ) -> tuple[np.ndarray, np.ndarray]: ...

        def plot(self, *args: Any, **kwargs: Any) -> list[Line2D]: ...

        def bar(self, *args: Any, **kwargs: Any) -> BarContainer: ...

        def barh(self, *args: Any, **kwargs: Any) -> BarContainer: ...

        def imshow(self, *args: Any, **kwargs: Any) -> Any: ...

        def axhline(self, *args: Any, **kwargs: Any) -> Line2D: ...

        def set_xticks(self, *args: Any, **kwargs: Any) -> None: ...

        def set_yticks(self, *args: Any, **kwargs: Any) -> None: ...

        def set_xlim(self, *args: Any, **kwargs: Any) -> None: ...

        def set_ylim(self, *args: Any, **kwargs: Any) -> None: ...

        def set_xscale(self, scale: str, **kwargs: Any) -> None: ...

        def set_yscale(self, scale: str, **kwargs: Any) -> None: ...

        def _axis_props(self, axis: str) -> dict[str, Any]: ...

        def _invalidate(self) -> None: ...

    def semilogx(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        """Like ``plot``, but sets the x-axis to log scale first.

        Accepts ``base``/``basex``, ``subs``/``subsx``, and
        ``nonpositive``/``nonposx`` in addition to every ``plot`` keyword.
        """
        base = kwargs.pop("base", kwargs.pop("basex", None))
        subs = kwargs.pop("subs", kwargs.pop("subsx", None))
        nonpositive = kwargs.pop("nonpositive", kwargs.pop("nonposx", "clip"))
        self.set_xscale(
            "log", base=10 if base is None else base, subs=subs, nonpositive=nonpositive
        )
        return self.plot(*args, **kwargs)

    def semilogy(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        """Like ``plot``, but sets the y-axis to log scale first.

        Accepts ``base``/``basey``, ``subs``/``subsy``, and
        ``nonpositive``/``nonposy`` in addition to every ``plot`` keyword.
        """
        base = kwargs.pop("base", kwargs.pop("basey", None))
        subs = kwargs.pop("subs", kwargs.pop("subsy", None))
        nonpositive = kwargs.pop("nonpositive", kwargs.pop("nonposy", "clip"))
        self.set_yscale(
            "log", base=10 if base is None else base, subs=subs, nonpositive=nonpositive
        )
        return self.plot(*args, **kwargs)

    def loglog(self, *args: Any, **kwargs: Any) -> list[Line2D]:
        """Like ``plot``, but sets both axes to log scale first.

        Accepts ``base``, ``subs``, and ``nonpositive`` in addition to every
        ``plot`` keyword.
        """
        base = kwargs.pop("base", None)
        subs = kwargs.pop("subs", None)
        nonpositive = kwargs.pop("nonpositive", "clip")
        scale_kwargs = {
            "base": 10 if base is None else base,
            "subs": subs,
            "nonpositive": nonpositive,
        }
        self.set_xscale("log", **scale_kwargs)
        self.set_yscale("log", **scale_kwargs)
        return self.plot(*args, **kwargs)

    def hlines(
        self,
        y: float | ArrayLike,
        xmin: float | ArrayLike,
        xmax: float | ArrayLike,
        colors: Any = None,
        linestyles: str = "solid",
        label: str = "",
        **kwargs: Any,
    ) -> PolyCollection:
        """Horizontal line segments from ``xmin`` to ``xmax`` at each ``y``.

        ``colors`` (a scalar or sequence; the first entry wins) and
        ``linestyles`` style the segments; supported keywords are
        ``linewidth``/``linewidths``/``lw``, ``alpha``, ``data``, and
        ``transform``. Dashed linestyles are emitted as data-space
        sub-segments. Unsupported keywords raise loudly.
        """
        width = kwargs.pop("linewidth", kwargs.pop("linewidths", kwargs.pop("lw", 1.2)))
        alpha = kwargs.pop("alpha", None)
        data = kwargs.pop("data", None)
        y, xmin, xmax = (_from_data(value, data) for value in (y, xmin, xmax))
        transform = kwargs.pop("transform", None)
        check_unsupported(kwargs, "hlines()")
        yv, x0, x1 = np.broadcast_arrays(y, xmin, xmax)
        yv, x0, x1 = (_segment_values(value) for value in (yv, x0, x1))
        if transform == "yaxis transform":
            lo, hi = self._entry_extent("x")
            x0, x1 = lo + x0 * (hi - lo), lo + x1 * (hi - lo)
        dash_pattern = _dash_segment_pattern("hlines", linestyles)
        sx0, sy0, sx1, sy1 = x0.reshape(-1), yv.reshape(-1), x1.reshape(-1), yv.reshape(-1)
        if transform not in (None, "yaxis transform"):
            sx0, sy0 = self._transform_points(sx0, sy0, transform)
            sx1, sy1 = self._transform_points(sx1, sy1, transform)
        if dash_pattern is not None:
            sx0, sy0, sx1, sy1 = _dashed_segments(sx0, sy0, sx1, sy1, dash_pattern)
        chosen_color = colors
        if chosen_color is not None and not isinstance(chosen_color, str) and len(chosen_color):
            chosen_color = chosen_color[0]
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (sx0, sy0, sx1, sy1),
                "kwargs": {
                    "color": resolve_color(chosen_color)
                    if chosen_color is not None
                    else self._next_color(),
                    "width": _float(np.asarray(width).reshape(-1)[0]),
                    "opacity": 1.0 if alpha is None else float(alpha),
                    "name": str(label) if label else None,
                },
            },
        )
        return PolyCollection(self, entry)

    def vlines(
        self,
        x: float | ArrayLike,
        ymin: float | ArrayLike,
        ymax: float | ArrayLike,
        colors: str | ColorsLike | None = None,
        linestyles: str = "solid",
        label: str = "",
        **kwargs: Any,
    ) -> PolyCollection:
        """Vertical line segments from ``ymin`` to ``ymax`` at each ``x``.

        The vertical twin of ``hlines``: supported keywords are
        ``linewidth``/``linewidths``/``lw``, ``color``, ``alpha``, ``data``,
        and ``transform``; dashed linestyles become data-space sub-segments,
        and unsupported keywords raise loudly.
        """
        data = kwargs.pop("data", None)
        x, ymin, ymax = (_from_data(value, data) for value in (x, ymin, ymax))
        xv, y0, y1 = np.broadcast_arrays(x, ymin, ymax)
        xv, y0, y1 = (_segment_values(value) for value in (xv, y0, y1))
        return self._vlines_entry(xv, y0, y1, colors, linestyles, label, kwargs)

    def _vlines_entry(
        self,
        xv: np.ndarray,
        y0: np.ndarray,
        y1: np.ndarray,
        colors: Any,
        linestyles: Any,
        label: Any,
        kwargs: dict[str, Any],
    ) -> PolyCollection:
        width = kwargs.pop("linewidth", kwargs.pop("linewidths", kwargs.pop("lw", 1.2)))
        alpha = kwargs.pop("alpha", None)
        color = kwargs.pop("color", colors)
        if (
            color is not None
            and not isinstance(color, str)
            and len(color)
            and not (len(color) in (3, 4) and all(np.isscalar(value) for value in color))
        ):
            color = color[0]
        transform = kwargs.pop("transform", None)
        dash_pattern = _dash_segment_pattern("vlines", linestyles)
        if transform == "xaxis transform":
            lo, hi = self._entry_extent("y")
            y0, y1 = lo + y0 * (hi - lo), lo + y1 * (hi - lo)
        check_unsupported(kwargs, "vlines()")
        sx0, sy0, sx1, sy1 = xv.reshape(-1), y0.reshape(-1), xv.reshape(-1), y1.reshape(-1)
        if transform not in (None, "xaxis transform"):
            sx0, sy0 = self._transform_points(sx0, sy0, transform)
            sx1, sy1 = self._transform_points(sx1, sy1, transform)
        if dash_pattern is not None:
            sx0, sy0, sx1, sy1 = _dashed_segments(sx0, sy0, sx1, sy1, dash_pattern)
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (sx0, sy0, sx1, sy1),
                "kwargs": {
                    "color": resolve_color(color) if color is not None else self._next_color(),
                    "width": _float(np.asarray(width).reshape(-1)[0]),
                    "opacity": 1.0 if alpha is None else float(alpha),
                    "name": str(label) if label else None,
                },
            },
        )
        return PolyCollection(self, entry)

    def broken_barh(
        self, xranges: ArrayLike, yrange: tuple[float | str, float], **kwargs: Any
    ) -> PolyCollection:
        """A sequence of horizontal bars at one vertical position.

        ``xranges`` is a sequence of ``(start, width)`` pairs and ``yrange`` a
        single ``(y, height)``. Supported keywords:
        ``facecolors``/``facecolor``/``color``, ``edgecolors``/``edgecolor``,
        ``linewidth``/``linewidths``, ``alpha``, ``label``, and ``align``
        (``"center"`` only). Unsupported keywords raise loudly.
        """
        ranges = np.asarray(xranges, dtype=np.float64)
        if ranges.ndim != 2 or ranges.shape[1:] != (2,):
            raise ValueError("broken_barh xranges must have shape (n, 2)")
        raw_ymin, height = yrange
        height = float(height)
        ymin = (
            self._categorical_position("y", raw_ymin) - height * 0.5
            if isinstance(raw_ymin, str)
            else float(raw_ymin)
        )
        color = kwargs.pop("facecolors", kwargs.pop("facecolor", kwargs.pop("color", None)))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        edgecolor = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("linewidths", None))
        align = kwargs.pop("align", "center")
        if align != "center":
            raise not_implemented(f"broken_barh(align={align!r})")
        check_unsupported(kwargs, "broken_barh()")
        entry_kwargs: dict[str, Any] = {
            "base": ranges[:, 0],
            "color": resolve_color(color) if color is not None else self._next_color(),
            "name": None if label is None else str(label),
            "opacity": 1.0 if alpha is None else float(alpha),
            "orientation": "horizontal",
            "width": height,
        }
        if edgecolor is not None:
            entry_kwargs["stroke"] = resolve_color(edgecolor)
            entry_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "bar",
            {
                "x": np.full(len(ranges), ymin + height * 0.5),
                "y": ranges[:, 1],
                "kwargs": entry_kwargs,
            },
        )
        return PolyCollection(self, entry)

    def fill_betweenx(
        self,
        y: ArrayLike,
        x1: float | ArrayLike,
        x2: float | ArrayLike = 0,
        where: ArrayLike | None = None,
        **kwargs: Any,
    ) -> PolyCollection:
        """Fill the area between two vertical curves ``x1`` and ``x2``.

        The vertical twin of ``fill_between``: ``where`` masks the fill to a
        boolean condition. Supported keywords: ``color``/``facecolor``,
        ``alpha``, ``label``, and ``data``. ``edgecolor``, ``linewidth``,
        ``interpolate=True``, ``step``, ``transform``, and any unknown
        keyword raise loudly.
        """
        data = kwargs.pop("data", None)
        if data is not None:
            # resolve string keys before any float coercion sees them
            y, x1, x2 = (_from_data(value, data) for value in (y, x1, x2))
        yv, left, right = np.broadcast_arrays(
            _masked_float(y),
            _masked_float(x1),
            _masked_float(x2),
        )
        if yv.ndim != 1 or len(yv) < 2:
            raise ValueError(
                "fill_betweenx inputs must resolve to 1-D arrays with at least two points"
            )
        color = kwargs.pop("color", kwargs.pop("facecolor", None))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        edgecolor = kwargs.pop("edgecolor", None)
        linewidth = kwargs.pop("linewidth", None)
        interpolate = kwargs.pop("interpolate", False)
        step = kwargs.pop("step", None)
        transform = kwargs.pop("transform", None)
        if edgecolor is not None or linewidth is not None:
            raise not_implemented("fill_betweenx(edge rendering)")
        if interpolate:
            raise not_implemented("fill_betweenx(interpolate=True)")
        if step is not None:
            raise not_implemented("fill_betweenx(step=...)")
        if transform is not None:
            raise not_implemented("fill_betweenx(transform=...)")
        check_unsupported(kwargs, "fill_betweenx()")
        valid = np.isfinite(yv + left + right)
        if where is not None:
            mask = np.ma.asarray(where, dtype=bool).filled(False)
            if mask.shape != yv.shape:
                raise ValueError("fill_betweenx where must match y")
            valid &= mask
        from xy import kernels

        mark_kwargs: dict[str, Any] = {
            "color": resolve_color(color) if color is not None else self._next_color(),
            "name": None if label is None else str(label),
            "opacity": 1.0 if alpha is None else float(alpha),
        }
        # Triangle meshes cannot stroke only the polygon perimeter; stroking
        # every tessellated triangle creates false internal striping. Keep the
        # fill exact and omit that approximation until perimeter paths exist.
        intervals = valid[:-1] & valid[1:]
        starts = np.flatnonzero(intervals & np.r_[True, ~intervals[:-1]])
        ends = np.flatnonzero(intervals & np.r_[~intervals[1:], True]) + 2
        entries: list[dict[str, Any]] = []
        for start, end in zip(starts, ends, strict=True):
            vertices_x = np.column_stack((left[start:end], right[start:end]))
            vertices_y = np.column_stack((yv[start:end], yv[start:end]))
            cells = np.zeros((end - start - 1, 1), dtype=np.float64)
            x0, y0, xa, ya, xb, yb, _ = kernels.quad_mesh_triangles(vertices_x, vertices_y, cells)
            entries.append(
                self._add(
                    "@mark",
                    {
                        "factory": "triangle_mesh",
                        "args": (x0, y0, xa, ya, xb, yb),
                        "kwargs": {
                            **mark_kwargs,
                            "name": mark_kwargs.get("name") if not entries else None,
                        },
                    },
                )
            )
        if not entries:
            entries.append(
                self._add(
                    "@mark",
                    {
                        "factory": "triangle_mesh",
                        "args": ([], [], [], [], [], []),
                        "kwargs": {**mark_kwargs, "opacity": 0.0},
                    },
                )
            )
        return PolyCollection(self, entries[0])

    def fill(self, *args: Any, data: TableLike = None, **kwargs: Any) -> list[PolyCollection]:
        """Draw filled polygons from ``x, y[, color]`` argument groups.

        Accepts matplotlib's repeated-group form ``fill(x1, y1, "b", x2, y2,
        "r")``. Supported keywords: ``color``/``facecolor``,
        ``edgecolor``/``ec``, ``linewidth``/``lw``, ``alpha``, and ``label``.
        Unsupported keywords raise loudly.
        """
        if len(args) < 2:
            raise TypeError("fill() requires x and y polygon coordinates")
        facecolor = kwargs.pop("color", kwargs.pop("facecolor", None))
        edgecolor = kwargs.pop("edgecolor", kwargs.pop("ec", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", None))
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        check_unsupported(kwargs, "fill()")
        groups: list[tuple[Any, Any, Any]] = []
        index = 0
        while index < len(args):
            if index + 1 >= len(args):
                raise TypeError("fill() polygon coordinates must be x, y pairs")
            x_values = _from_data(args[index], data)
            y_values = _from_data(args[index + 1], data)
            index += 2
            positional_color = None
            if index < len(args) and isinstance(args[index], str):
                try:
                    positional_color, _line, _marker = parse_fmt(args[index])
                except ValueError:
                    positional_color = args[index]
                index += 1
            groups.append((x_values, y_values, positional_color))
        from xy import kernels

        result: list[PolyCollection] = []
        for x_values, y_values, positional_color in groups:
            xv = np.asarray(x_values, dtype=np.float64)
            yv = np.asarray(y_values, dtype=np.float64)
            finite = np.isfinite(xv) & np.isfinite(yv)
            xv, yv = xv[finite], yv[finite]
            if len(xv) > 2 and np.allclose((xv[0], yv[0]), (xv[-1], yv[-1])):
                xv, yv = xv[:-1], yv[:-1]
            topology = kernels.polygon_triangles(xv, yv)
            x0, y0, x1, y1, x2, y2, _ = kernels.indexed_triangles(xv, yv, topology)
            chosen = facecolor
            if chosen is None and positional_color is not None:
                chosen = positional_color
            mark_kwargs: dict[str, Any] = {
                "color": resolve_color(chosen) if chosen is not None else self._next_color(),
                "name": None if label is None else str(label),
                "opacity": 1.0 if alpha is None else float(alpha),
                "_joined_fill": True,
            }
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": mark_kwargs,
                },
            )
            if edgecolor is not None and len(xv) >= 2:
                closed_x = np.concatenate((xv, xv[:1]))
                closed_y = np.concatenate((yv, yv[:1]))
                self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": (
                            closed_x[:-1],
                            closed_y[:-1],
                            closed_x[1:],
                            closed_y[1:],
                        ),
                        "kwargs": {
                            "color": resolve_color(edgecolor),
                            "width": 1.0 if linewidth is None else float(linewidth),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            result.append(PolyCollection(self, entry))
        return result

    def arrow(self, x: float, y: float, dx: float, dy: float, **kwargs: Any) -> PolyCollection:
        """An arrow from ``(x, y)`` to ``(x + dx, y + dy)`` in data coordinates.

        Supported keywords: ``color``/``facecolor``/``edgecolor``, ``alpha``,
        ``linewidth``/``width``, ``head_width``, ``head_length``, and
        ``transform``. ``length_includes_head``, non-``"full"`` ``shape``,
        ``overhang``, ``head_starts_at_zero``, and any unknown keyword raise
        loudly.
        """
        color = kwargs.pop("color", kwargs.pop("facecolor", kwargs.pop("edgecolor", None)))
        alpha = kwargs.pop("alpha", None)
        width = kwargs.pop("linewidth", kwargs.pop("width", 1.2))
        head_width = kwargs.pop("head_width", None)
        head_length = kwargs.pop("head_length", None)
        length_includes_head = kwargs.pop("length_includes_head", False)
        shape = kwargs.pop("shape", "full")
        overhang = kwargs.pop("overhang", 0)
        head_starts_at_zero = kwargs.pop("head_starts_at_zero", False)
        transform = kwargs.pop("transform", None)
        if length_includes_head or shape != "full" or overhang != 0 or head_starts_at_zero:
            raise not_implemented("arrow(head shape/overhang options)")
        check_unsupported(kwargs, "arrow()")
        ratio = 0.22
        if head_length is not None:
            length = float(np.hypot(dx, dy))
            ratio = 0.0 if length == 0 else min(1.0, float(head_length) / length)
        elif head_width is not None:
            length = float(np.hypot(dx, dy))
            ratio = 0.0 if length == 0 else min(1.0, float(head_width) / length)
        from xy import kernels

        x0, x1, y0, y1 = kernels.vector_segments(
            np.array([x]),
            np.array([y]),
            np.array([dx]),
            np.array([dy]),
            head_ratio=ratio,
        )
        if transform is not None:
            x0, y0 = self._transform_points(x0, y0, transform)
            x1, y1 = self._transform_points(x1, y1, transform)
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": resolve_color(color) if color is not None else self._next_color(),
                    "opacity": 1.0 if alpha is None else float(alpha),
                    "width": float(width),
                },
            },
        )
        return PolyCollection(self, entry)

    def axline(
        self, xy1: tuple[float, float], xy2: Any = None, *, slope: Any = None, **kwargs: Any
    ) -> Line2D:
        """An infinite line through ``xy1`` and ``xy2`` (or with ``slope``).

        Exactly one of ``xy2`` and ``slope`` must be given. Styled by the
        ``plot`` line keywords — ``color``/``c``, ``linewidth``/``lw``,
        ``linestyle``/``ls``, ``dashes``, ``alpha``, ``label`` —
        plus ``transform``; unsupported keywords raise loudly.
        """
        if (xy2 is None) == (slope is None):
            raise TypeError("axline() requires exactly one of xy2 or slope")
        if slope is not None and any(
            self._scale_specs[axis]["name"] != "linear" for axis in ("x", "y")
        ):
            raise TypeError("'slope' cannot be used with non-linear scales")
        transform = kwargs.pop("transform", None)
        transform_space = None
        if transform is self.transAxes:
            # Resolve against the final view at materialization time: callers
            # commonly set limits after adding axlines, and Matplotlib applies
            # the transform to the point(s) but never to the data-space slope.
            transform_space = "axes_fraction"
        elif transform is not None:
            points = [xy1] if xy2 is None else [xy1, xy2]
            tx, ty = self._transform_points(
                [point[0] for point in points],
                [point[1] for point in points],
                transform,
            )
            points = [(float(x), float(y)) for x, y in zip(tx, ty, strict=True)]
            xy1, xy2 = points[0], None if xy2 is None else points[1]
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "axline()")
        width = props.get("width", rcParams["lines.linewidth"])
        if props.get("dash") is not None:
            props["dash"] = self._mpl_dash(props["dash"], width)
        entry = self._add(
            "@axline",
            {
                "xy1": (float(xy1[0]), float(xy1[1])),
                "xy2": (None if xy2 is None else (float(xy2[0]), float(xy2[1]))),
                "slope": None if slope is None else float(slope),
                "transform_space": transform_space,
                "kwargs": {
                    "color": props.get("color"),
                    "opacity": props.get("opacity", 1.0),
                    "width": width,
                    "name": props.get("name"),
                    **({"dash": props["dash"]} if props.get("dash") is not None else {}),
                    **(
                        {"_gapcolor": props["_gapcolor"]}
                        if props.get("_gapcolor") is not None
                        else {}
                    ),
                },
            },
        )
        return Line2D(self, entry)

    def _spectral_line(
        self, frequency: np.ndarray, values: np.ndarray, kwargs: dict[str, Any]
    ) -> Line2D:
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "spectral plot")
        entry = self._add("line", {"x": frequency, "y": values, "kwargs": props})
        return Line2D(self, entry)

    def magnitude_spectrum(
        self,
        x: ArrayLike,
        Fs: float = 2,
        Fc: float = 0,
        window: Any = None,
        pad_to: int | None = None,
        sides: str | None = None,
        scale: str | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Line2D]:
        """Plot the magnitude spectrum of ``x``.

        ``Fs`` is the sampling frequency, ``Fc`` offsets the frequency axis,
        ``pad_to`` sets the FFT length, and ``scale`` is ``"linear"`` or
        ``"dB"``. ``window`` and ``sides`` raise loudly. Line keywords
        (``color``/``c``, ``linewidth``/``lw``, ``alpha``,
        ``linestyle``/``ls``, ``dashes``, ``label``) style the
        curve; unknown keywords raise loudly. Returns
        ``(spectrum, freqs, line)``.
        """
        _reject_spectral_options("magnitude_spectrum()", window=window, sides=sides)
        if scale not in (None, "linear", "dB"):
            raise ValueError("magnitude_spectrum scale must be 'linear' or 'dB'")
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        nfft = len(values) if pad_to is None else int(pad_to)
        from xy import kernels

        frequency, real, imag = kernels.rfft(values, nfft=nfft, sample_rate=float(Fs))
        magnitude = np.hypot(real, imag) / max(1.0, nfft * 0.5)
        shown = (
            20.0 * np.log10(np.maximum(magnitude, np.finfo(float).tiny))
            if scale == "dB"
            else magnitude
        )
        line = self._spectral_line(frequency + float(Fc), shown, kwargs)
        return magnitude, frequency + float(Fc), line

    def angle_spectrum(
        self,
        x: ArrayLike,
        Fs: float = 2,
        Fc: float = 0,
        window: Any = None,
        pad_to: int | None = None,
        sides: str | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Line2D]:
        """Plot the angle (wrapped phase) spectrum of ``x``.

        ``Fs`` is the sampling frequency, ``Fc`` offsets the frequency axis,
        and ``pad_to`` sets the FFT length; ``window`` and ``sides`` raise
        loudly. Line keywords (``color``/``c``, ``linewidth``/``lw``,
        ``alpha``, ``linestyle``/``ls``, ``dashes``, ``label``)
        style the curve. Returns ``(spectrum, freqs, line)``.
        """
        _reject_spectral_options("angle_spectrum()", window=window, sides=sides)
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        nfft = len(values) if pad_to is None else int(pad_to)
        from xy import kernels

        frequency, real, imag = kernels.rfft(values, nfft=nfft, sample_rate=float(Fs))
        angle = np.arctan2(imag, real)
        frequency = frequency + float(Fc)
        return angle, frequency, self._spectral_line(frequency, angle, kwargs)

    def phase_spectrum(
        self,
        x: ArrayLike,
        Fs: float = 2,
        Fc: float = 0,
        window: Any = None,
        pad_to: int | None = None,
        sides: str | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Line2D]:
        """Plot the unwrapped phase spectrum of ``x``.

        ``Fs`` is the sampling frequency, ``Fc`` offsets the frequency axis,
        and ``pad_to`` sets the FFT length; ``window`` and ``sides`` raise
        loudly. Line keywords (``color``/``c``, ``linewidth``/``lw``,
        ``alpha``, ``linestyle``/``ls``, ``dashes``, ``label``)
        style the curve. Returns ``(spectrum, freqs, line)``.
        """
        _reject_spectral_options("phase_spectrum()", window=window, sides=sides)
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        nfft = len(values) if pad_to is None else int(pad_to)
        from xy import kernels

        frequency, real, imag = kernels.rfft(values, nfft=nfft, sample_rate=float(Fs))
        phase = np.unwrap(np.arctan2(imag, real))
        frequency = frequency + float(Fc)
        return phase, frequency, self._spectral_line(frequency, phase, kwargs)

    def grouped_bar(
        self,
        heights: Any,
        *,
        positions: ArrayLike | None = None,
        group_spacing: float = 1.5,
        bar_spacing: float = 0,
        tick_labels: Sequence[str] | None = None,
        labels: Sequence[str] | None = None,
        orientation: str = "vertical",
        colors: Any = None,
        **kwargs: Any,
    ) -> GroupedBarReturn:
        """Draw Matplotlib 3.11 grouped bars using ordinary generic bar marks."""
        inferred_ticks = inferred_labels = None
        if hasattr(heights, "to_numpy") and hasattr(heights, "index"):
            matrix = np.asarray(heights.to_numpy(), dtype=np.float64)
            inferred_ticks = list(heights.index)
            inferred_labels = list(heights.columns)
            datasets = [matrix[:, index] for index in range(matrix.shape[1])]
        elif isinstance(heights, dict):
            if labels is not None:
                raise ValueError("labels must not be passed with dict heights")
            inferred_labels = list(heights)
            datasets = [np.asarray(value, dtype=np.float64) for value in heights.values()]
        elif isinstance(heights, (list, tuple)):
            datasets = [np.asarray(value, dtype=np.float64) for value in heights]
        else:
            matrix = np.asarray(heights, dtype=np.float64)
            if matrix.ndim == 1:
                matrix = matrix[:, None]
            if matrix.ndim != 2:
                raise ValueError("grouped_bar heights must be 1-D or 2-D")
            datasets = [matrix[:, index] for index in range(matrix.shape[1])]
        if not datasets or any(values.ndim != 1 for values in datasets):
            raise ValueError("grouped_bar requires one or more 1-D datasets")
        count = len(datasets[0])
        if any(len(values) != count for values in datasets):
            raise ValueError("all grouped_bar datasets must have equal length")
        centers = (
            np.arange(count, dtype=np.float64)
            if positions is None
            else np.asarray(positions, dtype=np.float64)
        )
        if centers.shape != (count,):
            raise ValueError("grouped_bar positions must match the category count")
        dataset_labels = inferred_labels if labels is None else list(labels)
        if dataset_labels is None:
            dataset_labels = [None] * len(datasets)
        if len(dataset_labels) != len(datasets):
            raise ValueError("grouped_bar labels must match the dataset count")
        palette = (
            [self._next_color() for _ in datasets]
            if colors is None
            else [list(colors)[index % len(list(colors))] for index in range(len(datasets))]
        )
        step = float(np.min(np.diff(centers))) if len(centers) > 1 else 1.0
        denominator = (
            len(datasets)
            + max(0.0, float(group_spacing))
            + max(0.0, float(bar_spacing)) * max(0, len(datasets) - 1)
        )
        width = step / max(denominator, 1.0)
        stride = width * (1.0 + max(0.0, float(bar_spacing)))
        start = -0.5 * stride * (len(datasets) - 1)
        containers: list[BarContainer] = []
        for index, values in enumerate(datasets):
            local = dict(kwargs)
            local["color"] = palette[index]
            if dataset_labels[index] is not None:
                local["label"] = dataset_labels[index]
            shifted = centers + start + index * stride
            if orientation == "vertical":
                containers.append(self.bar(shifted, values, width=width, **local))
            elif orientation == "horizontal":
                containers.append(self.barh(shifted, values, height=width, **local))
            else:
                raise ValueError("grouped_bar orientation must be 'vertical' or 'horizontal'")
        chosen_ticks = inferred_ticks if tick_labels is None else tick_labels
        if chosen_ticks is not None:
            if orientation == "vertical":
                self.set_xticks(centers, chosen_ticks)
            else:
                self.set_yticks(centers, chosen_ticks)
        return GroupedBarReturn(containers)

    def bar_label(
        self,
        container: BarContainer,
        labels: Sequence[str] | None = None,
        *,
        fmt: Any = "%g",
        label_type: str = "edge",
        padding: float = 0,
        **kwargs: Any,
    ) -> list[Text]:
        """Label the bars of a ``bar``/``barh`` container with their values.

        ``labels`` overrides the default value labels; ``fmt`` is a %-format,
        ``{}``-format, or callable; ``label_type`` places labels at the bar
        ``"edge"`` or ``"center"``, offset by ``padding`` points. Supported
        keywords: ``color`` and ``fontsize``; ``fontproperties`` and any
        unknown keyword raise loudly.
        """
        if label_type not in ("edge", "center"):
            raise ValueError("bar_label label_type must be 'edge' or 'center'")
        values = np.asarray(container.datavalues, dtype=np.float64)
        centers = np.asarray(container.position_centers)
        bottoms = np.asarray(container.bottoms, dtype=np.float64)
        tops = np.asarray(container.tops, dtype=np.float64)
        raw_labels = [None] * len(values) if labels is None else list(labels)
        if len(raw_labels) != len(values):
            raise ValueError("bar_label labels must match the number of bars")
        color = kwargs.pop("color", None)
        fontsize = kwargs.pop("fontsize", None)
        if kwargs.pop("fontproperties", None) is not None:
            raise not_implemented("bar_label(fontproperties=...)", alternative="fontsize=")
        check_unsupported(kwargs, "bar_label()")
        if label_type == "edge":
            value_axis = "y" if container.orientation == "vertical" else "x"
            # Matplotlib's Annotation does not contribute its text bbox to
            # dataLim. Its default 5% margin therefore leaves a padded 10 pt
            # bar label on (or fractionally beyond) the top spine. Reserve a
            # small label-aware default while preserving explicit margins().
            self._reserve_annotation_margin(value_axis, 0.075)
        result: list[Text] = []
        for index, value in enumerate(values):
            if raw_labels[index] is not None:
                label = str(raw_labels[index])
            elif callable(fmt):
                label = str(fmt(value if label_type == "center" else tops[index]))
            elif "{" in str(fmt):
                label = str(fmt).format(value if label_type == "center" else tops[index])
            else:
                label = str(fmt) % (value if label_type == "center" else tops[index])
            coordinate = (
                (bottoms[index] + tops[index]) * 0.5 if label_type == "center" else tops[index]
            )
            x, y = (
                (centers[index], coordinate)
                if container.orientation == "vertical"
                else (coordinate, centers[index])
            )
            pixel_padding = float(padding) * self._point_scale()
            positive = value >= 0
            if container.orientation == "vertical":
                anchor = "middle"
                dx = 0.0
                dy = pixel_padding * (1.0 if positive else -1.0)
                # SVG/browser y grows downward, so matplotlib's positive
                # point offset is an upward (negative) screen-space offset.
                dy *= -1.0
                vertical_align = (
                    "center" if label_type == "center" else ("bottom" if positive else "top")
                )
            elif label_type == "center":
                anchor, dx, dy = "middle", pixel_padding * (1.0 if positive else -1.0), 0.0
                vertical_align = "center"
            else:
                anchor = "start" if positive else "end"
                dx = pixel_padding * (1.0 if positive else -1.0)
                dy = 0.0
                vertical_align = "center"
            text_kwargs: dict[str, Any] = {
                "color": resolve_color(color) if color is not None else None,
                "anchor": anchor,
                "dx": dx,
                "dy": dy,
                "style": {"vertical_align": vertical_align},
            }
            if fontsize is not None:
                text_kwargs["style"]["font_size"] = float(fontsize)
            entry = self._add("@text", {"args": (x, y, label), "kwargs": text_kwargs})
            result.append(Text(self, entry))
        return result

    def psd(
        self,
        x: ArrayLike,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 0,
        pad_to: int | None = None,
        sides: str | None = None,
        scale_by_freq: bool | None = None,
        return_line: bool | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> Any:
        """Plot the power spectral density of ``x`` (Welch's method).

        ``NFFT``/``noverlap`` control the segmenting and ``Fs`` is the
        sampling frequency; ``detrend``, ``window``, ``pad_to``, ``sides``,
        and ``scale_by_freq`` raise loudly. Line keywords (``color``/``c``,
        ``linewidth``/``lw``, ``alpha``, ``linestyle``/``ls``, ``dashes``,
        ``label``) style the curve. Returns ``(Pxx, freqs)``
        (plus the line with ``return_line=True``).
        """
        _reject_spectral_options(
            "psd()",
            detrend=detrend,
            window=window,
            pad_to=pad_to,
            sides=sides,
            scale_by_freq=scale_by_freq,
        )
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        from xy import kernels

        frequency, pxx, _pyy, _cross_real, _cross_imag = kernels.welch_spectra(
            values, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        frequency = frequency + float(Fc)
        shown = 10.0 * np.log10(np.maximum(pxx, np.finfo(float).tiny))
        line = self._spectral_line(frequency, shown, kwargs)
        return (pxx, frequency, line) if return_line else (pxx, frequency)

    def csd(
        self,
        x: ArrayLike,
        y: ArrayLike,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 0,
        pad_to: int | None = None,
        sides: str | None = None,
        scale_by_freq: bool | None = None,
        return_line: bool | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> Any:
        """Plot the cross-spectral density of ``x`` and ``y``.

        Same segmenting keywords as ``psd``; ``detrend``, ``window``,
        ``pad_to``, ``sides``, and ``scale_by_freq`` raise loudly, and line
        keywords (``color``/``c``, ``linewidth``/``lw``, ``alpha``,
        ``linestyle``/``ls``, ``dashes``, ``label``) style the
        curve. Returns ``(Pxy, freqs)`` (plus the line with
        ``return_line=True``).
        """
        _reject_spectral_options(
            "csd()",
            detrend=detrend,
            window=window,
            pad_to=pad_to,
            sides=sides,
            scale_by_freq=scale_by_freq,
        )
        xv = np.asarray(_from_data(x, data), dtype=np.float64)
        yv = np.asarray(_from_data(y, data), dtype=np.float64)
        from xy import kernels

        frequency, _pxx, _pyy, real, imag = kernels.welch_spectra(
            xv, yv, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        cross = real + 1j * imag
        frequency = frequency + float(Fc)
        shown = 10.0 * np.log10(np.maximum(np.abs(cross), np.finfo(float).tiny))
        line = self._spectral_line(frequency, shown, kwargs)
        return (cross, frequency, line) if return_line else (cross, frequency)

    def cohere(
        self,
        x: ArrayLike,
        y: ArrayLike,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 0,
        pad_to: int | None = None,
        sides: str | None = None,
        scale_by_freq: bool | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Plot the coherence between ``x`` and ``y``.

        Same segmenting keywords as ``psd``; ``detrend``, ``window``,
        ``pad_to``, ``sides``, and ``scale_by_freq`` raise loudly, and line
        keywords (``color``/``c``, ``linewidth``/``lw``, ``alpha``,
        ``linestyle``/``ls``, ``dashes``, ``label``) style the
        curve. Returns ``(Cxy, freqs)``.
        """
        _reject_spectral_options(
            "cohere()",
            detrend=detrend,
            window=window,
            pad_to=pad_to,
            sides=sides,
            scale_by_freq=scale_by_freq,
        )
        xv = np.asarray(_from_data(x, data), dtype=np.float64)
        yv = np.asarray(_from_data(y, data), dtype=np.float64)
        from xy import kernels

        frequency, pxx, pyy, real, imag = kernels.welch_spectra(
            xv, yv, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        coherence = (real * real + imag * imag) / np.maximum(pxx * pyy, np.finfo(float).tiny)
        frequency = frequency + float(Fc)
        self._spectral_line(frequency, coherence, kwargs)
        return coherence, frequency

    def specgram(
        self,
        x: ArrayLike,
        NFFT: int = 256,
        Fs: float = 2,
        Fc: float = 0,
        detrend: Any = None,
        window: Any = None,
        noverlap: int = 128,
        cmap: Any = None,
        xextent: tuple[float, float] | None = None,
        pad_to: int | None = None,
        sides: str | None = None,
        scale_by_freq: bool | None = None,
        mode: str | None = None,
        scale: str | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, PolyCollection]:
        """Plot a spectrogram of ``x`` as a pseudocolor image.

        Segmenting follows ``psd``; ``cmap``, ``vmin``/``vmax``, and the
        ``alpha`` keyword style the image. ``detrend``, ``window``,
        ``xextent``, ``pad_to``, ``sides``, ``scale_by_freq``, ``mode``,
        ``scale``, and any unknown keyword raise loudly. Returns
        ``(spectrum, freqs, t, image)``.
        """
        _reject_spectral_options(
            "specgram()",
            detrend=detrend,
            window=window,
            xextent=xextent,
            pad_to=pad_to,
            sides=sides,
            scale_by_freq=scale_by_freq,
            mode=mode,
            scale=scale,
        )
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        from xy import kernels

        power, frequency, time = kernels.spectrogram(
            values, nfft=int(NFFT), noverlap=int(noverlap), sample_rate=float(Fs)
        )
        frequency = frequency + float(Fc)
        shown = 10.0 * np.log10(np.maximum(power, np.finfo(float).tiny))
        alpha = kwargs.pop("alpha", None)
        check_unsupported(kwargs, "specgram()")
        mark_kwargs: dict[str, Any] = {
            "x": time,
            # Matplotlib draws the spectrogram through imshow with the
            # frequency *endpoints* as its extent, not as cell centers.  Pick
            # centers whose reconstructed cell edges land on those endpoints.
            "y": np.linspace(
                frequency[0] + (frequency[-1] - frequency[0]) / (2 * len(frequency)),
                frequency[-1] - (frequency[-1] - frequency[0]) / (2 * len(frequency)),
                len(frequency),
            ),
            "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
            "opacity": 1.0 if alpha is None else float(alpha),
        }
        if vmin is not None and vmax is not None:
            mark_kwargs["domain"] = (float(vmin), float(vmax))
        entry = self._add(
            "@mark", {"factory": "heatmap", "args": (shown.T,), "kwargs": mark_kwargs}
        )
        return power.T, frequency, time, PolyCollection(self, entry)

    def xcorr(
        self,
        x: ArrayLike,
        y: ArrayLike,
        normed: bool = True,
        detrend: Callable[[np.ndarray], ArrayLike] | None = None,
        usevlines: bool = True,
        maxlags: int | None = 10,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, Any, Any]:
        """Plot the cross-correlation of ``x`` and ``y`` per lag.

        ``maxlags`` bounds the lag window, ``usevlines`` draws stems instead
        of markers, and ``detrend`` is an optional callable applied to both
        inputs. Supported keywords: ``color`` and ``linewidth``/``lw``;
        anything else raises loudly. Returns
        ``(lags, correlations, lines, baseline)``.
        """
        xv = np.asarray(_from_data(x, data), dtype=np.float64)
        yv = np.asarray(_from_data(y, data), dtype=np.float64)
        if detrend is not None:
            if not callable(detrend):
                raise TypeError("xcorr detrend must be callable or None")
            xv = np.asarray(detrend(xv), dtype=np.float64)
            yv = np.asarray(detrend(yv), dtype=np.float64)
            if xv.shape != yv.shape or xv.ndim != 1:
                raise ValueError("xcorr detrend must preserve the 1-D input shape")
        from xy import kernels

        lag, correlation = kernels.correlation(
            xv, yv, max_lags=None if maxlags is None else int(maxlags), normalize=bool(normed)
        )
        color = kwargs.pop("color", None)
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", 1.2))
        check_unsupported(kwargs, "xcorr()/acorr()")
        chosen = (
            resolve_color(color)
            if color is not None and (isinstance(color, str) or np.isscalar(color))
            else self._next_color()
        )
        if usevlines:
            artist = self.vlines(lag, 0.0, correlation, colors=chosen, linewidth=linewidth)
        else:
            artist = self.plot(lag, correlation, color=chosen, linewidth=linewidth)[0]
        baseline = self.axhline(0.0, color=chosen, linewidth=0.8)
        return lag, correlation, artist, baseline

    def acorr(self, x: ArrayLike, **kwargs: Any) -> tuple[np.ndarray, np.ndarray, Any, Any]:
        """Plot the autocorrelation of ``x`` (see ``xcorr`` for the keywords).

        Returns ``(lags, correlations, lines, baseline)``.
        """
        return self.xcorr(x, x, **kwargs)

    def stem(
        self,
        *args: Any,
        linefmt: str | None = None,
        markerfmt: str | None = None,
        basefmt: str | None = None,
        bottom: float = 0,
        label: str | None = None,
        orientation: str = "vertical",
        data: TableLike = None,
    ) -> StemContainer:
        """A stem plot: vertical lines from a baseline to markers at each y.

        Call as ``stem(y)`` or ``stem(x, y)``. ``linefmt``/``markerfmt`` are
        ``plot``-style fmt strings for the stems and heads, ``bottom`` moves
        the baseline, and ``orientation`` may be ``"horizontal"``.
        """
        if len(args) == 1:
            y = _from_data(args[0], data)
            x = np.arange(len(y), dtype=np.float64)
        elif len(args) == 2:
            x, y = (_from_data(arg, data) for arg in args)
        else:
            raise TypeError("stem() takes y or x, y")
        color = None
        dash_pattern = None
        if linefmt:
            color_spec, linestyle, _marker = parse_fmt(str(linefmt))
            color = resolve_color(color_spec) if color_spec else None
            dash_pattern = _dash_segment_pattern("stem", linestyle)
        symbol = "circle"
        marker_color = None
        if markerfmt:
            marker_color_spec, _linestyle, marker = parse_fmt(str(markerfmt))
            marker_color = resolve_color(marker_color_spec) if marker_color_spec else None
            from ._translate import MARKER_TO_SYMBOL

            symbol = MARKER_TO_SYMBOL.get(marker or "o", "circle")
        chosen = color or self._next_color()
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("stem orientation must be 'vertical' or 'horizontal'")

        xv = np.asarray(x, dtype=np.float64)
        yv = np.asarray(y, dtype=np.float64)
        if xv.ndim != 1 or yv.ndim != 1 or xv.shape != yv.shape:
            raise ValueError("stem x and y must be equally sized 1-D arrays")
        base = np.full_like(xv, float(bottom))
        if orientation == "vertical":
            segments = (xv, base, xv, yv)
            marker_x, marker_y = xv, yv
            baseline_x = np.asarray([xv.min(), xv.max()]) if xv.size else np.asarray([])
            baseline_y = np.full(2 if xv.size else 0, float(bottom))
        else:
            segments = (base, xv, yv, xv)
            marker_x, marker_y = yv, xv
            baseline_x = np.full(2 if xv.size else 0, float(bottom))
            baseline_y = np.asarray([xv.min(), xv.max()]) if xv.size else np.asarray([])
        if dash_pattern is not None:
            segments = _dashed_segments(*segments, dash_pattern)

        if orientation == "vertical" and dash_pattern is None:
            # Retain the compact native stem primitive (and its public trace
            # kind), but render markers separately so the returned markerline
            # can be styled independently like Matplotlib's Line2D.
            stem_entry = self._add(
                "@mark",
                {
                    "factory": "stem",
                    "args": (xv, yv),
                    "kwargs": {
                        "base": bottom,
                        "marker": False,
                        "name": str(label) if label is not None else None,
                        "color": chosen,
                        "width": 1.2,
                    },
                },
            )
        else:
            stem_entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": segments,
                    "kwargs": {
                        "name": str(label) if label is not None else None,
                        "color": chosen,
                        "width": 1.2,
                    },
                },
            )
        edge_width = float(rcParams["lines.markeredgewidth"]) * self._point_scale()
        marker_size = float(rcParams["lines.markersize"]) * self._point_scale() + edge_width
        marker_entry = self._add(
            "scatter",
            {
                "x": marker_x,
                "y": marker_y,
                "kwargs": {
                    "color": marker_color or chosen,
                    "stroke": marker_color or chosen,
                    "stroke_width": edge_width,
                    "symbol": symbol,
                    "size": marker_size,
                    "opacity": 1.0,
                },
            },
        )

        base_color, base_linestyle, _base_marker = parse_fmt(str(basefmt or "C3-"))
        base_dash = LINESTYLE_TO_DASH.get(base_linestyle)
        if base_dash is not None:
            base_dash = self._mpl_dash(base_dash, 1.5)
        baseline_entry = self._add(
            "line",
            {
                "x": baseline_x,
                "y": baseline_y,
                "kwargs": {
                    "color": resolve_color(base_color or "C3"),
                    # The axes spine is painted after marks.  Matplotlib's
                    # baseline remains visible when it coincides with that
                    # spine, so give the colored rule enough width to remain
                    # visible on either side of the 1 px frame.
                    "width": 1.5,
                    **({"dash": list(base_dash)} if base_dash is not None else {}),
                },
            },
        )
        return StemContainer(
            Line2D(self, marker_entry),
            Artist(self, stem_entry),
            Line2D(self, baseline_entry),
        )

    def stairs(
        self,
        values: ArrayLike,
        edges: ArrayLike | None = None,
        *,
        orientation: str = "vertical",
        baseline: float | ArrayLike | None = 0,
        fill: bool = False,
        data: TableLike = None,
        **kwargs: Any,
    ) -> StepPatch:
        """A stepwise constant function as a line or filled patch.

        ``values`` has one entry per interval, ``edges`` one more (defaults
        to ``0..len(values)``). Supported keywords: the ``plot`` line
        keywords (``color``/``c``, ``linewidth``/``lw``, ``alpha``,
        ``linestyle``/``ls``, ``dashes``, ``label``) plus
        ``hatch``; unknown keywords raise loudly.
        """
        values = _from_data(values, data)
        edges = _from_data(edges, data)
        hatch = kwargs.pop("hatch", None)
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "stairs()")
        vals = np.asarray(values, dtype=np.float64)
        edge_values = (
            np.arange(len(vals) + 1, dtype=np.float64)
            if edges is None
            else np.asarray(edges, dtype=np.float64)
        )
        if vals.ndim != 1 or edge_values.shape != (len(vals) + 1,):
            raise ValueError("stairs edges must have one more element than values")
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("stairs orientation must be 'vertical' or 'horizontal'")
        if fill:
            base_values = np.broadcast_to(
                np.asarray(0.0 if baseline is None else baseline, dtype=np.float64), vals.shape
            )
            entry = None
            for index, (value, base_value, left, right) in enumerate(
                zip(vals, base_values, edge_values[:-1], edge_values[1:], strict=True)
            ):
                item = self._add(
                    "bar",
                    {
                        "x": [(left + right) * 0.5],
                        "y": [value - base_value],
                        "kwargs": {
                            "color": props.get("color"),
                            "width": float(right - left),
                            "base": [base_value],
                            "orientation": orientation,
                            "opacity": props.get("opacity", 1.0),
                            "name": props.get("name") if index == 0 else None,
                        },
                        "values": values,
                        "edges": edges,
                        "baseline": baseline,
                    },
                )
                entry = entry or item
            assert entry is not None
            if hatch:
                self._stairs_hatch(
                    vals, edge_values, base_values, orientation, props, hatch=str(hatch)
                )
            return StepPatch(self, entry)
        if orientation == "horizontal":
            x0 = np.concatenate((vals, vals[:-1]))
            x1 = np.concatenate((vals, vals[1:]))
            y0 = np.concatenate((edge_values[:-1], edge_values[1:-1]))
            y1 = np.concatenate((edge_values[1:], edge_values[1:-1]))
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": {
                        "color": props.get("color"),
                        "width": props.get("width", 1.2),
                        "opacity": props.get("opacity", 1.0),
                        "name": props.get("name"),
                    },
                    "values": values,
                    "edges": edges,
                    "baseline": baseline,
                },
            )
            if hatch:
                base_values = np.broadcast_to(
                    np.asarray(0.0 if baseline is None else baseline, dtype=np.float64), vals.shape
                )
                self._stairs_hatch(
                    vals, edge_values, base_values, orientation, props, hatch=str(hatch)
                )
            return StepPatch(self, entry)
        entry = self._add(
            "@mark",
            {
                "factory": "stairs",
                "args": (values, edges),
                "values": values,
                "edges": edges,
                "kwargs": props,
            },
        )
        return StepPatch(self, entry)

    def _stairs_hatch(
        self,
        values: np.ndarray,
        edges: np.ndarray,
        bases: np.ndarray,
        orientation: str,
        props: dict[str, Any],
        *,
        hatch: str = "/",
        right_edges: np.ndarray | None = None,
    ) -> None:
        """Approximate Matplotlib hatch families with bin-local geometry."""
        x0: list[float] = []
        y0: list[float] = []
        x1: list[float] = []
        y1: list[float] = []
        left_edges = np.asarray(edges, dtype=np.float64)
        if right_edges is None:
            right_values = left_edges[1:]
            left_edges = left_edges[:-1]
        else:
            right_values = np.asarray(right_edges, dtype=np.float64)
        if not (len(values) == len(bases) == len(left_edges) == len(right_values)):
            raise ValueError("hatch geometry must have one rectangle per value")
        edge_extent = np.concatenate((left_edges, right_values))
        value_extent = np.concatenate(
            (np.asarray(values, dtype=np.float64), np.asarray(bases, dtype=np.float64))
        )
        finite_edge_extent = edge_extent[np.isfinite(edge_extent)]
        finite_value_extent = value_extent[np.isfinite(value_extent)]
        edge_span = float(np.ptp(finite_edge_extent)) if finite_edge_extent.size else 0.0
        value_span = float(np.ptp(finite_value_extent)) if finite_value_extent.size else 0.0
        x_span, y_span = (
            (edge_span, value_span) if orientation == "vertical" else (value_span, edge_span)
        )
        pattern = set(hatch)
        density = max(1, min(3, max((hatch.count(char) for char in pattern), default=1)))
        line_count = 4 + density * 3

        for value, base, edge0, edge1 in zip(values, bases, left_edges, right_values, strict=True):
            if orientation == "vertical":
                rx0, rx1 = edge0, edge1
                ry0, ry1 = sorted((base, value))
            else:
                rx0, rx1 = sorted((base, value))
                ry0, ry1 = edge0, edge1

            def segment(
                u0: float,
                v0: float,
                u1: float,
                v1: float,
                *,
                _rx0: float = float(rx0),
                _rx1: float = float(rx1),
                _ry0: float = float(ry0),
                _ry1: float = float(ry1),
            ) -> None:
                x0.append(_rx0 + u0 * (_rx1 - _rx0))
                y0.append(_ry0 + v0 * (_ry1 - _ry0))
                x1.append(_rx0 + u1 * (_rx1 - _rx0))
                y1.append(_ry0 + v1 * (_ry1 - _ry0))

            def diagonals(reverse: bool) -> None:
                for offset in np.linspace(-0.85, 0.85, line_count):
                    u0, u1 = max(0.0, -offset), min(1.0, 1.0 - offset)
                    if u1 <= u0:
                        continue
                    v0, v1 = u0 + offset, u1 + offset
                    if reverse:
                        v0, v1 = 1.0 - v0, 1.0 - v1
                    segment(u0, v0, u1, v1)

            if "/" in pattern or "x" in pattern or "*" in pattern:
                diagonals(False)
            if "\\" in pattern or "x" in pattern or "*" in pattern:
                diagonals(True)
            if "|" in pattern or "+" in pattern or "*" in pattern:
                for position in np.linspace(0.1, 0.9, line_count):
                    segment(float(position), 0.0, float(position), 1.0)
            if "-" in pattern or "+" in pattern or "*" in pattern:
                for position in np.linspace(0.1, 0.9, line_count):
                    segment(0.0, float(position), 1.0, float(position))

            rect_width = abs(float(rx1) - float(rx0))
            rect_height = abs(float(ry1) - float(ry0))
            rectangle = (rect_width, rect_height)

            def ring(
                u: float,
                v: float,
                *,
                scale: float,
                steps: int,
                rectangle: tuple[float, float],
            ) -> None:
                rect_width, rect_height = rectangle
                if rect_width <= 0.0 or rect_height <= 0.0:
                    return
                # Hatch circles are display-sized in Matplotlib and clipped by
                # each Rectangle. The shim has no per-bin clip primitive, so
                # materialize a small data-space polygon and clamp both radii
                # inside this rectangle. That keeps even tail-bin glyphs local
                # instead of letting fixed-size scatter markers leak across the
                # histogram baseline.
                ru = min(0.08 * scale, (x_span / 160.0) * scale / rect_width)
                rv = min(0.08 * scale, (y_span / 120.0) * scale / rect_height)
                if ru <= 0.0 or rv <= 0.0:
                    return
                angles = np.linspace(0.0, 2.0 * np.pi, steps + 1)
                points = [
                    (u + ru * float(np.cos(angle)), v + rv * float(np.sin(angle)))
                    for angle in angles
                ]
                for start, end in pairwise(points):
                    segment(*start, *end)

            if "." in pattern:
                grid = np.linspace(0.12, 0.88, 3 + density)
                for u in grid:
                    for v in grid:
                        ring(
                            float(u),
                            float(v),
                            scale=0.45,
                            steps=6,
                            rectangle=rectangle,
                        )
            if "o" in pattern or "O" in pattern:
                grid = np.linspace(0.14, 0.86, 3 + density)
                for u in grid:
                    for v in grid:
                        ring(
                            float(u),
                            float(v),
                            scale=1.35 if "O" in pattern else 1.0,
                            steps=10,
                            rectangle=rectangle,
                        )

        color = props.get("color")
        opacity = props.get("opacity", 1.0)
        if x0:
            self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": {
                        "color": color,
                        "width": 0.8,
                        "opacity": opacity,
                        "name": None,
                    },
                },
            )

    def ecdf(
        self,
        x: ArrayLike,
        weights: ArrayLike | None = None,
        *,
        complementary: bool = False,
        orientation: str = "vertical",
        compress: bool = False,
        data: TableLike = None,
        **kwargs: Any,
    ) -> Artist:
        """The empirical cumulative distribution function of ``x``.

        ``complementary=True`` plots 1 - ECDF, ``weights`` weighs the
        samples, and ``orientation`` may be ``"horizontal"``. Line keywords
        (``color``/``c``, ``linewidth``/``lw``, ``alpha``,
        ``linestyle``/``ls``, ``dashes``, ``label``) style the
        curve; unknown keywords raise loudly.
        """
        values = np.asarray(_from_data(x, data), dtype=np.float64)
        props = _line_props(self, kwargs)
        check_unsupported(kwargs, "ecdf()")
        if weights is None and not complementary and orientation == "vertical" and not compress:
            entry = self._add("@mark", {"factory": "ecdf", "args": (values,), "kwargs": props})
            return Artist(self, entry)
        weight_values = (
            np.ones(len(values), dtype=np.float64)
            if weights is None
            else np.asarray(_from_data(weights, data), dtype=np.float64)
        )
        if len(weight_values) != len(values) or np.any(weight_values < 0):
            raise ValueError("ecdf weights must be nonnegative and match x")
        from xy import kernels

        unique, cumulative = kernels.weighted_ecdf(values, weight_values)
        if complementary:
            cumulative = 1.0 - cumulative
        sx = np.concatenate(([unique[0]], unique))
        sy = np.concatenate(([1.0 if complementary else 0.0], cumulative))
        if orientation == "vertical":
            args = (sx, sy)
        elif orientation == "horizontal":
            args = (sy, sx)
        else:
            raise ValueError("ecdf orientation must be 'vertical' or 'horizontal'")
        entry = self._add(
            "@mark",
            {
                "factory": "step",
                "args": args,
                "kwargs": {"where": "post", **props},
                "_mpl_sticky_edges": {"y" if orientation == "vertical" else "x": (0.0, 1.0)},
            },
        )
        return Artist(self, entry)

    def boxplot(
        self,
        x: ArrayLike,
        *,
        notch: bool | None = None,
        sym: str | None = None,
        vert: bool | None = None,
        orientation: str = "vertical",
        whis: float | tuple[float, float] | None = None,
        positions: ArrayLike | None = None,
        widths: float | ArrayLike | None = None,
        patch_artist: bool | None = None,
        bootstrap: int | None = None,
        usermedians: Any = None,
        conf_intervals: Any = None,
        meanline: bool | None = None,
        showmeans: bool | None = None,
        showcaps: bool | None = None,
        showbox: bool | None = None,
        showfliers: bool | None = None,
        boxprops: Mapping[str, Any] | None = None,
        tick_labels: Sequence[str] | None = None,
        flierprops: Mapping[str, Any] | None = None,
        medianprops: Mapping[str, Any] | None = None,
        meanprops: Mapping[str, Any] | None = None,
        capprops: Mapping[str, Any] | None = None,
        whiskerprops: Mapping[str, Any] | None = None,
        manage_ticks: bool = True,
        autorange: bool = False,
        zorder: float | None = None,
        capwidths: float | ArrayLike | None = None,
        label: str | Sequence[str] | None = None,
        data: TableLike = None,
    ) -> dict[str, list[Artist]]:
        """Box-and-whisker plots of one dataset or a sequence of datasets.

        Follows matplotlib's ``Axes.boxplot``: ``whis`` sets the whisker
        reach, ``positions``/``widths``/``tick_labels`` lay the boxes out,
        the ``show*`` flags toggle elements, and the ``*props`` dicts style
        them. Returns the matplotlib-shaped dict of artist lists.
        """
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        values = _from_data(x, data)
        if isinstance(values, (list, tuple)) and values and all(np.ndim(v) == 1 for v in values):
            groups = [np.asarray(v, dtype=np.float64) for v in values]
        else:
            arr = np.asarray(values, dtype=np.float64)
            groups = [arr[:, i] for i in range(arr.shape[1])] if arr.ndim == 2 else [arr]
        groups = [group[np.isfinite(group)] for group in groups]
        if any(len(group) == 0 for group in groups):
            raise ValueError("boxplot groups must each contain a finite value")
        count = len(groups)
        medians_override = [None] * count if usermedians is None else list(usermedians)
        intervals_override = [None] * count if conf_intervals is None else list(conf_intervals)
        if len(medians_override) != count or len(intervals_override) != count:
            raise ValueError("usermedians/conf_intervals must match the number of boxes")
        whisker = 1.5 if whis is None else whis
        stats: list[dict[str, Any]] = []
        for index, group in enumerate(groups):
            q1, med, q3 = np.percentile(group, [25, 50, 75])
            data_median = med  # usermedians replaces the drawn median only;
            median_override = medians_override[index]  # CIs stay data-derived
            if median_override is not None:
                med = _float(median_override)
            effective_whis = (0.0, 100.0) if autorange and q1 == q3 else whisker
            if np.isscalar(effective_whis):
                iqr = q3 - q1
                whisker_factor = _float(effective_whis)
                lower_bound = q1 - whisker_factor * iqr
                upper_bound = q3 + whisker_factor * iqr
            else:
                percentile_whis = np.asarray(effective_whis, dtype=np.float64).reshape(-1)
                if percentile_whis.size != 2:
                    raise ValueError("whis must be a scalar or a two-percentile sequence")
                lower_bound, upper_bound = np.percentile(group, percentile_whis)
            below = group[group >= lower_bound]
            above = group[group <= upper_bound]
            whislo = float(np.min(below)) if len(below) else float(q1)
            whishi = float(np.max(above)) if len(above) else float(q3)
            fliers = group[(group < whislo) | (group > whishi)]
            interval = intervals_override[index]
            if interval is not None:
                cilo, cihi = map(float, interval)
            elif bootstrap is not None:
                samples = int(bootstrap)
                if samples <= 0:
                    raise ValueError("bootstrap must be a positive integer")
                indices = np.random.randint(0, len(group), size=(samples, len(group)))
                cilo, cihi = np.percentile(np.median(group[indices], axis=1), [2.5, 97.5])
            else:
                delta = 1.57 * (q3 - q1) / np.sqrt(len(group))
                cilo, cihi = data_median - delta, data_median + delta
            stats.append(
                {
                    "q1": float(q1),
                    "med": float(med),
                    "q3": float(q3),
                    "whislo": whislo,
                    "whishi": whishi,
                    "fliers": fliers,
                    "mean": float(np.mean(group)),
                    "cilo": float(cilo),
                    "cihi": float(cihi),
                }
            )
        if sym == "":
            showfliers = False  # matplotlib: an empty sym string suppresses fliers
        elif sym is not None:
            sym_color, _sym_line, sym_marker = parse_fmt(str(sym))
            overrides: dict[str, Any] = {}
            if sym_marker is not None:
                overrides["marker"] = sym_marker
            if sym_color is not None:
                overrides["color"] = sym_color
            flierprops = {**(flierprops or {}), **overrides}
        result = self.bxp(
            stats,
            positions=positions,
            widths=widths,
            orientation=orientation,
            patch_artist=bool(patch_artist),
            shownotches=bool(notch),
            showmeans=bool(showmeans),
            showcaps=True if showcaps is None else bool(showcaps),
            showbox=True if showbox is None else bool(showbox),
            showfliers=True if showfliers is None else bool(showfliers),
            boxprops=boxprops,
            whiskerprops=whiskerprops,
            flierprops=flierprops,
            medianprops=medianprops,
            capprops=capprops,
            meanprops=meanprops,
            meanline=bool(meanline),
            manage_ticks=manage_ticks,
            zorder=zorder,
            capwidths=capwidths,
            label=label,
        )
        if tick_labels is not None:
            centers = np.arange(1, count + 1) if positions is None else positions
            (self.set_xticks if orientation == "vertical" else self.set_yticks)(
                centers, tick_labels
            )
        return result

    def violinplot(
        self,
        dataset: ArrayLike,
        positions: ArrayLike | None = None,
        *,
        vert: bool | None = None,
        orientation: str = "vertical",
        widths: float = 0.5,
        showmeans: bool = False,
        showextrema: bool = True,
        showmedians: bool = False,
        quantiles: Any = None,
        points: int = 100,
        bw_method: Any = None,
        side: str = "both",
        facecolor: ColorsLike | None = None,
        linecolor: ColorsLike | None = None,
        data: TableLike = None,
    ) -> dict[str, Any]:
        """Violin plots (kernel density estimates) of one or more datasets.

        ``bw_method`` tunes the KDE bandwidth, ``points`` its resolution;
        the ``show*`` flags toggle means/extrema/medians and ``side`` draws
        half violins. Returns the matplotlib-shaped dict of artists.
        """
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        values = _from_data(dataset, data)
        if (
            isinstance(values, (list, tuple))
            and values
            and all(np.ndim(value) == 1 for value in values)
        ):
            groups = [np.asarray(group, dtype=np.float64) for group in values]
        else:
            array = np.asarray(values, dtype=np.float64)
            groups = (
                [array]
                if array.ndim == 1
                else [np.asarray(array[:, index]) for index in range(array.shape[1])]
            )
        if points < 2:
            raise ValueError("violinplot points must be at least 2")
        vpstats: list[dict[str, Any]] = []
        for group in groups:
            group = group[np.isfinite(group)]
            if len(group) == 0:
                raise ValueError("violinplot groups must each contain a finite value")
            coords = np.linspace(float(np.min(group)), float(np.max(group)), int(points))
            std = float(np.std(group, ddof=1)) if len(group) > 1 else 0.0
            if callable(bw_method):

                class _KDECarrier:
                    dataset = group[None, :]
                    n, d = len(group), 1

                    def scotts_factor(self) -> float:
                        return self.n ** (-1 / 5)

                    def silverman_factor(self) -> float:
                        return (self.n * 3 / 4) ** (-1 / 5)

                factor = float(bw_method(_KDECarrier()))
            elif bw_method in (None, "scott"):
                factor = len(group) ** (-1 / 5)
            elif bw_method == "silverman":
                factor = (len(group) * 3 / 4) ** (-1 / 5)
            elif np.isscalar(bw_method):
                factor = _float(bw_method)
            else:
                raise ValueError("bw_method must be 'scott', 'silverman', a scalar, or callable")
            bandwidth = max(std * factor, np.finfo(float).eps)
            delta = (coords[:, None] - group[None, :]) / bandwidth
            density = np.mean(np.exp(-0.5 * delta * delta), axis=1) / (
                bandwidth * np.sqrt(2 * np.pi)
            )
            item: dict[str, Any] = {
                "coords": coords,
                "vals": density,
                "mean": float(np.mean(group)),
                "median": float(np.median(group)),
                "min": float(np.min(group)),
                "max": float(np.max(group)),
            }
            vpstats.append(item)
        if quantiles is not None:
            quantile_groups = list(quantiles)
            if quantile_groups and all(np.isscalar(value) for value in quantile_groups):
                quantile_groups = [quantile_groups]
            elif not quantile_groups:
                quantile_groups = [[] for _ in groups]
            if len(quantile_groups) != len(groups):
                raise ValueError("quantiles must contain one sequence per violin")
            for item, group, requested in zip(vpstats, groups, quantile_groups, strict=True):
                item["quantiles"] = np.quantile(group[np.isfinite(group)], requested)
        return self.violin(
            vpstats,
            positions=positions,
            orientation=orientation,
            widths=widths,
            showmeans=showmeans,
            showextrema=showextrema,
            showmedians=showmedians,
            side=side,
            facecolor=facecolor,
            linecolor=linecolor,
        )

    def errorbar(
        self,
        x: ArrayLike,
        y: ArrayLike,
        yerr: float | ArrayLike | None = None,
        xerr: float | ArrayLike | None = None,
        fmt: str = "",
        *,
        ecolor: ColorLike | None = None,
        elinewidth: float | None = None,
        capsize: float | None = None,
        barsabove: bool = False,
        lolims: bool | ArrayLike = False,
        uplims: bool | ArrayLike = False,
        xlolims: bool | ArrayLike = False,
        xuplims: bool | ArrayLike = False,
        errorevery: Any = 1,
        capthick: float | None = None,
        elinestyle: str | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> ErrorbarContainer:
        """Plot ``y`` versus ``x`` with error bars.

        ``xerr``/``yerr`` are scalars, per-point arrays, or ``(lower,
        upper)`` pairs; ``fmt`` is a ``plot``-style format for the data line
        and markers. ``ecolor``/``elinewidth``/``capsize`` style the bars,
        ``errorevery`` subsamples them, and the ``*lims`` flags zero the
        limited side. Line keywords (``color``/``c``, ``linewidth``/``lw``,
        ``alpha``, ``label``, ...) style the line; ``barsabove``,
        ``capthick``, ``elinestyle``, and unknown keywords raise loudly.
        """
        unsupported = {
            "barsabove": True if barsabove else None,
            "capthick": capthick,
            "elinestyle": elinestyle,
        }
        check_unsupported(
            {name: value for name, value in unsupported.items() if value is not None},
            "errorbar()",
        )
        x, y = _from_data(x, data), _from_data(y, data)
        yerr, xerr = _from_data(yerr, data), _from_data(xerr, data)
        if errorevery != 1:
            start, stride = (
                (0, int(np.asarray(errorevery).item()))
                if np.isscalar(errorevery)
                else map(int, errorevery)
            )
            selection = np.arange(len(np.asarray(x)))[start::stride]
            x, y = np.asarray(x)[selection], np.asarray(y)[selection]

            def subset_error(error: Any) -> Any:
                if error is None or np.isscalar(error):
                    return error
                arr = np.asarray(error)
                return arr[..., selection]

            yerr, xerr = subset_error(yerr), subset_error(xerr)

            def subset_limit(flag: Any) -> Any:
                return flag if np.isscalar(flag) else np.asarray(flag)[selection]

            lolims, uplims = subset_limit(lolims), subset_limit(uplims)
            xlolims, xuplims = subset_limit(xlolims), subset_limit(xuplims)
        x_values = np.asarray(x)
        y_values = np.asarray(y)
        limit_markers: list[tuple[np.ndarray, np.ndarray, str]] = []
        if yerr is not None:
            lower, upper = _error_sides(yerr, len(y_values))
            lower_flags = np.broadcast_to(np.asarray(lolims, dtype=bool), y_values.shape)
            upper_flags = np.broadcast_to(np.asarray(uplims, dtype=bool), y_values.shape)
            if lower_flags.any():
                limit_markers.append(
                    (x_values[lower_flags], y_values[lower_flags] + upper[lower_flags], "^")
                )
            if upper_flags.any():
                limit_markers.append(
                    (x_values[upper_flags], y_values[upper_flags] - lower[upper_flags], "v")
                )
        if xerr is not None:
            lower, upper = _error_sides(xerr, len(x_values))
            lower_flags = np.broadcast_to(np.asarray(xlolims, dtype=bool), x_values.shape)
            upper_flags = np.broadcast_to(np.asarray(xuplims, dtype=bool), x_values.shape)
            if lower_flags.any():
                limit_markers.append(
                    (x_values[lower_flags] + upper[lower_flags], y_values[lower_flags], ">")
                )
            if upper_flags.any():
                limit_markers.append(
                    (x_values[upper_flags] - lower[upper_flags], y_values[upper_flags], "<")
                )
        yerr = _limit_error(yerr, lolims, uplims, len(y_values))
        xerr = _limit_error(xerr, xlolims, xuplims, len(x_values))
        base = line_kwargs(kwargs)
        marker = kwargs.pop("marker", None)
        markersize = kwargs.pop("markersize", kwargs.pop("ms", None))
        check_unsupported(kwargs, "errorbar()")
        # When ecolor is omitted, the bars inherit the resolved data-series
        # color, exactly as matplotlib does: an explicit color kwarg wins, then
        # a color from the fmt string (e.g. ".k"), then the property cycle.
        fmt_color = parse_fmt(fmt)[0] if fmt and fmt.lower() != "none" else None
        # The marker/line color resolves independently of ecolor: an explicit
        # ecolor recolors only the bars (fmt='o', color='black',
        # ecolor='lightgray' keeps black markers).
        line_color: Optional[str] = None
        if "color" in base:
            line_color = base["color"]
        elif fmt_color is not None:
            line_color = resolve_color(fmt_color)
        if ecolor is not None:
            color = resolve_color(ecolor)
        else:
            if line_color is None:
                line_color = self._next_color()
            color = line_color
        resolved_capsize = float(rcParams["errorbar.capsize"] if capsize is None else capsize)
        errorbar_width = float(
            elinewidth if elinewidth is not None else base.get("width", rcParams["lines.linewidth"])
        )
        entry = self._add(
            "@mark",
            {
                "factory": "errorbar",
                "args": (x, y),
                "kwargs": {
                    "yerr": yerr,
                    "xerr": xerr,
                    "name": base.get("name"),
                    "color": color,
                    "width": errorbar_width,
                    "cap_size": resolved_capsize,
                    "opacity": base.get("opacity", 1.0),
                },
            },
        )
        marker_area = float(max(float(rcParams["lines.markersize"]), 2.0 * resolved_capsize) ** 2)
        for marker_x, marker_y, marker_symbol in limit_markers:
            self.scatter(
                marker_x,
                marker_y,
                s=marker_area,
                c=color,
                marker=marker_symbol,
                edgecolors=color,
                linewidths=0.0,
            )
        data_line: Optional[Line2D] = None
        if fmt.lower() != "none":
            line_kwargs_for_plot: dict[str, Any] = {}
            # Pass the already-resolved series color so plot() renders the data
            # line/markers in the same color as the bars without re-advancing
            # the property cycle (fmt still supplies the color when line_color
            # is None, e.g. when ecolor was given explicitly).
            if line_color is not None:
                line_kwargs_for_plot["color"] = line_color
            if "width" in base:
                line_kwargs_for_plot["linewidth"] = base["width"]
            if "opacity" in base:
                line_kwargs_for_plot["alpha"] = base["opacity"]
            if "linestyle" in base:
                line_kwargs_for_plot["linestyle"] = base["linestyle"]
            if "dash" in base:
                line_kwargs_for_plot["dashes"] = base["dash"]
            if marker is not None:
                line_kwargs_for_plot["marker"] = marker
            if markersize is not None:
                line_kwargs_for_plot["markersize"] = markersize
            data_line = self.plot(x, y, fmt, **line_kwargs_for_plot)[0]
        return ErrorbarContainer(Artist(self, entry), data_line)

    def hexbin(
        self,
        x: ArrayLike,
        y: ArrayLike,
        C: ArrayLike | None = None,
        *,
        gridsize: int | tuple[int, int] = 100,
        bins: str | None = None,
        xscale: str = "linear",
        yscale: str = "linear",
        extent: tuple[float, float, float, float] | None = None,
        cmap: Any = None,
        norm: Any = None,
        vmin: float | None = None,
        vmax: float | None = None,
        alpha: float | None = None,
        linewidths: float | None = None,
        edgecolors: str | None = "face",
        reduce_C_function: Callable[..., Any] = np.mean,
        mincnt: int | None = None,
        marginals: bool = False,
        colorizer: Any = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> PathCollection:
        """A hexagonal binning plot of ``x``/``y`` point density.

        With ``C`` given, each hexagon shows ``reduce_C_function`` of the
        values that fall in it instead of a count. ``gridsize`` sets the
        number of hexagons across, ``bins="log"`` log-scales the counts,
        ``mincnt`` hides sparse cells, and ``cmap``/``alpha``/``extent``
        style the mesh. ``norm``, ``vmin``/``vmax``, ``marginals``,
        ``colorizer``, ``linewidths``, non-``"face"`` ``edgecolors``, and
        unknown keywords raise loudly.
        """
        if linewidths is not None:
            raise not_implemented("hexbin(linewidths=...)")
        if edgecolors not in (None, "face"):
            raise not_implemented("hexbin(edgecolors=...)")
        unsupported_options = {
            "norm": norm,
            "marginals": True if marginals else None,
            "colorizer": colorizer,
            "vmin": vmin,
            "vmax": vmax,
        }
        check_unsupported(
            {name: value for name, value in unsupported_options.items() if value is not None},
            "hexbin()",
        )
        check_unsupported(kwargs, "hexbin()")
        x, y = _from_data(x, data), _from_data(y, data)
        if xscale != "linear":
            self.set_xscale(xscale)
        if yscale != "linear":
            self.set_yscale(yscale)
        data_range = None
        if extent is not None:
            xmin, xmax, ymin, ymax = map(float, extent)
            data_range = ((xmin, xmax), (ymin, ymax))
        mode = "log" if bins == "log" else "count"
        entry = self._add(
            "@mark",
            {
                "factory": "hexbin",
                "args": (x, y),
                "x": x,
                "y": y,
                "kwargs": {
                    "gridsize": gridsize,
                    "range": data_range,
                    "bins": mode,
                    "C": None if C is None else _from_data(C, data),
                    "reduce_C_function": reduce_C_function,
                    "mincnt": mincnt,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "opacity": 0.9 if alpha is None else float(alpha),
                },
            },
        )
        if bins == "log":
            # The core pre-transforms the compact per-cell paint channel, but
            # Matplotlib exposes a LogNorm over the original counts. Preserve
            # that normalization contract for the associated colorbar.
            entry["_mpl_norm_scale"] = "log"
        return PathCollection(self, entry)

    def _contour(self, filled: bool, args: tuple[Any, ...], kwargs: dict[str, Any]) -> ContourSet:
        inherited_corner_mask: bool | None = None
        if args and isinstance(args[0], ContourSet):
            source = args[0]._entry
            z = source["args"][0]
            x = source["kwargs"].get("x")
            y = source["kwargs"].get("y")
            inherited_corner_mask = source.get("corner_mask")
            positional_levels = args[1] if len(args) > 1 else None
            args = ()
        elif len(args) in (1, 2):
            z = _masked_float(args[0])
            x = y = None
            positional_levels = args[1] if len(args) == 2 else None
        elif len(args) in (3, 4):
            x, y, z = args[:3]
            z = _masked_float(z)
            positional_levels = args[3] if len(args) == 4 else None
            za = np.asarray(z)
            xa, ya = np.asarray(x), np.asarray(y)
            if xa.ndim == 2 and ya.ndim == 2:
                try:
                    x, y = _regular_mesh_axes(xa, ya, za.shape)
                except ValueError:
                    # Curvilinear grids become an unstructured native
                    # triangulation; all O(n²) topology work remains in Rust.
                    return self._tricontour(
                        filled,
                        (xa.reshape(-1), ya.reshape(-1), za.reshape(-1)),
                        kwargs,
                    )
        elif args:
            raise TypeError("contour() expects Z, [levels] or X, Y, Z, [levels]")
        # Matplotlib's auto-level path is MaxNLocator(N+1) with N=7; matching
        # that default count keeps xy's contour density in step (it previously
        # defaulted to 10, ~1.5x too many isolines).
        levels = kwargs.pop("levels", positional_levels if positional_levels is not None else 7)
        cmap = kwargs.pop("cmap", None)
        colors = kwargs.pop("colors", None)
        linewidths = kwargs.pop("linewidths", None)
        alpha = kwargs.pop("alpha", None)
        origin = kwargs.pop("origin", None)
        if origin == "image":
            origin = rcParams["image.origin"]
        if origin not in (None, "lower", "upper"):
            raise ValueError("origin must be None, 'lower', 'upper', or 'image'")
        extent = kwargs.pop("extent", None)
        norm = kwargs.pop("norm", None)
        linestyles = kwargs.pop("linestyles", None)
        if linestyles not in (None, "-", "solid"):
            raise not_implemented("contour(linestyles=...)")
        corner_mask = kwargs.pop("corner_mask", inherited_corner_mask)
        if corner_mask is None:
            corner_mask = rcParams["contour.corner_mask"]
        if not isinstance(corner_mask, (bool, np.bool_)):
            raise TypeError("corner_mask must be a boolean")
        public_extend = kwargs.pop("extend", None)
        if public_extend is None:
            public_extend = "neither"
        # Matplotlib stores unrecognized public values but treats them as an
        # unextended contour. Keep that observable value on the ContourSet
        # while passing the renderer its normalized four-value contract.
        extend = public_extend if public_extend in ("neither", "min", "max", "both") else "neither"
        cmap_under = cmap_extreme(cmap, "under")
        cmap_over = cmap_extreme(cmap, "over")
        hatches = kwargs.pop("hatches", None)
        locator = kwargs.pop("locator", None)
        za = np.asarray(z, dtype=np.float64)
        if x is None and za.ndim == 2:
            rows, cols = za.shape
            if origin is None:
                if extent is not None:
                    # Without image-oriented origin, extent gives the exact
                    # positions of Z[0, 0] and Z[-1, -1].
                    x0_extent, x1_extent, y0_extent, y1_extent = map(float, extent)
                    x = np.linspace(x0_extent, x1_extent, cols)
                    y = np.linspace(y0_extent, y1_extent, rows)
            else:
                # Matplotlib places contour samples at image-pixel centers.
                # For origin='upper', the first Z row belongs at the top.
                x0_extent, x1_extent, y0_extent, y1_extent = (
                    (0.0, float(cols), 0.0, float(rows))
                    if extent is None
                    else tuple(map(float, extent))
                )
                dx = (x1_extent - x0_extent) / cols
                dy = (y1_extent - y0_extent) / rows
                x = x0_extent + (np.arange(cols, dtype=float) + 0.5) * dx
                y = y0_extent + (np.arange(rows, dtype=float) + 0.5) * dy
                if origin == "upper":
                    y = y[::-1]
        # The native regular-grid contour kernel intentionally requires
        # increasing coordinates.  Matplotlib's origin='upper' represents the
        # same field with descending y centers; reverse both the centers and
        # the corresponding data rows so geometry and public axis direction
        # remain identical while satisfying the kernel contract.
        if x is not None and np.asarray(x).ndim == 1 and len(x) > 1:
            x_values = np.asarray(x, dtype=np.float64)
            if np.all(np.diff(x_values) < 0):
                x = x_values[::-1]
                za = za[:, ::-1]
        if y is not None and np.asarray(y).ndim == 1 and len(y) > 1:
            y_values = np.asarray(y, dtype=np.float64)
            if np.all(np.diff(y_values) < 0):
                y = y_values[::-1]
                za = za[::-1, :]
        if np.isscalar(levels):
            finite = za[np.isfinite(za)]
            if locator is not None and "LogLocator" in type(locator).__name__:
                positive = finite[finite > 0]
                if not positive.size:
                    raise ValueError("LogLocator contour data must contain positive values")
                base = float(getattr(locator, "_base", 10.0))
                low_power = int(np.floor(np.log(positive.min()) / np.log(base)))
                high_power = int(np.ceil(np.log(positive.max()) / np.log(base)))
                levels = base ** np.arange(low_power, high_power + 1, dtype=np.float64)
            else:
                count = int(np.asarray(levels, dtype=np.float64).item())
                levels = _nice_contour_levels(float(finite.min()), float(finite.max()), count)
                # Match ContourSet._autolev: keep one locator boundary beyond
                # each data limit, except that an extended end discards its
                # outer boundary because the under/over band owns that range.
                # Unrecognized public values remain unextended; this preserves
                # the gallery's legacy ``extend="lower"`` behavior.
                under = np.flatnonzero(levels < float(finite.min()))
                lower = int(under[-1]) if under.size else 0
                over = np.flatnonzero(levels > float(finite.max()))
                upper = int(over[0]) + 1 if over.size else len(levels)
                if public_extend in ("min", "both"):
                    lower += 1
                if public_extend in ("max", "both"):
                    upper -= 1
                if upper - lower >= 3:
                    levels = levels[lower:upper]
        public_levels = np.asarray(levels, dtype=np.float64)
        rendered_z = za
        rendered_levels = public_levels
        if norm is not None and callable(norm):
            rendered_z = np.ma.asarray(norm(za), dtype=np.float64).filled(np.nan)
            rendered_levels = np.asarray(norm(public_levels), dtype=np.float64)
        elif locator is not None and "LogLocator" in type(locator).__name__:
            rendered_z = np.where(za > 0, np.log10(za), np.nan)
            rendered_levels = np.log10(public_levels)
        check_unsupported(kwargs, "contour()/contourf()")
        color: Any = None
        monochrome = False
        if colors is not None:
            scalar_color = isinstance(colors, str) or (
                isinstance(colors, tuple)
                and len(colors) in (3, 4)
                and all(
                    np.isscalar(value) and not isinstance(value, (str, bytes)) for value in colors
                )
            )
            color_values = [colors] if scalar_color else list(colors)
            if not color_values:
                raise ValueError("colors must contain at least one color")
            monochrome = len(color_values) == 1
            if not filled and monochrome:
                color = resolve_color(color_values[0])
            else:
                # Matplotlib resizes the supplied sequence to one color per
                # isoline (or one per filled band), repeating short sequences
                # and truncating long ones.  Filled contours may additionally
                # reserve the first/last colors for extended regions.
                ncolors = len(public_levels) - int(filled)
                extend_min = filled and extend in ("min", "both")
                extend_max = filled and extend in ("max", "both")
                total = ncolors + int(extend_min) + int(extend_max)
                use_extreme_colors = len(color_values) == total and (extend_min or extend_max)
                interior_source = (
                    color_values[1:] if use_extreme_colors and extend_min else color_values
                )
                interior = [
                    interior_source[index % len(interior_source)] for index in range(ncolors)
                ]
                resolved = [resolve_rgba(value) for value in interior]
                if extend_min:
                    resolved.insert(
                        0,
                        resolve_rgba(color_values[0]) if use_extreme_colors else resolved[0],
                    )
                if extend_max:
                    resolved.append(
                        resolve_rgba(color_values[-1]) if use_extreme_colors else resolved[-1],
                    )
                color = np.ascontiguousarray(resolved, dtype=np.float64)
        # Keep Matplotlib's public linewidth state in points while the render
        # trace uses output pixels.
        if linewidths is None:
            public_width: Any = float(rcParams["lines.linewidth"])
        elif np.isscalar(linewidths):
            public_width = _float(linewidths)
        else:
            public_width = np.asarray(linewidths, dtype=float).reshape(-1)
            if not len(public_width):
                raise ValueError("linewidths must contain at least one value")
        public_values = np.asarray(public_width, dtype=float).reshape(-1)
        if not np.isfinite(public_values).all() or np.any(public_values <= 0):
            raise ValueError("linewidths must contain positive finite values")
        width_values = public_values * self._point_scale()
        width: Any = float(width_values[0]) if len(width_values) == 1 else width_values
        transparent_fill = filled and isinstance(colors, str) and colors.lower() == "none"
        entry = self._add(
            "@mark",
            {
                "factory": "contour",
                "args": (rendered_z,),
                "kwargs": {
                    "x": x,
                    "y": y,
                    "levels": rendered_levels,
                    "filled": filled,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "color": color,
                    "width": width,
                    "extend": extend,
                    "opacity": 0.0
                    if transparent_fill
                    else (1.0 if alpha is None else float(alpha)),
                    # Matplotlib dashes negative-level lines for a single-color
                    # contour; a colormapped contour keeps every level solid.
                    "dash_negative": (
                        monochrome
                        and linestyles is None
                        and rcParams["contour.negative_linestyle"] == "dashed"
                    ),
                    "corner_mask": bool(corner_mask),
                },
                "source_z": za,
                "source_linewidths": public_width,
                "corner_mask": bool(corner_mask),
                "domain": (float(public_levels[0]), float(public_levels[-1])),
                "hatches": list(hatches) if hatches is not None else None,
                "extend": public_extend,
                "levels": public_levels,
                "cmap_under": cmap_under,
                "cmap_over": cmap_over,
            },
        )
        if filled:
            # A filled contour owns one solid color band between each adjacent
            # level. Preserve both the count and exact boundaries for colorbar
            # renderers instead of degrading it to a continuous gradient.
            entry["discrete_levels"] = max(1, len(public_levels) - 1)
            entry["discrete_boundaries"] = public_levels
        if filled and hatches:
            patterns = list(hatches)
            x_values = (
                np.arange(za.shape[1], dtype=float) if x is None else np.asarray(x, dtype=float)
            )
            y_values = (
                np.arange(za.shape[0], dtype=float) if y is None else np.asarray(y, dtype=float)
            )
            if x_values.ndim == y_values.ndim == 1:
                if len(x_values) == za.shape[1] + 1:
                    x_values = (x_values[:-1] + x_values[1:]) * 0.5
                if len(y_values) == za.shape[0] + 1:
                    y_values = (y_values[:-1] + y_values[1:]) * 0.5
                sample_cols = np.unique(
                    np.linspace(0, len(x_values) - 1, min(34, len(x_values))).astype(int)
                )
                sample_rows = np.unique(
                    np.linspace(0, len(y_values) - 1, min(30, len(y_values))).astype(int)
                )
                dx = (
                    float(np.ptp(x_values)) / max(1, len(sample_cols) - 1)
                    if len(x_values) > 1
                    else 1.0
                )
                dy = (
                    float(np.ptp(y_values)) / max(1, len(sample_rows) - 1)
                    if len(y_values) > 1
                    else 1.0
                )
                hx0: list[float] = []
                hy0: list[float] = []
                hx1: list[float] = []
                hy1: list[float] = []
                dot_x: list[float] = []
                dot_y: list[float] = []
                star_x: list[float] = []
                star_y: list[float] = []
                extend_min = extend in ("min", "both")
                extend_max = extend in ("max", "both")
                for row in sample_rows:
                    for col in sample_cols:
                        if not np.isfinite(za[row, col]):
                            continue
                        band = int(np.searchsorted(levels, za[row, col], side="right") - 1)
                        if band < 0:
                            if not extend_min:
                                continue
                            path_index = 0
                        elif band >= len(levels) - 1:
                            if not extend_max:
                                continue
                            path_index = len(levels) - 1 + int(extend_min)
                        else:
                            path_index = band + int(extend_min)
                        pattern = patterns[path_index % len(patterns)]
                        if not pattern:
                            continue
                        text = str(pattern)
                        cx, cy = float(x_values[col]), float(y_values[row])

                        def stroke(
                            angle: str,
                            offset: float = 0.0,
                            *,
                            _cx: float = cx,
                            _cy: float = cy,
                        ) -> None:
                            if angle == "horizontal":
                                vx, vy, ox, oy = 0.38 * dx, 0.0, 0.0, offset * dy
                            elif angle == "backslash":
                                vx, vy, ox, oy = (
                                    0.32 * dx,
                                    -0.32 * dy,
                                    offset * dx,
                                    offset * dy,
                                )
                            else:
                                vx, vy, ox, oy = (
                                    0.32 * dx,
                                    0.32 * dy,
                                    -offset * dx,
                                    offset * dy,
                                )
                            hx0.append(_cx + ox - vx)
                            hy0.append(_cy + oy - vy)
                            hx1.append(_cx + ox + vx)
                            hy1.append(_cy + oy + vy)

                        if "-" in text:
                            stroke("horizontal")
                        for char, angle in (("/", "slash"), ("\\", "backslash")):
                            count = min(3, text.count(char))
                            for index in range(count):
                                stroke(angle, (index - (count - 1) / 2) * 0.16)
                        if "." in text:
                            dot_x.append(cx)
                            dot_y.append(cy)
                        if "*" in text:
                            star_x.append(cx)
                            star_y.append(cy)
                if hx0:
                    self._add(
                        "@mark",
                        {
                            "factory": "segments",
                            "args": (hx0, hy0, hx1, hy1),
                            "kwargs": {"color": "#222222", "width": 0.9, "opacity": 0.95},
                        },
                    )
                for marker_x, marker_y, symbol, size in (
                    (dot_x, dot_y, "circle", 2.2),
                    (star_x, star_y, "star", 7.0),
                ):
                    if marker_x:
                        overlay = self._add(
                            "scatter",
                            {
                                "x": marker_x,
                                "y": marker_y,
                                "kwargs": {
                                    "color": "#222222",
                                    "opacity": 0.95,
                                    "symbol": symbol,
                                    "size": size,
                                    "stroke_width": 0.0,
                                    "name": None,
                                },
                            },
                        )
                        overlay["_legend_skip"] = True
        return ContourSet(self, entry)

    def contour(self, *args: Any, data: TableLike = None, **kwargs: Any) -> ContourSet:
        """Contour lines of a 2-D array.

        Call as ``contour(Z)``, ``contour(X, Y, Z)``, or with a trailing
        level count/sequence. Supported keywords: ``levels``, ``cmap``,
        ``colors``, ``linewidths``, ``alpha``, ``extent``, ``norm``,
        ``extend``, ``hatches``, ``locator``, and image-oriented ``origin``.
        ``linestyles`` accepts the solid forms ``"-"`` and ``"solid"``;
        other line styles and unknown keywords raise loudly.
        """
        return self._contour(False, tuple(_from_data(value, data) for value in args), kwargs)

    def contourf(self, *args: Any, data: TableLike = None, **kwargs: Any) -> ContourSet:
        """Filled contours of a 2-D array (same call forms as ``contour``).

        Accepts the ``contour`` keywords; ``hatches`` fills bands with
        approximate hatch strokes, and ``colors="none"`` renders a fully
        transparent fill.
        """
        return self._contour(True, tuple(_from_data(value, data) for value in args), kwargs)

    def clabel(
        self,
        CS: ContourSet,
        levels: ArrayLike | None = None,
        *,
        fontsize: float | str | None = None,
        inline: bool = True,
        inline_spacing: float = 5,
        fmt: Any = None,
        colors: Any = None,
        use_clabeltext: bool = False,
        manual: Any = False,
        rightside_up: bool = True,
        zorder: float | None = None,
    ) -> list[Text]:
        """Label connected contour paths using Matplotlib-like screen geometry.

        Marching squares remains native, while path joining and text placement
        stay in the compatibility shim.  Automatic labels prefer flat path
        windows, avoid prior labels in display space, rotate to the local
        tangent, and place at most one label on each eligible connected
        component.  Iterable ``manual`` positions are snapped to the nearest
        requested contour instead of being assigned to levels round-robin.
        ``zorder`` controls the returned text artists. Dynamic aspect-following
        rotation from ``use_clabeltext=True`` is rejected until the shim can
        recompute text transforms after an aspect change.
        """
        if use_clabeltext:
            raise not_implemented(
                "clabel(use_clabeltext=True)",
                "fixed contour-label rotation or explicit relabeling after aspect changes",
            )
        if not isinstance(CS, ContourSet) or CS._axes is not self:
            raise ValueError("clabel() requires a ContourSet from this Axes")
        inline_spacing = float(inline_spacing)
        if not np.isfinite(inline_spacing) or inline_spacing < 0:
            raise ValueError("inline_spacing must be a non-negative finite value")
        if isinstance(manual, (bool, np.bool_)) and bool(manual):
            raise not_implemented(
                "clabel(manual=True)",
                "an iterable of manual data-coordinate positions",
            )

        source = CS._entry
        public_levels = np.asarray(CS.levels, dtype=np.float64).reshape(-1)
        requested = (
            public_levels if levels is None else np.asarray(levels, dtype=np.float64).reshape(-1)
        )
        chosen_indices: list[int] = []
        for index, level in enumerate(public_levels):
            tolerance = np.finfo(float).eps * max(1.0, abs(float(level))) * 8.0
            if np.any(np.isclose(requested, level, rtol=0.0, atol=tolerance)):
                chosen_indices.append(index)
        matched = public_levels[chosen_indices]
        if len(matched) < len(requested):
            raise ValueError(
                f"Specified levels {requested.tolist()} don't match available levels "
                f"{public_levels.tolist()}"
            )

        grid = np.asarray(source["args"][0], dtype=np.float64)
        x_values = source["kwargs"].get("x")
        y_values = source["kwargs"].get("y")
        x_values = (
            np.arange(grid.shape[1], dtype=np.float64)
            if x_values is None
            else np.asarray(x_values, dtype=np.float64)
        )
        y_values = (
            np.arange(grid.shape[0], dtype=np.float64)
            if y_values is None
            else np.asarray(y_values, dtype=np.float64)
        )
        rendered_levels = np.asarray(
            source["kwargs"].get("levels", public_levels), dtype=np.float64
        ).reshape(-1)

        from xy import kernels

        x0, x1, y0, y1, segment_levels = kernels.marching_squares(
            grid, x_values, y_values, rendered_levels
        )
        canvas_width, canvas_height = rc_figsize_px(self.figure._figsize, self.figure._dpi)
        _left, _bottom, axes_width, axes_height = self.get_position().bounds
        plot_width = max(40.0, float(canvas_width) * axes_width)
        plot_height = max(40.0, float(canvas_height) * axes_height)
        x_span = max(float(np.ptp(x_values)), np.finfo(float).eps)
        y_span = max(float(np.ptp(y_values)), np.finfo(float).eps)
        scale = np.asarray((plot_width / x_span, plot_height / y_span), dtype=np.float64)

        all_connected: list[tuple[int, np.ndarray, np.ndarray]] = []
        for public_index, rendered_level in enumerate(rendered_levels):
            tolerance = np.finfo(float).eps * max(1.0, abs(float(rendered_level))) * 16.0
            selected = np.isclose(segment_levels, rendered_level, rtol=0.0, atol=tolerance)
            for path in _joined_contour_paths(
                x0[selected], x1[selected], y0[selected], y1[selected]
            ):
                all_connected.append((public_index, path, path * scale))
        connected = [item for item in all_connected if int(item[0]) in set(chosen_indices)]

        font_points = _text_font_size_points(
            rcParams["font.size"] if fontsize is None else fontsize
        )
        font_pixels = font_points * self._point_scale()

        def label_text(level: float) -> str:
            if callable(getattr(fmt, "format_ticks", None)):
                value = fmt.format_ticks([*matched, level])[-1]
            elif callable(fmt):
                value = fmt(level)
            elif isinstance(fmt, dict):
                value = fmt.get(level, "%1.3f")
            elif isinstance(fmt, str):
                value = fmt % level
            else:
                value = f"{level:g}"
            return _plain_label(value)

        default_colors = _contour_legend_colors(source, len(public_levels))
        color_array = (
            np.asarray(colors) if colors is not None and not isinstance(colors, str) else None
        )
        scalar_explicit_color = isinstance(colors, str) or (
            color_array is not None
            and color_array.ndim == 1
            and len(color_array) in (3, 4)
            and all(
                np.isscalar(value) and not isinstance(value, (str, bytes)) for value in color_array
            )
        )
        if colors is None:
            explicit_colors: list[Any] | None = None
        elif scalar_explicit_color:
            explicit_colors = [colors]
        else:
            explicit_colors = list(colors)
            if not explicit_colors:
                raise ValueError("colors must contain at least one color")

        label_specs: list[dict[str, Any]] = []
        occupied: list[tuple[float, float, float]] = []
        if not (manual is None or (isinstance(manual, (bool, np.bool_)) and not bool(manual))):
            try:
                manual_locations = list(manual)
            except TypeError as exc:
                raise TypeError("manual must be False, True, or an iterable of (x, y)") from exc
            for raw_location in manual_locations:
                values = np.asarray(raw_location, dtype=np.float64).reshape(-1)
                if len(values) != 2 or not np.isfinite(values).all():
                    raise ValueError("manual contour-label positions must be finite (x, y) pairs")
                snapped = _nearest_contour_location(
                    (float(values[0]) * scale[0], float(values[1]) * scale[1]),
                    connected,
                    rightside_up=rightside_up,
                )
                if snapped is None:
                    continue
                public_index = int(snapped["level_index"])
                text = label_text(float(public_levels[public_index]))
                snapped.update(
                    {
                        "level": float(public_levels[public_index]),
                        "text": text,
                        "label_width": max(font_pixels * 0.7, len(text) * font_pixels * 0.62),
                    }
                )
                label_specs.append(snapped)
        else:
            for public_index, path, screen_path in connected:
                text = label_text(float(public_levels[public_index]))
                label_width = max(font_pixels * 0.7, len(text) * font_pixels * 0.62)
                placed = _contour_label_location(
                    path,
                    screen_path,
                    label_width,
                    font_pixels,
                    occupied,
                    rightside_up=rightside_up,
                )
                if placed is None:
                    continue
                placed.update(
                    {
                        "level_index": public_index,
                        "level": float(public_levels[public_index]),
                        "path": path,
                        "screen_path": screen_path,
                        "text": text,
                        "label_width": label_width,
                    }
                )
                label_specs.append(placed)

        if inline and label_specs and not source["kwargs"].get("filled", False):
            exclusions: dict[int, list[tuple[float, float]]] = {}
            for spec in label_specs:
                half_width = float(spec["label_width"]) * 0.5 + inline_spacing
                exclusions.setdefault(id(spec["path"]), []).append(
                    (
                        float(spec["distance"]) - half_width,
                        float(spec["distance"]) + half_width,
                    )
                )
            contour_colors = _contour_legend_colors(source, len(public_levels))
            contour_widths = np.asarray(source["kwargs"].get("width", 1.1), dtype=float).reshape(-1)
            opacity = float(source["kwargs"].get("opacity", 1.0))
            generated: list[dict[str, Any]] = []
            for public_index in range(len(public_levels)):
                visible: list[tuple[np.ndarray, np.ndarray]] = []
                for level_index, path, screen_path in all_connected:
                    if level_index != public_index:
                        continue
                    visible.extend(
                        _contour_visible_segments(
                            path,
                            _path_cumulative(screen_path),
                            exclusions.get(id(path), []),
                        )
                    )
                if not visible:
                    continue
                rendered_width = float(contour_widths[public_index % len(contour_widths)])
                dash = (
                    [3.7 * rendered_width, 1.6 * rendered_width]
                    if source["kwargs"].get("dash_negative") and public_levels[public_index] < 0
                    else None
                )
                generated.append(
                    self._add(
                        "@mark",
                        {
                            "factory": "segments",
                            "args": (
                                [float(segment[0][0]) for segment in visible],
                                [float(segment[0][1]) for segment in visible],
                                [float(segment[1][0]) for segment in visible],
                                [float(segment[1][1]) for segment in visible],
                            ),
                            "kwargs": {
                                "color": contour_colors[public_index],
                                "width": rendered_width,
                                "opacity": opacity,
                                "dash": dash,
                            },
                        },
                    )
                )
            if generated:
                # The mappable remains live for colorbar()/clim(), but its
                # unsplit native trace is hidden behind exact generic segment
                # replacements. Keep those replacements adjacent to the
                # original artist so later marks retain their creation order.
                source["kwargs"]["opacity"] = 0.0
                source_index = next(
                    index for index, entry in enumerate(self._entries) if entry is source
                )
                generated_ids = {id(entry) for entry in generated}
                self._entries[:] = [
                    entry for entry in self._entries if id(entry) not in generated_ids
                ]
                self._entries[source_index + 1 : source_index + 1] = generated
                self._invalidate()

        result: list[Text] = []
        contour_zorder = CS.get_zorder()
        if "_zorder" not in source:
            # Matplotlib's default collection zorders are 1 for filled
            # contours and 2 for contour lines. The shim's contour payload
            # predates public zorder state, so use those defaults only while
            # the caller has not explicitly mutated the ContourSet.
            contour_zorder = 1.0 if source["kwargs"].get("filled", False) else 2.0
        label_zorder = 2.0 + contour_zorder if zorder is None else float(zorder)
        for spec in label_specs:
            public_index = int(spec["level_index"])
            if explicit_colors is None:
                color = default_colors[public_index]
            else:
                color = resolve_color(
                    explicit_colors[chosen_indices.index(public_index) % len(explicit_colors)]
                )
            style = {
                "font_size": font_points,
                "rotation": float(spec["angle"]),
                "vertical_align": "center",
            }
            entry = self._add(
                "@text",
                {
                    "args": (
                        float(spec["position"][0]),
                        float(spec["position"][1]),
                        str(spec["text"]),
                    ),
                    "kwargs": {
                        "anchor": "middle",
                        "color": color,
                        "style": style,
                    },
                },
            )
            label = Text(self, entry)
            label.set_zorder(label_zorder)
            result.append(label)
        return result

    def bxp(
        self,
        bxpstats: Sequence[Mapping[str, Any]],
        positions: ArrayLike | None = None,
        *,
        widths: float | ArrayLike | None = None,
        vert: bool | None = None,
        orientation: str = "vertical",
        patch_artist: bool = False,
        shownotches: bool = False,
        showmeans: bool = False,
        showcaps: bool = True,
        showbox: bool = True,
        showfliers: bool = True,
        boxprops: Mapping[str, Any] | None = None,
        whiskerprops: Mapping[str, Any] | None = None,
        flierprops: Mapping[str, Any] | None = None,
        medianprops: Mapping[str, Any] | None = None,
        capprops: Mapping[str, Any] | None = None,
        meanprops: Mapping[str, Any] | None = None,
        meanline: bool = False,
        manage_ticks: bool = True,
        zorder: float | None = None,
        capwidths: float | ArrayLike | None = None,
        label: str | Sequence[str] | None = None,
    ) -> dict[str, list[Artist]]:
        """Draw exact precomputed box geometry with generic segment/scatter marks."""
        stats = list(bxpstats)
        count = len(stats)
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("bxp orientation must be 'vertical' or 'horizontal'")
        pos = (
            np.arange(1, count + 1, dtype=np.float64)
            if positions is None
            else np.asarray(positions, dtype=np.float64)
        )
        if pos.shape != (count,):
            raise ValueError("bxp positions must match bxpstats")
        default_width = float(np.clip(0.15 * np.ptp(pos), 0.15, 0.5)) if count else 0.15
        box_widths = np.asarray(
            _sequence_param(default_width if widths is None else widths, count, "widths"),
            dtype=np.float64,
        )
        cap_width_values = np.asarray(
            _sequence_param(
                box_widths * 0.5 if capwidths is None else capwidths, count, "capwidths"
            ),
            dtype=np.float64,
        )
        from xy import kernels

        def style(
            props: Any, fallback: Any = None
        ) -> tuple[dict[str, Any], Optional[tuple[tuple[float, float], ...]]]:
            source = dict(props or {})
            color = source.pop("color", source.pop("edgecolor", fallback))
            width = source.pop("linewidth", source.pop("lw", 1.2))
            alpha = source.pop("alpha", 1.0)
            linestyle = source.pop("linestyle", source.pop("ls", None))
            dash_pattern = _dash_segment_pattern("bxp component", linestyle)
            check_unsupported(source, "bxp component properties")
            return (
                {
                    "color": resolve_color(color) if color is not None else fallback,
                    "width": float(width),
                    "opacity": float(alpha),
                },
                dash_pattern,
            )

        def emit(
            coords: list[tuple[float, float, float, float]],
            props: Any,
            fallback: Any,
        ) -> Artist:
            values = np.asarray(coords, dtype=np.float64)
            rendered_style, dash_pattern = style(props, fallback)
            x0, y0, x1, y1 = (
                values[:, 0],
                values[:, 1],
                values[:, 2],
                values[:, 3],
            )
            if dash_pattern is not None:
                x0, y0, x1, y1 = _dashed_segments(x0, y0, x1, y1, dash_pattern)
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": rendered_style,
                },
            )
            return Artist(self, entry)

        def emit_patch(
            coords: list[tuple[float, float, float, float]],
            props: Any,
        ) -> PolyCollection:
            source = dict(props or {})
            combined = source.pop("color", None)
            facecolor = source.pop("facecolor", source.pop("fc", combined or "C0"))
            edgecolor = source.pop(
                "edgecolor",
                source.pop("ec", combined or rcParams["patch.edgecolor"]),
            )
            linewidth = source.pop(
                "linewidth",
                source.pop("lw", rcParams["patch.linewidth"]),
            )
            alpha = source.pop("alpha", 1.0)
            linestyle = source.pop("linestyle", source.pop("ls", None))
            if linestyle not in (None, "solid", "-"):
                raise not_implemented(
                    "bxp patch box linestyle",
                    "solid patch boundaries",
                )
            check_unsupported(source, "bxp patch properties")
            vertices = np.asarray([(x0, y0) for x0, y0, _x1, _y1 in coords])
            topology = kernels.polygon_triangles(vertices[:, 0], vertices[:, 1])
            x0, y0, x1, y1, x2, y2, _ = kernels.indexed_triangles(
                vertices[:, 0],
                vertices[:, 1],
                topology,
            )
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": {
                        "color": resolve_color(facecolor),
                        "stroke": resolve_color(edgecolor),
                        "stroke_width": float(linewidth),
                        "opacity": float(alpha),
                        "_joined_fill": True,
                    },
                },
            )
            return PolyCollection(self, entry)

        def emit_points(
            x_values: Sequence[float],
            y_values: Sequence[float],
            props: Any,
            *,
            default_marker: str,
            default_face: Any,
            default_size: float,
            default_edge: Any = None,
        ) -> Artist:
            source = dict(props or {})
            color = source.pop("color", default_face)
            marker = source.pop("marker", default_marker)
            size = source.pop("markersize", source.pop("ms", default_size))
            facecolor = source.pop("markerfacecolor", source.pop("mfc", color))
            edgecolor = source.pop(
                "markeredgecolor",
                source.pop("mec", color if default_edge is None else default_edge),
            )
            edgewidth = source.pop("markeredgewidth", source.pop("mew", 1.0))
            alpha = source.pop("alpha", 1.0)
            source.pop("linestyle", source.pop("ls", None))
            check_unsupported(source, "bxp point properties")
            entry = self._add(
                "scatter",
                {
                    "x": x_values,
                    "y": y_values,
                    "kwargs": {
                        "color": resolve_color(facecolor),
                        "stroke": resolve_color(edgecolor),
                        "stroke_width": float(edgewidth),
                        "size": float(size),
                        "symbol": MARKER_TO_SYMBOL.get(marker or default_marker, "circle"),
                        "opacity": float(alpha),
                    },
                },
            )
            return Artist(self, entry)

        result: dict[str, list[Artist]] = {
            "boxes": [],
            "medians": [],
            "whiskers": [],
            "caps": [],
            "means": [],
            "fliers": [],
        }
        for index, item in enumerate(stats):
            required = ("med", "q1", "q3", "whislo", "whishi")
            if any(name not in item for name in required):
                raise ValueError(f"bxpstats[{index}] is missing a required statistic")
            center = float(pos[index])
            half = float(box_widths[index]) * 0.5
            cap_half = float(cap_width_values[index]) * 0.5
            q1, q3 = float(item["q1"]), float(item["q3"])
            med = float(item["med"])
            low, high = float(item["whislo"]), float(item["whishi"])
            if orientation == "vertical":
                if shownotches:
                    cilo = float(item.get("cilo", med))
                    cihi = float(item.get("cihi", med))
                    notch_half = half * 0.5
                    box_segments = [
                        (center - half, q1, center + half, q1),
                        (center + half, q1, center + half, cilo),
                        (center + half, cilo, center + notch_half, med),
                        (center + notch_half, med, center + half, cihi),
                        (center + half, cihi, center + half, q3),
                        (center + half, q3, center - half, q3),
                        (center - half, q3, center - half, cihi),
                        (center - half, cihi, center - notch_half, med),
                        (center - notch_half, med, center - half, cilo),
                        (center - half, cilo, center - half, q1),
                    ]
                else:
                    box_segments = [
                        (center - half, q1, center + half, q1),
                        (center + half, q1, center + half, q3),
                        (center + half, q3, center - half, q3),
                        (center - half, q3, center - half, q1),
                    ]
                median_segment = (center - half, med, center + half, med)
                whisker_segments = [
                    (center, low, center, q1),
                    (center, q3, center, high),
                ]
                cap_segments = [
                    (center - cap_half, low, center + cap_half, low),
                    (center - cap_half, high, center + cap_half, high),
                ]
                flier_values = [float(value) for value in item.get("fliers", ())]
                flier_x = [center] * len(flier_values)
                flier_y = flier_values
                if showmeans and "mean" in item:
                    mean = float(item["mean"])
                    if meanline:
                        mean_segment = (center - half, mean, center + half, mean)
                    else:
                        mean_point = (center, mean)
            else:
                if shownotches:
                    cilo = float(item.get("cilo", med))
                    cihi = float(item.get("cihi", med))
                    notch_half = half * 0.5
                    box_segments = [
                        (q1, center - half, q1, center + half),
                        (q1, center + half, cilo, center + half),
                        (cilo, center + half, med, center + notch_half),
                        (med, center + notch_half, cihi, center + half),
                        (cihi, center + half, q3, center + half),
                        (q3, center + half, q3, center - half),
                        (q3, center - half, cihi, center - half),
                        (cihi, center - half, med, center - notch_half),
                        (med, center - notch_half, cilo, center - half),
                        (cilo, center - half, q1, center - half),
                    ]
                else:
                    box_segments = [
                        (q1, center - half, q1, center + half),
                        (q1, center + half, q3, center + half),
                        (q3, center + half, q3, center - half),
                        (q3, center - half, q1, center - half),
                    ]
                median_segment = (med, center - half, med, center + half)
                whisker_segments = [
                    (low, center, q1, center),
                    (q3, center, high, center),
                ]
                cap_segments = [
                    (low, center - cap_half, low, center + cap_half),
                    (high, center - cap_half, high, center + cap_half),
                ]
                flier_values = [float(value) for value in item.get("fliers", ())]
                flier_x = flier_values
                flier_y = [center] * len(flier_values)
                if showmeans and "mean" in item:
                    mean = float(item["mean"])
                    if meanline:
                        mean_segment = (mean, center - half, mean, center + half)
                    else:
                        mean_point = (mean, center)

            if showbox:
                result["boxes"].append(
                    emit_patch(box_segments, boxprops)
                    if patch_artist
                    else emit(box_segments, boxprops, "black")
                )
            result["medians"].append(emit([median_segment], medianprops, "C1"))
            result["whiskers"].extend(
                emit([segment], whiskerprops, "black") for segment in whisker_segments
            )
            if showcaps:
                result["caps"].extend(
                    emit([segment], capprops, "black") for segment in cap_segments
                )
            if showmeans and "mean" in item:
                if meanline:
                    result["means"].append(emit([mean_segment], meanprops, "C2"))
                else:
                    result["means"].append(
                        emit_points(
                            [mean_point[0]],
                            [mean_point[1]],
                            meanprops,
                            default_marker="^",
                            default_face="C2",
                            default_size=6.0,
                        )
                    )
            if showfliers:
                result["fliers"].append(
                    emit_points(
                        flier_x,
                        flier_y,
                        flierprops,
                        default_marker="o",
                        default_face="transparent",
                        default_size=5.0,
                        default_edge="black",
                    )
                )
        legend_handles = result["boxes"] if patch_artist and showbox else result["medians"]
        if label is not None and legend_handles:
            if isinstance(label, str):
                legend_handles[0].set_label(label)
            else:
                labels = list(label)
                if len(labels) != len(legend_handles):
                    raise ValueError("bxp label sequence must match the number of boxes")
                for handle, item_label in zip(legend_handles, labels, strict=True):
                    handle.set_label(str(item_label))
        if zorder is not None:
            for artists in result.values():
                for artist in artists:
                    artist.set_zorder(float(zorder))
        if manage_ticks and result["medians"]:
            category_axis = "x" if orientation == "vertical" else "y"
            category_extent = np.concatenate((pos - 0.5, pos + 0.5))
            result["medians"][0]._entry["_mpl_extent"] = {category_axis: category_extent}
            result["medians"][0]._entry["_mpl_sticky_edges"] = {category_axis: category_extent}
            set_ticks = self.set_xticks if orientation == "vertical" else self.set_yticks
            if any("label" in item for item in stats):
                datalabels = [
                    str(item.get("label", position))
                    for item, position in zip(stats, pos, strict=True)
                ]
                set_ticks(pos, datalabels)
            else:
                set_ticks(pos)
        return result

    def violin(
        self,
        vpstats: Sequence[Mapping[str, Any]],
        positions: ArrayLike | None = None,
        *,
        vert: bool | None = None,
        orientation: str = "vertical",
        widths: float | ArrayLike = 0.5,
        showmeans: bool = False,
        showextrema: bool = True,
        showmedians: bool = False,
        side: str = "both",
        facecolor: ColorsLike | None = None,
        linecolor: ColorsLike | None = None,
    ) -> dict[str, Any]:
        """Draw violin bodies from precomputed coordinates and densities."""
        stats = list(vpstats)
        if vert is not None:
            orientation = "vertical" if vert else "horizontal"
        if orientation not in ("vertical", "horizontal"):
            raise ValueError("violin orientation must be 'vertical' or 'horizontal'")
        if side not in ("both", "low", "high"):
            raise ValueError("violin side must be 'both', 'low', or 'high'")
        pos = (
            np.arange(1, len(stats) + 1, dtype=np.float64)
            if positions is None
            else np.asarray(positions, dtype=np.float64)
        )
        width_values = np.asarray(_sequence_param(widths, len(stats), "widths"), dtype=float)
        if pos.shape != (len(stats),):
            raise ValueError("violin positions must match vpstats")
        default_color = (
            self._next_color() if stats and (facecolor is None or linecolor is None) else "C0"
        )
        body_colors = (
            [default_color] * len(stats)
            if facecolor is None
            else _cycled_colors(facecolor, len(stats), "violin facecolor")
        )
        line_colors = (
            [default_color] * len(stats)
            if linecolor is None
            else _cycled_colors(linecolor, len(stats), "violin linecolor")
        )
        body_opacity = 0.3 if facecolor is None else 1.0
        from xy import kernels

        bodies: list[PolyCollection] = []
        center_segments: dict[str, list[tuple[float, float, float, float]]] = {
            "cmeans": [],
            "cmedians": [],
            "cmins": [],
            "cmaxes": [],
            "cbars": [],
            "cquantiles": [],
        }
        center_colors: dict[str, list[str]] = {name: [] for name in center_segments}
        for index, item in enumerate(stats):
            coords = np.asarray(item["coords"], dtype=np.float64)
            vals = np.asarray(item["vals"], dtype=np.float64)
            if coords.ndim != 1 or vals.shape != coords.shape or len(coords) < 2:
                raise ValueError("violin stats coords and vals must be matching 1-D arrays")
            peak = float(np.max(np.abs(vals)))
            density = np.zeros_like(vals) if peak == 0 else vals / peak * width_values[index] * 0.5
            center = float(pos[index])
            low = center - density if side in ("both", "low") else np.full_like(density, center)
            high = center + density if side in ("both", "high") else np.full_like(density, center)
            if orientation == "vertical":
                polygon_x = np.concatenate((low, high[::-1]))
                polygon_y = np.concatenate((coords, coords[::-1]))
            else:
                polygon_x = np.concatenate((coords, coords[::-1]))
                polygon_y = np.concatenate((low, high[::-1]))
            if float(np.ptp(coords)) == 0.0 or peak == 0:
                # constant data: matplotlib draws a zero-area body; emit an
                # invisible placeholder instead of a degenerate mesh
                entry = self._add(
                    "area",
                    {
                        "x": [center, center],
                        "y": [np.nan, np.nan],
                        "kwargs": {
                            "base": [np.nan, np.nan],
                            "color": body_colors[index],
                            "opacity": 0.0,
                        },
                    },
                )
            else:
                topology = kernels.polygon_triangles(polygon_x, polygon_y)
                x0, y0, x1, y1, x2, y2, _ = kernels.indexed_triangles(
                    polygon_x, polygon_y, topology
                )
                entry = self._add(
                    "@mark",
                    {
                        "factory": "triangle_mesh",
                        "args": (x0, y0, x1, y1, x2, y2),
                        "kwargs": {
                            "color": body_colors[index],
                            "opacity": body_opacity,
                            "_joined_fill": True,
                        },
                    },
                )
            bodies.append(PolyCollection(self, entry))
            half = width_values[index] * 0.25

            def line_at(
                value: float, center: float = center, half: float = half
            ) -> tuple[float, float, float, float]:
                return (
                    (center - half, value, center + half, value)
                    if orientation == "vertical"
                    else (value, center - half, value, center + half)
                )

            minimum, maximum = (
                float(item.get("min", coords.min())),
                float(item.get("max", coords.max())),
            )
            if showextrema:
                center_segments["cmins"].append(line_at(minimum))
                center_colors["cmins"].append(line_colors[index])
                center_segments["cmaxes"].append(line_at(maximum))
                center_colors["cmaxes"].append(line_colors[index])
                center_segments["cbars"].append(
                    (center, minimum, center, maximum)
                    if orientation == "vertical"
                    else (minimum, center, maximum, center)
                )
                center_colors["cbars"].append(line_colors[index])
            if showmeans and "mean" in item:
                center_segments["cmeans"].append(line_at(float(item["mean"])))
                center_colors["cmeans"].append(line_colors[index])
            if showmedians and "median" in item:
                center_segments["cmedians"].append(line_at(float(item["median"])))
                center_colors["cmedians"].append(line_colors[index])
            quantiles = list(item.get("quantiles", ()))
            center_segments["cquantiles"].extend(line_at(float(value)) for value in quantiles)
            center_colors["cquantiles"].extend([line_colors[index]] * len(quantiles))
        result: dict[str, Any] = {"bodies": bodies}
        for name, coordinates in center_segments.items():
            if not coordinates:
                continue
            values = np.asarray(coordinates, dtype=np.float64)
            colors = center_colors[name]
            rendered_color: Any = (
                colors[0] if all(color == colors[0] for color in colors) else colors
            )
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (values[:, 0], values[:, 1], values[:, 2], values[:, 3]),
                    "kwargs": {"color": rendered_color, "width": 1.0},
                },
            )
            result[name] = Artist(self, entry)
        return result

    def hist2d(
        self,
        x: ArrayLike,
        y: ArrayLike,
        bins: Any = 10,
        *,
        range: tuple[tuple[float, float], tuple[float, float]] | None = None,  # noqa: A002 - Matplotlib signature
        density: bool = False,
        weights: ArrayLike | None = None,
        cmin: float | None = None,
        cmax: float | None = None,
        data: TableLike = None,
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, PolyCollection]:
        """A 2-D histogram of ``x``/``y`` rendered as a pseudocolor mesh.

        ``bins``/``range``/``density``/``weights`` follow
        ``numpy.histogram2d``; ``cmin``/``cmax`` blank cells outside the
        count window. Supported keywords: ``cmap``, ``alpha``,
        ``vmin``/``vmax``, and linear or logarithmic normalization.
        Unknown keywords raise loudly.
        Returns ``(counts, xedges, yedges, image)`` as matplotlib does.
        """
        x = np.asarray(_from_data(x, data), dtype=np.float64)
        y = np.asarray(_from_data(y, data), dtype=np.float64)
        if x.ndim != 1 or y.ndim != 1 or len(x) != len(y):
            raise ValueError("hist2d x and y must be equal-length 1-D arrays")
        weight_values = None
        if weights is not None:
            weight_values = np.asarray(_from_data(weights, data), dtype=np.float64)
            if weight_values.ndim != 1 or len(weight_values) != len(x):
                raise ValueError("hist2d weights must have the same length as x and y")
        from xy import kernels

        finite = np.isfinite(x) & np.isfinite(y)
        xv, yv = x[finite], y[finite]
        if not len(xv):
            raise ValueError("hist2d requires at least one finite pair")
        wv = None if weight_values is None else weight_values[finite]
        if range is None:
            xr = kernels.min_max(xv)
            yr = kernels.min_max(yv)
            if xr is None or yr is None:
                raise ValueError("hist2d requires finite x and y ranges")
            xr = (xr[0] - 0.5, xr[1] + 0.5) if xr[0] == xr[1] else xr
            yr = (yr[0] - 0.5, yr[1] + 0.5) if yr[0] == yr[1] else yr
        else:
            if len(range) != 2 or len(range[0]) != 2 or len(range[1]) != 2:
                raise ValueError("hist2d range must be ((xmin, xmax), (ymin, ymax))")
            xr = (float(range[0][0]), float(range[0][1]))
            yr = (float(range[1][0]), float(range[1][1]))

        def make_edges(spec: Any, bounds: tuple[float, float], label: str) -> np.ndarray:
            if isinstance(spec, (int, np.integer)):
                count = int(spec)
                if count <= 0:
                    raise ValueError(f"hist2d {label} bins must be positive")
                return np.linspace(bounds[0], bounds[1], count + 1)
            edges = np.asarray(spec, dtype=np.float64)
            if edges.ndim != 1 or len(edges) < 2 or not np.all(np.diff(edges) > 0):
                raise ValueError(
                    f"hist2d {label} bin edges must be a strictly increasing 1-D array"
                )
            return edges

        if isinstance(bins, (int, np.integer)):
            x_spec = y_spec = bins
        else:
            bin_values = list(bins)
            if len(bin_values) == 2 and (
                any(not np.isscalar(value) for value in bin_values)
                or all(isinstance(value, (int, np.integer)) for value in bin_values)
            ):
                x_spec, y_spec = bin_values
            else:
                x_spec = y_spec = bin_values
        xedges = make_edges(x_spec, xr, "x")
        yedges = make_edges(y_spec, yr, "y")
        # Unlike the density binner, histogram bins include the top/right edge.
        # Keep that Matplotlib/NumPy contract for uniform and irregular bins.
        h = kernels.histogram2d(xv, yv, xedges, yedges, wv)
        if density:
            total = float(h.sum())
            if total:
                areas = np.diff(xedges)[:, None] * np.diff(yedges)[None, :]
                h = h / total / areas
        if cmin is not None:
            h[h < float(cmin)] = np.nan
        if cmax is not None:
            h[h > float(cmax)] = np.nan
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        norm = kwargs.pop("norm", None)
        check_unsupported(kwargs, "hist2d()")
        mesh_values = h.T
        mesh_norm = norm
        mesh_vmin, mesh_vmax = vmin, vmax
        norm_name = norm.lower() if isinstance(norm, str) else type(norm).__name__
        log_domain: tuple[float, float] | None = None
        if norm_name == "linear":
            mesh_norm = None
        elif norm_name in {"log", "LogNorm"}:
            if not isinstance(norm, str) and (vmin is not None or vmax is not None):
                raise ValueError(
                    "Passing a Normalize instance simultaneously with vmin/vmax "
                    "is not supported; set the bounds on the norm instance instead"
                )
            raw = np.asarray(mesh_values, dtype=np.float64)
            finite_positive = raw[np.isfinite(raw) & (raw > 0.0)]
            lo_arg = getattr(norm, "vmin", None) if vmin is None else vmin
            hi_arg = getattr(norm, "vmax", None) if vmax is None else vmax
            if not finite_positive.size and (lo_arg is None or hi_arg is None):
                raise ValueError("log normalization requires at least one positive finite value")
            lo = float(lo_arg) if lo_arg is not None else float(finite_positive.min())
            hi = float(hi_arg) if hi_arg is not None else float(finite_positive.max())
            if not np.isfinite([lo, hi]).all() or lo <= 0.0 or hi <= 0.0:
                raise ValueError("Invalid vmin or vmax")
            if hi < lo:
                raise ValueError("vmin must be less than or equal to vmax")
            invalid = ~np.isfinite(raw) | (raw <= 0.0)
            if callable(norm):
                normalized = np.ma.asarray(
                    norm(np.ma.masked_where(invalid, raw)),
                    dtype=np.float64,
                ).filled(np.nan)
            elif hi == lo:
                normalized = np.zeros(raw.shape, dtype=np.float64)
            else:
                normalized = (np.log(raw, where=~invalid, out=np.zeros_like(raw)) - np.log(lo)) / (
                    np.log(hi) - np.log(lo)
                )
            if normalized.shape != raw.shape:
                raise ValueError("normalization must preserve the histogram grid shape")
            normalized[invalid] = np.nan
            mesh_values = normalized
            mesh_norm = None
            mesh_vmin, mesh_vmax = 0.0, 1.0
            log_domain = (lo, hi)
        image = self.pcolormesh(
            xedges,
            yedges,
            mesh_values,
            cmap=cmap,
            alpha=alpha,
            vmin=mesh_vmin,
            vmax=mesh_vmax,
            norm=mesh_norm,
        )
        if log_domain is not None:
            image._entry["source_z"] = h.T
            image._entry["_mpl_domain"] = log_domain
            image._entry["_mpl_norm_scale"] = "log"
        return h, xedges, yedges, image

    def eventplot(
        self,
        positions: ArrayLike,
        *,
        orientation: str = "horizontal",
        lineoffsets: float | ArrayLike = 1,
        linelengths: float | ArrayLike = 1,
        linewidths: float | ArrayLike | None = None,
        colors: ColorsLike | None = None,
        alpha: float | None = None,
        linestyles: str | Sequence[str] = "solid",
        data: TableLike = None,
        **kwargs: Any,
    ) -> list[PolyCollection]:
        """Plot identical parallel event lines at the given positions.

        One row (or column, with ``orientation="vertical"``) per dataset;
        ``lineoffsets``/``linelengths`` place and size the ticks, and
        ``linewidths``/``colors``/``alpha``/``linestyles`` may be scalars or
        one per dataset. Unknown keywords raise loudly.
        """
        check_unsupported(kwargs, "eventplot()")
        source = _from_data(positions, data)
        try:
            arr = np.asarray(source)
        except ValueError:  # ragged event groups
            arr = np.asarray(source, dtype=object)
        if arr.ndim == 1 and (arr.dtype != object or len(arr) == 0 or np.isscalar(arr[0])):
            groups = [arr]
        elif arr.ndim == 2 and arr.dtype != object:
            groups = list(arr)
        else:
            groups = list(source)
        offsets = _sequence_param(lineoffsets, len(groups), "lineoffsets")
        lengths = _sequence_param(linelengths, len(groups), "linelengths")
        widths = _sequence_param(
            1.5 if linewidths is None else linewidths, len(groups), "linewidths"
        )
        styles = _sequence_param(linestyles, len(groups), "linestyles")
        palette = PROP_CYCLE if colors is None else _sequence_param(colors, len(groups), "colors")
        if colors is None:
            palette = [self._next_color() for _ in groups]
        result: list[PolyCollection] = []
        for group, offset, length, width, color, style in zip(
            groups, offsets, lengths, widths, palette, styles, strict=True
        ):
            values = np.asarray(group, dtype=np.float64)
            fixed = np.full(len(values), float(offset), dtype=np.float64)
            half = float(length) * 0.5
            if orientation == "horizontal":
                x, y = values, fixed
                err_kwargs = {"yerr": half}
            elif orientation == "vertical":
                x, y = fixed, values
                err_kwargs = {"xerr": half}
            else:
                raise ValueError("eventplot orientation must be 'horizontal' or 'vertical'")
            pattern = _dash_segment_pattern("eventplot", style)
            if pattern is None:
                entry = self._add(
                    "@mark",
                    {
                        "factory": "errorbar",
                        "args": (x, y),
                        "kwargs": {
                            **err_kwargs,
                            "cap_size": 0.0,
                            "color": resolve_color(color),
                            "width": float(width),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            else:
                if orientation == "horizontal":
                    ticks = (values, fixed - half, values, fixed + half)
                else:
                    ticks = (fixed - half, values, fixed + half, values)
                entry = self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": _dashed_segments(*ticks, pattern),
                        "kwargs": {
                            "color": resolve_color(color),
                            "width": float(width),
                            "opacity": 1.0 if alpha is None else float(alpha),
                        },
                    },
                )
            result.append(PolyCollection(self, entry))
        return result

    def stackplot(
        self,
        x: ArrayLike,
        *args: Any,
        labels: Sequence[str] = (),
        colors: Any = None,
        baseline: str = "zero",
        data: TableLike = None,
        **kwargs: Any,
    ) -> list[PolyCollection]:
        """Stack areas using native lower/upper-bound computation."""
        if not args:
            raise TypeError("stackplot() requires at least one y series")
        x = np.asarray(_from_data(x, data), dtype=np.float64)
        if len(args) == 1 and not isinstance(args[0], np.ndarray):
            candidate = list(args[0])
            args = tuple(candidate) if candidate and np.ndim(candidate[0]) > 0 else args
        resolved = [_from_data(value, data) for value in args]
        values = np.vstack(resolved).astype(np.float64, copy=False)
        if values.ndim != 2 or values.shape[1] != len(x):
            raise ValueError("stackplot y series must all have the same length as x")
        from xy import kernels

        lower, upper = kernels.stacked_bounds(values, baseline)
        label_values = (
            _sequence_param(labels, values.shape[0], "labels")
            if labels
            else [None] * values.shape[0]
        )
        if colors is None:
            color_values = [self._next_color() for _ in range(values.shape[0])]
        else:
            raw_colors = list(colors) if not isinstance(colors, str) else [colors]
            if not raw_colors:
                raise ValueError("stackplot colors must not be empty")
            color_values = [raw_colors[i % len(raw_colors)] for i in range(values.shape[0])]
        alpha = kwargs.pop("alpha", None)
        linewidth = kwargs.pop("linewidth", kwargs.pop("lw", None))
        edgecolor = kwargs.pop("edgecolor", None)
        facecolor = kwargs.pop("facecolor", None)
        if edgecolor is not None:
            raise not_implemented("stackplot(edgecolor=...)")
        if facecolor is not None:
            color_values = [facecolor] * values.shape[0]
        check_unsupported(kwargs, "stackplot()")
        result: list[PolyCollection] = []
        for row in range(values.shape[0]):
            entry = self._add(
                "@mark",
                {
                    "factory": "area",
                    "args": (x, upper[row]),
                    "kwargs": {
                        "base": lower[row],
                        "name": None if label_values[row] is None else str(label_values[row]),
                        "color": resolve_color(color_values[row]),
                        "opacity": 1.0 if alpha is None else float(alpha),
                        "line_width": 1.2 if linewidth is None else float(linewidth),
                    },
                },
            )
            result.append(PolyCollection(self, entry))
        return result

    def pcolormesh(self, *args: Any, **kwargs: Any) -> PolyCollection:
        """A pseudocolor quadrilateral mesh of a 2-D array.

        Call as ``pcolormesh(C)`` or ``pcolormesh(X, Y, C)``. Supported
        keywords: ``cmap``, ``vmin``/``vmax``, ``alpha``, ``shading``
        (``"flat"``/``"nearest"``/``"auto"``/``"gouraud"``),
        ``edgecolors``/``edgecolor``, ``linewidth``/``linewidths``, ``norm``
        (``"linear"``/``"log"``, their Normalize classes, or ``BoundaryNorm``),
        ``rasterized`` for the regular heatmap path, and ``antialiased``
        (default only).
        Unknown keywords raise loudly.
        """
        if len(args) == 1:
            z = _masked_float(args[0])
            x = y = None
        elif len(args) == 3:
            x, y, raw = args
            z = _masked_float(raw)
        else:
            raise TypeError("pcolormesh() expects C or X, Y, C")
        if z.ndim != 2:
            raise ValueError("pcolormesh C must be 2-D")
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        shading = kwargs.pop("shading", None)
        _reject_non_default("pcolormesh", "antialiased", kwargs.pop("antialiased", None), True)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("linewidths", None))
        norm = kwargs.pop("norm", None)
        rasterized = kwargs.pop("rasterized", False)
        if not isinstance(rasterized, (bool, np.bool_)):
            raise TypeError("pcolormesh rasterized must be a boolean")
        if shading not in (None, "auto", "flat", "nearest", "gouraud"):
            raise ValueError(f"invalid pcolormesh shading {shading!r}")
        check_unsupported(kwargs, "pcolormesh()")
        cmap_value = cmap if cmap is not None else "viridis"
        colormap = resolve_cmap(cmap_value)
        opacity = 1.0 if alpha is None else float(alpha)
        prepared_boundary = prepare_boundary_norm(z, norm, cmap_value, vmin, vmax)
        boundary_boundaries: np.ndarray | None = None
        boundary_colors: np.ndarray | None = None
        if prepared_boundary is None:
            render_z, domain, norm_scale = normalize_scalar_grid(z, norm, vmin, vmax)
            truecolor_z = scalar_grid_rgba(render_z, cmap_value) if norm_scale == "log" else None
        else:
            domain = prepared_boundary.domain
            norm_scale = "boundary"
            truecolor_z = prepared_boundary.rgba
            boundary_boundaries = prepared_boundary.boundaries
            boundary_colors = prepared_boundary.band_colors
        regular = None if x is None else _uniform_mesh_axes(x, y, z.shape)

        def finish(entry: dict[str, Any]) -> PolyCollection:
            if domain is not None:
                entry["_mpl_domain"] = domain
            if norm_scale == "log":
                entry["_mpl_norm_scale"] = norm_scale
            if boundary_boundaries is not None and boundary_colors is not None:
                entry["discrete_levels"] = len(boundary_boundaries) - 1
                entry["discrete_boundaries"] = boundary_boundaries
                entry["discrete_colors"] = boundary_colors
            handle = PolyCollection(self, entry)
            handle._rasterized = bool(rasterized)
            return handle

        if shading == "gouraud":
            gouraud_axes = (
                (np.arange(z.shape[1], dtype=float), np.arange(z.shape[0], dtype=float))
                if x is None
                else _gouraud_rect_axes(x, y, z.shape)
            )
            no_edges = edgecolors is None or (
                isinstance(edgecolors, str) and edgecolors.lower() == "none"
            )
            if gouraud_axes is not None and no_edges:
                width = max(2, min(512, max(256, z.shape[1] * 32)))
                height = max(2, min(512, max(256, z.shape[0] * 32)))
                smooth = _bilinear_grid(
                    truecolor_z if truecolor_z is not None else z, width, height
                )
                gx, gy = gouraud_axes
                mark_kwargs: dict[str, Any] = {
                    "x": np.linspace(float(gx[0]), float(gx[-1]), width),
                    "y": np.linspace(float(gy[0]), float(gy[-1]), height),
                    "colormap": colormap,
                    "opacity": opacity,
                }
                if domain is not None and norm_scale == "linear":
                    mark_kwargs["domain"] = domain
                entry = self._add(
                    "@mark",
                    {
                        "factory": "heatmap",
                        "args": (smooth,),
                        "kwargs": mark_kwargs,
                        "source_z": z,
                    },
                )
                return finish(entry)
        if x is None or (regular is not None and shading != "gouraud"):
            if regular is not None:
                x, y = regular
            elif x is None:
                # Matplotlib's implicit pcolormesh coordinates are cell
                # *edges* 0..N and 0..M.  Heatmaps consume centers, so use
                # half-integer centers to preserve that exact geometry.
                x = np.arange(z.shape[1], dtype=np.float64) + 0.5
                y = np.arange(z.shape[0], dtype=np.float64) + 0.5
            mark_kwargs: dict[str, Any] = {
                "x": x,
                "y": y,
                "colormap": colormap,
                "opacity": opacity,
            }
            if domain is not None and norm_scale == "linear":
                mark_kwargs["domain"] = domain
            entry = self._add(
                "@mark",
                {
                    "factory": "heatmap",
                    "args": (truecolor_z if truecolor_z is not None else z,),
                    "kwargs": mark_kwargs,
                    "source_z": z,
                },
            )
            return finish(entry)

        from xy import kernels

        if rasterized:
            raise not_implemented(
                "pcolormesh(rasterized=True) on a non-uniform mesh",
                "rasterized=True on a regular rectilinear mesh",
            )
        if y is None:
            raise ValueError("pcolormesh requires Y when X is provided")
        x0, y0, x1, y1, x2, y2, scalar = kernels.quad_mesh_triangles(x, y, z)
        mesh_x = np.concatenate((x0, x1, x2))
        mesh_y = np.concatenate((y0, y1, y2))
        finite_x = mesh_x[np.isfinite(mesh_x)]
        finite_y = mesh_y[np.isfinite(mesh_y)]
        # The native expansion elides triangles whose scalar is masked.  An
        # entirely masked QuadMesh still contributes its coordinate grid to
        # Matplotlib's data limits, so recover that extent from X/Y when no
        # triangle survives.
        if not finite_x.size:
            source_x = np.asarray(x, dtype=np.float64).reshape(-1)
            finite_x = source_x[np.isfinite(source_x)]
        if not finite_y.size:
            source_y = np.asarray(y, dtype=np.float64).reshape(-1)
            finite_y = source_y[np.isfinite(source_y)]
        mesh_extent = {
            "x": (float(finite_x.min()), float(finite_x.max())),
            "y": (float(finite_y.min()), float(finite_y.max())),
        }
        finite_triangles = np.isfinite(scalar)
        if not np.all(finite_triangles):
            x0, y0, x1, y1, x2, y2, scalar = (
                values[finite_triangles] for values in (x0, y0, x1, y1, x2, y2, scalar)
            )
        if norm_scale == "boundary":
            scalar_boundary = prepare_boundary_norm(scalar, norm, cmap_value)
            assert scalar_boundary is not None
            painted_scalar = scalar_boundary.rgba
        elif norm_scale == "log":
            normalized_scalar, _resolved_domain, _scale = normalize_scalar_grid(
                scalar,
                norm_scale,
                domain[0] if domain is not None else vmin,
                domain[1] if domain is not None else vmax,
            )
            painted_scalar: Any = scalar_grid_rgba(normalized_scalar, cmap_value)
        else:
            painted_scalar = scalar
        mark_kwargs = {
            "color": painted_scalar,
            "colormap": colormap,
            "opacity": opacity,
        }
        if domain is not None and norm_scale == "linear":
            mark_kwargs["domain"] = domain
        no_edges = edgecolors is None or (
            isinstance(edgecolors, str) and edgecolors.lower() == "none"
        )
        if not no_edges:
            mark_kwargs["stroke"] = resolve_color(edgecolors)
            mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, x1, y1, x2, y2),
                "kwargs": mark_kwargs,
                "source_z": scalar,
                "domain": domain,
                "_mpl_extent": mesh_extent,
                "_mpl_sticky_edges": mesh_extent,
            },
        )
        return finish(entry)

    def pcolor(self, *args: Any, **kwargs: Any) -> PolyCollection:
        """A pseudocolor plot of a 2-D array (see ``pcolormesh``).

        Same call forms and keywords as ``pcolormesh``, which implements it.
        """
        return self.pcolormesh(*args, **kwargs)

    def pcolorfast(self, *args: Any, **kwargs: Any) -> PolyCollection:
        """matplotlib's fast pseudocolor path, served by ``pcolormesh`` here.

        Same call forms and keywords as ``pcolormesh``.
        """
        return self.pcolormesh(*args, **kwargs)

    def matshow(self, z: ArrayLike, **kwargs: Any) -> Any:
        """Display a matrix with ticks on top, as matplotlib's ``matshow``.

        Accepts the ``imshow`` keywords (``cmap``, ``vmin``/``vmax``,
        ``alpha``, ``extent``, ...); the y-axis is reversed and the x ticks
        move to the top.
        """
        kwargs.setdefault("origin", "upper")
        image = self.imshow(z, **kwargs)
        self._axis_props("y")["reverse"] = True
        self._axis_props("x")["side"] = "top"
        self._invalidate()
        return image

    def spy(
        self,
        z: Any,
        precision: float | str = 0,
        marker: str | None = None,
        markersize: float | None = None,
        aspect: str = "equal",
        origin: str = "upper",
        **kwargs: Any,
    ) -> Any:
        """Plot the sparsity pattern of a 2-D array.

        Cells with ``|value| > precision`` are drawn; with ``marker`` or
        ``markersize`` given they render as marker-like blocks instead of
        image cells. Remaining keywords go to ``imshow``; a non-``"equal"``
        ``aspect`` raises loudly.
        """
        _reject_non_default("spy", "aspect", aspect, "equal")
        values = z.toarray() if hasattr(z, "toarray") else np.asarray(z)
        threshold = 0.0 if precision in (None, "present") else float(precision)
        present = np.abs(np.asarray(values, dtype=np.float64)) > threshold
        marker_mode = marker is not None or markersize is not None
        color = (
            np.array([31, 119, 180], dtype=np.uint8) if marker_mode else np.zeros(3, dtype=np.uint8)
        )
        if marker_mode:
            scale = max(3, int(round(float(markersize or 5))))
            image = np.full(
                (present.shape[0] * scale, present.shape[1] * scale, 3),
                255,
                dtype=np.uint8,
            )
            for row, col in np.argwhere(present):
                image[
                    row * scale + 1 : (row + 1) * scale,
                    col * scale + 1 : (col + 1) * scale,
                ] = color
        else:
            image = np.full(present.shape + (3,), 255, dtype=np.uint8)
            image[present] = color
        kwargs["origin"] = origin
        kwargs["extent"] = (-0.5, present.shape[1] - 0.5, -0.5, present.shape[0] - 0.5)
        result = self.imshow(image, **kwargs)
        self._axis_props("y")["reverse"] = True
        self._axis_props("x")["side"] = "top"
        self._invalidate()
        return result

    def pie(
        self,
        x: ArrayLike,
        explode: ArrayLike | None = None,
        labels: Sequence[str] | None = None,
        colors: Any = None,
        autopct: Any = None,
        pctdistance: float = 0.6,
        shadow: bool = False,
        labeldistance: float | None = 1.1,
        startangle: float = 0,
        radius: float = 1,
        counterclock: bool = True,
        wedgeprops: Mapping[str, Any] | None = None,
        textprops: Mapping[str, Any] | None = None,
        center: tuple[float, float] = (0, 0),
        frame: bool = False,
        rotatelabels: bool = False,
        normalize: bool = True,
        hatch: str | Sequence[str] | None = None,
        *,
        data: TableLike = None,
    ) -> Any:
        """A pie chart of the values in ``x``.

        ``explode`` offsets slices, ``autopct`` labels them with their share
        (%-format or callable), ``startangle``/``counterclock`` control
        orientation, and ``wedgeprops``/``textprops`` style slices and
        labels. ``shadow``, ``frame``, ``rotatelabels``, and ``hatch`` raise
        loudly. Returns ``(wedges, texts)`` or ``(wedges, texts, autotexts)``
        as matplotlib does.
        """
        _reject_non_default("pie", "shadow", shadow, False)
        _reject_non_default("pie", "frame", frame, False)
        _reject_non_default("pie", "rotatelabels", rotatelabels, False)
        if hatch is not None:
            raise not_implemented("pie(hatch=...)")
        source_values = np.asarray(_from_data(x, data))
        values = np.asarray(source_values, dtype=np.float64)
        if values.ndim != 1 or len(values) == 0:
            raise ValueError("pie x must be a non-empty 1-D array")
        offsets = np.zeros(len(values), dtype=np.float64)
        if explode is not None:
            offsets = np.asarray(_from_data(explode, data), dtype=np.float64)
            if offsets.shape != values.shape:
                raise ValueError("pie explode must have the same length as x")
        label_values = (
            [None] * len(values)
            if labels is None
            else _sequence_param(labels, len(values), "labels")
        )
        if colors is None:
            color_values = [self._next_color() for _ in values]
        else:
            provided = list(colors) if not isinstance(colors, str) else [colors]
            if not provided:
                raise ValueError("pie colors must not be empty")
            color_values = [provided[index % len(provided)] for index in range(len(values))]
        wedge_style = dict(wedgeprops or {})
        width = wedge_style.pop("width", None)
        edgecolor = wedge_style.pop("edgecolor", wedge_style.pop("ec", None))
        linewidth = wedge_style.pop("linewidth", wedge_style.pop("lw", None))
        alpha = wedge_style.pop("alpha", None)
        if wedge_style.pop("hatch", None) is not None:
            raise not_implemented("pie(wedgeprops={'hatch': ...})")
        if wedge_style:
            check_unsupported(wedge_style, "pie(wedgeprops=)")
        inner_radius = 0.0 if width is None else max(0.0, float(radius) - float(width))
        from xy import kernels

        x0, y0, x1, y1, x2, y2, sectors = kernels.sector_triangles(
            values,
            explode=offsets,
            center=(float(center[0]), float(center[1])),
            radius=float(radius),
            inner_radius=inner_radius,
            start_degrees=float(startangle),
            counterclockwise=bool(counterclock),
            normalize=bool(normalize),
        )
        total = float(np.sum(values)) if normalize else 1.0
        direction = 1.0 if counterclock else -1.0
        boundaries = np.deg2rad(float(startangle)) + direction * np.pi * 2.0 * np.concatenate(
            ([0.0], np.cumsum(values) / total)
        )
        mids = (boundaries[:-1] + boundaries[1:]) * 0.5
        wedges: list[Wedge] = []
        for index in range(len(values)):
            selected = sectors == float(index)
            face = resolve_color(color_values[index])
            mark_kwargs: dict[str, Any] = {
                "color": face,
                "name": None if label_values[index] is None else str(label_values[index]),
                "opacity": 1.0 if alpha is None else float(alpha),
            }
            if edgecolor is not None:
                mark_kwargs["stroke"] = resolve_color(edgecolor)
                mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
            else:
                # A sector is a fan of adjacent triangles. Stroke each fan
                # triangle with its own face color so anti-aliasing cannot
                # expose the figure background as radial hairline spokes.
                mark_kwargs["stroke"] = face
                mark_kwargs["stroke_width"] = 0.75
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (
                        x0[selected],
                        y0[selected],
                        x1[selected],
                        y1[selected],
                        x2[selected],
                        y2[selected],
                    ),
                    "kwargs": mark_kwargs,
                },
            )
            entry["pie_center"] = (float(center[0]), float(center[1]))
            entry["pie_mid"] = float(mids[index])
            entry["pie_radius"] = float(radius)
            entry["pie_explode"] = float(offsets[index])
            theta_start, theta_end = np.rad2deg(boundaries[index : index + 2])
            entry["pie_theta1"] = float(min(theta_start, theta_end))
            entry["pie_theta2"] = float(max(theta_start, theta_end))
            wedges.append(Wedge(self, entry))

        angle = np.deg2rad(float(startangle))
        text_kwargs = _textprops_kwargs(textprops, "pie(textprops=)")

        def add_text(distance: float, mid: float, value: str, offset: float) -> Text:
            local_center_x = float(center[0]) + offset * float(radius) * np.cos(mid)
            local_center_y = float(center[1]) + offset * float(radius) * np.sin(mid)
            entry = self._add(
                "@text",
                {
                    "args": (
                        local_center_x + distance * float(radius) * np.cos(mid),
                        local_center_y + distance * float(radius) * np.sin(mid),
                        value,
                    ),
                    "kwargs": dict(text_kwargs),
                },
            )
            return Text(self, entry)

        texts: list[Text] = []
        autotexts: list[Text] = []
        for index, value in enumerate(values):
            sweep = direction * np.pi * 2.0 * float(value) / total
            mid = angle + sweep * 0.5
            if labeldistance is not None:
                texts.append(
                    add_text(
                        float(labeldistance),
                        mid,
                        "" if label_values[index] is None else str(label_values[index]),
                        float(offsets[index]),
                    )
                )
            if autopct is not None:
                percentage = 100.0 * float(value) / total
                label = autopct(percentage) if callable(autopct) else str(autopct) % percentage
                autotexts.append(
                    add_text(float(pctdistance), mid, str(label), float(offsets[index]))
                )
            angle += sweep
        extent = float(radius) * (1.25 + float(np.max(offsets)))
        self.set_xlim(float(center[0]) - extent, float(center[0]) + extent)
        self.set_ylim(float(center[1]) - extent, float(center[1]) + extent)
        self.set_aspect("equal", adjustable="box")
        if not frame:
            self.set_axis_off()
            self._hidden_spines.update(("left", "bottom", "top", "right"))
        return PieContainer(wedges, source_values, bool(normalize), texts, autotexts)

    def pie_label(
        self,
        container: PieContainer,
        labels: str | Sequence[str],
        *,
        distance: float = 0.6,
        textprops: Mapping[str, Any] | None = None,
        rotate: bool = False,
        alignment: str = "auto",
    ) -> list[Text]:
        """Label the wedges of a ``pie`` result (matplotlib 3.11's ``Axes.pie_label``).

        ``labels`` may be a sequence or a ``{}``-format string receiving
        ``absval`` and ``frac`` per wedge; ``distance`` places labels as a
        fraction of the radius and ``textprops`` styles them.
        ``rotate=True`` orients each label away from its wedge center.
        """
        if alignment not in ("auto", "center", "outer"):
            raise ValueError("pie_label alignment must be 'auto', 'center', or 'outer'")
        resolved_alignment = "outer" if alignment == "auto" and distance > 1 else alignment
        if resolved_alignment == "auto":
            resolved_alignment = "center"
        if isinstance(labels, str):
            formatted = [
                labels.format(absval=value, frac=frac)
                for value, frac in zip(container.values, container.fracs, strict=True)
            ]
        else:
            formatted = list(labels)
        if len(formatted) != len(container.wedges):
            raise ValueError("pie_label labels must match the wedge count")
        text_kwargs = _textprops_kwargs(textprops, "pie_label(textprops=)")
        result: list[Text] = []
        for wedge, label in zip(container.wedges, formatted, strict=True):
            entry_data = wedge._entry
            center_x, center_y = entry_data["pie_center"]
            mid = float(entry_data["pie_mid"])
            radius = float(entry_data["pie_radius"])
            explode = float(entry_data["pie_explode"])
            radial = (float(distance) + explode) * radius
            x = center_x + radial * np.cos(mid)
            y = center_y + radial * np.sin(mid)
            base_style: dict[str, Any] = {"vertical_align": "center"}
            anchor = "middle"
            if resolved_alignment == "outer":
                anchor = "start" if x > 0 else "end"
            if rotate:
                if resolved_alignment == "outer":
                    base_style["vertical_align"] = "bottom" if y > 0 else "top"
                base_style["rotation"] = float(np.rad2deg(mid) + (0.0 if x > 0 else 180.0))
            kwargs = {"anchor": anchor, "style": base_style}
            kwargs.update({key: value for key, value in text_kwargs.items() if key != "style"})
            if text_kwargs.get("style"):
                kwargs["style"] = {**base_style, **text_kwargs["style"]}
            entry = self._add(
                "@text",
                {
                    "args": (x, y, str(label)),
                    "kwargs": kwargs,
                },
            )
            result.append(Text(self, entry))
        container.add_texts(result)
        return result

    def table(
        self,
        cellText: Sequence[Sequence[str]] | None = None,
        cellColours: Any = None,
        cellLoc: str = "right",
        colWidths: Sequence[float] | None = None,
        rowLabels: Sequence[str] | None = None,
        rowColours: Sequence[ColorLike] | None = None,
        rowLoc: str = "left",
        colLabels: Sequence[str] | None = None,
        colColours: Sequence[ColorLike] | None = None,
        colLoc: str = "center",
        loc: str = "bottom",
        bbox: tuple[float, float, float, float] | None = None,
        edges: str = "closed",
        **kwargs: Any,
    ) -> Table:
        """Render an Axes table as generic colored cells, rules, and text."""
        _reject_non_default("table", "cellLoc", cellLoc, "right")
        _reject_non_default("table", "rowLoc", rowLoc, "left")
        _reject_non_default("table", "colLoc", colLoc, "center")
        _reject_non_default("table", "loc", loc, "bottom")
        if cellText is None:
            if cellColours is None:
                raise ValueError("table requires cellText or cellColours")
            shape = np.asarray(cellColours, dtype=object).shape
            raw_text = [[""] * shape[1] for _ in range(shape[0])]
        else:
            raw_text = [list(row) for row in cellText]
        if not raw_text or not raw_text[0] or any(len(row) != len(raw_text[0]) for row in raw_text):
            raise ValueError("table cellText must be a non-empty rectangular matrix")
        rows, cols = len(raw_text), len(raw_text[0])
        raw_colors = (
            [["#ffffff"] * cols for _ in range(rows)]
            if cellColours is None
            else [list(row) for row in cellColours]
        )
        if len(raw_colors) != rows or any(len(row) != cols for row in raw_colors):
            raise ValueError("table cellColours must match cellText")
        if rowLabels is not None:
            labels = list(rowLabels)
            if len(labels) != rows:
                raise ValueError("table rowLabels must match the row count")
            row_palette = (
                ["#ffffff"] * rows
                if rowColours is None
                else _sequence_param(rowColours, rows, "rowColours")
            )
            for index in range(rows):
                raw_text[index].insert(0, labels[index])
                raw_colors[index].insert(0, row_palette[index])
            cols += 1
        if colLabels is not None:
            labels = list(colLabels)
            expected = cols - (1 if rowLabels is not None else 0)
            if len(labels) != expected:
                raise ValueError("table colLabels must match the column count")
            if rowLabels is not None:
                labels.insert(0, "")
            palette = (
                ["#ffffff"] * expected
                if colColours is None
                else _sequence_param(colColours, expected, "colColours")
            )
            if rowLabels is not None:
                palette.insert(0, "#ffffff")
            raw_text.insert(0, labels)
            raw_colors.insert(0, palette)
            rows += 1
        if bbox is None:
            left, bottom, width, height = 0.0, 0.0, 1.0, 1.0
        else:
            left, bottom, width, height = map(float, bbox)
        if colWidths is None:
            widths = np.full(cols, width / cols, dtype=np.float64)
        else:
            widths = np.asarray(colWidths, dtype=np.float64)
            if rowLabels is not None and len(widths) == cols - 1:
                widths = np.insert(widths, 0, widths[0])
            if widths.shape != (cols,):
                raise ValueError("table colWidths must match the column count")
            widths *= width / widths.sum()
        x_edges = left + np.concatenate(([0.0], np.cumsum(widths)))
        y_edges = bottom + np.linspace(0.0, height, rows + 1)
        x0: list[float] = []
        y0: list[float] = []
        x1: list[float] = []
        y1: list[float] = []
        x2: list[float] = []
        y2: list[float] = []
        triangle_colors: list[str] = []
        for row in range(rows):
            display_row = rows - row - 1
            for col in range(cols):
                xa, xb = x_edges[col], x_edges[col + 1]
                ya, yb = y_edges[display_row], y_edges[display_row + 1]
                x0.extend((xa, xa))
                y0.extend((ya, ya))
                x1.extend((xb, xb))
                y1.extend((ya, yb))
                x2.extend((xb, xa))
                y2.extend((yb, yb))
                chosen = resolve_color(raw_colors[row][col]) or "#ffffff"
                triangle_colors.extend((chosen, chosen))
        fill_entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, x1, y1, x2, y2),
                "kwargs": {"color": triangle_colors, "opacity": 0.9},
            },
        )
        artists: list[Artist] = [Artist(self, fill_entry)]
        if edges not in ("", "open"):
            sx0 = np.concatenate((x_edges, np.full(len(y_edges), left)))
            sy0 = np.concatenate((np.full(len(x_edges), bottom), y_edges))
            sx1 = np.concatenate((x_edges, np.full(len(y_edges), left + width)))
            sy1 = np.concatenate((np.full(len(x_edges), bottom + height), y_edges))
            rule_entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (sx0, sy0, sx1, sy1),
                    "kwargs": {"color": "#1f2937", "width": 0.8},
                },
            )
            artists.append(Artist(self, rule_entry))
        text_color = kwargs.pop("color", None)
        fontsize = kwargs.pop("fontsize", None)
        check_unsupported(kwargs, "table()")
        cell_text_kwargs: dict[str, Any] = {}
        if text_color is not None:
            cell_text_kwargs["color"] = resolve_color(text_color)
        if fontsize is not None:
            cell_text_kwargs["style"] = {"font_size": float(fontsize)}
        cells: dict[tuple[int, int], Text] = {}
        for row in range(rows):
            display_row = rows - row - 1
            for col in range(cols):
                entry = self._add(
                    "@text",
                    {
                        "args": (
                            (x_edges[col] + x_edges[col + 1]) * 0.5,
                            (y_edges[display_row] + y_edges[display_row + 1]) * 0.5,
                            str(raw_text[row][col]),
                        ),
                        "kwargs": dict(cell_text_kwargs),
                    },
                )
                handle = Text(self, entry)
                cells[(row, col)] = handle
                artists.append(handle)
        return Table(artists, cells)

    def tripcolor(
        self,
        *args: Any,
        triangles: ArrayLike | None = None,
        facecolors: ArrayLike | None = None,
        shading: str = "flat",
        data: TableLike = None,
        **kwargs: Any,
    ) -> PolyCollection:
        """A pseudocolor plot over an unstructured triangular grid.

        Call as ``tripcolor(x, y, values)`` with optional ``triangles``
        indices (Delaunay otherwise), or pass ``facecolors`` for per-triangle
        values. Supported keywords: ``cmap``, ``alpha``, ``vmin``/``vmax``,
        ``edgecolors``/``edgecolor``, ``linewidth``/``linewidths``,
        ``label``, and ``norm`` (linear ``Normalize`` only); unknown
        keywords raise loudly.
        """
        x, y, topology, rest = _triangulation_inputs(args, triangles, data)
        if facecolors is None:
            if len(rest) != 1:
                raise TypeError("tripcolor() requires one color-value array")
            values = np.asarray(_from_data(rest[0], data), dtype=np.float64)
            values_at = "vertex"
        else:
            if rest:
                raise TypeError("tripcolor() facecolors conflicts with positional color values")
            values = np.asarray(_from_data(facecolors, data), dtype=np.float64)
            values_at = "face"
        if shading not in ("flat", "gouraud"):
            raise ValueError("tripcolor shading must be 'flat' or 'gouraud'")
        cmap = kwargs.pop("cmap", None)
        alpha = kwargs.pop("alpha", None)
        vmin = kwargs.pop("vmin", None)
        vmax = kwargs.pop("vmax", None)
        edgecolors = kwargs.pop("edgecolors", kwargs.pop("edgecolor", None))
        linewidth = kwargs.pop("linewidth", kwargs.pop("linewidths", None))
        label = kwargs.pop("label", None)
        norm = kwargs.pop("norm", None)
        if norm is not None and type(norm).__name__ != "Normalize":
            # Only the linear Normalize maps onto the engine's domain contract.
            raise not_implemented(
                f"tripcolor(norm={type(norm).__name__})", alternative="vmin=/vmax="
            )
        if vmin is None:
            vmin = getattr(norm, "vmin", None)
        if vmax is None:
            vmax = getattr(norm, "vmax", None)
        _reject_non_default("tripcolor", "antialiased", kwargs.pop("antialiased", None), False)
        check_unsupported(kwargs, "tripcolor()")
        from xy import kernels

        x0, y0, x1, y1, x2, y2, scalar = kernels.indexed_triangles(
            x, y, topology, values, values_at=values_at
        )
        mark_kwargs: dict[str, Any] = {
            "color": scalar,
            "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
            "name": None if label is None else str(label),
            "opacity": 1.0 if alpha is None else float(alpha),
        }
        if vmin is not None and vmax is not None:
            mark_kwargs["domain"] = (float(vmin), float(vmax))
        if edgecolors is not None and not (
            isinstance(edgecolors, str) and edgecolors.lower() == "none"
        ):
            mark_kwargs["stroke"] = resolve_color(edgecolors)
            mark_kwargs["stroke_width"] = 1.0 if linewidth is None else float(linewidth)
        entry = self._add(
            "@mark",
            {
                "factory": "triangle_mesh",
                "args": (x0, y0, x1, y1, x2, y2),
                "kwargs": mark_kwargs,
            },
        )
        return PolyCollection(self, entry)

    def triplot(
        self, *args: Any, triangles: ArrayLike | None = None, data: TableLike = None, **kwargs: Any
    ) -> list[Line2D]:
        """Draw the edges of an unstructured triangular grid.

        Call as ``triplot(x, y[, fmt])`` with optional ``triangles`` indices.
        Supported keywords: ``markersize``/``ms`` plus the ``plot`` line
        keywords (``color``/``c``, ``linewidth``/``lw``, ``alpha``,
        ``linestyle``/``ls``, ``label``); ``dashes`` sequences
        and unknown keywords raise loudly.
        """
        x, y, topology, rest = _triangulation_inputs(args, triangles, data)
        fmt = rest[0] if rest else None
        if len(rest) > 1:
            raise TypeError("triplot() accepts at most one format string")
        marker_size = float(kwargs.pop("markersize", kwargs.pop("ms", 6.0))) * (4.0 / 3.0)
        props = _line_props(self, kwargs)
        marker = None
        dash_value = props.pop("dash", None)
        if fmt is not None:
            color_spec, linestyle, marker = parse_fmt(str(fmt))
            if color_spec is not None:
                props["color"] = resolve_color(color_spec)
            if linestyle is not None:
                dash_value = linestyle
        if isinstance(dash_value, (list, tuple)):
            raise not_implemented("triplot(dashes=...)")
        pattern = _dash_segment_pattern("triplot", dash_value)
        check_unsupported(kwargs, "triplot()")
        from xy import kernels

        x0, x1, y0, y1 = kernels.triangle_edges(x, y, topology)
        if pattern is not None:
            x0, y0, x1, y1 = _dashed_segments(x0, y0, x1, y1, pattern)
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": props.get("color"),
                    "width": props.get("width", 1.2),
                    "opacity": props.get("opacity", 1.0),
                    "name": props.get("name"),
                },
            },
        )
        if marker is not None:
            self._add(
                "scatter",
                {
                    "x": x,
                    "y": y,
                    "kwargs": {
                        "color": props.get("color"),
                        "size": marker_size,
                        "opacity": props.get("opacity", 1.0),
                        "symbol": MARKER_TO_SYMBOL.get(marker, "circle"),
                    },
                },
            )
        return [Line2D(self, entry)]

    def _tricontour(
        self, filled: bool, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> ContourSet:
        triangles = kwargs.pop("triangles", None)
        data = kwargs.pop("data", None)
        x, y, topology, rest = _triangulation_inputs(args, triangles, data)
        if not rest:
            raise TypeError("tricontour() requires z values")
        z = np.asarray(_from_data(rest[0], data), dtype=np.float64)
        if z.ndim != 1 or len(z) != len(x):
            raise ValueError("tricontour z must be a 1-D array matching x and y")
        positional_levels = rest[1] if len(rest) > 1 else None
        if len(rest) > 2:
            raise TypeError("tricontour() received too many positional arguments")
        level_arg = kwargs.pop("levels", positional_levels if positional_levels is not None else 10)
        levels = _triangle_levels(z, level_arg)
        cmap = kwargs.pop("cmap", None)
        colors = kwargs.pop("colors", None)
        linewidths = kwargs.pop("linewidths", None)
        alpha = kwargs.pop("alpha", None)
        label = kwargs.pop("label", None)
        where = "tricontourf" if filled else "tricontour"
        norm = kwargs.pop("norm", None)
        if norm is not None and type(norm).__name__ != "Normalize":
            # Only the linear Normalize maps onto the engine's domain contract.
            raise not_implemented(f"{where}(norm={type(norm).__name__})", alternative="vmin=/vmax=")
        # Matplotlib antialiases contour lines but not filled bands by default.
        _reject_non_default(where, "antialiased", kwargs.pop("antialiased", None), not filled)
        linestyles = kwargs.pop("linestyles", None)
        if linestyles not in (None, "-", "solid"):
            raise not_implemented(f"{where}(linestyles=...)")
        _reject_non_default(where, "extend", kwargs.pop("extend", None), "neither")
        hatches = kwargs.pop("hatches", None)
        check_unsupported(kwargs, "tricontour()/tricontourf()")
        colormap = resolve_cmap(cmap) if cmap is not None else "viridis"
        transparent_fill = filled and isinstance(colors, str) and colors.lower() == "none"
        opacity = 0.0 if transparent_fill else (1.0 if alpha is None else float(alpha))
        domain_lo, domain_hi = float(levels[0]), float(levels[-1])
        if domain_lo == domain_hi:
            padding = abs(domain_lo) * 0.05 or 0.5
            domain_lo, domain_hi = domain_lo - padding, domain_hi + padding
        norm_vmin, norm_vmax = getattr(norm, "vmin", None), getattr(norm, "vmax", None)
        if norm_vmin is not None:
            domain_lo = float(norm_vmin)
        if norm_vmax is not None:
            domain_hi = float(norm_vmax)
        explicit_color = None
        if colors is not None:
            explicit_color = resolve_color(
                colors if isinstance(colors, str) else next(iter(colors))
            )
        from xy import kernels

        if filled:
            x0, y0, x1, y1, x2, y2, scalar = kernels.indexed_triangles(
                x, y, topology, z, values_at="vertex"
            )
            mark_kwargs: dict[str, Any] = {
                "color": explicit_color if explicit_color is not None else scalar,
                "colormap": colormap,
                "name": None if label is None else str(label),
                "opacity": opacity,
            }
            if explicit_color is None:
                mark_kwargs["domain"] = (domain_lo, domain_hi)
            entry = self._add(
                "@mark",
                {
                    "factory": "triangle_mesh",
                    "args": (x0, y0, x1, y1, x2, y2),
                    "kwargs": mark_kwargs,
                    "levels": levels,
                },
            )
            if hatches:
                patterns = list(hatches)
                centers_x = np.mean(x[topology], axis=1)
                centers_y = np.mean(y[topology], axis=1)
                centers_z = np.nanmean(z[topology], axis=1)
                sx = max(float(np.ptp(x)) / 70.0, np.finfo(float).eps)
                sy = max(float(np.ptp(y)) / 70.0, np.finfo(float).eps)
                hx0: list[float] = []
                hy0: list[float] = []
                hx1: list[float] = []
                hy1: list[float] = []
                for cx, cy, value in zip(centers_x, centers_y, centers_z, strict=True):
                    band = int(np.searchsorted(levels, value, side="right") - 1)
                    pattern = patterns[band % len(patterns)]
                    if not pattern:
                        continue
                    text = str(pattern)

                    def add(
                        dx: float,
                        dy: float,
                        *,
                        _cx: float = float(cx),
                        _cy: float = float(cy),
                    ) -> None:
                        hx0.append(_cx - dx)
                        hy0.append(_cy - dy)
                        hx1.append(_cx + dx)
                        hy1.append(_cy + dy)

                    if "-" in text or "." in text or "*" in text:
                        add(sx, 0.0)
                    if "/" in text or "." in text or "*" in text:
                        add(sx, sy)
                    if "\\" in text or "*" in text:
                        add(sx, -sy)
                if hx0:
                    self._add(
                        "@mark",
                        {
                            "factory": "segments",
                            "args": (hx0, hy0, hx1, hy1),
                            "kwargs": {"color": "#222222", "width": 0.7},
                        },
                    )
        else:
            x0, x1, y0, y1, segment_levels = kernels.marching_triangles(x, y, z, topology, levels)
            width = _float(np.asarray(linewidths).reshape(-1)[0]) if linewidths is not None else 1.1
            segment_kwargs: dict[str, Any] = {
                "color": explicit_color if explicit_color is not None else segment_levels,
                "colormap": colormap,
                "name": None if label is None else str(label),
                "opacity": opacity,
                "width": width,
            }
            if explicit_color is None:
                segment_kwargs["domain"] = (domain_lo, domain_hi)
            entry = self._add(
                "@mark",
                {
                    "factory": "segments",
                    "args": (x0, y0, x1, y1),
                    "kwargs": segment_kwargs,
                    "levels": levels,
                },
            )
        return ContourSet(self, entry)

    def tricontour(self, *args: Any, **kwargs: Any) -> ContourSet:
        """Contour lines over an unstructured triangular grid.

        Call as ``tricontour(x, y, values[, levels])`` with optional
        ``triangles`` indices. Supported keywords: ``levels``, ``cmap``,
        ``colors``, ``linewidths``, ``alpha``, ``label``, ``norm`` (linear
        ``Normalize`` only), and ``data``. ``linestyles`` accepts the solid
        aliases ``"-"`` and ``"solid"``; other line styles, a non-default
        ``extend``, and unknown keywords raise loudly.
        """
        return self._tricontour(False, args, kwargs)

    def tricontourf(self, *args: Any, **kwargs: Any) -> ContourSet:
        """Filled contours over an unstructured triangular grid.

        Same call forms and keywords as ``tricontour``; ``hatches`` fills
        bands with approximate hatch strokes, and ``colors="none"`` renders
        a fully transparent fill. Filled bands remain a per-triangle color
        approximation rather than clipped triangular isoband polygons.
        """
        return self._tricontour(True, args, kwargs)

    def _vector_field(
        self, args: tuple[Any, ...], kwargs: dict[str, Any], name: str
    ) -> PolyCollection:
        if len(args) == 2:
            raw_u, raw_v = args
            u_grid = _masked_float(raw_u)
            v_grid = _masked_float(raw_v)
            if u_grid.shape != v_grid.shape:
                raise ValueError(f"{name} U and V must have matching shapes")
            if u_grid.ndim == 1:
                x = np.arange(u_grid.size, dtype=np.float64)
                y = np.zeros(u_grid.size, dtype=np.float64)
            elif u_grid.ndim == 2:
                rows, cols = u_grid.shape
                xx, yy = np.meshgrid(np.arange(cols), np.arange(rows))
                x, y = xx.reshape(-1), yy.reshape(-1)
            else:
                raise ValueError(f"{name} U and V must be 1-D or 2-D")
            u, v = u_grid.reshape(-1), v_grid.reshape(-1)
            c = None
        elif len(args) in (4, 5):
            raw_x, raw_y, raw_u, raw_v = args[:4]
            c = args[4] if len(args) == 5 else None
            u_grid = _masked_float(raw_u)
            v_grid = _masked_float(raw_v)
            if u_grid.shape != v_grid.shape:
                raise ValueError(f"{name} U and V must have matching shapes")
            x_grid = _masked_float(raw_x)
            y_grid = _masked_float(raw_y)
            if x_grid.ndim == y_grid.ndim == 1 and u_grid.ndim == 2:
                x_grid, y_grid = np.meshgrid(x_grid, y_grid)
            if x_grid.shape != u_grid.shape or y_grid.shape != u_grid.shape:
                raise ValueError(f"{name} X, Y, U, and V must resolve to matching shapes")
            x, y = x_grid.reshape(-1), y_grid.reshape(-1)
            u, v = u_grid.reshape(-1), v_grid.reshape(-1)
        else:
            raise TypeError(f"{name}() expects U, V or X, Y, U, V[, C]")
        color = kwargs.pop("color", c)
        alpha = kwargs.pop("alpha", None)
        width = kwargs.pop("width", kwargs.pop("linewidth", None))
        scale = kwargs.pop("scale", None)
        pivot = kwargs.pop("pivot", "tail")
        angles = kwargs.pop("angles", "uv")
        scale_units = kwargs.pop("scale_units", None)
        units = kwargs.pop("units", "width")
        _reject_non_default(name, "headwidth", kwargs.pop("headwidth", None), 3.0)
        _reject_non_default(name, "headlength", kwargs.pop("headlength", None), 5.0)
        _reject_non_default(name, "headaxislength", kwargs.pop("headaxislength", None), 4.5)
        _reject_non_default(name, "minshaft", kwargs.pop("minshaft", None), 1.0)
        _reject_non_default(name, "minlength", kwargs.pop("minlength", None), 1.0)
        cmap = kwargs.pop("cmap", None)
        if kwargs.pop("norm", None) is not None:
            raise not_implemented(f"{name}(norm=...)")
        if kwargs.pop("clim", None) is not None:
            raise not_implemented(f"{name}(clim=...)")
        if kwargs.pop("zorder", None) is not None:
            raise not_implemented(f"{name}(zorder=...)")
        check_unsupported(kwargs, f"{name}()")
        if not isinstance(angles, str):
            directions = np.deg2rad(np.asarray(angles, dtype=np.float64).reshape(-1))
            lengths = np.hypot(u, v)
            if directions.shape != lengths.shape:
                raise ValueError(f"{name} angles must match U and V")
            u, v = lengths * np.cos(directions), lengths * np.sin(directions)
        elif angles not in ("uv", "xy"):
            raise ValueError(f"invalid {name} angles {angles!r}")
        if scale_units not in (None, "width", "height", "dots", "inches", "x", "y", "xy"):
            raise ValueError(f"invalid {name} scale_units {scale_units!r}")
        if units not in ("width", "height", "dots", "inches", "x", "y", "xy"):
            raise ValueError(f"invalid {name} units {units!r}")
        from xy import kernels

        magnitudes = np.hypot(u, v)
        if scale is None:
            spacings: list[float] = []
            for positions in (x, y):
                unique = np.unique(positions[np.isfinite(positions)])
                if len(unique) > 1:
                    spacings.append(float(np.median(np.diff(unique))))
            spacing = min(spacings) if spacings else 1.0
            finite_magnitudes = magnitudes[np.isfinite(magnitudes) & (magnitudes > 0)]
            typical = float(np.median(finite_magnitudes)) if len(finite_magnitudes) else 1.0
            vector_scale = typical / max(0.55 * spacing, np.finfo(float).eps)
        else:
            vector_scale = float(scale)
        color_repeats: Optional[np.ndarray] = None
        if name == "barbs":
            starts_x: list[float] = []
            starts_y: list[float] = []
            ends_x: list[float] = []
            ends_y: list[float] = []
            repeats: list[int] = []
            for px, py, du, dv, magnitude in zip(x, y, u, v, magnitudes, strict=True):
                if not np.isfinite(px + py + du + dv + magnitude) or magnitude <= 0:
                    repeats.append(0)
                    continue
                dx, dy = du / magnitude, dv / magnitude
                length = magnitude / vector_scale
                tail_x, tail_y = px, py
                tip_x, tip_y = px + dx * length, py + dy * length
                starts_x.append(float(tail_x))
                starts_y.append(float(tail_y))
                ends_x.append(float(tip_x))
                ends_y.append(float(tip_y))
                count = max(2, min(6, int(round(magnitude / 10.0))))
                for index in range(count):
                    along = length * (0.08 + index * 0.13)
                    bx, by = tip_x - dx * along, tip_y - dy * along
                    starts_x.append(float(bx))
                    starts_y.append(float(by))
                    ends_x.append(float(bx - dx * length * 0.16 - dy * length * 0.28))
                    ends_y.append(float(by - dy * length * 0.16 + dx * length * 0.28))
                repeats.append(1 + count)
            x0, y0, x1, y1 = map(np.asarray, (starts_x, starts_y, ends_x, ends_y))
            color_repeats = np.asarray(repeats, dtype=np.int64)
        else:
            x0, x1, y0, y1 = kernels.vector_segments(
                x,
                y,
                u,
                v,
                scale=vector_scale,
                pivot=pivot,
                head_ratio=0.22,
            )
        segment_color: Any
        if color is not None and not isinstance(color, str):
            values = np.asarray(color).reshape(-1)
            if len(values) != len(x):
                raise ValueError(f"{name} color values must match U and V")
            keep = np.isfinite(x) & np.isfinite(y) & np.isfinite(u) & np.isfinite(v)
            keep &= np.hypot(u, v) > 0
            segment_color = (
                np.repeat(values, color_repeats)
                if color_repeats is not None
                else np.repeat(values[keep], 3)
            )
        else:
            segment_color = resolve_color(color) if color is not None else self._next_color()
        if width is None:
            rendered_width = 1.2
        else:
            # Matplotlib's ``units`` controls arrow *width*, while
            # ``scale_units`` controls length.  Segment widths are pixels in
            # xy, so convert with a stable nominal 500x370 px Axes viewport;
            # resizing preserves the important data-unit distinction.
            x_span = max(float(np.ptp(x[np.isfinite(x)])), np.finfo(float).eps)
            y_span = max(float(np.ptp(y[np.isfinite(y)])), np.finfo(float).eps)
            dots_per_unit = {
                "width": 500.0,
                "height": 370.0,
                "dots": 1.0,
                "inches": 100.0,
                "x": 500.0 / x_span,
                "y": 370.0 / y_span,
                "xy": float(np.hypot(500.0, 370.0) / np.hypot(x_span, y_span)),
            }[units]
            rendered_width = max(0.5, float(width) * dots_per_unit)
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {
                    "color": segment_color,
                    "colormap": resolve_cmap(cmap) if cmap is not None else "viridis",
                    "width": rendered_width,
                    "opacity": 1.0 if alpha is None else float(alpha),
                },
                "vector_scale": vector_scale,
            },
        )
        return PolyCollection(self, entry)

    def _barb_field(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        length: float,
        fill_empty: bool,
        rounding: bool,
        flip_barb: Any,
        sizes: Mapping[str, float],
        barbcolor: Any,
        flagcolor: Any,
        barb_increments: Mapping[str, float],
    ) -> PolyCollection:
        """Render Matplotlib-compatible fixed-length wind-barb geometry."""
        if len(args) == 2:
            raw_u, raw_v = args
            u_grid, v_grid = _masked_float(raw_u), _masked_float(raw_v)
            if u_grid.shape != v_grid.shape:
                raise ValueError("barbs U and V must have matching shapes")
            if u_grid.ndim == 1:
                x, y = np.arange(u_grid.size, dtype=np.float64), np.zeros(u_grid.size)
            elif u_grid.ndim == 2:
                rows, cols = u_grid.shape
                x, y = (
                    values.reshape(-1) for values in np.meshgrid(np.arange(cols), np.arange(rows))
                )
            else:
                raise ValueError("barbs U and V must be 1-D or 2-D")
            u, v, c = u_grid.reshape(-1), v_grid.reshape(-1), None
        elif len(args) in (4, 5):
            raw_x, raw_y, raw_u, raw_v = args[:4]
            c = args[4] if len(args) == 5 else None
            u_grid, v_grid = _masked_float(raw_u), _masked_float(raw_v)
            x_grid, y_grid = _masked_float(raw_x), _masked_float(raw_y)
            if x_grid.ndim == y_grid.ndim == 1 and u_grid.ndim == 2:
                x_grid, y_grid = np.meshgrid(x_grid, y_grid)
            if (
                u_grid.shape != v_grid.shape
                or x_grid.shape != u_grid.shape
                or y_grid.shape != u_grid.shape
            ):
                raise ValueError("barbs X, Y, U, and V must resolve to matching shapes")
            x, y = x_grid.reshape(-1), y_grid.reshape(-1)
            u, v = u_grid.reshape(-1), v_grid.reshape(-1)
        else:
            raise TypeError("barbs() expects U, V or X, Y, U, V[, C]")

        pivot = kwargs.pop("pivot", "tip")
        linewidth = float(kwargs.pop("linewidth", kwargs.pop("lw", 1.0)))
        alpha = float(kwargs.pop("alpha", 1.0))
        color = kwargs.pop("color", None)
        cmap = kwargs.pop("cmap", None)
        if kwargs.pop("norm", None) is not None:
            raise not_implemented("barbs(norm=...)")
        check_unsupported(kwargs, "barbs()")
        if length <= 0:
            raise ValueError("barbs length must be positive")
        if isinstance(pivot, str) and pivot.lower() not in ("tip", "middle", "mid"):
            raise ValueError("barbs pivot must be 'tip', 'middle', or a number")

        allowed_sizes = {"spacing", "height", "width", "emptybarb"}
        unknown_sizes = set(sizes) - allowed_sizes
        if unknown_sizes:
            raise ValueError(f"unsupported barbs sizes: {sorted(unknown_sizes)}")
        increments = {"half": 5.0, "full": 10.0, "flag": 50.0}
        unknown_increments = set(barb_increments) - set(increments)
        if unknown_increments:
            raise ValueError(f"unsupported barb_increments: {sorted(unknown_increments)}")
        increments.update({key: float(value) for key, value in barb_increments.items()})
        if any(value <= 0 for value in increments.values()):
            raise ValueError("barb increments must be positive")

        valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(u) & np.isfinite(v)
        x, y, u, v = x[valid], y[valid], u[valid], v[valid]
        if c is not None:
            c_values = np.ma.asarray(c).filled(np.nan).reshape(-1)
            if len(c_values) != len(valid):
                raise ValueError("barbs color values must match U and V")
            c = c_values[valid]
        flip_values = np.asarray(flip_barb, dtype=bool).reshape(-1)
        if len(flip_values) == 1:
            flip_values = np.broadcast_to(flip_values, len(x))
        elif len(flip_values) == len(valid):
            flip_values = flip_values[valid]
        elif len(flip_values) != len(x):
            raise ValueError("barbs flip_barb must be scalar or match U and V")

        magnitudes = np.hypot(u, v)
        rounded = (
            increments["half"] * np.around(magnitudes / increments["half"])
            if rounding
            else magnitudes.copy()
        )
        nflags = np.floor_divide(rounded, increments["flag"]).astype(int)
        remainder = np.mod(rounded, increments["flag"])
        nbarbs = np.floor_divide(remainder, increments["full"]).astype(int)
        remainder = np.mod(remainder, increments["full"])
        halves = remainder >= increments["half"]
        empty = ~(halves | (nflags > 0) | (nbarbs > 0))

        def visible_span(values: np.ndarray) -> float:
            if values.size == 0:
                return 1.0
            span = float(np.ptp(values))
            if span > np.finfo(float).eps:
                return span
            # Matplotlib's nonsingular locator expands a constant zero-valued
            # offset range to roughly (-.05, .05).
            return max(0.1, 0.1 * float(np.max(np.abs(values), initial=0.0)))

        x_span = visible_span(x)
        y_span = visible_span(y)
        figure_width, figure_height = rc_figsize_px(self.figure._figsize, self.figure._dpi)
        rects = self.figure._effective_rects()
        if rects is None:
            plot_width = figure_width * 0.775
            plot_height = figure_height * 0.77
        else:
            axes_index = self.figure._axes.index(self)
            rect = rects[axes_index]
            plot_width = figure_width * rect[2]
            plot_height = figure_height * rect[3]
        # Barbs are a point-sized PolyCollection in Matplotlib. Its path is
        # scaled by sqrt(length**2 / 4) * dpi / 72 before the data-position
        # offset is applied. Convert that screen-space path scale separately
        # on x/y so a single-panel and a dense subplot grid retain the same
        # visual glyph size and circular calm-wind markers remain circular.
        dpi = float(self.figure._dpi if self.figure._dpi is not None else rcParams["figure.dpi"])
        path_pixel_scale = length * 0.5 * dpi / 72.0
        data_per_path_x = path_pixel_scale * x_span / max(plot_width, 1.0)
        data_per_path_y = path_pixel_scale * y_span / max(plot_height, 1.0)
        spacing = length * float(sizes.get("spacing", 0.125))
        full_height = length * float(sizes.get("height", 0.4))
        full_width = length * float(sizes.get("width", 0.25))
        empty_radius = length * float(sizes.get("emptybarb", 0.15))

        sx0: list[float] = []
        sy0: list[float] = []
        sx1: list[float] = []
        sy1: list[float] = []
        segment_sources: list[int] = []
        tx0: list[float] = []
        ty0: list[float] = []
        tx1: list[float] = []
        ty1: list[float] = []
        tx2: list[float] = []
        ty2: list[float] = []
        triangle_sources: list[int] = []

        def add_segment(ax: float, ay: float, bx: float, by: float, source: int) -> None:
            sx0.append(ax)
            sy0.append(ay)
            sx1.append(bx)
            sy1.append(by)
            segment_sources.append(source)

        def add_triangle(
            ax: float,
            ay: float,
            bx: float,
            by: float,
            cx: float,
            cy: float,
            source: int,
        ) -> None:
            tx0.append(ax)
            ty0.append(ay)
            tx1.append(bx)
            ty1.append(by)
            tx2.append(cx)
            ty2.append(cy)
            triangle_sources.append(source)

        for index, (px, py, du, dv, magnitude) in enumerate(
            zip(x, y, u, v, magnitudes, strict=True)
        ):
            if empty[index] or magnitude <= np.finfo(float).eps:
                theta = np.linspace(0.0, 2.0 * np.pi, 13)
                circle_x = px + empty_radius * data_per_path_x * np.cos(theta)
                circle_y = py + empty_radius * data_per_path_y * np.sin(theta)
                for point_index in range(12):
                    add_segment(
                        float(circle_x[point_index]),
                        float(circle_y[point_index]),
                        float(circle_x[point_index + 1]),
                        float(circle_y[point_index + 1]),
                        index,
                    )
                    if fill_empty:
                        add_triangle(
                            float(px),
                            float(py),
                            float(circle_x[point_index]),
                            float(circle_y[point_index]),
                            float(circle_x[point_index + 1]),
                            float(circle_y[point_index + 1]),
                            index,
                        )
                continue

            ux, uy = du / magnitude, dv / magnitude
            shaft_x, shaft_y = -ux, -uy
            side_sign = -1.0 if flip_values[index] else 1.0
            side_x, side_y = side_sign * -uy, side_sign * ux

            def transform_point(
                staff: float,
                side: float = 0.0,
                *,
                origin_x: float = float(px),
                origin_y: float = float(py),
                staff_x: float = float(shaft_x),
                staff_y: float = float(shaft_y),
                feature_x: float = float(side_x),
                feature_y: float = float(side_y),
            ) -> tuple[float, float]:
                return (
                    origin_x + (staff_x * staff + feature_x * side) * data_per_path_x,
                    origin_y + (staff_y * staff + feature_y * side) * data_per_path_y,
                )

            if isinstance(pivot, str):
                pivot_offset = -length / 2.0 if pivot.lower() in ("middle", "mid") else 0.0
            else:
                pivot_offset = float(pivot)
            root_x, root_y = transform_point(pivot_offset)
            outer_x, outer_y = transform_point(pivot_offset + length)
            add_segment(root_x, root_y, outer_x, outer_y, index)
            offset = length

            for _ in range(nflags[index]):
                if offset != length:
                    offset += spacing / 2.0
                a_x, a_y = transform_point(pivot_offset + offset)
                b_x, b_y = transform_point(
                    pivot_offset + offset - full_width / 2.0,
                    full_height,
                )
                c_x, c_y = transform_point(pivot_offset + offset - full_width)
                add_triangle(a_x, a_y, b_x, b_y, c_x, c_y, index)
                add_segment(a_x, a_y, b_x, b_y, index)
                add_segment(b_x, b_y, c_x, c_y, index)
                offset -= full_width + spacing

            for _ in range(nbarbs[index]):
                a_x, a_y = transform_point(pivot_offset + offset)
                b_x, b_y = transform_point(
                    pivot_offset + offset + full_width / 2.0,
                    full_height,
                )
                add_segment(a_x, a_y, b_x, b_y, index)
                offset -= spacing

            if halves[index]:
                if offset == length:
                    offset -= 1.5 * spacing
                a_x, a_y = transform_point(pivot_offset + offset)
                b_x, b_y = transform_point(
                    pivot_offset + offset + full_width / 4.0,
                    full_height / 2.0,
                )
                add_segment(a_x, a_y, b_x, b_y, index)

        edge_spec = c if c is not None else (barbcolor if barbcolor is not None else color or "k")
        face_spec = c if c is not None else (flagcolor if flagcolor is not None else edge_spec)
        colormap = resolve_cmap(cmap) if cmap is not None else "viridis"
        entries: list[dict[str, Any]] = []

        def emit(
            factory: str,
            coordinates: tuple[list[float], ...],
            sources: list[int],
            color_spec: Any,
            extra: dict[str, Any],
        ) -> None:
            arrays = tuple(np.asarray(values, dtype=np.float64) for values in coordinates)
            source_array = np.asarray(sources, dtype=np.int64)
            if isinstance(color_spec, str):
                groups = [(np.ones(len(source_array), dtype=bool), resolve_color(color_spec))]
            else:
                colors = np.asarray(color_spec)
                if colors.ndim == 0:
                    groups = [
                        (np.ones(len(source_array), dtype=bool), resolve_color(colors.item()))
                    ]
                elif colors.dtype.kind in "OUS":
                    cycled = np.asarray(
                        [resolve_color(colors.reshape(-1)[i % colors.size]) for i in range(len(x))]
                    )
                    groups = [
                        (cycled[source_array] == chosen, chosen)
                        for chosen in dict.fromkeys(cycled.tolist())
                    ]
                else:
                    if colors.size != len(x):
                        raise ValueError("barbs color values must match U and V")
                    groups = [
                        (np.ones(len(source_array), dtype=bool), colors.reshape(-1)[source_array])
                    ]
            for keep, chosen_color in groups:
                if not np.any(keep):
                    continue
                entries.append(
                    self._add(
                        "@mark",
                        {
                            "factory": factory,
                            "args": tuple(values[keep] for values in arrays),
                            "kwargs": {
                                "color": chosen_color,
                                "colormap": colormap,
                                "opacity": alpha,
                                **extra,
                            },
                        },
                    )
                )

        emit(
            "segments",
            (sx0, sy0, sx1, sy1),
            segment_sources,
            edge_spec,
            {"width": linewidth},
        )
        if triangle_sources:
            emit(
                "triangle_mesh",
                (tx0, ty0, tx1, ty1, tx2, ty2),
                triangle_sources,
                face_spec,
                {},
            )
        if not entries:
            entries.append(
                self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": ([], [], [], []),
                        "kwargs": {"color": "#000000", "opacity": 0.0},
                    },
                )
            )
        return PolyCollection(self, entries[0])

    def quiver(self, *args: Any, data: TableLike = None, **kwargs: Any) -> PolyCollection:
        """A field of arrows: ``quiver(U, V)`` or ``quiver(X, Y, U, V[, C])``.

        Supported keywords: ``color``, ``alpha``, ``width``/``linewidth``,
        ``scale``, ``pivot``, ``angles``, ``units``, ``scale_units``,
        ``cmap``, and ``data``. Non-default ``headwidth``/``headlength``/
        ``headaxislength``/``minshaft``/``minlength``, any ``norm``/``clim``/
        ``zorder``, and unknown keywords raise loudly.
        """
        return self._vector_field(
            tuple(_from_data(value, data) for value in args), kwargs, "quiver"
        )

    def barbs(self, *args: Any, data: TableLike = None, **kwargs: Any) -> PolyCollection:
        """A field of wind barbs: ``barbs(U, V)`` or ``barbs(X, Y, U, V[, C])``.

        Supports Matplotlib's fixed-length staff, flag/full/half-barb
        decomposition, pivot, colors, empty-barb fill, feature sizes,
        increment controls, rounding, and per-vector flipping.
        """
        args = tuple(_from_data(value, data) for value in args)
        return self._barb_field(
            args,
            kwargs,
            length=float(kwargs.pop("length", 7.0)),
            fill_empty=bool(kwargs.pop("fill_empty", False)),
            rounding=bool(kwargs.pop("rounding", True)),
            flip_barb=kwargs.pop("flip_barb", False),
            sizes=dict(kwargs.pop("sizes", None) or {}),
            barbcolor=kwargs.pop("barbcolor", None),
            flagcolor=kwargs.pop("flagcolor", None),
            barb_increments=dict(kwargs.pop("barb_increments", None) or {}),
        )

    def quiverkey(
        self,
        Q: PolyCollection,
        X: float,
        Y: float,
        U: float,
        label: str,
        **kwargs: Any,
    ) -> PolyCollection:
        """Add a key (reference arrow + label) for a ``quiver`` plot.

        Supported keywords: ``coordinates`` (default ``"axes"``),
        ``labelpos`` (N/S/E/W), ``labelsep``, ``angle``, ``color``, and
        ``labelcolor``. ``fontproperties``, ``zorder``, and unknown keywords
        raise loudly.
        """
        angle = np.deg2rad(float(kwargs.pop("angle", 0.0)))
        coordinates = kwargs.pop("coordinates", "axes")
        labelpos = kwargs.pop("labelpos", "N")
        labelsep = float(kwargs.pop("labelsep", 0.1))
        color = kwargs.pop("color", Q.get_color())
        labelcolor = kwargs.pop("labelcolor", None)
        if kwargs.pop("fontproperties", None) is not None:
            raise not_implemented("quiverkey(fontproperties=...)")
        if kwargs.pop("zorder", None) is not None:
            raise not_implemented("quiverkey(zorder=...)")
        check_unsupported(kwargs, "quiverkey()")
        from xy import kernels

        if coordinates in ("axes", "figure"):
            qx = np.concatenate((np.asarray(Q._entry["args"][0]), np.asarray(Q._entry["args"][2])))
            qy = np.concatenate((np.asarray(Q._entry["args"][1]), np.asarray(Q._entry["args"][3])))
            x_fraction, y_fraction = float(X), float(Y)
            if coordinates == "figure":
                # Default Matplotlib subplot bounds: left/right=.125/.9 and
                # bottom/top=.11/.88.  Convert figure fractions into the
                # equivalent axes fractions so keys at (.9, .9) sit on the
                # outer top-right edge, as in the gallery.
                x_fraction = (x_fraction - 0.125) / 0.775
                y_fraction = (y_fraction - 0.11) / 0.77
            px = float(np.nanmin(qx) + x_fraction * (np.nanmax(qx) - np.nanmin(qx)))
            py = float(np.nanmin(qy) + y_fraction * (np.nanmax(qy) - np.nanmin(qy)))
        elif coordinates == "data":
            px, py = float(X), float(Y)
        else:
            raise ValueError("quiverkey coordinates must be 'axes', 'figure', or 'data'")
        x0, x1, y0, y1 = kernels.vector_segments(
            np.asarray([px], dtype=np.float64),
            np.asarray([py], dtype=np.float64),
            np.asarray([float(U) * np.cos(angle)], dtype=np.float64),
            np.asarray([float(U) * np.sin(angle)], dtype=np.float64),
            scale=float(Q._entry.get("vector_scale", 1.0)),
            head_ratio=0.22,
        )
        chosen = (
            resolve_color(color)
            if color is not None and isinstance(color, (str, tuple, list))
            else self._next_color()
        )
        entry = self._add(
            "@mark",
            {
                "factory": "segments",
                "args": (x0, y0, x1, y1),
                "kwargs": {"color": chosen, "width": 1.2},
            },
        )
        offsets = {
            "N": (0.0, labelsep),
            "S": (0.0, -labelsep),
            "E": (labelsep, 0.0),
            "W": (-labelsep, 0.0),
        }
        if labelpos not in offsets:
            raise ValueError("quiverkey labelpos must be N, S, E, or W")
        dx, dy = offsets[labelpos]
        # Math mode discards ordinary whitespace, but the plain-text fraction
        # fallback needs a visible word gap before units (`1 m/s`).
        key_label = str(label).replace(r" \frac", r"\ \frac")
        self._add(
            "@text",
            {
                "args": (px + dx, py + dy, mathtext_to_unicode(key_label)),
                "kwargs": {"color": resolve_color(labelcolor)} if labelcolor is not None else {},
            },
        )
        return PolyCollection(self, entry)

    def streamplot(
        self,
        x: ArrayLike,
        y: ArrayLike,
        u: ArrayLike,
        v: ArrayLike,
        density: float | ArrayLike = 1,
        linewidth: float | ArrayLike | None = None,
        color: str | ArrayLike | None = None,
        cmap: Any = None,
        norm: Any = None,
        arrowsize: float = 1,
        arrowstyle: str = "-|>",
        minlength: float = 0.1,
        transform: Any = None,
        zorder: float | None = None,
        start_points: ArrayLike | None = None,
        maxlength: float = 4.0,
        integration_direction: str = "both",
        broken_streamlines: bool = True,
        integration_max_step_scale: float = 1.0,
        integration_max_error_scale: float = 1.0,
        *,
        num_arrows: int = 1,
        data: TableLike = None,
    ) -> StreamplotSet:
        """Streamlines of the vector field ``(u, v)`` on the grid ``(x, y)``.

        ``density`` controls line spacing, ``start_points`` seeds specific
        trajectories, and ``color``/``linewidth`` may be arrays evaluated
        along the field (``cmap``/``norm`` map array colors). Unbroken
        streamlines and the integration step/error scale controls use the
        adaptive Python integrator. Non-default ``arrowstyle`` and
        ``minlength`` raise loudly, as do ``transform`` and ``zorder``.
        """
        if transform is not None:
            raise not_implemented("streamplot(transform=...)")
        if zorder is not None:
            raise not_implemented("streamplot(zorder=...)")
        _reject_non_default("streamplot", "arrowstyle", arrowstyle, "-|>")
        _reject_non_default("streamplot", "minlength", minlength, 0.1)
        if integration_max_step_scale <= 0.0:
            raise ValueError("streamplot integration_max_step_scale must be positive")
        if integration_max_error_scale <= 0.0:
            raise ValueError("streamplot integration_max_error_scale must be positive")
        if norm is not None and type(norm).__name__ != "Normalize":
            # Only the linear Normalize maps onto the engine's domain contract.
            raise not_implemented(
                f"streamplot(norm={type(norm).__name__})",
                alternative="a plain Normalize(vmin=..., vmax=...)",
            )
        if integration_direction not in ("both", "forward", "backward"):
            raise ValueError(
                "streamplot integration_direction must be 'both', 'forward', or 'backward'"
            )
        num_arrows = int(num_arrows)
        if num_arrows < 0:
            raise ValueError("streamplot num_arrows must be non-negative")
        x_values = np.asarray(_from_data(x, data), dtype=np.float64)
        y_values = np.asarray(_from_data(y, data), dtype=np.float64)
        u_values = _masked_float(_from_data(u, data))
        v_values = _masked_float(_from_data(v, data))
        if u_values.shape != v_values.shape or u_values.ndim != 2:
            raise ValueError("streamplot U and V must be matching 2-D arrays")
        if x_values.ndim == y_values.ndim == 2:
            x_values, y_values = _regular_mesh_axes(x_values, y_values, u_values.shape)
        if x_values.ndim != 1 or y_values.ndim != 1:
            raise ValueError("streamplot X and Y must define a regular grid")
        try:
            density_xy = np.broadcast_to(np.asarray(density, dtype=np.float64), 2)
        except ValueError as exc:
            raise ValueError("streamplot density must be a scalar or have length 2") from exc
        if np.any(density_xy <= 0):
            raise ValueError("streamplot density must be positive")
        max_steps = max(1, min(100_000, int(float(maxlength) * max(u_values.shape) * 8)))
        native_fast_path = (
            start_points is None
            and integration_direction == "both"
            and broken_streamlines
            and integration_max_step_scale == 1.0
            and integration_max_error_scale == 1.0
            and density_xy[0] == density_xy[1]
        )
        if start_points is not None:
            seeds = np.asarray(start_points, dtype=np.float64)
            if seeds.ndim != 2 or seeds.shape[1] != 2:
                raise ValueError("streamplot start_points must have shape (n, 2)")
            inside = (
                (seeds[:, 0] >= x_values[0])
                & (seeds[:, 0] <= x_values[-1])
                & (seeds[:, 1] >= y_values[0])
                & (seeds[:, 1] <= y_values[-1])
            )
            if not np.all(inside):
                raise ValueError("streamplot start_points must lie inside the x/y grid")
        elif not native_fast_path:
            seed_x, seed_y = np.meshgrid(
                np.linspace(x_values[0], x_values[-1], max(2, int(18 * density_xy[0]))),
                np.linspace(y_values[0], y_values[-1], max(2, int(18 * density_xy[1]))),
            )
            seeds = np.column_stack((seed_x.reshape(-1), seed_y.reshape(-1)))
        if native_fast_path:
            from xy import kernels

            kx0, kx1, ky0, ky1 = kernels.streamlines(
                x_values,
                y_values,
                u_values,
                v_values,
                density=float(density_xy[0]),
                max_steps=max_steps,
            )
            source_segments = [
                np.asarray(((sx, sy), (ex, ey)), dtype=np.float64)
                for sx, ex, sy, ey in zip(kx0, kx1, ky0, ky1, strict=True)
            ]
        else:
            source_segments = _integrate_streamlines(
                x_values,
                y_values,
                u_values,
                v_values,
                seeds,
                integration_direction,
                max_steps,
                float(maxlength),
                float(minlength),
                broken_streamlines=broken_streamlines,
                density=(float(density_xy[0]), float(density_xy[1])),
                step_scale=integration_max_step_scale,
                error_scale=integration_max_error_scale,
                skip_occupied_seeds=start_points is None,
            )
        x0_values: list[float] = []
        y0_values: list[float] = []
        x1_values: list[float] = []
        y1_values: list[float] = []
        for segment in source_segments:
            x0_values.extend(segment[:-1, 0])
            y0_values.extend(segment[:-1, 1])
            x1_values.extend(segment[1:, 0])
            y1_values.extend(segment[1:, 1])
        x0, y0, x1, y1 = map(
            lambda values: np.asarray(values, dtype=np.float64),
            (x0_values, y0_values, x1_values, y1_values),
        )

        mid_x = (x0 + x1) * 0.5
        mid_y = (y0 + y1) * 0.5
        # Grid-valued color/linewidth arrays are sampled at segment midpoints,
        # so scalar encodings survive without any external integrator.
        if color is not None and not isinstance(color, str):
            color_grid = _masked_float(color)
            if color_grid.shape != u_values.shape:
                raise ValueError("streamplot color array must match the U and V grid shape")
            chosen_color: Any = _bilinear_grid_sample(x_values, y_values, color_grid, mid_x, mid_y)
        else:
            chosen_color = resolve_color(color) if color is not None else self._next_color()
        if linewidth is None:
            width_value: Any = 1.2
        elif np.isscalar(linewidth):
            width_value = float(np.asarray(linewidth, dtype=np.float64).item())
        else:
            width_grid = _masked_float(linewidth)
            if width_grid.shape != u_values.shape:
                raise ValueError("streamplot linewidth array must match the U and V grid shape")
            width_value = _bilinear_grid_sample(x_values, y_values, width_grid, mid_x, mid_y)
        colormap = resolve_cmap(cmap) if cmap is not None else "viridis"
        color_domain = None
        if color is not None and not isinstance(color, str):
            original_color = np.asarray(color, dtype=np.float64)
            original_color = original_color[np.isfinite(original_color)]
            norm_lo, norm_hi = getattr(norm, "vmin", None), getattr(norm, "vmax", None)
            if norm_lo is not None and norm_hi is not None:
                color_domain = (float(norm_lo), float(norm_hi))
            elif original_color.size and float(original_color.min()) != float(original_color.max()):
                color_domain = (float(original_color.min()), float(original_color.max()))

        entries: list[dict[str, Any]] = []
        if isinstance(width_value, np.ndarray) and len(width_value) == len(x0):
            width_array = np.asarray(width_value, dtype=np.float64)
            finite_width = width_array[np.isfinite(width_array)]
            if finite_width.size:
                edges = np.unique(np.quantile(finite_width, np.linspace(0.0, 1.0, 7)))
                bins = np.clip(np.digitize(width_array, edges[1:-1]), 0, max(0, len(edges) - 2))
                for bin_index in np.unique(bins):
                    keep = bins == bin_index
                    kwargs_for_bin: dict[str, Any] = {
                        "color": (
                            np.asarray(chosen_color)[keep]
                            if not isinstance(chosen_color, str)
                            else chosen_color
                        ),
                        "colormap": colormap,
                        "width": float(np.nanmean(width_array[keep])),
                    }
                    if color_domain is not None and not isinstance(chosen_color, str):
                        kwargs_for_bin["domain"] = color_domain
                    entries.append(
                        self._add(
                            "@mark",
                            {
                                "factory": "segments",
                                "args": (x0[keep], y0[keep], x1[keep], y1[keep]),
                                "kwargs": kwargs_for_bin,
                            },
                        )
                    )
        if not entries:
            if isinstance(width_value, np.ndarray):
                width_scalar = float(np.nanmean(width_value)) if width_value.size else 1.2
            else:
                width_scalar = float(width_value)
            entry_kwargs: dict[str, Any] = {
                "color": chosen_color,
                "colormap": colormap,
                "width": width_scalar,
            }
            if color_domain is not None and not isinstance(chosen_color, str):
                entry_kwargs["domain"] = color_domain
            entries.append(
                self._add(
                    "@mark",
                    {
                        "factory": "segments",
                        "args": (x0, y0, x1, y1),
                        "kwargs": entry_kwargs,
                    },
                )
            )
        collection = PolyCollection(self, entries[0])
        arrow_collection = collection
        if num_arrows > 0 and len(x0):
            if native_fast_path:
                arrow_count = max(
                    1,
                    min(len(x0), num_arrows * int(30 * float(density_xy[0]))),
                )
                arrow_indices = np.unique(np.linspace(0, len(x0) - 1, arrow_count, dtype=np.int64))
            else:
                arrow_indices_list: list[int] = []
                segment_offset = 0
                for streamline in source_segments:
                    deltas = np.diff(streamline, axis=0)
                    lengths = np.hypot(
                        deltas[:, 0] / max(float(np.ptp(x_values)), np.finfo(float).eps),
                        deltas[:, 1] / max(float(np.ptp(y_values)), np.finfo(float).eps),
                    )
                    cumulative = np.cumsum(lengths)
                    if cumulative.size and cumulative[-1] > 0.0:
                        targets = cumulative[-1] * (
                            np.arange(1, num_arrows + 1, dtype=np.float64) / (num_arrows + 1)
                        )
                        local = np.clip(np.searchsorted(cumulative, targets), 0, len(lengths) - 1)
                        arrow_indices_list.extend((segment_offset + local).tolist())
                    segment_offset += len(lengths)
                arrow_indices = np.unique(np.asarray(arrow_indices_list, dtype=np.int64))
            dx = x1[arrow_indices] - x0[arrow_indices]
            dy = y1[arrow_indices] - y0[arrow_indices]
            lengths = np.hypot(dx, dy)
            valid = np.isfinite(lengths) & (lengths > np.finfo(float).eps)
            arrow_indices = arrow_indices[valid]
            if len(arrow_indices):
                ux = dx[valid] / lengths[valid]
                uy = dy[valid] / lengths[valid]
                scale = (
                    0.022 * min(float(np.ptp(x_values)), float(np.ptp(y_values))) * float(arrowsize)
                )
                tip_x, tip_y = x1[arrow_indices], y1[arrow_indices]
                base_x, base_y = tip_x - ux * scale, tip_y - uy * scale
                wing = scale * 0.42
                left_x, left_y = base_x - uy * wing, base_y + ux * wing
                right_x, right_y = base_x + uy * wing, base_y - ux * wing
                arrow_color: Any = chosen_color
                if not isinstance(chosen_color, str):
                    arrow_color = np.asarray(chosen_color)[arrow_indices]
                arrow_kwargs: dict[str, Any] = {
                    "color": arrow_color,
                    "colormap": colormap,
                    "opacity": 1.0,
                }
                if color_domain is not None and not isinstance(arrow_color, str):
                    arrow_kwargs["domain"] = color_domain
                arrow_entry = self._add(
                    "@mark",
                    {
                        "factory": "triangle_mesh",
                        "args": (tip_x, tip_y, left_x, left_y, right_x, right_y),
                        "kwargs": arrow_kwargs,
                    },
                )
                arrow_collection = PolyCollection(self, arrow_entry)
        return StreamplotSet(collection, arrow_collection)
