"""Git provenance recorded by the differential gallery report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.pyplot_gallery import run_gallery as gallery_runner


def _git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=Gallery Test",
        "-c",
        "user.email=gallery@example.invalid",
        "commit",
        "-q",
        "-m",
        "initial",
    )
    return repo, _git(repo, "rev-parse", "HEAD")


def test_repository_snapshot_ignores_only_selected_output_and_test_png(tmp_path: Path) -> None:
    repo, head = _repository(tmp_path)
    output_root = repo / "artifacts" / "selected"
    start = gallery_runner._repository_snapshot(output_root, repo_root=repo)
    assert start == gallery_runner._RepositorySnapshot(head=head, dirty=False)

    output_root.mkdir(parents=True)
    (output_root / "report-part.json").write_text("{}", encoding="utf-8")
    (repo / "test.png").write_bytes(b"user artifact")
    clean_output = gallery_runner._repository_snapshot(output_root, repo_root=repo)
    assert clean_output == gallery_runner._RepositorySnapshot(head=head, dirty=False)
    assert gallery_runner._implementation_provenance(start, clean_output) == (head, False)

    (repo / "artifacts" / "sibling.txt").write_text("not selected\n", encoding="utf-8")
    unrelated = gallery_runner._repository_snapshot(output_root, repo_root=repo)
    assert unrelated.dirty is True
    assert gallery_runner._implementation_provenance(start, unrelated) == (head, True)


def test_repository_snapshot_handles_renames_across_output_boundary(tmp_path: Path) -> None:
    repo, _head = _repository(tmp_path)
    output_root = repo / "gallery-output"
    output_root.mkdir()
    (output_root / "first.txt").write_text("artifact\n", encoding="utf-8")
    _git(repo, "add", "gallery-output/first.txt")
    _git(
        repo,
        "-c",
        "user.name=Gallery Test",
        "-c",
        "user.email=gallery@example.invalid",
        "commit",
        "-q",
        "-m",
        "tracked output",
    )

    _git(repo, "mv", "gallery-output/first.txt", "gallery-output/second.txt")
    assert gallery_runner._repository_snapshot(output_root, repo_root=repo).dirty is False
    _git(
        repo,
        "-c",
        "user.name=Gallery Test",
        "-c",
        "user.email=gallery@example.invalid",
        "commit",
        "-q",
        "-m",
        "rename output",
    )

    _git(repo, "mv", "tracked.txt", "gallery-output/tracked.txt")
    assert gallery_runner._repository_snapshot(output_root, repo_root=repo).dirty is True


def test_repository_provenance_retains_start_dirtiness_and_detects_head_change(
    tmp_path: Path,
) -> None:
    repo, initial_head = _repository(tmp_path)
    output_root = repo / "gallery-output"

    (repo / "tracked.txt").write_text("dirty before run\n", encoding="utf-8")
    dirty_start = gallery_runner._repository_snapshot(output_root, repo_root=repo)
    (repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
    clean_end = gallery_runner._repository_snapshot(output_root, repo_root=repo)
    assert dirty_start.dirty is True
    assert clean_end.dirty is False
    assert gallery_runner._implementation_provenance(dirty_start, clean_end) == (
        initial_head,
        True,
    )

    clean_start = clean_end
    (repo / "second.txt").write_text("second\n", encoding="utf-8")
    _git(repo, "add", "second.txt")
    _git(
        repo,
        "-c",
        "user.name=Gallery Test",
        "-c",
        "user.email=gallery@example.invalid",
        "commit",
        "-q",
        "-m",
        "second",
    )
    changed_head = gallery_runner._repository_snapshot(output_root, repo_root=repo)
    assert changed_head.head != initial_head
    assert changed_head.dirty is False
    assert gallery_runner._implementation_provenance(clean_start, changed_head) == (None, True)


def test_configured_commit_cannot_mask_repository_head(monkeypatch, tmp_path: Path) -> None:
    repo, head = _repository(tmp_path)
    snapshot = gallery_runner._repository_snapshot(repo / "output", repo_root=repo)

    monkeypatch.setenv("XY_GALLERY_IMPLEMENTATION_COMMIT", "b" * 40)
    assert gallery_runner._implementation_provenance(snapshot, snapshot) == (head, True)

    monkeypatch.setenv("XY_GALLERY_IMPLEMENTATION_COMMIT", head)
    assert gallery_runner._implementation_provenance(snapshot, snapshot) == (head, False)

    no_repository = gallery_runner._RepositorySnapshot(head=None, dirty=None)
    assert gallery_runner._implementation_provenance(no_repository, no_repository) == (head, None)


def test_clean_in_repo_output_produces_promotion_eligible_report(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo, head = _repository(tmp_path)
    manifest_path = repo / "manifest.json"
    baseline_path = repo / "baseline.json"
    extended_spec_path = repo / "extended-environment.json"
    corpus_root = repo / "corpus"
    corpus_root.mkdir()
    manifest_path.write_text(
        json.dumps({"examples": [], "matplotlib_version": "3.11.0"}),
        encoding="utf-8",
    )
    baseline_path.write_text(json.dumps({"examples": {}}), encoding="utf-8")
    extended_spec_path.write_text(json.dumps({"examples": []}), encoding="utf-8")
    _git(repo, "add", "manifest.json", "baseline.json", "extended-environment.json")
    _git(
        repo,
        "-c",
        "user.name=Gallery Test",
        "-c",
        "user.email=gallery@example.invalid",
        "commit",
        "-q",
        "-m",
        "contract",
    )
    head = _git(repo, "rev-parse", "HEAD")

    monkeypatch.setattr(gallery_runner, "REPO_ROOT", repo)
    monkeypatch.setattr(gallery_runner, "_prewarm_mplconfig", lambda *_args: None)
    monkeypatch.delenv("XY_GALLERY_IMPLEMENTATION_COMMIT", raising=False)
    output_root = repo / "reports" / "extended"
    report = gallery_runner.run_gallery(
        output_root=output_root,
        python=Path(sys.executable),
        timeout=1,
        workers=1,
        profile="extended",
        shard=(0, 1),
        match=None,
        engines=("matplotlib", "xy"),
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        corpus_root=corpus_root,
        extended_spec_path=extended_spec_path,
    )

    assert report["implementation_commit"] == head
    assert report["implementation_dirty"] is False
    assert (output_root / "report.json").is_file()
    assert (output_root / "junit.xml").is_file()
