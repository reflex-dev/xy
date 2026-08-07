"""The staged `compatibility=` modes: legacy is untouched, warn says every
loss out loud once, strict refuses before emission, and no mode ever
re-routes an explicit engine (spec/process/style-compatibility-migration.md).
"""

from __future__ import annotations

import warnings

import pytest

import xy
from xy import export
from xy.styling.preflight import (
    StyleCompatibilityError,
    StyleCompatibilityWarning,
    validate_compatibility,
)


def _chart(**props):
    return xy.scatter_chart(xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]), **props)


def _lossy_chart():
    return _chart(class_names={"legend": "bg-slate-900"})


# -- vocabulary --------------------------------------------------------------


def test_unknown_modes_fail_loudly_and_lossless_is_reserved() -> None:
    with pytest.raises(ValueError, match="legacy"):
        _chart().to_png(compatibility="Legacy")
    with pytest.raises(ValueError, match="reserved"):
        _lossy_chart().to_png(compatibility="lossless")
    # An invalid mode fails even when nothing could drop: vocabulary errors
    # must not depend on what happens to be styled.
    with pytest.raises(ValueError, match="compatibility"):
        _chart().to_png(compatibility="stricted")
    assert validate_compatibility("warn") == "warn"


# -- legacy: byte-identical, zero machinery ----------------------------------


def test_legacy_output_is_byte_identical_to_the_default() -> None:
    chart = _lossy_chart()
    assert chart.to_png() == chart.to_png(compatibility="legacy")
    assert chart.to_svg() == chart.to_svg(compatibility="legacy")


def test_legacy_never_warns() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", StyleCompatibilityWarning)
        _lossy_chart().to_png()
        _lossy_chart().to_png(compatibility="legacy")


# -- warn --------------------------------------------------------------------


def test_warn_names_each_loss_once_and_still_emits_bytes() -> None:
    with pytest.warns(StyleCompatibilityWarning, match=r"class_names\['legend'\]") as caught:
        data = _lossy_chart().to_png(compatibility="warn")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len([w for w in caught if w.category is StyleCompatibilityWarning]) == 1


def test_warn_is_silent_when_nothing_drops() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", StyleCompatibilityWarning)
        # Unstyled: the constant-time early-out.
        _chart().to_png(compatibility="warn")
        # State-gated only: a clean static file contains no tooltip to lose.
        _chart(styles={"tooltip": {"color": "red"}}).to_png(compatibility="warn")
        # Vector keeps the full text subset this declaration uses.
        _chart(styles={"tick_label": {"letter_spacing": "0.08em"}}).to_svg(compatibility="warn")


def test_warn_fires_when_the_raster_drops_a_vector_only_declaration() -> None:
    # letter-spacing survives the vector writers but not the raster one, so
    # the PNG path must warn where the SVG path (covered above) stays silent.
    with pytest.warns(StyleCompatibilityWarning, match="tick_label"):
        _chart(styles={"tick_label": {"letter_spacing": "0.08em"}}).to_png(compatibility="warn")


def test_warnings_land_on_the_callers_line_not_export_plumbing() -> None:
    # The distance from the warn call to user code differs per entry point,
    # so the stacklevel is measured; every public route must attribute the
    # warning to this file, not to export.py or preflight.py internals.
    chart = _lossy_chart()
    with pytest.warns(StyleCompatibilityWarning) as caught:
        chart.to_png(compatibility="warn")
        chart.figure().to_svg(compatibility="warn")
        chart.to_image("jpeg", compatibility="warn")
    assert [w.filename for w in caught] == [__file__] * len(caught)


# -- strict ------------------------------------------------------------------


def test_strict_refuses_before_emission_with_the_report_attached(tmp_path) -> None:
    target = tmp_path / "chart.png"
    with pytest.raises(StyleCompatibilityError) as excinfo:
        _lossy_chart().write_image(target, compatibility="strict")
    assert not target.exists(), "strict must fail before any bytes are written"
    report = excinfo.value.report
    assert not report.lossless
    assert any(f.slot == "legend" for f in report.findings)
    assert "chromium" in str(excinfo.value).lower()


def test_strict_passes_lossless_exports_untouched() -> None:
    chart = _chart(styles={"title": {"font-size": 18}})
    assert chart.to_png(compatibility="strict") == chart.to_png()
    assert chart.to_svg(compatibility="strict") == chart.to_svg()


def test_strict_batch_fails_whole_before_any_file(tmp_path) -> None:
    clean, lossy = _chart(), _lossy_chart()
    paths = [tmp_path / "a.png", tmp_path / "b.png"]
    with pytest.raises(StyleCompatibilityError):
        export.write_images([clean, lossy], [str(p) for p in paths], compatibility="strict")
    assert not any(p.exists() for p in paths)


# -- the engine contract -----------------------------------------------------


def test_no_mode_reroutes_an_explicit_engine() -> None:
    # Chromium pin + lossy styling: the browser renders the cascade, so every
    # mode proceeds without warning or error — and none of them may fall back
    # to native. Native pin + lossy styling: strict refuses rather than
    # re-routing to Chromium.
    chart = _lossy_chart()
    if export.find_chromium() is not None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", StyleCompatibilityWarning)
            data = chart.to_png(engine=export.Engine.chromium, compatibility="strict")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(StyleCompatibilityError):
        chart.to_png(engine=export.Engine.default, compatibility="strict")


def test_resolution_errors_precede_and_outrank_mode_logic() -> None:
    # custom_css with a pinned native engine raises today's ValueError in
    # every mode — never a StyleCompatibilityError, never a silent re-route.
    # The lossy chart is the load-bearing case: enforcement would otherwise
    # run its preflight (and warn or raise) before the resolution check.
    for chart in (_chart(), _lossy_chart()):
        for mode in ("legacy", "warn", "strict"):
            with warnings.catch_warnings():
                warnings.simplefilter("error", StyleCompatibilityWarning)
                with pytest.raises(ValueError, match="custom_css requires") as excinfo:
                    chart.to_png(
                        engine=export.Engine.default, custom_css=".x{}", compatibility=mode
                    )
            assert not isinstance(excinfo.value, StyleCompatibilityError)
            with pytest.raises(ValueError, match="custom_css requires") as excinfo:
                chart.to_image(
                    "png", engine=export.Engine.default, custom_css=".x{}", compatibility=mode
                )
            assert not isinstance(excinfo.value, StyleCompatibilityError)


def test_auto_with_custom_css_is_lossless_in_every_mode() -> None:
    if export.find_chromium() is None:
        pytest.skip("Chromium unavailable")
    chart = _lossy_chart()
    with warnings.catch_warnings():
        warnings.simplefilter("error", StyleCompatibilityWarning)
        data = chart.to_image("png", custom_css=".x{}", compatibility="strict")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


# -- routing symmetry --------------------------------------------------------


def test_every_image_entry_point_honors_the_mode(tmp_path) -> None:
    chart = _lossy_chart()
    with pytest.raises(StyleCompatibilityError):
        chart.to_image("jpeg", compatibility="strict")
    with pytest.raises(StyleCompatibilityError):
        chart.to_svg(compatibility="strict")
    with pytest.raises(StyleCompatibilityError):
        chart.figure().write_image(tmp_path / "x.pdf", compatibility="strict")
    with pytest.raises(StyleCompatibilityError):
        export.to_png(chart.figure(), compatibility="strict")


def test_html_rejects_a_compatibility_mode_like_other_inapplicable_options(
    tmp_path,
) -> None:
    # HTML renders the full cascade; there is nothing for a mode to check, so
    # write_image treats it like the other options HTML cannot honor.
    with pytest.raises(ValueError, match="compatibility"):
        _chart().write_image(tmp_path / "chart.html", compatibility="strict")
    # The default passes through untouched.
    _chart().write_image(tmp_path / "chart2.html")


def test_batch_validates_the_mode_vocabulary_even_for_all_html(tmp_path) -> None:
    # A mixed batch legitimately carries a mode for its image entries, so
    # HTML entries are exempt rather than rejecting the whole batch — but the
    # vocabulary is validated up front, so a typo fails an all-HTML batch too
    # instead of passing silently.
    chart = _lossy_chart()
    with pytest.raises(ValueError, match="compatibility"):
        export.write_images([chart], [str(tmp_path / "a.html")], compatibility="stricted")
    # strict + only HTML: nothing to check, bytes written.
    export.write_images([chart], [str(tmp_path / "b.html")], compatibility="strict")
    assert (tmp_path / "b.html").exists()


def test_strict_svg_remediation_does_not_recommend_a_refused_engine() -> None:
    # SVG is native-only; a strict SVG failure must not point at
    # engine=Engine.chromium, which that format rejects.
    with pytest.raises(StyleCompatibilityError) as svg_err:
        _lossy_chart().to_svg(compatibility="strict")
    assert "SVG is native-only" in str(svg_err.value)
    with pytest.raises(StyleCompatibilityError) as png_err:
        _lossy_chart().to_png(compatibility="strict")
    assert "engine=Engine.chromium or to_html()" in str(png_err.value)
