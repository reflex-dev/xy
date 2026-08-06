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
registers this worker's chart plans (`_ensure_page_plans`, fail-closed),
captures the event loop (for thread-safe broadcasts from sync handlers),
and runs the registry TTL sweep.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, Optional

from reflex.plugins import Plugin

from .handles import FigureHandle, token_of
from .namespace import XYNamespace
from .registry import registry
from .state_bridge import make_rebuild_hook

__all__ = [
    "XYPlugin",
    "append",
    "clear_selection",
    "reset_view",
    "select",
    "set_view",
    "setup",
]

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

    def _lifespan() -> Coroutine[Any, Any, None]:
        # Deliberately a *sync* function returning the sweep coroutine, not an
        # `async def`. Reflex starts a coroutine lifespan task with
        # `asyncio.create_task(task())` and then yields, so anything raised
        # inside an `async def` body surfaces in the background *after* the
        # worker is already serving — exactly the fail-open shape
        # `_ensure_page_plans` exists to prevent. Reflex calls `task()` inline
        # to *get* that coroutine, before create_task and before the lifespan
        # yields, so raising from this body aborts startup instead.
        _ensure_page_plans(app)
        return _xy_lifespan()

    app.register_lifespan_task(_lifespan)
    _namespace = namespace
    return namespace


def _ensure_page_plans(app: Any) -> None:
    """Evaluate the app's page component functions so chart plans register.

    The data-bound tier's plan map is process-local and populated by the
    chart factories *as page bodies run* (reflex-integration.md §3.6). A
    backend-only worker — dev backend subprocesses and prod workers alike —
    imports the app module but skips the frontend compile, so its pages sit
    unevaluated and every plan subscription would answer `err {resync}`
    forever. Running the page functions here makes "the plan map is
    populated in every worker" true by construction; the built component
    trees are discarded (plans and payload assets are content-addressed and
    idempotent).

    Failure is fail-closed: a page that cannot evaluate here leaves this
    worker with an incomplete plan map, and behind a load balancer that is
    the worst failure shape there is — charts blank or not depending on
    which worker answers, with only a startup warning to explain it. Every
    failing page is collected and the worker refuses to start, naming the
    pages; the same page code already fails `reflex run`'s real compile, so
    a healthy deployment never hits this. "Refuses to start" is load-bearing
    and depends on *where* this runs: `setup`'s lifespan calls it in the
    synchronous part of the task, before Reflex schedules the sweep
    coroutine, so the exception aborts lifespan startup rather than landing
    in a background task on an already-serving worker.
    """
    pages = getattr(app, "_unevaluated_pages", None) or {}
    failures: list[str] = []
    for route, page in dict(pages).items():
        component = getattr(page, "component", None)
        if not callable(component):
            continue  # already-built component instances registered at add_page
        try:
            component()
        except Exception as exc:  # noqa: BLE001 - user page code is an input boundary
            failures.append(f"{route!r}: {type(exc).__name__}: {exc}")
    if failures:
        msg = (
            "reflex_xy: evaluating page component functions for chart-plan "
            "registration failed on this worker; serving would leave its "
            "plan map incomplete (load-balancer-dependent blank charts), "
            "so startup is refused. Failing pages: " + "; ".join(sorted(failures))
        )
        raise RuntimeError(msg)


def wire(namespace: XYNamespace) -> None:
    """Point the registry's fan-out seams at a namespace (setup and tests)."""
    registry.on_publish(namespace.broadcast_payload)
    registry.on_push(namespace.broadcast_message)
    registry.on_error(namespace.broadcast_error)


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


def _token(source: "str | FigureHandle") -> str:
    """Normalize a public figure argument (handle or bare token string)."""
    token = token_of(source)
    if token is None:
        msg = f"expected a FigureHandle or figure token string, got {type(source).__name__}"
        raise TypeError(msg)
    return token


def append(
    token: "str | FigureHandle",
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
    registry.append(_token(token), x, y, color=color, size=size, trace=trace)


def set_view(
    token: "str | FigureHandle", ranges: Any, *, animate: bool = True, history: bool = True
) -> None:
    """Out-of-band programmatic view patch (view-state.md §5.2).

    Mirrors `append`: callable from any event handler, background task, or
    thread; one wire message pushed room-wide, applied by every client
    through the same clamped mutation path as a gesture, `source: "api"`.
    """
    registry.set_view(_token(token), ranges, animate=animate, history=history)


def reset_view(token: "str | FigureHandle", axes: Any = None) -> None:
    """Out-of-band navigation to the home ranges (room-wide)."""
    registry.reset_view(_token(token), axes)


def select(
    token: "str | FigureHandle",
    *,
    range: Any = None,
    polygon: Any = None,
    rows: Any = None,
    history: bool = True,
) -> None:
    """Out-of-band programmatic selection (room-wide). Geometric forms
    resolve client-side like a gesture; `rows=` resolves kernel-side and is
    non-durable (see view-state.md §5.1)."""
    registry.select(_token(token), range=range, polygon=polygon, rows=rows, history=history)


def clear_selection(token: "str | FigureHandle") -> None:
    """Out-of-band selection clear (room-wide)."""
    registry.clear_selection(_token(token))


def reset_setup_for_tests() -> None:
    """Forget the wired namespace (test isolation only)."""
    global _namespace
    _namespace = None
