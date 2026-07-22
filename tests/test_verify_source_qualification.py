from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_source_qualification.py"
    spec = importlib.util.spec_from_file_location("verify_source_qualification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


qualification = _load_module()


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(("git", *args), cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release@example.com")
    (repo / "payload.txt").write_text("qualified\n", encoding="utf-8")
    _git(repo, "add", "payload.txt")
    _git(repo, "commit", "-m", "qualified source")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "v1.2.3")
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "origin", "main:refs/remotes/origin/main")
    return repo, sha


def test_git_source_accepts_exact_tagged_main_commit(tmp_path: Path) -> None:
    repo, sha = _repository(tmp_path)

    assert qualification.check_git_source(repo, sha, tag="v1.2.3") == []


def test_git_source_rejects_tag_mismatch_and_non_main_commit(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    _git(repo, "checkout", "--orphan", "detached-work")
    (repo / "side.txt").write_text("not main\n", encoding="utf-8")
    _git(repo, "add", "side.txt")
    _git(repo, "commit", "-m", "unqualified source")
    side_sha = _git(repo, "rev-parse", "HEAD")

    errors = qualification.check_git_source(repo, side_sha, tag="v1.2.3")

    assert any("not an ancestor" in error for error in errors)
    assert any("resolves to" in error and "expected exact SHA" in error for error in errors)


def test_release_metadata_reuses_version_and_changelog_gate(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "xy"\nversion = "1.2.3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [1.2.3] — 2026-07-21\n", encoding="utf-8")

    assert qualification.check_release_metadata("v1.2.3", pyproject, changelog) == []
    assert qualification.check_release_metadata("v9.9.9", pyproject, changelog)


def _api(*, sha: str, required_conclusion: str = "success", run_conclusion: str = "success"):
    def get_json(path: str):
        if "/actions/workflows/ci.yml/runs?" in path:
            return {
                "workflow_runs": [
                    {
                        "id": 91,
                        "head_sha": sha,
                        "status": "completed",
                        "conclusion": run_conclusion,
                        "run_attempt": 1,
                    },
                    {
                        "id": 90,
                        "head_sha": "0" * 40,
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                    },
                ]
            }
        if path == "/repos/reflex-dev/xy/actions/runs/91/jobs?filter=latest&per_page=100":
            return {
                "jobs": [
                    {
                        "name": "Required CI",
                        "status": "completed",
                        "conclusion": required_conclusion,
                    }
                ]
            }
        raise AssertionError(path)

    return get_json


def test_exact_sha_actions_inspection_accepts_successful_required_job() -> None:
    sha = "a" * 40

    result = qualification.inspect_required_ci(_api(sha=sha), "reflex-dev/xy", sha)

    assert result.run_id == 91
    assert result.errors == ()


def test_exact_sha_actions_inspection_rejects_skipped_required_job() -> None:
    sha = "b" * 40

    result = qualification.inspect_required_ci(
        _api(sha=sha, required_conclusion="skipped"), "reflex-dev/xy", sha
    )

    assert result.run_id is None
    assert any("skipped" in error for error in result.errors)


def test_exact_sha_actions_inspection_ignores_advisory_workflow_failure() -> None:
    sha = "c" * 40

    result = qualification.inspect_required_ci(
        _api(sha=sha, run_conclusion="failure"), "reflex-dev/xy", sha
    )

    assert result.run_id == 91
    assert result.errors == ()


def _multiple_run_api(*, sha: str, newest_status: str, newest_required: str = "failure"):
    def get_json(path: str):
        if "/actions/workflows/ci.yml/runs?" in path:
            return {
                "workflow_runs": [
                    {
                        "id": 92,
                        "head_sha": sha,
                        "status": newest_status,
                        "conclusion": None if newest_status != "completed" else "failure",
                        "run_attempt": 1,
                    },
                    {
                        "id": 91,
                        "head_sha": sha,
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                    },
                ]
            }
        if path == "/repos/reflex-dev/xy/actions/runs/92/jobs?filter=latest&per_page=100":
            return {
                "jobs": [
                    {
                        "name": "Required CI",
                        "status": "completed",
                        "conclusion": newest_required,
                    }
                ]
            }
        if path == "/repos/reflex-dev/xy/actions/runs/91/jobs?filter=latest&per_page=100":
            return {
                "jobs": [
                    {
                        "name": "Required CI",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        raise AssertionError(path)

    return get_json


def test_exact_sha_actions_inspection_waits_for_newest_run() -> None:
    sha = "d" * 40

    result = qualification.inspect_required_ci(
        _multiple_run_api(sha=sha, newest_status="in_progress"),
        "reflex-dev/xy",
        sha,
    )

    assert result.run_id is None
    assert result.active is True
    assert any("run 92" in error and "in_progress" in error for error in result.errors)


def test_exact_sha_actions_inspection_rejects_newest_failure_over_older_success() -> None:
    sha = "e" * 40

    result = qualification.inspect_required_ci(
        _multiple_run_api(sha=sha, newest_status="completed"),
        "reflex-dev/xy",
        sha,
    )

    assert result.run_id is None
    assert any("run 92" in error and "failure" in error for error in result.errors)
