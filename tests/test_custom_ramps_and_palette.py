"""Author-supplied color: custom colormaps, the chart palette, and the axis
visibility shorthands.

A chart's colors have to come from the host's design tokens, not from a fixed
list of twenty presets. These tests pin the three surfaces that make that
possible and — the part that is easy to regress — that all three renderers
(WebGL spec, SVG, native raster) resolve them from **one** definition.
"""

from __future__ import annotations

import json
import re
import warnings

import numpy as np
import pytest

import xy
from xy import _raster, _svg, channels
from xy.config import DEFAULT_PALETTE

RAMP = ["#0b1220", "#2563eb", "#22d3ee", "#fde68a"]
PALETTE = ["#38bdf8", "#e879f9", "#fbbf24", "#34d399"]


def _xy(n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(4)
    return rng.normal(size=n), rng.normal(size=n)


# --- resolve_colormap --------------------------------------------------------


def test_builtin_names_pass_through_untouched():
    assert channels.resolve_colormap("magma") == "magma"
    assert channels.resolve_colormap("magma_r") == "magma_r"


def test_uniform_color_list_ships_its_own_stops():
    assert channels.resolve_colormap(RAMP) == [
        [11, 18, 32],
        [37, 99, 235],
        [34, 211, 238],
        [253, 230, 138],
    ]


def test_every_closed_css_grammar_resolves_to_channels():
    stops = channels.resolve_colormap(["rgb(255 0 0)", "hsl(120 100% 50%)", "tomato"])
    assert stops == [[255, 0, 0], [0, 255, 0], [255, 99, 71]]


def test_positioned_stops_resample_onto_the_lut_grid():
    # Non-uniform positions cannot ship as evenly spaced stops without moving
    # the ramp, so they resample at the client's own texel count — exact, not
    # approximate.
    stops = channels.resolve_colormap([(0.0, "#000000"), (0.25, "#ffffff"), (1.0, "#000000")])
    assert len(stops) == 256
    assert stops[0] == [0, 0, 0] and stops[-1] == [0, 0, 0]
    assert stops[64] == [255, 255, 255]  # the 25% anchor lands on texel 64
    assert stops[32] == [128, 128, 128]  # linear on either side of it


def test_uniform_positions_still_ship_short():
    assert channels.resolve_colormap([(0.0, "#000000"), (1.0, "#ffffff")]) == [
        [0, 0, 0],
        [255, 255, 255],
    ]


def test_css_gradient_syntax_matches_the_equivalent_pair_list():
    gradient = channels.resolve_colormap("linear-gradient(#000000, #ffffff 25%, #000000)")
    pairs = channels.resolve_colormap([(0.0, "#000000"), (0.25, "#ffffff"), (1.0, "#000000")])
    assert gradient == pairs


def test_resolution_is_idempotent():
    once = channels.resolve_colormap(RAMP)
    assert channels.resolve_colormap(once) == once


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (["#fff"], "between 2 and 256 color stops"),
        (["var(--brand)", "#fff"], "cannot be resolved to fixed channels"),
        (["oklch(0.7 0.15 250)", "#fff"], "cannot be resolved to fixed channels"),
        (["color-mix(in oklab, #f00, #00f)", "#fff"], "cannot be resolved to fixed channels"),
        ("nope", "unknown colormap"),
        ([(1.5, "#fff"), (0.0, "#000")], "must be between 0 and 1"),
        ([("x", "#fff"), (1.0, "#000")], "position must be a number"),
        (7, "must be a built-in name"),
        ([["#f00", "#0f0", "#00f"], "#fff"], "must be a color or a (position, color) pair"),
        # A LUT carries no alpha, so a translucent stop must raise rather than
        # silently become opaque: ["transparent", "#00f"] would otherwise ship
        # as an opaque BLACK -> blue ramp.
        (["transparent", "#0000ff"], "is translucent"),
        (["rgba(255,0,0,0.5)", "#fff"], "is translucent"),
        (["#ff000080", "#fff"], "is translucent"),
        ("linear-gradient(#ff000080, #ffffff)", "is translucent"),
    ],
)
def test_bad_colormaps_raise_with_the_reason(value, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        channels.resolve_colormap(value)


def test_browser_only_colors_are_refused_because_static_export_cannot_resolve_them():
    # `var()` is legal on every *paint* prop — it just cannot build a LUT that
    # SVG and native PNG agree with, so it fails at build rather than making
    # the browser and the exports disagree.
    xy.scatter_chart(xy.scatter(*_xy(), color="var(--brand)")).figure()
    with pytest.raises(ValueError, match="colormap stops must be"):
        xy.scatter_chart(
            xy.scatter(*_xy(), color=np.linspace(0, 1, 400), colormap=["var(--a)", "#fff"])
        ).figure()


# --- custom colormaps reach every renderer -----------------------------------


def test_custom_ramp_reaches_the_wire_and_the_colorbar():
    x, y = _xy()
    chart = xy.scatter_chart(
        xy.scatter(x, y, color=np.linspace(0.0, 1.0, len(x)), colormap=RAMP),
        xy.colorbar(title="v"),
    )
    spec, _ = chart.figure().build_payload()
    stops = channels.resolve_colormap(RAMP)
    assert spec["traces"][0]["color"]["colormap"] == stops
    # Regression: str()-ing the colormap here made every custom ramp fall back
    # to viridis in the colorbar while the marks were painted correctly.
    assert spec["colorbar"]["colormap"] == stops


@pytest.mark.parametrize("kind", ["scatter", "hexbin", "heatmap", "contour"])
def test_every_colormap_bearing_mark_ships_the_custom_ramp(kind):
    rng = np.random.default_rng(9)
    if kind == "scatter":
        x, y = _xy()
        chart = xy.scatter_chart(xy.scatter(x, y, color=rng.random(len(x)), colormap=RAMP))
    elif kind == "hexbin":
        x, y = _xy(2000)
        chart = xy.hexbin_chart(xy.hexbin(x, y, gridsize=12, colormap=RAMP))
    elif kind == "heatmap":
        chart = xy.heatmap_chart(xy.heatmap(rng.random((8, 10)), colormap=RAMP))
    else:
        chart = xy.contour_chart(xy.contour(rng.random((8, 10)), levels=4, colormap=RAMP))
    spec, _ = chart.figure().build_payload()
    assert spec["traces"], f"{kind} produced no traces"
    # The ramp must reach the wire, not merely be accepted at the door: find it
    # wherever this kind carries it, and prove no viridis leaked in.
    blob = json.dumps(spec)
    stops = channels.resolve_colormap(RAMP)
    assert json.dumps(stops)[1:-1] in blob, f"{kind} dropped the custom ramp before shipping"
    assert "viridis" not in blob, f"{kind} shipped the default colormap alongside a custom ramp"


def test_svg_and_native_png_paint_the_custom_ramp_not_viridis():
    x, y = _xy(300)
    values = np.linspace(0.0, 1.0, len(x))
    chart = xy.scatter_chart(
        xy.scatter(x, y, color=values, colormap=RAMP, size=8), xy.colorbar(title="v")
    )
    svg = chart.to_svg()
    # The ramp's own endpoints must appear; viridis' must not.
    assert "rgb(11,18,32)" in svg and "rgb(253,230,138)" in svg
    assert "rgb(68,1,84)" not in svg, "viridis' dark end leaked into a custom ramp"
    # And the LUT the exporters sample is the client's, stop for stop.
    sampled = _svg._lut(channels.resolve_colormap(RAMP), np.array([0.0, 1.0]))
    assert sampled.tolist() == [[11, 18, 32], [253, 230, 138]]
    assert chart.to_png().startswith(b"\x89PNG")


def test_fully_opaque_alpha_notation_is_still_accepted():
    assert channels.resolve_colormap(["rgba(255,0,0,1)", "#ffffffff"]) == [
        [255, 0, 0],
        [255, 255, 255],
    ]


def test_reversal_stays_a_builtin_only_affordance():
    # `_r` is a NAME suffix. A custom ramp must not pick up reversal semantics
    # from a stop that happens to end in "_r", and the built-in path must still
    # reverse -- the two must not be resolved by the same branch.
    assert channels.resolve_colormap("magma_r") == "magma_r"
    assert _svg._colormap_stops("magma_r") == list(reversed(_svg._colormap_stops("magma")))
    # A custom ramp is data, not a name: it reaches the LUT in the given order.
    stops = channels.resolve_colormap(["#000000", "#ffffff"])
    assert _svg._lut(stops, np.array([0.0, 1.0])).tolist() == [[0, 0, 0], [255, 255, 255]]
    assert _svg._colormap_stops(stops) == [(0, 0, 0), (255, 255, 255)]


# --- chart palette -----------------------------------------------------------


def test_theme_palette_colors_unnamed_series_in_order():
    chart = xy.line_chart(
        *[xy.line([0, 1], [0, i], name=f"s{i}") for i in range(4)],
        xy.theme(palette=PALETTE),
    )
    spec, _ = chart.figure().build_payload()
    assert [t["style"]["color"] for t in spec["traces"]] == PALETTE


def test_theme_palette_drives_categorical_color_channels():
    x, y = _xy()
    cats = np.array(["a", "b", "c"])[np.arange(len(x)) % 3]
    chart = xy.scatter_chart(xy.scatter(x, y, color=cats), xy.theme(palette=PALETTE))
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["color"]["palette"] == PALETTE[:3]
    assert spec["palette"] == PALETTE


def test_without_a_theme_palette_nothing_changes():
    chart = xy.line_chart(*[xy.line([0, 1], [0, i], name=f"s{i}") for i in range(3)])
    spec, _ = chart.figure().build_payload()
    assert [t["style"]["color"] for t in spec["traces"]] == list(DEFAULT_PALETTE[:3])
    assert "palette" not in spec, "the default palette must not bloat every spec"


def test_explicit_color_still_beats_the_palette_and_keeps_its_slot():
    chart = xy.line_chart(
        xy.line([0, 1], [0, 1], name="a", color="#ff00ff"),
        xy.line([0, 1], [0, 2], name="b"),
        xy.theme(palette=PALETTE),
    )
    spec, _ = chart.figure().build_payload()
    colors = [t["style"]["color"] for t in spec["traces"]]
    # The explicit color wins and does NOT consume a palette slot, so the
    # first series that actually needs one still gets the brand's first color
    # (matplotlib's property cycle behaves the same way).
    assert colors[0] == "#ff00ff" and colors[1] == PALETTE[0]


@pytest.mark.parametrize(
    ("mark", "kwargs"),
    [
        (xy.line, {"x": [0, 1], "y": [0, 1]}),
        (xy.area, {"x": [0, 1], "y": [1, 2]}),
        (xy.scatter, {"x": [0, 1], "y": [0, 1]}),
        (xy.box, {"values": [1, 2, 3, 4, 9]}),
        (xy.violin, {"values": [1, 2, 3, 4, 2, 3, 9]}),
        (xy.stem, {"x": [0, 1], "y": [0, 1]}),
        (xy.errorbar, {"x": [0, 1], "y": [0, 1], "yerr": [0.1, 0.1]}),
        (xy.error_band, {"x": [0, 1], "lower": [0, 1], "upper": [2, 3]}),
        (xy.bar, {"x": [0, 1], "y": [1, 2]}),
        (xy.hist, {"values": [1, 2, 2, 3, 3, 3]}),
    ],
)
def test_every_mark_takes_exactly_one_palette_slot_per_series(mark, kwargs):
    """A mark is one series, whatever its trace count.

    `box` builds four traces and `stem` two. Cycling on `len(traces)` made
    four boxes under a four-color palette all wear `palette[0]`, and made any
    later series skip entries — this pins one slot per series instead.
    """
    chart = xy.chart(
        xy.theme(palette=PALETTE),
        *[mark(name=f"s{i}", **kwargs) for i in range(4)],
    )
    spec, _ = chart.figure().build_payload()
    colors = [
        (t.get("style") or {}).get("color") or (t.get("color") or {}).get("color")
        for t in spec["traces"]
        if t.get("name")
    ]
    assert colors == PALETTE[:4]


def test_a_multi_trace_mark_does_not_shift_the_series_after_it():
    chart = xy.chart(
        xy.theme(palette=PALETTE),
        xy.box(values=[1, 2, 3, 4, 9], x=[0] * 5, name="dist"),
        xy.line([0, 1], [2, 3], name="a"),
        xy.line([0, 1], [3, 4], name="b"),
    )
    spec, _ = chart.figure().build_payload()
    named = [t for t in spec["traces"] if t.get("name")]
    assert [t["style"]["color"] for t in named] == PALETTE[:3]


def test_a_grouped_bar_takes_one_slot_per_series_it_emits():
    chart = xy.chart(
        xy.theme(palette=PALETTE),
        xy.bar(x=["p", "q"], y=[[1, 2], [3, 4], [2, 1]], series=["s1", "s2", "s3"]),
        xy.line([0, 1], [5, 6], name="after"),
    )
    spec, _ = chart.figure().build_payload()
    named = [t for t in spec["traces"] if t.get("name")]
    assert [t["style"]["color"] for t in named] == PALETTE[:4]


def test_a_palette_map_pins_colors_to_category_labels():
    x, y = _xy()
    brand = {"setosa": "#4c72b0", "versicolor": "#dd8452", "virginica": "#55a868"}
    cats = np.array(["setosa", "versicolor", "virginica"])[np.arange(len(x)) % 3]
    chart = xy.scatter_chart(xy.scatter(x, y, color=cats), xy.theme(palette=brand))
    spec, _ = chart.figure().build_payload()
    color = spec["traces"][0]["color"]
    assert color["categories"] == ["setosa", "versicolor", "virginica"]
    assert color["palette"] == [brand[c] for c in color["categories"]]


def test_a_palette_map_survives_a_panel_that_is_missing_a_category():
    """The drift a positional cycle cannot avoid.

    A facet panel holding only two of three species factorizes to codes 0 and
    1, so a positional palette repaints them with the first two colors and the
    same species means a different color in each panel."""
    brand = {"setosa": "#4c72b0", "versicolor": "#dd8452", "virginica": "#55a868"}
    x, y = _xy(60)

    def palette_for(labels):
        cats = np.array(labels)[np.arange(len(x)) % len(labels)]
        chart = xy.scatter_chart(xy.scatter(x, y, color=cats), xy.theme(palette=brand))
        spec, _ = chart.figure().build_payload()
        color = spec["traces"][0]["color"]
        return dict(zip(color["categories"], color["palette"], strict=True))

    full = palette_for(["setosa", "versicolor", "virginica"])
    partial = palette_for(["versicolor", "virginica"])
    assert partial["versicolor"] == full["versicolor"] == brand["versicolor"]
    assert partial["virginica"] == full["virginica"] == brand["virginica"]


def test_categories_outside_the_palette_map_take_unused_defaults_and_warn():
    x, y = _xy()
    cats = np.array(["a", "b", "c"])[np.arange(len(x)) % 3]
    with pytest.warns(RuntimeWarning, match="not in the xy.theme"):
        chart = xy.scatter_chart(xy.scatter(x, y, color=cats), xy.theme(palette={"a": "#ff0000"}))
        spec, _ = chart.figure().build_payload()
    palette = spec["traces"][0]["color"]["palette"]
    assert palette[0] == "#ff0000"
    # Distinct, and never a repeat of a color the map already spent.
    assert len(set(palette)) == 3


def test_a_palette_map_still_cycles_plain_series():
    chart = xy.line_chart(
        *[xy.line([0, 1], [0, i], name=f"s{i}") for i in range(3)],
        xy.theme(palette={"a": "#ff0000", "b": "#00ff00", "c": "#0000ff"}),
    )
    spec, _ = chart.figure().build_payload()
    assert [t["style"]["color"] for t in spec["traces"]] == ["#ff0000", "#00ff00", "#0000ff"]
    assert spec["palette"] == ["#ff0000", "#00ff00", "#0000ff"], "must ship colors, not labels"


def test_a_list_of_css_colors_paints_those_colors_instead_of_factorizing():
    """`["#ff0000", "#00ff00"]` is paint, not two categories to re-encode."""
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0], [0.0, 1.0, 2.0], color=["#ff0000", "#00ff00", "#0000ff"])
    )
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["color"]["mode"] == "direct_rgba"
    svg = chart.to_svg()
    assert "255,0,0" in svg.replace(" ", "") or "#ff0000" in svg


class _NoMaterialize(np.ndarray):
    """An array that refuses to become a Python list."""

    def tolist(self):  # noqa: D102 - the whole point is that this never runs
        raise AssertionError("the literal-color probe materialized the whole column")


def test_the_literal_color_probe_does_not_materialize_category_columns():
    """`_factorize_categories` identifies equal records in Rust precisely to
    avoid creating N Python objects; an unconditional `tolist()` in the probe
    ahead of it threw that away for every categorical scatter (~39% of the
    payload build at 500k rows). A category column must be rejected on its
    first value."""
    column = np.array([f"group-{i % 24:02d}" for i in range(1000)]).view(_NoMaterialize)
    assert channels._literal_color_rgba(column) is None


def test_the_probe_still_reads_a_column_that_actually_looks_like_paint():
    column = np.array(["#ff0000", "#00ff00", "#0000ff"])
    rgba = channels._literal_color_rgba(column)
    assert rgba is not None and rgba.shape == (3, 4)
    # One bad entry anywhere still means "this is data, not paint".
    assert channels._literal_color_rgba(np.array(["#ff0000", "b"])) is None


def test_named_colors_stay_categorical_because_a_column_can_hold_them():
    chart = xy.scatter_chart(
        xy.scatter([0.0, 1.0, 2.0], [0.0, 1.0, 2.0], color=["red", "green", "blue"])
    )
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["color"]["mode"] == "categorical"


def test_palette_shorter_than_the_categories_warns_before_it_repeats():
    x, y = _xy()
    cats = np.array(["a", "b", "c", "d"])[np.arange(len(x)) % 4]
    with pytest.warns(RuntimeWarning, match="colors repeat every 2"):
        xy.scatter_chart(xy.scatter(x, y, color=cats), xy.theme(palette=["#f00", "#0f0"])).figure()


def test_static_exporters_use_the_chart_palette():
    x, y = _xy(200)
    cats = np.array(["a", "b"])[np.arange(len(x)) % 2]
    chart = xy.scatter_chart(xy.scatter(x, y, color=cats, size=8), xy.theme(palette=PALETTE))
    svg = chart.to_svg()
    assert "rgb(56,189,248)" in svg and "rgb(232,121,249)" in svg  # #38bdf8 / #e879f9
    assert "rgb(57,135,229)" not in svg  # DEFAULT_PALETTE[0] = #3987e5


@pytest.mark.parametrize(
    "entry", ["var(--brand)", "oklch(0.7 0.15 250)", "color-mix(in oklab, #f00, #00f)"]
)
def test_browser_only_palette_entries_are_refused_like_colormap_stops(entry):
    # A palette is an INDEXED lookup consumed by four things with no DOM (the
    # density plane, the SVG writer, the rasterizer, the client's worker
    # re-bin). Several browser-only entries would land on one fallback and merge
    # distinct categories, so the rule is the same as for colormap stops.
    with pytest.raises(ValueError, match="cannot be resolved to fixed channels"):
        xy.theme(palette=[entry, "#ffffff"])
    # ...but a single paint prop is unaffected: one mark, one color.
    xy.scatter_chart(xy.scatter(*_xy(), color=entry)).figure()


def test_hand_authored_specs_degrade_per_index_never_onto_one_color():
    # The public API refuses browser-only entries, so this resolver is the
    # safety net for a hand-built spec. It must substitute the built-in palette
    # AT THE SAME INDEX — one shared fallback would merge categories, and black
    # would make a density surface disagree with the points it aggregates.
    with pytest.warns(RuntimeWarning, match="resolve only in a browser"):
        rows = channels.palette_rows_rgba8(["var(--a)", "var(--b)", "var(--c)"], 3)
    assert len({tuple(row) for row in rows}) == 3, "distinct entries collapsed onto one color"
    assert not (rows[:, :3].sum(axis=1) == 0).any(), "entry resolved to black"
    assert [list(row[:3]) for row in rows] == [
        list(channels.palette_rows_rgba8([c], 1)[0][:3]) for c in DEFAULT_PALETTE[:3]
    ]


def test_native_raster_categorical_fallback_is_indexed_and_warns() -> None:
    trace = {
        "color": {
            "mode": "categorical",
            "buf": 0,
            "palette": ["var(--a)", "var(--b)", "var(--c)"],
        }
    }
    codes = np.arange(3, dtype=np.uint8)

    with pytest.warns(RuntimeWarning, match="resolve only in a browser"):
        rgba = _raster._trace_paint_rgba(trace, "color", 3, "#000000", lambda _index: codes)

    assert np.rint(rgba * 255).astype(np.uint8).tolist() == [
        list(channels.palette_rows_rgba8([color], 1)[0]) for color in DEFAULT_PALETTE[:3]
    ]


def test_native_raster_literal_categorical_palette_never_warns() -> None:
    trace = {"color": {"mode": "categorical", "buf": 0, "palette": PALETTE[:3]}}
    codes = np.arange(3, dtype=np.uint8)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        rgba = _raster._trace_paint_rgba(trace, "color", 3, "#000000", lambda _index: codes)

    assert np.rint(rgba * 255).astype(np.uint8).tolist() == [
        list(row) for row in channels.palette_rows_rgba8(PALETTE[:3], 3)
    ]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [("tomato", "#ff6347"), ("rgb(14,165,233)", "#0ea5e9"), ("hsl(280 80% 60%)", "#b447eb")],
)
def test_palette_entries_ship_resolved_to_hex(entry, expected):
    # The client's only cascade-free decode is `hexColor`. Shipping "tomato"
    # verbatim sent it to a getComputedStyle probe, which returns "" while the
    # root is still detached (notebook webviews attach asynchronously) -> black,
    # and permanently so, because nothing rebuilds a cached palette LUT.
    x, y = _xy()
    cats = np.array(["a", "b"])[np.arange(len(x)) % 2]
    chart = xy.scatter_chart(xy.scatter(x, y, color=cats), xy.theme(palette=[entry, "#ffffff"]))
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["color"]["palette"][0] == expected
    assert spec["palette"][0] == expected
    assert all(color.startswith("#") for color in spec["palette"]), (
        "a non-hex palette entry reached the wire; the client would have to resolve "
        "it through the DOM"
    )


def test_series_colors_from_the_palette_also_ship_as_hex():
    chart = xy.line_chart(
        *[xy.line([0, 1], [0, i], name=f"s{i}") for i in range(3)],
        xy.theme(palette=["tomato", "rgb(14,165,233)", "hsl(280 80% 60%)"]),
    )
    spec, _ = chart.figure().build_payload()
    assert [t["style"]["color"] for t in spec["traces"]] == ["#ff6347", "#0ea5e9", "#b447eb"]


def test_translucent_palette_entries_keep_their_alpha_in_hex():
    chart = xy.line_chart(
        xy.line([0, 1], [0, 1], name="a"), xy.theme(palette=["rgba(255,0,0,0.5)"])
    )
    spec, _ = chart.figure().build_payload()
    assert spec["traces"][0]["style"]["color"] == "#ff000080"


def test_a_literal_palette_resolves_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        rows = channels.palette_rows_rgba8(PALETTE, len(PALETTE))
    assert rows.shape == (len(PALETTE), 4)
    assert list(rows[0][:3]) == [56, 189, 248]  # #38bdf8


def test_a_fully_literal_palette_never_warns():
    rng = np.random.default_rng(2)
    n = 260_000
    x, y = rng.normal(size=n), rng.normal(size=n)
    cats = np.array(["a", "b"])[rng.integers(0, 2, n)]
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        xy.scatter_chart(
            xy.scatter(x, y, color=cats, density=True), xy.theme(palette=PALETTE)
        ).figure().build_payload()


@pytest.mark.parametrize("value", ["#f00", [], ["not a color"], 5])
def test_bad_palettes_raise(value):
    with pytest.raises(ValueError):
        xy.theme(palette=value)


# --- axis visibility shorthands ----------------------------------------------


def test_show_false_hides_line_ticks_text_and_grid():
    assert xy.x_axis(show=False).style == {
        "axis_width": 0,
        "axis_color": "#00000000",
        "tick_length": 0,
        "tick_width": 0,
        "grid_opacity": 0,
        "tick_label_color": "#00000000",
        "label_color": "#00000000",
    }


def test_ticks_off_hides_the_marks_without_erasing_the_labels():
    # Regression: `ticks=False` used to blank `tick_color`, and every renderer
    # resolves the tick-LABEL color as tick_label_color -> tick_color, so the
    # labels vanished with the marks -- the opposite of the documented meaning.
    import io

    Image = pytest.importorskip("PIL.Image")

    def pixels(*axis):
        chart = xy.scatter_chart(xy.scatter([1, 2, 3], [1, 2, 3]), *axis, width=420, height=260)
        return np.array(Image.open(io.BytesIO(chart.to_png())).convert("RGB")).astype(int)

    base = pixels()
    no_ticks = pixels(xy.x_axis(ticks=False))
    no_text = pixels(xy.x_axis(text=False))
    changed = lambda other: int((np.abs(base - other).sum(axis=2) > 12).sum())  # noqa: E731
    # Both do something, and removing the text moves far more pixels than
    # removing the marks -- i.e. ticks=False did not take the labels with it.
    assert 0 < changed(no_ticks) < changed(no_text) / 4
    assert "#00000000" not in str(xy.x_axis(ticks=False).style)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"grid": False}, {"grid_opacity": 0}),
        ({"line": False}, {"axis_width": 0, "axis_color": "#00000000"}),
        ({"ticks": False}, {"tick_length": 0, "tick_width": 0}),
        ({"text": False}, {"tick_label_color": "#00000000", "label_color": "#00000000"}),
    ],
)
def test_each_switch_touches_only_its_own_properties(kwargs, expected):
    assert xy.y_axis(**kwargs).style == expected


def test_a_narrow_switch_overrides_show_in_both_directions():
    grid_only = xy.y_axis(show=False, grid=True).style
    assert "grid_opacity" not in grid_only
    assert grid_only["axis_width"] == 0
    only_grid_hidden = xy.y_axis(show=True, grid=False).style
    assert only_grid_hidden == {"grid_opacity": 0}


def test_explicit_style_wins_over_a_switch():
    style = xy.x_axis(show=False, style={"tick_label_color": "#ff0000"}).style
    assert style["tick_label_color"] == "#ff0000"
    assert style["label_color"] == "#00000000"


def test_switches_default_to_no_style_at_all():
    assert xy.x_axis().style == {}
    assert xy.y_axis(show=True).style == {}


@pytest.mark.parametrize("switch", ["show", "line", "ticks", "grid", "text"])
def test_switches_are_strictly_boolean(switch):
    with pytest.raises(ValueError, match="must be True or False"):
        xy.x_axis(**{switch: 1})


def test_text_switch_does_not_collide_with_tick_labels():
    axis = xy.x_axis(tick_values=(0.0, 1.0), tick_labels=("lo", "hi"), text=False)
    assert axis.tick_labels == ["lo", "hi"]
    assert axis.style["tick_label_color"] == "#00000000"
