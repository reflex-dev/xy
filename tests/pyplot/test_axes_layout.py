from __future__ import annotations

import builtins

import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def _axis_child(ax, which: str):
    chart = ax._build_chart(640, 480)
    return next(child for child in chart.children if getattr(child, "which", None) == which)


def test_get_position_is_dependency_free_and_set_position_preserves_bounds(monkeypatch) -> None:
    real_import = builtins.__import__

    def no_matplotlib(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    _fig, ax = plt.subplots()
    monkeypatch.setattr(builtins, "__import__", no_matplotlib)

    default = ax.get_position()
    assert default.bounds == (0.125, 0.11, 0.775, 0.77)
    assert (default.x0, default.y0, default.x1, default.y1) == (0.125, 0.11, 0.9, 0.88)

    ax.set_position([0.2, 0.3, 0.4, 0.5])

    moved = ax.get_position()
    assert moved.bounds == (0.2, 0.3, 0.4, 0.5)
    assert ax._figure_rect == (0.2, 0.3, 0.4, 0.5)


def test_margins_expand_only_automatic_domains() -> None:
    _fig, ax = plt.subplots()
    ax.plot([10.0, 20.0], [100.0, 140.0])

    ax.margins(x=0.1, y=0.25)

    assert ax.get_xlim() == (9.0, 21.0)
    assert ax.get_ylim() == (90.0, 150.0)
    assert _axis_child(ax, "x").domain == (9.0, 21.0)
    assert _axis_child(ax, "y").domain == (90.0, 150.0)

    ax.set_xlim(0.0, 1.0)
    ax.margins(x=0.5)

    assert ax.get_xlim() == (0.0, 1.0)


def test_axis_tight_sets_data_domains_and_equal_expands_to_panel_ratio() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 2.0], [0.0, 1.0])

    assert ax.axis("tight") == pytest.approx((-0.1, 2.1, -0.05, 1.05))
    assert ax._axis["x"]["domain"] == pytest.approx((-0.1, 2.1))
    assert ax._axis["y"]["domain"] == pytest.approx((-0.05, 1.05))

    ax.axis("equal")
    x_axis = _axis_child(ax, "x")
    y_axis = _axis_child(ax, "y")

    assert x_axis.domain == pytest.approx((-0.1, 2.1))
    assert y_axis.domain[0] < -0.05
    assert y_axis.domain[1] > 1.05


def test_axis_tight_honors_configured_margins() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [-1.0, 1.0])
    ax.margins(x=0.1, y=0.25)

    assert ax.axis("tight") == pytest.approx((-1.0, 11.0, -1.5, 1.5))


@pytest.mark.parametrize("mode", ["auto", "equal", "scaled", "image"])
def test_axis_autoscale_and_aspect_modes_start_from_padded_limits(mode: str) -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 2.0], [0.0, 1.0])

    assert ax.axis(mode) == pytest.approx((-0.1, 2.1, -0.05, 1.05))
    assert ax._aspect_equal is (mode != "auto")


def test_axis_square_matches_matplotlib_limit_contract() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 2.0], [0.0, 1.0])

    assert ax.axis("square") == pytest.approx((-0.1, 2.1, -0.05, 2.15))
    assert ax._aspect_equal
    assert ax._absolute_plot_ratio == 1.0
    assert ax.get_position().bounds == pytest.approx((0.22375, 0.11, 0.5775, 0.77))


@pytest.mark.parametrize("mode", ["scaled", "image"])
def test_axis_adjustable_box_modes_match_matplotlib_position(mode: str) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.plot([0.0, 2.0], [0.0, 1.0])

    ax.axis(mode)
    ax._build_chart(*fig._panel_px())

    assert ax.get_xlim() == pytest.approx((-0.1, 2.1))
    assert ax.get_ylim() == pytest.approx((-0.05, 1.05))
    assert ax.get_position().bounds == pytest.approx((0.125, 0.2366666667, 0.775, 0.5166666667))


def test_axis_boolean_case_insensitive_and_keyword_forms() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 2.0], [0.0, 1.0])

    ax.axis(False)
    assert ax._axis_props("x")["tick_label_strategy"] == "none"
    ax.axis("ON")
    assert ax._axis_props("x")["tick_label_strategy"] is None
    assert ax.axis(xmin=-3.0, ymax=4.0) == pytest.approx((-3.0, 2.1, -0.05, 4.0))

    with pytest.raises(TypeError, match="unexpected keyword"):
        ax.axis(zmin=0.0)
    with pytest.raises(TypeError, match="xmin, xmax, ymin, ymax"):
        ax.axis([0.0, 1.0])


def test_default_auto_tick_density_matches_matplotlib_tick_space() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.plot([0.0, 10.0], [-1.0, 1.0])

    chart = ax._build_chart(558, 418)
    axes = {child.which: child for child in chart.children if hasattr(child, "which")}

    assert axes["x"].tick_count == 9
    assert axes["y"].tick_count == 9


def test_auto_tick_density_reduces_for_shorter_axes() -> None:
    fig, ax = plt.subplots(figsize=(4.0, 3.0), dpi=100)
    ax.plot([0.0, 10.0], [-1.0, 1.0])
    ax._padding = [14.0, 19.0, 34.0, 43.0]

    chart = ax._build_chart(372, 279)
    axes = {child.which: child for child in chart.children if hasattr(child, "which")}

    assert axes["x"].tick_count == 7
    assert axes["y"].tick_count == 8


def test_tick_params_records_supported_style_and_rejects_unknown() -> None:
    _fig, ax = plt.subplots()

    ax.tick_params(
        axis="x",
        labelrotation=45,
        colors="tab:red",
        length=7,
        width=2,
        direction="in",
        labelbottom=False,
    )

    x_axis = _axis_child(ax, "x")
    assert x_axis.tick_label_angle == 45.0
    assert x_axis.tick_label_strategy == "off"  # labels hidden, ticks/baselines kept
    assert x_axis.style == {
        "axis_width": pytest.approx(0.8 * 4.0 / 3.0),
        "tick_color": "#d62728",
        "tick_label_color": "#d62728",
        "tick_length": pytest.approx(7.0 * 4.0 / 3.0),
        "tick_width": pytest.approx(2.0 * 4.0 / 3.0),
        "tick_direction": "in",
    }

    with pytest.raises(TypeError, match="unsupported keyword"):
        ax.tick_params(which="minor")


def test_axes_set_rejects_unknown_properties_after_applying_known_setters() -> None:
    _fig, ax = plt.subplots()

    with pytest.raises(AttributeError, match="unsupported property"):
        ax.set(xlabel="time", ylabel="value", made_up=True)

    assert ax._axis["x"]["label"] == "time"
    assert ax._axis["y"]["label"] == "value"


def test_set_anchor_accepts_mpl_anchor_codes_and_rejects_unknown() -> None:
    _fig, ax = plt.subplots()

    ax.set_anchor("SW")
    assert ax._anchor == "SW"

    with pytest.raises(ValueError, match="unsupported anchor"):
        ax.set_anchor("baseline")
