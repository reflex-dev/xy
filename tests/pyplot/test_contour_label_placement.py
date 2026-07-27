from __future__ import annotations

import io
import re

import numpy as np
import pytest

import xy.pyplot as plt
from xy.pyplot._plot_types import _joined_contour_paths


def _gaussian_difference() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.arange(-3.0, 3.0, 0.025)
    y = np.arange(-2.0, 2.0, 0.025)
    X, Y = np.meshgrid(x, y)
    z = 2 * (np.exp(-(X**2) - Y**2) - np.exp(-((X - 1) ** 2) - (Y - 1) ** 2))
    return X, Y, z


def test_clabel_joins_paths_rotates_and_uses_contour_colors() -> None:
    X, Y, z = _gaussian_difference()
    fig, ax = plt.subplots()
    contour = ax.contour(X, Y, z)
    labels = ax.clabel(contour, fontsize=10)

    # Matplotlib's gallery result has one eligible connected component for
    # each interior level, not 3-6 labels sampled from each segment soup.
    assert [label.get_text() for label in labels] == [
        "-1.5",
        "-1",
        "-0.5",
        "0",
        "0.5",
        "1",
        "1.5",
    ]
    assert all(label._entry["kwargs"]["anchor"] == "middle" for label in labels)
    assert all(label._entry["kwargs"]["style"]["font_size"] == 10 for label in labels)
    assert all(-90 <= label._entry["kwargs"]["style"]["rotation"] <= 90 for label in labels)
    assert any(abs(label._entry["kwargs"]["style"]["rotation"]) > 20 for label in labels)
    assert len({label.get_color() for label in labels}) == len(labels)

    # inline=True keeps the original mappable live but replaces its visible
    # geometry with connected segments split around the label windows.
    assert [entry["kind"] for entry in ax._entries[:2]] == ["@mark", "@mark"]
    assert ax._entries[0]["factory"] == "contour"
    assert ax._entries[0]["kwargs"]["opacity"] == 0
    replacements = [
        entry
        for entry in ax._entries
        if entry["kind"] == "@mark" and entry["factory"] == "segments"
    ]
    assert len(replacements) == len(labels)
    assert all(len(entry["args"][0]) > 2 for entry in replacements)

    svg = fig._single().to_svg()
    rotations = [
        float(value) for value in re.findall(r'<text[^>]+transform="rotate\((-?[0-9.]+) ', svg)
    ]
    assert rotations and any(abs(value) > 20 for value in rotations)


def test_manual_clabel_locations_snap_to_the_nearest_requested_contour() -> None:
    y, x = np.mgrid[0:1:60j, -1:1:80j]
    _fig, ax = plt.subplots()
    contour = ax.contour(x, y, x, levels=[-0.5, 0.0, 0.5])

    (label,) = ax.clabel(
        contour,
        levels=[0.0],
        manual=[(0.22, 0.73)],
        inline=False,
        colors="red",
    )

    label_x, label_y, _text = label._entry["args"]
    assert label_x == pytest.approx(0.0, abs=1e-12)
    assert label_y == pytest.approx(0.73, abs=0.02)
    assert label.get_text() == "0"
    assert label.get_color() == "red"
    assert [entry["kind"] for entry in ax._entries] == ["@mark", "@text"]


def test_clabel_validates_levels_and_noninteractive_manual_mode() -> None:
    _fig, ax = plt.subplots()
    contour = ax.contour(np.arange(16.0).reshape(4, 4), levels=[4.0, 8.0])

    with pytest.raises(ValueError, match="don't match available levels"):
        ax.clabel(contour, levels=[6.0])
    with pytest.raises(NotImplementedError, match="iterable"):
        ax.clabel(contour, manual=True)
    with pytest.raises(ValueError, match="inline_spacing"):
        ax.clabel(contour, inline_spacing=-1)


def test_joined_contour_paths_finds_true_open_endpoint_after_segment_shuffle() -> None:
    # Seed segment is in the middle; a joiner that only looks at the seed's
    # endpoints splits this one open contour into two paths.
    x0 = np.asarray([1.0, 0.0, 2.0])
    x1 = np.asarray([2.0, 1.0, 3.0])
    y0 = y1 = np.zeros(3)

    paths = _joined_contour_paths(x0, x1, y0, y1)

    assert len(paths) == 1
    np.testing.assert_allclose(paths[0][:, 0], [0.0, 1.0, 2.0, 3.0])


def test_contour_colorbar_inherits_extend_lines_and_colorbar_axes_state() -> None:
    fig, ax = plt.subplots()
    contour = ax.contourf(
        np.arange(16.0).reshape(4, 4),
        levels=[2.0, 6.0, 10.0],
        extend="both",
    )
    lines = ax.contour(
        np.arange(16.0).reshape(4, 4),
        levels=[2.0, 6.0, 10.0],
        colors="red",
        linewidths=2,
    )

    colorbar = fig.colorbar(contour)
    colorbar.ax.set_ylabel("mapped value")
    colorbar.add_lines(lines)

    assert ax._colorbar is not None
    assert ax._colorbar["extend"] == "both"
    assert ax._colorbar["label"] == "mapped value"
    assert ax.get_ylabel() == ""
    assert [line["value"] for line in ax._colorbar["lines"]] == [2.0, 6.0, 10.0]
    assert {line["color"] for line in ax._colorbar["lines"]} == {"red"}
    assert {line["dash"] for line in ax._colorbar["lines"]} == {None}

    before = colorbar.ax.get_position().bounds
    colorbar.ax.set_position([before[0], before[1] + 0.1 * before[3], before[2], 0.8 * before[3]])
    assert ax._colorbar["shrink"] == pytest.approx(0.8)

    svg = fig._single().to_svg()
    assert svg.count("<polygon") >= 2
    assert svg.count('data-xy-colorbar-line="true"') == 3


def test_colorbar_add_lines_preserves_negative_contour_dashes() -> None:
    fig, ax = plt.subplots()
    values = np.linspace(-1.0, 1.0, 36).reshape(6, 6)
    filled = ax.contourf(values, levels=[-1.0, -0.5, 0.0, 0.5, 1.0])
    lines = ax.contour(values, levels=[-0.5, 0.0, 0.5], colors="red")

    colorbar = fig.colorbar(filled)
    colorbar.add_lines(lines)

    assert [line["dash"] for line in ax._colorbar["lines"]] == ["dashed", None, None]
    svg = fig._single().to_svg()
    assert svg.count("stroke-dasharray=") >= 1


def test_constrained_layout_reserves_contour_colorbar_inside_canvas() -> None:
    from xy.pyplot._rc import rc_figsize_px

    fig, ax = plt.subplots(layout="constrained")
    values = np.arange(16.0).reshape(4, 4)
    filled = ax.contourf(values, levels=[2.0, 6.0, 10.0], extend="both")
    lines = ax.contour(values, levels=[2.0, 6.0, 10.0], colors="red")
    colorbar = fig.colorbar(filled)
    colorbar.ax.set_ylabel("mapped value")
    colorbar.add_lines(lines)

    canvas_width, canvas_height = rc_figsize_px(fig._figsize, fig._dpi)
    rects = fig._effective_rects()
    assert rects is not None
    position = fig._panel_positions(rects, (canvas_width, canvas_height))[0]
    panel = fig._charts()[0].figure()
    panel_x = round(position[0] * canvas_width)
    panel_y = round((1.0 - position[1] - position[3]) * canvas_height)

    # Before reserving the colorbar strip from the plot width, this panel was
    # 732 px wide on a 640 px constrained-layout canvas. The colorbar existed
    # in the payload but only red line slivers survived the export crop.
    assert panel_x + panel.width <= canvas_width
    assert panel_y + panel.height <= canvas_height


def test_second_automatic_colorbar_uses_explicit_axes_without_overwriting_first() -> None:
    fig, ax = plt.subplots()
    values = np.linspace(-1.0, 1.0, 64).reshape(8, 8)
    image = ax.imshow(values, cmap="gray")
    contour = ax.contour(values, levels=[-0.5, 0.0, 0.5], cmap="flag", extend="both")

    first = fig.colorbar(contour, shrink=0.8)
    second = fig.colorbar(image, orientation="horizontal", shrink=0.8)

    assert ax._colorbar is first._options
    assert ax._colorbar["orientation"] == "vertical"
    assert ax._colorbar["line_only"] is True
    assert second.ax is fig.axes[-1]
    assert second.ax is not ax
    assert second.ax._colorbar["orientation"] == "horizontal"
    assert "line_only" not in second.ax._colorbar
    assert second.ax._colorbar["placement"] == "axes"

    output = io.BytesIO()
    fig.savefig(output, format="svg")
    svg = output.getvalue().decode()
    assert svg.count("<linearGradient") >= 2


def test_line_contour_colorbar_is_unfilled_with_its_own_level_overlays() -> None:
    fig, ax = plt.subplots()
    values = np.linspace(-1.2, 1.4, 100).reshape(10, 10)
    levels = np.arange(-1.2, 1.6, 0.2)
    contour = ax.contour(
        values,
        levels=levels,
        cmap="flag",
        extend="both",
        linewidths=2,
    )

    fig.colorbar(contour, shrink=0.8)

    assert ax._colorbar["line_only"] is True
    assert [line["value"] for line in ax._colorbar["lines"]] == pytest.approx(levels)
    assert ax._colorbar["ticks"] == pytest.approx(levels[::2])
    svg = fig._single().to_svg()
    assert 'data-xy-colorbar-line-only="true"' in svg
    assert svg.count('data-xy-colorbar-line="true"') == len(levels)
    assert svg.count("<polygon points=") == 2

    output = io.BytesIO()
    fig.savefig(output, format="png")
    assert output.getvalue().startswith(b"\x89PNG")


def test_listed_contour_colorbar_keeps_exact_bands_and_extension_colors() -> None:
    fig, ax = plt.subplots()
    values = np.linspace(-2.0, 2.0, 100).reshape(10, 10)
    contour = ax.contourf(
        values,
        levels=[-1.5, -1.0, -0.5, 0.0, 0.5, 1.0],
        colors=("red", "green", "blue"),
        extend="both",
    )
    contour.cmap.set_under("yellow")
    contour.cmap.set_over("cyan")

    fig.colorbar(contour)

    assert ax._colorbar["band_colors"] == [
        [255, 0, 0],
        [0, 128, 0],
        [0, 0, 255],
        [255, 0, 0],
        [0, 128, 0],
    ]
    assert ax._colorbar["under_color"] == [255, 255, 0]
    assert ax._colorbar["over_color"] == [0, 255, 255]

    svg = fig._single().to_svg()
    assert svg.count('fill="rgb(255,0,0)"') >= 2
    assert 'fill="rgb(0,128,0)"' in svg
    assert 'fill="rgb(0,0,255)"' in svg
    assert 'fill="rgb(255,255,0)"' in svg
    assert 'fill="rgb(0,255,255)"' in svg


def test_named_contour_colormap_keeps_explicit_extension_colors() -> None:
    fig, ax = plt.subplots()
    values = np.linspace(-2.0, 2.0, 100).reshape(10, 10)
    cmap = plt.colormaps["winter"].with_extremes(under="magenta", over="yellow")
    contour = ax.contourf(
        values,
        levels=[-1.0, -0.5, 0.0, 0.5, 1.0],
        cmap=cmap,
        extend="both",
    )

    fig.colorbar(contour)

    assert ax._colorbar["under_color"] == [255, 0, 255]
    assert ax._colorbar["over_color"] == [255, 255, 0]
