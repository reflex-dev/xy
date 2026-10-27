"""Native PNG export (`_raster.py` + the Rust `xy_rasterize` core): valid PNGs
for every chart kind, `scale=`/dimension handling, indexed-vs-truecolor
selection, the screen-bounded size guarantee, colormap fidelity, and parity of
the shared layout with the SVG exporter."""

# ruff: noqa: RUF001 — the glyph-coverage tests are ABOUT confusable non-ASCII.
from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest

import xy
from xy import _png, _raster
from xy._figure import Figure


def _ihdr(png: bytes) -> tuple[int, int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "bad PNG signature"
    assert png[12:16] == b"IHDR"
    w, h = struct.unpack(">II", png[16:24])
    color_type = png[25]
    return w, h, color_type


def _decode_rgba(png: bytes) -> np.ndarray:
    """Small stdlib PNG decoder for the exporter parity oracle."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    position = 8
    width = height = color_type = None
    palette = b""
    transparency = b""
    idat = bytearray()
    while position + 8 <= len(png):
        (length,) = struct.unpack(">I", png[position : position + 4])
        kind = png[position + 4 : position + 8]
        start = position + 8
        chunk = png[start : start + length]
        position = start + length + 4
        if kind == b"IHDR":
            width, height, depth, color_type, _compression, _filter, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            assert depth == 8 and interlace == 0
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            transparency = chunk
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
    assert width is not None and height is not None and color_type is not None
    channels = {2: 3, 3: 1, 6: 4}[color_type]
    row_length = width * channels
    raw = zlib.decompress(bytes(idat))
    previous = bytearray(row_length)
    decoded = bytearray(width * height * 4)
    source = destination = 0
    for _ in range(height):
        filter_kind = raw[source]
        source += 1
        row = bytearray(raw[source : source + row_length])
        source += row_length
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            up_left = previous[index - channels] if index >= channels else 0
            if filter_kind == 1:
                row[index] = (value + left) & 0xFF
            elif filter_kind == 2:
                row[index] = (value + up) & 0xFF
            elif filter_kind == 3:
                row[index] = (value + ((left + up) >> 1)) & 0xFF
            elif filter_kind == 4:
                predictor = left + up - up_left
                distances = (
                    abs(predictor - left),
                    abs(predictor - up),
                    abs(predictor - up_left),
                )
                estimate = (left, up, up_left)[distances.index(min(distances))]
                row[index] = (value + estimate) & 0xFF
            else:
                assert filter_kind == 0
        for column in range(width):
            if color_type == 6:
                rgba = row[column * 4 : column * 4 + 4]
            elif color_type == 2:
                rgba = row[column * 3 : column * 3 + 3] + b"\xff"
            else:
                palette_index = row[column]
                base = palette_index * 3
                alpha = transparency[palette_index] if palette_index < len(transparency) else 255
                rgba = palette[base : base + 3] + bytes((alpha,))
            decoded[destination : destination + 4] = rgba
            destination += 4
        previous = row
    return np.frombuffer(decoded, dtype=np.uint8).reshape(height, width, 4)


def _record_text(monkeypatch) -> list[tuple[float, float, int, float, str]]:
    """Capture every native text command as (x, y, anchor_flags, size, text)."""
    recorded: list[tuple[float, float, int, float, str]] = []
    original_text = _raster._Cmd.text

    def record_text(self, x, y, anchor, size, color, value, **kwargs):
        recorded.append((float(x), float(y), int(anchor), float(size), str(value)))
        return original_text(self, x, y, anchor, size, color, value, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", record_text)
    return recorded


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


def test_raster_best_legend_rescores_final_size_without_mutating_extras() -> None:
    figure = xy.chart(
        xy.bar([0.75], [1.0], base=[0.90], width=0.04, name="series"),
        xy.x_axis(domain=(0.0, 1.0)),
        xy.y_axis(domain=(0.0, 1.0)),
        xy.legend(loc="best"),
        width=640,
        height=360,
    ).figure()
    extra = {
        "loc": "upper right",
        "auto_loc": "best",
        "items": [{"name": "extra", "kind": "bar", "style": {}}],
    }
    figure.extra_legends = [extra]

    spec, _blob, _borrowed = _raster._export_payload(figure, 280, None, None)

    assert spec["legend"] == {
        "loc": "upper left",
        "ncols": 1,
        "auto_loc": "best",
    }
    assert spec["extra_legends"][0]["loc"] == "upper left"
    assert spec["extra_legends"][0]["auto_loc"] == "best"
    assert extra["loc"] == "upper right"
    assert figure.extra_legends[0] is extra


def test_flat_chart_is_indexed_gradient_chart_is_truecolor() -> None:
    # optimize=True retains the size-oriented palette selection path.
    flat = Figure(width=200, height=120).bar(["a", "b"], [1.0, 2.0], color="#2563eb")
    assert _ihdr(flat.to_png(scale=1, optimize=True))[2] == 3
    # A gradient + AA area blows past 256 colors → truecolor (color type 6).
    x = np.linspace(0.0, 6.0, 40)
    grad = Figure(width=400, height=200).area(
        x, np.abs(np.sin(x)) + 0.2, fill="linear-gradient(#1e40af, #93c5fd)"
    )
    assert _ihdr(grad.to_png(scale=1, optimize=True))[2] == 6


def test_public_native_png_defaults_fast_and_optimize_preserves_pixels() -> None:
    fig = Figure(width=320, height=180).line(
        np.linspace(0.0, 8.0, 200), np.sin(np.linspace(0.0, 8.0, 200))
    )

    fast = fig.to_png(scale=1)
    optimized = fig.to_png(scale=1, optimize=True)

    assert _ihdr(fast)[2] == 2
    np.testing.assert_array_equal(_decode_rgba(fast), _decode_rgba(optimized))


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


def test_render_paints_figure_background() -> None:
    import xy

    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        xy.theme(background="#000000"),
        width=200,
        height=120,
    )
    img = _raster.render_raster(*chart.figure().build_payload(), scale=1)
    # Figure patch (mpl figure.facecolor) covers the margins...
    assert tuple(img[0, 0]) == (0, 0, 0, 255)
    # ...and shows through the plot rect when plot_background is unset
    # (no white fallback fill).
    assert (img[10, 50][:3] < 100).all()


def test_render_composites_translucent_figure_background() -> None:
    import xy

    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
        xy.theme(background="rgba(0, 0, 0, 0.5)"),
        width=200,
        height=120,
    )
    img = _raster.render_raster(*chart.figure().build_payload(), scale=1)
    # A translucent figure patch composites over the white canvas fill (the
    # browser's white host page) -> mid gray at full alpha, not raw rgba.
    assert 100 <= int(img[0, 0][0]) <= 155
    assert img[0, 0][3] == 255


def test_raster_honors_tick_label_anchor() -> None:
    import xy

    def render(**axis_kwargs):
        chart = xy.line_chart(
            xy.line(x=[0.0, 1.0], y=[0.0, 1.0]),
            xy.x_axis(**axis_kwargs),
            width=200,
            height=120,
        )
        return _raster.render_raster(*chart.figure().build_payload(), scale=1)

    # Anchoring shifts every x tick label left of its tick; the images must
    # differ only because the anchor reached the rasterizer.
    assert not np.array_equal(render(), render(tick_label_anchor="end"))


@pytest.mark.parametrize(
    ("side", "angle", "expected_anchor"),
    [
        ("bottom", -35, 2),
        ("bottom", 35, 0),
        ("top", 35, 2),
        ("top", -35, 0),
    ],
)
def test_raster_rotated_x_ticks_match_svg_default_anchor(
    monkeypatch,
    side: str,
    angle: int,
    expected_anchor: int,
) -> None:
    axis_id = "x" if side == "bottom" else "x2"
    chart = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0], x_axis=axis_id),
        xy.x_axis(
            id=axis_id,
            side=side,
            tick_values=(0.0, 1.0),
            tick_labels=("Long category alpha", "Long category beta"),
            tick_label_strategy="preserve",
            tick_label_angle=angle,
        ),
        width=480,
        height=280,
    )
    spec, blob = chart.figure().build_payload()
    recorded = _record_text(monkeypatch)

    _raster.render_raster(spec, blob, scale=1)

    anchors = {entry[2] & 0x03 for entry in recorded if entry[4].startswith("Long category")}
    assert anchors == {expected_anchor}


def test_raster_legend_text_honors_theme_text_color() -> None:
    # Red is reserved for the theme text color; every other paint is green,
    # and the tick labels are overridden, so red pixels can only come from
    # the legend text.
    chart = xy.line_chart(
        xy.line(x=[0.0, 1.0], y=[0.0, 1.0], color="#00ff00", name="walk"),
        xy.x_axis(style={"tick_label_color": "#00ff00"}),
        xy.y_axis(style={"tick_label_color": "#00ff00"}),
        xy.legend(loc="upper right"),
        xy.theme(
            text_color="#ff0000",
            grid_color="transparent",
            axis_color="#00ff00",
        ),
        width=300,
        height=200,
    )
    img = _raster.render_raster(*chart.figure().build_payload(), scale=1)
    red = (img[:, :, 0] > 150) & (img[:, :, 1] < 80) & (img[:, :, 2] < 80)
    assert int(red.sum()) > 20


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
    x = np.linspace(-2.0, 2.0, 80)
    xx, yy = np.meshgrid(x, x)
    figures = [
        Figure(width=360, height=220).line(x, np.sin(x * 3.0)),
        Figure(width=360, height=220).heatmap(np.sin(xx) + np.cos(yy)),
        Figure(width=360, height=220).contour(np.sin(xx * 1.7) + np.cos(yy * 2.1), levels=7),
    ]

    for figure in figures:
        balanced = _decode_rgba(_raster.to_png(figure, scale=1))
        fast = _decode_rgba(_raster.to_png(figure, scale=1, fast=True))
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


def test_native_long_legend_is_clamped_and_ellipsized_inside_plot(monkeypatch) -> None:
    from xy import _svg

    names = [f"series-{index}-" + "very-long-operational-label-" * 2 for index in range(4)]
    chart = xy.line_chart(
        *(
            xy.line([0.0, 1.0], [float(index), float(index + 1)], name=name)
            for index, name in enumerate(names)
        ),
        xy.legend(
            loc="upper right",
            ncols=2,
            title="Long operational series",
            style={"background": "#ff00ff", "--xy-legend-frame-alpha": 1},
        ),
        width=320,
        height=260,
    )
    spec, blob = chart.figure().build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    recorded = _record_text(monkeypatch)
    image = _raster.render_raster(spec, blob, scale=1)
    rendered_text = [entry[4] for entry in recorded]

    magenta = np.all(image[:, :, :3] == np.array([255, 0, 255], dtype=np.uint8), axis=2)
    rows, columns = np.where(magenta)
    assert len(columns) > 0
    assert columns.min() >= int(plot["x"])
    assert columns.max() <= int(plot["x"] + plot["w"])
    assert rows.min() >= int(plot["y"])
    assert rows.max() <= int(plot["y"] + plot["h"])
    assert all(name not in rendered_text for name in names)
    assert any(text.endswith("...") for text in rendered_text)


def test_native_secondary_y_axis_scales_trace_and_renders_right_chrome() -> None:
    from xy import _svg

    chart = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0], color="#2563eb", width=3),
        xy.line(
            [0.0, 1.0],
            [100.0, 200.0],
            color="#dc2626",
            width=3,
            y_axis="y2",
        ),
        xy.y_axis(label="Primary"),
        xy.y_axis(
            id="y2",
            label="Secondary",
            side="right",
            domain=(100.0, 200.0),
            tick_values=(100.0, 150.0, 200.0),
            style={
                "axis_color": "#dc2626",
                "axis_width": 2,
                "tick_color": "#dc2626",
                "tick_label_color": "#dc2626",
                "label_color": "#dc2626",
                "tick_length": 5,
                "tick_width": 2,
            },
        ),
        width=400,
        height=240,
    )
    spec, blob = chart.figure().build_payload()
    width, _height, _compact, plot = _svg.layout(spec)
    image = _raster.render_raster(spec, blob, scale=1)

    red = (
        (image[:, :, 0] > 180)
        & (image[:, :, 1] < 100)
        & (image[:, :, 2] < 100)
        & (image[:, :, 3] > 0)
    )
    x0, x1 = int(plot["x"]), int(plot["x"] + plot["w"])
    y0, y1 = int(plot["y"]), int(plot["y"] + plot["h"])
    assert int(red[y0 + 2 : y1 - 2, x0 + 2 : x1 - 2].sum()) > 20
    assert int(red[y0:y1, x1 + 1 : width].sum()) > 20


def test_native_secondary_x_axis_scales_trace_and_renders_top_chrome() -> None:
    from xy import _svg

    chart = xy.chart(
        xy.line([0.0, 1.0], [0.0, 1.0], color="#2563eb", width=3),
        xy.line(
            [100.0, 200.0],
            [0.2, 0.8],
            color="#dc2626",
            width=3,
            x_axis="x2",
        ),
        xy.x_axis(label="Primary X"),
        xy.x_axis(
            id="x2",
            label="Secondary X",
            side="top",
            domain=(100.0, 200.0),
            tick_values=(100.0, 150.0, 200.0),
            style={
                "axis_color": "#dc2626",
                "axis_width": 2,
                "tick_color": "#dc2626",
                "tick_label_color": "#dc2626",
                "label_color": "#dc2626",
                "tick_length": 5,
                "tick_width": 2,
            },
        ),
        width=400,
        height=240,
    )
    spec, blob = chart.figure().build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    image = _raster.render_raster(spec, blob, scale=1)

    red = (
        (image[:, :, 0] > 180)
        & (image[:, :, 1] < 100)
        & (image[:, :, 2] < 100)
        & (image[:, :, 3] > 0)
    )
    x0, x1 = int(plot["x"]), int(plot["x"] + plot["w"])
    y0, y1 = int(plot["y"]), int(plot["y"] + plot["h"])
    assert int(red[y0 + 2 : y1 - 2, x0 + 2 : x1 - 2].sum()) > 20
    assert int(red[:y0, x0:x1].sum()) > 20


def test_native_mixed_primary_and_named_x_axis_kinds_render_independently(monkeypatch) -> None:
    cases = (
        (
            xy.chart(
                xy.line(["Primary Alpha", "Primary Beta", "Primary Gamma"], [1.0, 2.0, 3.0]),
                xy.line([100.0, 200.0, 300.0], [3.0, 2.0, 1.0], x_axis="x2"),
                xy.x_axis(tick_label_strategy="rotate"),
                xy.x_axis(
                    id="x2",
                    side="top",
                    type_="linear",
                    tick_values=(100.0, 200.0, 300.0),
                    tick_labels=("N100", "N200", "N300"),
                    tick_label_strategy="rotate",
                ),
                width=560,
                height=300,
            ),
            {"Primary Alpha", "Primary Gamma", "N100", "N300"},
        ),
        (
            xy.chart(
                xy.line([10.0, 20.0, 30.0], [1.0, 2.0, 3.0]),
                xy.line(["Named Red", "Named Green", "Named Blue"], [3.0, 2.0, 1.0], x_axis="x2"),
                xy.x_axis(
                    type_="linear",
                    tick_values=(10.0, 20.0, 30.0),
                    tick_labels=("P10", "P20", "P30"),
                    tick_label_strategy="rotate",
                ),
                xy.x_axis(id="x2", side="top", tick_label_strategy="rotate"),
                width=560,
                height=300,
            ),
            {"P10", "P30", "Named Red", "Named Blue"},
        ),
    )
    recorded = _record_text(monkeypatch)
    for chart, expected_labels in cases:
        recorded.clear()
        spec, blob = chart.figure().build_payload()
        _raster.render_raster(spec, blob, scale=1)
        assert expected_labels <= {entry[4] for entry in recorded}


def test_native_named_axis_collision_and_title_placement_controls(monkeypatch) -> None:
    from xy import _svg

    values = list(range(30))
    tick_labels = [f"very-long-native-label-{value}" for value in values]
    chart = xy.chart(
        xy.line(values, values, x_axis="x2"),
        xy.x_axis(
            id="x2",
            side="top",
            label="Native positioned title",
            label_position="inside_end",
            label_offset=6,
            label_angle=90,
            domain=(0.0, 29.0),
            tick_values=values,
            tick_labels=tick_labels,
            tick_label_strategy="hide",
        ),
        width=400,
        height=240,
    )
    spec, blob = chart.figure().build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    recorded = _record_text(monkeypatch)
    _raster.render_raster(spec, blob, scale=1)

    visible_ticks = [entry for entry in recorded if entry[4] in tick_labels]
    assert 0 < len(visible_ticks) < len(tick_labels)
    title_x, title_y, title_anchor, _size, _text = next(
        entry for entry in recorded if entry[4] == "Native positioned title"
    )
    assert title_x == plot["x"] + plot["w"]
    assert plot["y"] < title_y < plot["y"] + plot["h"]
    assert title_anchor == 2 | _raster._TEXT_ROT_CW


def test_native_vertical_colorbar_label_is_rotated_beside_the_bar_inside_the_canvas(
    monkeypatch,
) -> None:
    """A vertical colorbar's label must match Matplotlib: rotated 90° CCW,
    centered alongside the bar and outboard of its ticks, fully on canvas.

    It previously rendered horizontally above the bar at `plot.y - 5`, so the
    glyph ascent overflowed the canvas top edge and the label was clipped.
    """
    from xy import _svg

    chart = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis", domain=(0.0, 3.0)),
        xy.colorbar(title="counts in bin"),
        width=560,
        height=320,
    )
    spec, blob = chart.figure().build_payload()
    width, _height, _compact, plot = _svg.layout(spec)
    recorded = _record_text(monkeypatch)
    _raster.render_raster(spec, blob, scale=1)

    label_x, label_y, anchor, size, _text = next(
        entry for entry in recorded if entry[4] == "counts in bin"
    )
    # Rotated bottom-to-top (mpl rotation=90), centered along the reading axis.
    assert anchor == 1 | _raster._TEXT_ROT_CCW
    assert label_y == plot["y"] + plot["h"] / 2
    # Beside the bar, past every tick label — not above the bar.
    tick_x = max(entry[0] for entry in recorded if entry[4] in {"0", "1", "2", "3"})
    assert label_x > tick_x
    assert plot["y"] < label_y < plot["y"] + plot["h"]
    # Inside the canvas across the rotated label's baseline: the glyph box
    # spans [x - ascent, x + descent] (ascent ~0.78em, descent ~0.22em).
    assert label_x + 0.22 * size < width


def test_native_vertical_colorbar_label_leaves_the_canvas_edges_unpainted() -> None:
    """The clipping symptom itself: no label ink may reach the canvas border."""
    chart = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis", domain=(0.0, 3.0)),
        xy.colorbar(title="counts in bin"),
        width=560,
        height=320,
    )
    pixels = _decode_rgba(chart.to_png())
    ink = pixels[:, :, :3].astype(int).sum(axis=2) < 200
    assert not ink[0].any() and not ink[-1].any()
    assert not ink[:, 0].any() and not ink[:, -1].any()


def test_native_horizontal_colorbar_label_stays_upright_below_the_bar(monkeypatch) -> None:
    """The horizontal orientation reads left-to-right, so it must not rotate."""
    from xy import _svg

    chart = xy.heatmap_chart(
        xy.heatmap([[0.0, 1.0], [2.0, 3.0]], colormap="viridis", domain=(0.0, 3.0)),
        xy.colorbar(title="counts in bin", orientation="horizontal"),
        width=560,
        height=320,
    )
    spec, blob = chart.figure().build_payload()
    _width, _height, _compact, plot = _svg.layout(spec)
    recorded = _record_text(monkeypatch)
    _raster.render_raster(spec, blob, scale=1)

    label_x, label_y, anchor, _size, _text = next(
        entry for entry in recorded if entry[4] == "counts in bin"
    )
    assert anchor & (_raster._TEXT_ROT_CCW | _raster._TEXT_ROT_CW) == 0
    assert label_x == plot["x"] + plot["w"] / 2
    assert label_y > plot["y"] + plot["h"]


def test_native_diagonal_tick_angle_keeps_all_labels_when_they_fit(monkeypatch) -> None:
    # Arbitrary tick angles use the native styled-text command and keep the
    # same collision-selected label set as SVG/browser.
    tick_values = [0.0, 25.0, 50.0, 75.0, 100.0]
    tick_labels = ["t0", "t25", "t50", "t75", "t100"]
    chart = xy.chart(
        xy.line([0.0, 100.0], [0.0, 1.0]),
        xy.x_axis(
            domain=(0.0, 100.0),
            tick_values=tick_values,
            tick_labels=tick_labels,
            tick_label_angle=45,
        ),
        width=560,
        height=300,
    )
    spec, blob = chart.figure().build_payload()
    angles: dict[str, float] = {}
    original_text = _raster._Cmd.text

    def record_text(self, x, y, anchor, size, color, value, **kwargs):
        angles[str(value)] = float(kwargs.get("angle", 0.0))
        return original_text(self, x, y, anchor, size, color, value, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "text", record_text)
    _raster.render_raster(spec, blob, scale=1)

    assert set(tick_labels) <= angles.keys()
    assert {angles[label] for label in tick_labels} == {45.0}


def test_native_smooth_stroke_matches_reference_polyline() -> None:
    from xy import _scene, _svg, kernels

    x = np.array([0.0, 0.7, 0.7, 2.0, 2.8, 4.0])
    y = np.array([1.0, 3.0, 2.0, 2.5, -1.0, 1.0])
    sx = _svg._Scale({"range": [0.0, 4.0], "kind": "linear"}, 20, 580)
    sy = _svg._Scale({"range": [-1.0, 3.0], "kind": "linear"}, 280, 20)
    color = (30, 90, 210, 177)
    reference = _raster._Cmd(1)
    reference.clip(0, 0, 600, 300)
    reference.stroke(_scene.curve_points(x, y, sx, sy, True), 2.25, color, dash=[4.0, 2.0])
    native = _raster._Cmd(1)
    native.clip(0, 0, 600, 300)
    native.smooth_stroke(x, y, sx, sy, 2.25, color, dash=[4.0, 2.0])

    np.testing.assert_array_equal(
        kernels.rasterize(bytes(native.buf), 600, 300),
        kernels.rasterize(bytes(reference.buf), 600, 300),
    )


def test_native_shape_batches_match_individual_commands() -> None:
    from xy import kernels

    x0 = np.array([10.25, 45.0, 80.75])
    y0 = np.array([12.5, 30.25, 8.0])
    x1 = np.array([35.5, 72.75, 110.0])
    y1 = np.array([55.0, 70.5, 44.25])
    colors = np.array([[220, 40, 30, 255], [20, 160, 90, 177], [30, 80, 220, 96]], np.uint8)
    reference = _raster._Cmd(1)
    batch = _raster._Cmd(1)
    for i in range(len(x0)):
        reference.fill(
            [(x0[i], y0[i]), (x1[i], y0[i]), (x1[i], y1[i]), (x0[i], y1[i])],
            tuple(int(value) for value in colors[i]),
        )
    batch.rects(x0, y0, x1, y1, colors)
    np.testing.assert_array_equal(
        kernels.rasterize(bytes(batch.buf), 128, 80),
        kernels.rasterize(bytes(reference.buf), 128, 80),
    )
    tx0, ty0 = x0, y0
    tx1, ty1 = x1, y0 + 4.0
    tx2, ty2 = (x0 + x1) / 2.0, y1
    reference = _raster._Cmd(1)
    batch = _raster._Cmd(1)
    for i in range(len(tx0)):
        reference.fill(
            [(tx0[i], ty0[i]), (tx1[i], ty1[i]), (tx2[i], ty2[i])],
            tuple(int(value) for value in colors[i]),
        )
    batch.triangles(tx0, ty0, tx1, ty1, tx2, ty2, colors)
    np.testing.assert_array_equal(
        kernels.rasterize(bytes(batch.buf), 128, 80),
        kernels.rasterize(bytes(reference.buf), 128, 80),
    )


def test_borrowed_affine_points_match_expanded_batch() -> None:
    from xy import _native, _svg, kernels

    encoded_x = np.tile(np.array([-2.25, -0.5, 0.75, 2.0, np.nan], dtype="<f4"), 8)
    encoded_y = np.tile(np.array([1.5, -1.0, 0.25, 2.25, 0.0], dtype="<f4"), 8)
    x_meta = {"span": 0, "byte_offset": 4, "len": len(encoded_x), "scale": 0.25, "offset": 1000.0}
    y_meta = {"span": 1, "byte_offset": 8, "len": len(encoded_y), "scale": 2.0, "offset": -40.0}
    sx = _svg._Scale({"range": [990.0, 1010.0], "kind": "linear"}, 2.25, 37.5)
    sy = _svg._Scale({"range": [-42.0, -38.0], "kind": "linear"}, 25.0, 1.5)
    scale = 1.75
    radius, fill, symbol = 2.0, (27, 119, 231, 143), 3
    stroke_width, stroke = 0.75, (8, 9, 10, 211)
    spans = (b"xpad" + encoded_x.tobytes(), b"ypad----" + encoded_y.tobytes())

    direct = _raster._Cmd(scale)
    direct.affine_points(x_meta, y_meta, sx, sy, radius, fill, symbol, stroke_width, stroke)
    xv = encoded_x.astype(np.float64) / x_meta["scale"] + x_meta["offset"]
    yv = encoded_y.astype(np.float64) / y_meta["scale"] + y_meta["offset"]
    expanded = _raster._Cmd(scale)
    expanded.points(
        sx(xv),
        sy(yv),
        np.full(len(xv), radius),
        np.tile(np.asarray(fill, np.uint8), (len(xv), 1)),
        symbol,
        stroke_width,
        stroke,
    )

    assert len(direct.buf) < len(expanded.buf)
    np.testing.assert_array_equal(
        _native.rasterize_spans(bytes(direct.buf), spans, 72, 52),
        kernels.rasterize(bytes(expanded.buf), 72, 52),
    )


def test_static_scatter_affine_fast_path_keeps_general_fallbacks(monkeypatch) -> None:
    constant_calls = 0
    channel_calls = 0
    affine_points = _raster._Cmd.affine_points
    affine_channel_points = _raster._Cmd.affine_channel_points

    def recording_affine_points(self, *args, **kwargs):
        nonlocal constant_calls
        constant_calls += 1
        return affine_points(self, *args, **kwargs)

    def recording_affine_channel_points(self, *args, **kwargs):
        nonlocal channel_calls
        channel_calls += 1
        return affine_channel_points(self, *args, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "affine_points", recording_affine_points)
    monkeypatch.setattr(_raster._Cmd, "affine_channel_points", recording_affine_channel_points)
    x = np.linspace(1.0, 10.0, 31)
    constant = Figure(width=240, height=140).scatter(x, np.sin(x), color="#2563eb", size=7)
    assert _raster.render_raster(*constant.build_payload(), scale=1).shape == (140, 240, 4)
    assert (constant_calls, channel_calls) == (1, 0)

    colored = Figure(width=240, height=140).scatter(x, np.sin(x), color=x)
    assert _raster.render_raster(*colored.build_payload(), scale=1).shape == (140, 240, 4)
    assert (constant_calls, channel_calls) == (1, 1)

    sized = Figure(width=240, height=140).scatter(x, np.sin(x), size=x)
    assert _raster.render_raster(*sized.build_payload(), scale=1).shape == (140, 240, 4)
    assert (constant_calls, channel_calls) == (1, 2)

    log_axis = Figure(width=240, height=140).scatter(x, np.sin(x), color=x)
    log_axis.set_axis("x", type_="log")
    assert _raster.render_raster(*log_axis.build_payload(), scale=1).shape == (140, 240, 4)
    assert (constant_calls, channel_calls) == (1, 2)


def test_affine_static_scatter_full_render_matches_expanded(monkeypatch) -> None:
    from xy import _svg

    rng = np.random.default_rng(2026)
    x = 1e12 + rng.normal(scale=3.0, size=2_000)
    y = rng.normal(size=2_000)
    color_values = np.linspace(-1.0, 1.0, len(x))
    size_values = np.sin(np.linspace(0.0, 12.0, len(x)))
    categories = np.asarray([f"group-{index % 7}" for index in range(len(x))])
    figures = [
        Figure(width=360, height=220).scatter(
            x,
            y,
            color="#7c3aed",
            size=6,
            opacity=0.65,
            symbol="diamond",
            stroke="#111827",
            stroke_width=0.5,
        ),
        Figure(width=360, height=220).scatter(
            x,
            y,
            color="transparent",
            size=9,
            symbol="diamond",
            stroke="#666666",
            stroke_width=1.0,
        ),
        Figure(width=360, height=220).scatter(x, y, color=color_values, colormap="plasma"),
        Figure(width=360, height=220).scatter(x, y, color=categories),
        Figure(width=360, height=220).scatter(
            x, y, color="#2563eb", size=size_values, size_range=(2, 8)
        ),
        Figure(width=360, height=220).scatter(
            x, y, color=color_values, size=size_values, size_range=(2, 8)
        ),
    ]
    payloads = [figure.build_payload() for figure in figures]
    direct = [_raster.render_raster(spec, blob, scale=2) for spec, blob in payloads]
    monkeypatch.setattr(_svg._Scale, "affine", property(lambda _self: False))
    expanded = [_raster.render_raster(spec, blob, scale=2) for spec, blob in payloads]
    for direct_image, expanded_image in zip(direct, expanded, strict=True):
        np.testing.assert_array_equal(direct_image, expanded_image)


def test_stroked_triangle_mesh_batch_matches_expanded_commands(monkeypatch) -> None:
    rng = np.random.default_rng(741)
    n = 257
    x0 = rng.uniform(-2.0, 2.0, n)
    y0 = rng.uniform(-1.0, 1.0, n)
    x1 = x0 + rng.uniform(0.05, 0.3, n)
    y1 = y0 + rng.uniform(-0.15, 0.15, n)
    x2 = x0 + rng.uniform(-0.15, 0.15, n)
    y2 = y0 + rng.uniform(0.05, 0.3, n)
    figure = Figure(width=360, height=220).triangle_mesh(
        x0,
        y0,
        x1,
        y1,
        x2,
        y2,
        color=np.linspace(-1.0, 1.0, n),
        colormap="plasma",
        opacity=0.73,
        stroke="#111827",
        stroke_width=0.75,
    )
    payload = figure.build_payload()
    direct = _raster.render_raster(*payload, scale=2)

    def expanded_triangles(self, x0, y0, x1, y1, x2, y2, fills, sw=0.0, stroke=None):
        for i in range(len(x0)):
            triangle = [(x0[i], y0[i]), (x1[i], y1[i]), (x2[i], y2[i])]
            self.fill(triangle, tuple(int(value) for value in fills[i]))
            if sw > 0:
                self.stroke(triangle, sw, stroke, closed=True)

    monkeypatch.setattr(_raster._Cmd, "triangles", expanded_triangles)
    expanded = _raster.render_raster(*payload, scale=2)
    np.testing.assert_array_equal(direct, expanded)


def test_static_log_scale_reads_serialized_scale_field() -> None:
    from xy import _svg

    axis = {"kind": "linear", "scale": "log", "range": [1.0, 1_000.0]}
    scale = _svg._Scale(axis, 0.0, 300.0)
    np.testing.assert_allclose(scale(np.array([1.0, 10.0, 100.0, 1_000.0])), [0, 100, 200, 300])
    ticks, labels, _step = _svg.axis_ticks(axis, 300, True)
    assert {1.0, 10.0, 100.0, 1_000.0}.issubset(ticks)
    assert {1.0, 100.0}.issubset(labels)


def test_compact_density_command_matches_expanded_image() -> None:
    from xy import _native, kernels

    w, h = 31, 17
    encoded = ((np.arange(w * h, dtype=np.uint16) * 47 + 13) % 256).astype(np.uint8)
    stops = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [253, 231, 37]], np.uint8)
    maximum, opacity = 10_000.0, 0.73
    rgba = kernels.density_rgba(encoded, w, h, maximum, stops, opacity)

    compact = _raster._Cmd(1)
    compact.density_image(1.25, -0.75, 79.5, 45.25, w, h, 0, maximum, stops, opacity)
    expanded = _raster._Cmd(1)
    expanded.image(1.25, -0.75, 79.5, 45.25, w, h, rgba.tobytes())

    assert len(compact.buf) < len(expanded.buf) / 2
    np.testing.assert_array_equal(
        _native.rasterize_data(bytes(compact.buf), encoded.tobytes(), 82, 47),
        kernels.rasterize(bytes(expanded.buf), 82, 47),
    )


def test_direct_heatmap_command_matches_expanded_image() -> None:
    from xy import _native, kernels

    w, h = 31, 17
    values = ((np.arange(w * h, dtype=np.uint16) * 47 + 13) % 256).astype(np.float32) / 255
    values[::37] = np.nan
    values[1::37] = 0
    stops = np.array([[68, 1, 84], [59, 82, 139], [33, 145, 140], [253, 231, 37]], np.uint8)
    alpha = 187
    rgba = kernels.heatmap_rgba(values, w, h, stops, alpha)

    direct = _raster._Cmd(1)
    direct.heatmap_image(1.25, -0.75, 15.5, 10.25, w, h, 0, stops, alpha)
    expanded = _raster._Cmd(1)
    expanded.image(1.25, -0.75, 15.5, 10.25, w, h, rgba.tobytes(), nearest=True)

    np.testing.assert_array_equal(
        _native.rasterize_data(bytes(direct.buf), values.astype("<f4").tobytes(), 18, 11),
        kernels.rasterize(bytes(expanded.buf), 18, 11),
    )


def test_raster_payload_borrows_canonical_heatmap_with_exact_pixels() -> None:
    values = np.linspace(-3.0, 7.0, 31 * 17, dtype=np.float64).reshape(17, 31)
    values[2, 5] = np.nan
    figure = Figure(width=320, height=180).heatmap(values, domain=(-2.0, 6.0), opacity=0.73)

    browser_spec, browser_blob = figure.build_payload()
    raster_spec, raster_blob, borrowed = figure._build_raster_payload()
    browser_grid = browser_spec["traces"][0]["heatmap"]
    raster_grid = raster_spec["traces"][0]["heatmap"]
    raster_meta = raster_spec["columns"][raster_grid["buf"]]

    assert "enc" not in browser_grid
    assert len(browser_blob) == values.size * 4
    assert raster_grid["enc"] == "canonical-f64"
    assert raster_meta == {
        "span": 1,
        "byte_offset": 0,
        "len": values.size,
        "dtype": "f64",
    }
    assert raster_blob == b""
    assert len(borrowed) == 1
    assert np.shares_memory(borrowed[0], figure.traces[0].grid.values)

    expanded = _raster.render_raster(browser_spec, browser_blob, scale=1)
    direct = _raster.render_raster(
        raster_spec,
        raster_blob,
        scale=1,
        borrowed=borrowed,
    )
    np.testing.assert_array_equal(direct, expanded)


def test_public_native_heatmap_png_skips_browser_normalization(monkeypatch) -> None:
    from xy import _payload

    figure = Figure(width=180, height=120).heatmap(
        np.arange(20_000, dtype=np.float64).reshape(100, 200),
        domain=(0.0, 19_999.0),
    )

    def fail_normalization(*_args, **_kwargs):
        raise AssertionError("native static heatmap should borrow canonical values")

    monkeypatch.setattr(_payload.kernels, "normalize_f32", fail_normalization)
    png = figure.to_png(scale=1)
    assert _ihdr(png)[:2] == (180, 120)


def _dark_pixel_count(png: bytes, threshold: int = 60) -> int:
    rgba = _decode_rgba(png)
    rgb = rgba[..., :3].astype(np.int64)
    return int(((rgb < threshold).all(axis=-1) & (rgba[..., 3] > 200)).sum())


def test_bar_scalar_stroke_color_renders_in_png() -> None:
    """Regression: scalar stroke= must not collapse to the face paint."""
    fig = Figure().bar(
        [0, 1, 2], [1.0, 2.0, 3.0], color="white", stroke="black", stroke_width=4.0, opacity=1.0
    )
    assert _dark_pixel_count(fig.to_png(width=300, height=200)) > 200


def test_scatter_direct_edges_with_colormap_c_render_in_png() -> None:
    """Regression: the affine channel fast path must defer to the styled
    painter when a per-point stroke channel is present."""
    edges = np.tile([0.0, 0.0, 0.0, 1.0], (3, 1))
    fig = Figure().scatter(
        [0, 1, 2],
        [0, 1, 0],
        color=np.array([0.9, 0.95, 1.0]),
        size=24.0,
        stroke=edges,
        stroke_width=4.0,
        opacity=1.0,
    )
    assert _dark_pixel_count(fig.to_png(width=300, height=200)) > 200


def _text_commands(monkeypatch, chart) -> dict[str, tuple[float, float]]:
    """``{text: (x, y)}`` for every text op the raster display list emits."""
    emitted: dict[str, tuple[float, float]] = {}
    original = _raster._Cmd.text

    def record(self, x, y, anchor, size, color, s):
        emitted[str(s)] = (x, y)
        return original(self, x, y, anchor, size, color, s)

    monkeypatch.setattr(_raster._Cmd, "text", record)
    _raster.render_raster(*chart.figure().build_payload(), scale=1)
    return emitted


def _tick_geometry_chart(style=None) -> xy.Chart:
    """A 3x3 tick grid with a pinned plot rect, so offsets are exact integers."""
    return xy.chart(
        xy.line([0.0, 1.0, 2.0], [0.0, 1.0, 0.5]),
        xy.x_axis(domain=(0.0, 2.0), tick_values=[0.0, 1.0, 2.0], style=style),
        xy.y_axis(domain=(0.0, 1.0), tick_values=[0.0, 0.5, 1.0], style=style),
        width=400,
        height=300,
        padding=(40, 50, 40, 50),
    )


def test_unstyled_tick_labels_keep_their_historical_raster_placement(monkeypatch) -> None:
    """The native display list must place unstyled tick labels where it always
    has.

    `tick_padding` derives the spine-to-label gap from tick geometry, but
    core's default `tick_length` is 0, so deriving it unconditionally silently
    pulls every unstyled chart's labels toward the spine — see
    `_axis_tick_label_offset`. The 15 px bottom gap is one pixel tighter than
    the SVG exporter's 16 and has always been; this seam does not reconcile it.
    """
    plot = _raster.layout(_tick_geometry_chart().figure().build_payload()[0])[3]
    assert (plot["x"], plot["y"], plot["w"], plot["h"]) == (50.0, 40.0, 300.0, 220.0)

    unstyled = _text_commands(monkeypatch, _tick_geometry_chart())
    # x, bottom: baseline 15 px below the spine, centered on the tick.
    assert unstyled["0"] == (50.0, 275.0)
    assert unstyled["1"] == (200.0, 275.0)
    assert unstyled["2"] == (350.0, 275.0)
    # y, left: 8 px outside the spine, baseline nudged 4 px below the tick.
    assert unstyled["0.0"] == (42.0, 264.0)
    assert unstyled["0.5"] == (42.0, 154.0)
    assert unstyled["1.0"] == (42.0, 44.0)

    # Flat constants, as before `tick_padding`: the tick font must not move them.
    big_font = _text_commands(monkeypatch, _tick_geometry_chart(style={"tick_size": 20}))
    assert big_font["0"] == unstyled["0"]
    assert big_font["1.0"] == unstyled["1.0"]


def test_authored_tick_geometry_moves_raster_labels_off_the_spine(monkeypatch) -> None:
    """Authored geometry takes matplotlib's rule in the raster path too, and
    lands on the same coordinates the SVG exporter uses."""
    styled = _text_commands(
        monkeypatch, _tick_geometry_chart(style={"tick_length": 6, "tick_padding": 5})
    )
    # 6 px outward tick + 5 px pad = 11 px, then 0.8 * the 11 px font to the baseline.
    assert styled["0"] == (50.0, 279.8)
    # y: 11 px outside the spine, baseline centered on 0.35 * the font size.
    assert styled["0.0"] == (39.0, 263.85)


def mixed_anchor_legend_spec() -> tuple[dict, bytes]:
    """A figure carrying one anchored and one bounded legend box."""
    spec, blob = Figure().line([0.0, 1.0], [0.0, 1.0], name="a").build_payload()
    spec["show_legend"] = False
    spec["extra_legends"] = [
        {
            "title": "anchored",
            "loc": "lower left",
            "anchor": [0.0, 1.0],
            "items": [{"name": "outside", "kind": "line", "style": {}}],
        },
        {
            "title": "bounded",
            "loc": "upper right",
            "items": [{"name": "inside", "kind": "line", "style": {}}],
        },
    ]
    return spec, blob


def test_raster_scopes_the_legend_clip_exemption_per_legend(monkeypatch) -> None:
    """An anchored legend is exempt from the plot-rect clip that bounds static
    legends, but the exemption is that legend's alone (parity with `_svg.py`):
    one anchored box must not lift the clip off its non-anchored siblings."""
    spec, blob = mixed_anchor_legend_spec()
    _width, _height, _compact, plot = _raster.layout(spec)
    plot_rect = (plot["x"], plot["y"], plot["w"], plot["h"])

    events: list[tuple[str, object]] = []
    original_clip = _raster._Cmd.clip
    original_legend = _raster._emit_legend

    def record_clip(self, x, y, w, h):
        events.append(("clip", (float(x), float(y), float(w), float(h))))
        return original_clip(self, x, y, w, h)

    def record_legend(cmd, named, legend_plot, options, *args, **kwargs):
        # Signature-agnostic on purpose: this stub only records the emission
        # order, so a new writer argument must not turn into a test failure.
        events.append(("legend", options.get("title")))
        return original_legend(cmd, named, legend_plot, options, *args, **kwargs)

    monkeypatch.setattr(_raster._Cmd, "clip", record_clip)
    monkeypatch.setattr(_raster, "_emit_legend", record_legend)
    _raster.render_raster(spec, blob, scale=1)

    # The clip is stateful in the command stream, so the rectangle in force for
    # a legend is the last clip recorded before that legend's emission.
    in_force: dict[str, tuple[float, ...]] = {}
    current: tuple[float, ...] | None = None
    for kind, value in events:
        if kind == "clip":
            assert isinstance(value, tuple)
            current = value
        else:
            assert isinstance(value, str)
            assert current is not None, "legend emitted before any clip was set"
            in_force[value] = current

    assert set(in_force) == {"anchored", "bounded"}
    assert in_force["bounded"] == plot_rect
    assert in_force["anchored"] != plot_rect  # the full-frame chrome clip


def test_raster_uniform_anchor_legends_keep_their_whole_frame_clip_decision(
    monkeypatch,
) -> None:
    """The per-legend scoping must not change the all-anchored or the
    none-anchored figure: one keeps no plot-rect clip, the other keeps one."""
    original_clip = _raster._Cmd.clip

    def plot_clips(anchors: list[list[float] | None]) -> int:
        spec, blob = mixed_anchor_legend_spec()
        for extra, anchor in zip(spec["extra_legends"], anchors, strict=True):
            if anchor is None:
                extra.pop("anchor", None)
            else:
                extra["anchor"] = anchor
        _width, _height, _compact, plot = _raster.layout(spec)
        rect = (plot["x"], plot["y"], plot["w"], plot["h"])
        seen: list[tuple[float, ...]] = []

        def record_clip(self, x, y, w, h):
            seen.append((float(x), float(y), float(w), float(h)))
            return original_clip(self, x, y, w, h)

        monkeypatch.setattr(_raster._Cmd, "clip", record_clip)
        _raster.render_raster(spec, blob, scale=1)
        monkeypatch.undo()
        # The marks pass clips to the plot rect too; the legend pass is the
        # only source of a second one.
        return seen.count(rect) - 1

    assert plot_clips([[0.0, 1.0], [0.0, 1.0]]) == 0
    assert plot_clips([None, None]) == 1


def test_the_raster_exporter_draws_annotation_labels_and_marker_glyphs() -> None:
    """The PNG path had the same gap as SVG: rule/band/arrow/marker labels were
    never emitted, and `xy.marker()` drew nothing at all."""
    import xy._raster as raster

    chart = xy.line_chart(
        xy.line([1, 2, 3, 4], [1, 3, 2, 3.4], name="signal"),
        xy.hline(y=2, text="target"),
        xy.x_band(x0=2.6, x1=3.2, text="window"),
        xy.marker(x=2, y=3, text="peak"),
        width=680,
        height=400,
    )
    spec, blob = chart.figure().build_payload()
    calls: list[tuple] = []
    original_text = raster._Cmd.text
    original_point = raster._Cmd.point

    def record_text(self, *args, **kwargs):
        calls.append(("text", args[-1] if args else None))
        return original_text(self, *args, **kwargs)

    def record_point(self, *args, **kwargs):
        calls.append(("point", None))
        return original_point(self, *args, **kwargs)

    raster._Cmd.text, raster._Cmd.point = record_text, record_point
    try:
        chart.to_png()
    finally:
        raster._Cmd.text, raster._Cmd.point = original_text, original_point

    drawn = {value for kind, value in calls if kind == "text"}
    assert {"target", "window", "peak"} <= drawn
    assert any(kind == "point" for kind, _ in calls), "marker glyph never drawn"


def test_the_raster_exporter_expands_categorical_legend_rows() -> None:
    import xy._raster as raster

    species = ["setosa"] * 4 + ["versicolor"] * 4 + ["virginica"] * 4
    chart = xy.scatter_chart(
        xy.scatter(list(range(12)), list(range(12)), color=species, name="iris"),
        xy.legend(),
        width=560,
        height=380,
    )
    drawn: list[str] = []
    original_text = raster._Cmd.text

    def record_text(self, *args, **kwargs):
        drawn.append(args[-1] if args else "")
        return original_text(self, *args, **kwargs)

    raster._Cmd.text = record_text
    try:
        chart.to_png()
    finally:
        raster._Cmd.text = original_text
    assert {"setosa", "versicolor", "virginica"} <= set(drawn)


# --- glyph coverage -----------------------------------------------------------


def _title_png(title: str) -> bytes:
    return xy.line_chart(xy.line([1, 2], [1, 2]), title=title, width=420, height=240).to_png()


@pytest.mark.parametrize(
    "char",
    ["é", "ü", "ł", "Ø", "€", "£", "¥", "₹", "α", "²", "≤"],
)
def test_the_raster_atlas_draws_latin_and_currency(char: str) -> None:
    """A character outside the atlas was dropped whole — no glyph, no advance.

    `Zürich` exported as `Zrich` from `to_png()` while the same figure's SVG
    rendered it correctly, and `format="€,.0f"` lost its symbol."""
    assert _title_png(f"X{char}") != _title_png("X"), f"{char!r} left no marks on the canvas"


@pytest.mark.parametrize("char", ["東", "🎉"])
def test_characters_outside_the_atlas_box_instead_of_vanishing(char: str) -> None:
    """CJK and emoji stay unbakeable, but the failure must be visible (§28)."""
    assert _title_png(f"X{char}") != _title_png("X"), f"{char!r} vanished silently"
    assert _title_png(f"X{char}") == _title_png("X\ufffd"), (
        "an unbaked character should render as the replacement glyph"
    )


@pytest.mark.parametrize("space", ["\u00a0", "\u202f", "\u2009"])
def test_unicode_spaces_render_as_spaces_not_boxes(space: str) -> None:
    """Locale-aware number formatting emits NBSP and narrow NBSP as group
    separators, so these reach the rasterizer through ordinary tick labels.
    Whitespace is drawn by its advance, not its shape — a replacement box
    would be plainly wrong where a space belongs."""
    assert _title_png(f"X{space}Y") == _title_png("X Y")


def test_zero_width_characters_still_draw_nothing() -> None:
    # Spelled as an escape on purpose: a literal U+200B is invisible in the
    # source, and an editor or a copy-paste that strips it would silently
    # reduce this to `_title_png("X") == _title_png("X")`.
    assert _title_png("X\u200b") == _title_png("X")


def test_chunk_parts_join_to_the_canonical_chunk():
    """Parts assembly must equal the naive `tag + data` construction.

    PNG chunks are built as join-ready parts so the compressed IDAT — the whole
    image — is copied once into the file instead of once per `+`. The CRC is
    accumulated over the tag and then the data, which is exactly
    `crc32(tag + data)` without materializing the concatenation.
    """
    import struct
    import zlib

    from xy import _png

    for tag, data in (
        (b"IHDR", b"\x00" * 13),
        (b"IEND", b""),
        (b"IDAT", bytes(range(256)) * 40),
        (b"tRNS", b"\xff\x00\x7f"),
    ):
        body = tag + data
        canonical = struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
        assert b"".join(_png._chunk_parts(tag, data)) == canonical
        assert _png._chunk(tag, data) == canonical
