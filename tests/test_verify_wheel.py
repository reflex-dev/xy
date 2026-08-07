from __future__ import annotations

import base64
import hashlib
import importlib.util
import struct
import sys
import zipfile
from pathlib import Path
from typing import Optional, Union

import pytest

INIT_PY = """
__version__ = "0.0.1"
_EXPORTS = {"Selection": "._figure"}
__all__ = ["Selection", "__version__"]
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
XY_CHROMIUM = "XY_CHROMIUM"
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
REFLEX_INIT_PY = """
from .app import XYPlugin
from .component import chart
from .vars import figure
def __getattr__(name):
    if name == "__version__":
        return _distribution_version("xy")
"""
REFLEX_COMPONENT_JS = """
// XYChart imports the render client bundled in xy.
import { render } from "./xy_client.js";
export function XYChart() { return render; }
"""
# Shaped like the real minified vite bundles: export aliases in the ESM,
# a `var xy` IIFE namespace in the standalone build.
INDEX_JS = (
    "var C=class{};function r(){}function s(){}function d(){}"
    "var p=`" + ("x" * 1000) + "`;"
    "export{C as ChartView,d as decodeFrame,r as render,s as renderStandalone};"
)
STANDALONE_JS = (
    "var xy=(function(e){var p=`" + ("x" * 1000) + "`;"
    "return e.ChartView=class{},e.decodeFrame=()=>{},e.render=()=>{},"
    "e.renderStandalone=()=>{},e})({});"
)
DEFAULT_METADATA = "\n".join(
    [
        "Metadata-Version: 2.4",
        "Name: xy",
        "Version: 0.0.1",
        "Requires-Python: >=3.11",
        "Requires-Dist: anywidget>=0.9",
        "Requires-Dist: numpy>=1.24",
        "Requires-Dist: reflex>=0.9.6; extra == 'reflex'",
        "Provides-Extra: reflex",
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


@pytest.mark.parametrize(
    ("platform", "binary"),
    [
        (
            "manylinux_2_17_x86_64",
            b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(10) + struct.pack("<H", 62),
        ),
        (
            "macosx_11_0_arm64",
            b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C) + bytes(24),
        ),
        (
            "win_amd64",
            b"MZ"
            + bytes(58)
            + struct.pack("<I", 64)
            + b"PE\0\0"
            + struct.pack("<H", 0x8664)
            + bytes(18)
            + struct.pack("<H", 0x20B),
        ),
    ],
)
def test_native_binary_header_matches_wheel_platform(platform: str, binary: bytes) -> None:
    verify_wheel._require_native_target("native", binary, platform)


def test_native_binary_header_rejects_wrong_architecture() -> None:
    binary = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(10) + struct.pack("<H", 62)

    with pytest.raises(AssertionError, match="expected ELF/aarch64/64-bit"):
        verify_wheel._require_native_target("native", binary, "manylinux_2_17_aarch64")


def test_native_binary_rejects_missing_exported_abi_symbol() -> None:
    binary = b"\x7fELF" + bytes([2, 1, 1, 0]) + bytes(10) + struct.pack("<H", 62)

    with pytest.raises(AssertionError, match="missing exported ABI symbols"):
        verify_wheel._require_exported_symbols("native", binary, {"xy_abi_version"})


def test_native_binary_accepts_exported_elf_abi_symbol() -> None:
    data = bytearray(1024)
    data[:4] = b"\x7fELF"
    data[4:8] = bytes([2, 1, 1, 0])
    struct.pack_into("<H", data, 18, 62)
    struct.pack_into("<Q", data, 40, 512)
    struct.pack_into("<H", data, 58, 64)
    struct.pack_into("<H", data, 60, 3)
    struct.pack_into("<H", data, 62, 0)
    # The dynamic symbol table links to the following string-table section.
    struct.pack_into("<I", data, 512 + 64 + 4, 11)
    struct.pack_into("<Q", data, 512 + 64 + 24, 128)
    struct.pack_into("<Q", data, 512 + 64 + 32, 24)
    struct.pack_into("<I", data, 512 + 64 + 40, 2)
    struct.pack_into("<Q", data, 512 + 64 + 56, 24)
    struct.pack_into("<I", data, 512 + 128 + 4, 3)
    struct.pack_into("<Q", data, 512 + 128 + 24, 256)
    struct.pack_into("<Q", data, 512 + 128 + 32, 16)
    struct.pack_into("<IBBH", data, 128, 1, 0x10, 0, 1)
    data[256 : 256 + 16] = b"\0xy_abi_version\0"

    verify_wheel._require_exported_symbols("native", bytes(data), {"xy_abi_version"})


def test_macho_linkage_rejects_binary_above_wheel_floor() -> None:
    data = bytearray(48)
    data[:4] = b"\xcf\xfa\xed\xfe"
    struct.pack_into("<I", data, 4, 0x0100000C)
    struct.pack_into("<I", data, 16, 1)
    struct.pack_into("<II", data, 32, 0x32, 16)
    struct.pack_into("<I", data, 44, 12 << 16)

    with pytest.raises(AssertionError, match="above 11.0"):
        verify_wheel._require_macho_linkage("native", bytes(data), "macosx_11_0_arm64")


def test_linkage_validation_requires_platform() -> None:
    with pytest.raises(AssertionError, match="requires an expected native wheel platform"):
        verify_wheel.verify_wheel(
            Path("missing.whl"), expect_native=True, require_linkage=True
        )


def test_linkage_validation_requires_native_wheel() -> None:
    with pytest.raises(AssertionError, match="requires an expected native wheel platform"):
        verify_wheel.verify_wheel(
            Path("missing.whl"), expect_native=None, expect_platform="win_amd64", require_linkage=True
        )


def _elf_linkage_fixture(interpreter: bytes, dependency: bytes, version: bytes = b"") -> bytes:
    data = bytearray(512)
    data[:4] = b"\x7fELF"
    data[4:8] = bytes([2, 1, 1, 0])
    struct.pack_into("<H", data, 16, 3)
    struct.pack_into("<H", data, 18, 62)
    struct.pack_into("<I", data, 20, 1)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<H", data, 52, 64)
    struct.pack_into("<H", data, 54, 56)
    struct.pack_into("<H", data, 56, 3)
    # A load segment covering the fixture's dynamic data and string table.
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 0, 0, 0x400000, 0, 512, 512, 0)
    struct.pack_into("<IIQQQQQQ", data, 120, 3, 0, 240, 0, 0, len(interpreter), len(interpreter), 1)
    struct.pack_into("<IIQQQQQQ", data, 176, 2, 0, 280, 0, 0, 64, 64, 1)
    data[240 : 240 + len(interpreter)] = interpreter
    strings = b"\0" + dependency + b"\0" + version + b"\0"
    data[384 : 384 + len(strings)] = strings
    struct.pack_into("<QQ", data, 280, 5, 0x400000 + 384)
    struct.pack_into("<QQ", data, 296, 10, len(strings))
    struct.pack_into("<QQ", data, 312, 1, 1)
    struct.pack_into("<QQ", data, 328, 0, 0)
    return bytes(data)


def test_elf_linkage_validates_glibc_floor_and_dependency_family() -> None:
    binary = _elf_linkage_fixture(b"/lib64/ld-linux-x86-64.so.2\0", b"libc.so.6", b"GLIBC_2.17")

    verify_wheel._require_elf_linkage("native", binary, "manylinux_2_17_x86_64")

    with pytest.raises(AssertionError, match="above manylinux_2_17"):
        verify_wheel._require_elf_linkage(
            "native",
            _elf_linkage_fixture(b"/lib64/ld-linux-x86-64.so.2\0", b"libc.so.6", b"GLIBC_2.28"),
            "manylinux_2_17_x86_64",
        )


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
            if name == "xy/__init__.py" and name not in replacements:
                data = INIT_PY
            elif name == "xy/_figure.py" and name not in replacements:
                data = FIGURE_PY
            elif name == "xy/marks.py" and name not in replacements:
                data = MARKS_PY
            elif name == "xy/components.py" and name not in replacements:
                data = COMPONENTS_PY
            elif name == "xy/export.py" and name not in replacements:
                data = EXPORT_PY
            elif name == "xy/kernels.py" and name not in replacements:
                data = KERNELS_PY
            elif name == "xy/static/index.js" and name not in replacements:
                data = INDEX_JS
            elif name == "xy/static/standalone.js" and name not in replacements:
                data = STANDALONE_JS
            elif name == "reflex_xy/__init__.py" and name not in replacements:
                data = REFLEX_INIT_PY
            elif name == "reflex_xy/assets/XYChart.jsx" and name not in replacements:
                data = REFLEX_COMPONENT_JS
            write(zf, name, data)
        if native:
            write(zf, "xy/_native_lib/libxy_core.dylib", b"native")
        for name, data in extra.items():
            write(zf, name, data)
        wheel_name = "xy-0.0.1.dist-info/WHEEL"
        write(
            zf,
            wheel_name,
            (f"Wheel-Version: 1.0\nRoot-Is-Purelib: {str(root_is_purelib).lower()}\nTag: {tag}\n"),
        )
        if metadata is not None:
            write(zf, "xy-0.0.1.dist-info/METADATA", metadata)
        record_name = "xy-0.0.1.dist-info/RECORD"
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
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl)

    verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_accepts_required_artifact_shape(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=False)

    verify_wheel.verify_wheel(whl, expect_native=False)


def test_verify_wheel_accepts_normalized_metadata_spacing(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    metadata = DEFAULT_METADATA.replace(
        "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget >= 0.9"
    ).replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy >= 1.24")
    _write_wheel(whl, metadata=metadata)

    verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_accepts_zero_padded_dependency_floors(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    metadata = DEFAULT_METADATA.replace("anywidget>=0.9", "anywidget>=0.9.0").replace(
        "numpy>=1.24", "numpy>=1.24.0"
    )
    _write_wheel(whl, metadata=metadata)

    verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_native_wheel_rejects_filename_tag_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-macosx_11_0_arm64")

    with pytest.raises(AssertionError, match="filename tag"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_rejects_filename_tag_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=False)

    with pytest.raises(AssertionError, match="filename tag"):
        verify_wheel.verify_wheel(whl, expect_native=False)


def test_verify_wheel_rejects_missing_metadata_file(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, metadata=None)

    with pytest.raises(AssertionError, match="METADATA"):
        verify_wheel.verify_wheel(whl, expect_native=True)


@pytest.mark.parametrize(
    ("metadata", "match"),
    [
        (
            DEFAULT_METADATA.replace("Name: xy", "Name: othercharts"),
            "Name: xy",
        ),
        (
            DEFAULT_METADATA.replace("Version: 0.0.1", "Version: 0.2.0"),
            "Version: 0.0.1",
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
            DEFAULT_METADATA.replace(
                "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget>=999"
            ),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_METADATA.replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy>=999"),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_METADATA.replace(
                "Requires-Dist: anywidget>=0.9",
                "Requires-Dist: anywidget>=\u0660.\u0669",
            ),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_METADATA.replace(
                "Requires-Dist: numpy>=1.24",
                "Requires-Dist: numpy>=\u0661.\u0662\u0664",
            ),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_METADATA.replace(
                "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget>=0.9.dev0"
            ),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_METADATA.replace(
                "Requires-Dist: numpy>=1.24", "Requires-Dist: numpy>=1.24.dev0"
            ),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_METADATA.replace(
                "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget[dev]>=0.9"
            ),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_METADATA.replace(
                "Requires-Dist: numpy>=1.24", "Requires-Dist: numpy[typing]>=1.24"
            ),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_METADATA + "\nRequires-Dist: numpy<2",
            "exactly one requirement",
        ),
        (
            DEFAULT_METADATA.replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy>=1.24,<3"),
            "with no conflicts",
        ),
        (
            DEFAULT_METADATA + "\nRequires-Dist: reflex>=0.8",
            "only xy base dependencies",
        ),
        (
            DEFAULT_METADATA.replace("reflex>=0.9.6", "reflex>=0.8"),
            r"reflex>=0\.9\.6",
        ),
        (
            DEFAULT_METADATA + "\nRequires-Dist: reflex<0.9.6; extra == 'reflex'",
            "exactly one requirement",
        ),
        (
            DEFAULT_METADATA + "\nRequires-Dist: reflex>=0.9.6; extra == 'reflex'",
            "exactly one requirement",
        ),
        (
            DEFAULT_METADATA.replace("; extra == 'reflex'", ""),
            "only xy base dependencies",
        ),
        (
            DEFAULT_METADATA
            + "\nRequires-Dist: plotly>=5; extra == 'bench'\nProvides-Extra: bench",
            "only xy base dependencies",
        ),
        (
            DEFAULT_METADATA.replace("Provides-Extra: reflex", "Provides-Extra: dev"),
            "Provides-Extra: reflex",
        ),
    ],
)
def test_verify_wheel_rejects_invalid_metadata(tmp_path: Path, metadata: str, match: str) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, metadata=metadata)

    with pytest.raises(AssertionError, match=match):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_missing_type_marker(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, omit={"xy/py.typed"})

    with pytest.raises(AssertionError, match="py\\.typed"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_missing_reflex_integration(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, omit={"reflex_xy/assets/XYChart.jsx"})

    with pytest.raises(AssertionError, match="reflex_xy"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_missing_reflex_type_marker(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, omit={"reflex_xy/py.typed"})

    with pytest.raises(AssertionError, match="reflex_xy/py\\.typed"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_partial_type_marker(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"xy/py.typed": "partial\n"})

    with pytest.raises(AssertionError, match="full-package PEP 561 marker"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_partial_reflex_type_marker(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"reflex_xy/py.typed": "partial\n"})

    with pytest.raises(AssertionError, match="reflex_xy/py\\.typed"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_corrupt_python_module(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"xy/__init__.py": ""})

    with pytest.raises(AssertionError, match=r"__init__\.py"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_stale_figure_export_surface(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "xy/_figure.py": """
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
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "xy/marks.py": """
def line(self, x, y): ...
"""
        },
    )

    with pytest.raises(AssertionError, match=r"marks\.py"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_stale_component_export_surface(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "xy/components.py": """
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
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(
        whl,
        replacements={
            "xy/export.py": """
XY_CHROMIUM = "XY_CHROMIUM"
def _json_for_inline_script(value): ...
def html_to_png(html, width, height): ...
def to_png(fig): ...
"""
        },
    )

    with pytest.raises(AssertionError, match=r"export\.py.*_bundled_js"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_missing_static_bundle(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, omit={"xy/static/standalone.js"})

    with pytest.raises(AssertionError, match="required package files"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_corrupt_static_bundle(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, replacements={"xy/static/standalone.js": "not the client"})

    with pytest.raises(AssertionError, match=r"standalone\.js"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_unexpected_native_artifact(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, extra={"xy/bad_extension.so": b"native"})

    with pytest.raises(AssertionError, match="unexpected native artifacts"):
        verify_wheel.verify_wheel(whl, expect_native=True)


@pytest.mark.parametrize(
    "extra_name",
    [
        "spec/api/api-examples.md",
        "tests/test_view_state.py",
        "benchmarks/bench_vs.py",
        "examples/reflex/xy_reflex_demo/xy_reflex_demo.py",
    ],
)
def test_verify_wheel_rejects_sdist_only_files(tmp_path: Path, extra_name: str) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, extra={extra_name: b"sdist only"})

    with pytest.raises(AssertionError, match="sdist only"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_pure_wheel_rejects_native_library(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-any.whl"
    _write_wheel(whl, tag="py3-none-any", root_is_purelib=True, native=True)

    with pytest.raises(AssertionError, match="must not contain native libs"):
        verify_wheel.verify_wheel(whl, expect_native=False)


def test_verify_wheel_rejects_missing_record(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
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
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, record_override="")

    with pytest.raises(AssertionError, match="does not list archive files"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_incomplete_record(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, record_omit={"xy/widget.py"})

    with pytest.raises(AssertionError, match="does not match archive files"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_record_hash_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    _write_wheel(whl, record_overrides={"xy/widget.py": ("sha256=bad", "6559")})

    with pytest.raises(AssertionError, match="hash mismatch"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_record_size_mismatch(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    init_hash = f"sha256={_record_hash(INIT_PY.encode('utf-8'))}"
    _write_wheel(whl, record_overrides={"xy/__init__.py": (init_hash, "1")})

    with pytest.raises(AssertionError, match="size mismatch"):
        verify_wheel.verify_wheel(whl, expect_native=True)


def test_verify_wheel_rejects_duplicate_archive_entries(tmp_path: Path) -> None:
    whl = tmp_path / "xy-0.0.1-py3-none-macosx_11_0_arm64.whl"
    with pytest.warns(UserWarning, match="Duplicate name"):
        _write_wheel(whl, extra={"xy/widget.py": b"duplicate"})

    with pytest.raises(AssertionError, match="duplicate archive entries"):
        verify_wheel.verify_wheel(whl, expect_native=True)
