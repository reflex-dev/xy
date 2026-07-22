from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

# Actions are pinned to full commit SHAs (`@<40-hex> # vX`) per the org policy,
# so fixtures strip a step by its action *path*, not a version tag — a SHA bump
# must not silently turn these negative tests into no-ops.
_UPLOAD_ARTIFACT_USES = re.compile(r" *- uses: actions/upload-artifact@\S+.*\n")
_NODE24_ACTION_PINS = {
    "actions/cache": "55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "actions/setup-node": "820762786026740c76f36085b0efc47a31fe5020",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "astral-sh/setup-uv": "11f9893b081a58869d3b5fccaea48c9e9e46f990",
}


def _load_verify_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_ci_workflow.py"
    spec = importlib.util.spec_from_file_location("verify_ci_workflow", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_ci_workflow = _load_verify_module()


def test_ci_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_workflow() == []
    assert verify_ci_workflow.validate_ci_workflow() == []


def test_ci_workflow_rejects_path_filtered_required_result(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "  pull_request:\n", "  pull_request:\n    paths-ignore:\n      - 'spec/**'\n"
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("must run on every path" in error for error in errors)


def test_ci_workflow_rejects_required_aggregate_without_always(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("    if: always()\n    needs:\n", "    needs:\n", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("required_ci" in error and "if: always()" in error for error in errors)


def test_ci_workflow_rejects_required_aggregate_missing_hard_job(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("      - rust_release\n      - sdist\n", "      - rust_release\n"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("required_ci needs" in error and "sdist" in error for error in errors)


def test_ci_workflow_rejects_reflex_lane_outside_required_aggregate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("      - reflex_adapter\n", "", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("required_ci needs" in error and "reflex_adapter" in error for error in errors)


def test_ci_workflow_rejects_dependency_audit_outside_required_aggregate(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("      - dependency_audit\n", "", 1), encoding="utf-8")
    errors = verify_ci_workflow.validate_ci_workflow(path)
    assert any("required_ci needs" in error and "dependency_audit" in error for error in errors)


def test_ci_workflow_rejects_unpinned_dependency_scanner(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "15314940c10d26af9c6649f150b8a47c1262e8fc7e17b1d1029b0e479e8ed8a0",
            "0" * 64,
            1,
        ),
        encoding="utf-8",
    )
    errors = verify_ci_workflow.validate_ci_workflow(path)
    assert any(
        "dependency_audit" in error and "pinned multi-ecosystem" in error for error in errors
    )


def test_ci_workflow_rejects_advisory_dependency_audit(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "    timeout-minutes: 15\n    steps:\n",
            "    timeout-minutes: 15\n    continue-on-error: true\n    steps:\n",
            1,
        ),
        encoding="utf-8",
    )
    errors = verify_ci_workflow.validate_ci_workflow(path)
    assert any("dependency_audit must be a hard gate" in error for error in errors)


def test_ci_workflow_rejects_missing_locked_release_rust_suite(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Run locked release-profile suite\n"
            "        run: cargo test --locked --release\n",
            "      - name: Run locked release-profile suite\n        run: cargo test --release\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "rust_release" in error and "cargo test --locked --release" in error for error in errors
    )


def test_ci_workflow_rejects_missing_release_only_regression_inventory(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          grep -Fqx \\\n"
            "            'tiles::tests::compose_window_astronomically_past_domain_is_empty_not_panic: test' \\\n"
            "            release-tests.txt\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("rust_release" in error and "release-only regression" in error for error in errors)


def test_ci_workflow_rejects_release_rust_job_outside_required_aggregate(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("      - rust_release\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("required_ci needs" in error and "rust_release" in error for error in errors)


def test_ci_workflow_rejects_incomplete_native_parity_matrix(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          - os: macos-14\n            arch: aarch64\n            default: aarch64\n",
            "",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("native_parity matrix" in error for error in errors)


def test_ci_workflow_rejects_native_parity_outside_required_aggregate(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("      - native_parity\n", "", 1), encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("required_ci needs" in error and "native_parity" in error for error in errors)


def test_ci_workflow_requires_failure_retained_native_parity_report(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Retain native parity report\n        if: always()\n",
            "      - name: Retain native parity report\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("native_parity" in error and "if: always()" in error for error in errors)


def test_ci_workflow_rejects_conditioned_release_test_inventory(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Inventory release-only regression coverage\n",
            "      - name: Inventory release-only regression coverage\n"
            "        if: github.event_name == 'workflow_dispatch'\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "rust_release step" in error and "must be unconditional" in error for error in errors
    )


def test_ci_workflow_rejects_missing_release_test_inventory_artifact(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("          name: rust-release-test-inventory\n", ""),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "rust_release" in error and "rust-release-test-inventory" in error for error in errors
    )


def test_ci_workflow_rejects_invalid_embedded_python_indentation(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          else:\n              raise SystemExit("expected ImportError without the native core")\n',
            '          else:\n            raise SystemExit("expected ImportError without the native core")\n',
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("invalid Python heredoc" in error for error in errors)


def test_reference_gate_commands_must_be_in_the_named_step(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    command = "          .venv/bin/pytest -q tests/pyplot/test_reference_semantics.py\n"
    # Leaving the old verifier's needle elsewhere in the job must not satisfy
    # the structural step-local check.
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(command, "") + f"\n# {command.strip()}\n", encoding="utf-8")
    errors = verify_ci_workflow.validate_ci_workflow(path)
    assert any("reference test commands" in error for error in errors)


def test_codspeed_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_codspeed_workflow() == []


def test_all_workflows_accept_current_gates() -> None:
    assert verify_ci_workflow.validate_all_workflows() == []


def test_workflows_use_consistent_node24_action_pins() -> None:
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path(".github/workflows").glob("*.yml"))
    )

    for action, sha in _NODE24_ACTION_PINS.items():
        uses_lines = [line for line in workflow_text.splitlines() if f"uses: {action}@" in line]
        assert uses_lines, f"expected at least one {action} use"
        assert all(f"uses: {action}@{sha}" in line for line in uses_lines), uses_lines


def test_setup_uv_cache_is_only_enabled_intentionally() -> None:
    for path in sorted(Path(".github/workflows").glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "uses: astral-sh/setup-uv@" not in line:
                continue
            step_indent = len(line) - len(line.lstrip())
            boundary_indent = step_indent - 2 if line.lstrip().startswith("uses:") else step_indent
            block: list[str] = []
            for following in lines[index + 1 :]:
                indent = len(following) - len(following.lstrip())
                if following.strip() and indent <= boundary_indent:
                    break
                block.append(following)
            setting = "\n".join(block)
            assert "enable-cache:" in setting, f"{path}:{index + 1} relies on auto cache mode"


def test_ci_workflow_rejects_blocking_benchmark_job(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("    continue-on-error: true\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "continue-on-error" in error for error in errors)


def test_ci_workflow_rejects_regrouped_expensive_cross_library_adapters(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("          - name: plotly-svg\n", "", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("benchmark_vs" in error and "plotly-svg" in error for error in errors)


def test_ci_workflow_rejects_substring_preserving_adapter_regrouping(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "            libraries: plotly_svg\n",
            "            libraries: plotly_svg,bokeh_canvas\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "matrix entry 'plotly-svg'" in error
        and "must exactly equal" in error
        and "plotly_svg,bokeh_canvas" in error
        for error in errors
    )


def test_ci_workflow_rejects_unconditional_cross_library_browser_setup(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Install Chromium (Playwright)\n        if: matrix.browser\n",
            "      - name: Install Chromium (Playwright)\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "Install Chromium (Playwright)" in error and "matrix.browser" in error for error in errors
    )


def test_ci_workflow_rejects_unconditional_cross_library_native_build(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Build native core\n        if: matrix.xy\n",
            "      - name: Build native core\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Build native core" in error and "matrix.xy" in error for error in errors)


def test_ci_workflow_rejects_missing_cross_library_job_timeout(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("    timeout-minutes: 10\n", "", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("benchmark_vs" in error and "timeout-minutes: 10" in error for error in errors)


def test_ci_workflow_rejects_unlocked_competitor_install(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "            --constraint benchmarks/requirements-ci.lock ${{ matrix.packages }}\n",
            "            ${{ matrix.packages }}\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "Install selected competitors" in error and "requirements-ci.lock" in error
        for error in errors
    )


def test_ci_workflow_rejects_benchmark_upload_that_skips_after_failures(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("        if: always()\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "if: always()" in error for error in errors)


def test_ci_workflow_rejects_benchmark_upload_that_fails_on_missing_report(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("          if-no-files-found: warn\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "if-no-files-found" in error for error in errors)


def test_ci_workflow_rejects_missing_line_benchmark_verification(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          .venv/bin/python scripts/verify_benchmark_report.py line.json --kind line-decimation\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "line-decimation" in error for error in errors)


def test_ci_workflow_rejects_missing_install_benchmark_verification(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          .venv/bin/python scripts/verify_benchmark_report.py install.json --kind install-footprint\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "install-footprint" in error for error in errors)


def test_ci_workflow_rejects_benchmark_job_without_native_backend_assertion(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Verify native benchmark backend\n"
        "        run: |\n"
        "          .venv/bin/python - <<'PY'\n"
        "          import xy.kernels as k\n"
        '          assert k.BACKEND == "native", f"benchmark job requires native backend, got {k.BACKEND!r}"\n'
        "          PY\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "native backend" in error for error in errors)


def test_ci_workflow_rejects_benchmark_job_without_required_native_install(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '        env:\n          XY_REQUIRE_CARGO: "1"\n'
            "        run: |\n          uv venv .venv\n"
            "          uv pip install -p .venv/bin/python \\\n"
            "            --constraint benchmarks/requirements-ci.lock -e .\n",
            "        run: |\n          uv venv .venv\n"
            "          uv pip install -p .venv/bin/python \\\n"
            "            --constraint benchmarks/requirements-ci.lock -e .\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("benchmark" in error and "XY_REQUIRE_CARGO" in error for error in errors)


def test_codspeed_workflow_rejects_missing_native_backend_assertion(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/codspeed.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Verify native benchmark backend\n"
        "        run: |\n"
        "          .venv/bin/python - <<'PY'\n"
        "          import xy.kernels as k\n"
        '          assert k.BACKEND == "native", f"CodSpeed requires native backend, got {k.BACKEND!r}"\n'
        "          PY\n\n"
    )
    path = tmp_path / "codspeed.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_codspeed_workflow(path)

    assert any("CodSpeed benchmarks job" in error and "native backend" in error for error in errors)


def test_codspeed_workflow_rejects_non_strict_native_install(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/codspeed.yml").read_text(encoding="utf-8")
    path = tmp_path / "codspeed.yml"
    path.write_text(
        workflow.replace(
            '        env:\n          XY_REQUIRE_CARGO: "1"\n'
            "        run: |\n          uv venv .venv\n"
            '          uv pip install -p .venv/bin/python -e ".[dev,codspeed]"\n',
            "        run: |\n          uv venv .venv\n"
            '          uv pip install -p .venv/bin/python -e ".[dev]"\n',
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_codspeed_workflow(path)

    assert any(
        "CodSpeed benchmarks job" in error and "XY_REQUIRE_CARGO" in error for error in errors
    )


def test_ci_workflow_rejects_missing_claim_guardrail_gate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Claim guardrails\n"
            "        run: .venv/bin/python scripts/check_claim_guardrails.py\n\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "check_claim_guardrails" in error for error in errors)


def test_ci_workflow_rejects_missing_interaction_stress_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/interaction_stress_smoke.py "$CHROME" \\\n'
            "            --json interaction-worker-evidence.json\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "interaction_stress_smoke" in error for error in errors)


def test_ci_workflow_rejects_optional_interaction_worker(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "            --json interaction-worker-evidence.json\n",
            "            --json interaction-worker-evidence.json --allow-worker-skip\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("must not allow worker skips" in error for error in errors)


def test_ci_workflow_rejects_missing_interaction_worker_evidence_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Upload interaction worker evidence\n"
        "        if: always()\n"
        "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1\n"
        "        with:\n"
        "          name: interaction-worker-evidence\n"
        "          if-no-files-found: error\n"
        "          path: interaction-worker-evidence.json\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("Upload interaction worker evidence" in error for error in errors)


def test_ci_workflow_rejects_missing_animation_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/animation_smoke.py "$CHROME" \\\n'
            "            --evidence animation-browser-evidence.json\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("Animation smoke" in error and "animation_smoke.py" in error for error in errors)


def test_ci_workflow_rejects_missing_runtime_security_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/runtime_security_smoke.py "$CHROME" --no-sandbox \\\n'
            "            --evidence runtime-security-evidence.json\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any(
        "Runtime standalone security smoke" in error and "runtime_security_smoke.py" in error
        for error in errors
    )


def test_ci_workflow_rejects_missing_runtime_security_evidence_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Upload runtime security evidence\n"
        "        if: always()\n"
        "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1\n"
        "        with:\n"
        "          name: runtime-security-evidence\n"
        "          if-no-files-found: error\n"
        "          path: runtime-security-evidence.json\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("Upload runtime security evidence" in error for error in errors)


def test_ci_workflow_rejects_missing_animation_evidence_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Upload animation browser evidence\n"
        "        if: always()\n"
        "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1\n"
        "        with:\n"
        "          name: animation-browser-evidence\n"
        "          if-no-files-found: error\n"
        "          path: animation-browser-evidence.json\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("Upload animation browser evidence" in error for error in errors)


def test_ci_workflow_rejects_missing_pick_boundary_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/pick_boundary_smoke.py "$CHROME" \\\n'
            "            --evidence pick-boundary-evidence.json\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any(
        "Pick boundary smoke" in error and "pick_boundary_smoke.py" in error for error in errors
    )


def test_ci_workflow_rejects_missing_pick_boundary_evidence_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Upload pick boundary evidence\n"
        "        if: always()\n"
        "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1\n"
        "        with:\n"
        "          name: pick-boundary-evidence\n"
        "          if-no-files-found: error\n"
        "          path: pick-boundary-evidence.json\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("Upload pick boundary evidence" in error for error in errors)


def test_ci_workflow_rejects_missing_dashboard_reliability_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Browser dashboard reliability smoke (Chromium)\n"
        "        run: |\n"
        "          CHROME=$(node -e \"console.log(require('playwright').chromium.executablePath())\")\n"
        "          .venv/bin/python benchmarks/bench_dashboard.py \\\n"
        '            --chart-counts 10,20,50 --chromium "$CHROME" --json dashboard-smoke.json\n'
        "          .venv/bin/python scripts/verify_benchmark_report.py \\\n"
        "            dashboard-smoke.json --kind dashboard-browser --profile strict\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "dashboard reliability" in error for error in errors)


def test_ci_workflow_rejects_non_strict_dashboard_reliability_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "dashboard-smoke.json --kind dashboard-browser --profile strict",
            "dashboard-smoke.json --kind dashboard-browser",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "--profile strict" in error for error in errors)


def test_ci_workflow_rejects_missing_dashboard_failure_evidence(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Upload dashboard health evidence\n"
        "        if: always()\n"
        "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1\n"
        "        with:\n"
        "          name: dashboard-health-evidence\n"
        "          if-no-files-found: error\n"
        "          path: dashboard-smoke.json\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "dashboard-health-evidence" in error for error in errors)


def test_ci_workflow_rejects_missing_reflex_lifecycle_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/reflex_lifecycle_smoke.py "$CHROME"\n',
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "reflex_lifecycle_smoke" in error for error in errors)


def test_ci_workflow_rejects_missing_visual_health_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/visual_health_smoke.py "$CHROME"\n',
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "visual_health_smoke" in error for error in errors)


def test_ci_workflow_rejects_missing_reviewed_visual_baseline(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    command = (
        '          .venv/bin/python scripts/visual_baseline.py "$CHROME" \\\n'
        "            --baseline spec/visual-baselines/v1.json \\\n"
        "            --artifacts visual-baseline-artifacts \\\n"
        "            --evidence visual-baseline-evidence.json\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(command, ""), encoding="utf-8")
    errors = verify_ci_workflow.validate_workflow(path)
    assert any(
        "Reviewed visual baseline" in error and "visual_baseline.py" in error for error in errors
    )


def test_ci_workflow_rejects_visual_baseline_update_mode(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "            --evidence visual-baseline-evidence.json\n",
            "            --evidence visual-baseline-evidence.json --update-baselines\n",
            1,
        ),
        encoding="utf-8",
    )
    errors = verify_ci_workflow.validate_workflow(path)
    assert any("must never update reviewed baselines" in error for error in errors)


def test_ci_workflow_rejects_missing_visual_baseline_evidence_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Upload visual baseline evidence\n",
            "      - name: Removed visual baseline evidence\n",
            1,
        ),
        encoding="utf-8",
    )
    errors = verify_ci_workflow.validate_workflow(path)
    assert any("Upload visual baseline evidence" in error for error in errors)


def test_ci_workflow_rejects_missing_cross_browser_conformance(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace(
            '        run: xvfb-run --auto-servernum --server-args="-screen 0 1280x720x24" '
            "node scripts/browser_conformance.mjs\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("browser_conformance" in error and "conformance gate" in error for error in errors)


def test_ci_workflow_rejects_missing_reflex_adapter_browser_gate(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace(
            "          ../../.venv/bin/python ../../scripts/reflex_ws_smoke.py \\\n"
            '            --frontend http://localhost:3100 --chromium "$CHROME" \\\n'
            "            --screenshot reflex-e2e.png\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("reflex_adapter" in error and "reflex_ws_smoke.py" in error for error in errors)


def test_ci_workflow_rejects_reflex_adapter_without_screenshot_evidence(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace(" \\\n            --screenshot reflex-e2e.png\n", "\n", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("browser evidence capture" in error and "--screenshot" in error for error in errors)


def test_ci_workflow_rejects_reflex_evidence_upload_that_skips_failures(
    tmp_path: Path,
) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    marker = "      - name: Upload Reflex E2E evidence\n        if: always()\n"
    path.write_text(
        text.replace(marker, "      - name: Upload Reflex E2E evidence\n", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "failure-safe browser evidence upload" in error and "if: always()" in error
        for error in errors
    )


def test_ci_workflow_rejects_soft_reflex_adapter_gate(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace(
            "  reflex_adapter:\n    name:",
            "  reflex_adapter:\n    continue-on-error: true\n    name:",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("reflex_adapter job must be a hard gate" in error for error in errors)


def test_ci_workflow_rejects_root_owned_reflex_test_dependencies(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace(
            "          uv pip install -p .venv/bin/python -e .\n",
            '          uv pip install -p .venv/bin/python -e ".[dev]"\n',
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "python/reflex-xy[dev]" in error and "root xy dev extra" in error for error in errors
    )


def test_ci_workflow_rejects_adapter_tests_outside_package_boundary(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace("-q python/reflex-xy/tests\n", "-q tests/reflex_adapter\n", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("reflex_adapter" in error and "python/reflex-xy/tests" in error for error in errors)


def test_ci_workflow_rejects_missing_playwright_browser_cache(tmp_path: Path) -> None:
    text = verify_ci_workflow.DEFAULT_CI_WORKFLOW.read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        text.replace(
            "      - name: Cache Playwright browsers\n"
            "        uses: actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0\n"
            "        with:\n"
            "          path: ~/.cache/ms-playwright\n"
            "          key: playwright-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('package-lock.json') }}\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("browser_conformance" in error and "actions/cache" in error for error in errors)


def test_ci_workflow_rejects_missing_regression_gate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          python3 scripts/check_regressions.py --scatter scatter.json --kernel kernel.json \\\n"
            "            --transport transport.json --emit-md spec/benchmarks/metrics.md\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "check_regressions" in error for error in errors)


def test_ci_workflow_rejects_missing_transport_regression_probe(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          .venv/bin/python benchmarks/bench_transport.py --n 1e6 --reps 15 \\\n"
            '            --browser-reps 12 --chromium "$CHROME" --require-browser --json transport.json\n',
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "bench_transport" in error for error in errors)


def test_ci_workflow_rejects_missing_kernel_benchmark_verification(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "          python3 scripts/verify_benchmark_report.py kernel.json --kind kernel-native\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "kernel-native" in error for error in errors)


def test_ci_workflow_rejects_missing_regression_benchmark_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    # Strip the whole "Upload regression benchmark report" step (name line through
    # its trailing blank), independent of the pinned upload-artifact SHA.
    broken = re.sub(
        r" *- name: Upload regression benchmark report\n(?:[ \t]+.*\n|\n)*?(?=\S| *- |\Z)",
        "",
        workflow,
        count=1,
    )
    assert "regression-benchmark-report" not in broken
    path = tmp_path / "ci.yml"
    path.write_text(broken, encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "regression-benchmark-report" in error for error in errors)


def test_ci_workflow_rejects_regression_upload_that_skips_after_failures(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Upload regression benchmark report\n        if: always()\n",
            "      - name: Upload regression benchmark report\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any(
        "Upload regression benchmark report" in error and "if: always()" in error
        for error in errors
    )


def test_ci_workflow_rejects_missing_wheel_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(_UPLOAD_ARTIFACT_USES.sub("", workflow), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("wheels" in error and "upload-artifact" in error for error in errors)


def test_release_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_release_workflow() == []


def test_release_workflow_rejects_missing_native_wheel_verifier(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace('          python scripts/verify_wheel.py "$whl" --expect-native\n', ""),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release wheels job" in error and "verify_wheel" in error for error in errors)


def test_release_workflow_rejects_nonblocking_native_wheel_matrix(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "    runs-on: ${{ matrix.os }}\n",
            "    runs-on: ${{ matrix.os }}\n    continue-on-error: true\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("wheels job must block publishing" in error for error in errors)


def test_release_workflow_rejects_missing_native_artifact_runtime_probe(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "            python scripts/native_parity.py \\\n",
            "            python missing.py \\\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "Run musllinux wheel parity in musl 1.2" in error and "native_parity.py" in error
        for error in errors
    )


def test_release_workflow_requires_failure_retained_native_runtime_report(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "        if: always() && (matrix.runtime == 'manylinux' || "
            "matrix.runtime == 'musllinux')\n",
            "        if: matrix.runtime == 'manylinux' || matrix.runtime == 'musllinux'\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "Retain native artifact runtime report" in error and "always()" in error for error in errors
    )


def test_release_workflow_rejects_unpinned_pyodide_runtime_contract(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace('          RUSTFLAGS: "-C panic=abort"\n', "")
        .replace('          version: "4.0.9"\n', "")
        .replace("          npm i --no-save pyodide@0.29.4\n", ""),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "release wasm job" in error and "panic=abort" in error and "pyodide@0.29.4" in error
        for error in errors
    )


def test_release_workflow_rejects_nonblocking_pyodide_probe(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "  wasm:\n    name: Wheel Pyodide (runtime verified)\n"
            "    needs: qualify\n    runs-on: ubuntu-latest\n",
            "  wasm:\n    name: Wheel Pyodide (runtime verified)\n"
            "    needs: qualify\n    runs-on: ubuntu-latest\n"
            "    continue-on-error: true\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("wasm job must block publishing" in error for error in errors)


def test_release_workflow_rejects_pyodide_artifact_in_pypi_batch(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace("          name: pyodide-wheel\n", "          name: dist-pyodide\n"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release wasm job" in error and "pyodide-wheel" in error for error in errors)


def test_release_workflow_rejects_missing_pyodide_release_publisher(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace("  publish-pyodide:\n", "  publish-pyodide-removed:\n"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("missing required release job 'publish-pyodide'" in error for error in errors)


def test_release_workflow_rejects_missing_sdist_norust_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace('          XY_SKIP_CARGO: "1"\n', ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release sdist job" in error and "XY_SKIP_CARGO" in error for error in errors)


def test_release_workflow_rejects_missing_trusted_publishing(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace("      id-token: write", "      id-token-removed: write"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release publish job" in error and "id-token" in error for error in errors)


def test_release_workflow_rejects_pypi_token_publish(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "      id-token: write",
            "      id-token: write\n      api-token: ${{ secrets.PYPI_API_TOKEN }}",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("trusted publishing" in error and "token" in error for error in errors)


def test_release_workflow_rejects_missing_dry_run_input(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace("      dry_run:\n", "      dry_ran:\n"), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("dry-run input" in error for error in errors)


def test_release_workflow_rejects_ungated_pypi_publish_step(tmp_path: Path) -> None:
    """A sibling step's `if:` (the dry-run summary) must not mask a missing
    gate on the actual PyPI upload step — regression for a bug where the
    checker's own regex matched across step boundaries under re.DOTALL."""
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "        if: github.event_name != 'workflow_dispatch' "
            "|| github.event.inputs.dry_run != 'true'\n",
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("has no if: condition of its own" in error for error in errors)


def test_release_workflow_rejects_non_retryable_pypi_publish(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace("          skip-existing: true\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release publish job" in error and "skip-existing" in error for error in errors)


def test_release_workflow_rejects_missing_exact_source_metadata_gate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace("            args+=(--release-metadata)\n", ""), encoding="utf-8"
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release qualify job" in error and "--release-metadata" in error for error in errors)


def test_release_workflow_rejects_unbound_provenance_identity(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace('            --workflow-run-id "$GITHUB_RUN_ID" \\\n', "", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "release provenance job" in error and "--workflow-run-id" in error for error in errors
    )


def test_docs_dev_deploy_rejects_missing_exact_sha_preflight(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/deploy-docs-dev.yml").read_text(encoding="utf-8")
    path = tmp_path / "deploy-docs-dev.yml"
    path.write_text(
        workflow.replace("          python3 scripts/verify_source_qualification.py\n", ""),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_deploy_workflows(dev_path=path)

    assert any("docs dev deploy qualify job" in error for error in errors)


def test_docs_prod_deploy_rejects_mutable_artifact_promotion(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/deploy-docs-stg.yml").read_text(encoding="utf-8")
    path = tmp_path / "deploy-docs-stg.yml"
    path.write_text(
        workflow.replace(
            '          if [[ "$ACTUAL_FRONTEND" != "$EXPECTED_FRONTEND" ]]; then\n', ""
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_deploy_workflows(stg_path=path)

    assert any("verify-prod-artifacts" in error and "ACTUAL_FRONTEND" in error for error in errors)


def test_docs_image_build_rejects_disabled_provenance(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/_build-docs-images.yml").read_text(encoding="utf-8")
    path = tmp_path / "_build-docs-images.yml"
    path.write_text(
        workflow.replace("--provenance=mode=max", "--provenance=false", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_deploy_workflows(build_path=path)

    assert any("provenance" in error for error in errors)


def test_docs_helm_promotion_rejects_mutable_tags(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/_helm-docs-pr.yml").read_text(encoding="utf-8")
    path = tmp_path / "_helm-docs-pr.yml"
    path.write_text(
        workflow.replace(
            '          FRONTEND_REF="${IMAGE_TAG}@${FRONTEND_DIGEST}" \\\n',
            '          FRONTEND_REF="$IMAGE_TAG" \\\n',
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_deploy_workflows(helm_path=path)

    assert any("docs Helm promotion open-helm-pr job" in error for error in errors)
