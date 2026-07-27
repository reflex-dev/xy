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
    # (js/src/50_chartview.ts _applySlot), so the spec must carry them all. The
    # count is read from CHART_DOM_SLOTS below rather than written down here,
    # so adding a slot cannot leave this comment stale.
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


def test_a_legend_style_may_be_written_in_kebab_case() -> None:
    # The writers key on the browser's camelCase property names, but every doc
    # example — and normal CSS — uses kebab-case. Both spellings are the same
    # declaration, so both must reach the file; kebab used to lose the shadow
    # and the corner radius outright.
    def svg(style):
        return xy.line_chart(
            xy.line([0.0, 1.0], [0.0, 1.0], name="alpha"), xy.legend(style=style)
        ).to_svg()

    camel = svg({"background": "#ffeeaa", "borderRadius": "6px", "boxShadow": "2px 2px 4px #000"})
    kebab = svg({"background": "#ffeeaa", "border-radius": "6px", "box-shadow": "2px 2px 4px #000"})
    assert camel == kebab


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
    # 400 is Matplotlib's `axes.titleweight: normal`, the chrome-text default.
    assert '<text x="450" y="28" text-anchor="middle" font-size="14" font-weight="400"' in svg


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
    # The atlas carries a regular, a bold and an italic face, so size, paint,
    # weight and style all reach the pixels; it has no family axis and no
    # per-glyph advance control, so those two stay vector-only.
    def figure(**kwargs):
        return xy.line_chart(
            xy.line([0.0, 1.0], [0.0, 1.0], name="series"), title="title", **kwargs
        ).figure()

    def render(**kwargs):
        return _raster.render_raster(*figure(**kwargs).build_payload(), scale=1)

    plain = render()
    for declaration in ({"fill": "#ff0000"}, {"font_weight": 900}, {"font_style": "italic"}):
        assert not (plain == render(styles={"title": declaration})).all(), (
            f"the raster writer must honor {declaration}"
        )
    for declaration in ({"font_family": "Georgia"}, {"letter_spacing": "3px"}):
        assert (plain == render(styles={"title": declaration})).all(), (
            f"the atlas cannot draw {declaration}; it must not pretend to"
        )


def test_an_extra_legend_is_styled_like_the_main_one_in_both_writers() -> None:
    # A categorical color channel adds a second legend. `_svg` folded the slot
    # and the theme token into every legend; the raster writer originally did it
    # for the main legend only, so a multi-legend chart styled in SVG but not in
    # PNG — the exact parity this module exists to hold.
    def chart(**kwargs):
        return xy.scatter_chart(
            xy.scatter(x=[0.0, 1.0, 2.0, 3.0], y=[0.0, 1.0, 2.0, 3.0], color=["a", "b", "a", "b"]),
            xy.line([0.0, 1.0], [0.0, 1.0], name="trend"),
            **kwargs,
        )

    styled = {"legend_label": {"fill": "#123456", "font_size": 16}}
    assert "#123456" in chart(styles=styled).figure().to_svg()

    plain_png = _raster.render_raster(*chart().figure().build_payload(), scale=1)
    styled_png = _raster.render_raster(*chart(styles=styled).figure().build_payload(), scale=1)
    assert not (plain_png == styled_png).all(), "the raster writer skipped the extra legend"


def test_the_raster_property_subset_is_a_subset_of_the_vector_one() -> None:
    from xy._svg import SLOT_RASTER_PROPS, SLOT_TEXT_PROPS

    assert set(SLOT_RASTER_PROPS) < set(SLOT_TEXT_PROPS)
    # The atlas has no family axis, no per-glyph advance control and no alpha
    # channel on the blit, so these stay vector-only rather than being silently
    # approximated.
    assert set(SLOT_TEXT_PROPS) - set(SLOT_RASTER_PROPS) == {
        "font-family",
        "letter-spacing",
        "opacity",
    }
