"""Shared pyplot-shim test hygiene: no figure or rcParams state may leak
between tests — every test starts from a closed, default-configured shim."""

from __future__ import annotations

import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _pyplot_hygiene():
    plt.close("all")
    plt.rcParams.reset()
    yield
    plt.close("all")
    plt.rcParams.reset()
