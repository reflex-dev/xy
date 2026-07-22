from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    scripts = ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("animation_smoke", scripts / "animation_smoke.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


animation_smoke = _load_module()


def _success_title() -> str:
    return " ".join(animation_smoke.EXPECTED_ASSERTIONS) + " events=4/4"


def _stub_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "standalone.js").write_text("window.xy = {};", encoding="utf-8")
    monkeypatch.setattr(animation_smoke, "STATIC", tmp_path)


def _stub_browser(
    monkeypatch: pytest.MonkeyPatch,
    *,
    title: str,
    returncode: int = 0,
) -> None:
    monkeypatch.setattr(
        animation_smoke.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=f"<html><head><title>{title}</title></head></html>",
            stderr="synthetic animation diagnostic",
            returncode=returncode,
        ),
    )


def test_animation_fixtures_derive_the_shared_protocol() -> None:
    scatter, _ = animation_smoke._payload([(1, 2, 3)])
    errorbar, _ = animation_smoke._errorbar_payload()
    bar, _ = animation_smoke._bar_payload([(1, 2, 3)])
    assert {scatter["protocol"], errorbar["protocol"], bar["protocol"]} == {
        animation_smoke.PROTOCOL_VERSION
    }
    for builder in (
        animation_smoke._payload,
        animation_smoke._errorbar_payload,
        animation_smoke._bar_payload,
    ):
        assert '"protocol": PROTOCOL_VERSION' in inspect.getsource(builder)


def test_animation_smoke_writes_success_evidence(monkeypatch, tmp_path: Path) -> None:
    _stub_bundle(monkeypatch, tmp_path)
    _stub_browser(monkeypatch, title=_success_title())
    evidence = tmp_path / "artifacts" / "animation.json"

    rc = animation_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["missing_assertions"] == []
    assert payload["protocol"] == animation_smoke.PROTOCOL_VERSION


def test_animation_assertion_failure_is_blocking_and_retained(monkeypatch, tmp_path: Path) -> None:
    _stub_bundle(monkeypatch, tmp_path)
    _stub_browser(monkeypatch, title=_success_title().replace("frozen=1", "frozen=0"))
    evidence = tmp_path / "animation.json"

    rc = animation_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert "frozen=1" in payload["missing_assertions"]
    assert payload["stderr_tail"] == "synthetic animation diagnostic"


def test_animation_assertions_are_matched_as_complete_tokens() -> None:
    title = _success_title().replace(" bar=1 ", " bar=0 ")

    evidence = animation_smoke._evidence(
        title=title,
        chromium="/configured/chromium",
        returncode=0,
    )

    assert evidence["status"] == "failed"
    assert evidence["missing_assertions"] == ["bar=1"]


def test_explicit_missing_chromium_does_not_fall_back(monkeypatch) -> None:
    monkeypatch.setattr(
        animation_smoke.shutil,
        "which",
        lambda candidate: "/found/fallback" if candidate == "chromium" else None,
    )

    with pytest.raises(RuntimeError, match="configured chromium not found"):
        animation_smoke._chrome("/configured/but/missing/chromium")


def test_configured_browser_missing_is_blocking_and_retained(monkeypatch, tmp_path: Path) -> None:
    _stub_bundle(monkeypatch, tmp_path)
    evidence = tmp_path / "animation-missing-browser.json"

    rc = animation_smoke.main(["/configured/but/missing/chromium", "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["chromium_returncode"] is None
    assert "configured chromium not found" in payload["title"]


def test_browser_startup_failure_is_blocking_and_retained(monkeypatch, tmp_path: Path) -> None:
    _stub_bundle(monkeypatch, tmp_path)

    def fail_to_start(*args, **kwargs):
        raise OSError("synthetic browser startup failure")

    monkeypatch.setattr(animation_smoke.subprocess, "run", fail_to_start)
    evidence = tmp_path / "animation-startup.json"

    rc = animation_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["chromium_returncode"] is None
    assert "startup failed" in payload["title"]


def test_browser_timeout_is_blocking_and_retained(monkeypatch, tmp_path: Path) -> None:
    _stub_bundle(monkeypatch, tmp_path)

    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=kwargs["timeout"],
            stderr="synthetic animation timeout diagnostic",
        )

    monkeypatch.setattr(animation_smoke.subprocess, "run", time_out)
    evidence = tmp_path / "animation-timeout.json"

    rc = animation_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["timed_out"] is True
    assert payload["chromium_returncode"] is None
    assert payload["stderr_tail"] == "synthetic animation timeout diagnostic"
