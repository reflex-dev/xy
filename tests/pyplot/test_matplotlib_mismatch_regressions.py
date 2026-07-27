from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt
from xy._figure import Figure
from xy.pyplot import _axes as axes_module
from xy.pyplot._colors import _rgba_floats


def test_axis_equal_before_fill_keeps_data_autoscaling() -> None:
    _fig, ax = plt.subplots()
    ax.axis("equal")
    ax.fill([-3.0, 4.0, 1.0], [-2.0, 0.0, 5.0])

    assert "domain" not in ax._axis["x"]
    assert "domain" not in ax._axis["y"]
    assert ax._entry_extent("x") == (-3.0, 4.0)
    assert ax._entry_extent("y") == (-2.0, 5.0)
    assert ax._aspect_bounds == pytest.approx((-3.35, 4.35, -2.35, 5.35))


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


@pytest.mark.parametrize("interpolation", ["auto", "antialiased"])
def test_imshow_adaptive_interpolation_uses_matplotlib_sampling_rules(
    monkeypatch: pytest.MonkeyPatch,
    interpolation: str,
) -> None:
    calls: list[tuple[tuple[int, ...], int, int, str]] = []

    def record_target(
        grid: np.ndarray,
        width: int,
        height: int,
        method: str,
    ) -> np.ndarray:
        calls.append((grid.shape, width, height, method))
        return grid

    monkeypatch.setattr(axes_module, "_resample_grid", record_target)

    # The 450px source in Matplotlib's image-antialiasing gallery is enlarged
    # modestly by xy's 512px intermediate. Matplotlib therefore uses Hanning
    # after color mapping (RGBA stage).
    _fig, ax = plt.subplots()
    ax.imshow(np.zeros((450, 450)), interpolation=interpolation)
    assert calls == [((450, 450, 4), 512, 512, "hanning")]

    # Exact 1x/2x and enlargement above 3x use nearest, so no Python
    # resampling occurs and the source cells stay intact.
    calls.clear()
    _fig, axes = plt.subplots(1, 3)
    one_x = axes[0].imshow(np.zeros((512, 512)), interpolation=interpolation)
    two_x = axes[1].imshow(np.zeros((256, 256)), interpolation=interpolation)
    over_three_x = axes[2].imshow(np.zeros((170, 170)), interpolation=interpolation)
    assert calls == []
    assert np.asarray(one_x._entry["z"]).shape == (512, 512)
    assert np.asarray(two_x._entry["z"]).shape == (256, 256)
    assert np.asarray(over_three_x._entry["z"]).shape == (170, 170)


def test_imshow_auto_respects_explicit_interpolation_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[int, ...], str]] = []

    def record_target(
        grid: np.ndarray,
        width: int,
        height: int,
        method: str,
    ) -> np.ndarray:
        del width, height
        calls.append((grid.shape, method))
        return grid

    monkeypatch.setattr(axes_module, "_resample_grid", record_target)
    _fig, (data_ax, rgba_ax) = plt.subplots(1, 2)
    data_ax.imshow(
        np.zeros((450, 450)),
        interpolation="auto",
        interpolation_stage="data",
    )
    rgba_ax.imshow(
        np.zeros((450, 450)),
        interpolation="auto",
        interpolation_stage="rgba",
    )

    assert calls == [
        ((450, 450), "hanning"),
        ((450, 450, 4), "hanning"),
    ]


def test_imshow_resampling_preserves_the_source_data_extent() -> None:
    _fig, ax = plt.subplots()
    image = ax.imshow(np.zeros((3, 5)), interpolation="bilinear")

    assert np.asarray(image._entry["z"]).shape == (512, 512)
    assert image.get_extent() == pytest.approx((-0.5, 4.5, -0.5, 2.5))
    assert ax._entry_extent("x") == pytest.approx((-0.5, 4.5))
    assert ax._entry_extent("y") == pytest.approx((-0.5, 2.5))
    x = np.asarray(image._entry["kwargs"]["x"])
    y = np.asarray(image._entry["kwargs"]["y"])
    assert x[[0, -1]] == pytest.approx((-0.5 + 5 / 1024, 4.5 - 5 / 1024))
    assert y[[0, -1]] == pytest.approx((-0.5 + 3 / 1024, 2.5 - 3 / 1024))


@pytest.mark.parametrize("interpolation", ["lanczos", "sinc"])
def test_rgba_stage_ringing_filters_saturate_channel_overshoot(interpolation: str) -> None:
    values = np.array(
        [
            [0.0, 0.2, 0.8, 1.0],
            [1.0, 0.8, 0.2, 0.0],
            [0.0, 0.2, 0.8, 1.0],
            [1.0, 0.8, 0.2, 0.0],
        ]
    )
    _fig, ax = plt.subplots()
    image = ax.imshow(
        values,
        cmap="viridis",
        interpolation=interpolation,
        interpolation_stage="rgba",
    )
    pixels = np.asarray(image._entry["z"])

    assert pixels.shape == (512, 512, 4)
    assert np.isfinite(pixels).all()
    assert float(pixels.min()) >= 0.0
    assert float(pixels.max()) <= 1.0
    assert np.ptp(pixels[..., :3]) > 0.5


def test_imshow_colormap_extremes_accept_css_named_colors() -> None:
    assert _rgba_floats("limegreen") == pytest.approx((50 / 255, 205 / 255, 50 / 255, 1))
    assert _rgba_floats(("limegreen", 0.25)) == pytest.approx((50 / 255, 205 / 255, 50 / 255, 0.25))

    cmap = plt.get_cmap("RdBu_r")
    cmap.set_under("yellow")
    cmap.set_over("limegreen")
    _fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-1.0, 3.0]]),
        cmap=cmap,
        vmin=0.0,
        vmax=2.0,
        interpolation="nearest",
        origin="lower",
    )
    pixels = np.asarray(image._entry["z"])

    np.testing.assert_allclose(pixels[0, 0], (1.0, 1.0, 0.0, 1.0))
    np.testing.assert_allclose(pixels[0, 1], (50 / 255, 205 / 255, 50 / 255, 1.0))


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


def test_sparse_imshow_resampling_matches_dense_bilinear_reference() -> None:
    values = np.arange(12.0).reshape(3, 4)

    def dense_weights(source: int, target: int) -> np.ndarray:
        positions = np.linspace(0.0, source - 1.0, target)[:, None]
        distance = np.abs(positions - np.arange(source, dtype=np.float64)[None, :])
        weights = np.maximum(0.0, 1.0 - distance)
        return weights / weights.sum(axis=1, keepdims=True)

    wy = dense_weights(values.shape[0], 5)
    wx = dense_weights(values.shape[1], 7)
    expected = wy @ values @ wx.T

    np.testing.assert_allclose(
        axes_module._resample_grid(values, 7, 5, "bilinear"),
        expected,
        atol=1e-12,
    )


def test_sparse_imshow_resampling_matches_dense_lanczos_with_nan() -> None:
    values = np.arange(20.0).reshape(4, 5)
    values[1, 2] = np.nan

    def dense_weights(source: int, target: int) -> np.ndarray:
        positions = np.linspace(0.0, source - 1.0, target)[:, None]
        distance = positions - np.arange(source, dtype=np.float64)[None, :]
        absolute = np.abs(distance)
        weights = np.where(
            absolute < 3.0,
            np.sinc(distance) * np.sinc(distance / 3.0),
            0.0,
        )
        return weights / weights.sum(axis=1, keepdims=True)

    wy = dense_weights(values.shape[0], 7)
    wx = dense_weights(values.shape[1], 9)
    finite = np.isfinite(values)
    numerator = wy @ np.where(finite, values, 0.0) @ wx.T
    denominator = wy @ finite.astype(np.float64) @ wx.T
    expected = np.divide(
        numerator,
        denominator,
        out=np.full_like(numerator, np.nan),
        where=np.abs(denominator) > 1e-12,
    )

    np.testing.assert_allclose(
        axes_module._resample_grid(values, 9, 7, "lanczos"),
        expected,
        atol=1e-12,
        equal_nan=True,
    )


def test_sparse_imshow_kaiser_matches_matplotlib_agg_kernel() -> None:
    values = np.arange(12.0).reshape(3, 4)

    def dense_weights(source: int, target: int) -> np.ndarray:
        positions = np.linspace(0.0, source - 1.0, target)[:, None]
        distance = np.abs(positions - np.arange(source, dtype=np.float64)[None, :])
        beta = 6.33
        weights = np.where(
            distance < 1.0,
            np.i0(beta * np.sqrt(np.maximum(0.0, 1.0 - distance**2))) / np.i0(beta),
            0.0,
        )
        return weights / weights.sum(axis=1, keepdims=True)

    wy = dense_weights(values.shape[0], 7)
    wx = dense_weights(values.shape[1], 9)
    expected = wy @ values @ wx.T

    np.testing.assert_allclose(
        axes_module._resample_grid(values, 9, 7, "kaiser"),
        expected,
        atol=1e-12,
    )


def test_imshow_bounds_large_non_nearest_resampling(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[tuple[int, int]] = []

    def record_target(grid: np.ndarray, width: int, height: int, method: str) -> np.ndarray:
        del method
        requested.append((width, height))
        return grid

    monkeypatch.setattr(axes_module, "_resample_grid", record_target)
    _fig, ax = plt.subplots()
    ax.imshow(np.zeros((1025, 1537)), interpolation="bilinear")

    assert requested == [(1024, 1024)]


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
