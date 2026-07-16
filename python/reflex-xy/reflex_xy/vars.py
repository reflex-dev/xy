"""`@reflex_xy.figure`: a computed var that *is* the chart registration.

The pattern (docs/design/reflex-integration.md): the state method builds the
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

The builder must be a pure function of its state instance (same discipline
as any cached computed var) — that purity is exactly what makes the figure
a rebuildable cache instead of precious process state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional, overload

from reflex_base.vars.base import ComputedVar

from .registry import _figure_of, registry
from .tokens import BUILDER_ATTR, build_state_token

__all__ = ["FigureVar", "figure"]


class FigureVar(ComputedVar):
    """ComputedVar whose value is a figure token and whose dependencies are
    the *builder's* — reflex tracks what the chart reads, not what the
    token-minting wrapper reads."""

    def _deps(self, objclass: Any, obj: Any = None) -> dict[str, set[str]]:
        if obj is None:
            builder = getattr(self._fget, BUILDER_ATTR, None)
            if builder is not None:
                obj = builder
        return super()._deps(objclass, obj=obj)


def _make_fget(builder: Callable[[Any], Any]) -> Callable[[Any], str]:
    builder_name = _fn_name(builder)

    def fget(self: Any) -> str:
        client_token = self.router.session.client_token
        if not client_token:
            # Pre-hydration evaluation (e.g. initial state snapshot at
            # compile time): no session yet, so no figure to serve. The
            # component treats "" as "not ready" and waits for the
            # hydrated value.
            return ""
        token = build_state_token(client_token, type(self).get_full_name(), builder_name)
        chart = builder(self)
        if chart is None:
            registry.release(token)
            return ""
        registry.publish(token, _figure_of(chart))
        return token

    fget.__name__ = builder_name
    fget.__qualname__ = getattr(builder, "__qualname__", builder_name)
    fget.__module__ = getattr(builder, "__module__", fget.__module__)
    fget.__doc__ = builder.__doc__
    setattr(fget, BUILDER_ATTR, builder)
    return fget


def _fn_name(fn: Callable[..., Any]) -> str:
    name = getattr(fn, "__name__", "")
    if not name:
        msg = f"@reflex_xy.figure builders must be named functions, got {fn!r}"
        raise TypeError(msg)
    return name


@overload
def figure(builder: Callable[[Any], Any]) -> FigureVar: ...


@overload
def figure(
    builder: None = None, **var_kwargs: Any
) -> Callable[[Callable[[Any], Any]], FigureVar]: ...


def figure(
    builder: Optional[Callable[[Any], Any]] = None, **var_kwargs: Any
) -> "FigureVar | Callable[[Callable[[Any], Any]], FigureVar]":
    """Declare a chart on a Reflex state class.

    Usage::

        class Dash(rx.State):
            n: int = 100_000

            @reflex_xy.figure
            def chart(self) -> xy.Chart:
                x, y = self._points(self.n)
                return xy.scatter_chart(xy.scatter(x, y))

        # in the page:  reflex_xy.chart(Dash.chart, height="480px")

    The method must return a public ``xy`` chart (or an internal
    Figure), or ``None`` for "no chart right now". Keyword arguments pass
    through to reflex's ``ComputedVar`` (``deps=``, ``auto_deps=``,
    ``interval=``, ...); dependencies are auto-tracked from the builder's
    body by default, exactly like a normal ``@rx.var``.
    """

    def _decorate(fn: Callable[[Any], Any]) -> FigureVar:
        if _fn_name(fn).startswith("_"):
            # Backend (underscore) vars never reach the client, but the
            # token must — refuse early with a clear message instead of
            # compiling a chart nobody can subscribe to.
            msg = (
                "@reflex_xy.figure vars must not start with '_' (the token must sync to the client)"
            )
            raise ValueError(msg)
        var_kwargs.setdefault("cache", True)
        return FigureVar(fget=_make_fget(fn), return_type=str, **var_kwargs)

    if builder is None:
        return _decorate
    return _decorate(builder)
