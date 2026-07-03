"""Hatchling build hook: compile the Rust core and bundle it into the wheel.

Design dossier §33: `pip install` must deliver the native core prebuilt — a user
must never be dropped into a source build by surprise. This hook is what runs on
the CI wheel matrix; end users receive the .so/.dylib/.dll inside the wheel.

The wheel is tagged `py3-none-<platform>`: the core is a plain C-ABI cdylib
(no CPython ABI at all), so one wheel per platform covers every Python version.

Set FASTCHARTS_SKIP_CARGO=1 to skip the cargo build (e.g. when the artifact was
prebuilt by an earlier CI step); the hook then requires the library to already
be present and fails loudly otherwise — a missing wheel artifact is a build
failure, not a runtime surprise (§33).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any

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

        if os.environ.get("FASTCHARTS_SKIP_CARGO") == "1":
            if not dest.exists():
                raise RuntimeError(
                    f"FASTCHARTS_SKIP_CARGO=1 but {dest} does not exist — "
                    "the native core must be prebuilt for this platform."
                )
        else:
            subprocess.run(
                ["cargo", "build", "--release"],
                cwd=root,
                check=True,
            )
            built = root / "target" / "release" / lib_name
            if not built.exists():
                raise RuntimeError(f"cargo build succeeded but {built} is missing")
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(built, dest)

        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{_platform_tag()}"
        build_data.setdefault("force_include", {})[str(dest)] = (
            f"fastcharts/_native_lib/{lib_name}"
        )
