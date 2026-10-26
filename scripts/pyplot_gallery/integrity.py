"""Fail-closed validation for gallery capture provenance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

XY_BACKEND = "module://xy.backends.backend_xy"
XY_CANVAS_TYPE = "xy.backends.backend_xy.FigureCanvasXY"


def capture_background(capture: Mapping[str, Any]) -> tuple[int, int, int] | None:
    """Return a validated declared RGB background for one capture."""

    value = capture.get("background_rgb")
    if not isinstance(value, list) or len(value) != 3:
        return None
    if any(isinstance(channel, bool) or not isinstance(channel, int) for channel in value):
        return None
    if any(not 0 <= channel <= 255 for channel in value):
        return None
    return value[0], value[1], value[2]


def capture_integrity_errors(engine: str, result: Mapping[str, Any]) -> list[str]:
    """Return capture-provenance failures for one gallery engine result."""

    errors: list[str] = []
    capture_errors = result.get("capture_errors")
    if not isinstance(capture_errors, list):
        errors.append("capture_errors metadata is missing or invalid")
    elif capture_errors:
        errors.append("has capture errors")

    captures = result.get("captures")
    if not isinstance(captures, list) or not captures:
        errors.append("produced no captures")
        return errors

    if engine == "xy" and result.get("fallback_used") is not False:
        errors.append("fallback state is not explicitly false")

    for index, capture in enumerate(captures):
        prefix = f"capture {index}"
        if not isinstance(capture, Mapping):
            errors.append(f"{prefix} metadata is invalid")
            continue
        backend = capture.get("backend")
        if not isinstance(backend, str) or not backend:
            errors.append(f"{prefix} backend identity is missing")
        elif engine == "xy" and backend.lower() != XY_BACKEND:
            errors.append(f"{prefix} did not use the XY backend: {backend}")
        canvas_type = capture.get("canvas_type")
        if not isinstance(canvas_type, str) or not canvas_type:
            errors.append(f"{prefix} canvas identity is missing")
        elif engine == "xy" and canvas_type != XY_CANVAS_TYPE:
            errors.append(f"{prefix} did not use FigureCanvasXY: {canvas_type}")
        if "fallback_used" not in capture:
            errors.append(f"{prefix} fallback metadata is missing")
        elif engine == "xy" and capture["fallback_used"] is not False:
            errors.append(f"{prefix} fallback state is not explicitly false")
        facecolor = capture.get("figure_facecolor_rgba")
        if (
            not isinstance(facecolor, list)
            or len(facecolor) != 4
            or any(
                isinstance(channel, bool) or not isinstance(channel, (int, float))
                for channel in facecolor
            )
        ):
            errors.append(f"{prefix} declared figure facecolor is missing or invalid")
        if capture_background(capture) is None:
            errors.append(f"{prefix} declared background is missing or invalid")
    return errors


def aggregate_fallback_state(captures: object) -> bool | None:
    """Aggregate capture fallback flags without converting missing data to false."""

    if not isinstance(captures, list) or not captures:
        return None
    states: list[bool] = []
    for capture in captures:
        if not isinstance(capture, Mapping):
            return None
        state = capture.get("fallback_used")
        if state is not True and state is not False:
            return None
        states.append(state)
    return any(states)


__all__ = [
    "XY_BACKEND",
    "XY_CANVAS_TYPE",
    "aggregate_fallback_state",
    "capture_background",
    "capture_integrity_errors",
]
