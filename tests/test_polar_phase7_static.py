"""Focused static-export coverage for phase-7 polar geometry."""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

import xy
from xy import _raster, _svg
from xy._svg import (
    _annotation_connector_unclipped,
    _PolarProjection,
    _Scale,
    _segment_marks,
    _tick_text,
    axis_ticks,
    layout,
    polar_heatmap_rgba,
)

PLOT = {"x": 0.0, "y": 0.0, "w": 200.0, "h": 200.0}


def test_log_radius_and_hole_are_mapped_in_scale_coordinates() -> None:
    polar = _PolarProjection(
        {},
        {"range": [1.0, 100.0], "scale": "log", "hole": 0.2},
        PLOT,
    )
    assert float(polar.norm_radius(1.0)) == pytest.approx(0.2)
    assert float(polar.norm_radius(10.0)) == pytest.approx(0.6)
    assert float(polar.norm_radius(100.0)) == pytest.approx(1.0)
    assert float(polar.radius_value(0.6)) == pytest.approx(10.0)


def test_radial_origin_below_the_view_creates_an_annulus() -> None:
    polar = _PolarProjection(
        {},
        {"range": [2.0, 10.0], "r_origin": 0.0},
        PLOT,
    )
    assert polar.inner_fraction == pytest.approx(0.2)
    assert float(polar.norm_radius(10.0)) == pytest.approx(1.0)
    assert not bool(polar.visible_mask(1.99))
    assert bool(polar.visible_mask(2.0))


def test_reversed_radial_origin_maps_static_geometry_inward_to_outward() -> None:
    polar = _PolarProjection(
        {},
        {"range": [10.0, 2.0], "r_origin": 12.0},
        PLOT,
    )
    assert polar.inner_fraction == pytest.approx(0.2)
    assert np.asarray(polar.norm_radius([10.0, 6.0, 2.0])).tolist() == pytest.approx(
        [0.2, 0.6, 1.0]
    )
    assert float(polar.radius_value(0.6)) == pytest.approx(6.0)

    figure = xy.polar_chart(
        xy.area(
            [0.0, math.pi / 2.0, math.pi],
            [8.0, 6.0, 4.0],
            base=[10.0, 10.0, 10.0],
            color="#ff0000",
            opacity=1.0,
            line_width=0.0,
        ),
        xy.r_axis(domain=(2.0, 10.0), reverse=True, origin=12.0),
        width=240,
        height=220,
    ).figure()
    svg = figure.to_image(format="svg")
    assert b'fill="#ff0000"' in svg
    spec, blob, borrowed = figure._build_raster_payload()
    pixels = _raster.render_raster(spec, blob, scale=1.0, borrowed=borrowed)
    red = (pixels[:, :, 0] > 200) & (pixels[:, :, 1] < 80) & (pixels[:, :, 2] < 80)
    assert int(red.sum()) > 100


def test_near_one_hole_is_an_empty_native_clip_not_a_rejected_stream() -> None:
    figure = xy.polar_chart(
        xy.scatter([0.0], [1.0], color="#ff0000"),
        xy.r_axis(domain=(0.0, 1.0), hole=1.0 - 1e-12),
        width=200,
        height=200,
    ).figure()
    assert figure.to_image(format="svg").startswith(b"<svg")
    assert figure.to_image(format="png", scale=1).startswith(b"\x89PNG\r\n\x1a\n")


def test_categorical_theta_uses_distinct_full_and_partial_sector_spacing() -> None:
    categories = ["N", "E", "S", "W"]
    full = _PolarProjection(
        {"kind": "category", "categories": categories},
        {"range": [0.0, 1.0]},
        PLOT,
    )
    assert np.asarray(full.angle([0, 1, 2, 3])).tolist() == pytest.approx(
        [0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0]
    )

    partial = _PolarProjection(
        {
            "kind": "category",
            "categories": categories,
            "sector": [0.0, math.pi],
        },
        {"range": [0.0, 1.0]},
        PLOT,
    )
    assert np.asarray(partial.angle([0, 1, 2, 3])).tolist() == pytest.approx(
        [0.0, math.pi / 3.0, 2.0 * math.pi / 3.0, math.pi]
    )


def test_partial_sector_uses_its_bounding_box_and_sector_tick_domain() -> None:
    polar = _PolarProjection(
        {"sector": [0.0, math.pi]},
        {"range": [0.0, 1.0]},
        {"x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0},
    )
    # A semicircle is 2R by R, so it fills this 2:1 rectangle at R=100.
    assert polar.radius == pytest.approx(100.0, abs=1e-6)

    axis = {
        "kind": "linear",
        "range": [0.0, 2.0 * math.pi],
        "sector": [math.pi / 2.0, math.pi],
        "theta_unit": "radians",
        "tick_values": [0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0],
    }
    ticks, labels, _step = axis_ticks(axis, 200.0, True)
    assert ticks == labels == pytest.approx([math.pi / 2.0, math.pi])


def test_category_labels_take_precedence_over_angular_formatting() -> None:
    categories = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    axis = {
        "kind": "category",
        "range": [0.0, 7.0],
        "categories": categories,
        "theta_unit": "radians",
        "sector": [0.0, 2.0 * math.pi],
    }
    # A 300 px Cartesian category axis would normally thin eight labels to
    # four. Categorical theta keeps all eight because each tick is also one
    # spoke and one polygon-grid vertex.
    ticks, labels, step = axis_ticks(axis, 300.0, True)
    assert ticks == labels == list(np.arange(8.0))
    assert [_tick_text(axis, value, step) for value in labels] == categories


def test_svg_uses_annular_sector_clip_polygon_grid_and_polar_heatmap() -> None:
    chart = xy.polar_chart(
        xy.heatmap(
            np.arange(12.0).reshape(3, 4),
            x=np.linspace(0.0, math.pi, 4),
            y=[1.0, 2.0, 3.0],
        ),
        xy.theta_axis(sector=(0.0, math.pi), grid_shape="linear"),
        xy.r_axis(domain=(0.0, 3.0), hole=0.25),
        width=360,
        height=280,
    )
    document = chart.figure().to_image(format="svg").decode()
    assert 'data-xy-polar-heatmap="true"' in document
    assert re.search(r"<clipPath[^>]*><path ", document)
    assert '<polyline data-xy-grid="ring"' in document
    assert '<path data-xy-frame="polar"' in document


def test_shared_heatmap_raster_masks_the_hole_and_missing_sector() -> None:
    values = np.asarray([0.0, 0.33, 0.66, 1.0], dtype=np.float32)
    hm = {
        "w": 2,
        "h": 2,
        "buf": 0,
        "x_range": [0.0, math.pi],
        "y_range": [0.0, 2.0],
        "colormap": "viridis",
    }
    cols = [{"dtype": "f32", "len": 4, "byte_offset": 0, "scale": 1.0, "offset": 0.0}]
    polar = _PolarProjection(
        {"sector": [0.0, math.pi]},
        {"range": [0.0, 2.0], "hole": 0.4},
        PLOT,
    )
    rgba = polar_heatmap_rgba(hm, values.tobytes(), cols, {}, polar)
    cx = int(round(polar.cx - polar.plot["x"]))
    cy = min(rgba.shape[0] - 1, int(round(polar.cy - polar.plot["y"])))
    assert rgba[cy, cx, 3] == 0  # display-space hole
    px, py = polar(math.pi / 2.0, 1.0)
    ix = min(rgba.shape[1] - 1, max(0, int(float(px) - polar.plot["x"])))
    iy = min(rgba.shape[0] - 1, max(0, int(float(py) - polar.plot["y"])))
    assert rgba[iy, ix, 3] > 0
    # The lower half of the plot is outside the authored 0..pi sector.
    assert rgba[-1, rgba.shape[1] // 2, 3] == 0


def test_polar_heatmap_samples_canonical_source_and_native_device_scale(monkeypatch) -> None:
    source_w, source_h = 400, 300
    values = np.linspace(-2.0, 6.0, source_w * source_h, dtype=np.float64)
    values[17] = np.nan
    hm = {
        "w": source_w,
        "h": source_h,
        "buf": 0,
        "enc": "canonical-f64",
        "domain": [-1.0, 5.0],
        "x_range": [0.0, 2.0 * math.pi],
        "y_range": [0.0, 1.0],
        "colormap": "viridis",
    }
    canonical_cols = [{"span": 1, "len": values.size, "dtype": "f64"}]
    polar = _PolarProjection(
        {},
        {"range": [0.0, 1.0]},
        {"x": 0.0, "y": 0.0, "w": 24.0, "h": 18.0},
    )
    sample_sizes: list[int] = []
    original_sample = _svg._heatmap_sample_column

    def record_sample(meta, indices, blob, borrowed):
        sample_sizes.append(len(indices))
        return original_sample(meta, indices, blob, borrowed)

    monkeypatch.setattr(_svg, "_heatmap_sample_column", record_sample)
    monkeypatch.setattr(
        _svg,
        "_heatmap_rgba_grid",
        lambda *_args, **_kwargs: pytest.fail("polar heatmap expanded the full source grid"),
    )
    canonical = polar_heatmap_rgba(
        hm,
        b"",
        canonical_cols,
        {},
        polar,
        (values,),
        output_scale=2.0,
    )
    assert canonical.shape == (36, 48, 4)
    assert sample_sizes and max(sample_sizes) <= 36 * 48
    assert max(sample_sizes) < values.size

    normalized = np.clip((values - hm["domain"][0]) / 6.0, 0.0, 1.0).astype("<f4")
    expanded_hm = {key: value for key, value in hm.items() if key not in {"enc", "domain"}}
    expanded_cols = [
        {
            "dtype": "f32",
            "len": normalized.size,
            "byte_offset": 0,
            "scale": 1.0,
            "offset": 0.0,
        }
    ]
    expanded = polar_heatmap_rgba(
        expanded_hm,
        normalized.tobytes(),
        expanded_cols,
        {},
        polar,
        output_scale=2.0,
    )
    np.testing.assert_array_equal(canonical, expanded)


def test_polar_heatmap_samples_borrowed_rgba_without_source_expansion(monkeypatch) -> None:
    source_w, source_h = 300, 200
    size = source_w * source_h
    channels = tuple(np.full(size, value, dtype=np.float32) for value in (0.25, 0.5, 0.75, 1.0))
    hm = {
        "w": source_w,
        "h": source_h,
        "rgba_bufs": [0, 1, 2, 3],
        "x_range": [0.0, 2.0 * math.pi],
        "y_range": [0.0, 1.0],
    }
    cols = [{"span": index + 1, "len": size, "dtype": "f32"} for index in range(len(channels))]
    polar = _PolarProjection(
        {},
        {"range": [0.0, 1.0]},
        {"x": 0.0, "y": 0.0, "w": 20.0, "h": 16.0},
    )
    sample_sizes: list[int] = []
    original_sample = _svg._heatmap_sample_column

    def record_sample(meta, indices, blob, borrowed):
        sample_sizes.append(len(indices))
        return original_sample(meta, indices, blob, borrowed)

    monkeypatch.setattr(_svg, "_heatmap_sample_column", record_sample)
    rgba = polar_heatmap_rgba(hm, b"", cols, {"opacity": 0.5}, polar, channels)
    visible = rgba[rgba[:, :, 3] > 0]
    assert len(visible)
    np.testing.assert_array_equal(
        visible,
        np.broadcast_to(np.asarray([63, 127, 191, 127], dtype=np.uint8), visible.shape),
    )
    assert sample_sizes and max(sample_sizes) <= rgba.shape[0] * rgba.shape[1]
    assert max(sample_sizes) < size


def test_borrowed_heatmap_dtype_mismatch_casts_only_sampled_cells(monkeypatch) -> None:
    cast_sizes: list[int] = []

    class GuardedArray(np.ndarray):
        def astype(self, *args, **kwargs):
            cast_sizes.append(self.size)
            if self.size == source.size:
                raise AssertionError("full borrowed source was cast before sampling")
            return super().astype(*args, **kwargs)

    source = np.arange(10_000, dtype=np.float32).view(GuardedArray)
    real_asarray = np.asarray

    def guarded_asarray(value, *args, **kwargs):
        if value is source:
            assert not args and kwargs.get("dtype") is None
            return source
        return real_asarray(value, *args, **kwargs)

    monkeypatch.setattr(_svg.np, "asarray", guarded_asarray)
    sampled = _svg._heatmap_sample_column(
        {"span": 1, "len": source.size, "dtype": "f64"},
        np.asarray([1, 500, 9_999], dtype=np.int64),
        b"",
        (source,),
    )
    np.testing.assert_array_equal(sampled, [1.0, 500.0, 9_999.0])
    assert cast_sizes and set(cast_sizes) == {3}


def test_raster_polar_heatmap_forwards_device_scale(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_heatmap(*_args, output_scale, **_kwargs):
        seen["scale"] = output_scale
        return np.zeros((5, 7, 4), dtype=np.uint8)

    class RecordingCmd:
        s = 2.5

        def image(self, *args, **kwargs):
            seen["image"] = (args, kwargs)

    monkeypatch.setattr(_raster, "polar_heatmap_rgba", fake_heatmap)
    polar = _PolarProjection({}, {"range": [0.0, 1.0]}, PLOT)
    _raster._emit_grid(
        RecordingCmd(),
        "heatmap",
        {"w": 1, "h": 1},
        b"",
        [],
        _Scale({"range": [0.0, 1.0]}, 0.0, 1.0),
        _Scale({"range": [0.0, 1.0]}, 0.0, 1.0),
        {},
        polar=polar,
    )
    assert seen["scale"] == 2.5
    image_args, image_kwargs = seen["image"]
    assert image_args[4:6] == (7, 5)
    assert image_kwargs == {"nearest": True}


def test_segment_projection_clips_both_endpoints_jointly() -> None:
    arrays = [
        np.asarray([0.0], dtype=np.float32),
        np.asarray([math.pi / 2.0], dtype=np.float32),
        np.asarray([-1.0], dtype=np.float32),
        np.asarray([3.0], dtype=np.float32),
    ]
    blob = b"".join(value.tobytes() for value in arrays)
    cols = [
        {"dtype": "f32", "len": 1, "byte_offset": index * 4, "scale": 1.0, "offset": 0.0}
        for index in range(4)
    ]
    trace = {"x0": 0, "x1": 1, "y0": 2, "y1": 3}
    axis = {"range": [0.0, 2.0]}
    scale = _Scale(axis, 0.0, 100.0)
    polar = _PolarProjection({}, axis, PLOT)
    markup = _segment_marks(trace, blob, cols, scale, scale, {}, "#123456", polar)

    # Radial intersections are t=.25 and t=.75, so theta is interpolated to
    # pi/8 and 3pi/8 instead of retaining/clamping the original angles.
    want_x0, want_y0 = polar(math.pi / 8.0, 0.0)
    want_x1, want_y1 = polar(3.0 * math.pi / 8.0, 2.0)
    match = re.search(
        r'x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"',
        markup,
    )
    assert match is not None
    assert [float(value) for value in match.groups()] == pytest.approx(
        [float(want_x0), float(want_y0), float(want_x1), float(want_y1)],
        abs=1e-2,
    )


def test_native_point_annotations_use_joint_polar_projection() -> None:
    class RecordingCmd:
        def __init__(self) -> None:
            self.points: list[tuple[float, float]] = []
            self.strokes: list[list[tuple[float, float]]] = []

        def point(self, x, y, *_args, **_kwargs):
            self.points.append((x, y))

        def stroke(self, points, *_args, **_kwargs):
            self.strokes.append(list(points))

        def fill(self, *_args, **_kwargs):
            pass

        def clip(self, *_args, **_kwargs):
            pass

        def polar_clip(self, *_args, **_kwargs):
            pass

    theta_axis = {"range": [0.0, 2.0 * math.pi], "sector": [0.0, math.pi]}
    r_axis = {"range": [0.0, 1.0], "hole": 0.25}
    polar = _PolarProjection(theta_axis, r_axis, PLOT)
    sx = _Scale(theta_axis, 0.0, 200.0)
    sy = _Scale(r_axis, 200.0, 0.0)
    cmd = RecordingCmd()
    annotations = [
        {"kind": "marker", "x": math.pi / 2.0, "y": 0.75, "size": 8.0},
        {
            "kind": "arrow",
            "x0": 0.0,
            "y0": 0.5,
            "x1": math.pi / 2.0,
            "y1": 0.75,
            "style": {"head_style": "none"},
        },
    ]
    _raster._emit_annotations(cmd, annotations, sx, sy, PLOT, 200.0, 200.0, polar=polar)

    marker = tuple(float(value) for value in polar(math.pi / 2.0, 0.75))
    assert cmd.points == [pytest.approx(marker)]
    arrow_start = tuple(float(value) for value in polar(0.0, 0.5))
    arrow_end = tuple(float(value) for value in polar(math.pi / 2.0, 0.75))
    assert cmd.strokes[0][0] == pytest.approx(arrow_start)
    assert cmd.strokes[0][-1] == pytest.approx(arrow_end)
    assert _annotation_connector_unclipped(annotations[1], sx, sy, PLOT, polar)
    outside = {**annotations[1], "x1": 3.0 * math.pi / 2.0}
    assert not _annotation_connector_unclipped(outside, sx, sy, PLOT, polar)


def test_native_polar_clip_masks_area_hole_and_line_across_missing_sector() -> None:
    theta0, theta1 = math.pi / 4.0, 7.0 * math.pi / 4.0
    figure = xy.polar_chart(
        xy.area(
            [theta0, math.pi, theta1],
            [0.9, 0.9, 0.9],
            base=[0.0, 0.0, 0.0],
            color="#ff0000",
            opacity=1.0,
        ),
        xy.line([theta0, theta1], [0.9, 0.9], color="#ff0000", width=8.0),
        xy.theta_axis(sector=(theta0, theta1)),
        xy.r_axis(domain=(0.0, 1.0), hole=0.35),
        width=260,
        height=220,
    ).figure()
    spec, blob, borrowed = figure._build_raster_payload()
    pixels = _raster.render_raster(spec, blob, scale=1.0, borrowed=borrowed)
    _width, _height, _compact, plot = layout(spec)
    polar = _PolarProjection(spec["x_axis"], spec["y_axis"], plot)

    def red_near(x: float, y: float) -> bool:
        ix, iy = int(round(x)), int(round(y))
        window = pixels[max(0, iy - 2) : iy + 3, max(0, ix - 2) : ix + 3, :3].astype(int)
        return bool(((window[:, :, 0] > 200) & (window[:, :, 1] < 80)).any())

    assert not red_near(polar.cx, polar.cy), "area fill painted through the authored hole"
    endpoint0 = np.asarray(polar(theta0, 0.9), dtype=np.float64)
    endpoint1 = np.asarray(polar(theta1, 0.9), dtype=np.float64)
    midpoint = (endpoint0 + endpoint1) / 2.0
    assert not red_near(*midpoint), "line chord painted through the missing sector"


@pytest.mark.parametrize("kind", ["heatmap", "contour", "errorbar"])
def test_phase7_marks_complete_both_static_exports(kind: str) -> None:
    theta = np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False)
    radial = np.linspace(0.5, 2.5, 4)
    values = np.sin(theta[None, :]) + radial[:, None]
    if kind == "heatmap":
        mark = xy.heatmap(values, x=theta, y=radial)
    elif kind == "contour":
        mark = xy.contour(values, x=theta, y=radial, levels=4)
    else:
        mark = xy.errorbar(theta[:4], radial, yerr=0.35)
    figure = xy.polar_chart(mark, width=300, height=300).figure()
    assert figure.to_image(format="svg").startswith(b"<svg")
    assert figure.to_image(format="png", scale=1).startswith(b"\x89PNG\r\n\x1a\n")
