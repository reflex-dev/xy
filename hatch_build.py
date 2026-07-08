"""Hatchling build hook: compile the Rust core and bundle it into the wheel.

Install ergonomics, by audience (design dossier §33):

- **End users** run `pip install fastcharts` and get a prebuilt platform wheel
  from the CI matrix — the compiled core *and* the JS client are already inside
  it. **No Rust, no Node, no toolchain.** This is the front door.
- **Source builds** (`pip install .` / `-e .` from a clone) compile the core if
  a Rust toolchain is present. **If Rust is absent, the build still succeeds**
  but produces a pure-Python install with no native core — and since there is no
  NumPy fallback, importing the compute layer then raises a clear, actionable
  error (see `fastcharts.kernels`). Install a Rust toolchain, or use a published
  wheel, for a working compute backend.
- The JS client (`python/fastcharts/static/*`) is a **committed artifact**, so
  Node is only needed to *edit* the client, never to install.

Env switches:
- `FASTCHARTS_SKIP_CARGO=1` — don't invoke cargo; use an already-built lib if
  present, else build pure-Python. (Used when an earlier CI step prebuilt it.)
- `FASTCHARTS_REQUIRE_CARGO=1` — the native core MUST end up in the wheel; a
  missing toolchain or failed build is an error. CI wheel builds set this so a
  published wheel never silently ships without the core.
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
        return "fastcharts_core.dll"
    if sys.platform == "darwin":
        return "libfastcharts_core.dylib"
    return "libfastcharts_core.so"


def _platform_tag() -> str:
    # e.g. linux_x86_64, macosx_11_0_arm64, win_amd64. CI repairs linux wheels
    # to manylinux with auditwheel after the build.
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        lib_name = _lib_filename()
        dest_dir = root / "python" / "fastcharts" / "_native_lib"
        dest = dest_dir / lib_name
        require = os.environ.get("FASTCHARTS_REQUIRE_CARGO") == "1"

        native_src = self._provision_native(root, lib_name, dest, require)

        if native_src is not None:
            # Platform wheel carrying the compiled C-ABI core (one per platform,
            # every CPython version).
            build_data["pure_python"] = False
            build_data["tag"] = f"py3-none-{_platform_tag()}"
            build_data.setdefault("force_include", {})[str(native_src)] = (
                f"fastcharts/_native_lib/{lib_name}"
            )
        else:
            # No toolchain / build skipped: ship a pure-Python wheel (the JS
            # client is included via committed package data). There is no NumPy
            # fallback, so this install imports fine but raises a clear error the
            # moment compute is needed (fastcharts.kernels).
            print(
                "fastcharts: building WITHOUT the native Rust core (cargo not "
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

        Do not copy into `python/fastcharts/_native_lib` during a normal build:
        force-include can place the built artifact at that wheel path directly,
        and generated platform binaries should not dirty the source tree.
        """
        built = root / "target" / "release" / lib_name
        if os.environ.get("FASTCHARTS_SKIP_CARGO") == "1":
            if dest.exists():
                return dest
            if built.exists():
                return built
            if require:
                raise RuntimeError(
                    f"FASTCHARTS_REQUIRE_CARGO=1 and FASTCHARTS_SKIP_CARGO=1 but "
                    f"neither {dest} nor {built} exists — prebuild the core before this step."
                )
            return None

        if shutil.which("cargo") is None:
            if require:
                raise RuntimeError(
                    "FASTCHARTS_REQUIRE_CARGO=1 but cargo is not on PATH — a "
                    "published wheel must contain the native core."
                )
            return None  # graceful: pure-Python wheel

        try:
            subprocess.run(["cargo", "build", "--release"], cwd=root, check=True)
        except (subprocess.CalledProcessError, OSError) as e:
            if require:
                raise RuntimeError(f"cargo build failed: {e}") from e
            return None

        if not built.exists():
            if require:
                raise RuntimeError(f"cargo build succeeded but {built} is missing")
            return None
        return built
