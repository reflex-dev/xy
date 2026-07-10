"""Hatchling build hook: compile the Rust core and bundle it into the wheel.

Install ergonomics, by audience (design dossier §33):

- **End users** run `pip install xy` and get a prebuilt platform wheel
  from the CI matrix — the compiled core *and* the JS client are already inside
  it. **No Rust, no Node, no toolchain.** This is the front door.
- **Source builds** (`pip install .` / `-e .` from a clone) compile the core if
  a Rust toolchain is present. **If Rust is absent, the build still succeeds**
  but produces a pure-Python install with no native core — and since there is no
  NumPy fallback, importing the compute layer then raises a clear, actionable
  error (see `xy.kernels`). Install a Rust toolchain, or use a published
  wheel, for a working compute backend.
- The JS client (`python/xy/static/*`) is a **committed artifact**, so
  Node is only needed to *edit* the client, never to install.

Env switches:
- `XY_SKIP_CARGO=1` — don't invoke cargo; use an already-built lib if
  present, else build pure-Python. (Used when an earlier CI step prebuilt it.)
- `XY_REQUIRE_CARGO=1` — the native core MUST end up in the wheel; a
  missing toolchain or failed build is an error. CI wheel builds set this so a
  published wheel never silently ships without the core.
- `XY_CARGO_TARGET=<triple>` — cross-compile the core for a Rust target
  triple (e.g. `aarch64-unknown-linux-musl`, `aarch64-pc-windows-msvc`). The
  built lib is looked for under `target/<triple>/release/` instead of
  `target/release/`; if the crate's cdylib doesn't land under the host's usual
  suffix there (e.g. `wasm32-unknown-emscripten` isn't a `.so`), the target's
  release dir is scanned for whatever `xy_core.*` artifact cargo
  actually produced, rather than assuming one fixed filename. The release
  matrix sets this to reach every platform in one CI run.
- `XY_WHEEL_PLATFORM=<tag>` — override the wheel's platform tag (e.g.
  `musllinux_1_2_aarch64`, `win_arm64`). Cross-compiled builds need this because
  the build host's `sysconfig.get_platform()` describes the host, not the target.

Musl targets need one more thing this hook doesn't control: `*-unknown-linux-musl`
defaults to fully static linking (`crt-static`), under which rustc silently
*drops* the cdylib output entirely (a warning, not an error — cargo "succeeds"
having built nothing). The release workflow passes
`RUSTFLAGS=-C target-feature=-crt-static` for musl targets so a real cdylib
gets produced; that flag lives in CI, not here, since it's about how cargo is
invoked, not what this hook does with the result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any, Optional

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _lib_filename() -> str:
    if sys.platform == "win32":
        return "xy_core.dll"
    if sys.platform == "darwin":
        return "libxy_core.dylib"
    return "libxy_core.so"


_CDYLIB_SUFFIXES = (".so", ".dylib", ".dll", ".wasm")


def _find_cross_compiled_lib(release_dir: Path) -> Optional[Path]:
    """Cross-compiling to an exotic target can produce a cdylib under a suffix
    `_lib_filename()`'s host-platform guess never anticipated — e.g.
    `wasm32-unknown-emscripten` doesn't emit a `.so`. Scan the target's own
    release directory for whatever cdylib-shaped artifact cargo actually
    produced, keyed on the crate's lib name, instead of assuming one fixed
    filename derived from the *build host's* platform."""
    if not release_dir.is_dir():
        return None
    candidates = sorted(
        p
        for p in release_dir.iterdir()
        if p.is_file() and "xy_core" in p.stem and p.suffix in _CDYLIB_SUFFIXES
    )
    return candidates[0] if candidates else None


def _resolve_built(built: Path, target: Optional[str]) -> Optional[Path]:
    """Prefer the host-platform-derived guess; for a cross-compiled target
    where that guess doesn't exist, fall back to scanning its release dir."""
    if built.exists():
        return built
    if target is None:
        return None
    return _find_cross_compiled_lib(built.parent)


def _platform_tag() -> str:
    # e.g. linux_x86_64, macosx_11_0_arm64, win_amd64. CI repairs linux wheels
    # to manylinux/musllinux after the build. Cross-compiled builds can't infer
    # the target from the host, so an explicit override wins when set.
    override = os.environ.get("XY_WHEEL_PLATFORM")
    if override:
        return override.replace("-", "_").replace(".", "_")
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


def _cargo_target() -> Optional[str]:
    target = os.environ.get("XY_CARGO_TARGET", "").strip()
    return target or None


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        lib_name = _lib_filename()
        dest_dir = root / "python" / "xy" / "_native_lib"
        dest = dest_dir / lib_name
        require = os.environ.get("XY_REQUIRE_CARGO") == "1"

        native_src = self._provision_native(root, lib_name, dest, require)

        if native_src is not None:
            # Platform wheel carrying the compiled C-ABI core (one per platform,
            # every CPython version).
            build_data["pure_python"] = False
            build_data["tag"] = f"py3-none-{_platform_tag()}"
            build_data.setdefault("force_include", {})[str(native_src)] = (
                f"xy/_native_lib/{lib_name}"
            )
        else:
            # No toolchain / build skipped: ship a pure-Python wheel (the JS
            # client is included via committed package data). There is no NumPy
            # fallback, so this install imports fine but raises a clear error the
            # moment compute is needed (xy.kernels).
            print(
                "xy: building WITHOUT the native Rust core (cargo not "
                "found or build skipped). This install has no compute backend "
                "and will raise a clear error on first use. Install a prebuilt "
                "wheel or a Rust toolchain (https://rustup.rs) for a working "
                "install.",
                file=sys.stderr,
            )
            build_data["pure_python"] = True
            build_data["tag"] = "py3-none-any"

    def _provision_native(
        self, root: Path, lib_name: str, dest: Path, require: bool
    ) -> Optional[Path]:
        """Return a native library path to include in the wheel, if available.

        Do not copy into `python/xy/_native_lib` during a normal build:
        force-include can place the built artifact at that wheel path directly,
        and generated platform binaries should not dirty the source tree.
        """
        target = _cargo_target()
        # A cross-compiled build lands under target/<triple>/release/; a native
        # build under target/release/.
        built = (
            root / "target" / target / "release" / lib_name
            if target
            else root / "target" / "release" / lib_name
        )
        if os.environ.get("XY_SKIP_CARGO") == "1":
            if dest.exists():
                return dest
            resolved = _resolve_built(built, target)
            if resolved is not None:
                return resolved
            if require:
                raise RuntimeError(
                    f"XY_REQUIRE_CARGO=1 and XY_SKIP_CARGO=1 but "
                    f"neither {dest} nor {built} exists, and no xy_core.* "
                    f"artifact was found in {built.parent} — prebuild the core "
                    "before this step."
                )
            return None

        if shutil.which("cargo") is None:
            if require:
                raise RuntimeError(
                    "XY_REQUIRE_CARGO=1 but cargo is not on PATH — a "
                    "published wheel must contain the native core."
                )
            return None  # graceful: pure-Python wheel

        cmd = ["cargo", "build", "--release"]
        if target:
            cmd += ["--target", target]
        try:
            subprocess.run(cmd, cwd=root, check=True)
        except (subprocess.CalledProcessError, OSError) as e:
            if require:
                raise RuntimeError(f"cargo build failed: {e}") from e
            return None

        resolved = _resolve_built(built, target)
        if resolved is None:
            if require:
                raise RuntimeError(
                    f"cargo build succeeded but {built} is missing, and no "
                    f"xy_core.* artifact was found in {built.parent}"
                )
            return None
        return resolved
