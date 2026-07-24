"""Regression tests for the colorbar/colormap visual-parity fixes.

Each mirrors a defect confirmed by pixel comparison against Matplotlib 3.11
(PDSH ch.4 histograms/colorbars/contour notebooks): count-mappable colorbar
domains, nice colorbar ticks, opaque zero-count heatmap cells, reversed +
clamped imshow colormaps, discrete (resampled) colormaps, and the contour
auto-level count / dashed-negative / filled-band conventions.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def _svg():
    buffer = io.BytesIO()
    plt.savefig(buffer, format="svg")
    return buffer.getvalue().decode()


def _png():
    buffer = io.BytesIO()
    plt.savefig(buffer, format="png")
    data = buffer.getvalue()
    assert data[:4] == b"\x89PNG"
    return data


def _compiled_traces():
    ax = plt.gca()
    ax._chart = None
    return ax._build_chart(800, 600).figure().traces


def _blob(name: str) -> np.ndarray:
    """Compiled colorbar options for the current axes (after build)."""
    ax = plt.gca()
    ax._chart = None
    figure = ax._build_chart(800, 600).figure()
    return getattr(figure, name)


# -- defect 1/4: count-mappable colorbar domains ------------------------------


def test_hist2d_colorbar_domain_reflects_counts_not_unit_interval():
    np.random.seed(3)
    x, y = np.random.randn(2000), np.random.randn(2000)
    h, _xe, _ye, _im = plt.hist2d(x, y, bins=20)
    plt.colorbar()
    lo, hi = plt.gca()._colorbar["domain"]
    assert lo == 0.0
    assert hi == pytest.approx(float(h.max()))
    assert hi > 1.0  # regression: used to clamp to the 0..1 placeholder


def test_vertical_colorbar_label_does_not_expand_notebook_scroll_width():
    fig, _ax = plt.subplots()
    plt.hist2d(*np.random.default_rng(0).normal(size=(2, 200)), bins=10)
    colorbar = plt.colorbar()
    colorbar.set_label("counts in bin")

    html = fig._repr_html_()
    assert "top:50%;writing-mode:vertical-rl" in html
    assert "top:50%;transform:translateY(-50%) rotate(-90deg)" not in html
    assert "&quot;width&quot;:558" in html


def test_hexbin_colorbar_domain_autoscales_to_counts_at_build():
    np.random.seed(4)
    x, y = np.random.randn(3000), np.random.randn(3000)
    plt.hexbin(x, y, gridsize=20)
    plt.colorbar()
    # colorbar() cannot know binned counts yet, so it defers via _autoscale.
    assert plt.gca()._colorbar.get("_autoscale") is True
    options = _blob("colorbar_options")
    assert "_autoscale" not in options
    assert options["domain"][1] > 1.0


# -- defect 2: nice default colorbar ticks ------------------------------------


def test_default_colorbar_ticks_are_round_numbers():
    np.random.seed(5)
    x, y = np.random.randn(4000), np.random.randn(4000)
    plt.hist2d(x, y, bins=25)
    plt.colorbar()
    svg = _svg()
    # A count domain of ~[0, 40+] must tick on round multiples produced by the
    # nice-tick locator (0, 10, 20, ...), not the raw min/max endpoints only.
    assert ">10<" in svg
    assert ">20<" in svg


def test_default_colorbar_ticks_are_dense_for_small_decimal_domains():
    image = plt.imshow([[0.0, 0.15], [0.05, 0.1]], vmin=0.0, vmax=0.15)
    plt.colorbar(image)
    svg = _svg()
    assert all(f">{value:.2f}<" in svg for value in (0.02, 0.04, 0.06, 0.08, 0.12, 0.14))
    # A normal-height colorbar retains the dense eight-tick ceiling. Shorter
    # bars reduce their budget so labels do not collide.
    from xy._svg import _colorbar_tick_target

    assert _colorbar_tick_target(360) == 8
    assert _colorbar_tick_target(140) == 3
    # The client-side colorbar uses the same 48 px spacing budget; the embedded
    # bundle is minified, so assert against the client source instead of HTML.
    client = ROOT / "js" / "src" / "50_chartview.ts"
    assert "barLength) / 48" in client.read_text(encoding="utf-8")


def test_explicit_colorbar_ticks_still_honored():
    np.random.seed(6)
    x, y = np.random.randn(2000), np.random.randn(2000)
    plt.hist2d(x, y, bins=20)
    plt.colorbar(ticks=[0, 7, 14])
    svg = _svg()
    assert ">7<" in svg and ">14<" in svg


# -- defect 3: zero-count heatmap cells paint the colormap floor --------------


def test_zero_value_heatmap_cell_is_opaque_colormap_floor():
    from xy import kernels
    from xy._svg import _colormap_stops

    stops = np.asarray(_colormap_stops("viridis"), dtype=np.uint8)
    # value 0 -> opaque floor color; NaN (masked/missing) -> transparent.
    rgba = kernels.heatmap_rgba(np.array([[0.0, np.nan]]), 2, 1, stops, 255)
    assert rgba[0, 0, 3] == 255  # zero is painted, not a white hole
    assert tuple(rgba[0, 0, :3]) == tuple(int(v) for v in stops[0])
    assert rgba[0, 1, 3] == 0  # only genuine NaN stays transparent


# -- defect 5: imshow cmap (reversed) + clim reach the raster -----------------


def test_imshow_reversed_cmap_and_post_hoc_clim_reach_the_heatmap():
    from xy._svg import _colormap_stops

    grid = np.linspace(-3, 3, 100).reshape(10, 10)
    plt.imshow(grid, cmap="RdBu")
    plt.colorbar()
    plt.clim(-1, 1)
    entry = plt.gca()._entries[-1]
    assert entry["kwargs"]["colormap"] == "rdbu"  # true ColorBrewer table, not a coolwarm alias
    assert entry["kwargs"]["domain"] == (-1.0, 1.0)
    # The reversed lookup table must differ from the viridis fallback.
    assert _colormap_stops("coolwarm_r") == list(reversed(_colormap_stops("coolwarm")))
    _png()


# -- defect 6: discrete (resampled) colormaps ---------------------------------


def test_discrete_scatter_colormap_quantizes_into_n_bands():
    np.random.seed(7)
    x, y = np.random.randn(400), np.random.randn(400)
    plt.scatter(x, y, c=x, cmap=plt.get_cmap("viridis", 6))
    plt.colorbar()
    assert plt.gca()._colorbar["levels"] == 6
    scatter = next(t for t in _compiled_traces() if t.kind == "scatter")
    distinct = np.unique(scatter.color_ch.values)
    assert distinct.size <= 6  # quantized to <= N band representatives


def test_discrete_imshow_colormap_quantizes_and_survives_clim():
    grid = np.linspace(-3, 3, 100).reshape(10, 10)
    plt.imshow(grid, cmap=plt.get_cmap("Blues", 6))
    plt.colorbar(extend="both")
    plt.clim(-1, 1)
    assert plt.gca()._colorbar["levels"] == 6
    heatmap = next(t for t in _compiled_traces() if t.kind == "heatmap")
    finite = heatmap.grid.values[np.isfinite(heatmap.grid.values)]
    assert np.unique(finite).size <= 6


def test_discrete_colorbar_renders_solid_bands():
    np.random.seed(8)
    x, y = np.random.randn(300), np.random.randn(300)
    plt.scatter(x, y, c=y, cmap=plt.get_cmap("plasma", 4))
    plt.colorbar()
    assert _blob("colorbar_options")["levels"] == 4
    _svg()
    _png()


# -- defect 7: contour conventions --------------------------------------------


def _wiggle():
    def f(a, b):
        return np.sin(a) ** 10 + np.cos(10 + b * a) * np.cos(a)

    xg = np.linspace(0, 5, 50)
    yg = np.linspace(0, 5, 40)
    xx, yy = np.meshgrid(xg, yg)
    return xx, yy, f(xx, yy)


def test_auto_contour_level_count_matches_maxnlocator():
    xx, yy, zz = _wiggle()
    cs = plt.contour(xx, yy, zz)
    # MaxNLocator(N+1=8) over [-0.997, 1.05] -> 9 levels at 0.3 spacing.
    assert list(np.round(cs.levels, 3)) == [-1.2, -0.9, -0.6, -0.3, 0.0, 0.3, 0.6, 0.9, 1.2]


def test_monochrome_contour_dashes_negative_levels():
    xx, yy, zz = _wiggle()
    plt.contour(xx, yy, zz, colors="black")
    contours = [t for t in _compiled_traces() if t.kind == "contour"]
    assert len(contours) == 2
    dashes = sorted(str(t.style.get("dash")) for t in contours)
    assert dashes == ["None", "[7.4, 3.2]"]  # negatives dashed, non-negatives solid
    assert all(t.style["width"] == pytest.approx(2.0) for t in contours)
    assert all(t.style["opacity"] == pytest.approx(1.0) for t in contours)


def test_colormapped_contour_stays_solid():
    xx, yy, zz = _wiggle()
    plt.contour(xx, yy, zz, cmap="RdGy")
    contours = [t for t in _compiled_traces() if t.kind == "contour"]
    assert len(contours) == 1
    assert contours[0].style.get("dash") is None


def test_contourf_fills_discrete_bands_not_a_smooth_gradient():
    xx, yy, zz = _wiggle()
    contour_set = plt.contourf(xx, yy, zz, 20, cmap="RdGy")
    plt.colorbar()
    traces = _compiled_traces()
    heatmap = next(t for t in traces if t.kind == "heatmap")
    finite = heatmap.grid.values[np.isfinite(heatmap.grid.values)]
    assert heatmap.grid_shape[0] > zz.shape[0]
    assert heatmap.grid_shape[1] > zz.shape[1]
    # Piecewise-constant bands: far fewer distinct fill values than grid cells.
    assert np.unique(finite).size <= 21
    assert np.unique(finite).size < finite.size
    assert not any(t.kind == "contour" for t in traces)
    colorbar = _blob("colorbar_options")
    assert colorbar["levels"] == len(contour_set.levels) - 1
    assert colorbar["boundaries"] == pytest.approx(contour_set.levels)
    expected_ticks = contour_set.levels[1::3].copy()
    expected_ticks[np.abs(expected_ticks) < 1e-12] = 0.0
    assert colorbar["ticks"] == pytest.approx(expected_ticks)
    assert 0.0 in colorbar["ticks"]
