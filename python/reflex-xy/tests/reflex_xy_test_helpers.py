"""Helpers shared by the package-local reflex-xy tests."""

from __future__ import annotations


def make_router_data(token: str):
    import reflex.istate.data as istate_data

    return istate_data.RouterData.from_router_data({"token": token})
