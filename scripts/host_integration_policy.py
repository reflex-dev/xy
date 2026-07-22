#!/usr/bin/env python3
"""Validate host support metadata and record installed floor/latest versions."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "spec" / "testing" / "host-integration-policy.json"

EXPECTED_PACKAGES = {
    "anywidget": (">=0.9,<1", "==0.9.0"),
    "traitlets": (">=5.14,<6", "==5.14.0"),
    "reflex": (">=0.9.6,<1", "==0.9.6"),
    "fastapi": (">=0.110,<1", "==0.110.0"),
    "starlette": (">=0.36.3,<1", "==0.36.3"),
    "uvicorn": (">=0.29,<1", "==0.29.0"),
    "httpx": (">=0.27,<1", "==0.27.0"),
}
EXPECTED_HOSTS = {
    "anywidget": ["anywidget", "traitlets"],
    "reflex": ["reflex"],
    "fastapi": ["fastapi", "starlette", "uvicorn", "httpx"],
}
SOURCE_REQUIREMENTS = {
    "anywidget": [("pyproject.toml", "dependencies")],
    "traitlets": [("pyproject.toml", "dependencies")],
    "reflex": [("python/reflex-xy/pyproject.toml", "dependencies")],
    "fastapi": [
        ("pyproject.toml", "dev"),
        ("examples/fastapi/pyproject.toml", "dependencies"),
    ],
    "starlette": [
        ("pyproject.toml", "dev"),
        ("examples/fastapi/pyproject.toml", "dependencies"),
    ],
    "uvicorn": [
        ("pyproject.toml", "dev"),
        ("examples/fastapi/pyproject.toml", "dependencies"),
    ],
    "httpx": [
        ("pyproject.toml", "dev"),
        ("examples/fastapi/pyproject.toml", "dependencies"),
    ],
}


class PolicyError(RuntimeError):
    """Raised when the declared matrix and package metadata diverge."""


def load_policy(path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read host policy {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError("host policy root must be an object")
    return value


def _requirements(root: Path, relative: str, group: str) -> list[str]:
    path = root / relative
    try:
        project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise PolicyError(f"cannot read project requirements from {relative}: {exc}") from exc
    if group == "dependencies":
        values = project.get("dependencies", [])
    else:
        values = project.get("optional-dependencies", {}).get(group, [])
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise PolicyError(f"{relative} project requirement group {group!r} is not a string list")
    return values


def _requirement_for(requirements: list[str], package: str) -> str | None:
    canonical = package.lower().replace("_", "-")
    for requirement in requirements:
        name = requirement.split(";", 1)[0].split("[", 1)[0]
        for separator in ("<", ">", "=", "!", "~"):
            name = name.split(separator, 1)[0]
        if name.strip().lower().replace("_", "-") == canonical:
            return requirement.replace(" ", "")
    return None


def validate_policy(policy: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if policy.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    packages = policy.get("packages")
    if not isinstance(packages, dict) or set(packages) != set(EXPECTED_PACKAGES):
        actual = sorted(packages) if isinstance(packages, dict) else type(packages).__name__
        errors.append(f"package inventory must be exact; got {actual}")
        packages = {}
    for name, (supported, floor) in EXPECTED_PACKAGES.items():
        expected = {"distribution": name, "supported": supported, "floor": floor}
        if packages.get(name) != expected:
            errors.append(f"{name} policy must exactly equal {expected}")
    if policy.get("hosts") != EXPECTED_HOSTS:
        errors.append(f"host ownership must exactly equal {EXPECTED_HOSTS}")

    for package, sources in SOURCE_REQUIREMENTS.items():
        supported = EXPECTED_PACKAGES[package][0]
        expected_requirement = f"{package}{supported}"
        for relative, group in sources:
            try:
                actual = _requirement_for(_requirements(root, relative, group), package)
            except PolicyError as exc:
                errors.append(str(exc))
                continue
            if actual != expected_requirement:
                errors.append(
                    f"{relative} [{group}] must own {expected_requirement}; got {actual!r}"
                )
    return errors


def validate_installed(
    policy: dict[str, Any],
    profile: str,
    hosts: list[str],
    versions: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    if profile not in {"floor", "latest"}:
        return [f"unknown profile {profile!r}"], {}
    unknown = sorted(set(hosts) - set(EXPECTED_HOSTS))
    if unknown:
        return [f"unknown hosts: {unknown}"], {}
    package_names = sorted({name for host in hosts for name in EXPECTED_HOSTS[host]})
    installed: dict[str, str] = {}
    errors: list[str] = []
    for name in package_names:
        distribution = policy["packages"][name]["distribution"]
        try:
            installed[name] = (
                versions[name] if versions is not None else importlib.metadata.version(distribution)
            )
        except (KeyError, importlib.metadata.PackageNotFoundError):
            errors.append(f"required host package {distribution!r} is not installed")

    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:
        return [*errors, "packaging is required to validate host versions"], installed
    for name, version in installed.items():
        key = "floor" if profile == "floor" else "supported"
        selector = policy["packages"][name][key]
        if Version(version) not in SpecifierSet(selector):
            errors.append(f"{name} {version} does not satisfy {profile} selector {selector}")
    return errors, installed


def write_installed_report(
    path: Path,
    *,
    policy: dict[str, Any],
    profile: str,
    hosts: list[str],
) -> list[str]:
    policy_errors = validate_policy(policy)
    if policy_errors:
        version_errors, installed = [], {}
    else:
        version_errors, installed = validate_installed(policy, profile, hosts)
    errors = [*policy_errors, *version_errors]
    payload = {
        "schema_version": 1,
        "profile": profile,
        "hosts": hosts,
        "installed": installed,
        "selectors": {
            name: policy["packages"][name]["floor" if profile == "floor" else "supported"]
            for name in installed
        },
        "status": "failed" if errors else "passed",
        "errors": errors,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    report = subparsers.add_parser("report")
    report.add_argument("--profile", choices=("floor", "latest"), required=True)
    report.add_argument("--hosts", nargs="+", choices=tuple(EXPECTED_HOSTS), required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
    except PolicyError as exc:
        print(f"host integration policy error: {exc}", file=sys.stderr)
        return 1
    if args.command == "validate":
        errors = validate_policy(policy)
    else:
        errors = write_installed_report(
            args.output,
            policy=policy,
            profile=args.profile,
            hosts=args.hosts,
        )
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("host integration policy OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
