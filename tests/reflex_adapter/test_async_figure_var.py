"""Async figure builders: @reflex_xy.figure on `async def`, mirroring
reflex's ComputedVar/AsyncComputedVar split."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
import reflex as rx
import reflex_xy
from reflex.istate.manager.memory import StateManagerMemory
from reflex_base.vars.base import AsyncComputedVar
from reflex_xy.state_bridge import make_rebuild_hook
from reflex_xy.tokens import build_state_token
from reflex_xy.vars import AsyncFigureVar, FigureVar

import xy

from .conftest import make_router_data

BUILDER_CALLS = {"count": 0}


async def _fetch_scale() -> float:
    """Stands in for a database / HTTP / dataframe-store round trip."""
    await asyncio.sleep(0)
    return 3.0


class AsyncVarDemo(rx.State):
    n: int = 50
    _offset: float = 0.0

    @reflex_xy.figure
    async def chart(self) -> xy.Chart:
        BUILDER_CALLS["count"] += 1
        scale = await _fetch_scale()
        xs = np.linspace(0.0, 1.0, self.n)
        return xy.scatter_chart(xy.scatter(xs, xs * scale + self._offset), width=400, height=300)

    @reflex_xy.figure
    async def maybe_chart(self):
        if self.n < 0:
            return None
        xs = np.linspace(0.0, 1.0, 4)
        return xy.line_chart(xy.line(xs, xs), width=300, height=200)

    @reflex_xy.figure
    def sync_chart(self) -> xy.Chart:
        xs = np.linspace(0.0, 1.0, 8)
        return xy.line_chart(xy.line(xs, xs), width=300, height=200)


def hydrated_substate(client_token: str) -> AsyncVarDemo:
    root = rx.State(_reflex_internal_init=True)
    root.router = make_router_data(client_token)
    return root.get_substate(tuple(AsyncVarDemo.get_full_name().split("."))[1:])


def test_dispatch_mirrors_reflex():
    """Same rule rx.var applies: iscoroutinefunction -> the Async variant."""
    assert isinstance(AsyncVarDemo.computed_vars["chart"], AsyncFigureVar)
    assert isinstance(AsyncVarDemo.computed_vars["chart"], AsyncComputedVar)
    assert isinstance(AsyncVarDemo.computed_vars["sync_chart"], FigureVar)
    assert not isinstance(AsyncVarDemo.computed_vars["sync_chart"], AsyncComputedVar)


def test_deps_track_the_async_builder_body():
    deps = AsyncVarDemo.computed_vars["chart"]._deps(AsyncVarDemo)
    assert deps == {AsyncVarDemo.get_full_name(): {"n", "_offset"}}


def test_await_registers_caches_and_rebuilds(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    calls_before = BUILDER_CALLS["count"]

    async def main():
        token = await state.chart
        entry = _fresh_registry.get(token)
        assert entry is not None
        assert entry.figure.traces[0].n_points == 50

        # cache hit: the builder (and its awaited fetch) must not rerun
        assert await state.chart == token
        assert BUILDER_CALLS["count"] == calls_before + 1

        # dependency change -> dirty -> re-await rebuilds, token stable
        state.n = 120
        type(state).computed_vars["chart"].mark_dirty(state)
        assert await state.chart == token
        assert BUILDER_CALLS["count"] == calls_before + 2
        assert _fresh_registry.get(token).version == 2
        assert _fresh_registry.get(token).figure.traces[0].n_points == 120

    asyncio.run(main())


def test_pre_hydration_returns_empty(_fresh_registry):
    root = rx.State(_reflex_internal_init=True)
    state = root.get_substate(tuple(AsyncVarDemo.get_full_name().split("."))[1:])
    assert asyncio.run(state.chart) == ""
    assert len(_fresh_registry) == 0


def test_none_chart_unregisters(_fresh_registry, client_token):
    state = hydrated_substate(client_token)

    async def main():
        token = await state.maybe_chart
        assert _fresh_registry.get(token) is not None
        state.n = -1
        type(state).computed_vars["maybe_chart"].mark_dirty(state)
        assert await state.maybe_chart == ""
        assert _fresh_registry.get(token) is None

    asyncio.run(main())


def test_rebuild_from_state_awaits_async_builder(_fresh_registry, client_token):
    """The reconnect-on-a-fresh-node path awaits the data source again."""
    app = SimpleNamespace(state_manager=StateManagerMemory())
    token_obj = rx.BaseStateToken(ident=client_token, cls=rx.State)

    async def main():
        async with app.state_manager.modify_state(token_obj) as root:
            sub = await root.get_state(AsyncVarDemo)
            sub.n = 77
        hook = make_rebuild_hook(app)
        return await hook(build_state_token(client_token, AsyncVarDemo.get_full_name(), "chart"))

    figure = asyncio.run(main())
    assert figure is not None
    assert figure.traces[0].n_points == 77


def test_underscore_async_builder_rejected():
    with pytest.raises(ValueError, match="must not start with '_'"):

        class BadAsync(rx.State):  # noqa: F841 - definition is the assertion
            @reflex_xy.figure
            async def _hidden(self):
                return None
