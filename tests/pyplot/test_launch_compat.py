from __future__ import annotations

import warnings
from io import BytesIO

import numpy as np
import pytest

import xy.pyplot as plt
from xy._svg import COLORMAP_STOPS, _lut


def test_hist_weights_horizontal_and_stacked_return_matplotlib_geometry() -> None:
    fig, ax = plt.subplots()
    values = [np.arange(5), np.arange(5) + 1]
    weights = [np.ones(5), np.arange(1, 6)]
    counts, edges, containers = ax.hist(
        values, bins=3, weights=weights, orientation="horizontal", stacked=True
    )
    assert counts.shape == (2, 3)
    assert np.all(counts[1] >= counts[0])
    assert len(edges) == 4
    assert len(containers) == 2


def test_bar_snapshots_mutable_bottom_and_fill_between_segments_mask() -> None:
    _fig, ax = plt.subplots()
    bottom = np.zeros(3)
    ax.bar(["a", "b", "c"], [2, 3, 4], bottom=bottom)
    bottom += 10
    trace = ax._build_chart(640, 480).figure().traces[0]
    assert np.allclose(trace.y.values, [2, 3, 4])

    ax.fill_between(
        np.arange(6), np.arange(6), where=[True, True, False, True, True, True], step="mid"
    )
    areas = [entry for entry in ax._entries if entry["kind"] == "area"]
    assert len(areas) == 2
    assert all(np.isfinite(np.asarray(entry["x"], dtype=float)).all() for entry in areas)


def test_bar_labels_are_centered_over_vertical_bars() -> None:
    _fig, ax = plt.subplots()
    bars = ax.bar([0, 1], [10, 20])
    labels = ax.bar_label(bars, fmt="%.1f", padding=3)
    assert len(labels) == 2
    for label, center in zip(labels, [0, 1], strict=True):
        assert label._entry["args"][0] == center
        assert label._entry["kwargs"]["anchor"] == "middle"
        assert label._entry["kwargs"]["dx"] == 0.0
        assert label._entry["kwargs"]["dy"] == pytest.approx(-3.0 * 100.0 / 72.0)
        assert label._entry["kwargs"]["style"]["vertical_align"] == "bottom"


def test_pyplot_legend_location_and_columns_reach_render_spec() -> None:
    _fig, ax = plt.subplots()
    ax.bar([0, 1], [10, 20], label="values")
    ax.legend(loc="upper left", ncols=3)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["loc"] == "upper left"
    assert spec["legend"]["ncols"] == 3
    # Frame styling now rides along so the static-export legend can honor
    # frameon/facecolor/edgecolor (previously only the DOM legend saw it).
    assert "style" in spec["legend"]


def test_legend_best_avoids_the_busy_corner_and_default_axes_are_boxed() -> None:
    _fig, ax = plt.subplots()
    ax.scatter(np.linspace(0.72, 0.98, 100), np.linspace(0.7, 0.98, 100), label="busy")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend()
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["legend"]["loc"] in {"upper left", "lower left", "lower right"}
    assert spec["frame_sides"] == ["left", "bottom", "top", "right"]


def test_filled_stairs_use_seamless_bins_and_hatches_are_not_dropped() -> None:
    _fig, ax = plt.subplots()
    ax.stairs([1, 2], [0, 1, 2], fill=True)
    ax.stairs([0.5, 1], [2, 3, 4], orientation="horizontal", hatch="//")
    assert any(entry["kind"] == "bar" for entry in ax._entries)
    assert not any(entry.get("factory") == "triangle_mesh" for entry in ax._entries)
    hatch = [entry for entry in ax._entries if entry.get("factory") == "segments"][-1]
    assert len(hatch["args"][0]) >= 14
    assert len({len(values) for values in hatch["args"]}) == 1


def test_horizontal_stairs_ring_hatch_uses_oriented_data_spans() -> None:
    _fig, ax = plt.subplots()
    ax.stairs([100.0], [0.0, 1.0], orientation="horizontal", hatch="o")

    hatch = [entry for entry in ax._entries if entry.get("factory") == "segments"][-1]
    x0, y0, x1, y1 = (np.asarray(values[:10]) for values in hatch["args"])
    ring_x = np.concatenate((x0, x1))
    ring_y = np.concatenate((y0, y1))

    # The first ten segments are one ring. Its x radius scales from the
    # 100-unit value span while its y radius scales from the one-unit edge
    # span; using the vertical spans here makes it nearly flat in x and far
    # too tall in y.
    assert np.ptp(ring_x) == pytest.approx(1.25)
    assert np.ptp(ring_y) == pytest.approx(2.0 / 120.0 * np.sin(2.0 * np.pi / 5.0))


def test_adding_external_step_patch_does_not_advance_color_cycle() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import StepPatch as MatplotlibStepPatch

    _fig, ax = plt.subplots()
    ax.add_patch(MatplotlibStepPatch([1, 2], [0, 1, 2]))
    ax.stairs([2, 1], [0, 1, 2], fill=True)
    filled = [entry for entry in ax._entries if entry["kind"] == "bar"]
    assert filled[2]["kwargs"]["color"] == "#1f77b4"


def _mesh_area(entry: dict) -> float:
    x0, y0, x1, y1, x2, y2 = (np.asarray(values, dtype=np.float64) for values in entry["args"])
    return float(np.sum(np.abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0))) / 2.0)


def _shortest_relative_edge(entry: dict) -> float:
    """The outline's shortest segment as a fraction of its bounding diagonal.

    Scale-free, so it pins "no duplicate vertices survived" without pinning
    how many vertices Matplotlib's tessellation happens to emit. A duplicate
    left in place shows up here around 1e-16, real geometry above 1e-3.
    """
    x0, y0, x1, y1 = (np.asarray(values, dtype=np.float64) for values in entry["args"])
    xs, ys = np.concatenate((x0, x1)), np.concatenate((y0, y1))
    span = float(np.hypot(np.ptp(xs), np.ptp(ys)))
    return float(np.min(np.hypot(x1 - x0, y1 - y0)) / span)


def _patch_marks(ax: plt.Axes) -> tuple[list[dict], list[dict]]:
    meshes = [entry for entry in ax._entries if entry.get("factory") == "triangle_mesh"]
    edges = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    return meshes, edges


def test_added_rectangle_patch_fills_with_its_own_face_color() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue"))
    meshes, edges = _patch_marks(ax)
    # Matplotlib leaves edgecolor "none" on a filled patch, so there is no
    # outline to draw and none is emitted.
    assert len(meshes) == 1 and edges == []
    assert meshes[0]["kwargs"]["color"] == "rgba(31,119,180,1)"
    assert meshes[0]["kwargs"]["_joined_fill"] is True
    assert _mesh_area(meshes[0]) == pytest.approx(2.0)


def test_added_rotated_rectangle_keeps_its_rotation() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((1, 2), 3, 4, angle=30, facecolor="tab:blue"))
    meshes, _edges = _patch_marks(ax)
    xs = np.concatenate([np.asarray(meshes[0]["args"][index]) for index in (0, 2, 4)])
    # Ignoring `angle` leaves the axis-aligned span 1.000..4.000 instead.
    assert xs.min() == pytest.approx(-1.000, abs=1e-3)
    assert xs.max() == pytest.approx(3.598, abs=1e-3)
    assert _mesh_area(meshes[0]) == pytest.approx(12.0)


def test_added_ellipse_flattens_its_curve_under_the_patch_transform() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Ellipse

    _fig, ax = plt.subplots()
    ax.add_patch(Ellipse((0, 0), width=2, height=1, angle=20, facecolor="green"))
    meshes, _edges = _patch_marks(ax)
    # pi*a*b. Raw cubic Bézier control points without the transform give 3.2509.
    assert _mesh_area(meshes[0]) == pytest.approx(np.pi * 1.0 * 0.5, rel=1e-2)


def test_added_concave_polygon_patch_triangulates_its_true_area() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Polygon

    _fig, ax = plt.subplots()
    ax.add_patch(Polygon([[0, 0], [4, 0], [4, 4], [2, 1], [0, 4]], facecolor="green"))
    meshes, _edges = _patch_marks(ax)
    assert _mesh_area(meshes[0]) == pytest.approx(10.0)


def test_unfilled_patch_stays_edge_only() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 1, fill=False))
    meshes, edges = _patch_marks(ax)
    assert meshes == []
    assert len(edges) == 1


def test_degenerate_patch_draws_its_edge_without_raising() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 0, facecolor="tab:blue"))
    meshes, edges = _patch_marks(ax)
    assert meshes == []
    assert len(edges) == 1
    edge_x = np.concatenate((edges[0]["args"][0], edges[0]["args"][2]))
    assert np.ptp(edge_x) == pytest.approx(2.0)


def test_removing_a_filled_patch_takes_its_outline_with_it() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    artist = ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="red"))
    assert len(ax._entries) == 2
    artist.remove()
    assert ax._entries == []


def test_adding_a_filled_patch_does_not_advance_the_color_cycle() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:orange"))
    polygon = ax.fill([0, 1, 1], [0, 0, 1])[0]
    assert polygon._entry["kwargs"]["color"] == "#1f77b4"


def test_patch_outline_width_converts_points_to_pixels() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    widths = []
    for dpi in (72, 200):
        _fig, ax = plt.subplots(dpi=dpi)
        ax.add_patch(Rectangle((0, 0), 2, 1, fill=False, linewidth=5))
        widths.append(ax._entries[-1]["kwargs"]["width"])
    assert widths == pytest.approx([5.0, 5.0 * 200 / 72])


def test_patch_outline_stroke_thickens_with_dpi_in_the_png(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    image_module = pytest.importorskip("PIL.Image")
    from matplotlib.patches import Rectangle

    def stroke_runs(dpi: int) -> list[int]:
        fig, ax = plt.subplots(figsize=(4, 4), dpi=dpi)
        ax.add_patch(Rectangle((2, 4), 6, 2, fill=False, edgecolor="#ff0000", linewidth=5))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        path = tmp_path / f"stroke_{dpi}.png"
        fig.savefig(str(path))
        pixels = np.asarray(image_module.open(path).convert("RGB"))
        red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 100) & (pixels[:, :, 2] < 100)
        column = red[:, pixels.shape[1] // 2]
        edges = np.flatnonzero(np.diff(np.r_[False, column, False].astype(np.int8)))
        return (edges[1::2] - edges[0::2]).tolist()

    assert stroke_runs(72) == [5, 5]
    assert stroke_runs(200) == [13, 13]


def test_patch_with_nested_rings_abstains_from_filling_the_hole() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(3, 3), (3, 7), (7, 7), (7, 3), (3, 3)]
    codes = ([Path.MOVETO] + [Path.LINETO] * 3 + [Path.CLOSEPOLY]) * 2
    _fig, ax = plt.subplots()
    ax.add_patch(PathPatch(Path(square + hole, codes), facecolor="tab:blue"))
    meshes, edges = _patch_marks(ax)
    # Filling both rings would paint 116 for a true area of 84.
    assert meshes == []
    assert len(edges) == 2


def test_patch_with_disjoint_rings_still_fills_both() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    left = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    right = [(3, 0), (4, 0), (4, 1), (3, 1), (3, 0)]
    codes = ([Path.MOVETO] + [Path.LINETO] * 3 + [Path.CLOSEPOLY]) * 2
    _fig, ax = plt.subplots()
    ax.add_patch(PathPatch(Path(left + right, codes), facecolor="tab:blue"))
    meshes, _edges = _patch_marks(ax)
    assert len(meshes) == 2
    assert sum(_mesh_area(mesh) for mesh in meshes) == pytest.approx(2.0)


def test_annular_sector_fills_as_one_ring() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Wedge

    _fig, ax = plt.subplots()
    ax.add_patch(Wedge((0, 0), 1.0, 0.0, 90.0, width=0.4, facecolor="tab:blue"))
    meshes, _edges = _patch_marks(ax)
    # An annular sector traces out along one arc and back along the other, so
    # it is a single simple ring rather than a hole.
    assert len(meshes) == 1
    assert _mesh_area(meshes[0]) == pytest.approx(np.pi * (1.0**2 - 0.6**2) / 4.0, rel=1e-2)


def test_full_annulus_draws_both_outlines_without_raising() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Wedge

    _fig, ax = plt.subplots()
    ax.add_patch(Wedge((0, 0), 1.0, 0.0, 360.0, width=0.4, facecolor="tab:blue"))
    meshes, edges = _patch_marks(ax)
    assert meshes == []
    assert len(edges) == 2
    # Matplotlib repeats a vertex in its full-circle path. Leaving it in place
    # made the triangulator reject the ring, and the failure was swallowed, so
    # this asserts the repeat is gone rather than that we drew nothing.
    assert all(_shortest_relative_edge(edge) > 1e-6 for edge in edges)


def test_patch_at_genomic_coordinates_keeps_every_vertex() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((1e9, 0.0), 5000.0, 10.0, facecolor="tab:blue", edgecolor="black"))
    meshes, edges = _patch_marks(ax)
    # A magnitude-relative duplicate test collapses this to three vertices and
    # zero area, because 1e-5 of 1e9 is 10,000 data units.
    assert len(edges[0]["args"][0]) == 4
    assert _mesh_area(meshes[0]) == pytest.approx(50000.0)


def test_full_disc_wedge_fills_despite_its_repeated_vertex() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Wedge

    _fig, ax = plt.subplots()
    ax.add_patch(Wedge((0, 0), 1.0, 0.0, 360.0, facecolor="tab:blue", edgecolor="black"))
    meshes, edges = _patch_marks(ax)
    # The repeat is not bit-exact, so an exact-equality dedupe leaves it in
    # place and the triangulator rejects the whole disc.
    assert len(meshes) == 1
    assert _mesh_area(meshes[0]) == pytest.approx(np.pi, rel=1e-3)
    assert _shortest_relative_edge(edges[0]) > 1e-6


def test_tightly_spaced_but_distinct_vertices_survive() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Polygon

    _fig, ax = plt.subplots()
    ax.add_patch(
        Polygon(
            [[0, 0], [1e-9, 0], [1, 0], [1, 1], [0, 1]], facecolor="tab:blue", edgecolor="black"
        )
    )
    _meshes, edges = _patch_marks(ax)
    # A 1e-9 edge on a unit-span ring is real geometry, not floating-point
    # noise, and np.isclose's 1e-8 absolute floor would swallow it.
    assert len(edges[0]["args"][0]) == 5


@pytest.mark.parametrize("bad", [np.inf, -np.inf, np.nan])
def test_patch_with_a_non_finite_coordinate_keeps_its_vertices(bad: float) -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), bad, 1.0, fill=False))
    _meshes, edges = _patch_marks(ax)
    # The tolerance is a fraction of the ring's span, and none of these three
    # yield a usable one. They share a single guard, so what this pins is that
    # its predicate catches all three: an isnan check would let the infinities
    # through, an isinf check would let the NaN through.
    assert len(edges[0]["args"][0]) == 4


def test_patch_without_a_path_or_rectangle_getters_raises() -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(TypeError, match="unsupported patch"):
        ax.add_patch(object())


def _mesh_radii(entry: dict, radius: float) -> np.ndarray:
    """Every mesh vertex's distance from the origin, as a fraction of `radius`."""
    values = [np.asarray(entry["args"][index], dtype=np.float64) for index in range(6)]
    xs = np.concatenate(values[0::2])
    ys = np.concatenate(values[1::2])
    return np.hypot(xs, ys) / radius


@pytest.mark.parametrize("radius", [1e-3, 1.0, 1e3])
def test_patch_curves_flatten_at_output_scale_not_in_data_units(radius: float) -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Circle

    _fig, ax = plt.subplots()
    ax.add_patch(Circle((0, 0), radius, facecolor="tab:blue"))
    meshes, _edges = _patch_marks(ax)
    # `to_polygons` subdivides until flat in the units it is handed, so
    # flattening in data space made this 2.5% out at radius 1 and exact at
    # radius 1000 — the same circle on screen, drawn differently because of
    # the numbers behind it. Area hides this: the overshoot between the
    # on-curve points cancels the chord deficit, leaving 0.08% either way.
    assert _mesh_radii(meshes[0], radius).max() == pytest.approx(1.0, abs=1e-3)


def test_small_patch_at_a_large_offset_keeps_its_area() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((1e9, 0.0), 1e-4, 1e-4, facecolor="tab:blue"))
    meshes, _edges = _patch_marks(ax)
    # Flattening at output scale means a round trip through `* scale` and
    # `/ scale`. Carrying the 1e9 offset through it costs eight times more
    # area than scaling about the patch's own corner does.
    assert _mesh_area(meshes[0]) == pytest.approx(1e-8, rel=1e-3)


def test_filled_patch_with_no_edge_color_emits_no_outline_mark() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="none"))
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="red", linewidth=0))
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="red"))
    meshes, edges = _patch_marks(ax)
    # Three fills, and only the patch that actually asked for a stroke pays
    # for one. An invisible outline per ring is pure payload.
    assert len(meshes) == 3
    assert len(edges) == 1
    assert edges[0]["kwargs"]["color"] == "rgba(255,0,0,1)"


def test_invisible_patch_still_leaves_one_entry_to_hold() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    hole = [(3, 3), (3, 7), (7, 7), (7, 3), (3, 3)]
    codes = ([Path.MOVETO] + [Path.LINETO] * 3 + [Path.CLOSEPOLY]) * 2
    _fig, ax = plt.subplots()
    # Nested rings abstain from filling and the edge paints nothing, so the
    # outline is emitted anyway rather than leaving the handle with no entry.
    handle = ax.add_patch(Path and PathPatch(Path(square + hole, codes), edgecolor="none"))
    assert len(ax._entries) == 2
    handle.remove()
    assert ax._entries == []


def test_hiding_a_filled_patch_hides_its_outline_too() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    handle = ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="red"))
    handle.set_visible(False)
    # Hiding only the body left the outline drawn, so a "hidden" patch was
    # still a red rectangle on screen.
    assert [entry["kwargs"]["opacity"] for entry in ax._entries] == [0.0, 0.0]
    handle.set_visible(True)
    assert [entry["kwargs"]["opacity"] for entry in ax._entries] == [1.0, 1.0]


def test_alpha_and_color_on_a_filled_patch_reach_its_outline() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    handle = ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="red"))
    handle.set_alpha(0.25)
    assert [entry["kwargs"]["opacity"] for entry in ax._entries] == [0.25, 0.25]
    handle.set_color("green")
    # Matplotlib's Patch.set_color paints face and edge alike.
    assert {entry["kwargs"]["color"] for entry in ax._entries} == {"green"}


def test_transforming_a_filled_patch_moves_its_outline_too() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    from xy.pyplot._transforms import Affine2D

    _fig, ax = plt.subplots()
    handle = ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", edgecolor="red"))
    handle.set_transform(Affine2D().translate(10, 0))
    meshes, edges = _patch_marks(ax)
    # A transform that moved the body and left the outline behind would tear
    # the patch in two.
    assert np.asarray(meshes[0]["args"][0]).min() == pytest.approx(10.0)
    assert np.asarray(edges[0]["args"][0]).min() == pytest.approx(10.0)


def test_patch_artist_transform_rides_along() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle
    from matplotlib.transforms import Affine2D

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", transform=Affine2D().rotate_deg(90)))
    meshes, _edges = _patch_marks(ax)
    xs = np.concatenate([np.asarray(meshes[0]["args"][index]) for index in (0, 2, 4)])
    ys = np.concatenate([np.asarray(meshes[0]["args"][index]) for index in (1, 3, 5)])
    # Flattening through get_patch_transform alone drops the artist-level
    # transform and leaves the rectangle axis-aligned at x in 0..2.
    assert xs.min() == pytest.approx(-1.0)
    assert xs.max() == pytest.approx(0.0, abs=1e-9)
    assert ys.max() == pytest.approx(2.0)
    assert _mesh_area(meshes[0]) == pytest.approx(2.0)


def test_patch_transform_transdata_is_accepted_and_transaxes_rejected() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    ax.add_patch(Rectangle((0, 0), 2, 1, facecolor="tab:blue", transform=ax.transData))
    meshes, _edges = _patch_marks(ax)
    assert _mesh_area(meshes[0]) == pytest.approx(2.0)
    # Baked axes fractions go silently stale on the next limit change, so
    # this rejects like _transform_points does for every other data artist.
    with pytest.raises(NotImplementedError, match="transAxes"):
        ax.add_patch(Rectangle((0.1, 0.1), 0.5, 0.5, transform=ax.transAxes))


def test_partially_overlapping_rings_fill_instead_of_hollowing() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    left = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
    right = [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)]
    codes = ([Path.MOVETO] + [Path.LINETO] * 3 + [Path.CLOSEPOLY]) * 2
    _fig, ax = plt.subplots()
    ax.add_patch(PathPatch(Path(left + right, codes), facecolor="tab:blue"))
    meshes, _edges = _patch_marks(ax)
    # The right ring's first vertex sits inside the left ring, but the rings
    # only overlap. A first-vertex containment test called them nested and
    # hollowed the whole patch; overlap fills ring-by-ring instead.
    assert len(meshes) == 2
    assert sum(_mesh_area(mesh) for mesh in meshes) == pytest.approx(8.0)


def test_ring_past_the_triangulator_cap_says_so_instead_of_dropping_the_fill() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Polygon

    angles = np.linspace(0.0, 2.0 * np.pi, 12000, endpoint=False)
    _fig, ax = plt.subplots()
    with pytest.warns(RuntimeWarning, match="could not fill a 12000-vertex ring"):
        ax.add_patch(Polygon(np.c_[np.cos(angles), np.sin(angles)], facecolor="tab:blue"))
    meshes, edges = _patch_marks(ax)
    # Matplotlib fills this. Abstaining is defensible, doing it silently is
    # not: a hollow patch looks like a deliberate style choice.
    assert meshes == []
    assert len(edges) == 1


def test_self_intersecting_patch_says_why_it_could_not_fill() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Polygon

    _fig, ax = plt.subplots()
    with pytest.warns(RuntimeWarning, match="could not fill a 4-vertex ring"):
        ax.add_patch(Polygon([[0, 0], [2, 2], [2, 0], [0, 2]], facecolor="tab:blue"))
    assert _patch_marks(ax)[0] == []


def test_degenerate_ring_skips_its_fill_without_warning() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.patches import Rectangle

    _fig, ax = plt.subplots()
    with warnings.catch_warnings():
        # A zero-height Rectangle has no body by construction, so warning
        # about it would cry wolf on every axvline-style spacer.
        warnings.simplefilter("error")
        ax.add_patch(Rectangle((0, 0), 2, 0, facecolor="tab:blue"))
    meshes, edges = _patch_marks(ax)
    assert meshes == []
    assert len(edges) == 1


def test_masked_and_nan_lines_break_instead_of_bridging_missing_values() -> None:
    _fig, ax = plt.subplots()
    x = np.arange(5.0)
    masked = np.ma.masked_where(x == 2, x)
    ax.plot(x, masked, "o-")
    ax.plot(x, [0, 1, np.nan, 3, 4], "o-")
    segment_entries = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    assert len(segment_entries) == 2
    assert all(len(entry["args"][0]) == 2 for entry in segment_entries)


def test_line_collection_preserves_continuous_segment_colors() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots()
    collection = LineCollection(
        [[[0, 0], [1, 1]], [[1, 1], [2, 0]]], array=np.array([0.0, 1.0]), cmap="plasma"
    )
    artist = ax.add_collection(collection)
    fig.colorbar(artist, label="value")
    entry = ax._entries[-1]
    assert np.array_equal(entry["kwargs"]["color"], [0.0, 1.0])
    assert entry["kwargs"]["colormap"] == "plasma"
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["colorbar"] == {
        "colormap": "plasma",
        "domain": [0.0, 1.0],
        "label": "value",
        "orientation": "vertical",
    }


def test_colorbar_reads_original_matplotlib_scalar_mappable() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.collections import LineCollection

    fig, ax = plt.subplots()
    collection = LineCollection(
        [[[0, 0], [1, 1]], [[1, 1], [2, 0]]],
        array=np.array([0.0, 2.0]),
        cmap="plasma",
    )
    ax.add_collection(collection)
    fig.colorbar(collection)
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["colorbar"]["domain"] == [0.0, 2.0]
    assert spec["colorbar"]["colormap"] == "plasma"


def test_image_colorbar_uses_norm_domain_and_owns_its_label() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import Normalize

    fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-2.0, 0.0, 2.0]]),
        cmap=plt.colormaps["gray"].with_extremes(under="green", over="red"),
        norm=Normalize(vmin=-1.0, vmax=1.0),
    )
    colorbar = fig.colorbar(image)
    colorbar.set_label("intensity")
    spec, _ = ax._build_chart(640, 480).figure().build_payload()
    assert spec["colorbar"]["domain"] == [-1.0, 1.0]
    assert spec["colorbar"]["label"] == "intensity"
    assert ax._axis["y"].get("label") is None


def test_matplotlib_marker_sizes_are_converted_from_points_to_css_pixels() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], "o-")
    ax.scatter([0], [0])
    scatters = [entry for entry in ax._entries if entry["kind"] == "scatter"]
    # 6 pt marker path plus the centered 1 pt marker edge at figure DPI.
    assert scatters[0]["kwargs"]["size"] == pytest.approx(7 * 100 / 72)
    assert scatters[1]["kwargs"]["size"] == pytest.approx(7 * 100 / 72)


def test_explicit_line_color_does_not_advance_default_cycle() -> None:
    _fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1], color="lightgrey")
    second = ax.plot([0, 1], [1, 0])[0]
    assert second.get_color() == "#1f77b4"


def test_truecolor_imshow_keeps_rgba_channels_in_payload() -> None:
    _fig, ax = plt.subplots()
    image = np.array([[[255, 0, 0, 255], [0, 255, 0, 128]]], dtype=np.uint8)
    ax.imshow(image, interpolation="nearest")
    spec, _ = ax._build_chart(320, 200).figure().build_payload()
    heatmap = spec["traces"][0]["heatmap"]
    assert len(heatmap["rgba_bufs"]) == 4
    assert "buf" not in heatmap
    assert heatmap["h"] == 2


def test_boundary_norm_imshow_produces_discrete_truecolor_bands() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import BoundaryNorm

    cmap = plt.colormaps["gray"].with_extremes(under="green", over="red", bad="blue")
    _fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-2.0, -0.75, -0.25, 0.1, 0.75, 2.0]]),
        cmap=cmap,
        norm=BoundaryNorm([-1, -0.5, 0, 0.5, 1], ncolors=cmap.N),
    )
    rgba = np.asarray(image._entry["z"])
    assert rgba.shape == (2, 6, 4)
    assert not np.array_equal(rgba[0, 1], rgba[0, 2])
    assert np.allclose(rgba[0, 0, :3], [0.0, 128 / 255, 0.0], atol=0.02)
    assert np.allclose(rgba[0, -1, :3], [1.0, 0.0, 0.0], atol=0.02)


def test_normalize_with_extremes_remains_continuous() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.colors import Normalize

    cmap = plt.colormaps["gray"].with_extremes(under="green", over="red")
    _fig, ax = plt.subplots()
    image = ax.imshow(
        np.array([[-2.0, -0.5, 0.0, 0.5, 2.0]]),
        cmap=cmap,
        norm=Normalize(vmin=-1.0, vmax=1.0),
    )
    rgba = np.asarray(image._entry["z"])
    assert np.allclose(rgba[0, 2, :3], [0.5, 0.5, 0.5], atol=0.03)
    assert rgba[0, 1, 0] < rgba[0, 3, 0]


def test_affine_scalar_image_uses_transparent_rgba_outside_transform() -> None:
    pytest.importorskip("matplotlib")
    from matplotlib.transforms import Affine2D

    _fig, ax = plt.subplots()
    image = ax.imshow(np.arange(16, dtype=float).reshape(4, 4), origin="lower")
    image.set_transform(Affine2D().rotate_deg(30))
    rgba = np.asarray(image._entry["z"])
    assert rgba.shape == (4, 4, 4)
    assert np.any(rgba[..., 3] == 0.0)
    assert np.any(rgba[..., 3] == 1.0)


def test_filled_polygon_edge_is_one_outline_not_every_triangle_edge() -> None:
    _fig, ax = plt.subplots()
    ax.fill([0, 1, 1, 0], [0, 0, 1, 1], color="white", ec="black", lw=3)
    mesh = next(entry for entry in ax._entries if entry.get("factory") == "triangle_mesh")
    outline = next(entry for entry in ax._entries if entry.get("factory") == "segments")
    assert "stroke" not in mesh["kwargs"]
    assert len(outline["args"][0]) == 4
    assert outline["kwargs"]["width"] == 3.0


def test_streamplot_preserves_explicit_seeds_scalar_colors_and_widths() -> None:
    x = np.linspace(-1.0, 1.0, 20)
    y = np.linspace(-1.0, 1.0, 20)
    xx, yy = np.meshgrid(x, y)
    _fig, ax = plt.subplots()
    ax.streamplot(
        x,
        y,
        -yy,
        xx,
        start_points=np.array([[0.5, 0.0], [-0.5, 0.0]]),
        color=xx,
        linewidth=1.0 + np.abs(yy),
        cmap="viridis",
    )
    entries = [entry for entry in ax._entries if entry.get("factory") == "segments"]
    assert len(entries) == 1
    entry = entries[0]
    segment_count = len(entry["args"][0])
    widths = np.asarray(entry["kwargs"]["width"])
    assert segment_count > 0
    assert widths.shape == (segment_count,)
    assert np.ptp(widths) > 0
    assert entry["kwargs"].get("domain") == (-1.0, 1.0)
    assert np.ptp(np.asarray(entry["kwargs"]["color"])) > 0


def test_log_locator_contours_and_labels_use_real_contour_geometry() -> None:
    xx, yy = np.meshgrid(np.linspace(-2, 2, 40), np.linspace(-2, 2, 40))
    zz = 10.0 ** (2.0 * np.exp(-(xx**2 + yy**2)))
    _fig, ax = plt.subplots()
    contour = ax.contour(xx, yy, zz, locator=plt.LogLocator())
    labels = ax.clabel(contour, contour.levels)
    levels = np.asarray(contour.levels)
    assert np.allclose(levels, 10.0 ** np.arange(0, 3))
    positions = [label._entry["args"][:2] for label in labels]
    assert len(set(positions)) == len(positions)
    assert positions
    assert all(-2.0 <= x <= 2.0 and -2.0 <= y <= 2.0 for x, y in positions)


def test_parametric_line_preserves_input_order_instead_of_sorting_x() -> None:
    _fig, ax = plt.subplots()
    x = np.array([0.0, 1.0, 0.0, -1.0, 0.0])
    y = np.arange(len(x), dtype=float)
    ax.plot(x, y)
    trace = ax._build_chart(640, 480).figure().traces[0]
    assert trace.kind == "segments"
    assert np.array_equal(trace.x0.values, x[:-1])
    assert np.array_equal(trace.x1.values, x[1:])


def test_reversed_colormap_exact_ticks_and_fractional_annotations_export() -> None:
    fig, ax = plt.subplots()
    ax.imshow([[0.0, 1.0]], cmap="viridis_r")
    ax.set_xticks([0, 2, 4], ["zero", "two", "four"])
    ax.axhline(0.5, xmin=0.25, xmax=0.75)
    ax.text(0.5, 0.9, "axes text", transform=ax.transAxes, ha="center")
    core = ax._build_chart(640, 480).figure()
    spec, _blob = core.build_payload()
    assert spec["x_axis"]["tick_values"] == [0.0, 2.0, 4.0]
    assert spec["x_axis"]["tick_labels"] == ["zero", "two", "four"]
    assert np.array_equal(_lut("viridis_r", np.array([0.0]))[0], COLORMAP_STOPS["viridis"][-1])
    assert "axes text" in core.to_svg()
    assert fig._to_png().startswith(b"\x89PNG\r\n\x1a\n")


def test_imshow_interpolation_upsamples_gradients_but_nearest_keeps_cells() -> None:
    _fig, ax = plt.subplots()
    ax.imshow([[0.0, 1.0], [1.0, 0.0]], interpolation="bicubic")
    ax.imshow([[0.0, 1.0], [1.0, 0.0]], interpolation="nearest")
    assert np.asarray(ax._entries[0]["z"]).shape == (512, 512)
    assert np.asarray(ax._entries[1]["z"]).shape == (2, 2)
    core = ax._build_chart(640, 480).figure()
    spec, _blob = core.build_payload()
    assert spec["dom"]["style"]["--chart-grid"] == "transparent"
    assert 'stroke="transparent"' in core.to_svg()


def test_imshow_equal_aspect_preserves_explicit_extent_at_plot_edges() -> None:
    fig, ax = plt.subplots()
    ax.imshow(
        np.zeros((40, 50)),
        extent=[0, 5, 0, 5],
        origin="lower",
        interpolation="gaussian",
    )
    plt.colorbar()
    _doc, width, height = fig._to_notebook_html()
    assert (width, height) == (504, 418)
    core = ax._build_chart(width, height).figure()
    spec, _blob = core.build_payload()
    assert spec["x_axis"]["range"] == pytest.approx([0.0, 5.0])
    assert spec["y_axis"]["range"] == pytest.approx([0.0, 5.0])
    top, right, bottom, left = spec["padding"]
    # Equal x/y spans produce a square plot box after colorbar room is removed.
    assert width - left - right - 86 == pytest.approx(height - top - bottom)


def test_shared_subplots_link_live_views_and_grid_exports_keep_suptitle() -> None:
    fig, axes = plt.subplots(1, 2, sharex=True, sharey=True)
    axes[0].plot([0, 1], [0, 2])
    axes[1].plot([0, 2], [-1, 1])
    fig.suptitle("linked panels")
    figures = [chart.figure() for chart in fig._charts()]
    groups = {core.interaction.get("link_group") for core in figures}
    assert len(groups) == 1 and None not in groups
    assert all(core.interaction["link_axes"] == ["x", "y"] for core in figures)
    svg = BytesIO()
    fig.savefig(svg, format="svg")
    assert b"linked panels" in svg.getvalue()
    png = fig._to_png()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_boxplot_means_scatter_nonfinite_and_fontdict() -> None:
    _fig, ax = plt.subplots()
    box = ax.boxplot([[1, 2, 8], [2, 3, 4]], showmeans=True, meanline=True)
    assert box["means"]
    scatter = ax.scatter([0, 1, 2], [0, 1, 2], c=[0, np.nan, 2], plotnonfinite=False)
    assert len(np.asarray(scatter._entry["x"])) == 2
    text = ax.text(0, 0, "label", {"fontsize": 14, "fontfamily": "monospace"})
    assert text.get_text() == "label"
