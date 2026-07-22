#!/usr/bin/env python3
"""Qualify an exact source commit before release or deployment.

The gate proves that the source is a real commit on ``main`` and that a
successful ``Required CI`` job ran for that exact SHA. Release publication can
add ``--release-metadata`` to require tag, project-version, and dated changelog
agreement as part of the same preflight.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"[0-9a-f]{40}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}")
JsonGetter = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class RequiredCIInspection:
    run_id: int | None
    active: bool
    errors: tuple[str, ...]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )


def check_git_source(
    repo: Path,
    sha: str,
    *,
    main_ref: str = "origin/main",
    tag: str | None = None,
) -> list[str]:
    """Validate commit identity, main ancestry, and an optional exact tag."""
    errors: list[str] = []
    if SHA_RE.fullmatch(sha) is None:
        return [f"source SHA must be 40 lowercase hexadecimal characters, got {sha!r}"]
    if REF_RE.fullmatch(main_ref) is None or main_ref.startswith("-"):
        return [f"invalid main ref {main_ref!r}"]
    if tag is not None and TAG_RE.fullmatch(tag) is None:
        return [f"invalid tag {tag!r}"]

    resolved = _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}")
    if resolved.returncode != 0:
        errors.append(f"source SHA {sha} is not a commit in the checkout")
        return errors
    resolved_sha = resolved.stdout.strip()
    if resolved_sha != sha:
        errors.append(f"source SHA resolved to {resolved_sha}, expected exact commit {sha}")

    main = _git(repo, "rev-parse", "--verify", f"{main_ref}^{{commit}}")
    if main.returncode != 0:
        errors.append(f"main ancestry ref {main_ref!r} is unavailable")
    else:
        ancestor = _git(repo, "merge-base", "--is-ancestor", sha, main_ref)
        if ancestor.returncode != 0:
            errors.append(f"source SHA {sha} is not an ancestor of {main_ref}")

    if tag is not None:
        tagged = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
        if tagged.returncode != 0:
            errors.append(f"tag {tag!r} does not exist in the checkout")
        elif tagged.stdout.strip() != sha:
            errors.append(
                f"tag {tag!r} resolves to {tagged.stdout.strip()}, expected exact SHA {sha}"
            )
    return errors


def check_release_metadata(tag: str, pyproject: Path, changelog: Path) -> list[str]:
    """Reuse the release-version checker without weakening either CLI."""
    module_path = ROOT / "scripts" / "check_release_version.py"
    spec = importlib.util.spec_from_file_location("_source_qualification_release", module_path)
    if spec is None or spec.loader is None:
        return [f"cannot load release metadata checker from {module_path}"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_release(tag, pyproject, changelog)


def inspect_required_ci(
    get_json: JsonGetter,
    repository: str,
    sha: str,
    *,
    workflow: str = "ci.yml",
    required_job: str = "Required CI",
) -> RequiredCIInspection:
    """Inspect Actions runs and require the aggregate job on the exact SHA."""
    workflow_id = urllib.parse.quote(workflow, safe="")
    query = urllib.parse.urlencode({"head_sha": sha, "per_page": 100})
    payload = get_json(f"/repos/{repository}/actions/workflows/{workflow_id}/runs?{query}")
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        return RequiredCIInspection(None, False, ("Actions response has no workflow_runs list",))

    exact = [run for run in runs if isinstance(run, dict) and run.get("head_sha") == sha]
    if not exact:
        return RequiredCIInspection(
            None,
            False,
            (f"no {workflow} run exists for exact SHA {sha}",),
        )

    # Never fall back to an older success. A new run (or rerun attempt) may be
    # correcting a failure; accepting an older run while it is active or after
    # it fails would make the preflight raceable.
    newest = max(
        exact,
        key=lambda run: (int(run.get("id") or 0), int(run.get("run_attempt") or 0)),
    )
    run_id = newest.get("id")
    if not isinstance(run_id, int):
        return RequiredCIInspection(None, False, ("newest Actions run has no integer id",))
    status = newest.get("status")
    if status != "completed":
        return RequiredCIInspection(
            None,
            True,
            (f"newest Actions run {run_id} for exact SHA {sha} is {status!r}",),
        )

    jobs_payload = get_json(
        f"/repos/{repository}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"
    )
    jobs = jobs_payload.get("jobs")
    if not isinstance(jobs, list):
        return RequiredCIInspection(None, False, (f"Actions run {run_id} has no jobs list",))
    matches = [job for job in jobs if isinstance(job, dict) and job.get("name") == required_job]
    if not matches:
        return RequiredCIInspection(
            None,
            False,
            (f"Actions run {run_id} has no {required_job!r} job",),
        )
    if any(
        job.get("status") == "completed" and job.get("conclusion") == "success" for job in matches
    ):
        # Advisory jobs are intentionally non-blocking. Required CI is the
        # stable aggregate of the hard suite, so it alone controls promotion.
        return RequiredCIInspection(run_id, False, ())
    conclusions = sorted({str(job.get("conclusion")) for job in matches})
    return RequiredCIInspection(
        None,
        False,
        (
            f"newest Actions run {run_id} {required_job!r} conclusions are "
            f"{conclusions}, expected success",
        ),
    )


def _github_getter(api_url: str, token: str) -> JsonGetter:
    base = api_url.rstrip("/")

    def get_json(path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            base + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                payload = json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GitHub API request failed for {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"GitHub API returned a non-object for {path}")
        return payload

    return get_json


def wait_for_required_ci(
    get_json: JsonGetter,
    repository: str,
    sha: str,
    *,
    workflow: str,
    required_job: str,
    wait_seconds: float,
    poll_seconds: float,
) -> int:
    deadline = time.monotonic() + wait_seconds
    while True:
        inspection = inspect_required_ci(
            get_json,
            repository,
            sha,
            workflow=workflow,
            required_job=required_job,
        )
        if inspection.run_id is not None:
            return inspection.run_id
        remaining = deadline - time.monotonic()
        if remaining <= 0 or (inspection.errors and not inspection.active and wait_seconds == 0):
            raise RuntimeError("; ".join(inspection.errors))
        no_run_yet = bool(
            inspection.errors
            and inspection.errors[0].startswith("no ")
            and " run exists for exact SHA " in inspection.errors[0]
        )
        if inspection.errors and not inspection.active and not no_run_yet:
            raise RuntimeError("; ".join(inspection.errors))
        time.sleep(min(poll_seconds, remaining))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--tag")
    parser.add_argument("--release-metadata", action="store_true")
    parser.add_argument("--pyproject", type=Path, default=ROOT / "pyproject.toml")
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    parser.add_argument("--workflow", default="ci.yml")
    parser.add_argument("--required-job", default="Required CI")
    parser.add_argument("--wait-seconds", type=float, default=0.0)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    )
    args = parser.parse_args(argv)

    errors = check_git_source(args.repo, args.sha, main_ref=args.main_ref, tag=args.tag)
    if args.release_metadata:
        if args.tag is None:
            errors.append("--release-metadata requires --tag")
        else:
            errors.extend(check_release_metadata(args.tag, args.pyproject, args.changelog))
    if REPOSITORY_RE.fullmatch(args.repository) is None:
        errors.append(f"repository must be owner/name, got {args.repository!r}")
    if not args.token:
        errors.append("GitHub token is required for exact-SHA Actions verification")
    if args.wait_seconds < 0 or args.poll_seconds <= 0:
        errors.append("wait seconds must be non-negative and poll seconds must be positive")
    if errors:
        print("source qualification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    try:
        run_id = wait_for_required_ci(
            _github_getter(args.api_url, args.token),
            args.repository,
            args.sha,
            workflow=args.workflow,
            required_job=args.required_job,
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except RuntimeError as exc:
        print(f"source qualification failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"source qualification OK: {args.sha} is on {args.main_ref}; "
        f"Actions run {run_id} passed {args.required_job!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
