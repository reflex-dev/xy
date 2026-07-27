from __future__ import annotations

import builtins

import pytest
from tests.svg_test_utils import tick_label_positions

import xy.pyplot as plt
from xy._svg import layout


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
    # Resolved through the gridspec now that get_position() is grid-aware, so
    # the bottom edge carries matplotlib's own 0.88 - 0.77 rounding.
    assert default.bounds == pytest.approx((0.125, 0.11, 0.775, 0.77))
    assert (default.x0, default.y0, default.x1, default.y1) == pytest.approx(
        (0.125, 0.11, 0.9, 0.88)
    )

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
    figure = ax._build_chart(640, 480).figure()
    assert figure.x_range() == (9.0, 21.0)
    assert figure.y_range() == (90.0, 150.0)

    ax.set_xlim(0.0, 1.0)
    ax.margins(x=0.5)

    assert ax.get_xlim() == (0.0, 1.0)


def test_negative_margins_shrink_the_rendered_domain() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0.0, 10.0], [100.0, 140.0])

    ax.margins(x=-0.1, y=-0.25)

    assert ax.get_xlim() == (1.0, 9.0)
    assert ax.get_ylim() == (110.0, 130.0)
    figure = ax._build_chart(640, 480).figure()
    assert figure.x_range() == (1.0, 9.0)
    assert figure.y_range() == (110.0, 130.0)


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
    # axis("equal") uses adjustable='datalim': preserve the ordinary panel
    # rectangle and expand y until x/y data units have the same pixel scale.
    # The expansion now solves over the *matplotlib* axes rectangle
    # (0.775 x 0.77 of 640x480), so these are Matplotlib 3.11's own limits for
    # this figure rather than the ones implied by the old label-aware margins.
    assert y_axis.domain == pytest.approx((-0.31967741935483873, 1.3196774193548388))
    assert ax.get_position().bounds == pytest.approx((0.125, 0.11, 0.775, 0.77))


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

    ax.xaxis.set_visible(False)
    ax.axis(False)
    assert ax.axison is False
    # Matplotlib's axison flag overrides individual component visibility only
    # while it is off; it does not overwrite that state.
    assert ax._axis_props("x")["tick_label_strategy"] == "none"
    assert ax._axis_props("y").get("tick_label_strategy") is None
    off_spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert off_spec["frame_sides"] == []
    assert off_spec["x_axis"]["tick_label_strategy"] == "none"
    assert off_spec["y_axis"]["tick_label_strategy"] == "none"
    ax.axis("ON")
    assert ax.axison is True
    assert ax._axis_props("x")["tick_label_strategy"] == "none"
    assert ax._axis_props("y").get("tick_label_strategy") is None
    on_spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert on_spec["frame_sides"] == ["left", "bottom", "top", "right"]
    assert on_spec["x_axis"]["tick_label_strategy"] == "none"
    assert on_spec["y_axis"].get("tick_label_strategy") is None
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
        pad=6,
        width=2,
        direction="in",
        labelbottom=False,
    )

    x_axis = _axis_child(ax, "x")
    assert x_axis.tick_label_angle == 45.0
    assert x_axis.tick_label_strategy == "off"  # labels hidden, ticks/baselines kept
    assert x_axis.style == {
        "axis_width": pytest.approx(0.8 * 100.0 / 72.0),
        "tick_color": "#d62728",
        "tick_label_color": "#d62728",
        "tick_length": pytest.approx(7.0 * 100.0 / 72.0),
        "tick_padding": pytest.approx(6.0 * 100.0 / 72.0),
        "tick_width": pytest.approx(2.0 * 100.0 / 72.0),
        "tick_direction": "in",
        # Always explicit (10 pt font.size at dpi 100): the render client and
        # static exporters otherwise fall back to their own 11 px default.
        "tick_label_size": pytest.approx(10.0 * 100.0 / 72.0),
        "label_size": pytest.approx(10.0 * 100.0 / 72.0),
    }

    with pytest.raises(TypeError, match="unsupported keyword"):
        ax.tick_params(which="minor")


def test_rc_tick_padding_places_labels_by_the_matplotlib_rule() -> None:
    """The shim always supplies `{x,y}tick.major.size` and `.pad` from rcParams,
    so its tick labels follow matplotlib's geometry rule — padding measured from
    the outward end of the tick mark — instead of core's flat per-side gaps for
    charts that author no tick styling. The two regimes must stay
    distinguishable; `tests/test_svg_export.py` pins the core side of the seam.
    """
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 0.5])
    ax.set_xticks([0.0, 1.0, 2.0])
    ax.set_yticks([0.0, 0.5, 1.0])

    chart = ax._build_chart(400, 300)
    plot = layout(chart.figure().build_payload()[0])[3]
    labels = tick_label_positions(chart.to_svg())

    scale = 100.0 / 72.0  # figure.dpi 100: points -> px
    # 3.5 pt outward tick + 3.5 pt pad, then 0.8 * the 10 pt label font.
    x_gap = (3.5 + 3.5 + 0.8 * 10.0) * scale
    assert x_gap == pytest.approx(20.83, abs=0.01)
    assert labels["1"][1] == pytest.approx(plot["y"] + plot["h"] + x_gap, abs=0.01)
    assert x_gap > 16.0  # an unstyled core chart's flat bottom gap

    y_gap = (3.5 + 3.5) * scale
    assert y_gap == pytest.approx(9.72, abs=0.01)
    assert labels["0.5"][0] == pytest.approx(plot["x"] - y_gap, abs=0.01)
    assert y_gap > 8.0  # an unstyled core chart's flat y gap


def test_tick_params_pad_moves_the_labels_further_from_the_spine() -> None:
    """`tick_params(pad=)` overrides the rc pad in the same geometry."""
    _fig, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 0.5])
    ax.set_yticks([0.0, 0.5, 1.0])
    ax.tick_params(axis="y", pad=12)

    chart = ax._build_chart(400, 300)
    plot = layout(chart.figure().build_payload()[0])[3]
    labels = tick_label_positions(chart.to_svg())

    scale = 100.0 / 72.0
    assert labels["0.5"][0] == pytest.approx(plot["x"] - (3.5 + 12.0) * scale, abs=0.01)


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
