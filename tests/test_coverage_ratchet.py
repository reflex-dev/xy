from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "coverage_ratchet.py"
    spec = importlib.util.spec_from_file_location("coverage_ratchet", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


coverage_ratchet = _load_module()


def _entry(
    executed: range | list[int],
    missing: range | list[int],
    *,
    covered_branches: int = 8,
    branches: int = 10,
) -> dict[str, object]:
    executed_lines = list(executed)
    missing_lines = list(missing)
    return {
        "executed_lines": executed_lines,
        "missing_lines": missing_lines,
        "excluded_lines": [],
        "summary": {
            "covered_lines": len(executed_lines),
            "num_statements": len(executed_lines) + len(missing_lines),
            "num_branches": branches,
            "covered_branches": covered_branches,
        },
    }


def _project(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    paths = (
        "python/xy/core.py",
        "python/xy/pyplot/plot.py",
        "python/reflex-xy/reflex_xy/component.py",
    )
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(f"value_{line} = {line}" for line in range(1, 11)), encoding="utf-8"
        )
    policy: dict[str, object] = {
        "source_roots": ["python/xy", "python/reflex-xy/reflex_xy"],
        "packages": [
            {
                "name": "core",
                "path_prefix": "python/xy/",
                "exclude_prefixes": ["python/xy/pyplot/"],
                "minimum_line_percent": 80.0,
                "minimum_branch_percent": 70.0,
            },
            {
                "name": "pyplot",
                "path_prefix": "python/xy/pyplot/",
                "exclude_prefixes": [],
                "minimum_line_percent": 80.0,
                "minimum_branch_percent": 70.0,
            },
            {
                "name": "adapter",
                "path_prefix": "python/reflex-xy/reflex_xy/",
                "exclude_prefixes": [],
                "minimum_line_percent": 80.0,
                "minimum_branch_percent": 70.0,
            },
        ],
        "modules": [
            {
                "path": "python/xy/core.py",
                "minimum_line_percent": 80.0,
                "minimum_branch_percent": 70.0,
            }
        ],
        "diff": {"minimum_line_percent": 90.0, "missing_coverage_file": "fail"},
        "exclusions": [],
    }
    coverage: dict[str, object] = {
        "files": {
            "python/xy/core.py": _entry(range(1, 10), [10]),
            "python/xy/pyplot/plot.py": _entry(range(1, 10), [10]),
            "python/reflex-xy/reflex_xy/component.py": _entry(range(1, 10), [10]),
        }
    }
    return policy, coverage


def test_current_policy_is_structured_and_reviewed() -> None:
    policy, errors = coverage_ratchet.load_policy()
    assert errors == []
    assert {package["name"] for package in policy["packages"]} == {
        "core",
        "pyplot",
        "reflex_adapter",
    }
    assert all(len(item["rationale"]) >= 20 for item in policy["exclusions"])


def test_zero_context_diff_parser_returns_exact_added_lines() -> None:
    diff = """diff --git a/python/xy/core.py b/python/xy/core.py
--- a/python/xy/core.py
+++ b/python/xy/core.py
@@ -2,0 +3,2 @@
+first
+second
@@ -9 +11 @@
-old
+new
diff --git a/python/xy/new.py b/python/xy/new.py
--- /dev/null
+++ b/python/xy/new.py
@@ -0,0 +1,3 @@
+a
+b
+c
"""
    assert coverage_ratchet.parse_changed_lines(diff) == {
        "python/xy/core.py": {3, 4, 11},
        "python/xy/new.py": {1, 2, 3},
    }


def test_package_module_and_ninety_percent_diff_floors_pass(tmp_path: Path) -> None:
    policy, coverage = _project(tmp_path)
    changed = {"python/xy/core.py": set(range(1, 11))}
    report, errors = coverage_ratchet.evaluate(coverage, policy, changed, project_root=tmp_path)
    assert errors == []
    assert report["diff"]["line_percent"] == 90.0
    assert report["diff"]["files"]["python/xy/core.py"]["missing_lines"] == [10]


def test_known_coverage_mutations_fail_package_module_and_diff_ratchets(
    tmp_path: Path,
) -> None:
    policy, coverage = _project(tmp_path)
    coverage["files"]["python/xy/core.py"] = _entry(range(1, 9), [9, 10], covered_branches=6)
    report, errors = coverage_ratchet.evaluate(
        coverage,
        policy,
        {"python/xy/core.py": set(range(1, 11))},
        project_root=tmp_path,
    )
    assert report["status"] == "failed"
    assert any("package core branch coverage" in error for error in errors)
    assert any("module python/xy/core.py branch coverage" in error for error in errors)
    assert any("changed-line coverage 80.00%" in error for error in errors)


def test_new_shipped_module_without_measurement_fails_closed(tmp_path: Path) -> None:
    policy, coverage = _project(tmp_path)
    (tmp_path / "python/xy/unmeasured.py").write_text("value = 1\n", encoding="utf-8")
    _report, errors = coverage_ratchet.evaluate(coverage, policy, {}, project_root=tmp_path)
    assert any(
        "missing shipped Python files" in error and "unmeasured.py" in error for error in errors
    )


def test_loader_rejects_non_branch_coverage_and_weak_exclusions(tmp_path: Path) -> None:
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text(
        json.dumps({"meta": {"format": 3, "branch_coverage": False}, "files": {}}),
        encoding="utf-8",
    )
    _coverage, errors = coverage_ratchet.load_coverage(coverage_path)
    assert errors == ["coverage JSON must be generated with branch coverage enabled"]

    policy, _errors = coverage_ratchet.load_policy()
    policy["exclusions"][0]["rationale"] = "weak"
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    _policy, errors = coverage_ratchet.load_policy(policy_path)
    assert any("substantive rationale" in error for error in errors)
