"""The adapter's @reflex_xy.figure var: registration, stability, rebuild."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
import reflex as rx
import reflex_xy
from reflex_xy.tokens import builder_of, parse_token
from reflex_xy_test_helpers import make_router_data

import xy


class VarDemo(rx.State):
    """State under test: `n` drives the chart; `_scale` is a backend var."""

    n: int = 100
    _scale: float = 2.0

    @reflex_xy.figure
    def chart(self) -> xy.Chart:
        xs = np.linspace(0.0, 1.0, self.n)
        return xy.scatter_chart(xy.scatter(xs, xs * self._scale), width=500, height=300)

    @reflex_xy.figure
    def maybe_chart(self):
        if self.n < 0:
            return None
        xs = np.linspace(0.0, 1.0, 4)
        return xy.line_chart(xy.line(xs, xs), width=300, height=200)


def hydrated_substate(client_token: str) -> VarDemo:
    root = rx.State(_reflex_internal_init=True)
    root.router = make_router_data(client_token)
    return root.get_substate(tuple(VarDemo.get_full_name().split("."))[1:])


def test_deps_track_the_builder_not_the_wrapper():
    deps = VarDemo.computed_vars["chart"]._deps(VarDemo)
    assert deps == {VarDemo.get_full_name(): {"n", "_scale"}}


def test_evaluation_registers_and_token_parses(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    token = state.chart
    parsed = parse_token(token)
    assert parsed is not None
    assert parsed.client_token == client_token
    assert parsed.state_full_name == VarDemo.get_full_name()
    assert parsed.var_name == "chart"
    entry = _fresh_registry.get(token)
    assert entry is not None
    assert entry.figure.traces[0].n_points == 100


def test_dep_change_keeps_token_bumps_version(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    token = state.chart
    state.n = 250
    VarDemo.computed_vars["chart"].mark_dirty(state)
    assert state.chart == token  # stable identity: frontend never re-renders
    entry = _fresh_registry.get(token)
    assert entry.version == 2
    assert entry.figure.traces[0].n_points == 250


def test_recompute_broadcasts_to_publish_hook(_fresh_registry, client_token):
    published: list[tuple[str, int]] = []

    async def hook(token, entry):
        published.append((token, entry.version))

    async def main():
        _fresh_registry.attach_loop(asyncio.get_running_loop())
        _fresh_registry.on_publish(hook)
        state = hydrated_substate(client_token)
        token = state.chart  # first registration: new entry, no fan-out needed yet
        state.n = 300
        VarDemo.computed_vars["chart"].mark_dirty(state)
        assert state.chart == token
        await asyncio.sleep(0.02)
        return token

    token = asyncio.run(main())
    assert published == [(token, 2)]


def test_pre_hydration_returns_empty(_fresh_registry):
    root = rx.State(_reflex_internal_init=True)
    state = root.get_substate(tuple(VarDemo.get_full_name().split("."))[1:])
    assert state.chart == ""  # no client token yet -> no figure, no crash
    assert len(_fresh_registry) == 0


def test_none_chart_unregisters(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    token = state.maybe_chart
    assert _fresh_registry.get(token) is not None
    state.n = -1
    VarDemo.computed_vars["maybe_chart"].mark_dirty(state)
    assert state.maybe_chart == ""
    assert _fresh_registry.get(token) is None


def test_builder_resolvable_from_class(client_token):
    builder = builder_of(VarDemo, "chart")
    assert builder is not None
    state = hydrated_substate(client_token)
    chart = builder(state)
    assert chart.figure().traces[0].n_points == state.n


def test_underscore_var_rejected():
    with pytest.raises(ValueError, match="must not start with '_'"):

        class Bad(rx.State):  # noqa: F841 - definition is the assertion
            @reflex_xy.figure
            def _hidden(self):
                return None


def test_var_value_survives_state_serialization(_fresh_registry, client_token):
    """Simulates the reconnect-on-another-node handoff: the token rides the
    state serializer (as it would through redis); the figure does not."""
    state = hydrated_substate(client_token)
    token = state.chart
    payload = state._serialize()
    assert payload  # pickles fine with a registered figure in play

    _fresh_registry.release(token)  # "another node": no local figure
    restored = VarDemo._deserialize(payload)
    # The cached var value comes back verbatim WITHOUT re-running the
    # builder — exactly why the namespace needs the rebuild-from-state path.
    assert restored.chart == token
    assert _fresh_registry.get(token) is None
