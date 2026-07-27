from __future__ import annotations

import warnings

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._ticker import AutoLocator, MaxNLocator


def _auto_ticks_data() -> tuple[np.ndarray, np.ndarray]:
    dots = np.linspace(0.3, 1.2, 10)
    x, y = np.meshgrid(dots, dots)
    return x.ravel(), y.ravel()


def _axis_domains(ax) -> tuple[tuple[float, float], tuple[float, float]]:
    spec, _blob = ax._build_chart(640, 480).figure().build_payload()
    return tuple(spec["x_axis"]["domain"]), tuple(spec["y_axis"]["domain"])


def test_auto_ticks_round_numbers_matches_exact_gallery_domains() -> None:
    x, y = _auto_ticks_data()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        plt.rcParams["axes.autolimit_mode"] = "round_numbers"

    _fig, ax = plt.subplots()
    ax.scatter(x, y, c=x + y)
    x_domain, y_domain = _axis_domains(ax)
    assert x_domain == pytest.approx((0.2, 1.4))
    assert y_domain == pytest.approx((0.2, 1.4))

    _fig, ax = plt.subplots()
    ax.scatter(x, y, c=x + y)
    ax.set_xmargin(0.8)
    assert ax.get_xmargin() == 0.8
    assert ax.get_ymargin() == 0.05
    x_domain, y_domain = _axis_domains(ax)
    assert x_domain == pytest.approx((-0.5, 2.0))
    assert y_domain == pytest.approx((0.2, 1.4))


def test_round_numbers_is_read_at_render_time_and_respects_explicit_limits() -> None:
    x, y = _auto_ticks_data()
    _fig, ax = plt.subplots()
    ax.scatter(x, y)
    ax.set_xlim(0.0, 2.0)

    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        x_domain, y_domain = _axis_domains(ax)

    assert x_domain == (0.0, 2.0)
    assert y_domain == pytest.approx((0.2, 1.4))

    ax.clear()
    ax.scatter(x, y)
    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        x_domain, y_domain = _axis_domains(ax)
    assert x_domain == pytest.approx((0.2, 1.4))
    assert y_domain == pytest.approx((0.2, 1.4))


def test_axis_margin_setters_match_matplotlib_validation_and_clipping() -> None:
    _fig, ax = plt.subplots()
    assert ax.get_xmargin() == 0.05
    assert ax.get_ymargin() == 0.05

    ax.plot([0.0, 10.0], [0.0, 20.0])
    ax.set_xmargin(-0.1)
    ax.set_ymargin(0.25)
    assert ax.get_xlim() == pytest.approx((1.0, 9.0))
    assert ax.get_ylim() == pytest.approx((-5.0, 25.0))

    for value in (-0.5, -1.0, np.inf, np.nan):
        with pytest.raises(ValueError, match=r"greater than -0\.5"):
            ax.set_xmargin(value)


def test_auto_locator_round_view_limits_use_edge_ticks() -> None:
    locator = AutoLocator()
    locator._nbins_hint = 9
    assert locator.view_limits(0.255, 1.245) == pytest.approx((0.255, 1.245))
    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        assert locator.view_limits(0.255, 1.245) == pytest.approx((0.2, 1.4))
        assert locator.view_limits(-0.42, 1.92) == pytest.approx((-0.5, 2.0))


def test_maxn_locator_round_mode_uses_the_same_step_for_ticks_and_limits() -> None:
    locator = MaxNLocator(4)

    np.testing.assert_allclose(locator.tick_values(0.25, 0.35), [0.25, 0.275, 0.3, 0.325, 0.35])
    assert locator.view_limits(0.25, 0.35) == (0.25, 0.35)

    with plt.rc_context({"axes.autolimit_mode": "round_numbers"}):
        np.testing.assert_allclose(locator.tick_values(0.25, 0.35), [0.24, 0.27, 0.3, 0.33, 0.36])
        assert locator.view_limits(0.25, 0.35) == pytest.approx((0.24, 0.36))


@pytest.mark.parametrize("mode", ["data", "round_numbers"])
def test_maxn_locator_expands_singular_and_nonfinite_limits(mode: str) -> None:
    locator = MaxNLocator(4)

    with plt.rc_context({"axes.autolimit_mode": mode}):
        lo, hi = locator.view_limits(2.0, 2.0)
        assert np.isfinite([lo, hi]).all()
        assert lo < 2.0 < hi

        lo, hi = locator.view_limits(np.nan, np.inf)
        assert np.isfinite([lo, hi]).all()
        assert lo < hi

        ticks = locator.tick_values(2.0, 2.0)
        assert len(ticks) >= 2
        assert np.isfinite(ticks).all()
        assert ticks[0] < ticks[-1]


def test_autolimit_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match=r"data.*round_numbers"):
        plt.rcParams["axes.autolimit_mode"] = "rounded"
