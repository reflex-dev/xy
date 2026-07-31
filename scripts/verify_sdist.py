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
import re
import sys
import tarfile
from email.parser import Parser
from pathlib import PurePosixPath
from typing import Optional

REQUIRED_FILES = {
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Cargo.lock",
    "Cargo.toml",
    "LICENSE",
    "PKG-INFO",
    "README.md",
    "SECURITY.md",
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
    "js/src/46_worker.ts",
    "js/src/50_chartview.ts",
    "js/src/51_annotations.ts",
    "js/src/52_tooltip.ts",
    "js/src/53_interaction.ts",
    "js/src/54_kernel.ts",
    "js/src/55_marks.ts",
    "js/src/56_animation.ts",
    "js/src/57_viewstate.ts",
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
    "python/xy/channel.py",
    "python/xy/interaction.py",
    "python/xy/kernels.py",
    "python/xy/lod.py",
    "python/xy/plugins.py",
    "python/xy/py.typed",
    "python/xy/styling/__init__.py",
    "python/xy/styling/capabilities.py",
    "python/xy/static/index.js",
    "python/xy/static/standalone.js",
    "python/xy/widget.py",
    "src/css.rs",
    "src/font.rs",
    "src/kernels.rs",
    "src/lib.rs",
    "src/raster.rs",
    "src/simd.rs",
    "src/svg.rs",
    "src/tiles.rs",
    "src/transition.rs",
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
ALLOWED_TOP_LEVEL = {
    # Hatchling force-includes the active VCS exclusion file so builds from the
    # unpacked sdist preserve the source-selection rules.
    ".gitignore",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Cargo.lock",
    "Cargo.toml",
    "LICENSE",
    "PKG-INFO",
    "README.md",
    "SECURITY.md",
    "hatch_build.py",
    "js",
    "package-lock.json",
    "package.json",
    "pyproject.toml",
    "python",
    "src",
}
ROOT_RE = re.compile(r"^xy-\d+\.\d+\.\d+(?:[A-Za-z0-9_.+-]*)?$")


def _member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise AssertionError(f"unsafe tar member path: {name!r}")
    return path


def _normalized_files(path: str) -> tuple[str, set[str]]:
    roots: set[str] = set()
    files: set[str] = set()
    directories: set[str] = set()
    with tarfile.open(path, "r:gz") as tf:
        for member in tf.getmembers():
            member_path = _member_path(member.name)
            root = member_path.parts[0]
            roots.add(root)
            relative_parts = member_path.parts[1:]
            if member.isfile():
                if not relative_parts:
                    raise AssertionError(
                        f"sdist top-level entry must be a directory: {member.name!r}"
                    )
                rel = "/".join(relative_parts)
                if rel in files:
                    raise AssertionError(f"sdist contains duplicate file member: {rel}")
                files.add(rel)
            elif member.isdir():
                if relative_parts:
                    directories.add("/".join(relative_parts))
            else:
                raise AssertionError(f"sdist contains non-regular member: {member.name}")
    if len(roots) != 1:
        raise AssertionError(
            f"sdist must have exactly one top-level directory, got {sorted(roots)}"
        )
    root = next(iter(roots))
    if not ROOT_RE.match(root):
        raise AssertionError(f"sdist top-level directory has unexpected name: {root!r}")

    collisions = sorted(files & directories)
    for name in files | directories:
        parts = PurePosixPath(name).parts
        if any("/".join(parts[:index]) in files for index in range(1, len(parts))):
            collisions.append(name)
    if collisions:
        raise AssertionError(
            f"sdist contains file/directory path collisions: {sorted(set(collisions))}"
        )
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
        if _dependency_name(requirement) not in {"anywidget", "numpy"}
    ]
    if unexpected_requirements:
        missing.append(f"only xy runtime dependencies in Requires-Dist ({unexpected_requirements})")
    provided_extras = metadata.get_all("Provides-Extra") or []
    if provided_extras:
        missing.append(f"no published extras ({provided_extras})")
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


def verify_sdist(path: str) -> None:
    root, files = _normalized_files(path)
    missing = sorted(REQUIRED_FILES - files)
    if missing:
        raise AssertionError(f"sdist missing required files: {missing}")

    forbidden = sorted(
        name
        for name in files
        if PurePosixPath(name).parts[0] not in ALLOWED_TOP_LEVEL
        or (
            PurePosixPath(name).parts[0] == "python"
            and PurePosixPath(name).parts[:2] != ("python", "xy")
        )
        or any(part in FORBIDDEN_PARTS for part in PurePosixPath(name).parts)
        or any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        raise AssertionError(
            f"sdist contains repository-only/generated/native artifacts: {forbidden}"
        )
    _require_pkg_info(path, root)
    _require_exact_file(path, root, "python/xy/py.typed", b"")
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
