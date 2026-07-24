"""Spatial index — the Tier-3 out-of-core query path (dossier §28/§32b).

A companion to the out-of-core store (`_ooc`): where the pyramid answers
*zoomed-out* views in O(tiles), the spatial index answers *zoomed-in* views in
O(points in window) instead of O(N). Points are pre-sorted on disk into a
row-major grid of cells; a viewport reads only the cells it overlaps — one
contiguous slice per grid row — so deep zoom gets sharper *and* cheaper the
further you go.

Two on-disk generations share the reader:

- ``XYSPIDX1`` (positions only, produced by the OSM pipeline's external
  ``osm-sort``): f32 lon/lat planes. Points-band drills over v1 stay
  position-only — no channels to restore, no row ids for hover.
- ``XYSPIDX2`` (produced in-engine by :func:`build`): adds per-point
  **canonical row ids** (u32, or u64 past 2³²−1 rows) and optional
  **wire-quantized u8 channel planes** (continuous color/size exactly as the
  drill wire quantizes them; categorical color as its u8 codes). Row ids make
  index-served drills first-class: positions re-gather from the canonical f64
  columns (§16 — deep-zoom precision never rides the f32 cache), picks and
  selections translate exactly, and replies are byte-identical to the O(N)
  scan drill they replace. Within each cell, rows are stored in ascending
  canonical order.

All planes are derived **f32/u8 caches** (§27: canonical stays f64; every
derived buffer is rebuildable). Load is mmap-only — no data enters RAM until a
window touches it, and only that window's cells are paged in. The builder is a
two-pass streaming counting sort: every pass reads the canonical columns in
``_BUILD_CHUNK`` slices, so peak RAM stays chunk-bounded no matter how large N
grows (the same discipline as the chunked channel quantize, LOD doc §4.4).
"""

from __future__ import annotations

import contextlib
import os
import struct
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
import numpy.typing as npt

from . import kernels

_MAGIC_V1 = b"XYSPIDX1"
_MAGIC_V2 = b"XYSPIDX2"
_HEADER = 56  # magic(8) + g(4) + flags(4) + x0x1y0y1(32) + n(8)

# v2 header flags: which planes exist beside lon/lat.
_FLAG_ROWS_U32 = 1 << 0
_FLAG_ROWS_U64 = 1 << 1
_FLAG_COLOR_U8 = 1 << 2
_FLAG_SIZE_U8 = 1 << 3

# Builder pass chunk (rows). Bounds every transient the two passes make —
# cell ids, sort order, scatter positions — to a few hundred MB regardless
# of N; the outputs are written straight into the mapped plane files.
_BUILD_CHUNK = 1 << 22

# Final-plane bytes a build may scatter into directly. Beyond it, the random
# writes' working set no longer fits page cache next to the source columns
# and the build page-thrashes (measured: 12+ minutes for a 600M build's
# ~22 GB of I/O); the banded spill keeps every read and write sequential,
# and one band's planes stay comfortably cache-resident while it sorts.
_BAND_BUDGET = 1 << 28


@dataclass
class SpatialIndex:
    """Read-only view over an on-disk spatial index (v1 or v2)."""

    g: int
    x0: float
    x1: float
    y0: float
    y1: float
    n: int
    offsets: npt.NDArray[np.uint64]  # (g*g + 1,) cumulative cell offsets
    lon: np.memmap  # (n,) f32, sorted by cell
    lat: np.memmap  # (n,) f32, sorted by cell
    # v2 planes (None on v1 indexes): canonical row ids, ascending within each
    # cell, and wire-quantized u8 channel planes in the same order.
    rows: Optional[np.memmap] = None  # (n,) u32 or u64
    color_u8: Optional[np.memmap] = None  # (n,) u8
    size_u8: Optional[np.memmap] = None  # (n,) u8

    @classmethod
    def load(cls, prefix: str) -> SpatialIndex:
        with open(prefix + ".idx", "rb") as f:
            head = f.read(_HEADER)
            magic = head[:8]
            if magic not in (_MAGIC_V1, _MAGIC_V2):
                raise ValueError(f"{prefix}.idx is not a spatial index")
            g = struct.unpack_from("<I", head, 8)[0]
            flags = struct.unpack_from("<I", head, 12)[0] if magic == _MAGIC_V2 else 0
            x0, x1, y0, y1 = struct.unpack_from("<dddd", head, 16)
            n = struct.unpack_from("<Q", head, 48)[0]
            offsets = np.fromfile(f, dtype=np.uint64, count=g * g + 1)
        shape = (int(n),)

        def _plane(ext: str, dtype: Any) -> Any:
            # A memmap cannot map an empty file; n == 0 planes are 0 bytes on
            # disk (build truncates them) and read back as plain empty arrays.
            if n == 0:
                return np.empty(0, dtype=dtype)
            return np.memmap(prefix + ext, dtype=dtype, mode="r", shape=shape)

        lon = _plane(".lon.f32", np.float32)
        lat = _plane(".lat.f32", np.float32)
        rows = color_u8 = size_u8 = None
        if flags & _FLAG_ROWS_U32:
            rows = _plane(".rows.u32", np.uint32)
        elif flags & _FLAG_ROWS_U64:
            rows = _plane(".rows.u64", np.uint64)
        if flags & _FLAG_COLOR_U8:
            color_u8 = _plane(".color.u8", np.uint8)
        if flags & _FLAG_SIZE_U8:
            size_u8 = _plane(".size.u8", np.uint8)
        return cls(int(g), x0, x1, y0, y1, int(n), offsets, lon, lat, rows, color_u8, size_u8)

    def _cell_range(self, lo: float, hi: float, dlo: float, dhi: float) -> tuple[int, int]:
        span = dhi - dlo
        i0 = int((lo - dlo) / span * self.g)
        i1 = int((hi - dlo) / span * self.g)
        return max(0, min(self.g - 1, i0)), max(0, min(self.g - 1, i1))

    def window_count(self, x0: float, x1: float, y0: float, y1: float) -> int:
        """Points in the cells overlapping the window — O(rows), no point reads.
        A cheap upper bound on the exact in-window count (whole-cell overhang),
        used to decide whether an exact windowed bin is affordable."""
        ix0, ix1 = self._cell_range(x0, x1, self.x0, self.x1)
        iy0, iy1 = self._cell_range(y0, y1, self.y0, self.y1)
        g = self.g
        rows = self.offsets[(np.arange(iy0, iy1 + 1) * g)[:, None] + np.array([ix0, ix1 + 1])]
        return int((rows[:, 1] - rows[:, 0]).sum())

    def gather(
        self, x0: float, x1: float, y0: float, y1: float
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """The (lon, lat) of every point in the window's cells, as f64 for the
        f64 binning kernels. One contiguous memmap slice per grid row; only
        these cells are paged in. `density_grid` uses the f32 path directly and
        avoids this widening; this stays for callers that need f64."""
        lon, lat = self._gather_f32(x0, x1, y0, y1)
        return lon.astype(np.float64), lat.astype(np.float64)

    def density_grid(
        self, x0: float, x1: float, y0: float, y1: float, w: int, h: int
    ) -> npt.NDArray[np.float32]:
        """Exact density grid for the window at screen resolution, binned from
        only the in-window points (the cell overhang outside the window is
        discarded by `bin_2d`'s half-open range test).

        The sorted columns are f32, so bin them **directly** with the f32 kernel
        rather than gathering to f64 first: the f32→f64 widening copy of every
        in-window point otherwise dominates the query (~half the wall-clock on a
        30M-point window). One contiguous memmap slice per grid row is
        concatenated (no dtype change) and binned in a single parallel pass;
        the result is identical to `bin_2d` over the same points as f64."""
        lon, lat = self._gather_f32(x0, x1, y0, y1)
        return kernels.bin_2d_f32(lon, lat, x0, x1, y0, y1, w, h)

    def _window_slices(self, x0: float, x1: float, y0: float, y1: float) -> list[slice]:
        """The contiguous plane slices covering the window's cells, one per
        overlapped grid row — the shared walk behind every gather."""
        ix0, ix1 = self._cell_range(x0, x1, self.x0, self.x1)
        iy0, iy1 = self._cell_range(y0, y1, self.y0, self.y1)
        g = self.g
        out: list[slice] = []
        for iy in range(iy0, iy1 + 1):
            lo = int(self.offsets[iy * g + ix0])
            hi = int(self.offsets[iy * g + ix1 + 1])
            if hi > lo:
                out.append(slice(lo, hi))
        return out

    def _gather_f32(
        self, x0: float, x1: float, y0: float, y1: float
    ) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
        """Window points as **f32** (the on-disk dtype) — one contiguous memmap
        slice per grid row, concatenated with no widening. Backs `density_grid`;
        `gather` is the f64 view kept for callers that need f64 math."""
        slices = self._window_slices(x0, x1, y0, y1)
        if not slices:
            empty = np.empty(0, dtype=np.float32)
            return empty, empty
        return (
            np.concatenate([self.lon[s] for s in slices]),
            np.concatenate([self.lat[s] for s in slices]),
        )

    def gather_planes(self, x0: float, x1: float, y0: float, y1: float) -> dict[str, np.ndarray]:
        """Every stored plane over the window's cells, cell-major, aligned:
        ``{"lon", "lat"[, "rows"][, "color_u8"][, "size_u8"]}``. The caller
        window-tests once and applies the same mask to every plane."""
        slices = self._window_slices(x0, x1, y0, y1)
        planes: dict[str, Any] = {"lon": self.lon, "lat": self.lat}
        if self.rows is not None:
            planes["rows"] = self.rows
        if self.color_u8 is not None:
            planes["color_u8"] = self.color_u8
        if self.size_u8 is not None:
            planes["size_u8"] = self.size_u8
        if not slices:
            return {k: np.empty(0, dtype=v.dtype) for k, v in planes.items()}
        return {k: np.concatenate([v[s] for s in slices]) for k, v in planes.items()}


def default_grid_dim(n: int) -> int:
    """Power-of-two grid side for an n-point index: ~4k points per cell keeps
    `window_count`'s whole-cell overhang small next to the drill budget while
    the offsets table stays a few MB even at 10⁹⁺ rows."""
    import math

    ideal = math.sqrt(max(int(n), 1) / 4096.0)
    pow2 = 1 << max(0, math.ceil(math.log2(max(ideal, 1.0))))
    return int(min(4096, max(64, pow2)))


def build(
    prefix: str,
    x: npt.NDArray[np.float64],
    y: npt.NDArray[np.float64],
    *,
    color_u8: Optional[np.ndarray] = None,
    size_u8: Optional[np.ndarray] = None,
    g: Optional[int] = None,
    chunk: int = _BUILD_CHUNK,
    band_budget: int = _BAND_BUDGET,
) -> SpatialIndex:
    """Build an ``XYSPIDX2`` index from canonical columns (RAM or memmap).

    Two streaming passes of a counting sort, each reading the inputs in
    ``chunk``-row slices: pass 1 histograms cell occupancy into the offsets
    table; pass 2 places every finite row's planes into its cell's span,
    chunk order preserved within cells — so cells hold ascending canonical row
    ids by construction. Small builds scatter directly; builds whose final
    planes exceed ``band_budget`` bytes spill to per-band bucket files and
    finalize band by band so every read and write stays sequential (identical
    output bytes either way; the transient buckets cost roughly one extra
    copy of the planes plus a u32 cell id per row, deleted as bands
    complete). Non-finite rows are skipped exactly like the binning kernels
    (§19: NaN never reaches a vertex buffer). ``color_u8``/``size_u8`` must
    already be wire-quantized (the caller owns channel semantics; this module
    stores bytes), aligned with ``x``/``y``.
    """
    n_rows = len(x)
    if len(y) != n_rows:
        raise ValueError("x and y must have equal length")
    for name, plane in (("color_u8", color_u8), ("size_u8", size_u8)):
        if plane is not None and (plane.dtype != np.uint8 or len(plane) != n_rows):
            raise ValueError(f"{name} must be uint8 of the same length as x/y")
    g = int(g) if g else default_grid_dim(n_rows)
    if g < 2 or g & (g - 1):
        raise ValueError("grid dim must be a power of two >= 2")

    # Extent over finite rows only, chunked (min_max skips non-finite and
    # returns None for an all-NaN/empty chunk).
    x0 = y0 = np.inf
    x1 = y1 = -np.inf
    for s in range(0, n_rows, chunk):
        mx = kernels.min_max(x[s : s + chunk])
        my = kernels.min_max(y[s : s + chunk])
        if mx is not None:
            x0, x1 = min(x0, mx[0]), max(x1, mx[1])
        if my is not None:
            y0, y1 = min(y0, my[0]), max(y1, my[1])
    if not (np.isfinite(x0) and np.isfinite(x1) and np.isfinite(y0) and np.isfinite(y1)):
        # No finite rows: a valid, empty index (0-byte planes, all-zero
        # offsets) over a placeholder extent — the empty-column story of
        # `_ooc.MemmapF64Builder.finalize` applied to the derived cache.
        x0, x1, y0, y1 = 0.0, 1.0, 0.0, 1.0
    if x1 <= x0:
        x1 = x0 + 1.0
    if y1 <= y0:
        y1 = y0 + 1.0

    def cells_of(xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        cx = np.clip(((xs - x0) / (x1 - x0) * g).astype(np.int64), 0, g - 1)
        cy = np.clip(((ys - y0) / (y1 - y0) * g).astype(np.int64), 0, g - 1)
        return cy * g + cx

    # Pass 1: cell occupancy.
    counts = np.zeros(g * g, dtype=np.int64)
    for s in range(0, n_rows, chunk):
        xs = np.asarray(x[s : s + chunk], dtype=np.float64)
        ys = np.asarray(y[s : s + chunk], dtype=np.float64)
        finite = np.isfinite(xs) & np.isfinite(ys)
        if not finite.all():
            xs, ys = xs[finite], ys[finite]
        counts += np.bincount(cells_of(xs, ys), minlength=g * g)
    n = int(counts.sum())
    offsets = np.zeros(g * g + 1, dtype=np.uint64)
    np.cumsum(counts, out=offsets[1:])

    rows_dtype = np.uint32 if n_rows <= np.iinfo(np.uint32).max else np.uint64
    flags = _FLAG_ROWS_U32 if rows_dtype == np.uint32 else _FLAG_ROWS_U64
    if color_u8 is not None:
        flags |= _FLAG_COLOR_U8
    if size_u8 is not None:
        flags |= _FLAG_SIZE_U8

    shape = (max(n, 1),)  # a memmap cannot map an empty file
    lon_mm = np.memmap(prefix + ".lon.f32", dtype=np.float32, mode="w+", shape=shape)
    lat_mm = np.memmap(prefix + ".lat.f32", dtype=np.float32, mode="w+", shape=shape)
    rows_ext = ".rows.u32" if rows_dtype == np.uint32 else ".rows.u64"
    rows_mm = np.memmap(prefix + rows_ext, dtype=rows_dtype, mode="w+", shape=shape)
    color_mm = (
        np.memmap(prefix + ".color.u8", dtype=np.uint8, mode="w+", shape=shape)
        if color_u8 is not None
        else None
    )
    size_mm = (
        np.memmap(prefix + ".size.u8", dtype=np.uint8, mode="w+", shape=shape)
        if size_u8 is not None
        else None
    )

    # Pass 2: stable scatter, BANDED for large builds. A direct scatter
    # writes each chunk to cell positions spread across the whole output —
    # random writes whose working set is every plane at once, which
    # page-thrashes as soon as planes + source columns exceed RAM (measured:
    # a 600M build spent 12+ minutes on ~22 GB of I/O). When the final
    # planes exceed `band_budget`, the grid's rows split into contiguous
    # bands sized to fit it, chunks SPILL to per-band bucket files
    # (sequential appends), and each band then loads, stable-sorts by cell,
    # and writes its contiguous slice of every plane — sequential I/O end to
    # end, identical bytes to the direct scatter (chunk append order + the
    # stable in-band sort reproduce ascending canonical order per cell).
    # Bucket files cost one extra transient copy of the planes (+ a u32 cell
    # per row) and are deleted band by band.
    per_row_bytes = 4 + 4 + np.dtype(rows_dtype).itemsize
    per_row_bytes += 1 if color_u8 is not None else 0
    per_row_bytes += 1 if size_u8 is not None else 0
    row_starts = offsets[::g].astype(np.int64)  # cumulative rows at each grid-row boundary
    n_bands = max(1, -(-(n * per_row_bytes) // band_budget)) if n else 1
    if n_bands > 1:
        # Split grid rows into bands of ≈ equal ROW COUNT (not equal iy):
        # a dense stripe otherwise blows one band past the budget.
        targets = np.linspace(0, n, n_bands + 1)[1:-1]
        cut_iy = np.unique(np.searchsorted(row_starts, targets, side="left"))
        band_iy = np.concatenate(([0], cut_iy, [g]))
        band_iy = np.unique(band_iy)
    else:
        band_iy = np.array([0, g])
    band_of_iy = np.repeat(np.arange(len(band_iy) - 1), np.diff(band_iy))

    if len(band_iy) - 1 == 1:
        # Fits the budget: the direct scatter's working set is cache-resident.
        cursor = offsets[:-1].astype(np.int64)
        for s in range(0, n_rows, chunk):
            xs = np.asarray(x[s : s + chunk], dtype=np.float64)
            ys = np.asarray(y[s : s + chunk], dtype=np.float64)
            finite = np.isfinite(xs) & np.isfinite(ys)
            local = np.flatnonzero(finite)
            if not len(local):
                continue
            xs, ys = xs[local], ys[local]
            cells = cells_of(xs, ys)
            order = np.argsort(cells, kind="stable")
            cs = cells[order]
            uniq, first, per_cell = np.unique(cs, return_index=True, return_counts=True)
            within = np.arange(len(cs), dtype=np.int64) - np.repeat(first, per_cell)
            pos = cursor[cs] + within
            cursor[uniq] += per_cell
            lon_mm[pos] = xs[order].astype(np.float32)
            lat_mm[pos] = ys[order].astype(np.float32)
            rows_mm[pos] = (s + local[order]).astype(rows_dtype)
            if color_mm is not None and color_u8 is not None:
                plane = np.asarray(color_u8[s : s + chunk])[local]
                color_mm[pos] = plane[order]
            if size_mm is not None and size_u8 is not None:
                plane = np.asarray(size_u8[s : s + chunk])[local]
                size_mm[pos] = plane[order]
    else:
        n_b = len(band_iy) - 1
        plane_exts = ["cell.u32", "lon.f32", "lat.f32", "rows"]
        if color_u8 is not None:
            plane_exts.append("color.u8")
        if size_u8 is not None:
            plane_exts.append("size.u8")

        def bucket_path(b: int, ext: str) -> str:
            return f"{prefix}.band{b:04d}.{ext}"

        try:
            # Pass 2a: spill each chunk's rows to their bands, in chunk order
            # (sequential appends only). The cell id rides the bucket so pass
            # 2b never re-derives it from the f32-rounded positions.
            with contextlib.ExitStack() as stack:
                bucket_files = [
                    {
                        ext: stack.enter_context(open(bucket_path(b, ext), "wb"))
                        for ext in plane_exts
                    }
                    for b in range(n_b)
                ]
                for s in range(0, n_rows, chunk):
                    xs = np.asarray(x[s : s + chunk], dtype=np.float64)
                    ys = np.asarray(y[s : s + chunk], dtype=np.float64)
                    finite = np.isfinite(xs) & np.isfinite(ys)
                    local = np.flatnonzero(finite)
                    if not len(local):
                        continue
                    xs, ys = xs[local], ys[local]
                    cells = cells_of(xs, ys)
                    bands = band_of_iy[cells // g]
                    rows_ids = (s + local).astype(rows_dtype)
                    cplane = (
                        np.asarray(color_u8[s : s + chunk])[local] if color_u8 is not None else None
                    )
                    splane = (
                        np.asarray(size_u8[s : s + chunk])[local] if size_u8 is not None else None
                    )
                    for b in np.unique(bands):
                        m = bands == b
                        files = bucket_files[b]
                        cells[m].astype(np.uint32).tofile(files["cell.u32"])
                        xs[m].astype(np.float32).tofile(files["lon.f32"])
                        ys[m].astype(np.float32).tofile(files["lat.f32"])
                        rows_ids[m].tofile(files["rows"])
                        if cplane is not None:
                            cplane[m].tofile(files["color.u8"])
                        if splane is not None:
                            splane[m].tofile(files["size.u8"])
            # Pass 2b: one band at a time — load (sequential), stable-sort by
            # cell, write the band's contiguous slice of every plane
            # (sequential), delete its buckets.
            for b in range(n_b):
                cells_b = np.fromfile(bucket_path(b, "cell.u32"), dtype=np.uint32)
                if len(cells_b):
                    lo = int(row_starts[band_iy[b]])
                    hi = lo + len(cells_b)
                    # A band holds exactly its grid rows' points; a mismatch
                    # means a spill bug and must fail loudly, not corrupt.
                    assert hi == int(row_starts[band_iy[b + 1]])
                    order = np.argsort(cells_b, kind="stable")
                    lon_b = np.fromfile(bucket_path(b, "lon.f32"), dtype=np.float32)
                    lat_b = np.fromfile(bucket_path(b, "lat.f32"), dtype=np.float32)
                    rows_b = np.fromfile(bucket_path(b, "rows"), dtype=rows_dtype)
                    lon_mm[lo:hi] = lon_b[order]
                    lat_mm[lo:hi] = lat_b[order]
                    rows_mm[lo:hi] = rows_b[order]
                    if color_mm is not None:
                        cb = np.fromfile(bucket_path(b, "color.u8"), dtype=np.uint8)
                        color_mm[lo:hi] = cb[order]
                    if size_mm is not None:
                        sb = np.fromfile(bucket_path(b, "size.u8"), dtype=np.uint8)
                        size_mm[lo:hi] = sb[order]
                for ext in plane_exts:
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(bucket_path(b, ext))
        finally:
            for b in range(n_b):
                for ext in plane_exts:
                    with contextlib.suppress(FileNotFoundError):
                        os.remove(bucket_path(b, ext))

    for mm in (lon_mm, lat_mm, rows_mm, color_mm, size_mm):
        if mm is not None:
            mm.flush()
    if n == 0:
        # Truncate the placeholder row the memmaps needed; the reader maps
        # zero-length planes as empty arrays via n in the header.
        for path in (
            prefix + ".lon.f32",
            prefix + ".lat.f32",
            prefix + rows_ext,
            *((prefix + ".color.u8",) if color_mm is not None else ()),
            *((prefix + ".size.u8",) if size_mm is not None else ()),
        ):
            with open(path, "r+b") as f:
                f.truncate(0)

    with open(prefix + ".idx", "wb") as f:
        head = bytearray(_HEADER)
        head[:8] = _MAGIC_V2
        struct.pack_into("<I", head, 8, g)
        struct.pack_into("<I", head, 12, flags)
        struct.pack_into("<dddd", head, 16, x0, x1, y0, y1)
        struct.pack_into("<Q", head, 48, n)
        f.write(bytes(head))
        offsets.tofile(f)
    return SpatialIndex.load(prefix)


def remove_index_files(prefix: str) -> None:
    """Delete every plane an index prefix may own (missing files ignored) —
    the cleanup half of temp-dir builds, used by the trace finalizer."""
    for ext in (".idx", ".lon.f32", ".lat.f32", ".rows.u32", ".rows.u64", ".color.u8", ".size.u8"):
        with contextlib.suppress(FileNotFoundError):
            os.remove(prefix + ext)
