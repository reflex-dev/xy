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
    # Legend geometry in resolved px: before P4 this was expressible only in
    # em, which schema v1 refuses, so it was writer-domain by construction.
    "legend": {"background": "black", "padding": "12px", "gap": "6px"},
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
    # The gap between view and snapshot is enumerable and named. Since the P4
    # legend family it is exactly ONE thing: a relative-unit length, which
    # schema v1 refuses for every slot alike because it depends on a font
    # context the snapshot's consumer would have to re-derive.
    #
    # The legend contributes nothing now. Its geometry used to be expressible
    # only as em multipliers, so `padding`/`row-gap` were writer-domain by
    # construction; they resolve px today and intern like any other length.
    styling = resolve_declared(_spec(styles=STYLES))
    assert styling.writer_domain == {"tick_label": {"letter-spacing": "0.08em"}}
    # view = snapshot declarations ∪ residue, per slot.
    view = styling.slot_view()
    for slot, residue in styling.writer_domain.items():
        for prop in residue:
            assert prop in view[slot]


def test_px_legend_geometry_interns_instead_of_riding_the_residue() -> None:
    # The retirement, stated positively: the px spellings of the legend's
    # geometry are schema-legal resolved lengths and reach the snapshot.
    styling = resolve_declared(_spec(styles={"legend": {"padding": "12px", "gap": "6px"}}))
    assert styling.writer_domain == {}
    declaration = styling.snapshot.declarations[styling.snapshot.instances[0].declaration]
    # `padding` interns expanded — schema v1 carries only the longhands — and
    # the shorthand expansion resolves each side to a number on the way.
    assert declaration["padding-top"] == 12.0
    assert declaration["padding-left"] == 12.0
    # `gap` has no shorthand to expand, so it interns as the authored string;
    # a px length is a resolved value whether it is spelled 6 or "6px".
    assert declaration["gap"] == "6px"


def test_em_legend_geometry_still_reaches_the_writers_as_residue() -> None:
    # Retiring the residue did not retire the em spelling: it keeps working
    # through the writer view, it is simply no longer the ONLY spelling. An
    # em value is writer-domain for the same reason any other slot's is.
    styling = resolve_declared(_spec(styles={"legend": {"padding": "1.2em", "row_gap": "0.4em"}}))
    assert styling.writer_domain == {"legend": {"padding": "1.2em", "row-gap": "0.4em"}}
    assert styling.slot_view()["legend"]["padding"] == "1.2em"


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
