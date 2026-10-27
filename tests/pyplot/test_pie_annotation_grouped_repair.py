"""Regressions reduced from Matplotlib's pie-and-donut labels gallery."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

import xy.pyplot as plt
from conftest import probe_document, run_browser_probe
from xy._arrowgeom import arrow_geometry, shaft_points
from xy._svg import layout
from xy.export import find_chromium
from xy.pyplot._colors import resolve_color


@pytest.fixture(autouse=True)
def _clean_pyplot_state():
    plt.close("all")
    yield
    plt.close("all")


def test_pie_wedges_use_joined_fills_and_exterior_only_strokes() -> None:
    _fig, ax = plt.subplots()

    pie = ax.pie(
        [2, 3, 5],
        wedgeprops={"edgecolor": "black", "linewidth": 2},
    )

    for wedge in pie.wedges:
        assert wedge.get_zorder() == 1.0
        assert wedge._entry["kwargs"]["_joined_fill"] is True
        assert "stroke" not in wedge._entry["kwargs"]
        assert "stroke_width" not in wedge._entry["kwargs"]
        outline = wedge._outline_entry
        assert outline is not None
        assert outline["factory"] == "segments"
        assert outline["kwargs"]["color"] == "black"
        assert outline["kwargs"]["width"] == 2.0
        assert outline["_zorder"] == 1.0
        x0, y0, x1, y1 = outline["args"]
        assert len(x0) == len(y0) == len(x1) == len(y1)
        assert len(x0) < len(wedge._entry["args"][0]) * 3


def test_explicit_pie_legend_handles_stay_filled_patches() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([1, 2], colors=["tab:blue", "tab:orange"])

    legend = ax.legend(pie.wedges, ["flour", "sugar"])

    assert [item["kind"] for item in legend.spec()["items"]] == ["patch", "patch"]
    assert [item["style"]["color"] for item in legend.spec()["items"]] == [
        "#1f77b4",
        "#ff7f0e",
    ]


def test_one_slice_donut_outline_has_only_outer_and_inner_rings() -> None:
    _fig, ax = plt.subplots()

    wedge = ax.pie(
        [1],
        wedgeprops={"width": 0.5, "edgecolor": "black"},
    ).wedges[0]

    assert wedge._outline_entry is not None
    assert len(wedge._outline_entry["args"][0]) == 120


def _point_in_triangle(point: np.ndarray, triangle: np.ndarray) -> bool:
    edges = np.roll(triangle, -1, axis=0) - triangle
    offsets = point - triangle
    crosses = edges[:, 0] * offsets[:, 1] - edges[:, 1] * offsets[:, 0]
    return bool(np.all(crosses >= -1e-10) or np.all(crosses <= 1e-10))


def test_pie_hatches_cycle_and_every_stroke_is_sector_clipped() -> None:
    _fig, ax = plt.subplots()

    pie = ax.pie(
        [15, 30, 45, 10],
        labels=["Frogs", "Hogs", "Dogs", "Logs"],
        hatch=["**O", "oO"],
    )

    assert [wedge._entry["pie_hatch"] for wedge in pie.wedges] == [
        "**O",
        "oO",
        "**O",
        "oO",
    ]
    for wedge in pie.wedges:
        hatch = wedge._hatch_entry
        assert hatch is not None
        assert hatch["factory"] == "segments"
        assert hatch["_legend_skip"] is True
        triangles = np.stack(
            [
                np.column_stack((wedge._entry["args"][0], wedge._entry["args"][1])),
                np.column_stack((wedge._entry["args"][2], wedge._entry["args"][3])),
                np.column_stack((wedge._entry["args"][4], wedge._entry["args"][5])),
            ],
            axis=1,
        )
        x0, y0, x1, y1 = hatch["args"]
        assert len(x0) == len(y0) == len(x1) == len(y1) > 0
        for start_x, start_y, end_x, end_y in zip(x0, y0, x1, y1, strict=True):
            for point in (
                np.asarray((start_x, start_y)),
                np.asarray((end_x, end_y)),
                np.asarray(((start_x + end_x) / 2, (start_y + end_y) / 2)),
            ):
                assert any(_point_in_triangle(point, triangle) for triangle in triangles)

    legend = ax.legend(pie.wedges, ["one", "two", "three", "four"])
    assert [item["style"]["hatch"] for item in legend.spec()["items"]] == [
        "**O",
        "oO",
        "**O",
        "oO",
    ]


def test_wedgeprops_hatch_overrides_the_pie_hatch_cycle() -> None:
    _fig, ax = plt.subplots()

    pie = ax.pie([1, 2, 3], hatch=["/", "\\"], wedgeprops={"hatch": "x"})

    assert [wedge._entry["pie_hatch"] for wedge in pie.wedges] == ["x", "x", "x"]


def test_pie_shadow_dict_darkens_offsets_and_applies_alpha() -> None:
    _fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)

    pie = ax.pie(
        [1, 2],
        colors=["#ff0000", "#00ff00"],
        shadow={
            "ox": -2,
            "oy": 3,
            "shade": 0.9,
            "alpha": 0.25,
            "edgecolor": "none",
        },
    )

    for wedge in pie.wedges:
        assert len(wedge._shadow_entries) == 1
        shadow = wedge._shadow_entries[0]
        assert shadow["factory"] == "triangle_mesh"
        assert shadow["kwargs"]["opacity"] == 0.25
        assert shadow["_pie_shadow_offset_points"] == (-2.0, 3.0)
        assert shadow["_zorder"] < wedge.get_zorder()
        shadow_index = next(index for index, entry in enumerate(ax._entries) if entry is shadow)
        wedge_index = next(
            index for index, entry in enumerate(ax._entries) if entry is wedge._entry
        )
        assert shadow_index < wedge_index
        dx = np.asarray(shadow["args"][0]) - np.asarray(wedge._entry["args"][0])
        dy = np.asarray(shadow["args"][1]) - np.asarray(wedge._entry["args"][1])
        assert np.all(dx < 0)
        assert np.all(dy > 0)
        assert np.ptp(dx) < 1e-12
        assert np.ptp(dy) < 1e-12

    assert pie.wedges[0]._shadow_entries[0]["kwargs"]["color"] == resolve_color((0.1, 0, 0))
    assert pie.wedges[1]._shadow_entries[0]["kwargs"]["color"] == resolve_color((0, 0.1, 0))


def test_pie_shadow_point_offset_is_dpi_independent_in_data_space() -> None:
    shifts = []
    for dpi in (72, 144):
        fig, ax = plt.subplots(figsize=(4, 4), dpi=dpi)
        wedge = ax.pie([1], shadow={"ox": 2, "oy": -3, "edgecolor": "none"}).wedges[0]
        shadow = wedge._shadow_entries[0]
        shifts.append(
            (
                float(shadow["args"][0][0] - wedge._entry["args"][0][0]),
                float(shadow["args"][1][0] - wedge._entry["args"][1][0]),
            )
        )
        plt.close(fig)

    assert shifts[0] == pytest.approx(shifts[1])


def test_removing_a_wedge_removes_hatch_shadow_and_outline_entries() -> None:
    _fig, ax = plt.subplots()
    wedge = ax.pie(
        [1],
        hatch="/",
        shadow=True,
        wedgeprops={"edgecolor": "black"},
    ).wedges[0]
    owned = {
        id(wedge._entry),
        id(wedge._hatch_entry),
        id(wedge._outline_entry),
        *(id(entry) for entry in wedge._shadow_entries),
    }

    wedge.remove()

    assert not owned.intersection(id(entry) for entry in ax._entries)


def test_angle_connectionstyle_is_an_elbow_but_angle3_is_quadratic() -> None:
    _fig, ax = plt.subplots()
    angle = ax.annotate(
        "angle",
        xy=(1, 1),
        xytext=(0, 0),
        arrowprops={"arrowstyle": "-", "connectionstyle": "angle,angleA=0,angleB=90"},
    )
    angle3 = ax.annotate(
        "angle3",
        xy=(1, 1),
        xytext=(0, 0),
        arrowprops={"arrowstyle": "-", "connectionstyle": "angle3,angleA=0,angleB=90"},
    )

    arrows = [entry for entry in ax._entries if entry["kind"] == "@arrow"]
    assert arrows[0]["kwargs"]["style"]["elbow"] == 1.0
    assert "elbow" not in arrows[1]["kwargs"]["style"]
    assert angle.get_text() == "angle"
    assert angle3.get_text() == "angle3"
    elbow_geometry = arrow_geometry(
        0,
        0,
        10,
        10,
        {"angle_a": 0.0, "angle_b": 90.0, "elbow": 1.0},
    )
    quadratic_geometry = arrow_geometry(
        0,
        0,
        10,
        10,
        {"angle_a": 0.0, "angle_b": 90.0},
    )
    assert shaft_points(elbow_geometry) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert len(shaft_points(quadratic_geometry)) == 25


def test_annotation_zorder_is_stored_on_label_and_connector() -> None:
    _fig, ax = plt.subplots()
    pie = ax.pie([1, 1])

    label = ax.annotate(
        "outside",
        xy=(1, 0),
        xytext=(1.35, 0),
        arrowprops={"arrowstyle": "-"},
        zorder=0,
    )

    arrow = next(entry for entry in ax._entries if entry["kind"] == "@arrow")
    assert label.get_zorder() == 0.0
    assert arrow["_zorder"] == 0.0
    positions = {id(entry): index for index, entry in enumerate(ax._entries)}
    assert positions[id(arrow)] < min(positions[id(wedge._entry)] for wedge in pie.wedges)


def _outside_connector_chart():
    fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
    ax.set_axis_off()
    ax.set_xlim(-1.25, 1.25)
    ax.set_ylim(-1.0, 1.0)
    ax.annotate(
        "",
        xy=(1.0, 0.0),
        xytext=(1.4, 0.0),
        arrowprops={"arrowstyle": "-", "color": "#ff0000", "linewidth": 6},
    )
    return ax._build_chart(*fig._panel_px()).figure()


def test_svg_and_raster_keep_connector_outside_axes_when_target_is_inside() -> None:
    chart = _outside_connector_chart()
    spec, _blob = chart.build_payload()
    plot = layout(spec)[3]
    plot_right = plot["x"] + plot["w"]

    svg = chart.to_svg()
    connector = svg.index('stroke="#ff0000"')
    clipped_group = svg.index('<g clip-path="url(#')
    clipped_group_end = svg.index("</g>", clipped_group)
    assert connector > clipped_group_end

    pixels = np.asarray(plt.imread(BytesIO(chart.to_png())))
    outside = pixels[:, int(np.ceil(plot_right)) + 1 :, :3]
    red = (outside[..., 0] > 0.8) & (outside[..., 1] < 0.3) & (outside[..., 2] < 0.3)
    assert np.any(red)


def test_browser_keeps_connector_outside_axes_when_target_is_inside(tmp_path: Path) -> None:
    chromium = find_chromium()
    if chromium is None:
        pytest.skip("Chromium unavailable")
    chart = _outside_connector_chart()
    probe = """
<script>
try {
  const view = window.__fcProbeView;
  view._drawNow();
  view._raf = null;
  const ctx = view.overlay.getContext("2d");
  const pixels = ctx.getImageData(0, 0, view.overlay.width, view.overlay.height).data;
  const dpr = view.dpr;
  const right = Math.ceil((view.plot.x + view.plot.w + 1) * dpr);
  let outsideRed = 0;
  for (let y = 0; y < view.overlay.height; y++) {
    for (let x = right; x < view.overlay.width; x++) {
      const index = (y * view.overlay.width + x) * 4;
      if (pixels[index] > 200 && pixels[index + 1] < 80 && pixels[index + 2] < 80) {
        outsideRed++;
      }
    }
  }
  document.body.setAttribute(
    "data-xy-outside-annotation",
    JSON.stringify({outsideRed, plotRight: right, canvasWidth: view.overlay.width})
  );
} catch (err) {
  document.body.setAttribute(
    "data-xy-outside-annotation-error",
    String((err && err.stack) || err)
  );
}
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "outside_annotation.html",
        "data-xy-outside-annotation",
        label="outside annotation connector",
    )

    assert result["outsideRed"] > 0, result
    assert result["plotRight"] < result["canvasWidth"], result
