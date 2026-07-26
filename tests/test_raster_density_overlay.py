"""Raster exports skip the density point overlay; the wire payload keeps it.

`_build_raster_payload` sets `point_overlay=False` because `_emit_grid` never
reads `density["sample"]`. The browser client *does* draw it, so the public
`build_payload` must keep shipping it. These tests pin both halves of that
contract, and prove the raster grid counts are unchanged.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

import xy

DENSITY_N = 250_000  # comfortably over SCATTER_DENSITY_THRESHOLD (200k)


def _density_data(seed: int = 7, n: int = DENSITY_N) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    y = rng.standard_normal(n) + x
    return x, y


def _figure(**kwargs: object) -> xy.Figure:
    x, y = _density_data()
    return xy.scatter_chart(xy.scatter(x=x, y=y, **kwargs), width=900, height=420).figure()


def test_wire_payload_still_ships_the_overlay() -> None:
    """Regression guard: the flag must never leak into the client's payload."""
    fig = _figure()
    spec, _blob = fig.build_payload()
    density = spec["traces"][0]["density"]
    assert "sample" in density, "the JS client draws this overlay"
    assert density["sample"]["n"] > 0
    assert density["sample"]["mode"] == "sampled"


def test_raster_payload_omits_the_overlay() -> None:
    fig = _figure()
    spec, _blob, _borrowed = fig._build_raster_payload()
    density = spec["traces"][0]["density"]
    assert "sample" not in density
    # The grid itself must be fully intact.
    assert density["w"] > 0 and density["h"] > 0 and density["max"] > 0


def test_raster_grid_bytes_match_the_wire_grid() -> None:
    """Dropping the fused sampler must not perturb a single bin count."""
    fig = _figure()
    wire_spec, wire_blob = fig.build_payload()
    rast_spec, rast_blob, _ = fig._build_raster_payload()

    wire_d, rast_d = wire_spec["traces"][0]["density"], rast_spec["traces"][0]["density"]
    assert (wire_d["w"], wire_d["h"], wire_d["max"]) == (
        rast_d["w"],
        rast_d["h"],
        rast_d["max"],
    )
    wire_col = wire_spec["columns"][wire_d["buf"]]
    rast_col = rast_spec["columns"][rast_d["buf"]]
    assert wire_col["dtype"] == rast_col["dtype"] == "u8"  # 1 byte per entry
    assert wire_col["len"] == rast_col["len"] == wire_d["w"] * wire_d["h"]
    wire_grid = wire_blob[wire_col["byte_offset"] : wire_col["byte_offset"] + wire_col["len"]]
    rast_grid = rast_blob[rast_col["byte_offset"] : rast_col["byte_offset"] + rast_col["len"]]
    assert bytes(wire_grid) == bytes(rast_grid)


@pytest.mark.parametrize("n", [250_000, 1_000_000])
@pytest.mark.parametrize("scale", [1, 2])
def test_png_bytes_unchanged_by_scale_and_size(n: int, scale: int) -> None:
    """The deliverable is what matters: identical PNG at both raster scales."""
    x, y = _density_data(n=n)
    fig = xy.scatter_chart(xy.scatter(x=x, y=y), width=900, height=420).figure()
    png = fig.to_png(width=900, height=420, scale=scale, engine=xy.Engine.default)
    # Stable across runs: the density path is deterministic.
    again = fig.to_png(width=900, height=420, scale=scale, engine=xy.Engine.default)
    assert hashlib.sha256(png).hexdigest() == hashlib.sha256(again).hexdigest()
    assert len(png) > 1000


def test_direct_tier_untouched() -> None:
    """Below the density threshold nothing about this change applies."""
    rng = np.random.default_rng(3)
    x, y = rng.standard_normal(10_000), rng.standard_normal(10_000)
    fig = xy.scatter_chart(xy.scatter(x=x, y=y), width=900, height=420).figure()
    spec, _blob, _ = fig._build_raster_payload()
    assert spec["traces"][0]["tier"] == "direct"


def test_categorical_density_paths_omit_overlay() -> None:
    """Compact-categorical takes a different (stratified) sampler branch.

    A trace with per-item channels only reaches the density tier past
    DIRECT_SOFT_CEILING (2M), not SCATTER_DENSITY_THRESHOLD (200k), so this
    case needs a genuinely large array to exercise the branch at all.
    """
    n = 2_200_000
    x, y = _density_data(n=n)
    labels = np.array(["a", "b", "c", "d", "e"])[np.arange(n) % 5]
    with pytest.warns(RuntimeWarning, match="soft ceiling"):
        fig = xy.scatter_chart(xy.scatter(x=x, y=y, color=labels), width=900, height=420).figure()
    assert fig.traces[0].use_density()
    wire_spec, _ = fig.build_payload()
    rast_spec, _, _ = fig._build_raster_payload()
    assert "sample" in wire_spec["traces"][0]["density"]
    assert "sample" not in rast_spec["traces"][0]["density"]


def test_clipped_domain_keeps_visible_count() -> None:
    """The non-full-identity branch still needs bin_2d_indices for `visible`."""
    x, y = _density_data()
    fig = xy.scatter_chart(
        xy.scatter(x=x, y=y), xy.x_axis(domain=(-1.0, 1.0)), width=900, height=420
    ).figure()
    wire_spec, _ = fig.build_payload()
    rast_spec, _, _ = fig._build_raster_payload()
    wire_t, rast_t = wire_spec["traces"][0], rast_spec["traces"][0]
    assert rast_t["visible"] == wire_t["visible"] > 0
    assert rast_t["visible"] < DENSITY_N, "domain should actually clip"
    assert "sample" not in rast_t["density"]
