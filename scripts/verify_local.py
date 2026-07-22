#!/usr/bin/env python3
"""Run local xy verification checks with actionable missing-tool errors.

This is the contributor-friendly wrapper around the CI gates. It intentionally
stays stdlib-only so it can explain what is missing before the dev environment
is fully installed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    command: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    requires_executables: tuple[str, ...] = ()
    requires_modules: tuple[str, ...] = ()
    requires_files: tuple[Path, ...] = ()
    requires_paths: tuple[Path, ...] = ()
    requires_chromium: bool = False
    requires_node_major: Optional[int] = None
    requires_rust_toolchain: bool = False
    requires_rust_clippy: bool = False
    requires_argument: Optional[str] = None
    # Advisory checks report findings but do not fail the gate — mirrors how CI
    # runs them (e.g. ty is pre-1.0 and can't narrow known-non-None Optionals or
    # NumPy dtypes across stub versions). Keep this in sync with ci.yml.
    advisory: bool = False


def _python() -> str:
    return sys.executable


def _base_checks(
    chromium: Optional[Path] = None,
    *,
    sdist: Optional[Path] = None,
    wheel: Optional[Path] = None,
    wheel_expect: Optional[str] = None,
) -> dict[str, Check]:
    py = _python()
    chromium_arg = str(chromium) if chromium is not None else "<CHROMIUM>"
    chromium_paths = (chromium,) if chromium is not None else ()
    sdist_arg = str(sdist) if sdist is not None else "<SDIST>"
    wheel_arg = str(wheel) if wheel is not None else "<WHEEL>"
    wheel_command = [py, "scripts/verify_wheel.py", wheel_arg]
    if wheel_expect:
        wheel_command.append(wheel_expect)
    checks = [
        Check(
            "python_floor",
            "Python 3.11 syntax/API floor",
            (py, "scripts/check_python_floor.py"),
        ),
        Check("public_api", "lazy public API coherence", (py, "scripts/check_public_api.py")),
        Check(
            "import_budget",
            "import-time budget and dependency-boundary tests",
            (py, "-m", "pytest", "-q", "tests/test_import.py", "tests/test_dependencies.py"),
            requires_modules=("pytest",),
        ),
        Check(
            "claim_guardrails",
            "public performance-claim guardrails",
            (py, "scripts/check_claim_guardrails.py"),
        ),
        Check(
            "testing_spec",
            "testing catalog links, gap IDs, commands, and workflow jobs",
            (py, "scripts/check_testing_spec.py"),
        ),
        Check(
            "benchmark_harness",
            "benchmark metadata, report, regression, and claim guardrail tests",
            (
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_benchmark_environment.py",
                "tests/test_bench_pyplot_vs_matplotlib.py",
                "tests/test_verify_benchmark_report.py",
                "tests/test_check_regressions.py",
                "tests/test_claim_guardrails.py",
            ),
            requires_modules=("pytest",),
        ),
        Check(
            "api_surface",
            "public API and type-surface regression tests",
            (
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_public_api.py",
                "tests/test_type_surface.py",
                "tests/test_components.py::test_declarative_core_contract_for_layered_axis_chrome_and_interaction",
                "tests/test_components.py::test_declarative_chart_keeps_notebook_export_and_framework_chrome_contract",
            ),
            requires_modules=("pytest",),
        ),
        Check(
            "ci_workflow",
            "CI/release workflow production gates",
            (py, "scripts/verify_ci_workflow.py"),
        ),
        Check(
            "examples",
            "README/API examples and example-app checks",
            (
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_docs_examples.py",
                "tests/test_example_apps.py",
            ),
            requires_modules=("pytest",),
        ),
        Check(
            "security_export",
            "standalone HTML escaping, atomic writes, and client text-sink guardrails",
            (
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_static_client_security.py",
                "tests/test_figure.py::test_inline_json_export_escapes_html_hazards_without_changing_data",
                "tests/test_figure.py::test_inline_javascript_export_escapes_closing_script",
                "tests/test_figure.py::test_to_html_escapes_closing_script_inside_bundled_client",
                "tests/test_figure.py::test_to_html_escapes_every_chart_text_surface",
                "tests/test_figure.py::test_to_html_path_keeps_existing_file_on_atomic_replace_failure",
                "tests/test_scatter.py::test_to_html_escapes_user_strings",
                "tests/test_components.py::test_component_to_html_escapes_user_strings_across_public_surface",
                "tests/test_components.py::test_component_to_html_path_keeps_existing_file_on_atomic_replace_failure",
                "tests/test_docs_examples.py::test_readme_documents_standalone_html_security_contract",
                "tests/test_docs_examples.py::test_production_docs_capture_html_export_dom_text_contract",
            ),
            requires_modules=("pytest",),
        ),
        Check(
            "error_safety",
            "public error messages, LOD boundaries, and mutation-safety tests",
            (
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_figure.py",
                "tests/test_components.py",
                "tests/test_lod.py",
            ),
            requires_modules=("pytest",),
        ),
        Check(
            "ruff_check", "ruff lint", (py, "-m", "ruff", "check", "."), requires_modules=("ruff",)
        ),
        Check(
            "ruff_format",
            "ruff format check",
            (py, "-m", "ruff", "format", "--check", "."),
            requires_modules=("ruff",),
        ),
        Check(
            "ty",
            "type check shippable Python package (advisory)",
            (py, "-m", "ty", "check", "python"),
            requires_modules=("ty",),
            advisory=True,
        ),
        Check("pytest", "Python tests", (py, "-m", "pytest", "-q"), requires_modules=("pytest",)),
        Check(
            "js_bundle",
            "committed JavaScript bundles match source",
            ("node", "js/build.mjs", "--check"),
            requires_executables=("node",),
            requires_node_major=18,
        ),
        Check(
            "rust_test",
            "Rust unit tests",
            ("cargo", "test"),
            requires_executables=("cargo",),
            requires_rust_toolchain=True,
        ),
        Check(
            "rust_clippy",
            "Rust lint",
            ("cargo", "clippy", "--all-targets", "--", "-D", "warnings"),
            requires_executables=("cargo",),
            requires_rust_toolchain=True,
            requires_rust_clippy=True,
        ),
        Check(
            "rust_release_build",
            "release native core build",
            ("cargo", "build", "--release"),
            requires_executables=("cargo",),
            requires_rust_toolchain=True,
        ),
        Check("abi_smoke", "C ABI smoke", (py, "scripts/abi_smoke.py")),
        Check(
            "render_smoke_nonumpy",
            "stdlib payload render smoke in Chromium",
            (py, "scripts/render_smoke_nonumpy.py", chromium_arg),
            requires_paths=chromium_paths,
            requires_chromium=True,
        ),
        Check(
            "smoke_render",
            "real composed-chart HTML render smoke in Chromium",
            (py, "scripts/smoke_render.py", chromium_arg),
            requires_modules=("numpy",),
            requires_paths=chromium_paths,
            requires_chromium=True,
        ),
        Check(
            "reflex_lifecycle_smoke",
            "Reflex example iframe lifecycle smoke in Chromium",
            (py, "scripts/reflex_lifecycle_smoke.py", chromium_arg),
            requires_paths=chromium_paths,
            requires_chromium=True,
        ),
        Check(
            "visual_regression_smoke",
            "representative chart screenshot smoke in Chromium",
            (py, "scripts/visual_regression_smoke.py", chromium_arg),
            requires_modules=("numpy",),
            requires_paths=chromium_paths,
            requires_chromium=True,
        ),
        Check(
            "step_tier_smoke",
            "step traces stay step-shaped through kernel tier updates",
            (py, "scripts/step_tier_smoke.py", chromium_arg),
            requires_modules=("numpy",),
            requires_paths=chromium_paths,
            requires_chromium=True,
        ),
        Check(
            "interaction_stress_smoke",
            "browser interaction stress smoke with latency/visual budgets",
            (py, "scripts/interaction_stress_smoke.py", chromium_arg),
            requires_modules=("numpy",),
            requires_paths=chromium_paths,
            requires_chromium=True,
        ),
        Check(
            "sdist_artifact",
            "source distribution artifact contents",
            (py, "scripts/verify_sdist.py", sdist_arg),
            requires_files=(sdist,) if sdist is not None else (),
            requires_argument="--sdist",
        ),
        Check(
            "wheel_artifact",
            "wheel artifact contents and native/pure tagging",
            tuple(wheel_command),
            requires_files=(wheel,) if wheel is not None else (),
            requires_argument="--wheel",
        ),
    ]
    return {check.name: check for check in checks}


QUICK_CHECKS = (
    "python_floor",
    "public_api",
    "claim_guardrails",
    "testing_spec",
    "ci_workflow",
    "ruff_check",
    "ruff_format",
    "ty",
    "pytest",
)
FULL_EXTRA_CHECKS = (
    "js_bundle",
    "rust_test",
    "rust_clippy",
    "rust_release_build",
    "abi_smoke",
)
BROWSER_CHECKS = (
    "render_smoke_nonumpy",
    "smoke_render",
    "reflex_lifecycle_smoke",
    "visual_regression_smoke",
    "step_tier_smoke",
    "interaction_stress_smoke",
)
PACKAGING_CHECKS = ("sdist_artifact", "wheel_artifact")


def _parse_names(raw: list[str]) -> set[str]:
    names: set[str] = set()
    for item in raw:
        for part in item.split(","):
            name = part.strip()
            if name:
                names.add(name)
    return names


def select_checks(
    checks: dict[str, Check],
    *,
    full: bool = False,
    packaging: bool = False,
    browser: bool = False,
    only: Optional[set[str]] = None,
    skip: Optional[set[str]] = None,
) -> list[Check]:
    skip = skip or set()
    if only:
        unknown = sorted(only - set(checks))
        if unknown:
            raise ValueError(f"unknown check(s): {', '.join(unknown)}")
        names = [name for name in checks if name in only]
    else:
        names = list(PACKAGING_CHECKS) if packaging else list(QUICK_CHECKS)
        if full and not packaging:
            names.extend(FULL_EXTRA_CHECKS)
        if browser:
            names.extend(BROWSER_CHECKS)
    unknown_skip = sorted(skip - set(checks))
    if unknown_skip:
        raise ValueError(f"unknown check(s) to skip: {', '.join(unknown_skip)}")
    return [checks[name] for name in names if name not in skip]


def _module_missing(module: str) -> bool:
    return importlib.util.find_spec(module) is None


def _module_hint(module: str) -> str:
    package_hint = {
        "numpy": "Run `uv pip install -e . numpy anywidget`, or `make setup` for the dev environment.",
        "pytest": 'Run `make setup` or `uv pip install -e ".[dev]"` before local tests.',
        "ruff": 'Run `make setup` or `uv pip install -e ".[dev]"` before lint checks.',
        "ty": 'Run `make setup` or `uv pip install -e ".[dev]"` before type checks.',
    }.get(module)
    return package_hint or 'Run `make setup` or `uv pip install -e ".[dev]"` first.'


def _chromium_hint() -> str:
    return (
        "Pass --chromium to a real Chrome/Chromium executable, for example "
        '`make check-browser CHROMIUM="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`.'
    )


def _node_hint(required_major: int) -> str:
    return (
        f"Install Node {required_major}+ and rerun the check, or use `make check` "
        "for the quick non-JS gate."
    )


def _rust_hint() -> str:
    return (
        "Install Rust with rustup so both `cargo` and `rustc` are on PATH, "
        "or use `make check` for the quick non-Rust gate."
    )


def _clippy_hint() -> str:
    return "Install the Rust clippy component with `rustup component add clippy`."


def _artifact_hint(argument: str) -> str:
    if argument == "--sdist":
        return "Pass --sdist PATH, or run `make check-sdist` to build and verify one."
    if argument == "--wheel":
        return "Pass --wheel PATH, or run `make check-wheel` to build and verify one."
    return f"Pass {argument} PATH for this artifact check."


def _run_probe(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _probe_error(command: tuple[str, ...], exc: Exception) -> str:
    return f"could not run `{format_command_text(command)}`: {exc}"


def _node_major(version_output: str) -> Optional[int]:
    version = version_output.strip()
    if version.startswith("v"):
        version = version[1:]
    head = version.split(".", 1)[0]
    return int(head) if head.isdigit() else None


def format_command_text(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def missing_reasons(check: Check) -> list[str]:
    reasons: list[str] = []
    if check.requires_argument and not check.requires_files:
        reasons.append(
            f"missing artifact path for {check.name!r}. {_artifact_hint(check.requires_argument)}"
        )
    if check.requires_chromium and not check.requires_paths:
        reasons.append(f"missing Chromium executable for {check.name!r}. {_chromium_hint()}")
    for exe in check.requires_executables:
        if shutil.which(exe) is None:
            hint = {
                "cargo": "Install Rust with rustup, or use `make check` for the quick non-Rust gate.",
                "node": "Install Node 18+, or use `make check` for the quick non-JS gate.",
            }.get(exe, f"Install {exe} or skip this check.")
            reasons.append(f"missing executable {exe!r}. {hint}")
    if check.requires_node_major is not None and shutil.which("node") is not None:
        try:
            proc = _run_probe(("node", "--version"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            reasons.append(
                f"cannot determine Node version for {check.name!r}: "
                f"{_probe_error(('node', '--version'), exc)}. "
                f"{_node_hint(check.requires_node_major)}"
            )
        else:
            found = _node_major(proc.stdout or proc.stderr)
            if proc.returncode != 0 or found is None:
                output = (proc.stderr or proc.stdout).strip() or "<no output>"
                reasons.append(
                    f"cannot determine Node version for {check.name!r}: {output}. "
                    f"{_node_hint(check.requires_node_major)}"
                )
            elif found < check.requires_node_major:
                output = (proc.stdout or proc.stderr).strip()
                reasons.append(
                    f"Node {check.requires_node_major}+ required for {check.name!r}, "
                    f"found {output!r}. {_node_hint(check.requires_node_major)}"
                )
    if check.requires_rust_toolchain and shutil.which("cargo") is not None:
        if shutil.which("rustc") is None:
            reasons.append(f"missing executable 'rustc'. {_rust_hint()}")
        else:
            for command in (("cargo", "--version"), ("rustc", "--version")):
                try:
                    proc = _run_probe(command)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    reasons.append(
                        f"cannot validate Rust toolchain for {check.name!r}: "
                        f"{_probe_error(command, exc)}. {_rust_hint()}"
                    )
                    continue
                if proc.returncode != 0:
                    output = (proc.stderr or proc.stdout).strip() or "<no output>"
                    reasons.append(
                        f"Rust toolchain command `{format_command_text(command)}` failed "
                        f"for {check.name!r}: {output}. {_rust_hint()}"
                    )
    if check.requires_rust_clippy and shutil.which("cargo") is not None:
        try:
            proc = _run_probe(("cargo", "clippy", "--version"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            reasons.append(
                f"cannot validate Rust clippy for {check.name!r}: "
                f"{_probe_error(('cargo', 'clippy', '--version'), exc)}. {_clippy_hint()}"
            )
        else:
            if proc.returncode != 0:
                output = (proc.stderr or proc.stdout).strip() or "<no output>"
                reasons.append(
                    f"Rust clippy is unavailable for {check.name!r}: {output}. {_clippy_hint()}"
                )
    for module in check.requires_modules:
        if _module_missing(module):
            reasons.append(f"missing Python module {module!r}. {_module_hint(module)}")
    for path in check.requires_files:
        if not path.exists():
            argument = check.requires_argument or "artifact"
            reasons.append(f"missing {argument} artifact {str(path)!r}. {_artifact_hint(argument)}")
        elif not path.is_file():
            argument = check.requires_argument or "artifact"
            reasons.append(
                f"{argument} artifact {str(path)!r} is not a file. {_artifact_hint(argument)}"
            )
    for path in check.requires_paths:
        if not path.exists():
            reasons.append(f"missing Chromium path {str(path)!r}. {_chromium_hint()}")
        elif not path.is_file():
            reasons.append(f"Chromium path {str(path)!r} is not a file. {_chromium_hint()}")
        elif not os.access(path, os.X_OK):
            reasons.append(f"Chromium path {str(path)!r} is not executable. {_chromium_hint()}")
    return reasons


def format_command(check: Check) -> str:
    prefix = ""
    if check.env:
        prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(check.env.items())) + " "
    return prefix + format_command_text(check.command)


def run_check(check: Check) -> int:
    reasons = missing_reasons(check)
    if reasons:
        print(f"FAIL {check.name}: {check.description}", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 127
    print(f"RUN  {check.name}: {check.description}")
    env = os.environ.copy()
    env.update(check.env)
    return subprocess.run(check.command, cwd=ROOT, env=env, check=False).returncode


def _requirement_summary(check: Check) -> str:
    requirements: list[str] = []
    if check.requires_argument:
        requirements.append(f"artifact: {check.requires_argument}")
    if check.requires_modules:
        requirements.append(f"modules: {', '.join(check.requires_modules)}")
    if check.requires_executables:
        requirements.append(f"executables: {', '.join(check.requires_executables)}")
    if check.requires_node_major:
        requirements.append(f"node: >= {check.requires_node_major}")
    if check.requires_rust_toolchain:
        requirements.append("rust: cargo + rustc")
    if check.requires_rust_clippy:
        requirements.append("rust: clippy")
    if check.requires_chromium:
        requirements.append("chromium")
    if not requirements:
        return ""
    return " [requires " + "; ".join(requirements) + "]"


def _print_list(checks: dict[str, Check]) -> None:
    for check in checks.values():
        print(f"{check.name:22} {check.description}{_requirement_summary(check)}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true", help="run fast Python/dev gates (default)")
    mode.add_argument("--full", action="store_true", help="include JS, Rust, and ABI gates")
    mode.add_argument(
        "--packaging",
        action="store_true",
        help="verify already-built sdist/wheel artifacts only",
    )
    parser.add_argument(
        "--browser", action="store_true", help="include Chromium render smoke checks"
    )
    parser.add_argument(
        "--chromium", type=Path, help="Chromium/Chrome executable for browser checks"
    )
    parser.add_argument("--sdist", type=Path, help="source distribution artifact for --packaging")
    parser.add_argument("--wheel", type=Path, help="wheel artifact for --packaging")
    wheel_expect = parser.add_mutually_exclusive_group()
    wheel_expect.add_argument(
        "--expect-native",
        action="store_const",
        const="--expect-native",
        dest="wheel_expect",
        help="require a native wheel artifact in packaging checks",
    )
    wheel_expect.add_argument(
        "--expect-pure",
        action="store_const",
        const="--expect-pure",
        dest="wheel_expect",
        help="require an intentional pure (no-native) wheel artifact in packaging checks",
    )
    parser.add_argument(
        "--only", action="append", default=[], help="comma-separated check names to run"
    )
    parser.add_argument(
        "--skip", action="append", default=[], help="comma-separated check names to skip"
    )
    parser.add_argument("--list", action="store_true", help="list known checks")
    parser.add_argument(
        "--dry-run", action="store_true", help="print commands without running them"
    )
    args = parser.parse_args(argv)

    if args.browser and args.chromium is None and not args.list:
        parser.error("--browser requires --chromium PATH. " + _chromium_hint())

    checks = _base_checks(
        args.chromium,
        sdist=args.sdist,
        wheel=args.wheel,
        wheel_expect=args.wheel_expect,
    )
    if args.list:
        _print_list(checks)
        return 0

    only = _parse_names(args.only)
    skip = _parse_names(args.skip)
    try:
        selected = select_checks(
            checks,
            full=args.full,
            packaging=args.packaging,
            browser=args.browser,
            only=only,
            skip=skip,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if args.dry_run:
        for check in selected:
            print(f"{check.name:22} {format_command(check)}")
        return 0

    advisory_findings = 0
    for check in selected:
        rc = run_check(check)
        if rc != 0:
            if check.advisory:
                advisory_findings += 1
                print(
                    f"WARNING {check.name} reported findings (advisory, not gating)",
                    file=sys.stderr,
                )
                continue
            print(f"FAILED {check.name} with exit code {rc}", file=sys.stderr)
            return rc
    suffix = f" ({advisory_findings} advisory finding(s))" if advisory_findings else ""
    print(f"OK: {len(selected)} check(s) passed{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
