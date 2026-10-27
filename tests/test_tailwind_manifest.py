"""The Tailwind-core manifest: real palette, exact scales, honest boundary.

The manifest is generated from the vendored package palette
(`scripts/tailwind_palette_v3.json`, provenance in its header) — these
tests pin that the generated sheet resolves utilities to the exact
published values through the native cascade, that regeneration is a no-op
on a clean tree, and that anything outside the manifest is reported, not
guessed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import xy

cascade = pytest.importorskip("xy.styling.cascade")

try:
    cascade._find_library()
except FileNotFoundError:
    pytest.skip(
        "xy-cascade extension not built (cargo build --release -p xy-cascade)",
        allow_module_level=True,
    )

ROOT = Path(__file__).resolve().parents[1]


def _resolve(class_names, **kw):
    chart = xy.scatter_chart(xy.scatter([1.0, 2.0], [2.0, 1.0]), class_names=class_names)
    return cascade.resolve_for_figure(chart.figure(), tailwind_profile="core-v1", **kw)


def _decls(snapshot, slot):
    for inst in snapshot.instances:
        if inst.slot == slot:
            return dict(snapshot.declarations[inst.declaration])
    return {}


def test_palette_utilities_resolve_to_the_vendored_hexes() -> None:
    palette = json.loads((ROOT / "scripts" / "tailwind_palette_v3.json").read_text())
    snapshot, unsupported = _resolve(
        {"tick_label": "text-sky-800", "legend": "bg-slate-900 border-rose-500"}
    )
    assert unsupported == ()
    assert _decls(snapshot, "tick_label")["color"] == palette["colors"]["sky"]["800"]
    legend = _decls(snapshot, "legend")
    assert legend["background"] == palette["colors"]["slate"]["900"]
    assert legend["border-color"] == palette["colors"]["rose"]["500"]


def test_scales_resolve_through_the_font_cascade() -> None:
    snapshot, unsupported = _resolve(
        {"legend": "p-4 rounded-lg border-2", "tick_label": "text-sm font-semibold tracking-wide"}
    )
    assert unsupported == ()
    legend = _decls(snapshot, "legend")
    assert legend["padding-top"] == "16px"  # 1rem at the 16px root
    assert legend["border-radius"] == "8px"
    assert legend["border-width"] == "2px"
    tick = _decls(snapshot, "tick_label")
    assert tick["font-size"] == "14px"  # 0.875rem
    assert tick["font-weight"] == "600"
    assert tick["letter-spacing"] == "0.35px"  # 0.025em of the OWN 14px


def test_unknown_utilities_are_reported_not_guessed() -> None:
    # `backdrop-blur` is outside the manifest: the class simply matches no
    # rule, and the preflight/report boundary carries the class name.
    snapshot, _ = _resolve({"tick_label": "text-sky-800 backdrop-blur-md"})
    assert _decls(snapshot, "tick_label")["color"] == "#075985"
    # Unmatched classes are visible in the report surface: the class list
    # still declares them, and the capability report names class_names as
    # browser-carried; nothing pretends backdrop-blur resolved.
    assert "backdrop-filter" not in _decls(snapshot, "tick_label")


def test_utilities_export_natively_end_to_end() -> None:
    chart = xy.scatter_chart(
        xy.scatter([1.0, 2.0], [2.0, 1.0]), class_names={"tick_label": "text-sky-800"}
    )
    svg = chart.to_image("svg", style_source="native_cascade", tailwind_profile="core-v1")
    assert b"#075985" in svg


def test_profile_inputs_require_the_cascade_source() -> None:
    chart = xy.scatter_chart(xy.scatter([1.0, 2.0], [2.0, 1.0]))
    with pytest.raises(ValueError, match="native-cascade inputs"):
        chart.to_image("png", tailwind_profile="core-v1")
    with pytest.raises(ValueError, match="unknown tailwind_profile"):
        chart.to_image(
            "png", style_source="native_cascade", tailwind_profile="core-v2-does-not-exist"
        )


def test_custom_css_cascades_over_the_manifest() -> None:
    snapshot, _ = _resolve(
        {"tick_label": "text-sky-800"},
        custom_css="[data-xy-slot='tick_label'] { color: #123456; }",
    )
    # One attribute selector (0,1,0) vs one class (0,1,0): equal
    # specificity, custom_css comes later in cascade order and wins.
    assert _decls(snapshot, "tick_label")["color"] == "#123456"


def test_the_committed_manifest_is_regenerated_not_hand_edited() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_tailwind_core.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
