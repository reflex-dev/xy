"""Shared public-argument validators.

Before this module the same "reject bool → coerce → assert finite", "positive
int", and "finite-increasing pair" primitives were hand-reimplemented across
`figure`, `components`, `channels`, `_native`, `lod`, `interaction`, and
`export` — several under identical names with identical error strings. They now
live here once; the other modules alias these (so `Figure._finite_scalar`,
`components._axis_id`, etc. keep working with zero call-site churn) and the
error messages are unchanged, which the builder/mutation-safety tests assert.

Every function takes `(value, label)` and either returns the validated value or
raises `ValueError` (occasionally `TypeError`) naming `label`.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

_TICK_LABEL_STRATEGIES = frozenset({"auto", "hide", "rotate", "stagger", "none"})
_LABEL_POSITIONS = frozenset(
    {"start", "center", "end", "inside_start", "inside_center", "inside_end"}
)


def finite_scalar(value: Any, label: str) -> float:
    """A finite real number (rejects bool and non-finite)."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite real number")
    try:
        out = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be a finite real number") from e
    if not np.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def finite_increasing_pair(values: Any, label: str) -> tuple[float, float]:
    """Exactly two finite values with `hi > lo`."""
    try:
        lo_raw, hi_raw = values
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must contain exactly two finite values") from e
    lo = finite_scalar(lo_raw, f"{label}[0]")
    hi = finite_scalar(hi_raw, f"{label}[1]")
    if hi <= lo:
        raise ValueError(f"{label} must be finite and increasing")
    return lo, hi


def positive_scalar(value: Any, label: str) -> float:
    out = finite_scalar(value, label)
    if out <= 0:
        raise ValueError(f"{label} must be positive")
    return out


def nonnegative_scalar(value: Any, label: str) -> float:
    out = finite_scalar(value, label)
    if out < 0:
        raise ValueError(f"{label} must be non-negative")
    return out


def optional_finite_scalar(value: Any, label: str) -> Optional[float]:
    if value is None:
        return None
    return finite_scalar(value, label)


def optional_nonnegative_scalar(value: Any, label: str) -> Optional[float]:
    if value is None:
        return None
    return nonnegative_scalar(value, label)


def optional_positive_int(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{label} must be a positive integer")
    out = int(value)
    if out <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return out


def opacity(value: Any, label: str) -> float:
    out = finite_scalar(value, label)
    if out < 0 or out > 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return out


def optional_bool(value: Any, label: str) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise ValueError(f"{label} must be True, False, or None")


def bool_param(value: Any, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise ValueError(f"{label} must be True or False")


def optional_text(value: Any, label: str) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{label} must be a string or None")


def axis_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if value[0] not in {"x", "y"}:
        raise ValueError(f"{label} must start with 'x' or 'y'")
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in value):
        raise ValueError(f"{label} may only contain letters, digits, '_' and '-'")
    return value


def axis_tick_label_strategy(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or None")
    normalized = value.replace("-", "_")
    if normalized not in _TICK_LABEL_STRATEGIES:
        raise ValueError(f"{label} must be one of {sorted(_TICK_LABEL_STRATEGIES)}")
    return normalized


def string_mapping(value: dict[str, Any], label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dict[str, str]")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"{label} must be a dict[str, str]")
        out[key] = item
    return out


def style_mapping(value: dict[str, Any], label: str) -> dict[str, str | int | float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dict[str, str | int | float]")
    out: dict[str, str | int | float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(
            item, (str, int, float, np.integer, np.floating)
        ):
            raise ValueError(f"{label} must be a dict[str, str | int | float]")
        if isinstance(item, (bool, np.bool_)):
            raise ValueError(f"{label} must be a dict[str, str | int | float]")
        number = float(item) if isinstance(item, (int, float, np.integer, np.floating)) else None
        if number is not None and not np.isfinite(number):
            raise ValueError(f"{label} numeric values must be finite")
        out[key] = item.item() if isinstance(item, (np.integer, np.floating)) else item
    return out


def axis_label_position(value: Any, label: str) -> Optional[str | dict[str, str | int | float]]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.replace("-", "_")
        if normalized not in _LABEL_POSITIONS:
            raise ValueError(
                f"{label} must be one of {sorted(_LABEL_POSITIONS)} or a CSS style dict"
            )
        return normalized
    return style_mapping(value, label)
