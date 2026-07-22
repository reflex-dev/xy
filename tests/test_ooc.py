"""Out-of-core canonical columns (§27 "mmap (native)"; §2 100M+ out-of-core).

The engine's canonical store is CPU-side truth (§27 rule 1); on native that
truth may live in a disk-backed ``np.memmap`` instead of RAM. These tests pin
the contract that makes 1B+-row scatters renderable with resident memory
bounded by the *screen*, not the data:

  - a memmap column ingests **without a RAM copy** of the data,
  - it flows through the ordinary public scatter API unchanged,
  - ``memory_report`` counts mapped bytes honestly, separate from RAM-resident
    canonical bytes (§27: "if a number isn't in the report, it isn't real"),
  - density first-paint and pyramid views stay screen-bounded.
"""

from __future__ import annotations

import numpy as np

import xy
from xy._ooc import MemmapF64Builder, is_memmapped, open_f64
from xy.columns import ColumnStore


def _build(tmp_path, name, values, capacity=None):
    arr = np.asarray(values, dtype=np.float64)
    b = MemmapF64Builder(tmp_path / name, capacity=capacity or max(len(arr), 1))
    # Stream in two chunks to exercise the append cursor.
    half = len(arr) // 2
    b.extend(arr[:half])
    b.extend(arr[half:])
    return b.finalize()


def test_builder_roundtrip_and_growth(tmp_path):
    data = np.arange(1000, dtype=np.float64)
    # Tiny initial capacity forces at least one doubling grow.
    b = MemmapF64Builder(tmp_path / "x.f64", capacity=8)
    for i in range(0, 1000, 100):
        b.extend(data[i : i + 100])
    view = b.finalize()
    assert isinstance(view, np.memmap)
    assert len(view) == 1000
    np.testing.assert_array_equal(np.asarray(view), data)
    # Reopen from disk independently.
    assert np.array_equal(np.asarray(open_f64(tmp_path / "x.f64")), data)


def test_empty_builder(tmp_path):
    view = MemmapF64Builder(tmp_path / "e.f64").finalize()
    assert len(view) == 0
    assert is_memmapped(view)


def test_ingest_is_zero_copy_and_disk_backed(tmp_path):
    col = _build(tmp_path, "x.f64", np.linspace(0, 1, 5000))
    store = ColumnStore()
    ingested = store.ingest(col)
    # The store kept the memmap backing — no RAM materialization of the data.
    assert is_memmapped(ingested.values)
    assert np.shares_memory(ingested.values, col)
    assert ingested.ingest_copies == 0
    rep = store.memory_report()
    assert rep["canonical_bytes"] == 0  # nothing resident in RAM
    assert rep["canonical_mapped_bytes"] == 5000 * 8
    assert rep["columns"][0]["backing"] == "memmap"


def test_in_ram_report_unchanged():
    # Regression guard: an all-RAM figure reports mapped=0 and the same
    # canonical_bytes it always did.
    store = ColumnStore()
    store.ingest(np.arange(1000, dtype=np.float64))
    rep = store.memory_report()
    assert rep["canonical_bytes"] == 1000 * 8
    assert rep["canonical_mapped_bytes"] == 0
    assert rep["columns"][0]["backing"] == "ram"


def test_zone_maps_match_in_ram(tmp_path):
    # Statistics computed over a memmap must equal those over the same RAM data.
    data = np.concatenate([np.linspace(-50, 50, 4096), [np.nan, 1e9, -1e9]])
    mm = _build(tmp_path, "z.f64", data)
    ram_store, mm_store = ColumnStore(), ColumnStore()
    ram_col = ram_store.ingest(np.ascontiguousarray(data))
    mm_col = mm_store.ingest(mm)
    assert mm_col.min == ram_col.min
    assert mm_col.max == ram_col.max
    assert mm_col.zone.null_count == ram_col.zone.null_count == 1


def test_scatter_density_screen_bounded_out_of_core(tmp_path):
    # A memmap-backed scatter renders density first-paint with no per-point
    # geometry, and resident canonical stays 0.
    n = 300_000
    rng = np.random.default_rng(0)
    xcol = _build(tmp_path, "sx.f64", rng.normal(0, 1, n), capacity=n)
    ycol = _build(tmp_path, "sy.f64", rng.normal(0, 1, n), capacity=n)
    fig = xy.chart(xy.scatter(x=xcol, y=ycol, density=True)).figure()

    rep = fig.store.memory_report()
    assert rep["canonical_bytes"] == 0
    assert rep["canonical_mapped_bytes"] == n * 8 * 2

    spec, blob = fig.build_payload(1024)
    tr = spec["traces"][0]
    assert tr["tier"] == "density"
    # Screen-bounded: the wire payload is a grid + tiny sample, not O(n) points.
    assert len(blob) < n  # far under one f32 per point

    # The engine-owned resident set is the screen-sized pyramid/grid, not data.
    full = fig.memory_report()
    assert full["canonical_bytes"] == 0
    assert full["resident_array_bytes"] < n * 8  # << canonical data size
