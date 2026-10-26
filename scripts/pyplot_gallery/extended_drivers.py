"""Source-independent deterministic drivers for extended gallery cases."""

from __future__ import annotations

import sys
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from types import SimpleNamespace

INPUT_DRIVER_FIELDS = frozenset(
    {
        "ginput",
        "manual_clabel",
        "waitforbuttonpress",
    }
)
TIMER_DRIVER_FIELDS = frozenset(
    {
        "checkpoint_after_seconds",
        "checkpoint_line_count",
        "poll_interval_seconds",
        "show_policy",
    }
)
ACTION_DRIVER_FIELDS = frozenset(
    {
        "color_filters",
        "motion",
        "toolbar_action",
        "tool_triggers",
    }
)
CONTROL_DRIVER_FIELDS = frozenset(
    {
        "multiprocessing_start_method",
        "sleep_scale",
    }
)
SUPPORTED_DRIVER_FIELDS = (
    INPUT_DRIVER_FIELDS | TIMER_DRIVER_FIELDS | ACTION_DRIVER_FIELDS | CONTROL_DRIVER_FIELDS
)


class ScriptedInputDriver:
    """Consume the checked-in wait, point, and manual-label script exactly."""

    def __init__(self, settings: Mapping[str, object]) -> None:
        self._wait = deque(settings.get("waitforbuttonpress", []))
        self._ginput = deque(settings.get("ginput", []))
        manual = settings.get("manual_clabel", [])
        self._manual_clabel = [tuple(float(value) for value in point) for point in manual]
        self._manual_clabel_available = bool(self._manual_clabel)
        self.wait_results: list[bool] = []
        self.ginput_results: list[list[tuple[float, float]]] = []
        self.manual_clabel_results: list[list[tuple[float, float]]] = []

    @property
    def configured(self) -> bool:
        return bool(self._wait or self._ginput or self._manual_clabel_available)

    def waitforbuttonpress(self, *_args: object, **_kwargs: object) -> bool:
        if not self._wait:
            raise RuntimeError("deterministic waitforbuttonpress script is exhausted")
        result = bool(self._wait.popleft())
        self.wait_results.append(result)
        return result

    def ginput(self, n: int = 1, *_args: object, **_kwargs: object) -> list[tuple[float, float]]:
        if not self._ginput:
            raise RuntimeError("deterministic ginput script is exhausted")
        raw = self._ginput.popleft()
        if not isinstance(raw, Mapping):
            raise RuntimeError("deterministic ginput entry must be an object")
        points = [
            (float(point[0]), float(point[1]))
            for point in raw.get("points", [])
            if isinstance(point, (list, tuple)) and len(point) == 2
        ]
        if len(points) > n:
            raise RuntimeError(
                f"deterministic ginput returned {len(points)} points for a request of {n}"
            )
        self.ginput_results.append(points)
        return points

    def clabel(
        self,
        original: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        if kwargs.get("manual") is True:
            if not self._manual_clabel_available:
                raise RuntimeError("manual clabel requested without deterministic positions")
            positions = list(self._manual_clabel)
            self._manual_clabel_available = False
            kwargs["manual"] = positions
            self.manual_clabel_results.append(positions)
        return original(*args, **kwargs)

    def evidence(self) -> dict[str, object]:
        return {
            "waitforbuttonpress": self.wait_results,
            "ginput": [[list(point) for point in points] for points in self.ginput_results],
            "manual_clabel": [
                [list(point) for point in points] for points in self.manual_clabel_results
            ],
            "remaining": {
                "waitforbuttonpress": len(self._wait),
                "ginput": len(self._ginput),
                "manual_clabel": int(self._manual_clabel_available),
            },
        }


def _widget_text(widget: object | None) -> str | None:
    if widget is None:
        return None
    for name in ("get_text", "get_label"):
        getter = getattr(widget, name, None)
        if callable(getter):
            value = getter()
            return None if value is None else str(value)
    return None


def _callback_count(registry: object, event: str) -> int:
    callbacks = getattr(registry, "callbacks", {})
    try:
        return len(callbacks.get(event, {}))
    except (AttributeError, TypeError):
        return 0


def _tracked_filter(
    original: Callable[[object, object], object],
    calls: list[tuple[object, object]],
) -> Callable[[object, object], object]:
    def invoke(image: object, dpi: object) -> object:
        calls.append((image, dpi))
        return original(image, dpi)

    return invoke


def _drive_color_filters(
    *,
    filters: object,
    figures: list[object],
    namespace: Mapping[str, object] | None,
) -> dict[str, object]:
    if (
        not isinstance(filters, list)
        or not filters
        or not all(isinstance(name, str) for name in filters)
    ):
        raise RuntimeError("color_filters must be a non-empty list of names")
    if not figures:
        raise RuntimeError("color filter driver requires a live figure")
    callback = namespace.get("_set_menu_entry") if namespace is not None else None
    if not callable(callback):
        raise RuntimeError("color filter driver cannot find the source _set_menu_entry callback")

    figure = figures[0]
    canvas = getattr(figure, "canvas", None)
    draw = getattr(canvas, "draw", None)
    set_filter = getattr(figure, "set_agg_filter", None)
    get_filter = getattr(figure, "get_agg_filter", None)
    if canvas is None or not callable(draw) or not callable(set_filter):
        raise RuntimeError("color filter driver requires a drawable Figure canvas")
    original_filter = get_filter() if callable(get_filter) else None
    manager = getattr(canvas, "manager", None)
    toolbar = getattr(manager, "toolbar", None)
    callback_toolbar = (
        toolbar if getattr(toolbar, "canvas", None) is canvas else SimpleNamespace(canvas=canvas)
    )
    records: list[dict[str, object]] = []
    try:
        for name in filters:
            callback(callback_toolbar, name)
            active_filter = get_filter() if callable(get_filter) else None
            if not callable(active_filter):
                raise RuntimeError(f"color filter {name!r} did not install a Figure filter")
            filter_calls: list[tuple[object, object]] = []
            set_filter(_tracked_filter(active_filter, filter_calls))
            draw()
            if not filter_calls:
                raise RuntimeError(f"renderer did not execute color filter {name!r}")
            records.append(
                {
                    "name": name,
                    "active": True,
                    "filter_calls": len(filter_calls),
                    "toolbar_type": (
                        f"{type(toolbar).__module__}.{type(toolbar).__qualname__}"
                        if toolbar is not None
                        else None
                    ),
                    "canvas_type": f"{type(canvas).__module__}.{type(canvas).__qualname__}",
                    "fallback_used": bool(getattr(canvas, "fallback_used", False)),
                }
            )
    finally:
        set_filter(original_filter)
        draw()
    return {
        "status": "passed",
        "actions": records,
        "restored": (get_filter() if callable(get_filter) else None) is original_filter,
    }


def _drive_motion(
    *,
    coordinates: object,
    figures: list[object],
    namespace: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(coordinates, list) or not coordinates:
        raise RuntimeError("motion must be a non-empty list of [x, y] coordinates")
    if not figures:
        raise RuntimeError("motion driver requires a live figure")
    backend_bases = sys.modules.get("matplotlib.backend_bases")
    mouse_event_type = getattr(backend_bases, "MouseEvent", None)
    if not callable(mouse_event_type):
        raise RuntimeError("motion driver requires matplotlib.backend_bases.MouseEvent")

    figure = figures[0]
    canvas = getattr(figure, "canvas", None)
    registry = getattr(canvas, "callbacks", None)
    connect = getattr(canvas, "mpl_connect", None)
    disconnect = getattr(canvas, "mpl_disconnect", None)
    if registry is None or not callable(connect) or not callable(disconnect):
        raise RuntimeError("motion driver requires a canvas callback registry")
    event_name = "motion_notify_event"
    source_callbacks = _callback_count(registry, event_name)
    if source_callbacks == 0:
        raise RuntimeError("motion driver found no source callback")

    probe_events: list[object] = []
    callback_id = connect(event_name, probe_events.append)
    original_handler = getattr(registry, "exception_handler", None)
    label = namespace.get("label") if namespace is not None else None
    initial_label = _widget_text(label)
    records: list[dict[str, object]] = []

    def raise_callback_exception(exc: BaseException) -> None:
        raise exc

    try:
        if hasattr(registry, "exception_handler"):
            registry.exception_handler = raise_callback_exception
        for raw in coordinates:
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                raise RuntimeError("motion coordinates must contain exactly two values")
            x, y = float(raw[0]), float(raw[1])
            before = len(probe_events)
            event = mouse_event_type(event_name, canvas, x, y)
            registry.process(event_name, event)
            if len(probe_events) != before + 1:
                raise RuntimeError("motion event did not reach the probe callback")
            records.append(
                {
                    "x": x,
                    "y": y,
                    "xdata": getattr(event, "xdata", None),
                    "ydata": getattr(event, "ydata", None),
                    "inaxes": getattr(event, "inaxes", None) is not None,
                    "label_text": _widget_text(label),
                }
            )
    finally:
        if hasattr(registry, "exception_handler"):
            registry.exception_handler = original_handler
        disconnect(callback_id)
    final_label = _widget_text(label)
    if label is not None and final_label == initial_label:
        raise RuntimeError("motion callback did not update the source label")
    return {
        "status": "passed",
        "source_callbacks": source_callbacks,
        "probe_deliveries": len(probe_events),
        "events": records,
        "initial_label": initial_label,
        "final_label": final_label,
    }


def _drive_toolbar_action(
    *,
    action: object,
    namespace: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(action, str) or not action:
        raise RuntimeError("toolbar_action must be a non-empty label")
    button = namespace.get("button") if namespace is not None else None
    connect = getattr(button, "connect", None)
    emit = getattr(button, "emit", None)
    disconnect = getattr(button, "disconnect", None)
    if not callable(connect) or not callable(emit):
        raise RuntimeError("toolbar action cannot find a signal-capable source button")
    label = _widget_text(button)
    if label != action:
        raise RuntimeError(f"toolbar button label {label!r} does not match action {action!r}")
    probe_calls: list[object] = []
    handler_id = connect("clicked", lambda source: probe_calls.append(source))
    try:
        emit("clicked")
    finally:
        if callable(disconnect):
            disconnect(handler_id)
    if len(probe_calls) != 1:
        raise RuntimeError("toolbar clicked signal did not reach the probe callback exactly once")
    return {
        "status": "passed",
        "action": action,
        "button_type": f"{type(button).__module__}.{type(button).__qualname__}",
        "probe_deliveries": len(probe_calls),
    }


def _line_visibility(figure: object) -> list[bool]:
    return [
        bool(line.get_visible())
        for axes in getattr(figure, "axes", ())
        for line in getattr(axes, "lines", ())
        if callable(getattr(line, "get_visible", None))
    ]


def _drive_tool_triggers(
    *,
    triggers: object,
    figures: list[object],
) -> dict[str, object]:
    if (
        not isinstance(triggers, list)
        or not triggers
        or not all(isinstance(name, str) for name in triggers)
    ):
        raise RuntimeError("tool_triggers must be a non-empty list of tool names")
    if not figures:
        raise RuntimeError("tool trigger driver requires a live figure")
    figure = figures[0]
    canvas = getattr(figure, "canvas", None)
    manager = getattr(canvas, "manager", None)
    toolmanager = getattr(manager, "toolmanager", None)
    toolbar = getattr(manager, "toolbar", None)
    connect = getattr(toolmanager, "toolmanager_connect", None)
    disconnect = getattr(toolmanager, "toolmanager_disconnect", None)
    if toolmanager is None or not callable(connect) or not callable(disconnect):
        raise RuntimeError("tool trigger driver requires a ToolManager")

    records: list[dict[str, object]] = []
    for name in triggers:
        tools = getattr(toolmanager, "tools", {})
        if name not in tools:
            raise RuntimeError(f"tool trigger driver cannot find tool {name!r}")
        events: list[object] = []
        callback_id = connect(f"tool_trigger_{name}", events.append)
        try:
            toolbar_trigger = getattr(toolbar, "trigger_tool", None)
            if callable(toolbar_trigger):
                toolbar_trigger(name)
                route = "toolbar"
            else:
                toolmanager.trigger_tool(name)
                route = "toolmanager"
        finally:
            disconnect(callback_id)
        if len(events) != 1:
            raise RuntimeError(f"tool {name!r} did not emit exactly one trigger event")
        tool = tools[name]
        records.append(
            {
                "name": name,
                "route": route,
                "tool_type": f"{type(tool).__module__}.{type(tool).__qualname__}",
                "toggled": getattr(tool, "toggled", None),
                "line_visibility": _line_visibility(figure),
                "probe_deliveries": len(events),
            }
        )
    return {
        "status": "passed",
        "actions": records,
        "toolbar_type": (
            f"{type(toolbar).__module__}.{type(toolbar).__qualname__}"
            if toolbar is not None
            else None
        ),
    }


def drive_extended_actions(
    *,
    settings: Mapping[str, object],
    figures: Iterable[object],
    namespace: Mapping[str, object] | None,
) -> dict[str, object]:
    """Execute every declared UI/tool action against the live source objects."""

    figure_list = list(figures)
    drivers = {
        "color_filters": lambda value: _drive_color_filters(
            filters=value,
            figures=figure_list,
            namespace=namespace,
        ),
        "motion": lambda value: _drive_motion(
            coordinates=value,
            figures=figure_list,
            namespace=namespace,
        ),
        "toolbar_action": lambda value: _drive_toolbar_action(
            action=value,
            namespace=namespace,
        ),
        "tool_triggers": lambda value: _drive_tool_triggers(
            triggers=value,
            figures=figure_list,
        ),
    }
    evidence: dict[str, object] = {}
    errors: list[str] = []
    for field in sorted(ACTION_DRIVER_FIELDS & settings.keys()):
        try:
            evidence[field] = drivers[field](settings[field])
        except BaseException as exc:
            evidence[field] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            errors.append(f"{field}: {type(exc).__name__}: {exc}")
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "drivers": evidence,
    }


def drive_timer_until_close(
    *,
    timers: Iterable[object],
    live_figures: Callable[[], list[object]],
    checkpoint: Callable[[], None],
    settings: Mapping[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    """Service headless Matplotlib timers until their callback closes the figure."""

    poll_interval = float(settings.get("poll_interval_seconds", 0.02))
    checkpoint_after = float(settings.get("checkpoint_after_seconds", 1.0))
    checkpoint_line_count = settings.get("checkpoint_line_count")
    if checkpoint_line_count is not None:
        checkpoint_line_count = int(checkpoint_line_count)
    if poll_interval <= 0:
        raise ValueError("timer poll interval must be positive")
    if checkpoint_after < 0:
        raise ValueError("timer checkpoint delay cannot be negative")
    if checkpoint_line_count is not None and checkpoint_line_count <= 0:
        raise ValueError("timer checkpoint line count must be positive")

    started = time.monotonic()
    turns = 0
    callback_dispatches = 0
    checkpointed = False
    observed_line_count = 0
    captured_line_count: int | None = None
    while live_figures():
        active_timers = list(timers)
        if not active_timers:
            raise RuntimeError("native-until-close show requires at least one tracked timer")
        for timer in active_timers:
            on_timer = getattr(timer, "_on_timer", None)
            if not callable(on_timer):
                raise RuntimeError(f"{type(timer).__name__} has no timer dispatch method")
            on_timer()
            callback_dispatches += 1
        turns += 1
        elapsed = time.monotonic() - started
        figures = live_figures()
        observed_line_count = sum(
            len(getattr(axes, "lines", ()))
            for figure in figures
            for axes in getattr(figure, "axes", ())
        )
        checkpoint_ready = (
            observed_line_count >= checkpoint_line_count
            if checkpoint_line_count is not None
            else elapsed >= checkpoint_after
        )
        if not checkpointed and checkpoint_ready and figures:
            checkpoint()
            checkpointed = True
            captured_line_count = observed_line_count
        if elapsed > timeout_seconds:
            raise TimeoutError(
                f"native-until-close timer driver exceeded {timeout_seconds:g} seconds"
            )
        if live_figures():
            time.sleep(poll_interval)

    if not checkpointed:
        raise RuntimeError("timer-driven figure closed before a live checkpoint was captured")
    return {
        "status": "passed",
        "turns": turns,
        "callback_dispatches": callback_dispatches,
        "checkpointed": checkpointed,
        "checkpoint_line_count": captured_line_count,
        "duration_seconds": round(time.monotonic() - started, 6),
    }
