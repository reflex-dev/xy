"""Unified export API (ENG-10447): `to_image`/`write_image`/`write_images`
format matrix, extension inference, deterministic engine selection, the shared
background policy, declarative `export_config` defaults, and facet parity.

Native formats are exercised for real (no browser); the Chromium branch is
pinned through a fake CDP session, matching the repo convention that real
browser paths are validated by scripts/*smoke*.
"""

from __future__ import annotations

import io
import re
import struct
import zlib

import numpy as np
import pytest

import xy
from xy import export
from xy._figure import Figure


def _fig(width: int = 300, height: int = 200) -> Figure:
    rng = np.random.default_rng(11)
    return Figure(width=width, height=height, title="t").scatter(
        rng.uniform(0, 1, 200), rng.uniform(0, 1, 200)
    )


def _pil():
    return pytest.importorskip("PIL.Image")


def _decode(data: bytes):
    image = _pil().open(io.BytesIO(data))
    image.load()
    return image


# -- format selection -------------------------------------------------------


def test_format_normalization_and_aliases():
    assert export._normalize_format("PNG") == "png"
    assert export._normalize_format("jpg") == "jpeg"
    assert export._normalize_format(".webp") == "webp"
    with pytest.raises(ValueError, match="format must be one of"):
        export._normalize_format("tiff")
    with pytest.raises(ValueError, match="to_html"):
        export._normalize_format("html")


def test_extension_inference():
    assert export._infer_format("a/b/chart.JPG") == "jpeg"
    assert export._infer_format("chart.pdf") == "pdf"
    assert export._infer_format("chart.htm") == "html"
    with pytest.raises(ValueError, match="add a file extension"):
        export._infer_format("chart")
    with pytest.raises(ValueError, match="unknown extension"):
        export._infer_format("chart.tiff")


def test_to_image_png_matches_to_png():
    fig = _fig()
    assert export.to_image(fig, "png") == export.to_png(fig)


def test_every_image_format_produces_its_magic_bytes():
    fig = _fig()
    outputs = {fmt: export.to_image(fig, fmt) for fmt in export.IMAGE_FORMATS}
    assert outputs["png"][:8] == b"\x89PNG\r\n\x1a\n"
    assert outputs["jpeg"][:3] == b"\xff\xd8\xff"
    assert outputs["webp"][:4] == b"RIFF" and outputs["webp"][8:12] == b"WEBP"
    assert outputs["svg"][:5] == b"<svg "
    assert outputs["pdf"][:5] == b"%PDF-"


def test_exports_are_deterministic():
    fig = _fig()
    for fmt in export.IMAGE_FORMATS:
        assert export.to_image(fig, fmt) == export.to_image(fig, fmt), fmt


# -- background policy ------------------------------------------------------


def test_raster_background_color_reaches_corner_pixels():
    fig = _fig()
    png = export.to_image(fig, "png", background="#112233")
    image = np.asarray(_decode(png).convert("RGBA"))
    assert tuple(image[0, 0]) == (0x11, 0x22, 0x33, 255)
    jpeg = export.to_image(fig, "jpeg", background="#ff0000", quality=95)
    corner = np.asarray(_decode(jpeg).convert("RGB"))[0, 0]
    assert corner[0] > 240 and corner[1] < 15 and corner[2] < 15


def test_transparent_background_where_alpha_exists():
    fig = _fig()
    png = np.asarray(_decode(export.to_image(fig, "png", background="transparent")).convert("RGBA"))
    webp = np.asarray(
        _decode(export.to_image(fig, "webp", background="transparent")).convert("RGBA")
    )
    assert png[0, 0, 3] == 0
    assert webp[0, 0, 3] == 0
    svg = export.to_image(fig, "svg", background="transparent")
    assert b"transparent" not in svg  # no backdrop rect at all
    with pytest.raises(ValueError, match="JPEG has no alpha channel"):
        export.to_image(fig, "jpeg", background="transparent")


def test_svg_background_paints_one_backdrop_rect():
    svg = export.to_image(_fig(), "svg", background="#112233").decode()
    assert re.search(r'<rect width="\d+" height="\d+" fill="#112233"/>', svg)


def _themed_chart():
    return xy.chart(
        xy.line("x", "y", data={"x": np.arange(20.0), "y": np.arange(20.0)}),
        xy.theme(background="#ff0000", plot_background="#00ff00"),
        width=300,
        height=200,
    )


def _corner_center(data: bytes):
    image = np.asarray(_decode(data).convert("RGBA"))
    h, w = image.shape[:2]
    return tuple(int(v) for v in image[2, 2]), tuple(int(v) for v in image[h // 2, w // 2])


def test_explicit_background_replaces_theme_paints():
    # An explicit export background must replace the theme figure patch AND
    # the plot-rect fill — not be buried underneath them (PR #115 review).
    chart = _themed_chart()
    corner, center = _corner_center(chart.to_image("png", scale=1.0))
    assert corner == (255, 0, 0, 255) and center == (0, 255, 0, 255)  # theme intact
    corner, center = _corner_center(chart.to_image("png", scale=1.0, background="#112233"))
    assert corner == (0x11, 0x22, 0x33, 255) and center == (0x11, 0x22, 0x33, 255)
    corner, center = _corner_center(chart.to_image("png", scale=1.0, background="transparent"))
    assert corner[3] == 0 and center[3] == 0
    svg = chart.to_image("svg", background="#112233").decode()
    assert "#ff0000" not in svg and "#00ff00" not in svg
    assert svg.count("#112233") == 1  # exactly one backdrop, no double-composite


def test_browser_background_css_overrides_theme_tokens():
    css = export._background_css("#112233")
    assert "html,body{background:#112233 !important;}" in css
    assert ".xy{background:#112233 !important;--chart-bg:transparent !important;}" in css
    assert export._background_css(None) == ""


def test_background_rejects_unsafe_strings():
    with pytest.raises(ValueError, match="safe CSS color"):
        export.to_image(_fig(), "png", background="url(javascript:1)}{")


# -- quality policy ---------------------------------------------------------


def test_jpeg_quality_orders_size():
    fig = _fig()
    small = export.to_image(fig, "jpeg", quality=30)
    large = export.to_image(fig, "jpeg", quality=95)
    assert len(small) < len(large)


def test_quality_rejected_outside_lossy_formats():
    with pytest.raises(ValueError, match="quality applies to jpeg/webp"):
        export.to_image(_fig(), "png", quality=80)
    with pytest.raises(ValueError, match="lossless"):
        export.to_image(_fig(), "webp", quality=80)
    with pytest.raises(ValueError, match=r"1\.\.100"):
        export.to_image(_fig(), "jpeg", quality=0)


# -- engine selection -------------------------------------------------------


def test_svg_is_native_only():
    with pytest.raises(ValueError, match="native-only"):
        export.to_image(_fig(), "svg", engine=export.Engine.chromium)


def test_custom_css_forces_browser_or_rejects_native(monkeypatch):
    monkeypatch.setattr(export, "find_browser", lambda explicit=None: None)
    with pytest.raises(RuntimeError, match="browser image export"):
        export.to_image(_fig(), "png", custom_css=".x{}")
    with pytest.raises(ValueError, match="custom_css requires"):
        export.to_image(_fig(), "png", engine=export.Engine.default, custom_css=".x{}")


class _FakeSession:
    def __init__(self):
        self.calls = []

    def close(self):
        self.calls.append(("close",))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def render_image(self, html, width, height, *, format, scale, quality, transparent):
        self.calls.append(("image", format, width, height, scale, quality, transparent))
        return {
            "png": b"\x89PNG\r\n\x1a\nx",
            "jpeg": b"\xff\xd8\xffx",
            "webp": b"RIFF\x00\x00\x00\x00WEBPx",
        }[format]

    def render_pdf(self, html, width, height):
        self.calls.append(("pdf", width, height))
        return b"%PDF-1.4 fake"


def test_chromium_engine_routes_formats_through_cdp(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(export, "_browser_session", lambda **kw: session)
    fig = _fig()
    jpeg = export.to_image(fig, "jpeg", engine=export.Engine.chromium, quality=70)
    assert jpeg[:3] == b"\xff\xd8\xff"
    webp = export.to_image(
        fig, "webp", engine=export.Engine.chromium, quality=55, background="transparent"
    )
    assert webp[:4] == b"RIFF"
    pdf = export.to_image(fig, "pdf", engine=export.Engine.chromium)
    assert pdf[:5] == b"%PDF-"
    kinds = [c[0] for c in session.calls]
    assert kinds.count("image") == 2 and kinds.count("pdf") == 1
    image_calls = [c for c in session.calls if c[0] == "image"]
    assert image_calls[0][1] == "jpeg" and image_calls[0][5] == 70
    assert image_calls[1][1] == "webp" and image_calls[1][6] is True  # transparent


# -- write_image ------------------------------------------------------------


def test_write_image_infers_writes_atomically_and_returns_bytes(tmp_path):
    fig = _fig()
    path = tmp_path / "out.webp"
    data = fig.write_image(path)
    assert path.read_bytes() == data and data[:4] == b"RIFF"
    # No same-directory temp residue (atomic replace cleaned up).
    assert [p.name for p in tmp_path.iterdir()] == ["out.webp"]


def test_write_image_format_override_beats_extension(tmp_path):
    path = tmp_path / "chart.bin"
    data = _fig().write_image(path, format="png")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_write_image_html_routes_and_rejects_raster_options(tmp_path):
    fig = _fig()
    data = fig.write_image(tmp_path / "chart.html")
    assert b"<!doctype html>" in data
    with pytest.raises(ValueError, match="HTML export is interactive"):
        fig.write_image(tmp_path / "chart.html", width=800)


# -- write_images (batch) ---------------------------------------------------


def test_write_images_mixed_formats_and_chart_objects(tmp_path):
    chart = xy.chart(
        xy.line("x", "y", data={"x": np.arange(10.0), "y": np.arange(10.0)}),
        width=200,
        height=140,
    )
    paths = [tmp_path / "a.png", tmp_path / "b.svg", tmp_path / "c.jpg", tmp_path / "d.html"]
    out = xy.write_images(figures=[_fig(), _fig(), chart, _fig()], files=paths)
    assert out[0][:8] == b"\x89PNG\r\n\x1a\n"
    assert out[1][:5] == b"<svg "
    assert out[2][:3] == b"\xff\xd8\xff"
    assert b"<!doctype html>" in out[3]
    for path, data in zip(paths, out, strict=True):
        assert path.read_bytes() == data


def test_write_images_quality_ignored_by_non_lossy_batch_members(tmp_path):
    # PNG and native (lossless) WebP members must not abort a batch whose
    # quality only targets the lossy members (PR #115 review).
    out = export.write_images(
        [_fig(), _fig(), _fig()],
        [tmp_path / "a.png", tmp_path / "b.jpg", tmp_path / "c.webp"],
        quality=50,
    )
    assert out[0][:8] == b"\x89PNG\r\n\x1a\n" and out[1][:3] == b"\xff\xd8\xff"
    assert out[2][:4] == b"RIFF"
    with pytest.raises(ValueError, match=r"1\.\.100"):
        export.write_images([_fig()], [tmp_path / "d.png"], quality=500)


def test_write_images_resolves_chart_export_config_defaults(tmp_path):
    # Converting charts to figures must not drop their declarative export
    # defaults (PR #115 review): a chart configured for 123x77 at scale 1
    # exports at exactly 123x77 through the batch API too.
    chart = xy.chart(
        xy.line("x", "y", data={"x": np.arange(10.0), "y": np.arange(10.0)}),
        xy.export_config(width=123, height=77, scale=1.0),
    )
    out = export.write_images([chart], [tmp_path / "configured.png"])
    assert _decode(out[0]).size == (123, 77)
    # Batch-level arguments still override the declarative defaults.
    out = export.write_images([chart], [tmp_path / "explicit.png"], width=64, height=32, scale=1.0)
    assert _decode(out[0]).size == (64, 32)


def test_write_images_formats_override_and_mismatch(tmp_path):
    out = export.write_images([_fig()], [tmp_path / "chart.dat"], formats="png")
    assert out[0][:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError, match="1 formats but 2 paths"):
        export.write_images(
            [_fig(), _fig()], [tmp_path / "a.png", tmp_path / "b.png"], formats=["png"]
        )


def test_write_images_alias_conflicts_rejected(tmp_path):
    with pytest.raises(ValueError, match="not both"):
        export.write_images([_fig()], [tmp_path / "a.png"], figures=[_fig()])
    with pytest.raises(ValueError, match="needs both"):
        export.write_images(figures=[_fig()])


# -- declarative export_config ---------------------------------------------


def test_export_config_reaches_spec():
    chart = xy.chart(
        xy.line("x", "y", data={"x": np.arange(10.0), "y": np.arange(10.0)}),
        xy.export_config(
            formats=["png", "jpg", "csv"],
            filename="report",
            width=640,
            height=360,
            scale=1.0,
            background="#fff",
            quality=75,
        ),
    )
    spec, _ = chart.figure().build_payload()
    assert spec["export"] == {
        "formats": ["png", "jpeg", "csv"],
        "filename": "report",
        "width": 640,
        "height": 360,
        "scale": 1.0,
        "background": "#fff",
        "quality": 75,
    }


def test_export_config_defaults_apply_and_explicit_args_win():
    chart = xy.chart(
        xy.line("x", "y", data={"x": np.arange(10.0), "y": np.arange(10.0)}),
        xy.export_config(width=640, height=360, scale=1.0, quality=75),
    )
    assert _decode(chart.to_image("png")).size == (640, 360)
    assert _decode(chart.to_image("png", width=320, height=180)).size == (320, 180)
    # Config quality applies to JPEG but must not leak into non-lossy formats.
    assert chart.to_image("svg")[:5] == b"<svg "
    assert chart.to_image("webp")[:4] == b"RIFF"


def test_export_config_empty_formats_and_validation():
    assert xy.export_config(formats=[]).formats == ()
    with pytest.raises(ValueError, match="format must be one of"):
        xy.export_config(formats=["bmp"])
    with pytest.raises(ValueError, match="repeats"):
        xy.export_config(formats=["png", "jpg", "jpeg"])
    with pytest.raises(ValueError, match="plain basename"):
        xy.export_config(filename="../evil")
    with pytest.raises(ValueError, match=r"1\.\.100"):
        xy.export_config(quality=101)


def test_export_config_quality_reaches_chromium_webp(monkeypatch):
    # Declarative quality must flow to Chromium's lossy WebP, not just JPEG
    # (PR #115 review); native WebP continues to ignore it (lossless).
    session = _FakeSession()
    monkeypatch.setattr(export, "_browser_session", lambda **kw: session)
    chart = xy.chart(
        xy.line("x", "y", data={"x": np.arange(10.0), "y": np.arange(10.0)}),
        xy.export_config(quality=37),
    )
    chart.to_image("webp", engine=export.Engine.chromium)
    image_calls = [c for c in session.calls if c[0] == "image"]
    assert image_calls[0][1] == "webp" and image_calls[0][5] == 37
    assert chart.to_image("webp")[:4] == b"RIFF"  # native stays lossless, no error


def test_facet_browser_background_reaches_document(monkeypatch):
    # The facet Chromium path must inject the background override into the
    # captured document, as the single-chart path does (PR #115 review).
    session = _FakeSession()
    captured: list[str] = []

    def fake_session(**kw):
        return session

    original = session.render_image

    def spying_render_image(html, *args, **kwargs):
        captured.append(html)
        return original(html, *args, **kwargs)

    session.render_image = spying_render_image
    monkeypatch.setattr(export, "_browser_session", fake_session)
    grid = _grid().figure()
    grid.to_image("png", engine=export.Engine.chromium, background="#112233")
    assert ".xy{background:#112233 !important;--chart-bg:transparent !important;}" in captured[0]


def test_export_config_component_is_revalidated_at_compile():
    chart = xy.chart(
        xy.line("x", "y", data={"x": np.arange(4.0), "y": np.arange(4.0)}),
        xy.ExportConfig(formats=("bmp",)),
    )
    with pytest.raises(ValueError, match="format must be one of"):
        chart.figure()


# -- facet parity -----------------------------------------------------------


def _grid():
    return xy.facet_chart(
        xy.scatter("x", "y"),
        data={
            "x": np.arange(40.0),
            "y": np.arange(40.0),
            "g": np.repeat(["a", "b"], 20),
        },
        by="g",
    )


def test_facet_grid_supports_the_native_format_matrix(tmp_path):
    grid = _grid()
    assert grid.to_image("png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert grid.to_image("svg")[:5] == b"<svg "
    assert grid.to_image("pdf")[:5] == b"%PDF-"
    assert grid.to_image("jpeg")[:3] == b"\xff\xd8\xff"
    assert grid.to_image("webp")[:4] == b"RIFF"
    data = grid.write_image(tmp_path / "grid.webp")
    assert (tmp_path / "grid.webp").read_bytes() == data


def test_facet_background_reaches_gap_pixels():
    grid = _grid().figure()
    canvas = grid._compose_rgba(1.0, "#112233")
    # The inter-panel gap column shows the backdrop, not panel pixels.
    gap_x = grid.panel_width + grid.gap // 2
    assert tuple(canvas[0, gap_x]) == (0x11, 0x22, 0x33, 255)


def test_facet_write_image_html_route(tmp_path):
    data = _grid().write_image(tmp_path / "grid.html")
    assert b"<!doctype html>" in data


# -- compatibility ----------------------------------------------------------


def test_legacy_methods_unchanged():
    fig = _fig()
    assert fig.to_png()[:8] == b"\x89PNG\r\n\x1a\n"
    assert fig.to_svg().startswith("<svg ")
    assert "<!doctype html>" in fig.to_html()


def test_png_ihdr_dimensions_honor_scale():
    png = export.to_image(_fig(300, 200), "png", scale=1.0)
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (300, 200)
    png2x = export.to_image(_fig(300, 200), "png", scale=2.0)
    width2, height2 = struct.unpack(">II", png2x[16:24])
    assert (width2, height2) == (600, 400)


def test_pdf_content_is_vector_not_one_big_image():
    pdf = export.to_image(_fig(), "pdf")
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL)
    text = b"".join(
        zlib.decompress(s) if s[:2] in (b"\x78\x9c", b"\x78\xda", b"\x78\x01") else s
        for s in streams
    )
    assert b"BT" in text and b"ET" in text  # vector text survived
    assert b" re" in text or b" l" in text  # vector geometry survived
