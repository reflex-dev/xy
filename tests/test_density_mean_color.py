"""Mean-color density surface (LOD doc §2): the aggregated view wears the
data's own colors — per-cell alpha-weighted mean of the resolved point
colors, averaged in linear light — composited at the points' own alpha
(`1 − (1 − ā)^count`, the physical downsample). These tests pin the kernel
against a NumPy oracle (the LOD doc's exit criterion), the wire shape across
the initial emit / exact density_view / pyramid paths, and the static
exporters' color law.
"""

from __future__ import annotations

import numpy as np

from xy import channels, kernels
from xy._figure import Figure
from xy.config import DEFAULT_PALETTE, PYRAMID_MIN_POINTS, SCATTER_DENSITY_THRESHOLD
from xy.interaction import _decode_log_u8

# sRGB <-> linear-light, float oracle (IEC 61966-2-1) — independent of the
# kernel's integer tables so the test checks the law, not the implementation.


def _srgb_to_linear(byte: np.ndarray) -> np.ndarray:
    c = byte.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb_u8(lin: np.ndarray) -> np.ndarray:
    lin = np.clip(lin, 0.0, 1.0)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.rint(c * 255.0).astype(np.uint8)


def _mean_color_oracle(
    x: np.ndarray,
    y: np.ndarray,
    rgba: np.ndarray,
    window: tuple[float, float, float, float],
    w: int,
    h: int,
) -> np.ndarray:
    """NumPy reference for bin_2d_mean_color (straight-alpha RGBA8 out)."""
    x0, x1, y0, y1 = window
    out = np.zeros((h, w, 4), dtype=np.uint8)
    keep = np.isfinite(x) & np.isfinite(y) & (x >= x0) & (x < x1) & (y >= y0) & (y < y1)
    cx = np.minimum(((x[keep] - x0) * (w / (x1 - x0))).astype(np.int64), w - 1)
    cy = np.minimum(((y[keep] - y0) * (h / (y1 - y0))).astype(np.int64), h - 1)
    colors = rgba[keep]
    lin = _srgb_to_linear(colors[:, :3])
    alpha = colors[:, 3].astype(np.float64)
    for cell in np.unique(cy * w + cx):
        rows = cy * w + cx == cell
        weight = alpha[rows].sum()
        count = int(rows.sum())
        if weight <= 0:
            continue
        mean_lin = (lin[rows] * alpha[rows, None]).sum(axis=0) / weight
        out.reshape(-1, 4)[cell, :3] = _linear_to_srgb_u8(mean_lin)
        # Round half up, like the kernel's integer (sum + count/2) / count —
        # Python's round() is half-to-even and disagrees on exact halves.
        out.reshape(-1, 4)[cell, 3] = min(255, int(np.floor(weight / count + 0.5)))
    return out


def _decode_truecolor_png(data: bytes) -> tuple[int, int, np.ndarray]:
    """Minimal decoder for xy's own truecolor PNGs (color type 6,
    filter-0 scanlines, no interlace) — enough to assert exported pixels."""
    import struct
    import zlib

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    at = 8
    width = height = None
    idat = b""
    while at < len(data):
        (length,) = struct.unpack(">I", data[at : at + 4])
        kind = data[at + 4 : at + 8]
        chunk = data[at + 8 : at + 8 + length]
        at += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
            assert (depth, color_type, interlace) == (8, 6, 0)
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
    assert width and height
    raw = zlib.decompress(idat)
    stride = width * 4
    rows = []
    for row in range(height):
        offset = row * (stride + 1)
        assert raw[offset] == 0, "xy PNGs write filter-0 scanlines"
        rows.append(np.frombuffer(raw, dtype=np.uint8, count=stride, offset=offset + 1))
    return width, height, np.stack(rows).reshape(height, width, 4)


def _payload_u8(spec, blob, ref) -> np.ndarray:
    """Read a u8 column of a packed build_payload blob by column index."""
    meta = spec["columns"][ref]
    return np.frombuffer(blob, dtype=np.uint8, count=meta["len"], offset=meta["byte_offset"])


def test_mean_color_kernel_matches_numpy_oracle():
    rng = np.random.default_rng(11)
    n = 20_000
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    rgba = rng.integers(0, 256, size=(n, 4), dtype=np.uint8)
    got = kernels.bin_2d_mean_color(x, y, 0.0, 100.0, 0.0, 100.0, 32, 24, rgba=rgba)
    want = _mean_color_oracle(x, y, rgba, (0.0, 100.0, 0.0, 100.0), 32, 24)
    # Independent float oracle vs the kernel's exact integer pipeline: alphas
    # match to the byte; colors to 1 lsb (quantization at different stages).
    assert np.array_equal(got[..., 3], want[..., 3])
    lit = want[..., 3] > 0
    diff = np.abs(got.astype(np.int16) - want.astype(np.int16))[lit]
    assert diff.max() <= 1
    # Empty cells are fully zero — no invented color.
    assert not got[~lit].any()


def test_payload_density_ships_mean_colors_for_categorical():
    # Two spatially separated categories: left red-ish cells must wear the
    # first palette color exactly, right cells the second — the surface shows
    # the data's colors, not a count colormap.
    n = SCATTER_DENSITY_THRESHOLD + 10_000
    rng = np.random.default_rng(5)
    x = np.concatenate([rng.uniform(0.0, 1.0, n // 2), rng.uniform(9.0, 10.0, n - n // 2)])
    y = rng.uniform(0.0, 1.0, n)
    cats = np.where(x < 5.0, "left", "right")
    # density=True: channel-bearing traces keep direct draw until the 2M
    # ceiling, so force the aggregate view at test-friendly sizes.
    fig = Figure().scatter(x, y, color=cats, density=True)
    spec, blob = fig.build_payload()
    tr = spec["traces"][0]
    assert tr["tier"] == "density"
    d = tr["density"]
    assert d["color_agg"] == "mean"
    assert d["channels_dropped"] is False and d["dropped_channels"] == []
    w, h = d["w"], d["h"]
    rgba = _payload_u8(spec, blob, d["rgba"]).reshape(h, w, 4)
    counts = _decode_log_u8(_payload_u8(spec, blob, d["buf"]).tobytes(), d["max"]).reshape(h, w)
    palette = channels.palette_rgba8(DEFAULT_PALETTE, 2)
    lit = rgba[..., 3] > 0
    assert lit.any()
    assert np.array_equal(lit, counts > 0.5), "occupied cells match the count grid"
    # "left" sorts before "right": palette rows 0 / 1.
    left = rgba[:, : w // 2][lit[:, : w // 2]]
    right = rgba[:, w // 2 :][lit[:, w // 2 :]]
    assert (left == palette[0]).all()
    assert (right == palette[1]).all()


def test_constant_color_density_keeps_count_only_wire():
    n = SCATTER_DENSITY_THRESHOLD + 10_000
    rng = np.random.default_rng(6)
    fig = Figure().scatter(rng.uniform(0, 1, n), rng.uniform(0, 1, n), color="#ff0000")
    spec, _ = fig.build_payload()
    d = spec["traces"][0]["density"]
    assert "rgba" not in d and "color_agg" not in d
    assert d["color"] == "#ff0000"  # client tints; mean of a constant IS the constant


def test_density_view_exact_path_ships_mean_colors():
    n = SCATTER_DENSITY_THRESHOLD * 3
    rng = np.random.default_rng(7)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    values = x.copy()  # continuous channel correlated with position
    fig = Figure().scatter(x, y, color=values, density=True)
    upd, bufs = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 256, 192)
    tr = upd["traces"][0]
    assert tr["mode"] == "density" and tr["binning"] == "exact"
    d = tr["density"]
    assert d["color_agg"] == "mean"
    rgba = np.frombuffer(bufs[d["rgba"]], dtype=np.uint8).reshape(d["h"], d["w"], 4)
    lit = rgba[..., 3] > 0
    assert lit.any()
    # Viridis runs dark-purple -> yellow: left columns must be bluer, right
    # columns greener/yellower — the surface follows the channel, not count.
    left_mean = rgba[:, : d["w"] // 4][lit[:, : d["w"] // 4]].mean(axis=0)
    right_mean = rgba[:, 3 * d["w"] // 4 :][lit[:, 3 * d["w"] // 4 :]].mean(axis=0)
    assert left_mean[2] > right_mean[2]  # blue fades toward the right
    assert right_mean[1] > left_mean[1]  # green rises toward the right


def test_density_view_pyramid_path_ships_mean_colors():
    n = PYRAMID_MIN_POINTS + 50_000
    rng = np.random.default_rng(8)
    x = np.concatenate([rng.uniform(0.0, 1.0, n // 2), rng.uniform(9.0, 10.0, n - n // 2)])
    y = rng.uniform(0.0, 1.0, n)
    cats = np.where(x < 5.0, "left", "right")
    fig = Figure().scatter(x, y, color=cats)
    upd, bufs = fig.density_view(0, 0.0, 10.0, 0.0, 1.0, 128, 96)
    tr = upd["traces"][0]
    assert tr["binning"].startswith("pyramid-L"), "large trace must serve from the pyramid"
    d = tr["density"]
    assert d["color_agg"] == "mean"
    rgba = np.frombuffer(bufs[d["rgba"]], dtype=np.uint8).reshape(d["h"], d["w"], 4)
    palette = channels.palette_rgba8(DEFAULT_PALETTE, 2)
    lit = rgba[..., 3] > 0
    assert lit.any()
    left = rgba[:, : d["w"] // 2][lit[:, : d["w"] // 2]]
    right = rgba[:, d["w"] // 2 :][lit[:, d["w"] // 2 :]]
    assert (left == palette[0]).all()
    assert (right == palette[1]).all()
    # The area-weighted compose (#153) spreads a cluster-edge source cell
    # across every output bin its extent overlaps, so boundary bins can carry
    # a fractional sliver of count — lit in the color plane while the log-u8
    # count plane rounds the sliver to 0 or 1. The planes must still agree on
    # where mass exists: any bin the count plane shows nonzero is lit, and an
    # unlit bin never shows count.
    enc = np.frombuffer(bufs[d["buf"]], dtype=np.uint8).reshape(d["h"], d["w"])
    assert lit[enc > 0].all()
    assert (enc[~lit] == 0).all()


def test_colored_pyramid_append_invalidates_for_lazy_rebuild():
    n = PYRAMID_MIN_POINTS + 10_000
    rng = np.random.default_rng(9)
    x = rng.uniform(0.0, 10.0, n)
    y = rng.uniform(0.0, 1.0, n)
    fig = Figure().scatter(x, y, color=x.copy())
    fig.density_view(0, 0.0, 10.0, 0.0, 1.0, 128, 96)  # builds the colored pyramid
    t = fig.traces[0]
    assert getattr(t, "_pyr_handle", 0)
    assert getattr(t, "_pyr_colored", False) is True
    fig.append(0, [5.0], [0.5], color=[5.0])
    # The colored pyramid refuses native increments; the append must have
    # invalidated it for a lazy rebuild rather than leaving stale colors.
    assert getattr(t, "_pyr_handle", 0) in (None, 0)


def test_svg_export_density_uses_mean_colors():
    n = SCATTER_DENSITY_THRESHOLD + 10_000
    rng = np.random.default_rng(10)
    x = np.concatenate([rng.uniform(0.0, 1.0, n // 2), rng.uniform(9.0, 10.0, n - n // 2)])
    y = rng.uniform(0.0, 1.0, n)
    cats = np.where(x < 5.0, "left", "right")
    fig = Figure().scatter(x, y, color=cats, density=True)
    svg = fig.to_svg()
    assert "data:image/png;base64," in svg
    # The categorical palette must color the exported surface: decode the
    # embedded density PNG (png_truecolor writes filter-0 scanlines) and
    # check the two clusters' hues.
    import base64
    import re

    payload = re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", svg).group(1)
    w, h, img = _decode_truecolor_png(base64.b64decode(payload))
    lit = img[..., 3] > 0
    palette = channels.palette_rgba8(DEFAULT_PALETTE, 2)
    left = img[:, : w // 2][lit[:, : w // 2]]
    right = img[:, w // 2 :][lit[:, w // 2 :]]
    assert left.size and right.size
    assert (left[:, :3] == palette[0, :3]).all()
    assert (right[:, :3] == palette[1, :3]).all()


def test_physical_density_alpha_law():
    # LOD doc §2 rule 1: alpha = 1 - (1 - a_pt)^count with a_pt = channel
    # alpha x style opacity folded inside the exponent; empty/invisible
    # cells stay 0; a_pt = 1 saturates any occupied cell; no window max
    # enters anywhere. This is the exporters' twin of the client upload law.
    from xy._svg import _physical_density_alpha

    counts = np.asarray([0.0, 1.0, 3.0, 50.0, 2.0, 5.0])
    mean_a = np.asarray([255, 255, 255, 255, 0, 255], dtype=np.uint8)
    out = _physical_density_alpha(counts, mean_a, 0.72)
    expect = lambda k: round(255 * (1.0 - (1.0 - 0.72) ** k))  # noqa: E731
    assert out[0] == 0  # empty
    assert abs(int(out[1]) - expect(1)) <= 1  # one point IS the point alpha
    assert abs(int(out[2]) - expect(3)) <= 1
    assert out[3] >= 254  # saturates like overplotted marks
    assert out[4] == 0  # all-invisible cell never invents coverage
    # Style opacity 1 + full channel alpha: any occupied cell is opaque.
    full = _physical_density_alpha(counts, np.full(6, 255, dtype=np.uint8), 1.0)
    assert full[0] == 0 and (full[1:4] == 255).all()


def test_resolve_bin_colors_modes():
    # constant -> None (count-only grid + client tint)
    assert (
        channels.resolve_bin_colors(
            channels.ColorChannel(mode="constant", constant="#123456"), None, DEFAULT_PALETTE
        )
        is None
    )
    # continuous -> 256-texel colormap LUT + quantized indices
    cc = channels.resolve_color(np.array([0.0, 0.5, 1.0]), 3, default_constant="#000000")
    out = channels.resolve_bin_colors(cc, None, DEFAULT_PALETTE)
    assert out is not None and out["lut"].shape == (256, 4)
    assert out["idx"].dtype == np.uint8 and list(out["idx"]) == [0, 128, 255]
    # categorical -> palette rows, codes pass through
    cc = channels.resolve_color(np.array(["a", "b", "a"]), 3, default_constant="#000000")
    out = channels.resolve_bin_colors(cc, None, DEFAULT_PALETTE)
    assert out is not None and out["lut"].shape[0] == 2
    assert list(out["idx"]) == [0, 1, 0]
    # direct rgba -> packed straight-alpha bytes
    cc = channels.resolve_color(np.array([[1.0, 0.0, 0.0, 0.5]] * 3), 3, default_constant="#000000")
    out = channels.resolve_bin_colors(cc, None, DEFAULT_PALETTE)
    assert out is not None and out["rgba"].shape == (3, 4)
    assert list(out["rgba"][0]) == [255, 0, 0, 128]


def test_mean_color_weights_by_point_alpha():
    # A 20%-alpha red and an opaque blue in one cell: the mean must lean blue,
    # and the cell's mean alpha rides the wire so display intensity follows.
    x = np.array([0.5, 0.5])
    y = np.array([0.5, 0.5])
    rgba = np.array([[255, 0, 0, 51], [0, 0, 255, 255]], dtype=np.uint8)
    grid = kernels.bin_2d_mean_color(x, y, 0.0, 1.0, 0.0, 1.0, 1, 1, rgba=rgba)
    cell = grid[0, 0]
    assert cell[2] > cell[0] > 0
    assert cell[3] == 153  # mean straight alpha: (51 + 255) / 2
    # An all-invisible cell must not invent color or intensity.
    ghost = kernels.bin_2d_mean_color(
        x, y, 0.0, 1.0, 0.0, 1.0, 1, 1, rgba=np.array([[255, 0, 0, 0]] * 2, dtype=np.uint8)
    )
    assert list(ghost[0, 0]) == [0, 0, 0, 0]


def test_mean_color_mixed_cell_averages_in_linear_light():
    # Half red + half blue: linear-light averaging gives a brighter purple
    # (188) than naive sRGB byte averaging (128) — the physically downsampled
    # color of the cluster (LOD doc §2).
    x = np.array([0.5, 0.5])
    y = np.array([0.5, 0.5])
    rgba = np.array([[255, 0, 0, 255], [0, 0, 255, 255]], dtype=np.uint8)
    grid = kernels.bin_2d_mean_color(x, y, 0.0, 1.0, 0.0, 1.0, 1, 1, rgba=rgba)
    assert list(grid[0, 0]) == [188, 0, 188, 255]


def test_wide_categorical_codes_fold_onto_palette():
    # >256 categories ship u32 codes; binned colors must still be exactly the
    # palette color each point draws with (repeat rule, modulo palette).
    n_cats = 300
    codes = np.arange(n_cats, dtype=np.uint32)
    cc = channels.ColorChannel(
        mode="categorical",
        codes=codes,
        categories=[f"c{i}" for i in range(n_cats)],
    )
    out = channels.resolve_bin_colors(cc, None, DEFAULT_PALETTE)
    assert out is not None
    assert out["lut"].shape[0] == len(DEFAULT_PALETTE)
    expected = (codes % len(DEFAULT_PALETTE)).astype(np.uint8)
    assert np.array_equal(out["idx"], expected)


# --- resolution cost: once per trace, never per request ----------------------
# The full-column resolve quantizes every canonical row (O(N) with large NumPy
# temporaries — 1-2 s/request on the 100M FastAPI drilldown demo before it was
# cached). These tests pin the contract: at most one resolve per trace, shared
# by every consumer, refreshed exactly once by an append, and never triggered
# by a reply that ships no mean-color grid.


def _count_resolves(monkeypatch) -> dict[str, int]:
    calls = {"n": 0}
    original = channels.resolve_bin_colors

    def counting(cc, sel, palette):
        calls["n"] += 1
        return original(cc, sel, palette)

    monkeypatch.setattr(channels, "resolve_bin_colors", counting)
    return calls


def test_density_view_exact_band_resolves_colors_once(monkeypatch):
    calls = _count_resolves(monkeypatch)
    n = SCATTER_DENSITY_THRESHOLD * 3
    rng = np.random.default_rng(11)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, color=x.copy(), density=True)
    first, first_bufs = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 256, 192)
    assert calls["n"] == 1
    again, again_bufs = fig.density_view(0, 0.0, 90.0, 0.0, 90.0, 256, 192)
    assert calls["n"] == 1  # served from the trace cache, not re-resolved
    for update, bufs in ((first, first_bufs), (again, again_bufs)):
        d = update["traces"][0]["density"]
        assert d["color_agg"] == "mean" and len(bufs[d["rgba"]])  # plane still ships


def test_density_view_points_band_never_resolves_colors(monkeypatch):
    calls = _count_resolves(monkeypatch)
    n = SCATTER_DENSITY_THRESHOLD * 3
    rng = np.random.default_rng(12)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, color=x.copy(), density=True)
    upd, _ = fig.density_view(0, 0.0, 20.0, 0.0, 20.0, 256, 192)
    tr = upd["traces"][0]
    assert tr["mode"] == "points"
    assert tr["color"]["mode"] == "continuous"  # channels restored on drill
    assert calls["n"] == 0  # drills ship sliced channels; no full-column pass


def test_pyramid_band_reuses_build_time_resolution(monkeypatch):
    calls = _count_resolves(monkeypatch)
    n = PYRAMID_MIN_POINTS + 50_000
    rng = np.random.default_rng(13)
    x = rng.uniform(0.0, 10.0, n)
    y = rng.uniform(0.0, 1.0, n)
    fig = Figure().scatter(x, y, color=x.copy())
    upd, _ = fig.density_view(0, 0.0, 10.0, 0.0, 1.0, 128, 96)
    tr = upd["traces"][0]
    assert tr["binning"].startswith("pyramid-L")
    assert tr["density"]["color_agg"] == "mean"
    assert calls["n"] == 1  # the colored pyramid build resolved (and cached) it
    fig.density_view(0, 0.5, 9.5, 0.0, 1.0, 128, 96)
    assert calls["n"] == 1  # composes prebuilt color planes; no re-resolve


def test_append_re_resolves_bin_colors_exactly_once(monkeypatch):
    calls = _count_resolves(monkeypatch)
    n = SCATTER_DENSITY_THRESHOLD * 3
    rng = np.random.default_rng(14)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, color=x.copy(), density=True)
    fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 256, 192)
    assert calls["n"] == 1
    t = fig.traces[0]
    assert len(t._bin_colors["idx"]) == n
    # Appending invalidates the cache; the refresh payload the append emits
    # re-resolves over the post-append column — once — and later grid replies
    # reuse that fresh resolution.
    fig.append(0, [50.0], [50.0], color=[123.0])
    assert calls["n"] == 2
    assert len(t._bin_colors["idx"]) == n + 1
    fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 256, 192)
    assert calls["n"] == 2


def test_chunked_quantization_matches_one_shot_chain(monkeypatch):
    # The chunked resolve exists purely to bound transient memory (a one-shot
    # chain materializes several full-length f64 temporaries — ~20 GB at 1e9
    # rows); per-element math must stay bitwise identical to the historical
    # pipeline, including non-finite and out-of-domain values and chunk
    # boundaries.
    monkeypatch.setattr(channels, "_QUANTIZE_CHUNK", 7)
    rng = np.random.default_rng(16)
    vals = rng.uniform(-5.0, 15.0, 1000)
    vals[::17] = np.nan
    vals[3::29] = np.inf
    vals[5::31] = -np.inf
    domain = (0.0, 10.0)
    unit = channels.normalize_to_unit(vals, domain)
    want = np.rint(np.asarray(unit, dtype=np.float64) * 255.0).astype(np.uint8)
    assert np.array_equal(channels._quantized_lut_idx(vals, domain), want)

    rgba = rng.uniform(-0.2, 1.2, (500, 4))
    want_rgba = np.rint(np.clip(rgba, 0.0, 1.0) * 255.0).astype(np.uint8)
    assert np.array_equal(channels._quantized_rgba8(rgba), want_rgba)

    codes = rng.integers(0, 300, 400).astype(np.uint32)
    n_palette = len(DEFAULT_PALETTE)
    want_codes = (codes % n_palette).astype(np.uint8)
    assert np.array_equal(channels._folded_codes_u8(codes, n_palette), want_codes)


def test_no_rescan_traces_resolve_without_retention(monkeypatch):
    # Past the no-rescan threshold every interactive reply composes prebuilt
    # pyramid planes, so retaining a per-row idx (1 GB at 1e9 rows) would be
    # resident cost with no consumer: resolve on demand, never store.
    from xy import interaction

    calls = _count_resolves(monkeypatch)
    n = SCATTER_DENSITY_THRESHOLD * 3
    monkeypatch.setattr(interaction, "PYRAMID_NO_RESCAN_ROWS", n - 1)
    rng = np.random.default_rng(17)
    x = rng.uniform(0.0, 100.0, n)
    y = rng.uniform(0.0, 100.0, n)
    fig = Figure().scatter(x, y, color=x.copy(), density=True)
    upd, _ = fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 256, 192)
    tr = upd["traces"][0]
    assert tr["binning"] == "bin2d-oversized"  # the no-rescan correctness net
    assert tr["density"].get("color_agg") == "mean"  # the plane still ships
    assert calls["n"] == 1
    assert fig.traces[0]._bin_colors is None  # resolved, not retained
    fig.density_view(0, 0.0, 100.0, 0.0, 100.0, 256, 192)
    assert calls["n"] == 2  # re-resolved (chunk-bounded), by design
    assert fig.memory_report()["bin_color_bytes"] == 0


def test_categorical_cache_counts_only_owned_arrays():
    # Compact u8 categorical codes pass through the resolution by reference;
    # they are already counted as channel_bytes, so the cache line must count
    # only what the resolution owns (the palette LUT).
    n = SCATTER_DENSITY_THRESHOLD + 10_000
    rng = np.random.default_rng(18)
    x = rng.uniform(0.0, 10.0, n)
    cats = np.where(x < 5.0, "left", "right")
    fig = Figure().scatter(x, rng.uniform(0.0, 1.0, n), color=cats, density=True)
    report = fig.memory_report()
    assert fig.traces[0]._bin_colors["idx"] is fig.traces[0].color_ch.codes
    assert report["bin_color_bytes"] == 2 * 4  # the 2-row RGBA8 palette LUT only


def test_memory_report_itemizes_bin_color_cache_bytes():
    n = SCATTER_DENSITY_THRESHOLD * 3
    rng = np.random.default_rng(15)
    fig = Figure().scatter(
        rng.uniform(0.0, 100.0, n),
        rng.uniform(0.0, 100.0, n),
        color=np.arange(n, dtype=float),
        density=True,
    )
    report = fig.memory_report()  # build_payload inside resolves + caches
    # Continuous channel: n u8 LUT indices + the (256, 4) RGBA8 LUT.
    assert report["bin_color_bytes"] == n + 256 * 4
    assert (
        report["resident_array_bytes"]
        == report["canonical_bytes"]
        + report["channel_bytes"]
        + report["pyramid_bytes"]
        + report["bin_color_bytes"]
    )
    plain = Figure().scatter(np.arange(1000.0), np.arange(1000.0))
    assert plain.memory_report()["bin_color_bytes"] == 0
