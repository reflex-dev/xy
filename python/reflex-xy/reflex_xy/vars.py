"""`@reflex_xy.figure`: a computed var that *is* the chart registration.

The pattern (spec/design/reflex-integration.md): the state method builds the
chart from state, the computed var's value is only the figure *token*, and
evaluating the var is what (re)registers the figure in the per-process
registry. Reflex's own dependency tracking decides when that happens:

- first render: var evaluates -> figure built -> token into state.
- a dependency changes: reflex marks the var dirty, the next delta
  evaluation rebuilds the figure and re-publishes it; subscribers get the
  fresh payload pushed over the data plane. The token itself is stable, so
  the *frontend* sees no prop change at all — data moves, DOM doesn't.
- reconnect on another worker: the cached token comes back with the state,
  the component resubscribes, the registry misses, and the namespace
  rebuilds from state via the builder this module attached to the var.

Sync and async builders are both supported, mirroring reflex's own
`ComputedVar`/`AsyncComputedVar` split (and using the same
`iscoroutinefunction` dispatch `rx.var` uses): an ``async def`` builder may
await a database, an HTTP endpoint, or a dataframe store, and evaluates
under reflex's normal async-var machinery — cached the same way, marked
dirty the same way.

Builders must be pure functions of their state instance (same discipline as
any cached computed var) — that purity is exactly what makes the figure a
rebuildable cache instead of precious process state. For async builders the
bar is "deterministic given state": fetching the rows your state points at
is fine; the rebuild path (state_bridge.py) will await the same fetch when
a fresh worker needs the figure back.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Optional, overload

from reflex_base.vars.base import AsyncComputedVar, ComputedVar

from .registry import _figure_of, registry
from .tokens import BUILDER_ATTR, build_state_token

__all__ = ["AsyncFigureVar", "FigureVar", "figure"]


def _builder_target(var: Any, obj: Any) -> Any:
    """Point dependency tracking at the *builder*, not the token wrapper:
    reflex should track what the chart reads, and the wrapper fget reads
    nothing but the router."""
    if obj is not None:
        return obj
    return getattr(var._fget, BUILDER_ATTR, None)


class FigureVar(ComputedVar):
    """ComputedVar whose value is a figure token (sync builder)."""

    def _deps(self, objclass: Any, obj: Any = None) -> dict[str, set[str]]:
        return ComputedVar._deps(self, objclass, obj=_builder_target(self, obj))


class AsyncFigureVar(AsyncComputedVar):
    """AsyncComputedVar whose value is a figure token (async builder)."""

    def _deps(self, objclass: Any, obj: Any = None) -> dict[str, set[str]]:
        return AsyncComputedVar._deps(self, objclass, obj=_builder_target(self, obj))


def _mint_token(state: Any, builder_name: str) -> Optional[str]:
    """Deterministic token for this (session, state, var) — or None
    pre-hydration (no session yet, so no figure to serve; the component
    treats "" as "not ready" and waits for the hydrated value)."""
    client_token = state.router.session.client_token
    if not client_token:
        return None
    return build_state_token(client_token, type(state).get_full_name(), builder_name)


def _publish(token: str, chart: Any) -> str:
    if chart is None:
        registry.release(token)
        return ""
    registry.publish(token, _figure_of(chart))
    return token


def _adopt_identity(fget: Any, builder: Callable[..., Any], name: str) -> None:
    fget.__name__ = name
    fget.__qualname__ = getattr(builder, "__qualname__", name)
    fget.__module__ = getattr(builder, "__module__", fget.__module__)
    fget.__doc__ = builder.__doc__
    setattr(fget, BUILDER_ATTR, builder)


def _make_fget(builder: Callable[[Any], Any]) -> Callable[[Any], str]:
    builder_name = _fn_name(builder)

    def fget(self: Any) -> str:
        token = _mint_token(self, builder_name)
        if token is None:
            return ""
        return _publish(token, builder(self))

    _adopt_identity(fget, builder, builder_name)
    return fget


def _make_async_fget(builder: Callable[[Any], Any]) -> Callable[[Any], Any]:
    builder_name = _fn_name(builder)

    async def fget(self: Any) -> str:
        token = _mint_token(self, builder_name)
        if token is None:
            return ""
        return _publish(token, await builder(self))

    _adopt_identity(fget, builder, builder_name)
    return fget


def _fn_name(fn: Callable[..., Any]) -> str:
    name = getattr(fn, "__name__", "")
    if not name:
        msg = f"@reflex_xy.figure builders must be named functions, got {fn!r}"
        raise TypeError(msg)
    return name


@overload
def figure(builder: Callable[[Any], Any]) -> "FigureVar | AsyncFigureVar": ...


@overload
def figure(
    builder: None = None, **var_kwargs: Any
) -> Callable[[Callable[[Any], Any]], "FigureVar | AsyncFigureVar"]: ...


def figure(
    builder: Optional[Callable[[Any], Any]] = None, **var_kwargs: Any
) -> "FigureVar | AsyncFigureVar | Callable[[Callable[[Any], Any]], FigureVar | AsyncFigureVar]":
    """Declare a chart on a Reflex state class.

    Usage::

        class Dash(rx.State):
            n: int = 100_000

            @reflex_xy.figure
            def chart(self) -> xy.Chart:
                x, y = self._points(self.n)
                return xy.scatter_chart(xy.scatter(x, y))

            @reflex_xy.figure
            async def remote(self) -> xy.Chart:
                rows = await fetch_rows(self.query)     # db / http / store
                return xy.line_chart(xy.line(rows.t, rows.value))

        # in the page:  reflex_xy.chart(Dash.chart, height="480px")

    The method must return a public ``xy`` chart (or an internal
    Figure), or ``None`` for "no chart right now". ``async def`` builders
    become reflex ``AsyncComputedVar``s (same dispatch rule as ``rx.var``).
    Keyword arguments pass through to reflex's computed var (``deps=``,
    ``auto_deps=``, ``interval=``, ...); dependencies are auto-tracked from
    the builder's body by default, exactly like a normal ``@rx.var``.
    """

    def _decorate(fn: Callable[[Any], Any]) -> "FigureVar | AsyncFigureVar":
        if _fn_name(fn).startswith("_"):
            # Backend (underscore) vars never reach the client, but the
            # token must — refuse early with a clear message instead of
            # compiling a chart nobody can subscribe to.
            msg = (
                "@reflex_xy.figure vars must not start with '_' (the token must sync to the client)"
            )
            raise ValueError(msg)
        var_kwargs.setdefault("cache", True)
        if inspect.iscoroutinefunction(fn):
            return AsyncFigureVar(fget=_make_async_fget(fn), return_type=str, **var_kwargs)
        return FigureVar(fget=_make_fget(fn), return_type=str, **var_kwargs)

    if builder is None:
        return _decorate
    return _decorate(builder)
