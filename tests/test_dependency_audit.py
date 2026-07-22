from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
from scripts import dependency_audit

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "spec" / "testing" / "dependency-audit-policy.json"
REVIEW_DATE = date(2026, 7, 21)


def _policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _write_policy(tmp_path: Path, policy: dict) -> Path:
    path = tmp_path / "dependency-audit-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def _exception(*, expires: str = "2026-08-20") -> dict:
    return {
        "id": "GHSA-1234-5678-9abc",
        "package": {"ecosystem": "PyPI", "name": "example"},
        "environment": "root-python",
        "owner": "@reflex-dev/xy",
        "reason": "The affected path is unreachable while the upstream fix is prepared.",
        "expires": expires,
    }


def _raw_report(root: Path, *, vulnerability: dict | None = None) -> dict:
    results = []
    for environment in dependency_audit.REQUIRED_ENVIRONMENTS:
        package = {
            "package": {
                "name": "example",
                "version": "1.0.0",
                "ecosystem": "PyPI",
            }
        }
        if vulnerability is not None and not results:
            package["vulnerabilities"] = [vulnerability]
        results.append(
            {
                "source": {
                    "path": str((root / environment["path"]).resolve()),
                    "type": "lockfile",
                },
                "packages": [package],
            }
        )
    return {"results": results}


def _write_inventory(root: Path) -> None:
    for item in dependency_audit.REQUIRED_ENVIRONMENTS + dependency_audit.REQUIRED_EXCLUDED_LOCKS:
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reviewed lock fixture\n", encoding="utf-8")


def test_current_dependency_policy_is_complete() -> None:
    policy = dependency_audit.validate_policy(today=REVIEW_DATE)

    assert policy["environments"] == dependency_audit.REQUIRED_ENVIRONMENTS
    assert set(policy["fail_severities"]) == dependency_audit.SEVERITIES
    assert policy["exceptions"] == []


def test_policy_rejects_omitted_subsystem_lock(tmp_path: Path) -> None:
    policy = _policy()
    policy["environments"] = policy["environments"][:-1]

    with pytest.raises(dependency_audit.AuditError, match="every required subsystem lock"):
        dependency_audit.validate_policy(
            _write_policy(tmp_path, policy), root=ROOT, today=REVIEW_DATE
        )


def test_policy_rejects_removed_severity_gate(tmp_path: Path) -> None:
    policy = _policy()
    policy["fail_severities"].remove("UNKNOWN")

    with pytest.raises(dependency_audit.AuditError, match="every reviewed class"):
        dependency_audit.validate_policy(
            _write_policy(tmp_path, policy), root=ROOT, today=REVIEW_DATE
        )


def test_policy_rejects_unreviewed_scanner_checksum(tmp_path: Path) -> None:
    policy = _policy()
    policy["scanner"]["artifacts"]["linux-x86_64"]["sha256"] = "0" * 64

    with pytest.raises(dependency_audit.AuditError, match="reviewed version, URLs, and SHA-256"):
        dependency_audit.validate_policy(
            _write_policy(tmp_path, policy), root=ROOT, today=REVIEW_DATE
        )


def test_policy_rejects_new_uninventoried_lock(tmp_path: Path) -> None:
    _write_inventory(tmp_path)
    extra = tmp_path / "new-subsystem" / "uv.lock"
    extra.parent.mkdir()
    extra.write_text("unreviewed lock fixture\n", encoding="utf-8")

    with pytest.raises(dependency_audit.AuditError, match="unreviewed committed-style locks"):
        dependency_audit.validate_policy(POLICY_PATH, root=tmp_path, today=REVIEW_DATE)


def test_policy_rejects_missing_inventoried_lock(tmp_path: Path) -> None:
    _write_inventory(tmp_path)
    (tmp_path / dependency_audit.REQUIRED_ENVIRONMENTS[0]["path"]).unlink()

    with pytest.raises(dependency_audit.AuditError, match="inventoried locks do not exist"):
        dependency_audit.validate_policy(POLICY_PATH, root=tmp_path, today=REVIEW_DATE)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.pop("owner"), "keys must be exactly"),
        (lambda item: item.update(environment="not-a-subsystem"), "identify one of"),
        (lambda item: item.update(reason="too short"), "at least 20"),
        (lambda item: item.update(expires="2026-07-21"), "expired"),
        (lambda item: item.update(expires="2027-07-21"), "no more than 180 days"),
    ],
)
def test_policy_rejects_unowned_unreasoned_or_invalid_exceptions(
    tmp_path: Path, mutation, message: str
) -> None:
    policy = _policy()
    item = _exception()
    mutation(item)
    policy["exceptions"] = [item]

    with pytest.raises(dependency_audit.AuditError, match=message):
        dependency_audit.validate_policy(
            _write_policy(tmp_path, policy), root=ROOT, today=REVIEW_DATE
        )


def test_policy_rejects_duplicate_exact_exceptions(tmp_path: Path) -> None:
    policy = _policy()
    policy["exceptions"] = [_exception(), copy.deepcopy(_exception())]

    with pytest.raises(dependency_audit.AuditError, match="duplicates"):
        dependency_audit.validate_policy(
            _write_policy(tmp_path, policy), root=ROOT, today=REVIEW_DATE
        )


def test_report_requires_every_environment() -> None:
    policy = _policy()
    report = _raw_report(ROOT)
    report["results"].pop()

    with pytest.raises(dependency_audit.AuditError, match="omitted required environments"):
        dependency_audit.evaluate_report(report, policy, root=ROOT)


def test_report_requires_nonempty_package_inventory() -> None:
    policy = _policy()
    report = _raw_report(ROOT)
    report["results"][0]["packages"] = []

    with pytest.raises(dependency_audit.AuditError, match="found no packages"):
        dependency_audit.evaluate_report(report, policy, root=ROOT)


def test_exact_exception_is_recorded_and_stale_exception_is_rejected() -> None:
    policy = _policy()
    policy["exceptions"] = [_exception()]
    vulnerability = {
        "id": "GHSA-1234-5678-9abc",
        "summary": "Synthetic finding",
        "database_specific": {"severity": "HIGH"},
    }

    environments, findings, unused = dependency_audit.evaluate_report(
        _raw_report(ROOT, vulnerability=vulnerability), policy, root=ROOT
    )

    assert len(environments) == len(dependency_audit.REQUIRED_ENVIRONMENTS)
    assert findings[0]["severity"] == "HIGH"
    assert findings[0]["excepted"] is True
    assert unused == []

    clean_report = _raw_report(ROOT)
    _, clean_findings, unused = dependency_audit.evaluate_report(clean_report, policy, root=ROOT)
    assert clean_findings == []
    assert unused == policy["exceptions"]


def test_exception_does_not_cross_subsystem_boundaries() -> None:
    policy = _policy()
    exception = _exception()
    exception["environment"] = "docs-python"
    policy["exceptions"] = [exception]
    vulnerability = {"id": "GHSA-1234-5678-9abc", "summary": "Synthetic finding"}

    _, findings, unused = dependency_audit.evaluate_report(
        _raw_report(ROOT, vulnerability=vulnerability), policy, root=ROOT
    )

    assert findings[0]["environment"] == "root-python"
    assert findings[0]["excepted"] is False
    assert unused == policy["exceptions"]


def test_unknown_severity_remains_a_reviewed_failure_class() -> None:
    policy = _policy()
    vulnerability = {"id": "GHSA-1234-5678-9abc", "summary": "No CVSS yet"}

    _, findings, _ = dependency_audit.evaluate_report(
        _raw_report(ROOT, vulnerability=vulnerability), policy, root=ROOT
    )

    assert findings[0]["severity"] == "UNKNOWN"
    assert findings[0]["severity"] in policy["fail_severities"]
