from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_pyplot_options.py"
    spec = importlib.util.spec_from_file_location("check_pyplot_options", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_pyplot_options = _load_module()


def _fixture(tmp_path: Path, source: str) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "python" / "xy" / "pyplot"
    source_root.mkdir(parents=True)
    (source_root / "adapter.py").write_text(source, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "contracts.py").write_text("def test_contract():\n    pass\n", encoding="utf-8")
    return source_root, tmp_path / "policy.json", tmp_path


def _write_policy(path: Path, noops: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"schema_version": 1, "noops": noops}, indent=2) + "\n",
        encoding="utf-8",
    )


def _entry(*options: str) -> dict[str, object]:
    return {
        "path": "python/xy/pyplot/adapter.py",
        "function": "adapter",
        "options": list(options),
        "rationale": "The compatibility surface deliberately preserves this bounded no-op behavior.",
        "test": "tests/contracts.py::test_contract",
    }


def test_current_pyplot_option_contract_is_exact() -> None:
    assert check_pyplot_options.validate() == []


def test_discovery_rejects_new_named_and_assigned_unused_options(tmp_path: Path) -> None:
    source_root, _policy, project_root = _fixture(
        tmp_path,
        """
def named(value, ignored=None):
    return value

def bare(**kwargs):
    kwargs.pop("mode", None)
    return 1

def assigned(**kwargs):
    dropped = kwargs.pop("dpi", None)
    return 1

def effectful(**kwargs):
    mode = kwargs.pop("mode", None)
    return mode
""",
    )
    discovered = check_pyplot_options.discover_noops(source_root, project_root=project_root)
    assert discovered == {
        check_pyplot_options.Noop("python/xy/pyplot/adapter.py", "named", "ignored"),
        check_pyplot_options.Noop("python/xy/pyplot/adapter.py", "bare", "mode"),
        check_pyplot_options.Noop("python/xy/pyplot/adapter.py", "assigned", "dpi"),
    }


def test_only_reachable_closures_can_consume_an_outer_option(tmp_path: Path) -> None:
    source_root, _policy, project_root = _fixture(
        tmp_path,
        """
def active(option):
    def consume():
        return option
    return consume()

def inactive(option):
    def never_called():
        return option
    return 1
""",
    )
    discovered = check_pyplot_options.discover_noops(source_root, project_root=project_root)
    assert discovered == {
        check_pyplot_options.Noop("python/xy/pyplot/adapter.py", "inactive", "option")
    }


def test_policy_must_exactly_match_discovery(tmp_path: Path) -> None:
    source_root, policy, project_root = _fixture(
        tmp_path, "def adapter(value, ignored=None):\n    return value\n"
    )
    _write_policy(policy, [_entry("ignored")])
    assert check_pyplot_options.validate(source_root, policy, project_root=project_root) == []

    _write_policy(policy, [])
    errors = check_pyplot_options.validate(source_root, policy, project_root=project_root)
    assert any("no reviewed contract" in error and "ignored" in error for error in errors)

    _write_policy(policy, [_entry("ignored", "stale")])
    errors = check_pyplot_options.validate(source_root, policy, project_root=project_root)
    assert any("stale no-op policy" in error and "stale" in error for error in errors)


def test_policy_rejects_weak_rationale_and_missing_behavior_test(tmp_path: Path) -> None:
    source_root, policy, project_root = _fixture(
        tmp_path, "def adapter(value, ignored=None):\n    return value\n"
    )
    entry = _entry("ignored")
    entry["rationale"] = "because"
    entry["test"] = "tests/contracts.py::test_missing"
    _write_policy(policy, [entry])
    errors = check_pyplot_options.validate(source_root, policy, project_root=project_root)
    assert any("substantive rationale" in error for error in errors)
    assert any("missing test" in error for error in errors)


def test_cli_writes_machine_readable_evidence(tmp_path: Path) -> None:
    report = tmp_path / "contract.json"
    assert check_pyplot_options.main(["--report", str(report)]) == 0
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["status"] == "passed"
    assert evidence["reviewed_noop_count"] == len(evidence["discovered"]) == 34
    assert evidence["errors"] == []
