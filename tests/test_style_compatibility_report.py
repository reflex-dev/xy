"""The preflight report must mirror the export paths, never re-decide them.

`chart.style_compatibility_report()` is report-only (running it changes no
export), constant-time for charts with nothing to route, and derives every
fact from the capability registry, the writers' own honored-property
constants, and the export module's engine resolver. These tests pin all three
properties, plus the applicable-slot contract: state-gated chrome (tooltip,
modebar, crosshair, selection, reduction badges) is recorded, not counted as
a loss a clean static file never contained.
"""

from __future__ import annotations

import pytest

import xy
from xy import _svg, export
from xy.styling import capabilities as caps
from xy.styling import preflight as pf


def _chart(**props):
    return xy.scatter_chart(xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]), **props)


def _finding(report, slot, source):
    matches = [f for f in report.findings if f.slot == slot and f.source == source]
    assert len(matches) == 1, f"expected one finding for {source}[{slot!r}], got {matches!r}"
    return matches[0]


# -- constant-time path ------------------------------------------------------


@pytest.mark.parametrize("target", ["png", "jpeg", "webp", "svg", "pdf", "html"])
def test_unstyled_chart_is_lossless_with_no_findings(target: str) -> None:
    report = _chart().style_compatibility_report(target)
    assert report.lossless
    assert report.findings == ()
    assert report.losses == ()
    assert report.error is None
    assert not any(report.sources.values())


def test_chart_level_style_alone_stays_on_the_constant_time_path() -> None:
    # The chart-level token bag is read by every renderer (capability matrix,
    # `root` row), so it is a source that can never drop — the report says the
    # source is present and walks nothing.
    report = _chart(style={"background": "#111"}).style_compatibility_report("png")
    assert report.sources["chart_style"]
    assert report.lossless
    assert report.findings == ()


# -- routing: class_names ----------------------------------------------------


def test_class_on_static_slot_is_lost_natively_and_kept_in_browser_targets() -> None:
    chart = _chart(class_names={"legend": "bg-slate-900"})
    native = chart.style_compatibility_report("png")
    assert not native.lossless
    finding = _finding(native, "legend", "class_names")
    assert finding.route == pf.ROUTE_BROWSER_ONLY
    assert finding.lost == ("*",)

    assert chart.style_compatibility_report("html").lossless
    chromium = chart.style_compatibility_report("png", engine=export.Engine.chromium)
    assert chromium.engine == "browser"
    assert chromium.lossless


def test_class_on_hover_slot_is_state_gated_not_lost() -> None:
    # The applicable-slot contract: a clean static export contains no tooltip,
    # so a styled tooltip is not "dropped" by one — the report records the
    # gating state and stays lossless.
    report = _chart(class_names={"tooltip": "rounded-xl"}).style_compatibility_report("png")
    finding = _finding(report, "tooltip", "class_names")
    assert finding.route == pf.ROUTE_STATE_GATED
    assert finding.applicability == "hover"
    assert finding.lost == ()
    assert report.lossless


# -- routing: per-slot styles ------------------------------------------------


def test_subset_math_follows_the_writers_own_constants() -> None:
    chart = _chart(styles={"tick_label": {"font_weight": 600, "letter_spacing": "0.08em"}})

    raster = chart.style_compatibility_report("png")
    finding = _finding(raster, "tick_label", "styles")
    assert finding.route == pf.ROUTE_SUBSET
    assert "font-weight" in finding.kept
    assert finding.lost == ("letter-spacing",)
    assert "letter-spacing" not in _svg.SLOT_RASTER_PROPS

    vector = chart.style_compatibility_report("svg")
    finding = _finding(vector, "tick_label", "styles")
    assert finding.route == pf.ROUTE_SURVIVES
    assert finding.lost == ()
    assert "letter-spacing" in _svg.SLOT_TEXT_PROPS


def test_pdf_inherits_the_vector_subset() -> None:
    chart = _chart(styles={"axis_title": {"letter_spacing": "0.1em"}})
    assert chart.style_compatibility_report("pdf").lossless
    assert not chart.style_compatibility_report("jpeg").lossless


def test_styles_on_a_slot_with_no_native_path_are_named_lost() -> None:
    report = _chart(styles={"legend_swatch": {"border-radius": "2px"}})
    report = report.style_compatibility_report("png")
    finding = _finding(report, "legend_swatch", "styles")
    assert finding.route == pf.ROUTE_BROWSER_ONLY
    assert finding.lost == ("border-radius",)
    assert not report.lossless


def test_root_styles_point_at_the_token_bag_channel() -> None:
    report = _chart(styles={"root": {"background": "#111"}}).style_compatibility_report("png")
    finding = _finding(report, "root", "styles")
    assert finding.route == pf.ROUTE_BROWSER_ONLY
    assert "style=" in finding.detail


def test_legend_styles_route_at_property_level() -> None:
    # Box properties route through the merged legend declaration
    # (`_svg.LEGEND_BOX_PROPS`, writer-owned), text properties through the
    # per-family subsets — and a property in neither set is a provable loss.
    # The earlier declaration-level qualification rounded those to silence,
    # which let warn stay quiet and strict permit a drop.
    boxed = _chart(styles={"legend": {"background": "black", "border-radius": "6px"}})
    report = boxed.style_compatibility_report("png")
    finding = _finding(report, "legend", "styles")
    assert finding.route == pf.ROUTE_SUBSET
    assert finding.lost == ()
    assert set(finding.kept) == {"background", "border-radius"}
    assert "merged legend declaration" in finding.detail
    assert report.lossless

    # letter-spacing on the raster path is in neither the raster text subset
    # nor the box vocabulary: named lost, not qualified away.
    lossy = _chart(styles={"legend": {"letter_spacing": "0.08em", "background": "black"}})
    raster = lossy.style_compatibility_report("png")
    finding = _finding(raster, "legend", "styles")
    assert finding.lost == ("letter-spacing",)
    assert "background" in finding.kept
    assert not raster.lossless
    # The same declaration survives the vector writers, which honor it.
    assert lossy.style_compatibility_report("svg").lossless


def test_state_gated_styles_do_not_block_lossless() -> None:
    report = _chart(
        styles={"modebar_button": {"background": "red"}, "crosshair_x": {"opacity": 0.5}}
    ).style_compatibility_report("png")
    routes = {f.slot: f.route for f in report.findings}
    assert routes == {
        "modebar_button": pf.ROUTE_STATE_GATED,
        "crosshair_x": pf.ROUTE_STATE_GATED,
    }
    assert report.lossless


# -- engine interactions -----------------------------------------------------


def test_custom_css_routes_auto_to_browser_and_stays_lossless() -> None:
    report = _chart(class_names={"legend": "x"}).style_compatibility_report(
        "png", custom_css=".x{}"
    )
    assert report.engine == "browser"
    assert report.lossless


def test_browser_targets_mirror_custom_css_validation() -> None:
    # A browser-resolved export still validates the stylesheet itself
    # (`export._custom_css_block`): wrong type, or a sequence that could
    # break out of the <style> element. The report must carry the same
    # refusal instead of calling the export lossless.
    chart = _chart()
    for target in ("png", "html"):
        breakout = chart.style_compatibility_report(target, custom_css="</style><script>")
        assert breakout.error is not None
        assert not breakout.lossless
        assert "</style>" in breakout.error or "style" in breakout.error

        wrong_type = chart.style_compatibility_report(target, custom_css=123)  # type: ignore[arg-type]
        assert wrong_type.error == "custom_css must be a string"


def test_malformed_figure_styling_raises_exactly_like_the_export() -> None:
    # class_names/chrome_styles are assignable on the figure, so a report can
    # be requested before the spec build validates them. Skipping such an
    # entry would hide a declaration (§28); instead the report raises the
    # same error the export's own spec build raises.
    fig = _chart().figure()
    fig.class_names["not_a_slot"] = "x"
    with pytest.raises(ValueError, match="unknown slot"):
        fig.style_compatibility_report("png")

    fig = _chart().figure()
    fig.chrome_styles["title"] = "not-a-mapping"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="must be a mapping"):
        fig.style_compatibility_report("png")


def test_refusals_are_mirrored_not_re_decided() -> None:
    # The export path raises for these; the report carries the same message
    # instead of predicting a different outcome.
    pinned = _chart().style_compatibility_report(
        "png", engine=export.Engine.default, custom_css=".x{}"
    )
    assert pinned.error is not None
    assert not pinned.lossless
    with pytest.raises(ValueError) as excinfo:
        export._resolve_image_engine(export.Engine.default, "png", ".x{}")
    assert pinned.error == str(excinfo.value)

    svg_chromium = _chart().style_compatibility_report("svg", engine=export.Engine.chromium)
    assert svg_chromium.error is not None


# -- report surface ----------------------------------------------------------


def test_explain_names_every_route() -> None:
    text = (
        _chart(
            class_names={"legend": "x", "tooltip": "y"},
            styles={"tick_label": {"letter_spacing": "0.08em"}},
        )
        .style_compatibility_report("png")
        .explain()
    )
    assert "browser-only" in text
    assert "state-gated" in text
    assert "letter-spacing" in text
    assert "loss(es)" in text


def test_importing_the_styling_package_loads_no_machinery() -> None:
    # The package resolves submodules lazily (PEP 562): `capabilities`
    # reaches the writers' constants and through them the native library, so
    # a bare `import xy.styling` must not pay for any of it — the legacy
    # path's zero-import guarantee extends to the package itself.
    import subprocess
    import sys as _sys

    probe = (
        "import sys; import xy.styling; "
        "print(sorted(m for m in ('xy.styling.preflight', 'xy.styling.capabilities', "
        "'xy.styling.resolved', 'xy._svg') if m in sys.modules))"
    )
    result = subprocess.run(
        [_sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_chart_report_is_the_figure_report() -> None:
    chart = _chart(class_names={"legend": "x"})
    via_chart = chart.style_compatibility_report("png")
    via_figure = chart.figure().style_compatibility_report("png")
    assert via_chart == via_figure


def test_every_declared_style_lands_in_exactly_one_route() -> None:
    # §28 as a property: styled slots partition into survives / subset /
    # browser-only / state-gated. No styled slot may be absent from the
    # report, and no route outside the vocabulary may appear.
    styles = {slot.id: {"font-size": 10} for slot in caps.CHART_SLOTS}
    report = _chart(styles=styles).style_compatibility_report("png")
    assert {f.slot for f in report.findings} == {s.id for s in caps.CHART_SLOTS}
    allowed = {
        pf.ROUTE_SURVIVES,
        pf.ROUTE_SUBSET,
        pf.ROUTE_BROWSER_ONLY,
        pf.ROUTE_STATE_GATED,
    }
    assert {f.route for f in report.findings} <= allowed
