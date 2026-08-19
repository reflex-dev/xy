"""Funnel charts: stage math, quad geometry, wire shape, labels, and
cross-renderer parity.

The arithmetic and layout are pinned by direct assertions on
`_funnel.compute_stages` / `_funnel.compute_layout`; the geometry is pinned by
comparing both static exporters against `_scene.funnel_quad`, the single
reference the contract names — the failure mode being guarded is a renderer
quietly drawing its own quad (or a funnel entry silently skipped because its
wire columns don't match the rect family's names).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

import xy
from xy import _funnel
from xy._figure import Figure
from xy._funnel import compute_layout, compute_stages, decide_labels
from xy._scene import funnel_quad
from xy.config import PROTOCOL_VERSION
from xy.interaction import row_dict

STAGES = ["Visit", "Signup", "Activate", "Trial", "Pay"]
VALUES = [9800.0, 6200.0, 3100.0, 2200.0, 1450.0]


def _funnel_figure(**kwargs) -> Figure:
    fig = Figure(width=640, height=430)
    fig.funnel(STAGES, VALUES, **kwargs)
    return fig


# -- stage arithmetic --------------------------------------------------------


def test_conversion_and_dropoff_are_numerically_correct() -> None:
    stages = compute_stages(STAGES, VALUES)
    assert [s.value for s in stages] == VALUES
    assert stages[0].share == 1.0
    assert stages[0].prior is None
    assert stages[0].conversion is None
    assert stages[0].dropoff is None
    assert stages[1].share == pytest.approx(6200 / 9800)
    assert stages[1].prior == 9800.0
    assert stages[1].conversion == pytest.approx(6200 / 9800)
    assert stages[1].dropoff == pytest.approx(1 - 6200 / 9800)
    assert stages[4].share == pytest.approx(1450 / 9800)
    assert stages[4].conversion == pytest.approx(1450 / 2200)


def test_increasing_stage_is_allowed_with_conversion_above_one() -> None:
    stages = compute_stages(["a", "b"], [100.0, 120.0])
    assert stages[1].conversion == pytest.approx(1.2)
    assert stages[1].dropoff == pytest.approx(-0.2)


def test_zero_prior_yields_none_ratios_not_inf() -> None:
    stages = compute_stages(["a", "b", "c"], [10.0, 0.0, 5.0])
    assert stages[1].conversion == 0.0
    assert stages[1].dropoff == 1.0
    # c follows a zero stage: value / 0 has no meaning, and must never be inf.
    assert stages[2].conversion is None
    assert stages[2].dropoff is None
    assert all(s.share is not None for s in stages)


def test_zero_first_stage_makes_every_share_undefined() -> None:
    stages = compute_stages(["a", "b"], [0.0, 0.0])
    assert all(s.share is None for s in stages)


def test_repeated_values_are_full_conversion() -> None:
    stages = compute_stages(["a", "b"], [7.0, 7.0])
    assert stages[1].conversion == 1.0
    assert stages[1].dropoff == 0.0


@pytest.mark.parametrize(
    ("names", "values", "message"),
    [
        (["a", "b"], [1.0], "one value per stage"),
        ([], [], "at least one stage"),
        (["a", "a"], [1.0, 2.0], "unique"),
        (["a", "b"], [1.0, -2.0], r"negative value \(-2\)"),
        (["a", "b"], [1.0, float("nan")], "missing value"),
        (["a", "b"], [1.0, float("inf")], "non-finite"),
        (["a", "b"], [1.0, "wat"], "non-numeric"),
    ],
)
def test_bad_stage_values_are_refused_by_name(names, values, message) -> None:
    with pytest.raises(ValueError, match=message):
        compute_stages(names, values)


def test_validation_names_the_offending_stage() -> None:
    with pytest.raises(ValueError, match="'Signup'"):
        compute_stages(["Visit", "Signup"], [10.0, -1.0])


# -- layout ------------------------------------------------------------------


def test_stage_order_is_declared_order_never_sorted() -> None:
    names = ["Zeta", "Alpha", "Mid"]
    layout = compute_layout(names, [3.0, 2.0, 1.0])
    assert [s.name for s in layout.stages] == names
    assert [q.stage for q in layout.quads] == [0, 1, 2]
    # Position along the stage axis follows the declared order exactly.
    assert [q.pos0 for q in layout.quads] == sorted(q.pos0 for q in layout.quads)


def test_area_geometry_tapers_to_the_next_stage() -> None:
    layout = compute_layout(["a", "b", "c"], [10.0, 6.0, 2.0])
    assert layout.quads[0].hi0 == 5.0
    assert layout.quads[0].hi1 == 3.0  # previews b
    assert layout.quads[1].hi0 == 3.0
    assert layout.quads[1].hi1 == 1.0  # previews c
    # Last stage under the default rect neck holds its own width.
    assert layout.quads[2].hi0 == layout.quads[2].hi1 == 1.0
    for q in layout.quads:
        assert q.lo0 == -q.hi0 and q.lo1 == -q.hi1, "segments are centered"


def test_bar_geometry_holds_each_stages_own_width() -> None:
    layout = compute_layout(["a", "b"], [10.0, 6.0], geometry="bar")
    assert layout.quads[0].hi0 == layout.quads[0].hi1 == 5.0
    assert layout.quads[1].hi0 == layout.quads[1].hi1 == 3.0


def test_neck_taper_runs_the_last_stage_to_a_point() -> None:
    layout = compute_layout(["a", "b"], [10.0, 6.0], neck="taper")
    assert layout.quads[1].hi0 == 3.0
    assert layout.quads[1].hi1 == 0.0
    assert layout.quads[1].lo1 == 0.0


def test_default_gaps_resolve_per_geometry() -> None:
    area = compute_layout(["a", "b"], [4.0, 2.0])
    bar = compute_layout(["a", "b"], [4.0, 2.0], geometry="bar")
    assert area.gap == 0.0
    assert bar.gap == 0.2
    # Area segments touch; bar segments leave the bar-chart gap.
    assert area.quads[0].pos1 == area.quads[1].pos0
    assert bar.quads[0].pos1 == pytest.approx(0.4)
    assert bar.quads[1].pos0 == pytest.approx(0.6)


def test_explicit_gap_carves_the_stage_pitch() -> None:
    layout = compute_layout(["a", "b"], [4.0, 2.0], gap=0.5)
    assert layout.quads[0].pos0 == pytest.approx(-0.25)
    assert layout.quads[0].pos1 == pytest.approx(0.25)


def test_min_width_floors_drawn_geometry_only() -> None:
    layout = compute_layout(["a", "b", "c"], [100.0, 0.0, 50.0], min_width=0.1)
    # b draws at the floor (10% of the widest stage), stays hoverable...
    assert layout.quads[1].hi0 == pytest.approx(5.0)
    # ...but its VALUE is untouched everywhere semantic.
    assert layout.stages[1].value == 0.0
    # The taper into b also floors (drawn edges agree between neighbours).
    assert layout.quads[0].hi1 == pytest.approx(5.0)


def test_zero_stage_without_floor_draws_nothing_but_keeps_semantics() -> None:
    layout = compute_layout(["a", "b"], [10.0, 0.0])
    assert layout.quads[1].hi0 == 0.0
    assert layout.stages[1].dropoff == 1.0


def test_taper_neck_beats_the_floor_at_the_spout() -> None:
    # The documented point at the end of a tapered funnel is a point, not an
    # accidentally invisible stage — the floor deliberately does not apply.
    layout = compute_layout(["a", "b"], [10.0, 6.0], neck="taper", min_width=0.1)
    assert layout.quads[1].hi1 == 0.0


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"orientation": "diagonal"}, "orientation"),
        ({"geometry": "cone"}, "geometry"),
        ({"neck": "bulb"}, "neck"),
        ({"neck": "taper", "geometry": "bar"}, "neck applies"),
        ({"gap": 1.0}, "gap"),
        ({"gap": -0.1}, "gap"),
        ({"min_width": 1.5}, "min_width"),
    ],
)
def test_bad_layout_options_are_refused(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        compute_layout(["a", "b"], [2.0, 1.0], **kwargs)


def test_single_stage_funnel_is_legal() -> None:
    layout = compute_layout(["only"], [5.0])
    assert len(layout.quads) == 1
    assert layout.stages[0].conversion is None


# -- labels ------------------------------------------------------------------


def _labels(layout, **kwargs):
    defaults = dict(
        show_values=True,
        show_conversion=True,
        show_dropoff=False,
        value_format="{:,.10g}",
        percent_format="{:.0%}",
        font_size=12.0,
        plot_px=(544.0, 366.0),
    )
    defaults.update(kwargs)
    return decide_labels(layout, **defaults)


def test_wide_stages_label_inside_and_narrow_ones_outside() -> None:
    layout = compute_layout(STAGES, VALUES)
    labels = _labels(layout)
    placement = {label.stage: label.placement for label in labels}
    assert placement[0] == "inside"
    assert placement[1] == "inside"
    assert placement[4] == "outside", "the narrow Pay stage falls outside"
    outside = next(label for label in labels if label.stage == 4)
    assert outside.anchor == "start"
    assert outside.cross > 0.0


def test_labels_hide_when_the_stage_pitch_cannot_hold_a_line() -> None:
    layout = compute_layout(STAGES, VALUES)
    labels = _labels(layout, plot_px=(544.0, 40.0))
    assert {label.placement for label in labels} == {"hidden"}


def test_dropoff_labels_show_the_signed_change() -> None:
    layout = compute_layout(["a", "b", "c"], [100.0, 62.0, 74.4])
    labels = _labels(layout, show_dropoff=True)
    drop = [label for label in labels if label.kind == "dropoff"]
    assert [label.text for label in drop] == ["-38%", "+20%"]
    assert all(label.pos == label.stage - 0.5 for label in drop)


def test_dropoff_after_a_zero_stage_shows_a_dash() -> None:
    layout = compute_layout(["a", "b", "c"], [10.0, 0.0, 5.0])
    labels = _labels(layout, show_dropoff=True)
    drop = [label for label in labels if label.kind == "dropoff"]
    assert drop[1].text == "—"


def test_value_formats_are_honoured() -> None:
    layout = compute_layout(["a"], [1234.5])
    labels = _labels(layout, value_format="{:.1f}", percent_format="{:.1%}")
    assert labels[0].text == "1234.5  100.0%"


def test_funnel_figure_emits_label_annotations_with_contrast_color() -> None:
    fig = _funnel_figure()
    texts = [a for a in fig.annotations if a["kind"] == "text"]
    assert any("9,800" in a["text"] for a in texts)
    inside = next(a for a in texts if "9,800" in a["text"])
    # Inside labels carry an explicit contrast color picked from the fill.
    assert inside["style"]["color"] in {"#1f2430", "#f7f8fa"}
    fig_off = Figure(width=640, height=430)
    fig_off.funnel(STAGES, VALUES, labels=False)
    assert fig_off.annotations == []


# -- the mark and its wire shape ---------------------------------------------


def test_funnel_trace_ships_semantic_quads_direct_tier() -> None:
    fig = _funnel_figure()
    spec, _blob = fig.build_payload()
    entry = spec["traces"][0]
    assert entry["kind"] == "funnel"
    assert entry["tier"] == "direct"
    assert entry["orientation"] == "vertical"
    assert entry["n_marks"] == 5
    for key in ("pos0", "pos1", "lo0", "hi0", "lo1", "hi1"):
        assert isinstance(entry[key], int), f"{key} must be a shipped column index"
    rows = entry["tooltip_rows"]
    assert [row["stage"] for row in rows] == STAGES
    assert (
        rows[1]
        | {
            "stage": "Signup",
            "value": 6200.0,
            "share": pytest.approx(6200 / 9800),
            "prior": 9800.0,
            "conversion": pytest.approx(6200 / 9800),
            "dropoff": pytest.approx(1 - 6200 / 9800),
        }
        == rows[1]
    )


def test_categorical_palette_follows_declared_stage_order() -> None:
    """Factorization sorts labels alphabetically; the funnel must not — stage 0
    wears palette color 0 even when its name sorts last."""
    fig = Figure(width=400, height=300)
    fig.funnel(["Zeta", "Alpha"], [10.0, 5.0])
    channel = fig.traces[0].color_ch
    assert channel.mode == "categorical"
    assert channel.categories == ["Zeta", "Alpha"]
    assert list(channel.codes) == [0, 1]
    assert channel.palette[0] == fig.palette_color(0)


def test_explicit_colors_pin_by_position_and_validate_length() -> None:
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b"], [2.0, 1.0], colors=["#ff0000", "#00ff00"])
    assert fig.traces[0].color_ch.palette == ["#ff0000", "#00ff00"]
    with pytest.raises(ValueError, match="one entry per stage"):
        Figure(width=400, height=300).funnel(["a", "b"], [2.0, 1.0], colors=["#ff0000"])
    with pytest.raises(ValueError, match="color= or colors=, not both"):
        Figure(width=400, height=300).funnel(
            ["a", "b"], [2.0, 1.0], color="#fff", colors=["#ff0000", "#00ff00"]
        )


def test_constant_color_ships_a_constant_channel() -> None:
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b"], [2.0, 1.0], color="#123456")
    assert fig.traces[0].color_ch.mode == "constant"
    assert fig.traces[0].color_ch.constant == "#123456"


def test_stage_axis_is_categorical_with_declared_labels() -> None:
    fig = _funnel_figure()
    spec, _ = fig.build_payload()
    assert spec["y_axis"]["kind"] == "category"
    assert spec["y_axis"]["categories"] == STAGES
    fig_h = Figure(width=640, height=430)
    fig_h.funnel(STAGES, VALUES, orientation="horizontal")
    spec_h, _ = fig_h.build_payload()
    assert spec_h["x_axis"]["kind"] == "category"
    assert spec_h["x_axis"]["categories"] == STAGES


def test_horizontal_orientation_transposes_the_slots() -> None:
    fig_v = Figure(width=400, height=300)
    fig_v.funnel(["a", "b"], [4.0, 2.0])
    fig_h = Figure(width=400, height=300)
    fig_h.funnel(["a", "b"], [4.0, 2.0], orientation="horizontal")
    tv, th = fig_v.traces[0], fig_h.traces[0]
    # Vertical: stage edges ride y0/y1; horizontal: they ride x0/x1.
    assert list(tv.y0.values) == list(th.x0.values)
    assert list(tv.x0.values) == list(th.y0.values)


def test_autorange_covers_the_widest_stage_on_the_cross_axis() -> None:
    fig = _funnel_figure()
    t = fig.traces[0]
    columns = fig._range_columns(t, "x")
    lo = min(float(c.values.min()) for c in columns)
    hi = max(float(c.values.max()) for c in columns)
    assert lo == pytest.approx(-4900.0)
    assert hi == pytest.approx(4900.0)
    # The stage axis ranges over the quad edges, not the trailing cross edges.
    stage_cols = fig._range_columns(t, "y")
    assert len(stage_cols) == 2


def test_missing_stage_or_value_is_refused_with_usage() -> None:
    with pytest.raises(ValueError, match="funnel needs stage names and values"):
        Figure(width=400, height=300).funnel(None, None)


def test_per_stage_style_scalars_are_refused_as_arrays() -> None:
    with pytest.raises(ValueError, match="per-trace"):
        Figure(width=400, height=300).funnel(["a", "b"], [2.0, 1.0], opacity=[0.5, 1.0])
    with pytest.raises(ValueError, match="per-trace"):
        Figure(width=400, height=300).funnel(["a", "b"], [2.0, 1.0], stroke_width=[1.0, 2.0])


def test_failed_funnel_rolls_back_the_figure() -> None:
    fig = Figure(width=400, height=300)
    with pytest.raises(ValueError):
        fig.funnel(["a", "b"], [1.0, -1.0])
    assert fig.traces == []
    assert fig.annotations == []
    assert "y" not in fig._axis_categories


# -- events ------------------------------------------------------------------


def test_exact_pick_returns_stage_semantics_not_placement() -> None:
    fig = _funnel_figure()
    row = row_dict(fig, fig.traces[0], 2)
    assert row["stage"] == "Activate"
    assert row["value"] == 3100.0
    assert row["prior"] == 6200.0
    assert row["conversion"] == pytest.approx(3100 / 6200)
    assert row["dropoff"] == pytest.approx(0.5)
    assert "x" not in row, "geometry slots are placement, not readout"


def test_pick_ratios_after_zero_stage_are_json_null_not_inf() -> None:
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b", "c"], [10.0, 0.0, 5.0])
    row = row_dict(fig, fig.traces[0], 2)
    assert row["conversion"] is None
    assert row["dropoff"] is None


# -- keys and animation ------------------------------------------------------


def test_stable_keys_attach_for_key_matched_animation() -> None:
    chart = xy.funnel_chart(
        xy.funnel(
            stage=STAGES,
            value=VALUES,
            key=STAGES,
            animation=xy.animation(match="key"),
        ),
    )
    fig = chart.figure()
    funnel_traces = [t for t in fig.traces if t.kind == "funnel"]
    assert funnel_traces[0].transition_keys is not None
    assert len(funnel_traces[0].transition_keys) == 5


# -- composition surface -----------------------------------------------------


def test_funnel_chart_positional_form_builds_the_mark() -> None:
    fig = xy.funnel_chart(STAGES, VALUES).figure()
    kinds = [t.kind for t in fig.traces]
    assert kinds == ["funnel"]


def test_funnel_chart_hides_the_cross_axis_and_reverses_the_stage_axis() -> None:
    spec, _ = xy.funnel_chart(STAGES, VALUES).figure().build_payload()
    # A hidden axis compiles to fully transparent chrome, not a boolean.
    assert spec["x_axis"]["style"]["axis_color"] == "#00000000"
    assert spec["x_axis"]["style"]["tick_label_color"] == "#00000000"
    assert spec["y_axis"]["reverse"] is True
    assert spec["show_legend"] is False
    spec_h, _ = xy.funnel_chart(STAGES, VALUES, orientation="horizontal").figure().build_payload()
    assert spec_h["y_axis"]["style"]["axis_color"] == "#00000000"
    assert spec_h["x_axis"].get("reverse", False) is False


def test_funnel_chart_forwards_mark_kwargs_and_rejects_conflicts() -> None:
    fig = xy.funnel_chart(STAGES, VALUES, geometry="bar", gap=0.4).figure()
    t = fig.traces[0]
    quad_span = float(t.y1.values[0] - t.y0.values[0])
    assert quad_span == pytest.approx(0.6)
    with pytest.raises(ValueError, match="positional stages and stage="):
        xy.funnel_chart(STAGES, VALUES, stage=STAGES)


def test_funnel_chart_accepts_an_explicit_mark_child() -> None:
    fig = xy.funnel_chart(
        xy.funnel(stage=["a", "b"], value=[2.0, 1.0], orientation="horizontal"),
    ).figure()
    assert [t.kind for t in fig.traces] == ["funnel"]
    spec, _ = fig.build_payload()
    assert spec["y_axis"]["style"]["axis_color"] == "#00000000", (
        "orientation read from the child mark"
    )


def test_funnel_resolves_columns_from_data() -> None:
    data = {"step": ["a", "b"], "users": [4.0, 3.0], "id": ["a", "b"]}
    fig = xy.funnel_chart(data=data, stage="step", value="users", key="id").figure()
    t = fig.traces[0]
    assert t.kind == "funnel"
    assert t.tooltip_rows[0]["value"] == 4.0


# -- exports -----------------------------------------------------------------


def test_svg_funnel_is_four_corner_paths_with_stage_fills() -> None:
    doc = _funnel_figure().to_image(format="svg").decode()
    paths = re.findall(r'<path d="(M [^"]+Z)" fill="(rgb\([^)]+\))"', doc)
    assert len(paths) >= 5
    quad_paths = [p for p in paths if p[0].count(" L ") == 3]
    assert len(quad_paths) == 5, "each stage is one closed 4-corner path"
    fills = [p[1] for p in quad_paths]
    assert len(set(fills)) == 5, "each stage wears its own palette color"
    for d, _fill in quad_paths:
        assert " C " not in d, "funnel edges are straight, never cubics"


def test_svg_corners_match_the_scene_reference() -> None:
    fig = Figure(width=400, height=300)
    fig.set_axis("x", domain=(-6.0, 6.0), tick_label_strategy="none")
    fig.set_axis("y", domain=(-0.5, 1.5), tick_label_strategy="none")
    fig.funnel(["a", "b"], [10.0, 6.0], labels=False)
    doc = fig.to_image(format="svg").decode()

    from xy._svg import _Scale, layout

    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    sx = _Scale(spec["x_axis"], plot["x"], plot["x"] + plot["w"])
    sy = _Scale(spec["y_axis"], plot["y"] + plot["h"], plot["y"])
    expected = funnel_quad(
        float(sy(-0.5)),
        float(sy(0.5)),
        float(sx(-5.0)),
        float(sx(5.0)),
        float(sx(-3.0)),
        float(sx(3.0)),
        False,
    )
    d = re.findall(r'<path d="(M [^"]+Z)"', doc)[0]
    numbers = [float(v) for v in re.findall(r"[-\d.eE+]+", d)]
    corners = np.array(numbers, dtype=np.float64).reshape(4, 2)
    assert corners == pytest.approx(np.asarray(expected), abs=0.51)


def test_raster_ink_lands_on_the_reference_quad() -> None:
    """The PNG must have ink inside the taper and none outside the slanted
    edge — a renderer that fell through to the rect family would fill the
    corner the taper cuts away."""
    from test_png_export import _decode_rgba

    fig = Figure(width=400, height=300)
    fig.set_axis("x", domain=(-6.0, 6.0), tick_label_strategy="none")
    fig.set_axis("y", domain=(-0.5, 1.5), tick_label_strategy="none")
    fig.funnel(["a", "b"], [10.0, 2.0], color="#000000", labels=False, gap=0.0)
    pixels = _decode_rgba(fig.to_image(format="png", scale=1))

    from xy._svg import _Scale, layout

    spec, _ = fig.build_payload_split()
    _w, _h, _c, plot = layout(spec)
    sx = _Scale(spec["x_axis"], plot["x"], plot["x"] + plot["w"])
    sy = _Scale(spec["y_axis"], plot["y"] + plot["h"], plot["y"])
    # Mid-height of stage 0 (data y = 0): the taper narrows 5 -> 1, so the
    # half-width at the segment's own middle is 3.
    mid_y = int(float(sy(0.0)))
    inside_x = int(float(sx(2.5)))
    outside_x = int(float(sx(4.4)))
    assert pixels[mid_y, inside_x, 0] < 128, "ink inside the taper"
    assert pixels[mid_y, outside_x, 0] >= 128, "no ink outside the slanted edge"
    assert pixels[mid_y, int(float(sx(-4.4))), 0] >= 128, "symmetric on the left"


def test_exporters_share_the_reference_quad() -> None:
    quad = funnel_quad(0.0, 1.0, -5.0, 5.0, -3.0, 3.0, False)
    assert quad.shape == (4, 2)
    # A=(lo0@pos0) B=(hi0@pos0) C=(hi1@pos1) D=(lo1@pos1).
    assert quad.tolist() == [[-5.0, 0.0], [5.0, 0.0], [3.0, 1.0], [-3.0, 1.0]]
    horizontal = funnel_quad(0.0, 1.0, -5.0, 5.0, -3.0, 3.0, True)
    assert horizontal.tolist() == [[0.0, -5.0], [0.0, 5.0], [1.0, 3.0], [1.0, -3.0]]


def test_funnel_svg_stroke_defaults_to_each_stages_own_fill() -> None:
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b"], [4.0, 2.0], stroke_width=2.0, labels=False)
    doc = fig.to_image(format="svg").decode()
    quads = re.findall(r'<path d="M [^"]+Z" fill="(rgb\([^)]+\))" stroke="(rgb\([^)]+\))"', doc)
    assert len(quads) == 2
    for fill, stroke in quads:
        assert fill == stroke, "edgecolors='face': the outline matches the fill"


def test_protocol_version_carries_the_funnel_kind() -> None:
    # markOf() falls back to scatter for unknown kinds, so an old client would
    # silently render funnel quads as a point cloud; the handshake must fail
    # instead (the same tripwire the ribbon and polar kinds pinned).
    assert PROTOCOL_VERSION >= 13


# -- styling surface ---------------------------------------------------------


def test_funnel_style_surface_is_the_ribbon_contract() -> None:
    """Per-stage paint is a channel, so `fill` is absent from the property set
    and refuses with the supported list rather than silently painting one
    color across per-stage geometry."""
    with pytest.raises(ValueError, match="funnel supports: fill-opacity, opacity"):
        xy.funnel_chart(xy.funnel(stage=["a"], value=[1.0], style={"fill": "#ff0000"})).figure()
    with pytest.raises(ValueError, match="border-radius"):
        xy.funnel_chart(xy.funnel(stage=["a"], value=[1.0], style={"border-radius": 4})).figure()


def test_mark_style_compiles_into_both_static_exports() -> None:
    fig = xy.funnel_chart(
        xy.funnel(
            stage=["A", "B"],
            value=[4.0, 2.0],
            style={"stroke": "#123456", "stroke-width": 3, "fill-opacity": 0.8},
        ),
    ).figure()
    doc = fig.to_svg()
    assert 'stroke="#123456"' in doc
    assert 'fill-opacity="0.8"' in doc


def test_theme_palette_mapping_pins_stage_colors_by_name() -> None:
    fig = xy.funnel_chart(
        ["Visit", "Signup", "Pay"],
        [10.0, 6.0, 2.0],
        xy.theme(palette={"Pay": "#f4a300", "Visit": "#3b82f6", "Signup": "#10b981"}),
    ).figure()
    channel = fig.traces[0].color_ch
    assert channel.categories == ["Visit", "Signup", "Pay"]
    assert channel.palette == ["#3b82f6", "#10b981", "#f4a300"]


def test_color_shaped_stage_names_do_not_replace_the_trace_name() -> None:
    """The mapped-palette fallback iterates CSS-color-shaped stage names but
    must not shadow the already validated series name."""
    fig = xy.funnel_chart(
        ["red", "blue"],
        [4.0, 2.0],
        xy.theme(palette={"red": "#dc2626", "blue": "#2563eb"}),
        name="pipeline",
    ).figure()
    assert fig.traces[0].name == "pipeline"
    assert fig.traces[0].color_ch.palette == ["#dc2626", "#2563eb"]


def test_chart_class_names_reach_the_slot_spec() -> None:
    spec, _ = (
        xy.funnel_chart(
            ["a", "b"],
            [2.0, 1.0],
            class_names={
                "title": "text-xl font-semibold",
                "annotation_label": "tabular-nums",
                "tooltip": "rounded-xl",
            },
            title="t",
        )
        .figure()
        .build_payload()
    )
    assert spec["dom"]["class_names"]["title"] == "text-xl font-semibold"
    assert spec["dom"]["class_names"]["annotation_label"] == "tabular-nums"
    assert spec["dom"]["class_names"]["tooltip"] == "rounded-xl"


def test_tooltip_rows_carry_preformatted_text_for_renderer_parity() -> None:
    """The client has no `str.format`; Python ships the formatted twin so a
    tooltip, a label and a static export cannot disagree about a number."""
    fig = Figure(width=640, height=430)
    fig.funnel(STAGES, VALUES, value_format="{:,.0f}", percent_format="{:.1%}")
    row = fig.traces[0].tooltip_rows[1]
    assert row["value_text"] == "6,200"
    assert row["share_text"] == "63.3%"
    assert row["conversion_text"] == "63.3%"
    assert row["dropoff_text"] == "36.7%"
    # Numeric fields stay numeric for events.
    assert isinstance(row["value"], float)


def test_undefined_ratios_format_as_an_em_dash() -> None:
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b", "c"], [10.0, 0.0, 5.0])
    row = fig.traces[0].tooltip_rows[2]
    assert row["conversion"] is None
    assert row["conversion_text"] == "—"


# -- legend toggle -----------------------------------------------------------


def test_labels_are_tagged_with_the_stage_that_owns_them() -> None:
    """A legend toggle must retire a label with the geometry it describes; the
    client can only do that if the wire says which stage owns it."""
    spec, _ = _funnel_figure(show_dropoff=True).build_payload()
    annotations = spec["annotations"]
    assert annotations, "funnel labels ship as annotations"
    for annotation in annotations:
        assert annotation["owner"] == {"trace": 0, "category": annotation["owner"]["category"]}
        assert 0 <= annotation["owner"]["category"] < len(STAGES)
    # The value label of stage 0 belongs to stage 0.
    first = next(a for a in annotations if "9,800" in a["text"])
    assert first["owner"]["category"] == 0
    # A drop-off label belongs to the stage it names, not its predecessor.
    drop = next(a for a in annotations if a["text"].startswith("-37"))
    assert drop["owner"]["category"] == 1


def test_author_annotations_carry_no_owner_tag() -> None:
    fig = Figure(width=400, height=300)
    fig.text(0.0, 0.0, "hand written")
    spec, _ = fig.build_payload()
    assert "owner" not in spec["annotations"][0]


def test_tooltip_follows_the_pointer_inside_a_segment() -> None:
    """A funnel segment covers an area, so its tooltip tracks the cursor the
    way a Sankey band's does. Both the re-hover fast path (same hit id) and
    the anchor fallback must know that — the fast path is what froze the
    tooltip at its entry point."""
    view = (Path(__file__).parents[1] / "js" / "src" / "50_chartview.ts").read_text(
        encoding="utf-8"
    )
    assert "hit.g._cpuRibbon || hit.g._cpuFunnel" in view
    tooltip = (Path(__file__).parents[1] / "js" / "src" / "52_tooltip.ts").read_text(
        encoding="utf-8"
    )
    assert "g._cpuRibbon || g._cpuFunnel" in tooltip


def test_client_filters_funnel_stages_and_suppresses_owned_labels() -> None:
    """The category-visibility path must route funnels to their own filter —
    `_filterScatterRows` is gated on CPU color codes a funnel does not have,
    so without the branch a legend click silently did nothing."""
    client = (Path(__file__).parents[1] / "js" / "src" / "50_chartview.ts").read_text(
        encoding="utf-8"
    )
    assert "_filterFunnelStages" in client
    # The dispatch itself: _applyCategoryVisibility must route a funnel to it.
    dispatch = client.split("_applyCategoryVisibility(ti) {")[1][:1600]
    assert "g._cpuFunnel" in dispatch and "_filterFunnelStages" in dispatch
    annotations = (Path(__file__).parents[1] / "js" / "src" / "51_annotations.ts").read_text(
        encoding="utf-8"
    )
    assert "_annotationSuppressed" in annotations
    # Both draw loops consult it: shapes and labels.
    assert annotations.count("this._annotationSuppressed(ann)") == 2


# -- documentation contracts -------------------------------------------------


def test_default_formats_produce_the_documented_labels() -> None:
    assert _funnel.format_value(6200.0, "{:,.10g}") == "6,200"
    assert _funnel.format_value(0.5, "{:,.10g}") == "0.5"
    assert _funnel.format_ratio(0.6326, "{:.0%}") == "63%"
    assert _funnel.format_ratio(None, "{:.0%}") == "—"


# -- review round 2 (external review of PR #474) ------------------------------


def test_incompatible_axis_types_are_refused_at_build() -> None:
    """A log cross axis maps the centered (negative) corners to NaN and a
    forced stage-axis type strips the categorical labels — both would draw a
    plausible wrong picture, so both refuse at payload build (§28)."""
    with pytest.raises(ValueError, match="cross axis 'x' cannot be 'log'"):
        xy.funnel_chart(STAGES, VALUES, xy.x_axis(type_="log")).figure().build_payload()
    with pytest.raises(ValueError, match="stage axis 'y' cannot be 'time'"):
        xy.funnel_chart(STAGES, VALUES, xy.y_axis(type_="time")).figure().build_payload()
    with pytest.raises(ValueError, match="cross axis 'y' cannot be 'symlog'"):
        (
            xy.funnel_chart(STAGES, VALUES, xy.y_axis(type_="symlog"), orientation="horizontal")
            .figure()
            .build_payload()
        )


def test_raster_gives_var_palette_entries_distinct_fallbacks() -> None:
    """SVG/PDF degrade browser-only palette entries to DISTINCT built-ins;
    the PNG rasterizer must match instead of collapsing every var() stage
    onto one fallback color."""
    from test_png_export import _decode_rgba

    with pytest.warns(RuntimeWarning, match="resolve only in a browser"):
        fig = xy.funnel_chart(
            ["a", "b"],
            [4.0, 4.0],
            geometry="bar",
            labels=False,
            colors=["var(--a)", "var(--b)"],
            width=400,
            height=300,
        ).figure()
        pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    h, w = pixels.shape[:2]
    top = tuple(int(v) for v in pixels[int(h * 0.32), int(w * 0.5)][:3])
    bottom = tuple(int(v) for v in pixels[int(h * 0.72), int(w * 0.5)][:3])
    assert top != bottom


def test_inside_label_contrast_follows_the_drawn_constant_color() -> None:
    fig = Figure(width=640, height=430)
    fig.funnel(STAGES, VALUES, color="#ffffff")
    inside = next(a for a in fig.annotations if "9,800" in a["text"])
    assert inside["style"]["color"] == "#1f2430", "white fill takes a dark label"
    fig2 = Figure(width=640, height=430)
    fig2.funnel(STAGES, VALUES, color="#111111")
    inside2 = next(a for a in fig2.annotations if "9,800" in a["text"])
    assert inside2["style"]["color"] == "#f7f8fa", "near-black fill takes a light label"


def test_horizontal_label_fit_measures_the_pitch_not_the_height() -> None:
    """Ten stages across 400px leave ~34px of pitch; a ~100px text cannot sit
    inside OR beside its slot, so it hides — measuring the segment HEIGHT
    instead marked every one of them as fitting and they overlapped."""
    layout = compute_layout(
        [f"S{i}" for i in range(10)],
        [10_000.0 - 900.0 * i for i in range(10)],
        orientation="horizontal",
        geometry="bar",
    )
    cramped = decide_labels(
        layout,
        show_values=True,
        show_conversion=True,
        show_dropoff=False,
        value_format="{:,.0f}",
        percent_format="{:.0%}",
        font_size=12.0,
        plot_px=(400 * 0.85, 300 * 0.85),
    )
    assert {label.placement for label in cramped if label.kind == "value"} == {"hidden"}
    roomy = decide_labels(
        layout,
        show_values=True,
        show_conversion=True,
        show_dropoff=False,
        value_format="{:,.0f}",
        percent_format="{:.0%}",
        font_size=12.0,
        plot_px=(1400 * 0.85, 400 * 0.85),
    )
    assert {label.placement for label in roomy if label.kind == "value"} == {"inside"}


def test_funnel_chart_forwards_name_to_the_mark() -> None:
    fig = xy.funnel_chart(["a", "b"], [4.0, 2.0], name="pipeline").figure()
    assert fig.traces[0].name == "pipeline"


def test_chart_level_data_reaches_an_explicit_funnel_child() -> None:
    data = {"stage": ["a", "b"], "value": [4.0, 2.0]}
    fig = xy.funnel_chart(xy.funnel(stage="stage", value="value"), data=data).figure()
    assert [t.kind for t in fig.traces] == ["funnel"]
    assert fig.traces[0].tooltip_rows[0]["value"] == 4.0


def test_stray_kwargs_with_an_explicit_child_are_refused_by_name() -> None:
    with pytest.raises(ValueError, match=r"got \['gap'\] alongside an explicit"):
        xy.funnel_chart(xy.funnel(stage=["a"], value=[1.0]), gap=0.5)


@pytest.mark.parametrize(
    "implicit_kwargs",
    [
        {"stage": ["b"]},
        {"value": [2.0]},
        {"data": {"stage": ["b"], "value": [2.0]}, "stage": "stage", "value": "value"},
    ],
)
def test_explicit_child_cannot_be_combined_with_implicit_funnel_data(
    implicit_kwargs,
) -> None:
    explicit = xy.funnel(stage=["a"], value=[1.0])
    with pytest.raises(ValueError, match=r"alongside an explicit xy\.funnel"):
        xy.funnel_chart(explicit, **implicit_kwargs)


def test_empty_data_only_and_axis_only_funnel_charts_compile_without_a_mark() -> None:
    charts = (
        xy.funnel_chart(),
        xy.funnel_chart(data={"unused": [1.0]}),
        xy.funnel_chart(xy.x_axis(label="stage")),
    )
    for chart in charts:
        assert not any(isinstance(child, xy.Mark) for child in chart.children)
        fig = chart.figure()
        spec, blob = fig.build_payload()
        assert fig.traces == []
        assert spec["traces"] == []
        assert blob == b""


@pytest.mark.parametrize(
    "mark_kwargs",
    [
        {"stage": ["a"]},
        {"value": [1.0]},
        {"geometry": "bar"},
        {"data": {"unused": [1.0]}, "gap": 0.2},
    ],
)
def test_mark_options_without_funnel_data_are_refused(mark_kwargs) -> None:
    with pytest.raises(ValueError, match="without stage/value data"):
        xy.funnel_chart(**mark_kwargs)


def test_positional_stages_without_values_are_refused_at_factory_call() -> None:
    with pytest.raises(ValueError, match="without stage/value data"):
        xy.funnel_chart(["a"])


def test_mixed_orientations_in_one_chart_are_refused() -> None:
    with pytest.raises(ValueError, match="cannot mix vertical and horizontal"):
        xy.funnel_chart(
            xy.funnel(stage=["a"], value=[1.0]),
            xy.funnel(stage=["b"], value=[1.0], orientation="horizontal"),
        )


def test_failed_build_rolls_back_stage_categories() -> None:
    """A bad value_format used to leave the failed stages in the category
    registry, shifting the next valid funnel's positions by their count."""
    fig = Figure(width=400, height=300)
    with pytest.raises(ValueError):
        fig.funnel(["a", "b"], [4.0, 2.0], value_format="{:bogus}")
    assert fig._axis_categories == {}
    fig.funnel(["a", "b"], [4.0, 2.0])
    assert [float(v) for v in fig.traces[0].y0.values] == [pytest.approx(-0.5), pytest.approx(0.5)]


def test_multidimensional_stage_arrays_are_refused() -> None:
    with pytest.raises(ValueError, match="must be 1-D"):
        Figure(width=400, height=300).funnel(np.array([[1, 2], [3, 4]]), [1.0, 2.0, 3.0, 4.0])


def test_ratios_never_overflow_to_infinity() -> None:
    """A wide enough dynamic range makes a bare division inf, which is not
    JSON, not a wire value, and not a number to print. Undefined is undefined
    whether the denominator was zero or the quotient overflowed."""
    stages = compute_stages(["a", "b"], [1e-300, 1e10])
    assert stages[1].share is None
    assert stages[1].conversion is None
    assert stages[1].dropoff is None
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b"], [1e-300, 1e10])
    row = fig.traces[0].tooltip_rows[1]
    assert row["conversion"] is None
    assert row["conversion_text"] == "—"


def test_label_contrast_defers_on_browser_only_fills() -> None:
    """`_parse_color` silently substitutes its fallback blue for a var()/oklch()
    entry, so a luminance read there is a guess: a fill that resolves white on
    screen got a white label. Defer to the theme's own text color instead."""
    from xy.marks import _funnel_label_color

    assert _funnel_label_color("#ffffff") == "#1f2430"
    assert _funnel_label_color("#111111") == "#f7f8fa"
    assert _funnel_label_color("rgb(240,240,240)") == "#1f2430"
    assert _funnel_label_color("var(--brand)") is None
    assert _funnel_label_color("oklch(0.7 0.1 200)") is None


def test_theme_palette_map_survives_colour_shaped_stage_names() -> None:
    """The shared resolver reads a column of CSS colours as per-point PAINT,
    not as category labels, so stage names like "#ff0000" come back with no
    categories to reorder — the map is still keyed by stage name."""
    fig = xy.funnel_chart(
        ["#ff0000", "#00ff00"], [4.0, 2.0], xy.theme(palette={"#ff0000": "#123456"})
    ).figure()
    channel = fig.traces[0].color_ch
    assert channel.categories == ["#ff0000", "#00ff00"]
    assert channel.palette[0] == "#123456"
    assert channel.palette[1] != "#123456"


def test_funnel_outlines_declare_round_joins_for_raster_parity() -> None:
    """The native rasterizer's stroke is a distance field with round joins by
    construction, so an SVG miter would spike where a taper meets its neck."""
    doc = (
        xy.funnel_chart(["a", "b"], [4.0, 2.0], neck="taper", stroke="#000000", stroke_width=3.0)
        .figure()
        .to_svg()
    )
    quads = re.findall(r'<path d="M [^"]+Z"[^/]*?/>', doc)
    stroked = [q for q in quads if "stroke=" in q]
    assert stroked, "expected stroked funnel paths"
    for path in stroked:
        assert 'stroke-linejoin="round"' in path


def test_annotation_labels_follow_the_theme_text_colour_in_both_exporters() -> None:
    """The live client resolves an annotation label through
    var(--chart-annotation-text, var(--chart-text, inherit)); the exporters
    must reach the same colour or a themed chart prints its labels in the
    light-mode default. Shapes keep their own neutral paint."""
    from test_png_export import _decode_rgba

    chart = xy.funnel_chart(
        ["a", "b"], [4.0, 2.0], xy.theme(text_color="#cc0000"), width=420, height=300
    )
    doc = chart.figure().to_svg()
    assert 'fill="#cc0000"' in doc, "SVG label ignored --chart-text"
    pixels = _decode_rgba(chart.figure().to_image(format="png", scale=1))
    reds = ((pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 90) & (pixels[:, :, 2] < 90)).sum()
    assert reds > 0, "raster label ignored --chart-text"


def test_annotation_shape_paint_is_not_the_theme_text_colour() -> None:
    """Only the LABEL follows the theme text colour. Widening it to shapes
    diverged the SVG exporter from the raster and the live client."""
    doc = (
        xy.line_chart(
            xy.line([1.0, 2.0], [1.0, 2.0]),
            xy.hline(1.5, text="threshold"),
            xy.theme(text_color="#cc0000"),
        )
        .figure()
        .to_svg()
    )
    rules = re.findall(r"<line[^>]*stroke=\"(#[0-9a-fA-F]{6})\"", doc)
    assert "#cc0000" not in rules, "rule stroke took the theme text colour"


def test_hover_containment_rejects_the_bounding_box_corner() -> None:
    """The client's containment test is the trapezoid, not its bounding box.
    A point inside the box but outside the taper must miss — the same rule
    `_funnelHover` implements, checked here against the geometry source."""
    layout = compute_layout(["a", "b"], [10.0, 2.0], gap=0.0)
    quad = layout.quads[0]
    # Mid-segment: the taper has narrowed from 5 to 1, so the half-width is 3.
    t = 0.5
    edge = quad.hi0 + (quad.hi1 - quad.hi0) * t
    assert edge == pytest.approx(3.0)
    # A bounding-box test would accept 4.5 here (it is inside 5, the widest
    # edge); trapezoid containment must reject it.
    assert edge < 4.5
    assert edge > 2.0


def test_horizontal_outside_labels_center_over_their_stage() -> None:
    """A start anchor at the stage midpoint hung half the text over the
    neighbour and clipped the last stage at the plot edge; horizontal outside
    labels center instead. Vertical margin labels keep the start anchor."""
    layout = compute_layout(
        ["alpha", "beta", "gamma"],
        [10.0, 6.0, 1.0],
        orientation="horizontal",
        geometry="bar",
    )
    labels = decide_labels(
        layout,
        show_values=True,
        show_conversion=True,
        show_dropoff=False,
        value_format="{:,.0f}",
        percent_format="{:.0%}",
        font_size=12.0,
        plot_px=(700.0, 120.0),
    )
    outside = [label for label in labels if label.placement == "outside"]
    assert outside, "expected the thin stage to fall outside"
    assert {label.anchor for label in outside} == {"middle"}


def test_funnel_append_matching_downgrades_to_index_pairs() -> None:
    """Append matching pairs rows by decoded x value, and a vertical funnel's
    x centers are all ~0, so every new stage paired with the LAST old stage.
    The funnel prep rebuilds the pairs by position and records the downgrade."""
    source = (Path(__file__).parents[1] / "js" / "src" / "56_animation.ts").read_text(
        encoding="utf-8"
    )
    prep = source.split("_prepareFunnelPositionInterpolation(previous, next, match) {")[1]
    prep = prep.split("\n  },")[0]
    assert 'match.strategy === "snap"' in prep, "snap strategy must bail before mixing"
    assert 'match.strategy === "append"' in prep
    assert '"index:append-unsupported"' in prep


def test_stroke_without_width_still_draws_an_outline() -> None:
    """Every renderer skips a zero-width stroke, so `stroke=` alone drew
    nothing. The other mark builders imply 1px in exactly this case, and the
    implication happens at BUILD time — so it ships on the wire and both
    static exporters honour it, not just the client."""
    from test_png_export import _decode_rgba

    chart = xy.funnel_chart(
        ["a", "b"],
        [4.0, 2.0],
        geometry="bar",
        labels=False,
        color="#ffffff",
        stroke="#ff0000",
        width=400,
        height=300,
    )
    # One figure for all three surfaces: the point is that the SAME built
    # object reaches the wire, the SVG and the raster identically.
    fig = chart.figure()
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["style"]["stroke_width"] == 1.0
    doc = fig.to_svg()
    assert 'stroke="#ff0000"' in doc
    assert 'stroke-width="1"' in doc
    pixels = _decode_rgba(fig.to_image(format="png", scale=1))
    reds = ((pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 90) & (pixels[:, :, 2] < 90)).sum()
    assert reds > 0, "raster dropped the implied 1px outline"


def test_tooltip_rows_carry_the_prior_value_text() -> None:
    fig = Figure(width=400, height=300)
    fig.funnel(["a", "b"], [9800.0, 6200.0], value_format="{:,.0f}")
    rows = fig.traces[0].tooltip_rows
    assert rows[0]["prior_text"] is None, "stage 0 has no prior"
    assert rows[1]["prior_text"] == "9,800"


def test_funnel_stage_centers_stay_out_of_the_selection_universe() -> None:
    """`retainCpu` puts stage centers in `_cpu` for the KEYBOARD walk, but
    funnel selection is documented as absent — counting those centers reported
    a selection the chart never drew."""
    source = (Path(__file__).parents[1] / "js" / "src" / "53_interaction.ts").read_text(
        encoding="utf-8"
    )
    assert source.count("markOf(g.trace.kind).stageNav) continue;") == 2, (
        "both _selectLocal and _selectLocalPolygon must skip stageNav marks"
    )


def test_scene_reference_names_the_clients_actual_strip_order() -> None:
    """The client sweeps A,B,D,C (triangles ABD/BDC), not ABC/ACD. A normative
    comment that names the wrong tessellation misleads the next renderer."""
    from xy import _scene

    doc = _scene.funnel_quad.__doc__ or ""
    assert "A, B, D, C" in doc
    assert "ABD and BDC" in doc


def test_client_funnel_draw_multiplies_transition_opacity_into_both_paints() -> None:
    """Retained old traces retire via `_transitionOpacity = 0`; both the fill
    and outline uniforms must consume it or old funnel geometry ghosts."""
    source = (Path(__file__).parents[1] / "js" / "src" / "50_chartview.ts").read_text(
        encoding="utf-8"
    )
    draw = source.split("_drawFunnels(g, xm, ym) {")[1].split("\n  }\n\n", 1)[0]
    assert "const transitionAlpha = (g._transitionOpacity ?? 1)" in draw
    assert 'u("u_opacity"), this._fillOpacity(g.trace.style) * transitionAlpha' in draw
    assert 'u("u_strokeOpacity")' in draw and "* transitionAlpha" in draw


def test_client_funnel_geometry_uses_one_exported_slot_contract() -> None:
    """Filtering, build, per-frame mix, draw and animation must share one
    ordered semantic-column-to-GL-slot mapping."""
    root = Path(__file__).parents[1] / "js" / "src"
    header = (root / "00_header.ts").read_text(encoding="utf-8")
    chart = (root / "50_chartview.ts").read_text(encoding="utf-8")
    animation = (root / "56_animation.ts").read_text(encoding="utf-8")
    expected = (
        'pos0: "x0"',
        'pos1: "x1"',
        'lo0: "y0"',
        'hi0: "y1"',
        'lo1: "x2"',
        'hi1: "y2"',
    )
    assert "export const FUNNEL_SLOTS" in header
    assert all(entry in header for entry in expected)
    assert chart.count("Object.entries(FUNNEL_SLOTS)") == 3
    assert "Object.keys(FUNNEL_SLOTS)" in chart
    assert chart.count("Object.values(FUNNEL_SLOTS)") == 2
    assert "Object.keys(FUNNEL_SLOTS)" in animation
    duplicated = '{ pos0: "x0", pos1: "x1", lo0: "y0"'
    assert duplicated not in chart and duplicated not in animation


def test_client_funnel_precision_paths_use_the_shared_decoder() -> None:
    """Funnel center build, grow mix, containment and update retargeting must
    inherit the shared §4/§16 offset semantics rather than private formulas."""
    root = Path(__file__).parents[1] / "js" / "src"
    chart = (root / "50_chartview.ts").read_text(encoding="utf-8")
    animation = (root / "56_animation.ts").read_text(encoding="utf-8")
    chart_methods = (
        "_buildFunnelMark(g, t, buffer) {",
        "_mixFunnelGeometry(g) {",
        "_funnelHover(g, dataX, dataY) {",
    )
    for signature in chart_methods:
        body = chart.split(signature)[1].split("\n  }\n\n", 1)[0]
        assert "this._decodeValue" in body, signature
        assert ".offset || 0" not in body, signature
    prep = animation.split("_prepareFunnelPositionInterpolation(previous, next, match) {")[1]
    prep = prep.split("\n  },", 1)[0]
    assert prep.count("this._decodeValue") == 2
    assert ".offset || 0" not in prep
