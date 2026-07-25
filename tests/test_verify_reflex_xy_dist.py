from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_reflex_xy_dist.py"
    spec = importlib.util.spec_from_file_location("verify_reflex_xy_dist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


verify_reflex_xy_dist = _load_module()


def _metadata(version: str) -> str:
    return (
        "Metadata-Version: 2.4\n"
        "Name: reflex-xy\n"
        f"Version: {version}\n"
        "Requires-Python: >=3.11\n"
        "Requires-Dist: xy\n"
        "Requires-Dist: reflex>=0.9.6\n"
        "Requires-Dist: aiohttp>=3.9; extra == 'dev'\n"
        "Provides-Extra: dev\n"
    )


def _wheel(
    tmp_path: Path,
    version: str = "0.1.0",
    *,
    extra_members: dict[str, bytes] | None = None,
    wheel_tag: str = "py3-none-any",
    purelib: str = "true",
) -> Path:
    path = tmp_path / f"reflex_xy-{version}-py3-none-any.whl"
    dist_info = f"reflex_xy-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("reflex_xy/__init__.py", "__all__ = []\n")
        archive.writestr("reflex_xy/assets/XYChart.jsx", "export default null;\n")
        archive.writestr(f"{dist_info}/METADATA", _metadata(version))
        archive.writestr(
            f"{dist_info}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: {purelib}\nTag: {wheel_tag}\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
        for name, payload in (extra_members or {}).items():
            archive.writestr(name, payload)
    return path


def _sdist(
    tmp_path: Path,
    version: str = "0.1.0",
    *,
    omit: frozenset[str] = frozenset(),
    extra_members: dict[str, bytes] | None = None,
) -> Path:
    path = tmp_path / f"reflex_xy-{version}.tar.gz"
    root = f"reflex_xy-{version}"
    members = {
        "PKG-INFO": _metadata(version).encode(),
        "pyproject.toml": b"[project]\nname = 'reflex-xy'\n",
        "README.md": b"# reflex-xy\n",
        "CHANGELOG.md": b"# Changelog\n",
        "reflex_xy/__init__.py": b"__all__ = []\n",
        "reflex_xy/assets/XYChart.jsx": b"export default null;\n",
    }
    members = {name: data for name, data in members.items() if name not in omit}
    members.update(extra_members or {})
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path


def test_accepts_a_pure_wheel_and_sdist_pair(tmp_path: Path) -> None:
    paths = [_wheel(tmp_path), _sdist(tmp_path)]

    assert verify_reflex_xy_dist.verify_dist(paths) == []
    assert verify_reflex_xy_dist.verify_dist(paths, tag="reflex-xy-v0.1.0") == []


def test_rejects_a_tag_version_mismatch(tmp_path: Path) -> None:
    paths = [_wheel(tmp_path), _sdist(tmp_path)]

    errors = verify_reflex_xy_dist.verify_dist(paths, tag="reflex-xy-v0.2.0")

    assert any("does not match built version" in e for e in errors)


def test_rejects_an_unprefixed_tag(tmp_path: Path) -> None:
    # A bare core tag must never vouch for adapter artifacts.
    paths = [_wheel(tmp_path), _sdist(tmp_path)]

    errors = verify_reflex_xy_dist.verify_dist(paths, tag="v0.1.0")

    assert any("does not match built version" in e for e in errors)


def test_accepts_an_untagged_dev_build_but_rejects_it_under_a_tag(tmp_path: Path) -> None:
    version = "0.1.1.dev3+g1234567"
    paths = [_wheel(tmp_path, version), _sdist(tmp_path, version)]

    assert verify_reflex_xy_dist.verify_dist(paths) == []
    assert verify_reflex_xy_dist.verify_dist(paths, tag="reflex-xy-v0.1.1") != []


def test_rejects_the_fallback_version(tmp_path: Path) -> None:
    paths = [_wheel(tmp_path, "0.0.0"), _sdist(tmp_path, "0.0.0")]

    errors = verify_reflex_xy_dist.verify_dist(paths)

    assert any("0.0.0 fallback" in e for e in errors)


def test_rejects_a_render_client_copy(tmp_path: Path) -> None:
    # The client links out of the installed xy package at app compile;
    # a second copy in the adapter wheel would drift from the kernel.
    wheel = _wheel(tmp_path, extra_members={"reflex_xy/assets/index.js": b"var xy={};"})

    _, errors = verify_reflex_xy_dist.verify_wheel(wheel)

    assert any("render-client copy" in e for e in errors)


def test_rejects_a_compiled_library(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, extra_members={"reflex_xy/_native.so": b"\x7fELF"})

    _, errors = verify_reflex_xy_dist.verify_wheel(wheel)

    assert any("compiled library" in e for e in errors)


def test_rejects_a_non_pure_wheel_tag(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, wheel_tag="py3-none-manylinux_2_17_x86_64", purelib="false")

    _, errors = verify_reflex_xy_dist.verify_wheel(wheel)

    assert any("Root-Is-Purelib" in e for e in errors)
    assert any("py3-none-any" in e for e in errors)


def test_rejects_a_wheel_missing_the_jsx_asset(tmp_path: Path) -> None:
    version = "0.1.0"
    path = tmp_path / f"reflex_xy-{version}-py3-none-any.whl"
    dist_info = f"reflex_xy-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("reflex_xy/__init__.py", "__all__ = []\n")
        archive.writestr(f"{dist_info}/METADATA", _metadata(version))
        archive.writestr(f"{dist_info}/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{dist_info}/RECORD", "")

    _, errors = verify_reflex_xy_dist.verify_wheel(path)

    assert any("XYChart.jsx" in e for e in errors)


def test_rejects_metadata_that_disagrees_with_the_filename(tmp_path: Path) -> None:
    version = "0.1.0"
    path = tmp_path / f"reflex_xy-{version}-py3-none-any.whl"
    dist_info = f"reflex_xy-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("reflex_xy/__init__.py", "__all__ = []\n")
        archive.writestr("reflex_xy/assets/XYChart.jsx", "export default null;\n")
        archive.writestr(f"{dist_info}/METADATA", _metadata("0.2.0"))
        archive.writestr(f"{dist_info}/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{dist_info}/RECORD", "")

    _, errors = verify_reflex_xy_dist.verify_wheel(path)

    assert any("does not match" in e for e in errors)


def test_rejects_a_wheel_missing_dependencies(tmp_path: Path) -> None:
    version = "0.1.0"
    path = tmp_path / f"reflex_xy-{version}-py3-none-any.whl"
    dist_info = f"reflex_xy-{version}.dist-info"
    metadata = (
        f"Metadata-Version: 2.4\nName: reflex-xy\nVersion: {version}\nRequires-Python: >=3.11\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("reflex_xy/__init__.py", "__all__ = []\n")
        archive.writestr("reflex_xy/assets/XYChart.jsx", "export default null;\n")
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr(f"{dist_info}/RECORD", "")

    _, errors = verify_reflex_xy_dist.verify_wheel(path)

    assert any("missing the 'xy' dependency" in e for e in errors)
    assert any("missing the 'reflex' dependency" in e for e in errors)


def test_rejects_an_sdist_without_its_changelog(tmp_path: Path) -> None:
    sdist = _sdist(tmp_path, omit=frozenset({"CHANGELOG.md"}))

    _, errors = verify_reflex_xy_dist.verify_sdist(sdist)

    assert any("CHANGELOG.md" in e for e in errors)


def test_rejects_sdist_junk(tmp_path: Path) -> None:
    sdist = _sdist(tmp_path, extra_members={"reflex_xy/__pycache__/__init__.cpython-311.pyc": b""})

    _, errors = verify_reflex_xy_dist.verify_sdist(sdist)

    assert any("generated junk" in e for e in errors)


def test_rejects_disagreeing_artifact_versions(tmp_path: Path) -> None:
    paths = [_wheel(tmp_path, "0.1.0"), _sdist(tmp_path, "0.2.0")]

    errors = verify_reflex_xy_dist.verify_dist(paths)

    assert any("versions disagree" in e for e in errors)


def test_requires_exactly_one_wheel_and_one_sdist(tmp_path: Path) -> None:
    errors = verify_reflex_xy_dist.verify_dist([_wheel(tmp_path)])

    assert any("exactly one sdist" in e for e in errors)


def test_release_workflow_wires_the_verifier() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release-reflex-xy.yml"
    ).read_text(encoding="utf-8")

    assert "scripts/verify_reflex_xy_dist.py" in workflow
    assert '--tag "$GITHUB_REF_NAME"' in workflow


def test_accepts_a_prerelease_pair_under_its_tag(tmp_path: Path) -> None:
    version = "0.0.1a1"
    paths = [_wheel(tmp_path, version), _sdist(tmp_path, version)]

    assert verify_reflex_xy_dist.verify_dist(paths, tag="reflex-xy-v0.0.1a1") == []
    assert verify_reflex_xy_dist.verify_dist(paths, tag="reflex-xy-v0.0.1") != []
