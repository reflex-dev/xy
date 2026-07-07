#!/usr/bin/env python3
"""Verify workflow invariants that protect production-facing gates.

The workflows are YAML, but this checker intentionally stays stdlib-only so it
can run before the dev environment is installed. It does not try to be a full
YAML parser; it checks stable, high-value invariants that are easy to lose when
editing `.github/workflows/ci.yml` or `.github/workflows/release.yml`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEFAULT_CODSPEED_WORKFLOW = ROOT / ".github" / "workflows" / "codspeed.yml"
DEFAULT_RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
DEFAULT_WORKFLOW = DEFAULT_CI_WORKFLOW
REQUIRED_CI_JOBS = {
    "test",
    "python_floor",
    "benchmark",
    "sdist",
    "wheels",
    "install_without_rust",
}
REQUIRED_CODSPEED_JOBS = {"benchmarks"}
REQUIRED_RELEASE_JOBS = {"wheels", "sdist", "publish"}


def _job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "jobs:")
    except StopIteration:
        return {}

    blocks: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in lines[start + 1 :]:
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = [line]
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(block) for name, block in blocks.items()}


def _missing_needles(block: str, needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if needle not in block]


def _require_job_contains(
    errors: list[str],
    jobs: dict[str, str],
    job: str,
    workflow_label: str,
    description: str,
    *needles: str,
) -> None:
    block = jobs.get(job)
    if block is None:
        errors.append(f"missing required {workflow_label} job {job!r}")
        return
    missing = _missing_needles(block, needles)
    if missing:
        errors.append(f"{workflow_label} {job} job missing {description}: {missing}")


def _require_workflow_contains(
    errors: list[str],
    text: str,
    workflow_label: str,
    description: str,
    *needles: str,
) -> None:
    missing = _missing_needles(text, needles)
    if missing:
        errors.append(f"{workflow_label} workflow missing {description}: {missing}")


def validate_ci_workflow(path: Path = DEFAULT_CI_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CI workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    missing_jobs = sorted(REQUIRED_CI_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"CI workflow missing required jobs: {missing_jobs}")

    _require_job_contains(
        errors,
        jobs,
        "test",
        "CI",
        "hard production gates",
        "scripts/verify_ci_workflow.py",
        "scripts/check_public_api.py",
        "scripts/check_claim_guardrails.py",
        "ruff check .",
        "FASTCHARTS_FORCE_FALLBACK=1",
        "scripts/smoke_render.py",
        "Browser core lifecycle, visual, and interaction smoke",
        "scripts/reflex_lifecycle_smoke.py",
        "scripts/visual_regression_smoke.py",
        "scripts/interaction_stress_smoke.py",
        "scripts/bench_scatter_native.py --sizes 1e5,1e6,1e7 --json scatter.json",
        "scripts/bench_native.py --sizes 1e6,1e7 --json kernel.json",
        "scripts/verify_benchmark_report.py scatter.json --kind scatter-native",
        "scripts/verify_benchmark_report.py kernel.json --kind kernel-native",
        "scripts/check_regressions.py --scatter scatter.json --kernel kernel.json",
        "--emit-md docs/benchmark_metrics.md",
        "Upload regression benchmark report",
        "if: always()",
        "actions/upload-artifact@v4",
        "regression-benchmark-report",
        "if-no-files-found: warn",
        "docs/benchmark_metrics.md",
    )
    _require_job_contains(
        errors,
        jobs,
        "python_floor",
        "CI",
        "Python 3.11 floor gate",
        'python-version: "3.11"',
        "scripts/check_python_floor.py",
        "scripts/check_public_api.py",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark",
        "CI",
        "non-blocking benchmark artifact path",
        "continue-on-error: true",
        "Verify native benchmark backend",
        "FASTCHARTS_REQUIRE_CARGO",
        'k.BACKEND == "native"',
        "benchmark job requires native backend",
        "scripts/verify_benchmark_report.py",
        "Upload benchmark report",
        "if: always()",
        "actions/upload-artifact@v4",
        "benchmark.json",
        "line.json",
        "install.json",
        "interaction.json",
        "dashboard.json",
        "verify_benchmark_report.py benchmark.json --kind scatter-vs",
        "verify_benchmark_report.py line.json --kind line-decimation",
        "verify_benchmark_report.py install.json --kind install-footprint",
        "verify_benchmark_report.py interaction.json --kind interaction-browser",
        "verify_benchmark_report.py dashboard.json --kind dashboard-browser",
        "bench_interaction.py",
        "bench_dashboard.py",
        "docs/benchmark_ci.md",
        "if-no-files-found: warn",
    )
    _require_job_contains(
        errors,
        jobs,
        "sdist",
        "CI",
        "source artifact verification",
        "uv build --sdist",
        "scripts/verify_sdist.py",
        "FASTCHARTS_SKIP_CARGO",
    )
    _require_job_contains(
        errors,
        jobs,
        "wheels",
        "CI",
        "native wheel verification and upload",
        "FASTCHARTS_REQUIRE_CARGO",
        "scripts/verify_wheel.py",
        "--expect-native",
        "actions/upload-artifact@v4",
        "dist/*.whl",
    )
    _require_job_contains(
        errors,
        jobs,
        "install_without_rust",
        "CI",
        "pure fallback wheel verification",
        "Remove preinstalled Rust",
        "scripts/verify_wheel.py",
        "--expect-pure",
        'BACKEND == "numpy"',
    )
    return errors


def validate_workflow(path: Path = DEFAULT_WORKFLOW) -> list[str]:
    """Backward-compatible CI workflow verifier."""
    return validate_ci_workflow(path)


def validate_codspeed_workflow(path: Path = DEFAULT_CODSPEED_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CodSpeed workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    missing_jobs = sorted(REQUIRED_CODSPEED_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"CodSpeed workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "CodSpeed",
        "push, PR, manual triggers, and OIDC permissions",
        'branches: ["main"]',
        "pull_request:",
        "workflow_dispatch:",
        "id-token: write",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmarks",
        "CodSpeed",
        "native-only benchmark path",
        "dtolnay/rust-toolchain@stable",
        "actions/setup-python@v5",
        'python-version: "3.11"',
        "astral-sh/setup-uv@v5",
        "cargo build --release",
        "FASTCHARTS_REQUIRE_CARGO",
        "pytest-codspeed",
        "Verify native benchmark backend",
        'k.BACKEND == "native"',
        "CodSpeed requires native backend",
        "CodSpeedHQ/action@v4",
        "mode: simulation",
        "benchmarks/test_codspeed_kernels.py --codspeed",
    )
    return errors


def validate_release_workflow(path: Path = DEFAULT_RELEASE_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read release workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    missing_jobs = sorted(REQUIRED_RELEASE_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"release workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "release",
        "tag and manual triggers",
        'tags: ["v*"]',
        "workflow_dispatch:",
    )
    _require_job_contains(
        errors,
        jobs,
        "wheels",
        "release",
        "native wheel build, verification, size budget, install smoke, and upload",
        "dtolnay/rust-toolchain@stable",
        "astral-sh/setup-uv@v5",
        "actions/setup-node@v4",
        'node-version: "22"',
        "node js/build.mjs --check",
        "uv build --wheel",
        "FASTCHARTS_REQUIRE_CARGO",
        "auditwheel repair",
        "scripts/verify_wheel.py",
        "--expect-native",
        "Install-size budget (<= 15 MB)",
        "assert k.BACKEND=='native'",
        "actions/upload-artifact@v4",
        "dist/*.whl",
    )
    _require_job_contains(
        errors,
        jobs,
        "sdist",
        "release",
        "sdist build, content verification, fallback install smoke, and upload",
        "astral-sh/setup-uv@v5",
        "actions/setup-node@v4",
        'node-version: "22"',
        "node js/build.mjs --check",
        "uv build --sdist",
        "scripts/verify_sdist.py",
        "FASTCHARTS_SKIP_CARGO",
        'BACKEND == "numpy"',
        "actions/upload-artifact@v4",
        "dist/*.tar.gz",
    )
    _require_job_contains(
        errors,
        jobs,
        "publish",
        "release",
        "trusted PyPI publishing from downloaded artifacts",
        "needs: [wheels, sdist]",
        "environment: pypi",
        "id-token: write",
        "actions/download-artifact@v4",
        "pattern: dist-*",
        "merge-multiple: true",
        "pypa/gh-action-pypi-publish@release/v1",
        "packages-dir: dist/",
    )

    publish = jobs.get("publish", "")
    if "password:" in publish or "api-token" in publish:
        errors.append("release publish job should use trusted publishing, not a PyPI token")
    return errors


def validate_all_workflows(
    ci_path: Path = DEFAULT_CI_WORKFLOW,
    codspeed_path: Path = DEFAULT_CODSPEED_WORKFLOW,
    release_path: Path = DEFAULT_RELEASE_WORKFLOW,
) -> list[str]:
    return [
        *validate_ci_workflow(ci_path),
        *validate_codspeed_workflow(codspeed_path),
        *validate_release_workflow(release_path),
    ]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workflow",
        nargs="?",
        type=Path,
        help="legacy CI workflow path override; checks CI only when provided",
    )
    parser.add_argument("--ci-workflow", type=Path, default=DEFAULT_CI_WORKFLOW)
    parser.add_argument("--codspeed-workflow", type=Path, default=DEFAULT_CODSPEED_WORKFLOW)
    parser.add_argument("--release-workflow", type=Path, default=DEFAULT_RELEASE_WORKFLOW)
    parser.add_argument("--ci-only", action="store_true")
    parser.add_argument("--codspeed-only", action="store_true")
    parser.add_argument("--release-only", action="store_true")
    args = parser.parse_args(argv)

    selected_modes = [args.ci_only, args.codspeed_only, args.release_only]
    if sum(1 for selected in selected_modes if selected) > 1:
        parser.error("--ci-only, --codspeed-only, and --release-only are mutually exclusive")

    if args.workflow is not None:
        errors = validate_ci_workflow(args.workflow)
        checked = [args.workflow]
    elif args.ci_only:
        errors = validate_ci_workflow(args.ci_workflow)
        checked = [args.ci_workflow]
    elif args.codspeed_only:
        errors = validate_codspeed_workflow(args.codspeed_workflow)
        checked = [args.codspeed_workflow]
    elif args.release_only:
        errors = validate_release_workflow(args.release_workflow)
        checked = [args.release_workflow]
    else:
        errors = validate_all_workflows(
            args.ci_workflow, args.codspeed_workflow, args.release_workflow
        )
        checked = [args.ci_workflow, args.codspeed_workflow, args.release_workflow]

    if errors:
        print(
            "Workflow verification failed for " + ", ".join(str(path) for path in checked) + ":",
            file=sys.stderr,
        )
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Workflow verification OK: " + ", ".join(str(path) for path in checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
