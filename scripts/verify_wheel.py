#!/usr/bin/env python3
"""Verify fastcharts wheel artifacts before upload/install smoke tests.

The source checkout can pass every test while the wheel is still broken: missing
static JS, no `py.typed`, a native build tagged pure, or generated junk bundled
by accident. This script is intentionally stdlib-only so CI can run it before
installing the package.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REQUIRED_FILES = {
    "fastcharts/__init__.py",
    "fastcharts/_fallback.py",
    "fastcharts/_native.py",
    "fastcharts/channels.py",
    "fastcharts/columns.py",
    "fastcharts/components.py",
    "fastcharts/config.py",
    "fastcharts/export.py",
    "fastcharts/figure.py",
    "fastcharts/interaction.py",
    "fastcharts/kernels.py",
    "fastcharts/lod.py",
    "fastcharts/py.typed",
    "fastcharts/static/index.js",
    "fastcharts/static/standalone.js",
    "fastcharts/widget.py",
}

NATIVE_LIB_RE = re.compile(
    r"^fastcharts/_native_lib/(?:libfastcharts_core\.(?:so|dylib)|fastcharts_core\.dll)$"
)
FORBIDDEN_PARTS = {"__pycache__", "target", "node_modules", ".pytest_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True)
class WheelInfo:
    root_is_purelib: bool
    tags: list[str]


def _dist_info_name(names: set[str], filename: str) -> str:
    matches = [n for n in names if n.endswith(f".dist-info/{filename}")]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {filename}, found {matches}")
    return matches[0]


def _parse_wheel(names: set[str], data: bytes) -> WheelInfo:
    root: Optional[bool] = None
    tags: list[str] = []
    for raw in data.decode("utf-8").splitlines():
        if raw.startswith("Root-Is-Purelib:"):
            value = raw.split(":", 1)[1].strip().lower()
            if value not in {"true", "false"}:
                raise AssertionError(f"invalid Root-Is-Purelib value {value!r}")
            root = value == "true"
        elif raw.startswith("Tag:"):
            tags.append(raw.split(":", 1)[1].strip())
    if root is None:
        raise AssertionError(f"{_dist_info_name(names, 'WHEEL')} missing Root-Is-Purelib")
    if not tags:
        raise AssertionError(f"{_dist_info_name(names, 'WHEEL')} missing Tag")
    return WheelInfo(root_is_purelib=root, tags=tags)


def _require_metadata(names: set[str], data: bytes) -> None:
    text = data.decode("utf-8")
    required = {
        "Name: fastcharts",
        "Requires-Python: >=3.11",
        "Requires-Dist: anywidget>=0.9",
        "Requires-Dist: numpy>=1.24",
    }
    missing = sorted(line for line in required if line not in text)
    if missing:
        raise AssertionError(f"missing metadata lines: {missing}")
    _dist_info_name(names, "METADATA")


def _require_static_bundle(name: str, data: bytes, needles: set[str]) -> None:
    text = data.decode("utf-8")
    if len(text) < 1000:
        raise AssertionError(f"{name} is suspiciously small")
    missing = sorted(needle for needle in needles if needle not in text)
    if missing:
        raise AssertionError(f"{name} missing expected JS markers: {missing}")


def verify_wheel(path: Path, *, expect_native: Optional[bool]) -> None:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        wheel = _parse_wheel(names, zf.read(_dist_info_name(names, "WHEEL")))
        _require_metadata(names, zf.read(_dist_info_name(names, "METADATA")))

    missing = sorted(REQUIRED_FILES - names)
    if missing:
        raise AssertionError(f"wheel missing required package files: {missing}")

    with zipfile.ZipFile(path) as zf:
        _require_static_bundle(
            "fastcharts/static/index.js",
            zf.read("fastcharts/static/index.js"),
            {"export { render", "function render(", "class ChartView"},
        )
        _require_static_bundle(
            "fastcharts/static/standalone.js",
            zf.read("fastcharts/static/standalone.js"),
            {"window.fastcharts", "function renderStandalone(", "class ChartView"},
        )

    forbidden = sorted(
        n
        for n in names
        if any(part in FORBIDDEN_PARTS for part in Path(n).parts)
        or any(n.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        raise AssertionError(f"wheel contains generated/cache files: {forbidden}")

    native_libs = sorted(n for n in names if NATIVE_LIB_RE.match(n))
    if expect_native is True:
        if len(native_libs) != 1:
            raise AssertionError(
                f"native wheel must contain exactly one native lib, got {native_libs}"
            )
        if wheel.root_is_purelib:
            raise AssertionError("native wheel must set Root-Is-Purelib: false")
        if any(tag == "py3-none-any" for tag in wheel.tags):
            raise AssertionError(f"native wheel must not use a pure tag: {wheel.tags}")
    elif expect_native is False:
        if native_libs:
            raise AssertionError(f"pure fallback wheel must not contain native libs: {native_libs}")
        if not wheel.root_is_purelib:
            raise AssertionError("pure fallback wheel must set Root-Is-Purelib: true")
        if "py3-none-any" not in wheel.tags:
            raise AssertionError(
                f"pure fallback wheel must advertise py3-none-any, got {wheel.tags}"
            )
    elif native_libs and wheel.root_is_purelib:
        raise AssertionError("wheel contains a native lib but is tagged pure")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--expect-native", action="store_true")
    group.add_argument("--expect-pure", action="store_true")
    args = parser.parse_args(argv)

    expect_native = True if args.expect_native else False if args.expect_pure else None
    try:
        verify_wheel(args.wheel, expect_native=expect_native)
    except (AssertionError, KeyError, zipfile.BadZipFile) as e:
        print(f"wheel verification failed for {args.wheel}: {e}", file=sys.stderr)
        return 1
    print(f"wheel verification OK: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
