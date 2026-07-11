"""Native PNG export (`_raster.py` + the Rust `fc_rasterize` core): valid PNGs
for every chart kind, `scale=`/dimension handling, indexed-vs-truecolor
selection, the screen-bounded size guarantee, colormap fidelity, and parity of
the shared layout with the SVG exporter."""

from __future__ import annotations

import struct

import numpy as np

from xy import _png, _raster
from xy._figure import Figure


def _ihdr(png: bytes) -> tuple[int, int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "bad PNG signature"
    assert png[12:16] == b"IHDR"
    w, h = struct.unpack(">II", png[16:24])
    color_type = png[25]
    return w, h, color_type


def test_every_chart_kind_exports_valid_png() -> None:
    rng = np.random.default_rng(0)
    x = np.linspace(0.0, 10.0, 50)
    figs = [
        Figure().line(x, np.sin(x), dash="dashed", curve="smooth"),
        Figure().area(x, np.abs(np.sin(x)), fill="linear-gradient(currentColor, transparent)"),
        Figure().scatter(x, np.cos(x), symbol="triangle", stroke="#111", color=np.sin(x)),
        Figure().scatter(x, np.cos(x), color=np.array(["a", "b"] * 25)),
        Figure().bar(
            ["a", "b", "c"], [1.0, 3.0, 2.0], corner_radius=(4, 0), stroke="#123456", stroke_width=2
        ),
        Figure().bar(["a", "b"], [1.0, 2.0], orientation="horizontal"),
        Figure().histogram(rng.normal(size=500), corner_radius=2),
        Figure().heatmap(rng.random((8, 6))),
        Figure().scatter(rng.normal(size=200_000), rng.normal(size=200_000), density=True),
    ]
    for fig in figs:
        png = fig.to_png(scale=1)
        w, h, _ = _ihdr(png)
        assert (w, h) == (900, 420)  # default figure size at scale 1


def test_scale_multiplies_pixels() -> None:
    fig = Figure(width=320, height=200).line([0.0, 1.0], [0.0, 1.0])
    for scale, dims in [(1, (320, 200)), (2, (640, 400)), (3, (960, 600))]:
        assert _ihdr(fig.to_png(scale=scale))[:2] == dims


def test_dimension_override_and_fluid() -> None:
    fig = Figure(width="100%", height="100%").line([0.0, 1.0], [0.0, 1.0])
    png = fig.to_png(width=500, height=300, scale=1)
    assert _ihdr(png)[:2] == (500, 300)


def test_flat_chart_is_indexed_gradient_chart_is_truecolor() -> None:
    # A tiny flat-color chart stays within 256 colors → indexed (color type 3).
    flat = Figure(width=200, height=120).bar(["a", "b"], [1.0, 2.0], color="#2563eb")
    assert _ihdr(flat.to_png(scale=1))[2] == 3
    # A gradient + AA area blows past 256 colors → truecolor (color type 6).
    x = np.linspace(0.0, 6.0, 40)
    grad = Figure(width=400, height=200).area(
        x, np.abs(np.sin(x)) + 0.2, fill="linear-gradient(#1e40af, #93c5fd)"
    )
    assert _ihdr(grad.to_png(scale=1))[2] == 6


def test_png_is_screen_bounded_for_large_lines() -> None:
    n = 2_000_000
    y = np.cumsum(np.random.default_rng(1).normal(size=n))
    fig = Figure(width=950, height=420).line(np.arange(n, dtype=np.float64), y)
    png = fig.to_png(scale=1)
    # Screen-bounded: a 2M-point source must not inflate the file. Generous
    # ceiling — a 950x420 truecolor chart with M4-decimated ink.
    assert len(png) < 700_000, f"PNG not screen-bounded: {len(png)} bytes"
    spec, _ = fig.build_payload()
    assert spec["traces"][0]["n_points"] == n  # source size still recorded (§28)


def test_render_is_non_blank_and_has_background() -> None:
    fig = Figure(width=200, height=120).line([0.0, 1.0], [0.0, 1.0])
    img = _raster.render_raster(*fig.build_payload(), scale=1)
    assert img.shape == (120, 200, 4)
    # White background painted (corner pixel), and ink somewhere (not all white).
    assert tuple(img[0, 0]) == (255, 255, 255, 255)
    assert int((img[:, :, :3] < 200).any(axis=2).sum()) > 50


def test_colormap_matches_lut() -> None:
    # The grid RGBA the rasterizer blits comes straight from `_lut`, so the
    # hottest heatmap cell is the colormap's top color (before blit/compositing).
    from xy import _scene

    rng = np.random.default_rng(2)
    fig = Figure(width=300, height=300).heatmap(rng.random((8, 8)), colormap="viridis")
    spec, blob = fig.build_payload()
    hm = spec["traces"][0]["heatmap"]
    rgba, _xr, _yr = _scene.grid_rgba("heatmap", hm, blob, spec["columns"], {})
    viridis_top = np.array([253, 231, 37])  # last viridis stop (_svg.COLORMAP_STOPS)
    dist = np.abs(rgba[:, :, :3].astype(int) - viridis_top).sum(axis=2)
    assert int(dist.min()) < 20, f"hottest cell not viridis-top (dist {int(dist.min())})"


def test_png_encoder_selects_indexed_for_few_colors() -> None:
    few = np.zeros((10, 10, 4), np.uint8)
    few[:5] = [255, 0, 0, 255]
    few[5:] = [0, 0, 255, 255]
    assert _ihdr(_png.encode(few))[2] == 3
    many = (np.random.default_rng(3).random((20, 20, 4)) * 255).astype(np.uint8)
    assert _ihdr(_png.encode(many))[2] == 6


def test_png_encoder_uses_balanced_compression_level(monkeypatch) -> None:
    levels: list[int] = []
    compress = _png.zlib.compress

    def recording_compress(data: bytes, level: int) -> bytes:
        levels.append(level)
        return compress(data, level)

    monkeypatch.setattr(_png.zlib, "compress", recording_compress)
    few = np.zeros((10, 10, 4), np.uint8)
    many = (np.random.default_rng(4).random((20, 20, 4)) * 255).astype(np.uint8)

    _png.encode(few)
    _png.encode(many)

    assert levels == [6, 6]


def test_fast_native_png_is_valid_and_matches_dimensions() -> None:
    fig = Figure(width=320, height=180).line([0.0, 1.0], [0.0, 1.0])
    png = _raster.to_png(fig, scale=2, fast=True)

    assert _ihdr(png) == (640, 360, 2)


def test_fast_native_png_is_pixel_identical_to_balanced_export() -> None:
    from io import BytesIO

    from PIL import Image

    x = np.linspace(-2.0, 2.0, 80)
    xx, yy = np.meshgrid(x, x)
    figures = [
        Figure(width=360, height=220).line(x, np.sin(x * 3.0)),
        Figure(width=360, height=220).heatmap(np.sin(xx) + np.cos(yy)),
        Figure(width=360, height=220).contour(np.sin(xx * 1.7) + np.cos(yy * 2.1), levels=7),
    ]

    for figure in figures:
        balanced = np.asarray(Image.open(BytesIO(_raster.to_png(figure, scale=1))).convert("RGBA"))
        fast = np.asarray(
            Image.open(BytesIO(_raster.to_png(figure, scale=1, fast=True))).convert("RGBA")
        )
        np.testing.assert_array_equal(fast, balanced)


def test_native_and_svg_share_layout() -> None:
    # Both exporters compute the same plot rect / tick labels from one spec.
    from xy import _svg

    fig = Figure(width=640, height=360, title="t", x_label="xx").line([0.0, 5.0], [0.0, 5.0])
    spec, _ = fig.build_payload()
    width, height, _compact, plot = _svg.layout(spec)
    assert (width, height) == (640, 360)
    assert plot["w"] > 0 and plot["h"] > 0
    xt, _lab, _step = _svg.axis_ticks(spec["x_axis"], plot["w"], True)
    assert len(xt) >= 2  # shared tick math produces ticks both engines label
