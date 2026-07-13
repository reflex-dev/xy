"""Small, dependency-free transform values used by the pyplot shim.

This is deliberately not a replacement for Matplotlib's transform graph.  It
provides the affine and coordinate-space behavior needed by supported pyplot
calls while giving unsupported composition a clear boundary.
"""

from __future__ import annotations

from typing import Any

import numpy as np


class Bbox:
    def __init__(self, bounds: tuple[float, float, float, float]) -> None:
        if len(bounds) != 4:
            raise ValueError("Bbox bounds must contain x0, y0, width, height")
        self._bounds: tuple[float, float, float, float] = (
            float(bounds[0]),
            float(bounds[1]),
            float(bounds[2]),
            float(bounds[3]),
        )

    @classmethod
    def from_bounds(cls, x0: float, y0: float, width: float, height: float) -> "Bbox":
        return cls((x0, y0, width, height))

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self._bounds

    x0 = property(lambda self: self._bounds[0])
    y0 = property(lambda self: self._bounds[1])
    width = property(lambda self: self._bounds[2])
    height = property(lambda self: self._bounds[3])
    x1 = property(lambda self: self.x0 + self.width)
    y1 = property(lambda self: self.y0 + self.height)

    def frozen(self) -> "Bbox":
        return Bbox(self._bounds)


class Affine2D:
    """A bounded homogeneous 2-D affine transform."""

    coordinate_space = "data"

    def __init__(self, matrix: Any = None, *, coordinate_space: str = "data") -> None:
        self._matrix = np.eye(3, dtype=float) if matrix is None else np.asarray(matrix, dtype=float)
        if self._matrix.shape != (3, 3):
            raise ValueError("Affine2D matrix must have shape (3, 3)")
        self.coordinate_space = coordinate_space

    def get_matrix(self) -> np.ndarray:
        return self._matrix.copy()

    def transform(self, values: Any) -> np.ndarray:
        points = np.asarray(values, dtype=float)
        scalar = points.ndim == 1
        points = np.atleast_2d(points)
        if points.shape[1] != 2:
            raise ValueError("transform input must contain x/y pairs")
        homogeneous = np.column_stack((points, np.ones(len(points))))
        result = (homogeneous @ self._matrix.T)[:, :2]
        return result[0] if scalar else result

    transform_point = transform

    def inverted(self) -> "Affine2D":
        return Affine2D(np.linalg.inv(self._matrix), coordinate_space=self.coordinate_space)

    def translate(self, tx: float, ty: float) -> "Affine2D":
        operation = np.eye(3)
        operation[:2, 2] = (float(tx), float(ty))
        self._matrix = operation @ self._matrix
        return self

    def scale(self, sx: float, sy: Any = None) -> "Affine2D":
        sy = sx if sy is None else sy
        operation = np.diag((float(sx), float(sy), 1.0))
        self._matrix = operation @ self._matrix
        return self

    def rotate_deg(self, degrees: float) -> "Affine2D":
        angle = np.deg2rad(float(degrees))
        cosine, sine = np.cos(angle), np.sin(angle)
        operation = np.asarray([[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]])
        self._matrix = operation @ self._matrix
        return self

    def __add__(self, other: Any) -> "Affine2D":
        if not isinstance(other, Affine2D):
            raise TypeError("xy.pyplot only composes affine transforms with affine transforms")
        return Affine2D(other._matrix @ self._matrix, coordinate_space=other.coordinate_space)


class IdentityTransform(Affine2D):
    def __init__(self, *, coordinate_space: str = "data") -> None:
        super().__init__(coordinate_space=coordinate_space)

    def inverted(self) -> "IdentityTransform":
        return IdentityTransform(coordinate_space=self.coordinate_space)


class CoordinateTransform(IdentityTransform):
    """Identity-valued token that identifies a renderer coordinate space."""

    def __init__(self, coordinate_space: str) -> None:
        super().__init__(coordinate_space=coordinate_space)
