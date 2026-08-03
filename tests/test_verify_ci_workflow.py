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


def test_ci_workflow_requires_locked_reflex_environment(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "uv sync --locked --extra reflex --group dev",
            "uv sync --extra reflex --group dev",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("uv sync --locked --extra reflex --group dev" in error for error in errors)


def test_locked_reflex_environment_must_be_in_named_install_step(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "          uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            required,
            "          uv sync --extra reflex --group dev\n\n"
            "      - name: Unrelated example\n"
            f"        run: {required.strip()}",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_cannot_be_commented_out(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "          uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(required, f"          # {required.strip()}"), encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_cannot_hide_in_step_env(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            f"          FAKE_GATE: {required}\n",
        ).replace(f"          {required}", "          uv sync --extra reflex --group dev"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_requires_an_exact_command_line(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(f"          {required}", f"          echo '{required}'"),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_cannot_be_heredoc_data(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            f"          {required}",
            "          cat <<'EOF'\n"
            f"          {required}\n"
            "          EOF\n"
            "          uv sync --extra reflex --group dev",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_cannot_be_folded_echo_data(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            f"        run: |\n          {required}",
            f"        run: >\n          echo ignored\n          {required}",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_cannot_be_folded_comment_data(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "uv sync --locked --extra reflex --group dev"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            f"        run: |\n          {required}",
            f"        run: >\n          # disabled\n          {required}",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_step_must_be_a_hard_gate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    bypasses = (
        "if: false",
        "shell: echo {0}",
        "continue-on-error: true",
        "working-directory: decoy",
        '"if": false',
        "'shell': echo {0}",
        '"continue-on-error": true',
        "'working-directory': decoy",
        '"working\\u002ddirectory": decoy',
        "!!str working-directory: decoy",
        "&guard_key working-directory: decoy",
        "<<: *step_defaults",
        "? working-directory\n        : decoy",
        "?\n          working-directory\n        : decoy",
    )

    for index, bypass in enumerate(bypasses):
        path = tmp_path / f"ci-{index}.yml"
        path.write_text(
            workflow.replace(
                "      - name: Install package + dev deps\n",
                f"      - name: Install package + dev deps\n        {bypass}\n",
            ),
            encoding="utf-8",
        )

        errors = verify_ci_workflow.validate_ci_workflow(path)

        assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_job_must_be_a_hard_gate(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    bypasses = (
        "if: false",
        "continue-on-error: true",
        "defaults:\n      run:\n        shell: echo {0}",
        'container: { image: "ubuntu:24.04", env: { BASH_ENV: noop } }',
        "needs: skipped-prerequisite",
        "strategy:\n      matrix:\n        shard: []",
        '"if": false',
        "'continue-on-error': true",
        '"defaults":\n      run:\n        shell: echo {0}',
    )

    for index, bypass in enumerate(bypasses):
        path = tmp_path / f"ci-job-{index}.yml"
        path.write_text(
            workflow.replace(
                "  test:\n",
                f"  test:\n    {bypass}\n",
            ),
            encoding="utf-8",
        )

        errors = verify_ci_workflow.validate_ci_workflow(path)

        assert any("Install package + dev deps" in error for error in errors)


def test_locked_reflex_environment_rejects_workflow_shell_override(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "jobs:\n",
            "defaults:\n  run:\n    shell: echo {0}\n\njobs:\n",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("hard-gate run steps" in error for error in errors)


def test_locked_reflex_environment_rejects_quoted_workflow_shell_override(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "jobs:\n",
            '"defaults":\n  run:\n    shell: echo {0}\n\njobs:\n',
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("hard-gate run steps" in error for error in errors)


def test_hard_gates_reject_shell_init_environment_overrides(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    mutations = (
        (
            "jobs:\n",
            "env:\n  BASH_ENV: .github/noop-shell-init\n\njobs:\n",
        ),
        (
            "  test:\n",
            "  test:\n    env:\n      BASH_ENV: .github/noop-shell-init\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            "          'ENV': .github/noop-shell-init\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env: { BASH_ENV: .github/noop-shell-init }\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            '        env: { "ENV": .github/noop-shell-init }\n',
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            '        env: { "BASH\\u005fENV": .github/noop-shell-init }\n',
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            '        env: { "BASH\\x5fENV": .github/noop-shell-init }\n',
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env: &shell_env { BASH_ENV: .github/noop-shell-init }\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env: { !!str BASH_ENV: .github/noop-shell-init }\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            "          !!str BASH_ENV: .github/noop-shell-init\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            "          &shell_key BASH_ENV: .github/noop-shell-init\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            "          ? BASH_ENV\n"
            "          : .github/noop-shell-init\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            "          ?\n"
            "            BASH_ENV\n"
            "          : .github/noop-shell-init\n",
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            '          "\\u0045NV": .github/noop-shell-init\n',
        ),
        (
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n"
            "        env:\n"
            "          PATH: .github/fake-bin\n",
        ),
    )

    for index, (old, new) in enumerate(mutations):
        path = tmp_path / f"ci-shell-init-{index}.yml"
        path.write_text(workflow.replace(old, new), encoding="utf-8")

        errors = verify_ci_workflow.validate_ci_workflow(path)

        assert any("shell-init environment variables" in error for error in errors)


def test_hard_gates_reject_persistent_environment_file_writes(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Install package + dev deps\n",
            "      - name: Persist shell setup\n"
            "        run: |\n"
            "          printf 'BASH_ENV=%s\\n' noop >> \"$GITHUB_ENV\"\n\n"
            "          printf '%s\\n' fake-bin >> \"$GITHUB_PATH\"\n\n"
            "      - name: Install package + dev deps\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("shell-init environment variables" in error for error in errors)


def test_multiline_quoted_env_value_does_not_create_a_sibling_key() -> None:
    text = 'env:\n  SAFE: "start\n  BASH_ENV: harmless"\njobs:\n  test:\n    steps: []\n'

    assert not verify_ci_workflow._has_shell_init_environment(text)


def test_protected_step_requires_exactly_one_direct_run_key(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "          uv sync --locked --extra reflex --group dev\n"
    duplicate_run_keys = (
        "        run: echo bypassed\n",
        '        "run": echo bypassed\n',
        "        'run': echo bypassed\n",
        '        "r\\u0075n": echo bypassed\n',
        "        !!str run: echo bypassed\n",
        "        &run_key run: echo bypassed\n",
        "        <<: *run_defaults\n",
        "        ? run\n        : echo bypassed\n",
        "        ?\n          run\n        : echo bypassed\n",
    )

    for index, duplicate in enumerate(duplicate_run_keys):
        path = tmp_path / f"ci-duplicate-run-{index}.yml"
        path.write_text(workflow.replace(required, required + duplicate, 1), encoding="utf-8")

        errors = verify_ci_workflow.validate_ci_workflow(path)

        assert any("Install package + dev deps" in error for error in errors)


def test_shell_init_key_text_in_a_comment_is_not_a_mapping_key(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "jobs:\n",
            '# Documentation example only: { BASH_ENV: unsafe, "ENV": unsafe }\n'
            "# Mentioning GITHUB_ENV in a YAML comment is harmless.\n\n"
            "jobs:\n",
            1,
        ),
        encoding="utf-8",
    )

    assert verify_ci_workflow.validate_ci_workflow(path) == []


def test_shell_init_flow_mapping_on_an_indented_value_line_is_rejected() -> None:
    text = "env:\n  { BASH_ENV: .github/noop-shell-init }\n"

    assert verify_ci_workflow._has_shell_init_environment(text)


def test_sequence_mapping_sibling_after_block_scalar_is_still_checked() -> None:
    text = (
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: |\n"
        "          echo harmless\n"
        "        env:\n"
        "          BASH_ENV: .github/noop-shell-init\n"
    )

    assert verify_ci_workflow._has_shell_init_environment(text)


def test_anchored_steps_value_does_not_hide_step_environment() -> None:
    text = (
        "jobs:\n"
        "  test:\n"
        "    steps: &test_steps\n"
        "      - name: Protected\n"
        "        env:\n"
        "          BASH_ENV: .github/noop-shell-init\n"
        "        run: true\n"
    )

    assert verify_ci_workflow._has_shell_init_environment(text)


def test_plain_scalar_content_cannot_hide_a_later_shell_init_mapping() -> None:
    prefixes = (
        "name: Don't\n",
        'name: Say "hello\n',
        'run-name:\n  -"unterminated\n',
        'run-name:\n  name:"unterminated\n',
        'run-name:\n  CONFIG: plain\n    "unfinished\n',
    )

    for prefix in prefixes:
        text = prefix + "env: { BASH_ENV: .github/noop-shell-init }\n"
        assert verify_ci_workflow._has_shell_init_environment(text)


def test_scalar_contents_and_github_expressions_are_not_mapping_keys() -> None:
    harmless_yaml = (
        "matrix:\n"
        "  script:\n"
        "    - |\n"
        "      BASH_ENV: documentation\n"
        "anchored: &script |\n"
        "  ENV: documentation\n"
        "tagged: !!str >-\n"
        "  BASH_ENV: documentation\n"
        'quoted: "documentation starts\n'
        "  ENV: documentation\n"
        '  documentation ends"\n'
        'run-name:\n  &label "CI: run"\n'
        "condition: ${{ !cancelled() }}\n"
    )

    assert not verify_ci_workflow._has_shell_init_environment(harmless_yaml)


def test_unrelated_actions_env_fields_are_not_environment_mappings() -> None:
    text = (
        "run-name: Inspect GITHUB_ENV behavior\n"
        "jobs:\n"
        "  test:\n"
        "    strategy:\n"
        "      matrix:\n"
        "        env: [py311, py312]\n"
        "    steps:\n"
        "      - uses: example/action@0123456789abcdef\n"
        "        with:\n"
        "          env: production\n"
    )

    assert not verify_ci_workflow._has_shell_init_environment(text)


def test_url_like_scalar_values_are_not_mapping_keys() -> None:
    scalars = (
        "run-name:\n  ENV:https://example.com\n",
        "run-name:\n  !!str https://example.com\n",
        "run-name:\n  &label https://example.com\n",
    )

    for text in scalars:
        assert verify_ci_workflow._yaml_mapping_keys(text) == [(0, "run-name", False)]


def test_plain_scalar_continuation_cannot_hide_duplicate_run(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    required = "          uv sync --locked --extra reflex --group dev\n"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            required,
            required
            + "        env:\n"
            + "          NOTE: This is\n"
            + '            "unfinished\n'
            + "        run: echo bypassed\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_top_level_scalar_cannot_replace_the_real_job_block(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    original_test = verify_ci_workflow._job_blocks(workflow)["test"]
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace("  test:\n", "  test:\n    if: false\n", 1)
        + "\nrun-name: |2\n"
        + original_test
        + "\n",
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_job_scalar_cannot_replace_the_real_named_step(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    original_step = verify_ci_workflow._named_step_blocks(
        verify_ci_workflow._job_blocks(workflow)["test"]
    )["Install package + dev deps"]
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "      - name: Install package + dev deps\n",
            "      - name: Install package + dev deps\n        if: false\n",
            1,
        ).replace(
            "  browser_conformance:\n",
            "    name: |2\n" + original_step + "\n\n  browser_conformance:\n",
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("Install package + dev deps" in error for error in errors)


def test_reference_gate_commands_must_be_in_the_named_step(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    command = "          .venv/bin/pytest -q tests/pyplot/test_reference_semantics.py\n"
    # Leaving the old verifier's needle elsewhere in the job must not satisfy
    # the structural step-local check.
    path = tmp_path / "ci.yml"
    path.write_text(workflow.replace(command, "") + f"\n# {command.strip()}\n", encoding="utf-8")
    errors = verify_ci_workflow.validate_ci_workflow(path)
    assert any("reference test commands" in error for error in errors)


def test_reference_gate_commands_cannot_hide_in_inline_comments(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    commands = (
        ".venv/bin/pytest -q tests/pyplot/test_launch_compat.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_corpus.py",
        ".venv/bin/pytest -q tests/pyplot/test_reference_semantics.py",
    )
    for command in commands:
        workflow = workflow.replace(f"          {command}", f"          echo ignored # {command}")
    path = tmp_path / "ci.yml"
    path.write_text(workflow, encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("reference test commands" in error for error in errors)


def test_reference_gate_commands_cannot_be_heredoc_data(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    first = ".venv/bin/pytest -q tests/pyplot/test_launch_compat.py"
    last = ".venv/bin/pytest -q tests/pyplot/test_reference_semantics.py"
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            f"          {first}",
            "          cat <<'EOF'",
        ).replace(
            f"          {last}",
            f"          {last}\n          EOF",
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("reference test commands" in error for error in errors)


def test_reference_job_and_steps_must_be_hard_gates(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    mutations = (
        (
            "      - name: Run optional-interoperability and dual-engine corpus tests\n",
            "      - name: Run optional-interoperability and dual-engine corpus tests\n"
            "        if: false\n",
        ),
        (
            "      - name: Run optional-interoperability and dual-engine corpus tests\n",
            "      - name: Run optional-interoperability and dual-engine corpus tests\n"
            "        continue-on-error: true\n",
        ),
        (
            "      - name: Run optional-interoperability and dual-engine corpus tests\n",
            "      - name: Run optional-interoperability and dual-engine corpus tests\n"
            "        shell: echo {0}\n",
        ),
        (
            "      - name: Run optional-interoperability and dual-engine corpus tests\n",
            "      - name: Run optional-interoperability and dual-engine corpus tests\n"
            "        working-directory: decoy\n",
        ),
        ("  matplotlib_reference:\n", "  matplotlib_reference:\n    if: false\n"),
        (
            "  matplotlib_reference:\n",
            "  matplotlib_reference:\n    continue-on-error: true\n",
        ),
        (
            "  matplotlib_reference:\n",
            "  matplotlib_reference:\n    defaults:\n      run:\n        shell: echo {0}\n",
        ),
    )

    for index, (old, new) in enumerate(mutations):
        path = tmp_path / f"ci-reference-hard-gate-{index}.yml"
        path.write_text(workflow.replace(old, new), encoding="utf-8")

        errors = verify_ci_workflow.validate_ci_workflow(path)

        assert any("Run optional-interoperability" in error for error in errors)


def test_codspeed_workflow_accepts_current_gates() -> None:
    assert verify_ci_workflow.validate_codspeed_workflow() == []


def test_all_workflows_accept_current_gates() -> None:
    assert verify_ci_workflow.validate_all_workflows() == []


def test_workflows_reject_normalized_top_level_overrides(tmp_path: Path) -> None:
    cases = (
        ("ci", Path(".github/workflows/ci.yml"), verify_ci_workflow.validate_ci_workflow),
        (
            "codspeed",
            Path(".github/workflows/codspeed.yml"),
            verify_ci_workflow.validate_codspeed_workflow,
        ),
        (
            "release",
            Path(".github/workflows/release.yml"),
            verify_ci_workflow.validate_release_workflow,
        ),
    )

    for label, source, validate in cases:
        workflow = source.read_text(encoding="utf-8")
        for key, value in (("jobs", "  bypass: {}"), ("on", "  workflow_dispatch:")):
            path = tmp_path / f"{label}-{key}.yml"
            path.write_text(workflow + f'\n"{key}":\n{value}\n', encoding="utf-8")

            errors = validate(path)

            assert any(f"top-level '{key}' key" in error for error in errors)


def test_ci_workflow_requires_block_style_top_level_on(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    # Keep every trigger-shaped line as a decoy under another top-level key.
    path.write_text(workflow.replace("on:\n", "on: {}\ntrigger_decoys:\n", 1), encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("block-style top-level 'on' key" in error for error in errors)


def test_codspeed_trigger_checks_ignore_decoy_mapping(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/codspeed.yml").read_text(encoding="utf-8")
    path = tmp_path / "codspeed.yml"
    path.write_text(
        workflow.replace(
            "on:\n",
            'on:\n  schedule:\n    - cron: "0 0 * * *"\ntrigger_decoys:\n',
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_codspeed_workflow(path)

    assert any("missing pull_request trigger" in error for error in errors)
    assert any("missing push trigger" in error for error in errors)
    assert any("missing workflow_dispatch trigger" in error for error in errors)


def test_ci_workflow_rejects_normalized_duplicate_required_job(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    path.write_text(
        workflow.replace(
            "  browser_conformance:\n",
            '  "test":\n    runs-on: ubuntu-latest\n    steps: []\n\n  browser_conformance:\n',
            1,
        ),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any("exactly one unambiguous 'test' job" in error for error in errors)


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


def test_ci_workflow_rejects_missing_sdist_rust_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    path = tmp_path / "ci.yml"
    moved = workflow.replace(
        "      - name: Build sdist\n",
        '      - name: Build sdist\n        env:\n          XY_REQUIRE_CARGO: "1"\n',
        1,
    ).replace(
        "      - name: Build and load native core from sdist\n"
        "        shell: bash\n"
        "        env:\n"
        '          XY_REQUIRE_CARGO: "1"\n',
        "      - name: Build and load native core from sdist\n        shell: bash\n",
    )
    path.write_text(moved, encoding="utf-8")

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "Build and load native core from sdist" in error and "XY_REQUIRE_CARGO" in error
        for error in errors
    )


def test_release_workflow_rejects_missing_sdist_rust_smoke(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    moved = workflow.replace(
        "      - name: Build sdist\n",
        '      - name: Build sdist\n        env:\n          XY_REQUIRE_CARGO: "1"\n',
        1,
    ).replace(
        "      - name: Build and load native core from sdist\n"
        "        shell: bash\n"
        "        env:\n"
        '          XY_REQUIRE_CARGO: "1"\n',
        "      - name: Build and load native core from sdist\n        shell: bash\n",
    )
    path.write_text(moved, encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "Build and load native core from sdist" in error and "XY_REQUIRE_CARGO" in error
        for error in errors
    )


def test_ci_workflow_rejects_missing_coreless_sdist_reflex_import(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    prefix, smoke = workflow.split("      - name: Verify coreless sdist imports reflex_xy\n", 1)
    path = tmp_path / "ci.yml"
    path.write_text(
        prefix
        + "      - name: Verify coreless sdist imports reflex_xy\n"
        + smoke.replace("          import reflex_xy\n", "          import removed_reflex_xy\n", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_ci_workflow(path)

    assert any(
        "Verify coreless sdist imports reflex_xy" in error and "import reflex_xy" in error
        for error in errors
    )


def test_release_workflow_rejects_missing_coreless_sdist_reflex_import(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    prefix, smoke = workflow.split("      - name: Verify coreless sdist imports reflex_xy\n", 1)
    path = tmp_path / "release.yml"
    path.write_text(
        prefix
        + "      - name: Verify coreless sdist imports reflex_xy\n"
        + smoke.replace("          import reflex_xy\n", "          import removed_reflex_xy\n", 1),
        encoding="utf-8",
    )

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any(
        "Verify coreless sdist imports reflex_xy" in error and "import reflex_xy" in error
        for error in errors
    )


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


def test_release_dry_run_rejects_inline_or_unsafe_duplicate_trigger(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    marker = "\n# Limit build jobs to repository reads."
    assert marker in workflow
    duplicates = (
        '  "\\u0077orkflow_dispatch": {}\n',
        "  !!str workflow_dispatch: {}\n",
    )
    for index, duplicate in enumerate(duplicates):
        path = tmp_path / f"release-duplicate-trigger-{index}.yml"
        path.write_text(workflow.replace(marker, f"\n{duplicate}{marker}", 1), encoding="utf-8")

        errors = verify_ci_workflow.validate_release_workflow(path)

        assert any("dry-run input" in error for error in errors)


def test_release_workflow_rejects_false_dry_run_default_hidden_by_comment(
    tmp_path: Path,
) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(
        workflow.replace("        default: true\n", "        default: false # default: true\n", 1),
        encoding="utf-8",
    )

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


def test_release_workflow_rejects_duplicate_pypi_publish_condition(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    gate = (
        "        if: github.event_name != 'workflow_dispatch' "
        "|| github.event.inputs.dry_run != 'true'\n"
    )
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace(gate, gate + '        "if": always()\n', 1), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("is not gated by the dry-run predicate" in error for error in errors)


def test_release_job_scalar_cannot_decoy_the_publish_step(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    gate = (
        "        if: github.event_name != 'workflow_dispatch' "
        "|| github.event.inputs.dry_run != 'true'\n"
    )
    decoy = "\n    name: |2\n      - uses: pypa/gh-action-pypi-publish@decoy\n" + gate
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace(gate, "", 1) + decoy, encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("is not gated by the dry-run predicate" in error for error in errors)


def test_release_workflow_rejects_non_retryable_pypi_publish(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    path = tmp_path / "release.yml"
    path.write_text(workflow.replace("          skip-existing: true\n", ""), encoding="utf-8")

    errors = verify_ci_workflow.validate_release_workflow(path)

    assert any("release publish job" in error and "skip-existing" in error for error in errors)


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


def test_ci_workflow_decodes_quoted_checkout_uses_key(tmp_path: Path) -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    uses_keys = ('"uses"', '"\\u0075ses"')
    for index, uses_key in enumerate(uses_keys):
        mutated = workflow.replace(
            "      - uses: actions/checkout@",
            f"      - {uses_key}: actions/checkout@",
            1,
        ).replace("          fetch-depth: 0\n", "", 1)
        path = tmp_path / f"ci-quoted-checkout-{index}.yml"
        path.write_text(mutated, encoding="utf-8")

        errors = verify_ci_workflow.validate_ci_workflow(path)

        assert any("fetch-depth: 0" in error for error in errors)


def test_workflows_reject_fetch_depth_hidden_in_scalar_input(tmp_path: Path) -> None:
    cases = (
        (Path(".github/workflows/ci.yml"), verify_ci_workflow.validate_ci_workflow),
        (Path(".github/workflows/codspeed.yml"), verify_ci_workflow.validate_codspeed_workflow),
        (Path(".github/workflows/release.yml"), verify_ci_workflow.validate_release_workflow),
    )
    for index, (source, validate) in enumerate(cases):
        workflow = source.read_text(encoding="utf-8")
        path = tmp_path / f"workflow-{index}.yml"
        path.write_text(
            workflow.replace(
                "          fetch-depth: 0",
                "          decoy: |\n            fetch-depth: 0",
            ),
            encoding="utf-8",
        )

        errors = validate(path)

        assert any("fetch-depth: 0" in error for error in errors)


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
