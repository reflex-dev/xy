from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_required_jobs.py"
    spec = importlib.util.spec_from_file_location("check_required_jobs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_required_jobs = _load_module()


def _needs(result: str = "success") -> dict[str, dict[str, object]]:
    return {name: {"result": result, "outputs": {}} for name in check_required_jobs.HARD_JOBS}


def test_required_aggregate_accepts_only_all_success() -> None:
    assert "reflex_adapter" in check_required_jobs.HARD_JOBS
    assert "rust_release" in check_required_jobs.HARD_JOBS
    assert "native_parity" in check_required_jobs.HARD_JOBS
    assert "javascript_semantics" in check_required_jobs.HARD_JOBS
    assert "python_coverage" in check_required_jobs.HARD_JOBS
    assert check_required_jobs.evaluate_required_jobs(_needs()) == []


def test_required_aggregate_rejects_every_non_success_conclusion() -> None:
    for conclusion in ("failure", "cancelled", "skipped", None, ""):
        needs = _needs()
        needs["test"]["result"] = conclusion
        errors = check_required_jobs.evaluate_required_jobs(needs)
        assert any("'test'" in error and repr(conclusion) in error for error in errors)


def test_required_aggregate_rejects_missing_and_unexpected_dependencies() -> None:
    needs = _needs()
    del needs["sdist"]
    needs["benchmark"] = {"result": "success"}

    errors = check_required_jobs.evaluate_required_jobs(needs)

    assert any("'sdist' is missing" in error for error in errors)
    assert any("unexpected job 'benchmark'" in error for error in errors)


def test_required_aggregate_cli_rejects_a_seeded_skip(capsys) -> None:
    needs = _needs()
    needs["wheels"]["result"] = "skipped"

    assert check_required_jobs.main(["--needs-json", json.dumps(needs)]) == 1
    assert "concluded 'skipped'" in capsys.readouterr().err


def test_required_aggregate_cli_rejects_malformed_input(capsys) -> None:
    assert check_required_jobs.main(["--needs-json", "[]"]) == 2
    assert "must be an object" in capsys.readouterr().err
