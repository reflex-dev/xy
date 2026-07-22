#!/usr/bin/env python3
"""Enforce reviewed Python package, module, and changed-line coverage floors."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "spec" / "testing" / "coverage-policy.json"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_policy(path: Path = POLICY) -> tuple[dict[str, Any], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"cannot read coverage policy: {exc}"]
    errors: list[str] = []
    expected = {
        "schema_version",
        "coverage_format",
        "source_roots",
        "packages",
        "modules",
        "diff",
        "exclusions",
    }
    if not isinstance(data, dict) or set(data) != expected:
        return {}, [f"coverage policy must contain exactly {sorted(expected)}"]
    if data["schema_version"] != 1 or data["coverage_format"] != "coverage.py-json-v3":
        errors.append("coverage policy must use schema 1 and coverage.py-json-v3")
    roots = data["source_roots"]
    if (
        not isinstance(roots, list)
        or not roots
        or not all(isinstance(item, str) and item and not item.startswith("/") for item in roots)
    ):
        errors.append("source_roots must be a nonempty list of relative paths")
    packages = data["packages"]
    if not isinstance(packages, list) or not packages:
        errors.append("packages must be a nonempty list")
    else:
        names: set[str] = set()
        for index, package in enumerate(packages):
            fields = {
                "name",
                "path_prefix",
                "exclude_prefixes",
                "minimum_line_percent",
                "minimum_branch_percent",
            }
            if not isinstance(package, dict) or set(package) != fields:
                errors.append(f"packages[{index}] has invalid fields")
                continue
            if not isinstance(package["name"], str) or not package["name"]:
                errors.append(f"packages[{index}] needs a name")
            elif package["name"] in names:
                errors.append(f"duplicate package name {package['name']!r}")
            else:
                names.add(package["name"])
            if not isinstance(package["path_prefix"], str) or not package["path_prefix"].endswith(
                "/"
            ):
                errors.append(f"packages[{index}] path_prefix must end with /")
            excluded = package["exclude_prefixes"]
            if not isinstance(excluded, list) or not all(
                isinstance(item, str) and item.endswith("/") for item in excluded
            ):
                errors.append(f"packages[{index}] exclude_prefixes must be path prefixes")
            for field in ("minimum_line_percent", "minimum_branch_percent"):
                if not _number(package[field]) or not 0 <= package[field] <= 100:
                    errors.append(f"packages[{index}] {field} must be in [0, 100]")
    modules = data["modules"]
    if not isinstance(modules, list) or not modules:
        errors.append("modules must be a nonempty list")
    else:
        paths: set[str] = set()
        for index, module in enumerate(modules):
            fields = {"path", "minimum_line_percent", "minimum_branch_percent"}
            if not isinstance(module, dict) or set(module) != fields:
                errors.append(f"modules[{index}] has invalid fields")
                continue
            if not isinstance(module["path"], str) or not module["path"].endswith(".py"):
                errors.append(f"modules[{index}] path must name a Python file")
            elif module["path"] in paths:
                errors.append(f"duplicate module path {module['path']!r}")
            else:
                paths.add(module["path"])
            for field in ("minimum_line_percent", "minimum_branch_percent"):
                if not _number(module[field]) or not 0 <= module[field] <= 100:
                    errors.append(f"modules[{index}] {field} must be in [0, 100]")
    diff = data["diff"]
    if not isinstance(diff, dict) or set(diff) != {
        "minimum_line_percent",
        "missing_coverage_file",
    }:
        errors.append("diff must declare minimum_line_percent and missing_coverage_file")
    elif (
        not _number(diff["minimum_line_percent"])
        or not 0 <= diff["minimum_line_percent"] <= 100
        or diff["missing_coverage_file"] != "fail"
    ):
        errors.append("diff coverage must use a [0, 100] floor and fail on missing files")
    exclusions = data["exclusions"]
    if not isinstance(exclusions, list):
        errors.append("exclusions must be a list")
    else:
        for index, exclusion in enumerate(exclusions):
            if not isinstance(exclusion, dict) or set(exclusion) != {"pattern", "rationale"}:
                errors.append(f"exclusions[{index}] has invalid fields")
                continue
            if not isinstance(exclusion["pattern"], str) or not exclusion["pattern"]:
                errors.append(f"exclusions[{index}] needs a pattern")
            if (
                not isinstance(exclusion["rationale"], str)
                or len(exclusion["rationale"].strip()) < 20
            ):
                errors.append(f"exclusions[{index}] needs a substantive rationale")
    return data, errors


def load_coverage(path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"cannot read coverage JSON: {exc}"]
    errors: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("meta"), dict):
        return {}, ["coverage JSON must contain meta and files objects"]
    meta = data["meta"]
    if meta.get("format") != 3:
        errors.append("coverage JSON format must be 3")
    if meta.get("branch_coverage") is not True:
        errors.append("coverage JSON must be generated with branch coverage enabled")
    if not isinstance(data.get("files"), dict):
        errors.append("coverage JSON files must be an object")
    return data, errors


def parse_changed_lines(diff: str) -> dict[str, set[int]]:
    """Return added line numbers from a zero-context git diff."""
    result: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].split("\t", 1)[0]
            current = None if target == "/dev/null" else target.removeprefix("b/")
            continue
        match = _HUNK.match(line)
        if current is None or match is None:
            continue
        start = int(match.group(1))
        count = 1 if match.group(2) is None else int(match.group(2))
        result.setdefault(current, set()).update(range(start, start + count))
    return result


def git_changed_lines(
    base: str, head: str, source_roots: list[str], *, project_root: Path = ROOT
) -> tuple[dict[str, set[int]], list[str]]:
    command = [
        "git",
        "diff",
        "--unified=0",
        "--no-ext-diff",
        "--no-renames",
        base,
        head,
        "--",
        *source_roots,
    ]
    completed = subprocess.run(
        command, cwd=project_root, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown git error"
        return {}, [f"cannot compute changed lines for {base}..{head}: {detail}"]
    return parse_changed_lines(completed.stdout), []


def _source_files(policy: Mapping[str, Any], project_root: Path) -> set[str]:
    files: set[str] = set()
    for root in policy["source_roots"]:
        path = project_root / root
        if path.is_dir():
            files.update(
                candidate.relative_to(project_root).as_posix()
                for candidate in path.rglob("*.py")
                if "__pycache__" not in candidate.parts
            )
    return files


def _summary(files: Mapping[str, Any], paths: list[str]) -> dict[str, float | int]:
    statements = sum(int(files[path]["summary"]["num_statements"]) for path in paths)
    covered_lines = sum(int(files[path]["summary"]["covered_lines"]) for path in paths)
    branches = sum(int(files[path]["summary"]["num_branches"]) for path in paths)
    covered_branches = sum(int(files[path]["summary"]["covered_branches"]) for path in paths)
    return {
        "file_count": len(paths),
        "covered_lines": covered_lines,
        "statements": statements,
        "line_percent": _percent(covered_lines, statements),
        "covered_branches": covered_branches,
        "branches": branches,
        "branch_percent": _percent(covered_branches, branches),
    }


def _meets(
    errors: list[str], label: str, actual: Mapping[str, float | int], floor: Mapping[str, Any]
) -> None:
    for metric, key in (("line", "minimum_line_percent"), ("branch", "minimum_branch_percent")):
        value = float(actual[f"{metric}_percent"])
        minimum = float(floor[key])
        if value + 1e-9 < minimum:
            errors.append(f"{label} {metric} coverage {value:.2f}% is below {minimum:.2f}%")


def evaluate(
    coverage: Mapping[str, Any],
    policy: Mapping[str, Any],
    changed: Mapping[str, set[int]],
    *,
    project_root: Path = ROOT,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    raw_files = coverage.get("files", {})
    files = {str(path).removeprefix("./"): value for path, value in raw_files.items()}
    sources = _source_files(policy, project_root)
    exclusions = policy["exclusions"]

    def excluded(path: str) -> bool:
        return any(fnmatch(path, item["pattern"]) for item in exclusions)

    governed_sources = {path for path in sources if not excluded(path)}
    missing = sorted(governed_sources - files.keys())
    if missing:
        errors.append(f"coverage JSON is missing shipped Python files: {missing}")

    memberships: dict[str, list[str]] = {}
    for path in sorted(governed_sources):
        memberships[path] = [
            package["name"]
            for package in policy["packages"]
            if path.startswith(package["path_prefix"])
            and not any(path.startswith(prefix) for prefix in package["exclude_prefixes"])
        ]
    ambiguous = {path: names for path, names in memberships.items() if len(names) != 1}
    if ambiguous:
        errors.append(f"every shipped Python file must map to exactly one package: {ambiguous}")

    package_reports: dict[str, Any] = {}
    for package in policy["packages"]:
        paths = sorted(
            path
            for path, names in memberships.items()
            if names == [package["name"]] and path in files
        )
        if not paths:
            errors.append(f"package {package['name']!r} has no covered files")
            continue
        report = _summary(files, paths)
        report.update(
            minimum_line_percent=package["minimum_line_percent"],
            minimum_branch_percent=package["minimum_branch_percent"],
        )
        package_reports[package["name"]] = report
        _meets(errors, f"package {package['name']}", report, package)

    module_reports: dict[str, Any] = {}
    for module in policy["modules"]:
        path = module["path"]
        if path not in governed_sources:
            errors.append(f"reviewed module is absent from shipped sources: {path}")
            continue
        if path not in files:
            continue
        report = _summary(files, [path])
        report.update(
            minimum_line_percent=module["minimum_line_percent"],
            minimum_branch_percent=module["minimum_branch_percent"],
        )
        module_reports[path] = report
        _meets(errors, f"module {path}", report, module)

    diff_files: dict[str, Any] = {}
    changed_executable: set[tuple[str, int]] = set()
    covered_executable: set[tuple[str, int]] = set()
    for path, lines in sorted(changed.items()):
        if excluded(path) or path not in governed_sources:
            continue
        if path not in files:
            errors.append(f"changed shipped Python file has no coverage data: {path}")
            continue
        file_data = files[path]
        statements = set(file_data.get("executed_lines", ())) | set(
            file_data.get("missing_lines", ())
        )
        executable = set(lines) & statements
        covered_lines = executable & set(file_data.get("executed_lines", ()))
        changed_executable.update((path, line) for line in executable)
        covered_executable.update((path, line) for line in covered_lines)
        if executable:
            diff_files[path] = {
                "executable_lines": sorted(executable),
                "covered_lines": sorted(covered_lines),
                "missing_lines": sorted(executable - covered_lines),
            }
    diff_percent = _percent(len(covered_executable), len(changed_executable))
    diff_floor = float(policy["diff"]["minimum_line_percent"])
    if changed_executable and diff_percent + 1e-9 < diff_floor:
        errors.append(f"changed-line coverage {diff_percent:.2f}% is below {diff_floor:.2f}%")

    report = {
        "schema_version": 1,
        "status": "failed" if errors else "passed",
        "packages": package_reports,
        "modules": module_reports,
        "diff": {
            "minimum_line_percent": diff_floor,
            "executable_line_count": len(changed_executable),
            "covered_line_count": len(covered_executable),
            "line_percent": diff_percent,
            "files": diff_files,
        },
        "exclusions": exclusions,
        "errors": errors,
    }
    return report, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument("--base", required=True, help="base Git commit for diff coverage")
    parser.add_argument("--head", required=True, help="head Git commit for diff coverage")
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    policy, errors = load_policy(args.policy)
    coverage, coverage_errors = load_coverage(args.coverage_json)
    errors.extend(coverage_errors)
    changed: dict[str, set[int]] = {}
    if policy:
        changed, git_errors = git_changed_lines(args.base, args.head, policy["source_roots"])
        errors.extend(git_errors)
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "failed",
        "base": args.base,
        "head": args.head,
        "errors": errors,
    }
    if not errors:
        report, errors = evaluate(coverage, policy, changed)
        report.update(base=args.base, head=args.head)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if errors:
        print("coverage ratchet failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(
        "coverage ratchet OK: "
        f"{report['diff']['line_percent']:.2f}% of "
        f"{report['diff']['executable_line_count']} changed executable lines"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
