#!/usr/bin/env python3
"""Verify the reflex-xy release artifacts: one pure wheel plus one sdist.

The adapter is a pure-Python distribution — no native core, no platform
matrix — so its whole release surface is a single `py3-none-any` wheel and a
single sdist, built by `.github/workflows/release-reflex-xy.yml`. This checks
what that workflow uploads before it publishes:

- the wheel is genuinely pure (purelib, `py3-none-any`, no compiled
  libraries), carries the `reflex_xy` package and its `XYChart.jsx` asset,
  and carries **no copy of the render client** — the client links out of the
  installed xy package at app compile time so it can never drift
  (spec/design/reflex-integration.md §5);
- wheel `METADATA` name/version/floor/dependencies agree with the filename;
- the sdist's `PKG-INFO` agrees with its own `reflex_xy-<version>` root and
  the source tree rebuilds the wheel (pyproject + package + changelog);
- both artifacts carry the same version, never the `0.0.0` fallback (a
  tagless checkout builds that silently), and `--tag reflex-xy-vX.Y.Z` must
  match it exactly — a tagged build must never publish a dev version.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Optional

WHEEL_NAME_RE = re.compile(r"^reflex_xy-(?P<version>[^-]+)-py3-none-any\.whl$")
SDIST_NAME_RE = re.compile(r"^reflex_xy-(?P<version>[^-]+)\.tar\.gz$")
NATIVE_SUFFIXES = (".so", ".dylib", ".pyd", ".dll")
# The render client ships only inside the xy wheel; any copy here would
# drift from the kernel that produces its payloads.
RENDER_CLIENT_BASENAMES = {"index.js", "standalone.js"}
REQUIRED_WHEEL_MEMBERS = (
    "reflex_xy/__init__.py",
    "reflex_xy/assets/XYChart.jsx",
)
REQUIRED_SDIST_MEMBERS = (
    "reflex_xy/__init__.py",
    "reflex_xy/assets/XYChart.jsx",
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "PKG-INFO",
)


def _check_version_value(version: str, artifact: str, errors: list[str]) -> None:
    if version == "0.0.0":
        errors.append(
            f"{artifact} version is the 0.0.0 fallback — the build ran without "
            "git tags (shallow checkout?) and derived no real version"
        )


def _metadata_headers(text: str) -> dict[str, list[str]]:
    message = Parser().parsestr(text)
    headers: dict[str, list[str]] = {}
    for key, value in message.items():
        headers.setdefault(key, []).append(value)
    return headers


def _check_project_metadata(
    headers: dict[str, list[str]], version: str, artifact: str, errors: list[str]
) -> None:
    if headers.get("Name") != ["reflex-xy"]:
        errors.append(f"{artifact} metadata Name must be 'reflex-xy': {headers.get('Name')}")
    if headers.get("Version") != [version]:
        errors.append(
            f"{artifact} metadata Version {headers.get('Version')} does not match "
            f"the artifact's own filename version {version!r}"
        )
    if headers.get("Requires-Python") != [">=3.11"]:
        errors.append(
            f"{artifact} metadata Requires-Python must be '>=3.11': "
            f"{headers.get('Requires-Python')}"
        )
    requires = headers.get("Requires-Dist", [])
    for dependency in ("xy", "reflex"):
        if not any(re.match(rf"{dependency}\s*(?:[<>=!~(;]|$)", entry) for entry in requires):
            errors.append(f"{artifact} metadata is missing the {dependency!r} dependency")


def verify_wheel(path: Path) -> tuple[Optional[str], list[str]]:
    errors: list[str] = []
    match = WHEEL_NAME_RE.match(path.name)
    if match is None:
        return None, [
            f"unexpected wheel name {path.name!r} — the adapter builds exactly "
            "one pure 'reflex_xy-<version>-py3-none-any.whl'"
        ]
    version = match.group("version")
    _check_version_value(version, path.name, errors)
    dist_info = f"reflex_xy-{version}.dist-info"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for member in REQUIRED_WHEEL_MEMBERS + tuple(
            f"{dist_info}/{name}" for name in ("METADATA", "WHEEL", "RECORD")
        ):
            if member not in names:
                errors.append(f"{path.name} is missing {member}")
        for name in names:
            if name.endswith(NATIVE_SUFFIXES):
                errors.append(f"{path.name} contains a compiled library: {name}")
            if Path(name).name in RENDER_CLIENT_BASENAMES:
                errors.append(
                    f"{path.name} contains a render-client copy ({name}) — the "
                    "client links out of the installed xy package instead"
                )
        if f"{dist_info}/WHEEL" in names:
            wheel_headers = _metadata_headers(archive.read(f"{dist_info}/WHEEL").decode("utf-8"))
            if wheel_headers.get("Root-Is-Purelib") != ["true"]:
                errors.append(f"{path.name} WHEEL must declare Root-Is-Purelib: true")
            if wheel_headers.get("Tag") != ["py3-none-any"]:
                errors.append(
                    f"{path.name} WHEEL tag must be exactly py3-none-any: "
                    f"{wheel_headers.get('Tag')}"
                )
        if f"{dist_info}/METADATA" in names:
            headers = _metadata_headers(archive.read(f"{dist_info}/METADATA").decode("utf-8"))
            _check_project_metadata(headers, version, path.name, errors)
    return version, errors


def verify_sdist(path: Path) -> tuple[Optional[str], list[str]]:
    errors: list[str] = []
    match = SDIST_NAME_RE.match(path.name)
    if match is None:
        return None, [
            f"unexpected sdist name {path.name!r} — the adapter builds exactly "
            "one 'reflex_xy-<version>.tar.gz'"
        ]
    version = match.group("version")
    _check_version_value(version, path.name, errors)
    root = f"reflex_xy-{version}"
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        strays = [name for name in names if not (name == root or name.startswith(f"{root}/"))]
        if strays:
            errors.append(f"{path.name} has members outside {root}/: {strays[:5]}")
        members = {name.removeprefix(f"{root}/") for name in names}
        for member in REQUIRED_SDIST_MEMBERS:
            if member not in members:
                errors.append(f"{path.name} is missing {member}")
        junk = [name for name in names if "__pycache__" in name or name.endswith(".pyc")]
        if junk:
            errors.append(f"{path.name} contains generated junk: {junk[:5]}")
        if f"{root}/PKG-INFO" in names:
            pkg_info = archive.extractfile(f"{root}/PKG-INFO")
            assert pkg_info is not None
            headers = _metadata_headers(pkg_info.read().decode("utf-8"))
            _check_project_metadata(headers, version, path.name, errors)
    return version, errors


def verify_dist(paths: list[Path], tag: Optional[str] = None) -> list[str]:
    errors: list[str] = []
    versions: dict[str, Optional[str]] = {}
    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    unexpected = sorted(set(paths) - set(wheels) - set(sdists))
    if unexpected:
        errors.append(f"unexpected artifacts: {[path.name for path in unexpected]}")
    if len(wheels) != 1:
        errors.append(f"expected exactly one wheel, got {[path.name for path in wheels]}")
    if len(sdists) != 1:
        errors.append(f"expected exactly one sdist, got {[path.name for path in sdists]}")
    for wheel in wheels:
        versions[wheel.name], wheel_errors = verify_wheel(wheel)
        errors.extend(wheel_errors)
    for sdist in sdists:
        versions[sdist.name], sdist_errors = verify_sdist(sdist)
        errors.extend(sdist_errors)
    resolved = {version for version in versions.values() if version is not None}
    if len(resolved) > 1:
        errors.append(f"artifact versions disagree: {versions}")
    if tag is not None and resolved:
        expected = tag.removeprefix("reflex-xy-v")
        if tag == expected or resolved != {expected}:
            errors.append(
                f"tag {tag!r} does not match built version(s) {sorted(resolved)} — "
                "a reflex-xy-vX.Y.Z tag must produce exactly version X.Y.Z"
            )
    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="built artifacts (dist/*)")
    parser.add_argument(
        "--tag",
        default=None,
        help="release tag the artifacts must match exactly (reflex-xy-vX.Y.Z)",
    )
    args = parser.parse_args(argv)

    errors = verify_dist(args.paths, args.tag)
    if errors:
        print(f"reflex-xy dist verification failed for {args.paths}:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("reflex-xy dist verification OK: " + ", ".join(path.name for path in args.paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
