"""Regressions from the adversarial completion review: values that previously
crashed, were silently dropped, or bypassed validation must now behave."""

import ast
import warnings
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._colors import Cmap


def test_public_adapters_cannot_discard_parameters_without_an_explicit_marker():
    """Mechanical guard against newly accepted-and-dropped kwargs.

    A deliberate compatibility no-op must carry an inline ``compat-noop:``
    explanation. Bare ``kwargs.pop`` calls and deleting named public method
    parameters otherwise fail automatically; no hand-maintained keyword list
    is involved.
    """
    root = Path(__file__).resolve().parents[2] / "python" / "xy" / "pyplot"
    violations = []
    for path in root.glob("*.py"):
        source = path.read_text()
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        ):
            parameters = {
                arg.arg
                for arg in (
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                )
            }
            for node in ast.walk(function):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    marked = "compat-noop:" in lines[node.lineno - 1]
                    call = node.value
                    if (
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr == "pop"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id in {"kwargs", "options"}
                        and not marked
                    ):
                        violations.append(
                            f"{path.name}:{node.lineno} bare {call.func.value.id}.pop"
                        )
                if isinstance(node, ast.Delete):
                    marked = "compat-noop:" in lines[node.lineno - 1]
                    discarded = {
                        target.id for target in node.targets if isinstance(target, ast.Name)
                    } & parameters
                    if discarded and not marked:
                        violations.append(f"{path.name}:{node.lineno} deletes {sorted(discarded)}")
    assert not violations, "unexplained accepted-and-dropped options:\n" + "\n".join(violations)


def teardown_function():
    plt.close("all")
    plt.rcdefaults()


def test_legend_prop_dict_maps_size_and_rejects_other_font_properties():
    _, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")

    ax.legend(prop={"size": 8})
    assert ax._legend_options["style"]["fontSize"] == "10.6667px"

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
        assert ax._theme_style["font-size"] == "26.6667px"


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
    with plt.rc_context({"axes.spines.left": False, "axes.spines.top": True}):
        assert plt.rcParams["axes.spines.left"] is False
    with pytest.raises(ValueError, match="boolean"):
        plt.style.use({"axes.spines.top": "yes"})

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


def test_set_cmap_validates_and_feeds_default_colormaps():
    with pytest.raises(ValueError, match="unsupported colormap"):
        plt.set_cmap("notacmap")
    plt.set_cmap("magma")
    _, ax = plt.subplots()
    ax.imshow(np.arange(9.0).reshape(3, 3))
    assert ax._entries[-1]["kwargs"]["colormap"] == "magma"
    ax.scatter([1, 2, 3], [1, 2, 3], c=[0.1, 0.5, 0.9])
    assert ax._entries[-1]["kwargs"]["colormap"] == "magma"


def test_imsave_normalizes_before_quantizing():
    import io

    data = np.linspace(1000.0, 2000.0, 64).reshape(8, 8)
    buffer = io.BytesIO()
    plt.imsave(buffer, data, cmap="viridis")
    buffer.seek(0)
    pixels = plt.imread(buffer)
    # quantize-then-normalize collapsed this ramp to one uniform color
    assert len(np.unique(pixels.reshape(-1, pixels.shape[-1]), axis=0)) > 30


def test_scatter_drops_rows_masked_in_x_y_or_s():
    _, ax = plt.subplots()
    x = np.ma.masked_array([1.0, 2.0, 3.0, 4.0], mask=[False, True, False, False])
    y = np.ma.masked_array([1.0, 2.0, 3.0, 4.0], mask=[False, False, True, False])
    ax.scatter(x, y)
    assert len(np.asarray(ax._entries[-1]["x"])) == 2
    sizes = np.ma.masked_array([10.0, 20.0, 30.0], mask=[False, True, False])
    ax.scatter([1, 2, 3], [1, 2, 3], s=sizes)
    assert len(np.asarray(ax._entries[-1]["x"])) == 2


def test_fill_between_interpolate_draws_single_point_regions():
    x = np.array([0.0, 1.0, 2.0])
    y1 = np.array([-3.0, 1.0, -1.0])
    _, ax = plt.subplots()
    ax.fill_between(x, y1, 0.0, where=y1 > 0, interpolate=True)
    visible = [
        entry for entry in ax._entries if not np.all(np.isnan(np.asarray(entry["y"], dtype=float)))
    ]
    assert len(visible) == 1
    # matplotlib's wedge for this input crosses zero at x=0.75 and x=1.5
    np.testing.assert_allclose(sorted(np.asarray(visible[0]["x"], dtype=float)), [0.75, 1.0, 1.5])


def test_fill_betweenx_data_keys_resolve():
    _, ax = plt.subplots()
    ax.fill_betweenx("a", "b", data={"a": [0.0, 1.0, 2.0], "b": [1.0, 2.0, 3.0]})
    assert len(ax._entries) == 1


def test_savefig_svg_and_html_honor_facecolor_and_single_chart_suptitle():
    import io

    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    fig.suptitle("SoloTitle")
    svg = io.BytesIO()
    fig.savefig(svg, format="svg", facecolor="red")
    assert b"SoloTitle" in svg.getvalue()
    assert b'<rect width="100%" height="100%" fill="red"/>' in svg.getvalue()
    html_out = io.BytesIO()
    fig.savefig(html_out, format="html", facecolor="red")
    assert b"background-color:red" in html_out.getvalue()
    with pytest.raises(NotImplementedError):
        fig.savefig(io.BytesIO(), format="html", metadata={"Title": "x"})
    with pytest.raises(ValueError, match="Latin-1"):
        fig.savefig(io.BytesIO(), format="png", metadata={"键": "v"})


def test_boxplot_component_styles_and_sym_are_honored_or_rejected():
    _, ax = plt.subplots()
    with pytest.raises(NotImplementedError, match="linestyle"):
        ax.boxplot([[1.0, 2.0, 3.0, 4.0]], medianprops={"linestyle": "--"})
    # empty sym suppresses fliers like matplotlib
    data = [[1.0, 2.0, 3.0, 4.0, 50.0]]
    result = ax.boxplot(data, sym="")
    assert result["fliers"] == []
    # a fmt sym styles the fliers instead of vanishing
    result = ax.boxplot(data, sym="r+")
    assert result["fliers"]
    flier_kwargs = result["fliers"][0]._entry["kwargs"]
    assert flier_kwargs["color"] != result["boxes"][0]._entry["kwargs"].get("color")
    # flierprops face color reaches the drawn dots
    result = ax.boxplot(data, flierprops={"markerfacecolor": "#00ff00"}, notch=True)
    assert result["fliers"][0]._entry["kwargs"]["color"] == "#00ff00"


def test_boxplot_usermedians_keep_data_derived_notches():
    values = np.asarray([1.0, 2.0, 2.5, 3.0, 4.0])
    _, ax = plt.subplots()
    result = ax.boxplot([values], notch=True, usermedians=[10.0])
    outline = result["boxes"][0]._entry["args"]
    ys = np.concatenate([np.asarray(outline[1]), np.asarray(outline[3])])
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    delta = 1.57 * (q3 - q1) / np.sqrt(len(values))
    assert np.isclose(ys, med - delta).any() and np.isclose(ys, med + delta).any()
    assert not np.isclose(ys, 10.0 - delta).any()


def test_violinplot_constant_data_draws_without_crashing():
    _, ax = plt.subplots()
    result = ax.violinplot([[3.0, 3.0]], bw_method="scott")
    assert len(result["bodies"]) == 1


def test_secondary_axis_set_ticks_rejects_unknown_options():
    _, ax = plt.subplots()
    ax.plot([0.0, 1.0], [0.0, 1.0])
    secondary = ax.secondary_xaxis("top")
    with pytest.raises(TypeError):
        secondary.set_ticks([0.0, 0.5], minor=True)


def test_logit_scale_masks_domain_edges_instead_of_inf():
    _, ax = plt.subplots()
    ax.plot([0.0, 1.0, 2.0], [0.0, 0.5, 1.0])
    ax.set_yscale("logit")
    values = np.asarray(ax._entries[0]["y"], dtype=float)
    assert not np.isinf(values).any()
    lo, hi = ax.get_ylim()
    assert np.isfinite([lo, hi]).all()


def test_nonlinear_scale_ticks_follow_new_data():
    _, ax = plt.subplots()
    ax.plot([0.0, 1.0], [-1.0, 1.0])
    ax.set_yscale("symlog")
    ax.plot([0.0, 1.0], [-1000.0, 1000.0])
    ticks = ax.get_yticks()
    assert ticks.min() <= -100.0 and ticks.max() >= 100.0
    # explicit ticks win and stay labeled in data units
    ax.set_yticks([-100.0, 0.0, 100.0])
    assert ax._axis_props("y")["tick_labels"] == ["-100", "0", "100"]
    # returning to linear drops the generated ticks
    other = plt.figure().add_subplot(111)
    other.plot([0.0, 1.0], [-1000.0, 1000.0])
    other.set_yscale("symlog")
    other.set_yscale("linear")
    assert "tick_values" not in other._axis_props("y")


def test_data_artists_reject_fraction_space_transforms():
    _, ax = plt.subplots()
    with pytest.raises(NotImplementedError, match="transAxes"):
        ax.plot([0.25, 0.75], [0.5, 0.5], transform=ax.transAxes)


def test_set_transform_rejects_singular_matrices_immediately():
    from xy.pyplot._transforms import Affine2D

    _, ax = plt.subplots()
    (line,) = ax.plot([0.0, 1.0], [0.0, 1.0])
    with pytest.raises(ValueError, match="invertible"):
        line.set_transform(Affine2D(np.zeros((3, 3))))
