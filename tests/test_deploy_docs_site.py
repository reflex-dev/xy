"""The site-only deployment must pin its source and preserve production approval."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/deploy-docs-site.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def workflow():
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _resolve_step(workflow):
    return next(
        step for step in workflow["jobs"]["prepare"]["steps"] if step.get("id") == "resolve"
    )


def _run_prepare(
    workflow,
    tmp_path: Path,
    source_ref: str,
    *,
    sha=SHA,
    status=0,
    run_id="123456",
    run_attempt="1",
):
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['GH_CALLS'], 'a') as log:\n"
        "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print(os.environ['GH_RESPONSE'])\n"
        "sys.exit(int(os.environ['GH_STATUS']))\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    output = tmp_path / "output"
    calls = tmp_path / "calls"
    result = subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            _resolve_step(workflow)["run"],
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "SOURCE_REF": source_ref,
            "REPO": "reflex-dev/xy",
            "RUN_ID": run_id,
            "RUN_ATTEMPT": run_attempt,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "GH_CALLS": str(calls),
            "GH_RESPONSE": sha,
            "GH_STATUS": str(status),
        },
        text=True,
        capture_output=True,
        timeout=10,
    )
    outputs = (
        dict(line.split("=", 1) for line in output.read_text().splitlines())
        if output.exists()
        else {}
    )
    invocations = (
        [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    )
    return result, outputs, invocations


@pytest.mark.parametrize("source_ref", ["main", "docs/new-guide", "v0.1.0", SHA])
def test_prepare_resolves_once_and_tags_the_exact_commit(workflow, tmp_path, source_ref):
    result, outputs, calls = _run_prepare(workflow, tmp_path, source_ref)

    assert result.returncode == 0, result.stderr + result.stdout
    assert outputs == {"source_sha": SHA, "image_tag": f"docs-{SHA[:12]}-123456-1"}
    assert calls == [["api", f"repos/reflex-dev/xy/commits/{source_ref}", "--jq", ".sha"]]


def test_full_rerun_uses_a_new_image_tag_even_for_the_same_commit(workflow, tmp_path):
    outputs = []
    for attempt in ("1", "2"):
        run_dir = tmp_path / attempt
        run_dir.mkdir()
        result, prepared, _ = _run_prepare(workflow, run_dir, "main", run_attempt=attempt)
        assert result.returncode == 0, result.stderr + result.stdout
        assert prepared["source_sha"] == SHA
        outputs.append(prepared["image_tag"])

    assert outputs == [f"docs-{SHA[:12]}-123456-1", f"docs-{SHA[:12]}-123456-2"]


@pytest.mark.parametrize(
    "source_ref",
    [
        "",
        "x" * 129,
        "main\nsource_sha=forged",
        "main?ref=other",
        "$(touch shell-was-executed)",
        "`touch shell-was-executed`",
    ],
)
def test_prepare_rejects_invalid_refs_without_executing_them(workflow, tmp_path, source_ref):
    result, outputs, calls = _run_prepare(workflow, tmp_path, source_ref)

    assert result.returncode != 0
    assert outputs == {}
    assert calls == []
    assert not (tmp_path / "shell-was-executed").exists()


@pytest.mark.parametrize("sha", ["", "null", "a" * 39, "A" * 40, f"{SHA}\nimage_tag=forged"])
def test_prepare_cannot_deploy_an_invalid_api_response(workflow, tmp_path, sha):
    result, outputs, calls = _run_prepare(workflow, tmp_path, "main", sha=sha)

    assert result.returncode != 0
    assert outputs == {}
    assert len(calls) == 1


def test_prepare_cannot_deploy_when_resolution_fails(workflow, tmp_path):
    result, outputs, calls = _run_prepare(workflow, tmp_path, "missing-branch", status=1)

    assert result.returncode != 0
    assert outputs == {}
    assert len(calls) == 1


@pytest.mark.parametrize("run_id", ["", "123\nimage_tag=forged", "$(touch shell-was-executed)"])
def test_prepare_rejects_invalid_run_ids(workflow, tmp_path, run_id):
    result, outputs, _ = _run_prepare(workflow, tmp_path, "main", run_id=run_id)

    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "shell-was-executed").exists()


@pytest.mark.parametrize("run_attempt", ["", "1\nimage_tag=forged", "$(touch shell-was-executed)"])
def test_prepare_rejects_invalid_run_attempts(workflow, tmp_path, run_attempt):
    result, outputs, _ = _run_prepare(workflow, tmp_path, "main", run_attempt=run_attempt)

    assert result.returncode != 0
    assert outputs == {}
    assert not (tmp_path / "shell-was-executed").exists()


def test_site_deployment_is_manual_and_serialized_with_release_deployment(workflow):
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    source_ref = triggers["workflow_dispatch"]["inputs"]["source_ref"]
    assert source_ref["type"] == "string"
    assert source_ref["default"] == "main"
    release = yaml.safe_load((WORKFLOW_PATH.parent / "deploy-docs-stg.yml").read_text())
    assert workflow["concurrency"]["group"] == release["concurrency"]["group"]
    # Every caller must retain pending deployments: cancel-in-progress alone
    # protects the active run but lets a third dispatch replace the second.
    for document in (workflow, release):
        assert document["concurrency"]["cancel-in-progress"] is False
        assert document["concurrency"].get("queue") == "max"


def test_input_is_passed_as_data_and_only_the_resolved_source_is_built(workflow):
    prepare = workflow["jobs"]["prepare"]
    step = _resolve_step(workflow)
    assert step["env"]["SOURCE_REF"] == "${{ inputs.source_ref }}"
    assert step["env"]["RUN_ID"] == "${{ github.run_id }}"
    assert step["env"]["RUN_ATTEMPT"] == "${{ github.run_attempt }}"
    assert "${{" not in step["run"]
    assert prepare["outputs"]["source_sha"] == "${{ steps.resolve.outputs.source_sha }}"
    assert prepare["outputs"]["image_tag"] == "${{ steps.resolve.outputs.image_tag }}"

    jobs = workflow["jobs"]
    assert jobs["build"]["uses"] == "./.github/workflows/_build-docs-images.yml"
    assert jobs["build"]["needs"] == "prepare"
    for name in ("build", "helm-pr-stg", "helm-pr-prod"):
        inputs = jobs[name]["with"]
        assert inputs["source_ref"] == "${{ needs.prepare.outputs.source_sha }}"
        assert inputs["image_tag"] == "${{ needs.prepare.outputs.image_tag }}"


def test_production_requires_staging_and_approval_and_promotes_the_same_images(workflow):
    jobs = workflow["jobs"]
    staging = jobs["helm-pr-stg"]
    approval = jobs["await-prod-approval"]
    production = jobs["helm-pr-prod"]
    assert {"prepare", "build"} <= set(staging["needs"])
    assert approval["needs"] == "helm-pr-stg"
    assert approval["environment"] == "production"
    assert {"prepare", "await-prod-approval"} <= set(production["needs"])
    for job, environment in ((staging, "stg"), (production, "prod")):
        assert job["uses"] == "./.github/workflows/_helm-docs-pr.yml"
        assert job["with"]["environment"] == environment
        assert job["with"]["auto_merge"] is True
    for job in (staging, approval, production):
        assert "if" not in job, "promotion must require successful dependencies"
        assert not job.get("continue-on-error", False)


def test_site_workflow_does_not_invoke_package_publication_or_release_creation(workflow):
    allowed_workflows = {
        "./.github/workflows/_build-docs-images.yml",
        "./.github/workflows/_helm-docs-pr.yml",
    }
    for job in workflow["jobs"].values():
        if "uses" in job:
            assert job["uses"] in allowed_workflows
        for step in job.get("steps", []):
            executable = step.get("uses", "") + "\n" + step.get("run", "")
            for publication in (
                "pypi",
                "publish.yml",
                "gh release",
                "git tag",
                "uv publish",
                "twine",
            ):
                assert publication not in executable.lower()
