"""Regression tests for confirmed matplotlib visual-parity defects.

Each test pins a bug that was verified by pixel comparison against
matplotlib 3.11 (legend handling, marker shapes, prop-cycle advancement,
scatter alpha, errorbar/hist styling).  A regression here means one of those
static-export defects came back.
"""

import io

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._axes import _marker_symbol
from xy.pyplot._translate import MARKER_TO_SYMBOL


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    plt.close("all")
    plt.rcdefaults()


def _png(fig=None):
    buffer = io.BytesIO()
    (fig or plt.gcf()).savefig(buffer, format="png")
    data = buffer.getvalue()
    assert data[:4] == b"\x89PNG"
    return data


def _svg(fig=None):
    buffer = io.BytesIO()
    (fig or plt.gcf()).savefig(buffer, format="svg")
    return buffer.getvalue().decode()


# -- defect 1: legend with an explicit label list ---------------------------


def test_legend_label_list_labels_existing_lines():
    x = np.linspace(0, 10, 20)
    fig, ax = plt.subplots()
    ax.plot(x, np.column_stack([np.sin(x), np.cos(x), np.sin(x) * 0.5]))
    ax.legend(["a", "b", "c"], loc="lower left")
    svg = _svg(fig)
    for label in ("a", "b", "c"):
        assert f">{label}</text>" in svg
    _png(fig)


def test_legend_handles_labels_form_relabels_handles():
    x = np.linspace(0, 10, 20)
    fig, ax = plt.subplots()
    lines = ax.plot(x, np.sin(x))
    lines += ax.plot(x, np.cos(x))
    ax.legend(lines[:2], ["first", "second"])
    svg = _svg(fig)
    assert ">first</text>" in svg
    assert ">second</text>" in svg


# -- defect 2: legend swatches reflect the artist style ---------------------


def test_legend_line_entries_render_line_samples_with_dash():
    x = np.linspace(0, 10, 20)
    fig, ax = plt.subplots()
    ax.plot(x, np.sin(x), label="solid")
    ax.plot(x, np.cos(x), "--", label="dashed")
    svg = _svg(fig)
    # Line legend entries are drawn as <line> samples, and the dashed line
    # carries a dash array rather than a filled square.
    assert svg.count("<line") >= 2
    assert "stroke-dasharray" in svg


def test_legend_scatter_entry_renders_marker_glyph():
    x = np.arange(10)
    fig, ax = plt.subplots()
    ax.scatter(x, np.sin(x), marker="^", label="pts")
    svg = _svg(fig)
    assert ">pts</text>" in svg
    # A triangle marker glyph is a path, not a filled rectangle swatch.
    assert "<path" in svg


# -- defect 3: frameon=False drops the legend box ---------------------------


def test_legend_frameon_false_removes_frame_in_static_export():
    x = np.linspace(0, 10, 20)
    fig, ax = plt.subplots()
    ax.plot(x, np.sin(x), label="s")
    with_frame = _svg(fig)
    assert "rgba(128,128,128,0.08)" in with_frame

    fig2, ax2 = plt.subplots()
    ax2.plot(x, np.sin(x), label="s")
    ax2.legend(frameon=False)
    no_frame = _svg(fig2)
    assert "rgba(128,128,128,0.08)" not in no_frame
    assert ">s</text>" in no_frame


# -- defect 4: prop cycle advances per column of a 2-D operand --------------


def test_plot_2d_y_advances_prop_cycle_per_column():
    x = np.linspace(0, 10, 20)
    y = np.column_stack([np.sin(x), np.cos(x), np.sin(x) + 1, np.cos(x) - 1])
    fig, ax = plt.subplots()
    ax.plot(x, y)
    colors = [e["kwargs"].get("color") for e in ax._entries if e["kind"] == "line"]
    assert colors == ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]


# -- defect 5: real marker shapes, no silent square substitution ------------


def test_pentagon_and_polygon_markers_map_to_real_shapes():
    assert MARKER_TO_SYMBOL["p"] == "pentagon"
    assert MARKER_TO_SYMBOL["h"] == "hexagon"
    assert MARKER_TO_SYMBOL["H"] == "hexagon"
    assert MARKER_TO_SYMBOL["*"] == "star"
    assert _marker_symbol("p") == "pentagon"


def test_pentagon_marker_reaches_render_without_square_fallback():
    x = np.linspace(0, 10, 30)
    fig, ax = plt.subplots()
    ax.plot(
        x,
        np.sin(x),
        "-p",
        markersize=15,
        markerfacecolor="white",
        markeredgecolor="gray",
        color="gray",
    )
    overlay = [e for e in ax._entries if e["kind"] == "scatter"][-1]
    assert overlay["kwargs"]["symbol"] == "pentagon"
    _png(fig)
    assert "<path" in _svg(fig)


def test_new_symbols_are_valid_scatter_symbols():
    from xy import _validate

    for symbol in ("pentagon", "hexagon", "star"):
        assert _validate.point_symbol(symbol, "symbol") == symbol


# -- defect 6: scatter alpha survives a color/colormap encoding -------------


def test_scatter_alpha_applied_with_colormap_encoding():
    rng = np.random.default_rng(0)
    n = 50
    fig, ax = plt.subplots()
    ax.scatter(
        rng.normal(size=n),
        rng.normal(size=n),
        alpha=0.3,
        c=rng.random(n),
        cmap="viridis",
        s=rng.random(n) * 200,
    )
    entry = [e for e in ax._entries if e["kind"] == "scatter"][-1]
    assert entry["kwargs"]["opacity"] == pytest.approx(0.3)
    svg = _svg(fig)
    assert 'fill-opacity="0.3"' in svg
    _png(fig)


# -- defect 7: errorbar bars follow the fmt color ---------------------------


def test_errorbar_fmt_color_applies_to_bars():
    x = np.arange(10)
    fig, ax = plt.subplots()
    ax.errorbar(x, np.sin(x), yerr=0.3, fmt=".k")
    bars = [e for e in ax._entries if e.get("factory") == "errorbar"][-1]
    assert bars["kwargs"]["color"] == "#000000"
    _png(fig)


def test_errorbar_ecolor_still_overrides_fmt_color():
    x = np.arange(10)
    fig, ax = plt.subplots()
    ax.errorbar(x, np.sin(x), yerr=0.3, fmt=".k", ecolor="red")
    bars = [e for e in ax._entries if e.get("factory") == "errorbar"][-1]
    from xy.pyplot._colors import resolve_color

    assert bars["kwargs"]["color"] == resolve_color("red")
    assert bars["kwargs"]["color"] != "#000000"


# -- defect 8: histogram bars span the full bin width -----------------------


def test_hist_single_series_bars_span_full_bin_width():
    rng = np.random.default_rng(1)
    fig, ax = plt.subplots()
    counts, edges, _ = ax.hist(rng.normal(size=500), bins=12)
    bar = [e for e in ax._entries if e["kind"] == "bar"][-1]
    binwidth = float(np.min(np.diff(edges)))
    assert bar["kwargs"]["width"] == pytest.approx(binwidth)
    _png(fig)


def test_hist_multiple_series_stay_side_by_side():
    rng = np.random.default_rng(2)
    fig, ax = plt.subplots()
    data = [rng.normal(size=300), rng.normal(size=300)]
    _counts, edges, _ = ax.hist(data, bins=10)
    binwidth = float(np.min(np.diff(edges)))
    bars = [e for e in ax._entries if e["kind"] == "bar"]
    assert len(bars) == 2
    # Two side-by-side series each shrink to 0.8/2 of the bin (matplotlib).
    assert bars[0]["kwargs"]["width"] == pytest.approx(binwidth * 0.8 / 2)
