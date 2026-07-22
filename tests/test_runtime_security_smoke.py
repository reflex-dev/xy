from __future__ import annotations

import html
import importlib.util
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
    spec = importlib.util.spec_from_file_location(
        "runtime_security_smoke", scripts / "runtime_security_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runtime_security_smoke = _load_module()


def _browser_output(*, failures: list[str] | None = None) -> str:
    failures = [] if failures is None else failures
    report = {
        "failures": failures,
        "surfaces": [],
        "unsafeNodes": [],
        "transientUnsafeNodes": [],
        "executed": False,
        "dialogs": [],
        "apiAttempts": [],
        "pageErrors": [],
        "cspViolations": [{"effectiveDirective": "img-src"}],
        "cssApplied": True,
        "hostileBackground": True,
        "externalResources": [],
    }
    title = "XY_RUNTIME_SECURITY_OK" if not failures else "XY_RUNTIME_SECURITY_FAIL"
    return (
        f"<html><head><title>{title}</title></head><body>"
        f'<pre id="{runtime_security_smoke.REPORT_ID}">'
        f"{html.escape(json.dumps(report))}</pre></body></html>"
    )


def _stub_browser(monkeypatch: pytest.MonkeyPatch, *, failures: list[str] | None = None) -> None:
    monkeypatch.setattr(
        runtime_security_smoke,
        "_run_browser",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=_browser_output(failures=failures),
            stderr="synthetic browser diagnostic",
            returncode=0,
        ),
    )


def test_fixture_covers_each_public_text_surface_with_hostile_input() -> None:
    sentinel = "http://127.0.0.1:45678/blocked"

    document, expectations = runtime_security_smoke.build_runtime_fixture(sentinel)

    names = {item["name"] for item in expectations}
    assert names == {
        "title",
        "x-axis title",
        "y-axis title",
        "x tick label",
        "y tick label",
        "line trace name",
        "continuous trace name",
        "category",
        "annotation",
        "legend title",
        "colorbar title",
        "tooltip title",
        "tooltip x field",
        "tooltip y field",
        "tooltip category field",
        "tooltip category value",
    }
    assert all("</script><script>" in item["text"] for item in expectations)
    assert "--xy-runtime-security-probe: applied" in document
    assert sentinel in document
    assert "window.__xyRuntimeSecurityView = xy.renderStandalone" in document
    assert document.index("Content-Security-Policy") < document.index("window.__xyRuntimeSecurity")


def test_success_is_blocking_evidence_with_explicit_sandbox_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_browser(monkeypatch)
    evidence = tmp_path / "runtime-security.json"

    rc = runtime_security_smoke.main([sys.executable, "--no-sandbox", "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["status"] == "ok"
    assert payload["launch_sandbox"] == "disabled-explicitly"
    assert payload["network_requests"] == []
    assert len(payload["expected_surfaces"]) == 16


def test_browser_assertion_failure_is_retained_and_fails_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_browser(monkeypatch, failures=["annotation did not render as literal text"])
    evidence = tmp_path / "runtime-security-failed.json"

    rc = runtime_security_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["launch_sandbox"] == "enabled"
    assert payload["browser_report"]["failures"] == ["annotation did not render as literal text"]
    assert payload["stderr_tail"] == "synthetic browser diagnostic"


def test_explicit_missing_browser_never_falls_back_and_retains_failure(tmp_path: Path) -> None:
    evidence = tmp_path / "missing-browser.json"

    rc = runtime_security_smoke.main(
        ["/configured/but/missing/chromium", "--evidence", str(evidence)]
    )

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["chromium_returncode"] is None
    assert "configured chromium not found" in payload["title"]


def test_browser_timeout_is_retained_and_fails_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def time_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0], timeout=120, stderr="synthetic runtime security timeout"
        )

    monkeypatch.setattr(runtime_security_smoke, "_run_browser", time_out)
    evidence = tmp_path / "timeout.json"

    rc = runtime_security_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["timed_out"] is True
    assert payload["chromium_returncode"] is None
    assert payload["stderr_tail"] == "synthetic runtime security timeout"


def test_loopback_request_is_a_hard_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_browser(monkeypatch)

    @runtime_security_smoke.contextmanager
    def requested_sentinel():
        yield (
            "http://127.0.0.1:1/blocked",
            [{"method": "GET", "path": "/blocked", "client": "127.0.0.1"}],
        )

    monkeypatch.setattr(runtime_security_smoke, "network_sentinel", requested_sentinel)
    evidence = tmp_path / "network-request.json"

    rc = runtime_security_smoke.main([sys.executable, "--evidence", str(evidence)])

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert rc == 1
    assert payload["status"] == "failed"
    assert payload["network_requests"][0]["method"] == "GET"
    assert payload["failures"] == ["standalone page reached the loopback network sentinel"]
