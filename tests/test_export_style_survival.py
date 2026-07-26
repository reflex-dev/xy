"""Which styling survives which export path is a published contract, not luck.

Browser chrome is CSS-addressable; the native SVG/raster/PDF writers have no
cascade and read a strict subset of the same spec. Both facts are fine. What is
not fine is leaving the boundary undocumented, so this module pins it: every
assertion here corresponds to a row in `spec/api/export.md` § "What styling
survives which export path" and in
`docs/api-reference/limitations-and-alpha-status.md`.
"""

from __future__ import annotations

import re

import pytest

import xy
from xy import Engine, _raster
from xy._svg import STATIC_STYLED_SLOTS
from xy.dom import CHART_DOM_SLOTS


def _styled_chart() -> xy.Chart:
    return xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series"),
        title="title",
        class_names={slot: f"cls-{slot}" for slot in CHART_DOM_SLOTS},
        styles={slot: {"outline_color": "#123456"} for slot in CHART_DOM_SLOTS},
        style={"--chart-bg": "#101820"},
    )


def test_browser_spec_carries_every_slot_class_and_style() -> None:
    # The browser client applies dom.class_names / dom.styles to every slot
    # (js/src/50_chartview.ts _applySlot), so the spec must carry them all.
    spec, _ = _styled_chart().figure().build_payload()
    dom = spec["dom"]

    assert set(dom["class_names"]) == set(CHART_DOM_SLOTS)
    assert set(dom["styles"]) == set(CHART_DOM_SLOTS)


def test_native_writers_read_a_property_subset_not_the_whole_cascade() -> None:
    # The writers honor the text/box properties named in `_SLOT_TEXT_PROPS`.
    # Anything else in a slot's declaration block — here `outline-color`, which
    # no static writer paints — stays browser-only, and no class name reaches a
    # file, because a file has no stylesheet to match it against.
    figure = _styled_chart().figure()
    svg = figure.to_svg()

    assert "#101820" in svg, "chart-level style tokens must reach native output"
    assert "#123456" not in svg, "a property no writer paints must not reach native output"
    assert "class=" not in svg, "the SVG writer emits no class attributes"
    for slot in CHART_DOM_SLOTS:
        assert f"cls-{slot}" not in svg


#: The paint property each static slot answers to. `legend` is the frame box,
#: so it takes `background`; every other static slot is text, so it takes the
#: SVG text paint.
_SLOT_PAINT_PROPERTY = {slot: "fill" for slot in STATIC_STYLED_SLOTS} | {"legend": "background"}


@pytest.mark.parametrize("slot", STATIC_STYLED_SLOTS)
def test_every_static_slot_carries_its_paint_into_svg(slot: str) -> None:
    # The headline of the per-slot contract: a slot that names chrome a static
    # file contains must carry that chrome's paint into the file.
    chart = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series", color=[0.0, 1.0], colormap="viridis"),
        xy.legend(title="Legend title"),
        xy.colorbar(title="Colorbar title"),
        xy.x_axis(label="x label"),
        title="chart title",
        styles={slot: {_SLOT_PAINT_PROPERTY[slot]: "#123456"}},
    )
    assert "#123456" in chart.figure().to_svg(), f"styles={{{slot!r}: ...}} was dropped"


def test_the_two_spellings_of_a_legend_style_agree() -> None:
    # xy.legend(style=...) and the chart-level styles={"legend": ...} are the
    # same declaration written two ways. They agree in the browser, so they
    # must agree in a file.
    through_component = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series"),
        xy.legend(style={"background": "#123456"}),
    ).figure()
    through_slot = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series"),
        styles={"legend": {"background": "#123456"}},
    ).figure()

    assert "#123456" in through_component.to_svg()
    assert "#123456" in through_slot.to_svg()
    assert through_component.to_svg() == through_slot.to_svg()


def test_the_narrower_selector_wins_over_the_chart_wide_slot() -> None:
    # An axis's own label_color is more specific than styles={"axis_title": ...}.
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0]),
        xy.x_axis(label="x label", style={"label_color": "#ff0000"}),
        styles={"axis_title": {"fill": "#0000ff"}},
    )
    svg = chart.figure().to_svg()
    label = next(node for node in re.findall(r"<text[^>]*>x label</text>", svg))
    assert 'fill="#ff0000"' in label
    assert "#0000ff" not in label


def test_an_explicit_legend_background_is_opaque_like_the_browser() -> None:
    # `background:#ff00ff` paints opaque in the browser; the frame-alpha token
    # is the separate knob for the default grey frame.
    chart = xy.line_chart(
        xy.line([0.0, 1.0], [0.0, 1.0], name="series"),
        styles={"legend": {"background": "#ff00ff"}},
    )
    frame = next(
        node for node in re.findall(r"<rect[^>]*/>", chart.figure().to_svg()) if "#ff00ff" in node
    )
    assert 'fill-opacity="1"' in frame


def test_unstyled_output_is_untouched() -> None:
    # The per-slot path must be inert when nobody uses it: a chart with no
    # `styles=` renders exactly the bytes it rendered before the feature.
    plain = xy.line_chart(xy.line([0.0, 1.0], [0.0, 1.0], name="series"), title="t").figure()
    svg = plain.to_svg()
    assert '<text x="450" y="28" text-anchor="middle" font-size="14" font-weight="600"' in svg


def test_custom_css_is_refused_by_every_native_path() -> None:
    # custom_css is a browser stylesheet. Native export rejects it by name
    # rather than dropping it, and SVG rejects it for every engine because no
    # browser can emit vector SVG.
    chart = _styled_chart()

    for fmt in ("png", "pdf", "jpeg", "webp"):
        with pytest.raises(
            ValueError, match=re.escape("custom_css requires engine=Engine.chromium")
        ):
            chart.to_image(format=fmt, engine=Engine.default, custom_css=".x{color:red}")
    for engine in (Engine.auto, Engine.default, Engine.chromium):
        with pytest.raises(ValueError, match=r"SVG export is native-only|custom_css requires"):
            chart.to_image(format="svg", engine=engine, custom_css=".x{color:red}")


def test_native_raster_matches_the_svg_writer_on_slot_styling() -> None:
    # The two native writers must agree with each other, not only with the doc.
    # A slot the raster honors must change its pixels; the atlas is a single
    # baked face, so it reads size and paint and leaves weight/style/family to
    # the vector writers.
    def figure(**kwargs):
        return xy.line_chart(
            xy.line([0.0, 1.0], [0.0, 1.0], name="series"), title="title", **kwargs
        ).figure()

    plain = _raster.render_raster(*figure().build_payload(), scale=1)
    painted = _raster.render_raster(
        *figure(styles={"title": {"fill": "#ff0000"}}).build_payload(), scale=1
    )
    weighted = _raster.render_raster(
        *figure(styles={"title": {"font_weight": 900}}).build_payload(), scale=1
    )

    assert not (plain == painted).all(), "the raster writer must honor a slot's paint"
    assert (plain == weighted).all(), "the baked atlas has one weight; it must ignore font-weight"
