from __future__ import annotations

from pathlib import Path

from scripts import audit_dependencies
from scripts import verify_dependency_lock_inventory as inventory

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_recognizes_supported_lockfile_families() -> None:
    recognized = {
        "Cargo.lock",
        "Pipfile.lock",
        "bun.lockb",
        "go.sum",
        "gradle.lockfile",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "Package.resolved",
        "packages.lock.json",
        "pdm.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pylock.dev.toml",
        "requirements-docs.lock",
        "uv.lock",
        "yarn.lock",
    }
    ignored = {"application.lock", "requirements.txt", "package.json", "uv.toml"}

    assert all(inventory._is_lockfile(Path(name)) for name in recognized)
    assert not any(inventory._is_lockfile(Path(name)) for name in ignored)


def test_inventory_includes_audited_and_frozen_evidence_locks() -> None:
    actual = inventory.find_dependency_lockfiles()

    assert actual == inventory.EXPECTED_LOCKFILES
    assert inventory.AUDITED_LOCKFILES.isdisjoint(inventory.FROZEN_EVIDENCE_LOCKFILES)
    assert all("launch_baselines" in path for path in inventory.FROZEN_EVIDENCE_LOCKFILES)
    assert set(audit_dependencies.AUDIT_HANDLERS) == inventory.AUDITED_LOCKFILES


def test_dependency_audit_uses_the_inventory_and_every_active_ecosystem(monkeypatch) -> None:
    commands: list[tuple[str, ...]] = []

    monkeypatch.setattr(audit_dependencies, "_require_tools", lambda: None)
    monkeypatch.setattr(
        audit_dependencies,
        "_run",
        lambda _label, command, **_kwargs: commands.append(command),
    )

    assert audit_dependencies.main() == 0
    assert (
        audit_dependencies.sys.executable,
        "scripts/verify_dependency_lock_inventory.py",
    ) in commands
    assert any(command[:2] == ("cargo", "audit") for command in commands)
    assert any(command[:2] == ("npm", "audit") for command in commands)
    assert any(command[:2] == ("bun", "audit") for command in commands)
    pylock_exports = [command for command in commands if command[:2] == ("uv", "export")]
    pylock_audits = [command for command in commands if "pip-audit" in command]
    assert len(pylock_exports) == 2
    assert all("--format" in command and "pylock.toml" in command for command in pylock_exports)
    assert len(pylock_audits) == 3
    assert all("--locked" in command for command in pylock_audits[:2])


def test_security_workflow_uses_the_shared_local_audit_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "security-audit.yml").read_text(encoding="utf-8")

    assert "run: make PYTHON=python3 check-dependency-audit" in workflow
    assert 'bun-version: "1.4.2"' in workflow
    assert '"scripts/audit_dependencies.py"' in workflow
