"""Wiring the data plane into a Reflex app.

Two equivalent entry points, both one line for the user:

- ``rxconfig.py``: ``plugins=[reflex_xy.XYPlugin()]`` — the plugin's
  `post_compile` hook runs once at backend worker startup with the live
  App and calls `setup(app)`. Zero app-code changes.
- ``app.py``: ``reflex_xy.setup(app)`` right after ``app = rx.App()`` —
  the socket server already exists at that point.

`setup` is idempotent; using both costs nothing.

What setup does: registers the `/_xy` socket.io namespace on the app's
existing AsyncServer (same physical websocket as the app plane — see
namespace.py), wires publish fan-out, and adds a lifespan task that
captures the event loop (for thread-safe broadcasts from sync handlers)
and runs the registry TTL sweep.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Optional

from reflex.plugins import Plugin

from .namespace import XYNamespace
from .registry import registry
from .state_bridge import make_rebuild_hook

__all__ = ["XYPlugin", "append", "setup"]

_namespace: Optional[XYNamespace] = None


def setup(app: Any) -> XYNamespace:
    """Attach the xy data plane to a Reflex app (idempotent)."""
    global _namespace
    if _namespace is not None:
        return _namespace
    sio = getattr(app, "sio", None)
    if sio is None:
        msg = (
            "reflex_xy.setup(app) needs the app's socket server; it exists "
            "only when state is enabled (rx.App(enable_state=True), the default)."
        )
        raise RuntimeError(msg)
    namespace = XYNamespace(registry, rebuild=make_rebuild_hook(app))
    sio.register_namespace(namespace)
    wire(namespace)
    app.register_lifespan_task(_xy_lifespan)
    _namespace = namespace
    return namespace


def wire(namespace: XYNamespace) -> None:
    """Point the registry's fan-out seams at a namespace (setup and tests)."""
    registry.on_publish(namespace.broadcast_payload)
    registry.on_push(namespace.broadcast_message)


async def _xy_lifespan() -> None:
    """Capture the serving loop, then sweep idle figures forever."""
    registry.attach_loop(asyncio.get_running_loop())
    with contextlib.suppress(asyncio.CancelledError):  # normal shutdown
        await registry.sweep_forever()


class XYPlugin(Plugin):
    """Reflex plugin: `plugins=[reflex_xy.XYPlugin()]` in rxconfig.py.

    `post_compile` is the one plugin hook that receives the live App, and it
    fires at backend worker startup — after the socket server exists, before
    any client connects, and never during frontend-only compiles.
    """

    def post_compile(self, **context: Any) -> None:
        app = context.get("app")
        if app is not None:
            setup(app)


def append(
    token: str,
    x: Any,
    y: Any,
    *,
    color: Any = None,
    size: Any = None,
    trace: int = 0,
) -> None:
    """Stream-append points to a registered figure and push to subscribers.

    Thin alias for `registry.append` — see its docstring for the threading
    contract.
    """
    registry.append(token, x, y, color=color, size=size, trace=trace)


def reset_setup_for_tests() -> None:
    """Forget the wired namespace (test isolation only)."""
    global _namespace
    _namespace = None
