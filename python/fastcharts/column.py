"""The column store: canonical, typed, single-copy (§4).

Phase 0 contract:
- Canonical data lives CPU-side as contiguous NumPy float64; every encoded /
  decimated buffer is a *derived cache*, recomputable from here (§27 rule 1).
- Time columns (datetime64 / pandas datetime) are canonicalized to **ms since
  epoch as f64** — exact for |t| < 2^53, i.e. every real-world ms timestamp.
  i64-nanosecond end-to-end fidelity (§16) arrives with Arrow ingest.
- Zone maps (§22) are computed once at ingest — one pass, reused for autorange,
  offset selection, and (later) Tier-3 pruning.
- Ingest copy count is recorded, not hidden (§29: copies are counted, reported,
  never folklore).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from . import kernels


@dataclass
class ZoneMaps:
    """Per-chunk statistics (§22)."""

    mins: npt.NDArray[np.float64]
    maxs: npt.NDArray[np.float64]
    counts: npt.NDArray[np.uint64]
    null_counts: npt.NDArray[np.uint64]
    sums: npt.NDArray[np.float64]
    sum_sqs: npt.NDArray[np.float64]

    @property
    def min(self) -> float:
        valid = self.mins[self.counts > 0]
        return float(valid.min()) if len(valid) else float("nan")

    @property
    def max(self) -> float:
        valid = self.maxs[self.counts > 0]
        return float(valid.max()) if len(valid) else float("nan")

    @property
    def count(self) -> int:
        return int(self.counts.sum())

    @property
    def null_count(self) -> int:
        return int(self.null_counts.sum())


@dataclass
class Column:
    """A canonical column: values + zone maps + provenance."""

    id: int
    values: npt.NDArray[np.float64]  # contiguous f64, the single source of truth
    kind: str  # "float" | "time_ms"
    zone: ZoneMaps
    ingest_copies: int  # copies paid at ingest (§29 accounting)

    def __len__(self) -> int:
        return len(self.values)

    @property
    def min(self) -> float:
        return self.zone.min

    @property
    def max(self) -> float:
        return self.zone.max

    def suggest_offset(self) -> float:
        """Midpoint offset for relative-f32 encoding (§4). Re-centering on deep
        zoom (§16) picks a new offset at the viewport center instead."""
        lo, hi = self.min, self.max
        if np.isnan(lo) or np.isnan(hi):
            return 0.0
        return (lo + hi) / 2.0


class ColumnStore:
    """Owns canonical columns for one figure. Deduplicates by array identity so
    N traces over the same array hold the data once (§18's shared-columns win,
    per-figure scope in Phase 0)."""

    def __init__(self) -> None:
        self._columns: list[Column] = []
        self._by_key: dict[tuple[int, int], int] = {}  # (id(base), nbytes) -> col id

    def __len__(self) -> int:
        return len(self._columns)

    def __getitem__(self, col_id: int) -> Column:
        return self._columns[col_id]

    @property
    def columns(self) -> list[Column]:
        return self._columns

    def ingest(self, data: Any) -> Column:
        arr, kind, copies = _canonicalize(data)
        base = arr.base if arr.base is not None else arr
        key = (id(base), arr.nbytes)
        hit = self._by_key.get(key)
        if hit is not None and np.shares_memory(self._columns[hit].values, arr):
            return self._columns[hit]
        zone = ZoneMaps(*kernels.zone_maps(arr))
        col = Column(id=len(self._columns), values=arr, kind=kind, zone=zone, ingest_copies=copies)
        self._columns.append(col)
        self._by_key[key] = col.id
        return col

    def memory_report(self) -> dict[str, Any]:
        """Canonical bytes per column (§27: if a number isn't in the report, it
        isn't real). Derived/GPU classes are added as those caches land."""
        return {
            "canonical_bytes": int(sum(c.values.nbytes for c in self._columns)),
            "columns": [
                {
                    "id": c.id,
                    "kind": c.kind,
                    "len": len(c),
                    "bytes": int(c.values.nbytes),
                    "ingest_copies": c.ingest_copies,
                    "null_count": c.zone.null_count,
                }
                for c in self._columns
            ],
        }


def _canonicalize(data: Any) -> tuple[npt.NDArray[np.float64], str, int]:
    """To contiguous f64 (+ time detection), counting copies honestly (§29)."""
    # pandas Series / Index / Arrow-backed things all expose to_numpy.
    if hasattr(data, "to_numpy"):
        data = data.to_numpy()
    arr = np.asarray(data)

    kind = "float"
    copies = 0
    if np.issubdtype(arr.dtype, np.datetime64):
        # -> ms since epoch, exact below 2^53 (~year 287396).
        arr = arr.astype("datetime64[ms]").view(np.int64)
        kind = "time_ms"
    if arr.dtype != np.float64:
        arr = arr.astype(np.float64)  # one counted conversion copy
        copies += 1
    if not arr.flags.c_contiguous:
        arr = np.ascontiguousarray(arr)
        copies += 1
    if arr.ndim != 1:
        raise ValueError(f"columns must be 1-D, got shape {arr.shape}")
    return arr, kind, copies
