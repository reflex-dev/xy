from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "interaction_stress_smoke", scripts / "interaction_stress_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


interaction_stress_smoke = _load_module()


def _healthy_worker() -> dict:
    return {
        "status": "ok",
        "worker_created": True,
        "worker_rebinned": True,
        "nonblank_pixels": 981,
        "x_range_changed": True,
        "worker_terminated": True,
        "worker_cleared": True,
        "root_removed": True,
        "teardown_complete": True,
    }


def _stub_benchmark(monkeypatch: pytest.MonkeyPatch, worker: dict) -> None:
    benchmark = SimpleNamespace(
        _parse_sizes=lambda raw: [10_000],
        run=lambda **kwargs: {"kind": "interaction-browser", "rows": [], "reps": kwargs["reps"]},
        run_worker_probe=lambda **kwargs: dict(worker),
        to_markdown=lambda report: "# synthetic interaction report\n",
    )
    monkeypatch.setattr(interaction_stress_smoke, "_load_bench_interaction", lambda: benchmark)
    monkeypatch.setattr(
        interaction_stress_smoke.verify_benchmark_report,
        "validate_report",
        lambda *args, **kwargs: [],
    )


def test_worker_success_evidence_is_required_and_written(monkeypatch, tmp_path: Path) -> None:
    worker = _healthy_worker()
    _stub_benchmark(monkeypatch, worker)
    evidence = tmp_path / "artifacts" / "interaction.json"

    rc = interaction_stress_smoke.main([sys.executable, "--reps", "1", "--json", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["standalone_density_worker"] == worker


def test_skipped_worker_is_blocking_by_default(monkeypatch, capsys) -> None:
    _stub_benchmark(monkeypatch, {"status": "skipped(no chromium)"})

    rc = interaction_stress_smoke.main([sys.executable, "--reps", "1"])

    assert rc == 1
    assert "expected 'ok'" in capsys.readouterr().err


def test_explicit_local_opt_in_may_skip_unavailable_worker(monkeypatch, capsys) -> None:
    _stub_benchmark(
        monkeypatch,
        {"status": "failed(Playwright is not installed; run make setup-browser or npm install)"},
    )

    rc = interaction_stress_smoke.main([sys.executable, "--reps", "1", "--allow-worker-skip"])

    assert rc == 0
    assert "SKIPPED BY EXPLICIT LOCAL OPT-IN" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [(field, False) for field in interaction_stress_smoke.WORKER_REQUIRED_TRUE]
    + [("nonblank_pixels", 0), ("nonblank_pixels", float("nan"))],
)
def test_incomplete_worker_evidence_is_blocking(monkeypatch, capsys, field, bad_value) -> None:
    worker = _healthy_worker()
    worker[field] = bad_value
    _stub_benchmark(monkeypatch, worker)

    rc = interaction_stress_smoke.main([sys.executable, "--reps", "1"])

    assert rc == 1
    assert field in capsys.readouterr().err


def test_invalid_configured_browser_is_blocking_and_retained(tmp_path: Path) -> None:
    evidence = tmp_path / "interaction-missing-browser.json"

    rc = interaction_stress_smoke.main(
        ["/configured/but/missing/chromium", "--json", str(evidence)]
    )

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["standalone_density_worker"]["status"] == "not-run"
    assert "configured chromium not found" in payload["status"]
