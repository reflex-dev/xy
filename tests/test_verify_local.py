from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _load_verify_local_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_local.py"
    spec = importlib.util.spec_from_file_location("verify_local", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_local = _load_verify_local_module()
ROOT = Path(__file__).resolve().parents[1]
SPEC_DOCS = ROOT / "spec"


def test_default_selection_is_quick_checks_only() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks)

    assert [check.name for check in selected] == list(verify_local.QUICK_CHECKS)
    assert "ci_workflow" in verify_local.QUICK_CHECKS


def test_full_selection_adds_js_rust_and_abi_checks() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, full=True)

    assert [check.name for check in selected] == list(
        verify_local.QUICK_CHECKS + verify_local.FULL_EXTRA_CHECKS
    )


def test_browser_selection_requires_browser_checks_to_exist() -> None:
    checks = verify_local._base_checks(Path("/tmp/chrome"))
    selected = verify_local.select_checks(checks, browser=True)

    assert [check.name for check in selected][-len(verify_local.BROWSER_CHECKS) :] == list(
        verify_local.BROWSER_CHECKS
    )


def test_packaging_selection_runs_artifact_checks_only(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.1.0.tar.gz"
    wheel = tmp_path / "xy-0.1.0-py3-none-any.whl"
    checks = verify_local._base_checks(sdist=sdist, wheel=wheel)
    selected = verify_local.select_checks(checks, packaging=True)

    assert [check.name for check in selected] == list(verify_local.PACKAGING_CHECKS)
    assert "pytest" not in [check.name for check in selected]


def test_browser_checks_are_listed_without_chromium(capsys: pytest.CaptureFixture[str]) -> None:
    rc = verify_local.main(["--list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "render_smoke_nonumpy" in out
    assert "smoke_render" in out
    assert "reflex_lifecycle_smoke" in out
    assert "visual_regression_smoke" in out
    assert "interaction_stress_smoke" in out
    assert "chromium" in out


def test_browser_checks_are_known_without_chromium() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"smoke_render"})

    assert [check.name for check in selected] == ["smoke_render"]


def test_example_checks_are_known_as_targeted_gate() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"examples"})

    assert [check.name for check in selected] == ["examples"]
    assert selected[0].command[-2:] == (
        "tests/test_docs_examples.py",
        "tests/test_example_apps.py",
    )
    assert selected[0].requires_modules == ("pytest",)


def test_security_export_check_is_known_as_targeted_gate() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"security_export"})

    assert [check.name for check in selected] == ["security_export"]
    command = selected[0].command
    assert "tests/test_static_client_security.py" in command
    assert "tests/test_figure.py::test_to_html_escapes_every_chart_text_surface" in command
    assert (
        "tests/test_figure.py::test_to_html_path_keeps_existing_file_on_atomic_replace_failure"
        in command
    )
    assert (
        "tests/test_components.py::test_component_to_html_escapes_user_strings_across_public_surface"
        in command
    )
    assert (
        "tests/test_components.py::test_component_to_html_path_keeps_existing_file_on_atomic_replace_failure"
        in command
    )
    assert selected[0].requires_modules == ("pytest",)


def test_ty_check_is_advisory_matching_ci() -> None:
    # ci.yml runs `ty check python || echo "::warning::..."` — advisory, not
    # gating (pre-1.0, can't narrow Optionals / NumPy dtypes across stub
    # versions). The local full gate must match, or `make check-full` fails on
    # findings CI ignores. If ty ever goes gating, flip both together.
    checks = verify_local._base_checks()
    assert checks["ty"].advisory is True
    # every other check stays gating
    gating = [c.name for c in checks.values() if not c.advisory]
    assert "ty" not in gating and "pytest" in gating and "ruff_check" in gating


def test_advisory_check_findings_do_not_fail_the_gate() -> None:
    # A failing advisory check warns but returns success; a failing gating
    # check still fails. Drive main() with a stubbed runner.
    import scripts.verify_local as vl

    def fake_run(check: verify_local.Check) -> int:
        return 1 if check.name == "ty" else 0

    original = vl.run_check
    vl.run_check = fake_run  # type: ignore[assignment]
    try:
        rc = vl.main(["--only", "ty"])
    finally:
        vl.run_check = original  # type: ignore[assignment]
    assert rc == 0  # advisory finding does not gate


def test_error_safety_check_is_known_as_targeted_gate() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"error_safety"})

    assert [check.name for check in selected] == ["error_safety"]
    assert selected[0].command[-3:] == (
        "tests/test_figure.py",
        "tests/test_components.py",
        "tests/test_lod.py",
    )
    assert selected[0].requires_modules == ("pytest",)


def test_benchmark_harness_check_is_known_as_targeted_gate() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"benchmark_harness"})

    assert [check.name for check in selected] == ["benchmark_harness"]
    command = selected[0].command
    assert "tests/test_benchmark_environment.py" in command
    assert "tests/test_verify_benchmark_report.py" in command
    assert "tests/test_check_regressions.py" in command
    assert "tests/test_claim_guardrails.py" in command
    assert selected[0].requires_modules == ("pytest",)


def test_api_surface_check_is_known_as_targeted_gate() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"api_surface"})

    assert [check.name for check in selected] == ["api_surface"]
    command = selected[0].command
    assert "tests/test_public_api.py" in command
    assert "tests/test_type_surface.py" in command
    assert (
        "tests/test_components.py::test_declarative_core_contract_for_layered_axis_chrome_and_interaction"
        in command
    )
    assert (
        "tests/test_components.py::test_declarative_chart_keeps_notebook_export_and_framework_chrome_contract"
        in command
    )
    assert selected[0].requires_modules == ("pytest",)


def test_import_budget_check_is_known_as_targeted_gate() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"import_budget"})

    assert [check.name for check in selected] == ["import_budget"]
    assert selected[0].command[-2:] == ("tests/test_import.py", "tests/test_dependencies.py")
    assert selected[0].requires_modules == ("pytest",)


def test_packaging_checks_are_known_without_artifact_paths() -> None:
    checks = verify_local._base_checks()
    selected = verify_local.select_checks(checks, only={"sdist_artifact", "wheel_artifact"})

    assert [check.name for check in selected] == ["sdist_artifact", "wheel_artifact"]


def test_unknown_only_or_skip_names_are_actionable() -> None:
    checks = verify_local._base_checks()
    with pytest.raises(ValueError, match="unknown check"):
        verify_local.select_checks(checks, only={"nope"})
    with pytest.raises(ValueError, match="unknown check"):
        verify_local.select_checks(checks, skip={"nope"})


def test_missing_requirement_messages_include_remediation() -> None:
    check = verify_local.Check(
        "needs_everything",
        "synthetic missing tool",
        ("missing-tool",),
        requires_executables=("definitely-not-a-xy-tool",),
        requires_modules=("definitely_not_a_xy_module",),
        requires_paths=(Path("/definitely/not/chromium"),),
    )

    reasons = verify_local.missing_reasons(check)

    assert any("missing executable" in reason for reason in reasons)
    assert any("make setup" in reason for reason in reasons)
    assert any("--chromium" in reason for reason in reasons)


def test_missing_chromium_argument_has_browser_hint() -> None:
    check = verify_local._base_checks()["smoke_render"]

    reasons = verify_local.missing_reasons(check)

    assert any("missing Chromium executable" in reason for reason in reasons)
    assert any("--chromium" in reason for reason in reasons)
    assert any("make check-browser" in reason for reason in reasons)


def test_missing_packaging_artifacts_have_build_hints(capsys: pytest.CaptureFixture[str]) -> None:
    rc = verify_local.main(["--packaging"])

    err = capsys.readouterr().err
    assert rc == 127
    assert "missing artifact path" in err
    assert "--sdist PATH" in err
    assert "make check-sdist" in err


def test_missing_named_packaging_artifact_has_verify_hint(tmp_path: Path) -> None:
    missing_sdist = tmp_path / "missing.tar.gz"
    check = verify_local._base_checks(sdist=missing_sdist)["sdist_artifact"]

    reasons = verify_local.missing_reasons(check)

    assert any("missing --sdist artifact" in reason for reason in reasons)
    assert any("make check-sdist" in reason for reason in reasons)


def test_browser_mode_without_chromium_exits_with_browser_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        verify_local.main(["--browser"])

    err = capsys.readouterr().err
    assert "--chromium PATH" in err
    assert "make check-browser" in err


def test_missing_common_python_modules_name_specific_setup_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verify_local, "_module_missing", lambda _module: True)
    for module in ("pytest", "ruff", "ty"):
        check = verify_local.Check(
            f"needs_{module}",
            "synthetic missing module",
            ("python", "-m", module),
            requires_modules=(module,),
        )

        reasons = verify_local.missing_reasons(check)

        assert any("make setup" in reason for reason in reasons)
        assert any('uv pip install -e ".[dev]"' in reason for reason in reasons)

    check = verify_local.Check(
        "needs_numpy",
        "synthetic render smoke",
        ("python", "scripts/smoke_render.py"),
        requires_modules=("numpy",),
    )
    reasons = verify_local.missing_reasons(check)
    assert any("numpy anywidget" in reason for reason in reasons)


def test_chromium_path_must_be_existing_executable_file(tmp_path: Path) -> None:
    directory = tmp_path / "Chrome.app"
    directory.mkdir()
    not_executable = tmp_path / "chrome"
    not_executable.write_text("#!/bin/sh\n", encoding="utf-8")

    for path, match in ((directory, "not a file"), (not_executable, "not executable")):
        check = verify_local.Check(
            "browser",
            "synthetic browser smoke",
            ("python", "scripts/smoke_render.py", str(path)),
            requires_paths=(path,),
        )

        reasons = verify_local.missing_reasons(check)

        assert any(match in reason for reason in reasons)
    assert any("make check-browser" in reason for reason in reasons)


def test_list_output_includes_check_requirements(capsys: pytest.CaptureFixture[str]) -> None:
    rc = verify_local.main(["--list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "pytest" in out
    assert "modules: pytest" in out
    assert "js_bundle" in out
    assert "executables: node" in out
    assert "node: >= 18" in out
    assert "rust_test" in out
    assert "executables: cargo" in out
    assert "rust: cargo + rustc" in out
    assert "rust: clippy" in out
    assert "smoke_render" in out
    assert "modules: numpy" in out
    assert "chromium" in out
    assert "sdist_artifact" in out
    assert "artifact: --sdist" in out
    assert "wheel_artifact" in out
    assert "artifact: --wheel" in out


def test_dry_run_prints_selected_commands_without_running(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "python_floor,public_api,claim_guardrails"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "python_floor" in out
    assert "scripts/check_python_floor.py" in out
    assert "public_api" in out
    assert "scripts/check_public_api.py" in out
    assert "claim_guardrails" in out
    assert "scripts/check_claim_guardrails.py" in out


def test_dry_run_includes_ci_workflow_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "ci_workflow"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ci_workflow" in out
    assert "scripts/verify_ci_workflow.py" in out


def test_dry_run_includes_examples_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "examples"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "examples" in out
    assert "tests/test_docs_examples.py" in out
    assert "tests/test_example_apps.py" in out


def test_dry_run_includes_security_export_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "security_export"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "security_export" in out
    assert "tests/test_static_client_security.py" in out
    assert "test_inline_json_export_escapes_html_hazards_without_changing_data" in out
    assert "test_to_html_path_keeps_existing_file_on_atomic_replace_failure" in out
    assert "test_component_to_html_path_keeps_existing_file_on_atomic_replace_failure" in out


def test_dry_run_includes_error_safety_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "error_safety"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "error_safety" in out
    assert "tests/test_figure.py" in out
    assert "tests/test_components.py" in out
    assert "tests/test_lod.py" in out


def test_dry_run_includes_benchmark_harness_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "benchmark_harness"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "benchmark_harness" in out
    assert "tests/test_benchmark_environment.py" in out
    assert "tests/test_verify_benchmark_report.py" in out


def test_dry_run_includes_api_surface_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "public_api,api_surface"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "public_api" in out
    assert "scripts/check_public_api.py" in out
    assert "api_surface" in out
    assert "tests/test_public_api.py" in out
    assert "tests/test_type_surface.py" in out


def test_dry_run_includes_import_budget_gate(capsys) -> None:
    rc = verify_local.main(["--dry-run", "--only", "public_api,import_budget"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "public_api" in out
    assert "scripts/check_public_api.py" in out
    assert "import_budget" in out
    assert "tests/test_import.py" in out
    assert "tests/test_dependencies.py" in out


def test_packaging_dry_run_prints_artifact_verifiers(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sdist = tmp_path / "xy-0.1.0.tar.gz"
    wheel = tmp_path / "xy-0.1.0-py3-none-any.whl"

    rc = verify_local.main(
        [
            "--packaging",
            "--sdist",
            str(sdist),
            "--wheel",
            str(wheel),
            "--expect-pure",
            "--dry-run",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "sdist_artifact" in out
    assert "scripts/verify_sdist.py" in out
    assert str(sdist) in out
    assert "wheel_artifact" in out
    assert "scripts/verify_wheel.py" in out
    assert str(wheel) in out
    assert "--expect-pure" in out


def test_makefile_exposes_sdist_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-sdist:" in makefile
    assert "set -e" in makefile
    assert "UV_CACHE_DIR" in makefile
    assert "uv build --sdist" in makefile
    assert "scripts/verify_sdist.py" in makefile
    assert "make check-sdist" in makefile


def test_contributor_setup_builds_native_core_and_docs_use_it() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    setup_recipe = makefile.split("setup:\n", 1)[1].split("\n\n", 1)[0]

    assert "uv venv" in setup_recipe
    assert 'uv pip install -e ".[dev]"' in setup_recipe
    assert "cargo build --release" in setup_recipe

    contributor_docs = (
        (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"),
        (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8"),
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "docs" / "api-reference" / "contributing.md").read_text(encoding="utf-8"),
    )
    for text in contributor_docs:
        assert "make setup" in text


def test_makefile_exposes_wheel_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-wheel:" in makefile
    assert "WHEEL_EXPECT" in makefile
    assert "set -e" in makefile
    assert "UV_CACHE_DIR" in makefile
    assert "uv build --wheel" in makefile
    assert "scripts/verify_wheel.py" in makefile
    assert "make check-wheel" in makefile
    assert "WHEEL_EXPECT=--expect-native" in makefile


def test_makefile_exposes_prebuilt_artifact_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-artifacts:" in makefile
    assert "Set SDIST=/path/to/xy.tar.gz" in makefile
    assert "Set WHEEL=/path/to/xy.whl" in makefile
    assert "scripts/verify_local.py --packaging" in makefile
    assert "--sdist" in makefile
    assert "--wheel" in makefile
    assert "$(WHEEL_EXPECT)" in makefile


def test_makefile_exposes_benchmark_report_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-benchmark-report:" in makefile
    assert "BENCHMARK_JSON ?= benchmark.json" in makefile
    assert "BENCHMARK_KIND ?= auto" in makefile
    assert "scripts/verify_benchmark_report.py" in makefile
    assert "--kind" in makefile
    assert "make check-benchmark-report" in makefile
    assert "kernel-native" in makefile


def test_makefile_exposes_benchmark_harness_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-benchmark-harness:" in makefile
    assert "scripts/verify_local.py --only benchmark_harness" in makefile
    assert "make check-benchmark-harness" in makefile
    assert "benchmark metadata/report/regression tests" in makefile


def test_makefile_exposes_example_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-examples:" in makefile
    assert "scripts/verify_local.py --only examples" in makefile
    assert "make check-examples" in makefile


def test_makefile_exposes_docs_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-docs:" in makefile
    assert "scripts/verify_local.py --only examples,claim_guardrails" in makefile
    assert "make check-docs" in makefile
    assert "docs examples and public claim guardrails" in makefile


def test_makefile_exposes_security_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-security:" in makefile
    assert "scripts/verify_local.py --only security_export" in makefile
    assert "make check-security" in makefile
    assert "standalone HTML safety" in makefile


def test_makefile_exposes_error_safety_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-errors:" in makefile
    assert "scripts/verify_local.py --only error_safety" in makefile
    assert "make check-errors" in makefile
    assert "public error, LOD, and mutation-safety tests" in makefile


def test_makefile_exposes_api_surface_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-api:" in makefile
    assert "scripts/verify_local.py --only public_api,api_surface" in makefile
    assert "make check-api" in makefile
    assert "lazy public API and type-surface checks" in makefile


def test_makefile_exposes_import_budget_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-import:" in makefile
    assert "scripts/verify_local.py --only public_api,import_budget" in makefile
    assert "make check-import" in makefile
    assert "import-time and dependency-boundary checks" in makefile


def test_makefile_exposes_ci_workflow_verification_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-ci:" in makefile
    assert "scripts/verify_local.py --only ci_workflow" in makefile
    assert "make check-ci" in makefile
    assert "CI/release workflow invariant checks" in makefile


def test_makefile_exposes_claim_guardrail_shortcut() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "check-claims:" in makefile
    assert "scripts/verify_local.py --only claim_guardrails" in makefile
    assert "make check-claims" in makefile
    assert "public performance-claim guardrails" in makefile


def test_contributor_docs_name_full_gate_toolchain_requirements() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "Node 18+" in text
        assert "cargo" in text
        assert "rustc" in text
        assert "rustup component add clippy" in text


def test_docs_name_example_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-examples" in text
    assert "spec/api/api-examples.md" in contributing
    assert "Reflex example" in contributing


def test_docs_name_docs_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    production_inline = " ".join(production.split())

    for text in (contributing, production, readme):
        assert "make check-docs" in text
    assert "README/API prose" in contributing
    assert "public benchmark wording" in production_inline
    assert "README/API prose" in readme


def test_docs_name_security_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-security" in text
    assert "standalone HTML export" in contributing
    assert "browser client DOM" in production
    assert "browser client text" in readme


def test_docs_name_error_safety_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-errors" in text
    assert "builder rollback behavior" in contributing
    assert "LOD/drill mutation boundaries" in contributing
    assert "chart/widget caching" in production
    assert "LOD/drill mutation boundaries" in production
    assert "public errors" in readme
    assert "LOD/drill mutation boundaries" in readme


def test_docs_name_api_surface_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_inline = " ".join(readme.split())

    for text in (contributing, production, readme):
        assert "make check-api" in text
    assert "public export" in contributing
    assert "lazy import mappings" in production
    assert "public annotations" in readme_inline


def test_docs_name_import_budget_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-import" in text
        assert "lazy import" in text
        assert "dependency boundaries" in text
    assert "xy.__init__" in contributing
    assert "widget/export boundaries" in readme
    assert "backend import boundaries" in production


def test_docs_name_ci_workflow_verification_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-ci" in text
    assert ".github/workflows/ci.yml" in contributing
    assert "trusted publishing" in production
    assert "benchmark artifact wiring" in readme


def test_docs_name_claim_guardrail_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-claims" in text
    assert "public performance claim" in contributing
    assert "performance-claim surfaces" in production
    assert "public-facing text" in readme


def test_docs_name_benchmark_harness_shortcut() -> None:
    contributing = (SPEC_DOCS / "process" / "contributing.md").read_text(encoding="utf-8")
    production = (SPEC_DOCS / "process" / "production-readiness.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for text in (contributing, production, readme):
        assert "make check-benchmark-harness" in text
    assert "benchmark environment metadata" in contributing
    assert "report-schema validation" in production
    assert "regression comparison scripts" in readme


def test_node_version_parser_accepts_v_prefixed_versions() -> None:
    assert verify_local._node_major("v18.19.1\n") == 18
    assert verify_local._node_major("20.11.0") == 20
    assert verify_local._node_major("not-node") is None


def test_js_bundle_requires_node_18_or_newer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_local.shutil,
        "which",
        lambda exe: f"/mock/bin/{exe}" if exe == "node" else None,
    )

    def fake_probe(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        assert command == ("node", "--version")
        return subprocess.CompletedProcess(command, 0, stdout="v16.20.2\n", stderr="")

    monkeypatch.setattr(verify_local, "_run_probe", fake_probe)
    check = verify_local._base_checks()["js_bundle"]

    reasons = verify_local.missing_reasons(check)

    assert any("Node 18+ required" in reason and "v16.20.2" in reason for reason in reasons)
    assert any("quick non-JS gate" in reason for reason in reasons)


def test_js_bundle_reports_unparseable_node_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_local.shutil,
        "which",
        lambda exe: f"/mock/bin/{exe}" if exe == "node" else None,
    )

    def fake_probe(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        assert command == ("node", "--version")
        return subprocess.CompletedProcess(command, 0, stdout="node-ish\n", stderr="")

    monkeypatch.setattr(verify_local, "_run_probe", fake_probe)
    check = verify_local._base_checks()["js_bundle"]

    reasons = verify_local.missing_reasons(check)

    assert any(
        "cannot determine Node version" in reason and "node-ish" in reason for reason in reasons
    )
    assert any("Node 18+" in reason for reason in reasons)


def test_rust_checks_require_cargo_and_rustc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_local.shutil,
        "which",
        lambda exe: "/mock/bin/cargo" if exe == "cargo" else None,
    )
    check = verify_local._base_checks()["rust_test"]

    reasons = verify_local.missing_reasons(check)

    assert any("missing executable 'rustc'" in reason for reason in reasons)
    assert any("cargo` and `rustc`" in reason for reason in reasons)


def test_rust_clippy_check_reports_missing_component(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_local.shutil, "which", lambda exe: f"/mock/bin/{exe}")

    def fake_probe(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if command == ("cargo", "clippy", "--version"):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="no such command: clippy\n",
            )
        return subprocess.CompletedProcess(command, 0, stdout=f"{command[0]} 1.0.0\n", stderr="")

    monkeypatch.setattr(verify_local, "_run_probe", fake_probe)
    check = verify_local._base_checks()["rust_clippy"]

    reasons = verify_local.missing_reasons(check)

    assert any("Rust clippy is unavailable" in reason for reason in reasons)
    assert any("rustup component add clippy" in reason for reason in reasons)
