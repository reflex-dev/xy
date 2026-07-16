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
    "browser_conformance",
    "matplotlib_reference",
    "test",
    "python_floor",
    "benchmark_vs",
    "benchmark_methodology",
    "benchmark",
    "sdist",
    "wheels",
    "install_without_rust",
}
REQUIRED_CODSPEED_JOBS = {"benchmarks"}
REQUIRED_RELEASE_JOBS = {"wheels", "sdist", "publish", "wasm"}


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


def _named_step_blocks(job_text: str) -> dict[str, str]:
    """Return step-local blocks; comments elsewhere cannot satisfy a gate."""
    lines = job_text.splitlines()
    blocks: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in lines:
        match = re.match(r"^      - name:\s*(.+?)\s*$", line)
        if match:
            current = match.group(1)
            blocks[current] = [line]
            continue
        if re.match(r"^      - ", line):
            current = None
        elif current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def _require_step_contains(
    errors: list[str], job_text: str, step: str, description: str, *needles: str
) -> None:
    block = _named_step_blocks(job_text).get(step)
    if block is None:
        errors.append(f"missing required CI step {step!r}")
        return
    missing = _missing_needles(block, needles)
    if missing:
        errors.append(f"CI step {step!r} missing {description}: {missing}")


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


def _step_is_conditioned(job_text: str, step_needle: str) -> bool:
    """True if the step whose `uses:`/`run:` line contains `step_needle` has its
    own `if:` key — not just any `if:` elsewhere in the job (e.g. a sibling
    step's dry-run summary). Scoped to the step's own indented block so a
    same-level sibling step can't mask a missing gate.

    The prefix (the step's own `uses:`/`name:`/`run:` line) is matched with
    `[^\\n]*`, not a dot-all `.*` — under re.DOTALL a greedy `.*` would happily
    span past earlier sibling steps and swallow their `if:` lines too, which
    defeats the whole point of scoping this to one step.
    """
    match = re.search(
        rf"( *)- (?:uses|name|run): [^\n]*{re.escape(step_needle)}[^\n]*\n([\s\S]*?)(?=\n\1- |\Z)",
        job_text,
    )
    if match is None:
        return False
    return "if:" in match.group(0)


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
        "matplotlib_reference",
        "CI",
        "released Matplotlib compatibility gates",
        "matplotlib==3.11.0",
        "matplotlib.__version__ == '3.11.0'",
        "scripts/sync_matplotlib_compat.py --check",
        "tests/pyplot/test_launch_compat.py",
        "tests/pyplot/test_reference_corpus.py",
        "tests/pyplot/test_reference_semantics.py",
        "MPLBACKEND: Agg",
    )
    reference = jobs.get("matplotlib_reference", "")
    _require_step_contains(
        errors,
        reference,
        "Install xy and released reference wheel",
        "released reference installation",
        'uv pip install -p .venv/bin/python "matplotlib==3.11.0"',
    )
    _require_step_contains(
        errors,
        reference,
        "Verify released reference and reviewed snapshot",
        "version and snapshot checks",
        "matplotlib.__version__ == '3.11.0'",
        "scripts/sync_matplotlib_compat.py --check",
    )
    _require_step_contains(
        errors,
        reference,
        "Run optional-interoperability and dual-engine corpus tests",
        "reference test commands",
        ".venv/bin/pytest -q tests/pyplot/test_launch_compat.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_corpus.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_semantics.py",
    )

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
        "scripts/smoke_render.py",
        "Browser lifecycle smoke",
        "Browser visual regression smoke",
        "Browser interaction stress smoke",
        "Browser dashboard reliability smoke",
        "scripts/reflex_lifecycle_smoke.py",
        "scripts/visual_regression_smoke.py",
        "scripts/interaction_stress_smoke.py",
        "benchmarks/bench_dashboard.py",
        "--chart-counts 10,20,50",
        "dashboard-smoke.json --kind dashboard-browser",
        "--sizes 1e5,1e6,1e7 --production --json scatter.json",
        "scripts/bench_native.py --sizes 1e6,1e7 --json kernel.json",
        "scripts/verify_benchmark_report.py scatter.json --kind scatter-native",
        "scripts/verify_benchmark_report.py kernel.json --kind kernel-native",
        "benchmarks/bench_transport.py --n 1e6 --reps 15",
        '--browser-reps 12 --chromium "$CHROME" --require-browser --json transport.json',
        "scripts/verify_benchmark_report.py transport.json --kind transport-loopback",
        "scripts/check_regressions.py --scatter scatter.json --kernel kernel.json",
        "--transport transport.json --emit-md docs/engineering/benchmark_metrics.md",
        "Upload regression benchmark report",
        "if: always()",
        "actions/upload-artifact@",
        "regression-benchmark-report",
        "if-no-files-found: warn",
        "docs/engineering/benchmark_metrics.md",
        "transport.json",
    )
    _require_job_contains(
        errors,
        jobs,
        "browser_conformance",
        "CI",
        "accessibility and three-engine conformance gate",
        'node-version: "22"',
        "npm ci",
        "actions/cache@5a3ec84eff668545956fd18022155c47e93e2684",
        "~/.cache/ms-playwright",
        "playwright-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('package-lock.json') }}",
        "npx playwright install --with-deps chromium firefox webkit",
        "node js/build.mjs --check",
        "node scripts/browser_conformance.mjs",
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
        "benchmark_vs",
        "CI",
        "parallel cross-library benchmark matrix",
        "continue-on-error: true",
        "fail-fast: false",
        "matrix:",
        "--libraries",
        "--max-n",
        "Run cross-library benchmark group",
        "Upload cross-library benchmark part",
        "benchmark-vs-${{ matrix.name }}",
        "if: always()",
        "actions/upload-artifact@",
        "if-no-files-found: warn",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark_methodology",
        "CI",
        "non-blocking methodology benchmark artifact path",
        "continue-on-error: true",
        "Verify native benchmark backend",
        "XY_REQUIRE_CARGO",
        'k.BACKEND == "native"',
        "benchmark job requires native backend",
        "scripts/verify_benchmark_report.py",
        "Upload benchmark methodology",
        "if: always()",
        "actions/upload-artifact@",
        "line.json",
        "install.json",
        "interaction.json",
        "dashboard.json",
        "workflows.json",
        "install-fresh.json",
        "verify_benchmark_report.py line.json --kind line-decimation",
        "verify_benchmark_report.py install.json --kind install-footprint",
        "verify_benchmark_report.py interaction.json --kind interaction-browser",
        "verify_benchmark_report.py dashboard.json --kind dashboard-browser",
        "verify_benchmark_report.py workflows.json --kind workflow-native",
        "bench_interaction.py",
        "bench_dashboard.py",
        "docs/benchmark_ci.md",
        "if-no-files-found: warn",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark",
        "CI",
        "merged benchmark artifact path",
        "continue-on-error: true",
        "needs: [benchmark_vs, benchmark_methodology]",
        "if: always()",
        "actions/download-artifact@",
        "pattern: benchmark-vs-*",
        "name: benchmark-methodology",
        "scripts/merge_benchmark_reports.py",
        "benchmark.json",
        "verify_benchmark_report.py benchmark.json --kind scatter-vs",
        "Upload benchmark report",
        "actions/upload-artifact@",
        "line.json",
        "install.json",
        "interaction.json",
        "dashboard.json",
        "workflows.json",
        "install-fresh.json",
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
        "XY_SKIP_CARGO",
    )
    _require_job_contains(
        errors,
        jobs,
        "wheels",
        "CI",
        "native wheel verification and upload",
        "XY_REQUIRE_CARGO",
        "scripts/verify_wheel.py",
        "--expect-native",
        "actions/upload-artifact@",
        "dist/*.whl",
    )
    _require_job_contains(
        errors,
        jobs,
        "install_without_rust",
        "CI",
        "no-Rust wheel builds but errors clearly on compute",
        "Remove preinstalled Rust",
        "scripts/verify_wheel.py",
        "--expect-pure",
        "native Rust core",
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
        "dtolnay/rust-toolchain@",
        "actions/setup-python@",
        'python-version: "3.11"',
        "astral-sh/setup-uv@",
        "cargo build --release",
        "XY_REQUIRE_CARGO",
        ".[dev,codspeed]",
        "Verify native benchmark backend",
        'k.BACKEND == "native"',
        "CodSpeed requires native backend",
        "CodSpeedHQ/action@",
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
        "cross-platform wheel matrix (glibc+musl, macOS, Windows), verification, and upload",
        "dtolnay/rust-toolchain@",
        "astral-sh/setup-uv@",
        "actions/setup-node@",
        'node-version: "22"',
        "node js/build.mjs --check",
        "cargo-zigbuild",
        "uv build --wheel",
        "XY_REQUIRE_CARGO",
        "XY_WHEEL_PLATFORM",
        "musllinux_1_2_x86_64",
        "win_arm64",
        "scripts/verify_wheel.py",
        "--expect-native",
        "Install-size budget (<= 15 MB)",
        "assert k.BACKEND=='native'",
        "actions/upload-artifact@",
        "dist/*.whl",
    )
    _require_job_contains(
        errors,
        jobs,
        "wasm",
        "release",
        "runtime-verified Pyodide/Emscripten WASM wheel",
        "toolchain: 1.97.0",
        "wasm32-unknown-emscripten",
        "setup-emsdk",
        'version: "4.0.9"',
        'RUSTFLAGS: "-C panic=abort"',
        "pyodide_2025_0_wasm32",
        "pyodide@0.29.4",
        "scripts/pyodide_load_smoke.py",
        "scripts/verify_wheel.py",
        "--expect-native",
    )
    wasm_job = jobs.get("wasm", "")
    if "continue-on-error:" in wasm_job:
        errors.append("release wasm job must block publishing when the Pyodide runtime probe fails")
    _require_job_contains(
        errors,
        jobs,
        "sdist",
        "release",
        "sdist build, content verification, no-Rust clear-error smoke, and upload",
        "astral-sh/setup-uv@",
        "actions/setup-node@",
        'node-version: "22"',
        "node js/build.mjs --check",
        "uv build --sdist",
        "scripts/verify_sdist.py",
        "XY_SKIP_CARGO",
        "native Rust core",
        "actions/upload-artifact@",
        "dist/*.tar.gz",
    )
    _require_job_contains(
        errors,
        jobs,
        "publish",
        "release",
        "trusted PyPI publishing from downloaded artifacts, gated by a dry-run switch "
        "and a tag/version/CHANGELOG agreement gate",
        "needs: [wheels, sdist, wasm]",
        "environment: pypi",
        "id-token: write",
        "scripts/check_release_version.py",
        "actions/download-artifact@",
        "pattern: dist-*",
        "merge-multiple: true",
        "dry_run",
        "pypa/gh-action-pypi-publish@",
        "packages-dir: dist/",
    )
    _require_workflow_contains(
        errors,
        text,
        "release",
        "a workflow_dispatch dry-run input defaulting to true, so a manual run "
        "never accidentally publishes",
        "workflow_dispatch:",
        "dry_run:",
        "type: boolean",
        "default: true",
    )

    publish = jobs.get("publish", "")
    if "password:" in publish or "api-token" in publish:
        errors.append("release publish job should use trusted publishing, not a PyPI token")
    if "pypa/gh-action-pypi-publish@" in publish and not _step_is_conditioned(
        publish, "pypa/gh-action-pypi-publish@"
    ):
        errors.append(
            "release publish job's PyPI upload step has no if: condition of its "
            "own — it must be gated (dry_run) so a manual dispatch cannot "
            "publish unintentionally, even if a sibling step also has an if:"
        )
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
