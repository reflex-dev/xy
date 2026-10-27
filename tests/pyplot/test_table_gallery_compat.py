from __future__ import annotations

import numpy as np
import pytest

import xy.pyplot as plt


def test_table_is_axes_fraction_geometry_and_does_not_affect_data_limits() -> None:
    fig, ax = plt.subplots()
    ax.bar([10.0, 20.0], [2.0, 3.0])
    limits_before = ax.get_xlim(), ax.get_ylim()

    table = ax.table(
        cellText=[["11.0", "22.0"], ["33.0", "44.0"]],
        rowLabels=["first", "second"],
        rowColours=["#fee2e2", "#dcfce7"],
        colLabels=["A", "B"],
        cellLoc="right",
        rowLoc="left",
        colLoc="center",
    )
    fig.subplots_adjust(bottom=0.2)

    assert (ax.get_xlim(), ax.get_ylim()) == limits_before
    assert sorted(table.get_celld()) == [
        (0, 0),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
        (2, -1),
        (2, 0),
        (2, 1),
    ]
    assert {entry["kind"] for entry in ax._entries[-8:]} == {"@table_cell"}
    assert all(
        entry["kwargs"]["style"]["coordinate_space"] == "axes_fraction"
        for entry in ax._entries[-8:]
    )

    spec, _buffers = ax._build_chart(640, 480).figure().build_payload_split()
    table_annotations = [
        annotation
        for annotation in spec["annotations"]
        if annotation.get("class_name") == "xy-mpl-table-cell"
    ]
    assert len(table_annotations) == 16
    visible = [annotation for annotation in table_annotations if annotation["text"] != " "]
    assert [annotation["anchor"] for annotation in visible[:2]] == ["middle", "middle"]
    assert {annotation["anchor"] for annotation in visible[2:6]} == {"start", "end"}
    assert min(annotation["x"] for annotation in visible) < 0.0
    assert max(annotation["y"] for annotation in visible) < 0.0
    assert spec["padding"][2] >= ax._table_bottom_points * ax._point_scale()

    table.remove()
    assert ax._table_bottom_points == 0.0
    assert not any(entry["kind"] == "@table_cell" for entry in ax._entries)


def test_table_default_cells_are_readable_and_bbox_stays_inside_axes() -> None:
    _fig, ax = plt.subplots()
    ax.table(
        cellText=[["left", "center", "right"]],
        cellColours=[["#fee2e2", "#dcfce7", "#dbeafe"]],
        cellLoc="left",
        bbox=(0.1, 0.2, 0.75, 0.3),
        fontsize=9,
    )

    spec, _buffers = ax._build_chart(640, 480).figure().build_payload_split()
    table_annotations = [
        annotation
        for annotation in spec["annotations"]
        if annotation.get("class_name") == "xy-mpl-table-cell"
    ]
    boxes = [annotation for annotation in table_annotations if annotation["text"] == " "]
    labels = [annotation for annotation in table_annotations if annotation["text"] != " "]
    np.testing.assert_allclose([box["x"] for box in boxes], [0.225, 0.475, 0.725])
    np.testing.assert_allclose([box["y"] for box in boxes], [0.35, 0.35, 0.35])
    assert [box["style"]["background"] for box in boxes] == [
        "#fee2e2",
        "#dcfce7",
        "#dbeafe",
    ]
    assert [label["anchor"] for label in labels] == ["start", "start", "start"]
    assert ax._table_bottom_points == 0.0


def test_table_remove_recomputes_host_padding_for_twin_axes() -> None:
    _fig, ax = plt.subplots()
    twin = ax.twinx()
    twin_table = twin.table(cellText=[["twin"]])
    host_table = ax.table(cellText=[["host"]])

    host_table.remove()
    assert ax._table_bottom_points > 0.0

    twin_table.remove()
    assert ax._table_bottom_points == 0.0


def test_table_bbox_does_not_mutate_col_widths_array() -> None:
    _fig, ax = plt.subplots()
    col_widths = np.array([1.0, 3.0], dtype=np.float64)

    ax.table(cellText=[["a", "b"]], colWidths=col_widths, bbox=(0.0, 0.0, 1.0, 1.0))

    np.testing.assert_array_equal(col_widths, [1.0, 3.0])


@pytest.mark.parametrize("keyword", ["cellLoc", "rowLoc", "colLoc"])
def test_table_alignment_rejects_unknown_values(keyword: str) -> None:
    _fig, ax = plt.subplots()
    with pytest.raises(ValueError, match=keyword):
        ax.table(cellText=[["a"]], **{keyword: "baseline"})


@pytest.mark.parametrize("edges", ["horizontal", "vertical", "BRTL", "typo"])
def test_table_rejects_unsupported_partial_edges(edges: str) -> None:
    _fig, ax = plt.subplots()

    with pytest.raises(NotImplementedError, match=r"table\(edges=.*closed.*open"):
        ax.table(cellText=[["a"]], edges=edges)
