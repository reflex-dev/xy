#!/usr/bin/env python3
"""Verify fastcharts source distributions before upload/install smoke tests.

An sdist is the escape hatch for users without a prebuilt wheel. It must carry
the Rust source, committed JS bundles, package typing marker, and build hook,
while never carrying generated caches or platform-native binaries from a local
checkout. Stdlib-only so CI can run it before installing anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
import tomllib
from email.parser import Parser
from pathlib import Path, PurePosixPath
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = {
    ".github/workflows/ci.yml",
    ".github/workflows/codspeed.yml",
    ".github/workflows/release.yml",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Cargo.lock",
    "Cargo.toml",
    "LICENSE",
    "Makefile",
    "PKG-INFO",
    "README.md",
    "SECURITY.md",
    "benchmarks/__init__.py",
    "benchmarks/_browser.py",
    "benchmarks/_fastcharts_browser.py",
    "benchmarks/baseline.json",
    "benchmarks/bench.py",
    "benchmarks/bench_2d_charts.py",
    "benchmarks/bench_dashboard.py",
    "benchmarks/bench_install.py",
    "benchmarks/bench_interaction.py",
    "benchmarks/bench_line.py",
    "benchmarks/bench_native.py",
    "benchmarks/bench_scatter_native.py",
    "benchmarks/bench_vs.py",
    "benchmarks/categories.py",
    "benchmarks/environment.py",
    "docs/api-examples.md",
    "docs/benchmark.md",
    "docs/chart-roadmap.md",
    "docs/contributing.md",
    "docs/production-readiness.md",
    "hatch_build.py",
    "pyproject.toml",
    "js/src/00_header.js",
    "js/src/10_colormaps.js",
    "js/src/20_theme.js",
    "js/src/30_ticks.js",
    "js/src/40_gl.js",
    "js/src/45_lod.js",
    "js/src/50_chartview.js",
    "js/src/55_marks.js",
    "js/src/60_entries.js",
    "python/fastcharts/__init__.py",
    "python/fastcharts/_native.py",
    "python/fastcharts/channels.py",
    "python/fastcharts/columns.py",
    "python/fastcharts/components.py",
    "python/fastcharts/config.py",
    "python/fastcharts/export.py",
    "python/fastcharts/figure.py",
    "python/fastcharts/interaction.py",
    "python/fastcharts/kernels.py",
    "python/fastcharts/lod.py",
    "python/fastcharts/py.typed",
    "python/fastcharts/static/index.js",
    "python/fastcharts/static/standalone.js",
    "python/fastcharts/widget.py",
    "examples/reflex/README.md",
    "examples/reflex/requirements.txt",
    "examples/reflex/rxconfig.py",
    "examples/reflex/assets/charts/area.html",
    "examples/reflex/assets/charts/bar_column.html",
    "examples/reflex/assets/charts/business_overview.html",
    "examples/reflex/assets/charts/colored_scatter.html",
    "examples/reflex/assets/charts/density_scatter.html",
    "examples/reflex/assets/charts/heatmap.html",
    "examples/reflex/assets/charts/histogram.html",
    "examples/reflex/assets/charts/horizontal_bar.html",
    "examples/reflex/assets/charts/line_walk.html",
    "examples/reflex/assets/charts/live_drilldown_100m.html",
    "examples/reflex/assets/charts/live_drilldown_10m.html",
    "examples/reflex/assets/charts/plotly_colored_scatter.html",
    "examples/reflex/assets/charts/stacked_bar.html",
    "examples/reflex/reflex_fastcharts_app/__init__.py",
    "examples/reflex/reflex_fastcharts_app/live_drilldown.py",
    "examples/reflex/reflex_fastcharts_app/reflex_fastcharts_app.py",
    "examples/reflex/scripts/build_charts.py",
    "scripts/check_public_api.py",
    "scripts/check_claim_guardrails.py",
    "scripts/check_python_floor.py",
    "scripts/check_regressions.py",
    "scripts/bench_dashboard.py",
    "scripts/bench_interaction.py",
    "scripts/verify_ci_workflow.py",
    "scripts/verify_benchmark_report.py",
    "scripts/verify_local.py",
    "scripts/verify_sdist.py",
    "scripts/verify_wheel.py",
    "src/kernels.rs",
    "src/lib.rs",
    "tests/test_public_api.py",
    "tests/test_claim_guardrails.py",
    "tests/test_benchmark_environment.py",
    "tests/test_check_regressions.py",
    "tests/test_docs_examples.py",
    "tests/test_reflex_example_assets.py",
    "tests/test_type_surface.py",
    "tests/test_verify_benchmark_report.py",
    "tests/test_verify_ci_workflow.py",
    "tests/test_verify_local.py",
    "tests/test_verify_sdist.py",
    "tests/test_verify_wheel.py",
}

FORBIDDEN_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".states",
    ".venv",
    ".web",
    "__pycache__",
    "_native_lib",
    "dist",
    "node_modules",
    "reflex.lock",
    "target",
    "wheelhouse",
}
FORBIDDEN_SUFFIXES = {".dll", ".dylib", ".pyd", ".pyc", ".pyo", ".so", ".whl"}
ROOT_RE = re.compile(r"^fastcharts-\d+\.\d+\.\d+(?:[A-Za-z0-9_.+-]*)?$")


def _member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AssertionError(f"unsafe tar member path: {name!r}")
    return path


def _normalized_files(path: str) -> tuple[str, set[str]]:
    roots: set[str] = set()
    files: set[str] = set()
    with tarfile.open(path, "r:gz") as tf:
        for member in tf.getmembers():
            member_path = _member_path(member.name)
            root = member_path.parts[0]
            roots.add(root)
            if member.isfile():
                rel = "/".join(member_path.parts[1:])
                if rel in files:
                    raise AssertionError(f"sdist contains duplicate file member: {rel}")
                files.add(rel)
            elif member.isdir():
                continue
            else:
                raise AssertionError(f"sdist contains non-regular member: {member.name}")
    if len(roots) != 1:
        raise AssertionError(
            f"sdist must have exactly one top-level directory, got {sorted(roots)}"
        )
    root = next(iter(roots))
    if not ROOT_RE.match(root):
        raise AssertionError(f"sdist top-level directory has unexpected name: {root!r}")
    return root, files


def _dependency_satisfies_floor(requirement: str, package: str, minimum: str) -> bool:
    return bool(
        re.match(
            rf"^\s*{re.escape(package)}\s*(?:\[[^\]]+\])?\s*>=\s*"
            rf"{re.escape(minimum)}(?:\b|[,;\s])",
            requirement,
            flags=re.IGNORECASE,
        )
    )


def _dependency_name(requirement: str) -> str:
    requirement = requirement.split(";", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
    return "" if match is None else match.group(1).replace("_", "-").lower()


def _is_reflex_dependency(requirement: str) -> bool:
    name = _dependency_name(requirement)
    return name == "reflex" or name.startswith("reflex-")


def _require_pkg_info(path: str, root: str) -> None:
    with tarfile.open(path, "r:gz") as tf:
        data = tf.extractfile(f"{root}/PKG-INFO")
        if data is None:
            raise AssertionError("PKG-INFO is missing")
        text = data.read().decode("utf-8")
    metadata = Parser().parsestr(text)
    missing: list[str] = []
    if metadata.get("Name", "").strip() != "fastcharts":
        missing.append("Name: fastcharts")
    project_version = _project_version()
    if metadata.get("Version", "").strip() != project_version:
        missing.append(f"Version: {project_version}")
    if metadata.get("Requires-Python", "").strip() != ">=3.11":
        missing.append("Requires-Python: >=3.11")
    requirements = metadata.get_all("Requires-Dist") or []
    for package, minimum in (("anywidget", "0.9"), ("numpy", "1.24")):
        if not any(
            _dependency_satisfies_floor(requirement, package, minimum)
            for requirement in requirements
        ):
            missing.append(f"Requires-Dist: {package}>={minimum}")
    reflex_requirements = [
        requirement for requirement in requirements if _is_reflex_dependency(requirement)
    ]
    if reflex_requirements:
        missing.append(f"no Reflex runtime dependency ({reflex_requirements})")
    if missing:
        raise AssertionError(f"missing or invalid PKG-INFO lines: {missing}")


def _project_version(pyproject_path: Path = ROOT / "pyproject.toml") -> str:
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AssertionError(f"cannot read project version from {pyproject_path}: {exc}") from exc
    version = str((data.get("project") or {}).get("version") or "").strip()
    if not version:
        raise AssertionError(f"{pyproject_path} is missing project.version")
    return version


def _require_file_contains(path: str, root: str, member: str, needles: set[str]) -> None:
    with tarfile.open(path, "r:gz") as tf:
        data = tf.extractfile(f"{root}/{member}")
        if data is None:
            raise AssertionError(f"{member} is missing")
        text = data.read().decode("utf-8")
    if len(text) < 1000:
        raise AssertionError(f"{member} is suspiciously small")
    missing = sorted(needle for needle in needles if needle not in text)
    if missing:
        raise AssertionError(f"{member} missing expected markers: {missing}")


def _require_exact_file(path: str, root: str, member: str, expected: bytes) -> None:
    with tarfile.open(path, "r:gz") as tf:
        data = tf.extractfile(f"{root}/{member}")
        if data is None:
            raise AssertionError(f"{member} is missing")
        actual = data.read()
    if actual != expected:
        raise AssertionError(f"{member} must be an empty full-package PEP 561 marker")


def _require_baseline_json(path: str, root: str) -> None:
    with tarfile.open(path, "r:gz") as tf:
        data = tf.extractfile(f"{root}/benchmarks/baseline.json")
        if data is None:
            raise AssertionError("benchmarks/baseline.json is missing")
        text = data.read().decode("utf-8")
    try:
        baseline = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"benchmarks/baseline.json is not valid JSON: {exc}") from exc
    metrics = baseline.get("metrics") if isinstance(baseline, dict) else None
    if not isinstance(metrics, dict) or not metrics:
        raise AssertionError("benchmarks/baseline.json must contain a non-empty metrics object")


def verify_sdist(path: str) -> None:
    root, files = _normalized_files(path)
    missing = sorted(REQUIRED_FILES - files)
    if missing:
        raise AssertionError(f"sdist missing required files: {missing}")

    forbidden = sorted(
        name
        for name in files
        if any(part in FORBIDDEN_PARTS for part in PurePosixPath(name).parts)
        or any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        raise AssertionError(f"sdist contains generated/native artifacts: {forbidden}")
    _require_pkg_info(path, root)
    _require_exact_file(path, root, "python/fastcharts/py.typed", b"")
    _require_baseline_json(path, root)
    _require_file_contains(
        path,
        root,
        "python/fastcharts/static/index.js",
        {"export { render", "function render(", "class ChartView"},
    )
    _require_file_contains(
        path,
        root,
        "python/fastcharts/static/standalone.js",
        {"window.fastcharts", "function renderStandalone(", "class ChartView"},
    )
    _require_file_contains(
        path,
        root,
        "js/src/60_entries.js",
        {"function render(", "function renderStandalone(", "// ---- exports ----"},
    )
    _require_file_contains(
        path,
        root,
        "README.md",
        {"Stable Vs Experimental", "Python 3.11+", "docs/api-examples.md", "make check-examples"},
    )
    _require_file_contains(
        path,
        root,
        "docs/api-examples.md",
        {
            "Chart Family Quick Reference",
            "Small Business Chart",
            "Revenue vs pipeline",
            "Figure().heatmap",
            "fc.heatmap_chart",
        },
    )
    _require_file_contains(
        path,
        root,
        "docs/benchmark.md",
        {
            "benchmark-report",
            "regression-benchmark-report",
            "docs/benchmark_metrics.md",
            "scatter.json",
            "kernel.json",
        },
    )
    _require_file_contains(
        path,
        root,
        "docs/production-readiness.md",
        {
            "Release-Blocking Gates",
            "make check-artifacts",
            "make check-examples",
            "Reflex example app",
            "package-only",
            "sdist-only",
            "scripts/verify_benchmark_report.py",
            "scripts/verify_wheel.py",
            "import fastcharts",
        },
    )
    _require_file_contains(
        path,
        root,
        "docs/contributing.md",
        {
            "Pull Request Checklist",
            "make check-full",
            "make check-sdist",
            "make check-examples",
            "make check-benchmark-report",
            "Performance Claims",
        },
    )
    _require_file_contains(
        path,
        root,
        "examples/reflex/README.md",
        {
            "fastcharts Reflex Example",
            "Business overview",
            "assets/charts/business_overview.html",
            "python scripts/build_charts.py",
        },
    )
    _require_file_contains(
        path,
        root,
        "examples/reflex/assets/charts/business_overview.html",
        {"fastcharts.renderStandalone", "Small business overview", "Revenue", "Pipeline"},
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/ci.yml",
        {"scripts/verify_ci_workflow.py", "actions/upload-artifact@v4", "continue-on-error: true"},
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/codspeed.yml",
        {"CodSpeedHQ/action@v4", "pytest-codspeed", 'k.BACKEND == "native"'},
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/release.yml",
        {
            "pypa/gh-action-pypi-publish@release/v1",
            "scripts/verify_wheel.py",
            "scripts/verify_sdist.py",
            "id-token: write",
        },
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist")
    args = parser.parse_args(argv)
    try:
        verify_sdist(args.sdist)
    except (AssertionError, KeyError, tarfile.TarError) as e:
        print(f"sdist verification failed for {args.sdist}: {e}", file=sys.stderr)
        return 1
    print(f"sdist verification OK: {args.sdist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
