"""The capability registry has to be checkable, or it is just a nicer README.

`benchmarks/categories.py` set the pattern for performance and left one gap:
nothing asserts that the committed markdown table matches the registry, so
`spec/benchmarks/results.md` is hand-maintained and can drift. This module
closes that gap for customization — the registry is pinned to `styles.py` and
`dom.py`, and the generated document is pinned to the registry.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from xy import styles
from xy.dom import CHART_DOM_SLOTS
from xy.styling import capabilities as caps

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "spec" / "api" / "capability-matrix.md"


def _compiled_property_names() -> set[str]:
    return {
        prop
        for kind in styles._MARK_KINDS
        for prop in styles._supported_mark_style_properties(kind)
    }


def test_registry_covers_exactly_the_properties_styles_compiles() -> None:
    # The point of the registry is that it cannot quietly fall behind the
    # implementation. A new property with no entry fails here; so does an entry
    # for a property that was removed.
    registered = {p.id for p in caps.MARK_STYLE_PROPERTIES if p.status != "planned"}
    assert registered == _compiled_property_names()


def test_planned_properties_are_exactly_the_ones_style_still_refuses() -> None:
    # There are no planned rows today; the registry lists what ships. The guard
    # stays so that if one is ever added, it has to actually be refused —
    # a `planned` row the implementation quietly accepts would understate the
    # library, which is the direction that is easy to miss.
    for prop in caps.MARK_STYLE_PROPERTIES:
        if prop.status != "planned":
            continue
        assert prop.id not in _compiled_property_names(), (
            f"{prop.id!r} is marked planned but styles.py now compiles it"
        )


def test_registry_covers_exactly_the_public_dom_slots() -> None:
    assert tuple(slot.id for slot in caps.CHART_SLOTS) == CHART_DOM_SLOTS


def test_axis_style_registry_covers_the_compiler_vocabulary() -> None:
    expected = (
        styles._AXIS_COLOR_PROPERTIES
        | styles._AXIS_FONT_PROPERTIES
        | styles._AXIS_LENGTH_PROPERTIES
        | styles._AXIS_SIZE_PROPERTIES
        | styles._AXIS_COMPAT_PROPERTIES
        | {"tick_direction", "tick_label_anchor"}
    )
    assert set(caps.axis_style_keys()) == expected


def test_property_kinds_are_derived_not_restated() -> None:
    # `kinds` reads from styles.py at access time rather than being typed out,
    # so there is no second list to keep in sync. Guard that it stays that way.
    for prop in caps.MARK_STYLE_PROPERTIES:
        for kind in prop.kinds:
            assert prop.id in styles._supported_mark_style_properties(kind)
        if prop.status != "planned":
            assert prop.kinds, f"{prop.id!r} is shipped but no mark kind accepts it"


def test_support_and_status_vocabularies_are_closed() -> None:
    for prop in caps.MARK_STYLE_PROPERTIES:
        assert set(prop.support) == set(caps.RENDERERS)
        assert set(prop.support.values()) <= caps.SUPPORT_LEVELS
        assert prop.status in caps.STATUSES
        assert prop.vocabulary in caps.VOCABULARIES
    for slot in caps.CHART_SLOTS:
        assert set(slot.support) == set(caps.SURFACES)
        assert set(slot.support.values()) <= caps.SUPPORT_LEVELS
    for point in caps.EXTENSION_POINTS:
        assert point.status in caps.STATUSES


def test_every_partial_or_missing_entry_explains_itself() -> None:
    # "none" is allowed and several are deliberate — but an unexplained gap is
    # indistinguishable from a bug, so anything short of `full` owes a reason.
    for prop in caps.MARK_STYLE_PROPERTIES:
        if any(level != "full" for level in prop.support.values()):
            assert prop.notes.strip(), f"{prop.id!r} is not full everywhere and says nothing"
    for slot in caps.CHART_SLOTS:
        if slot.support["native_raster"] == "partial":
            assert slot.notes.strip() and slot.channel.strip()


def test_the_shipped_extension_point_is_the_one_that_exists() -> None:
    import xy

    shipped = {e.id for e in caps.EXTENSION_POINTS if e.status == "shipped"}
    assert shipped == {"mark_plugin_composition"}
    assert callable(xy.register_mark)
    for point in caps.EXTENSION_POINTS:
        if point.status == "shipped":
            assert point.entry_point and point.limits, f"{point.id!r} claims no limits"


def test_the_committed_matrix_is_regenerated_not_hand_edited() -> None:
    # The gap `benchmarks/categories.py` left open: a committed table nothing
    # checks. Running the generator must be a no-op on a clean tree.
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_capability_matrix.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_matrix_names_every_property_and_slot() -> None:
    text = REPORT.read_text(encoding="utf-8")
    for prop in caps.MARK_STYLE_PROPERTIES:
        assert f"`{prop.id}`" in text
    for slot in caps.CHART_SLOTS:
        assert f"`{slot.id}`" in text
