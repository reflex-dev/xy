from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
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
ENTRIES_JS = (
    "function render() {}\n"
    "function renderStandalone() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "// ---- exports ----\n"
)


def _load_sdist_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_sdist.py"
    spec = importlib.util.spec_from_file_location("verify_sdist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_sdist = _load_sdist_module()


def _add_file(tf: tarfile.TarFile, name: str, data: bytes = b"") -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def _write_sdist(
    path: Path,
    *,
    omit: Optional[set[str]] = None,
    extra: Optional[dict[str, bytes]] = None,
    replacements: Optional[dict[str, Union[bytes, str]]] = None,
) -> None:
    root = "fastcharts-0.1.0"
    omit = omit or set()
    extra = extra or {}
    replacements = replacements or {}
    with tarfile.open(path, "w:gz") as tf:
        for name in sorted(verify_sdist.REQUIRED_FILES - omit):
            data = b""
            if name == "PKG-INFO":
                data = (
                    b"Metadata-Version: 2.4\n"
                    b"Name: fastcharts\n"
                    b"Version: 0.1.0\n"
                    b"Requires-Python: >=3.11\n"
                    b"Requires-Dist: anywidget>=0.9\n"
                    b"Requires-Dist: numpy>=1.24\n"
                )
            if name in replacements:
                raw = replacements[name]
                data = raw.encode("utf-8") if isinstance(raw, str) else raw
            elif name == "python/fastcharts/static/index.js":
                data = INDEX_JS.encode("utf-8")
            elif name == "python/fastcharts/static/standalone.js":
                data = STANDALONE_JS.encode("utf-8")
            elif name == "js/src/60_entries.js":
                data = ENTRIES_JS.encode("utf-8")
            _add_file(tf, f"{root}/{name}", data)
        for name, data in extra.items():
            _add_file(tf, f"{root}/{name}", data)


def test_verify_sdist_accepts_required_source_shape(tmp_path: Path) -> None:
    sdist = tmp_path / "fastcharts-0.1.0.tar.gz"
    _write_sdist(sdist)

    verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_static_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "fastcharts-0.1.0.tar.gz"
    _write_sdist(sdist, omit={"python/fastcharts/static/standalone.js"})

    with pytest.raises(AssertionError, match="missing required files"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_static_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "fastcharts-0.1.0.tar.gz"
    _write_sdist(sdist, replacements={"python/fastcharts/static/index.js": "not the client"})

    with pytest.raises(AssertionError, match=r"index\.js"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_source_entry_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "fastcharts-0.1.0.tar.gz"
    _write_sdist(sdist, replacements={"js/src/60_entries.js": "not the source client"})

    with pytest.raises(AssertionError, match=r"60_entries\.js"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_generated_artifacts(tmp_path: Path) -> None:
    sdist = tmp_path / "fastcharts-0.1.0.tar.gz"
    _write_sdist(sdist, extra={"python/fastcharts/__pycache__/figure.pyc": b"cache"})

    with pytest.raises(AssertionError, match="generated/native artifacts"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_unsafe_member_paths(tmp_path: Path) -> None:
    sdist = tmp_path / "fastcharts-0.1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as tf:
        _add_file(tf, "fastcharts-0.1.0/PKG-INFO", b"Name: fastcharts\n")
        _add_file(tf, "fastcharts-0.1.0/../evil.py", b"")

    with pytest.raises(AssertionError, match="unsafe tar member path"):
        verify_sdist.verify_sdist(str(sdist))
