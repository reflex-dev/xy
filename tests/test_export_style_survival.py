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
    # The browser client applies dom.class_names / dom.styles to all 29 slots
    # (js/src/50_chartview.ts _applySlot), so the spec must carry all 29.
    spec, _ = _styled_chart().figure().build_payload()
    dom = spec["dom"]

    assert set(dom["class_names"]) == set(CHART_DOM_SLOTS)
    assert set(dom["styles"]) == set(CHART_DOM_SLOTS)


def test_native_writers_read_chart_style_and_nothing_per_slot() -> None:
    # python/xy/_svg.py:767,1481 and python/xy/_raster.py:662 read
    # spec["dom"]["style"] — the chart-level token bag — and never
    # spec["dom"]["styles"] or spec["dom"]["class_names"].
    figure = _styled_chart().figure()
    svg = figure.to_svg()

    assert "#101820" in svg, "chart-level style tokens must reach native output"
    assert "#123456" not in svg, "per-slot styles must not reach native output"
    assert "class=" not in svg, "the SVG writer emits no class attributes"
    for slot in CHART_DOM_SLOTS:
        assert f"cls-{slot}" not in svg


def test_legend_is_the_one_slot_with_a_parallel_native_channel() -> None:
    # xy.legend(style=...) is written twice: to chrome_styles (browser) and to
    # legend_options["style"], which the native writers do read. The
    # chart-level styles={"legend": ...} form only reaches the browser.
    through_component = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series"),
        xy.legend(style={"background": "#123456"}),
    ).figure()
    assert "#123456" in through_component.to_svg()

    through_slot = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series"),
        styles={"legend": {"background": "#123456"}},
    ).figure()
    assert "#123456" not in through_slot.to_svg()


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
    # The two native writers must agree with each other, not only with the doc:
    # neither honors a per-slot style, so the styled and unstyled renders are
    # pixel-identical.
    styled = _raster.render_raster(*_styled_chart().figure().build_payload(), scale=1)
    plain = xy.scatter_chart(
        xy.scatter(x=[0.0, 1.0], y=[1.0, 2.0], name="series"),
        title="title",
        style={"--chart-bg": "#101820"},
    ).figure()
    assert (styled == _raster.render_raster(*plain.build_payload(), scale=1)).all()
