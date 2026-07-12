"""The column store: canonical, typed, single-copy (§4).

Phase 0 contract:
- Canonical data lives CPU-side as contiguous NumPy float64; every encoded /
  decimated buffer is a *derived cache*, recomputable from here (§27 rule 1).
- Time columns (datetime64 / pandas datetime) are canonicalized to **ms since
  epoch as f64** — exact for |t| < 2^53, i.e. every real-world ms timestamp.
- pyarrow Arrays / ChunkedArrays ingest **zero-copy** when null-free and
  primitive (see `_arrow_to_numpy`); nulls/chunking pay counted copies.
  i64-nanosecond end-to-end fidelity (§16) is still a later milestone.
- Zone maps (§22) are computed once at ingest — one pass, reused for autorange,
  offset selection, and (later) Tier-3 pruning.
- Ingest copy count is recorded, not hidden (§29: copies are counted, reported,
  never folklore).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
import numpy.typing as npt

from . import kernels

ColumnStoreCheckpoint = tuple[int, dict[tuple[int, int, int], int]]

# Zone-map chunk size — must match the kernels' default (§22) so incremental
# appends splice tail chunks that align with a from-scratch recompute.
ZONE_CHUNK = 65_536


@dataclass
class ZoneMaps:
    """Per-chunk statistics (§22)."""

    mins: npt.NDArray[np.float64]
    maxs: npt.NDArray[np.float64]
    counts: npt.NDArray[np.uint64]
    null_counts: npt.NDArray[np.uint64]
    sums: npt.NDArray[np.float64]
    sum_sqs: npt.NDArray[np.float64]
    positive_mins: npt.NDArray[np.float64]
    positive_maxs: npt.NDArray[np.float64]

    # The folded reductions are cached: instances are replaced wholesale when a
    # column changes (`Column.append` builds a fresh ZoneMaps), never mutated in
    # place, so the fold is a pure function of construction-time state. Autorange
    # and offset selection read min/max several times per payload build.

    @cached_property
    def min(self) -> float:
        valid = self.mins[self.counts > 0]
        return float(valid.min()) if len(valid) else float("nan")

    @cached_property
    def max(self) -> float:
        valid = self.maxs[self.counts > 0]
        return float(valid.max()) if len(valid) else float("nan")

    @cached_property
    def positive_min(self) -> float:
        valid = self.positive_mins[np.isfinite(self.positive_mins)]
        return float(valid.min()) if len(valid) else float("nan")

    @cached_property
    def positive_max(self) -> float:
        valid = self.positive_maxs[np.isfinite(self.positive_maxs)]
        return float(valid.max()) if len(valid) else float("nan")

    @cached_property
    def count(self) -> int:
        return int(self.counts.sum())

    @cached_property
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

    def append(self, data: Any) -> None:
        """Streaming append (rust-engine §5, Phase-0 Python-side).

        Canonicalizes `data` like ingest and extends this column in place:

        - **Amortized growth buffer**: values live in a capacity-doubling
          backing array, so a long append stream pays O(N) total copies, not
          O(N) per append. Migrations are counted in `ingest_copies` (§29);
          the tail write itself is inherent to appending, not a copy on the
          books. (Zero-copy Arrow views migrate on first append — the read-only
          Arrow buffer cannot be grown in place.)
        - **Incremental zone maps** (§22): only chunks at or after the old
          length are recomputed; the splice is bitwise identical to a
          from-scratch recompute because chunks fold serially either way.
        - Kind is sticky: appending floats to a `time_ms` column (or vice
          versa) raises rather than silently mixing units.
        """
        arr, kind, _copies = _canonicalize(data)
        if kind != self.kind:
            raise ValueError(f"appended values are {kind!r}, column is {self.kind!r}")
        if len(arr) == 0:
            return
        n_old = len(self.values)
        n_new = n_old + len(arr)
        grow = getattr(self, "_grow", None)
        if grow is None or grow.shape[0] < n_new:
            cap = max(n_new, n_old * 2, 1024)
            new_buf = np.empty(cap, dtype=np.float64)
            new_buf[:n_old] = self.values
            self._grow = new_buf
            self.ingest_copies += 1  # the migration is the O(N) event
        self._grow[n_old:n_new] = arr
        self.values = self._grow[:n_new]
        # Recompute only the tail: the last (possibly partial) old chunk plus
        # everything new. Slicing at a chunk boundary keeps alignment with a
        # full recompute, so autorange/pruning consumers see identical maps.
        k = n_old // ZONE_CHUNK
        tail = ZoneMaps(*kernels.zone_maps(self.values[k * ZONE_CHUNK :]))
        z = self.zone
        self.zone = ZoneMaps(
            mins=np.concatenate([z.mins[:k], tail.mins]),
            maxs=np.concatenate([z.maxs[:k], tail.maxs]),
            counts=np.concatenate([z.counts[:k], tail.counts]),
            null_counts=np.concatenate([z.null_counts[:k], tail.null_counts]),
            sums=np.concatenate([z.sums[:k], tail.sums]),
            sum_sqs=np.concatenate([z.sum_sqs[:k], tail.sum_sqs]),
            positive_mins=np.concatenate([z.positive_mins[:k], tail.positive_mins]),
            positive_maxs=np.concatenate([z.positive_maxs[:k], tail.positive_maxs]),
        )


class ColumnStore:
    """Owns canonical columns for one figure. Deduplicates by array identity so
    N traces over the same array hold the data once (§18's shared-columns win,
    per-figure scope in Phase 0)."""

    def __init__(self) -> None:
        self._columns: list[Column] = []
        self._by_key: dict[tuple[int, int, int], int] = {}  # (id(base), data_ptr, nbytes)

    def __len__(self) -> int:
        return len(self._columns)

    def __getitem__(self, col_id: int) -> Column:
        return self._columns[col_id]

    @property
    def columns(self) -> list[Column]:
        return self._columns

    def checkpoint(self) -> ColumnStoreCheckpoint:
        """Capture a cheap rollback point for multi-column trace builders."""
        return (len(self._columns), dict(self._by_key))

    def rollback(self, checkpoint: ColumnStoreCheckpoint) -> None:
        """Restore a checkpoint captured before speculative ingests."""
        length, by_key = checkpoint
        del self._columns[length:]
        self._by_key = dict(by_key)

    def ingest(self, data: Any) -> Column:
        arr, kind, copies = _canonicalize(data)
        base = arr.base if arr.base is not None else arr
        data_ptr = int(arr.__array_interface__["data"][0])
        key = (id(base), data_ptr, arr.nbytes)
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


def _arrow_to_numpy(data: Any) -> tuple[npt.NDArray[Any], int] | None:
    """Ingest a pyarrow Array/ChunkedArray, zero-copy when possible.

    Detected by module name so xy itself never imports pyarrow (it
    stays an optional input format, not a dependency). The contract, with
    copies counted honestly (§29):

    - null-free primitive numeric Array — the shape Arrow-native pipelines
      ship — becomes a **zero-copy** (read-only) NumPy view of the Arrow
      buffer; canonical columns are never written in place, so read-only is
      safe.
    - nulls force one counted copy: numerics are cast to float64 so nulls
      materialize as NaN (the engine-wide null encoding, §19); temporal
      arrays convert to datetime64 with NaT and take the existing time path.
    - a multi-chunk ChunkedArray (a Table column) pays one counted
      concatenation first; single-chunk is unwrapped for free.

    Returns None when `data` is not a pyarrow value.
    """
    if (type(data).__module__ or "").split(".", 1)[0] != "pyarrow":
        return None
    copies = 0
    if hasattr(data, "combine_chunks"):  # ChunkedArray
        if data.num_chunks == 1:
            data = data.chunk(0)
        else:
            data = data.combine_chunks()
            copies += 1
    if not (hasattr(data, "null_count") and hasattr(data, "to_numpy")):
        return None  # a Table/scalar/etc. — let the generic error path speak
    if data.null_count == 0:
        try:
            return data.to_numpy(), copies  # zero_copy_only=True by default
        except Exception:
            pass  # non-primitive layout (strings, dictionaries…): fall through
    kind = str(data.type)
    if not (kind.startswith("timestamp") or kind.startswith("date")):
        try:
            cast = data.cast("float64")
        except Exception as e:
            raise ValueError("columns must be real numeric or datetime-like") from e
        if cast is not data:
            copies += 1
        data = cast
    return data.to_numpy(zero_copy_only=False), copies + 1


def _canonicalize(data: Any) -> tuple[npt.NDArray[np.float64], str, int]:
    """To contiguous f64 (+ time detection), counting copies honestly (§29)."""
    arrow_copies = 0
    arrow = _arrow_to_numpy(data)
    if arrow is not None:
        data, arrow_copies = arrow
    # pandas Series / Index / Arrow-backed things all expose to_numpy.
    elif hasattr(data, "to_numpy"):
        data = data.to_numpy()
    arr = np.asarray(data)
    if arr.ndim != 1:
        raise ValueError(f"columns must be 1-D, got shape {arr.shape}")

    kind = "float"
    copies = arrow_copies
    if np.issubdtype(arr.dtype, np.datetime64) or _is_datetime_object_array(arr):
        arr, copies = _datetime_to_float_ms(arr, copies)
        kind = "time_ms"
    else:
        if np.issubdtype(arr.dtype, np.bool_):
            raise ValueError("columns must be real numeric or datetime-like, not boolean")
        if np.issubdtype(arr.dtype, np.complexfloating):
            raise ValueError("columns must be real numeric or datetime-like")
        if arr.dtype == object and any(isinstance(value, (bool, np.bool_)) for value in arr):
            raise ValueError("columns must be real numeric or datetime-like, not boolean")
        try:
            arr, copies = _astype_counted(arr, np.float64, copies)
        except (TypeError, ValueError) as e:
            raise ValueError("columns must be real numeric or datetime-like") from e
    if not arr.flags.c_contiguous:
        arr = np.ascontiguousarray(arr)
        copies += 1
    return arr, kind, copies


def _datetime_to_float_ms(
    arr: npt.NDArray[Any], copies: int
) -> tuple[npt.NDArray[np.float64], int]:
    """Canonicalize datetime-like columns to f64 ms, preserving nulls as NaN."""
    try:
        dt_ms, copies = _astype_counted(arr, "datetime64[ms]", copies)
    except (TypeError, ValueError) as e:
        raise ValueError("columns must be real numeric or datetime-like") from e
    nat = np.isnat(dt_ms)
    out, copies = _astype_counted(dt_ms.view(np.int64), np.float64, copies)
    if np.any(nat):
        out[nat] = np.nan
    return out, copies


def _astype_counted(arr: npt.NDArray[Any], dtype: Any, copies: int) -> tuple[npt.NDArray[Any], int]:
    out = arr.astype(dtype, copy=False)
    if out is not arr and not np.shares_memory(out, arr):
        copies += 1
    return out, copies


def _is_datetime_object_array(arr: npt.NDArray[Any]) -> bool:
    """Detect Python datetime/date object arrays without classifying strings."""
    if arr.dtype != object:
        return False
    for value in arr:
        if _is_object_missing(value):
            continue
        return isinstance(value, (dt.datetime, dt.date, np.datetime64))
    return False


def _is_object_missing(value: Any) -> bool:
    if value is None:
        return True
    if value.__class__.__name__ in {"NAType", "NaTType"}:
        return True
    if isinstance(value, float):
        return bool(np.isnan(value))
    return False
