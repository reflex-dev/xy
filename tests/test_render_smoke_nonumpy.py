from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_render_smoke():
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts"
    sys.path.insert(0, str(scripts))
    path = scripts / "render_smoke_nonumpy.py"
    spec = importlib.util.spec_from_file_location("render_smoke_nonumpy", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render_smoke = _load_render_smoke()


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_run_probe_propagates_one_deadline_through_every_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = _Clock()
    calls: list[tuple[str, float]] = []
    page_path = tmp_path / "probe.html"

    class FakeSession:
        def __init__(
            self,
            _executable: str,
            *,
            gl: str,
            sandbox: bool,
            launch_timeout_s: float,
        ) -> None:
            assert (gl, sandbox) == ("software", False)
            calls.append(("launch", launch_timeout_s))
            clock.advance(40.0)

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:  # noqa: ANN001
            pass

        def _page_session(self, _page: str, timeout_s: float):
            calls.append(("page_session", timeout_s))
            clock.advance(50.0)
            return "target", "session", page_path

        def _call(
            self,
            method: str,
            _params=None,  # noqa: ANN001
            *,
            session_id: str,
            timeout_s: float,
        ):
            assert session_id == "session"
            calls.append((method, timeout_s))
            if method == "Page.navigate":
                clock.advance(60.0)
                return {}
            return {"result": {"value": "XY_OK"}}

        def _wait_event(self, method: str, *, session_id: str, timeout_s: float) -> None:
            assert (method, session_id) == ("Page.loadEventFired", "session")
            calls.append((method, timeout_s))
            clock.advance(70.0)

    monkeypatch.setattr(render_smoke.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(render_smoke.time, "sleep", clock.sleep)
    monkeypatch.setattr(render_smoke, "find_chromium", lambda: "/fake/chromium")
    monkeypatch.setattr(render_smoke, "ChromiumSession", FakeSession)

    assert render_smoke.run_probe("<title>pending</title>", timeout_s=300.0) == "XY_OK"
    assert calls == [
        ("launch", pytest.approx(300.0)),
        ("page_session", pytest.approx(260.0)),
        ("Page.navigate", pytest.approx(210.0)),
        ("Page.loadEventFired", pytest.approx(150.0)),
        ("Runtime.evaluate", pytest.approx(80.0)),
    ]


def test_run_probe_stops_setup_when_the_shared_deadline_expires(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clock = _Clock()
    calls: list[tuple[str, float]] = []
    page_path = tmp_path / "probe.html"

    class StallingSession:
        def __init__(self, _executable: str, *, launch_timeout_s: float, **_kwargs) -> None:
            calls.append(("launch", launch_timeout_s))
            clock.advance(100.0)

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:  # noqa: ANN001
            pass

        def _page_session(self, _page: str, timeout_s: float):
            calls.append(("page_session", timeout_s))
            clock.advance(100.0)
            return "target", "session", page_path

        def _call(
            self,
            method: str,
            _params=None,  # noqa: ANN001
            *,
            session_id: str,
            timeout_s: float,
        ):
            assert session_id == "session"
            calls.append((method, timeout_s))
            clock.advance(100.0)
            return {}

        def _wait_event(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise AssertionError("load wait must not start after the deadline")

    monkeypatch.setattr(render_smoke.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(render_smoke.time, "sleep", clock.sleep)
    monkeypatch.setattr(render_smoke, "find_chromium", lambda: "/fake/chromium")
    monkeypatch.setattr(render_smoke, "ChromiumSession", StallingSession)

    with pytest.raises(TimeoutError, match="within 300 seconds"):
        render_smoke.run_probe("<title>pending</title>", timeout_s=300.0)

    assert calls == [
        ("launch", pytest.approx(300.0)),
        ("page_session", pytest.approx(200.0)),
        ("Page.navigate", pytest.approx(100.0)),
    ]
