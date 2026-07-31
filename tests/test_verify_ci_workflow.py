from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Actions are pinned to full commit SHAs (`@<40-hex> # vX`) per the org policy,
# so fixtures strip a step by its action *path*, not a version tag — a SHA bump
# must not silently turn these negative tests into no-ops.
_UPLOAD_ARTIFACT_USES = re.compile(r" *- uses: actions/upload-artifact@\S+.*\n")
_NODE24_ACTION_PINS = {
    "actions/attest": "508db95dd578ae2727ebd6217d5ba78e4fbda05d",
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


def test_named_step_run_stops_before_following_step_metadata() -> None:
    job = """\
  example:
    steps:
      - name: Guard
        env:
          VALUE: safe
        run: |
          echo "$VALUE"
          # ignored shell comment
        shell: echo "metadata is not shell"
        timeout-minutes: 5
"""

    assert verify_ci_workflow._named_step_run(job, "Guard") == 'echo "$VALUE"'


def test_ci_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_workflow() == []
    assert verify_ci_workflow.validate_ci_workflow() == []


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
            "          uv pip install -p .venv/bin/python -e . --group dev --group codspeed\n",
            "        run: |\n          uv venv .venv\n"
            "          uv pip install -p .venv/bin/python -e . --group dev\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_codspeed_workflow(path)

    assert any(
        "CodSpeed benchmarks job" in error and "XY_REQUIRE_CARGO" in error for error in errors
    )


def test_ci_workflow_rejects_missing_interaction_stress_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/interaction_stress_smoke.py "$CHROME"\n',
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "interaction_stress_smoke" in error for error in errors)


def test_ci_workflow_rejects_missing_dashboard_reliability_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    block = (
        "      - name: Browser dashboard reliability smoke (Chromium)\n"
        "        run: |\n"
        "          CHROME=$(node -e \"console.log(require('playwright').chromium.executablePath())\")\n"
        "          .venv/bin/python benchmarks/bench_dashboard.py \\\n"
        '            --chart-counts 10,20,50 --chromium "$CHROME" --json dashboard-smoke.json\n'
        "          .venv/bin/python scripts/verify_benchmark_report.py \\\n"
        "            dashboard-smoke.json --kind dashboard-browser\n\n"
    )
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(block, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "dashboard reliability" in error for error in errors)


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


def test_ci_workflow_rejects_missing_visual_regression_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            '          .venv/bin/python scripts/visual_regression_smoke.py "$CHROME"\n',
            "",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("test job" in error and "visual_regression_smoke" in error for error in errors)


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
    # Strip the whole step up to its next sibling, independent of the pinned
    # upload-artifact SHA. Explicit boundaries avoid regex backtracking on
    # adversarially long workflow text.
    step_start = workflow.index("      - name: Upload regression benchmark report\n")
    next_step = workflow.index("\n      - ", step_start)
    broken = workflow[:step_start] + workflow[next_step + 1 :]
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

    assert any("test job" in error and "if: always()" in error for error in errors)


def test_ci_workflow_rejects_missing_wheel_upload(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(_UPLOAD_ARTIFACT_USES.sub("", workflow), encoding="utf-8")

    errors = verify_ci_workflow.validate_workflow(path)

    assert any("wheels" in error and "upload-artifact" in error for error in errors)


def test_release_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_release_workflow() == []


@pytest.mark.parametrize(
    ("tag", "expected"),
    (
        ("v1.2.3", False),
        ("v1.2.3a1", True),
        ("v1.2.3b2", True),
        ("v1.2.3rc4", True),
        ("v1.2.3.post1", False),
        ("v1.2.3-rc1", False),
        ("v1.2.3rc1-extra", False),
        ("prefix-v1.2.3rc1", False),
    ),
)
def test_release_prerelease_classifier_is_canonical(tag: str, expected: bool) -> None:
    assert (
        re.fullmatch(verify_ci_workflow.CORE_PRERELEASE_TAG_PATTERN, tag) is not None
    ) is expected


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


def test_release_workflow_rejects_unpinned_pyodide_runtime_contract(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace('            RUSTFLAGS="-C panic=abort"\n', "")
        .replace("          CIBW_BUILD: cp314-pyodide_wasm32\n", "")
        .replace('          CIBW_PYODIDE_VERSION: "314.0.0"\n', "")
        .replace(
            "          CIBW_BEFORE_BUILD_PYODIDE: >-\n"
            "            cargo build --release --target wasm32-unknown-emscripten\n",
            "",
        )
        .replace(
            "        uses: pypa/cibuildwheel@294735312765b09d24a2fbec22660ce817587d55 # v4.1.0\n",
            "",
        )
        .replace("          npm i --no-save pyodide@314.0.0\n", ""),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "release wasm job" in error
        and "panic=abort" in error
        and "cibuildwheel" in error
        and "pyodide@314.0.0" in error
        for error in errors
    )


def test_release_workflow_rejects_nonblocking_pyodide_probe(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "    runs-on: ubuntu-latest\n",
            "    runs-on: ubuntu-latest\n    continue-on-error: true\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("wasm job must block publishing" in error for error in errors)


def test_release_workflow_rejects_broad_wasm_permissions(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "    permissions:\n      contents: read\n    steps:\n",
            "    steps:\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release wasm job" in error and "contents: read" in error for error in errors)


def test_release_workflow_rejects_pyemscripten_artifact_outside_pypi_batch(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            "          name: dist-pyemscripten\n", "          name: pyemscripten-wheel\n"
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release wasm job" in error and "dist-pyemscripten" in error for error in errors)


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

    assert any("is not gated by the dry-run predicate" in error for error in errors)


def test_release_workflow_rejects_non_retryable_pypi_publish(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace("          skip-existing: true\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release publish job" in error and "skip-existing" in error for error in errors)


def test_release_workflow_rejects_missing_github_release_job(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.split("\n  github-release:\n", 1)[0], encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("github-release" in error for error in errors)


def test_release_workflow_rejects_manual_github_release_creation(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    gate = "    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')\n"
    assert gate in workflow
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            gate,
            "    # if: github.event_name == 'push' && "
            "startsWith(github.ref, 'refs/tags/v')\n"
            "    if: always()\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "github-release job" in error and "active tag-only gate" in error for error in errors
    )


def test_release_workflow_rejects_unsafe_github_release_job(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace("      contents: write\n", "      contents: read\n", 1)
        .replace(" --clobber\n", "\n", 1)
        .replace(" --verify-tag ", " --no-verify-tag ", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("permissions must be exactly" in error and "contents" in error for error in errors)
    assert any("--clobber" in error and "--verify-tag" in error for error in errors)


def test_release_workflow_rejects_missing_github_release_artifact_guard(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    guard = """\
          shopt -s nullglob
          wheels=(dist/*.whl)
          sdists=(dist/*.tar.gz)
          artifacts=("${wheels[@]}" "${sdists[@]}")
          if (( ${#wheels[@]} == 0 || ${#sdists[@]} != 1 )); then
            echo "::error::Expected at least one wheel and exactly one sdist"
            exit 1
          fi

"""
    assert guard in workflow
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace(guard, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "github-release job" in error
        and "shopt -s nullglob" in error
        and "wheels=(dist/*.whl)" in error
        and "exactly one sdist" in error
        for error in errors
    )


def test_release_workflow_rejects_unvalidated_existing_github_release(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    final_view = """\
              gh release view "$TAG" \\
                --repo "$REPO" \\
                --json assets,body,isDraft,isImmutable,isPrerelease,name,publishedAt,tagName
"""
    assert workflow.count(final_view) == 2
    path = tmp_path / "release.yml"
    before, separator, after = workflow.rpartition(final_view)
    assert separator
    path.write_text(before + '              echo "validation removed"\n' + after, encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "github-release job" in error
        and ("after normalization" in error or "validate again" in error)
        for error in errors
    )


def test_release_workflow_rejects_extra_github_release_write_scope(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    permission = "      contents: write\n"
    assert permission in workflow
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            permission,
            permission + "      issues: write\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("permissions must be exactly" in error and "issues" in error for error in errors)


def test_release_workflow_rejects_removed_prerelease_classifier(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    classifier = f"""\
          if [[ "$TAG" =~ {verify_ci_workflow.CORE_PRERELEASE_TAG_PATTERN} ]]; then
            prerelease=(--prerelease)
            edit_prerelease=(--prerelease)
            expected_prerelease=true
          fi
"""
    assert classifier in workflow
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace(classifier, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert "--prerelease=false" in workflow
    assert any("classify canonical alpha/beta/RC tags" in error for error in errors)


def test_release_workflow_rejects_detached_release_artifacts(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    upload = (
        '            gh release upload "$TAG" "${artifacts[@]}" "$provenance_file" '
        '--repo "$REPO" --clobber\n'
    )
    create = (
        '          gh release create "$TAG" "${artifacts[@]}" "$provenance_file" '
        '--repo "$REPO" --verify-tag --title "$TAG" --notes-file "$notes_file" '
        '"${prerelease[@]}"\n'
    )
    assert upload in workflow
    assert create in workflow
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            upload,
            '            gh release upload "$TAG" "$provenance_file" --repo "$REPO" --clobber\n',
        ).replace(
            create,
            '          gh release create "$TAG" "$provenance_file" '
            '--repo "$REPO" --verify-tag --title "$TAG" '
            '--notes-file "$notes_file" "${prerelease[@]}"\n',
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("pass verified distributions and provenance directly" in error for error in errors)


def test_release_workflow_binds_clobber_to_artifact_upload(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    upload = (
        '            gh release upload "$TAG" "${artifacts[@]}" "$provenance_file" '
        '--repo "$REPO" --clobber\n'
    )
    assert upload in workflow
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            upload,
            '            gh release upload "$TAG" "${artifacts[@]}" "$provenance_file" '
            '--repo "$REPO"\n'
            '            unused_retry_flag="--clobber"\n',
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("pass verified distributions and provenance directly" in error for error in errors)


def test_release_workflow_rejects_missing_stale_asset_reconciliation(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    endpoint = '"repos/${REPO}/releases/assets/${asset_id}"'
    assert endpoint in workflow
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace(endpoint, '"stale asset deletion removed"'), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "prune stale assets by id" in error or "releases/assets/${asset_id}" in error
        for error in errors
    )


def test_release_workflow_rejects_missing_signed_provenance_footer(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    marker = "<!-- xy-release-provenance:v1:%s:sha256:%s -->"
    assert marker in workflow
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace(marker, "<!-- marker removed -->"), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("provenance preparation" in error and marker in error for error in errors)


def test_release_workflow_rejects_unattested_provenance(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    action = "        uses: actions/attest@508db95dd578ae2727ebd6217d5ba78e4fbda05d # v4.2.1\n"
    assert action in workflow
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(action, "        uses: example/untrusted-attest@v1\n"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("pinned actions/attest" in error for error in errors)


def test_release_workflow_rejects_non_failing_empty_notes_guard(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    guard = """\
          if [[ -z "${generated_notes//[[:space:]]/}" ]]; then
            echo "::error::GitHub generated empty release notes for ${TAG}"
            exit 1
          fi
"""
    assert guard in workflow
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace(
            guard,
            """\
          if [[ -z "${generated_notes//[[:space:]]/}" ]]; then
            echo "::error::GitHub generated empty release notes for ${TAG}"
            true
          fi
          unused_empty_notes_exit="exit 1"
""",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("provenance preparation" in error for error in errors)


def test_docs_deploy_workflow_accepts_release_contract() -> None:
    assert verify_ci_workflow.validate_docs_deploy_workflow() == []


def test_docs_deploy_rejects_existence_only_release_gate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/deploy-docs-stg.yml").read_text(encoding="utf-8")
    fields = "--json assets,body,isDraft,isPrerelease,name,publishedAt,tagName"
    assert fields in workflow
    path = tmp_path / "deploy-docs-stg.yml"
    path.write_text(workflow.replace(fields, "--json name"), encoding="utf-8")

    errors = verify_ci_workflow.validate_docs_deploy_workflow(path)

    assert any("expected non-draft metadata" in error and fields in error for error in errors)


def test_docs_deploy_rejects_asset_set_check_removal(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/deploy-docs-stg.yml").read_text(encoding="utf-8")
    comparison = '                     [[ "$github_hashes_json" == "$manifest_hashes_json" &&\n'
    assert comparison in workflow
    path = tmp_path / "deploy-docs-stg.yml"
    path.write_text(
        workflow.replace(comparison, "                     [[ true == true &&\n"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_docs_deploy_workflow(path)

    assert any("exact asset hashes" in error for error in errors)


def test_docs_deploy_rejects_yanked_file_guard_removal(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/deploy-docs-stg.yml").read_text(encoding="utf-8")
    guard = "                 all(.urls[]; .yanked == false) and\n"
    assert guard in workflow
    path = tmp_path / "deploy-docs-stg.yml"
    path.write_text(workflow.replace(guard, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_docs_deploy_workflow(path)

    assert any("non-yanked PyPI files" in error for error in errors)


def test_docs_deploy_rejects_bypassed_production_release_gate(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/deploy-docs-stg.yml").read_text(encoding="utf-8")
    dependency = "    needs: [prepare, await-prod-approval, verify-library-release]\n"
    assert dependency in workflow
    path = tmp_path / "deploy-docs-stg.yml"
    path.write_text(
        workflow.replace(
            dependency,
            "    needs: [prepare, await-prod-approval]\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_docs_deploy_workflow(path)

    assert any("production Helm promotion" in error for error in errors)


@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="release workflow runtime simulation requires bash and jq",
)
def test_release_workflow_reconciles_stale_assets_before_publishing(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    job = verify_ci_workflow._job_blocks(workflow)["github-release"]
    release_shell = verify_ci_workflow._named_step_run(
        job,
        "Create GitHub Release and attach distributions",
    )
    assert release_shell is not None

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        r"""#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$GH_LOG"
state="$(<"$GH_STATE")"
if [[ "$1" == "api" && "$*" == *"/generate-notes"* ]]; then
  printf '## Changes\n\n- Generated\n'
elif [[ "$1" == "api" && "$*" == *"/releases/assets/"* ]]; then
  [[ "$*" == *"/releases/assets/9003"* ]]
  printf 'deleted' > "$GH_STATE"
elif [[ "$1" == "release" && "$2" == "upload" ]]; then
  [[ "$state" == "initial" ]]
  printf 'uploaded' > "$GH_STATE"
elif [[ "$1" == "release" && "$2" == "edit" ]]; then
  [[ "$state" == "deleted" ]]
  printf 'edited' > "$GH_STATE"
elif [[ "$1" == "release" && "$2" == "view" ]]; then
  if [[ "$state" == "edited" ]]; then
    printf '%s\n' '{"assets":[{"name":"xy-1.2.3-py3-none-any.whl","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9001"},{"name":"xy-1.2.3.tar.gz","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9002"},{"name":"checksums.txt","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9004"}],"body":"## Changes\n\n- Generated\n\n<!-- xy-release-workflow:v1.2.3 -->","isDraft":false,"isImmutable":false,"isPrerelease":false,"name":"v1.2.3","publishedAt":"2026-07-31T00:00:00Z","tagName":"v1.2.3"}'
  else
    printf '%s\n' '{"assets":[{"name":"xy-1.2.3-py3-none-any.whl","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9001"},{"name":"xy-1.2.3.tar.gz","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9002"},{"name":"stale.whl","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9003"},{"name":"checksums.txt","apiUrl":"https://api.github.com/repos/reflex-dev/xy/releases/assets/9004"}],"body":"manual","isDraft":true,"isImmutable":false,"isPrerelease":false,"name":"manual","publishedAt":null,"tagName":"v1.2.3"}'
  fi
else
  printf 'unexpected gh invocation: %s\n' "$*" >&2
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "xy-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "dist" / "xy-1.2.3.tar.gz").write_bytes(b"sdist")
    state = tmp_path / "state"
    state.write_text("initial", encoding="utf-8")
    log = tmp_path / "gh.log"
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_STATE": str(state),
        "GH_TOKEN": "test",
        "REPO": "reflex-dev/xy",
        "RUNNER_TEMP": str(runner_temp),
        "TAG": "v1.2.3",
    }

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", release_shell],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    calls = log.read_text(encoding="utf-8")
    assert "release upload v1.2.3 dist/xy-1.2.3-py3-none-any.whl dist/xy-1.2.3.tar.gz" in calls
    assert "api --method DELETE repos/reflex-dev/xy/releases/assets/9003" in calls
    assert "releases/assets/9004" not in calls
    assert "release edit v1.2.3" in calls
    assert state.read_text(encoding="utf-8") == "edited"


@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="release workflow runtime simulation requires bash and jq",
)
def test_release_workflow_never_mutates_mismatched_immutable_release(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    release_shell = verify_ci_workflow._named_step_run(
        verify_ci_workflow._job_blocks(workflow)["github-release"],
        "Create GitHub Release and attach distributions",
    )
    assert release_shell is not None

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        r"""#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$GH_LOG"
if [[ "$1" == "api" && "$*" == *"/generate-notes"* ]]; then
  printf '## Changes\n\n- Generated\n'
elif [[ "$1" == "release" && "$2" == "view" ]]; then
  printf '%s\n' '{"assets":[{"name":"xy-1.2.3-py3-none-any.whl"},{"name":"xy-1.2.3.tar.gz"}],"body":"manual notes","isDraft":false,"isImmutable":true,"isPrerelease":false,"name":"v1.2.3","publishedAt":"2026-07-31T00:00:00Z","tagName":"v1.2.3"}'
else
  printf 'mutation attempted: %s\n' "$*" >&2
  exit 98
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "xy-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "dist" / "xy-1.2.3.tar.gz").write_bytes(b"sdist")
    log = tmp_path / "gh.log"
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_TOKEN": "test",
        "REPO": "reflex-dev/xy",
        "RUNNER_TEMP": str(runner_temp),
        "TAG": "v1.2.3",
    }

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", release_shell],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1
    assert "immutable but does not match" in result.stdout
    calls = log.read_text(encoding="utf-8")
    assert "release upload" not in calls
    assert "release edit" not in calls
    assert "/releases/assets/" not in calls
    assert "release create" not in calls


@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None,
    reason="docs promotion runtime simulation requires bash and jq",
)
def test_docs_promotion_accepts_only_matching_ready_distribution_set(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/deploy-docs-stg.yml").read_text(encoding="utf-8")
    gate_shell = verify_ci_workflow._named_step_run(
        verify_ci_workflow._job_blocks(workflow)["verify-library-release"],
        "Await GitHub Release and PyPI availability",
    )
    assert gate_shell is not None

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        r"""#!/usr/bin/env bash
set -eu
printf '%s\n' '{"assets":[{"name":"xy-1.2.3-py3-none-any.whl"},{"name":"xy-1.2.3.tar.gz"},{"name":"checksums.txt"}],"body":"## Changes\n\n<!-- xy-release-workflow:v1.2.3 -->","isDraft":false,"isPrerelease":false,"name":"v1.2.3","publishedAt":"2026-07-31T00:00:00Z","tagName":"v1.2.3"}'
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        r"""#!/usr/bin/env bash
set -eu
printf '%s\n' '{"urls":[{"filename":"xy-1.2.3.tar.gz"},{"filename":"xy-1.2.3-py3-none-any.whl"}]}'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    fake_sleep.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "test",
        "REPO": "reflex-dev/xy",
        "VERSION": "v1.2.3",
    }

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", gate_shell],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "v1.2.3 is on GitHub Releases and PyPI" in result.stdout


def test_release_workflow_rejects_shallow_checkout(tmp_path: Path) -> None:
    """A depth-1 checkout fetches no tags, and the version is derived from them.

    That failure is silent — the build succeeds at the 0.0.0 fallback and
    publishes it — so the checker has to catch it instead of the release.
    """
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace("          fetch-depth: 0\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("fetch-depth: 0" in error and "0.0.0" in error for error in errors)


def test_ci_workflow_rejects_shallow_checkout(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace("          fetch-depth: 0\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("fetch-depth: 0" in error for error in errors)


def test_reflex_xy_release_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_reflex_xy_release_workflow() == []


def test_reflex_xy_release_workflow_rejects_ungated_pypi_publish(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release-reflex-xy.yml").read_text(encoding="utf-8")
    path = tmp_path / "release-reflex-xy.yml"
    gate = (
        "        if: github.event_name != 'workflow_dispatch' "
        "|| github.event.inputs.dry_run != 'true'\n"
    )
    assert gate in workflow
    path.write_text(workflow.replace(gate, ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_reflex_xy_release_workflow(path)

    assert any("is not gated by the dry-run predicate" in error for error in errors)


def test_reflex_xy_release_workflow_rejects_missing_dist_verifier(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release-reflex-xy.yml").read_text(encoding="utf-8")
    path = tmp_path / "release-reflex-xy.yml"
    stripped = "\n".join(
        line for line in workflow.splitlines() if "scripts/verify_reflex_xy_dist.py" not in line
    )
    path.write_text(stripped + "\n", encoding="utf-8")

    errors = verify_ci_workflow.validate_reflex_xy_release_workflow(path)

    assert any(
        "reflex-xy release build job" in error and "verify_reflex_xy_dist" in error
        for error in errors
    )


def test_reflex_xy_release_workflow_rejects_core_tag_trigger(tmp_path: Path) -> None:
    # The adapter workflow firing on bare `v*` tags would publish reflex-xy on
    # every xy core release; the namespaces must stay disjoint.
    workflow = Path(".github/workflows/release-reflex-xy.yml").read_text(encoding="utf-8")
    path = tmp_path / "release-reflex-xy.yml"
    path.write_text(
        workflow.replace('    tags: ["reflex-xy-v*"]\n', '    tags: ["v*"]\n'),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_reflex_xy_release_workflow(path)

    assert any("must not trigger on bare `v*` tags" in error for error in errors)


def test_reflex_xy_release_workflow_rejects_shallow_checkout(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release-reflex-xy.yml").read_text(encoding="utf-8")
    path = tmp_path / "release-reflex-xy.yml"
    path.write_text(workflow.replace("          fetch-depth: 0\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_reflex_xy_release_workflow(path)

    assert any("fetch-depth: 0" in error and "0.0.0" in error for error in errors)


def test_release_workflow_rejects_adapter_tag_namespace(tmp_path: Path) -> None:
    # And the inverse guard: release.yml reaching into `reflex-xy-v*` would
    # run the full cross-compile matrix (and publish xy) on adapter tags.
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace('    tags: ["v*"]\n', '    tags: ["v*", "reflex-xy-v*"]\n'),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("must not touch the reflex-xy tag namespace" in error for error in errors)


def test_release_workflow_rejects_always_conditioned_pypi_publish(tmp_path: Path) -> None:
    # `if: always()` is *a* condition but gates nothing: a mere has-an-if
    # check would accept it and let a manual dispatch publish unconditionally.
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    gate = (
        "        if: github.event_name != 'workflow_dispatch' "
        "|| github.event.inputs.dry_run != 'true'\n"
    )
    assert gate in workflow
    path.write_text(workflow.replace(gate, "        if: always()\n"), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("is not gated by the dry-run predicate" in error for error in errors)


def test_reflex_xy_release_workflow_rejects_always_conditioned_pypi_publish(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release-reflex-xy.yml").read_text(encoding="utf-8")
    path = tmp_path / "release-reflex-xy.yml"
    gate = (
        "        if: github.event_name != 'workflow_dispatch' "
        "|| github.event.inputs.dry_run != 'true'\n"
    )
    assert gate in workflow
    path.write_text(workflow.replace(gate, "        if: always()\n"), encoding="utf-8")

    errors = verify_ci_workflow.validate_reflex_xy_release_workflow(path)

    assert any("is not gated by the dry-run predicate" in error for error in errors)
