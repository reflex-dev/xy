from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = REPO_ROOT / "scripts" / "check_testing_spec.py"
    spec = importlib.util.spec_from_file_location("check_testing_spec", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_testing_spec = _load_module()


GOOD_README = """# Testing Specification

See [`current.md`](current.md) and [`gaps.md`](gaps.md).
"""

GOOD_CURRENT = """# Current Testing Inventory

| Surface | Evidence | Enforcement | Status | Boundary |
|---|---|---|---|---|
| Lint | `ruff check .` | `make lint` | `IMPLEMENTED` | Configured sources. |
| Widgets | `scripts/abi_smoke.py` | None | `NOT IMPLEMENTED` | See TST-NI-001. |

| Workflow | Current jobs | Testing role |
|---|---|---|
| `ci.yml` | `test`, `sdist` | Main evidence |
"""

GOOD_GAPS = """# Testing Gap Register

## P0 — Release confidence

### TST-NI-001 — Example gap

- Status: `NOT IMPLEMENTED`
- Owner: unassigned — file a tracking issue before implementation starts
- Current gap: nothing enforces the widget contract.
- Implemented when: a hard job proves it.
"""


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a minimal repository so negative controls can corrupt one fact."""
    testing = tmp_path / "spec" / "testing"
    testing.mkdir(parents=True)
    (testing / "README.md").write_text(GOOD_README, encoding="utf-8")
    (testing / "current.md").write_text(GOOD_CURRENT, encoding="utf-8")
    (testing / "gaps.md").write_text(GOOD_GAPS, encoding="utf-8")

    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "abi_smoke.py").write_text("", encoding="utf-8")
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\n", encoding="utf-8")

    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("jobs:\n  test:\n  sdist:\n", encoding="utf-8")

    monkeypatch.setattr(check_testing_spec, "ROOT", tmp_path)
    monkeypatch.setattr(check_testing_spec, "SPEC_DIR", tmp_path / "spec")
    monkeypatch.setattr(check_testing_spec, "TESTING_DIR", testing)
    monkeypatch.setattr(check_testing_spec, "MAKEFILE", tmp_path / "Makefile")
    monkeypatch.setattr(check_testing_spec, "WORKFLOW_DIR", workflows)
    return testing


def _errors() -> list[str]:
    findings = check_testing_spec.Findings()
    testing_dir = check_testing_spec.TESTING_DIR
    for path in sorted(testing_dir.rglob("*.md")):
        raw_text = path.read_text(encoding="utf-8")
        prose = check_testing_spec._strip_code_blocks(raw_text)
        check_testing_spec.check_status_vocabulary(path, prose, findings)
        check_testing_spec.check_links(path, prose, findings)
        check_testing_spec.check_repository_references(path, raw_text, findings)
        if path == testing_dir / "current.md":
            check_testing_spec.check_workflow_registry(path, raw_text, findings)
            check_testing_spec.check_evidence_rows(path, raw_text, findings)
    check_testing_spec.check_gap_register(findings)
    return findings.errors


def test_real_testing_specification_passes() -> None:
    assert check_testing_spec.main([]) == 0


def test_fixture_repository_is_clean(fake_repo: Path) -> None:
    # Guards the negative controls below: they must fail for their own reason.
    assert _errors() == []


def test_main_rejects_broken_link_outside_testing_spec(fake_repo: Path, capsys) -> None:
    design = check_testing_spec.SPEC_DIR / "design.md"
    design.write_text("# Design\n\n[retired contract](missing-contract.md)\n", encoding="utf-8")

    assert check_testing_spec.main([]) == 1
    assert "spec/design.md: broken link target missing-contract.md" in capsys.readouterr().err


def test_github_anchor_slug_keeps_separator_gaps() -> None:
    # A removed em dash leaves two spaces, and GitHub emits two hyphens. A slug
    # that collapses whitespace runs silently accepts every broken anchor.
    heading = " TST-NI-002 — Strict dashboard 10/20/50 health gate"
    assert check_testing_spec._slug(heading) == "tst-ni-002--strict-dashboard-102050-health-gate"


def test_unknown_status_value_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("`IMPLEMENTED`", "`MOSTLY IMPLEMENTED`"),
        encoding="utf-8",
    )
    assert any("unknown status value" in error for error in _errors())


def test_duplicate_gap_id_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n### TST-NI-001 — Duplicate\n\n"
        "- Status: `NOT IMPLEMENTED`\n- Implemented when: never.\n",
        encoding="utf-8",
    )
    assert any("duplicate definition of TST-NI-001" in error for error in _errors())


def test_non_sequential_gap_id_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("TST-NI-001", "TST-NI-007"),
        encoding="utf-8",
    )
    assert any("not sequential" in error for error in _errors())


def test_reference_to_undefined_gap_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("TST-NI-001", "TST-NI-099"),
        encoding="utf-8",
    )
    assert any("references undefined gap TST-NI-099" in error for error in _errors())


def test_gap_unreachable_from_current_inventory_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("See TST-NI-001.", "No gap link."),
        encoding="utf-8",
    )
    assert any("unreachable from current.md" in error for error in _errors())


def test_gap_without_completion_criteria_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("- Implemented when: a hard job proves it.\n", ""),
        encoding="utf-8",
    )
    assert any("no completion criteria" in error for error in _errors())


def test_implemented_gap_without_explicit_evidence_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "- Status: `NOT IMPLEMENTED`", "- Status: `IMPLEMENTED`"
        ),
        encoding="utf-8",
    )
    assert any("implemented but has no explicit evidence" in error for error in _errors())


def test_implemented_gap_with_evidence_and_inventory_link_is_accepted(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("- Status: `NOT IMPLEMENTED`", "- Status: `IMPLEMENTED`")
        .replace(
            "- Current gap: nothing enforces the widget contract.",
            "- Evidence: `scripts/abi_smoke.py` and the hard `test` job.\n"
            "- Current gap: closed by the cited evidence.",
        ),
        encoding="utf-8",
    )

    assert _errors() == []


def test_p0_gap_without_owner_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    path.write_text(
        re.sub(r"- Owner:[^\n]*\n", "", path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    assert any("is P0 and must name an owner" in error for error in _errors())


def test_owner_is_not_required_outside_p0(fake_repo: Path) -> None:
    path = fake_repo / "gaps.md"
    text = path.read_text(encoding="utf-8").replace("## P0 — Release confidence", "## P2 — Depth")
    path.write_text(re.sub(r"- Owner:[^\n]*\n", "", text), encoding="utf-8")
    assert not any("must name an owner" in error for error in _errors())


def test_broken_link_target_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "README.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("(current.md)", "(retired.md)"),
        encoding="utf-8",
    )
    assert any("broken link target retired.md" in error for error in _errors())


def test_broken_link_anchor_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "README.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("(gaps.md)", "(gaps.md#tst-ni-404-missing)"),
        encoding="utf-8",
    )
    assert any("broken link anchor" in error for error in _errors())


def test_missing_make_target_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("`make lint`", "`make lint-everything`"),
        encoding="utf-8",
    )
    assert any("is not a Makefile target" in error for error in _errors())


def test_missing_repository_path_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "`scripts/abi_smoke.py`", "`scripts/removed_smoke.py`"
        ),
        encoding="utf-8",
    )
    assert any("scripts/removed_smoke.py does not exist" in error for error in _errors())


def test_missing_python_symbol_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "`scripts/abi_smoke.py`", "`scripts/abi_smoke.py::removed_probe`"
        ),
        encoding="utf-8",
    )
    assert any("Python symbol" in error and "removed_probe" in error for error in _errors())


def test_incomplete_evidence_row_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "| Lint | `ruff check .` | `make lint` | `IMPLEMENTED` | Configured sources. |",
            "| Lint |  | `make lint` | `IMPLEMENTED` | Configured sources. |",
        ),
        encoding="utf-8",
    )
    assert any("evidence row has an empty required cell" in error for error in _errors())


def test_missing_workflow_job_is_rejected(fake_repo: Path) -> None:
    path = fake_repo / "current.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("`test`, `sdist`", "`test`, `renamed_job`"),
        encoding="utf-8",
    )
    assert any("ci.yml has no job `renamed_job`" in error for error in _errors())
