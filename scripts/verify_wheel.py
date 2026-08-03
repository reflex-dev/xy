#!/usr/bin/env python3
"""Verify xy wheel artifacts before upload/install smoke tests.

The source checkout can pass every test while the wheel is still broken: missing
static JS, no `py.typed`, a native build tagged pure, or generated junk bundled
by accident. This script is intentionally stdlib-only so CI can run it before
installing the package.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import re
import sys
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Optional

try:
    from artifact_metadata import dependency_metadata_errors
except ModuleNotFoundError:  # imported by tests from the repository root
    from scripts.artifact_metadata import dependency_metadata_errors

# Mirrors verify_sdist's root-directory shape: a release version (`0.0.2`) plus
# whatever PEP 440 suffix a between-tags build appends (`0.0.3.dev4+g63c0697`).
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[A-Za-z0-9_.+!]*)?$")

REQUIRED_FILES = {
    "reflex_xy/__init__.py",
    "reflex_xy/app.py",
    "reflex_xy/assets/XYChart.jsx",
    "reflex_xy/assets/__init__.py",
    "reflex_xy/component.py",
    "reflex_xy/events.py",
    "reflex_xy/namespace.py",
    "reflex_xy/payload_asset.py",
    "reflex_xy/py.typed",
    "reflex_xy/registry.py",
    "reflex_xy/selections.py",
    "reflex_xy/state_bridge.py",
    "reflex_xy/tokens.py",
    "reflex_xy/vars.py",
    "xy/__init__.py",
    "xy/_native.py",
    "xy/_framing.py",
    "xy/channels.py",
    "xy/channel.py",
    "xy/columns.py",
    "xy/components.py",
    "xy/config.py",
    "xy/export.py",
    "xy/_figure.py",
    "xy/marks.py",
    "xy/interaction.py",
    "xy/kernels.py",
    "xy/lod.py",
    "xy/py.typed",
    "xy/static/index.js",
    "xy/static/standalone.js",
    "xy/widget.py",
}

NATIVE_LIB_RE = re.compile(r"^xy/_native_lib/(?:libxy_core\.(?:so|dylib)|xy_core\.dll)$")
NATIVE_ARTIFACT_SUFFIXES = (".dll", ".dylib", ".pyd", ".so")
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


def _require_dist_info_version(names: set[str], expected_version: str) -> None:
    """The `.dist-info` directory must be named for the same version as the file."""
    directory = _dist_info_name(names, "METADATA").split("/", 1)[0]
    if directory != f"xy-{expected_version}.dist-info":
        raise AssertionError(
            f"wheel has {directory!r} but its filename says version {expected_version!r}"
        )


def _require_unique_archive_members(infos: list[zipfile.ZipInfo]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for info in infos:
        if info.filename in seen:
            duplicates.add(info.filename)
        seen.add(info.filename)
    if duplicates:
        raise AssertionError(f"wheel contains duplicate archive entries: {sorted(duplicates)}")


def _require_only_shippable_roots(names: set[str]) -> None:
    unexpected = sorted(
        name
        for name in names
        if name.rstrip("/")
        and not (
            name.startswith(("reflex_xy/", "xy/")) or name.split("/", 1)[0].endswith(".dist-info")
        )
    )
    if unexpected:
        raise AssertionError(
            "wheel contains non-package source/example files that belong in the sdist only: "
            f"{unexpected}"
        )


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


def _filename_tag(path: Path) -> str:
    if path.suffix != ".whl":
        raise AssertionError(f"wheel artifact must end in .whl: {path.name}")
    parts = path.name[:-4].split("-")
    if len(parts) not in {5, 6}:
        raise AssertionError(
            "wheel filename must follow "
            "{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl: "
            f"{path.name}"
        )
    return "-".join(parts[-3:])


def _require_filename_tag(path: Path, tags: list[str]) -> None:
    filename_tag = _filename_tag(path)
    if filename_tag not in tags:
        raise AssertionError(
            f"wheel filename tag {filename_tag!r} is not listed in WHEEL tags {tags}"
        )


def _require_metadata(names: set[str], data: bytes, expected_version: str) -> None:
    text = data.decode("utf-8")
    metadata = Parser().parsestr(text)
    missing: list[str] = []
    if metadata.get("Name", "").strip() != "xy":
        missing.append("Name: xy")
    if metadata.get("Version", "").strip() != expected_version:
        missing.append(f"Version: {expected_version}")
    if metadata.get("Requires-Python", "").strip() != ">=3.11":
        missing.append("Requires-Python: >=3.11")
    missing.extend(dependency_metadata_errors(metadata))
    if missing:
        raise AssertionError(f"missing or invalid METADATA lines: {missing}")
    _dist_info_name(names, "METADATA")


def _filename_version(path: Path) -> str:
    """The version the wheel *claims* to be, taken from its own filename.

    pyproject no longer carries a version to compare against — it is derived
    from the git tag at build time — so the invariant this can still enforce is
    internal consistency: the filename installers key off and the METADATA pip
    records must agree. A build that resolved the version twice and differently
    (say, a tagless CI checkout mid-way through) shows up as exactly that
    disagreement.
    """
    version = path.name[:-4].split("-")[1]
    if not VERSION_RE.match(version):
        raise AssertionError(f"wheel filename has an unexpected version segment: {path.name}")
    return version


def _require_static_bundle(name: str, data: bytes, needles: set[str]) -> None:
    text = data.decode("utf-8")
    if len(text) < 1000:
        raise AssertionError(f"{name} is suspiciously small")
    missing = sorted(needle for needle in needles if needle not in text)
    if missing:
        raise AssertionError(f"{name} missing expected JS markers: {missing}")


def _require_text_markers(name: str, data: bytes, needles: set[str]) -> None:
    text = data.decode("utf-8")
    if len(text.strip()) < 20:
        raise AssertionError(f"{name} is suspiciously small")
    missing = sorted(needle for needle in needles if needle not in text)
    if missing:
        raise AssertionError(f"{name} missing expected markers: {missing}")


def _require_py_typed_marker(data: bytes, name: str = "xy/py.typed") -> None:
    if data != b"":
        raise AssertionError(f"{name} must be an empty full-package PEP 561 marker")


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _require_record(zf: zipfile.ZipFile, names: set[str]) -> None:
    record_name = _dist_info_name(names, "RECORD")
    text = zf.read(record_name).decode("utf-8")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        raise AssertionError(f"{record_name} does not list archive files")

    record_paths: list[str] = []
    records: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            raise AssertionError(f"{record_name} rows must have exactly 3 fields")
        archive_name, digest, size = row
        if not archive_name:
            raise AssertionError(f"{record_name} contains an empty archive path")
        if archive_name.startswith("/") or "\\" in archive_name or ".." in Path(archive_name).parts:
            raise AssertionError(f"{record_name} contains unsafe archive path {archive_name!r}")
        if archive_name in records:
            raise AssertionError(f"{record_name} lists {archive_name!r} more than once")
        record_paths.append(archive_name)
        records[archive_name] = (digest, size)

    archive_files = {name for name in names if not name.endswith("/")}
    listed_files = set(record_paths)
    missing = sorted(archive_files - listed_files)
    extra = sorted(listed_files - archive_files)
    if missing or extra:
        raise AssertionError(
            f"{record_name} does not match archive files; missing={missing}, extra={extra}"
        )

    for archive_name in record_paths:
        digest, size = records[archive_name]
        if archive_name == record_name:
            if digest or size:
                raise AssertionError(f"{record_name} row must have empty hash and size")
            continue
        if not digest.startswith("sha256="):
            raise AssertionError(f"{record_name} row for {archive_name} missing sha256 hash")
        expected_digest = _record_hash(zf.read(archive_name))
        if digest != f"sha256={expected_digest}":
            raise AssertionError(f"{record_name} hash mismatch for {archive_name}")
        try:
            recorded_size = int(size)
        except ValueError as exc:
            raise AssertionError(
                f"{record_name} row for {archive_name} has invalid size {size!r}"
            ) from exc
        actual_size = zf.getinfo(archive_name).file_size
        if recorded_size != actual_size:
            raise AssertionError(
                f"{record_name} size mismatch for {archive_name}: "
                f"record={recorded_size}, archive={actual_size}"
            )


def verify_wheel(path: Path, *, expect_native: Optional[bool]) -> None:
    with zipfile.ZipFile(path) as zf:
        _require_unique_archive_members(zf.infolist())
        names = set(zf.namelist())
        _require_only_shippable_roots(names)
        wheel = _parse_wheel(names, zf.read(_dist_info_name(names, "WHEEL")))
        _require_filename_tag(path, wheel.tags)
        expected_version = _filename_version(path)
        _require_dist_info_version(names, expected_version)
        _require_metadata(names, zf.read(_dist_info_name(names, "METADATA")), expected_version)
        _require_record(zf, names)

    missing = sorted(REQUIRED_FILES - names)
    if missing:
        raise AssertionError(f"wheel missing required package files: {missing}")

    with zipfile.ZipFile(path) as zf:
        _require_text_markers(
            "xy/__init__.py",
            zf.read("xy/__init__.py"),
            {"__version__", "__all__", "_EXPORTS", "__getattr__"},
        )
        _require_text_markers(
            "reflex_xy/__init__.py",
            zf.read("reflex_xy/__init__.py"),
            {"XYPlugin", "chart", "figure", "__version__", '_distribution_version("xy")'},
        )
        _require_text_markers(
            "reflex_xy/assets/XYChart.jsx",
            zf.read("reflex_xy/assets/XYChart.jsx"),
            {"XYChart", "xy_client.js"},
        )
        _require_text_markers(
            "xy/_figure.py",
            zf.read("xy/_figure.py"),
            {
                "class Figure",
                "scatter = _marks.scatter",
                "line = _marks.line",
                "def to_html(",
                "def to_png(",
            },
        )
        _require_text_markers(
            "xy/marks.py",
            zf.read("xy/marks.py"),
            {"def scatter(", "def line(", "def heatmap("},
        )
        _require_text_markers(
            "xy/components.py",
            zf.read("xy/components.py"),
            {"class Chart", "def to_html(", "def to_png(", "dict[str, Any]"},
        )
        _require_text_markers(
            "xy/export.py",
            zf.read("xy/export.py"),
            {
                "_bundled_js",
                "_json_for_inline_script",
                "_javascript_for_inline_script",
                "def html_to_png(",
                "def to_png(",
                "XY_CHROMIUM",
            },
        )
        _require_text_markers(
            "xy/kernels.py",
            zf.read("xy/kernels.py"),
            {"BACKEND", "_native", "ImportError"},
        )
        _require_py_typed_marker(zf.read("xy/py.typed"))
        _require_py_typed_marker(zf.read("reflex_xy/py.typed"), "reflex_xy/py.typed")
        _require_static_bundle(
            "xy/static/index.js",
            zf.read("xy/static/index.js"),
            # Minified bundle: assert the export aliases, not source lines.
            {"as render", "as renderStandalone", "as decodeFrame", "as ChartView"},
        )
        _require_static_bundle(
            "xy/static/standalone.js",
            zf.read("xy/static/standalone.js"),
            # Minified IIFE namespace: `var xy` is window.xy in a classic script.
            {"var xy=", ".renderStandalone=", ".decodeFrame=", ".ChartView="},
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
    unexpected_native = sorted(
        n for n in names if n.endswith(NATIVE_ARTIFACT_SUFFIXES) and not NATIVE_LIB_RE.match(n)
    )
    if unexpected_native:
        raise AssertionError(f"wheel contains unexpected native artifacts: {unexpected_native}")
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
            raise AssertionError(
                f"pure (no-native) wheel must not contain native libs: {native_libs}"
            )
        if not wheel.root_is_purelib:
            raise AssertionError("pure (no-native) wheel must set Root-Is-Purelib: true")
        if "py3-none-any" not in wheel.tags:
            raise AssertionError(
                f"pure (no-native) wheel must advertise py3-none-any, got {wheel.tags}"
            )
    elif native_libs and wheel.root_is_purelib:
        raise AssertionError("wheel contains a native lib but is tagged pure")
    elif not native_libs and not wheel.root_is_purelib:
        raise AssertionError("wheel is tagged non-pure but contains no native lib")


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
