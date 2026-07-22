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
DEFAULT_DEPLOY_DEV_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-docs-dev.yml"
DEFAULT_DEPLOY_STG_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-docs-stg.yml"
DEFAULT_BUILD_DOCS_WORKFLOW = ROOT / ".github" / "workflows" / "_build-docs-images.yml"
DEFAULT_HELM_DOCS_WORKFLOW = ROOT / ".github" / "workflows" / "_helm-docs-pr.yml"
DEFAULT_WORKFLOW = DEFAULT_CI_WORKFLOW
REQUIRED_CI_JOBS = {
    "browser_conformance",
    "dependency_audit",
    "javascript_semantics",
    "reflex_adapter",
    "matplotlib_reference",
    "native_parity",
    "python_coverage",
    "test",
    "python_floor",
    "rust_release",
    "benchmark_vs",
    "benchmark_methodology",
    "benchmark",
    "sdist",
    "wheels",
    "install_without_rust",
    "required_ci",
}
REQUIRED_CODSPEED_JOBS = {"benchmarks"}
REQUIRED_RELEASE_JOBS = {
    "qualify",
    "wheels",
    "sdist",
    "provenance",
    "publish",
    "publish-pyodide",
    "wasm",
}


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


def _matrix_include_entries(job_text: str) -> list[dict[str, str]]:
    """Parse the flat mappings under one job's strategy.matrix.include list."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_include = False
    for line in job_text.splitlines():
        if line == "        include:":
            in_include = True
            continue
        if not in_include:
            continue
        if line.startswith("          - "):
            if current is not None:
                entries.append(current)
            current = {}
            item = line.removeprefix("          - ")
        elif line.startswith("            ") and not line.lstrip().startswith("#"):
            item = line.removeprefix("            ")
        elif line.strip() and len(line) - len(line.lstrip()) <= 8:
            break
        else:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+):\s*(.*?)", item)
        if match and current is not None:
            current[match.group(1)] = match.group(2)
    if current is not None:
        entries.append(current)
    return entries


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


def _require_pr_all_paths(errors: list[str], text: str, workflow_label: str) -> None:
    """Require a PR trigger that cannot omit the workflow's stable result."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "  pull_request:")
    except StopIteration:
        errors.append(f"{workflow_label} workflow missing pull_request trigger")
        return

    for line in lines[start + 1 :]:
        indent = len(line) - len(line.lstrip())
        if line.strip() and indent <= 2:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if indent == 4 and re.match(r"paths(?:-ignore)?:", stripped):
            errors.append(
                f"{workflow_label} pull_request trigger must run on every path; found {stripped!r}"
            )


def _listed_needs(job_text: str) -> set[str]:
    """Return names from a block-form top-level ``needs`` list."""
    needs: set[str] = set()
    collecting = False
    for line in job_text.splitlines():
        if line == "    needs:":
            collecting = True
            continue
        if collecting:
            match = re.fullmatch(r"      - ([A-Za-z0-9_-]+)", line)
            if match:
                needs.add(match.group(1))
                continue
            if line.strip():
                break
    return needs


def _python_heredoc_syntax_errors(text: str) -> list[str]:
    """Compile Python heredocs after applying YAML block-scalar indentation."""
    lines = text.splitlines()
    errors: list[str] = []
    for index, line in enumerate(lines):
        if not re.search(r"<<-?['\"]?PY['\"]?\s*$", line):
            continue
        indent = len(line) - len(line.lstrip())
        prefix = " " * indent
        body: list[str] = []
        for end in range(index + 1, len(lines)):
            if lines[end] == f"{prefix}PY":
                source = "\n".join(
                    candidate[indent:] if candidate.startswith(prefix) else candidate
                    for candidate in body
                )
                try:
                    compile(source, f"workflow-heredoc:{index + 1}", "exec")
                except (IndentationError, SyntaxError) as exc:
                    errors.append(f"invalid Python heredoc at line {index + 1}: {exc.msg}")
                for offset, candidate in enumerate(source.splitlines(), 1):
                    leading = len(candidate) - len(candidate.lstrip())
                    if candidate.strip() and leading % 4:
                        errors.append(
                            "invalid Python heredoc indentation at line "
                            f"{index + offset + 1}: expected a multiple of four spaces"
                        )
                break
            body.append(lines[end])
        else:
            errors.append(f"unterminated Python heredoc at line {index + 1}")
    return errors


def validate_ci_workflow(path: Path = DEFAULT_CI_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CI workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors = _python_heredoc_syntax_errors(text)
    _require_pr_all_paths(errors, text, "CI")
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
        "scripts/check_pyplot_options.py",
        "--report pyplot-option-contract.json",
        "Upload pyplot option contract evidence",
        "pyplot-option-contract",
        "scripts/check_claim_guardrails.py",
        "ruff check .",
        "scripts/smoke_render.py",
        "Browser lifecycle smoke",
        "Browser visual health smoke",
        "Reviewed visual baseline",
        "Runtime standalone security smoke",
        "Animation smoke",
        "Pick boundary smoke",
        "Browser interaction stress smoke",
        "Browser dashboard reliability smoke",
        "scripts/reflex_lifecycle_smoke.py",
        "scripts/visual_health_smoke.py",
        "scripts/visual_baseline.py",
        "spec/visual-baselines/v1.json",
        "--artifacts visual-baseline-artifacts",
        "--evidence visual-baseline-evidence.json",
        "Upload visual baseline evidence",
        "visual-baseline-evidence",
        "Rendered label and formatter oracle (Chromium)",
        "npm run test:labels",
        "XY_LABEL_EVIDENCE: rendered-label-evidence.json",
        "Upload rendered label evidence",
        "rendered-label-evidence",
        "Every chart-kind render matrix",
        "scripts/chart_kind_matrix.py",
        "--evidence chart-kind-matrix-evidence.json",
        "Upload chart-kind matrix evidence",
        "chart-kind-matrix-evidence",
        "scripts/runtime_security_smoke.py",
        "--evidence runtime-security-evidence.json",
        "Upload runtime security evidence",
        "runtime-security-evidence",
        "scripts/animation_smoke.py",
        "--evidence animation-browser-evidence.json",
        "Upload animation browser evidence",
        "animation-browser-evidence",
        "scripts/pick_boundary_smoke.py",
        "--evidence pick-boundary-evidence.json",
        "Upload pick boundary evidence",
        "pick-boundary-evidence",
        "if-no-files-found: error",
        "scripts/interaction_stress_smoke.py",
        "--json interaction-worker-evidence.json",
        "Upload interaction worker evidence",
        "interaction-worker-evidence",
        "Pan/zoom acceptance matrix (Chromium)",
        "scripts/pan_zoom_matrix.mjs",
        "--profile full",
        "--browsers chromium",
        "--evidence pan-zoom-matrix-evidence.json",
        "Upload pan/zoom matrix evidence",
        "pan-zoom-matrix-evidence",
        "benchmarks/bench_dashboard.py",
        "--chart-counts 10,20,50",
        "dashboard-smoke.json --kind dashboard-browser",
        "--profile strict",
        "Upload dashboard health evidence",
        "dashboard-health-evidence",
        "if-no-files-found: error",
        "--sizes 1e5,1e6,1e7 --production --json scatter.json",
        "scripts/bench_native.py --sizes 1e6,1e7 --json kernel.json",
        "scripts/verify_benchmark_report.py scatter.json --kind scatter-native",
        "scripts/verify_benchmark_report.py kernel.json --kind kernel-native",
        "benchmarks/bench_transport.py --n 1e6 --reps 15",
        '--browser-reps 12 --chromium "$CHROME" --require-browser --json transport.json',
        "scripts/verify_benchmark_report.py transport.json --kind transport-loopback",
        "scripts/check_regressions.py --scatter scatter.json --kernel kernel.json",
        "--transport transport.json --emit-md spec/benchmarks/metrics.md",
        "Upload regression benchmark report",
        "if: always()",
        "actions/upload-artifact@",
        "regression-benchmark-report",
        "if-no-files-found: warn",
        "spec/benchmarks/metrics.md",
        "transport.json",
    )
    hard_test = jobs.get("test", "")
    _require_step_contains(
        errors,
        hard_test,
        "Rendered label and formatter oracle (Chromium)",
        "hard rendered-label DOM and formatter oracle",
        "npm run test:labels",
        "XY_LABEL_EVIDENCE: rendered-label-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload rendered label evidence",
        "failure-retaining rendered-label artifact policy",
        "if: always()",
        "actions/upload-artifact@",
        "rendered-label-evidence",
        "if-no-files-found: error",
        "rendered-label-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Pyplot option contract",
        "fail-closed structured no-op audit",
        "scripts/check_pyplot_options.py",
        "--report pyplot-option-contract.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload pyplot option contract evidence",
        "failure-retaining option-contract evidence",
        "if: always()",
        "actions/upload-artifact@",
        "pyplot-option-contract",
        "if-no-files-found: error",
        "pyplot-option-contract.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Browser visual health smoke (Chromium)",
        "honestly named broad visual-health command",
        "scripts/visual_health_smoke.py",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Reviewed visual baseline (Chromium)",
        "pinned baseline command and artifact paths",
        "scripts/visual_baseline.py",
        "spec/visual-baselines/v1.json",
        "--artifacts visual-baseline-artifacts",
        "--evidence visual-baseline-evidence.json",
        "if: ${{ !cancelled() }}",
    )
    baseline_step = _named_step_blocks(hard_test).get("Reviewed visual baseline (Chromium)", "")
    if "--update-baselines" in baseline_step:
        errors.append("hard visual baseline CI step must never update reviewed baselines")
    _require_step_contains(
        errors,
        hard_test,
        "Upload visual baseline evidence",
        "failure-retaining expected/actual/diff artifact policy",
        "if: always()",
        "actions/upload-artifact@",
        "visual-baseline-evidence",
        "if-no-files-found: error",
        "visual-baseline-evidence.json",
        "visual-baseline-artifacts/",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Every chart-kind render matrix (Chromium)",
        "registry-complete browser render command",
        "scripts/chart_kind_matrix.py",
        "--no-sandbox",
        "--evidence chart-kind-matrix-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload chart-kind matrix evidence",
        "failure-retaining chart-kind evidence artifact",
        "if: always()",
        "actions/upload-artifact@",
        "chart-kind-matrix-evidence",
        "if-no-files-found: error",
        "chart-kind-matrix-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Runtime standalone security smoke (Chromium)",
        "hard runtime DOM/CSP command and diagnostic path",
        "scripts/runtime_security_smoke.py",
        "--no-sandbox",
        "--evidence runtime-security-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload runtime security evidence",
        "failure-retaining runtime security artifact policy",
        "if: always()",
        "actions/upload-artifact@",
        "runtime-security-evidence",
        "if-no-files-found: error",
        "runtime-security-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Animation smoke (Chromium)",
        "hard animation command and diagnostic path",
        "scripts/animation_smoke.py",
        "--evidence animation-browser-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload animation browser evidence",
        "failure-retaining animation artifact policy",
        "if: always()",
        "actions/upload-artifact@",
        "animation-browser-evidence",
        "if-no-files-found: error",
        "animation-browser-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Pick boundary smoke (Chromium)",
        "hard pick-boundary command and diagnostic path",
        "scripts/pick_boundary_smoke.py",
        "--evidence pick-boundary-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload pick boundary evidence",
        "failure-retaining pick-boundary artifact policy",
        "if: always()",
        "actions/upload-artifact@",
        "pick-boundary-evidence",
        "if-no-files-found: error",
        "pick-boundary-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Browser interaction stress smoke (Chromium)",
        "required worker command and diagnostic path",
        "scripts/interaction_stress_smoke.py",
        "--json interaction-worker-evidence.json",
    )
    interaction_step = _named_step_blocks(hard_test).get(
        "Browser interaction stress smoke (Chromium)", ""
    )
    if "--allow-worker-skip" in interaction_step:
        errors.append("hard interaction worker CI step must not allow worker skips")
    _require_step_contains(
        errors,
        hard_test,
        "Upload interaction worker evidence",
        "failure-retaining worker artifact policy",
        "if: always()",
        "actions/upload-artifact@",
        "interaction-worker-evidence",
        "if-no-files-found: error",
        "interaction-worker-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Pan/zoom acceptance matrix (Chromium)",
        "complete hard Chromium pan/zoom matrix and diagnostic path",
        "scripts/pan_zoom_matrix.mjs",
        "--profile full",
        "--browsers chromium",
        '--executable-path "$CHROME"',
        "--evidence pan-zoom-matrix-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload pan/zoom matrix evidence",
        "failure-retaining pan/zoom matrix artifact policy",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "pan-zoom-matrix-evidence",
        "if-no-files-found: error",
        "pan-zoom-matrix-evidence.json",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload regression benchmark report",
        "failure-retaining regression artifact policy",
        "if: always()",
        "regression-benchmark-report",
        "if-no-files-found: warn",
    )
    _require_step_contains(
        errors,
        hard_test,
        "Upload dashboard health evidence",
        "failure-retaining dashboard artifact policy",
        "if: always()",
        "dashboard-health-evidence",
        "if-no-files-found: error",
        "dashboard-smoke.json",
    )
    javascript_semantics = jobs.get("javascript_semantics", "")
    if "continue-on-error:" in javascript_semantics:
        errors.append("CI javascript_semantics job must be a hard gate without continue-on-error")
    if "npm ci" in javascript_semantics or "npm install" in javascript_semantics:
        errors.append(
            "CI javascript_semantics job must use only pinned Node built-ins without npm installs"
        )
    _require_job_contains(
        errors,
        jobs,
        "javascript_semantics",
        "CI",
        "pinned dependency-free semantic units with retained test and coverage evidence",
        "name: JavaScript semantic unit suite",
        "timeout-minutes: 10",
        "actions/setup-node@",
        'node-version: "22"',
        "node --test --experimental-test-coverage",
        "--test-coverage-include=python/xy/static/index.js",
        "--test-coverage-lines=15",
        "--test-coverage-branches=60",
        "--test-coverage-functions=10",
        "--test-reporter=junit",
        "test-results/javascript/junit.xml",
        "NODE_V8_COVERAGE=coverage/javascript",
        "js/test/*.test.mjs",
        "Upload JavaScript semantic evidence",
        "javascript-semantic-evidence",
    )
    _require_step_contains(
        errors,
        javascript_semantics,
        "Run JavaScript semantic unit suite",
        "hard semantic command, coverage thresholds, and JUnit evidence",
        "set -o pipefail",
        "NODE_V8_COVERAGE=coverage/javascript",
        "node --test --experimental-test-coverage",
        "--test-coverage-lines=15",
        "--test-coverage-branches=60",
        "--test-coverage-functions=10",
        "--test-reporter=junit",
        "test-results/javascript/junit.xml",
        "tee test-results/javascript/coverage.txt",
    )
    _require_step_contains(
        errors,
        javascript_semantics,
        "Upload JavaScript semantic evidence",
        "failure-retaining JavaScript test and coverage artifact policy",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "javascript-semantic-evidence",
        "if-no-files-found: error",
        "test-results/javascript/",
        "coverage/javascript/",
    )
    python_coverage = jobs.get("python_coverage", "")
    if "continue-on-error:" in python_coverage:
        errors.append("CI python_coverage job must be a hard gate without continue-on-error")
    _require_job_contains(
        errors,
        jobs,
        "python_coverage",
        "CI",
        "branch-aware package/module and changed-line ratchet with retained evidence",
        "name: Python branch and diff coverage",
        "timeout-minutes: 15",
        "fetch-depth: 0",
        'python-version: "3.13"',
        "uv sync --frozen --project python/reflex-xy --extra dev",
        "UV_PROJECT_ENVIRONMENT=python/reflex-xy/.venv",
        "uv sync --frozen --extra dev --inexact",
        "coverage run --branch --source=python/xy",
        "coverage run --branch --append",
        "--source=python/reflex-xy/reflex_xy",
        "scripts/run_pytest_no_skips.py -q",
        "python/reflex-xy/tests",
        "scripts/coverage_ratchet.py",
        "spec/testing/coverage-policy.json",
        "coverage/python/coverage.json",
        "coverage/python/coverage.xml",
        "coverage/python/ratchet.json",
        "github.event.pull_request.base.sha",
        "github.event.pull_request.head.sha",
        "Upload Python coverage evidence",
        "python-coverage-evidence",
        "retention-days: 30",
    )
    _require_step_contains(
        errors,
        python_coverage,
        "Enforce reviewed package, module, and changed-line floors",
        "branch-aware reports and exact Git comparison",
        "coverage json -o coverage/python/coverage.json",
        "coverage xml -o coverage/python/coverage.xml",
        "scripts/coverage_ratchet.py",
        '--base "$BASE_SHA" --head "$HEAD_SHA"',
        "--report coverage/python/ratchet.json",
    )
    _require_step_contains(
        errors,
        python_coverage,
        "Upload Python coverage evidence",
        "failure-retaining raw, JSON, XML, and ratchet evidence",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "python-coverage-evidence",
        "if-no-files-found: error",
        "retention-days: 30",
        ".coverage",
        "coverage/python/",
    )
    reflex_adapter = jobs.get("reflex_adapter", "")
    # This lane is intentionally hard.  Check the forbidden form explicitly
    # rather than relying on absence of a positive token.
    if "continue-on-error:" in reflex_adapter:
        errors.append("CI reflex_adapter job must be a hard gate without continue-on-error")
    if '-e ".[dev]"' in reflex_adapter:
        errors.append(
            "CI reflex_adapter job must provision tests from python/reflex-xy[dev], "
            "not the root xy dev extra"
        )
    _require_job_contains(
        errors,
        jobs,
        "reflex_adapter",
        "CI",
        "Reflex host matrix, zero-skip suite, compile, and real browser E2E",
        "reflex==0.9.6",
        "reflex>=0.9.6",
        'XY_REQUIRE_CARGO: "1"',
        "uv pip install -p .venv/bin/python -e .",
        "python/reflex-xy[dev]",
        "from importlib.metadata import version",
        "version('reflex')",
        "scripts/run_pytest_no_skips.py -q python/reflex-xy/tests",
        "reflex compile --dry",
        "reflex run --env prod --single-port",
        "scripts/reflex_ws_smoke.py",
        "--screenshot reflex-e2e.png",
        "scripts/pan_zoom_matrix.mjs --profile reflex --browsers chromium",
        "--evidence pan-zoom-reflex-evidence.json",
        "npx playwright install --with-deps chromium",
        "Upload Reflex E2E evidence",
        "reflex-e2e-${{ matrix.name }}",
        "examples/reflex/reflex-e2e.log",
        "examples/reflex/reflex-e2e.png",
        "Upload Reflex pan/zoom evidence",
        "reflex-pan-zoom-${{ matrix.name }}",
        "examples/reflex/pan-zoom-reflex-evidence.json",
    )
    _require_step_contains(
        errors,
        reflex_adapter,
        "Run real Reflex browser E2E",
        "browser evidence capture",
        "scripts/reflex_ws_smoke.py",
        "--screenshot reflex-e2e.png",
        "scripts/pan_zoom_matrix.mjs",
        "--profile reflex",
        "--browsers chromium",
        "--url http://localhost:3100",
        "--evidence pan-zoom-reflex-evidence.json",
    )
    _require_step_contains(
        errors,
        reflex_adapter,
        "Upload Reflex E2E evidence",
        "failure-safe browser evidence upload",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "reflex-e2e-${{ matrix.name }}",
        "if-no-files-found: warn",
        "examples/reflex/reflex-e2e.log",
        "examples/reflex/reflex-e2e.png",
    )
    _require_step_contains(
        errors,
        reflex_adapter,
        "Upload Reflex pan/zoom evidence",
        "failure-retaining live/static Reflex pan/zoom evidence",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "reflex-pan-zoom-${{ matrix.name }}",
        "if-no-files-found: error",
        "examples/reflex/pan-zoom-reflex-evidence.json",
    )
    _require_job_contains(
        errors,
        jobs,
        "browser_conformance",
        "CI",
        "accessibility and three-engine conformance gate",
        'node-version: "22"',
        "npm ci",
        "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
        "~/.cache/ms-playwright",
        "playwright-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('package-lock.json') }}",
        "npx playwright install --with-deps chromium firefox webkit",
        "node js/build.mjs --check",
        "node scripts/browser_conformance.mjs",
        "--evidence browser-conformance-evidence.json",
        "Upload browser conformance evidence",
        "browser-conformance-evidence",
        "if-no-files-found: error",
        "Focused pan/zoom matrix (three engines)",
        "scripts/pan_zoom_matrix.mjs",
        "--profile focused",
        "--browsers chromium,firefox,webkit",
        "--evidence pan-zoom-cross-engine-evidence.json",
        "Upload cross-engine pan/zoom evidence",
        "pan-zoom-cross-engine-evidence",
    )
    browser_conformance = jobs.get("browser_conformance", "")
    _require_step_contains(
        errors,
        browser_conformance,
        "Run accessibility and cross-browser conformance",
        "bounded three-engine matrix and retained evidence command",
        'server-args="-screen 0 1920x1200x24"',
        "node scripts/browser_conformance.mjs",
        "--evidence browser-conformance-evidence.json",
    )
    conformance_step = _named_step_blocks(browser_conformance).get(
        "Run accessibility and cross-browser conformance", ""
    )
    if "--browsers" in conformance_step:
        errors.append("hard browser_conformance step must run all three engines")
    _require_step_contains(
        errors,
        browser_conformance,
        "Upload browser conformance evidence",
        "failure-retaining conformance evidence policy",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "browser-conformance-evidence",
        "if-no-files-found: error",
        "browser-conformance-evidence.json",
    )
    _require_step_contains(
        errors,
        browser_conformance,
        "Focused pan/zoom matrix (three engines)",
        "hard focused three-engine pan/zoom subset",
        'XY_PAN_ZOOM_HEADFUL: "1"',
        "xvfb-run",
        "scripts/pan_zoom_matrix.mjs",
        "--profile focused",
        "--browsers chromium,firefox,webkit",
        "--evidence pan-zoom-cross-engine-evidence.json",
    )
    _require_step_contains(
        errors,
        browser_conformance,
        "Upload cross-engine pan/zoom evidence",
        "failure-retaining cross-engine pan/zoom artifact policy",
        "if: always()",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "pan-zoom-cross-engine-evidence",
        "if-no-files-found: error",
        "pan-zoom-cross-engine-evidence.json",
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
        "timeout-minutes: 10",
        "fail-fast: false",
        "matrix:",
        "xy: false",
        "browser: false",
        "build_js: false",
        "if: matrix.xy",
        "if: matrix.browser",
        "if: matrix.build_js",
        "--constraint benchmarks/requirements-ci.lock",
        "CHROMIUM_ARGS=()",
        "--libraries",
        "--max-n",
        "Run cross-library benchmark group",
        "Upload cross-library benchmark part",
        "benchmark-vs-${{ matrix.name }}",
        "if: always()",
        "actions/upload-artifact@",
        "if-no-files-found: warn",
    )
    cross_library = jobs.get("benchmark_vs", "")
    expected_matrix = {
        "native-and-webgl": {
            "libraries": "xy,plotly_gl,bokeh_webgl,datashader",
            "packages": "plotly kaleido bokeh datashader psutil",
            "max_n": "10000000",
            "xy": "true",
            "browser": "true",
            "build_js": "true",
        },
        "matplotlib": {
            "libraries": "matplotlib",
            "packages": "numpy matplotlib psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "false",
            "build_js": "false",
        },
        "seaborn": {
            "libraries": "seaborn",
            "packages": "numpy seaborn psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "false",
            "build_js": "false",
        },
        "plotly-svg": {
            "libraries": "plotly_svg",
            "packages": "numpy plotly kaleido psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "true",
            "build_js": "false",
        },
        "bokeh-canvas": {
            "libraries": "bokeh_canvas",
            "packages": "numpy bokeh psutil",
            "max_n": "10000000",
            "xy": "false",
            "browser": "true",
            "build_js": "false",
        },
        "html-adapters": {
            "libraries": "altair,hvplot_bokeh",
            "packages": "numpy altair hvplot psutil",
            "max_n": "100000",
            "xy": "false",
            "browser": "true",
            "build_js": "false",
        },
    }
    matrix_entries = _matrix_include_entries(cross_library)
    matrix_by_name = {
        entry["name"]: entry for entry in matrix_entries if isinstance(entry.get("name"), str)
    }
    matrix_names = [entry.get("name") for entry in matrix_entries]
    duplicate_names = sorted({name for name in matrix_names if matrix_names.count(name) > 1})
    if duplicate_names:
        errors.append(f"CI benchmark_vs matrix has duplicate names: {duplicate_names}")
    if set(matrix_by_name) != set(expected_matrix):
        errors.append(
            "CI benchmark_vs matrix names must exactly match isolated benchmark groups; "
            f"got {sorted(matrix_by_name)}, expected {sorted(expected_matrix)}"
        )
    for name, expected in expected_matrix.items():
        actual = matrix_by_name.get(name)
        if actual is None:
            continue
        expected_entry = {"name": name, **expected}
        if actual != expected_entry:
            errors.append(
                f"CI benchmark_vs matrix entry {name!r} must exactly equal "
                f"{expected_entry!r}; got {actual!r}"
            )
    if not _step_is_conditioned(cross_library, "dtolnay/rust-toolchain@"):
        errors.append("CI benchmark_vs Rust toolchain setup must be conditioned on matrix.xy")
    _require_step_contains(
        errors,
        cross_library,
        "Build native core",
        "xy-only setup condition",
        "if: matrix.xy",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Install xy",
        "xy-only constrained install",
        "if: matrix.xy",
        'XY_REQUIRE_CARGO: "1"',
        "--constraint benchmarks/requirements-ci.lock",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Install selected competitors",
        "locked benchmark dependency constraint",
        "--constraint benchmarks/requirements-ci.lock",
        "${{ matrix.packages }}",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Verify native benchmark backend",
        "xy-only verification condition",
        "if: matrix.xy",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Install Chromium (Playwright)",
        "browser-only setup condition",
        "if: matrix.browser",
    )
    _require_step_contains(
        errors,
        cross_library,
        "Build JS client",
        "xy browser-build condition",
        "if: matrix.build_js",
    )
    _require_job_contains(
        errors,
        jobs,
        "benchmark_methodology",
        "CI",
        "non-blocking methodology benchmark artifact path",
        "continue-on-error: true",
        "benchmarks/requirements-ci.lock",
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
        "dependency_audit",
        "CI",
        "pinned multi-ecosystem audit and retained machine-readable evidence",
        "name: Multi-ecosystem dependency audit",
        "timeout-minutes: 15",
        "Validate dependency audit policy",
        "python3 scripts/dependency_audit.py validate",
        "Install pinned OSV-Scanner",
        "osv-scanner/releases/download/v2.4.0/osv-scanner_linux_amd64",
        "15314940c10d26af9c6649f150b8a47c1262e8fc7e17b1d1029b0e479e8ed8a0",
        "sha256sum --check --strict",
        "Audit every active dependency environment",
        "python3 scripts/dependency_audit.py scan",
        "Retain dependency audit evidence",
        "if: always()",
        "actions/upload-artifact@",
        "if-no-files-found: error",
        "retention-days: 30",
        "dependency-audit/*.json",
        "dependency-audit/*.txt",
    )
    dependency_audit = jobs.get("dependency_audit", "")
    if "continue-on-error:" in dependency_audit:
        errors.append("CI dependency_audit must be a hard gate without continue-on-error")
    if re.search(r"^    if:", dependency_audit, flags=re.MULTILINE):
        errors.append("CI dependency_audit job must be unconditional")
    for step_name in (
        "Validate dependency audit policy",
        "Install pinned OSV-Scanner",
        "Audit every active dependency environment",
    ):
        if _step_is_conditioned(dependency_audit, step_name):
            errors.append(f"CI dependency_audit step {step_name!r} must be unconditional")

    _require_job_contains(
        errors,
        jobs,
        "rust_release",
        "CI",
        "locked release-profile suite and release-only regression inventory",
        "name: Rust release-profile tests",
        "timeout-minutes: 15",
        "dtolnay/rust-toolchain@",
        "Inventory release-only regression coverage",
        "cargo test --locked --release -- --list",
        "release-tests.txt",
        "grep -Fqx",
        "tiles::tests::compose_window_astronomically_past_domain_is_empty_not_panic: test",
        "Run locked release-profile suite",
        "run: cargo test --locked --release",
        "Upload release-profile test inventory",
        "if: always()",
        "actions/upload-artifact@",
        "name: rust-release-test-inventory",
        "if-no-files-found: error",
        "path: release-tests.txt",
    )
    release_tests = jobs.get("rust_release", "")
    if "continue-on-error:" in release_tests:
        errors.append("CI rust_release must be a hard gate without continue-on-error")
    for step_name in (
        "Inventory release-only regression coverage",
        "Run locked release-profile suite",
    ):
        if _step_is_conditioned(release_tests, step_name):
            errors.append(f"CI rust_release step {step_name!r} must be unconditional")
    _require_job_contains(
        errors,
        jobs,
        "native_parity",
        "CI",
        "hard native architecture matrix and retained common parity probe",
        "timeout-minutes: 15",
        "fail-fast: false",
        "ubuntu-latest",
        "ubuntu-24.04-arm",
        "windows-latest",
        "macos-14",
        "cargo build --locked --release",
        "scripts/native_parity.py",
        "--expect-arch ${{ matrix.arch }}",
        "--expect-default ${{ matrix.default }}",
        "if: always()",
        "actions/upload-artifact@",
        "name: native-parity-${{ matrix.os }}",
        "if-no-files-found: error",
    )
    native_parity = jobs.get("native_parity", "")
    expected_native_matrix = [
        {"os": "ubuntu-latest", "arch": "x86_64", "default": "avx2"},
        {"os": "ubuntu-24.04-arm", "arch": "aarch64", "default": "aarch64"},
        {"os": "windows-latest", "arch": "x86_64", "default": "avx2"},
        {"os": "macos-14", "arch": "aarch64", "default": "aarch64"},
    ]
    if _matrix_include_entries(native_parity) != expected_native_matrix:
        errors.append(
            "CI native_parity matrix must exactly cover native Linux x64/ARM64, "
            "Windows x64, and macOS ARM64 with explicit dispatch expectations"
        )
    if "continue-on-error:" in native_parity:
        errors.append("CI native_parity must be a hard gate without continue-on-error")
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
    hard_jobs = {
        "browser_conformance",
        "dependency_audit",
        "install_without_rust",
        "javascript_semantics",
        "matplotlib_reference",
        "native_parity",
        "python_coverage",
        "python_floor",
        "reflex_adapter",
        "rust_release",
        "sdist",
        "test",
        "wheels",
    }
    aggregate = jobs.get("required_ci", "")
    _require_job_contains(
        errors,
        jobs,
        "required_ci",
        "CI",
        "stable hard-gate aggregation",
        "name: Required CI",
        "if: always()",
        "timeout-minutes: 5",
        "NEEDS_JSON: ${{ toJSON(needs) }}",
        "scripts/check_required_jobs.py",
    )
    if aggregate and _listed_needs(aggregate) != hard_jobs:
        errors.append(
            "CI required_ci needs must exactly match hard jobs; "
            f"got {sorted(_listed_needs(aggregate))}, expected {sorted(hard_jobs)}"
        )
    if "continue-on-error:" in aggregate:
        errors.append("CI required_ci must not use continue-on-error")
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
    errors = _python_heredoc_syntax_errors(text)
    # CodSpeed is advisory and may remain path-filtered; only the stable hard
    # aggregate in ci.yml is required on every pull request.
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
    errors = _python_heredoc_syntax_errors(text)
    missing_jobs = sorted(REQUIRED_RELEASE_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"release workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "release",
        "tag and manual triggers plus exact-SHA Actions access",
        'tags: ["v*"]',
        "workflow_dispatch:",
        "actions: read",
    )
    _require_job_contains(
        errors,
        jobs,
        "qualify",
        "release",
        "unconditional exact-SHA, main-ancestry, hard-CI, tag, version, and changelog preflight",
        "fetch-depth: 0",
        "main:refs/remotes/origin/main",
        "refs/tags/*:refs/tags/*",
        "source_sha=$(git rev-parse",
        "scripts/verify_source_qualification.py",
        '--sha "$SOURCE_SHA"',
        '--repository "$GITHUB_REPOSITORY"',
        '--tag "$RELEASE_TAG"',
        "--release-metadata",
        "--wait-seconds 3600",
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
        "needs: qualify",
        "ref: ${{ needs.qualify.outputs.source_sha }}",
    )
    wheels_job = jobs.get("wheels", "")
    if "continue-on-error:" in wheels_job:
        errors.append(
            "release wheels job must block publishing when any native wheel build or "
            "verification fails"
        )
    _require_step_contains(
        errors,
        wheels_job,
        "Run manylinux wheel parity in glibc 2.17",
        "pinned manylinux runtime and common artifact parity probe",
        "if: matrix.runtime == 'manylinux'",
        "manylinux2014_x86_64@sha256:",
        "scripts/native_parity.py",
        "--wheel",
        "--expect-default avx2",
    )
    _require_step_contains(
        errors,
        wheels_job,
        "Run musllinux wheel parity in musl 1.2",
        "pinned musllinux runtime and common artifact parity probe",
        "if: matrix.runtime == 'musllinux'",
        "python:3.13-alpine3.22@sha256:",
        "scripts/native_parity.py",
        "--wheel",
        "--expect-default avx2",
    )
    _require_step_contains(
        errors,
        wheels_job,
        "Retain native artifact runtime report",
        "manylinux/musllinux runtime evidence retention",
        "always() && (matrix.runtime == 'manylinux' || matrix.runtime == 'musllinux')",
        "actions/upload-artifact@",
        "if-no-files-found: error",
        "native-parity-${{ matrix.plat }}.json",
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
        "name: pyodide-wheel",
        "needs: qualify",
        "ref: ${{ needs.qualify.outputs.source_sha }}",
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
        "needs: qualify",
        "ref: ${{ needs.qualify.outputs.source_sha }}",
    )
    _require_job_contains(
        errors,
        jobs,
        "provenance",
        "release",
        "one immutable hash manifest for the exact artifacts built in this run",
        "needs: [qualify, wheels, sdist, wasm]",
        "pattern: dist-*",
        "name: pyodide-wheel",
        "scripts/release_provenance.py create",
        "scripts/release_provenance.py verify",
        '--source-sha "$SOURCE_SHA"',
        '--repository "$GITHUB_REPOSITORY"',
        '--workflow-run-id "$GITHUB_RUN_ID"',
        '--tag "$RELEASE_TAG"',
        "name: release-provenance",
        "if-no-files-found: error",
    )
    provenance_job = jobs.get("provenance", "")
    for identity_argument in (
        '--source-sha "$SOURCE_SHA"',
        '--repository "$GITHUB_REPOSITORY"',
        '--workflow-run-id "$GITHUB_RUN_ID"',
        '--tag "$RELEASE_TAG"',
    ):
        if provenance_job.count(identity_argument) != 2:
            errors.append(
                "release provenance job must bind "
                f"{identity_argument} during both creation and self-verification"
            )
    _require_job_contains(
        errors,
        jobs,
        "publish",
        "release",
        "trusted PyPI publishing from downloaded artifacts, gated by a dry-run switch "
        "and a tag/version/CHANGELOG agreement gate",
        "needs: [qualify, wheels, sdist, wasm, provenance]",
        "environment: pypi",
        "id-token: write",
        "scripts/check_release_version.py",
        "scripts/release_provenance.py verify",
        '--repository "$GITHUB_REPOSITORY"',
        '--workflow-run-id "$GITHUB_RUN_ID"',
        '--tag "$RELEASE_TAG"',
        "name: release-provenance",
        "ref: ${{ needs.qualify.outputs.source_sha }}",
        "actions/download-artifact@",
        "pattern: dist-*",
        "merge-multiple: true",
        "dry_run",
        "pypa/gh-action-pypi-publish@",
        "packages-dir: dist/",
        "skip-existing: true",
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
    _require_job_contains(
        errors,
        jobs,
        "publish-pyodide",
        "release",
        "GitHub Release publication of the runtime-verified Pyodide wheel",
        "needs: [qualify, wheels, sdist, wasm, provenance]",
        "contents: write",
        "actions/setup-node@",
        'node-version: "22"',
        "actions/download-artifact@",
        "name: pyodide-wheel",
        "dry_run",
        "scripts/check_release_version.py",
        "scripts/release_provenance.py verify",
        '--repository "$GITHUB_REPOSITORY"',
        '--workflow-run-id "$GITHUB_RUN_ID"',
        '--tag "$RELEASE_TAG"',
        "name: release-provenance",
        "ref: ${{ needs.qualify.outputs.source_sha }}",
        "GH_TOKEN",
        "gh release upload",
        "provenance/release-provenance.json",
        "--clobber",
        "gh release create",
        "--verify-tag",
        "steps.publish.outputs.wheel_url",
        "pyodide@0.29.4",
        "scripts/pyodide_load_smoke.py",
    )

    publish = jobs.get("publish", "")
    qualify = jobs.get("qualify", "")
    if re.search(r"^    if:", qualify, flags=re.MULTILINE):
        errors.append("release qualify job must be unconditional; publication cannot bypass it")
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


def validate_deploy_workflows(
    dev_path: Path = DEFAULT_DEPLOY_DEV_WORKFLOW,
    stg_path: Path = DEFAULT_DEPLOY_STG_WORKFLOW,
    build_path: Path = DEFAULT_BUILD_DOCS_WORKFLOW,
    helm_path: Path = DEFAULT_HELM_DOCS_WORKFLOW,
) -> list[str]:
    """Verify exact-source qualification and immutable docs promotion."""
    texts: dict[str, str] = {}
    errors: list[str] = []
    for label, path in (
        ("docs dev deploy", dev_path),
        ("docs stage/prod deploy", stg_path),
        ("docs image build", build_path),
        ("docs Helm promotion", helm_path),
    ):
        try:
            texts[label] = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read {label} workflow {path}: {exc}")
            texts[label] = ""

    dev_text = texts["docs dev deploy"]
    dev_jobs = _job_blocks(dev_text)
    _require_workflow_contains(
        errors,
        dev_text,
        "docs dev deploy",
        "exact-SHA Actions access",
        "actions: read",
    )
    _require_job_contains(
        errors,
        dev_jobs,
        "qualify",
        "docs dev deploy",
        "exact-SHA main-ancestry and hard-CI preflight",
        "needs: prepare",
        "fetch-depth: 0",
        "main:refs/remotes/origin/main",
        "scripts/verify_source_qualification.py",
        '--sha "$SOURCE_SHA"',
        '--repository "$GITHUB_REPOSITORY"',
        "--wait-seconds 3600",
    )
    _require_job_contains(
        errors,
        dev_jobs,
        "build",
        "docs dev deploy",
        "qualified exact-source build dependency",
        "needs: [prepare, qualify]",
        "source_ref: ${{ needs.prepare.outputs.source_sha }}",
    )
    _require_job_contains(
        errors,
        dev_jobs,
        "helm-pr",
        "docs dev deploy",
        "immutable build digest promotion",
        "frontend_digest: ${{ needs.build.outputs.frontend_digest }}",
        "backend_digest: ${{ needs.build.outputs.backend_digest }}",
    )

    stg_text = texts["docs stage/prod deploy"]
    stg_jobs = _job_blocks(stg_text)
    _require_workflow_contains(
        errors,
        stg_text,
        "docs stage/prod deploy",
        "exact-SHA Actions access",
        "actions: read",
    )
    _require_job_contains(
        errors,
        stg_jobs,
        "qualify",
        "docs stage/prod deploy",
        "exact tagged source, main-ancestry, and hard-CI preflight",
        "needs: prepare",
        "fetch-depth: 0",
        "main:refs/remotes/origin/main",
        "refs/tags/*:refs/tags/*",
        "scripts/verify_source_qualification.py",
        '--sha "$SOURCE_SHA"',
        '--tag "$VERSION"',
        "--wait-seconds 3600",
    )
    _require_job_contains(
        errors,
        stg_jobs,
        "build",
        "docs stage/prod deploy",
        "qualified exact-source build dependency",
        "needs: [prepare, qualify]",
        "source_ref: ${{ needs.prepare.outputs.source_sha }}",
    )
    _require_job_contains(
        errors,
        stg_jobs,
        "helm-pr-stg",
        "docs stage/prod deploy",
        "immutable staging digest promotion",
        "frontend_digest: ${{ needs.build.outputs.frontend_digest }}",
        "backend_digest: ${{ needs.build.outputs.backend_digest }}",
    )
    _require_job_contains(
        errors,
        stg_jobs,
        "verify-prod-artifacts",
        "docs stage/prod deploy",
        "post-approval ECR digest verification against the original build",
        "needs: [prepare, build, await-prod-approval]",
        "EXPECTED_FRONTEND: ${{ needs.build.outputs.frontend_digest }}",
        "EXPECTED_BACKEND: ${{ needs.build.outputs.backend_digest }}",
        '[[ "$ACTUAL_FRONTEND" != "$EXPECTED_FRONTEND" ]]',
        '[[ "$ACTUAL_BACKEND" != "$EXPECTED_BACKEND" ]]',
    )
    _require_job_contains(
        errors,
        stg_jobs,
        "release",
        "docs stage/prod deploy",
        "verified digest provenance in the deployment release",
        "needs: [prepare, build, verify-prod-artifacts]",
        "FRONTEND_DIGEST: ${{ needs.build.outputs.frontend_digest }}",
        "BACKEND_DIGEST: ${{ needs.build.outputs.backend_digest }}",
    )
    _require_job_contains(
        errors,
        stg_jobs,
        "helm-pr-prod",
        "docs stage/prod deploy",
        "verified immutable production promotion",
        "needs: [prepare, build, verify-prod-artifacts, release]",
        "frontend_digest: ${{ needs.build.outputs.frontend_digest }}",
        "backend_digest: ${{ needs.build.outputs.backend_digest }}",
    )

    build_text = texts["docs image build"]
    build_jobs = _job_blocks(build_text)
    _require_workflow_contains(
        errors,
        build_text,
        "docs image build",
        "reusable immutable digest outputs",
        "frontend_digest:",
        "backend_digest:",
        "value: ${{ jobs.build-and-push.outputs.frontend_digest }}",
        "value: ${{ jobs.build-and-push.outputs.backend_digest }}",
    )
    _require_job_contains(
        errors,
        build_jobs,
        "build-and-push",
        "docs image build",
        "ECR digest resolution and provenance attestations",
        "id: digests",
        "--repository-name xy/frontend",
        "--repository-name xy/backend",
        "frontend_digest=$FRONTEND_DIGEST",
        "backend_digest=$BACKEND_DIGEST",
        "^sha256:[0-9a-f]{64}$",
    )
    if build_text.count("--provenance=mode=max") != 2:
        errors.append("docs image build must enable max provenance on both image builds")
    if "--provenance=false" in build_text:
        errors.append("docs image build must not disable image provenance")

    helm_text = texts["docs Helm promotion"]
    helm_jobs = _job_blocks(helm_text)
    _require_workflow_contains(
        errors,
        helm_text,
        "docs Helm promotion",
        "required immutable digest inputs",
        "frontend_digest:",
        "backend_digest:",
        'description: "Immutable sha256 digest for the frontend image"',
        'description: "Immutable sha256 digest for the backend image"',
    )
    _require_job_contains(
        errors,
        helm_jobs,
        "open-helm-pr",
        "docs Helm promotion",
        "digest validation and tag-at-digest chart pins",
        "^sha256:[0-9a-f]{64}$",
        'FRONTEND_REF="${IMAGE_TAG}@${FRONTEND_DIGEST}"',
        'BACKEND_REF="${IMAGE_TAG}@${BACKEND_DIGEST}"',
        ".apps.xy.frontend.image.tag = strenv(FRONTEND_REF)",
        ".apps.xy.backend.image.tag = strenv(BACKEND_REF)",
        "FRONTEND_IMAGE}:${IMAGE_TAG}@${FRONTEND_DIGEST}",
        "BACKEND_IMAGE}:${IMAGE_TAG}@${BACKEND_DIGEST}",
    )
    return errors


def validate_all_workflows(
    ci_path: Path = DEFAULT_CI_WORKFLOW,
    codspeed_path: Path = DEFAULT_CODSPEED_WORKFLOW,
    release_path: Path = DEFAULT_RELEASE_WORKFLOW,
    deploy_dev_path: Path = DEFAULT_DEPLOY_DEV_WORKFLOW,
    deploy_stg_path: Path = DEFAULT_DEPLOY_STG_WORKFLOW,
    build_docs_path: Path = DEFAULT_BUILD_DOCS_WORKFLOW,
    helm_docs_path: Path = DEFAULT_HELM_DOCS_WORKFLOW,
) -> list[str]:
    return [
        *validate_ci_workflow(ci_path),
        *validate_codspeed_workflow(codspeed_path),
        *validate_release_workflow(release_path),
        *validate_deploy_workflows(
            deploy_dev_path,
            deploy_stg_path,
            build_docs_path,
            helm_docs_path,
        ),
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
    parser.add_argument("--deploy-dev-workflow", type=Path, default=DEFAULT_DEPLOY_DEV_WORKFLOW)
    parser.add_argument("--deploy-stg-workflow", type=Path, default=DEFAULT_DEPLOY_STG_WORKFLOW)
    parser.add_argument("--build-docs-workflow", type=Path, default=DEFAULT_BUILD_DOCS_WORKFLOW)
    parser.add_argument("--helm-docs-workflow", type=Path, default=DEFAULT_HELM_DOCS_WORKFLOW)
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
            args.ci_workflow,
            args.codspeed_workflow,
            args.release_workflow,
            args.deploy_dev_workflow,
            args.deploy_stg_workflow,
            args.build_docs_workflow,
            args.helm_docs_workflow,
        )
        checked = [
            args.ci_workflow,
            args.codspeed_workflow,
            args.release_workflow,
            args.deploy_dev_workflow,
            args.deploy_stg_workflow,
            args.build_docs_workflow,
            args.helm_docs_workflow,
        ]

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
