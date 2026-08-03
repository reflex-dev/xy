from __future__ import annotations

import http.client
import io
import json
import os
import struct
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit

import pytest

IPython = pytest.importorskip("IPython")
matplotlib = pytest.importorskip("matplotlib")
np = pytest.importorskip("numpy")
FuncAnimation = pytest.importorskip("matplotlib.animation").FuncAnimation
Figure = pytest.importorskip("matplotlib.figure").Figure
Rectangle = pytest.importorskip("matplotlib.patches").Rectangle
backend_tools = pytest.importorskip("matplotlib.backend_tools")
ToolBase = backend_tools.ToolBase
ToolToggleBase = backend_tools.ToolToggleBase
font_manager = pytest.importorskip("matplotlib.font_manager")
FontProperties = font_manager.FontProperties
get_font = font_manager.get_font
fontManager = font_manager.fontManager
LoadFlags = pytest.importorskip("matplotlib.ft2font").LoadFlags
Bbox = pytest.importorskip("matplotlib.transforms").Bbox
backend_xy = pytest.importorskip("xy.backends.backend_xy")
FigureCanvasXY = backend_xy.FigureCanvasXY
NavigationToolbar2XY = backend_xy.NavigationToolbar2XY
RendererXY = backend_xy.RendererXY
TimerXY = backend_xy.TimerXY
ToolbarXY = backend_xy.ToolbarXY


def _mixed_figure() -> tuple[Figure, FigureCanvasXY]:
    figure = Figure(figsize=(4, 3), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.plot([0, 1, 2], [0, 1, 0], marker="o", label="line")
    axes.scatter([0.5, 1.5], [0.2, 0.7], c=["red", "blue"])
    axes.imshow(np.arange(4).reshape(2, 2), extent=(0.1, 0.4, 0.1, 0.4))
    axes.set_title(r"$x^2$ and text")
    axes.legend()
    return figure, canvas


def test_renderer_records_device_space_primitives_without_fallback() -> None:
    _figure, canvas = _mixed_figure()

    canvas.draw()

    assert isinstance(canvas.renderer, RendererXY)
    display_list = canvas.renderer.display_list
    command_types = Counter(command["type"] for command in display_list.commands)
    assert command_types["path"] > 0
    assert command_types["marker_collection"] > 0
    assert command_types["path_collection"] > 0
    assert command_types["image"] == 1
    assert command_types["text"] > 0
    assert display_list.width == 400
    assert display_list.height == 300
    assert display_list.fallback_used is False
    assert canvas.fallback_used is False
    text_commands = [
        command
        for command in display_list.commands
        if command["type"] == "text" and command["text"].strip()
    ]
    assert all(
        display_list.path_resource(command["glyph_path_resource"]) for command in text_commands
    )
    assert all(display_list.font_resource(command["font_resource"]) for command in text_commands)
    assert all("glyph_path" not in command and "font" not in command for command in text_commands)


def test_canvas_rejects_three_dimensional_axes() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    figure.add_subplot(projection="3d")

    with pytest.raises(NotImplementedError, match="does not support three-dimensional axes"):
        canvas.draw()


def test_canvas_rejects_three_dimensional_axes_added_by_draw_callback() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    figure.subplots().plot([0, 1], [0, 1])

    def add_three_dimensional_axes(_event: object) -> None:
        figure.add_subplot(projection="3d")

    canvas.mpl_connect("draw_event", add_three_dimensional_axes)

    with pytest.raises(NotImplementedError, match="does not support three-dimensional axes"):
        canvas.draw()

    assert any(axes.name == "3d" for axes in figure.axes)
    assert canvas._draw_generation == 0


def test_figure_agg_filter_executes_and_changes_xy_output_without_fallback() -> None:
    figure = Figure(figsize=(2, 2), dpi=50, facecolor="white")
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.set_axis_off()
    axes.imshow(np.full((8, 8, 3), [1.0, 0.0, 0.0]))
    canvas.draw()
    assert canvas.renderer is not None
    renderer = canvas.renderer
    unfiltered = renderer.display_list.to_rgba()
    calls: list[tuple[tuple[int, ...], float]] = []

    def blue_filter(image: np.ndarray, dpi: float) -> tuple[np.ndarray, int, int]:
        calls.append((image.shape, dpi))
        filtered = image.copy()
        filtered[..., :3] = [0.0, 0.0, 1.0]
        return filtered, 0, 0

    figure.set_agg_filter(blue_filter)
    canvas.draw()

    assert canvas.renderer is renderer
    display_list = renderer.display_list
    filtered = display_list.to_rgba()
    assert calls == [((100, 100, 4), 50.0)]
    assert [command["type"] for command in display_list.commands] == ["image"]
    assert not np.array_equal(filtered, unfiltered)
    assert np.all(filtered[..., :3] == [0, 0, 255])
    assert "<image" in display_list.to_svg()
    assert display_list.fallback_used is False
    assert canvas.fallback_used is False

    figure.set_agg_filter(None)
    canvas.draw()

    assert renderer._filter_display_lists == []
    assert any(command["type"] == "path" for command in renderer.display_list.commands)
    assert np.array_equal(renderer.display_list.to_rgba(), unfiltered)
    assert canvas.fallback_used is False


def test_agg_filter_exception_restores_renderer_state() -> None:
    figure = Figure(figsize=(2, 1), dpi=72)
    canvas = FigureCanvasXY(figure)
    figure.subplots().plot([0, 1], [0, 1])

    def failing_filter(image: np.ndarray, dpi: float) -> tuple[np.ndarray, int, int]:
        raise RuntimeError("filter failed")

    figure.set_agg_filter(failing_filter)
    with pytest.raises(RuntimeError, match="filter failed"):
        canvas.draw()

    assert canvas.renderer is not None
    renderer = canvas.renderer
    assert renderer._filter_display_lists == []

    figure.set_agg_filter(None)
    canvas.draw()

    assert any(command["type"] == "path" for command in renderer.display_list.commands)
    assert renderer.display_list.fallback_used is False


def test_plain_text_metrics_match_configured_freetype_hinting() -> None:
    renderer = RendererXY(200, 100, 100)
    properties = FontProperties(family="DejaVu Sans", size=12)
    font = get_font(fontManager._find_fonts_by_props(properties))
    font.clear()
    font.set_size(properties.get_size_in_points(), renderer.dpi)
    font.set_text("narrow 111", 0, flags=LoadFlags.FORCE_AUTOHINT)
    width, height = font.get_width_height()
    expected = width / 64, height / 64, font.get_descent() / 64

    with matplotlib.rc_context({"text.hinting": "force_autohint"}):
        actual = renderer.get_text_width_height_descent(
            "narrow 111",
            properties,
            ismath=False,
        )

    assert actual == expected


def test_tex_path_keeps_explicit_absolute_font_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_scales: list[float] = []

    def fake_text_path(
        text_to_path: object,
        prop: object,
        text: str,
        ismath: object = False,
        *,
        features: object = None,
        language: object = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        observed_scales.append(float(text_to_path.FONT_SCALE))
        assert text == r"\font\a ptmr8r at 14pt\a Nimbus"
        assert ismath == "TeX"
        return (
            np.asarray([[0, 0], [14, 0], [14, 14], [0, 14], [0, 0]], dtype=float),
            np.asarray([1, 2, 2, 2, 79], dtype=np.uint8),
        )

    monkeypatch.setattr(backend_xy.TextToPath, "get_text_path", fake_text_path)
    renderer = RendererXY(200, 100, 100)
    original_scale = renderer._text2path.FONT_SCALE
    properties = FontProperties(size=10)

    renderer.draw_tex(
        renderer.new_gc(),
        5,
        7,
        r"\font\a ptmr8r at 14pt\a Nimbus",
        properties,
        0,
    )

    command = next(
        command for command in renderer.display_list.commands if command["type"] == "text"
    )
    glyph_path = renderer.display_list.path_resource(command["glyph_path_resource"])
    coordinates = [value for segment in glyph_path for value in segment[1:]]
    xs = coordinates[0::2]
    ys = coordinates[1::2]
    assert observed_scales == [10]
    assert max(xs) - min(xs) == pytest.approx(14 * 100 / 72)
    assert max(ys) - min(ys) == pytest.approx(14 * 100 / 72)
    assert renderer._text2path.FONT_SCALE == original_scale == 100


@pytest.mark.parametrize(
    ("shading", "command_type", "expected_count"),
    [
        ("flat", "quad_mesh", 9),
        ("gouraud", "gouraud_triangles", 16),
    ],
)
def test_renderer_records_mesh_batches(
    shading: str,
    command_type: str,
    expected_count: int,
) -> None:
    figure = Figure(figsize=(3, 2), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.pcolormesh(np.arange(9).reshape(3, 3), shading=shading)

    canvas.draw()

    command = next(
        command
        for command in canvas.renderer.display_list.commands
        if command["type"] == command_type
    )
    actual_count = command.get("count")
    if actual_count is None:
        actual_count = len(command["triangles"])
    assert actual_count == expected_count
    assert "<path" in canvas.renderer.display_list.to_svg()
    rgba = canvas.renderer.display_list.to_rgba()
    assert rgba.shape == (200, 300, 4)
    assert np.any(rgba[:, :, :3] != 255)


def test_large_gouraud_mesh_uses_packed_resources_and_vectorized_raster() -> None:
    figure = Figure(figsize=(3, 2), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    values = np.arange(40 * 40, dtype=float).reshape(40, 40)
    axes.pcolormesh(values, shading="gouraud")

    canvas.draw()

    assert canvas.renderer is not None
    command = next(
        command
        for command in canvas.renderer.display_list.commands
        if command["type"] == "gouraud_triangles"
    )
    assert command["count"] == 4 * 39 * 39
    assert "triangles" not in command
    assert "colors" not in command
    assert command["triangles_resource"] in canvas.renderer.display_list.resources
    assert command["colors_resource"] in canvas.renderer.display_list.resources
    assert {
        canvas.renderer.display_list.resources[command[resource_key]]["type"]
        for resource_key in ("triangles_resource", "colors_resource")
    } == {"application/vnd.xy.ndarray"}
    rgba = canvas.renderer.display_list.to_rgba()
    assert rgba.shape == (200, 300, 4)
    assert len(np.unique(rgba.reshape(-1, 4), axis=0)) > 100
    assert canvas.fallback_used is False


def test_large_marker_and_path_collections_have_bounded_packed_commands() -> None:
    figure = Figure(figsize=(3, 2), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    values = np.linspace(0, 1, 10_000)
    axes.plot(values, values, marker="o", markersize=2)
    axes.scatter(values, 1 - values, s=4, c=values)

    canvas.draw()

    assert canvas.renderer is not None
    display_list = canvas.renderer.display_list
    marker = max(
        (command for command in display_list.commands if command["type"] == "marker_collection"),
        key=lambda command: command["count"],
    )
    collection = max(
        (command for command in display_list.commands if command["type"] == "path_collection"),
        key=lambda command: command["count"],
    )
    assert marker["count"] == 10_000
    assert "positions" not in marker
    assert "path" not in marker
    assert len(json.dumps(marker)) < 2_000
    assert collection["count"] == 10_000
    assert "items" not in collection
    assert "paths" not in collection
    assert len(collection["style_templates"]) <= 2
    assert len(json.dumps(collection)) < 4_000
    marker_positions = display_list.resources[marker["positions_resource"]]
    collection_instances = display_list.resources[collection["instances_resource"]]
    assert marker_positions["shape"] == [10_000, 2]
    assert collection_instances["shape"] == [10_000, 24]
    assert display_list.resources[marker["path_resource"]]["type"].endswith("path+json")
    assert all(
        display_list.resources[path_resource]["type"].endswith("path+json")
        for path_resource in collection["path_resources"]
    )


def test_large_flat_quad_mesh_has_bounded_packed_resources() -> None:
    figure = Figure(figsize=(3, 2), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.pcolormesh(np.arange(100 * 100, dtype=float).reshape(100, 100), shading="flat")

    canvas.draw()

    assert canvas.renderer is not None
    display_list = canvas.renderer.display_list
    command = next(command for command in display_list.commands if command["type"] == "quad_mesh")
    assert command["count"] == 10_000
    assert "quads" not in command
    assert len(json.dumps(command)) < 2_000
    assert display_list.resources[command["points_resource"]]["shape"] == [10_000, 4, 2]
    assert display_list.resources[command["faces_resource"]]["shape"] == [10_000, 4]
    assert command["edges_resource"] is None


def test_canvas_emits_standalone_svg_html_and_json() -> None:
    _figure, canvas = _mixed_figure()
    svg_output = io.StringIO()
    html_output = io.StringIO()
    json_output = io.StringIO()

    canvas.print_svg(svg_output, metadata={"Title": "backend smoke"})
    canvas.print_html(html_output, title="backend smoke")
    canvas.print_json(json_output)

    svg = svg_output.getvalue()
    html = html_output.getvalue()
    payload = json.loads(json_output.getvalue())
    assert svg.startswith('<?xml version="1.0"')
    assert "<path" in svg
    assert "data:image/png;base64," in svg
    assert "&quot;fallback_used&quot;:false" in svg
    assert html.startswith("<!doctype html>")
    assert "<svg" in html
    assert payload["schema"] == "xy.display-list/1"
    assert payload["fallback_used"] is False


def test_figure_savefig_uses_xy_svg_print_method() -> None:
    figure, canvas = _mixed_figure()
    output = io.BytesIO()

    figure.savefig(output, format="svg", backend="module://xy.backends.backend_xy")

    assert output.getvalue().startswith(b'<?xml version="1.0"')
    assert canvas.fallback_used is False


def test_savefig_without_extension_uses_matplotlib_default_png(tmp_path: Path) -> None:
    figure = Figure(figsize=(2, 1), dpi=72)
    FigureCanvasXY(figure)
    figure.subplots().plot([0, 1], [0, 1])
    target = tmp_path / "default-format"

    with matplotlib.rc_context({"savefig.format": "png"}):
        assert FigureCanvasXY.get_default_filetype() == "png"
        figure.savefig(target)

    output = tmp_path / "default-format.png"
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_png_uses_xy_rasterizer_with_expected_dimensions_and_nonblank_output() -> None:
    figure, canvas = _mixed_figure()
    output = io.BytesIO()

    figure.savefig(output, format="png")

    png = output.getvalue()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (400, 300)
    assert "png" in canvas.get_supported_filetypes()
    assert canvas.renderer is not None
    rgba = canvas.renderer.display_list.to_rgba()
    assert rgba.shape == (300, 400, 4)
    assert np.any(rgba[:, :, :3] != 255)
    assert len(np.unique(rgba.reshape(-1, 4), axis=0)) > 20
    assert canvas.renderer.display_list.fallback_used is False
    assert canvas.fallback_used is False


def test_draw_callbacks_and_headless_timer_protocol() -> None:
    figure = Figure()
    canvas = FigureCanvasXY(figure)
    draw_events: list[object] = []
    canvas.mpl_connect("draw_event", draw_events.append)
    timer_calls: list[str] = []
    timer = canvas.new_timer(interval=5)
    timer.add_callback(lambda: timer_calls.append("tick") or False)

    canvas.draw()
    timer.start()
    remains_active = timer.fire()

    assert len(draw_events) == 1
    assert isinstance(timer, TimerXY)
    assert timer_calls == ["tick"]
    assert remains_active is False
    assert timer.running is False


def test_timer_callback_may_flush_events_without_recursive_redispatch() -> None:
    figure = Figure()
    canvas = FigureCanvasXY(figure)
    timer = canvas.new_timer(interval=1)
    calls: list[str] = []

    def callback() -> None:
        calls.append("tick")
        canvas.flush_events()
        timer.stop()

    timer.add_callback(callback)
    timer.start()

    assert timer.fire() is False
    assert calls == ["tick"]
    assert timer.running is False


def test_manager_show_displays_cached_live_widget_in_ipython(monkeypatch) -> None:
    figure = Figure(figsize=(2, 1), dpi=100)
    canvas = FigureCanvasXY(figure)
    manager = backend_xy.FigureManagerXY(canvas, 7)
    widget = canvas.widget
    displayed: list[object] = []
    ipython = ModuleType("IPython")
    ipython.get_ipython = lambda: object()
    display_module = ModuleType("IPython.display")
    display_module.display = displayed.append
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)

    manager.show()
    manager.show()

    assert displayed == [widget]
    assert manager.widget is widget
    manager.destroy()


def test_manager_show_opens_authenticated_live_loopback_browser_host(monkeypatch) -> None:
    figure = Figure(figsize=(2, 1), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [0, 1])
    manager = backend_xy.FigureManagerXY(canvas, 8)
    opened: list[str] = []
    monkeypatch.setattr(IPython, "get_ipython", lambda: None)
    monkeypatch.setattr(backend_xy.webbrowser, "open", lambda url: opened.append(url) or True)

    manager.show()
    manager.show()
    assert manager._browser_host is not None
    host = manager._browser_host
    parsed = urlsplit(host.url)
    assert parsed.hostname == "127.0.0.1"
    assert len(parsed.path.strip("/")) == 64
    assert opened == [host.url]

    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    connection.request("GET", parsed.path)
    response = connection.getresponse()
    document = response.read().decode()
    assert response.status == 200
    assert "default-src 'none'" in response.getheader("Content-Security-Policy", "")
    assert "./host.js" in document

    connection.request("GET", "/not-the-token/state")
    response = connection.getresponse()
    response.read()
    assert response.status == 404

    connection.request("GET", f"{parsed.path}event")
    response = connection.getresponse()
    response.read()
    assert response.status == 405

    connection.request(
        "POST",
        f"{parsed.path}event",
        body="{}",
        headers={"Content-Type": "text/plain"},
    )
    response = connection.getresponse()
    response.read()
    assert response.status == 415

    oversized = b" " * (64 * 1024 + 1)
    connection.request(
        "POST",
        f"{parsed.path}event",
        body=oversized,
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    response.read()
    assert response.status == 413

    connection.request("GET", f"{parsed.path}state")
    response = connection.getresponse()
    original = json.loads(response.read())
    assert response.status == 200

    connection.request(
        "GET",
        f"{parsed.path}state?generation={original['generation']}",
    )
    response = connection.getresponse()
    unchanged = json.loads(response.read())
    assert response.status == 200
    assert "svg" not in unchanged
    assert unchanged["generation"] == original["generation"]

    callback_threads: list[int] = []
    keys: list[str] = []
    canvas.mpl_connect(
        "key_press_event",
        lambda event: (keys.append(event.key), callback_threads.append(threading.get_ident())),
    )
    body = json.dumps({"type": "event", "name": "key_press_event", "key": "a"})
    connection.request(
        "POST",
        f"{parsed.path}event",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    response.read()
    assert response.status == 202
    assert keys == []
    canvas.flush_events()
    assert keys == ["a"]
    assert callback_threads == [threading.get_ident()]

    line.set_ydata([1, 0])
    canvas.draw_idle()
    connection.request("GET", f"{parsed.path}state")
    response = connection.getresponse()
    refreshed = json.loads(response.read())
    connection.close()

    assert refreshed["generation"] > original["generation"]
    assert refreshed["svg"] != original["svg"]
    manager.destroy()
    assert host.closed is True
    assert host._thread.is_alive() is False


def test_manager_main_loop_advances_timers_until_idle(monkeypatch) -> None:
    from matplotlib._pylab_helpers import Gcf

    figure = Figure()
    canvas = FigureCanvasXY(figure)
    manager = backend_xy.FigureManagerXY(canvas, 9)
    calls: list[int] = []
    timer = canvas.new_timer(interval=1)

    def callback() -> bool:
        calls.append(len(calls) + 1)
        return len(calls) < 3

    timer.add_callback(callback)
    timer.start()
    monkeypatch.setattr(Gcf, "get_all_fig_managers", staticmethod(lambda: [manager]))

    manager.start_main_loop()

    assert calls == [1, 2, 3]
    assert timer.running is False
    manager.destroy()


def test_canvas_region_copy_restore_publishes_incremental_display_list() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [0, 1], animated=True)
    canvas.draw()
    generation = canvas._draw_generation
    assert canvas.renderer is not None

    region = canvas.copy_from_bbox(axes.bbox)
    canvas.restore_region(region)
    line.set_ydata([1, 0])
    axes.draw_artist(line)
    canvas.blit(axes.bbox)
    incremental = canvas.renderer.display_list.to_rgba()

    assert region.bbox == tuple(float(value) for value in axes.bbox.extents)
    assert region.generation == generation
    assert canvas._draw_generation == generation + 1
    assert [command["type"] for command in canvas.renderer.display_list.commands] == ["image"]
    assert len(canvas.renderer.display_list.resources) == 1
    assert canvas.fallback_used is False

    line.set_animated(False)
    canvas.draw()
    reference = canvas.renderer.display_list.to_rgba()
    assert np.array_equal(incremental, reference)


def test_canvas_region_restore_preserves_an_independent_axes_overlay() -> None:
    figure = Figure(figsize=(4, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    left, right = figure.subplots(1, 2)
    (left_line,) = left.plot([0, 1], [0, 1], color="red", animated=True)
    (right_line,) = right.plot([0, 1], [1, 0], color="blue", animated=True)
    canvas.draw()
    left_background = canvas.copy_from_bbox(left.bbox)
    right_background = canvas.copy_from_bbox(right.bbox)

    canvas.restore_region(left_background)
    left_line.set_ydata([0.2, 0.8])
    left.draw_artist(left_line)
    canvas.blit(left.bbox)
    canvas.restore_region(right_background)
    right_line.set_ydata([0.8, 0.2])
    right.draw_artist(right_line)
    canvas.blit(right.bbox)
    before_left_update = canvas.renderer.display_list.to_rgba()

    canvas.restore_region(left_background)
    left_line.set_ydata([0.8, 0.2])
    left.draw_artist(left_line)
    canvas.blit(left.bbox)
    incremental = canvas.renderer.display_list.to_rgba()

    height = incremental.shape[0]
    right_left, right_bottom, right_right, right_top = canvas._pixel_bounds(
        right.bbox,
        incremental.shape[1],
        height,
    )
    assert np.array_equal(
        incremental[height - right_top : height - right_bottom, right_left:right_right],
        before_left_update[
            height - right_top : height - right_bottom,
            right_left:right_right,
        ],
    )
    assert [command["type"] for command in canvas.renderer.display_list.commands] == ["image"]
    assert len(canvas.renderer.display_list.resources) == 1

    left_line.set_animated(False)
    right_line.set_animated(False)
    canvas.draw()
    reference = canvas.renderer.display_list.to_rgba()
    differing = np.abs(incremental.astype(int) - reference.astype(int))
    assert np.count_nonzero(differing) <= 4


def test_canvas_work_surface_survives_interleaved_partial_blits_and_copies() -> None:
    figure = Figure(figsize=(4, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    left, right = figure.subplots(1, 2)
    (left_line,) = left.plot([0, 1], [1, 0], color="red", animated=True)
    (right_line,) = right.plot([0, 1], [0, 1], color="blue", animated=True)
    canvas.draw()
    left_background = canvas.copy_from_bbox(left.bbox)
    right_background = canvas.copy_from_bbox(right.bbox)

    canvas.restore_region(left_background)
    canvas.restore_region(right_background)
    left.draw_artist(left_line)
    right.draw_artist(right_line)
    canvas.blit(left.bbox)

    assert canvas._blit_work is not None
    assert canvas._blit_front is not None
    right_left, right_top, right_right, right_bottom = right_background.pixel_bounds
    rows = slice(right_top, right_bottom)
    columns = slice(right_left, right_right)
    assert not np.array_equal(
        canvas._blit_front[rows, columns],
        canvas._blit_work[rows, columns],
    )

    # A background copy reads renderer WORK, including the as-yet-unpresented
    # right artist, rather than accidentally sampling browser FRONT.
    copied = canvas.copy_from_bbox(right.bbox)
    assert np.array_equal(copied.pixels, canvas._blit_work[rows, columns])
    canvas.blit(right.bbox)
    assert np.array_equal(
        canvas._blit_front[rows, columns],
        canvas._blit_work[rows, columns],
    )


def test_canvas_repeated_region_blits_are_bounded_without_full_redraws() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [0, 1], animated=True)
    draw_events: list[int] = []
    canvas.mpl_connect("draw_event", lambda _event: draw_events.append(1))
    canvas.draw()
    background = canvas.copy_from_bbox(axes.bbox)

    for index in range(20):
        canvas.restore_region(background)
        line.set_ydata([index / 20, 1 - index / 20])
        axes.draw_artist(line)
        canvas.blit(axes.bbox)
        assert [command["type"] for command in canvas.renderer.display_list.commands] == ["image"]
        assert len(canvas.renderer.display_list.resources) == 1

    assert len(draw_events) == 1
    assert canvas._draw_generation == 21


def test_canvas_full_draw_repairs_a_partial_blit_from_draw_event() -> None:
    figure = Figure(figsize=(2, 2), dpi=72, facecolor="red")
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    canvas.mpl_connect("draw_event", lambda _event: canvas.blit(axes.bbox))

    canvas.draw()

    published = canvas.renderer.display_list.to_rgba()
    assert canvas._blit_work is not None
    assert canvas._blit_front is not None
    assert np.array_equal(published, canvas._blit_work)
    assert np.array_equal(published, canvas._blit_front)
    assert published[0, 0].tolist() == [255, 0, 0, 255]


def test_canvas_full_draw_publishes_a_restore_from_draw_event() -> None:
    figure = Figure(figsize=(1, 1), dpi=50, facecolor="red")
    canvas = FigureCanvasXY(figure)
    canvas.draw()
    red = canvas.copy_from_bbox(figure.bbox)
    figure.set_facecolor("blue")
    canvas.mpl_connect("draw_event", lambda _event: canvas.restore_region(red))

    canvas.draw()

    published = canvas.renderer.display_list.to_rgba()
    assert canvas._blit_work is not None
    assert canvas._blit_front is not None
    assert np.array_equal(published, canvas._blit_work)
    assert np.array_equal(published, canvas._blit_front)
    assert published[0, 0].tolist() == [255, 0, 0, 255]


def test_canvas_full_draw_reconciles_a_draw_event_resize() -> None:
    figure = Figure(figsize=(2, 2), dpi=50, facecolor="red")
    canvas = FigureCanvasXY(figure)
    resize_events = 0

    def resize_once(_event: object) -> None:
        nonlocal resize_events
        resize_events += 1
        figure.set_size_inches(3, 3, forward=False)
        canvas.get_renderer()

    canvas.mpl_connect("draw_event", resize_once)
    canvas.draw()

    assert resize_events == 2
    assert canvas.renderer is not None
    assert canvas._renderer_key(canvas.renderer) == (150.0, 150.0, 50.0)
    assert canvas._blit_renderer_key == (150.0, 150.0, 50.0)
    assert canvas.renderer.display_list.commands
    rendered = canvas.renderer.display_list.to_rgba()
    assert rendered.shape == (150, 150, 4)
    assert rendered[0, 0].tolist() == [255, 0, 0, 255]


def test_canvas_nested_draw_event_preserves_the_outer_incremental_state() -> None:
    figure = Figure(figsize=(1, 1), dpi=50, facecolor="red")
    canvas = FigureCanvasXY(figure)
    canvas.draw()
    red = canvas.copy_from_bbox(figure.bbox)
    figure.set_facecolor("blue")
    nested = False

    def nested_draw_then_restore(_event: object) -> None:
        nonlocal nested
        if nested:
            return
        nested = True
        canvas.draw()
        canvas.restore_region(red)

    canvas.mpl_connect("draw_event", nested_draw_then_restore)
    canvas.draw()

    published = canvas.renderer.display_list.to_rgba()
    assert canvas._full_draw_depth == 0
    assert canvas._blit_work is not None
    assert canvas._blit_front is not None
    assert np.array_equal(published, canvas._blit_work)
    assert np.array_equal(published, canvas._blit_front)
    assert published[0, 0].tolist() == [255, 0, 0, 255]


def test_canvas_transparent_region_restore_source_replaces_pixels() -> None:
    figure = Figure(figsize=(1, 1), dpi=50, facecolor="none")
    canvas = FigureCanvasXY(figure)
    canvas.draw()
    transparent = canvas.copy_from_bbox(figure.bbox)
    assert np.count_nonzero(transparent.pixels[:, :, 3]) == 0

    figure.set_facecolor("red")
    canvas.draw()
    assert np.all(canvas.renderer.display_list.to_rgba()[:, :, 3] == 255)
    canvas.restore_region(transparent)
    canvas.blit(figure.bbox)

    restored = canvas.renderer.display_list.to_rgba()
    assert np.count_nonzero(restored[:, :, 3]) == 0


def test_canvas_partial_region_restore_honors_bbox_and_xy() -> None:
    figure = Figure(figsize=(2, 2), dpi=50)
    canvas = FigureCanvasXY(figure)
    for xy, color in (
        ((0, 0), "red"),
        ((0.5, 0), "green"),
        ((0, 0.5), "blue"),
        ((0.5, 0.5), "yellow"),
    ):
        figure.add_artist(
            Rectangle(
                xy,
                0.5,
                0.5,
                transform=figure.transFigure,
                facecolor=color,
                edgecolor="none",
            )
        )
    canvas.draw()
    original = canvas.renderer.display_list.to_rgba()
    region = canvas.copy_from_bbox(Bbox.from_extents(10, 10, 90, 70))
    assert region.pixel_bounds == (10, 30, 90, 90)
    assert region.get_extents() == (10, 30, 90, 90)

    for patch in figure.artists:
        patch.set_facecolor("black")
    canvas.draw()
    changed = canvas.renderer.display_list.to_rgba()
    source = (30, 40, 49, 59)
    # Advanced restore coordinates are top-origin.  Relative to the region's
    # (10, 30) origin, this source begins at (20, 10), so an anchor of (5, 7)
    # places the 20x20 destination at top-origin (25, 17).
    destination = Bbox.from_extents(25, 63, 45, 83)
    canvas.restore_region(region, bbox=source, xy=(5, 7))
    canvas.blit(destination)
    restored = canvas.renderer.display_list.to_rgba()

    # Match RendererAgg's BufferRegion convention: advanced source and
    # destination coordinates are top-origin buffer coordinates.
    assert np.array_equal(restored[17:37, 25:45], original[40:60, 30:50])
    outside = np.ones(restored.shape[:2], dtype=bool)
    outside[17:37, 25:45] = False
    assert np.array_equal(restored[outside], changed[outside])


def test_canvas_region_retains_out_of_bounds_extent_and_buffer_shape() -> None:
    figure = Figure(figsize=(2, 2), dpi=50, facecolor="red")
    canvas = FigureCanvasXY(figure)
    canvas.draw()

    region = canvas.copy_from_bbox(Bbox.from_extents(-10, -20, 40, 30))

    assert region.get_extents() == (-10, 70, 40, 120)
    assert region.pixels.shape == (50, 50, 4)
    assert np.count_nonzero(region.pixels[30:, :, 3]) == 0
    assert np.count_nonzero(region.pixels[:, :10, 3]) == 0
    assert np.all(region.pixels[:30, 10:, 3] == 255)
    array = np.asarray(region)
    buffer = memoryview(region)
    assert array.shape == (50, 50, 4)
    assert array.dtype == np.uint8
    assert array.flags.writeable
    assert buffer.shape == (50, 50, 4)
    assert buffer.format == "B"
    assert not buffer.readonly
    assert bool(region) is True
    assert region == region
    assert region != region.copy()
    assert hash(region) == hash(region)
    array[0, 0] = [1, 2, 3, 4]
    assert region.pixels[0, 0].tolist() == [1, 2, 3, 4]
    region.set_x(5)
    region.set_y(7)
    assert region.get_extents() == (5, 7, 40, 120)
    with pytest.raises(TypeError):
        region.set_x(5.9)
    with pytest.raises(TypeError):
        region.set_y(7.9)


def test_canvas_region_set_position_preserves_the_pixel_buffer_dimensions() -> None:
    figure = Figure(figsize=(2, 2), dpi=50, facecolor="red")
    canvas = FigureCanvasXY(figure)
    canvas.draw()
    region = canvas.copy_from_bbox(Bbox.from_extents(10, 10, 90, 90))
    region.set_x(5)
    region.set_y(15)
    assert region.get_extents() == (5, 15, 90, 90)
    assert np.asarray(region).shape == (80, 80, 4)

    figure.set_facecolor("black")
    canvas.draw()
    canvas.restore_region(region)
    canvas.blit()
    restored = canvas.renderer.display_list.to_rgba()

    assert np.all(restored[15:95, 5:85] == [255, 0, 0, 255])
    outside = np.ones(restored.shape[:2], dtype=bool)
    outside[15:95, 5:85] = False
    assert np.all(restored[outside] == [0, 0, 0, 255])

    # Supplying only xy selects RendererAgg's advanced overload.  It uses the
    # mutable extents as an inclusive source bbox, so moving the lower bounds
    # inward crops the unchanged 80x80 backing buffer to 76x76.
    region.set_x(15)
    figure.set_facecolor("black")
    canvas.draw()
    canvas.restore_region(region, xy=(2, 3))
    canvas.blit()
    advanced = canvas.renderer.display_list.to_rgba()
    assert np.all(advanced[3:79, 2:78] == [255, 0, 0, 255])
    outside = np.ones(advanced.shape[:2], dtype=bool)
    outside[3:79, 2:78] = False
    assert np.all(advanced[outside] == [0, 0, 0, 255])


def test_canvas_stale_region_after_silent_resize_rebuilds_the_figure() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [0, 1], animated=True)
    canvas.draw()
    old_region = canvas.copy_from_bbox(axes.bbox)

    figure.set_size_inches(4, 3, forward=False)
    canvas.restore_region(old_region)
    line.set_ydata([1, 0])
    axes.draw_artist(line)
    canvas.blit(axes.bbox)
    incremental = canvas.renderer.display_list.to_rgba()

    assert incremental.shape == (216, 288, 4)
    line.set_animated(False)
    canvas.draw()
    reference = canvas.renderer.display_list.to_rgba()
    assert np.array_equal(incremental, reference)


def test_canvas_blit_after_silent_resize_discards_the_old_geometry() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    canvas.draw()

    figure.set_size_inches(4, 3, forward=False)
    canvas.blit()
    resized = canvas.renderer.display_list.to_rgba()

    assert resized.shape == (216, 288, 4)
    canvas.draw()
    reference = canvas.renderer.display_list.to_rgba()
    assert np.array_equal(resized, reference)


def test_canvas_resize_during_blit_repair_redraws_animated_artists() -> None:
    figure = Figure(figsize=(2, 2), dpi=50)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [1, 0], color="red", animated=True)
    canvas.draw()

    figure.set_size_inches(3, 3, forward=False)
    axes.draw_artist(line)
    resized = False

    def resize_once(_event: object) -> None:
        nonlocal resized
        if resized:
            return
        resized = True
        figure.set_size_inches(4, 4, forward=False)
        canvas.get_renderer()

    canvas.mpl_connect("draw_event", resize_once)
    canvas.blit(axes.bbox)
    incremental = canvas.renderer.display_list.to_rgba()

    assert incremental.shape == (200, 200, 4)
    line.set_animated(False)
    canvas.draw()
    reference = canvas.renderer.display_list.to_rgba()
    assert np.array_equal(incremental, reference)


def test_canvas_region_geometry_epoch_survives_resize_away_and_back() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    canvas.draw()
    region = canvas.copy_from_bbox(axes.bbox)

    figure.set_size_inches(3, 3, forward=False)
    canvas.get_renderer()
    figure.set_size_inches(2, 2, forward=False)
    generation = canvas._draw_generation
    canvas.restore_region(region)

    assert canvas._draw_generation == generation + 1
    assert canvas._blit_geometry_epoch > region.geometry_epoch
    assert canvas._renderer_key(canvas.renderer) == canvas._current_renderer_key()

    other = FigureCanvasXY(Figure(figsize=(2, 2), dpi=72, facecolor="blue"))
    other.draw()
    other.restore_region(region)
    other.blit()

    assert other._blit_work is not None
    left, top, right, bottom = region.pixel_bounds
    assert np.array_equal(
        other._blit_work[top:bottom, left:right],
        region.pixels,
    )


def test_matplotlib_hatches_and_artist_gids_survive_all_xy_consumers() -> None:
    figure = Figure(figsize=(2, 2), dpi=72)
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    patch = axes.bar([0], [1], color="white", edgecolor="black", hatch="//")[0]
    patch.set_gid("Frogs_shadow")

    canvas.draw()
    assert canvas.renderer is not None
    display_list = canvas.renderer.display_list
    hatch_commands = [
        command
        for command in display_list.commands
        if command["type"] == "path" and command["style"].get("hatch")
    ]
    rgba = display_list.to_rgba()
    svg = display_list.to_svg()
    html = display_list.to_html()
    payload = json.loads(display_list.to_json())
    _root, ids = ET.XMLID(svg)

    assert len(hatch_commands) == 1
    assert hatch_commands[0]["style"]["hatch_path"]
    assert "<pattern" in svg
    assert "Frogs_shadow" in ids
    assert len(np.unique(rgba.reshape(-1, 4), axis=0)) > 20
    assert "<pattern" in html
    assert any(
        command.get("gid") == "Frogs_shadow"
        for command in payload["commands"]
        if command["type"] == "group_open"
    )
    assert display_list.fallback_used is False


def test_toolmanager_toolbar_add_remove_toggle_and_message_protocol() -> None:
    calls: list[str] = []

    class ProbeTool(ToolBase):
        description = "Probe"

        def trigger(self, *args, **kwargs):
            calls.append("probe")

    class ToggleTool(ToolToggleBase):
        description = "Toggle"

        def enable(self, *args):
            calls.append("enabled")

        def disable(self, *args):
            calls.append("disabled")

    with matplotlib.rc_context({"toolbar": "toolmanager"}):
        figure = Figure()
        canvas = FigureCanvasXY(figure)
        manager = backend_xy.FigureManagerXY(canvas, 1)

    assert manager.toolmanager is not None
    assert isinstance(manager.toolbar, ToolbarXY)
    assert canvas.toolbar is None
    manager.toolmanager.add_tool("Probe", ProbeTool)
    manager.toolmanager.add_tool("Toggle", ToggleTool)
    manager.toolbar.add_tool("Probe", "custom")
    manager.toolbar.add_tool("Toggle", "custom")
    manager.toolbar.trigger_tool("Probe")
    manager.toolbar.trigger_tool("Toggle")
    manager.toolbar.set_message("ready")

    assert calls == ["probe", "enabled"]
    assert manager.toolbar.toggled["Toggle"] is True
    assert manager.toolbar.message == "ready"
    manager.toolmanager.remove_tool("Probe")
    assert all(item["name"] != "Probe" for item in manager.toolbar.items)


def test_toolbar2_is_hidden_from_figure_hooks_until_first_manager_access() -> None:
    observed: list[object | None] = []

    def backend_specific_hook(figure: Figure) -> None:
        observed.append(figure.canvas.toolbar)
        if figure.canvas.toolbar is not None:
            raise NotImplementedError("The current backend is not supported")

    with matplotlib.rc_context({"toolbar": "toolbar2"}):
        figure = Figure()
        canvas = FigureCanvasXY(figure)
        manager = backend_xy.FigureManagerXY(canvas, 2)
        backend_specific_hook(figure)

    assert observed == [None]
    assert manager.vbox.children == [canvas]

    toolbar = manager.toolbar

    assert isinstance(toolbar, NavigationToolbar2XY)
    assert canvas.toolbar is toolbar
    assert manager.vbox.children == [canvas, toolbar]
    assert manager.toolbar is toolbar

    canvas.draw()

    assert manager.toolbar is toolbar
    assert manager.vbox.children == [canvas, toolbar]


def test_toolbar2_is_materialized_by_first_canvas_draw() -> None:
    with matplotlib.rc_context({"toolbar": "toolbar2"}):
        figure = Figure()
        canvas = FigureCanvasXY(figure)
        manager = backend_xy.FigureManagerXY(canvas, 2)

    assert canvas.toolbar is None
    assert manager._toolbar is None

    canvas.draw()

    assert isinstance(canvas.toolbar, NavigationToolbar2XY)
    assert manager._toolbar is canvas.toolbar
    assert manager.vbox.children == [canvas, canvas.toolbar]


def test_foreign_toolbar_and_vbox_reference_methods_retain_callbacks_and_order() -> None:
    class ForeignWidget:
        def __init__(self) -> None:
            self.callbacks: dict[str, object] = {}

        def connect(self, signal: str, callback: object) -> None:
            self.callbacks[signal] = callback

        def emit(self, signal: str) -> None:
            callback = self.callbacks[signal]
            assert callable(callback)
            callback(self)

    with matplotlib.rc_context({"toolbar": "toolbar2"}):
        figure = Figure()
        canvas = FigureCanvasXY(figure)
        manager = backend_xy.FigureManagerXY(canvas, 2)
    figure.subplots()  # Exercises the manager's axes-change update hook.
    assert canvas._draw_generation == 0
    clicked: list[object] = []
    first = ForeignWidget()
    second = ForeignWidget()
    label = ForeignWidget()
    first.connect("clicked", clicked.append)

    manager.toolbar.insert(first, 8)
    manager.toolbar.append(second)
    manager.vbox.pack_start(label, False, False, 0)
    manager.vbox.reorder_child(manager.toolbar, -1)
    manager.vbox.insert_child_after(label, canvas)
    first.emit("clicked")

    assert manager.toolbar.foreign_widgets == [first, second]
    assert manager.vbox.children[1] is label
    assert manager.vbox.children[-1] is manager.toolbar
    assert clicked == [first]
    assert isinstance(manager.toolbar, NavigationToolbar2XY)
    assert canvas._draw_generation == 0
    assert canvas.toolbar is manager.toolbar


def test_widget_key_and_pointer_events_drive_pan_zoom_home_back_forward() -> None:
    with matplotlib.rc_context({"toolbar": "toolbar2"}):
        figure = Figure(figsize=(3, 2), dpi=100)
        canvas = FigureCanvasXY(figure)
        manager = backend_xy.FigureManagerXY(canvas, 3)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    canvas.draw()
    widget = canvas.widget
    original_x = axes.get_xlim()
    original_y = axes.get_ylim()
    x0 = float((axes.bbox.x0 + axes.bbox.x1) / 2)
    y0 = float((axes.bbox.y0 + axes.bbox.y1) / 2)

    def send(name: str, **payload: object) -> None:
        widget._on_custom_msg(
            widget,
            {"type": "event", "name": name, **payload},
            [],
        )

    send("figure_enter_event", x=x0, y=y0, modifiers=[])
    send("key_press_event", key="p")
    send("button_press_event", x=x0, y=y0, button=0, modifiers=[])
    send("motion_notify_event", x=x0 + 30, y=y0, buttons=1, modifiers=[])
    send("button_release_event", x=x0 + 30, y=y0, button=0, modifiers=[])

    assert isinstance(manager.toolbar, NavigationToolbar2XY)
    assert axes.get_xlim() != pytest.approx(original_x)
    send("key_press_event", key="home")
    assert axes.get_xlim() == pytest.approx(original_x)
    assert axes.get_ylim() == pytest.approx(original_y)

    send("key_press_event", key="o")
    send(
        "button_press_event",
        x=float(axes.bbox.x0 + axes.bbox.width * 0.25),
        y=float(axes.bbox.y0 + axes.bbox.height * 0.25),
        button=0,
        modifiers=[],
    )
    send(
        "motion_notify_event",
        x=float(axes.bbox.x0 + axes.bbox.width * 0.75),
        y=float(axes.bbox.y0 + axes.bbox.height * 0.75),
        buttons=1,
        modifiers=[],
    )
    send(
        "button_release_event",
        x=float(axes.bbox.x0 + axes.bbox.width * 0.75),
        y=float(axes.bbox.y0 + axes.bbox.height * 0.75),
        button=0,
        modifiers=[],
    )
    zoomed_x = axes.get_xlim()
    assert zoomed_x[1] - zoomed_x[0] < original_x[1] - original_x[0]
    send("key_press_event", key="left")
    assert axes.get_xlim() == pytest.approx(original_x)
    send("key_press_event", key="right")
    assert axes.get_xlim() == pytest.approx(zoomed_x)
    manager.destroy()


def test_func_animation_constructs_and_uses_xy_timer() -> None:
    figure = Figure()
    canvas = FigureCanvasXY(figure)
    axes = figure.subplots()
    (line,) = axes.plot([], [])

    def update(frame: int):
        line.set_data([0, frame], [0, frame])
        return (line,)

    animation = FuncAnimation(figure, update, frames=[0, 1], interval=5, repeat=False)
    canvas.draw()

    assert isinstance(animation.event_source, TimerXY)
    assert animation.event_source.running is True
    animation.event_source.fire()
    assert list(line.get_xdata()) in ([0, 0], [0, 1])
    animation._stop()


def test_backend_module_loader_and_optional_import_boundary(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    script = """
import sys
import xy.backends
assert "matplotlib" not in sys.modules
from xy.backends import DisplayList
assert "matplotlib" not in sys.modules
import matplotlib
matplotlib.use("module://xy.backends.backend_xy", force=True)
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot([0, 1], [0, 1])
fig.canvas.draw()
assert type(fig.canvas).__name__ == "FigureCanvasXY"
assert fig.canvas.renderer.display_list.fallback_used is False
print(type(fig.canvas).__name__)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "python")
    environment["MPLCONFIGDIR"] = str(tmp_path / "mplconfig")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "FigureCanvasXY"


def test_pyplot_figure_hook_precedes_lazy_toolbar_materialization(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    script = """
import sys
from types import ModuleType

import matplotlib

matplotlib.use("module://xy.backends.backend_xy", force=True)
observed = []
hook_module = ModuleType("xy_toolbar_hook_probe")

def setup(figure):
    observed.append((figure.canvas.toolbar, figure.canvas.manager._toolbar))

hook_module.setup = setup
sys.modules[hook_module.__name__] = hook_module
matplotlib.rcParams["toolbar"] = "toolbar2"
matplotlib.rcParams["figure.hooks"] = ["xy_toolbar_hook_probe:setup"]

import matplotlib.pyplot as plt
from xy.backends.backend_xy import NavigationToolbar2XY

figure, _axes = plt.subplots()
manager = figure.canvas.manager
assert observed == [(None, None)]
assert isinstance(manager.toolbar, NavigationToolbar2XY)
assert figure.canvas.toolbar is manager.toolbar
assert manager.vbox.children.count(manager.toolbar) == 1
plt.close("all")
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "python")
    environment["MPLCONFIGDIR"] = str(tmp_path / "mplconfig")

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
