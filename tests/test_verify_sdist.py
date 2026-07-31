from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
from pathlib import Path
from typing import Optional, Union

import pytest

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
ENTRIES_JS = (
    "export function render() {}\n"
    "export function renderStandalone() {}\n"
    "const padding = '" + ("x" * 1000) + "';\n"
    "export default { render, decodeFrame };\n"
)
DEFAULT_PKG_INFO = (
    "Metadata-Version: 2.4\n"
    "Name: xy\n"
    "Version: 0.0.1\n"
    "Requires-Python: >=3.11\n"
    "Requires-Dist: anywidget>=0.9\n"
    "Requires-Dist: numpy>=1.24\n"
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
    pkg_info: Optional[str] = DEFAULT_PKG_INFO,
    omit: Optional[set[str]] = None,
    extra: Optional[dict[str, bytes]] = None,
    replacements: Optional[dict[str, Union[bytes, str]]] = None,
    root_file: bool = False,
) -> None:
    root = "xy-0.0.1"
    omit = omit or set()
    extra = extra or {}
    replacements = replacements or {}
    with tarfile.open(path, "w:gz") as tf:
        if root_file:
            _add_file(tf, root, b"not a directory")
        for name in sorted(verify_sdist.REQUIRED_FILES - omit):
            data = b""
            if name == "PKG-INFO" and pkg_info is not None:
                data = pkg_info.encode("utf-8")
            if name == "PKG-INFO" and pkg_info is None:
                continue
            elif name in replacements:
                raw = replacements[name]
                data = raw.encode("utf-8") if isinstance(raw, str) else raw
            elif name == "python/xy/static/index.js":
                data = INDEX_JS.encode("utf-8")
            elif name == "python/xy/static/standalone.js":
                data = STANDALONE_JS.encode("utf-8")
            elif name == "js/src/60_entries.ts":
                data = ENTRIES_JS.encode("utf-8")
            _add_file(tf, f"{root}/{name}", data)
        for name, data in extra.items():
            _add_file(tf, f"{root}/{name}", data)


def test_verify_sdist_accepts_required_source_shape(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist)

    verify_sdist.verify_sdist(str(sdist))


@pytest.mark.parametrize(
    "root", [".github", "benchmarks", "docs", "examples", "scripts", "spec", "tests"]
)
def test_readme_does_not_reference_excluded_sdist_content(root: str) -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    relative_references = (
        f"]({root}/",
        f'href="{root}/',
        f'src="{root}/',
        f'srcset="{root}/',
    )

    assert not any(reference in readme for reference in relative_references)


def test_verify_sdist_accepts_normalized_metadata_spacing(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    pkg_info = DEFAULT_PKG_INFO.replace(
        "Requires-Dist: anywidget>=0.9", "Requires-Dist: anywidget >= 0.9"
    ).replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy >= 1.24")
    _write_sdist(sdist, pkg_info=pkg_info)

    verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_pkg_info(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, pkg_info=None)

    with pytest.raises(AssertionError, match="PKG-INFO"):
        verify_sdist.verify_sdist(str(sdist))


@pytest.mark.parametrize(
    ("pkg_info", "match"),
    [
        (
            DEFAULT_PKG_INFO.replace("Name: xy", "Name: othercharts"),
            "Name: xy",
        ),
        (
            DEFAULT_PKG_INFO.replace("Version: 0.0.1", "Version: 0.2.0"),
            "Version: 0.0.1",
        ),
        (
            DEFAULT_PKG_INFO.replace("Requires-Python: >=3.11", "Requires-Python: >=3.10"),
            r"Requires-Python: >=3\.11",
        ),
        (
            DEFAULT_PKG_INFO.replace("Requires-Dist: anywidget>=0.9", ""),
            r"anywidget>=0\.9",
        ),
        (
            DEFAULT_PKG_INFO.replace("Requires-Dist: numpy>=1.24", "Requires-Dist: numpy>=1.20"),
            r"numpy>=1\.24",
        ),
        (
            DEFAULT_PKG_INFO + "Requires-Dist: reflex>=0.8\n",
            "only xy runtime dependencies",
        ),
        (
            DEFAULT_PKG_INFO
            + "Requires-Dist: plotly>=5; extra == 'bench'\nProvides-Extra: bench\n",
            "only xy runtime dependencies",
        ),
        (
            DEFAULT_PKG_INFO + "Provides-Extra: dev\n",
            "no published extras",
        ),
    ],
)
def test_verify_sdist_rejects_invalid_pkg_info(tmp_path: Path, pkg_info: str, match: str) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, pkg_info=pkg_info)

    with pytest.raises(AssertionError, match=match):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_missing_static_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, omit={"python/xy/static/standalone.js"})

    with pytest.raises(AssertionError, match="missing required files"):
        verify_sdist.verify_sdist(str(sdist))


@pytest.mark.parametrize(
    "name",
    [
        ".agents/config.json",
        ".binder/environment.yml",
        ".github/workflows/ci.yml",
        "AGENTS.md",
        "Makefile",
        "benchmarks/bench.py",
        "docs/index.md",
        "examples/demo.ipynb",
        "pr-assets/review.png",
        "python/other-package/__init__.py",
        "python/reflex-xy/reflex_xy/__init__.py",
        "scripts/verify_local.py",
        "spec/design-dossier.md",
        "tests/test_import.py",
        "uv.lock",
    ],
)
def test_verify_sdist_rejects_repository_only_content(tmp_path: Path, name: str) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, extra={name: b"repository-only content"})

    with pytest.raises(AssertionError, match="generated/native artifacts"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_partial_type_marker(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"python/xy/py.typed": "partial\n"})

    with pytest.raises(AssertionError, match="full-package PEP 561 marker"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_static_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"python/xy/static/index.js": "not the client"})

    with pytest.raises(AssertionError, match=r"index\.js"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_corrupt_source_entry_bundle(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, replacements={"js/src/60_entries.ts": "not the source client"})

    with pytest.raises(AssertionError, match=r"60_entries\.ts"):
        verify_sdist.verify_sdist(str(sdist))


@pytest.mark.parametrize(
    "artifact",
    [
        "python/xy/__pycache__/figure.pyc",
        "examples/reflex/.web/package.json",
        "examples/reflex/.states/state.pkl",
        "examples/reflex/reflex.lock/package.json",
    ],
)
def test_verify_sdist_rejects_generated_artifacts(tmp_path: Path, artifact: str) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, extra={artifact: b"cache"})

    with pytest.raises(AssertionError, match="generated/native artifacts"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_duplicate_file_member(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, extra={"LICENSE": b"duplicate"})

    with pytest.raises(AssertionError, match="duplicate file member"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_regular_file_at_distribution_root(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, root_file=True)

    with pytest.raises(AssertionError, match="top-level entry must be a directory"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_file_directory_path_collisions(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    _write_sdist(sdist, extra={"README.md/repository-only.txt": b"not extractable"})

    with pytest.raises(AssertionError, match="file/directory path collisions"):
        verify_sdist.verify_sdist(str(sdist))


def test_verify_sdist_rejects_unsafe_member_paths(tmp_path: Path) -> None:
    sdist = tmp_path / "xy-0.0.1.tar.gz"
    with tarfile.open(sdist, "w:gz") as tf:
        _add_file(tf, "xy-0.0.1/PKG-INFO", b"Name: xy\n")
        _add_file(tf, "xy-0.0.1/../evil.py", b"")

    with pytest.raises(AssertionError, match="unsafe tar member path"):
        verify_sdist.verify_sdist(str(sdist))
