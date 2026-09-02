"""P1 audit fixes: legend keyword/loc forms and proxy handles (E), accepted
Artist-level keywords (F), partial ``subplot(n, m, i)`` grids (G), and the
commonly rejected kwargs / missing attributes (H).

Where the semantics are "match Matplotlib", the expected values are taken
from Matplotlib 3.11 and asserted against it too when it is installed.
"""

from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._translate import ARTIST_KWARG_KEEP, ARTIST_KWARG_METHODS, ARTIST_NOOP_KWARGS

INVENTORY = Path(__file__).with_name("matplotlib_311_plotting.json")

# Matplotlib's ``Legend.codes`` (index = numeric loc code).
LEGEND_CODES = (
    "best",
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "right",
    "center left",
    "center right",
    "lower center",
    "upper center",
    "center",
)


def _matplotlib():
    return pytest.importorskip("matplotlib")


def _svg(fig) -> str:
    target = BytesIO()
    fig.savefig(target, format="svg")
    return target.getvalue().decode()


# --- E: legend keyword forms, loc codes, proxy handles -----------------------


def test_legend_keyword_handles_and_labels_match_positional_form() -> None:
    _fig, ax = plt.subplots()
    (a,) = ax.plot([0, 1], [0, 1], label="a")
    (b,) = ax.plot([0, 1], [1, 0], label="b")
    positional = ax.legend([a, b], ["A", "B"]).spec()["items"]
    keyword = ax.legend(handles=[a, b], labels=["A", "B"]).spec()["items"]
    assert [item["name"] for item in keyword] == ["A", "B"]
    assert keyword == positional


def test_legend_handles_only_reads_labels_off_the_handles() -> None:
    _fig, ax = plt.subplots()
    (hidden,) = ax.plot([0, 1], [0, 1], label="_hidden")
    (shown,) = ax.plot([0, 1], [1, 0], label="shown")
    names = [item["name"] for item in ax.legend(handles=[hidden, shown]).spec()["items"]]
    # Matplotlib keeps underscore labels when the handles are given explicitly.
    assert names == ["_hidden", "shown"]
    mpl = _matplotlib()
    mpl.use("Agg")
    import matplotlib.pyplot as mplt

    mfig, max_ = mplt.subplots()
    (mh,) = max_.plot([0, 1], [0, 1], label="_hidden")
    (ms,) = max_.plot([0, 1], [1, 0], label="shown")
    assert [t.get_text() for t in max_.legend(handles=[mh, ms]).get_texts()] == names
    mplt.close(mfig)


def test_legend_labels_only_assigns_positionally() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.plot([0, 1], [1, 0])
    legend = ax.legend(labels=["X", "Y"])
    assert [item["name"] for item in legend.spec()["items"]] == ["X", "Y"]
    with pytest.raises(TypeError, match="positionally or as keywords"):
        ax.legend(["X"], labels=["Y"])


@pytest.mark.parametrize("code", range(11))
def test_legend_integer_loc_codes_map_to_matplotlib_names(code: int) -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    assert ax.legend(loc=code)._options["loc"] == LEGEND_CODES[code]
    assert ax.legend(loc=np.int64(code))._options["loc"] == LEGEND_CODES[code]


def test_legend_loc_codes_match_matplotlib_table() -> None:
    mpl = _matplotlib()
    codes = {value: key for key, value in mpl.legend.Legend.codes.items()}
    assert tuple(codes[i] for i in range(11)) == LEGEND_CODES


def test_legend_tuple_loc_anchors_the_lower_left_corner() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], label="a")
    options = ax.legend(loc=(0.5, 0.25))._options
    assert options["loc"] == "lower left"
    assert options["anchor"] == (0.5, 0.25)
    _svg(plt.gcf())  # anchored placement must export
    with pytest.raises(ValueError, match="two finite"):
        ax.legend(loc=(0.5, 0.25, 0.1))
    with pytest.raises(ValueError, match="between 0 and 10"):
        ax.legend(loc=11)
    with pytest.raises(ValueError, match="legend loc must be one of"):
        ax.legend(loc="upper middle")


def test_line2d_proxy_constructs_and_freezes_a_legend_swatch() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    dashed = plt.Line2D([0], [0], color="r", linestyle="--", linewidth=2, label="red dashed")
    dots = plt.Line2D([0], [0], color="b", marker="o", linestyle="none", ms=4, label="blue dots")
    both = plt.Line2D([0], [0], color="g", marker="s", mfc="w", mec="k", label="line+square")
    assert dashed.get_label() == "red dashed"
    assert dashed.get_visible() is True
    dashed.set_color("darkred")  # proxies own no axes; mutations must not crash
    legend = ax.legend(handles=[dashed, dots, both], loc=2)
    items = {item["name"]: item for item in legend.spec()["items"]}
    scale = ax._point_scale()
    assert items["red dashed"]["kind"] == "line"
    assert items["red dashed"]["style"]["color"] == "darkred"
    assert items["red dashed"]["style"]["width"] == pytest.approx(2 * scale)
    # Matplotlib's dashed pattern (3.7, 1.6) scaled by linewidth and DPI.
    assert items["red dashed"]["style"]["dash"] == pytest.approx(
        [3.7 * 2 * scale, 1.6 * 2 * scale], abs=1e-3
    )
    assert items["blue dots"]["kind"] == "scatter"
    assert items["blue dots"]["style"]["symbol"] == "circle"
    assert items["blue dots"]["style"]["size"] == pytest.approx((4 + 1) * scale)
    assert items["line+square"]["kind"] == "line"
    marker = items["line+square"]["style"]["legend_marker"]
    assert marker["symbol"] == "square"
    assert marker["color"] == "#ffffff"
    assert marker["stroke"] == "#000000"
    svg = _svg(fig)
    assert "red dashed" in svg and "blue dots" in svg and "line+square" in svg
    with pytest.raises(TypeError, match="Line2D\\(\\) got unsupported"):
        plt.Line2D([0], [0], glow=True)


def test_patch_and_rectangle_proxies_are_legend_handles() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    patch = plt.Patch(facecolor="orange", edgecolor="k", label="area", alpha=0.5)
    rect = plt.Rectangle((0, 0), 1, 1, color="purple", label="box")
    hollow = plt.Patch(fill=False, edgecolor="green", label="outline")
    assert patch.get_facecolor() == "orange" and patch.get_edgecolor() == "#000000"
    assert rect.get_width() == 1.0 and rect.get_xy() == (0.0, 0.0)
    assert hollow.get_fill() is False
    legend = ax.legend(handles=[patch, rect, hollow])
    items = {item["name"]: item for item in legend.spec()["items"]}
    assert items["area"]["kind"] == "bar"
    assert items["area"]["style"]["color"] == "orange"
    assert items["area"]["style"]["opacity"] == 0.5
    assert items["area"]["style"]["stroke"] == "#000000"
    assert items["box"]["style"]["color"] == "purple"
    assert items["box"]["style"]["stroke"] == "purple"
    assert items["outline"]["style"]["color"] == "transparent"
    assert items["outline"]["style"]["stroke"] == "green"
    svg = _svg(fig)
    assert "area" in svg and "box" in svg and "outline" in svg
    with pytest.raises(NotImplementedError):
        plt.Rectangle((0, 0), 1, 1, angle=30)


def test_rectangle_proxy_also_works_with_add_patch() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    before = len(ax._entries)
    handle = ax.add_patch(plt.Rectangle((0.2, 0.2), 0.5, 0.3, facecolor="red", edgecolor="k"))
    assert len(ax._entries) > before
    assert handle.get_visible()
    fig.savefig(BytesIO(), format="png")


# --- F: Artist-level keywords -------------------------------------------------

NOOPS = dict.fromkeys(sorted(ARTIST_NOOP_KWARGS), None)
NOOPS.update(
    zorder=3,
    clip_on=False,
    rasterized=True,
    antialiased=False,
    aa=False,
    snap=True,
    gid="g",
    url="https://example.invalid",
    picker=5,
    in_layout=False,
    path_effects=[],
    mouseover=True,
    animated=False,
)
Z = np.arange(9.0).reshape(3, 3)


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("plot", ([0, 1], [0, 1])),
        ("scatter", ([0, 1], [0, 1])),
        ("bar", ([0, 1], [1, 2])),
        ("barh", ([0, 1], [1, 2])),
        ("hist", ([1, 2, 2, 3],)),
        ("fill_between", ([0, 1], [0, 1])),
        ("axvspan", (0.2, 0.4)),
        ("axhspan", (0.2, 0.4)),
        ("axhline", (0.5,)),
        ("axvline", (0.5,)),
        ("text", (0.5, 0.5, "t")),
        ("errorbar", ([0, 1], [0, 1], 0.1)),
        ("step", ([0, 1], [0, 1])),
        ("imshow", (Z,)),
        ("pcolormesh", (Z,)),
        ("contour", (Z,)),
        ("hlines", (0.5, 0, 1)),
        ("vlines", (0.5, 0, 1)),
        ("stem", ([0, 1], [1, 2])),
        ("pie", ([1, 2],)),
        ("set_title", ("T",)),
        ("set_xlabel", ("x",)),
    ],
)
def test_artist_noop_kwargs_are_accepted_on_every_plotting_call(method: str, args) -> None:
    _fig, ax = plt.subplots()
    # Names a method implements itself (ARTIST_KWARG_KEEP) keep their own
    # contract, e.g. imshow rejects clip_on=False rather than ignoring it.
    kept = ARTIST_KWARG_KEEP.get(method, frozenset())
    getattr(ax, method)(*args, **{k: v for k, v in NOOPS.items() if k not in kept})
    # and still loud for a keyword no Matplotlib artist takes
    with pytest.raises((TypeError, NotImplementedError)):
        getattr(ax, method)(*args, glow=True)


def test_kept_artist_kwargs_still_reach_their_implementations() -> None:
    _fig, ax = plt.subplots()
    mesh = ax.pcolormesh(Z, rasterized=True)
    assert mesh.get_rasterized() is True
    with pytest.raises(NotImplementedError, match="clip_on"):
        ax.imshow(Z, clip_on=False)


def test_grid_accepts_artist_noops() -> None:
    _fig, ax = plt.subplots()
    ax.grid(True, zorder=0, clip_on=False)
    assert ax._grid


def test_artist_kwarg_methods_cover_the_plotting_inventory() -> None:
    inventory = json.loads(INVENTORY.read_text())
    methods = {name for family in inventory["families"].values() for name in family}
    missing = methods - set(ARTIST_KWARG_METHODS)
    assert not missing, sorted(missing)
    for name in ARTIST_KWARG_METHODS:
        assert callable(getattr(plt.Axes, name)), name


def test_visible_false_hides_the_returned_artists() -> None:
    fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], visible=False)
    text = ax.text(0.5, 0.5, "HIDDEN", visible=False)
    _counts, _edges, patches = ax.hist([1, 2, 2], visible=False)
    collection = ax.scatter([0], [0], visible=True)
    bars = ax.errorbar([0, 1], [0, 1], yerr=0.1, visible=False)
    assert not line.get_visible() and line._entry["kwargs"]["opacity"] == 0.0
    assert not text.get_visible() and not patches.get_visible()
    assert collection.get_visible()
    assert not bars.lines[2][0].get_visible()
    svg = _svg(fig)
    assert "HIDDEN" not in svg
    text.set_visible(True)
    ax._chart = None
    assert "HIDDEN" in _svg(fig)


def test_annotate_and_clabel_keep_honoring_zorder() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    note = ax.annotate("n", (0.5, 0.5), zorder=-3, clip_on=False)
    assert note._entry["_zorder"] == -3.0
    contour = ax.contour(Z)
    labels = ax.clabel(contour, inline=False, zorder=-2, rasterized=True)
    assert {label.get_zorder() for label in labels} == {-2.0}


# --- G: partial subplot grids ------------------------------------------------


def test_subplot_creates_only_the_requested_cells() -> None:
    plt.subplot(221)
    plt.plot([0, 1])
    plt.subplot(224)
    plt.plot([1, 0])
    fig = plt.gcf()
    assert len(fig.axes) == 2
    top_left, bottom_right = (ax.get_position().bounds for ax in fig.axes)
    # Matplotlib 3.11's SubplotParams cells for a 2x2 grid.
    assert top_left == pytest.approx((0.125, 0.53, 0.35227272727, 0.35))
    assert bottom_right == pytest.approx((0.54772727272, 0.11, 0.35227272727, 0.35))
    assert all(ax._entries for ax in fig.axes)


def test_subplot_positions_match_matplotlib() -> None:
    _matplotlib().use("Agg")
    import matplotlib.pyplot as mplt

    mplt.subplot(221)
    mplt.subplot(224)
    expected = [tuple(ax.get_position().bounds) for ax in mplt.gcf().axes]
    mplt.close("all")
    plt.subplot(221)
    plt.subplot(224)
    actual = [tuple(ax.get_position().bounds) for ax in plt.gcf().axes]
    np.testing.assert_allclose(actual, expected)


def test_subplot_grids_of_different_shapes_share_a_figure() -> None:
    first = plt.subplot(2, 2, 1)
    plt.plot([0, 1])
    plt.subplot(2, 2, 2)
    plt.plot([1, 0])
    bottom = plt.subplot(2, 1, 2)
    plt.plot([0, 1, 0])
    fig = plt.gcf()
    assert len(fig.axes) == 3
    assert bottom.get_position().bounds == pytest.approx((0.125, 0.11, 0.775, 0.35))
    assert plt.subplot(2, 2, 1) is first  # pyplot.subplot() reuses a matching cell
    assert plt.gca() is first
    assert fig.add_subplot(2, 2, 1) is not first  # Figure.add_subplot() never does
    assert len(fig.axes) == 4


def test_partial_grid_renders_only_its_panels_in_every_exporter() -> None:
    plt.subplot(221)
    plt.plot([0, 1])
    plt.subplot(224)
    plt.plot([1, 0])
    fig = plt.gcf()
    html = fig._to_html()
    assert len(re.findall(r'style="position:absolute;left:', html)) == 2
    assert _svg(fig).count("<svg x=") == 2
    png = BytesIO()
    fig.savefig(png, format="png")
    pixels = np.asarray(plt.imread(BytesIO(png.getvalue())))
    assert pixels.shape[:2] == (480, 640)
    height, width = pixels.shape[:2]
    # The two empty cells (top-right, bottom-left) stay blank: no frame ink.
    for rows, cols in (
        (slice(int(height * 0.12), int(height * 0.45)), slice(int(width * 0.55), int(width * 0.9))),
        (slice(int(height * 0.55), int(height * 0.9)), slice(int(width * 0.12), int(width * 0.45))),
    ):
        block = pixels[rows, cols, :3]
        assert np.all(block >= 0.99), "an unrequested subplot cell was drawn"


def test_whole_figure_subplot_keeps_the_single_chart_path() -> None:
    ax = plt.subplot(111)
    ax.plot([0, 1])
    fig = plt.gcf()
    assert len(fig.axes) == 1
    assert ax._figure_rect is None
    assert fig._single() is not None
    assert plt.subplot(1, 1, 1) is ax


def test_subplot_rejects_an_out_of_range_index() -> None:
    with pytest.raises(ValueError, match="1 <= num <= 4, not 5"):
        plt.subplot(2, 2, 5)
    with pytest.raises(ValueError, match="1 <= num <= 6, not 0"):
        plt.figure().add_subplot(2, 3, 0)


# --- H: rejected kwargs and missing attributes --------------------------------


def test_scatter_facecolors_none_draws_hollow_markers() -> None:
    _fig, ax = plt.subplots()
    hollow = ax.scatter([0, 1], [0, 1], facecolors="none", edgecolors="r")
    assert hollow._entry["kwargs"]["color"] == "transparent"
    assert hollow._entry["kwargs"]["stroke"] == "#ff0000"
    alias = ax.scatter([0, 1], [0, 1], facecolor="none", edgecolor="b")
    assert alias._entry["kwargs"]["color"] == "transparent"
    # ``c`` wins over facecolors, as in Matplotlib.
    filled = ax.scatter([0, 1], [0, 1], c="g", facecolors="none")
    assert filled._entry["kwargs"]["color"] == "#008000"


def test_bar_tick_label_places_one_labeled_tick_per_bar() -> None:
    _fig, ax = plt.subplots()
    ax.bar([1, 2, 3], [1, 2, 3], tick_label=["x", "y", "z"])
    assert ax._axis_props("x")["tick_labels"] == ["x", "y", "z"]
    assert list(ax._axis_props("x")["tick_values"]) == [1.0, 2.0, 3.0]
    ax.barh([1, 2], [1, 2], tick_label="same")
    assert ax._axis_props("y")["tick_labels"] == ["same", "same"]
    with pytest.raises(ValueError, match="number of tick labels"):
        ax.bar([1, 2], [1, 2], tick_label=["only one"])
    with pytest.raises(NotImplementedError):
        ax.bar(["a", "b"], [1, 2], tick_label=["A", "B"])


def test_bar_and_hist_log_put_the_value_axis_on_a_log_scale() -> None:
    _fig, ax = plt.subplots()
    ax.bar([1, 2, 3], [1, 10, 100], log=True)
    assert ax._scale_specs["y"]["name"] == "log"
    _fig, ax = plt.subplots()
    ax.barh([1, 2, 3], [1, 10, 100], log=True)
    assert ax._scale_specs["x"]["name"] == "log"
    _fig, ax = plt.subplots()
    ax.hist([1, 2, 2, 3, 3, 3], bins=3, log=True)
    assert ax._scale_specs["y"]["name"] == "log"


def test_hist_bottom_and_align_match_matplotlib_geometry() -> None:
    _fig, ax = plt.subplots()
    counts, edges, patches = ax.hist([1, 2, 2, 3], bins=3, bottom=5, align="left")
    np.testing.assert_allclose(counts, [1, 2, 1])  # raw counts, not lifted
    geometry = [(r.get_x(), r.get_y(), r.get_height()) for r in patches]
    expected = [(2 / 3, 5.0, 1.0), (4 / 3, 5.0, 2.0), (2.0, 5.0, 1.0)]
    np.testing.assert_allclose(geometry, expected)
    _matplotlib().use("Agg")
    import matplotlib.pyplot as mplt

    mfig, max_ = mplt.subplots()
    _n, _b, mpatches = max_.hist([1, 2, 2, 3], bins=3, bottom=5, align="left")
    np.testing.assert_allclose(geometry, [(r.get_x(), r.get_y(), r.get_height()) for r in mpatches])
    mplt.close(mfig)
    _fig, ax = plt.subplots()
    _counts, _edges, right = ax.hist([1, 2, 2, 3], bins=3, bottom=[1, 2, 3], align="right")
    assert [r.get_y() for r in right] == [1.0, 2.0, 3.0]
    assert right[0].get_x() == pytest.approx(2 / 3 + 2 / 3)
    with pytest.raises(ValueError, match="align"):
        ax.hist([1, 2], align="middle")
    with pytest.raises(NotImplementedError):
        ax.hist([1, 2], histtype="step", align="left")


def test_text_alpha_reaches_the_entry_and_static_export() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    text = ax.text(0.5, 0.5, "FADED", alpha=0.3)
    assert text.get_alpha() == 0.3
    assert 'fill-opacity="0.3"' in _svg(fig)


def test_hlines_and_vlines_accept_the_singular_linestyle_spelling() -> None:
    _fig, ax = plt.subplots()
    solid = ax.hlines(0.5, 0, 1)
    dashed = ax.hlines(0.5, 0, 1, linestyle="--")
    dotted = ax.vlines(0.5, 0, 1, ls=":")
    assert len(dashed._entry["args"][0]) > len(solid._entry["args"][0])
    assert len(dotted._entry["args"][0]) > len(solid._entry["args"][0])


def test_errorbar_capthick_and_marker_style_kwargs() -> None:
    _fig, ax = plt.subplots()
    container = ax.errorbar(
        [0, 1], [0, 1], yerr=0.1, fmt="o", capsize=3, capthick=2, mfc="w", mec="k", mew=1.5
    )
    caps = container.lines[1]
    assert caps and all(cap._entry["_mpl_line_marker_stroke_points"] == 2.0 for cap in caps)
    (marker_entry,) = container.lines[0]._marker_entries()
    assert marker_entry["kwargs"]["color"] == "#ffffff"
    assert marker_entry["kwargs"]["stroke"] == "#000000"
    assert marker_entry["kwargs"]["stroke_width"] == pytest.approx(1.5 * ax._point_scale())


def test_colorbar_fraction_is_an_accepted_noop() -> None:
    fig, ax = plt.subplots()
    image = ax.imshow(Z)
    fig.colorbar(image, fraction=0.046, pad=0.04)
    assert ax._colorbar is not None


def test_stateful_tick_params_margins_and_locator_params_delegate_to_gca() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 10], [0, 10])
    plt.tick_params(axis="x", labelsize=8, labelrotation=45)
    assert ax._axis_props("x")["tick_label_angle"] == 45.0
    plt.margins(0.25)
    assert plt.margins() == (0.25, 0.25)
    plt.locator_params(axis="y", nbins=3)
    assert ax._axis_props("y")["tick_count"] == 3
    for name in ("tick_params", "margins", "locator_params"):
        assert name in plt.__all__


def test_cm_namespace_returns_callable_colormaps() -> None:
    viridis = plt.cm.viridis
    assert callable(viridis) and viridis.N == 256 and viridis.name == "viridis"
    assert np.asarray(viridis(np.linspace(0, 1, 3))).shape == (3, 4)
    assert plt.cm.viridis_r.name == "viridis_r"
    tab10 = plt.cm.tab10
    assert tab10.N == 10
    assert np.asarray(tab10(np.arange(3))).shape == (3, 4)
    assert tab10(0) == pytest.approx((0x1F / 255, 0x77 / 255, 0xB4 / 255, 1.0))
    assert [plt.cm.tab20.N, plt.cm.Set1.N, plt.cm.Set2.N, plt.cm.Set3.N, plt.cm.Paired.N] == [
        20,
        9,
        8,
        12,
        12,
    ]
    assert np.allclose(plt.cm.Set1_r(0), plt.cm.Set1(8))
    assert plt.get_cmap("tab10").N == 10 and plt.get_cmap("Paired", 4).N == 4
    assert plt.get_cmap(viridis) is viridis
    with pytest.raises(AttributeError):
        getattr(plt.cm, "not_a_colormap")  # noqa: B009 - attribute access is the API under test
    _fig, ax = plt.subplots()
    ax.imshow(Z, cmap=plt.cm.gray)
    ax.scatter([0, 1], [0, 1], c=[0, 1], cmap=plt.cm.plasma_r)
    with pytest.raises(ValueError):
        ax.imshow(Z, cmap=plt.cm.tab10)  # no engine table: still loud


def test_qualitative_tables_match_matplotlib() -> None:
    mpl = _matplotlib()
    from matplotlib.colors import to_hex

    for name in ("tab10", "tab20", "Set1", "Set2", "Set3", "Paired", "Dark2", "Pastel1"):
        reference = [to_hex(c) for c in mpl.colormaps[name].colors]
        ours = [to_hex(c) for c in getattr(plt.cm, name)(np.arange(len(reference)))]
        assert ours == reference, name


def test_bar_patch_geometry_matches_matplotlib() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([1, 2, 3], [1, 2, 3], width=0.5, bottom=[0, 1, 2])
    geometry = [(r.get_x(), r.get_y(), r.get_width(), r.get_height()) for r in bars]
    np.testing.assert_allclose(geometry, [(0.75, 0, 0.5, 1), (1.75, 1, 0.5, 2), (2.75, 2, 0.5, 3)])
    assert bars[1].get_xy() == pytest.approx((1.75, 1.0))
    assert bars[1].get_bbox().bounds == pytest.approx((1.75, 1.0, 0.5, 2.0))
    assert bars[1].get_center() == pytest.approx((2.0, 2.0))
    horizontal = ax.barh([0, 1], [3, 4], height=0.4, left=1)
    np.testing.assert_allclose(
        [(r.get_x(), r.get_y(), r.get_width(), r.get_height()) for r in horizontal],
        [(1, -0.2, 3, 0.4), (1, 0.8, 4, 0.4)],
    )
    _fig, ax = plt.subplots()
    categorical = ax.bar(["a", "b", "c"], [1, 2, 3])
    for r in categorical:
        ax.text(r.get_x() + r.get_width() / 2, r.get_height(), f"{r.get_height():g}", ha="center")
    assert [r.get_x() for r in categorical] == pytest.approx([-0.4, 0.6, 1.6])
    _matplotlib().use("Agg")
    import matplotlib.pyplot as mplt

    mfig, max_ = mplt.subplots()
    reference = max_.bar([1, 2, 3], [1, 2, 3], width=0.5, bottom=[0, 1, 2])
    np.testing.assert_allclose(
        geometry, [(r.get_x(), r.get_y(), r.get_width(), r.get_height()) for r in reference]
    )
    mplt.close(mfig)


def test_bar_with_string_categories_and_error_bars_autoscales() -> None:
    _fig, ax = plt.subplots()
    ax.bar(["a", "b", "c"], [1, 2, 3], yerr=[0.1, 0.2, 0.3])
    assert ax.get_xlim() == pytest.approx((-0.54, 2.54))
    assert ax.get_ylim()[1] >= 3.3
    _fig, ax = plt.subplots()
    ax.barh(["a", "b", "c"], [1, 2, 3], xerr=[0.1, 0.2, 0.3])
    assert ax.get_ylim() == pytest.approx((-0.54, 2.54))
    assert ax.get_xlim()[1] >= 3.3
    assert len(ax.get_yticklabels()) == 3


# --- review round: visibility of proxies and chrome, partial-grid layout ------


def test_legend_proxies_honor_visible_and_propagate_to_their_marker() -> None:
    hidden_line = plt.Line2D([0], [0], color="r", marker="o", visible=False)
    assert not hidden_line.get_visible()
    assert hidden_line._entry["kwargs"]["opacity"] == 0.0
    assert hidden_line._proxy_marker_entry["kwargs"]["opacity"] == 0.0
    assert not plt.Patch(facecolor="r", visible=False).get_visible()
    assert not plt.Rectangle((0, 0), 1, 1, visible=False).get_visible()
    shown = plt.Line2D([0], [0], color="b", marker="s", alpha=0.5)
    shown.set_visible(False)
    assert shown._proxy_marker_entry["kwargs"]["opacity"] == 0.0
    shown.set_visible(True)
    assert shown._proxy_marker_entry["kwargs"]["opacity"] == 0.5
    assert shown._entry["kwargs"]["opacity"] == 0.5


def test_plotted_line_visibility_moves_its_marker_overlay_too() -> None:
    _fig, ax = plt.subplots()
    (line,) = ax.plot([0, 1], [0, 1], marker="o", visible=False)
    kinds = [(entry["kind"], entry["kwargs"].get("opacity")) for entry in ax._entries]
    assert kinds == [("line", 0.0), ("scatter", 0.0)]
    line.set_visible(True)
    assert [entry["kwargs"]["opacity"] for entry in ax._entries] == [1.0, 1.0]
    line.set_alpha(0.4)
    assert [entry["kwargs"]["opacity"] for entry in ax._entries] == [0.4, 0.4]


def test_chrome_setters_apply_visible_to_their_text() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.set_title("HIDDENTITLE", visible=False)
    ax.set_xlabel("HIDDENX", visible=False)
    ax.set_ylabel("SHOWNY", visible=True)
    svg = _svg(fig)
    assert "HIDDENTITLE" not in svg and "HIDDENX" not in svg
    assert "SHOWNY" in svg
    assert ax.get_title() == ""
    ax.set_title("SHOWNTITLE", visible=True, zorder=2)
    assert "SHOWNTITLE" in _svg(fig)


def test_partial_grid_records_its_dimensions_for_tight_layout() -> None:
    plt.subplot(221)
    plt.plot([0, 1])
    plt.subplot(224)
    plt.plot([1, 0])
    fig = plt.gcf()
    assert (fig._nrows, fig._ncols) == (2, 2)
    fig.tight_layout()
    fig.savefig(BytesIO(), format="png")
    partial = [np.asarray(ax.get_position().bounds) for ax in fig.axes]
    plt.close("all")
    full_fig, axes = plt.subplots(2, 2)
    axes[0, 0].plot([0, 1])
    axes[1, 1].plot([1, 0])
    full_fig.tight_layout()
    full_fig.savefig(BytesIO(), format="png")
    full = [
        np.asarray(axes[0, 0].get_position().bounds),
        np.asarray(axes[1, 1].get_position().bounds),
    ]
    # Row geometry (bottom, height) and the figure-edge margins are the 2x2
    # grid's; only the inter-column gap differs, because Matplotlib (and xy)
    # size that gap from the chrome of *adjacent* panels, which a 221/224
    # figure does not have. Matplotlib 3.11 shows the same width difference.
    for got, want in zip(partial, full, strict=True):
        np.testing.assert_allclose(got[[1, 3]], want[[1, 3]], atol=1e-6)
    np.testing.assert_allclose(partial[0][0], full[0][0], atol=1e-6)  # left margin
    np.testing.assert_allclose(partial[1][0] + partial[1][2], full[1][0] + full[1][2], atol=1e-6)
    for rect in partial:  # each panel stays inside its own quadrant
        assert rect[2] < 0.5 and rect[3] < 0.5
    assert partial[0][0] < 0.5 < partial[1][0]


def test_get_cmap_lut_resamples_qualitative_palettes_like_matplotlib() -> None:
    mpl = _matplotlib()
    mpl.use("Agg")
    import matplotlib.pyplot as mplt
    from matplotlib.colors import to_hex

    for name, count in (("tab10", 4), ("tab10", 12), ("tab10_r", 4), ("Paired", 5)):
        ours = plt.get_cmap(name, count)
        reference = mplt.get_cmap(name, count)
        assert ours.N == count == reference.N
        assert [to_hex(c) for c in ours.colors] == [to_hex(c) for c in reference.colors], name
        assert ours.name == reference.name
    assert [to_hex(c) for c in plt.get_cmap("tab10", 4).colors] == [
        "#1f77b4",
        "#d62728",
        "#e377c2",
        "#17becf",
    ]


@pytest.mark.parametrize("align", ["left", "right", "mid"])
@pytest.mark.parametrize("rwidth", [None, 0.5])
def test_hist_align_bar_rectangles_match_matplotlib(align: str, rwidth) -> None:
    mpl = _matplotlib()
    mpl.use("Agg")
    import matplotlib.pyplot as mplt

    data = [1, 2, 2, 3, 3.5, 2.2]
    _fig, ax = plt.subplots()
    _n, _e, patches = ax.hist(data, bins=3, align=align, rwidth=rwidth)
    _n, _e, grouped = ax.hist([data, data], bins=3, align=align, rwidth=rwidth)
    mfig, max_ = mplt.subplots()
    _n, _e, reference = max_.hist(data, bins=3, align=align, rwidth=rwidth)
    _n, _e, reference_grouped = max_.hist([data, data], bins=3, align=align, rwidth=rwidth)
    geometry = [(r.get_x(), r.get_width()) for r in patches]
    expected = [(r.get_x(), r.get_width()) for r in reference]
    np.testing.assert_allclose(geometry, expected, atol=1e-9)
    for ours, theirs in zip(grouped, reference_grouped, strict=True):
        np.testing.assert_allclose(
            [(r.get_x(), r.get_width()) for r in ours],
            [(r.get_x(), r.get_width()) for r in theirs],
            atol=1e-9,
        )
    mplt.close(mfig)


@pytest.mark.parametrize(
    ("colors", "expected"),
    [
        (["red", "green", "blue"], "red"),  # 3 names: first entry wins, not RGB
        (["red", "green", "blue", "black"], "red"),  # 4 names: not RGBA either
        (["red", "green"], "red"),
        (["red", "green", "blue", "black", "white"], "red"),
        ((1.0, 0.0, 0.0), "rgb(255,0,0)"),  # one numeric RGB tuple is one color
        ((1.0, 0.0, 0.0, 0.5), "rgba(255,0,0,0.5)"),
        ("red", "red"),
    ],
)
def test_hlines_vlines_colors_read_names_first_and_rgba_tuples_whole(colors, expected) -> None:
    _fig, ax = plt.subplots()
    assert ax.hlines(0.5, 0, 1, colors=colors)._entry["kwargs"]["color"] == expected
    assert ax.vlines(0.5, 0, 1, colors=colors)._entry["kwargs"]["color"] == expected
