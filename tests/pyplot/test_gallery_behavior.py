"""Deterministic interaction and animation evidence for the gallery gate."""

from __future__ import annotations

import ast
import itertools
import json
import random
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from scripts.pyplot_gallery.behavior import (
    REQUIRED_CANVAS_EVENTS,
    WIDGET_TRANSPORT_EVENTS,
    behavior_gate,
    drive_behavior,
)
from scripts.pyplot_gallery.metrics import compare_images, evaluate_visual
from scripts.pyplot_gallery.run_case import run_case
from scripts.pyplot_gallery.run_gallery import _ratchet_case

matplotlib = pytest.importorskip("matplotlib")
np = pytest.importorskip("numpy")


def _interactive_objects() -> tuple[object, dict[str, object], list[object]]:
    from matplotlib.animation import FuncAnimation
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.widgets import Button, Slider

    figure = Figure()
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [0, 1])
    calls: list[object] = []

    button_axes = figure.add_axes((0.1, 0.02, 0.2, 0.08))
    button = Button(button_axes, "Advance")
    button.on_clicked(lambda _event: calls.append("button"))

    slider_axes = figure.add_axes((0.4, 0.02, 0.4, 0.08))
    slider = Slider(slider_axes, "Value", 0, 10, valinit=1)
    slider.on_changed(lambda value: calls.append(("slider", float(value))))
    for event_name in (
        "figure_enter_event",
        "figure_leave_event",
        "axes_enter_event",
        "axes_leave_event",
    ):
        figure.canvas.mpl_connect(
            event_name,
            lambda event, name=event_name: calls.append((name, event.inaxes is not None)),
        )

    animation = FuncAnimation(
        figure,
        lambda frame: (line.set_ydata([frame, frame + 1]), line)[1:],
        frames=5,
        interval=5,
    )
    return (
        figure,
        {"button": button, "slider": slider, "animation": animation},
        calls,
    )


def test_behavior_driver_exercises_canvas_widgets_animation_and_timer() -> None:
    figure, namespace, calls = _interactive_objects()
    result = drive_behavior(
        engine="matplotlib",
        requirements=("interactive", "animation"),
        figures=[figure],
        namespace=namespace,
    )

    assert result["status"] == "passed", result["errors"]
    assert [event["event"] for event in result["events"]] == list(REQUIRED_CANVAS_EVENTS)
    assert all(event["probe_delivered"] for event in result["events"])
    location_events = [
        event
        for event in result["events"]
        if event["event"]
        in {
            "figure_enter_event",
            "figure_leave_event",
            "axes_enter_event",
            "axes_leave_event",
        }
    ]
    assert all(event["source_callbacks"] >= 1 for event in location_events)
    assert all(event["inaxes"] is True for event in location_events)
    assert {widget["type"].rsplit(".", 1)[-1] for widget in result["widgets"]} == {
        "Button",
        "Slider",
    }
    assert calls
    assert [phase["role"] for phase in result["animations"][0]["phases"]] == [
        "initial",
        "middle",
        "final",
    ]
    assert result["animations"][0]["finite"] is True
    assert result["timers"][0]["probe_delivered"] is True
    assert result["timers"][0]["source_callbacks"] >= 1


def test_xy_behavior_driver_requires_the_live_widget_transport() -> None:
    from matplotlib.figure import Figure

    from xy.backends.backend_xy import FigureCanvasXY

    figure = Figure(figsize=(2, 1), dpi=100)
    FigureCanvasXY(figure)
    figure.subplots().plot([0, 1], [0, 1])

    result = drive_behavior(
        engine="xy",
        requirements=("interactive",),
        figures=[figure],
        namespace={},
    )

    assert result["status"] == "passed", result["errors"]
    transport = result["browser_transport"]
    assert transport["required"] is True
    assert transport["attempted"] == len(WIDGET_TRANSPORT_EVENTS)
    assert transport["delivered"] == transport["attempted"]
    widget_events = [event for event in result["events"] if event["transport"] == "widget"]
    assert {event["event"] for event in widget_events} == WIDGET_TRANSPORT_EVENTS
    assert all(event["browser_message"]["type"] == "event" for event in widget_events)


@pytest.mark.parametrize(
    "selector_name",
    ["LassoSelector", "PolygonSelector", "RectangleSelector", "SpanSelector"],
)
@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_selector_driver_delivers_the_real_selection_callback(
    selector_name: str,
    engine: str,
) -> None:
    from matplotlib import widgets
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from xy.backends.backend_xy import FigureCanvasXY

    figure = Figure()
    (FigureCanvasXY if engine == "xy" else FigureCanvasAgg)(figure)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    figure.canvas.draw()
    calls: list[tuple[object, ...]] = []
    selector_type = getattr(widgets, selector_name)
    if selector_name == "SpanSelector":
        selector = selector_type(axes, lambda *args: calls.append(args), "horizontal")
    else:
        selector = selector_type(axes, lambda *args: calls.append(args))
    if selector_name == "PolygonSelector":
        selector.disconnect_events()

    result = drive_behavior(
        engine=engine,
        requirements=("interactive",),
        figures=[figure],
        namespace={"selector": selector},
    )

    assert result["status"] == "passed", result["errors"]
    assert calls
    record = result["widgets"][0]
    assert record["selector_callback_calls"] >= 1
    assert record["operation"] in {"drag_select", "polygon_select"}
    assert record["reconnected"] is (selector_name == "PolygonSelector")
    if engine == "xy":
        assert all(event["transport"] == "widget" for event in record["events"])


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_axes_limit_callback_driver_mutates_limits_and_delivers_callbacks(
    engine: str,
) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from xy.backends.backend_xy import FigureCanvasXY

    figure = Figure()
    (FigureCanvasXY if engine == "xy" else FigureCanvasAgg)(figure)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    figure.canvas.draw()
    calls: list[str] = []
    axes.callbacks.connect("xlim_changed", lambda _axes: calls.append("x"))
    axes.callbacks.connect("ylim_changed", lambda _axes: calls.append("y"))
    calls.clear()

    result = drive_behavior(
        engine=engine,
        requirements=("interactive",),
        figures=[figure],
        namespace={},
    )

    assert result["status"] == "passed", result["errors"]
    assert set(calls) == {"x", "y"}
    assert {record["signal"] for record in result["axes_callbacks"]} == {
        "xlim_changed",
        "ylim_changed",
    }
    assert all(record["probe_delivered"] for record in result["axes_callbacks"])
    assert all(record["state_changed"] for record in result["axes_callbacks"])


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_coordinate_navigation_and_draggable_probes_change_live_state(
    engine: str,
) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from xy.backends.backend_xy import FigureCanvasXY, FigureManagerXY

    figure = Figure()
    if engine == "xy":
        canvas = FigureCanvasXY(figure)
        FigureManagerXY(canvas, 1)
    else:
        FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1])
    axes.format_coord = lambda x, y: f"custom x={x:.2f}, y={y:.2f}"
    annotation = axes.annotate(
        "drag",
        (0.5, 0.5),
        xytext=(20, 20),
        textcoords="offset points",
    )
    dependent = axes.annotate(
        "dependent",
        (0.5, 0.5),
        xycoords=annotation,
        xytext=(0.5, 0.25),
        textcoords="axes fraction",
        arrowprops={"arrowstyle": "->"},
    )
    annotation.draggable()
    dependent.draggable()

    result = drive_behavior(
        engine=engine,
        requirements=("interactive", "coordinates", "navigation"),
        figures=[figure],
        namespace={"annotation": annotation, "dependent": dependent},
    )

    assert result["status"] == "passed", result["errors"]
    assert result["coordinate_reports"][0]["formatted"].startswith("custom x=")
    assert len(result["draggables"]) == 2
    assert all(record["state_changed"] for record in result["draggables"])
    assert result["navigation"][0]["state_changed"] is True
    if engine == "xy":
        assert result["coordinate_reports"][0]["toolbar_message"].startswith("custom x=")
        assert result["navigation"][0]["transport"] == "widget"


def test_unbounded_animation_uses_a_declared_bounded_final() -> None:
    from matplotlib.animation import FuncAnimation
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure()
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    (line,) = axes.plot([0, 1], [0, 1])
    animation = FuncAnimation(
        figure,
        lambda frame: (line.set_ydata([frame, frame + 1]), line)[1:],
        frames=itertools.count(),
        save_count=8,
    )

    result = drive_behavior(
        engine="matplotlib",
        requirements=("animation",),
        figures=[figure],
        namespace={"animation": animation},
    )

    assert result["status"] == "passed", result["errors"]
    record = result["animations"][0]
    assert record["finite"] is False
    assert record["sampled_frame_count"] == 8
    assert [phase["role"] for phase in record["phases"]] == [
        "initial",
        "middle",
        "bounded_final",
    ]


def test_callback_exception_is_recorded_and_fails_the_gate() -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure()
    FigureCanvasAgg(figure)
    figure.subplots().plot([0, 1], [0, 1])

    def fail(_event: object) -> None:
        raise ValueError("source callback failed")

    figure.canvas.mpl_connect("key_press_event", fail)
    result = drive_behavior(
        engine="matplotlib",
        requirements=("interactive",),
        figures=[figure],
        namespace={},
    )

    assert result["status"] == "failed"
    key_record = next(event for event in result["events"] if event["event"] == "key_press_event")
    assert key_record["failure"]["exception_type"] == "ValueError"
    assert "source callback failed" in key_record["failure"]["message"]
    passed, reasons = behavior_gate(
        {"status": "passed", "behavior": result},
        ("interactive",),
    )
    assert passed is False
    assert any("key_press_event" in reason for reason in reasons)


def test_recursive_draw_callback_still_delivers_the_probe() -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure()
    FigureCanvasAgg(figure)
    figure.subplots().plot([0, 1], [0, 1])
    recursing = False

    def draw_again(_event: object) -> None:
        nonlocal recursing
        if not recursing:
            recursing = True
            figure.canvas.draw()
            recursing = False

    figure.canvas.mpl_connect("draw_event", draw_again)
    result = drive_behavior(
        engine="matplotlib",
        requirements=("interactive",),
        figures=[figure],
        namespace={},
    )

    assert result["status"] == "passed", result["errors"]
    draw = next(event for event in result["events"] if event["event"] == "draw_event")
    assert draw["probe_delivered"] is True
    assert draw["probe_call_count"] >= 2


def test_pick_driver_supplies_custom_picker_properties() -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    figure = Figure()
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    (line,) = axes.plot(
        np.array([0.0, 1.0]),
        np.array([2.0, 3.0]),
        picker=lambda *_: (
            True,
            {"pickx": np.array([0.0]), "picky": np.array([2.0])},
        ),
    )
    picked: list[tuple[float, float]] = []

    def on_pick(event: object) -> None:
        picked.append((float(event.pickx[0]), float(event.picky[0])))

    figure.canvas.mpl_connect("pick_event", on_pick)
    result = drive_behavior(
        engine="matplotlib",
        requirements=("interactive",),
        figures=[figure],
        namespace={"line": line},
    )

    assert result["status"] == "passed", result["errors"]
    assert (0.0, 2.0) in picked


def test_textbox_receives_resize_and_resubmits_a_valid_current_value() -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.widgets import TextBox

    figure = Figure()
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    axes.plot([-1, 1], [1, 1])
    box_axes = figure.add_axes((0.1, 0.02, 0.8, 0.08))
    box = TextBox(box_axes, "Evaluate")
    submitted: list[str] = []

    def submit(expression: str) -> None:
        eval(expression, {"np": np}, {"t": np.array([0.0, 1.0])})
        submitted.append(expression)

    box.on_submit(submit)
    box.set_val("t ** 2")
    submitted.clear()
    result = drive_behavior(
        engine="matplotlib",
        requirements=("interactive",),
        figures=[figure],
        namespace={"box": box},
    )

    assert result["status"] == "passed", result["errors"]
    resize = next(event for event in result["events"] if event["event"] == "resize_event")
    assert resize["probe_delivered"] is True
    assert submitted == ["np.sin(t)"]
    assert result["widgets"][0]["operation"] == "submit_valid_value"


def test_missing_behavior_evidence_is_a_hard_gate_failure() -> None:
    passed, reasons = behavior_gate({"status": "passed"}, ("interactive",))
    assert passed is False
    assert reasons == ["required behavior result is missing"]


def test_missing_behavior_evidence_is_a_ratchet_failure() -> None:
    errors, _warnings = _ratchet_case(
        entry={"path": "widgets/example.py", "behavior": ["interactive"]},
        baseline={
            "reference": {"status": "error"},
            "xy": {"status": "error"},
            "capture_parity": False,
            "dimension_parity": False,
            "visual_gate_passed": False,
            "semantic_gate_passed": False,
        },
        results={"xy": {"status": "passed"}},
        comparison={
            "capture_parity": False,
            "exact_dimension_parity": False,
            "visual_gate_passed": False,
            "semantic_gate_passed": False,
            "behavior_gate_passed": False,
        },
    )
    assert (
        "widgets/example.py: xy required behavior failed: required behavior result is missing"
        in errors
    )


def test_writer_animation_requires_three_captured_phases() -> None:
    frames = [{"frame_index": index, "state_sha256": str(index)} for index in range(5)]
    writer = {
        "type": "matplotlib.animation.FFMpegWriter",
        "frame_count": len(frames),
        "frames": frames,
        "phase_captures": {
            role: {"file": f"{role}.png"} for role in ("initial", "middle", "final")
        },
    }
    captured = drive_behavior(
        engine="matplotlib",
        requirements=("animation",),
        figures=[],
        namespace={},
        writer_frames=[writer],
        capture_animation_phase=lambda *_args: {},
    )
    assert captured["status"] == "passed", captured["errors"]
    assert [phase["role"] for phase in captured["writer_animations"][0]["phases"]] == [
        "initial",
        "middle",
        "final",
    ]

    writer["phase_captures"].pop("middle")
    missing = drive_behavior(
        engine="matplotlib",
        requirements=("animation",),
        figures=[],
        namespace={},
        writer_frames=[writer],
        capture_animation_phase=lambda *_args: {},
    )
    assert missing["status"] == "failed"
    assert any("missing a representative writer capture" in error for error in missing["errors"])


def test_real_pyplot_pause_animation_captures_initial_middle_and_final(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pause_animation.py"
    source.write_text(
        """\
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
line, = ax.plot([0, 1], [0, 0])
ax.set(xlim=(0, 1), ylim=(0, 5))
for frame in range(5):
    line.set_ydata([frame, frame + 0.5])
    plt.pause(0.01)
""",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=output,
        timeout=30,
        python=Path(sys.executable),
        behavior_requirements=("interactive", "animation"),
    )

    assert result["status"] == "passed", (output / "stderr.txt").read_text()
    assert result["behavior"]["status"] == "passed", result["behavior"]["errors"]
    assert [capture["stage"] for capture in result["captures"]] == [
        "animation-pause-initial",
        "animation-pause-middle",
        "animation-pause-final",
    ]
    assert [capture["animation_frame_index"] for capture in result["captures"]] == [0, 2, 4]
    assert len({capture["sha256"] for capture in result["captures"]}) == 3
    pause_record = result["behavior"]["pyplot_animations"][0]
    assert pause_record["type"] == "matplotlib.pyplot.pause"
    assert pause_record["frame_count"] == 5
    assert [phase["role"] for phase in pause_record["phases"]] == [
        "initial",
        "middle",
        "final",
    ]
    assert all(phase["captures"] for phase in pause_record["phases"])


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_matplotlib_311_resample_gallery_callback_accepts_step(
    tmp_path: Path,
    engine: str,
) -> None:
    source = tmp_path / "resample_callback.py"
    source.write_text(
        """\
import matplotlib.pyplot as plt
import numpy as np

fig, ax = plt.subplots()
x = np.linspace(0, 10, 101)
y = np.sin(x)
line, = ax.plot(x, y)
poly = ax.fill_between(x, y, y + 0.2, step="pre")
ax.set_autoscale_on(False)

def update(changed_axes):
    left, right = changed_axes.get_xlim()
    mask = (x >= left) & (x <= right)
    line.set_data(x[mask], y[mask])
    poly.set_data(x[mask], y[mask], y[mask] + 0.2, step="pre")
    changed_axes.figure.canvas.draw_idle()

ax.callbacks.connect("xlim_changed", update)
plt.show()
""",
        encoding="utf-8",
    )
    output = tmp_path / engine

    result = run_case(
        engine=engine,
        source_path=source,
        output_dir=output,
        timeout=30,
        python=Path(sys.executable),
        behavior_requirements=("interactive",),
    )

    assert result["status"] == "passed", (output / "stderr.txt").read_text()
    assert result["behavior"]["status"] == "passed", result["behavior"]["errors"]
    assert result["behavior"]["axes_callbacks"][0]["signal"] == "xlim_changed"
    if engine == "matplotlib":
        assert result["behavior"]["gallery_adapters"] == [
            {
                "artist_type": "matplotlib.collections.FillBetweenPolyCollection",
                "figure_index": 0,
                "id": "matplotlib-3.11-fill-between-set-data-step",
            }
        ]
    else:
        assert result["behavior"]["gallery_adapters"] == []


@pytest.mark.parametrize("engine", ["matplotlib", "xy"])
def test_figure_show_uses_the_nonblocking_gallery_capture_hook(
    tmp_path: Path,
    engine: str,
) -> None:
    source = tmp_path / "figure_show.py"
    source.write_text(
        """\
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.plot([0, 1], [0, 1])
fig.show()
""",
        encoding="utf-8",
    )
    output = tmp_path / engine

    result = run_case(
        engine=engine,
        source_path=source,
        output_dir=output,
        timeout=30,
        python=Path(sys.executable),
    )

    assert result["status"] == "passed", (output / "stderr.txt").read_text()
    assert result["show_count"] == 1
    assert result["capture_count"] == 1


def test_real_script_runtime_tracks_widget_animation_and_timer(tmp_path: Path) -> None:
    source = tmp_path / "behavior_case.py"
    source.write_text(
        """\
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Button

fig, ax = plt.subplots()
line, = ax.plot([], [])
ax.set(xlim=(0, 1), ylim=(0, 6))
button_ax = fig.add_axes((0.1, 0.02, 0.2, 0.08))
button = Button(button_ax, "Update")
button.on_clicked(lambda event: line.set_data([0, 1], [1, 0]))
animation = FuncAnimation(
    fig,
    lambda frame: (line.set_data([0, 1], [frame, frame + 1]), line)[1:],
    frames=5,
    interval=5,
)
plt.show()
""",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    result = run_case(
        engine="matplotlib",
        source_path=source,
        output_dir=output,
        timeout=30,
        python=Path(sys.executable),
        behavior_requirements=("interactive", "animation"),
    )

    assert result["status"] == "passed", (output / "stderr.txt").read_text()
    assert result["behavior"]["status"] == "passed", result["behavior"]["errors"]
    assert result["behavior"]["widgets"]
    assert result["behavior"]["animations"]
    assert result["behavior"]["timers"]
    assert result["capture_count"] == 3
    assert [capture["stage"] for capture in result["captures"]] == [
        "animation-initial",
        "animation-middle",
        "animation-final",
    ]
    assert len({capture["sha256"] for capture in result["captures"]}) == 3
    for capture in result["captures"]:
        path = output / capture["file"]
        with Image.open(path).convert("RGB") as image:
            background = Image.new("RGB", image.size, image.getpixel((0, 0)))
            assert ImageChops.difference(image, background).getbbox() is not None
        metrics = compare_images(path, path)
        assert evaluate_visual(metrics, "text_thin_line").decision == "pass"
    assert result["deterministic_seed"] == {
        "numpy_random": True,
        "python_random": True,
        "value": 19680801,
    }


def test_reference_and_xy_processes_receive_the_same_global_random_seed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "random_case.py"
    source_text = """\
import json
import random

import matplotlib.pyplot as plt
import numpy as np

print(json.dumps([random.random(), np.random.random()], sort_keys=True))
"""
    source.write_text(source_text, encoding="utf-8")
    original_ast = ast.dump(ast.parse(source_text), include_attributes=False)
    outputs: dict[str, str] = {}
    for engine in ("matplotlib", "xy"):
        output = tmp_path / engine
        result = run_case(
            engine=engine,
            source_path=source,
            output_dir=output,
            timeout=30,
            python=Path(sys.executable),
        )
        assert result["status"] == "passed", (output / "stderr.txt").read_text()
        outputs[engine] = (output / "stdout.txt").read_text().strip()
        assert result["deterministic_seed"]["value"] == 19680801

    assert json.loads(outputs["matplotlib"]) == json.loads(outputs["xy"])
    assert ast.dump(ast.parse(source.read_text()), include_attributes=False) == original_ast
    random.seed(19680801)
    np.random.seed(19680801)
    assert json.loads(outputs["matplotlib"]) == [random.random(), np.random.random()]


def test_capture_slots_track_unique_figures_and_keep_the_latest_state(
    tmp_path: Path,
) -> None:
    source = tmp_path / "multi_show.py"
    source.write_text(
        """\
import matplotlib.pyplot as plt

first = plt.figure()
first.subplots().plot([0, 1], [0, 1])
plt.show()
second = plt.figure()
second.subplots().plot([0, 1], [1, 0])
plt.show()
first.suptitle("retained final state")
plt.show()
plt.close(first)
replacement = plt.figure(1)
replacement.subplots().plot([0, 1], [0.5, 0.5])
replacement.suptitle("replacement figure")
plt.show()
""",
        encoding="utf-8",
    )

    for engine in ("matplotlib", "xy"):
        output = tmp_path / engine
        result = run_case(
            engine=engine,
            source_path=source,
            output_dir=output,
            timeout=30,
            python=Path(sys.executable),
        )
        assert result["status"] == "passed", (output / "stderr.txt").read_text()
        assert result["capture_count"] == 3
        assert [capture["figure_number"] for capture in result["captures"]] == [1, 2, 1]
        assert result["captures"][0]["semantic"]["figure_text"] == ["retained final state"]
        assert result["captures"][2]["semantic"]["figure_text"] == ["replacement figure"]
