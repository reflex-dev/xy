from __future__ import annotations

import numpy as np

import xy.pyplot as plt
from xy.pyplot._transforms import Affine2D


def test_boxplot_notches_bootstrap_overrides_and_custom_whiskers() -> None:
    np.random.seed(4)
    _, ax = plt.subplots()
    result = ax.boxplot(
        [[1, 2, 3, 4, 40]],
        notch=True,
        usermedians=[2.75],
        conf_intervals=[[2.25, 3.25]],
        whis=(5, 95),
        capwidths=0.2,
        showmeans=True,
    )
    assert all(result[name] for name in ("boxes", "medians", "whiskers", "caps", "means"))
    box_segments = result["boxes"][0]._entry["args"]
    assert len(box_segments[0]) == 10  # notched outline, not a rectangular approximation
    median_segments = result["medians"][0]._entry["args"]
    np.testing.assert_allclose(median_segments[1], [2.75])

    _, bootstrap_ax = plt.subplots()
    bootstrapped = bootstrap_ax.boxplot([[1, 2, 3, 4, 40]], notch=True, bootstrap=1)
    outline = bootstrapped["boxes"][0]._entry["args"]
    assert outline[3][1] == outline[3][3]  # one resample gives a collapsed bootstrap CI


def test_violin_kde_bandwidth_quantiles_and_sides() -> None:
    _, ax = plt.subplots()
    result = ax.violinplot(
        [[0, 0.5, 1, 2]],
        points=41,
        bw_method="silverman",
        quantiles=[[0.25, 0.75]],
        side="low",
    )
    assert "cquantiles" in result
    body = result["bodies"][0]._entry
    x_coordinates = np.concatenate((body["args"][0], body["args"][2], body["args"][4]))
    assert np.max(x_coordinates) <= 1.0  # center is position 1; only the low half is drawn


def test_hexbin_custom_reducer_is_materialized() -> None:
    _, ax = plt.subplots()
    ax.hexbin(
        [0.0, 0.01, 0.02],
        [0.0, 0.01, 0.02],
        C=[1.0, 8.0, 3.0],
        gridsize=4,
        reduce_C_function=np.max,
        mincnt=1,
    )
    trace = ax._build_chart(640, 480).figure().traces[0]
    # every point aggregates, including the one on the domain edge; a mean
    # reducer would produce different values, so this discriminates np.max
    np.testing.assert_allclose(sorted(trace.color_ch.values), [1.0, 3.0, 8.0])


def test_nonlinear_scales_secondary_axes_and_affine_transforms() -> None:
    _, ax = plt.subplots()
    line = ax.plot([-10, -1, 0, 1, 10], [0, 1, 2, 3, 4])[0]
    ax.set_xscale("symlog", linthresh=1)
    adjusted = 1 / (1 - 0.1)
    np.testing.assert_allclose(
        line.get_xdata(), [-(adjusted + 1), -adjusted, 0, adjusted, adjusted + 1]
    )
    np.testing.assert_allclose(ax.get_xlim(), (-16.259646938814825, 16.259646938814825))
    secondary = ax.secondary_xaxis("top", functions=(lambda x: x * 100, lambda x: x / 100))
    secondary.set_xlabel("percent")
    axis = ax._build_chart(640, 480).figure().axis_options["xs1"]
    assert axis["side"] == "top" and axis["tick_labels"][-1] == "1625.96"

    _, transformed = plt.subplots()
    line = transformed.plot([0, 1], [0, 1], transform=Affine2D().translate(2, 3))[0]
    np.testing.assert_allclose(line.get_xdata(), [2, 3])
    line.set_transform(Affine2D().scale(2))
    np.testing.assert_allclose(line.get_xdata(), [0, 2])
