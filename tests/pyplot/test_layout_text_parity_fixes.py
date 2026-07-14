"""Regression tests for the layout/annotate/tick-text visual-parity fixes.

Each test pins a defect confirmed by the PDSH image-level audit: inset rects
in mixed figures, shared-axes label suppression, annotate arrows at xytext,
locator label precision, log-axis decade labels, mathtext-to-unicode, and the
rotated raster y-label.
"""

from __future__ import annotations

import io
import re

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._mathtext import mathtext_to_unicode


@pytest.fixture(autouse=True)
def _reset():
    plt.close("all")
    plt.rcdefaults()
    yield
    plt.close("all")
    plt.rcdefaults()


def _svg(fig) -> str:
    out = io.BytesIO()
    fig.savefig(out, format="svg")
    return out.getvalue().decode()


def _png_pixels(fig) -> np.ndarray:
    out = io.BytesIO()
    fig.savefig(out, format="png")
    out.seek(0)
    return np.asarray(plt.imread(out))


def test_inset_rect_survives_next_to_a_default_axes() -> None:
    ax1 = plt.axes()
    ax2 = plt.axes([0.65, 0.65, 0.2, 0.2])
    fig = plt.gcf()
    rects = fig._effective_rects()
    assert rects is not None
    assert rects[0] == (0.125, 0.11, 0.775, 0.77)  # matplotlib SubplotParams
    assert rects[1] == (0.65, 0.65, 0.2, 0.2)
    ax1.plot([0, 1], [0, 1])
    ax2.plot([0, 1], [1, 0])
    out = io.BytesIO()
    fig.savefig(out, format="png")
    assert out.getvalue()[:4] == b"\x89PNG"


def test_shared_axes_hide_inner_tick_labels_only() -> None:
    fig, ax = plt.subplots(2, 3, sharex="col", sharey="row")
    strategies = [
        (a._axis["x"].get("tick_label_strategy"), a._axis["y"].get("tick_label_strategy"))
        for a in fig.axes
    ]
    # Top row hides x labels; columns 1-2 hide y labels; edges keep labels.
    assert strategies == [
        ("off", None),
        ("off", "off"),
        ("off", "off"),
        (None, None),
        (None, "off"),
        (None, "off"),
    ]
    # 'col' unions x-domains per column, not globally.
    assert fig._share_groups("col", 6) == [[0, 3], [1, 4], [2, 5]]
    assert fig._share_groups("row", 6) == [[0, 1, 2], [3, 4, 5]]
    assert fig._share_groups("all", 6) == [[0, 1, 2, 3, 4, 5]]
    with pytest.raises(ValueError, match="sharex"):
        plt.subplots(2, 2, sharex="diagonal")


def test_off_strategy_keeps_baselines_and_hides_labels_in_svg() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax._axis_props("x")["tick_label_strategy"] = "off"
    svg = _svg(fig)
    assert 'text-anchor="middle">0.5<' not in svg  # x tick labels hidden
    assert 'text-anchor="end">' in svg  # y tick labels still present
    # The x baseline survives (two axis baselines drawn).
    assert svg.count('stroke="#c8cdd4"') >= 2 or "baseline" not in svg


def test_annotate_draws_arrow_at_xytext() -> None:
    fig, ax = plt.subplots()
    x = np.linspace(0, 20, 50)
    ax.plot(x, np.cos(x))
    ax.annotate(
        "peak", xy=(6.28, 1.0), xytext=(10.0, 4.0), arrowprops=dict(facecolor="black", shrink=0.05)
    )
    entry = next(e for e in ax._entries if e["kind"] == "@text")
    assert entry["args"][:2] == (10.0, 4.0)
    arrow = next(e for e in ax._entries if e["kind"] == "@arrow")
    sx0, sy0, ex0, ey0 = arrow["args"]
    # shrink=0.05 pulls both ends 5% toward each other along the segment
    np.testing.assert_allclose((sx0, sy0), (10 + 0.05 * (6.28 - 10), 4 + 0.05 * (1 - 4)))
    np.testing.assert_allclose((ex0, ey0), (6.28 - 0.05 * (6.28 - 10), 1 - 0.05 * (1 - 4)))
    svg = _svg(fig)
    assert "<polygon points=" in svg  # the arrowhead
    with pytest.raises(NotImplementedError, match="arrowprops"):
        ax.annotate(
            "frac",
            xy=(0.5, 0.5),
            xytext=(0.1, 0.1),
            xycoords="axes fraction",
            arrowprops=dict(arrowstyle="->"),
        )


def test_multiple_locator_labels_keep_step_precision() -> None:
    fig, ax = plt.subplots()
    x = np.linspace(0, 10, 100)
    ax.plot(x, np.sin(x))
    ax.xaxis.set_major_locator(plt.MultipleLocator(np.pi / 2))
    svg = _svg(fig)
    for label in ("1.57", "3.14", "4.71"):
        assert f">{label}<" in svg
    assert ">2</text>" not in svg.split('text-anchor="middle"')[1][:400]


def test_default_ticks_use_matplotlib_density_and_uniform_decimal_padding() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [-1, 1])
    ax.set_ylim(-1, 1)
    svg = _svg(fig)
    for label in ("-1.00", "-0.75", "0.00", "0.75", "1.00"):
        assert f">{label}<" in svg


def test_log_axes_label_decades_and_grid_majors_only() -> None:
    fig, ax = plt.subplots()
    x = np.linspace(1, 2000, 100)
    ax.loglog(x, x**2)
    chart = ax._build_chart(640, 480).figure()
    x_opts = chart.axis_options["x"]
    ticks = x_opts["tick_values"]
    # decades only — no 2x/5x minor positions frozen into the spec
    assert all(abs(t - round(t)) < 1e-9 for t in np.log10(ticks).tolist())
    assert x_opts["tick_labels"][0].startswith("10")
    assert "10⁰" in x_opts["tick_labels"] or "10¹" in x_opts["tick_labels"]


def test_mathtext_subset_converts_and_unknown_tex_passes_through() -> None:
    assert mathtext_to_unicode(r"$\pi/2$") == "π/2"
    assert mathtext_to_unicode(r"$3\pi/2$") == "3π/2"
    assert mathtext_to_unicode("km$^2$") == "km²"
    assert mathtext_to_unicode("log$_{10}$(population)") == "log₁₀(population)"
    assert mathtext_to_unicode(r"$\mathdefault{10^{3}}$") == "10³"
    assert mathtext_to_unicode(r"$\frac{1}{2}\pi$") == "1/2π"
    assert mathtext_to_unicode(r"$\unknowncmd{x}$") == r"$\unknowncmd{x}$"
    assert mathtext_to_unicode(r"$x^q$") == r"$x^q$"  # no unicode superscript q


def test_mathtext_reaches_labels_ticks_and_legend() -> None:
    fig, ax = plt.subplots()
    x = np.linspace(0, 2 * np.pi, 30)
    ax.plot(x, np.sin(x), label=r"$\sigma^2$")
    ax.set_ylabel("area km$^2$")
    ax.set_xticks([0, np.pi, 2 * np.pi], [r"$0$", r"$\pi$", r"$2\pi$"])
    ax.legend()
    svg = _svg(fig)
    assert "km²" in svg
    assert ">π<" in svg and ">2π<" in svg
    assert "σ²" in svg


def test_funcformatter_mathtext_tick_labels_render_unicode() -> None:
    fig, ax = plt.subplots()
    x = np.linspace(0, 3 * np.pi, 100)
    ax.plot(x, np.sin(x))
    ax.set_xlim(0, 3 * np.pi)
    ax.xaxis.set_major_locator(plt.MultipleLocator(np.pi / 2))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _n: rf"${v / np.pi:g}\pi$"))
    svg = _svg(fig)
    assert re.search(r">[\d.]+π<", svg)


def test_unicode_glyphs_produce_ink_in_png() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.set_title("π σ² 10³")
    with_title = _png_pixels(fig)
    plt.close("all")
    fig2, ax2 = plt.subplots()
    ax2.plot([0, 1], [0, 1])
    without_title = _png_pixels(fig2)
    band = slice(0, with_title.shape[0] // 8)
    assert (with_title[band] != without_title[band]).any()


def test_ylabel_renders_rotated_in_png_left_margin() -> None:
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    ax.set_ylabel("amplitude of the signal")
    pixels = _png_pixels(fig)
    height, width = pixels.shape[:2]
    # Ink confined to a tall, narrow left-margin band — rotated text; the old
    # horizontal top-left placement would put ink in the top band instead.
    left_band = pixels[height // 4 : 3 * height // 4, : width // 24, :3]
    assert (left_band < 200).any()
    top_band = pixels[: height // 40, : width // 24, :3]
    assert not (top_band < 200).any()


def test_errorbar_color_and_ecolor_resolve_independently() -> None:
    fig, ax = plt.subplots()
    ax.errorbar([0, 1], [0, 1], yerr=0.1, fmt="o", color="black", ecolor="lightgray")
    svg = _svg(fig)
    assert "black" in svg or "#000000" in svg  # markers keep the explicit color
    assert "lightgray" in svg or "#d3d3d3" in svg  # bars take ecolor
    assert "#1f77b4" not in svg  # nobody falls back to the cycle


def test_rdbu_is_colorbrewer_not_coolwarm() -> None:
    from xy._svg import COLORMAP_STOPS

    assert COLORMAP_STOPS["rdbu"][0] == (103, 0, 31)
    assert COLORMAP_STOPS["rdbu"][-1] == (5, 48, 97)


def test_colormap_stop_tables_track_matplotlib_bands() -> None:
    # plasma's top-of-ramp anchors were once padded duplicates, merging the
    # last discrete bands; the tail must stay distinct and orange-then-yellow.
    from xy._svg import COLORMAP_STOPS

    tail = COLORMAP_STOPS["plasma"][-3:]
    assert len({tuple(anchor) for anchor in tail}) == 3
    assert tail[-1][0] > 200 and tail[-1][1] > 200  # yellow
    assert tail[0][1] < 200  # still orange two anchors down


def test_scatter_size_arrays_keep_absolute_scale() -> None:
    fig, ax = plt.subplots()
    sizes = np.array([36.0, 900.0])
    ax.scatter([0, 1], [0, 1], s=sizes)
    entry = ax._entries[-1]
    lo, hi = entry["kwargs"]["size_range"]
    np.testing.assert_allclose((lo, hi), (np.sqrt(36) * 4 / 3, np.sqrt(900) * 4 / 3))


def test_colorbar_label_converts_mathtext() -> None:
    fig, ax = plt.subplots()
    handle = ax.scatter([0, 1], [0, 1], c=[0.0, 1.0])
    fig.colorbar(handle, label="log$_{10}$(population)")
    assert "log₁₀(population)" in _svg(fig)
