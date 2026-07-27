import pytest

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_grid_selects_axis_and_records_supported_style():
    _, ax = plt.subplots()
    ax.grid(True, axis="x", which="major", color="red", linewidth=2, linestyle="--", alpha=0.5)

    x_style = ax._axis_props("x")["style"]
    y_style = ax._axis_props("y")["style"]
    assert ax._grid is True
    assert ax._grid_axis == "x"
    assert x_style["grid_color"] == "red"
    assert x_style["grid_width"] == 2.0
    assert x_style["grid_dash"] == "dashed"
    assert x_style["grid_opacity"] == 0.5
    assert y_style["grid_color"] == "transparent"

    ax.grid(False, axis="y", color="blue")
    assert ax._axis_props("y")["style"]["grid_color"] == "transparent"
    with pytest.raises(ValueError):
        ax.grid(True, axis="z")
    ax.grid(True, which="minor", color="0.9")
    assert ax._axis_props("x")["minor_style"]["grid_color"] == "rgb(230,230,230)"
    assert ax._axis_props("y")["minor_style"]["grid_color"] == "rgb(230,230,230)"
    with pytest.raises(TypeError):
        ax.grid(True, unsupported=True)


def test_grid_linestyle_rcparam_reaches_major_and_minor_payload_styles():
    with plt.rc_context({"axes.grid": True, "grid.linestyle": "--"}):
        _, ax = plt.subplots()
        ax.grid(True, which="minor")

        for axis in ("x", "y"):
            assert ax._axis_props(axis)["style"]["grid_dash"] == "dashed"
            assert ax._axis_props(axis)["minor_style"]["grid_dash"] == "dashed"

        payload = ax._build_chart(640, 480).figure().axis_options
        for axis in ("x", "y"):
            assert payload[axis]["style"]["grid_dash"] == "dashed"
            assert payload[axis]["minor_style"]["grid_dash"] == "dashed"


def test_legend_maps_supported_style_and_rejects_unknown_options():
    _, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], label="line")
    ax.legend(
        loc="upper right",
        ncols=2,
        title="Legend",
        fontsize=13,
        labelcolor="green",
        frameon=True,
        facecolor="white",
        edgecolor="black",
    )

    assert ax._legend is True
    assert ax._legend_options["loc"] == "upper right"
    assert ax._legend_options["ncols"] == 2
    assert ax._legend_options["title"] == "Legend"
    assert ax._legend_options["handlelength"] == 2.0
    assert ax._legend_options["handletextpad"] == 0.8
    assert ax._legend_options["border_pad"] == pytest.approx(0.5 * 13 * 100 / 72)
    assert ax._legend_options["style"] == {
        "fontSize": "18.0556px",
        "color": "green",
        "background": "white",
        "borderColor": "black",
        "borderStyle": "solid",
        "borderWidth": "1px",
        "--xy-legend-frame-alpha": 0.8,
        "padding": "0.4em",
        "rowGap": "0.5em",
    }

    ax.legend(shadow=True, fancybox=True, framealpha=0.8, borderpad=1, labelspacing=0.7)
    style = ax._legend_options["style"]
    assert style["boxShadow"]
    assert style["borderRadius"] == "4px"
    assert style["padding"] == "1em"
    assert style["rowGap"] == "0.7em"

    ax.legend(fontsize=13, borderaxespad=0.75)
    assert ax._legend_options["border_pad"] == pytest.approx(0.75 * 13 * 100 / 72)
    with pytest.raises(ValueError, match="borderaxespad"):
        ax.legend(borderaxespad=-0.1)

    ax.legend(handlelength=4, handletextpad=1.25)
    assert ax._legend_options["handlelength"] == 4.0
    assert ax._legend_options["handletextpad"] == 1.25
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["handlelength"] == 4.0
    assert spec["legend"]["handletextpad"] == 1.25
    with pytest.raises(ValueError, match="handlelength"):
        ax.legend(handlelength=-1)
    with pytest.raises(ValueError, match="handletextpad"):
        ax.legend(handletextpad=float("nan"))


def test_legend_frameoff_maps_to_transparent_style():
    _, ax = plt.subplots()
    ax.plot([0, 1], [1, 2], label="line")
    ax.legend(frameon=False)

    assert ax._legend_options["style"]["background"] == "transparent"
    assert ax._legend_options["style"]["borderColor"] == "transparent"


def test_second_legend_via_add_artist_renders_own_box_with_dash_handles():
    import numpy as np

    from xy.pyplot import Legend

    _, ax = plt.subplots()
    x = np.linspace(0, 10, 200)
    styles = ["-", "--", "-.", ":"]
    lines = []
    for i, sty in enumerate(styles):
        lines += ax.plot(x, np.sin(x - i), sty, color="black")

    # Primary legend restricted to the first two handles.
    ax.legend(lines[:2], ["line A", "line B"], loc="upper right")
    # A manually built Legend for the remaining handles must render separately
    # without leaking its labels into the primary (trace-derived) legend.
    leg = Legend(ax, lines[2:], ["line C", "line D"], loc="lower right")
    assert ax.add_artist(leg) is leg

    spec, _ = ax._build_chart(573, 400).figure().build_payload()
    assert spec["legend"]["loc"] == "upper right"
    assert [item["name"] for item in spec["legend"]["items"]] == ["line A", "line B"]
    extras = spec.get("extra_legends")
    assert extras and len(extras) == 1
    assert extras[0]["loc"] == "lower right"
    names = [it["name"] for it in extras[0]["items"]]
    assert names == ["line C", "line D"]
    # dashdot then dotted patterns survive to the render item.
    dashes = [it["style"].get("dash") for it in extras[0]["items"]]
    assert dashes[0] and len(dashes[0]) == 4  # "-." → [on, off, on, off]
    assert dashes[1] and len(dashes[1]) == 2  # ":" → [on, off]
    # Neither explicit legend mutates trace names.
    named_traces = [t.get("name") for t in spec["traces"] if t.get("name")]
    assert not named_traces


def test_standalone_extra_legend_survives_primary_legend_suppression():
    from xy.pyplot import Legend

    _, ax = plt.subplots()
    line = ax.plot([0, 1], [0, 1], "--", color="red")[0]
    ax.add_artist(Legend(ax, [line], ["only extra"], loc="upper left"))

    spec, _ = ax._build_chart(573, 400).figure().build_payload()
    assert spec["show_legend"] is False
    assert [item["name"] for item in spec["extra_legends"][0]["items"]] == ["only extra"]


def test_standalone_legend_unwraps_errorbar_container():
    from xy.pyplot import Legend

    _, ax = plt.subplots()
    errorbar = ax.errorbar([0, 1], [1, 2], yerr=[0.1, 0.2], fmt="none", color="red")
    ax.add_artist(Legend(ax, [errorbar], ["uncertainty"], loc="upper left"))

    spec, _ = ax._build_chart(573, 400).figure().build_payload()
    assert spec["extra_legends"][0]["items"] == [
        {
            "name": "uncertainty",
            "kind": "line",
            "style": {
                "color": "red",
                "width": pytest.approx(plt.rcParams["lines.linewidth"] * 100.0 / 72.0),
                "opacity": 1.0,
            },
        }
    ]


def test_standalone_legend_preserves_rule_annotation_dash():
    from xy.pyplot import Legend

    _, ax = plt.subplots()
    rule = ax.axvline(0.5, linestyle="--", linewidth=2, color="red")
    ax.add_artist(Legend(ax, [rule], ["rule"], loc="upper left"))

    spec, _ = ax._build_chart(573, 400).figure().build_payload()
    item = spec["extra_legends"][0]["items"][0]
    assert item["style"]["dash"] == [10.2778, 4.4444]


def test_center_band_legend_loc_reaches_spec():
    import numpy as np

    _, ax = plt.subplots()
    x = np.linspace(0, 10, 500)
    # A full-amplitude oscillation leaves every corner busy; matplotlib's "best"
    # parks the legend on the sparse vertical-center band. Matplotlib 3.11.1
    # scores this exact figure center left 20 against center right 36 — a
    # decisive win for the left band, not a tie. This asserted "center right"
    # while the shim compared *mean fractional* occupancy under a 0.02 tie band,
    # which flattened the 20-vs-36 gap into a tie and handed it to the
    # earlier-ordered candidate.
    ax.plot(x, np.sin(x[:, None] + np.pi * np.arange(0, 2, 0.5)))
    ax.legend(["a", "b"])
    spec, _ = ax._build_chart(573, 400).figure().build_payload()
    assert spec["legend"]["loc"] == "center left"


def test_best_legend_materializes_cumulative_histogram_and_ecdf_paths():
    import numpy as np

    np.random.seed(19680801)
    mean = 200
    sigma = 25
    data = np.random.normal(mean, sigma, size=100)
    fig = plt.figure(figsize=(9, 4), layout="constrained")
    axes = fig.subplots(1, 2, sharex=True, sharey=True)

    axes[0].ecdf(data, label="CDF")
    _counts, bins, _patches = axes[0].hist(
        data,
        25,
        density=True,
        histtype="step",
        cumulative=True,
        label="Cumulative histogram",
    )
    x = np.linspace(data.min(), data.max())
    y = (1 / (np.sqrt(2 * np.pi) * sigma)) * np.exp(-0.5 * (1 / sigma * (x - mean)) ** 2)
    y = y.cumsum()
    y /= y[-1]
    axes[0].plot(x, y, "k--", linewidth=1.5, label="Theory")

    axes[1].ecdf(data, complementary=True, label="CCDF")
    axes[1].hist(
        data,
        bins=bins,
        density=True,
        histtype="step",
        cumulative=-1,
        label="Reversed cumulative histogram",
    )
    axes[1].plot(x, 1 - y, "k--", linewidth=1.5, label="Theory")

    for ax in axes:
        ax.legend()
    # These are the gallery's Matplotlib axes dimensions. XY's current
    # constrained-layout fallback produces a narrower panel; that independent
    # layout discrepancy is deliberately not hidden by the scorer.
    locations = [
        ax._best_legend_loc(
            legend_options=ax._legend_options,
            plot_size=(348.75, 308.0),
        )
        for ax in axes
    ]
    assert locations == ["upper left", "lower left"]
