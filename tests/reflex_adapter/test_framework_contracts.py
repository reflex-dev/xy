"""Pins for the Reflex framework facts the component API design rests on.

Facts R1/R7/R8 from spec/design/reflex-component-api-options.md §4, verified
against reflex 0.9.6-0.9.8. These tests use a local ``Handle`` type (not the
shipped ``reflex_xy`` handles) on purpose: they pin the *framework* contract
itself, so a Reflex upgrade that moves the ground fails here first, named
after the design fact that broke — independent of any adapter code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypedDict, TypeVar, get_args, get_type_hints

import pytest
import reflex as rx

S = TypeVar("S")


@dataclass(frozen=True)
class ContractHandle(Generic[S]):
    """Stand-in for reflex_xy's handle types: frozen, generic, tiny."""

    token: str = ""


@rx.serializer
def _serialize_contract_handle(handle: ContractHandle) -> dict:
    return {"token": handle.token}


class ContractSchema(TypedDict):
    x: list[float]
    y: list[float]
    mag: list[float]


class ContractState(rx.State):
    points: int = 5
    handles: list[ContractHandle[ContractSchema]] = []

    @rx.var
    def cloud(self) -> ContractHandle[ContractSchema]:
        return ContractHandle("tok")


class ContractComponent(rx.Component):
    """Minimal component with one ``Var[T]``-typed prop (the R1 seam)."""

    tag = "ContractComponent"
    figure: rx.Var[ContractHandle]


def test_computed_var_preserves_parametrized_generic_alias():
    """R7: the class-level Var of a computed var returning a parametrized
    generic frozen dataclass carries the full alias; ``get_args`` recovers
    the TypedDict and ``get_type_hints`` its column names — the schema
    channel, readable without executing anything."""
    var_type = ContractState.cloud._var_type
    args = get_args(var_type)
    assert args == (ContractSchema,)
    assert set(get_type_hints(args[0])) == {"x", "y", "mag"}


def test_list_base_var_and_loop_element_keep_the_alias():
    """R7 (foreach half): a base var annotated ``list[Handle[Schema]]``
    keeps the alias, and so do the element Vars produced by indexing and by
    ``rx.foreach`` — schema-aware checks work per item inside loops."""
    assert get_args(ContractState.handles._var_type) == (ContractHandle[ContractSchema],)
    assert ContractState.handles[0]._var_type == ContractHandle[ContractSchema]

    element_types: list[object] = []

    def render(item: rx.Var) -> rx.Component:
        element_types.append(item._var_type)
        return rx.text("item")

    rx.foreach(ContractState.handles, render).render()
    assert element_types == [ContractHandle[ContractSchema]]


def test_var_typed_prop_checks_fire_at_create():
    """R1: a prop annotated ``rx.Var[Handle]`` accepts the parametrized var
    and rejects an int var and a raw string with ``TypeError`` at
    ``create()`` — i.e. at page evaluation, which is compile time."""
    ContractComponent.create(figure=ContractState.cloud)

    with pytest.raises(TypeError, match="figure"):
        ContractComponent.create(figure=ContractState.points)
    with pytest.raises(TypeError, match="figure"):
        ContractComponent.create(figure="raw-token-string")


def test_unknown_event_kwarg_fails_but_unknown_prop_becomes_style():
    """R8: an unknown ``on_*`` kwarg already raises ``ValueError`` at
    ``create()`` (framework machinery, only the message needs help). An
    unknown *non-event* kwarg is silently absorbed into ``style`` — this
    half documents the hazard the flat factories' kwarg partition exists to
    compensate for. If Reflex ever starts rejecting these, the partition
    layer gets simpler; this test failing on the second clause is that
    signal."""
    with pytest.raises(ValueError, match="on_select_typo"):
        ContractComponent.create(on_select_typo=rx.console_log("x"))

    absorbed = ContractComponent.create(colormapp="viridis")
    assert "colormapp" in absorbed.style
