"""Deterministic guardrails against structural regressions in the pyplot shim.

Wall-clock performance is tracked by CodSpeed and ``make check-pyplot-speed``.
The tests here enforce the underlying invariants without comparing
sub-millisecond timings on shared CI runners.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def test_theme_and_axis_components_are_shared() -> None:
    """CSS token validation must stay O(1) per process, not O(charts)."""
    from xy.pyplot import _axes

    plt.close("all")
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    first = ax._build_chart(640, 480)
    plt.close("all")
    _fig2, ax2 = plt.subplots()
    ax2.plot([1, 2], [3, 4])
    second = ax2._build_chart(640, 480)
    themes1 = [c for c in first.children if type(c).__name__ == "Theme"]
    themes2 = [c for c in second.children if type(c).__name__ == "Theme"]
    if themes1 and themes2:  # mpl theme active (default)
        assert themes1[0] is themes2[0], "theme component must be cached, not rebuilt"
    assert _axes._component_cache, "component cache unexpectedly empty"


@pytest.mark.parametrize(
    ("method", "axis"),
    [("bar", "x"), ("bar", "y"), ("barh", "x"), ("barh", "y")],
)
def test_bar_dataless_probe_avoids_materializing_geometry(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    axis: str,
) -> None:
    """Ordinary bars answer the empty-axis question from their compact entry."""
    plt.close("all")
    _fig, ax = plt.subplots()
    getattr(ax, method)(["a", "b"], [1.0, 2.0])

    def unexpected_scan(_axis: str):
        raise AssertionError("ordinary bar dataless probe materialized full geometry")

    monkeypatch.setattr(ax, "_iter_entry_arrays", unexpected_scan)
    assert not ax._axis_is_dataless(axis)


def test_all_nonfinite_bar_remains_dataless() -> None:
    plt.close("all")
    _fig, ax = plt.subplots()
    ax.bar([np.nan], [np.nan], bottom=np.nan)

    assert ax._axis_is_dataless("x")
    assert ax._axis_is_dataless("y")
