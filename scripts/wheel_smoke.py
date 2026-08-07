"""Run the representative native-kernel smoke test against an installed wheel."""

import importlib.metadata as metadata

import numpy as np

import reflex_xy
import xy.kernels as kernels


def main() -> None:
    if kernels.BACKEND != "native":
        raise RuntimeError(f"expected native backend, got {kernels.BACKEND!r}")
    if reflex_xy.__version__ != metadata.version("xy"):
        raise RuntimeError("installed reflex_xy and xy versions do not match")
    codes, unique = kernels.factorize_fixed(np.asarray(["a", "b", "a"], dtype="S1"))
    if codes.tolist() != [0, 1, 0] or unique.tolist() != [0, 1]:
        raise RuntimeError(f"unexpected factorize_fixed result: {codes}, {unique}")
    print("native", kernels.__file__)


if __name__ == "__main__":
    main()
