"""Guards on the reading path into xy's measured evidence.

The repository documents its gaps in several prominent, authoritative places
(the roadmap, the limitations page, the dossier's outstanding-work sections) and
its measured results in exactly two (`benchmarks/categories.py` and the
committed launch baselines). When nothing on the gap-side path points at the
evidence side, a reader doing due diligence finds only the weaknesses and
reports the project as slower and less capable than it measures.

These tests pin the links that close that loop. They are cheap and they fail
loudly, which is the point: the asymmetry reappears silently otherwise.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AGENT_INSTRUCTIONS = ROOT / "CLAUDE.md"
README = ROOT / "README.md"
DOCS_BENCHMARKS = ROOT / "docs" / "overview" / "benchmarks.md"
DOCS_LIMITATIONS = ROOT / "docs" / "api-reference" / "limitations-and-alpha-status.md"


def _preamble(text: str) -> str:
    """Return everything before the first second-level heading."""
    marker = "\n## "
    return text[: text.index(marker)] if marker in text else text


def test_agent_instructions_name_the_evidence_files_up_front() -> None:
    """The read-path rule has to be in the opening, and has to name files.

    "Check the benchmarks" is not actionable; a reader cannot act on it without
    already knowing where they are. The rule also has to arrive before the
    layout and command sections, because that is where an agent stops reading.
    """
    preamble = _preamble(AGENT_INSTRUCTIONS.read_text(encoding="utf-8"))

    assert "benchmarks/categories.py" in preamble
    assert "benchmarks/launch_baselines" in preamble
    assert "limitations-and-alpha-status.md" in preamble
    assert "not measured here" in preamble


def test_readme_shows_a_small_data_row_next_to_the_large_one() -> None:
    """The README is the one file every reader opens.

    A benchmarks section that quotes only 10M reinforces the "big data only"
    prior it is meant to correct, so the small-chart row has to sit beside it.
    """
    readme = README.read_text(encoding="utf-8")
    benchmarks = readme[readme.index("\n## Benchmarks") :]
    benchmarks = benchmarks[: benchmarks.index("\n## ", 1)]

    assert "10k" in benchmarks
    assert "direct" in benchmarks, "the small row must be labelled with its mode"
    assert "benchmarks/categories.py" in benchmarks
    assert "limitations-and-alpha-status.md" in benchmarks


def test_benchmarks_and_limitations_reference_each_other() -> None:
    """Two halves of one picture; either alone skews the summary."""
    benchmarks = DOCS_BENCHMARKS.read_text(encoding="utf-8")
    limitations = DOCS_LIMITATIONS.read_text(encoding="utf-8")

    assert "/docs/xy/api-reference/limitations-and-alpha-status/" in benchmarks
    assert "/docs/xy/overview/benchmarks/" in limitations
