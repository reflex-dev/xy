from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt


@pytest.fixture(autouse=True)
def _clean():
    plt.close("all")
    yield
    plt.close("all")


def test_gcf_materializes_and_persists() -> None:
    fig = plt.gcf()
    assert plt.gcf() is fig
    fig2 = plt.figure()
    assert fig2 is not fig
    assert plt.gcf() is fig2


def test_figure_by_number_activates() -> None:
    f1 = plt.figure(1)
    plt.figure(2)
    assert plt.figure(1) is f1
    assert plt.gcf() is f1


def test_close_all_resets() -> None:
    plt.plot([0, 1], [1, 2])
    plt.close("all")
    fresh = plt.gcf()
    assert fresh._axes == [] or all(not ax._entries for ax in fresh._axes)


def test_implicit_pyplot_functions_target_current_axes() -> None:
    plt.plot([0, 1], [1, 2], label="a")
    plt.title("t")
    plt.xlabel("xx")
    plt.ylabel("yy")
    plt.legend()
    html = plt.gcf()._repr_html_()
    for needle in ("t", "xx", "yy"):
        assert needle in html


def test_subplots_return_shapes() -> None:
    _f, ax = plt.subplots()
    assert hasattr(ax, "plot")
    _f, axes = plt.subplots(2)
    assert axes.shape == (2,)
    _f, axes = plt.subplots(1, 3)
    assert axes.shape == (3,)
    _f, axes = plt.subplots(2, 2)
    assert axes.shape == (2, 2)


def test_subplots_activates_last_axes_for_implicit_pyplot_calls() -> None:
    fig, axes = plt.subplots(3, 1)
    plt.stairs([1, 2, 1])
    assert plt.gca() is axes[-1]
    assert axes[-1]._entries
    assert all(not ax._entries for ax in fig.axes[:-1])
    _f, axes = plt.subplots(2, 2, squeeze=False)
    assert axes.shape == (2, 2)


def test_add_subplot_grammar() -> None:
    fig = plt.figure()
    ax = fig.add_subplot(2, 2, 1)
    ax2 = fig.add_subplot(224)
    assert ax is not ax2


def test_savefig_png_svg_html(tmp_path: Path) -> None:
    _fig, ax = plt.subplots()
    ax.plot(np.arange(50, dtype=float), np.random.default_rng(0).normal(size=50))
    for suffix, magic in (
        ("png", b"\x89PNG\r\n\x1a\n"),
        ("svg", b"<svg"),
        ("html", b"<!doctype html>"),
    ):
        target = tmp_path / f"chart.{suffix}"
        plt.savefig(target)
        data = target.read_bytes()
        assert data[:32].lstrip().startswith(magic) or data.startswith(magic), suffix


def test_grid_savefig_png_stitches(tmp_path: Path) -> None:
    fig, axes = plt.subplots(1, 2)
    axes[0].plot([0, 1], [1, 2])
    axes[1].bar(["a", "b"], [2, 1])
    target = tmp_path / "grid.png"
    plt.savefig(target)
    data = target.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", data[16:24]) == tuple(
        round(value * fig.get_dpi()) for value in fig.get_size_inches()
    )


def test_add_axes_png_uses_native_facecolor_parser() -> None:
    fig = plt.figure(facecolor="rgba(12,34,56,0.5)")
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.plot([0, 1], [1, 2])

    assert fig._to_png().startswith(b"\x89PNG\r\n\x1a\n")


def test_grid_html_has_panels() -> None:
    _fig, axes = plt.subplots(2, 2, figsize=(8, 6))
    for i, ax in enumerate(axes.ravel()):
        ax.plot([0, 1], [i, i + 1])
    html = plt.gcf()._to_html()
    assert html.count('class="xy-panel"') == 4
    # Multi-panel grids are absolutely placed on a figsize canvas at their
    # matplotlib gridspec rects.
    assert html.count("position:absolute") >= 4
    # One document, one client: every panel hydrates through the same WebGL
    # context governor (panel-per-iframe rendered only the first ~12 panels).
    assert html.count("xy.renderStandalone(") == 1  # single hydrate loop
    assert '"spec":' in html and '"chunks":' in html
    assert "<iframe" not in html
    assert "Content-Security-Policy" in html


def test_notebook_repr_isolates_standalone_document_styles() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.plot([0, 1], [1, 2])

    html = fig._repr_html_()

    assert html.startswith('<iframe class="xy-notebook-frame"')
    assert 'sandbox="allow-scripts"' in html
    assert 'width="558" height="418"' in html
    assert "margin-left:8px" in html
    assert "<style>" not in html
    assert "&lt;style&gt;" in html
    assert "&lt;!doctype html&gt;" in html


def test_figsize_dpi_map_to_pixels() -> None:
    fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
    ax.plot([0, 1], [1, 2])
    chart = ax._build_chart(*fig._panel_px())
    assert chart.width == 800 and chart.height == 600


def test_rc_figsize_default() -> None:
    plt.rcParams.reset()
    fig = plt.figure()
    w, h = fig._panel_px()
    assert (w, h) == (640, 480)


def test_rc_unknown_key_warns_once() -> None:
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        plt.rcParams["nonsense.key"] = 1
        plt.rcParams["nonsense.key"] = 2
    assert len([w for w in caught if "nonsense.key" in str(w.message)]) == 1


def test_subplot_activates_current_axes() -> None:
    """plt.subplot(2,1,2) then implicit plt.plot must draw on panel 2."""
    plt.subplot(2, 1, 1)
    ax2 = plt.subplot(2, 1, 2)
    plt.plot([0, 1], [1, 2])
    fig = plt.gcf()
    assert plt.gca() is ax2
    assert ax2._entries and not fig._axes[0]._entries


def test_sca_switches_without_reordering() -> None:
    _fig, axes = plt.subplots(1, 2)
    order_before = list(plt.gcf()._axes)
    plt.sca(axes[1])
    plt.plot([0, 1], [5, 6])
    assert plt.gca() is axes[1]
    assert list(plt.gcf()._axes) == order_before
    assert axes[1]._entries and not axes[0]._entries
