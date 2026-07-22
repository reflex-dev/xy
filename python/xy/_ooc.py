"""Out-of-core canonical columns — building f64 columns too large for RAM.

Design dossier §27 lists canonical columns as living in "JS ArrayBuffers /
**mmap (native)** / server (Tier 3)", and §32 gives the native core "real
threads, **mmap**, no WASM caps, no 4 GB ceiling". This module realizes the
mmap case for ingest.

The load-bearing observation: a NumPy ``memmap`` is a *transparent* ``ndarray``.
A canonical column backed by one

- satisfies the :class:`~xy.columns.ColumnStore` dedup key
  (``id(base)``, ``data_ptr``, ``nbytes`` — see ``ColumnStore._array_key``),
- passes straight to the ctypes kernels, which take the raw buffer address
  (``arr.ctypes.data``; see ``_native._ptr_f64``) — the OS then pages the file
  in on demand, so ``zone_maps``, ``bin_2d``, ``range_indices`` and the density
  pyramid (``tiles.rs``) all consume it with **no special-casing**,
- is dropped by the kernel as a rebuildable cache exactly like an in-RAM one.

So the store, the zone maps, and every LOD tier already work out-of-core. The
one thing you cannot do at 9-billion-row scale is *materialize the array in RAM
to hand to* ``Figure.scatter``. This builder is that missing piece: it writes
canonical f64 to a disk memmap one batch at a time (peak RAM = one batch), then
returns the finished read-only view. Feed that view to the ordinary public
API — ``fig.scatter(x=view_x, y=view_y, density=True)`` — and the whole
pipeline runs against disk-backed truth with resident memory bounded by the
screen, not the data (§2, §27).

Pure NumPy; no ``reflex``/widget/pyarrow imports, matching ``columns.py``.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import numpy.typing as npt

_F64_BYTES = 8


class MemmapF64Builder:
    """Stream f64 values into a disk-backed column without ever holding the
    whole column in RAM.

    ``capacity`` pre-sizes the backing file (a *sparse* file on ext4/xfs/apfs:
    it costs no disk until pages are actually written, so a generous upper
    bound is cheap). If an append would exceed capacity the file is grown by
    doubling. :meth:`finalize` truncates the file to the exact written length
    and returns a read-only memmap view suitable for ingest.
    """

    def __init__(self, path: str | os.PathLike[str], capacity: int = 1 << 20) -> None:
        self.path = os.fspath(path)
        self.capacity = max(int(capacity), 1)
        self.n = 0
        self._mm: np.memmap | None = np.memmap(
            self.path, dtype=np.float64, mode="w+", shape=(self.capacity,)
        )

    def _grow(self, needed: int) -> None:
        new_cap = max(needed, self.capacity * 2)
        assert self._mm is not None
        self._mm.flush()
        self._mm = None  # release the mapping before resizing the file
        with open(self.path, "r+b") as f:
            f.truncate(new_cap * _F64_BYTES)
        self._mm = np.memmap(self.path, dtype=np.float64, mode="r+", shape=(new_cap,))
        self.capacity = new_cap

    def extend(self, batch: npt.ArrayLike) -> None:
        """Append a 1-D batch of values (copied once into the mapped file)."""
        arr = np.ascontiguousarray(batch, dtype=np.float64).reshape(-1)
        m = arr.shape[0]
        if m == 0:
            return
        if self.n + m > self.capacity:
            self._grow(self.n + m)
        assert self._mm is not None
        self._mm[self.n : self.n + m] = arr
        self.n += m

    def finalize(self) -> np.memmap:
        """Flush, truncate to the written length, and return a read-only view.

        The returned array is a canonical f64 column: contiguous, single-copy,
        disk-backed. Hand it to :meth:`xy.Figure.scatter` /
        ``ColumnStore.ingest`` exactly like an in-RAM array.
        """
        if self._mm is not None:
            self._mm.flush()
            self._mm = None
        if self.n == 0:
            # An empty column still needs a valid (zero-length) mapping; keep a
            # single f64 slot on disk so the memmap open succeeds, view is [:0].
            with open(self.path, "r+b") as f:
                f.truncate(_F64_BYTES)
            return np.memmap(self.path, dtype=np.float64, mode="r", shape=(0,))
        with open(self.path, "r+b") as f:
            f.truncate(self.n * _F64_BYTES)
        return np.memmap(self.path, dtype=np.float64, mode="r", shape=(self.n,))


def is_memmapped(arr: Any) -> bool:
    """True if ``arr`` is, or is a view onto, a disk-backed ``np.memmap``.

    Walks the ``.base`` chain because ``astype(copy=False)`` /
    ``ascontiguousarray`` on a memmap may return a plain-``ndarray`` view that
    still shares the mapped buffer.
    """
    seen = arr
    while seen is not None:
        if isinstance(seen, np.memmap):
            return True
        seen = getattr(seen, "base", None)
    return False


def backing_path(arr: Any) -> str | None:
    """Filesystem path of the ``np.memmap`` backing ``arr``, or ``None`` when
    ``arr`` is not disk-backed. Walks the ``.base`` chain like
    :func:`is_memmapped` (a contiguity/astype view still shares the mapping)."""
    seen = arr
    while seen is not None:
        if isinstance(seen, np.memmap):
            name = getattr(seen, "filename", None)
            return os.fspath(name) if name is not None else None
        seen = getattr(seen, "base", None)
    return None


def open_f64(path: str | os.PathLike[str]) -> np.memmap:
    """Reopen an existing canonical f64 file as a read-only memmap column."""
    path = os.fspath(path)
    n, rem = divmod(os.path.getsize(path), _F64_BYTES)
    if rem:
        raise ValueError(f"{path!r} is not a whole number of f64 values")
    return np.memmap(path, dtype=np.float64, mode="r", shape=(int(n),))
