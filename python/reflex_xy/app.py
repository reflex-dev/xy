"""Wiring the data plane into a Reflex app.

Two equivalent entry points, both one line for the user:

- ``rxconfig.py``: ``plugins=[reflex_xy.XYPlugin()]`` — the plugin's
  `post_compile` hook runs once at backend worker startup with the live
  App and calls `setup(app)`. Zero app-code changes.
- ``app.py``: ``reflex_xy.setup(app)`` right after ``app = rx.App()`` —
  the socket server already exists at that point.

`setup` is idempotent; using both costs nothing.

What setup does: registers the `/_xy` channel on the app's existing event
websocket (data_plane.py — the same physical connection as the app plane),
wires publish fan-out, and adds a lifespan task that
registers this worker's chart plans (`_ensure_page_plans`, fail-closed),
captures the event loop (for thread-safe broadcasts from sync handlers),
and runs the registry TTL sweep.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import warnings
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, Optional, cast

from reflex.plugins import Plugin

from .data_plane import XYChannel
from .handles import FigureHandle, token_of
from .registry import _figure_of, registry
from .state_bridge import app_ref, make_rebuild_hook
from .tokens import BUILDER_ATTR, PROBE_ATTR
from .vars import AsyncFigureVar, FigureVar

__all__ = [
    "FigureProbeError",
    "XYPlugin",
    "append",
    "clear_selection",
    "probe_figure_builders",
    "reset_view",
    "select",
    "set_view",
    "setup",
]

# Attached (app accessor, channel) pairs. Attachment is per *app*, not per
# process: a hot reload (and AppHarness) re-imports the app module, and the new
# App gets its own websocket that must be attached to. An App is unhashable, so
# this is an identity list rather than a dict, and `app_ref` keeps the app
# weakly so a replaced one does not outlive its reload.
_attached: "list[tuple[Callable[[], Any], XYChannel]]" = []


def _live_planes() -> list[XYChannel]:
    """Attached channels whose app is still alive (forgetting the rest)."""
    live: list[XYChannel] = []
    for pair in list(_attached):
        resolve_app, channel = pair
        if resolve_app() is None:
            _attached.remove(pair)
        else:
            live.append(channel)
    return live


def setup(app: Any) -> XYChannel:
    """Attach the xy data plane to a Reflex app (idempotent *per app*).

    The plane is a Reflex channel on the app's own event websocket. Reflex's
    `register_channel` refuses an app that cannot carry one — state disabled,
    or a non-WebSocket transport — so a misconfiguration fails here at startup
    rather than as a blank chart in the browser.

    Idempotency is keyed on the app itself, which matters once more than one
    App exists in a process: keying on "the most recent app" instead would hand
    an already-attached app a second channel, and Reflex rejects a duplicate
    channel name outright.
    """
    for resolve_app, channel in _attached:
        if resolve_app() is app:
            return channel
    channel = XYChannel(registry, rebuild=make_rebuild_hook(app))
    app.register_channel(channel)
    _attached.append((app_ref(app), channel))
    wire_attached()

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
    return channel


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


def wire(channel: XYChannel) -> None:
    """Point the registry's fan-out seams at one data plane (tests)."""
    registry.on_publish(channel.broadcast_payload)
    registry.on_push(channel.broadcast_message)
    registry.on_error(channel.broadcast_error)


def wire_attached() -> None:
    """Point the registry's fan-out seams at *every* attached data plane.

    The registry is process-global; apps are not. A hot reload, an AppHarness
    test, or simply two Apps built in one process each get their own channel,
    and pointing the seams at the newest one alone would silently strand the
    subscribers of every other live app — their figures would keep updating
    server-side and never push. Fanning out costs one extra payload build per
    additional *live* app, which is exactly the case that would otherwise be
    broken; with the single app of a normal deployment it is the same work as
    `wire`.
    """
    registry.on_publish(_fan_out_payload)
    registry.on_push(_fan_out_message)
    registry.on_error(_fan_out_error)


async def _fan_out(calls: "Sequence[Coroutine[Any, Any, None]]") -> None:
    """Await every fan-out, then re-raise the first failure.

    One app's transport failing must not swallow the others' deliveries — that
    is the whole point of fanning out — but the error still has to surface the
    way a single-plane send does, so it is raised after the rest have run.
    """
    results = await asyncio.gather(*calls, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def _fan_out_payload(token: str, entry: Any) -> None:
    await _fan_out([plane.broadcast_payload(token, entry) for plane in _live_planes()])


async def _fan_out_message(
    token: str, message: dict, buffers: Any = None, version: Optional[int] = None
) -> None:
    await _fan_out(
        [plane.broadcast_message(token, message, buffers, version) for plane in _live_planes()]
    )


async def _fan_out_error(token: str, error: str, resync: bool = False) -> None:
    await _fan_out([plane.broadcast_error(token, error, resync) for plane in _live_planes()])


async def _xy_lifespan() -> None:
    """Capture the serving loop, then sweep idle figures forever."""
    registry.attach_loop(asyncio.get_running_loop())
    with contextlib.suppress(asyncio.CancelledError):  # normal shutdown
        await registry.sweep_forever()


class FigureProbeError(Exception):
    """A `@reflex_xy.figure` builder failed its compile-time probe."""


def _builder_location(builder: Any) -> str:
    try:
        filename = inspect.getsourcefile(builder)
        _, line = inspect.getsourcelines(builder)
    except (OSError, TypeError):
        return "<source unavailable>"
    return f"{filename}:{line}"


def _touches_session(builder: Any) -> bool:
    """Heuristic escape valve (constraint 2): builders that read the session
    (`self.router`) cannot be expected to run against default state — their
    probe failures degrade to a warning instead of failing the compile."""
    try:
        source = inspect.getsource(builder)
    except (OSError, TypeError):
        return False
    return "self.router" in source


def _iter_probed_figure_vars(state_cls: Any, seen: set[Any]):
    if state_cls in seen:
        return
    seen.add(state_cls)
    computed = getattr(state_cls, "computed_vars", {})
    for name, var in computed.items():
        if isinstance(var, (FigureVar, AsyncFigureVar)):
            yield state_cls, name, var
    for subclass in state_cls.get_substates():
        yield from _iter_probed_figure_vars(subclass, seen)


def probe_figure_builders(root_cls: Any = None) -> list[str]:
    """Run every probe-enabled `@reflex_xy.figure` builder against default
    state (reflex-integration.md §3.1): the compile gate of the escape-hatch
    tier. Returns the probed var full names; raises :class:`FigureProbeError`
    (wrapping the original) on the first failing builder.

    Level ``"build"`` runs the builder body and type-checks its return —
    hallucinated `xy.*` names, wrong kwargs, eager chrome errors, and a
    return value that is not a chart (or ``None``) fail here. ``"figure"``
    also compiles the returned chart. ``False`` (and, by default, async
    builders) are skipped. Builders whose source touches ``self.router`` degrade
    failures to a `RuntimeWarning`: they are session-dependent by
    declaration and only a live session can validate them.
    """
    import reflex as rx

    root_cls = root_cls if root_cls is not None else cast("Any", rx.State)
    root = root_cls(_reflex_internal_init=True)
    probed: list[str] = []
    for state_cls, name, var in _iter_probed_figure_vars(root_cls, set()):
        fget = var._fget
        level = getattr(fget, PROBE_ATTR, False)
        builder = getattr(fget, BUILDER_ATTR, None)
        if not level or builder is None:
            continue
        full_name = f"{state_cls.get_full_name()}.{name}"
        try:
            substate = root.get_substate(tuple(state_cls.get_full_name().split("."))[1:])
        except (KeyError, ValueError):
            continue  # not reachable from this root (e.g. mixin scaffolding)
        try:
            if inspect.iscoroutinefunction(builder):
                chart = asyncio.run(builder(substate))
            else:
                chart = builder(substate)
            if chart is not None and not (
                callable(getattr(chart, "figure", None))
                or callable(getattr(chart, "build_payload", None))
            ):
                # Every probe level checks the return *type*: a builder that
                # returns something no registry publish can accept would
                # otherwise reach hydrate before failing.
                msg = (
                    f"builder returned {type(chart).__name__}; expected an "
                    "xy Chart (or internal Figure), or None for 'no chart'"
                )
                raise TypeError(msg)
            if level == "figure" and chart is not None:
                _figure_of(chart)
        except Exception as exc:
            location = _builder_location(builder)
            if _touches_session(builder):
                warnings.warn(
                    f"@reflex_xy.figure probe: {full_name} ({location}) reads the "
                    f"session and failed against default state: {exc!r}. Probes "
                    "validate what they can; pass probe=False to silence.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            msg = (
                f"@reflex_xy.figure probe failed for {full_name} ({location}): "
                f"{type(exc).__name__}: {exc}. The builder ran against default "
                "state at compile so this error would not wait for a browser "
                "session; pass @reflex_xy.figure(probe=False) if this builder "
                "cannot run outside a live session."
            )
            raise FigureProbeError(msg) from exc
        probed.append(full_name)
    return probed


class XYPlugin(Plugin):
    """Reflex plugin: `plugins=[reflex_xy.XYPlugin()]` in rxconfig.py.

    `post_compile` is the one plugin hook that receives the live App, and it
    fires at backend worker startup — after the socket server exists, before
    any client connects, and never during frontend-only compiles. It wires
    the data plane and then runs the figure-builder compile probes (§3.1) so
    escape-hatch builders fail `reflex run`, not the browser.
    """

    def post_compile(self, **context: Any) -> None:
        app = context.get("app")
        if app is not None:
            setup(app)
            probe_figure_builders()


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
    """Forget every attached data plane (test isolation only)."""
    _attached.clear()
