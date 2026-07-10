from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_release_version.py"
    spec = importlib.util.spec_from_file_location("check_release_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_release_version = _load_module()


def _files(tmp_path: Path, version: str, changelog_heading: str) -> tuple[Path, Path]:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "xy"\nversion = "{version}"\n')
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"# Changelog\n\n{changelog_heading}\n\n- Something.\n")
    return pyproject, changelog


def test_gate_passes_when_tag_version_and_changelog_agree(tmp_path: Path) -> None:
    pyproject, changelog = _files(tmp_path, "0.2.0", "## [0.2.0] — 2026-07-09")

    assert check_release_version.check_release("v0.2.0", pyproject, changelog) == []


def test_gate_accepts_plain_hyphen_date_separator(tmp_path: Path) -> None:
    pyproject, changelog = _files(tmp_path, "0.2.0", "## [0.2.0] - 2026-07-09")

    assert check_release_version.check_release("v0.2.0", pyproject, changelog) == []


def test_gate_rejects_tag_version_mismatch(tmp_path: Path) -> None:
    pyproject, changelog = _files(tmp_path, "0.1.0", "## [0.1.0] — 2026-07-09")

    errors = check_release_version.check_release("v0.2.0", pyproject, changelog)

    assert any("does not match pyproject version" in e for e in errors)


def test_gate_rejects_undated_changelog_entry(tmp_path: Path) -> None:
    pyproject, changelog = _files(tmp_path, "0.1.0", "## [0.1.0] — unreleased development line")

    errors = check_release_version.check_release("v0.1.0", pyproject, changelog)

    assert any("no dated" in e for e in errors)


def test_gate_rejects_missing_changelog_entry(tmp_path: Path) -> None:
    pyproject, changelog = _files(tmp_path, "0.3.0", "## [0.2.0] — 2026-07-09")

    errors = check_release_version.check_release("v0.3.0", pyproject, changelog)

    assert any("no dated" in e for e in errors)


def test_main_requires_a_tag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    pyproject, changelog = _files(tmp_path, "0.1.0", "## [0.1.0] — 2026-07-09")

    rc = check_release_version.main(["--pyproject", str(pyproject), "--changelog", str(changelog)])

    assert rc == 1


def test_release_workflow_wires_the_gate() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    assert "scripts/check_release_version.py" in workflow
    assert "if: github.event_name == 'push'" in workflow
