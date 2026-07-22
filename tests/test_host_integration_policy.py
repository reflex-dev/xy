from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts import host_integration_policy


def test_host_policy_matches_package_owned_requirements() -> None:
    policy = host_integration_policy.load_policy()
    assert host_integration_policy.validate_policy(policy) == []


def test_host_policy_rejects_widened_unreviewed_range() -> None:
    policy = copy.deepcopy(host_integration_policy.load_policy())
    policy["packages"]["anywidget"]["supported"] = ">=0.9"
    errors = host_integration_policy.validate_policy(policy)
    assert any("anywidget policy must exactly equal" in error for error in errors)


def test_host_policy_rejects_missing_related_dependency() -> None:
    policy = copy.deepcopy(host_integration_policy.load_policy())
    policy["hosts"]["fastapi"].remove("httpx")
    errors = host_integration_policy.validate_policy(policy)
    assert any("host ownership must exactly equal" in error for error in errors)


def test_installed_floor_validation_rejects_version_drift() -> None:
    policy = host_integration_policy.load_policy()
    errors, installed = host_integration_policy.validate_installed(
        policy,
        "floor",
        ["anywidget"],
        versions={"anywidget": "0.9.1", "traitlets": "5.14.0"},
    )
    assert installed["anywidget"] == "0.9.1"
    assert any("does not satisfy floor selector ==0.9.0" in error for error in errors)


def test_installed_validation_rejects_unknown_host() -> None:
    errors, installed = host_integration_policy.validate_installed(
        host_integration_policy.load_policy(), "latest", ["unknown"]
    )
    assert installed == {}
    assert errors == ["unknown hosts: ['unknown']"]


def test_invalid_policy_still_writes_failure_evidence(tmp_path: Path) -> None:
    policy = copy.deepcopy(host_integration_policy.load_policy())
    policy["packages"]["anywidget"]["supported"] = ">=0.9"
    report = tmp_path / "versions.json"

    errors = host_integration_policy.write_installed_report(
        report,
        policy=policy,
        profile="latest",
        hosts=["anywidget"],
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert errors
    assert payload["status"] == "failed"
    assert payload["installed"] == {}
