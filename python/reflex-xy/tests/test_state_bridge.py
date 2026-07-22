"""Adapter rebuild-from-state: the multi-worker / reconnect recovery path."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
import reflex as rx
import reflex_xy
from reflex.istate.manager.memory import StateManagerMemory
from reflex_xy.state_bridge import make_rebuild_hook
from reflex_xy.tokens import build_state_token, parse_token

import xy


class BridgeDemo(rx.State):
    points: int = 12

    @reflex_xy.figure
    def chart(self) -> xy.Chart:
        xs = np.linspace(0.0, 1.0, self.points)
        return xy.scatter_chart(xy.scatter(xs, xs), width=400, height=300)


def make_app_stub():
    # 0.9.6 memory manager needs no root class up front: the BaseStateToken
    # passed to get_state/modify_state carries it.
    return SimpleNamespace(state_manager=StateManagerMemory())


def test_rebuild_default_state(_fresh_registry, client_token):
    """A fresh node with no prior events still serves the figure (defaults)."""
    app = make_app_stub()
    token = build_state_token(client_token, BridgeDemo.get_full_name(), "chart")
    hook = make_rebuild_hook(app)
    figure = asyncio.run(hook(token))
    assert figure is not None
    assert figure.traces[0].n_points == 12


def test_rebuild_reads_session_state(_fresh_registry, client_token):
    """State mutated by earlier events drives the rebuilt figure."""
    app = make_app_stub()
    token_obj = rx.BaseStateToken(ident=client_token, cls=rx.State)

    async def main():
        async with app.state_manager.modify_state(token_obj) as root:
            sub = await root.get_state(BridgeDemo)
            sub.points = 77
        hook = make_rebuild_hook(app)
        return await hook(build_state_token(client_token, BridgeDemo.get_full_name(), "chart"))

    figure = asyncio.run(main())
    assert figure is not None
    assert figure.traces[0].n_points == 77


@pytest.mark.parametrize(
    "token",
    [
        "not-a-state-token",
        # valid grammar, unknown state
        "xyv1|11111111-2222-4333-8444-555566667777|no.such_state|chart",
    ],
)
def test_rebuild_unknown_fails_closed(_fresh_registry, token):
    hook = make_rebuild_hook(make_app_stub())
    assert asyncio.run(hook(token)) is None


def test_rebuild_var_without_builder_fails_closed(_fresh_registry, client_token):
    """A plain @rx.var of the same name is not a figure recipe."""

    class NotAFigure(rx.State):
        @rx.var
        def chart(self) -> str:
            return "hello"

    token = build_state_token(client_token, NotAFigure.get_full_name(), "chart")
    hook = make_rebuild_hook(make_app_stub())
    assert asyncio.run(hook(token)) is None


def test_token_full_name_resolves_class(client_token):
    token = build_state_token(client_token, BridgeDemo.get_full_name(), "chart")
    parsed = parse_token(token)
    cls = rx.State.get_class_substate(tuple(parsed.state_full_name.split(".")))
    assert cls is BridgeDemo
