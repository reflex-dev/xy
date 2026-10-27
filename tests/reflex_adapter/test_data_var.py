"""The @reflex_xy.data computed var: columns in, typed handle out."""

from __future__ import annotations

import asyncio
from typing import TypedDict, get_args

import numpy as np
import pytest
import reflex as rx
from reflex_base.vars.base import AsyncComputedVar

import reflex_xy
import xy
from reflex_xy.data_vars import AsyncDataVar, DataVar, validate_columns
from reflex_xy.handles import DataHandle
from reflex_xy.plan import build_plan
from reflex_xy.tokens import build_plan_token, builder_of, parse_token

from .conftest import make_router_data


class DataSchema(TypedDict):
    x: np.ndarray
    y: np.ndarray
    mag: np.ndarray


class DataDemo(rx.State):
    n: int = 16
    _scale: float = 2.0

    @reflex_xy.data
    def cloud(self) -> DataSchema:
        xs = np.linspace(0.0, 1.0, self.n)
        return {"x": xs, "y": xs * self._scale, "mag": np.abs(xs)}

    @reflex_xy.data
    def maybe(self):
        if self.n < 0:
            return None
        return {"x": [1.0], "y": [2.0]}

    @reflex_xy.data
    async def remote(self) -> DataSchema:
        await asyncio.sleep(0)
        xs = np.linspace(0.0, 1.0, self.n)
        return {"x": xs, "y": xs, "mag": xs}


def hydrated_substate(client_token: str) -> DataDemo:
    root = rx.State(_reflex_internal_init=True)
    root.router = make_router_data(client_token)
    return root.get_substate(tuple(DataDemo.get_full_name().split("."))[1:])


def test_dispatch_and_schema_channel():
    """R7: the TypedDict return annotation parametrizes the var's value type;
    async methods dispatch to AsyncDataVar exactly like rx.var."""
    assert isinstance(DataDemo.computed_vars["cloud"], DataVar)
    assert DataDemo.cloud._var_type == DataHandle[DataSchema]
    assert get_args(DataDemo.cloud._var_type) == (DataSchema,)
    # untyped methods degrade to the plain handle (columns checked at runtime)
    assert DataDemo.maybe._var_type is DataHandle
    assert isinstance(DataDemo.computed_vars["remote"], AsyncDataVar)
    assert isinstance(DataDemo.computed_vars["remote"], AsyncComputedVar)
    assert DataDemo.remote._var_type == DataHandle[DataSchema]


def test_deps_track_the_data_method_not_the_wrapper():
    deps = DataDemo.computed_vars["cloud"]._deps(DataDemo)
    assert deps == {DataDemo.get_full_name(): {"n", "_scale"}}


def test_evaluation_publishes_columns_and_returns_handle(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    handle = state.cloud
    assert isinstance(handle, DataHandle)
    parsed = parse_token(handle.token)
    assert parsed is not None and parsed.kind == "data"
    assert parsed.client_token == client_token
    assert parsed.var_name == "cloud"
    entry = _fresh_registry.get_columns(handle.token)
    assert entry is not None
    assert sorted(entry.columns) == ["mag", "x", "y"]
    assert len(entry.columns["x"]) == 16


def test_republish_keeps_handle_bumps_column_version(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    handle = state.cloud
    state.n = 32
    DataDemo.computed_vars["cloud"].mark_dirty(state)
    assert state.cloud == handle  # stable identity, like figure vars
    entry = _fresh_registry.get_columns(handle.token)
    assert entry.version == 2
    assert len(entry.columns["x"]) == 32


def test_pre_session_short_circuit(_fresh_registry):
    root = rx.State(_reflex_internal_init=True)
    state = root.get_substate(tuple(DataDemo.get_full_name().split("."))[1:])
    assert state.cloud == DataHandle("")  # data method never ran
    assert len(_fresh_registry._column_entries) == 0


def test_none_releases_columns(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    token = state.maybe.token
    assert _fresh_registry.get_columns(token) is not None
    state.n = -1
    DataDemo.computed_vars["maybe"].mark_dirty(state)
    assert state.maybe == DataHandle("")
    assert _fresh_registry.get_columns(token) is None


def test_async_variant_awaits_and_publishes(_fresh_registry, client_token):
    state = hydrated_substate(client_token)

    async def main():
        handle = await state.remote
        assert _fresh_registry.get_columns(handle.token) is not None
        return handle

    handle = asyncio.run(main())
    assert handle.token.startswith("xyd1|")


def test_underscore_name_refused():
    with pytest.raises(ValueError, match="must not start with '_'"):

        class BadData(rx.State):  # noqa: F841 - definition is the assertion
            @reflex_xy.data
            def _hidden(self):
                return None


def test_method_resolvable_from_class(client_token):
    method = builder_of(DataDemo, "cloud")
    assert method is not None
    state = hydrated_substate(client_token)
    assert sorted(method(state)) == ["mag", "x", "y"]


@pytest.mark.parametrize(
    ("columns", "match"),
    [
        ([1, 2, 3], "mapping"),
        ({1: [1.0]}, "column names must be strings"),
        ({"x": "not-values"}, "array-like"),
        ({"x": {"nested": 1}}, "array-like"),
        ({"x": 3.5}, "with a length"),
    ],
)
def test_validate_columns_rejects_malformed(columns, match):
    with pytest.raises((TypeError, ValueError), match=match):
        validate_columns(columns, source="Demo.cloud")


def test_validate_columns_allows_mixed_lengths_and_dims():
    """One var may feed marks with different row counts — a stairs mark's
    ``len+1`` edges, a heatmap's 2-D grid — beside ordinary columns.
    Coupled-length contracts live with the mark validators at bind, where
    the errors name the mark and channels involved."""
    columns = {
        "x": np.arange(5.0),
        "counts": np.arange(4.0),
        "edges": np.arange(5.0),
        "grid": np.arange(12.0).reshape(3, 4),
    }
    assert validate_columns(columns, source="Demo.cloud") == columns


def test_republish_rebuilds_and_bumps_mounted_dependents(_fresh_registry, client_token):
    """The data-token -> digest index: a column republish re-binds every
    mounted plan into a fresh figure generation (broadcast by publish)."""
    state = hydrated_substate(client_token)
    handle = state.cloud
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    composite = build_plan_token(plan.digest, handle.token)
    # mount: first bind, as the namespace does on sub
    entry = _fresh_registry.publish(
        composite,
        plan.bind(_fresh_registry.get_columns(handle.token).columns).figure(),
        broadcast=False,
    )
    _fresh_registry.bind_plan(handle.token, plan.digest)
    assert entry.figure.traces[0].n_points == 16

    state.n = 48
    DataDemo.computed_vars["cloud"].mark_dirty(state)
    assert state.cloud == handle
    rebuilt = _fresh_registry.get(composite)
    assert rebuilt.version == entry.version + 1
    assert rebuilt.figure.traces[0].n_points == 48


def test_stale_column_generation_cannot_overwrite_a_newer_publish(_fresh_registry, client_token):
    """Two concurrent republishes may finish their rebuilds in reverse order;
    the older generation's late publish must be dropped, atomically with the
    currency check, so subscribers never regress to stale pixels."""
    state = hydrated_substate(client_token)
    handle = state.cloud
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    composite = build_plan_token(plan.digest, handle.token)
    _fresh_registry.publish(
        composite,
        plan.bind(_fresh_registry.get_columns(handle.token).columns).figure(),
        broadcast=False,
    )
    _fresh_registry.bind_plan(handle.token, plan.digest)

    old_generation = _fresh_registry.get_columns(handle.token)
    state.n = 48
    DataDemo.computed_vars["cloud"].mark_dirty(state)
    assert state.cloud == handle
    current = _fresh_registry.get(composite)
    assert current.figure.traces[0].n_points == 48

    # The older generation's rebuild finishes late: its publish must be a
    # no-op (same for its failure path — no release, no stale err frame).
    _fresh_registry._rebuild_dependent(handle.token, plan.digest, old_generation)
    after = _fresh_registry.get(composite)
    assert after is current
    assert after.figure.traces[0].n_points == 48
    assert after.version == current.version

    broken = type(old_generation)(columns={"x": [1.0]}, token=handle.token, version=1)
    _fresh_registry._rebuild_dependent(handle.token, plan.digest, broken)
    assert _fresh_registry.get(composite) is current  # stale failure: no release


def test_republish_drops_unmounted_dependents_from_the_index(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    handle = state.cloud
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    _fresh_registry.bind_plan(handle.token, plan.digest)  # indexed, never mounted

    state.n = 20
    DataDemo.computed_vars["cloud"].mark_dirty(state)
    assert state.cloud == handle
    assert _fresh_registry._digests_by_data_token.get(handle.token) is None


def test_unmount_transitions_drop_plan_bindings(_fresh_registry, client_token):
    """The plan index is bounded by *mounted* plans: unsubscribe/disconnect
    and entry eviction (release, sweep) must unbind — never only a later
    republish under the same session token (short-lived sessions would
    otherwise accumulate bindings forever)."""
    registry = _fresh_registry
    data_token = f"xyd1|{client_token}|app.app.State|cloud"
    digest = "ab" * 10
    composite = build_plan_token(digest, data_token)

    # subscriber-only mount (no cached figure): last unsubscribe unbinds
    registry.bind_plan(data_token, digest)
    registry.subscribe(composite, "sid-1", rebuildable=True)
    registry.unsubscribe(composite, "sid-1")
    assert registry._digests_by_data_token.get(data_token) is None

    # same via disconnect
    registry.bind_plan(data_token, digest)
    registry.subscribe(composite, "sid-2", rebuildable=True)
    registry.disconnect("sid-2")
    assert registry._digests_by_data_token.get(data_token) is None

    # a cached figure keeps the mount alive across unsubscribe...
    registry.bind_plan(data_token, digest)
    registry.subscribe(composite, "sid-3", rebuildable=True)
    registry.publish(composite, xy.scatter_chart(xy.scatter([0.0], [0.0])).figure())
    registry.unsubscribe(composite, "sid-3")
    assert registry._digests_by_data_token.get(data_token) == {digest}
    # ...until the entry itself goes: release unbinds
    registry.release(composite)
    assert registry._digests_by_data_token.get(data_token) is None

    # and the TTL sweep unbinds an idle, unsubscribed composite entry
    registry.bind_plan(data_token, digest)
    entry = registry.publish(composite, xy.scatter_chart(xy.scatter([0.0], [0.0])).figure())
    registry.sweep(now=entry.last_access + 10**9)
    assert registry._digests_by_data_token.get(data_token) is None


def test_release_columns_releases_dependent_figures(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    handle = state.maybe.token
    plan = build_plan("scatter_chart", (xy.scatter("x", "y"),), {})
    composite = build_plan_token(plan.digest, handle)
    columns = _fresh_registry.get_columns(handle).columns
    _fresh_registry.publish(composite, plan.bind(columns).figure(), broadcast=False)
    _fresh_registry.bind_plan(handle, plan.digest)

    state.n = -1
    DataDemo.computed_vars["maybe"].mark_dirty(state)
    assert state.maybe == DataHandle("")
    assert _fresh_registry.get(composite) is None
    assert _fresh_registry.get_columns(handle) is None


def test_column_entries_sweep_like_figures(_fresh_registry, client_token):
    state = hydrated_substate(client_token)
    token = state.cloud.token
    entry = _fresh_registry.get_columns(token)
    dropped = _fresh_registry.sweep(now=entry.last_access + 10**9)
    assert token in dropped
    assert _fresh_registry.get_columns(token) is None
