"""The declared resolver: one pass, two outputs, zero drift between them.

`slot_view()` must be byte-for-byte the old `_svg.slot_styles` normalization
(the writers' output bytes depend on it), the snapshot must carry every
schema-legal declared value, and the difference between the two must be
exactly the enumerable writer-domain residue — nothing silent in the gap.
"""

from __future__ import annotations

import pytest

import xy
from xy import _svg
from xy.styling.declared import resolve_declared


def _spec(**props):
    chart = xy.scatter_chart(xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]), **props)
    spec, _buffers = chart.figure().build_payload()
    return spec


def _legacy_slot_styles(spec):
    # The pre-IR normalization, verbatim — the equivalence oracle.
    raw = (spec.get("dom") or {}).get("styles") or {}
    out = {}
    for slot, decls in raw.items():
        if not isinstance(decls, dict):
            continue
        out[str(slot)] = {
            (k if str(k).startswith("--") else str(k).replace("_", "-")): v
            for k, v in decls.items()
        }
    return out


STYLES = {
    "tick_label": {"font_weight": 600, "letter_spacing": "0.08em", "color": "#94a3b8"},
    "legend": {"background": "black", "padding": "1.2em", "row_gap": "0.4em"},
    "title": {"font-size": 18, "fill": "rgb(100% 0% 0%)"},
    "tooltip_title": {"color": "red"},
}


def test_slot_view_is_byte_equivalent_to_the_old_normalization() -> None:
    spec = _spec(styles=STYLES, style={"background": "#111"})
    view = _svg.slot_styles(spec)
    legacy = _legacy_slot_styles(spec)
    assert view == legacy
    # Object fidelity, not just equality: an authored int must stay an int,
    # because the writers' f-string emission spells 600 and 600.0 apart.
    assert isinstance(view["tick_label"]["font-weight"], int)


def test_snapshot_carries_every_schema_legal_declaration() -> None:
    styling = resolve_declared(_spec(styles=STYLES))
    by_slot = {
        inst.slot: styling.snapshot.declarations[inst.declaration]
        for inst in styling.snapshot.instances
    }
    assert by_slot["tick_label"]["font-weight"] == 600.0
    assert by_slot["tick_label"]["color"] == "#94a3b8"
    assert by_slot["title"]["fill"] == "rgb(100% 0% 0%)"
    assert by_slot["legend"]["background"] == "black"
    assert by_slot["tooltip_title"]["color"] == "red"


def test_the_residue_is_exactly_the_writer_domain_values() -> None:
    # The gap between view and snapshot is enumerable and named: legend em
    # multipliers (the legend's own unit domain) and nothing else here.
    styling = resolve_declared(_spec(styles=STYLES))
    assert styling.writer_domain == {
        "tick_label": {"letter-spacing": "0.08em"},
        "legend": {"padding": "1.2em", "row-gap": "0.4em"},
    }
    # view = snapshot declarations ∪ residue, per slot.
    view = styling.slot_view()
    for slot, residue in styling.writer_domain.items():
        for prop in residue:
            assert prop in view[slot]


def test_identical_slot_declarations_intern_once() -> None:
    spec = _spec(
        styles={
            "axis_title": {"font-size": 12, "color": "#e2e8f0"},
            "legend_title": {"color": "#e2e8f0", "font-size": 12},
        }
    )
    styling = resolve_declared(spec)
    assert len(styling.snapshot.declarations) == 1
    assert len(styling.snapshot.instances) == 2


def test_chart_tokens_ride_the_snapshot() -> None:
    styling = resolve_declared(_spec(style={"background": "#111", "--chart-fg": "#e2e8f0"}))
    assert styling.snapshot.tokens["background"] == "#111"
    assert styling.snapshot.tokens["--chart-fg"] == "#e2e8f0"


def test_unstyled_chart_resolves_to_an_empty_snapshot() -> None:
    styling = resolve_declared(_spec())
    assert styling.snapshot.declarations == ()
    assert styling.snapshot.instances == ()
    assert styling.slot_view() == {}
    assert styling.writer_domain == {}


def test_export_bytes_are_unchanged_by_the_routing() -> None:
    # The real gate: styled exports through the routed slot_styles are
    # deterministic and carry the styling the writers honored before.
    chart = xy.scatter_chart(
        xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]),
        title="t",
        styles={"tick_label": {"font_weight": 600}, "title": {"font-size": 18.0}},
    )
    svg = chart.to_svg()
    assert 'font-weight="600"' in svg
    assert svg == chart.to_svg()
    png = chart.to_png()
    assert png == chart.to_png()


@pytest.mark.parametrize("bad", [None, "x", 7])
def test_non_mapping_slot_entries_are_skipped_like_before(bad) -> None:
    spec = _spec()
    spec.setdefault("dom", {})["styles"] = {"title": bad, "legend": {"background": "black"}}
    assert _svg.slot_styles(spec) == {"legend": {"background": "black"}}
