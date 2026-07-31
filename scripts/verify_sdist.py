#!/usr/bin/env python3
"""Verify xy source distributions before upload/install smoke tests.

An sdist is the escape hatch for users without a prebuilt wheel. It must carry
the Rust source, the prebuilt render-client bundles (built into it by the hatch
build hook so a from-sdist install needs no Node; §33), the package typing
marker, and the build hook, while never carrying generated caches or
platform-native binaries from a local checkout. Stdlib-only so CI can run it
before installing anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from email.parser import Parser
from pathlib import PurePosixPath
from typing import Optional

REQUIRED_FILES = {
    ".github/workflows/ci.yml",
    ".github/workflows/codspeed.yml",
    ".github/workflows/release.yml",
    ".github/workflows/release-reflex-xy.yml",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Cargo.lock",
    "Cargo.toml",
    "LICENSE",
    "Makefile",
    "PKG-INFO",
    "SECURITY.md",
    "benchmarks/__init__.py",
    "benchmarks/_browser.py",
    "benchmarks/_xy_browser.py",
    "benchmarks/baseline.json",
    "benchmarks/bench.py",
    "benchmarks/bench_2d_charts.py",
    "benchmarks/bench_pyplot_vs_matplotlib.py",
    "benchmarks/bench_dashboard.py",
    "benchmarks/bench_install.py",
    "benchmarks/bench_interaction.py",
    "benchmarks/bench_line.py",
    "benchmarks/bench_native.py",
    "benchmarks/bench_scatter_native.py",
    "benchmarks/bench_vs.py",
    "benchmarks/bench_workflows.py",
    "benchmarks/categories.py",
    "benchmarks/environment.py",
    "spec/design-dossier.md",
    "spec/api/api-examples.md",
    "spec/api/chart-roadmap.md",
    "spec/benchmarks/results.md",
    "spec/design/renderer-architecture.md",
    "spec/matplotlib/backend-xy.md",
    "spec/matplotlib/compat.md",
    "spec/matplotlib/live-canvas.md",
    "spec/process/contributing.md",
    "spec/process/production-readiness.md",
    "spec/assets/benchmark-snapshot.svg",
    "spec/assets/launch-benchmark-comparison.svg",
    "hatch_build.py",
    "pyproject.toml",
    "js/build.mjs",
    "js/tsconfig.json",
    "js/src/00_header.ts",
    "js/src/10_colormaps.ts",
    "js/src/20_theme.ts",
    "js/src/30_ticks.ts",
    "js/src/40_gl.ts",
    "js/src/45_lod.ts",
    "js/src/50_chartview.ts",
    "js/src/55_marks.ts",
    "js/src/60_entries.ts",
    "package.json",
    "package-lock.json",
    "python/xy/__init__.py",
    "python/xy/_framing.py",
    "python/xy/_native.py",
    "python/xy/channels.py",
    "python/xy/columns.py",
    "python/xy/components.py",
    "python/xy/config.py",
    "python/xy/export.py",
    "python/xy/_figure.py",
    "python/xy/backends/__init__.py",
    "python/xy/backends/backend_xy.py",
    "python/xy/backends/backend_xy_host.py",
    "python/xy/backends/backend_xy_widget.js",
    "python/xy/backends/backend_xy_widget.py",
    "python/xy/backends/display_list.py",
    "python/xy/backends/raster.py",
    "python/xy/channel.py",
    "python/xy/interaction.py",
    "python/xy/kernels.py",
    "python/xy/lod.py",
    "python/xy/plugins.py",
    "python/xy/pyplot/_compat_inventory.py",
    "python/xy/py.typed",
    "python/xy/styling/__init__.py",
    "python/xy/styling/capabilities.py",
    "python/xy/static/index.js",
    "python/xy/static/standalone.js",
    "python/xy/widget.py",
    "examples/fastapi/pyproject.toml",
    "examples/fastapi/app.py",
    "examples/fastapi/charts.py",
    "examples/fastapi/live_drilldown.py",
    "examples/reflex/pyproject.toml",
    "examples/reflex/rxconfig.py",
    "examples/reflex/xy_reflex_demo/__init__.py",
    "examples/reflex/xy_reflex_demo/xy_reflex_demo.py",
    "gallery/matplotlib-3.11.1/LICENSE",
    "gallery/matplotlib-3.11.1/README.md",
    "gallery/matplotlib-3.11.1/baseline.json",
    "gallery/matplotlib-3.11.1/extended-environment.json",
    "gallery/matplotlib-3.11.1/manifest.json",
    "gallery/matplotlib-3.11.1/provenance.json",
    "scripts/check_public_api.py",
    "scripts/gen_capability_matrix.py",
    "scripts/generate_pyplot_compat_inventory.py",
    "scripts/check_python_floor.py",
    "scripts/check_regressions.py",
    "scripts/bench_dashboard.py",
    "scripts/bench_interaction.py",
    "scripts/bench_pyplot_vs_matplotlib.py",
    "scripts/verify_ci_workflow.py",
    "scripts/verify_benchmark_report.py",
    "scripts/verify_local.py",
    "scripts/verify_reflex_xy_dist.py",
    "scripts/verify_sdist.py",
    "scripts/verify_wheel.py",
    "scripts/pyplot_gallery/__init__.py",
    "scripts/pyplot_gallery/contract.py",
    "scripts/pyplot_gallery/extended_drivers.py",
    "scripts/pyplot_gallery/extended_environment.py",
    "scripts/pyplot_gallery/metrics.py",
    "scripts/pyplot_gallery/rewrite.py",
    "scripts/pyplot_gallery/run_case.py",
    "scripts/pyplot_gallery/run_gallery.py",
    "scripts/pyplot_gallery/runtime.py",
    "spec/matplotlib/gallery-contract.md",
    "src/kernels.rs",
    "src/lib.rs",
    "tests/test_public_api.py",
    "tests/test_benchmark_environment.py",
    "tests/test_bench_pyplot_vs_matplotlib.py",
    "tests/test_check_regressions.py",
    "tests/test_example_apps.py",
    "tests/test_type_surface.py",
    "tests/test_verify_benchmark_report.py",
    "tests/test_verify_ci_workflow.py",
    "tests/test_verify_local.py",
    "tests/test_verify_reflex_xy_dist.py",
    "tests/test_verify_sdist.py",
    "tests/test_verify_wheel.py",
    "tests/backends/pyplot_svg_gallery_probe.mjs",
    "tests/backends/test_backend_xy.py",
    "tests/backends/test_backend_xy_widget.py",
    "tests/backends/test_display_list.py",
    "tests/backends/test_pyplot_svg_gallery_browser.py",
    "tests/pyplot/test_gallery_contract.py",
    "tests/pyplot/test_gallery_extended_environment.py",
    "tests/pyplot/test_gallery_metrics.py",
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
ROOT_RE = re.compile(r"^xy-\d+\.\d+\.\d+(?:[A-Za-z0-9_.+-]*)?$")


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


def _is_matplotlib_compat_extra(requirement: str) -> bool:
    compact = re.sub(r"\s+", "", requirement.lower()).replace('"', "'")
    if _dependency_name(requirement) != "matplotlib" or ";" not in compact:
        return False
    specifier, marker = compact.split(";", 1)
    constraints = set(specifier.removeprefix("matplotlib").split(","))
    return constraints == {">=3.11", "<3.12"} and marker in {
        "extra=='matplotlib'",
        "'matplotlib'==extra",
    }


def _require_pkg_info(path: str, root: str) -> None:
    with tarfile.open(path, "r:gz") as tf:
        data = tf.extractfile(f"{root}/PKG-INFO")
        if data is None:
            raise AssertionError("PKG-INFO is missing")
        text = data.read().decode("utf-8")
    metadata = Parser().parsestr(text)
    missing: list[str] = []
    if metadata.get("Name", "").strip() != "xy":
        missing.append("Name: xy")
    # pyproject no longer carries a version to compare against — it is derived
    # from the git tag at build time — so what stays checkable is the sdist's
    # internal consistency: the `xy-<version>` root directory and the PKG-INFO
    # that a wheel build reads back out of it must name the same version.
    expected_version = root.split("-", 1)[1]
    if metadata.get("Version", "").strip() != expected_version:
        missing.append(f"Version: {expected_version}")
    if metadata.get("Requires-Python", "").strip() != ">=3.11":
        missing.append("Requires-Python: >=3.11")
    requirements = metadata.get_all("Requires-Dist") or []
    for package, minimum in (("anywidget", "0.9"), ("numpy", "1.24")):
        if not any(
            _dependency_satisfies_floor(requirement, package, minimum)
            for requirement in requirements
        ):
            missing.append(f"Requires-Dist: {package}>={minimum}")
    unexpected_requirements = [
        requirement
        for requirement in requirements
        if (
            (_dependency_name(requirement) not in {"anywidget", "numpy"} or ";" in requirement)
            and not _is_matplotlib_compat_extra(requirement)
        )
    ]
    if unexpected_requirements:
        missing.append(
            "only xy runtime dependencies and the matplotlib compatibility extra "
            f"in Requires-Dist ({unexpected_requirements})"
        )
    if not any(_is_matplotlib_compat_extra(requirement) for requirement in requirements):
        missing.append("Requires-Dist: matplotlib>=3.11,<3.12; extra == 'matplotlib'")
    provided_extras = metadata.get_all("Provides-Extra") or []
    if provided_extras != ["matplotlib"]:
        missing.append(f"only the matplotlib published extra ({provided_extras})")
    if missing:
        raise AssertionError(f"missing or invalid PKG-INFO lines: {missing}")


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


def _require_gallery_contract(path: str, root: str, files: set[str]) -> None:
    gallery_root = "gallery/matplotlib-3.11.1"
    source_prefix = f"{gallery_root}/examples/"
    source_paths = sorted(
        member.removeprefix(source_prefix)
        for member in files
        if member.startswith(source_prefix) and member.endswith(".py")
    )
    if len(source_paths) != 507:
        raise AssertionError(
            f"sdist gallery must contain exactly 507 Python sources, got {len(source_paths)}"
        )
    notebook_members = [
        member for member in files if member.startswith(source_prefix) and member.endswith(".ipynb")
    ]
    if notebook_members:
        raise AssertionError("sdist gallery must not duplicate the 507 Jupyter notebooks")

    with tarfile.open(path, "r:gz") as tf:
        documents: dict[str, dict[str, object]] = {}
        for name in (
            "manifest.json",
            "baseline.json",
            "provenance.json",
            "extended-environment.json",
        ):
            member = tf.extractfile(f"{root}/{gallery_root}/{name}")
            if member is None:
                raise AssertionError(f"{gallery_root}/{name} is missing")
            try:
                documents[name] = json.loads(member.read().decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise AssertionError(f"{gallery_root}/{name} is invalid JSON: {exc}") from exc

        manifest = documents["manifest.json"]
        examples = manifest.get("examples")
        if not isinstance(examples, list) or len(examples) != 507:
            raise AssertionError("gallery manifest must describe exactly 507 examples")
        manifest_paths = [entry.get("path") for entry in examples if isinstance(entry, dict)]
        if manifest_paths != sorted(source_paths):
            raise AssertionError("gallery manifest paths do not exactly match sdist sources")
        for entry in examples:
            member = tf.extractfile(f"{root}/{source_prefix}{entry['path']}")
            if member is None:
                raise AssertionError(f"gallery source is missing: {entry['path']}")
            source = member.read()
            if hashlib.sha256(source).hexdigest() != entry.get("sha256"):
                raise AssertionError(f"gallery source hash differs: {entry['path']}")
            if len(source) != entry.get("byte_count"):
                raise AssertionError(f"gallery source byte count differs: {entry['path']}")
            if entry.get("notebook_ast_matches") is not True:
                raise AssertionError(f"gallery notebook AST proof is false: {entry['path']}")
            if entry.get("notebook_code_ast_sha256") != entry.get("normalized_ast_sha256"):
                raise AssertionError(f"gallery notebook/source AST proof differs: {entry['path']}")

    if manifest.get("source_count") != 507 or manifest.get("notebook_count") != 507:
        raise AssertionError("gallery manifest source/notebook counts must both be 507")
    if manifest.get("pyplot_eligible_count") != 485:
        raise AssertionError("gallery manifest must contain 485 pyplot-eligible examples")
    if manifest.get("profile_counts") != {
        "extended": 13,
        "non_pyplot": 22,
        "standard": 472,
    }:
        raise AssertionError("gallery manifest profile counts changed")

    extended = documents["extended-environment.json"]
    extended_examples = extended.get("examples")
    if not isinstance(extended_examples, list) or len(extended_examples) != 13:
        raise AssertionError("extended gallery environment must describe exactly 13 examples")
    extended_paths = {entry.get("path") for entry in extended_examples if isinstance(entry, dict)}
    manifest_extended_paths = {
        entry.get("path")
        for entry in examples
        if isinstance(entry, dict) and entry.get("profile") == "extended"
    }
    if extended_paths != manifest_extended_paths:
        raise AssertionError("extended gallery environment paths differ from manifest")
    if any(entry.get("argv") != [] for entry in extended_examples):
        raise AssertionError("extended gallery examples must preserve clean argv")
    if any(
        entry.get("backends", {}).get("xy") != "module://xy.backends.backend_xy"
        for entry in extended_examples
    ):
        raise AssertionError("extended gallery xy cases must use the XY backend")

    baseline = documents["baseline.json"]
    expected_baseline = {
        "source_count": 507,
        "pyplot_eligible_count": 485,
        "standard_profile_count": 472,
        "extended_profile_count": 13,
        "xy_execution_passed": 485,
        "capture_parity_passed": 485,
        "dimension_parity_passed": 485,
        "exact_dimension_parity_passed": 481,
        "visual_gate_passed": 485,
        "semantic_gate_passed": 485,
        "behavior_gate_passed": 485,
        "accepted_examples": 485,
        "temporary_waiver_count": 0,
        "acceptance_complete": True,
    }
    summary = baseline.get("summary", {})
    for key, expected in expected_baseline.items():
        if summary.get(key) != expected:
            raise AssertionError(f"gallery baseline {key} must be {expected}")
    baseline_examples = baseline.get("examples")
    if not isinstance(baseline_examples, dict) or set(baseline_examples) != set(source_paths):
        raise AssertionError("gallery baseline paths do not exactly match sdist sources")

    provenance = documents["provenance.json"]
    archive_hashes = {
        kind: metadata.get("sha256")
        for kind, metadata in provenance.get("archives", {}).items()
        if isinstance(metadata, dict)
    }
    if archive_hashes != {
        "jupyter": "bb00657280bf0dfaac11ccf56bff15e959b90ba8d0365e055e9f4ef971edf870",
        "python": "fcbf2359353c06443e7f6c5477acb82e7bbf9d79672bd2c1e597ff5e357248bc",
    }:
        raise AssertionError("gallery archive provenance hashes changed")


# Every grouped subdirectory of spec/ must survive packaging. Pinning
# individual files alone would let a whole group be dropped as long as the
# pinned member stayed, so require each group to be non-empty in its own right.
SPEC_SUBDIRS = ("api", "benchmarks", "design", "matplotlib", "process")


def _require_spec_layout(files: set[str]) -> None:
    empty = [
        name
        for name in SPEC_SUBDIRS
        if not any(f.startswith(f"spec/{name}/") and f.endswith(".md") for f in files)
    ]
    if empty:
        raise AssertionError(f"sdist has no markdown under spec/ subdirectories: {empty}")

    svgs = sorted(f for f in files if f.startswith("spec/assets/") and f.endswith(".svg"))
    if len(svgs) < 2:
        raise AssertionError(f"sdist is missing spec/assets SVG evidence snapshots: {svgs}")


def verify_sdist(path: str) -> None:
    root, files = _normalized_files(path)
    missing = sorted(REQUIRED_FILES - files)
    if missing:
        raise AssertionError(f"sdist missing required files: {missing}")
    _require_spec_layout(files)

    forbidden = sorted(
        name
        for name in files
        if any(part in FORBIDDEN_PARTS for part in PurePosixPath(name).parts)
        or any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        raise AssertionError(f"sdist contains generated/native artifacts: {forbidden}")
    _require_pkg_info(path, root)
    _require_exact_file(path, root, "python/xy/py.typed", b"")
    _require_baseline_json(path, root)
    _require_gallery_contract(path, root, files)
    _require_file_contains(
        path,
        root,
        "python/xy/static/index.js",
        # The bundle is minified (identifiers renamed), so markers are the
        # export aliases the minifier must preserve.
        {"as render", "as renderStandalone", "as decodeFrame", "as ChartView"},
    )
    _require_file_contains(
        path,
        root,
        "python/xy/static/standalone.js",
        # Minified IIFE: a top-level `var xy` namespace (window.xy in the
        # classic <script> that to_html emits) carrying the public surface.
        {"var xy=", ".renderStandalone=", ".decodeFrame=", ".ChartView="},
    )
    _require_file_contains(
        path,
        root,
        "js/src/60_entries.ts",
        {
            "export function render(",
            "export function renderStandalone(",
            "export default { render, decodeFrame };",
        },
    )
    _require_file_contains(
        path,
        root,
        "spec/api/api-examples.md",
        {
            "Chart Family Quick Reference",
            "Small Business Chart",
            "Revenue vs pipeline",
            "xy.heatmap(",
            "xy.heatmap_chart",
        },
    )
    _require_file_contains(
        path,
        root,
        "spec/benchmarks/results.md",
        {
            "benchmark-report",
            "regression-benchmark-report",
            "spec/benchmarks/metrics.md",
            "scatter.json",
            "kernel.json",
        },
    )
    _require_file_contains(
        path,
        root,
        "spec/process/production-readiness.md",
        {
            "Release-Blocking Gates",
            "make check-artifacts",
            "make check-examples",
            "example apps' source",
            "package-only",
            "sdist-only",
            "scripts/verify_benchmark_report.py",
            "scripts/verify_wheel.py",
            "import xy",
        },
    )
    _require_file_contains(
        path,
        root,
        "spec/process/contributing.md",
        {
            "Pull Request Checklist",
            "make check-full",
            "make check-sdist",
            "make check-examples",
            "make check-benchmark-report",
            "Competitive Evidence",
            "outperform every competing charting library",
        },
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/ci.yml",
        {"scripts/verify_ci_workflow.py", "actions/upload-artifact@", "continue-on-error: true"},
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/codspeed.yml",
        {"CodSpeedHQ/action@", "pytest-codspeed", 'k.BACKEND == "native"'},
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/release.yml",
        {
            "pypa/gh-action-pypi-publish@",
            "scripts/verify_wheel.py",
            "scripts/verify_sdist.py",
            "id-token: write",
        },
    )
    _require_file_contains(
        path,
        root,
        ".github/workflows/release-reflex-xy.yml",
        {
            'tags: ["reflex-xy-v*"]',
            "pypa/gh-action-pypi-publish@",
            "scripts/verify_reflex_xy_dist.py",
            "scripts/check_release_version.py --package reflex-xy",
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
