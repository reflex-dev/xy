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
    with pytest.raises(ValueError):
        ax.grid(True, which="minor")
    with pytest.raises(TypeError):
        ax.grid(True, unsupported=True)


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
    assert ax._legend_options["style"] == {
        "fontSize": "18.0556px",
        "color": "green",
        "background": "white",
        "borderColor": "black",
        "borderStyle": "solid",
        "--xy-legend-frame-alpha": 0.8,
    }

    ax.legend(shadow=True, fancybox=True, framealpha=0.8, borderpad=1, labelspacing=0.7)
    style = ax._legend_options["style"]
    assert style["boxShadow"]
    assert style["borderRadius"] == "4px"
    assert style["padding"] == "1em"
    assert style["rowGap"] == "0.7em"


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
    extras = spec.get("extra_legends")
    assert extras and len(extras) == 1
    assert extras[0]["loc"] == "lower right"
    names = [it["name"] for it in extras[0]["items"]]
    assert names == ["line C", "line D"]
    # dashdot then dotted patterns survive to the render item.
    dashes = [it["style"].get("dash") for it in extras[0]["items"]]
    assert dashes[0] and len(dashes[0]) == 4  # "-." → [on, off, on, off]
    assert dashes[1] and len(dashes[1]) == 2  # ":" → [on, off]
    # The primary legend must not have acquired the second legend's labels.
    named_traces = [t.get("name") for t in spec["traces"] if t.get("name")]
    assert "line C" not in named_traces and "line D" not in named_traces


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
            "style": {"color": "red", "width": pytest.approx(1.6666666667), "opacity": 1.0},
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


def test_center_right_legend_loc_reaches_spec():
    import numpy as np

    _, ax = plt.subplots()
    x = np.linspace(0, 10, 500)
    # A full-amplitude oscillation leaves every corner busy; matplotlib's "best"
    # parks the legend on the sparse vertical-center band.
    ax.plot(x, np.sin(x[:, None] + np.pi * np.arange(0, 2, 0.5)))
    ax.legend(["a", "b"])
    spec, _ = ax._build_chart(573, 400).figure().build_payload()
    assert spec["legend"]["loc"] == "center right"
