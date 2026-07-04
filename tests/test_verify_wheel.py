from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path
from typing import Optional, Union

import pytest

INDEX_JS = (
    "class ChartView {}\n"
    "function render() {}\n"
    "function renderStandalone() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "export { render, renderStandalone, ChartView };\n"
)
STANDALONE_JS = (
    "class ChartView {}\n"
    "function render() {}\n"
    "function renderStandalone() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "window.fastcharts = { render, renderStandalone, ChartView };\n"
)


def _load_verify_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_wheel.py"
    spec = importlib.util.spec_from_file_location("verify_wheel", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_wheel = _load_verify_module()


def _write_wheel(
    path: Path,
    *,
    tag: str = "py3-none-macosx_11_0_arm64",
    root_is_purelib: bool = False,
    native: bool = True,
    omit: Optional[set[str]] = None,
    replacements: Optional[dict[str, Union[bytes, str]]] = None,
) -> None:
    omit = omit or set()
    replacements = replacements or {}
    with zipfile.ZipFile(path, "w") as zf:
        for name in sorted(verify_wheel.REQUIRED_FILES - omit):
            data: bytes | str = replacements.get(name, "")
            if name == "fastcharts/static/index.js" and name not in replacements:
                data = INDEX_JS
            elif name == "fastcharts/static/standalone.js" and name not in replacements:
                data = STANDALONE_JS
            zf.writestr(name, data)
        if native:
            zf.writestr("fastcharts/_native_lib/libfastcharts_core.dylib", b"native")
        zf.writestr(
            "fastcharts-0.1.0.dist-info/WHEEL",
            f"Wheel-Version: 1.0\nRoot-Is-Purelib: {str(root_is_purelib).lower()}\nTag: {tag}\n",
        )
        zf.writestr(
            "fastcharts-0.1.0.dist-info/METADATA",
            "\n".join(
                [
                    "Metadata-Version: 2.4",
                    "Name: fastcharts",
                    "Version: 0.1.0",
                    "Requires-Python: >=3.11",
                    "Requires-Dist: anywidget>=0.9",
                    "Requires-Dist: numpy>=1.24",
                ]
            ),
        )
        zf.writestr("fastcharts-0.1.0.dist-info/RECORD", "")


def test_verify_native_wheel_accepts_required_artifact_shape(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl)

    verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_missing_static_bundle(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, omit={"fastcharts/static/standalone.js"})

    with pytest.raises(AssertionError, match="required package files"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_corrupt_static_bundle(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"fastcharts/static/standalone.js": "not the client"})

    with pytest.raises(AssertionError, match=r"standalone\.js"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_rejects_native_library(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=True)

    with pytest.raises(AssertionError, match="must not contain native libs"):
        verify_wheel.verify_wheel(whl, expect_native=False)
