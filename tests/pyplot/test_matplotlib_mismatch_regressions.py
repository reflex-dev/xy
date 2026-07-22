from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy._figure import Figure


def test_axis_equal_before_fill_keeps_data_autoscaling() -> None:
    _fig, ax = plt.subplots()
    ax.axis("equal")
    ax.fill([-3.0, 4.0, 1.0], [-2.0, 0.0, 5.0])

    assert "domain" not in ax._axis["x"]
    assert "domain" not in ax._axis["y"]
    assert ax._entry_extent("x") == (-3.0, 4.0)
    assert ax._entry_extent("y") == (-2.0, 5.0)
    assert ax._aspect_bounds == pytest.approx((-3.0, 4.0, -2.0, 5.0))


def test_barh_error_components_stay_on_the_requested_axes() -> None:
    _fig, ax = plt.subplots()
    ax.barh([0.0, 1.0], [3.0, 4.0], xerr=[0.2, 0.3], yerr=[0.4, 0.5])

    errorbar = next(entry for entry in ax._entries if entry.get("factory") == "errorbar")
    np.testing.assert_allclose(errorbar["kwargs"]["xerr"], [0.2, 0.3])
    np.testing.assert_allclose(errorbar["kwargs"]["yerr"], [0.4, 0.5])


def test_direct_bar_and_mesh_strokes_match_each_face_without_extra_color_data() -> None:
    rgba = np.array([[1.0, 0.0, 0.0, 0.4], [0.0, 0.0, 1.0, 0.8]])
    bars = Figure().bar([0.0, 1.0], [2.0, 3.0], color=rgba, stroke_width=[1.0, 2.0])
    bar_spec = bars.build_payload()[0]["traces"][0]
    assert bar_spec["stroke"] == {"mode": "match_fill"}
    bar_svg = bars.to_svg()
    assert 'stroke="rgb(255,0,0)"' in bar_svg
    assert 'stroke="rgb(0,0,255)"' in bar_svg

    mesh = Figure().triangle_mesh(
        [0.0, 2.0],
        [0.0, 0.0],
        [1.0, 3.0],
        [0.0, 0.0],
        [0.0, 2.0],
        [1.0, 1.0],
        color=rgba,
        stroke_width=[1.0, 2.0],
    )
    mesh_spec = mesh.build_payload()[0]["traces"][0]
    assert mesh_spec["stroke"] == {"mode": "match_fill"}
    mesh_svg = mesh.to_svg()
    assert 'stroke="rgb(255,0,0)"' in mesh_svg
    assert 'stroke="rgb(0,0,255)"' in mesh_svg


def test_imshow_interpolates_truecolor_and_honors_rgba_stage() -> None:
    _fig, ax = plt.subplots()
    rgb = np.zeros((2, 2, 3), dtype=float)
    rgb[0, 0] = 1.0
    truecolor = ax.imshow(rgb, interpolation="bilinear")
    assert np.asarray(truecolor._entry["z"]).shape == (512, 512, 3)

    _fig, (data_ax, rgba_ax) = plt.subplots(1, 2)
    values = np.array([[0.0, 1.0], [1.0, 0.0]])
    data_image = data_ax.imshow(
        values, cmap="viridis", interpolation="bilinear", interpolation_stage="data"
    )
    rgba_image = rgba_ax.imshow(
        values, cmap="viridis", interpolation="bilinear", interpolation_stage="rgba"
    )
    assert np.asarray(data_image._entry["z"]).shape == (512, 512)
    assert np.asarray(rgba_image._entry["z"]).shape == (512, 512, 4)


def test_named_imshow_filters_are_not_all_bilinear_aliases() -> None:
    values = np.array([[0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 1.0, 0.0]] * 2)
    _fig, (linear_ax, lanczos_ax) = plt.subplots(1, 2)
    linear = np.asarray(linear_ax.imshow(values, interpolation="bilinear")._entry["z"])
    lanczos = np.asarray(lanczos_ax.imshow(values, interpolation="lanczos")._entry["z"])
    assert not np.allclose(linear, lanczos)


def test_imshow_interpolation_does_not_spread_one_nan_over_the_image() -> None:
    values = np.arange(9.0).reshape(3, 3)
    values[0, 0] = np.nan
    _fig, ax = plt.subplots()
    interpolated = np.asarray(ax.imshow(values, interpolation="bilinear")._entry["z"])
    assert np.isfinite(interpolated).any()
    assert np.isfinite(interpolated[-1, -1])


def test_regular_gouraud_pcolormesh_uses_a_smooth_scalar_surface() -> None:
    _fig, ax = plt.subplots()
    values = np.arange(15.0).reshape(3, 5)
    artist = ax.pcolormesh(
        np.arange(5.0),
        np.arange(3.0),
        values,
        shading="gouraud",
        vmin=0.0,
        vmax=14.0,
    )
    assert artist._entry["factory"] == "heatmap"
    smooth = np.asarray(artist._entry["args"][0])
    assert smooth.shape == (256, 256)
    assert np.unique(smooth).size > values.size

    with pytest.raises(ValueError, match="matching shapes"):
        ax.pcolormesh(np.arange(6.0), np.arange(4.0), values, shading="gouraud")
