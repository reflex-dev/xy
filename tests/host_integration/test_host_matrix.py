from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import anywidget
from fastapi.testclient import TestClient
from scripts import host_integration_policy

from xy._figure import Figure
from xy.widget import FigureWidget, bundled_js

ROOT = Path(__file__).resolve().parents[2]
FASTAPI_DIR = ROOT / "examples" / "fastapi"


def _load_fastapi_app():
    sys.path.insert(0, str(FASTAPI_DIR))
    spec = importlib.util.spec_from_file_location(
        "xy_host_matrix_fastapi_app", FASTAPI_DIR / "app.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_installed_anywidget_and_fastapi_stack_matches_selected_profile() -> None:
    profile = os.environ.get("XY_HOST_PROFILE", "latest")
    policy = host_integration_policy.load_policy()
    errors, installed = host_integration_policy.validate_installed(
        policy, profile, ["anywidget", "fastapi"]
    )
    assert errors == []
    assert set(installed) == {
        "anywidget",
        "traitlets",
        "fastapi",
        "starlette",
        "uvicorn",
        "httpx",
    }


def test_anywidget_mount_and_binary_comm_transport() -> None:
    figure = Figure().scatter([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
    widget = FigureWidget(figure)
    sent: list[tuple[dict, object]] = []
    widget.send = lambda content, buffers=None: sent.append((content, buffers))
    try:
        assert isinstance(widget, anywidget.AnyWidget)
        assert "export" in bundled_js("widget")
        assert widget.spec["buffer_layout"] == "split"
        assert widget.buffers and all(isinstance(value, memoryview) for value in widget.buffers)

        widget._on_custom_msg(
            None,
            {"type": "pick", "trace": 0, "index": 1, "seq": 19},
            None,
        )
        assert sent[-1][0]["type"] == "pick_result"
        assert sent[-1][0]["seq"] == 19
        assert sent[-1][0]["row"]["x"] == 1.0

        widget.append(figure.traces[0].id, [3.0], [1.0])
        assert sent[-1][0]["type"] == "append"
        assert sent[-1][1] and isinstance(sent[-1][1][0], (bytes, memoryview))
    finally:
        widget.close()


def test_fastapi_compile_mount_and_http_transport(monkeypatch) -> None:
    for path in sorted(FASTAPI_DIR.glob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    monkeypatch.setenv("XY_LIVE_POINTS", "2000")
    module = _load_fastapi_app()
    with TestClient(module.app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200

        chart = client.get("/chart/line-walk")
        assert chart.status_code == 200
        assert "renderStandalone" in chart.text
        assert "<canvas" not in chart.text  # the host mounts it at runtime

        drill = client.post(
            "/api/xy/drilldown",
            json={
                "type": "density_view",
                "trace": 0,
                "x0": -1,
                "x1": 1,
                "y0": -1,
                "y1": 1,
                "w": 64,
                "h": 48,
                "seq": 7,
                "client_id": "host-matrix",
            },
        )
        assert drill.status_code == 200
        assert drill.json()["message"]["type"] == "density_update"
