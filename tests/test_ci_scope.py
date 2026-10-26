"""Exercise selection boundaries and the actual complete git-diff path."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from scripts.ci_scope import GROUPS, select_checks

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "path", ["docs/app/xy_docs/page.py", "spec/design-dossier.md", "README.md", "news/ci.misc.md"]
)
def test_documentation_does_not_build_or_test_library(path):
    assert not any(select_checks([path]).values())


@pytest.mark.parametrize(
    "path",
    [
        "python/xy/pyplot/axes.py",
        "tests/backends/test_backend_xy.py",
        "gallery/matplotlib-3.11.1/baseline.json",
    ],
)
def test_pyplot_selects_compatibility_without_platform_builds(path):
    selected = select_checks([path])
    assert {key for key, enabled in selected.items() if enabled} == {"runtime", "pyplot"}


@pytest.mark.parametrize(
    "path",
    [
        "src/lib.rs",
        "js/src/60_entries.ts",
        "python/xy/_figure.py",
        "pyproject.toml",
        "new-build-input",
    ],
)
def test_shared_and_unknown_changes_do_not_select_pyplot(path):
    selected = select_checks([path])
    assert not selected["pyplot"]
    assert all(selected[group] for group in GROUPS if group != "pyplot")


def test_mixed_changes_and_manual_runs():
    selected = select_checks(["docs/index.md", "tests/test_figure.py", "benchmarks/bench_line.py"])
    assert {key for key, enabled in selected.items() if enabled} == {"runtime", "benchmarks"}
    assert all(select_checks([], full=True).values())
    assert not any(select_checks([]).values())


def test_deleted_and_renamed_inputs_are_in_complete_diff(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    git("init")
    git("config", "user.name", "CI test")
    git("config", "user.email", "ci@example.invalid")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/core.rs").write_text("core")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "docs").mkdir()
    git("mv", "src/core.rs", "docs/core.md")
    git("commit", "-am", "move")
    output = tmp_path / "outputs"
    script = Path(__file__).resolve().parents[1] / "scripts/ci_scope.py"
    subprocess.run(
        [sys.executable, str(script), "--base", base],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        check=True,
    )
    assert "pyplot=false" in output.read_text()
    assert all(f"{key}=true" in output.read_text() for key in (*GROUPS, "build") if key != "pyplot")


def test_shared_build_dependencies_and_summary():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    consumers = [
        "test",
        "browser_smokes",
        "regression_checks",
        "python_floor",
        "matplotlib_reference",
        "matplotlib_patch_smoke",
        "pyplot_gallery",
        "pyplot_gallery_extended",
        "browser_conformance",
        "benchmark_vs",
        "benchmark_methodology",
    ]
    for name in consumers:
        job = jobs[name]
        assert set(job["needs"]) == {"changes", "build"}
        restore = next(
            step
            for step in job["steps"]
            if step.get("uses") == "./.github/actions/restore-ci-build"
        )
        if name == "benchmark_vs":
            assert restore["if"] == "matrix.xy"
        else:
            assert "if" not in restore
        if name.startswith("benchmark"):
            assert job.get("continue-on-error") is True
        else:
            assert name in jobs["result"]["needs"]
    assert jobs["result"]["if"] == "always()"
    assert "test" not in jobs["wheels"]["needs"]


def test_restore_action_unpacks_only_shared_native_and_client(tmp_path):
    from zipfile import ZipFile

    action = yaml.safe_load((ROOT / ".github/actions/restore-ci-build/action.yml").read_text())
    dist = tmp_path / "dist"
    dist.mkdir()
    with ZipFile(dist / "xy-test.whl", "w") as wheel:
        wheel.writestr("xy/_native_lib/libxy_core.so", b"native artifact")
        wheel.writestr("xy/static/index.js", b"ESM client")
        wheel.writestr("xy/static/standalone.js", b"IIFE client")
        wheel.writestr("xy/__init__.py", b"do not overwrite source")
    environment = tmp_path / "github-env"
    subprocess.run(
        ["bash", "-e", "-c", action["runs"]["steps"][1]["run"]],
        cwd=tmp_path,
        env={**os.environ, "GITHUB_ENV": str(environment)},
        check=True,
    )
    assert (tmp_path / "python/xy/_native_lib/libxy_core.so").read_bytes() == b"native artifact"
    assert (tmp_path / "target/release/libxy_core.so").read_bytes() == b"native artifact"
    assert (tmp_path / "python/xy/static/standalone.js").read_bytes() == b"IIFE client"
    assert not (tmp_path / "python/xy/__init__.py").exists()
    assert environment.read_text() == "XY_SKIP_CARGO=1\n"


@pytest.mark.parametrize(
    "failed_job",
    [
        "changes",
        "build",
        "test",
        "rust_checks",
        "browser_smokes",
        "regression_checks",
        "python_floor",
        "matplotlib_reference",
        "matplotlib_patch_smoke",
        "pyplot_gallery",
        "pyplot_gallery_extended",
        "browser_conformance",
        "sdist",
        "wheels",
        "install_without_rust",
        None,
    ],
)
@pytest.mark.parametrize("status", ["failure", "cancelled"])
def test_ci_summary_rejects_selected_failures(tmp_path, failed_job, status):
    import json

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    result = workflow["jobs"]["result"]
    results = {name: {"result": "skipped"} for name in result["needs"]}
    results["changes"]["result"] = "success"
    if failed_job:
        results[failed_job]["result"] = status
    completed = subprocess.run(
        ["bash", "-e", "-c", result["steps"][0]["run"]],
        cwd=tmp_path,
        env={**os.environ, "RESULTS": json.dumps(results)},
        capture_output=True,
    )
    assert (completed.returncode == 0) == (failed_job is None)


@pytest.mark.parametrize("reverse", [False, True])
def test_ci_pr_skips_pyplot_unless_compatibility_also_changes(reverse):
    paths = [
        ".github/workflows/ci.yml",
        ".github/workflows/codspeed.yml",
        ".github/actions/restore-ci-build/action.yml",
        "scripts/ci_scope.py",
        "scripts/verify_ci_workflow.py",
        "tests/test_ci_scope.py",
        "tests/test_verify_ci_workflow.py",
        "spec/process/production-readiness.md",
        "news/ci-selection.misc.md",
    ]
    assert not select_checks(paths)["pyplot"]
    paths.append("python/xy/pyplot/_axes.py")
    if reverse:
        paths.reverse()
    assert select_checks(paths)["pyplot"]


@pytest.mark.parametrize(
    "path",
    [
        "benchmarks/bench_scatter_native.py",
        "benchmarks/bench_transport.py",
        "scripts/bench_native.py",
        "scripts/bench.py",
    ],
)
def test_benchmark_inputs_select_blocking_runtime_checks(path):
    selected = select_checks([path])
    assert selected["runtime"]
    assert selected["benchmarks"]
    assert not selected["pyplot"]


def test_codspeed_keeps_pyplot_performance_checks_selected():
    from fnmatch import fnmatchcase

    workflow = yaml.safe_load((ROOT / ".github/workflows/codspeed.yml").read_text())
    # PyYAML's YAML 1.1 loader interprets the unquoted Actions `on` key as True.
    ignored = workflow[True]["pull_request"]["paths-ignore"]
    assert not any(fnmatchcase("python/xy/pyplot/_axes.py", pattern) for pattern in ignored)


def test_actual_contributor_instructions_are_docs_only():
    assert not any(select_checks(["CLAUDE.md"]).values())


def test_codspeed_excludes_nested_markdown_and_license_changes():
    workflow = yaml.safe_load((ROOT / ".github/workflows/codspeed.yml").read_text())
    ignored = workflow[True]["pull_request"]["paths-ignore"]
    assert "**.md" in ignored
    assert "LICENSE" in ignored


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/workflows/codspeed.yml",
        ".github/actions/restore-ci-build/action.yml",
        "scripts/ci_scope.py",
        "scripts/verify_ci_workflow.py",
    ],
)
def test_ci_configuration_changes_skip_advisory_benchmarks(path):
    selected = select_checks([path])
    assert selected["runtime"]
    assert not selected["benchmarks"]
    assert not selected["pyplot"]


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_ci_and_benchmark_changes_preserve_benchmark_selection(reverse):
    paths = [".github/workflows/ci.yml", "benchmarks/bench_interaction.py"]
    if reverse:
        paths.reverse()
    assert select_checks(paths)["benchmarks"]


def test_methodology_browser_setup_avoids_system_package_downloads():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["benchmark_methodology"]
    steps = {step.get("name"): step for step in job["steps"]}
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == 20
    install = steps["Install Chromium (Playwright)"]
    assert install["timeout-minutes"] == 5
    assert install["run"].strip() == "npx playwright install --no-shell chromium"
    preflight = steps["Verify methodology Chromium"]
    assert preflight["timeout-minutes"] == 1
    assert "chromium.launch({executablePath: chromium.executablePath()})" in preflight["run"]
    cache = steps["Cache methodology Chromium"]
    assert cache["with"]["path"] == "~/.cache/ms-playwright"
    assert "hashFiles('package-lock.json')" in cache["with"]["key"]


def test_runtime_checks_run_in_independent_blocking_jobs():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    lanes = {
        "rust_checks": "Rust unit tests",
        "test": "Python tests (native core)",
        "browser_smokes": "Real-Figure render smoke (numpy + Chromium)",
        "regression_checks": "Regression gate (deterministic payloads = hard fail; timing = advisory)",
    }
    for name, required_step in lanes.items():
        job = jobs[name]
        dependencies = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
        assert set(dependencies) == ({"changes"} if name == "rust_checks" else {"changes", "build"})
        assert not set(lanes).intersection(dependencies)
        assert job["if"] == "needs.changes.outputs.runtime == 'true'"
        assert not job.get("continue-on-error", False)
        assert name in jobs["result"]["needs"]
        assert required_step in {step.get("name") for step in job["steps"]}
    assert "Rust unit tests" not in {step.get("name") for step in jobs["test"]["steps"]}


def test_parallel_runtime_browser_lanes_share_pinned_chromium_setup():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for name in ("test", "browser_smokes", "regression_checks"):
        setup = next(
            step
            for step in jobs[name]["steps"]
            if step.get("name") == "Install Chromium (Playwright)"
        )
        assert setup["uses"] == "./.github/actions/setup-ci-chromium"
        assert setup["timeout-minutes"] == 5


@pytest.mark.parametrize("filename", ["ci.yml", "codspeed.yml"])
def test_ci_checkouts_never_persist_credentials(filename):
    jobs = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step.get("with", {}).get("persist-credentials") is False


@pytest.mark.parametrize("filename", ["ci.yml", "codspeed.yml"])
def test_ci_bootstrap_tool_versions_are_exact(filename):
    jobs = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"]
    tools = {
        "actions/setup-node@": ("node-version", "22.23.3"),
        "astral-sh/setup-uv@": ("version", "0.13.5"),
        "dtolnay/rust-toolchain@": ("toolchain", "1.99.1"),
        "actions/setup-python@": ("python-version", "3.11.17"),
    }
    for job in jobs.values():
        for step in job.get("steps", []):
            for action, (key, version) in tools.items():
                if step.get("uses", "").startswith(action):
                    assert step.get("with", {}).get(key) == version


def test_codspeed_uses_verified_commit_instead_of_tag_object():
    job = yaml.safe_load((ROOT / ".github/workflows/codspeed.yml").read_text())["jobs"][
        "benchmarks"
    ]
    step = next(
        step for step in job["steps"] if step.get("uses", "").startswith("CodSpeedHQ/action@")
    )
    assert step["uses"] == "CodSpeedHQ/action@f99becdce5e5d51fd556489ebef684f4ecfd6286"


def test_pinned_rust_toolchain_installs_clippy():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    setup = next(
        step
        for step in jobs["rust_checks"]["steps"]
        if step.get("uses", "").startswith("dtolnay/rust-toolchain@")
    )
    assert "clippy" in setup["with"].get("components", "").split(",")


def test_wheel_repair_installs_and_executes_the_pinned_auditwheel():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    repair = next(
        step
        for step in jobs["wheels"]["steps"]
        if step.get("name") == "Repair Linux wheel to manylinux"
    )
    assert "uv tool install auditwheel==6.8.2" in repair["run"]
    assert "uv tool run --from auditwheel==6.8.2 auditwheel repair" in repair["run"]


def test_conformance_reuses_pinned_browser_image_instead_of_installing_engines():
    import json
    import re

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["browser_conformance"]
    version = json.loads((ROOT / "package.json").read_text())["devDependencies"]["playwright"]
    assert re.fullmatch(
        r"mcr\.microsoft\.com/playwright:v" + re.escape(version) + r"-noble@sha256:[0-9a-f]{64}",
        job["container"]["image"],
    )
    step_budget = sum(step.get("timeout-minutes", 0) for step in job["steps"])
    assert job["timeout-minutes"] >= step_budget + 4
    assert job["env"]["PLAYWRIGHT_BROWSERS_PATH"] == "/ms-playwright"
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "playwright install" not in commands
    assert "apt-get" not in commands
    assert "chromium, firefox, webkit" in commands
    assert "accessSync(browser.executablePath())" in commands
    assert "scripts/browser_conformance.mjs" in commands
    conformance = next(
        step
        for step in job["steps"]
        if step.get("name") == "Run accessibility and cross-browser conformance"
    )
    assert conformance["env"]["HOME"] == "/root"


def test_codspeed_skips_ci_only_prs_but_keeps_implementation_changes():
    from fnmatch import fnmatchcase

    workflow = yaml.safe_load((ROOT / ".github/workflows/codspeed.yml").read_text())
    ignored = workflow[True]["pull_request"]["paths-ignore"]
    ci_paths = [
        ".github/workflows/ci.yml",
        ".github/workflows/codspeed.yml",
        ".github/actions/setup-ci-chromium/action.yml",
        "scripts/ci_scope.py",
        "scripts/verify_ci_workflow.py",
        "tests/test_ci_scope.py",
        "spec/process/production-readiness.md",
        "news/539.misc.md",
    ]
    assert all(any(fnmatchcase(path, pattern) for pattern in ignored) for path in ci_paths)
    for path in (
        "src/lib.rs",
        "js/src/60_entries.ts",
        "python/xy/pyplot/_axes.py",
        "benchmarks/test_codspeed_kernels.py",
    ):
        assert not any(fnmatchcase(path, pattern) for pattern in ignored), path
