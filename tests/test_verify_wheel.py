from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
import zipfile
from pathlib import Path
from typing import Optional, Union

import pytest

INIT_PY = """
__version__ = "0.1.0"
_EXPORTS = {"Figure": ".figure"}
__all__ = ["Figure", "__version__"]
def __getattr__(name):
    raise AttributeError(name)
"""
FIGURE_PY = """
from . import marks as _marks
class Figure:
    line = _marks.line
    scatter = _marks.scatter
    def to_html(self): ...
    def to_png(self): ...
"""
MARKS_PY = """
def line(self, x, y): ...
def scatter(self, x, y): ...
def heatmap(self, z): ...
"""
COMPONENTS_PY = """
from typing import Any
class Chart:
    props: dict[str, Any]
    def to_html(self): ...
    def to_png(self): ...
"""
EXPORT_PY = """
FASTCHARTS_CHROMIUM = "FASTCHARTS_CHROMIUM"
def _bundled_js(which): ...
def _json_for_inline_script(value): ...
def _javascript_for_inline_script(source): ...
def html_to_png(html, width, height): ...
def to_png(fig): ...
"""
KERNELS_PY = """
try:
    from . import _native as _impl
except ImportError as err:
    raise ImportError("native core required") from err
BACKEND = "native"
"""
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
DEFAULT_METADATA = "\n".join(
    [
        "Metadata-Version: 2.4",
        "Name: fastcharts",
        "Version: 0.1.0",
        "Requires-Python: >=3.11",
        "Requires-Dist: anywidget>=0.9",
        "Requires-Dist: numpy>=1.24",
    ]
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


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _record_text(
    files: dict[str, bytes],
    record_name: str,
    *,
    omit: Optional[set[str]] = None,
    overrides: Optional[dict[str, tuple[str, str]]] = None,
) -> str:
    omit = omit or set()
    overrides = overrides or {}
    rows: list[str] = []
    for name, data in files.items():
        if name in omit:
            continue
        digest, size = overrides.get(name, (f"sha256={_record_hash(data)}", str(len(data))))
        rows.append(f"{name},{digest},{size}")
    if record_name not in omit:
        rows.append(f"{record_name},,")
    return "\n".join(rows) + "\n"


def _write_wheel(
    path: Path,
    *,
    tag: str = "py3-none-macosx_11_0_arm64",
    root_is_purelib: bool = False,
    native: bool = True,
    metadata: Optional[str] = DEFAULT_METADATA,
    omit: Optional[set[str]] = None,
    extra: Optional[dict[str, bytes]] = None,
    replacements: Optional[dict[str, Union[bytes, str]]] = None,
    record_omit: Optional[set[str]] = None,
    record_overrides: Optional[dict[str, tuple[str, str]]] = None,
    record_override: Optional[str] = None,
) -> None:
    omit = omit or set()
    extra = extra or {}
    replacements = replacements or {}
    files: dict[str, bytes] = {}

    def write(zf: zipfile.ZipFile, name: str, data: bytes | str) -> None:
        data_bytes = data.encode("utf-8") if isinstance(data, str) else data
        zf.writestr(name, data_bytes)
        files[name] = data_bytes

    with zipfile.ZipFile(path, "w") as zf:
        for name in sorted(verify_wheel.REQUIRED_FILES - omit):
            data: bytes | str = replacements.get(name, "")
            if name == "fastcharts/__init__.py" and name not in replacements:
                data = INIT_PY
            elif name == "fastcharts/figure.py" and name not in replacements:
                data = FIGURE_PY
            elif name == "fastcharts/marks.py" and name not in replacements:
                data = MARKS_PY
            elif name == "fastcharts/components.py" and name not in replacements:
                data = COMPONENTS_PY
            elif name == "fastcharts/export.py" and name not in replacements:
                data = EXPORT_PY
            elif name == "fastcharts/kernels.py" and name not in replacements:
                data = KERNELS_PY
            elif name == "fastcharts/static/index.js" and name not in replacements:
                data = INDEX_JS
            elif name == "fastcharts/static/standalone.js" and name not in replacements:
                data = STANDALONE_JS
            write(zf, name, data)
        if native:
            write(zf, "fastcharts/_native_lib/libfastcharts_core.dylib", b"native")
        for name, data in extra.items():
            write(zf, name, data)
        wheel_name = "fastcharts-0.1.0.dist-info/WHEEL"
        write(
            zf,
            wheel_name,
            (f"Wheel-Version: 1.0\nRoot-Is-Purelib: {str(root_is_purelib).lower()}\nTag: {tag}\n"),
        )
        if metadata is not None:
            write(zf, "fastcharts-0.1.0.dist-info/METADATA", metadata)
        record_name = "fastcharts-0.1.0.dist-info/RECORD"
        record_data = (
            record_override
            if record_override is not None
            else _record_text(
                files,
                record_name,
                omit=record_omit,
                overrides=record_overrides,
            )
        )
        zf.writestr(record_name, record_data)


def test_verify_native_wheel_accepts_required_artifact_shape(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl)

    verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_accepts_required_artifact_shape(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=False)

    verify_wheel.verify_wheel(whl, expect_native=False)


def test_verify_wheel_accepts_normalized_metadata_spacing(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    metadata = DEFAULT_METADATA.replace(
        "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget >= 0.9"
    ).replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy >= 1.24")
    _write_wheel(whl, metadata=metadata)

    verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_native_wheel_rejects_filename_tag_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-macosx_11_0_arm64")

    with pytest.raises(AssertionError, match="filename tag"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_rejects_filename_tag_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=False)

    with pytest.raises(AssertionError, match="filename tag"):
        verify_wheel.verify_wheel(whl, expect_native=False)


def test_verify_wheel_rejects_missing_metadata_file(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, metadata=None)

    with pytest.raises(AssertionError, match="METADATA"):
        verify_wheel.verify_wheel(whl, expect_native=True)


@pytest.mark.parametrize(
    ("metadata", "match"),
    [
        (
            DEFAULT_METADATA.replace("Name: fastcharts", "Name: othercharts"),
            "Name: fastcharts",
        ),
        (
            DEFAULT_METADATA.replace("Version: 0.1.0", "Version: 0.2.0"),
            "Version: 0.1.0",
        ),
        (
            DEFAULT_METADATA.replace("Requires-Python: >=3.11", "Requires-Python: >=3.10"),
            r"Requires-Python: >=3\.11",
        ),
        (
            DEFAULT_METADATA.replace("Requires-Dist: anywidget>=0.9", ""),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_METADATA.replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy>=1.20"),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_METADATA + "\nRequires-Dist: reflex>=0.8",
            "no Reflex runtime dependency",
        ),
    ],
)
def test_verify_wheel_rejects_invalid_metadata(tmp_path: Path, metadata: str, match: str) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, metadata=metadata)

    with pytest.raises(AssertionError, match=match):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_missing_type_marker(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, omit={"fastcharts/py.typed"})

    with pytest.raises(AssertionError, match="py\\.typed"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_partial_type_marker(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"fastcharts/py.typed": "partial\n"})

    with pytest.raises(AssertionError, match="full-package PEP 561 marker"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_corrupt_python_module(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"fastcharts/__init__.py": ""})

    with pytest.raises(AssertionError, match=r"__init__\.py"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_stale_figure_export_surface(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "fastcharts/figure.py": """
from . import marks as _marks
class Figure:
    line = _marks.line
    scatter = _marks.scatter
    def to_html(self): ...
"""
        },
    )

    with pytest.raises(AssertionError, match=r"figure\.py.*to_png"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_stale_marks_export_surface(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "fastcharts/marks.py": """
def line(self, x, y): ...
"""
        },
    )

    with pytest.raises(AssertionError, match=r"marks\.py"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_stale_component_export_surface(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "fastcharts/components.py": """
from typing import Any
class Chart:
    props: dict[str, Any]
    def to_html(self): ...
"""
        },
    )

    with pytest.raises(AssertionError, match=r"components\.py.*to_png"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_stale_html_export_safety_surface(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "fastcharts/export.py": """
FASTCHARTS_CHROMIUM = "FASTCHARTS_CHROMIUM"
def _json_for_inline_script(value): ...
def html_to_png(html, width, height): ...
def to_png(fig): ...
"""
        },
    )

    with pytest.raises(AssertionError, match=r"export\.py.*_bundled_js"):
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


def test_verify_wheel_rejects_unexpected_native_artifact(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, extra={"fastcharts/bad_extension.so": b"native"})

    with pytest.raises(AssertionError, match="unexpected native artifacts"):
        verify_wheel.verify_wheel(whl, expect_native=True)


@pytest.mark.parametrize(
    "extra_name",
    [
        "docs/api-examples.md",
        "tests/test_docs_examples.py",
        "benchmarks/bench_vs.py",
        "examples/reflex/reflex_fastcharts_app/reflex_fastcharts_app.py",
    ],
)
def test_verify_wheel_rejects_sdist_only_files(tmp_path: Path, extra_name: str) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, extra={extra_name: b"sdist only"})

    with pytest.raises(AssertionError, match="sdist only"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_rejects_native_library(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=True)

    with pytest.raises(AssertionError, match="must not contain native libs"):
        verify_wheel.verify_wheel(whl, expect_native=False)


def test_verify_wheel_rejects_missing_record(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl)
    with zipfile.ZipFile(whl) as zf:
        entries = [
            (info.filename, zf.read(info.filename))
            for info in zf.infolist()
            if not info.filename.endswith(".dist-info/RECORD")
        ]
    with zipfile.ZipFile(whl, "w") as zf:
        for filename, data in entries:
            zf.writestr(filename, data)

    with pytest.raises(AssertionError, match="RECORD"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_empty_record(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, record_override="")

    with pytest.raises(AssertionError, match="does not list archive files"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_incomplete_record(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, record_omit={"fastcharts/widget.py"})

    with pytest.raises(AssertionError, match="does not match archive files"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_record_hash_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, record_overrides={"fastcharts/widget.py": ("sha256=bad", "6559")})

    with pytest.raises(AssertionError, match="hash mismatch"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_record_size_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    init_hash = f"sha256={_record_hash(INIT_PY.encode('utf-8'))}"
    _write_wheel(whl, record_overrides={"fastcharts/__init__.py": (init_hash, "1")})

    with pytest.raises(AssertionError, match="size mismatch"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_duplicate_archive_entries(tmp_path: Path) -> None:
    whl = tmp_path / "fastcharts-0.1.0-py3-none-macosx_11_0_arm64.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_wheel(whl, extra={"fastcharts/widget.py": b"duplicate"})

    with pytest.raises(AssertionError, match="duplicate archive entries"):
        verify_wheel.verify_wheel(whl, expect_native=True)
