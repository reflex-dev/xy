"""Kernel-connected browser host for :class:`FigureCanvasXY`.

The widget is intentionally separate from :mod:`xy.widget`: Matplotlib compat
figures carry genuine Matplotlib events and Artists, while ``xy.FigureWidget``
continues to host XY's dependency-free native figure model.
"""

from __future__ import annotations

import math
import weakref
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anywidget
import traitlets

try:
    from matplotlib.backend_bases import (
        CloseEvent,
        KeyEvent,
        LocationEvent,
        MouseButton,
        MouseEvent,
        ResizeEvent,
    )
except ImportError as exc:  # pragma: no cover - optional dependency boundary
    raise ImportError(
        "xy's Matplotlib widget requires the optional Matplotlib integration; "
        'install it with `pip install "xy[matplotlib]"`'
    ) from exc

if TYPE_CHECKING:
    from .backend_xy import FigureCanvasXY
    from .display_list import DisplayList

_ESM = Path(__file__).with_name("backend_xy_widget.js")
_BUTTONS = {
    0: MouseButton.LEFT,
    1: MouseButton.MIDDLE,
    2: MouseButton.RIGHT,
    3: MouseButton.BACK,
    4: MouseButton.FORWARD,
}
_BUTTON_MASKS = (
    (MouseButton.LEFT, 1),
    (MouseButton.RIGHT, 2),
    (MouseButton.MIDDLE, 4),
    (MouseButton.BACK, 8),
    (MouseButton.FORWARD, 16),
)
_LOCATION_EVENTS = frozenset({"figure_enter_event", "figure_leave_event"})
_MOUSE_EVENTS = frozenset(
    {
        "button_press_event",
        "button_release_event",
        "motion_notify_event",
        "scroll_event",
    }
)
_KEY_EVENTS = frozenset({"key_press_event", "key_release_event"})
_MODIFIERS = frozenset({"alt", "ctrl", "shift", "super"})
_TOOLBAR_ACTIONS = frozenset({"home", "back", "forward", "pan", "zoom"})

__all__ = ["FigureCanvasXYWidget", "widget_esm"]


def widget_esm() -> str:
    """Return the bundled widget ES module for packaging and browser probes."""
    return _ESM.read_text(encoding="utf-8")


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == value else None


def _modifiers(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        modifier for modifier in value if isinstance(modifier, str) and modifier in _MODIFIERS
    )


def _process(event: Any) -> None:
    """Dispatch through Matplotlib's runtime event API (missing in its stubs)."""
    event._process()


class FigureCanvasXYWidget(anywidget.AnyWidget):
    """Live anywidget view backed by a real :class:`FigureCanvasXY`.

    Browser input is converted to Matplotlib's event classes and dispatched by
    their standard ``_process`` path, so ``mpl_connect`` callbacks, picking,
    widgets, and Matplotlib's own axes-enter/leave machinery see the same event
    objects as they do with a GUI backend.
    """

    _esm = _ESM

    svg = traitlets.Unicode().tag(sync=True)
    width = traitlets.Float(min=1.0).tag(sync=True)
    height = traitlets.Float(min=1.0).tag(sync=True)
    generation = traitlets.Int(min=0).tag(sync=True)
    timer_interval = traitlets.Int(min=0).tag(sync=True)
    toolbar_enabled = traitlets.Bool().tag(sync=True)
    toolbar_mode = traitlets.Unicode().tag(sync=True)
    toolbar_message = traitlets.Unicode().tag(sync=True)
    toolbar_can_back = traitlets.Bool().tag(sync=True)
    toolbar_can_forward = traitlets.Bool().tag(sync=True)
    cursor = traitlets.Unicode().tag(sync=True)

    def __init__(self, canvas: FigureCanvasXY, **kwargs: Any) -> None:
        self._canvas_ref = weakref.ref(canvas)
        self._closed = False
        self._refreshing = False
        self._last_mouse_xy = (0.0, 0.0)
        if canvas.renderer is None:
            canvas.draw()
        renderer = canvas.renderer
        assert renderer is not None
        display_list = renderer.display_list
        state = {
            "svg": display_list.to_svg(),
            "width": max(1.0, float(display_list.width)),
            "height": max(1.0, float(display_list.height)),
            "generation": max(0, int(canvas._draw_generation)),
            "timer_interval": canvas._timer_pump_interval(),
            **canvas._browser_ui_state(),
            **kwargs,
        }
        super().__init__(
            **state,
        )
        self.on_msg(self._on_custom_msg)

    @property
    def canvas(self) -> FigureCanvasXY | None:
        """The live canvas, or ``None`` after it has been collected."""
        return self._canvas_ref()

    def refresh(self, display_list: DisplayList | None = None) -> None:
        """Push one freshly drawn display list into every browser view."""
        if self._refreshing:
            return
        canvas = self._canvas_ref()
        if canvas is None:
            return
        self._refreshing = True
        try:
            if display_list is None:
                if canvas.renderer is None:
                    canvas.draw()
                renderer = canvas.renderer
                assert renderer is not None
                display_list = renderer.display_list
            generation = max(self.generation + 1, int(canvas._draw_generation))
            with self.hold_sync():
                self.svg = display_list.to_svg()
                self.width = max(1.0, float(display_list.width))
                self.height = max(1.0, float(display_list.height))
                self.generation = generation
        finally:
            self._refreshing = False

    def sync_timer_interval(self) -> None:
        """Start or stop the browser event-loop heartbeat for canvas timers."""
        canvas = self._canvas_ref()
        if canvas is not None:
            self.timer_interval = canvas._timer_pump_interval()

    def sync_browser_ui(self, state: Mapping[str, Any] | None = None) -> None:
        """Push toolbar, status, history, and cursor state to browser views."""
        canvas = self._canvas_ref()
        if canvas is None:
            return
        if state is None:
            state = canvas._browser_ui_state()
        with self.hold_sync():
            self.toolbar_enabled = bool(state["toolbar_enabled"])
            self.toolbar_mode = str(state["toolbar_mode"])
            self.toolbar_message = str(state["toolbar_message"])
            self.toolbar_can_back = bool(state["toolbar_can_back"])
            self.toolbar_can_forward = bool(state["toolbar_can_forward"])
            self.cursor = str(state["cursor"])

    def close(self) -> None:
        """Close the comm after delivering Matplotlib's close event once."""
        self._dispatch_close(destroy_manager=False)
        super().close()

    def _location(self, content: Mapping[str, Any]) -> tuple[float, float] | None:
        x = _finite_number(content.get("x"))
        y = _finite_number(content.get("y"))
        if x is None or y is None:
            return None
        self._last_mouse_xy = x, y
        return x, y

    def _dispatch_mouse(self, name: str, content: Mapping[str, Any]) -> None:
        canvas = self._canvas_ref()
        location = self._location(content)
        if canvas is None or location is None:
            return
        x, y = location
        event_x: Any = x
        event_y: Any = y
        modifiers = _modifiers(content.get("modifiers"))
        if name == "motion_notify_event":
            mask = _integer(content.get("buttons")) or 0
            buttons = {button for button, bit in _BUTTON_MASKS if mask >= 0 and mask & bit}
            _process(
                MouseEvent(
                    name,
                    canvas,
                    event_x,
                    event_y,
                    buttons=buttons,
                    modifiers=modifiers,
                )
            )
            return
        if name == "scroll_event":
            step = _finite_number(content.get("step"))
            if step is None:
                return
            _process(
                MouseEvent(
                    name,
                    canvas,
                    event_x,
                    event_y,
                    step=step,
                    modifiers=modifiers,
                )
            )
            return
        raw_button = _integer(content.get("button"))
        button = _BUTTONS.get(raw_button)
        if button is None:
            return
        _process(
            MouseEvent(
                name,
                canvas,
                event_x,
                event_y,
                button=button,
                dblclick=bool(content.get("dblclick", False)),
                modifiers=modifiers,
            )
        )

    def _dispatch_location(self, name: str, content: Mapping[str, Any]) -> None:
        canvas = self._canvas_ref()
        location = self._location(content)
        if canvas is None or location is None:
            return
        event_x: Any = location[0]
        event_y: Any = location[1]
        _process(
            LocationEvent(
                name,
                canvas,
                event_x,
                event_y,
                modifiers=_modifiers(content.get("modifiers")),
            )
        )

    def _dispatch_key(self, name: str, content: Mapping[str, Any]) -> None:
        canvas = self._canvas_ref()
        key = content.get("key")
        if canvas is None or not isinstance(key, str):
            return
        event_x: Any = self._last_mouse_xy[0]
        event_y: Any = self._last_mouse_xy[1]
        _process(KeyEvent(name, canvas, key, event_x, event_y))

    def _dispatch_resize(self, content: Mapping[str, Any]) -> None:
        canvas = self._canvas_ref()
        width = _finite_number(content.get("width"))
        height = _finite_number(content.get("height"))
        if canvas is None or width is None or height is None or width <= 0 or height <= 0:
            return
        dpi = float(canvas.figure.dpi)
        canvas.figure.set_size_inches(width / dpi, height / dpi, forward=False)
        _process(ResizeEvent("resize_event", canvas))
        canvas.draw_idle()
        # Directly constructed widgets are not cached on the canvas and thus
        # do not receive the canvas draw hook.
        if getattr(canvas, "_widget", None) is not self and canvas.renderer is not None:
            self.refresh(canvas.renderer.display_list)

    def _dispatch_close(self, *, destroy_manager: bool = True) -> None:
        canvas = self._canvas_ref()
        if canvas is None or self._closed:
            return
        self._closed = True
        _process(CloseEvent("close_event", canvas))
        manager = getattr(canvas, "manager", None)
        number = getattr(manager, "num", None)
        if destroy_manager and number is not None:
            from matplotlib._pylab_helpers import Gcf  # noqa: PLC0415

            if Gcf.has_fignum(number):
                Gcf.destroy(number)

    def _dispatch_toolbar(self, content: Mapping[str, Any]) -> None:
        canvas = self._canvas_ref()
        action = content.get("action")
        if canvas is None or not isinstance(action, str) or action not in _TOOLBAR_ACTIONS:
            return
        toolbar = getattr(canvas, "toolbar", None)
        callback = getattr(toolbar, action, None)
        if not callable(callback):
            return
        callback()
        canvas._sync_browser_ui()

    def _on_custom_msg(self, widget: Any, content: Any, msg_buffers: Any) -> None:
        """Validate one browser message before entering Matplotlib callbacks."""
        if not isinstance(content, Mapping):
            return
        if content.get("type") == "event_loop":
            canvas = self._canvas_ref()
            if canvas is not None:
                canvas.flush_events()
                self.sync_timer_interval()
            return
        if content.get("type") == "toolbar":
            self._dispatch_toolbar(content)
            return
        if content.get("type") != "event":
            return
        name = content.get("name")
        if not isinstance(name, str):
            return
        if name in _MOUSE_EVENTS:
            self._dispatch_mouse(name, content)
        elif name in _LOCATION_EVENTS:
            self._dispatch_location(name, content)
        elif name in _KEY_EVENTS:
            self._dispatch_key(name, content)
        elif name == "resize_event":
            self._dispatch_resize(content)
        elif name == "close_event":
            self._dispatch_close()
