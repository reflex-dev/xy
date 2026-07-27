from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def teardown_function() -> None:
    plt.close("all")


@pytest.mark.parametrize(
    ("cumulative", "expected"),
    [
        (
            False,
            [
                [1 / 13, 8 / 39, 16 / 117],
                [2 / 13, 6 / 13, 16 / 39],
            ],
        ),
        (
            True,
            [
                [1 / 13, 7 / 39, 5 / 13],
                [2 / 13, 5 / 13, 1.0],
            ],
        ),
        (
            -1,
            [
                [5 / 13, 4 / 13, 8 / 39],
                [1.0, 11 / 13, 8 / 13],
            ],
        ),
    ],
)
def test_stacked_weighted_density_matches_matplotlib_311(
    cumulative: bool | int, expected: list[list[float]]
) -> None:
    datasets = [
        np.array([0.2, 0.4, 1.1, 2.1]),
        np.array([0.3, 1.2, 1.8, 2.4]),
    ]
    weights = [
        np.array([1.0, 2.0, 4.0, 8.0]),
        np.array([3.0, 5.0, 7.0, 9.0]),
    ]
    edges = np.array([0.0, 1.0, 1.5, 3.0])
    _fig, ax = plt.subplots()

    counts, returned_edges, containers = ax.hist(
        datasets,
        bins=edges,
        weights=weights,
        density=True,
        stacked=True,
        cumulative=cumulative,
    )

    np.testing.assert_array_equal(returned_edges, edges)
    np.testing.assert_allclose(counts, expected, rtol=1e-14, atol=0.0)
    np.testing.assert_allclose(containers[0].datavalues, counts[0], rtol=1e-14, atol=0.0)
    np.testing.assert_allclose(
        containers[1].datavalues, counts[1] - counts[0], rtol=1e-14, atol=0.0
    )
    if not cumulative:
        assert np.sum(counts[-1] * np.diff(edges)) == pytest.approx(1.0)


def test_uniform_multihist_keeps_a_scalar_swatch_width_for_legend() -> None:
    values = np.arange(24.0).reshape(8, 3)
    _fig, ax = plt.subplots()

    ax.hist(values, bins=4, label=["a", "b", "c"])

    assert all(np.isscalar(entry["kwargs"]["width"]) for entry in ax._entries)
    assert ax.legend() is not None


def test_hist2d_lognorm_uses_opaque_mesh_and_retains_count_domain() -> None:
    class LogNorm:
        def __init__(self) -> None:
            self.vmin: float | None = None
            self.vmax: float | None = None

        def __call__(self, values: object) -> np.ma.MaskedArray:
            source = np.ma.asarray(values, dtype=np.float64)
            positive = source.compressed()
            positive = positive[positive > 0.0]
            if self.vmin is None:
                self.vmin = float(positive.min())
            if self.vmax is None:
                self.vmax = float(positive.max())
            masked = np.ma.masked_less_equal(source, 0.0)
            if self.vmin == self.vmax:
                return np.ma.zeros(masked.shape)
            return (np.ma.log(masked) - np.log(self.vmin)) / (np.log(self.vmax) - np.log(self.vmin))

    x = np.asarray([0.1, 0.2, 0.3, 1.2, 1.3, 2.4])
    y = np.asarray([0.1, 0.2, 0.3, 1.2, 1.3, 2.4])
    _fig, ax = plt.subplots()

    counts, xedges, yedges, image = ax.hist2d(
        x,
        y,
        bins=3,
        range=((0.0, 3.0), (0.0, 3.0)),
        norm=LogNorm(),
    )

    np.testing.assert_array_equal(xedges, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_array_equal(yedges, [0.0, 1.0, 2.0, 3.0])
    np.testing.assert_array_equal(
        counts,
        [[3.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.0]],
    )
    assert image._entry["factory"] == "heatmap"
    assert image._entry["kwargs"]["opacity"] == pytest.approx(1.0)
    assert image._entry["_mpl_domain"] == (1.0, 3.0)
    assert image._entry["_mpl_norm_scale"] == "log"
    np.testing.assert_array_equal(image._entry["source_z"], counts.T)
    normalized = np.asarray(image._entry["args"][0])
    assert np.isnan(normalized[counts.T == 0.0]).all()
    assert np.isfinite(normalized[counts.T > 0.0]).all()


def test_spectral_defaults_match_matplotlib_311_detrend_none() -> None:
    values = np.arange(32.0) + 10.0
    paired = values * 2.0 + 3.0
    _fig, axes = plt.subplots(2, 2)

    pxx, psd_frequency = axes[0, 0].psd(values, NFFT=8, Fs=8, noverlap=4)
    cross, csd_frequency = axes[0, 1].csd(values, paired, NFFT=8, Fs=8, noverlap=4)
    coherence, coherence_frequency = axes[1, 0].cohere(values, paired, NFFT=8, Fs=8, noverlap=4)
    spectrum, specgram_frequency, time, _image = axes[1, 1].specgram(
        values, NFFT=8, Fs=8, noverlap=4
    )

    expected_frequency = np.arange(5.0)
    np.testing.assert_array_equal(psd_frequency, expected_frequency)
    np.testing.assert_array_equal(csd_frequency, expected_frequency)
    np.testing.assert_array_equal(coherence_frequency, expected_frequency)
    np.testing.assert_array_equal(specgram_frequency, expected_frequency)
    np.testing.assert_allclose(
        pxx,
        [
            416.64583333333326,
            295.1202610077128,
            3.262486283380658,
            0.2026258643942779,
            0.0001600718929495325,
        ],
        rtol=2e-13,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        cross,
        [
            877.9166666666665 + 0j,
            621.7620582723312 + 1.739820039209479j,
            6.85707872472207 + 0.07949547574694463j,
            0.4266093139222703 + 0.00284381010992434j,
            0.0003201437858990622 + 0j,
        ],
        rtol=2e-13,
        atol=1e-14,
    )
    np.testing.assert_allclose(
        coherence,
        [0.9997457628240807, 0.9997470977563064, 0.9997692102108691, 0.9997533865121703, 1.0],
        rtol=2e-13,
        atol=1e-15,
    )
    np.testing.assert_array_equal(time, np.arange(0.5, 4.0, 0.5))
    np.testing.assert_allclose(
        spectrum[:, 0],
        [
            106.3125,
            75.9116689989058,
            0.9529375770392008,
            0.05409991287616042,
            0.0001600718929494961,
        ],
        rtol=2e-13,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        spectrum[:, -1],
        [820.3125, 580.256249109394, 6.266636104411269, 0.3958212750155887, 0.00016007189294957457],
        rtol=2e-13,
        atol=1e-15,
    )


@pytest.mark.parametrize("method", ["psd", "csd", "cohere", "specgram"])
def test_explicit_spectral_detrending_fails_loudly(method: str) -> None:
    _fig, ax = plt.subplots()
    values = np.arange(32.0) + 10.0
    args = (values, values * 2.0 + 3.0) if method in {"csd", "cohere"} else (values,)

    with pytest.raises(TypeError, match=r"unsupported keyword.*detrend"):
        getattr(ax, method)(*args, NFFT=8, detrend="mean")
