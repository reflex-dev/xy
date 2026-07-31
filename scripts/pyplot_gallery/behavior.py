"""Deterministic event, widget, timer, and animation gallery probes.

The probes run against the live Matplotlib objects created by an upstream
example.  XY browser-shaped events traverse the actual anywidget message
handler; backend-neutral events use the canvas callback registry.  Widgets
receive events in their own axes, timers execute one callback turn, and
animations draw a bounded set of representative frames.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import sys
import traceback
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from typing import Any

REQUIRED_CANVAS_EVENTS = (
    "draw_event",
    "resize_event",
    "figure_enter_event",
    "axes_enter_event",
    "motion_notify_event",
    "button_press_event",
    "button_release_event",
    "scroll_event",
    "key_press_event",
    "key_release_event",
    "pick_event",
    "axes_leave_event",
    "figure_leave_event",
    "close_event",
)
WIDGET_TRANSPORT_EVENTS = frozenset(
    {
        "resize_event",
        "figure_enter_event",
        "motion_notify_event",
        "button_press_event",
        "button_release_event",
        "scroll_event",
        "key_press_event",
        "key_release_event",
        "figure_leave_event",
        "close_event",
    }
)
MAX_ANIMATION_FRAMES = 4096
DEFAULT_UNBOUNDED_FRAMES = 64
MAX_NAMESPACE_OBJECTS = 4096
GATED_BEHAVIORS = frozenset(
    {
        "animation",
        "coordinates",
        "cursor",
        "interactive",
        "navigation",
    }
)


def _exception_record(context: str, exc: BaseException) -> dict[str, str]:
    return {
        "context": context,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def _stable_value(value: object) -> object:
    """Return a small, deterministic token for common Artist state values."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return round(value, 12)
    if isinstance(value, bytes):
        return {
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        values = list(value)
        if len(values) > 32:
            values = values[:16] + values[-16:]
        return [_stable_value(item) for item in values]
    tobytes = getattr(value, "tobytes", None)
    if callable(tobytes):
        try:
            data = tobytes()
            return {
                "type": type(value).__name__,
                "shape": list(getattr(value, "shape", ())),
                "dtype": str(getattr(value, "dtype", "")),
                "byte_count": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        except BaseException:
            pass
    try:
        text = repr(value)
    except BaseException:
        text = f"<{type(value).__module__}.{type(value).__qualname__}>"
    if len(text) > 2048:
        text = text[:1024] + "…" + text[-1024:]
    return text


def figure_state_sha256(figure: object) -> str:
    """Hash renderer-independent visible Artist state for behavior evidence."""

    records: list[dict[str, object]] = []
    findobj = getattr(figure, "findobj", None)
    try:
        artists = list(findobj()) if callable(findobj) else []
    except BaseException:
        artists = []
    getters = (
        "get_visible",
        "get_text",
        "get_data",
        "get_data_3d",
        "get_offsets",
        "get_array",
        "get_segments",
        "get_xy",
        "get_width",
        "get_height",
        "get_angle",
        "get_alpha",
        "get_bbox_to_anchor",
        "get_position",
        "get_xlim",
        "get_ylim",
        "get_zlim",
    )
    for artist in artists:
        record: dict[str, object] = {
            "type": f"{type(artist).__module__}.{type(artist).__qualname__}",
        }
        for getter_name in getters:
            getter = getattr(artist, getter_name, None)
            if not callable(getter):
                continue
            try:
                record[getter_name] = _stable_value(getter())
            except BaseException:
                continue
        records.append(record)
    payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _callback_count(registry: object, signal: str) -> int:
    callbacks = getattr(registry, "callbacks", {})
    try:
        return len(callbacks.get(signal, {}))
    except (AttributeError, TypeError):
        return 0


def _axes_center(figure: object, *, axes: object | None = None) -> tuple[float, float]:
    candidate = axes
    if candidate is None:
        all_axes = list(getattr(figure, "axes", []))
        candidate = all_axes[0] if all_axes else None
    bbox = getattr(candidate, "bbox", None)
    if bbox is None:
        bbox = getattr(figure, "bbox", None)
    try:
        return (
            float(bbox.x0 + bbox.x1) / 2.0,
            float(bbox.y0 + bbox.y1) / 2.0,
        )
    except (AttributeError, TypeError, ValueError):
        return (1.0, 1.0)


def _pick_artist(figure: object) -> object:
    fallback = getattr(figure, "patch", figure)
    for axes in list(getattr(figure, "axes", [])):
        get_children = getattr(axes, "get_children", None)
        try:
            children = list(get_children()) if callable(get_children) else []
        except BaseException:
            children = []
        for artist in children:
            get_picker = getattr(artist, "get_picker", None)
            try:
                picker = get_picker() if callable(get_picker) else None
            except BaseException:
                picker = None
            if picker not in (None, False):
                return artist
            if fallback is figure:
                fallback = artist
    return fallback


def _event_object(
    event_name: str,
    *,
    canvas: object,
    figure: object,
    axes: object | None = None,
    xy: tuple[float, float] | None = None,
    button: object | None = None,
    buttons: set[object] | None = None,
    key: str | None = None,
) -> object:
    backend_bases = sys.modules.get("matplotlib.backend_bases")
    if backend_bases is None:
        raise RuntimeError("matplotlib.backend_bases is not loaded")
    x, y = xy or _axes_center(figure, axes=axes)
    if event_name == "resize_event":
        event = backend_bases.ResizeEvent(event_name, canvas)
        event.x = x
        event.y = y
        all_axes = list(getattr(figure, "axes", []))
        event.inaxes = axes or (all_axes[0] if all_axes else None)
        event.xdata = event.ydata = None
        if event.inaxes is not None:
            with suppress(AttributeError, TypeError, ValueError):
                event.xdata, event.ydata = event.inaxes.transData.inverted().transform((x, y))
        return event
    if event_name == "close_event":
        return backend_bases.CloseEvent(event_name, canvas)
    if event_name in {
        "figure_enter_event",
        "figure_leave_event",
        "axes_enter_event",
        "axes_leave_event",
    }:
        return backend_bases.LocationEvent(event_name, canvas, x, y)
    if event_name.startswith("key_"):
        return backend_bases.KeyEvent(event_name, canvas, key=key or "a", x=x, y=y)
    if event_name == "scroll_event":
        return backend_bases.MouseEvent(
            event_name,
            canvas,
            x,
            y,
            button="up",
            step=1,
        )
    if event_name in {"button_press_event", "button_release_event"}:
        event_button = button or getattr(
            getattr(backend_bases, "MouseButton", None),
            "LEFT",
            1,
        )
        return backend_bases.MouseEvent(event_name, canvas, x, y, button=event_button)
    if event_name == "pick_event":
        mouse_event = backend_bases.MouseEvent(
            "button_press_event",
            canvas,
            x,
            y,
            button=getattr(getattr(backend_bases, "MouseButton", None), "LEFT", 1),
        )
        artist = _pick_artist(figure)
        properties: dict[str, object] = {"ind": [0]}
        try:
            xdata = artist.get_xdata()
            ydata = artist.get_ydata()
            try:
                properties["pickx"] = xdata[[0]]
            except (IndexError, TypeError):
                properties["pickx"] = [xdata[0]]
            try:
                properties["picky"] = ydata[[0]]
            except (IndexError, TypeError):
                properties["picky"] = [ydata[0]]
        except (AttributeError, IndexError, TypeError, KeyError):
            pass
        return backend_bases.PickEvent(
            event_name,
            canvas,
            mouse_event,
            artist,
            **properties,
        )
    return backend_bases.MouseEvent(
        event_name,
        canvas,
        x,
        y,
        buttons=buttons,
        key=key,
    )


def _widget_message(
    event_name: str,
    *,
    figure: object,
    axes: object | None = None,
    xy: tuple[float, float] | None = None,
    button: int = 0,
    buttons: int = 0,
    key: str = "a",
) -> dict[str, object]:
    """Build the same validated payload emitted by the live browser widget."""
    if event_name not in WIDGET_TRANSPORT_EVENTS:
        raise ValueError(f"{event_name} has no browser-widget transport mapping")
    if event_name == "close_event":
        return {"type": "event", "name": event_name}
    if event_name == "resize_event":
        bbox = getattr(figure, "bbox", None)
        width = max(1, round(float(getattr(bbox, "width", 1))))
        height = max(1, round(float(getattr(bbox, "height", 1))))
        return {
            "type": "event",
            "name": event_name,
            "width": width,
            "height": height,
        }
    if event_name.startswith("key_"):
        return {"type": "event", "name": event_name, "key": key}
    x, y = xy or _axes_center(figure, axes=axes)
    message: dict[str, object] = {
        "type": "event",
        "name": event_name,
        "x": x,
        "y": y,
        "modifiers": [],
    }
    if event_name in {"button_press_event", "button_release_event"}:
        message["button"] = button
    elif event_name == "motion_notify_event":
        message["buttons"] = buttons
    elif event_name == "scroll_event":
        message["step"] = 1
    return message


def dispatch_canvas_event(
    figure: object,
    event_name: str,
    *,
    axes: object | None = None,
    context: str | None = None,
    widget_transport: bool = False,
    xy: tuple[float, float] | None = None,
    button: object | None = None,
    buttons: set[object] | None = None,
    widget_button: int = 0,
    widget_buttons: int = 0,
    key: str | None = None,
) -> dict[str, Any]:
    """Dispatch one event and report registered and delivered callback counts."""

    canvas = getattr(figure, "canvas", None)
    registry = getattr(canvas, "callbacks", None)
    record: dict[str, Any] = {
        "event": event_name,
        "context": context or event_name,
        "attempted": True,
        "source_callbacks": _callback_count(registry, event_name),
        "attempted_callbacks": 0,
        "delivered_callbacks": 0,
        "probe_delivered": False,
        "transport": "widget" if widget_transport else "canvas_registry",
        "failure": None,
    }
    if canvas is None or registry is None:
        record["failure"] = {
            "context": record["context"],
            "exception_type": "MissingCallbackRegistry",
            "message": "figure canvas has no callback registry",
            "traceback": "",
        }
        return record

    probe_calls: list[str] = []

    def probe(_event: object) -> None:
        probe_calls.append(event_name)

    connect = getattr(canvas, "mpl_connect", None)
    disconnect = getattr(canvas, "mpl_disconnect", None)
    callback_id: object | None = None
    original_exception_handler = getattr(registry, "exception_handler", None)

    def raise_callback_exception(exc: BaseException) -> None:
        raise exc

    try:
        if not callable(connect):
            raise RuntimeError("canvas does not implement mpl_connect")
        callback_id = connect(event_name, probe)
        registered = _callback_count(registry, event_name)
        record["attempted_callbacks"] = registered
        if hasattr(registry, "exception_handler"):
            registry.exception_handler = raise_callback_exception
        if widget_transport:
            widget = getattr(canvas, "widget", None)
            handler = getattr(widget, "_on_custom_msg", None)
            if widget is None or not callable(handler):
                raise RuntimeError("canvas does not expose the live XY widget transport")
            message = _widget_message(
                event_name,
                figure=figure,
                axes=axes,
                xy=xy,
                button=widget_button,
                buttons=widget_buttons,
                key=key or "a",
            )
            record["browser_message"] = _stable_value(message)
            handler(widget, message, [])
        elif event_name == "draw_event":
            draw = getattr(canvas, "draw", None)
            if not callable(draw):
                raise RuntimeError("canvas does not implement draw")
            draw()
        else:
            event = _event_object(
                event_name,
                canvas=canvas,
                figure=figure,
                axes=axes,
                xy=xy,
                button=button,
                buttons=buttons,
                key=key,
            )
            record["inaxes"] = getattr(event, "inaxes", None) is not None
            registry.process(event_name, event)
        record["probe_call_count"] = len(probe_calls)
        record["probe_delivered"] = bool(probe_calls)
        record["delivered_callbacks"] = registered if record["probe_delivered"] else 0
        record["state_sha256"] = figure_state_sha256(figure)
    except BaseException as exc:
        record["failure"] = _exception_record(str(record["context"]), exc)
    finally:
        if hasattr(registry, "exception_handler"):
            registry.exception_handler = original_exception_handler
        if callback_id is not None and callable(disconnect):
            try:
                disconnect(callback_id)
            except BaseException as exc:
                if record["failure"] is None:
                    record["failure"] = _exception_record(
                        f"{record['context']}: disconnect",
                        exc,
                    )
    return record


def _axes_limits(figure: object) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, axes in enumerate(list(getattr(figure, "axes", []))):
        record: dict[str, object] = {"axes_index": index}
        for axis_name in ("x", "y", "z"):
            getter = getattr(axes, f"get_{axis_name}lim", None)
            if not callable(getter):
                continue
            with suppress(BaseException):
                record[f"{axis_name}lim"] = _stable_value(getter())
        records.append(record)
    return records


def _contracted_limits(value: object) -> tuple[float, float]:
    try:
        low_value, high_value = value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected a two-value limit, got {value!r}") from exc
    low, high = float(low_value), float(high_value)
    if not math.isfinite(low) or not math.isfinite(high) or low == high:
        return (-1.0, 1.0)
    span = high - low
    return low + 0.2 * span, high - 0.2 * span


def install_matplotlib_311_gallery_adapters(figure: object) -> list[dict[str, object]]:
    """Install narrowly-scoped adapters for inconsistent 3.11 gallery calls."""

    findobj = getattr(figure, "findobj", None)
    artists = list(findobj()) if callable(findobj) else []
    records: list[dict[str, object]] = []
    for artist in artists:
        artist_type = type(artist)
        if (
            artist_type.__module__ != "matplotlib.collections"
            or artist_type.__name__ != "FillBetweenPolyCollection"
        ):
            continue
        original = getattr(artist, "set_data", None)
        if not callable(original):
            continue
        if getattr(original, "__xy_matplotlib_311_gallery_compat__", False):
            continue
        with suppress(TypeError, ValueError):
            if "step" in inspect.signature(original).parameters:
                continue

        def set_data(
            t: object,
            f1: object,
            f2: object,
            *,
            where: object = None,
            step: str | None = None,
            _original: Callable[..., object] = original,
            _artist: object = artist,
        ) -> object:
            if step is not None:
                _artist._step = step
            return _original(t, f1, f2, where=where)

        artist.set_data = set_data
        records.append(
            {
                "id": "matplotlib-3.11-fill-between-set-data-step",
                "artist_type": f"{artist_type.__module__}.{artist_type.__qualname__}",
            }
        )
    return records


def drive_axes_callbacks(figure: object) -> list[dict[str, Any]]:
    """Change registered axes limits and require callback-registry delivery."""

    records: list[dict[str, Any]] = []
    for axes_index, axes in enumerate(list(getattr(figure, "axes", []))):
        registry = getattr(axes, "callbacks", None)
        for signal, getter_name, setter_name in (
            ("xlim_changed", "get_xlim", "set_xlim"),
            ("ylim_changed", "get_ylim", "set_ylim"),
            ("zlim_changed", "get_zlim", "set_zlim"),
        ):
            source_callbacks = _callback_count(registry, signal)
            if registry is None or source_callbacks == 0:
                continue
            getter = getattr(axes, getter_name, None)
            setter = getattr(axes, setter_name, None)
            record: dict[str, Any] = {
                "axes_index": axes_index,
                "signal": signal,
                "source_callbacks": source_callbacks,
                "probe_delivered": False,
                "state_changed": False,
                "failure": None,
            }
            records.append(record)
            callback_id: object | None = None
            original_exception_handler = getattr(registry, "exception_handler", None)
            probe_calls: list[object] = []

            def raise_callback_exception(exc: BaseException) -> None:
                raise exc

            try:
                if not callable(getter) or not callable(setter):
                    raise RuntimeError(f"axes does not implement {getter_name}/{setter_name}")
                before = getter()
                before_state = figure_state_sha256(figure)
                callback_id = registry.connect(signal, probe_calls.append)
                if hasattr(registry, "exception_handler"):
                    registry.exception_handler = raise_callback_exception
                setter(*_contracted_limits(before), emit=True)
                draw_idle = getattr(getattr(figure, "canvas", None), "draw_idle", None)
                if callable(draw_idle):
                    draw_idle()
                after = getter()
                after_state = figure_state_sha256(figure)
                record.update(
                    {
                        "before": _stable_value(before),
                        "after": _stable_value(after),
                        "probe_call_count": len(probe_calls),
                        "probe_delivered": bool(probe_calls),
                        "state_before_sha256": before_state,
                        "state_after_sha256": after_state,
                        "state_changed": before_state != after_state,
                    }
                )
                if not probe_calls:
                    raise RuntimeError(f"{signal} did not deliver its probe callback")
                if before_state == after_state:
                    raise RuntimeError(f"{signal} did not change visible axes state")
            except BaseException as exc:
                record["failure"] = _exception_record(
                    f"axes {axes_index}: {signal}",
                    exc,
                )
            finally:
                if hasattr(registry, "exception_handler"):
                    registry.exception_handler = original_exception_handler
                if callback_id is not None:
                    with suppress(BaseException):
                        registry.disconnect(callback_id)
    return records


def _axes_drag_points(axes: object) -> tuple[tuple[float, float], tuple[float, float]]:
    bbox = axes.bbox
    width = float(bbox.x1 - bbox.x0)
    height = float(bbox.y1 - bbox.y0)
    return (
        (float(bbox.x0) + width * 0.42, float(bbox.y0) + height * 0.46),
        (float(bbox.x0) + width * 0.62, float(bbox.y0) + height * 0.61),
    )


def drive_navigation(figure: object, *, engine: str) -> dict[str, Any]:
    """Exercise real 2-D pan or 3-D rotation through the live XY transport."""

    axes_list = [
        axes
        for axes in list(getattr(figure, "axes", []))
        if bool(getattr(axes, "get_navigate", lambda: True)())
    ]
    record: dict[str, Any] = {
        "attempted": True,
        "transport": "widget" if engine == "xy" else "axes_pan",
        "axes_index": None,
        "events": [],
        "state_changed": False,
        "failure": None,
    }
    if not axes_list:
        record["failure"] = _exception_record(
            "navigation",
            RuntimeError("figure has no navigable axes"),
        )
        return record

    axes = next(
        (candidate for candidate in axes_list if getattr(candidate, "_colorbar", None) is not None),
        axes_list[0],
    )
    record["axes_index"] = list(getattr(figure, "axes", [])).index(axes)
    canvas = getattr(figure, "canvas", None)
    draw = getattr(canvas, "draw", None)
    if callable(draw):
        draw()
    start, end = _axes_drag_points(axes)
    is_3d = hasattr(axes, "get_zlim") and hasattr(axes, "azim")
    before = {
        "limits": _axes_limits(figure),
        "view": _stable_value(
            (
                getattr(axes, "elev", None),
                getattr(axes, "azim", None),
                getattr(axes, "roll", None),
            )
        ),
    }
    record["before"] = before
    backend_bases = sys.modules.get("matplotlib.backend_bases")
    left = getattr(getattr(backend_bases, "MouseButton", None), "LEFT", 1)

    try:
        if is_3d or engine == "xy":
            toolbar = getattr(getattr(canvas, "manager", None), "toolbar", None)
            if engine == "xy" and not is_3d:
                pan = getattr(toolbar, "pan", None)
                if not callable(pan):
                    raise RuntimeError("XY navigation requires NavigationToolbar2.pan")
                pan()
            for event_name, xy, raw_buttons, widget_buttons in (
                ("button_press_event", start, None, 0),
                ("motion_notify_event", end, {left}, 1),
                ("button_release_event", end, None, 0),
            ):
                event = dispatch_canvas_event(
                    figure,
                    event_name,
                    axes=axes,
                    context=f"navigation: {event_name}",
                    widget_transport=engine == "xy",
                    xy=xy,
                    button=left,
                    buttons=raw_buttons,
                    widget_button=0,
                    widget_buttons=widget_buttons,
                )
                record["events"].append(event)
                if event["failure"] is not None:
                    raise RuntimeError(
                        f"{event_name} failed: {event['failure']['exception_type']}: "
                        f"{event['failure']['message']}"
                    )
            if engine == "xy" and not is_3d:
                pan()
        else:
            start_pan = getattr(axes, "start_pan", None)
            drag_pan = getattr(axes, "drag_pan", None)
            end_pan = getattr(axes, "end_pan", None)
            if not all(callable(value) for value in (start_pan, drag_pan, end_pan)):
                raise RuntimeError("reference axes does not implement pan")
            start_pan(*start, left)
            drag_pan(left, None, *end)
            end_pan()
            draw_idle = getattr(canvas, "draw_idle", None)
            if callable(draw_idle):
                draw_idle()

        after = {
            "limits": _axes_limits(figure),
            "view": _stable_value(
                (
                    getattr(axes, "elev", None),
                    getattr(axes, "azim", None),
                    getattr(axes, "roll", None),
                )
            ),
        }
        record["after"] = after
        record["state_changed"] = before != after
        record["toolbar_message"] = str(getattr(toolbar, "message", "")) if engine == "xy" else ""
        if before == after:
            raise RuntimeError("navigation gesture did not change limits or 3-D view")
    except BaseException as exc:
        record["failure"] = _exception_record("navigation", exc)
    return record


def drive_coordinate_reporting(figure: object, *, engine: str) -> list[dict[str, Any]]:
    """Exercise axes coordinate formatting and XY's live toolbar message."""

    records: list[dict[str, Any]] = []
    canvas = getattr(figure, "canvas", None)
    draw = getattr(canvas, "draw", None)
    if callable(draw):
        draw()
    for axes_index, axes in enumerate(list(getattr(figure, "axes", []))):
        formatter = getattr(axes, "format_coord", None)
        if not callable(formatter):
            continue
        center = _axes_center(figure, axes=axes)
        record: dict[str, Any] = {
            "axes_index": axes_index,
            "display_xy": _stable_value(center),
            "formatted": None,
            "toolbar_message": None,
            "event": None,
            "failure": None,
        }
        records.append(record)
        try:
            xdata, ydata = axes.transData.inverted().transform(center)
            formatted = str(formatter(float(xdata), float(ydata)))
            record["data_xy"] = _stable_value((xdata, ydata))
            record["formatted"] = formatted
            if not formatted.strip():
                raise RuntimeError("format_coord returned an empty message")
            event = dispatch_canvas_event(
                figure,
                "motion_notify_event",
                axes=axes,
                context=f"coordinate reporting: axes {axes_index}",
                widget_transport=engine == "xy",
                xy=center,
            )
            record["event"] = event
            if event["failure"] is not None:
                raise RuntimeError(
                    f"motion event failed: {event['failure']['exception_type']}: "
                    f"{event['failure']['message']}"
                )
            if engine == "xy":
                toolbar = getattr(getattr(canvas, "manager", None), "toolbar", None)
                message = str(getattr(toolbar, "message", ""))
                record["toolbar_message"] = message
                if not message.strip():
                    raise RuntimeError("XY toolbar did not report pointer coordinates")
        except BaseException as exc:
            record["failure"] = _exception_record(
                f"coordinate reporting: axes {axes_index}",
                exc,
            )
    return records


def drive_cursor_variants(figure: object, *, engine: str) -> dict[str, Any]:
    """Hover every Axes and require the source to request multiple cursors."""

    canvas = getattr(figure, "canvas", None)
    original = getattr(canvas, "set_cursor", None)
    record: dict[str, Any] = {
        "events": [],
        "requests": [],
        "distinct_requests": 0,
        "browser_cursor": None,
        "failure": None,
    }
    if not callable(original):
        record["failure"] = _exception_record(
            "cursor variants",
            RuntimeError("figure canvas does not implement set_cursor"),
        )
        return record
    requests: list[str] = []

    def set_cursor(cursor: object) -> None:
        requests.append(str(getattr(cursor, "name", cursor)))
        original(cursor)

    try:
        canvas.set_cursor = set_cursor
        for axes_index, axes in enumerate(list(getattr(figure, "axes", []))):
            event = dispatch_canvas_event(
                figure,
                "motion_notify_event",
                axes=axes,
                context=f"cursor variants: axes {axes_index}",
                widget_transport=engine == "xy",
                xy=_axes_center(figure, axes=axes),
            )
            record["events"].append(event)
            if event["failure"] is not None:
                raise RuntimeError(
                    f"axes {axes_index} motion failed: "
                    f"{event['failure']['exception_type']}: "
                    f"{event['failure']['message']}"
                )
        distinct = sorted(set(requests))
        record["requests"] = requests
        record["distinct_requests"] = len(distinct)
        record["browser_cursor"] = getattr(canvas, "_cursor_name", None)
        if len(distinct) < 2:
            raise RuntimeError(
                "cursor example did not request at least two distinct cursors "
                f"while hovering {len(getattr(figure, 'axes', []))} axes"
            )
    except BaseException as exc:
        record["failure"] = _exception_record("cursor variants", exc)
    finally:
        canvas.set_cursor = original
    return record


def _artist_drag_center(artist: object, canvas: object) -> tuple[float, float]:
    get_renderer = getattr(canvas, "get_renderer", None)
    renderer = get_renderer() if callable(get_renderer) else None
    get_bbox_patch = getattr(artist, "get_bbox_patch", None)
    bbox_patch = get_bbox_patch() if callable(get_bbox_patch) else None
    if bbox_patch is not None:
        bbox = bbox_patch.get_window_extent(renderer)
    elif type(artist).__name__ == "Annotation":
        # Annotation.get_window_extent() unions the text with its arrow.  The
        # center of that union can be nowhere near the pickable text.
        update_positions = getattr(artist, "update_positions", None)
        if callable(update_positions):
            update_positions(renderer)
        layout, _info, _descent = artist._get_layout(renderer)
        x, y = artist.get_unitless_position()
        x, y = artist.get_transform().transform((x, y))
        bbox = layout.translated(x, y)
    else:
        get_window_extent = getattr(artist, "get_window_extent", None)
        if not callable(get_window_extent):
            raise RuntimeError("draggable artist has no window extent")
        bbox = get_window_extent(renderer)
    return (
        float(bbox.x0 + bbox.x1) / 2.0,
        float(bbox.y0 + bbox.y1) / 2.0,
    )


def drive_draggable_artists(figure: object, *, engine: str) -> list[dict[str, Any]]:
    """Move every live Matplotlib draggable through press/move/release events."""

    canvas = getattr(figure, "canvas", None)
    findobj = getattr(figure, "findobj", None)
    all_artists = list(findobj()) if callable(findobj) else []
    artists = [artist for artist in all_artists if getattr(artist, "_draggable", None) is not None]
    if not artists:
        return []
    draw = getattr(canvas, "draw", None)
    if callable(draw):
        draw()
    records: list[dict[str, Any]] = []
    backend_bases = sys.modules.get("matplotlib.backend_bases")
    left = getattr(getattr(backend_bases, "MouseButton", None), "LEFT", 1)
    for artist in artists:
        if callable(draw):
            # One draggable can define another annotation's coordinate
            # transform. Refresh those dependent extents before each gesture.
            draw()
        record: dict[str, Any] = {
            "type": f"{type(artist).__module__}.{type(artist).__qualname__}",
            "events": [],
            "state_changed": False,
            "failure": None,
        }
        records.append(record)
        try:
            start = _artist_drag_center(artist, canvas)
            end = (start[0] + 23.0, start[1] + 17.0)
            record["center_before"] = [start[0], start[1]]
            before = figure_state_sha256(figure)
            record["state_before_sha256"] = before
            for event_name, xy, raw_buttons, widget_buttons in (
                ("button_press_event", start, None, 0),
                ("motion_notify_event", end, {left}, 1),
                ("button_release_event", end, None, 0),
            ):
                event = dispatch_canvas_event(
                    figure,
                    event_name,
                    axes=getattr(artist, "axes", None),
                    context=f"draggable {type(artist).__name__}: {event_name}",
                    widget_transport=engine == "xy",
                    xy=xy,
                    button=left,
                    buttons=raw_buttons,
                    widget_button=0,
                    widget_buttons=widget_buttons,
                )
                record["events"].append(event)
                if event["failure"] is not None:
                    raise RuntimeError(
                        f"{event_name} failed: {event['failure']['exception_type']}: "
                        f"{event['failure']['message']}"
                    )
            if callable(draw):
                draw()
            center_after = _artist_drag_center(artist, canvas)
            after = figure_state_sha256(figure)
            geometry_changed = not (
                math.isclose(start[0], center_after[0], abs_tol=1e-6)
                and math.isclose(start[1], center_after[1], abs_tol=1e-6)
            )
            record["center_after"] = [center_after[0], center_after[1]]
            record["geometry_changed"] = geometry_changed
            record["state_after_sha256"] = after
            record["state_changed"] = before != after or geometry_changed
            if not record["state_changed"]:
                raise RuntimeError("drag gesture did not change visible artist state")
        except BaseException as exc:
            record["failure"] = _exception_record(
                f"draggable {type(artist).__name__}",
                exc,
            )
    return records


def _walk_namespace(namespace: Mapping[str, object] | None) -> list[object]:
    if namespace is None:
        return []
    queue: deque[tuple[object, int]] = deque((value, 0) for value in namespace.values())
    seen: set[int] = set()
    result: list[object] = []
    while queue and len(result) < MAX_NAMESPACE_OBJECTS:
        value, depth = queue.popleft()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
        if depth >= 2:
            continue
        if isinstance(value, Mapping):
            queue.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            queue.extend((item, depth + 1) for item in value)
        elif type(value).__module__ == "__main__":
            with suppress(TypeError, AttributeError):
                queue.extend((item, depth + 1) for item in vars(value).values())
    return result


def discover_behavior_objects(
    namespace: Mapping[str, object] | None,
    *,
    tracked_animations: Iterable[object] = (),
    tracked_timers: Iterable[object] = (),
) -> tuple[list[object], list[object], list[object]]:
    """Find live animations, timers, and Matplotlib widgets without importing them."""

    values = [
        *tracked_animations,
        *tracked_timers,
        *_walk_namespace(namespace),
    ]
    animation_module = sys.modules.get("matplotlib.animation")
    backend_module = sys.modules.get("matplotlib.backend_bases")
    widgets_module = sys.modules.get("matplotlib.widgets")
    animation_type = getattr(animation_module, "Animation", ())
    timer_type = getattr(backend_module, "TimerBase", ())
    widget_type = getattr(widgets_module, "Widget", ())
    groups: list[list[object]] = [[], [], []]
    seen: list[set[int]] = [set(), set(), set()]
    for value in values:
        for index, expected_type in enumerate((animation_type, timer_type, widget_type)):
            if not expected_type:
                continue
            try:
                matches = isinstance(value, expected_type)
            except TypeError:
                matches = False
            if matches and id(value) not in seen[index]:
                seen[index].add(id(value))
                groups[index].append(value)
    return groups[0], groups[1], groups[2]


def _frame_sequence(animation: object) -> tuple[list[object], bool, int]:
    new_frame_seq = getattr(animation, "new_frame_seq", None)
    if not callable(new_frame_seq):
        raise RuntimeError("animation does not implement new_frame_seq")
    hint = getattr(animation, "_save_count", None)
    if isinstance(hint, int) and hint > 0:
        limit = min(hint, MAX_ANIMATION_FRAMES)
    else:
        limit = DEFAULT_UNBOUNDED_FRAMES
    sequence = iter(new_frame_seq())
    frames: list[object] = []
    finite = False
    for _index in range(limit + 1):
        try:
            frames.append(next(sequence))
        except StopIteration:
            finite = True
            break
    if len(frames) > limit:
        frames.pop()
        finite = False
    if not frames:
        raise RuntimeError("animation produced no frames")
    return frames, finite, limit


def drive_animation(
    animation: object,
    *,
    capture_phase: Callable[[object, str, int], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Draw an animation's initial, middle, and final-or-bounded-final updates."""

    record: dict[str, Any] = {
        "type": f"{type(animation).__module__}.{type(animation).__qualname__}",
        "finite": None,
        "sampled_frame_count": 0,
        "frame_limit": 0,
        "phases": [],
        "failure": None,
    }
    figure = getattr(animation, "_fig", None)
    try:
        frames, finite, limit = _frame_sequence(animation)
        record["finite"] = finite
        record["sampled_frame_count"] = len(frames)
        record["frame_limit"] = limit
        init_draw = getattr(animation, "_init_draw", None)
        if callable(init_draw):
            init_draw()
        chosen = (
            ("initial", 0),
            ("middle", len(frames) // 2),
            ("final" if finite else "bounded_final", len(frames) - 1),
        )
        draw_next_frame = getattr(animation, "_draw_next_frame", None)
        if not callable(draw_next_frame):
            raise RuntimeError("animation does not implement _draw_next_frame")
        draw_frame = getattr(animation, "_draw_frame", None)
        if not callable(draw_frame):
            raise RuntimeError("animation does not implement _draw_frame")
        roles_by_index: dict[int, list[str]] = {}
        for role, index in chosen:
            roles_by_index.setdefault(index, []).append(role)
        for index, frame in enumerate(frames):
            roles = roles_by_index.get(index, [])
            if roles:
                draw_next_frame(frame, blit=False)
                for role in roles:
                    phase = {
                        "role": role,
                        "frame_index": index,
                        "frame": _stable_value(frame),
                        "state_sha256": (
                            figure_state_sha256(figure) if figure is not None else None
                        ),
                    }
                    if capture_phase is not None and figure is not None:
                        phase["capture"] = dict(capture_phase(figure, role, index))
                    record["phases"].append(phase)
            else:
                # Stateful update functions (rain, strip charts, random walks)
                # must observe every preceding frame even though only three
                # representative frames are rendered and retained.
                draw_frame(frame)
    except BaseException as exc:
        record["failure"] = _exception_record("animation frame driver", exc)
    return record


def drive_timer(timer: object) -> dict[str, Any]:
    """Execute one deterministic timer turn with a probe callback."""

    callbacks = getattr(timer, "callbacks", [])
    try:
        source_callbacks = len(callbacks)
    except TypeError:
        source_callbacks = 0
    record: dict[str, Any] = {
        "type": f"{type(timer).__module__}.{type(timer).__qualname__}",
        "attempted": True,
        "source_callbacks": source_callbacks,
        "attempted_callbacks": 0,
        "delivered_callbacks": 0,
        "probe_delivered": False,
        "failure": None,
    }
    probe_calls: list[bool] = []

    def probe() -> bool:
        probe_calls.append(True)
        return True

    add_callback = getattr(timer, "add_callback", None)
    remove_callback = getattr(timer, "remove_callback", None)
    on_timer = getattr(timer, "_on_timer", None)
    try:
        if not callable(add_callback) or not callable(on_timer):
            raise RuntimeError("timer does not implement callback dispatch")
        add_callback(probe)
        record["attempted_callbacks"] = source_callbacks + 1
        on_timer()
        record["probe_call_count"] = len(probe_calls)
        record["probe_delivered"] = bool(probe_calls)
        if record["probe_delivered"]:
            record["delivered_callbacks"] = source_callbacks + 1
    except BaseException as exc:
        record["failure"] = _exception_record("timer callback driver", exc)
    finally:
        if callable(remove_callback):
            try:
                remove_callback(probe)
            except BaseException as exc:
                if record["failure"] is None:
                    record["failure"] = _exception_record(
                        "timer probe disconnect",
                        exc,
                    )
    return record


def _widget_observer_count(widget: object) -> int:
    observers = getattr(widget, "_observers", None)
    callbacks = getattr(observers, "callbacks", {})
    try:
        return sum(len(group) for group in callbacks.values())
    except (AttributeError, TypeError):
        return 0


def _set_widget_value(widget: object) -> str:
    name = type(widget).__name__
    if name == "Slider":
        low = float(widget.valmin)
        high = float(widget.valmax)
        widget.set_val(low + (high - low) * 0.61803398875)
        return "set_val"
    if name == "RangeSlider":
        low = float(widget.valmin)
        high = float(widget.valmax)
        span = high - low
        widget.set_val((low + span * 0.25, low + span * 0.75))
        return "set_val"
    if name == "CheckButtons":
        statuses = list(widget.get_status())
        if statuses:
            widget.set_active(0)
        return "set_active"
    if name == "RadioButtons":
        labels = list(getattr(widget, "labels", []))
        if labels:
            current = getattr(widget, "value_selected", None)
            values = list(getattr(widget, "_values", range(len(labels))))
            try:
                current_index = values.index(current)
            except ValueError:
                current_index = -1
            widget.set_active((current_index + 1) % len(labels))
        return "set_active"
    if name == "TextBox":
        original = str(getattr(widget, "text", ""))
        value = "np.sin(t)" if "t" in original else original + " xy-gallery"
        widget.set_val(value)
        return "submit_valid_value"
    set_active = getattr(widget, "set_active", None)
    get_active = getattr(widget, "get_active", None)
    if callable(set_active) and callable(get_active):
        original = bool(get_active())
        set_active(not original)
        set_active(original)
        return "toggle_active"
    return "canvas_events"


def _widget_probe_connector(widget: object) -> Callable[[Callable[..., None]], object] | None:
    name = type(widget).__name__
    method_name = {
        "Button": "on_clicked",
        "CheckButtons": "on_clicked",
        "RadioButtons": "on_clicked",
        "RangeSlider": "on_changed",
        "Slider": "on_changed",
        "TextBox": "on_submit",
    }.get(name)
    connector = getattr(widget, method_name, None) if method_name is not None else None
    return connector if callable(connector) else None


def _reconnect_selector_if_needed(widget: object) -> bool:
    axes = getattr(widget, "ax", None)
    canvas = getattr(getattr(axes, "figure", None), "canvas", None)
    registry = getattr(canvas, "callbacks", None)
    callback_groups = getattr(registry, "callbacks", {})
    connection_ids = set(getattr(widget, "_cids", ()))
    connected_ids = {
        callback_id for callbacks in callback_groups.values() for callback_id in callbacks
    }
    if connection_ids & connected_ids:
        return False
    connect_default_events = getattr(widget, "connect_default_events", None)
    if not callable(connect_default_events):
        raise RuntimeError("disconnected selector cannot reconnect its default events")
    connect_default_events()
    return True


def _widget_gesture(
    widget: object,
    *,
    engine: str,
) -> tuple[str, list[dict[str, Any]]]:
    axes = getattr(widget, "ax", None)
    figure = getattr(axes, "figure", None)
    if axes is None or figure is None:
        return "no_canvas", []
    bbox = axes.bbox
    left = getattr(
        getattr(sys.modules.get("matplotlib.backend_bases"), "MouseButton", None),
        "LEFT",
        1,
    )

    def point(x_fraction: float, y_fraction: float) -> tuple[float, float]:
        return (
            float(bbox.x0) + float(bbox.width) * x_fraction,
            float(bbox.y0) + float(bbox.height) * y_fraction,
        )

    name = type(widget).__name__
    if name == "PolygonSelector":
        vertices = (
            point(0.28, 0.28),
            point(0.72, 0.28),
            point(0.72, 0.72),
            point(0.28, 0.28),
        )
        specifications = [
            specification
            for vertex in vertices
            for specification in (
                ("motion_notify_event", vertex, None, 0),
                ("button_press_event", vertex, None, 0),
                ("button_release_event", vertex, None, 0),
            )
        ]
        operation = "polygon_select"
    elif name.endswith("Selector"):
        start = point(0.28, 0.32)
        middle = point(0.50, 0.52)
        end = point(0.72, 0.68)
        specifications = [
            ("button_press_event", start, None, 0),
            ("motion_notify_event", middle, {left}, 1),
            ("motion_notify_event", end, {left}, 1),
            ("button_release_event", end, None, 0),
        ]
        operation = "drag_select"
    elif name == "Button":
        center = point(0.50, 0.50)
        specifications = [
            ("motion_notify_event", center, None, 0),
            ("button_press_event", center, None, 0),
            ("button_release_event", center, None, 0),
        ]
        operation = "click"
    else:
        center = point(0.50, 0.50)
        specifications = [("motion_notify_event", center, None, 0)]
        operation = "canvas_motion"

    records: list[dict[str, Any]] = []
    for event_name, xy, raw_buttons, widget_buttons in specifications:
        event = dispatch_canvas_event(
            figure,
            event_name,
            axes=axes,
            context=f"widget {name}: {event_name}",
            widget_transport=engine == "xy",
            xy=xy,
            button=left,
            buttons=raw_buttons,
            widget_button=0,
            widget_buttons=widget_buttons,
        )
        records.append(event)
        if event["failure"] is not None:
            raise RuntimeError(
                f"{event_name} failed: {event['failure']['exception_type']}: "
                f"{event['failure']['message']}"
            )
    return operation, records


def drive_widget(widget: object, *, engine: str) -> dict[str, Any]:
    """Operate one widget via its public API and its canvas event path."""

    axes = getattr(widget, "ax", None)
    figure = getattr(axes, "figure", None)
    name = type(widget).__name__
    original_onselect = getattr(widget, "onselect", None)
    selector_calls: list[object] = []
    observer_calls: list[tuple[object, ...]] = []
    observer_id: object | None = None
    record: dict[str, Any] = {
        "type": f"{type(widget).__module__}.{type(widget).__qualname__}",
        "observer_callbacks": _widget_observer_count(widget),
        "operation": None,
        "events": [],
        "observer_probe_calls": 0,
        "selector_callback_calls": 0,
        "reconnected": False,
        "state_changed": False,
        "failure": None,
    }

    def observe(*args: object) -> None:
        observer_calls.append(args)

    def select(*args: object, **kwargs: object) -> object:
        selector_calls.append(_stable_value((args, kwargs)))
        return original_onselect(*args, **kwargs)

    try:
        before = figure_state_sha256(figure) if figure is not None else None
        record["state_before_sha256"] = before
        connector = _widget_probe_connector(widget)
        if connector is not None:
            observer_id = connector(observe)
        is_selector = name.endswith("Selector")
        if is_selector and callable(original_onselect):
            widget.onselect = select
        if is_selector:
            record["reconnected"] = _reconnect_selector_if_needed(widget)
            clear = getattr(widget, "clear", None)
            if callable(clear):
                clear()
        if not is_selector and name != "Button":
            record["operation"] = _set_widget_value(widget)
        if figure is not None:
            gesture, events = _widget_gesture(widget, engine=engine)
            record["events"] = events
            if record["operation"] in (None, "canvas_events"):
                record["operation"] = gesture
        record["observer_probe_calls"] = len(observer_calls)
        record["selector_callback_calls"] = len(selector_calls)
        after = figure_state_sha256(figure) if figure is not None else None
        record["state_after_sha256"] = after
        record["state_changed"] = before != after
        if connector is not None and not observer_calls:
            raise RuntimeError("widget operation did not deliver its observer callback")
        if is_selector and callable(original_onselect) and not selector_calls:
            raise RuntimeError("selector gesture did not deliver its onselect callback")
    except BaseException as exc:
        record["failure"] = _exception_record(f"widget {type(widget).__name__}", exc)
    finally:
        if name.endswith("Selector") and callable(original_onselect):
            widget.onselect = original_onselect
        disconnect = getattr(widget, "disconnect", None)
        if observer_id is not None and callable(disconnect):
            with suppress(BaseException):
                disconnect(observer_id)
    return record


def _summarize_writer_frames(writer_frames: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for raw in writer_frames:
        frames = list(raw.get("frames", []))
        if not frames:
            continue
        indexes = (0, len(frames) // 2, len(frames) - 1)
        roles = ("initial", "middle", "final")
        phase_captures = raw.get("phase_captures", {})
        phases: list[dict[str, Any]] = []
        for role, index in zip(roles, indexes, strict=True):
            frame = frames[index]
            phase = {
                "role": role,
                "frame_index": frame.get("frame_index"),
                "state_sha256": frame.get("state_sha256"),
            }
            if role in phase_captures:
                phase["capture"] = phase_captures[role]
            if "capture_failure" in frame:
                phase["capture_failure"] = frame["capture_failure"]
            phases.append(phase)
        summaries.append(
            {
                "type": raw.get("type"),
                "frame_count": int(raw.get("frame_count", len(frames))),
                "phases": phases,
            }
        )
    return summaries


def _summarize_pyplot_animations(
    pyplot_calls: Mapping[str, object] | None,
) -> list[dict[str, Any]]:
    """Summarize frame evidence from pyplot-driven ``pause`` animations."""

    if not isinstance(pyplot_calls, Mapping):
        return []
    raw_pause = pyplot_calls.get("pause")
    if not isinstance(raw_pause, Mapping):
        return []
    raw_states = raw_pause.get("states")
    if not isinstance(raw_states, list) or not raw_states:
        return []
    states = [state for state in raw_states if isinstance(state, Mapping)]
    if not states:
        return []
    raw_phase_captures = raw_pause.get("phase_captures")
    phase_captures = raw_phase_captures if isinstance(raw_phase_captures, Mapping) else {}
    indexes = (0, len(states) // 2, len(states) - 1)
    roles = ("initial", "middle", "final")
    phases: list[dict[str, Any]] = []
    for role, index in zip(roles, indexes, strict=True):
        state = states[index]
        figure_states = state.get("figures", [])
        encoded = json.dumps(
            _stable_value(figure_states),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        phase: dict[str, Any] = {
            "role": role,
            "frame_index": state.get("call_index", index),
            "state_sha256": hashlib.sha256(encoded).hexdigest(),
        }
        captures = phase_captures.get(role)
        if isinstance(captures, list):
            phase["captures"] = captures
        phases.append(phase)
    return [
        {
            "type": "matplotlib.pyplot.pause",
            "frame_count": int(raw_pause.get("count", len(states))),
            "sampled_frame_count": len(states),
            "phases": phases,
        }
    ]


def drive_behavior(
    *,
    engine: str,
    requirements: Iterable[str],
    figures: Iterable[object],
    namespace: Mapping[str, object] | None,
    tracked_animations: Iterable[object] = (),
    tracked_timers: Iterable[object] = (),
    writer_frames: Iterable[dict[str, Any]] = (),
    pyplot_calls: Mapping[str, object] | None = None,
    capture_animation_phase: (Callable[[object, str, int], Mapping[str, Any]] | None) = None,
    preserve_figures: bool = False,
) -> dict[str, Any]:
    """Run every required behavior probe and return JSON-safe evidence."""

    required = sorted(set(requirements) & GATED_BEHAVIORS)
    result: dict[str, Any] = {
        "required": required,
        "status": "not_required" if not required else "running",
        "errors": [],
        "canvases": [],
        "events": [],
        "axes_callbacks": [],
        "coordinate_reports": [],
        "cursor_variants": [],
        "draggables": [],
        "gallery_adapters": [],
        "navigation": [],
        "widgets": [],
        "animations": [],
        "writer_animations": [],
        "pyplot_animations": [],
        "timers": [],
        "pyplot_calls": dict(pyplot_calls or {}),
        "browser_transport": {
            "required": bool(
                engine == "xy" and set(required) & {"coordinates", "interactive", "navigation"}
            ),
            "attempted": 0,
            "delivered": 0,
        },
    }
    if not required:
        return result

    figure_list = list(figures)
    animations, timers, widgets = discover_behavior_objects(
        namespace,
        tracked_animations=tracked_animations,
        tracked_timers=tracked_timers,
    )
    errors: list[str] = result["errors"]

    if "interactive" in required:
        if not figure_list:
            errors.append("interactive behavior requires at least one live figure")
        for figure_index, figure in enumerate(figure_list):
            for adapter in install_matplotlib_311_gallery_adapters(figure):
                result["gallery_adapters"].append(
                    {
                        "figure_index": figure_index,
                        **adapter,
                    }
                )
        for index, figure in enumerate(figure_list):
            canvas = getattr(figure, "canvas", None)
            canvas_type = (
                f"{type(canvas).__module__}.{type(canvas).__qualname__}"
                if canvas is not None
                else None
            )
            result["canvases"].append(
                {
                    "figure_index": index,
                    "canvas_type": canvas_type,
                    "callback_registry_type": (
                        f"{type(getattr(canvas, 'callbacks', None)).__module__}."
                        f"{type(getattr(canvas, 'callbacks', None)).__qualname__}"
                    ),
                }
            )
            if engine == "xy" and canvas_type != "xy.backends.backend_xy.FigureCanvasXY":
                errors.append(
                    f"xy interactive figure {index} did not use FigureCanvasXY: {canvas_type}"
                )
            for event_name in REQUIRED_CANVAS_EVENTS:
                if event_name == "close_event":
                    continue
                widget_transport = bool(engine == "xy" and event_name in WIDGET_TRANSPORT_EVENTS)
                event = dispatch_canvas_event(
                    figure,
                    event_name,
                    context=f"figure {index}: {event_name}",
                    widget_transport=widget_transport,
                )
                result["events"].append(event)
                if widget_transport:
                    result["browser_transport"]["attempted"] += 1
                    if event["failure"] is None and event["probe_delivered"]:
                        result["browser_transport"]["delivered"] += 1
                if event["failure"] is not None:
                    errors.append(
                        f"{event['context']} failed: {event['failure']['exception_type']}: "
                        f"{event['failure']['message']}"
                    )
                elif not event["probe_delivered"]:
                    errors.append(f"{event['context']} did not deliver its probe callback")

        for widget in widgets:
            widget_record = drive_widget(widget, engine=engine)
            result["widgets"].append(widget_record)
            if widget_record["failure"] is not None:
                errors.append(
                    f"{widget_record['type']} failed: "
                    f"{widget_record['failure']['exception_type']}: "
                    f"{widget_record['failure']['message']}"
                )
        for figure_index, figure in enumerate(figure_list):
            for callback_record in drive_axes_callbacks(figure):
                callback_record["figure_index"] = figure_index
                result["axes_callbacks"].append(callback_record)
                if callback_record["failure"] is not None:
                    errors.append(
                        f"figure {figure_index} axes {callback_record['axes_index']} "
                        f"{callback_record['signal']} failed: "
                        f"{callback_record['failure']['exception_type']}: "
                        f"{callback_record['failure']['message']}"
                    )
            for draggable_record in drive_draggable_artists(figure, engine=engine):
                draggable_record["figure_index"] = figure_index
                result["draggables"].append(draggable_record)
                if draggable_record["failure"] is not None:
                    errors.append(
                        f"figure {figure_index} {draggable_record['type']} failed: "
                        f"{draggable_record['failure']['exception_type']}: "
                        f"{draggable_record['failure']['message']}"
                    )

    if "coordinates" in required:
        if not figure_list:
            errors.append("coordinate behavior requires at least one live figure")
        for figure_index, figure in enumerate(figure_list):
            records = drive_coordinate_reporting(figure, engine=engine)
            if not records:
                errors.append(f"figure {figure_index} has no coordinate formatter")
            for coordinate_record in records:
                coordinate_record["figure_index"] = figure_index
                result["coordinate_reports"].append(coordinate_record)
                if coordinate_record["failure"] is not None:
                    errors.append(
                        f"figure {figure_index} axes {coordinate_record['axes_index']} "
                        f"coordinate reporting failed: "
                        f"{coordinate_record['failure']['exception_type']}: "
                        f"{coordinate_record['failure']['message']}"
                    )

    if "cursor" in required:
        if not figure_list:
            errors.append("cursor behavior requires at least one live figure")
        for figure_index, figure in enumerate(figure_list):
            cursor_record = drive_cursor_variants(figure, engine=engine)
            cursor_record["figure_index"] = figure_index
            result["cursor_variants"].append(cursor_record)
            if cursor_record["failure"] is not None:
                errors.append(
                    f"figure {figure_index} cursor behavior failed: "
                    f"{cursor_record['failure']['exception_type']}: "
                    f"{cursor_record['failure']['message']}"
                )

    if "navigation" in required:
        if not figure_list:
            errors.append("navigation behavior requires at least one live figure")
        for figure_index, figure in enumerate(figure_list):
            navigation_record = drive_navigation(figure, engine=engine)
            navigation_record["figure_index"] = figure_index
            result["navigation"].append(navigation_record)
            if navigation_record["failure"] is not None:
                errors.append(
                    f"figure {figure_index} navigation failed: "
                    f"{navigation_record['failure']['exception_type']}: "
                    f"{navigation_record['failure']['message']}"
                )

    if "animation" in required:
        for animation in animations:
            animation_record = drive_animation(
                animation,
                capture_phase=capture_animation_phase,
            )
            result["animations"].append(animation_record)
            if animation_record["failure"] is not None:
                errors.append(
                    f"{animation_record['type']} failed: "
                    f"{animation_record['failure']['exception_type']}: "
                    f"{animation_record['failure']['message']}"
                )
        result["writer_animations"] = _summarize_writer_frames(writer_frames)
        result["pyplot_animations"] = _summarize_pyplot_animations(pyplot_calls)
        if capture_animation_phase is not None:
            for animation_record in result["animations"]:
                if any("capture" not in phase for phase in animation_record["phases"]):
                    errors.append(
                        f"{animation_record['type']} is missing a representative frame capture"
                    )
            for writer_record in result["writer_animations"]:
                if any("capture" not in phase for phase in writer_record["phases"]):
                    errors.append(
                        f"{writer_record['type']} is missing a representative writer capture"
                    )
            for pyplot_record in result["pyplot_animations"]:
                if any(not phase.get("captures") for phase in pyplot_record["phases"]):
                    errors.append(
                        f"{pyplot_record['type']} is missing a representative frame capture"
                    )
        if (
            not result["animations"]
            and not result["writer_animations"]
            and not result["pyplot_animations"]
        ):
            errors.append(
                "animation behavior required but no live animation, writer frames, "
                "or pyplot pause frames found"
            )

    animation_timer_ids = {
        id(getattr(animation, "event_source", None))
        for animation in animations
        if getattr(animation, "event_source", None) is not None
    }
    timer_by_id = {id(timer): timer for timer in timers}
    for animation in animations:
        event_source = getattr(animation, "event_source", None)
        if event_source is not None:
            timer_by_id[id(event_source)] = event_source
    for timer in timer_by_id.values():
        timer_record = drive_timer(timer)
        result["timers"].append(timer_record)
        if timer_record["failure"] is not None:
            errors.append(
                f"{timer_record['type']} failed: "
                f"{timer_record['failure']['exception_type']}: "
                f"{timer_record['failure']['message']}"
            )
        elif not timer_record["probe_delivered"]:
            errors.append(f"{timer_record['type']} did not deliver its timer probe")
    if animations and not animation_timer_ids:
        errors.append("live animation did not expose a timer event source")
    if animation_timer_ids and not result["timers"]:
        errors.append("animation timer callback behavior was not exercised")

    if "interactive" in required:
        if engine == "xy" and result["browser_transport"]["delivered"] == 0:
            errors.append("xy interactive behavior did not traverse the live widget transport")
        for index, figure in enumerate(figure_list):
            # A multiprocessing gallery child must remain alive after its
            # checkpoint so the parent can finish sending pipe data. Deliver
            # the genuine CloseEvent through the registry there; all ordinary
            # live-browser cases still exercise the destructive widget close.
            widget_transport = bool(engine == "xy" and not preserve_figures)
            event = dispatch_canvas_event(
                figure,
                "close_event",
                context=f"figure {index}: close_event",
                widget_transport=widget_transport,
            )
            result["events"].append(event)
            if widget_transport:
                result["browser_transport"]["attempted"] += 1
                if event["failure"] is None and event["probe_delivered"]:
                    result["browser_transport"]["delivered"] += 1
            if event["failure"] is not None:
                errors.append(
                    f"{event['context']} failed: {event['failure']['exception_type']}: "
                    f"{event['failure']['message']}"
                )
            elif not event["probe_delivered"]:
                errors.append(f"{event['context']} did not deliver its probe callback")

    result["status"] = "failed" if errors else "passed"
    return result


def behavior_gate(
    result: Mapping[str, Any],
    requirements: Iterable[str],
) -> tuple[bool, list[str]]:
    """Evaluate the hard behavior acceptance gate for one engine result."""

    required = sorted(set(requirements) & GATED_BEHAVIORS)
    if not required:
        return True, []
    if result.get("status") != "passed":
        return False, [f"execution status is {result.get('status')}"]
    behavior = result.get("behavior")
    if not isinstance(behavior, Mapping):
        return False, ["required behavior result is missing"]
    reasons: list[str] = []
    if behavior.get("status") != "passed":
        reasons.extend(str(error) for error in behavior.get("errors", []))
        if not reasons:
            reasons.append(f"behavior status is {behavior.get('status')}")
    recorded = sorted(set(behavior.get("required", [])))
    if recorded != required:
        reasons.append(f"behavior requirements {recorded} do not match manifest {required}")
    return not reasons, reasons
