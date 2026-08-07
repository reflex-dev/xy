"""Run the representative native-kernel smoke test against an installed wheel."""

import importlib.metadata as metadata

import numpy as np

import reflex_xy
import xy.kernels as kernels


def main() -> None:
    assert kernels.BACKEND == "native", kernels.BACKEND
    assert reflex_xy.__version__ == metadata.version("xy")
    codes, unique = kernels.factorize_fixed(np.asarray(["a", "b", "a"], dtype="S1"))
    assert codes.tolist() == [0, 1, 0]
    assert unique.tolist() == [0, 1]
    print("native", kernels.__file__)


if __name__ == "__main__":
    main()
