from __future__ import annotations

import json
import struct
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import numpy as np
import pytest

from xy import _png
from xy.backends import DisplayList, DisplayListError
from xy.backends.display_list import DISPLAY_LIST_SCHEMA, PATH_COLLECTION_BATCH_SCHEMA


def test_display_list_round_trips_plain_json_and_fallback_state() -> None:
    display_list = DisplayList(320, 200, 100, metadata={"case": "roundtrip"})
    display_list.add(
        "path",
        path=[["M", 0, 0], ["L", 10, 20]],
        style={"fill": None, "stroke": [1, 0, 0, 1], "linewidth": 2},
        clip=None,
        url=None,
        gid="line",
    )

    encoded = display_list.to_json()
    decoded = json.loads(encoded)
    restored = DisplayList.from_dict(decoded)

    assert decoded["schema"] == DISPLAY_LIST_SCHEMA
    assert decoded["fallback_used"] is False
    assert decoded["fallback_reason"] is None
    assert restored.to_dict() == display_list.to_dict()


def test_png_resources_are_content_addressed_and_deduplicated() -> None:
    display_list = DisplayList(10, 10, 72)
    png = b"\x89PNG\r\n\x1a\nnot-a-real-png-but-valid-as-an-opaque-resource"

    first = display_list.add_png_resource(png, width=2, height=3)
    second = display_list.add_png_resource(png, width=2, height=3)

    assert first == second
    assert list(display_list.resources) == [first]
    assert display_list.resources[first]["sha256"]


def test_packed_array_resources_round_trip_across_svg_and_native_raster() -> None:
    display_list = DisplayList(40, 40, 72)
    triangle_data = struct.pack("<6f", 4, 4, 36, 4, 4, 36)
    color_data = struct.pack("<12f", 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1)
    triangles = display_list.add_array_resource(
        triangle_data,
        dtype="<f4",
        shape=(1, 3, 2),
    )
    assert display_list.add_array_resource(triangle_data, dtype="<f4", shape=(1, 3, 2)) == triangles
    colors = display_list.add_array_resource(
        color_data,
        dtype="<f4",
        shape=(1, 3, 4),
    )
    display_list.add(
        "gouraud_triangles",
        triangles_resource=triangles,
        colors_resource=colors,
        count=1,
        clip=None,
        gid="packed-gouraud",
    )

    restored = DisplayList.from_dict(json.loads(display_list.to_json()))
    rgba = restored.to_rgba()
    svg = restored.to_svg()

    assert len(restored.resources) == 2
    assert restored.resources[triangles]["type"] == "application/vnd.xy.ndarray"
    assert rgba[33, 7, 0] > 4 * max(rgba[33, 7, 1], rgba[33, 7, 2])
    assert svg.count("<linearGradient") == 3
    assert 'id="packed-gouraud"' in svg


def test_text_resources_are_content_addressed_bounded_and_shared_across_consumers() -> None:
    display_list = DisplayList(32, 24, 72)
    font = {
        "family": ["DejaVu Sans"],
        "style": "normal",
        "variant": "normal",
        "weight": "normal",
        "stretch": "normal",
        "size_points": 10.0,
    }
    glyph_path = [
        ["M", 4, 4],
        ["L", 12, 4],
        ["L", 12, 16],
        ["L", 4, 16],
        ["Z"],
    ]
    font_resource = display_list.add_font_resource(font)
    glyph_resource = display_list.add_path_resource(glyph_path)
    assert display_list.add_font_resource(dict(reversed(list(font.items())))) == font_resource
    assert display_list.add_path_resource(glyph_path) == glyph_resource

    style = {"fill": [0, 0, 0, 1], "stroke": None, "linewidth": 0}
    legacy = DisplayList(32, 24, 72)
    for index in range(64):
        display_list.add(
            "text",
            text="A",
            glyph_path_resource=glyph_resource,
            font_resource=font_resource,
            style=style,
            clip=None,
            url=None,
            gid=f"text-{index}",
        )
        legacy.add(
            "text",
            text="A",
            glyph_path=glyph_path,
            font=font,
            style=style,
            clip=None,
            url=None,
            gid=f"text-{index}",
        )

    restored = DisplayList.from_dict(json.loads(display_list.to_json()))
    svg = restored.to_svg()
    document = restored.to_html()
    commands = [command for command in restored.commands if command["type"] == "text"]

    assert len(restored.resources) == 2
    assert restored.font_resource(font_resource) == font
    assert restored.path_resource(glyph_resource) == glyph_path
    assert all(command["font_resource"] == font_resource for command in commands)
    assert all(command["glyph_path_resource"] == glyph_resource for command in commands)
    assert all("font" not in command and "glyph_path" not in command for command in commands)
    assert max(map(lambda command: len(json.dumps(command)), commands)) < 500
    assert svg.count('id="xy-path-resource-1"') == 1
    assert svg.count('href="#xy-path-resource-1"') == 64
    assert svg.count(f'data-font-resource="{font_resource}"') == 64
    assert f'"{font_resource}"' in document
    assert "application/vnd.xy.font+json" in document
    assert np.array_equal(restored.to_rgba(), legacy.to_rgba())
    assert np.count_nonzero(restored.to_rgba()[:, :, 3]) > 0


def test_packed_collections_match_legacy_geometry_across_consumers() -> None:
    path = [
        ["M", -2, -2],
        ["L", 2, -2],
        ["L", 2, 2],
        ["L", -2, 2],
        ["Z"],
    ]
    marker_style = {
        "fill": [0, 1, 0, 1],
        "stroke": None,
        "linewidth": 0,
        "opacity": 1,
        "antialiased": True,
    }
    red_style = {
        "fill": [1, 0, 0, 1],
        "stroke": None,
        "linewidth": 0,
        "opacity": 1,
        "antialiased": True,
    }
    blue_style = {**red_style, "fill": [0, 0, 1, 1]}
    clip = {"type": "rect", "x": 0, "y": 0, "width": 60, "height": 40}
    legacy = DisplayList(60, 40, 72)
    legacy.add(
        "marker_collection",
        path=path,
        positions=[[8, 8], [14, 8]],
        style=marker_style,
        clip=None,
        url=None,
        gid="markers",
    )
    legacy.add(
        "path_collection",
        paths=[path],
        items=[
            {
                "path": 0,
                "offset": [24, 20],
                "style": red_style,
                "clip": clip,
                "url": "https://example.test/red",
                "gid": None,
            },
            {
                "path": 0,
                "offset": [36, 20],
                "style": blue_style,
                "clip": None,
                "url": None,
                "gid": None,
            },
        ],
        gid="collection",
    )
    legacy.add(
        "quad_mesh",
        quads=[
            {
                "points": [[44, 6], [54, 6], [54, 16], [44, 16]],
                "face": [1, 1, 0, 1],
                "edge": [0, 0, 0, 1],
            }
        ],
        style={"fill": None, "stroke": None, "linewidth": 1, "antialiased": True},
        clip=None,
        gid="mesh",
    )

    packed = DisplayList(60, 40, 72)
    path_resource = packed.add_path_resource(path)
    assert packed.add_path_resource(path) == path_resource
    positions = np.asarray([[8, 8], [14, 8]], dtype="<f4")
    positions_resource = packed.add_array_resource(
        positions.tobytes(), dtype="<f4", shape=positions.shape
    )
    packed.add(
        "marker_collection",
        path_resource=path_resource,
        positions_resource=positions_resource,
        count=2,
        style=marker_style,
        clip=None,
        url=None,
        gid="markers",
    )
    instances = np.zeros((2, 24), dtype="<f4")
    instances[:, :7] = [
        [0, 24, 20, 0, 0, 0, 1],
        [0, 36, 20, 0, -1, -1, 1],
    ]
    instances[0, 7:11] = [1, 0, 0, 1]
    instances[1, 7:11] = [0, 0, 1, 1]
    instances[:, 11] = 0
    instances[:, 16:19] = [0, 1, 1]
    instances_resource = packed.add_array_resource(
        instances.tobytes(), dtype="<f4", shape=instances.shape
    )
    packed.add(
        "path_collection",
        path_resources=[path_resource],
        instances_resource=instances_resource,
        instances_schema=PATH_COLLECTION_BATCH_SCHEMA,
        count=2,
        style_templates=[{}],
        clips=[clip],
        urls=["https://example.test/red"],
        gid="collection",
    )
    points = np.asarray([[[44, 6], [54, 6], [54, 16], [44, 16]]], dtype="<f4")
    faces = np.asarray([[1, 1, 0, 1]], dtype="<f4")
    edges = np.asarray([[0, 0, 0, 1]], dtype="<f4")
    points_resource = packed.add_array_resource(points.tobytes(), dtype="<f4", shape=points.shape)
    faces_resource = packed.add_array_resource(faces.tobytes(), dtype="<f4", shape=faces.shape)
    edges_resource = packed.add_array_resource(edges.tobytes(), dtype="<f4", shape=edges.shape)
    packed.add(
        "quad_mesh",
        points_resource=points_resource,
        faces_resource=faces_resource,
        edges_resource=edges_resource,
        count=1,
        style={"fill": None, "stroke": None, "linewidth": 1, "antialiased": True},
        clip=None,
        gid="mesh",
    )

    restored = DisplayList.from_dict(json.loads(packed.to_json()))
    packed_svg = restored.to_svg()
    packed_html = restored.to_html()

    assert np.array_equal(restored.to_rgba(), legacy.to_rgba())
    assert packed_svg.count("<use") == legacy.to_svg().count("<use") == 4
    assert packed_svg.count('id="xy-path-resource-') == 1
    assert f'"{path_resource}"' in packed_html
    assert "items" not in restored.commands[1]
    assert "quads" not in restored.commands[2]


def test_svg_serializer_preserves_order_clips_and_metadata() -> None:
    display_list = DisplayList(
        100,
        80,
        100,
        metadata={"owner": "xy", "created": datetime(2026, 7, 31, tzinfo=UTC)},
    )
    clip = {"type": "rect", "x": 5, "y": 6, "width": 70, "height": 60}
    display_list.add(
        "path",
        path=[["M", 5, 6], ["L", 75, 66]],
        style={
            "fill": None,
            "stroke": [0.1, 0.2, 0.3, 0.5],
            "linewidth": 2,
            "dash": {"offset": 1, "sequence": [3, 2]},
            "join": "round",
            "cap": "butt",
        },
        clip=clip,
        url="https://example.test",
        gid="first",
    )
    display_list.add(
        "text",
        text="<label>",
        glyph_path=[["M", 10, 10], ["L", 12, 14], ["Z"]],
        style={"fill": [0, 0, 0, 1], "stroke": None, "linewidth": 0},
        clip=None,
        url=None,
        gid=None,
    )

    svg = display_list.to_svg(metadata={"case": "serializer"})
    rgba = display_list.to_rgba()

    assert "<clipPath" in svg
    assert 'clip-path="url(#xy-clip-1)"' in svg
    assert svg.index('id="first"') < svg.index('data-text="&lt;label&gt;"')
    assert '"fallback_used": false' not in svg  # compact JSON has no spaces
    assert "&quot;fallback_used&quot;:false" in svg
    assert "&quot;case&quot;:&quot;serializer&quot;" in svg
    assert "&quot;owner&quot;:&quot;xy&quot;" in svg
    assert "2026-07-31T00:00:00+00:00" in svg
    assert np.count_nonzero(rgba[:, :, 3]) > 0


def test_html_is_standalone_and_script_safe() -> None:
    display_list = DisplayList(20, 10, 72, metadata={"unsafe": "</script><script>"})

    document = display_list.to_html(title="<XY>")

    assert document.startswith("<!doctype html>")
    assert "<title>&lt;XY&gt;</title>" in document
    assert "<?xml" not in document
    assert '<script type="application/json" id="xy-display-list">' in document
    assert "</script><script>" not in document
    assert "\\u003c/script\\u003e" in document


def test_collection_clip_wraps_transformed_instances() -> None:
    display_list = DisplayList(100, 80, 100)
    display_list.add(
        "marker_collection",
        path=[["M", -1, 0], ["L", 1, 0]],
        positions=[[20, 30]],
        style={"fill": None, "stroke": [0, 0, 0, 1], "linewidth": 1},
        clip={"type": "rect", "x": 10, "y": 10, "width": 80, "height": 60},
        url=None,
        gid=None,
    )

    svg = display_list.to_svg()

    assert '<g clip-path="url(#xy-clip-1)"><use' in svg
    assert 'transform="translate(20 -30)"' in svg
    assert '<use clip-path="url(#xy-clip-1)"' not in svg


def test_native_raster_honors_rectangular_clip_and_png_dimensions() -> None:
    display_list = DisplayList(20, 12, 72)
    display_list.add(
        "path",
        path=[["M", 0, 0], ["L", 20, 0], ["L", 20, 12], ["L", 0, 12], ["Z"]],
        style={"fill": [1, 0, 0, 1], "stroke": None, "linewidth": 0},
        clip={"type": "rect", "x": 5, "y": 2, "width": 10, "height": 8},
        url=None,
        gid=None,
    )

    rgba = display_list.to_rgba()
    png = display_list.to_png()
    scaled_png = display_list.to_png(scale=2)

    assert rgba.shape == (12, 20, 4)
    assert rgba[6, 10].tolist() == [255, 0, 0, 255]
    assert rgba[0, 0].tolist() == [0, 0, 0, 0]
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (20, 12)
    assert struct.unpack(">II", scaled_png[16:24]) == (40, 24)
    assert display_list.fallback_used is False


def test_native_raster_preserves_compound_path_hole() -> None:
    display_list = DisplayList(20, 20, 72)
    display_list.add(
        "path",
        path=[
            ["M", 2, 2],
            ["L", 18, 2],
            ["L", 18, 18],
            ["L", 2, 18],
            ["Z"],
            ["M", 7, 7],
            ["L", 7, 13],
            ["L", 13, 13],
            ["L", 13, 7],
            ["Z"],
        ],
        style={"fill": [0, 0, 1, 1], "stroke": None, "linewidth": 0},
        clip=None,
        url=None,
        gid=None,
    )

    rgba = display_list.to_rgba()

    assert rgba[10, 3].tolist() == [0, 0, 255, 255]
    assert rgba[10, 10].tolist() == [0, 0, 0, 0]


@pytest.fixture
def renderer_conformance_display_list() -> DisplayList:
    display_list = DisplayList(48, 32, 72, metadata={"case": "renderer-conformance"})
    display_list.add("group_open", name="hatch", gid="hatch & clip")
    display_list.add(
        "path",
        path=[["M", 2, 2], ["L", 24, 2], ["L", 24, 30], ["L", 2, 30], ["Z"]],
        style={
            "fill": [1, 1, 1, 1],
            "stroke": [0.8, 0, 0, 1],
            "linewidth": 1,
            "hatch": "/",
            "hatch_path": [["M", -5, -5], ["L", 15, 15]],
            "hatch_tile_size": 10,
            "hatch_color": [0, 0, 0, 1],
            "hatch_linewidth": 1,
        },
        clip={
            "type": "path",
            "path": [["M", 13, 3], ["L", 23, 16], ["L", 13, 29], ["L", 3, 16], ["Z"]],
        },
        url=None,
        gid="hatched-path",
    )
    display_list.add("group_close", name="hatch")
    display_list.add(
        "gouraud_triangles",
        triangles=[[[28, 4], [46, 4], [28, 28]]],
        colors=[[[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]]],
        clip=None,
        gid="gouraud",
    )
    return display_list


def test_renderer_conformance_outputs_share_geometry_without_fallback(
    renderer_conformance_display_list: DisplayList,
) -> None:
    display_list = renderer_conformance_display_list

    rgba = display_list.to_rgba()
    png = display_list.to_png()
    svg = display_list.to_svg()
    html = display_list.to_html()
    payload = json.loads(display_list.to_json())
    _root, ids = ET.XMLID(svg)

    assert rgba.shape == (32, 48, 4)
    assert np.count_nonzero(rgba[:, :, 3]) > 200
    assert struct.unpack(">II", png[16:24]) == (48, 32)
    assert '<pattern id="xy-hatch-1"' in svg
    assert svg.count("<linearGradient") == 3
    assert '<clipPath id="xy-clip-1"' in svg
    assert ids["hatch & clip"].find("{http://www.w3.org/2000/svg}path") is not None
    assert "<svg" in html and '"type":"gouraud_triangles"' in html
    assert payload["commands"] == display_list.commands
    assert payload["fallback_used"] is False
    assert display_list.fallback_used is False


def test_native_raster_interpolates_gouraud_vertex_colors() -> None:
    display_list = DisplayList(40, 40, 72)
    display_list.add(
        "gouraud_triangles",
        triangles=[[[4, 4], [36, 4], [4, 36]]],
        colors=[[[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]]],
        clip=None,
        gid=None,
    )

    rgba = display_list.to_rgba()

    assert rgba[33, 7, 0] > 4 * max(rgba[33, 7, 1], rgba[33, 7, 2])
    assert rgba[33, 31, 1] > 4 * max(rgba[33, 31, 0], rgba[33, 31, 2])
    assert rgba[8, 7, 2] > 4 * max(rgba[8, 7, 0], rgba[8, 7, 1])
    assert len(np.unique(rgba.reshape(-1, 4), axis=0)) > 200


def test_nonrectangular_clip_is_exact_in_raster_and_svg() -> None:
    display_list = DisplayList(20, 20, 72)
    clip = {
        "type": "path",
        "path": [["M", 10, 2], ["L", 18, 10], ["L", 10, 18], ["L", 2, 10], ["Z"]],
    }
    display_list.add(
        "path",
        path=[["M", 0, 0], ["L", 20, 0], ["L", 20, 20], ["L", 0, 20], ["Z"]],
        style={"fill": [1, 0, 0, 1], "stroke": None, "linewidth": 0},
        clip=clip,
        url=None,
        gid=None,
    )

    rgba = display_list.to_rgba()
    svg = display_list.to_svg()

    assert rgba[10, 10].tolist() == [255, 0, 0, 255]
    assert rgba[3, 3].tolist() == [0, 0, 0, 0]
    assert '<clipPath id="xy-clip-1"' in svg
    assert '<path d="M10 18 L18 10 L10 2 L2 10 Z"' in svg


def test_native_raster_reuses_identical_shaped_clip_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    from xy.backends import raster

    display_list = DisplayList(80, 80, 72)
    clip = {
        "type": "path",
        "path": [["M", 40, 5], ["L", 75, 40], ["L", 40, 75], ["L", 5, 40], ["Z"]],
    }
    style = {"fill": None, "stroke": [0, 0, 0, 1], "linewidth": 2}
    for y in (20, 40, 60):
        display_list.add(
            "path",
            path=[["M", 0, y], ["L", 80, y]],
            style=style,
            clip=clip,
            url=None,
            gid=None,
        )
    original = raster._coverage_mask
    shaped_clip_calls = 0

    def tracked(*args: object, **kwargs: object) -> np.ndarray:
        nonlocal shaped_clip_calls
        contours = args[0]
        if any(closed and len(points) >= 3 for points, closed in contours):
            shaped_clip_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(raster, "_coverage_mask", tracked)

    rgba = display_list.to_rgba()

    assert shaped_clip_calls == 1
    assert np.count_nonzero(rgba[:, :, 3]) > 0


def test_hatch_pattern_preserves_fill_stroke_and_artist_order() -> None:
    display_list = DisplayList(30, 20, 72)
    path = [["M", 2, 2], ["L", 28, 2], ["L", 28, 18], ["L", 2, 18], ["Z"]]
    display_list.add(
        "path",
        path=path,
        style={"fill": [0, 0, 1, 1], "stroke": None, "linewidth": 0},
        clip=None,
        url=None,
        gid="before",
    )
    display_list.add(
        "path",
        path=path,
        style={
            "fill": [1, 1, 1, 1],
            "stroke": [1, 0, 0, 1],
            "linewidth": 1,
            "hatch": "/",
            "hatch_path": [["M", -5, -5], ["L", 15, 15]],
            "hatch_tile_size": 10,
            "hatch_color": [0, 0, 0, 1],
            "hatch_linewidth": 1,
        },
        clip=None,
        url=None,
        gid="hatched",
    )
    display_list.add(
        "path",
        path=[["M", 4, 10], ["L", 26, 10]],
        style={"fill": None, "stroke": [0, 1, 0, 1], "linewidth": 1},
        clip=None,
        url=None,
        gid="after",
    )

    rgba = display_list.to_rgba()
    svg = display_list.to_svg()

    assert len(np.unique(rgba[3:17, 3:27].reshape(-1, 4), axis=0)) >= 4
    assert '<pattern id="xy-hatch-1"' in svg
    assert 'fill="url(#xy-hatch-1)"' in svg
    assert 'stroke="#ff0000"' in svg
    assert svg.index('id="before"') < svg.index('id="hatched"') < svg.index('id="after"')


def test_svg_groups_are_nested_ordered_and_xml_safe() -> None:
    display_list = DisplayList(10, 10, 72)
    display_list.add("group_open", name="artist", gid="Line 1_shadow & blur")
    display_list.add(
        "path",
        path=[["M", 1, 1], ["L", 9, 9]],
        style={"fill": None, "stroke": [0, 0, 0, 1], "linewidth": 1},
        clip=None,
        url=None,
        gid=None,
    )
    display_list.add("group_close", name="artist")

    svg = display_list.to_svg()
    _root, ids = ET.XMLID(svg)

    group = ids["Line 1_shadow & blur"]
    assert group.tag == "{http://www.w3.org/2000/svg}g"
    assert group.find("{http://www.w3.org/2000/svg}path") is not None
    assert 'id="Line 1_shadow &amp; blur"' in svg


def test_svg_exposes_mutable_namespaced_default_style() -> None:
    display_list = DisplayList(10, 10, 72)

    root = ET.fromstring(display_list.to_svg())
    style = root.find("{http://www.w3.org/2000/svg}defs/{http://www.w3.org/2000/svg}style")

    assert style is not None
    assert style.text == "*{stroke-linejoin: round; stroke-linecap: butt}"
    style.text += "\n.histogram { stroke-width: 2; }"
    assert ".histogram" in style.text


def test_quad_mesh_does_not_inherit_missing_edges_but_keeps_explicit_edges() -> None:
    display_list = DisplayList(30, 16, 72)
    display_list.add(
        "quad_mesh",
        quads=[
            {
                "points": [[2, 2], [12, 2], [12, 14], [2, 14]],
                "face": [1, 1, 1, 1],
                "edge": None,
            },
            {
                "points": [[17, 2], [27, 2], [27, 14], [17, 14]],
                "face": [1, 1, 1, 1],
                "edge": [1, 0, 0, 1],
            },
        ],
        style={"fill": None, "stroke": [0, 0, 0, 1], "linewidth": 2},
        clip=None,
        gid=None,
    )

    rgba = display_list.to_rgba()
    root = ET.fromstring(display_list.to_svg())
    paths = root.findall("{http://www.w3.org/2000/svg}path")

    assert rgba[8, 2].tolist() == [255, 255, 255, 255]
    assert rgba[8, 17].tolist() == [255, 0, 0, 255]
    assert "stroke" not in paths[0].attrib
    assert paths[1].attrib["stroke"] == "#ff0000"


def test_edge_less_non_antialiased_quad_mesh_has_no_shared_cell_seams() -> None:
    def render(antialiased: bool) -> np.ndarray:
        display_list = DisplayList(16, 10, 72)
        display_list.add(
            "quad_mesh",
            quads=[
                {
                    "points": [[2.25, 2.25], [7.25, 2.25], [7.25, 7.25], [2.25, 7.25]],
                    "face": [1, 0, 0, 1],
                    "edge": None,
                },
                {
                    "points": [[7.25, 2.25], [12.25, 2.25], [12.25, 7.25], [7.25, 7.25]],
                    "face": [0, 0, 1, 1],
                    "edge": None,
                },
            ],
            style={
                "fill": None,
                "stroke": None,
                "linewidth": 0,
                "antialiased": antialiased,
            },
            clip=None,
            gid=None,
        )
        return display_list.to_rgba()

    crisp = render(False)
    antialiased = render(True)

    # Every pixel centre inside the half-open pair belongs to exactly one
    # opaque cell, including the shared boundary at column 7.
    assert np.all(crisp[3:8, 2:12, 3] == 255)
    assert np.all(crisp[3:8, 2:7, :3] == [255, 0, 0])
    assert np.all(crisp[3:8, 7:12, :3] == [0, 0, 255])
    # General antialiased paths retain subpixel boundary coverage.
    assert np.any(antialiased[3:8, 7, 3] < 255)


def test_affine_image_resampling_preserves_quad_shape_orientation_and_mode() -> None:
    source = np.array(
        [
            [[255, 0, 0, 255], [0, 255, 0, 255]],
            [[0, 0, 255, 255], [255, 255, 0, 255]],
        ],
        dtype=np.uint8,
    )

    def render(interpolation: str) -> tuple[DisplayList, np.ndarray]:
        display_list = DisplayList(30, 30, 72)
        resource = display_list.add_png_resource(
            _png.png_truecolor(2, 2, source),
            width=2,
            height=2,
        )
        display_list.add(
            "image",
            resource=resource,
            x=0,
            y=0,
            width=2,
            height=2,
            transform=[12, 6, -4, 12, 10, 5],
            interpolation=interpolation,
            alpha=1,
            clip=None,
            url=None,
            gid="affine-image",
        )
        return display_list, display_list.to_rgba()

    nearest_display_list, nearest = render("nearest")
    _bilinear_display_list, bilinear = render("bilinear")
    svg = nearest_display_list.to_svg()

    assert nearest[8, 7].tolist() == [0, 0, 0, 0]
    assert nearest[14, 8, :3].tolist() == [255, 0, 0]
    assert nearest[9, 17, :3].tolist() == [0, 255, 0]
    assert nearest[23, 10, :3].tolist() == [0, 0, 255]
    assert nearest[18, 20, :3].tolist() == [255, 255, 0]
    assert bilinear[17, 14, :3].tolist() == [128, 128, 96]
    assert len(np.unique(bilinear.reshape(-1, 4), axis=0)) > 100
    assert 'transform="matrix(6 -3 2 6 6 13)"' in svg
    assert "image-rendering:pixelated" in svg


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"width": 0, "height": 1, "dpi": 1}, "width"),
        ({"width": 1, "height": float("nan"), "dpi": 1}, "height"),
        (
            {
                "width": 1,
                "height": 1,
                "dpi": 1,
                "fallback_used": True,
            },
            "fallback_reason",
        ),
    ],
)
def test_display_list_rejects_invalid_contracts(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(DisplayListError, match=message):
        DisplayList(**kwargs)
