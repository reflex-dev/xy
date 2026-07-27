"""The rendered axes frame must land on the rectangle `get_position()` reports.

Every assertion here reads real emitted geometry: `_svg.layout()` is the single
plot-rect resolver both static exporters use (and the browser client mirrors it),
and the dense-grid check probes the composed PNG buffer itself.  Reference values
are Matplotlib 3.11's own — figure.subplot.* frame, gridspec cell arithmetic, and
`Axes.get_window_extent()` — so a drift shows up as a compatibility failure
rather than a snapshot churn.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

import xy.pyplot as plt
from xy import _svg


def teardown_function():
    plt.close("all")


def _plot_rects(fig) -> list[tuple[float, float, float, float]]:
    """Absolute (x0, y0_from_top, w, h) px of every panel's plot rect."""
    from xy.pyplot._rc import rc_figsize_px

    canvas = rc_figsize_px(fig._figsize, fig._dpi)
    charts = fig._charts()
    rects = fig._effective_rects()
    if rects is None:
        offsets = [(0.0, 0.0)]
    else:
        offsets = [
            (round(p[0] * canvas[0]), round((1.0 - p[1] - p[3]) * canvas[1]))
            for p in fig._panel_positions(rects, canvas)
        ]
    out = []
    for (ox, oy), chart in zip(offsets, charts, strict=True):
        spec, _blob = chart.figure().build_payload()
        _w, _h, _compact, plot = _svg.layout(spec)
        out.append((ox + plot["x"], oy + plot["y"], plot["w"], plot["h"]))
    return out


def _reported_rects(fig) -> list[tuple[float, float, float, float]]:
    """The same rectangles as scripts read them, converted to top-origin px."""
    from xy.pyplot._rc import rc_figsize_px

    width, height = rc_figsize_px(fig._figsize, fig._dpi)
    out = []
    for ax in fig.axes:
        x0, y0, w, h = ax.get_position().bounds
        out.append((x0 * width, (1.0 - y0 - h) * height, w * width, h * height))
    return out


def test_default_axes_renders_on_the_matplotlib_subplot_frame():
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.plot([0, 1, 2], [1, 3, 2])

    # rcParams figure.subplot.*: left .125, bottom .11, right .9, top .88.
    assert ax.get_position().bounds == pytest.approx((0.125, 0.11, 0.775, 0.77))
    (rendered,) = _plot_rects(fig)
    assert rendered == pytest.approx((80.0, 57.6, 496.0, 369.6), abs=0.5)


def test_axes_title_does_not_move_the_rendered_frame():
    """matplotlib draws the title above the axes without changing its position."""
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.plot([0, 1], [0, 1])
    (plain,) = _plot_rects(fig)

    plt.close("all")
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.plot([0, 1], [0, 1])
    ax.set_title("titled")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    (titled,) = _plot_rects(fig)

    assert titled == pytest.approx(plain, abs=0.5)


@pytest.mark.parametrize(
    "figsize",
    [(6.4, 4.8), (3.2, 2.4), (12.0, 3.0), (5.0, 5.0)],
)
def test_reported_and_rendered_frames_agree_for_a_single_axes(figsize):
    fig, ax = plt.subplots(figsize=figsize, dpi=100)
    ax.plot([0, 1], [0, 1])

    (reported,) = _reported_rects(fig)
    (rendered,) = _plot_rects(fig)
    assert rendered == pytest.approx(reported, abs=0.5)


@pytest.mark.parametrize(
    ("nrows", "ncols", "figsize", "adjust"),
    [
        (2, 2, (6.4, 4.8), {}),
        (1, 3, (9.0, 3.0), {"left": 0.05, "right": 0.98, "wspace": 0.35}),
        (5, 5, (5.0, 5.0), {"hspace": 0.0, "wspace": 0.0}),
        (8, 8, (6.0, 6.0), {}),
    ],
)
def test_reported_and_rendered_frames_agree_for_every_grid_panel(nrows, ncols, figsize, adjust):
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, dpi=100)
    if adjust:
        fig.subplots_adjust(**adjust)
    for ax in np.asarray(axes).ravel():
        ax.plot([0, 1], [0, 1])

    reported = _reported_rects(fig)
    rendered = _plot_rects(fig)
    assert len(rendered) == nrows * ncols
    for want, got in zip(reported, rendered, strict=True):
        assert got == pytest.approx(want, abs=1.0)


def test_grid_panel_reservations_keep_the_plot_rect_on_its_cell():
    """A top-side x axis (matshow) and a secondary y axis both take room the
    renderers reserve outside the padding; the panel must grow, not shift."""
    fig, axes = plt.subplots(2, 2, figsize=(6.4, 4.8), dpi=100)
    flat = list(np.asarray(axes).ravel())
    flat[0].matshow(np.arange(9.0).reshape(3, 3))
    flat[1].plot([0, 1], [0, 1])
    flat[1].twinx().plot([0, 1], [3, 4])
    flat[2].plot([0, 1], [0, 1])
    flat[2].set_title("titled")
    flat[3].plot([0, 1], [0, 1])

    for index, (want, got) in enumerate(zip(_reported_rects(fig), _plot_rects(fig), strict=True)):
        # matshow is aspect-equal, so only its cell *origin* and height are
        # pinned — adjustable='box' centers a square axes inside the cell.
        if index == 0:
            assert got[1] == pytest.approx(want[1], abs=1.0)
            assert got[3] == pytest.approx(want[3], abs=1.0)
        else:
            assert got == pytest.approx(want, abs=1.0)


def test_get_position_reports_one_distinct_box_per_grid_panel():
    fig, axes = plt.subplots(8, 8, figsize=(6.0, 6.0), dpi=100)
    boxes = [tuple(np.round(ax.get_position().bounds, 6)) for ax in np.asarray(axes).ravel()]

    assert len(boxes) == 64
    assert len(set(boxes)) == 64
    # Matplotlib's gridspec arithmetic: 0.775 wide / 0.77 tall frame, cells
    # separated by wspace/hspace = 0.2 of the average cell.
    assert boxes[0][0] == pytest.approx(0.125)
    assert boxes[-1][0] + boxes[-1][2] == pytest.approx(0.9)
    assert boxes[-1][1] == pytest.approx(0.11)
    assert boxes[0][1] + boxes[0][3] == pytest.approx(0.88)
    del fig


def test_get_position_keeps_subplot_cells_stable_after_an_axes_is_removed():
    fig, axes = plt.subplots(2, 2, figsize=(6.4, 4.8), dpi=100)
    flat = list(np.asarray(axes).ravel())
    expected = [ax.get_position().bounds for ax in flat]

    fig.delaxes(flat[0])

    assert [ax.get_position().bounds for ax in fig.axes] == pytest.approx(expected[1:])
    for want, got in zip(_reported_rects(fig), _plot_rects(fig), strict=True):
        assert got == pytest.approx(want, abs=1.0)


def test_get_position_distinguishes_active_and_original_aspect_boxes():
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    ax.imshow(np.arange(4.0).reshape(2, 2))

    assert ax.get_position(original=True).bounds == pytest.approx((0.125, 0.11, 0.775, 0.77))
    assert ax.get_position().bounds == pytest.approx((0.22375, 0.11, 0.5775, 0.77))
    assert _plot_rects(fig)[0] == pytest.approx(_reported_rects(fig)[0], abs=1.0)

    ax.set_anchor("W")
    assert ax.get_position().bounds == pytest.approx((0.125, 0.11, 0.5775, 0.77))
    assert _plot_rects(fig)[0] == pytest.approx(_reported_rects(fig)[0], abs=1.0)


def test_subplots_adjust_restores_a_set_position_axes_to_its_grid_cell():
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 4.8), dpi=100)
    left, right = list(np.asarray(axes).ravel())
    left.set_position((0.01, 0.02, 0.03, 0.04))
    assert left.get_position(original=True).bounds == pytest.approx((0.01, 0.02, 0.03, 0.04))

    fig.subplots_adjust(left=0.2, right=0.8, wspace=0.0)

    assert left.get_position(original=True).bounds == pytest.approx((0.2, 0.11, 0.3, 0.77))
    assert right.get_position(original=True).bounds == pytest.approx((0.5, 0.11, 0.3, 0.77))


def test_rgba_composition_preserves_straight_alpha_on_transparent_figures():
    from xy.pyplot._grid import _composite_rgba

    destination = np.asarray([[[0, 0, 255, 128]]], dtype=np.uint8)
    source = np.asarray([[[255, 0, 0, 128]]], dtype=np.uint8)

    _composite_rgba(destination, source)

    # Source-over in straight alpha: A=0.75, RGB=(2/3 red, 1/3 blue).
    assert destination[0, 0] == pytest.approx((170, 0, 85, 192), abs=1)


def test_get_position_follows_subplots_adjust_and_ratios():
    fig, axes = plt.subplots(2, 2, figsize=(6.4, 4.8), width_ratios=[1, 3])
    fig.subplots_adjust(left=0.2, right=0.95, wspace=0.0)
    flat = list(np.asarray(axes).ravel())

    left, right = flat[0].get_position(), flat[1].get_position()
    assert left.x0 == pytest.approx(0.2)
    assert right.x0 + right.width == pytest.approx(0.95)
    # wspace=0 makes the columns adjacent, split 1:3 across the frame.
    assert left.x0 + left.width == pytest.approx(right.x0)
    assert right.width == pytest.approx(3.0 * left.width)


def test_explicit_rects_and_set_position_still_win():
    fig = plt.figure(figsize=(6.4, 4.8), dpi=100)
    ax = fig.add_axes((0.2, 0.25, 0.6, 0.5))
    ax.plot([0, 1], [0, 1])

    assert ax.get_position().bounds == pytest.approx((0.2, 0.25, 0.6, 0.5))
    (rendered,) = _plot_rects(fig)
    assert rendered == pytest.approx((128.0, 120.0, 384.0, 240.0), abs=0.5)

    ax.set_position([0.1, 0.1, 0.5, 0.5])
    assert ax.get_position().bounds == pytest.approx((0.1, 0.1, 0.5, 0.5))


def test_dense_grid_composite_draws_every_panel(monkeypatch):
    """Panels are wider than their gridspec cell, so the compositor must
    alpha-blend them; an opaque paste left only the last column visible."""
    from xy import _png

    captured: list[np.ndarray] = []
    real_encode = _png.encode

    def capture(canvas, *args, **kwargs):
        captured.append(np.array(canvas))
        return real_encode(canvas, *args, **kwargs)

    monkeypatch.setattr(_png, "encode", capture)

    nrows = ncols = 8
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(nrows, ncols, figsize=(6.0, 6.0), dpi=100)
    for ax in np.asarray(axes).ravel():
        ax.imshow(rng.random((8, 8)), cmap="binary")
        ax.set(xticks=[], yticks=[])
    rects = _plot_rects(fig)

    fig.savefig(io.BytesIO(), format="png", dpi=100)
    assert captured, "savefig did not compose a figure canvas"
    canvas = captured[-1]
    assert canvas.shape[:2] == (600, 600)

    # Probe the middle of each panel's own plot rect on the composed buffer.
    covered = []
    for x0, y0, w, h in rects:
        patch = canvas[
            int(y0 + 0.25 * h) : int(y0 + 0.75 * h),
            int(x0 + 0.25 * w) : int(x0 + 0.75 * w),
            :3,
        ].astype(int)
        covered.append(float(np.mean(np.any(np.abs(patch - 255) > 12, axis=2))))

    assert len(covered) == nrows * ncols
    assert min(covered) > 0.5, f"blank panels: {[i for i, c in enumerate(covered) if c <= 0.5]}"
    # The composed figure canvas stays opaque for the default white facecolor.
    assert int(canvas[..., 3].min()) == 255
