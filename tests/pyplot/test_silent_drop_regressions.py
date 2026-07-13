"""Regressions from the adversarial completion review: values that previously
crashed, were silently dropped, or bypassed validation must now behave."""

import warnings

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._colors import Cmap


def teardown_function():
    plt.close("all")
    plt.rcdefaults()


def test_legend_prop_dict_maps_size_and_rejects_other_font_properties():
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")

    ax.legend(prop={"size": 8})
    assert ax._legend_options["style"]["fontSize"] == "8px"

    with pytest.raises(NotImplementedError):
        ax.legend(prop={"family": "serif"})


def test_zero_marker_edge_width_and_size_are_not_treated_as_unset():
    _, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], "o", mec="black", mew=0)
    assert line._entry["kwargs"]["stroke_width"] == 0.0

    collection = ax.scatter([0, 1], [0, 1], edgecolors="black", linewidths=0)
    assert collection._entry["kwargs"]["stroke_width"] == 0.0


def test_text_visibility_and_alpha_reach_rendered_output():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    text = ax.text(0.5, 0.5, "SECRET")

    text.set_visible(False)
    svg = ax._build_chart(640, 480).figure().to_svg()
    assert "SECRET" not in svg

    text.set_visible(True)
    text.set_alpha(0.5)
    ax._chart = None
    svg = ax._build_chart(640, 480).figure().to_svg()
    assert "SECRET" in svg
    assert 'fill-opacity="0.5"' in svg


def test_set_visible_true_on_visible_artist_preserves_alpha():
    _, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    line.set_alpha(0.5)
    line.set_visible(True)  # no-op in matplotlib; must not clobber alpha
    assert line.get_alpha() == 0.5

    line.set_alpha(0.3)
    line.set_visible(False)
    assert line.get_alpha() == 0.3
    line.set_visible(True)
    assert line._entry["kwargs"]["opacity"] == 0.3


def test_set_rasterized_true_fails_loudly():
    _, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1])
    with pytest.raises(NotImplementedError):
        line.set_rasterized(True)
    line.set_rasterized(False)
    assert line.get_rasterized() is False


def test_hist_stepfilled_produces_filled_step_geometry():
    _, ax = plt.subplots()
    counts, edges, _ = ax.hist([0, 1, 1, 2, 2, 2], bins=3, histtype="stepfilled")

    entry = ax._entries[-1]
    assert entry["kind"] == "@mark"
    assert entry["factory"] == "area"
    xs, tops = entry["args"]
    np.testing.assert_allclose(xs, np.repeat(edges, 2)[1:-1])
    np.testing.assert_allclose(tops, np.repeat(counts, 2))


def test_scatter_one_sided_vmin_vmax_autoscale_the_other_side():
    _, ax = plt.subplots()
    low = ax.scatter([0, 1, 2], [0, 1, 2], c=[1.0, 5.0, 9.0], vmin=2.0)
    assert low._entry["kwargs"]["domain"] == (2.0, 9.0)

    high = ax.scatter([0, 1, 2], [0, 1, 2], c=[1.0, 5.0, 9.0], vmax=6.0)
    assert high._entry["kwargs"]["domain"] == (1.0, 6.0)


def test_clear_reapplies_current_rc_chrome_not_just_prop_cycle():
    with plt.rc_context({"axes.facecolor": "#102030", "font.size": 20.0}):
        _, ax = plt.subplots()
        ax.cla()
        assert ax._theme_tokens["plot_background"] == "#102030"
        assert ax._theme_style["font-size"] == "20px"


def test_auto_ticks_report_exporter_locations_instead_of_empty():
    _, ax = plt.subplots()
    ax.plot([0, 10], [0, 100])
    np.testing.assert_allclose(ax.get_xticks(), [0.0, 2.0, 4.0, 6.0, 8.0, 10.0])

    ax.set_yscale("log")
    ax.set_ylim(1, 1000)
    ticks = ax.get_yticks()
    assert ticks[0] == 1.0 and ticks[-1] == 1000.0 and len(ticks) > 2

    ax.set_xticks([1.0, 5.0])
    np.testing.assert_allclose(ax.get_xticks(), [1.0, 5.0])


def test_savefig_without_extension_defaults_to_png(tmp_path):
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fig.savefig(tmp_path / "noext")
    data = (tmp_path / "noext.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_rc_update_paths_enforce_the_same_validation_as_setitem():
    with pytest.raises(NotImplementedError), plt.rc_context({"axes.spines.left": False}):
        pass
    with pytest.raises(NotImplementedError):
        plt.style.use({"axes.spines.top": True})

    plt.style.use({"font.size": "14"})
    assert plt.rcParams["font.size"] == 14.0

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with plt.rc_context({"lines.antialiased": True}):
            pass
    assert any("lines.antialiased" in str(item.message) for item in caught)


def test_rcdefaults_is_immune_to_list_default_mutation():
    plt.rcParams["font.family"].append("Comic Sans")
    plt.rcdefaults()
    assert plt.rcParams["font.family"] == ["sans-serif"]


def test_cmap_extremes_accept_tuple_colors_in_call_and_imshow_paths():
    cmap = Cmap("viridis")
    cmap.set_bad((1.0, 0.0, 0.0))
    cmap.set_under((0.0, 1.0, 0.0), alpha=0.5)
    cmap.set_over(("red", 0.25))

    rgba = cmap(np.array([np.nan, -1.0, 2.0]))
    np.testing.assert_allclose(rgba[0], [1.0, 0.0, 0.0, 1.0])
    np.testing.assert_allclose(rgba[1], [0.0, 1.0, 0.0, 0.5])
    np.testing.assert_allclose(rgba[2], [1.0, 0.0, 0.0, 0.25])

    _, ax = plt.subplots()
    grid = np.array([[0.0, 1.0], [np.nan, 0.5]])
    image = ax.imshow(grid, cmap=cmap.with_extremes(bad=(0.0, 0.0, 1.0)))
    assert image is not None
