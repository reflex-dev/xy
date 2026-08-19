"""Tests for the bundled ``xy[reflex]`` integration.

These run only when the optional framework dependency is installed
(`uv sync --extra reflex --group dev`); plain `xy` must never require Reflex
(CLAUDE.md dependency rule), so this suite uses ``pytest.importorskip`` for
both optional import namespaces.
"""

from __future__ import annotations

import pytest

reflex = pytest.importorskip("reflex")
pytest.importorskip("reflex_xy")

import reflex_xy.app as adapter_app  # noqa: E402
from reflex_xy.plan import reset_plans_for_tests  # noqa: E402
from reflex_xy.registry import reset_registry_for_tests  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Isolate registry + plan map + wiring between tests."""
    registry = reset_registry_for_tests()
    reset_plans_for_tests()
    adapter_app.reset_setup_for_tests()
    yield registry
    reset_registry_for_tests()
    reset_plans_for_tests()
    adapter_app.reset_setup_for_tests()


@pytest.fixture
def app_cwd(tmp_path, monkeypatch):
    """Emulate a Reflex app directory for the compile-time asset seams.

    `rx.asset` symlinks into `Path.cwd()/assets` and `payload_asset` writes
    under it, so a test that mounts a chart needs a private cwd. The private
    component class is cached per process and its asset registration is
    per-cwd, so it is dropped too — rebuilding it exercises registration in
    *this* cwd instead of reusing another test's symlinks.
    """
    monkeypatch.chdir(tmp_path)
    import reflex_xy.component as component_mod

    monkeypatch.setattr(component_mod, "_component_cls", None)
    return tmp_path


@pytest.fixture
def client_token() -> str:
    return "11111111-2222-4333-8444-555566667777"


def make_router_data(token: str):
    import reflex.istate.data as istate_data

    return istate_data.RouterData.from_router_data({"token": token})
