"""The shim's speed promise, as a test: pyplot builds the same chart the
declarative API builds, plus only figure-lifecycle bookkeeping.

Locally measured (2026-07-14, M-series): +60% at 10k points, +26% at 100k —
the 10k number is ~50us of fixed per-figure bookkeeping over an ~85us
baseline, not O(n) work. The gate uses generous headroom plus a small
absolute allowance for sub-millisecond timer jitter on CI runners — it exists
to catch structural regressions (an O(n) copy or per-build revalidation
sneaking into the shim), not to re-measure the margin.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

import xy as fc
import xy.pyplot as plt

_CI_TIMER_JITTER = 100e-6


def _best(fn, reps: int) -> float:
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


@pytest.mark.parametrize(
    "n,reps,ceiling",
    [(10_000, 60, 1.6), (100_000, 30, 1.5)],
)
def test_pyplot_build_tracks_declarative(n: int, reps: int, ceiling: float) -> None:
    rng = np.random.default_rng(0)
    x = np.arange(n, dtype=np.float64)
    y = rng.normal(size=n)

    def declarative() -> None:
        c = fc.chart(fc.line(x=x, y=y, color="#1f77b4"), fc.x_axis(), fc.y_axis())
        c.figure().build_payload(2048)

    def pyplot() -> None:
        plt.close("all")
        _fig, ax = plt.subplots()
        ax.plot(x, y)
        ax._build_chart(640, 480).figure().build_payload(2048)

    declarative(), pyplot()  # warm caches
    d = _best(declarative, reps)
    p = _best(pyplot, reps)
    limit = d * ceiling + _CI_TIMER_JITTER
    assert p <= limit, (
        f"pyplot {p * 1e3:.3f}ms vs declarative {d * 1e3:.3f}ms at n={n}; limit {limit * 1e3:.3f}ms"
    )


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
