"""Schema v1 of the ResolvedStyleSnapshot: interned, concrete, versioned.

Three contracts, each load-bearing for a later phase: declarations intern
(the size budget assumes repeated chrome shares records), values are
concrete (a var()/em that slips through re-creates per-renderer divergence
inside the IR), and the schema refuses versions and vocabulary it does not
know (growing either is a deliberate version bump, never an accident).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from xy.styling import resolved as rs

ROOT = Path(__file__).resolve().parents[1]


def _env() -> rs.SnapshotEnvironment:
    return rs.SnapshotEnvironment(width=640.0, height=400.0, dpr=2.0, color_scheme="dark")


# -- interning ---------------------------------------------------------------


def test_identical_declarations_intern_to_one_record_in_any_order() -> None:
    builder = rs.SnapshotBuilder()
    first = builder.add("tick_label", {"font-size": 11, "color": "#94a3b8"})
    second = builder.add("tick_label", {"color": "#94a3b8", "font-size": 11.0})
    assert first == second == 0
    snapshot = builder.build(_env())
    assert len(snapshot.declarations) == 1
    assert len(snapshot.instances) == 2


def test_a_dense_axis_stays_inside_the_size_budget() -> None:
    # 400 tick labels + 60 legend rows styled alike: the spec's 50 KB
    # uncompressed budget assumes exactly this shape. Assert with headroom so
    # growth is a decision, not drift.
    builder = rs.SnapshotBuilder()
    for i in range(400):
        builder.add(
            "tick_label",
            {"font-size": 11, "color": "#94a3b8", "font-weight": 500},
            qualifiers=("x", "major", str(i)),
            geometry=(4.0 * i, 380.0, 24.0, 12.0),
            content=str(i),
        )
    for i in range(60):
        builder.add(
            "legend_label",
            {"font-size": 12, "color": "#e2e8f0"},
            qualifiers=(f"series-{i}",),
            content=f"series {i}",
        )
    snapshot = builder.build(_env(), style_epoch=7)
    assert len(snapshot.declarations) == 2
    assert len(snapshot.instances) == 460
    # ~38.6 KB when this landed; the spec budget is 50 KB uncompressed. The
    # gap is the schema's headroom — a change that eats it shows up here as
    # a decision to make, not after a capture starts failing in the field.
    assert snapshot.payload_bytes() < 50_000


def test_builder_output_is_insertion_order_independent() -> None:
    a, b = rs.SnapshotBuilder(), rs.SnapshotBuilder()
    a.add("title", {"font-size": 18, "color": "#fff"})
    a.add("axis_title", {"font-size": 12})
    b.add("axis_title", {"font-size": 12})
    b.add("title", {"color": "#fff", "font-size": 18})
    left = a.build(_env()).declarations
    right = b.build(_env()).declarations
    assert set(map(tuple, (d.items() for d in left))) == set(map(tuple, (d.items() for d in right)))


def test_empty_declarations_are_refused() -> None:
    with pytest.raises(ValueError, match="styles nothing"):
        rs.SnapshotBuilder().intern({})


# -- concreteness ------------------------------------------------------------


@pytest.mark.parametrize(
    "value, why",
    [
        ("var(--chart-fg)", "cascade"),
        ("calc(100% - 8px)", "cascade"),
        ("env(safe-area-inset-top)", "cascade"),
        ("inherit", "cascade"),
        ("1.5em", "re-derive"),
        ("120%", "re-derive"),
        ("2rem", "re-derive"),
        (float("nan"), "finite"),
        (float("inf"), "finite"),
        (True, "numbers or strings"),
        (None, "numbers or strings"),
        ("", "empty"),
    ],
)
def test_unresolved_values_are_rejected_with_the_reason(value, why) -> None:
    with pytest.raises(ValueError, match=why):
        rs.assert_resolved("font-size", value)


def test_concrete_values_pass_unchanged() -> None:
    assert rs.assert_resolved("font-size", 11) == 11.0
    assert rs.assert_resolved("color", "#94a3b8") == "#94a3b8"
    assert rs.assert_resolved("stroke-width", "2px") == "2px"
    assert rs.assert_resolved("background-image", "linear-gradient(#000, #fff)")
    assert rs.assert_resolved("transform", "matrix(1, 0, 0, 1, 4, 8)")


def test_vocabulary_is_closed_per_version() -> None:
    with pytest.raises(ValueError, match="STYLE_SNAPSHOT_VERSION"):
        rs.assert_resolved("backdrop-filter", "blur(4px)")
    assert len(rs.PROPERTIES_V1) == len(set(rs.PROPERTIES_V1))


def test_tokens_carry_open_names_but_the_same_value_contract() -> None:
    builder = rs.SnapshotBuilder()
    builder.add("title", {"font-size": 18})
    snapshot = builder.build(_env(), tokens={"--chart-legend-bg": "#0f172a"})
    assert snapshot.tokens["--chart-legend-bg"] == "#0f172a"
    with pytest.raises(ValueError, match="cascade"):
        builder.build(_env(), tokens={"--chart-legend-bg": "var(--slate-900)"})


# -- wire round-trip ---------------------------------------------------------


def test_payload_round_trips_exactly() -> None:
    builder = rs.SnapshotBuilder()
    builder.add(
        "tick_label",
        {"font-size": 11, "color": "#94a3b8"},
        qualifiers=("y", "major", "3"),
        geometry=(12.0, 40.0, 30.0, 12.0),
        content="1,000",
    )
    builder.add("legend", {"background": "#0f172a", "border-radius": 6})
    snapshot = builder.build(
        _env(),
        tokens={"--chart-fg": "#e2e8f0"},
        states=("hover",),
        unrepresentable=("backdrop-filter",),
        style_epoch=3,
    )
    payload = snapshot.to_payload()
    assert rs.snapshot_from_payload(payload).to_payload() == payload


def test_unknown_versions_are_refused_not_guessed() -> None:
    payload = rs.SnapshotBuilder().build(_env()).to_payload()
    payload["version"] = rs.STYLE_SNAPSHOT_VERSION + 1
    with pytest.raises(ValueError, match="refusing to guess"):
        rs.snapshot_from_payload(payload)


def test_malformed_payloads_fail_loudly() -> None:
    builder = rs.SnapshotBuilder()
    builder.add("title", {"font-size": 18})
    good = builder.build(_env()).to_payload()

    dangling = {**good, "instances": [{"s": "title", "d": 5}]}
    with pytest.raises(ValueError, match="absent"):
        rs.snapshot_from_payload(dangling)

    unknown_slot = {**good, "instances": [{"s": "not_a_slot", "d": 0}]}
    with pytest.raises(ValueError, match="unknown slot"):
        rs.snapshot_from_payload(unknown_slot)

    bad_geometry = {**good, "instances": [{"s": "title", "d": 0, "g": [1.0, 2.0]}]}
    with pytest.raises(ValueError, match="four finite"):
        rs.snapshot_from_payload(bad_geometry)

    smuggled = {**good, "declarations": [{"color": "var(--fg)"}]}
    with pytest.raises(ValueError, match="cascade"):
        rs.snapshot_from_payload(smuggled)


def test_environment_is_validated() -> None:
    with pytest.raises(ValueError, match="color_scheme"):
        rs.SnapshotBuilder().build(
            rs.SnapshotEnvironment(width=100, height=100, color_scheme="sepia")
        )


# -- the TypeScript mirror ---------------------------------------------------


def test_the_committed_typescript_mirror_is_regenerated_not_hand_edited() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_style_snapshot_types.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_mirror_names_every_property_and_the_version() -> None:
    text = (ROOT / "js" / "src" / "14_style_snapshot.ts").read_text(encoding="utf-8")
    for prop in rs.PROPERTIES_V1:
        assert f'"{prop}"' in text
    assert f"STYLE_SNAPSHOT_VERSION = {rs.STYLE_SNAPSHOT_VERSION}" in text
