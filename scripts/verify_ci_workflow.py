#!/usr/bin/env python3
"""Verify workflow invariants that protect production-facing gates.

The workflows are YAML, but this checker intentionally stays stdlib-only so it
can run before the dev environment is installed. It does not try to be a full
YAML parser; it checks stable, high-value invariants that are easy to lose when
editing `.github/workflows/ci.yml`, `.github/workflows/release.yml`,
`.github/workflows/release-reflex-xy.yml`, or the production docs release gate.
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
DEFAULT_REFLEX_XY_RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release-reflex-xy.yml"
DEFAULT_DOCS_DEPLOY_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-docs-stg.yml"
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
REQUIRED_RELEASE_JOBS = {"wheels", "sdist", "publish", "wasm", "github-release"}
REQUIRED_REFLEX_XY_RELEASE_JOBS = {"build", "publish"}


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


def _job_scalar(job_text: str, key: str) -> str | None:
    """Return an active job-level scalar, ignoring comments and nested keys."""
    match = re.search(rf"^    {re.escape(key)}:\s*(.*?)\s*$", job_text, re.MULTILINE)
    return None if match is None else match.group(1)


def _job_mapping(job_text: str, key: str) -> dict[str, str] | None:
    """Return an active job-level mapping with direct scalar children."""
    lines = job_text.splitlines()
    try:
        start = lines.index(f"    {key}:")
    except ValueError:
        return None

    mapping: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 4:
            break
        match = re.fullmatch(r"      ([A-Za-z0-9_-]+):\s*(.*?)\s*", line)
        if match:
            mapping[match.group(1)] = match.group(2)
    return mapping


def _named_step_run(job_text: str, step: str) -> str | None:
    """Return one named step's active shell body without comment-only lines."""
    block = _named_step_blocks(job_text).get(step)
    if block is None:
        return None
    lines = block.splitlines()
    try:
        start = lines.index("        run: |")
    except ValueError:
        return None
    shell_lines = [
        line[10:] if line.startswith("          ") else line.lstrip()
        for line in lines[start + 1 :]
        if not line.lstrip().startswith("#")
    ]
    return "\n".join(shell_lines)


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


def _step_block(job_text: str, step_needle: str) -> Optional[str]:
    """The indented block of the step whose `uses:`/`run:` line contains
    `step_needle` — the step's own lines only, so a same-level sibling step
    can't mask a missing key.

    The prefix (the step's own `uses:`/`name:`/`run:` line) is matched with
    `[^\\n]*`, not a dot-all `.*` — under re.DOTALL a greedy `.*` would happily
    span past earlier sibling steps and swallow their `if:` lines too, which
    defeats the whole point of scoping this to one step.
    """
    match = re.search(
        rf"( *)- (?:uses|name|run): [^\n]*{re.escape(step_needle)}[^\n]*\n([\s\S]*?)(?=\n\1- |\Z)",
        job_text,
    )
    return None if match is None else match.group(0)


def _step_is_conditioned(job_text: str, step_needle: str) -> bool:
    """True if the step has its own `if:` key — not just any `if:` elsewhere
    in the job (e.g. a sibling step's dry-run summary)."""
    block = _step_block(job_text, step_needle)
    return block is not None and "if:" in block


# The one condition that actually gates a PyPI upload behind the manual
# dry-run switch. Requiring this exact predicate on the upload step itself —
# not merely *an* `if:` — is the point: `if: always()` or any unrelated
# condition would satisfy a mere presence check while gating nothing.
PYPI_PUBLISH_GATE = (
    "if: github.event_name != 'workflow_dispatch' || github.event.inputs.dry_run != 'true'"
)
CORE_PRERELEASE_TAG_PATTERN = r"^v[0-9]+\.[0-9]+\.[0-9]+(a|b|rc)[0-9]+$"


def _step_carries_publish_gate(job_text: str, step_needle: str) -> bool:
    block = _step_block(job_text, step_needle)
    return block is not None and PYPI_PUBLISH_GATE in block


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


def _require_unshallow_checkouts(errors: list[str], text: str, workflow_label: str) -> None:
    """Every checkout must fetch full history, tags included.

    The distribution version is derived from the latest `v*` tag
    (uv-dynamic-versioning in pyproject), and `actions/checkout` defaults to a
    depth-1 clone carrying no tags at all. Under that default the version
    resolves to the `0.0.0` fallback *silently* — a build succeeds and ships the
    wrong number rather than failing. So a shallow checkout here is a publishing
    bug, not a performance tweak, and it is invisible until someone reads a
    PyPI page. Cheap to require, expensive to notice late.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "uses: actions/checkout@" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        step: list[str] = []
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped:
                continue
            following_indent = len(following) - len(following.lstrip())
            if following_indent < indent or (
                following_indent == indent and stripped.startswith("-")
            ):
                break
            step.append(stripped)
        if "fetch-depth: 0" not in step:
            errors.append(
                f"{workflow_label} workflow has an actions/checkout step (line {index + 1}) "
                "without `fetch-depth: 0` — the distribution version is derived from git "
                "tags, which a shallow checkout does not fetch, so the build would quietly "
                "fall back to 0.0.0"
            )


def _require_docs_spec_pr_paths_ignored(errors: list[str], text: str, workflow_label: str) -> None:
    """Require PR-only docs/spec changes to skip an expensive workflow."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "  pull_request:")
    except StopIteration:
        errors.append(f"{workflow_label} workflow missing pull_request trigger")
        return

    paths_ignore: list[str] | None = None
    collecting_paths_ignore = False
    for line in lines[start + 1 :]:
        indent = len(line) - len(line.lstrip())
        if line.strip() and indent <= 2:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if indent == 4:
            collecting_paths_ignore = bool(re.fullmatch(r"paths-ignore:\s*(?:#.*)?", stripped))
            if collecting_paths_ignore:
                paths_ignore = []
            continue
        if not collecting_paths_ignore or indent <= 4:
            continue
        item = re.fullmatch(r"-\s+(.+?)\s*", stripped)
        if item is None or paths_ignore is None:
            continue
        value = re.sub(r"\s+#.*$", "", item.group(1)).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        paths_ignore.append(value)

    required = {"docs/**", "spec/**"}
    missing = sorted(required - set(paths_ignore or []))
    if missing:
        errors.append(
            f"{workflow_label} pull_request trigger must skip docs/spec-only changes: {missing}"
        )


def validate_ci_workflow(path: Path = DEFAULT_CI_WORKFLOW) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read CI workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_docs_spec_pr_paths_ignored(errors, text, "CI")
    _require_unshallow_checkouts(errors, text, "CI")
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
        "ruff check .",
        "scripts/smoke_render.py",
        "Polar phase 6/7 live examples",
        "scripts/polar_phase7_smoke.py",
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
        "--transport transport.json --emit-md spec/benchmarks/metrics.md",
        "Upload regression benchmark report",
        "if: always()",
        "actions/upload-artifact@",
        "regression-benchmark-report",
        "if-no-files-found: warn",
        "spec/benchmarks/metrics.md",
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
        "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
        "~/.cache/ms-playwright",
        "playwright-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('package-lock.json') }}",
        "npx playwright install --with-deps chromium firefox webkit",
        "node js/build.mjs",
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
    _require_docs_spec_pr_paths_ignored(errors, text, "CodSpeed")
    _require_unshallow_checkouts(errors, text, "CodSpeed")
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
        "--group dev --group codspeed",
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
    _require_unshallow_checkouts(errors, text, "release")
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
    if "reflex-xy-v" in text:
        errors.append(
            "release workflow must not touch the reflex-xy tag namespace — the "
            "adapter publishes via release-reflex-xy.yml (bare `v*` tags never "
            "match `reflex-xy-v*` and vice versa; keep it that way)"
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
        "npm ci",
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
    wheels_job = jobs.get("wheels", "")
    if "continue-on-error:" in wheels_job:
        errors.append(
            "release wheels job must block publishing when any native wheel build or "
            "verification fails"
        )
    _require_job_contains(
        errors,
        jobs,
        "wasm",
        "release",
        "runtime-verified, PyPI-published PyEmscripten WASM wheel",
        "permissions:",
        "contents: read",
        "toolchain: 1.97.0",
        "wasm32-unknown-emscripten",
        'RUSTFLAGS="-C panic=abort"',
        "pypa/cibuildwheel@294735312765b09d24a2fbec22660ce817587d55",
        "CIBW_PLATFORM: pyodide",
        "CIBW_BUILD: cp314-pyodide_wasm32",
        'CIBW_PYODIDE_VERSION: "314.0.0"',
        "CIBW_BEFORE_BUILD_PYODIDE",
        "CIBW_ENVIRONMENT_PYODIDE",
        "pyemscripten_2026_0_wasm32",
        "pyodide@314.0.0",
        "scripts/pyodide_load_smoke.py",
        "scripts/verify_wheel.py",
        "--expect-native",
        "wheelhouse/*.whl",
        "name: dist-pyemscripten",
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
        "npm ci",
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
    publish = jobs.get("publish", "")
    if "password:" in publish or "api-token" in publish:
        errors.append("release publish job should use trusted publishing, not a PyPI token")
    if "pypa/gh-action-pypi-publish@" in publish and not _step_carries_publish_gate(
        publish, "pypa/gh-action-pypi-publish@"
    ):
        errors.append(
            "release publish job's PyPI upload step is not gated by the dry-run "
            f"predicate on the step itself (`{PYPI_PUBLISH_GATE}`) — a missing or "
            "unrelated condition (e.g. `if: always()`) would let a manual "
            "dispatch publish unintentionally"
        )
    _require_job_contains(
        errors,
        jobs,
        "github-release",
        "release",
        "GitHub Release creation from downloaded verified distributions",
        "actions/download-artifact@",
        "pattern: dist-*",
        "merge-multiple: true",
        "GH_TOKEN: ${{ github.token }}",
        "Create GitHub Release and attach distributions",
    )
    github_release = jobs.get("github-release")
    if github_release is not None:
        expected_gate = "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')"
        if _job_scalar(github_release, "if") != expected_gate:
            errors.append(
                "release github-release job must use the active tag-only gate "
                f"`if: {expected_gate}`"
            )
        if _job_scalar(github_release, "needs") != "publish":
            errors.append("release github-release job must actively declare `needs: publish`")
        permissions = _job_mapping(github_release, "permissions")
        if permissions != {"contents": "write"}:
            errors.append(
                "release github-release job permissions must be exactly "
                f"`contents: write`, found {permissions!r}"
            )

        release_shell = _named_step_run(
            github_release,
            "Create GitHub Release and attach distributions",
        )
        if release_shell is None:
            errors.append(
                "release github-release job is missing the active release publication shell step"
            )
        else:
            required_shell = (
                "shopt -s nullglob",
                "wheels=(dist/*.whl)",
                "sdists=(dist/*.tar.gz)",
                'artifacts=("${wheels[@]}" "${sdists[@]}")',
                "if (( ${#wheels[@]} == 0 || ${#sdists[@]} != 1 )); then\n"
                '  echo "::error::Expected at least one wheel and exactly one sdist"\n'
                "  exit 1\n"
                "fi",
                f'if [[ "$TAG" =~ {CORE_PRERELEASE_TAG_PATTERN} ]]; then',
                "prerelease=(--prerelease)",
                "edit_prerelease=(--prerelease)",
                "expected_prerelease=true",
                '"${edit_prerelease[@]}"',
                '"${prerelease[@]}"',
                "expected_assets_json=",
                'gh release upload "$TAG" "${artifacts[@]}"',
                'gh release create "$TAG" "${artifacts[@]}"',
                "--verify-tag",
                "--prerelease=false",
                "index($name) != null",
                '.assets[] | select(.name | endswith(".whl") or endswith(".tar.gz"))',
                '"repos/${REPO}/releases/assets/${asset_id}"',
                '"repos/${REPO}/releases/generate-notes"',
                '-f tag_name="$TAG"',
                '--notes-file "$notes_file"',
                "<!-- xy-release-workflow:%s -->",
                'generated_notes="$(<"$notes_file")"',
                'if [[ -z "${generated_notes//[[:space:]]/}" ]]; then',
                "isImmutable",
                "publishedAt",
                "tagName",
                "actual_assets_json=",
                '"$actual_assets_json" != "$expected_assets_json"',
                "--draft=false",
                "--clobber",
            )
            missing = _missing_needles(release_shell, required_shell)
            if missing:
                errors.append(
                    "release github-release job missing retry-safe artifact, metadata, "
                    f"prerelease, or generated-notes behavior: {missing}"
                )

            active_lines = [
                line.strip().removesuffix("\\").rstrip()
                for line in release_shell.splitlines()
                if line.strip()
            ]
            release_view = 'gh release view "$TAG"'
            release_json_fields = (
                "--json assets,body,isDraft,isImmutable,isPrerelease,name,publishedAt,tagName"
            )
            if active_lines.count(release_view) < 3 or active_lines.count(release_json_fields) < 3:
                errors.append(
                    "release github-release job must inspect full release metadata and "
                    "assets before recovery, after upload, and after normalization"
                )
            upload_lines = [
                line
                for line in active_lines
                if line.startswith('gh release upload "$TAG" "${artifacts[@]}" ')
            ]
            create_lines = [
                line
                for line in active_lines
                if line == 'gh release create "$TAG" "${artifacts[@]}"'
            ]
            if len(upload_lines) != 1 or len(create_lines) != 1:
                errors.append(
                    "release github-release job must pass the verified artifact array "
                    "directly to one active upload command and one active create command"
                )

            classifier = f'if [[ "$TAG" =~ {CORE_PRERELEASE_TAG_PATTERN} ]]; then'
            for assignment in (
                classifier,
                "prerelease=(--prerelease)",
                "edit_prerelease=(--prerelease)",
                "expected_prerelease=true",
            ):
                if assignment not in active_lines:
                    errors.append(
                        "release github-release job must actively classify canonical "
                        f"alpha/beta/RC tags; missing {assignment!r}"
                    )

            initial_view_position = release_shell.find(release_view)
            upload_position = release_shell.find('gh release upload "$TAG"')
            uploaded_view_position = release_shell.find(
                release_view,
                upload_position + 1 if upload_position >= 0 else 0,
            )
            prune_position = release_shell.find('"repos/${REPO}/releases/assets/${asset_id}"')
            edit_position = release_shell.find('gh release edit "$TAG"')
            final_view_position = release_shell.find(
                release_view,
                edit_position + 1 if edit_position >= 0 else 0,
            )
            if not (
                0
                <= initial_view_position
                < upload_position
                < uploaded_view_position
                < prune_position
                < edit_position
                < final_view_position
            ):
                errors.append(
                    "release github-release recovery must inspect, upload, re-read, "
                    "prune stale assets by id, edit metadata last, and validate again"
                )
    return errors


def validate_docs_deploy_workflow(path: Path = DEFAULT_DOCS_DEPLOY_WORKFLOW) -> list[str]:
    """Keep production promotion behind a complete, published library release."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read docs deploy workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_job_contains(
        errors,
        jobs,
        "verify-library-release",
        "docs deploy",
        "published GitHub Release metadata, generated notes, distribution assets, "
        "and PyPI availability before production promotion",
        "needs: [prepare, await-prod-approval]",
        "permissions:",
        "contents: read",
        "Await GitHub Release and PyPI availability",
    )
    release_gate = jobs.get("verify-library-release")
    if release_gate is None:
        return errors
    if _job_scalar(release_gate, "needs") != "[prepare, await-prod-approval]":
        errors.append(
            "docs deploy verify-library-release job must actively depend on "
            "prepare and production approval"
        )
    if _job_mapping(release_gate, "permissions") != {"contents": "read"}:
        errors.append(
            "docs deploy verify-library-release permissions must be exactly `contents: read`"
        )

    production = jobs.get("helm-pr-prod")
    if production is None:
        errors.append("docs deploy workflow is missing the production Helm promotion job")
    elif _job_scalar(production, "needs") != (
        "[prepare, await-prod-approval, verify-library-release]"
    ):
        errors.append(
            "docs deploy production Helm promotion must actively depend on verify-library-release"
        )

    gate_shell = _named_step_run(
        release_gate,
        "Await GitHub Release and PyPI availability",
    )
    if gate_shell is None:
        errors.append("docs deploy release gate is missing its active polling shell step")
        return errors

    required = (
        "EXPECTED_PRERELEASE=false",
        f'if [[ "$VERSION" =~ {CORE_PRERELEASE_TAG_PATTERN} ]]; then',
        "EXPECTED_PRERELEASE=true",
        'gh release view "$VERSION"',
        "--json assets,body,isDraft,isPrerelease,name,publishedAt,tagName",
        ".isDraft == false",
        ".name == $name",
        ".tagName == $name",
        ".publishedAt != null",
        ".isPrerelease == $prerelease",
        '(.body | endswith("<!-- xy-release-workflow:" + $name + " -->"))',
        'any(.assets[]?; .name | endswith(".whl"))',
        '([.assets[]? | select(.name | endswith(".tar.gz"))] | length) == 1',
        "[.assets[]?.name |",
        "[.urls[]?.filename |",
        '[[ "$github_assets" == "$pypi_assets" ]]; then',
        'if [[ "$RELEASED" == true &&',
        '"$PUBLISHED" == true &&',
        '"$ASSETS_MATCH" == true ]]; then',
    )
    missing = _missing_needles(gate_shell, required)
    if missing:
        errors.append(
            "docs deploy release gate must require expected non-draft metadata, "
            f"generated notes, wheel/sdist assets, and PyPI: {missing}"
        )
    return errors


def validate_reflex_xy_release_workflow(
    path: Path = DEFAULT_REFLEX_XY_RELEASE_WORKFLOW,
) -> list[str]:
    """The adapter's deliberately small release pipeline stays wired.

    reflex-xy is a pure-Python distribution (one py3-none-any wheel + one
    sdist), so it publishes from its own `reflex-xy-vX.Y.Z` tags via a
    separate workflow rather than a second build shape wedged into
    release.yml's cross-compile matrix. Small is the point — but the safety
    rails must match release.yml's: unshallow checkouts (tag-derived
    version), artifact verification, a changelog gate, trusted publishing,
    and a dry-run default that keeps manual dispatches from publishing.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read reflex-xy release workflow {path}: {exc}"]

    jobs = _job_blocks(text)
    errors: list[str] = []
    _require_unshallow_checkouts(errors, text, "reflex-xy release")
    missing_jobs = sorted(REQUIRED_REFLEX_XY_RELEASE_JOBS - set(jobs))
    if missing_jobs:
        errors.append(f"reflex-xy release workflow missing required jobs: {missing_jobs}")

    _require_workflow_contains(
        errors,
        text,
        "reflex-xy release",
        "adapter tag trigger and a workflow_dispatch dry-run input defaulting "
        "to true, so a manual run never accidentally publishes",
        'tags: ["reflex-xy-v*"]',
        "workflow_dispatch:",
        "dry_run:",
        "type: boolean",
        "default: true",
    )
    if 'tags: ["v*"]' in text or '"v*"' in text:
        errors.append(
            "reflex-xy release workflow must not trigger on bare `v*` tags — "
            "those belong to the xy core's release.yml"
        )
    _require_job_contains(
        errors,
        jobs,
        "build",
        "reflex-xy release",
        "pure sdist+wheel build, verification, install smoke, and upload",
        "astral-sh/setup-uv@",
        "working-directory: python/reflex-xy",
        "uv build",
        "scripts/verify_reflex_xy_dist.py",
        '--tag "$GITHUB_REF_NAME"',
        "import reflex_xy",
        "actions/upload-artifact@",
        "name: dist-reflex-xy",
    )
    _require_job_contains(
        errors,
        jobs,
        "publish",
        "reflex-xy release",
        "trusted PyPI publishing from downloaded artifacts, gated by a dry-run "
        "switch and the adapter tag/CHANGELOG agreement gate",
        "needs: [build]",
        "environment: pypi",
        "id-token: write",
        "scripts/check_release_version.py --package reflex-xy",
        "actions/download-artifact@",
        "name: dist-reflex-xy",
        "dry_run",
        "pypa/gh-action-pypi-publish@",
        "packages-dir: dist/",
        "skip-existing: true",
    )

    publish = jobs.get("publish", "")
    if "password:" in publish or "api-token" in publish:
        errors.append(
            "reflex-xy release publish job should use trusted publishing, not a PyPI token"
        )
    if "pypa/gh-action-pypi-publish@" in publish and not _step_carries_publish_gate(
        publish, "pypa/gh-action-pypi-publish@"
    ):
        errors.append(
            "reflex-xy release publish job's PyPI upload step is not gated by "
            f"the dry-run predicate on the step itself (`{PYPI_PUBLISH_GATE}`) — "
            "a missing or unrelated condition (e.g. `if: always()`) would let a "
            "manual dispatch publish unintentionally"
        )
    return errors


def validate_all_workflows(
    ci_path: Path = DEFAULT_CI_WORKFLOW,
    codspeed_path: Path = DEFAULT_CODSPEED_WORKFLOW,
    release_path: Path = DEFAULT_RELEASE_WORKFLOW,
    reflex_xy_release_path: Path = DEFAULT_REFLEX_XY_RELEASE_WORKFLOW,
    docs_deploy_path: Path = DEFAULT_DOCS_DEPLOY_WORKFLOW,
) -> list[str]:
    return [
        *validate_ci_workflow(ci_path),
        *validate_codspeed_workflow(codspeed_path),
        *validate_release_workflow(release_path),
        *validate_reflex_xy_release_workflow(reflex_xy_release_path),
        *validate_docs_deploy_workflow(docs_deploy_path),
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
    parser.add_argument(
        "--reflex-xy-release-workflow", type=Path, default=DEFAULT_REFLEX_XY_RELEASE_WORKFLOW
    )
    parser.add_argument(
        "--docs-deploy-workflow",
        type=Path,
        default=DEFAULT_DOCS_DEPLOY_WORKFLOW,
    )
    parser.add_argument("--ci-only", action="store_true")
    parser.add_argument("--codspeed-only", action="store_true")
    parser.add_argument("--release-only", action="store_true")
    parser.add_argument("--reflex-xy-release-only", action="store_true")
    parser.add_argument("--docs-deploy-only", action="store_true")
    args = parser.parse_args(argv)

    selected_modes = [
        args.ci_only,
        args.codspeed_only,
        args.release_only,
        args.reflex_xy_release_only,
        args.docs_deploy_only,
    ]
    if sum(1 for selected in selected_modes if selected) > 1:
        parser.error(
            "--ci-only, --codspeed-only, --release-only, "
            "--reflex-xy-release-only, and --docs-deploy-only are mutually exclusive"
        )

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
    elif args.reflex_xy_release_only:
        errors = validate_reflex_xy_release_workflow(args.reflex_xy_release_workflow)
        checked = [args.reflex_xy_release_workflow]
    elif args.docs_deploy_only:
        errors = validate_docs_deploy_workflow(args.docs_deploy_workflow)
        checked = [args.docs_deploy_workflow]
    else:
        errors = validate_all_workflows(
            args.ci_workflow,
            args.codspeed_workflow,
            args.release_workflow,
            args.reflex_xy_release_workflow,
            args.docs_deploy_workflow,
        )
        checked = [
            args.ci_workflow,
            args.codspeed_workflow,
            args.release_workflow,
            args.reflex_xy_release_workflow,
            args.docs_deploy_workflow,
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
