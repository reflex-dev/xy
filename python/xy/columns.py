"""The column store: canonical, typed, single-copy (§4).

Phase 0 contract:
- Canonical data lives CPU-side as contiguous NumPy float64; every encoded /
  decimated buffer is a *derived cache*, recomputable from here (§27 rule 1).
- Time columns (datetime64 / pandas datetime) are canonicalized to **ms since
  epoch as f64** — exact for |t| < 2^53, i.e. every real-world ms timestamp.
- pyarrow Arrays / ChunkedArrays ingest **zero-copy** when null-free and
  primitive (see `_arrow_to_numpy`); nulls/chunking pay counted copies.
  i64-nanosecond end-to-end fidelity (§16) is still a later milestone.
- Zone maps (§22) are computed once and reused for autorange, offset selection,
  and (later) Tier-3 pruning. Explicit-domain heatmap grids defer that scan
  until a statistics consumer actually asks for it; their render path already
  has all policy inputs and never needs the maps.
- Ingest copy count is recorded, not hidden (§29: copies are counted, reported,
  never folklore).
"""

from __future__ import annotations

import datetime as dt
import math
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
    """Per-chunk column statistics (min/max/counts; design dossier §22)."""

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
        """Column-wide minimum over non-empty zones (NaN when all-null)."""
        valid = self.mins[self.counts > 0]
        return min(valid.tolist()) if len(valid) else float("nan")

    @cached_property
    def max(self) -> float:
        """Column-wide maximum over non-empty zones (NaN when all-null)."""
        valid = self.maxs[self.counts > 0]
        return max(valid.tolist()) if len(valid) else float("nan")

    @cached_property
    def positive_min(self) -> float:
        """Smallest strictly-positive value (for log-scale domains)."""
        valid = self.positive_mins[np.isfinite(self.positive_mins)]
        return min(valid.tolist()) if len(valid) else float("nan")

    @cached_property
    def positive_max(self) -> float:
        """Largest strictly-positive value (for log-scale domains)."""
        valid = self.positive_maxs[np.isfinite(self.positive_maxs)]
        return max(valid.tolist()) if len(valid) else float("nan")

    @cached_property
    def count(self) -> int:
        """Total finite-value count across zones."""
        return int(self.counts.sum())

    @cached_property
    def null_count(self) -> int:
        """Total NaN/null count across zones."""
        return int(self.null_counts.sum())


@dataclass
class Column:
    """A canonical column: values + zone maps + provenance."""

    id: int
    values: npt.NDArray[np.float64]  # contiguous f64, the single source of truth
    kind: str  # "float" | "time_ms"
    _zone: ZoneMaps | None
    ingest_copies: int  # copies paid at ingest (§29 accounting)

    def __len__(self) -> int:
        return len(self.values)

    @property
    def zone(self) -> ZoneMaps:
        """Materialize deferred statistics at most once."""
        if self._zone is None:
            self._zone = ZoneMaps(*kernels.zone_maps(self.values))
        return self._zone

    @property
    def min(self) -> float:
        """Column minimum, materializing zone maps on first use."""
        return self.zone.min

    @property
    def max(self) -> float:
        """Column maximum, materializing zone maps on first use."""
        return self.zone.max

    def suggest_offset(self) -> float:
        """Midpoint offset for relative-f32 encoding (design dossier §4).
        Re-centering on deep zoom (§16 there) picks a new offset at the
        viewport center instead."""
        lo, hi = self.min, self.max
        if np.isnan(lo) or np.isnan(hi):
            return 0.0
        return (lo + hi) / 2.0

    def append(self, data: Any) -> None:
        """Streaming append (design dossier §5, Phase-0 Python-side).

        Canonicalizes `data` like ingest and extends this column in place:

        - **Amortized growth buffer**: values live in a capacity-doubling
          backing array, so a long append stream pays O(N) total copies, not
          O(N) per append. Migrations are counted in `ingest_copies`;
          the tail write itself is inherent to appending, not a copy on the
          books. (Zero-copy Arrow views migrate on first append — the read-only
          Arrow buffer cannot be grown in place.)
        - **Incremental zone maps**: only chunks at or after the old
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
        self._zone = ZoneMaps(
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
    """Owns canonical columns for one figure. Deduplicates by array identity
    so N traces over the same array hold the data once (the design dossier's
    §18 shared-columns win; per-figure scope in Phase 0)."""

    def __init__(self) -> None:
        self._columns: list[Column] = []
        self._by_key: dict[tuple[int, int, int], int] = {}  # (id(base), data_ptr, nbytes)

    def __len__(self) -> int:
        return len(self._columns)

    def __getitem__(self, col_id: int) -> Column:
        return self._columns[col_id]

    @property
    def columns(self) -> list[Column]:
        """All ingested columns, in id order."""
        return self._columns

    def checkpoint(self) -> ColumnStoreCheckpoint:
        """Capture a cheap rollback point for multi-column trace builders."""
        return (len(self._columns), dict(self._by_key))

    def rollback(self, checkpoint: ColumnStoreCheckpoint) -> None:
        """Restore a checkpoint captured before speculative ingests."""
        length, by_key = checkpoint
        del self._columns[length:]
        self._by_key = dict(by_key)

    @staticmethod
    def _array_key(arr: np.ndarray) -> tuple[int, int, int]:
        base = arr.base if arr.base is not None else arr
        return (id(base), int(arr.__array_interface__["data"][0]), arr.nbytes)

    def _lookup(self, arr: np.ndarray, key: tuple[int, int, int]) -> Column | None:
        hit = self._by_key.get(key)
        if hit is not None and np.shares_memory(self._columns[hit].values, arr):
            return self._columns[hit]
        return None

    def _append_canonical(
        self,
        arr: npt.NDArray[np.float64],
        kind: str,
        copies: int,
        key: tuple[int, int, int],
        zone: ZoneMaps | None,
    ) -> Column:
        col = Column(
            id=len(self._columns),
            values=arr,
            kind=kind,
            _zone=zone,
            ingest_copies=copies,
        )
        self._columns.append(col)
        self._by_key[key] = col.id
        return col

    def _ingest_canonical(
        self,
        arr: npt.NDArray[np.float64],
        kind: str,
        copies: int,
        *,
        defer_zone_maps: bool,
    ) -> Column:
        key = self._array_key(arr)
        col = self._lookup(arr, key)
        if col is not None:
            if not defer_zone_maps:
                _ = col.zone
            return col
        zone = None if defer_zone_maps else ZoneMaps(*kernels.zone_maps(arr))
        return self._append_canonical(arr, kind, copies, key, zone)

    def ingest(self, data: Any, *, defer_zone_maps: bool = False) -> Column:
        """Canonicalize ``data`` to an f64 `Column`, deduplicating repeats.

        ``defer_zone_maps=True`` postpones the statistics fold until first
        use (streaming builders re-fold anyway).
        """
        arr, kind, copies = _canonicalize(data)
        return self._ingest_canonical(
            arr,
            kind,
            copies,
            defer_zone_maps=defer_zone_maps,
        )

    def ingest_pair(self, x: Any, y: Any) -> tuple[Column, Column]:
        """Ingest equal-length x/y columns with one paired statistics call.

        The fused path applies only when both canonical arrays are new and
        distinct. Existing/shared columns retain the ordinary deduplication
        behavior, including deferred-zone materialization.
        """
        x_arr, x_kind, x_copies = _canonicalize(x)
        y_arr, y_kind, y_copies = _canonicalize(y)
        if len(x_arr) != len(y_arr):
            raise ValueError(f"x and y must have equal length, got {len(x_arr)} and {len(y_arr)}")
        x_key = self._array_key(x_arr)
        y_key = self._array_key(y_arr)
        x_hit = self._lookup(x_arr, x_key)
        y_hit = self._lookup(y_arr, y_key)
        if (
            x_hit is not None
            or y_hit is not None
            or (x_key == y_key and np.shares_memory(x_arr, y_arr))
        ):
            return (
                self._ingest_canonical(
                    x_arr,
                    x_kind,
                    x_copies,
                    defer_zone_maps=False,
                ),
                self._ingest_canonical(
                    y_arr,
                    y_kind,
                    y_copies,
                    defer_zone_maps=False,
                ),
            )
        x_zone_raw, y_zone_raw = kernels.zone_maps_pair(x_arr, y_arr)
        x_col = self._append_canonical(
            x_arr,
            x_kind,
            x_copies,
            x_key,
            ZoneMaps(*x_zone_raw),
        )
        y_col = self._append_canonical(
            y_arr,
            y_kind,
            y_copies,
            y_key,
            ZoneMaps(*y_zone_raw),
        )
        return x_col, y_col

    def memory_report(self) -> dict[str, Any]:
        """Canonical bytes per column — if a number isn't in the report, it
        isn't real (design dossier §27). Derived/GPU classes are added as
        those caches land."""
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
    if np.issubdtype(arr.dtype, np.datetime64) and arr.dtype.isnative:
        ratio = _fixed_datetime_ms_ratio(arr.dtype)
        if ratio is not None:
            numerator, denominator = ratio
            try:
                # The native loop consumes the datetime array's i64 view at
                # its original stride and writes canonical f64 ms directly:
                # one full-size output, rather than datetime64[ms] plus f64.
                return (
                    kernels.datetime64_to_ms(arr.view(np.int64), numerator, denominator),
                    copies + 1,
                )
            except ValueError:
                # Exotic dtype multipliers outside the int64 ABI ratio keep
                # NumPy's general calendar-aware fallback below.
                pass
    try:
        dt_ms, copies = _astype_counted(arr, "datetime64[ms]", copies)
    except (TypeError, ValueError) as e:
        raise ValueError("columns must be real numeric or datetime-like") from e
    nat = np.isnat(dt_ms)
    out, copies = _astype_counted(dt_ms.view(np.int64), np.float64, copies)
    if np.any(nat):
        out[nat] = np.nan
    return out, copies


_FIXED_DATETIME_MS_RATIOS: dict[str, tuple[int, int]] = {
    "W": (7 * 24 * 60 * 60 * 1000, 1),
    "D": (24 * 60 * 60 * 1000, 1),
    "h": (60 * 60 * 1000, 1),
    "m": (60 * 1000, 1),
    "s": (1000, 1),
    "ms": (1, 1),
    "us": (1, 1000),
    "ns": (1, 1_000_000),
    "ps": (1, 1_000_000_000),
    "fs": (1, 1_000_000_000_000),
    "as": (1, 1_000_000_000_000_000),
}


def _fixed_datetime_ms_ratio(dtype: np.dtype[Any]) -> tuple[int, int] | None:
    """Milliseconds per datetime tick for fixed-duration NumPy units.

    Years and months deliberately return ``None``: their conversion is
    calendar-dependent, so NumPy remains the correctness oracle for them.
    """
    unit, step = np.datetime_data(dtype)
    base = _FIXED_DATETIME_MS_RATIOS.get(unit)
    if base is None:
        return None
    numerator = int(base[0]) * int(step)
    denominator = int(base[1])
    # Reduce before crossing the fixed-width C ABI. This also handles dtypes
    # such as datetime64[1000us] as the exact 1 ms/tick ratio.
    divisor = math.gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor


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
