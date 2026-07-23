"""Per-chart LOD tuning: `density_threshold` / `density_sample_target` (§28).

The drill budget (the each-point-rendered threshold) and the hybrid overlay's
base sample size were process-wide config constants; both are now per-trace
tunables on `xy.scatter(...)`, with the config values as defaults. The budget
governs `use_density`, every `density_view` tier decision, the pyramid
margin, `lod_blend` normalization, and the near-boundary sample ramp — and it
ships on the wire (`density.budget`, points-update `budget`) so client-side
heuristics track the override instead of assuming the default.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy
from xy._figure import Figure
from xy.config import (
    DENSITY_SAMPLE_TARGET,
    DIRECT_SOFT_CEILING,
    SCATTER_DENSITY_THRESHOLD,
)


def _xy(n: int, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    return rng.uniform(0, 100, n), rng.uniform(0, 100, n)


# -- tier choice ---------------------------------------------------------------


def test_density_threshold_replaces_auto_tier_choice():
    x, y = _xy(50_000)
    fig = Figure().scatter(x, y, density_threshold=10_000)
    assert fig.traces[0].use_density()  # 50k > 10k: aggregates well below 200k
    assert fig.traces[0].drill_budget() == 10_000

    fig2 = Figure().scatter(x, y, density_threshold=60_000)
    assert not fig2.traces[0].use_density()  # 50k <= 60k: stays direct
    assert fig2.traces[0].drill_budget() == 60_000

    # Defaults unchanged when the knob is not passed.
    fig3 = Figure().scatter(x, y)
    assert fig3.traces[0].drill_budget() == SCATTER_DENSITY_THRESHOLD
    assert fig3.traces[0].sample_target() == DENSITY_SAMPLE_TARGET


def test_density_threshold_replaces_channel_soft_ceiling():
    # A per-point size channel normally keeps direct draw to the 2M ceiling;
    # an explicit threshold governs instead.
    x, y = _xy(50_000)
    size = np.linspace(2, 10, len(x))
    assert not Figure().scatter(x, y, size=size).traces[0].use_density()
    with pytest.warns(RuntimeWarning, match="drops per-point channels"):
        fig = Figure().scatter(x, y, size=size, density_threshold=10_000)
    assert fig.traces[0].use_density()


def test_density_threshold_above_ceiling_warns_like_density_false():
    x, y = _xy(DIRECT_SOFT_CEILING + 1)
    with pytest.warns(RuntimeWarning, match="fill-rate-bound"):
        fig = Figure().scatter(x, y, density_threshold=DIRECT_SOFT_CEILING + 10)
    assert not fig.traces[0].use_density()


# -- density_view / drill ------------------------------------------------------


def test_density_view_drills_at_the_custom_budget():
    n = 50_000
    x, y = _xy(n)
    fig = Figure().scatter(x, y, density_threshold=10_000)
    trace = fig.traces[0]

    # Full view: 50k visible > 10k budget -> density, budget on the wire.
    update, _ = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 320, 240)
    tr = update["traces"][0]
    assert tr["mode"] == "density"
    assert tr["density"]["budget"] == 10_000

    # A ~16%-area window (~8k visible) fits the 10k budget -> exact points,
    # where the stock 200k budget would never have drilled this trace at all.
    upd, bufs = fig.density_view(0, 0.0, 40.0, 0.0, 40.0, 320, 240)
    tr = upd["traces"][0]
    inwin = int(np.sum((x >= 0) & (x <= 40) & (y >= 0) & (y <= 40)))
    assert 0 < inwin <= 10_000
    assert tr["mode"] == "points"
    assert tr["visible"] == inwin
    assert tr["budget"] == 10_000
    # The handoff blend normalizes against the trace's own budget.
    assert tr["lod_blend"] == pytest.approx(inwin / 10_000)
    assert trace.drill_mode is True


def test_density_sample_target_sets_the_overlay_floor_and_ramp_cap():
    n = 50_000
    x, y = _xy(n)
    fig = Figure().scatter(x, y, density_threshold=2_000, density_sample_target=500)
    update, buffers = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 320, 240)
    sample = update["traces"][0]["density"]["sample"]
    # 50k visible with a 2k budget: the ramp (budget^2/visible = 80) sits
    # below the trace's own 500 floor, so the floor governs.
    assert sample["target"] == 500
    assert 0 < sample["n"] <= int(500 * 1.3)

    # Near the boundary the ramp tops out at the trace's budget, not 200k.
    upd2, _ = fig.density_view(0, 0.0, 22.0, 0.0, 22.0, 320, 240)
    tr2 = upd2["traces"][0]
    if tr2["mode"] == "density":  # ~2.4k visible, just over the 2k budget
        assert 500 <= tr2["density"]["sample"]["target"] <= 2_000


def test_initial_payload_ships_custom_budget_and_sample_target():
    n = 30_000
    x, y = _xy(n)
    fig = Figure().scatter(x, y, density=True, density_threshold=5_000, density_sample_target=750)
    spec, _ = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["tier"] == "density"
    assert tr["density"]["budget"] == 5_000
    sample = tr["density"]["sample"]
    # 30k visible, 5k budget: ramp = 834, above the 750 floor.
    assert sample["target"] == 834
    assert 0 < sample["n"] <= int(834 * 1.3)


# -- composition API pass-through ----------------------------------------------


def test_composed_scatter_passes_density_tuning_through():
    x, y = _xy(30_000)
    chart = xy.scatter_chart(
        xy.scatter(x, y, density_threshold=4_000, density_sample_target=600),
        xy.x_axis(),
        xy.y_axis(),
    )
    trace = chart.figure().traces[0]
    assert trace.density_threshold == 4_000
    assert trace.density_sample_target == 600
    assert trace.use_density()  # 30k > 4k


@pytest.mark.parametrize(
    "kwargs",
    [
        {"density_threshold": 0},
        {"density_threshold": -5},
        {"density_threshold": True},
        {"density_sample_target": 0},
        {"density_sample_target": 2.5},
    ],
)
def test_density_tuning_rejects_non_positive_ints(kwargs):
    x, y = _xy(100)
    with pytest.raises(ValueError, match="density_threshold|density_sample_target"):
        Figure().scatter(x, y, **kwargs)


def test_bad_density_tuning_does_not_add_a_trace():
    x, y = _xy(100)
    fig = Figure()
    with pytest.raises(ValueError):
        fig.scatter(x, y, density_threshold=-1)
    assert fig.traces == []
