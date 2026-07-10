"""Regression tests for the wheel build hook's native-artifact resolution.

The hook packs a prebuilt Rust cdylib into the wheel. Two cross-compile failure
modes bit us in a real release dry-run and are guarded here:

- `wasm32-unknown-emscripten` doesn't emit a `.so`, so a filename guessed from
  the *build host* platform never matches — the target's release dir must be
  scanned for whatever `xy_core.*` artifact cargo actually produced.
- A scan must not grab the wrong file (an `.rlib`, or an unrelated `.wasm`).

`hatch_build.py` imports hatchling (a build-time-only dependency absent from the
runtime venv), so we stub it before loading the module to test the pure helpers.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_hatch_build():
    for name in (
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.hooks",
        "hatchling.builders.hooks.plugin",
        "hatchling.builders.hooks.plugin.interface",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    iface = sys.modules["hatchling.builders.hooks.plugin.interface"]
    if not hasattr(iface, "BuildHookInterface"):
        iface.BuildHookInterface = type("BuildHookInterface", (), {})
    spec = importlib.util.spec_from_file_location("hatch_build", ROOT / "hatch_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hb = _load_hatch_build()


def _release_dir(base: Path, triple: str) -> Path:
    d = base / "target" / triple / "release"
    d.mkdir(parents=True)
    return d


def test_resolve_prefers_host_guess_when_present(tmp_path: Path) -> None:
    rel = _release_dir(tmp_path, "x86_64-unknown-linux-musl")
    so = rel / "libxy_core.so"
    so.write_bytes(b"\x7fELF")
    assert hb._resolve_built(so, "x86_64-unknown-linux-musl") == so


def test_resolve_scans_for_wasm_artifact_the_host_guess_misses(tmp_path: Path) -> None:
    rel = _release_dir(tmp_path, "wasm32-unknown-emscripten")
    wasm = rel / "libxy_core.wasm"
    wasm.write_bytes(b"\0asm")
    # The host-derived guess (.so) does not exist; the scan must find the .wasm.
    assert hb._resolve_built(rel / "libxy_core.so", "wasm32-unknown-emscripten") == wasm


def test_resolve_ignores_wrong_suffix_and_wrong_stem(tmp_path: Path) -> None:
    rel = _release_dir(tmp_path, "wasm32-unknown-emscripten")
    (rel / "libxy_core.rlib").write_bytes(b"x")  # right stem, wrong suffix
    (rel / "something_else.wasm").write_bytes(b"x")  # right suffix, wrong stem
    assert hb._resolve_built(rel / "libxy_core.so", "wasm32-unknown-emscripten") is None


def test_resolve_does_not_scan_for_native_builds(tmp_path: Path) -> None:
    # target is None (a plain host build): a missing guess is just missing, no
    # scanning of the release dir for a mystery artifact.
    rel = tmp_path / "target" / "release"
    rel.mkdir(parents=True)
    stray = rel / "libxy_core.wasm"
    stray.write_bytes(b"x")
    assert hb._resolve_built(rel / "libxy_core.so", None) is None


@pytest.mark.parametrize("suffix", [".so", ".dylib", ".dll", ".wasm"])
def test_resolve_accepts_every_cdylib_suffix(tmp_path: Path, suffix: str) -> None:
    rel = _release_dir(tmp_path, "some-cross-triple")
    lib = rel / f"libxy_core{suffix}"
    lib.write_bytes(b"x")
    assert hb._resolve_built(rel / "libxy_core.so", "some-cross-triple") == lib
