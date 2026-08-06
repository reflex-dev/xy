"""Typed handles: the values chart-related state vars carry.

The integration keeps figures and columns in the per-process registry;
Reflex state only ever holds a small *handle* wrapping the registry token
(spec/design/reflex-integration.md §5). Wrapping the token in a frozen
dataclass instead of a bare ``str`` is what gives the component seam a
compile-time type: ``XYChart.figure`` / ``XYChart.data`` are ``Var[T]``
props, so passing the wrong var (``Dash.points``) or a raw string fails at
``create()`` — page evaluation — with the framework's own ``TypeError``
(design facts R1/R7, pinned in tests/reflex_adapter/test_framework_contracts.py).

``DataHandle`` is generic over the data method's return annotation:
``DataHandle[CloudData]`` survives as the class-level Var's ``_var_type``,
which is the schema channel the flat factories read column names from —
without executing any user code.

The empty token is the "not ready / no chart" sentinel (pre-hydration, or a
builder returning ``None``), so the var types stay non-optional.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

import reflex as rx

__all__ = ["DataHandle", "FigureHandle"]

S = TypeVar("S")


@dataclass(frozen=True)
class FigureHandle:
    """Reference to a registered figure; ``token`` is the registry key."""

    token: str = ""

    def __bool__(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True)
class DataHandle(Generic[S]):
    """Reference to a registered column set; ``token`` is the registry key.

    The type parameter carries the data method's declared schema (a
    ``TypedDict``) purely at the annotation level.
    """

    token: str = ""

    def __bool__(self) -> bool:
        return bool(self.token)


# Serializers keep the state-delta path a plain dict (and make reflex's
# guess_type treat handle-valued vars as object vars).


@rx.serializer
def serialize_figure_handle(handle: FigureHandle) -> dict:
    return {"token": handle.token}


@rx.serializer
def serialize_data_handle(handle: DataHandle) -> dict:
    return {"token": handle.token}


def token_of(source: object) -> str | None:
    """The token string of a *figure* source; None otherwise.

    The one-cycle compatibility seam: public helpers that take "a figure"
    (``append``, ``set_view``, ``release``, ...) accept both a handle and the
    old-style bare token string through this normalizer. A ``DataHandle``
    names a column set, never a figure — figure-only operations must reject
    it immediately (None here) instead of addressing a room that can never
    exist.
    """
    if isinstance(source, FigureHandle):
        return source.token
    if isinstance(source, str):
        return source
    return None
