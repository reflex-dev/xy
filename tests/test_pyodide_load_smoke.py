from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _load_smoke_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "pyodide_load_smoke.py"
    spec = importlib.util.spec_from_file_location("pyodide_load_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pyodide_load_smoke = _load_smoke_module()


def test_remote_wheel_url_is_installed_directly(monkeypatch, tmp_path: Path) -> None:
    url = (
        "https://github.com/reflex-dev/xy/releases/download/v0.0.1/"
        "xy-0.0.1-py3-none-pyodide_2025_0_wasm32.whl"
    )
    observed: dict[str, object] = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["driver"] = Path(command[1]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='RESULT {"ok":true,"backend":"native","abi":34,"min":1,"max":3}\n',
            stderr="",
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pyodide_load_smoke.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["pyodide_load_smoke.py", url])

    assert pyodide_load_smoke.main() == 0
    assert observed["command"][-1] == url
    assert "await micropip.install(wheelPath)" in observed["driver"]
    assert not (tmp_path / "_pyodide_load_driver.mjs").exists()
