"""Rebuild figures from Reflex state: the distributed-deployment answer.

The figure registry is process-local. What makes that safe in a
multi-worker / reconnecting world is this module: given a state token
(`xyv1|client|state|var`) and the app's state manager, we can always
recover the figure by re-running the builder against the session's state —
which Reflex already stores durably (memory/disk/redis) and already knows
how to hand to any worker. No figure server, no data in Redis beyond the
state that was there anyway (§27 applied to processes: the figure is a
rebuildable cache, Reflex state is canonical).

Read-only by design: rebuilds use `state_manager.get_state` (no state lock,
no delta emission). Builders must therefore be pure functions of state —
the same contract cached computed vars already impose.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, Optional

from .registry import _figure_of
from .tokens import ParsedToken, builder_of, parse_token

if TYPE_CHECKING:
    from xy._figure import Figure

__all__ = ["make_rebuild_hook", "rebuild_figure"]


def _resolve_state_cls(state_full_name: str) -> Any:
    """State full name (as stored in the token) -> state class.

    Mirrors reflex's own legacy-token resolution
    (`BaseStateToken.from_legacy_token`): the full name is split on dots and
    resolved from the root state class.
    """
    import reflex as rx

    return rx.State.get_class_substate(tuple(state_full_name.split(".")))


async def rebuild_figure(app: Any, parsed: ParsedToken) -> Optional["Figure"]:
    """Re-run a figure var's builder against the session's stored state."""
    import reflex as rx

    try:
        state_cls = _resolve_state_cls(parsed.state_full_name)
    except (KeyError, ValueError):
        return None
    builder = builder_of(state_cls, parsed.var_name)
    if builder is None:
        return None
    token = rx.BaseStateToken(ident=parsed.client_token, cls=rx.State)
    root = await app.state_manager.get_state(token)
    substate = await root.get_state(state_cls)
    # Async builders (AsyncFigureVar) await their data source here exactly
    # as they would during normal var evaluation.
    if inspect.iscoroutinefunction(builder):
        chart = await builder(substate)
    else:
        chart = builder(substate)
    if chart is None:
        return None
    return _figure_of(chart)


def make_rebuild_hook(app: Any) -> Any:
    """The namespace's RebuildHook, bound to one app instance."""

    async def _rebuild(token_str: str) -> Optional["Figure"]:
        parsed = parse_token(token_str)
        if parsed is None:
            return None
        return await rebuild_figure(app, parsed)

    return _rebuild
