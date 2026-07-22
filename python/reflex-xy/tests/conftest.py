"""Fixtures for the reflex-xy package test suite."""

from __future__ import annotations

import pytest
import reflex_xy.app as adapter_app
from reflex_xy.registry import reset_registry_for_tests


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
