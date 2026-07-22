"""Arrow-path geometry: the label_clear start clearance (mirrored in
js/src/51_annotations.ts — keep behaviors in sync)."""

from __future__ import annotations

import math

from xy._arrowgeom import arrow_geometry


def test_label_clear_trims_start_along_departure_tangent():
    # Label extends 90px to the right of the start; a rightward arrow must
    # start past it, exactly where the tangent exits the rectangle.
    geom = arrow_geometry(0, 0, 300, 0, {"label_clear": "2.8,90,2.8,17"})
    assert math.isclose(geom["p0"][0], 90.0)
    assert geom["p0"][1] == 0.0
    assert geom["p1"] == (300, 0)


def test_label_clear_is_direction_dependent():
    # The same label, arrow leaving away from the text: only the margin side
    # of the rectangle is in the way.
    geom = arrow_geometry(0, 0, -300, 0, {"label_clear": "2.8,90,2.8,17"})
    assert math.isclose(geom["p0"][0], -2.8)


def test_label_clear_vertical_exit():
    # Downward departure exits through the rectangle's bottom extent.
    geom = arrow_geometry(0, 0, 0, 300, {"label_clear": "2.8,90,2.8,17"})
    assert math.isclose(geom["p0"][1], 17.0)


def test_label_clear_respects_larger_explicit_gap():
    geom = arrow_geometry(0, 0, 300, 0, {"label_clear": "0,10,0,0", "gap_start": 40})
    assert math.isclose(geom["p0"][0], 40.0)


def test_label_clear_malformed_values_are_ignored():
    for bad in ("", "1,2,3", "1,2,3,x", "1,2,3,-4", 12):
        geom = arrow_geometry(0, 0, 300, 0, {"label_clear": bad})
        assert geom["p0"] == (0, 0)


def test_start_offset_shifts_the_departure_point():
    # matplotlib relpos: the arrow leaves the label's box center. The offset
    # moves the start before tangents, control points, and gaps resolve.
    geom = arrow_geometry(0, 0, 300, 40, {"start_offset": "50,-7"})
    assert geom["p0"] == (50, -7)
    geom = arrow_geometry(0, 0, 300, 0, {"start_offset": "50,-7", "label_clear": "60,60,12,12"})
    assert geom["p0"][0] > 50 + 55  # trimmed from the shifted center outward


def test_start_offset_malformed_values_are_ignored():
    for bad in ("", "5", "5,x", 7):
        geom = arrow_geometry(0, 0, 300, 0, {"start_offset": bad})
        assert geom["p0"] == (0, 0)


def test_label_clear_never_swallows_short_arrows():
    # The existing trim guard: gaps close to the whole span leave the arrow
    # untrimmed instead of collapsing it.
    geom = arrow_geometry(0, 0, 50, 0, {"label_clear": "2.8,90,2.8,17"})
    assert geom["p0"] == (0, 0)
