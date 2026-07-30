"""Sankey and the ribbon primitive: layout, wire shape, and cross-renderer
geometry.

The layout is pinned by direct assertions on `_sankey.compute_layout`; the
geometry is pinned by comparing both static exporters against
`_scene.ribbon_polygon`, the single reference the contract names — the failure
mode being guarded is a renderer quietly keeping its own curve (or falling
through to the rect family, which shares the ribbon's column names).
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

import pytest

import xy
from xy._figure import Figure
from xy._sankey import compute_layout
from xy._scene import RIBBON_STEPS, ribbon_polygon

LINKS = [
    ("Inflow", "Equities", 78000.0),
    ("Inflow", "Bonds", 46000.0),
    ("Inflow", "Cash", 24000.0),
    ("Equities", "Growth", 61000.0),
    ("Equities", "Income", 17000.0),
    ("Bonds", "Income", 28000.0),
    ("Bonds", "Reserve", 18000.0),
    ("Cash", "Reserve", 24000.0),
]


# -- layout ------------------------------------------------------------------


def test_layers_follow_the_longest_path() -> None:
    layout = compute_layout(LINKS)
    layer = {n.name: n.layer for n in layout.nodes}
    assert layer["Inflow"] == 0
    assert layer["Equities"] == layer["Bonds"] == layer["Cash"] == 1
    assert layer["Growth"] == layer["Income"] == layer["Reserve"] == 2
    assert layout.layers == 3


def test_node_value_is_max_of_inflow_and_outflow() -> None:
    layout = compute_layout([("a", "b", 5.0), ("b", "c", 9.0)])
    value = {n.name: n.value for n in layout.nodes}
    # b receives 5 but emits 9: it must be tall enough for what it emits.
    assert value["b"] == 9.0


def test_every_ribbon_is_equal_width_at_both_ends() -> None:
    layout = compute_layout(LINKS)
    for link in layout.links:
        source_h = link.source_y1 - link.source_y0
        target_h = link.target_y1 - link.target_y0
        assert source_h == pytest.approx(target_h, abs=1e-12)


def test_outgoing_stacks_fill_each_node_exactly() -> None:
    layout = compute_layout(LINKS)
    for node in layout.nodes:
        spans = sorted(
            (layout.links[i].source_y0, layout.links[i].source_y1) for i in node.outgoing
        )
        if not spans:
            continue
        assert spans[0][0] == pytest.approx(node.y0)
        assert spans[-1][1] == pytest.approx(node.y1)
        for (_, top_end), (next_start, _) in pairwise(spans):
            assert top_end == pytest.approx(next_start)


def test_cycles_are_refused_by_name() -> None:
    with pytest.raises(ValueError, match=r"cycle.*'a'.*'b'|cycle through \['a', 'b'\]"):
        compute_layout([("a", "b", 1.0), ("b", "a", 1.0)])


def test_right_alignment_hangs_every_node_by_its_distance_to_a_sink() -> None:
    # Two disjoint chains of different length: the short one starts late under
    # `right`, is stretched by its sink under `justify`, and stays at the far
    # left under `left`.
    links = [("a", "b", 1.0), ("b", "c", 1.0), ("x", "y", 1.0)]
    for align, expected in (
        ("left", {"x": 0, "y": 1}),
        ("justify", {"x": 0, "y": 2}),
        ("right", {"x": 1, "y": 2}),
    ):
        layer = {n.name: n.layer for n in compute_layout(links, align=align).nodes}
        assert (layer["a"], layer["b"], layer["c"]) == (0, 1, 2), align
        assert {name: layer[name] for name in expected} == expected, align


def test_center_alignment_moves_source_only_nodes_toward_their_targets() -> None:
    links = [("a", "b", 1.0), ("b", "c", 1.0), ("late", "c", 1.0)]
    layer = {n.name: n.layer for n in compute_layout(links, align="center").nodes}
    assert layer == {"a": 0, "b": 1, "late": 1, "c": 2}
    # `left` keeps the longest-path layering, so `late` opens at the far left.
    layer = {n.name: n.layer for n in compute_layout(links, align="left").nodes}
    assert layer["late"] == 0


def test_overpacked_node_padding_is_refused_by_name() -> None:
    # Three nodes in a layer with padding 0.6 would need 1.2 of a 1.0 box for
    # the gaps alone; a negative room flips the shared scale into inverted
    # spans, so it is refused rather than drawn wrong.
    with pytest.raises(ValueError, match=r"node_padding 0\.6 leaves no room .* layer 1 holds 3"):
        compute_layout(LINKS, node_padding=0.6)


@pytest.mark.parametrize(
    ("links", "message"),
    [
        ([("a", "a", 1.0)], "connects 'a' to itself"),
        ([("a", "b", 1.0), ("a", "b", 2.0)], "duplicate link"),
        ([("a", "b", -1.0)], "finite and non-negative"),
        ([], "at least one link"),
    ],
)
def test_bad_links_are_refused(links: list, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        compute_layout(links)


def test_unknown_node_in_explicit_node_list_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown node 'c'"):
        compute_layout([("a", "c", 1.0)], nodes=["a", "b"])


# -- wire --------------------------------------------------------------------


def _ribbon_figure() -> Figure:
    f = Figure(width=420, height=300)
    f.ribbon(
        [0.1, 0.1],
        [0.9, 0.9],
        [0.0, 0.5],
        [0.4, 0.9],
        [0.2, 0.6],
        [0.55, 0.95],
        color=["#7c3aed", "#0891b2"],
        color_target=["#34d399", "#f59e0b"],
    )
    return f


def test_ribbon_ships_direct_with_both_paints() -> None:
    spec, _ = _ribbon_figure().build_payload_split()
    t = spec["traces"][0]
    assert t["kind"] == "ribbon"
    assert t["tier"] == "direct"
    for key in ("x0", "x1", "y0", "y1", "target_y0", "target_y1"):
        assert key in t
    assert t["color"]["mode"] == "direct_rgba"
    assert t["color_target"]["mode"] == "direct_rgba"


def test_flat_ribbon_ships_no_target_channel() -> None:
    f = Figure(width=300, height=200)
    f.ribbon([0.0], [1.0], [0.0], [0.3], [0.2], [0.5], color="#7c3aed")
    spec, _ = f.build_payload_split()
    assert "color_target" not in spec["traces"][0]


def test_ribbon_autorange_covers_both_spans() -> None:
    spec, _ = _ribbon_figure().build_payload_split()
    lo, hi = spec["y_axis"]["range"]
    # Data spans 0.0..0.95 across the four span edges; the two ridden in the
    # x/y slots must reach autorange or the far ends clip.
    assert lo <= 0.0 and hi >= 0.95


def test_sankey_chart_builds_ribbon_traces_only() -> None:
    chart = xy.sankey_chart(LINKS, width=680, height=420)
    figure = chart.figure()
    spec, _ = figure.build_payload_split()
    assert [t["kind"] for t in spec["traces"]] == ["ribbon", "ribbon"]
    assert spec["traces"][0]["tooltip_rows"][0] == {
        "source": "Inflow",
        "target": "Equities",
        "value": 78000.0,
    }
    assert spec["traces"][1]["tooltip_rows"][0] == {
        "node": "Inflow",
        "value": 148000.0,
    }
    exact_link = figure.pick(0, 0)
    assert exact_link is not None
    assert exact_link["source"] == "Inflow"
    assert exact_link["target"] == "Equities"
    assert exact_link["value"] == 78000.0
    exact_node = figure.pick(1, 0)
    assert exact_node is not None
    assert exact_node["node"] == "Inflow"
    assert exact_node["value"] == 148000.0
    # Semantic rows REPLACE the coordinate projection: the x/y slots hold a
    # ribbon's internal placement (its target span), never a data readout.
    for row in (exact_link, exact_node):
        assert "x" not in row and "y" not in row
    assert spec["protocol"] == 11


# -- golden geometry ---------------------------------------------------------


def test_svg_ribbon_is_the_contract_cubic_not_a_rectangle() -> None:
    """A ribbon ships x0/x1/y0/y1, so the rect fall-through would happily draw
    it as a rectangle; the dispatch order is all that prevents it."""
    doc = _ribbon_figure().to_image(format="svg").decode()
    paths = re.findall(r'<path d="(M [^"]+)"', doc)
    assert len(paths) == 2
    for d in paths:
        assert d.count(" C ") == 2, "each band must be two cubics, not line segments"
    assert "userSpaceOnUse" in doc, "flow gradients are two-point user-space gradients"


def test_svg_cubic_control_points_sit_at_the_horizontal_midpoint() -> None:
    doc = _ribbon_figure().to_image(format="svg").decode()
    d = re.findall(r'<path d="(M [^"]+)"', doc)[0]
    start = re.match(r"M ([\d.eE+-]+) ([\d.eE+-]+) C ([\d.eE+-]+)", d)
    assert start is not None
    move_x = float(start.group(1))
    control_x = float(start.group(3))
    end_x = float(re.findall(r"C [^C]*? ([\d.eE+-]+) [\d.eE+-]+ L", d + " L")[0].split()[-1])
    # curveBumpX: the first control point's x is the midpoint of the faces.
    assert control_x == pytest.approx((move_x + end_x) / 2.0, abs=0.6)


def test_raster_ink_lands_on_the_reference_polygon() -> None:
    """The PNG must have ink where `_scene.ribbon_polygon` says the band runs,
    and none at the straight-chord midpoint the cubic pulls away from."""
    from test_png_export import _decode_rgba

    f = Figure(width=400, height=300)
    f.set_axis("x", domain=(0.0, 1.0), tick_label_strategy="none")
    f.set_axis("y", domain=(0.0, 1.0), tick_label_strategy="none")
    f.ribbon([0.05], [0.95], [0.05], [0.25], [0.7], [0.9], color="#000000", opacity=1.0)
    pixels = _decode_rgba(f.to_image(format="png", scale=1))

    from xy._svg import _Scale, layout

    spec, _ = f.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    sx = _Scale(spec["x_axis"], plot["x"], plot["x"] + plot["w"])
    sy = _Scale(spec["y_axis"], plot["y"] + plot["h"], plot["y"])
    poly = ribbon_polygon(0.05, 0.95, 0.05, 0.25, 0.7, 0.9)
    mid = poly[RIBBON_STEPS // 2]  # a point on the upper edge, mid-flow
    upper_px, upper_py = float(sx(mid[0])), float(sy(mid[1]))
    # 3px inside the band, measured downward from the upper edge (y grows up
    # in data space, down in screen space).
    inside = pixels[int(upper_py) + 3, int(upper_px), 0]
    assert inside < 128, "no ink just inside the band's upper edge"

    # The straight chord between the two upper corners passes well above the
    # bump cubic at mid-flow; a renderer that drew chords (or a rectangle)
    # would put ink here.
    chord_y = float(sy((0.25 + 0.9) / 2.0))
    off_band = pixels[int(chord_y) - 8, int(upper_px), 0]
    assert off_band >= 128, "ink on the straight chord: the cubic was not drawn"


def test_exporters_share_the_reference_flattening() -> None:
    """`ribbon_polygon` is the single geometry source; its ends must be exactly
    the four corners and its width exact at every step."""
    poly = ribbon_polygon(0.0, 1.0, 0.1, 0.3, 0.6, 0.8)
    assert poly.shape == (2 * (RIBBON_STEPS + 1), 2)
    upper, lower = poly[: RIBBON_STEPS + 1], poly[RIBBON_STEPS + 1 :][::-1]
    assert tuple(upper[0]) == pytest.approx((0.0, 0.3))
    assert tuple(upper[-1]) == pytest.approx((1.0, 0.8))
    assert tuple(lower[0]) == pytest.approx((0.0, 0.1))
    assert tuple(lower[-1]) == pytest.approx((1.0, 0.6))
    for i in range(RIBBON_STEPS + 1):
        assert upper[i][0] == pytest.approx(lower[i][0], abs=1e-12)


def test_live_ribbons_use_smooth_antialiased_edges() -> None:
    """Wide, high-contrast flows must not expose polygon-strip corners."""
    assert RIBBON_STEPS >= 96
    root = Path(__file__).resolve().parents[1]
    shader = (root / "js/src/40_gl.ts").read_text(encoding="utf-8")
    assert "export const RIBBON_STEPS = 96" in shader
    assert "fwidth(v_side)" in shader
    assert "u_opacity * coverage" in shader
    # The outline clause of the ribbon contract: the client draws stroke /
    # stroke-width / stroke-opacity, closes the band over its two end faces,
    # and matches the band's own fill when no stroke colour was declared.
    ribbon_fs = shader.split("RIBBON_FS", 1)[1].split("MESH_VS", 1)[0]
    assert "u_strokeWidth" in ribbon_fs
    assert "u_strokeOpacity" in ribbon_fs
    assert "fwidth(v_t)" in ribbon_fs, "the end faces must join the outline distance"
    assert "u_strokeMode == 1 ? v_rgba0" in ribbon_fs, "match-fill outline missing"


def test_svg_ribbon_interpolates_endpoint_alpha_per_stop() -> None:
    """Ends differing only in alpha still ramp: the gradient carries per-stop
    stop-opacity instead of flattening both ends to the source's alpha."""
    f = Figure(width=420, height=300)
    f.ribbon(
        [0.1],
        [0.9],
        [0.3],
        [0.5],
        [0.4],
        [0.6],
        color="rgba(20,40,60,0.9)",
        color_target="rgba(20,40,60,0.2)",
    )
    doc = f.to_image(format="svg").decode()
    assert 'stop-opacity="0.9"' in doc
    assert 'stop-opacity="0.2"' in doc
    band = re.search(r'<path d="M [^"]+" fill="url\(#[^"]+\)"([^>]*)/>', doc)
    assert band is not None
    assert "fill-opacity" not in band.group(1), "path-level opacity would flatten the ramp"


def test_raster_ribbon_ramps_alpha_along_the_flow() -> None:
    """The PNG's ink must fade with the target end's alpha, matching the SVG's
    per-stop opacity and the client's per-fragment RGBA mix."""
    from test_png_export import _decode_rgba

    f = Figure(width=400, height=300)
    f.set_axis("x", domain=(0.0, 1.0), tick_label_strategy="none")
    f.set_axis("y", domain=(0.0, 1.0), tick_label_strategy="none")
    f.ribbon(
        [0.05],
        [0.95],
        [0.4],
        [0.6],
        [0.4],
        [0.6],
        color="rgba(0,0,0,1.0)",
        color_target="rgba(0,0,0,0.08)",
    )
    pixels = _decode_rgba(f.to_image(format="png", scale=1))

    from xy._svg import _Scale, layout

    spec, _ = f.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    sx = _Scale(spec["x_axis"], plot["x"], plot["x"] + plot["w"])
    sy = _Scale(spec["y_axis"], plot["y"] + plot["h"], plot["y"])
    mid_row = int(float(sy(0.5)))
    source_ink = pixels[mid_row, int(float(sx(0.1))), 0]
    target_ink = pixels[mid_row, int(float(sx(0.9))), 0]
    assert source_ink < 90, "the source end must stay near-opaque"
    assert target_ink > 180, "the target end must fade over the page"


def test_ribbon_stroke_defaults_to_each_bands_own_colour_in_svg() -> None:
    """`stroke_width` without a stroke colour must still outline, and must
    match EACH band's fill: a per-band ribbon has no single trace colour, so
    one shared fallback would outline every flow in a colour it never uses."""
    f = Figure(width=420, height=300)
    f.ribbon(
        [0.1, 0.1],
        [0.9, 0.9],
        [0.0, 0.5],
        [0.2, 0.7],
        [0.1, 0.6],
        [0.3, 0.8],
        color=["#7c3aed", "#0891b2"],
        stroke_width=2.0,
    )
    doc = f.to_image(format="svg").decode()
    strokes = re.findall(r'<path d="M [^"]+"[^>]*stroke="([^"]+)" stroke-width="2"', doc)
    assert strokes == ["rgb(124,58,237)", "rgb(8,145,178)"], strokes


def test_ribbon_raster_outline_matches_each_bands_own_colour() -> None:
    """The PNG outline follows the band paint too, so an implicit outline is
    the same colour in both exporters rather than one arbitrary fallback."""
    from test_png_export import _decode_rgba

    f = Figure(width=420, height=320)
    f.set_axis("x", domain=(0.0, 1.0), tick_label_strategy="none")
    f.set_axis("y", domain=(0.0, 1.0), tick_label_strategy="none")
    # Two flat bands, well separated, each a saturated primary: the outline
    # pixels must carry the band's own hue, not a shared blue-gray.
    f.ribbon(
        [0.1, 0.1],
        [0.9, 0.9],
        [0.05, 0.6],
        [0.3, 0.85],
        [0.05, 0.6],
        [0.3, 0.85],
        color=["#ff0000", "#00ff00"],
        stroke_width=3.0,
        opacity=1.0,
    )
    pixels = _decode_rgba(f.to_image(format="png", scale=1))
    reds = pixels[:, :, 0].astype(int)
    greens = pixels[:, :, 1].astype(int)
    # A red-dominant and a green-dominant band both present means each band's
    # own paint reached its outline; a shared fallback would tint one of them.
    assert ((reds > 180) & (greens < 90)).any(), "no red band ink"
    assert ((greens > 180) & (reds < 90)).any(), "no green band ink"


def test_ribbon_style_stroke_compiles_to_the_outline_not_the_fill() -> None:
    """style={'stroke': ...} must reach the trace outline; before the ribbon
    kinds joined the stroke target sets it silently repainted the band."""
    from xy import styles

    css = styles.compile_mark_style(
        "ribbon", {"stroke": "#112233", "stroke-width": "2px", "stroke-opacity": 0.5}
    )
    assert css == {"stroke": "#112233", "stroke_width": 2.0, "stroke_opacity": 0.5}

    f = Figure(width=420, height=300)
    f.ribbon(
        [0.1],
        [0.9],
        [0.3],
        [0.5],
        [0.4],
        [0.6],
        color="#7c3aed",
        style={"stroke": "#112233", "stroke-width": 2, "stroke-opacity": 0.5},
    )
    trace_style = f.traces[-1].style
    assert trace_style["stroke"] == "#112233"
    assert trace_style["stroke_width"] == 2.0
    assert trace_style["stroke_opacity"] == 0.5
    doc = f.to_image(format="svg").decode()
    assert 'fill="rgb(124,58,237)"' in doc, "the outline must not repaint the band"
    assert re.search(r'stroke="#112233" stroke-width="2" stroke-opacity="0.5"', doc)
