from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

matplotlib = pytest.importorskip("matplotlib")
backend_bases = pytest.importorskip("matplotlib.backend_bases")
backend_tools = pytest.importorskip("matplotlib.backend_tools")
Figure = pytest.importorskip("matplotlib.figure").Figure
backend_xy = pytest.importorskip("xy.backends.backend_xy")
backend_xy_widget = pytest.importorskip("xy.backends.backend_xy_widget")

CloseEvent = backend_bases.CloseEvent
KeyEvent = backend_bases.KeyEvent
LocationEvent = backend_bases.LocationEvent
MouseButton = backend_bases.MouseButton
MouseEvent = backend_bases.MouseEvent
ResizeEvent = backend_bases.ResizeEvent
Cursors = backend_tools.Cursors
FigureCanvasXY = backend_xy.FigureCanvasXY
FigureManagerXY = backend_xy.FigureManagerXY
FigureCanvasXYWidget = backend_xy_widget.FigureCanvasXYWidget
widget_esm = backend_xy_widget.widget_esm

ROOT = Path(__file__).resolve().parents[2]
LIVE_TOOLBAR_PROBE = Path(__file__).with_name("backend_xy_live_toolbar_probe.mjs")


def _event_figure() -> tuple[object, FigureCanvasXY, object]:
    figure = Figure(figsize=(2, 1), dpi=100)
    canvas = FigureCanvasXY(figure)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set(xlim=(0, 2), ylim=(-1, 1))
    axes.plot([0, 2], [-1, 1])
    return figure, canvas, axes


def _message(widget: FigureCanvasXYWidget, name: str, **content: object) -> None:
    widget._on_custom_msg(
        widget,
        {"type": "event", "name": name, **content},
        [],
    )


def _browser_toolchain() -> tuple[str, str]:
    from xy.export import find_chromium

    chromium = find_chromium()
    node = shutil.which("node")
    required = bool(os.environ.get("XY_REQUIRE_BROWSER"))
    if chromium is None or node is None:
        message = f"live toolbar probe requires Chromium and Node ({chromium=}, {node=})"
        if required:
            pytest.fail(message)
        pytest.skip(message)
    playwright = subprocess.run(
        [node, "-e", "require.resolve('playwright')"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if playwright.returncode != 0:
        message = f"live toolbar probe requires Playwright: {playwright.stderr.strip()}"
        if required:
            pytest.fail(message)
        pytest.skip(message)
    return node, chromium


def test_widget_dispatches_genuine_matplotlib_events_with_data_coordinates() -> None:
    figure, canvas, axes = _event_figure()
    widget = FigureCanvasXYWidget(canvas)
    seen: dict[str, object] = {}
    names = (
        "motion_notify_event",
        "button_press_event",
        "button_release_event",
        "scroll_event",
        "figure_enter_event",
        "figure_leave_event",
        "key_press_event",
        "key_release_event",
        "resize_event",
        "close_event",
    )
    for name in names:
        canvas.mpl_connect(name, lambda event, name=name: seen.__setitem__(name, event))

    location = {"x": 100, "y": 50, "modifiers": ["ctrl"], "buttons": 5}
    _message(widget, "motion_notify_event", **location)
    _message(widget, "button_press_event", **location, button=0)
    _message(widget, "button_release_event", **location, button=0)
    _message(widget, "scroll_event", **location, step=-2)
    _message(widget, "figure_enter_event", **location)
    _message(widget, "figure_leave_event", **location)
    _message(widget, "key_press_event", key="ctrl+a")
    _message(widget, "key_release_event", key="ctrl+a")
    _message(widget, "resize_event", width=300, height=150)
    _message(widget, "close_event")
    _message(widget, "close_event")

    motion = seen["motion_notify_event"]
    assert isinstance(motion, MouseEvent)
    assert motion.canvas is canvas
    assert motion.inaxes is axes
    assert motion.xdata == pytest.approx(1)
    assert motion.ydata == pytest.approx(0)
    assert motion.buttons == {MouseButton.LEFT, MouseButton.MIDDLE}
    assert motion.modifiers == frozenset({"ctrl"})
    press = seen["button_press_event"]
    assert isinstance(press, MouseEvent)
    assert press.button is MouseButton.LEFT
    assert isinstance(seen["scroll_event"], MouseEvent)
    assert seen["scroll_event"].step == -2
    assert isinstance(seen["figure_enter_event"], LocationEvent)
    assert isinstance(seen["figure_leave_event"], LocationEvent)
    key = seen["key_press_event"]
    assert isinstance(key, KeyEvent)
    assert (key.x, key.y, key.key) == (100, 50, "ctrl+a")
    resize = seen["resize_event"]
    assert isinstance(resize, ResizeEvent)
    assert resize.inaxes is axes
    assert (resize.xdata, resize.ydata) == pytest.approx((1, 0))
    assert tuple(figure.bbox.size) == pytest.approx((300, 150))
    assert isinstance(seen["close_event"], CloseEvent)


def test_widget_refreshes_from_draw_idle_and_manager_exposes_same_instance() -> None:
    import xy.backends

    figure, canvas, axes = _event_figure()
    widget = canvas.widget
    manager = FigureManagerXY(canvas, 7)
    original_generation = widget.generation
    original_svg = widget.svg

    axes.lines[0].set_ydata([1, -1])
    canvas.draw_idle()

    assert canvas.get_widget() is widget
    assert manager.widget is widget
    assert manager.get_widget() is widget
    assert xy.backends.FigureCanvasXYWidget is FigureCanvasXYWidget
    assert widget.generation > original_generation
    assert widget.svg != original_svg
    assert widget.width == 200
    assert widget.height == 100
    assert canvas.fallback_used is False
    manager.destroy()


def test_widget_event_loop_heartbeat_advances_and_stops_canvas_timer() -> None:
    _figure, canvas, _axes = _event_figure()
    widget = canvas.widget
    calls: list[str] = []
    timer = canvas.new_timer(interval=1)
    timer.add_callback(lambda: calls.append("tick") or False)

    timer.start()
    assert widget.timer_interval == 1
    time.sleep(0.01)
    widget._on_custom_msg(widget, {"type": "event_loop"}, [])

    assert calls == ["tick"]
    assert timer.running is False
    assert widget.timer_interval == 0


def test_widget_syncs_coords_cursor_and_toolbar_navigation_state() -> None:
    with matplotlib.rc_context({"toolbar": "toolbar2"}):
        figure, canvas, axes = _event_figure()
        manager = FigureManagerXY(canvas, 11)
    axes.format_coord = lambda x, y: f"CUSTOM x={x:.2f}, y={y:.2f}"
    canvas.draw()
    widget = canvas.widget
    original_x = axes.get_xlim()
    original_y = axes.get_ylim()
    x0 = float((axes.bbox.x0 + axes.bbox.x1) / 2)
    y0 = float((axes.bbox.y0 + axes.bbox.y1) / 2)

    cursor_callback = canvas.mpl_connect(
        "motion_notify_event", lambda _event: canvas.set_cursor(Cursors.SELECT_REGION)
    )
    _message(widget, "motion_notify_event", x=x0, y=y0, buttons=0, modifiers=[])
    canvas.mpl_disconnect(cursor_callback)

    assert widget.toolbar_enabled is True
    assert "CUSTOM x=1.00, y=0.00" in widget.toolbar_message
    assert widget.cursor == "select_region"
    assert widget.toolbar_mode == ""
    assert widget.toolbar_can_back is False
    assert widget.toolbar_can_forward is False

    widget._on_custom_msg(widget, {"type": "toolbar", "action": "pan"}, [])
    assert widget.toolbar_mode == "pan/zoom"
    _message(widget, "button_press_event", x=x0, y=y0, button=0, modifiers=[])
    _message(
        widget,
        "motion_notify_event",
        x=x0 + 30,
        y=y0,
        buttons=1,
        modifiers=[],
    )
    _message(widget, "button_release_event", x=x0 + 30, y=y0, button=0, modifiers=[])
    panned_x = axes.get_xlim()
    panned_y = axes.get_ylim()

    assert panned_x != pytest.approx(original_x)
    assert widget.toolbar_can_back is True
    assert widget.toolbar_can_forward is False

    widget._on_custom_msg(widget, {"type": "toolbar", "action": "pan"}, [])
    widget._on_custom_msg(widget, {"type": "toolbar", "action": "back"}, [])
    assert axes.get_xlim() == pytest.approx(original_x)
    assert axes.get_ylim() == pytest.approx(original_y)
    assert widget.toolbar_can_back is False
    assert widget.toolbar_can_forward is True

    widget._on_custom_msg(widget, {"type": "toolbar", "action": "forward"}, [])
    assert axes.get_xlim() == pytest.approx(panned_x)
    assert axes.get_ylim() == pytest.approx(panned_y)
    assert widget.toolbar_can_back is True
    assert widget.toolbar_can_forward is False
    manager.destroy()


def test_widget_ignores_malformed_or_unknown_browser_messages() -> None:
    _figure, canvas, _axes = _event_figure()
    widget = FigureCanvasXYWidget(canvas)
    events: list[object] = []
    canvas.mpl_connect("button_press_event", events.append)

    malformed = (
        None,
        [],
        {},
        {"type": "other", "name": "button_press_event"},
        {"type": "event"},
        {"type": "event", "name": "unknown_event"},
        {"type": "event", "name": "button_press_event", "x": "bad", "y": 1},
        {"type": "event", "name": "button_press_event", "x": 1, "y": 1, "button": 99},
        {"type": "event", "name": "resize_event", "width": -1, "height": 10},
        {"type": "toolbar"},
        {"type": "toolbar", "action": "save"},
        {"type": "toolbar", "action": []},
    )
    for content in malformed:
        widget._on_custom_msg(widget, content, [])

    assert events == []


def test_widget_esm_drives_browser_events_and_live_svg_refresh(tmp_path: Path) -> None:
    from conftest import run_browser_probe
    from xy.export import find_chromium

    chromium = find_chromium()
    if chromium is None:
        if os.environ.get("XY_REQUIRE_BROWSER"):
            pytest.fail("XY_REQUIRE_BROWSER is set but no Chromium installation was found")
        pytest.skip("no chromium installation found")

    client = tmp_path / "backend_xy_widget.js"
    client.write_text(widget_esm(), encoding="utf-8")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<rect id="initial" width="200" height="100"/></svg>'
    )
    refreshed_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
        '<circle id="refreshed" cx="20" cy="20" r="10"/></svg>'
    )
    document = f"""<!doctype html>
<html><body><div id="mount"></div>
<script type="module">
import {{ render }} from "./backend_xy_widget.js";
class Model {{
  constructor(state) {{
    this.state = state;
    this.listeners = new Map();
    this.messages = [];
  }}
  get(name) {{ return this.state[name]; }}
  on(name, callback) {{
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(callback);
  }}
  off(name, callback) {{ this.listeners.get(name)?.delete(callback); }}
  send(message) {{ this.messages.push(message); }}
  set(name, value) {{
    this.state[name] = value;
    for (const callback of this.listeners.get(`change:${{name}}`) || []) callback();
  }}
}}
let resizeObserver;
window.ResizeObserver = class {{
  constructor(callback) {{
    this.callback = callback;
    resizeObserver = this;
  }}
  observe(target) {{ this.target = target; }}
  disconnect() {{}}
}};
const model = new Model({{
  svg: {json.dumps(svg)},
  width: 200,
  height: 100,
  generation: 1,
  timer_interval: 10,
  toolbar_enabled: true,
  toolbar_mode: "",
  toolbar_message: "",
  toolbar_can_back: false,
  toolbar_can_forward: true,
  cursor: "pointer",
}});
render({{ model, el: document.getElementById("mount") }});
const root = document.querySelector(".xy-matplotlib-canvas");
const toolbar = document.querySelector(".xy-matplotlib-toolbar");
const status = document.querySelector(".xy-matplotlib-status");
const controls = [...toolbar.querySelectorAll("button")];
const backInitiallyDisabled = toolbar.querySelector('[data-xy-toolbar-action="back"]').disabled;
const initialCursor = getComputedStyle(root).cursor;
model.set("toolbar_message", "CUSTOM x=1.00, y=0.00");
model.set("cursor", "select_region");
model.set("toolbar_mode", "pan/zoom");
model.set("toolbar_can_back", true);
const panPressed = toolbar
  .querySelector('[data-xy-toolbar-action="pan"]')
  .getAttribute("aria-pressed");
for (const control of controls) control.click();
model.set("toolbar_mode", "zoom rect");
const zoomPressed = toolbar
  .querySelector('[data-xy-toolbar-action="zoom"]')
  .getAttribute("aria-pressed");
const pointerEvent = typeof PointerEvent === "function" ? PointerEvent : MouseEvent;
const pointerPrefix = typeof PointerEvent === "function" ? "pointer" : "mouse";
const initialBounds = root.getBoundingClientRect();
const pointer = (suffix, options) => root.dispatchEvent(
  new pointerEvent(`${{pointerPrefix}}${{suffix}}`, {{
    bubbles: true,
    pointerId: 1,
    clientX: initialBounds.left + initialBounds.width * 0.25,
    clientY: initialBounds.top + initialBounds.height * 0.25,
    ...options,
  }}),
);
pointer("enter", {{ button: -1, buttons: 0 }});
pointer("move", {{ button: -1, buttons: 5, ctrlKey: true }});
pointer("down", {{ button: 0, buttons: 1 }});
pointer("up", {{ button: 0, buttons: 0 }});
root.dispatchEvent(new WheelEvent("wheel", {{
  bubbles: true, clientX: 50, clientY: 25, deltaY: -20,
}}));
root.dispatchEvent(new KeyboardEvent("keydown", {{
  bubbles: true, key: "a", ctrlKey: true,
}}));
root.dispatchEvent(new KeyboardEvent("keyup", {{
  bubbles: true, key: "a", ctrlKey: true,
}}));
pointer("leave", {{ button: -1, buttons: 0 }});
root.style.width = "240px";
root.style.height = "120px";
resizeObserver.callback([{{ contentRect: {{ width: 240, height: 120 }} }}]);
model.set("svg", {json.dumps(refreshed_svg)});
model.set("generation", 2);
root.dispatchEvent(new CustomEvent("xy-close"));
setTimeout(() => {{
  document.body.setAttribute(
    "data-xy-mpl-widget-probe",
    JSON.stringify({{
      messages: model.messages,
      generation: root.dataset.xyGeneration,
      refreshed: Boolean(root.querySelector("#refreshed")),
      live: root.dataset.xyBackendWidget,
      controls: controls.map((control) => control.textContent),
      toolbarVisible: getComputedStyle(toolbar).display !== "none",
      status: status.dataset.xyToolbarStatus,
      initialCursor,
      cursor: getComputedStyle(root).cursor,
      cursorName: root.dataset.xyCursor,
      backInitiallyDisabled,
      backEnabled: !toolbar.querySelector('[data-xy-toolbar-action="back"]').disabled,
      panPressed,
      zoomPressed,
    }}),
  );
}}, 100);
</script></body></html>"""

    result = run_browser_probe(
        chromium,
        document,
        tmp_path / "widget-probe.html",
        "data-xy-mpl-widget-probe",
        label="Matplotlib live canvas widget",
    )

    assert result["generation"] == "2"
    assert result["refreshed"] is True
    assert result["live"] == "live"
    assert result["controls"] == ["Home", "Back", "Forward", "Pan", "Zoom"]
    assert result["toolbarVisible"] is True
    assert result["status"] == "CUSTOM x=1.00, y=0.00"
    assert result["initialCursor"] == "default"
    assert result["cursor"] == "crosshair"
    assert result["cursorName"] == "select_region"
    assert result["backInitiallyDisabled"] is True
    assert result["backEnabled"] is True
    assert result["panPressed"] == "true"
    assert result["zoomPressed"] == "true"
    messages = result["messages"]
    toolbar_messages = [message for message in messages if message["type"] == "toolbar"]
    assert toolbar_messages == [
        {"type": "toolbar", "action": action}
        for action in ("home", "back", "forward", "pan", "zoom")
    ]
    names = [message["name"] for message in messages if message["type"] == "event"]
    assert {
        "figure_enter_event",
        "motion_notify_event",
        "button_press_event",
        "button_release_event",
        "scroll_event",
        "key_press_event",
        "key_release_event",
        "figure_leave_event",
        "resize_event",
        "close_event",
    }.issubset(names)
    motion = next(message for message in messages if message.get("name") == "motion_notify_event")
    assert motion["x"] == pytest.approx(50)
    assert motion["y"] == pytest.approx(75)
    assert motion["buttons"] == 5
    assert motion["modifiers"] == ["ctrl"]
    key = next(message for message in messages if message.get("name") == "key_press_event")
    assert key["key"] == "ctrl+a"
    scroll = next(message for message in messages if message.get("name") == "scroll_event")
    assert scroll["step"] == 1
    resize = next(message for message in messages if message.get("name") == "resize_event")
    assert (resize["width"], resize["height"]) == (240, 120)
    assert names.count("close_event") == 1
    assert any(message == {"type": "event_loop"} for message in messages)

    # Replay the exact payloads emitted by Chromium through the real anywidget
    # message handler. This joins the browser and Python halves of the comm
    # contract instead of validating each side with unrelated fixtures.
    figure, canvas, axes = _event_figure()
    widget = FigureCanvasXYWidget(canvas)
    received: list[str] = []
    for name in {
        "figure_enter_event",
        "motion_notify_event",
        "button_press_event",
        "button_release_event",
        "scroll_event",
        "key_press_event",
        "key_release_event",
        "figure_leave_event",
        "resize_event",
        "close_event",
    }:
        canvas.mpl_connect(name, lambda _event, name=name: received.append(name))
    timer_ticks: list[str] = []
    timer = canvas.new_timer(interval=1)
    timer.add_callback(lambda: timer_ticks.append("tick") or False)
    timer.start()
    time.sleep(0.01)
    for message in messages:
        widget._on_custom_msg(widget, message, [])

    assert set(names).issubset(received)
    assert timer_ticks == ["tick"]
    assert timer.running is False
    assert widget.timer_interval == 0
    assert tuple(figure.bbox.size) == pytest.approx((240, 120))
    assert canvas.fallback_used is False


def test_live_browser_coords_cursor_and_toolbar_controls_drive_python_state() -> None:
    node, chromium = _browser_toolchain()
    with matplotlib.rc_context({"toolbar": "toolbar2"}):
        figure = Figure(figsize=(4, 3), dpi=100)
        canvas = FigureCanvasXY(figure)
        manager = FigureManagerXY(canvas, 12)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1e7], "o")
    axes.fmt_ydata = lambda y: f"${y * 1e-6:1.1f}M"
    axes.cursor_to_use = Cursors.SELECT_REGION

    def hover(event: object) -> None:
        if canvas.widgetlock.locked():
            return
        inaxes = getattr(event, "inaxes", None)
        canvas.set_cursor(inaxes.cursor_to_use if inaxes is not None else Cursors.POINTER)

    canvas.mpl_connect("motion_notify_event", hover)
    canvas.draw()
    original_x = axes.get_xlim()
    observed_x: list[tuple[float, float]] = []
    axes.callbacks.connect("xlim_changed", lambda current: observed_x.append(current.get_xlim()))
    host = manager._refresh_browser_host()
    process = subprocess.Popen(
        [node, str(LIVE_TOOLBAR_PROBE), host.url, chromium],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 60
    try:
        while process.poll() is None and time.monotonic() < deadline:
            canvas.flush_events()
            time.sleep(0.005)
        if process.poll() is None:
            process.kill()
            pytest.fail("live toolbar browser probe timed out after 60 seconds")
        canvas.flush_events()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, f"stdout:\n{stdout}\nstderr:\n{stderr}"
        result = json.loads(stdout)
        coords = result.pop("coords")

        assert result == {
            "controls": ["Home", "Back", "Forward", "Pan", "Zoom"],
            "backInitiallyDisabled": True,
            "forwardInitiallyDisabled": True,
            "cursor": "crosshair",
            "panPressed": "true",
            "panCursor": "move",
            "backAfterPanEnabled": True,
            "forwardAfterBackEnabled": True,
            "backAfterForwardEnabled": True,
            "forwardAfterForwardDisabled": True,
            "pageErrors": [],
        }
        assert "$5.0M" in coords
        assert any(bounds != pytest.approx(original_x) for bounds in observed_x)
        assert any(bounds == pytest.approx(original_x) for bounds in observed_x)
        assert axes.get_xlim() != pytest.approx(original_x)
        assert manager.toolbar.history_back_enabled is True
        assert manager.toolbar.history_forward_enabled is False
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        manager.destroy()


def test_standalone_html_is_static_and_does_not_claim_python_callbacks() -> None:
    _figure, canvas, _axes = _event_figure()
    canvas.draw()
    assert canvas.renderer is not None

    document = canvas.renderer.display_list.to_html()

    assert "xy-matplotlib-canvas" not in document
    assert "kernel-connected" not in document
    assert "mpl_connect" not in document
    assert "backend_xy_widget.js" not in document
    assert "<svg" in html.unescape(document)
