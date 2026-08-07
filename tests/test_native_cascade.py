"""The mount-free native cascade: profile resolution without a browser.

Skips cleanly when the optional extension is not built (CI builds it; a
contributor who has not run `cargo build --release -p xy-cascade` gets a
skip naming the command, not a red suite). Everything here mirrors a
browser-verifiable behavior; the differential smoke
(`scripts/cascade_differential_smoke.py`) compares against live Chromium.
"""

from __future__ import annotations

import pytest

import xy
from xy.styling.preflight import StyleCompatibilityError, StyleCompatibilityWarning

cascade = pytest.importorskip("xy.styling.cascade")

try:
    cascade._find_library()
except FileNotFoundError:
    pytest.skip(
        "xy-cascade extension not built (cargo build --release -p xy-cascade)",
        allow_module_level=True,
    )


def _chart(**props):
    return xy.scatter_chart(xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]), **props)


def _decls(snapshot, slot):
    for inst in snapshot.instances:
        if inst.slot == slot:
            return dict(snapshot.declarations[inst.declaration])
    return {}


# -- resolver semantics -------------------------------------------------------


def test_classes_resolve_with_specificity_inheritance_and_units() -> None:
    chart = _chart(class_names={"tick_label": "smoke-tick", "legend": "frame"})
    snapshot, unsupported = cascade.resolve_for_figure(
        chart.figure(),
        custom_css=(
            ":root { font-size: 20px; color: #111111; }\n"
            ".smoke-tick { color: rgb(7, 89, 133); letter-spacing: 0.1em; font-size: 0.5em; }\n"
            ".frame { background: #0f172a; }"
        ),
    )
    assert unsupported == ()
    tick = _decls(snapshot, "tick_label")
    assert tick["color"] == "#075985"
    assert tick["font-size"] == "10px"  # 0.5em of the root's 20px
    assert tick["letter-spacing"] == "1px"  # 0.1em of the OWN 10px
    assert _decls(snapshot, "legend")["background"] == "#0f172a"
    # :root color inherits to slots with no own declaration.
    assert _decls(snapshot, "title").get("color") == "#111"  # lightningcss shortens hex


def test_dark_scheme_media_gates_like_a_browser() -> None:
    chart = _chart(class_names={"tick_label": "t"})
    css = (
        "@media (prefers-color-scheme: dark) { .t { color: #e2e8f0; } }\n"
        "@media (prefers-color-scheme: light) { .t { color: #0f172a; } }"
    )
    dark, _ = cascade.resolve_for_figure(chart.figure(), custom_css=css, color_scheme="dark")
    light, _ = cascade.resolve_for_figure(chart.figure(), custom_css=css, color_scheme="light")
    assert _decls(dark, "tick_label")["color"] == "#e2e8f0"
    assert _decls(light, "tick_label")["color"] == "#0f172a"


def test_out_of_profile_constructs_are_reported_never_guessed() -> None:
    chart = _chart(class_names={"tick_label": "t"})
    snapshot, unsupported = cascade.resolve_for_figure(
        chart.figure(),
        custom_css=(
            ".t:hover { color: red; }\n@keyframes spin { from { opacity: 0; } }\n.t { width: 50%; }"
        ),
    )
    assert _decls(snapshot, "tick_label").get("color") is None
    assert len(unsupported) == 3
    assert any("pseudo-class" in u for u in unsupported)
    assert any("percentage" in u for u in unsupported)


def test_stylesheet_order_is_cascade_order() -> None:
    # Earlier sheets are wider (a manifest); custom_css is narrowest-last.
    chart = _chart(class_names={"legend": "frame"})
    snapshot, _ = cascade.resolve_for_figure(
        chart.figure(),
        stylesheets=(".frame { background: #111111; padding: 4px; }",),
        custom_css=".frame { background: #222222; }",
    )
    legend = _decls(snapshot, "legend")
    assert legend["background"] == "#222"
    assert legend["padding-top"] == "4px"  # shorthand splits to schema longhands
    assert legend["padding-left"] == "4px"


def test_synthetic_tree_covers_every_slot_exactly_once() -> None:
    from xy.dom import CHART_DOM_SLOTS

    slots = [slot for slot, _parent in cascade.SYNTHETIC_TREE]
    assert sorted(slots) == sorted(CHART_DOM_SLOTS)
    seen: set[str] = set()
    for slot, parent in cascade.SYNTHETIC_TREE:
        assert parent is None or parent in seen, f"{slot} before its parent {parent}"
        seen.add(slot)


# -- export integration -------------------------------------------------------


def test_class_styled_charts_export_natively_across_formats(tmp_path) -> None:
    chart = _chart(class_names={"tick_label": "smoke-tick"})
    css = ".smoke-tick { color: rgb(7, 89, 133); }"
    svg = chart.to_image("svg", custom_css=css, style_source="native_cascade")
    assert b"#075985" in svg
    png = chart.to_png(custom_css=css, style_source="native_cascade")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = chart.write_image(tmp_path / "c.pdf", custom_css=css, style_source="native_cascade")
    assert pdf[:4] == b"%PDF"


def test_unsupported_constructs_warn_by_default_and_refuse_in_strict() -> None:
    chart = _chart(class_names={"tick_label": "t"})
    css = ".t:hover { color: red; }"
    with pytest.warns(StyleCompatibilityWarning, match="could not honor"):
        chart.to_image("svg", custom_css=css, style_source="native_cascade")
    with pytest.raises(StyleCompatibilityError, match="could not honor"):
        chart.to_image("svg", custom_css=css, style_source="native_cascade", compatibility="strict")


def test_cascade_and_snapshot_are_mutually_exclusive_sources() -> None:
    from xy.styling.resolved import SnapshotBuilder, SnapshotEnvironment

    builder = SnapshotBuilder()
    builder.add("title", {"font-size": 18})
    snap = builder.build(SnapshotEnvironment(width=100, height=100))
    with pytest.raises(ValueError, match="two sources"):
        _chart().to_image("png", style_snapshot=snap, style_source="native_cascade")
    with pytest.raises(ValueError, match="native path"):
        _chart().to_image("png", engine=xy.Engine.chromium, style_source="native_cascade")


def test_vocabulary_is_closed() -> None:
    with pytest.raises(ValueError, match="style_source"):
        _chart().to_image("png", style_source="browser")
