"""`@reflex_xy.data`: a computed var that *is* the dataset registration.

The data-plane sibling of `@reflex_xy.figure` (vars.py) for the data-bound
component tier: the state method returns **columns only** — a mapping of
column name to array-likes — so there is no chart API inside it to get
wrong. Evaluating the var publishes the columns into the per-process
registry under a deterministic token (`xyd1|<client>|<state>|<var>`) and
its value is a tiny typed :class:`~reflex_xy.handles.DataHandle`. Reflex's
dependency tracking watches the method body; a state change republishes the
columns, and the registry rebuilds + broadcasts every mounted chart plan
bound to them.

The method's return annotation is the compile-time schema channel (fact
R7): annotate a ``TypedDict`` and the class-level var carries
``DataHandle[Schema]``, which the chart factories read column names from —
without executing any user code. A plain ``dict[str, ...]`` annotation
degrades gracefully to first-execution validation.

Like figure builders, data methods must be pure functions of their state
instance: the token is the rebuild recipe (state_bridge.py re-runs the
method when a fresh worker needs the columns back), and purity is what
makes the column set a rebuildable cache instead of precious process state.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, Optional, get_type_hints, is_typeddict, overload

from reflex_base.vars.base import AsyncComputedVar, ComputedVar

from .handles import DataHandle
from .registry import registry
from .tokens import BUILDER_ATTR, build_data_token
from .vars import _builder_target

__all__ = ["AsyncDataVar", "DataVar", "data", "validate_columns"]


class DataVar(ComputedVar):
    """ComputedVar whose value is a DataHandle (sync data method)."""

    def _deps(self, objclass: Any, obj: Any = None) -> dict[str, set[str]]:
        return ComputedVar._deps(self, objclass, obj=_builder_target(self, obj))


class AsyncDataVar(AsyncComputedVar):
    """AsyncComputedVar whose value is a DataHandle (async data method)."""

    def _deps(self, objclass: Any, obj: Any = None) -> dict[str, set[str]]:
        return AsyncComputedVar._deps(self, objclass, obj=_builder_target(self, obj))


def validate_columns(columns: Any, *, source: str) -> dict[str, Any]:
    """The only check that needs real data: a mapping of named array-like
    columns. Columns may differ in length and dimensionality — one var can
    carry a scatter's rows next to a stairs mark's ``len+1`` edges or a
    heatmap's 2-D grid. Coupled-length and shape contracts (x vs y, edges
    vs values, z's 2-D-ness) belong to the mark validators when a plan
    binds, where the errors name the mark and channels involved."""
    if not isinstance(columns, Mapping):
        raise TypeError(
            f"{source} must return a mapping of column name -> values "
            f"(e.g. a TypedDict of arrays), got {type(columns).__name__}"
        )
    validated: dict[str, Any] = {}
    for key, values in columns.items():
        if not isinstance(key, str):
            raise TypeError(f"{source} column names must be strings, got {key!r}")
        if isinstance(values, (str, bytes, Mapping)):
            raise TypeError(
                f"{source} column {key!r} must be an array-like of values, "
                f"got {type(values).__name__}"
            )
        try:
            len(values)
        except TypeError as exc:
            raise TypeError(
                f"{source} column {key!r} must be an array-like with a length, "
                f"got {type(values).__name__}"
            ) from exc
        validated[key] = values
    return validated


def _mint_token(state: Any, var_name: str) -> Optional[str]:
    client_token = state.router.session.client_token
    if not client_token:
        return None
    return build_data_token(client_token, type(state).get_full_name(), var_name)


def _publish(token: str, columns: Any, *, source: str) -> DataHandle:
    if columns is None:
        registry.release_columns(token)
        return DataHandle("")
    registry.publish_columns(token, validate_columns(columns, source=source))
    return DataHandle(token)


def _source_label(method: Callable[..., Any]) -> str:
    qualname = getattr(method, "__qualname__", None) or getattr(method, "__name__", "data method")
    return qualname.rsplit(".<locals>.", 1)[-1]


def _adopt_identity(fget: Any, method: Callable[..., Any], name: str) -> None:
    fget.__name__ = name
    fget.__qualname__ = getattr(method, "__qualname__", name)
    fget.__module__ = getattr(method, "__module__", fget.__module__)
    fget.__doc__ = method.__doc__
    setattr(fget, BUILDER_ATTR, method)


def _make_fget(method: Callable[[Any], Any]) -> Callable[[Any], DataHandle]:
    name = _fn_name(method)
    source = _source_label(method)

    def fget(self: Any) -> DataHandle:
        token = _mint_token(self, name)
        if token is None:
            return DataHandle("")
        return _publish(token, method(self), source=source)

    _adopt_identity(fget, method, name)
    return fget


def _make_async_fget(method: Callable[[Any], Any]) -> Callable[[Any], Any]:
    name = _fn_name(method)
    source = _source_label(method)

    async def fget(self: Any) -> DataHandle:
        token = _mint_token(self, name)
        if token is None:
            return DataHandle("")
        return _publish(token, await method(self), source=source)

    _adopt_identity(fget, method, name)
    return fget


def _fn_name(fn: Callable[..., Any]) -> str:
    name = getattr(fn, "__name__", "")
    if not name:
        msg = f"@reflex_xy.data methods must be named functions, got {fn!r}"
        raise TypeError(msg)
    return name


def _return_type(method: Callable[..., Any]) -> Any:
    """``DataHandle[Schema]`` when the return annotation is a TypedDict —
    the schema survives as the class-level var's ``_var_type`` (R7) and is
    how the factories compile-check column names. Anything else (plain
    dicts, missing or unresolvable annotations) degrades to ``DataHandle``:
    columns are then validated on first execution instead."""
    try:
        hints = get_type_hints(method)
    except Exception:  # noqa: BLE001 - annotations may reference unimportable names
        return DataHandle
    annotation = hints.get("return")
    if annotation is not None and is_typeddict(annotation):
        return DataHandle[annotation]
    return DataHandle


@overload
def data(method: Callable[[Any], Any]) -> "DataVar | AsyncDataVar": ...


@overload
def data(
    method: None = None, **var_kwargs: Any
) -> Callable[[Callable[[Any], Any]], "DataVar | AsyncDataVar"]: ...


def data(
    method: Optional[Callable[[Any], Any]] = None, **var_kwargs: Any
) -> "DataVar | AsyncDataVar | Callable[[Callable[[Any], Any]], DataVar | AsyncDataVar]":
    """Declare a chart dataset on a Reflex state class.

    Usage::

        class CloudData(TypedDict):
            x: np.ndarray
            y: np.ndarray
            mag: np.ndarray

        class Dash(rx.State):
            points: int = 200_000

            @reflex_xy.data
            def cloud(self) -> CloudData:
                rng = np.random.default_rng(7)
                x = rng.normal(size=self.points)
                return {"x": x, "y": x * 0.6, "mag": np.abs(x)}

        # in the page:
        #   reflex_xy.scatter_chart(data=Dash.cloud, x="x", y="y", color="mag")

    The method must return a mapping of column name -> array-likes — mixed
    lengths and dimensionalities are fine (a scatter's rows can sit next to
    a stairs mark's ``len+1`` edges or a heatmap's 2-D grid; coupled-shape
    contracts belong to the mark validators when a plan binds) — or
    ``None`` for "no data right now" (which releases the registered columns
    and yields the empty handle). ``async def`` methods
    become ``AsyncDataVar``s (same dispatch rule as ``rx.var``); keyword
    arguments pass through to reflex's computed var (``deps=``,
    ``interval=``, ...).
    """

    def _decorate(fn: Callable[[Any], Any]) -> "DataVar | AsyncDataVar":
        if _fn_name(fn).startswith("_"):
            # Same rule as figure vars: the handle must sync to the client,
            # and backend (underscore) vars never do.
            msg = (
                "@reflex_xy.data vars must not start with '_' (the handle must sync to the client)"
            )
            raise ValueError(msg)
        var_kwargs.setdefault("cache", True)
        return_type = _return_type(fn)
        if inspect.iscoroutinefunction(fn):
            return AsyncDataVar(fget=_make_async_fget(fn), return_type=return_type, **var_kwargs)
        return DataVar(fget=_make_fget(fn), return_type=return_type, **var_kwargs)

    if method is None:
        return _decorate
    return _decorate(method)
