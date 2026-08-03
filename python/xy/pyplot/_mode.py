"""Runtime selection for the native and Matplotlib-compatible pyplot frontends.

This module deliberately contains no static Matplotlib imports.  Selecting
``compat`` is cheap; Matplotlib and the XY backend are imported only when the
first routed pyplot call needs them.
"""

from __future__ import annotations

import functools
import importlib
import importlib.metadata
import os
import re
import sys
import threading
from collections.abc import Callable
from types import ModuleType
from typing import Any, Literal, cast

PyplotMode = Literal["auto", "native", "compat"]

_ENVIRONMENT_VARIABLE = "XY_PYPLOT_MODE"
_COMPAT_BACKEND = "module://xy.backends.backend_xy"
_SUPPORTED_MATPLOTLIB = (3, 11)
_VALID_MODES = frozenset({"auto", "native", "compat"})
_COMPAT_SUBMODULE_OBJECTS: dict[str, tuple[str, str | None]] = {
    # pyplot does not re-export these consistently, but real gallery scripts
    # construct them through the pyplot alias.
    "AutoMinorLocator": ("matplotlib.ticker", "AutoMinorLocator"),
    "dates": ("matplotlib.dates", None),
    "StrMethodFormatter": ("matplotlib.ticker", "StrMethodFormatter"),
    "ListedColormap": ("matplotlib.colors", "ListedColormap"),
    "LinearSegmentedColormap": ("matplotlib.colors", "LinearSegmentedColormap"),
    # Kept explicit even where 3.11 currently re-exports them so the proxy
    # remains stable across patch releases.
    "Normalize": ("matplotlib.colors", "Normalize"),
    "Polygon": ("matplotlib.patches", "Polygon"),
    # Existing xy.pyplot artist classes that Matplotlib keeps in submodules.
    "AxesImage": ("matplotlib.image", "AxesImage"),
    "BarContainer": ("matplotlib.container", "BarContainer"),
    "ContourSet": ("matplotlib.contour", "ContourSet"),
    "ErrorbarContainer": ("matplotlib.container", "ErrorbarContainer"),
    "Legend": ("matplotlib.legend", "Legend"),
    "PathCollection": ("matplotlib.collections", "PathCollection"),
    "PieContainer": ("matplotlib.container", "PieContainer"),
    "PolyCollection": ("matplotlib.collections", "PolyCollection"),
    "StemContainer": ("matplotlib.container", "StemContainer"),
    "StepPatch": ("matplotlib.patches", "StepPatch"),
    "StreamplotSet": ("matplotlib.streamplot", "StreamplotSet"),
    "Table": ("matplotlib.table", "Table"),
}
_lock = threading.RLock()
_compat_pyplot: Any = None
_compat_previous_mplbackend: str | None = None
_compat_backend_hint_active = False
_auto_compat_unavailable = False
# Resolving distribution metadata performs filesystem work.  Keep the result
# stable across routed pyplot calls and refresh it only at the explicit
# ``set_mode("auto")`` boundary.
_auto_compat_supported: bool | None = None


class _AutoCompatFallback(RuntimeError):
    """Signal that lazy ``auto`` initialization should retry in native mode."""


class _CompatBackendStateError(RuntimeError):
    """Signal that live Matplotlib state cannot safely be repaired in place."""


def _parse_mode(value: object, *, source: str) -> PyplotMode:
    normalized = str(value).strip().lower()
    if normalized not in _VALID_MODES:
        choices = ", ".join(sorted(_VALID_MODES))
        raise ValueError(f"{source} must be one of {choices}; got {value!r}")
    return cast(PyplotMode, normalized)


_requested_mode: PyplotMode = _parse_mode(
    os.environ.get(_ENVIRONMENT_VARIABLE, "auto"),
    source=_ENVIRONMENT_VARIABLE,
)


def _activate_compat_backend_hint() -> None:
    """Select XY for a later Matplotlib import without importing Matplotlib.

    Toolkit helpers can create a Matplotlib figure before the first routed
    ``xy.pyplot`` function is called.  The environment hint ensures those
    figures already use ``FigureCanvasXY`` while preserving lightweight import
    and lazy Matplotlib initialization.
    """

    global _compat_backend_hint_active, _compat_previous_mplbackend
    if _compat_backend_hint_active:
        return
    _compat_previous_mplbackend = os.environ.get("MPLBACKEND")
    os.environ["MPLBACKEND"] = _COMPAT_BACKEND
    _compat_backend_hint_active = True


def _deactivate_compat_backend_hint() -> None:
    """Restore the pre-compat backend environment setting when possible."""

    global _compat_backend_hint_active, _compat_previous_mplbackend
    if not _compat_backend_hint_active:
        return
    if os.environ.get("MPLBACKEND") == _COMPAT_BACKEND:
        if _compat_previous_mplbackend is None:
            os.environ.pop("MPLBACKEND", None)
        else:
            os.environ["MPLBACKEND"] = _compat_previous_mplbackend
    _compat_previous_mplbackend = None
    _compat_backend_hint_active = False


def get_mode() -> PyplotMode:
    """Return the configured pyplot mode.

    The value is the explicit setting (including ``"auto"``), not the
    currently resolved implementation.
    """

    with _lock:
        return _requested_mode


def _effective_mode() -> Literal["native", "compat"]:
    with _lock:
        return "compat" if _mode_resolves_compat(_requested_mode) else "native"


def _native_figures_are_open() -> bool:
    # Importing a sibling does not pull in Matplotlib, and _state is already
    # loaded by xy.pyplot before these helpers become public.
    state = importlib.import_module("xy.pyplot._state")
    return bool(getattr(state, "_figures", {}))


def _matplotlib_figures_are_open() -> bool:
    pyplot = sys.modules.get("matplotlib.pyplot")
    if pyplot is None:
        return False
    get_fignums = getattr(pyplot, "get_fignums", None)
    return bool(get_fignums and get_fignums())


def _is_compat_backend(value: object) -> bool:
    return str(value).strip().lower() == _COMPAT_BACKEND.lower()


def _is_xy_canvas_class(value: object) -> bool:
    return (
        getattr(value, "__module__", None) == "xy.backends.backend_xy"
        and getattr(value, "__name__", None) == "FigureCanvasXY"
    )


def _ensure_compat_backend(matplotlib: Any, pyplot: Any) -> None:
    """Repair backend drift or fail before a non-XY figure can be reused."""
    pylab_helpers = importlib.import_module("matplotlib._pylab_helpers")
    figures = [manager.canvas.figure for manager in pylab_helpers.Gcf.get_all_fig_managers()]
    incompatible = [figure for figure in figures if not _is_xy_canvas_class(type(figure.canvas))]
    if incompatible:
        canvases = ", ".join(sorted({type(figure.canvas).__name__ for figure in incompatible}))
        raise _CompatBackendStateError(
            "xy.pyplot compat mode found open Matplotlib figures on non-XY canvases "
            f'({canvases}); call matplotlib.pyplot.close("all") and retry'
        )

    backend = matplotlib.get_backend()
    backend_module = getattr(pyplot, "_backend_mod", None)
    backend_canvas = getattr(backend_module, "FigureCanvas", None)
    if _is_compat_backend(backend) and (
        backend_canvas is None or _is_xy_canvas_class(backend_canvas)
    ):
        return

    try:
        pyplot.switch_backend(_COMPAT_BACKEND)
    except Exception as exc:
        raise _CompatBackendStateError(
            f"xy.pyplot compat mode could not reactivate {_COMPAT_BACKEND!r}"
        ) from exc

    backend = matplotlib.get_backend()
    backend_module = getattr(pyplot, "_backend_mod", None)
    backend_canvas = getattr(backend_module, "FigureCanvas", None)
    if not _is_compat_backend(backend) or not _is_xy_canvas_class(backend_canvas):
        raise _CompatBackendStateError(
            "xy.pyplot compat mode reactivation did not install FigureCanvasXY"
        )


def _install_matplotlib_311_gallery_compatibility() -> None:
    """Repair a documented 3.11 gallery/API inconsistency.

    ``event_handling/resample.py`` calls
    ``FillBetweenPolyCollection.set_data(..., step="pre")`` even though
    Matplotlib 3.11.0's method omits that keyword while retaining ``_step`` as
    collection state.  Accepting the gallery's call is required for the
    example's interactive zoom callback to work unchanged.
    """

    collections = importlib.import_module("matplotlib.collections")
    collection_type = collections.FillBetweenPolyCollection
    original = collection_type.set_data
    if getattr(original, "__xy_matplotlib_311_gallery_compat__", False):
        return

    @functools.wraps(original)
    def set_data(
        instance: Any,
        t: Any,
        f1: Any,
        f2: Any,
        *,
        where: Any = None,
        step: str | None = None,
    ) -> Any:
        if step is not None:
            instance._step = step
        return original(instance, t, f1, f2, where=where)

    set_data.__xy_matplotlib_311_gallery_compat__ = True  # ty: ignore[unresolved-attribute]
    collection_type.set_data = set_data  # ty: ignore[invalid-assignment]


def _figures_are_open() -> bool:
    return _native_figures_are_open() or _matplotlib_figures_are_open()


def _matplotlib_series(version: str) -> tuple[int, int] | None:
    match = re.match(r"\s*(\d+)\.(\d+)", version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _mode_resolves_compat(mode: PyplotMode) -> bool:
    global _auto_compat_supported
    if mode == "auto" and _auto_compat_unavailable:
        return False
    if mode == "compat":
        return True
    if mode == "native":
        return False
    if _auto_compat_supported is None:
        try:
            version = importlib.metadata.version("matplotlib")
        except importlib.metadata.PackageNotFoundError:
            _auto_compat_supported = False
        else:
            _auto_compat_supported = _matplotlib_series(version) == _SUPPORTED_MATPLOTLIB
    return _auto_compat_supported


if _mode_resolves_compat(_requested_mode):
    # Distribution metadata is sufficient to resolve ``auto`` without
    # importing Matplotlib.  The backend hint also covers toolkit helpers that
    # create the first Figure before a routed pyplot function is called.
    _activate_compat_backend_hint()


def _unsupported_matplotlib_message(version: str | None) -> str:
    installed = "not installed" if version is None else f"version {version} is installed"
    return (
        "xy.pyplot compat mode requires Matplotlib >=3.11,<3.12 "
        f'({installed}). Install it with `pip install "xy[matplotlib]"`.'
    )


def _validate_installed_matplotlib() -> str:
    try:
        version = importlib.metadata.version("matplotlib")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(_unsupported_matplotlib_message(None)) from exc
    if _matplotlib_series(version) != _SUPPORTED_MATPLOTLIB:
        raise RuntimeError(_unsupported_matplotlib_message(version))
    return version


def set_mode(mode: PyplotMode | str) -> None:
    """Configure the pyplot implementation before creating any figures.

    ``native`` is xy's dependency-free implementation.  ``compat`` delegates
    Matplotlib's public semantics to the XY Matplotlib backend and requires the
    ``xy[matplotlib]`` extra.  ``auto`` selects ``compat`` when the supported
    Matplotlib series is installed and otherwise selects ``native``.

    Switching modes while either frontend has an open figure is rejected.
    Close all figures first (``plt.close("all")``). Calling
    ``set_mode("auto")`` again refreshes optional Matplotlib discovery, for
    example after installing or uninstalling the extra in a live process.
    """

    requested = _parse_mode(mode, source="mode")
    with _lock:
        global _auto_compat_supported, _auto_compat_unavailable, _requested_mode
        if requested == _requested_mode and requested != "auto":
            return

        previous_auto_supported = _auto_compat_supported
        previous_auto_unavailable = _auto_compat_unavailable
        previous_effective = "compat" if _mode_resolves_compat(_requested_mode) else "native"

        # A same-mode call is the explicit refresh boundary for optional
        # dependency changes.  Ordinary pyplot dispatch remains filesystem-free.
        if requested == "auto":
            _auto_compat_supported = None
            _auto_compat_unavailable = False
        new_effective = "compat" if _mode_resolves_compat(requested) else "native"
        mode_changed = requested != _requested_mode
        effective_changed = new_effective != previous_effective
        if (mode_changed or effective_changed) and _figures_are_open():
            _auto_compat_supported = previous_auto_supported
            _auto_compat_unavailable = previous_auto_unavailable
            raise RuntimeError(
                "cannot switch xy.pyplot mode while figures are open; "
                'call close("all") before set_mode()'
            )
        if requested == "compat":
            # Distribution metadata is enough to fail early without importing
            # Matplotlib or paying its startup cost.
            _validate_installed_matplotlib()
        if new_effective == "compat":
            _activate_compat_backend_hint()
        elif previous_effective == "compat":
            _deactivate_compat_backend_hint()
        _requested_mode = requested


def _load_compat_pyplot() -> Any:
    global _auto_compat_supported, _auto_compat_unavailable, _compat_pyplot
    with _lock:
        if _compat_pyplot is not None:
            # Production cache entries are the actual pyplot module.  Validate
            # them on every routed call because Matplotlib exposes mutable
            # process-global backend state through use(), switch_backend(), and
            # rcParams.  SimpleNamespace test doubles deliberately stay cheap.
            if not isinstance(_compat_pyplot, ModuleType):
                return _compat_pyplot
            cached_module = sys.modules.get("matplotlib.pyplot")
            matplotlib_module = sys.modules.get("matplotlib")
            if cached_module is _compat_pyplot and isinstance(matplotlib_module, ModuleType):
                _ensure_compat_backend(matplotlib_module, _compat_pyplot)
                return _compat_pyplot
            _compat_pyplot = None

        try:
            expected_version = _validate_installed_matplotlib()
        except RuntimeError as exc:
            if _requested_mode != "auto":
                raise
            # Metadata can change after auto was resolved but before the first
            # routed compat call. Fall back transactionally instead of leaking
            # an explicit-compat installation error from auto mode.
            _auto_compat_supported = False
            _auto_compat_unavailable = True
            _deactivate_compat_backend_hint()
            raise _AutoCompatFallback(
                "supported Matplotlib metadata disappeared or changed; auto mode selected native"
            ) from exc
        try:
            matplotlib = importlib.import_module("matplotlib")
            runtime_version = str(getattr(matplotlib, "__version__", expected_version))
            if _matplotlib_series(runtime_version) != _SUPPORTED_MATPLOTLIB:
                raise RuntimeError(_unsupported_matplotlib_message(runtime_version))
            _install_matplotlib_311_gallery_compatibility()
            loaded_pyplot = sys.modules.get("matplotlib.pyplot")
            if loaded_pyplot is None:
                matplotlib.use(_COMPAT_BACKEND, force=True)
                pyplot = importlib.import_module("matplotlib.pyplot")
            else:
                pyplot = loaded_pyplot
            _ensure_compat_backend(matplotlib, pyplot)
        except _CompatBackendStateError:
            raise
        except Exception as exc:
            if _requested_mode == "auto":
                _auto_compat_unavailable = True
                _deactivate_compat_backend_hint()
                raise _AutoCompatFallback(
                    "supported Matplotlib metadata was present, but Matplotlib "
                    "could not be initialized; auto mode selected native"
                ) from exc
            raise RuntimeError(
                f"could not initialize xy.pyplot compat mode with the {_COMPAT_BACKEND!r} backend"
            ) from exc
        _auto_compat_unavailable = False
        _compat_pyplot = pyplot
        return pyplot


def switch_backend(newbackend: str) -> None:
    """Keep Matplotlib compat mode pinned to XY's renderer backend.

    Compat mode cannot honor a request for another renderer without violating
    its no-fallback contract.  Select ``native`` mode after closing all figures
    if an XY-owned Matplotlib canvas is not desired.
    """
    if _effective_mode() != "compat":
        raise RuntimeError("switch_backend() is only available in xy.pyplot compat mode")
    if not _is_compat_backend(newbackend):
        raise RuntimeError(
            "xy.pyplot compat mode pins Matplotlib to "
            f"{_COMPAT_BACKEND!r}; switch_backend({newbackend!r}) would bypass RendererXY"
        )
    _load_compat_pyplot()


def _compat_callable(name: str) -> Callable[..., Any]:
    pyplot = _load_compat_pyplot()
    target = getattr(pyplot, name, None)
    if callable(target):
        return target

    # A handful of xy's stateful helpers map to Matplotlib Axes methods rather
    # than pyplot functions (for example relim(), autoscale_view(), and the
    # Matplotlib 3.11 violin helper).
    axes_target = getattr(pyplot.gca(), name, None)
    if callable(axes_target):
        return axes_target
    raise AttributeError(f"Matplotlib 3.11 has no pyplot or Axes callable named {name!r}")


def _compat_object(name: str) -> Any:
    pyplot = _load_compat_pyplot()
    if hasattr(pyplot, name):
        return getattr(pyplot, name)
    # Upstream assigns these only while backend fallback remains enabled.
    # Selecting an explicit module backend disables that branch, but both
    # names are part of the reviewed default pyplot 3.11 public inventory.
    if name == "available_backends":
        backends = importlib.import_module("matplotlib.backends")
        registry = backends.backend_registry
        backend_filter = backends.BackendFilter
        return registry.list_builtin(backend_filter.INTERACTIVE)
    if name == "requested_backend":
        return None
    matplotlib = sys.modules["matplotlib"]
    if hasattr(matplotlib, name):
        return getattr(matplotlib, name)
    location = _COMPAT_SUBMODULE_OBJECTS.get(name)
    if location is not None:
        module_name, attribute = location
        module = importlib.import_module(module_name)
        if attribute is None:
            return module
        if hasattr(module, attribute):
            return getattr(module, attribute)
    raise AttributeError(f"Matplotlib 3.11 has no public object named {name!r}")


def _compat_names() -> set[str]:
    pyplot = _load_compat_pyplot()
    return set(dir(pyplot)) | set(_COMPAT_SUBMODULE_OBJECTS)


__all__ = ["PyplotMode", "get_mode", "set_mode", "switch_backend"]
