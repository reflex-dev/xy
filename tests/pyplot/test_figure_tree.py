"""Native figure-tree ownership and measured-export regressions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from io import BytesIO

import pytest

from xy.pyplot._mplfig import Figure


def _node(fig: Figure, owner: object):
    resolved = fig.get_figure_tree().for_owner(owner)
    assert resolved is not None
    return resolved


def test_figure_text_is_tree_owned_without_creating_axes() -> None:
    fig = Figure(1, figsize=(4, 2), dpi=100)

    text = fig.text(0.25, 0.75, "figure-owned")
    tree = fig.get_figure_tree()

    assert fig.axes == []
    assert [node.kind for node in tree.nodes] == ["figure", "figure_text"]
    text_node = tree.for_owner(text)
    assert text_node is not None
    assert text_node.parent_id == tree.root.node_id
    assert text_node.viewport == (0.25, 0.75, 0.0, 0.0)
    assert text_node.clip == (0.0, 0.0, 1.0, 1.0)
    with pytest.raises(FrozenInstanceError):
        text_node.viewport = (0.0, 0.0, 0.0, 0.0)  # ty: ignore[invalid-assignment]
    with pytest.raises(TypeError):
        text_node.metadata["entry"] = {}  # ty: ignore[invalid-assignment]

    output = BytesIO()
    fig.savefig(output, format="svg")
    assert b"figure-owned" in output.getvalue()


def test_inset_uses_parent_coordinates_but_owns_its_viewport_and_clip() -> None:
    fig = Figure(1)
    parent = fig.add_axes((0.1, 0.2, 0.4, 0.5))

    inset = parent.inset_axes((0.75, 0.5, 0.5, 0.75))
    tree = fig.get_figure_tree()
    parent_node = tree.for_owner(parent)
    inset_node = tree.for_owner(inset)

    assert parent_node is not None
    assert inset_node is not None
    assert inset_node.kind == "inset_axes"
    assert inset_node.parent_id == parent_node.node_id
    assert inset_node.viewport == pytest.approx((0.4, 0.45, 0.2, 0.375))
    # The inset extends beyond the parent axes and is clipped only by its
    # figure/subfigure container, not by the parent's data rectangle.
    assert inset_node.clip == pytest.approx(inset_node.viewport)
    assert inset_node.viewport[0] + inset_node.viewport[2] > 0.5
    assert inset.get_position().bounds == pytest.approx(inset_node.viewport)


def test_twin_and_colorbar_nodes_record_ownership_and_rendering() -> None:
    fig = Figure(1)
    host = fig.add_axes((0.2, 0.2, 0.5, 0.6))
    image = host.imshow([[0.0, 1.0], [2.0, 3.0]])
    right_axis = host.twinx()
    top_axis = host.twiny()
    colorbar = fig.colorbar(image, ax=host)

    tree = fig.get_figure_tree()
    host_node = tree.for_owner(host)
    right_node = tree.for_owner(right_axis)
    top_node = tree.for_owner(top_axis)
    colorbar_node = tree.for_owner(colorbar)

    assert host_node is not None
    assert right_node is not None
    assert top_node is not None
    assert colorbar_node is not None
    assert (
        right_node.parent_id == top_node.parent_id == colorbar_node.parent_id == host_node.node_id
    )
    assert right_node.kind == top_node.kind == "twin_axes"
    assert right_node.viewport == top_node.viewport == host_node.viewport
    assert right_node.rendered is False  # twinx is composed into the host chart.
    assert top_node.rendered is True
    assert colorbar_node.kind == "colorbar_chrome"
    assert colorbar_node.rendered is False
    assert colorbar_node.viewport[0] > host_node.viewport[0]

    explicit = fig.add_axes((0.75, 0.2, 0.04, 0.6))
    second = fig.colorbar(image, cax=explicit, ax=host)
    explicit_node = _node(fig, explicit)
    assert second.ax is explicit
    assert explicit_node.kind == "colorbar_axes"
    assert explicit_node.parent_id == _node(fig, host).node_id
    assert explicit_node.rendered is True


def test_nested_subfigures_own_axes_and_resolve_root_coordinates() -> None:
    fig = Figure(1)
    left, right = fig.subfigures(1, 2)
    top, bottom = left.subfigures(2, 1)
    ax = bottom.subplots()

    tree = fig.get_figure_tree()
    left_node = tree.for_owner(left)
    bottom_node = tree.for_owner(bottom)
    axes_node = tree.for_owner(ax)

    assert left_node is not None
    assert bottom_node is not None
    assert axes_node is not None
    assert left_node.parent_id == tree.root.node_id
    assert bottom_node.parent_id == left_node.node_id
    assert axes_node.parent_id == bottom_node.node_id
    assert left_node.viewport == pytest.approx((0.0, 0.0, 0.5, 1.0))
    assert bottom_node.viewport == pytest.approx((0.0, 0.0, 0.5, 0.5))
    assert axes_node.clip == pytest.approx(axes_node.viewport)

    assert fig.axes == [ax]
    assert bottom.axes == [ax]
    assert left.axes == right.axes == top.axes == []
    assert ax.figure is bottom
    assert ax.get_figure() is bottom
    assert ax.get_figure(root=True) is fig
    assert bottom.get_figure(root=False) is left
    assert bottom.get_figure() is fig


def test_subfigure_ratios_and_spacing_resolve_like_matplotlib_311() -> None:
    fig = Figure(1)

    subfigures = fig.subfigures(
        2,
        2,
        squeeze=False,
        width_ratios=[2, 1],
        height_ratios=[1, 3],
        wspace=0.2,
        hspace=0.3,
    )

    expected = [
        (0.0, 18 / 23, 20 / 33, 5 / 23),
        (23 / 33, 18 / 23, 10 / 33, 5 / 23),
        (0.0, 0.0, 20 / 33, 15 / 23),
        (23 / 33, 0.0, 10 / 33, 15 / 23),
    ]
    for subfigure, viewport in zip(subfigures.ravel(), expected, strict=True):
        assert subfigure.get_position().bounds == pytest.approx(viewport)


def test_subfigure_axes_measure_screen_geometry_against_the_root_canvas() -> None:
    fig = Figure(1, figsize=(8, 4), dpi=100)
    left, _right = fig.subfigures(1, 2)
    ax = left.subplots()

    metrics = ax._quiver_metrics()

    assert left.get_size_inches() == pytest.approx((4.0, 4.0))
    assert left._panel_px() == (800, 400)
    assert metrics["figure_width"] == 800
    assert metrics["figure_height"] == 400
    assert metrics["plot_width"] == pytest.approx(800 * ax.get_position().width)
    assert metrics["plot_height"] == pytest.approx(400 * ax.get_position().height)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal", adjustable="box")
    adjusted = ax.get_position()
    assert adjusted.width * 800 / (adjusted.height * 400) == pytest.approx(1.0)


@pytest.mark.parametrize("file_format", ["png", "svg", "html"])
def test_each_export_uses_one_resolved_figure_tree(
    monkeypatch: pytest.MonkeyPatch,
    file_format: str,
) -> None:
    fig = Figure(1, figsize=(4, 3), dpi=100)
    left, right = fig.subfigures(1, 2)
    left.subplots().plot([0, 1], [0, 1])
    right.subplots().plot([0, 1], [1, 0])
    real_measure = fig._measure_layout
    layouts = []

    def measured(chrome_cache=None):
        layout = real_measure(chrome_cache)
        layouts.append(layout)
        return layout

    monkeypatch.setattr(fig, "_measure_layout", measured)
    output = BytesIO()
    fig.savefig(output, format=file_format)

    assert output.getvalue()
    assert len(layouts) == 1
    snapshot = layouts[0]
    assert snapshot.canvas_size == (400, 300)
    assert snapshot.rects is not None
    assert snapshot.rects == [
        snapshot.tree.for_owner(ax).viewport  # type: ignore[union-attr]
        for ax in fig.axes
    ]


def test_tree_detaches_removed_axes_and_subfigure_clear_is_scoped() -> None:
    fig = Figure(1)
    left, right = fig.subfigures(1, 2)
    left_ax = left.subplots()
    right_ax = right.subplots()

    left.clear()

    tree = fig.get_figure_tree()
    assert tree.for_owner(left_ax) is None
    assert tree.for_owner(right_ax) is not None
    assert left.axes == []
    assert right.axes == [right_ax]
    assert fig.axes == [right_ax]


def test_removing_parent_axes_does_not_leave_orphan_tree_nodes() -> None:
    fig = Figure(1)
    host = fig.subplots()
    host.inset_axes((0.5, 0.5, 0.5, 0.5))
    host.twiny()
    host.twinx()

    fig.delaxes(host)

    assert fig.axes == []
    assert fig.get_figure_tree().axes == ()
    output = BytesIO()
    fig.savefig(output, format="png")
    assert output.getvalue().startswith(b"\x89PNG\r\n\x1a\n")
