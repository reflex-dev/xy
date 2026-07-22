from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module():
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "pick_boundary_smoke", scripts / "pick_boundary_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pick_boundary_smoke = _load_module()


def _stub_fixture(monkeypatch, tmp_path: Path, *, title: str, returncode: int = 0) -> None:
    (tmp_path / "standalone.js").write_text("window.xy = {};", encoding="utf-8")
    monkeypatch.setattr(pick_boundary_smoke, "STATIC", tmp_path)
    monkeypatch.setattr(
        pick_boundary_smoke,
        "build_payload",
        lambda: ({"protocol": 4}, b"", {"protocol": 4}, b""),
    )
    monkeypatch.setattr(
        pick_boundary_smoke.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=f"<html><head><title>{title}</title></head></html>",
            stderr="synthetic browser diagnostic",
            returncode=returncode,
        ),
    )


def test_pick_boundary_smoke_writes_success_evidence(monkeypatch, tmp_path: Path) -> None:
    _stub_fixture(
        monkeypatch,
        tmp_path,
        title="XY_OK slots=0,127,253,254,255 big=69999 second=1/0 hoverPickRenders=1 viewRefresh=1",
    )
    evidence = tmp_path / "artifacts" / "pick.json"

    rc = pick_boundary_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["trace_slots"][-1] == 255
    assert payload["large_pick_index"] == 69_999


def test_pick_boundary_smoke_failure_is_blocking_and_retained(monkeypatch, tmp_path: Path) -> None:
    _stub_fixture(monkeypatch, tmp_path, title="XY_FAIL slot 255: picked trace 254")
    evidence = tmp_path / "pick.json"

    rc = pick_boundary_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert "slot 255" in payload["title"]
    assert payload["stderr_tail"] == "synthetic browser diagnostic"


def test_explicit_missing_chromium_does_not_fall_back(monkeypatch) -> None:
    monkeypatch.setattr(
        pick_boundary_smoke.shutil,
        "which",
        lambda candidate: "/found/fallback" if candidate == "chromium" else None,
    )

    with pytest.raises(SystemExit, match="configured chromium not found"):
        pick_boundary_smoke.find_chromium("/configured/but/missing/chromium")


def test_pick_boundary_timeout_is_blocking_and_retained(monkeypatch, tmp_path: Path) -> None:
    _stub_fixture(monkeypatch, tmp_path, title="unused")

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs["timeout"],
            stderr="synthetic timeout diagnostic",
        )

    monkeypatch.setattr(pick_boundary_smoke.subprocess, "run", time_out)
    evidence = tmp_path / "pick-timeout.json"

    rc = pick_boundary_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["timed_out"] is True
    assert payload["chromium_returncode"] is None
    assert "timeout" in payload["title"]
    assert payload["stderr_tail"] == "synthetic timeout diagnostic"
