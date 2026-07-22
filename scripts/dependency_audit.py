#!/usr/bin/env python3
"""Enforce the repository's multi-ecosystem vulnerability policy.

The policy and runner are stdlib-only. CI can therefore validate its complete
lock inventory, verify the scanner binary, and produce retained evidence
without first installing any project environment that it is meant to audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "spec" / "testing" / "dependency-audit-policy.json"

SEVERITIES = {"CRITICAL", "HIGH", "MODERATE", "LOW", "UNKNOWN"}
MAX_EXCEPTION_DAYS = 180
LOCK_NAMES = {"Cargo.lock", "bun.lock", "package-lock.json", "requirements-ci.lock", "uv.lock"}
DISCOVERY_IGNORES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "dist",
    "node_modules",
    "target",
    "venv",
}

REQUIRED_ENVIRONMENTS = [
    {"subsystem": "root-python", "path": "uv.lock", "format": "uv.lock"},
    {"subsystem": "docs-python", "path": "docs/app/uv.lock", "format": "uv.lock"},
    {
        "subsystem": "docs-javascript",
        "path": "docs/app/reflex.lock/bun.lock",
        "format": "bun.lock",
    },
    {
        "subsystem": "reflex-adapter-python",
        "path": "python/reflex-xy/uv.lock",
        "format": "uv.lock",
    },
    {
        "subsystem": "benchmark-python",
        "path": "benchmarks/requirements-ci.lock",
        "format": "requirements.txt",
    },
    {"subsystem": "native-rust", "path": "Cargo.lock", "format": "Cargo.lock"},
    {
        "subsystem": "browser-javascript",
        "path": "package-lock.json",
        "format": "package-lock.json",
    },
]
REQUIRED_EXCLUDED_LOCKS = [
    {
        "path": "benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/uv.lock",
        "owner": "@reflex-dev/xy",
        "reason": (
            "Immutable historical launch-measurement evidence; it is never installed or "
            "executed by a current subsystem."
        ),
    }
]
TRUSTED_SCANNER = {
    "name": "osv-scanner",
    "version": "2.4.0",
    "artifacts": {
        "darwin-arm64": {
            "url": (
                "https://github.com/google/osv-scanner/releases/download/v2.4.0/"
                "osv-scanner_darwin_arm64"
            ),
            "sha256": "9ca3185ad63e9ab54f7cb90f46a7362be02d80e37f0123d095a54355ea202f5d",
        },
        "linux-x86_64": {
            "url": (
                "https://github.com/google/osv-scanner/releases/download/v2.4.0/"
                "osv-scanner_linux_amd64"
            ),
            "sha256": "15314940c10d26af9c6649f150b8a47c1262e8fc7e17b1d1029b0e479e8ed8a0",
        },
    },
}


class AuditError(RuntimeError):
    """Raised when policy, scanner, or report evidence is incomplete."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read JSON from {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_exact_keys(value: Any, expected: set[str], label: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be an object"]
    actual = set(value)
    if actual == expected:
        return []
    return [f"{label} keys must be exactly {sorted(expected)}; got {sorted(actual)}"]


def _discover_locks(root: Path) -> set[str]:
    discovered: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file() or path.name not in LOCK_NAMES:
            continue
        relative = path.relative_to(root)
        if any(part in DISCOVERY_IGNORES for part in relative.parts[:-1]):
            continue
        discovered.add(relative.as_posix())
    return discovered


def _validate_exception(
    item: Any, index: int, *, today: date
) -> tuple[list[str], tuple[str, str, str, str] | None]:
    label = f"exceptions[{index}]"
    errors = _require_exact_keys(
        item, {"id", "package", "environment", "owner", "reason", "expires"}, label
    )
    if errors:
        return errors, None

    assert isinstance(item, dict)
    errors.extend(_require_exact_keys(item["package"], {"ecosystem", "name"}, f"{label}.package"))
    if errors:
        return errors, None
    package = item["package"]
    assert isinstance(package, dict)

    finding_id = item["id"]
    ecosystem = package["ecosystem"]
    package_name = package["name"]
    environment = item["environment"]
    for value, field in (
        (finding_id, "id"),
        (ecosystem, "package.ecosystem"),
        (package_name, "package.name"),
    ):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:/-]*", value):
            errors.append(f"{label}.{field} must be an exact non-wildcard identifier")
    valid_environments = {item["subsystem"] for item in REQUIRED_ENVIRONMENTS}
    if environment not in valid_environments:
        errors.append(f"{label}.environment must identify one of {sorted(valid_environments)}")

    owner = item["owner"]
    if not isinstance(owner, str) or not re.fullmatch(
        r"(?:@[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)?"
        r"|[^@\s]+@[^@\s]+\.[^@\s]+)",
        owner,
    ):
        errors.append(f"{label}.owner must be a GitHub user/team or an email address")

    reason = item["reason"]
    if not isinstance(reason, str) or len(reason.strip()) < 20:
        errors.append(f"{label}.reason must contain at least 20 non-padding characters")

    expires = item["expires"]
    expiry: date | None = None
    if not isinstance(expires, str):
        errors.append(f"{label}.expires must be an ISO 8601 date")
    else:
        try:
            expiry = date.fromisoformat(expires)
        except ValueError:
            errors.append(f"{label}.expires must be an ISO 8601 date")
    if expiry is not None:
        remaining = (expiry - today).days
        if remaining <= 0:
            errors.append(f"{label} expired on {expiry.isoformat()}")
        elif remaining > MAX_EXCEPTION_DAYS:
            errors.append(
                f"{label}.expires must be no more than {MAX_EXCEPTION_DAYS} days from review"
            )

    if errors:
        return errors, None
    assert isinstance(finding_id, str)
    assert isinstance(ecosystem, str)
    assert isinstance(package_name, str)
    assert isinstance(environment, str)
    return [], (finding_id, ecosystem, package_name, environment)


def validate_policy(
    policy_path: Path = DEFAULT_POLICY,
    *,
    root: Path = ROOT,
    today: date | None = None,
) -> dict[str, Any]:
    """Return a validated policy or raise with every detected defect."""
    policy = _read_json(policy_path)
    errors = _require_exact_keys(
        policy,
        {
            "schema_version",
            "scanner",
            "fail_severities",
            "environments",
            "excluded_locks",
            "exceptions",
        },
        "policy",
    )
    if errors:
        raise AuditError("; ".join(errors))
    assert isinstance(policy, dict)

    if policy["schema_version"] != 1:
        errors.append("schema_version must be 1")
    if policy["scanner"] != TRUSTED_SCANNER:
        errors.append("scanner must exactly match the reviewed version, URLs, and SHA-256 pins")
    fail_severities = policy["fail_severities"]
    if (
        not isinstance(fail_severities, list)
        or not all(isinstance(item, str) for item in fail_severities)
        or set(fail_severities) != SEVERITIES
    ):
        errors.append(f"fail_severities must contain every reviewed class: {sorted(SEVERITIES)}")
    elif len(fail_severities) != len(SEVERITIES):
        errors.append("fail_severities must not contain duplicate classes")
    if policy["environments"] != REQUIRED_ENVIRONMENTS:
        errors.append("environments must exactly inventory every required subsystem lock")
    if policy["excluded_locks"] != REQUIRED_EXCLUDED_LOCKS:
        errors.append("excluded_locks must exactly identify the reviewed historical fixture")

    expected_locks = {item["path"] for item in REQUIRED_ENVIRONMENTS + REQUIRED_EXCLUDED_LOCKS}
    discovered_locks = _discover_locks(root)
    missing = sorted(expected_locks - discovered_locks)
    extra = sorted(discovered_locks - expected_locks)
    if missing:
        errors.append(f"inventoried locks do not exist: {missing}")
    if extra:
        errors.append(f"unreviewed committed-style locks are not inventoried: {extra}")
    for environment in REQUIRED_ENVIRONMENTS:
        lock = root / environment["path"]
        if lock.exists() and lock.stat().st_size == 0:
            errors.append(f"environment lock is empty: {environment['path']}")

    exceptions = policy["exceptions"]
    if not isinstance(exceptions, list):
        errors.append("exceptions must be a list")
    else:
        keys: set[tuple[str, str, str, str]] = set()
        review_date = today or datetime.now(UTC).date()
        for index, item in enumerate(exceptions):
            item_errors, key = _validate_exception(item, index, today=review_date)
            errors.extend(item_errors)
            if key is not None and key in keys:
                errors.append(f"exceptions[{index}] duplicates {key!r}")
            elif key is not None:
                keys.add(key)

    if errors:
        raise AuditError("; ".join(errors))
    return policy


def _platform_key() -> str:
    os_name = (
        "darwin"
        if sys.platform == "darwin"
        else "linux"
        if sys.platform.startswith("linux")
        else ""
    )
    machine = platform.machine().lower()
    arch = (
        "x86_64"
        if machine in {"amd64", "x86_64"}
        else "arm64"
        if machine in {"aarch64", "arm64"}
        else ""
    )
    key = f"{os_name}-{arch}"
    if not os_name or not arch:
        raise AuditError(f"unsupported scanner host: {sys.platform}/{platform.machine()}")
    return key


def _scanner_metadata(scanner: Path, policy: dict[str, Any], output_dir: Path) -> dict[str, str]:
    platform_key = _platform_key()
    artifact = policy["scanner"]["artifacts"].get(platform_key)
    if artifact is None:
        raise AuditError(f"policy has no reviewed scanner artifact for {platform_key}")
    if not scanner.is_file():
        raise AuditError(f"scanner executable does not exist: {scanner}")
    actual_hash = _sha256(scanner)
    if actual_hash != artifact["sha256"]:
        raise AuditError(
            f"scanner SHA-256 mismatch for {platform_key}: got {actual_hash}, "
            f"expected {artifact['sha256']}"
        )

    completed = subprocess.run(
        [str(scanner), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    version_text = (completed.stdout + completed.stderr).strip()
    (output_dir / "scanner-version.txt").write_text(version_text + "\n", encoding="utf-8")
    if completed.returncode:
        raise AuditError(f"scanner --version exited {completed.returncode}: {version_text}")

    fields: dict[str, str] = {}
    for line in version_text.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            fields[key.strip()] = value.strip()
    version = fields.get("osv-scanner version")
    commit = fields.get("commit", "")
    built_at = fields.get("built at", "")
    if version != policy["scanner"]["version"]:
        raise AuditError(
            f"scanner version mismatch: got {version!r}, expected {policy['scanner']['version']!r}"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AuditError("scanner version output is missing its exact commit")
    try:
        built_timestamp = datetime.fromisoformat(built_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError("scanner version output is missing its build timestamp") from exc
    if built_timestamp.utcoffset() is None:
        raise AuditError("scanner build timestamp must include its UTC offset")
    return {
        "name": policy["scanner"]["name"],
        "version": version,
        "scalibr_version": fields.get("osv-scalibr version", ""),
        "commit": commit,
        "built_at": built_at,
        "platform": platform_key,
        "sha256": actual_hash,
    }


def _severity_label(vulnerability: dict[str, Any]) -> str:
    database = vulnerability.get("database_specific")
    candidates: list[Any] = []
    if isinstance(database, dict):
        candidates.extend((database.get("severity"), database.get("cvss_score")))
    severity = vulnerability.get("severity")
    if isinstance(severity, list):
        candidates.extend(item.get("score") for item in severity if isinstance(item, dict))
    for candidate in candidates:
        if not isinstance(candidate, (str, int, float)):
            continue
        normalized = str(candidate).strip().upper()
        if normalized == "MEDIUM":
            return "MODERATE"
        if normalized in SEVERITIES:
            return normalized
        try:
            score = float(normalized)
        except ValueError:
            continue
        if score >= 9:
            return "CRITICAL"
        if score >= 7:
            return "HIGH"
        if score >= 4:
            return "MODERATE"
        if score > 0:
            return "LOW"
    return "UNKNOWN"


def evaluate_report(
    raw_report: dict[str, Any], policy: dict[str, Any], *, root: Path = ROOT
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate scanner coverage and return environments, findings, unused exceptions."""
    results = raw_report.get("results")
    if not isinstance(results, list):
        raise AuditError("raw OSV report is missing its results list")

    environment_by_path = {(root / item["path"]).resolve(): item for item in policy["environments"]}
    seen: set[Path] = set()
    environment_reports: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    exception_by_key = {
        (
            item["id"],
            item["package"]["ecosystem"],
            item["package"]["name"],
            item["environment"],
        ): item
        for item in policy["exceptions"]
    }
    used_exceptions: set[tuple[str, str, str, str]] = set()

    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise AuditError(f"raw OSV result {index} must be an object")
        source = result.get("source")
        if not isinstance(source, dict) or source.get("type") != "lockfile":
            raise AuditError(f"raw OSV result {index} is not sourced from a lockfile")
        source_path = source.get("path")
        if not isinstance(source_path, str):
            raise AuditError(f"raw OSV result {index} has no source path")
        source_candidate = Path(source_path)
        resolved = (
            source_candidate if source_candidate.is_absolute() else root / source_candidate
        ).resolve()
        environment = environment_by_path.get(resolved)
        if environment is None:
            raise AuditError(f"raw OSV report contains an unrequested source: {source_path}")
        if resolved in seen:
            raise AuditError(f"raw OSV report repeats source: {environment['path']}")
        seen.add(resolved)

        packages = result.get("packages")
        if not isinstance(packages, list) or not packages:
            raise AuditError(f"scanner found no packages in {environment['path']}")
        environment_reports.append(
            {
                **environment,
                "package_count": len(packages),
            }
        )
        for package_result in packages:
            if not isinstance(package_result, dict):
                raise AuditError(f"invalid package entry in {environment['path']}")
            package = package_result.get("package")
            if not isinstance(package, dict):
                raise AuditError(f"package metadata missing in {environment['path']}")
            name = package.get("name")
            version = package.get("version")
            ecosystem = package.get("ecosystem")
            if not all(isinstance(value, str) and value for value in (name, version, ecosystem)):
                raise AuditError(f"incomplete package identity in {environment['path']}")
            vulnerabilities = package_result.get("vulnerabilities", [])
            if not isinstance(vulnerabilities, list):
                raise AuditError(f"invalid vulnerabilities list for {ecosystem}/{name}")
            for vulnerability in vulnerabilities:
                if not isinstance(vulnerability, dict) or not isinstance(
                    vulnerability.get("id"), str
                ):
                    raise AuditError(f"vulnerability without an ID for {ecosystem}/{name}")
                finding_id = vulnerability["id"]
                key = (finding_id, ecosystem, name, environment["subsystem"])
                exception = exception_by_key.get(key)
                if exception is not None:
                    used_exceptions.add(key)
                aliases = vulnerability.get("aliases", [])
                findings.append(
                    {
                        "id": finding_id,
                        "aliases": aliases if isinstance(aliases, list) else [],
                        "summary": vulnerability.get("summary", ""),
                        "published": vulnerability.get("published"),
                        "modified": vulnerability.get("modified"),
                        "severity": _severity_label(vulnerability),
                        "raw_severity": vulnerability.get("severity", []),
                        "package": {
                            "ecosystem": ecosystem,
                            "name": name,
                            "version": version,
                        },
                        "environment": environment["subsystem"],
                        "source": environment["path"],
                        "excepted": exception is not None,
                        "exception": exception,
                    }
                )

    missing = sorted(
        environment["path"] for path, environment in environment_by_path.items() if path not in seen
    )
    if missing:
        raise AuditError(f"raw OSV report omitted required environments: {missing}")

    unused = [item for key, item in exception_by_key.items() if key not in used_exceptions]
    return environment_reports, findings, unused


def _database_metadata(cache_dir: Path) -> list[dict[str, Any]]:
    database_root = cache_dir / "osv-scanner"
    archives = sorted(database_root.glob("*/all.zip"))
    expected = {"PyPI", "crates.io", "npm"}
    actual = {path.parent.name for path in archives}
    if actual != expected:
        raise AuditError(
            f"scanner database snapshot must exactly cover {sorted(expected)}; got {sorted(actual)}"
        )
    reports: list[dict[str, Any]] = []
    for archive in archives:
        if archive.stat().st_size == 0:
            raise AuditError(f"scanner database archive is empty: {archive}")
        try:
            with zipfile.ZipFile(archive) as database_zip:
                entries = database_zip.infolist()
        except (OSError, zipfile.BadZipFile) as exc:
            raise AuditError(f"invalid scanner database archive {archive}: {exc}") from exc
        if not entries:
            raise AuditError(f"scanner database archive has no advisories: {archive}")
        latest = max(entry.date_time for entry in entries)
        reports.append(
            {
                "ecosystem": archive.parent.name,
                "retrieved_at": datetime.fromtimestamp(archive.stat().st_mtime, tz=UTC).isoformat(),
                "latest_archive_entry_at": datetime(*latest, tzinfo=UTC).isoformat(),
                "archive_entry_count": len(entries),
                "archive_size_bytes": archive.stat().st_size,
                "archive_sha256": _sha256(archive),
            }
        )
    return reports


def _write_report(output: Path, report: dict[str, Any]) -> None:
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_scan(
    scanner: Path,
    output_dir: Path,
    *,
    policy_path: Path = DEFAULT_POLICY,
    root: Path = ROOT,
) -> int:
    policy = validate_policy(policy_path, root=root)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scanner = scanner.resolve()
    scanner_metadata = _scanner_metadata(scanner, policy, output_dir)
    raw_output = output_dir / "osv-results.json"
    scanner_log = output_dir / "scanner-output.txt"
    cache_dir = output_dir / "osv-databases"
    started = datetime.now(UTC)

    command = [
        str(scanner),
        "scan",
        "source",
        "--offline-vulnerabilities",
        "--download-offline-databases",
        "--format",
        "json",
        "--all-packages",
        "--output-file",
        str(raw_output),
    ]
    for environment in policy["environments"]:
        command.extend(["--lockfile", f"{environment['format']}:{environment['path']}"])
    environment = os.environ.copy()
    environment["OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY"] = str(cache_dir)
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    finished = datetime.now(UTC)
    scanner_text = completed.stdout + completed.stderr
    scanner_log.write_text(scanner_text, encoding="utf-8")
    if scanner_text:
        print(scanner_text, end="" if scanner_text.endswith("\n") else "\n")
    if completed.returncode not in {0, 1}:
        report = {
            "schema_version": 1,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "scanner": scanner_metadata,
            "scanner_exit_code": completed.returncode,
            "outcome": "scanner-error",
        }
        _write_report(output_dir / "dependency-audit.json", report)
        raise AuditError(f"OSV-Scanner exited unexpectedly with {completed.returncode}")
    if not raw_output.is_file():
        raise AuditError("OSV-Scanner did not produce its machine-readable result")

    raw_report = _read_json(raw_output)
    if not isinstance(raw_report, dict):
        raise AuditError("raw OSV report must be an object")
    environments, findings, unused_exceptions = evaluate_report(raw_report, policy, root=root)
    databases = _database_metadata(cache_dir)
    blocking = [
        item
        for item in findings
        if not item["excepted"] and item["severity"] in policy["fail_severities"]
    ]
    if completed.returncode == 1 and not findings:
        raise AuditError("OSV-Scanner reported vulnerabilities but emitted no findings")

    outcome = "pass" if not blocking and not unused_exceptions else "fail"
    try:
        report_policy_path = policy_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        report_policy_path = str(policy_path.resolve())
    report = {
        "schema_version": 1,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "policy": {
            "path": report_policy_path,
            "sha256": _sha256(policy_path),
            "fail_severities": policy["fail_severities"],
            "exception_count": len(policy["exceptions"]),
        },
        "scanner": scanner_metadata,
        "databases": databases,
        "environments": environments,
        "findings": findings,
        "unused_exceptions": unused_exceptions,
        "summary": {
            "environment_count": len(environments),
            "package_count": sum(item["package_count"] for item in environments),
            "finding_count": len(findings),
            "excepted_finding_count": sum(item["excepted"] for item in findings),
            "blocking_finding_count": len(blocking),
            "unused_exception_count": len(unused_exceptions),
            "scanner_exit_code": completed.returncode,
            "outcome": outcome,
        },
    }
    _write_report(output_dir / "dependency-audit.json", report)
    print(
        "Dependency audit "
        f"{outcome}: {report['summary']['package_count']} packages across "
        f"{len(environments)} environments; {len(blocking)} blocking findings; "
        f"{len(unused_exceptions)} unused exceptions."
    )
    return 0 if outcome == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate policy and lock inventory")
    scan = subparsers.add_parser("scan", help="run the pinned scanner and enforce policy")
    scan.add_argument("--scanner", type=Path, required=True)
    scan.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            policy = validate_policy(args.policy)
            print(
                f"Dependency audit policy valid: {len(policy['environments'])} environments, "
                f"{len(policy['exceptions'])} exceptions."
            )
            return 0
        return run_scan(args.scanner, args.output_dir, policy_path=args.policy)
    except AuditError as exc:
        print(f"dependency audit error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
