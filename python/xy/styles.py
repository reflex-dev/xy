"""CSS-first styling for rendered XY marks.

DOM chrome already accepts arbitrary safe CSS declarations.  Marks are drawn
by WebGL, SVG, and the native rasterizer, so they cannot honestly accept the
entire browser cascade.  This module defines the smaller, internal CSS subset
that all renderers can compile to XY's existing trace style vocabulary.

The input contract is ordinary CSS: kebab-case property names and CSS values.
Python snake_case aliases remain accepted for ergonomics and backwards
compatibility, but normalized output uses CSS names.
Unsupported declarations fail before data ingestion rather than being silently
ignored by one renderer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, TypeAlias

import numpy as np

from . import _validate

StyleValue: TypeAlias = str | int | float
StyleMapping: TypeAlias = Mapping[str, StyleValue]

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_PX_RE = re.compile(rf"^\s*({_NUMBER})(?:px)?\s*$", re.IGNORECASE)

_LINE_KINDS = frozenset({"line", "step", "stairs", "ecdf"})
_SIMPLE_STROKE_KINDS = frozenset({"segments", "errorbar", "contour", "stem"})
_AREA_KINDS = frozenset({"area", "error_band"})
_POINT_KINDS = frozenset({"scatter"})
_RECT_KINDS = frozenset({"histogram", "hist", "bar", "column"})
_FILL_KINDS = frozenset({"box", "violin"})
_MESH_KINDS = frozenset({"triangle_mesh"})
_DENSITY_KINDS = frozenset({"heatmap", "hexbin"})

_AXIS_COLOR_PROPERTIES = frozenset(
    {"grid_color", "axis_color", "tick_color", "tick_label_color", "label_color"}
)
_AXIS_LENGTH_PROPERTIES = frozenset({"grid_width", "axis_width", "tick_length", "tick_width"})
_AXIS_SIZE_PROPERTIES = frozenset({"tick_size", "tick_label_size", "label_size"})
_AXIS_COMPAT_PROPERTIES = frozenset({"grid_dash", "grid_opacity"})
_AXIS_DASH_STYLES = frozenset({"solid", "dashed", "dotted", "dashdot"})
_AXIS_DIRECTIONS = frozenset({"in", "out", "inout"})

_MARK_KINDS = tuple(
    sorted(
        _LINE_KINDS
        | _SIMPLE_STROKE_KINDS
        | _AREA_KINDS
        | _POINT_KINDS
        | _RECT_KINDS
        | _FILL_KINDS
        | _MESH_KINDS
        | _DENSITY_KINDS
    )
)


def normalize_css_style(value: StyleMapping | None, label: str = "style") -> dict[str, StyleValue]:
    """Validate and canonicalize a CSS declaration mapping.

    The shared declaration grammar provides injection safety and strict checks
    for known colors, lengths, and numeric properties.  Canonicalization makes
    serialization and schema-driven generation deterministic.
    """
    if value is None:
        return {}
    raw = dict(value)
    gradient_fills: dict[str, StyleValue] = {}
    ordinary: dict[str, StyleValue] = {}
    for key, item in raw.items():
        canonical = _validate._css_property_name(key).lower() if isinstance(key, str) else key
        if (
            canonical == "fill"
            and isinstance(item, str)
            and item.strip().lower().startswith("linear-gradient(")
        ):
            _validate.mark_fill(item, f"{label}[{key!r}]")
            gradient_fills[key] = item
        else:
            ordinary[key] = item
    validated = _validate.style_mapping(ordinary, label)
    validated.update(gradient_fills)
    out: dict[str, StyleValue] = {}
    for key, item in validated.items():
        canonical = _validate._css_property_name(key).lower()
        if canonical in out and out[canonical] != item:
            raise ValueError(
                f"{label} defines {canonical!r} more than once through CSS/Python aliases"
            )
        out[canonical] = item
    return out


def _px(value: StyleValue, label: str, *, positive: bool = False) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        match = _PX_RE.match(value)
        if match is None:
            raise ValueError(f"{label} must be a finite CSS px length")
        number = float(match.group(1))
    else:  # pragma: no cover - normalize_css_style rejects this first
        raise ValueError(f"{label} must be a finite CSS px length")
    if not np.isfinite(number) or number < 0 or (positive and number <= 0):
        qualifier = "positive " if positive else "non-negative "
        raise ValueError(f"{label} must be a {qualifier}finite CSS px length")
    return number


def _opacity(value: StyleValue, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number between 0 and 1") from exc
    return _validate.opacity(number, label)


def _dasharray(value: StyleValue, label: str) -> list[float] | None:
    if isinstance(value, str):
        if value.strip().lower() == "none":
            return None
        tokens = [token for token in re.split(r"[\s,]+", value.strip()) if token]
    elif isinstance(value, (int, float)):
        tokens = [value]
    else:  # pragma: no cover - normalize_css_style rejects this first
        tokens = []
    lengths = [_px(token, f"{label}[{i}]", positive=True) for i, token in enumerate(tokens)]
    if not 2 <= len(lengths) <= 8:
        raise ValueError(f"{label} must contain between 2 and 8 positive CSS px lengths")
    return lengths


def _paint(value: StyleValue, label: str) -> str:
    return _validate.css_color(value, label)


def _fill(value: StyleValue, label: str) -> tuple[str, Any]:
    if isinstance(value, str) and value.strip().lower().startswith("linear-gradient("):
        _validate.mark_fill(value, label)
        return "fill", value.strip()
    return "color", _paint(value, label)


def _set(result: dict[str, Any], key: str, value: Any, source: str, seen: dict[str, str]) -> None:
    previous = seen.get(key)
    if previous is not None and result[key] != value:
        raise ValueError(f"style properties {previous!r} and {source!r} set conflicting {key!r}")
    result[key] = value
    seen[key] = source


def _supported_mark_style_properties(kind: str) -> tuple[str, ...]:
    """Return canonical CSS properties supported by a rendered mark kind."""
    if kind not in _MARK_KINDS:
        raise ValueError(f"unknown mark kind {kind!r}; expected one of {_MARK_KINDS}")
    props = {"opacity"}
    if kind in _LINE_KINDS:
        props |= {"stroke", "stroke-width", "stroke-opacity", "stroke-dasharray"}
    elif kind in _SIMPLE_STROKE_KINDS:
        props |= {"stroke", "stroke-width", "stroke-opacity"}
    elif kind in _AREA_KINDS:
        props |= {
            "fill",
            "fill-opacity",
            "stroke",
            "stroke-width",
            "stroke-opacity",
            "stroke-dasharray",
        }
        if kind == "error_band":
            props.discard("stroke-dasharray")
    elif kind in _POINT_KINDS:
        props |= {
            "fill",
            "fill-opacity",
            "stroke",
            "stroke-width",
            "stroke-opacity",
        }
    elif kind in _RECT_KINDS:
        props |= {
            "fill",
            "fill-opacity",
            "stroke",
            "stroke-width",
            "stroke-opacity",
            "border-radius",
        }
    elif kind in _FILL_KINDS:
        props |= {"fill", "fill-opacity"}
    elif kind in _MESH_KINDS:
        props |= {
            "fill",
            "fill-opacity",
            "stroke",
            "stroke-width",
            "stroke-opacity",
        }
    elif kind in _DENSITY_KINDS:
        props |= {"fill-opacity"}
    return tuple(sorted(props))


def compile_mark_style(
    kind: str, value: StyleMapping | None, label: str | None = None
) -> dict[str, Any]:
    """Compile standard CSS declarations into a mark builder's keyword args."""
    label = label or f"{kind} style"
    style = normalize_css_style(value, label)
    supported = set(_supported_mark_style_properties(kind))
    unknown = sorted(set(style) - supported)
    if unknown:
        expected = ", ".join(sorted(supported))
        raise ValueError(
            f"{label} has unsupported CSS property/properties {unknown}; "
            f"{kind} supports: {expected}"
        )

    out: dict[str, Any] = {}
    seen: dict[str, str] = {}
    for prop, raw in style.items():
        if prop == "opacity":
            _set(out, "opacity", _opacity(raw, f"{label}['opacity']"), prop, seen)
        elif prop == "fill-opacity":
            _set(
                out,
                "fill_opacity",
                _opacity(raw, f"{label}['fill-opacity']"),
                prop,
                seen,
            )
        elif prop == "stroke-opacity":
            _set(
                out,
                "stroke_opacity",
                _opacity(raw, f"{label}['stroke-opacity']"),
                prop,
                seen,
            )
        elif prop == "fill":
            target, paint = _fill(raw, f"{label}[{prop!r}]")
            if target == "fill" and kind not in _AREA_KINDS | _RECT_KINDS:
                raise ValueError(f"{label}[{prop!r}] gradients are not supported by {kind}")
            if kind in _LINE_KINDS | _SIMPLE_STROKE_KINDS:
                target = "color"
            _set(out, target, paint, prop, seen)
        elif prop == "stroke":
            target = "line_color" if kind == "area" else "color"
            if kind in _POINT_KINDS | _RECT_KINDS | _MESH_KINDS:
                target = "stroke"
            _set(out, target, _paint(raw, f"{label}['stroke']"), prop, seen)
        elif prop == "stroke-width":
            target = "line_width" if kind in _AREA_KINDS else "width"
            if kind in _POINT_KINDS | _RECT_KINDS | _MESH_KINDS:
                target = "stroke_width"
            _set(out, target, _px(raw, f"{label}['stroke-width']"), prop, seen)
        elif prop == "stroke-dasharray":
            _set(out, "dash", _dasharray(raw, f"{label}['stroke-dasharray']"), prop, seen)
        elif prop == "border-radius":
            _set(out, "corner_radius", _px(raw, f"{label}['border-radius']"), prop, seen)
    return out


def compile_axis_style(
    value: StyleMapping | None, label: str = "axis style"
) -> dict[str, StyleValue]:
    """Validate renderer-backed axis appearance and normalize it to wire keys.

    Axis chrome is partly canvas-painted and partly DOM, so it has a strict
    cross-renderer vocabulary just like marks. Pixel lengths accept numbers or
    CSS ``px`` strings and are serialized as finite numbers for every renderer.
    The more explicit ``tick_label_*`` keys are retained for the pyplot adapter
    and can differ from the tick-mark paint.
    """
    style = normalize_css_style(value, label)
    supported = (
        _AXIS_COLOR_PROPERTIES
        | _AXIS_LENGTH_PROPERTIES
        | _AXIS_SIZE_PROPERTIES
        | _AXIS_COMPAT_PROPERTIES
        | {"tick_direction"}
    )
    out: dict[str, StyleValue] = {}
    sources: dict[str, str] = {}
    for css_prop, raw in style.items():
        prop = css_prop.replace("-", "_")
        if prop not in supported:
            expected = ", ".join(sorted(supported))
            raise ValueError(f"{label} has unsupported property {css_prop!r}; supports: {expected}")
        if prop in _AXIS_COLOR_PROPERTIES:
            parsed: StyleValue = _paint(raw, f"{label}[{css_prop!r}]")
        elif prop in _AXIS_LENGTH_PROPERTIES:
            parsed = _px(raw, f"{label}[{css_prop!r}]")
        elif prop in _AXIS_SIZE_PROPERTIES:
            parsed = _px(raw, f"{label}[{css_prop!r}]", positive=True)
        elif prop == "grid_opacity":
            parsed = _opacity(raw, f"{label}[{css_prop!r}]")
        elif prop == "grid_dash":
            if not isinstance(raw, str) or raw not in _AXIS_DASH_STYLES:
                raise ValueError(
                    f"{label}[{css_prop!r}] must be one of {sorted(_AXIS_DASH_STYLES)}"
                )
            parsed = raw
        else:
            if not isinstance(raw, str) or raw not in _AXIS_DIRECTIONS:
                raise ValueError(f"{label}[{css_prop!r}] must be one of {sorted(_AXIS_DIRECTIONS)}")
            parsed = raw
        _set(out, prop, parsed, css_prop, sources)
    return out


def _opacity_channels(compiled: Mapping[str, Any]) -> dict[str, float]:
    """Return renderer-only fill/stroke alpha channels from compiled CSS."""
    return {
        key: float(compiled[key]) for key in ("fill_opacity", "stroke_opacity") if key in compiled
    }


__all__ = [
    "StyleMapping",
    "StyleValue",
    "compile_axis_style",
    "compile_mark_style",
    "normalize_css_style",
]
