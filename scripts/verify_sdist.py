#!/usr/bin/env python3
"""Verify fastcharts source distributions before upload/install smoke tests.

An sdist is the escape hatch for users without a prebuilt wheel. It must carry
the Rust source, committed JS bundles, package typing marker, and build hook,
while never carrying generated caches or platform-native binaries from a local
checkout. Stdlib-only so CI can run it before installing anything.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
from pathlib import PurePosixPath
from typing import Optional

REQUIRED_FILES = {
    "Cargo.lock",
    "Cargo.toml",
    "PKG-INFO",
    "README.md",
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
    "python/fastcharts/_fallback.py",
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
    "src/kernels.rs",
    "src/lib.rs",
}

FORBIDDEN_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "_native_lib",
    "dist",
    "node_modules",
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
                files.add("/".join(member_path.parts[1:]))
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


def _require_pkg_info(path: str, root: str) -> None:
    with tarfile.open(path, "r:gz") as tf:
        data = tf.extractfile(f"{root}/PKG-INFO")
        if data is None:
            raise AssertionError("PKG-INFO is missing")
        text = data.read().decode("utf-8")
    required = {
        "Name: fastcharts",
        "Requires-Python: >=3.11",
        "Requires-Dist: anywidget>=0.9",
        "Requires-Dist: numpy>=1.24",
    }
    missing = sorted(line for line in required if line not in text)
    if missing:
        raise AssertionError(f"missing PKG-INFO lines: {missing}")


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
