"""Rebuild figures and datasets from Reflex state: the distributed answer.

The figure registry is process-local. What makes that safe in a
multi-worker / reconnecting world is this module: given a state token, we
can always recover the served object by re-running the decorated state
method against the session's state — which Reflex already stores durably
(memory/disk/redis) and already knows how to hand to any worker. No figure
server, no data in Redis beyond the state that was there anyway (§27
applied to processes: the served object is a rebuildable cache, Reflex
state is canonical).

Three recipes, one contract:

- `xyv1|client|state|var` — re-run the `@reflex_xy.figure` builder → Figure.
- `xyd1|client|state|var` — re-run the `@reflex_xy.data` method → columns.
- `xyp1|digest|xyd1|…` — plan lookup (process-local; every worker's map
  is populated at startup, see app.py `_ensure_page_plans`) + column
  resolve (registry hit, else the xyd1 recipe) + bind → Figure.

Read-only by design: rebuilds use `state_manager.get_state` (no state lock,
no delta emission). Builders and data methods must therefore be pure
functions of state — the same contract cached computed vars already impose.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Optional

from .data_vars import validate_columns
from .plan import require_plan
from .registry import _figure_of, registry
from .tokens import ParsedPlanToken, ParsedToken, builder_of, parse_plan_token, parse_token

if TYPE_CHECKING:
    from xy._figure import Figure

__all__ = ["make_rebuild_hook", "rebuild_data", "rebuild_figure", "rebuild_plan_figure"]


def _resolve_state_cls(state_full_name: str) -> Any:
    """State full name (as stored in the token) -> state class.

    Mirrors reflex's own legacy-token resolution
    (`BaseStateToken.from_legacy_token`): the full name is split on dots and
    resolved from the root state class.
    """
    import reflex as rx

    return rx.State.get_class_substate(tuple(state_full_name.split(".")))


async def _run_state_method(app: Any, parsed: ParsedToken) -> Any:
    """Re-run a decorated state method against the session's stored state."""
    import reflex as rx

    try:
        state_cls = _resolve_state_cls(parsed.state_full_name)
    except (KeyError, ValueError):
        return None
    method = builder_of(state_cls, parsed.var_name)
    if method is None:
        return None
    token = rx.BaseStateToken(ident=parsed.client_token, cls=rx.State)
    root = await app.state_manager.get_state(token)
    substate = await root.get_state(state_cls)
    # Async builders/data methods await their data source here exactly as
    # they would during normal var evaluation.
    if inspect.iscoroutinefunction(method):
        return await method(substate)
    return method(substate)


async def rebuild_figure(app: Any, parsed: ParsedToken) -> Optional["Figure"]:
    """Re-run a figure var's builder against the session's stored state."""
    from xy._figure import Figure

    if parsed.kind != "figure":
        return None
    chart = await _run_state_method(app, parsed)
    if chart is None:
        return None
    figure = _figure_of(chart)
    return figure if isinstance(figure, Figure) else None


async def rebuild_data(app: Any, parsed: ParsedToken) -> Optional[dict[str, Any]]:
    """Re-run a data var's method against the session's stored state."""
    if parsed.kind != "data":
        return None
    columns = await _run_state_method(app, parsed)
    if columns is None:
        return None
    return validate_columns(columns, source=f"{parsed.state_full_name}.{parsed.var_name}")


async def rebuild_plan_figure(app: Any, composite: ParsedPlanToken) -> Optional["Figure"]:
    """Recover a data-bound figure: plan (local map) + columns (registry or
    state) + bind. Raises PlanMissError / PlanBindError for spec-aware `err`
    frames; anything else fails closed in the namespace."""
    plan = require_plan(composite.digest)
    entry = registry.get_columns(composite.data_token)
    if entry is not None:
        columns = entry.columns
    else:
        columns = await rebuild_data(app, composite.data)
        if columns is None:
            return None
        # Future binds (other plans over the same data var) hit the cache;
        # bind_plan below is the subscribe path's job, not the rebuild's.
        registry.publish_columns(composite.data_token, columns)
    # Same label the registry's republish path builds in _rebuild_dependent:
    # one mismatch, one err frame, whichever path hits it first.
    source = f"{composite.data.state_full_name}.{composite.data.var_name}"
    return plan.bind(columns, source=source).figure()


def make_rebuild_hook(app: Any) -> Any:
    """The namespace's RebuildHook, bound to one app instance."""

    async def _rebuild(token_str: str) -> Optional["Figure"]:
        composite = parse_plan_token(token_str)
        if composite is not None:
            return await rebuild_plan_figure(app, composite)
        parsed = parse_token(token_str)
        if parsed is None or parsed.kind != "figure":
            # Bare data tokens never serve figures; fail closed.
            return None
        return await rebuild_figure(app, parsed)

    return _rebuild
