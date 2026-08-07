"""Worker-startup plan registration: X4 made true by construction.

Backend-only Reflex workers (dev backend subprocesses, prod workers) import
the app module but never run the frontend compile, so page bodies — and the
chart-factory calls inside them that register plans — would never execute
there. `setup(app)`'s lifespan evaluates the app's unevaluated pages once at
startup; these tests pin that seam (reflex-integration.md §3.6).
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import TypedDict

import numpy as np
import pytest
import reflex as rx

import reflex_xy
from reflex_xy.app import _ensure_page_plans
from reflex_xy.plan import _PLANS


class PageSchema(TypedDict):
    x: np.ndarray
    y: np.ndarray


class PagePlanState(rx.State):
    @reflex_xy.data
    def table(self) -> PageSchema:
        return {"x": np.array([1.0]), "y": np.array([2.0])}


def test_backend_worker_page_evaluation_registers_plans(app_cwd, _fresh_registry):
    def index() -> rx.Component:
        return reflex_xy.scatter_chart(data=PagePlanState.table, x="x", y="y")

    app = SimpleNamespace(_unevaluated_pages={"index": SimpleNamespace(component=index)})
    assert not _PLANS  # the worker imported the module; nothing evaluated pages
    _ensure_page_plans(app)
    assert len(_PLANS) == 1  # the factory ran and content-addressed its plan


def test_failing_page_refuses_worker_startup(app_cwd, _fresh_registry):
    """Fail closed: a worker whose plan map would be incomplete must not
    serve (blank charts depending on which worker the balancer picks). The
    error names every failing page; healthy pages still registered, so a
    fixed deployment starts clean."""

    def good() -> rx.Component:
        return reflex_xy.line_chart(data=PagePlanState.table, x="x", y="y")

    def broken() -> rx.Component:
        raise RuntimeError("page body exploded")

    def also_broken() -> rx.Component:
        raise ValueError("second page exploded")

    app = SimpleNamespace(
        _unevaluated_pages={
            "broken": SimpleNamespace(component=broken),
            "good": SimpleNamespace(component=good),
            "worse": SimpleNamespace(component=also_broken),
        }
    )
    with pytest.raises(RuntimeError, match=r"'broken'.*'worse'") as excinfo:
        _ensure_page_plans(app)
    assert "page body exploded" in str(excinfo.value)
    assert "second page exploded" in str(excinfo.value)
    assert len(_PLANS) == 1  # the good page registered before the refusal


def test_apps_without_unevaluated_pages_are_a_noop():
    _ensure_page_plans(SimpleNamespace())  # nothing to do, nothing raised
    assert not _PLANS


def _fake_app(pages: dict, tasks: list) -> SimpleNamespace:
    """Enough of an `rx.App` for `setup()`: a socket server and task sink."""

    class _Sio:
        def register_namespace(self, namespace) -> None:
            pass

    return SimpleNamespace(
        sio=_Sio(),
        _unevaluated_pages=pages,
        register_lifespan_task=tasks.append,
        _state=None,
        state_manager=None,
    )


def test_page_evaluation_runs_before_the_lifespan_coroutine_is_scheduled(app_cwd, _fresh_registry):
    """Fail-closed only holds if the refusal reaches Reflex's startup path.

    Reflex runs a coroutine lifespan task as `asyncio.create_task(task())`
    and then yields — so an `async def` body raising after that point would
    leave the worker serving with an incomplete plan map, the exact
    load-balancer-dependent failure `_ensure_page_plans` exists to prevent.
    The registered task must therefore do the page pass in its *synchronous*
    part (the `task()` call) and return the sweep coroutine.
    """

    def broken() -> rx.Component:
        raise RuntimeError("page body exploded")

    tasks: list = []
    reflex_xy.setup(_fake_app({"broken": SimpleNamespace(component=broken)}, tasks))
    (task,) = tasks
    assert not inspect.iscoroutinefunction(task)  # else the raise lands in the task
    with pytest.raises(RuntimeError, match="page body exploded"):
        task()  # Reflex calls this inline, before create_task and before yield


def test_lifespan_task_returns_the_sweep_coroutine(app_cwd, _fresh_registry):
    """The healthy path still hands Reflex a coroutine to run as the task."""

    def index() -> rx.Component:
        return reflex_xy.scatter_chart(data=PagePlanState.table, x="x", y="y")

    tasks: list = []
    reflex_xy.setup(_fake_app({"index": SimpleNamespace(component=index)}, tasks))
    (task,) = tasks
    coro = task()
    assert inspect.iscoroutine(coro)
    coro.close()  # never awaited here; the sweep runs forever
    assert len(_PLANS) == 1  # the page pass already ran, synchronously
