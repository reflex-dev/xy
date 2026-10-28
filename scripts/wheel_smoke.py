"""Run the representative native-kernel smoke test against an installed wheel."""

import importlib.metadata as metadata
from pathlib import Path

import numpy as np

import reflex_xy
import xy
import xy.kernels as kernels


def main() -> None:
    if kernels.BACKEND != "native":
        raise RuntimeError(f"expected native backend, got {kernels.BACKEND!r}")
    distribution = metadata.distribution("xy")
    installed_files = {
        str(file).replace("\\", "/"): distribution.locate_file(file).resolve()
        for file in distribution.files or ()
    }
    for member, imported_path in (
        ("xy/__init__.py", xy.__file__),
        ("xy/kernels.py", kernels.__file__),
        ("reflex_xy/__init__.py", reflex_xy.__file__),
    ):
        if installed_files.get(member) != Path(imported_path).resolve():
            raise RuntimeError(f"{member} was not imported from the installed xy wheel")

    native_members = [member for member in installed_files if member.startswith("xy/_native_lib/")]
    native_path = Path(kernels._impl._lib._name).resolve()
    if len(native_members) != 1 or installed_files[native_members[0]] != native_path:
        raise RuntimeError("native core was not loaded from the installed xy wheel")
    if xy.__version__ != distribution.version or reflex_xy.__version__ != distribution.version:
        raise RuntimeError("installed reflex_xy and xy versions do not match")
    codes, unique = kernels.factorize_fixed(np.asarray(["a", "b", "a"], dtype="S1"))
    if codes.tolist() != [0, 1, 0] or unique.tolist() != [0, 1]:
        raise RuntimeError(f"unexpected factorize_fixed result: {codes}, {unique}")
    print("native", kernels.__file__)


if __name__ == "__main__":
    main()
