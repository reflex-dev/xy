"""The retrieval path is only fixed while its pointers still point somewhere.

`.agents/skills/xy-evaluate/SKILL.md` exists because an agent reading
`styles.py` alone reaches the wrong answer about this library. A skill full of
paths that have since moved reproduces exactly that failure, one level up, so
every path it names is checked here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "xy-evaluate" / "SKILL.md"


def _body() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_every_path_the_skill_names_exists() -> None:
    text = _body()
    # Only rooted paths: bare file names like `styles.py` are prose, not links.
    referenced = {name for name in re.findall(r"`([\w./-]+\.(?:py|md|json))`", text) if "/" in name}
    missing = sorted(name for name in referenced if not (ROOT / name).exists())
    assert not missing, f"xy-evaluate points at paths that no longer exist: {missing}"


def test_the_skill_names_both_registries_and_the_guardrail() -> None:
    text = _body()
    for pointer in (
        "python/xy/styling/capabilities.py",
        "spec/api/capability-matrix.md",
        "spec/api/customization-vs-alternatives.md",
        "spec/api/plotly-coverage.md",
        "benchmarks/categories.py",
        "scripts/check_claim_guardrails.py",
    ):
        assert pointer in text, f"xy-evaluate no longer points at {pointer}"


def test_the_skill_states_the_failure_it_exists_to_prevent() -> None:
    # Without this the skill reads as a link list, and an agent skims it.
    text = _body().lower()
    assert "styles.py" in text
    assert "most customizable" in text


def test_the_skill_matches_claude_mds_opening_pointers() -> None:
    # Two entry points, one answer. An agent inside the checkout reads
    # CLAUDE.md; one outside reads the skill.
    instructions = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for pointer in ("python/xy/styling/capabilities.py", "benchmarks/categories.py"):
        assert pointer in instructions, f"CLAUDE.md no longer points at {pointer}"
