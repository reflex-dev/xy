"""The comparison matrix quotes numbers; those numbers have to still be true.

`spec/benchmarks/methodology.md` bans numbers in prose that no artifact backs.
The customization comparison is prose by necessity — most of its rows are
capability questions, not measurements — so the parts that *are* countable are
checked here against the registry they came from. The rest is held to a
different standard: it must name its method, and it must keep its losses.
"""

from __future__ import annotations

import re
from pathlib import Path

from xy.styling import capabilities as caps

DOC = Path(__file__).resolve().parents[1] / "spec" / "api" / "customization-vs-alternatives.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_the_xy_counts_match_the_registry() -> None:
    text = _text()
    counts = caps.summary()

    assert f"{counts['mark_style_properties_shipped']} shipped mark style properties" in text
    assert f"{counts['chart_slots']} chrome slots" in text
    # Added after a fresh-agent evaluation caught this line quoting 15 axis
    # keys once a 16th had shipped. Every count the document states is pinned;
    # an unpinned one is the drift this whole chain exists to prevent.
    assert f"{counts['axis_style_keys']} axis keys" in text


def test_every_row_names_its_method() -> None:
    # A row without a method is an assertion, and this document exists to not be
    # a pile of assertions. Both tables end in a method column.
    rows = [
        line
        for line in _text().splitlines()
        if line.startswith("| ") and "---" not in line and not line.startswith("| Question")
    ]
    matrix_rows = [r for r in rows if r.rstrip().endswith(("| schema |", "| code |", "| docs |"))]
    assert len(matrix_rows) >= 12, "expected the win and loss tables to carry method columns"


def test_the_loss_table_is_not_empty_and_names_who_wins() -> None:
    # The single most important property of this document. A matrix where XY
    # wins every row is evidence of nothing, so an edit that empties the loss
    # table has to fail rather than read as an improvement.
    section = _text().split("## What XY is genuinely worse at", 1)
    assert len(section) == 2, "the loss section must exist"
    body = section[1].split("## ", 1)[0]
    rows = [line for line in body.splitlines() if line.startswith("| ") and "---" not in line]
    data_rows = [r for r in rows if not r.startswith("| Question")]
    assert len(data_rows) >= 6, "the loss table must keep its rows"
    assert all("**" in row for row in data_rows), "each loss must name the library that wins"


def test_pinned_competitor_versions_match_the_benchmark_constraints() -> None:
    # Same rule as the benchmark harness: a comparison against an unpinned
    # version is a comparison against nothing in particular.
    text = _text()
    pins = Path(__file__).resolve().parents[1] / "benchmarks" / "requirements-ci.in"
    pinned = dict(
        re.findall(r"^([a-z0-9-]+)==([0-9.]+)", pins.read_text(encoding="utf-8"), re.MULTILINE)
    )
    for package, label in (("plotly", "Plotly"), ("bokeh", "Bokeh"), ("matplotlib", "Matplotlib")):
        assert f"{label} {pinned[package]}" in text, (
            f"{label} is pinned at {pinned[package]} but the comparison quotes another version"
        )


def test_breadth_is_named_as_a_loss_not_a_win() -> None:
    # The one claim shape most likely to creep in and least defensible.
    text = _text()
    assert "**Do not claim breadth.**" in text
    assert "most customizable" in text.split("never defensible", 1)[1]
