"""reflex-xy adapter tests.

These run only when the adapter's dependencies are installed
(`uv pip install -e python/reflex-xy`); the core `xy` suite must
never require Reflex (CLAUDE.md dependency rule), so everything here
importorskips.
"""

from __future__ import annotations

import pytest

reflex = pytest.importorskip("reflex")
pytest.importorskip("reflex_xy")

import reflex_xy.app as adapter_app  # noqa: E402
from reflex_xy.registry import reset_registry_for_tests  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Isolate registry + wiring between tests."""
    registry = reset_registry_for_tests()
    adapter_app.reset_setup_for_tests()
    yield registry
    reset_registry_for_tests()
    adapter_app.reset_setup_for_tests()


@pytest.fixture
def client_token() -> str:
    return "11111111-2222-4333-8444-555566667777"


def make_router_data(token: str):
    import reflex.istate.data as istate_data

    return istate_data.RouterData.from_router_data({"token": token})
