"""In-process instrumentation injected into each real gallery script."""

from __future__ import annotations

import atexit
import builtins
import functools
import hashlib
import importlib
import json
import os
import random
import resource
import struct
import sys
import time
import traceback
import warnings
import webbrowser
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from . import HARNESS_VERSION
from .behavior import GATED_BEHAVIORS, drive_behavior, figure_state_sha256
from .extended_drivers import (
    ACTION_DRIVER_FIELDS,
    INPUT_DRIVER_FIELDS,
    SUPPORTED_DRIVER_FIELDS,
    TIMER_DRIVER_FIELDS,
    ScriptedInputDriver,
    drive_extended_actions,
    drive_timer_until_close,
)
from .integrity import aggregate_fallback_state
from .provenance import current_python_interpreter

DETERMINISTIC_SEED = 19680801


def _seed_random_generators() -> dict[str, Any]:
    """Reset process-global generators before any upstream source executes."""

    random.seed(DETERMINISTIC_SEED)
    record = {
        "value": DETERMINISTIC_SEED,
        "python_random": True,
        "numpy_random": False,
    }
    try:
        numpy = importlib.import_module("numpy")
    except ImportError:
        return record
    numpy.random.seed(DETERMINISTIC_SEED)
    record["numpy_random"] = True
    return record


def _safe_call(obj: object, name: str, default: Any, *args: object) -> Any:
    method = getattr(obj, name, None)
    if not callable(method):
        return default
    try:
        return method(*args)
    except BaseException:
        return default


def _float_pair(value: object) -> list[float]:
    try:
        values = list(value)  # type: ignore[arg-type]
        return [float(values[0]), float(values[1])]
    except (IndexError, TypeError, ValueError):
        return []


def _bounds(value: object) -> list[float]:
    raw = getattr(value, "bounds", value)
    try:
        values = list(raw)  # type: ignore[arg-type]
        if len(values) != 4:
            return []
        return [float(item) for item in values]
    except (TypeError, ValueError):
        return []


def _text_value(value: object) -> str:
    text = _safe_call(value, "get_text", None)
    if text is None:
        text = getattr(value, "text", getattr(value, "_text", ""))
    return str(text)


def _legend_text(ax: object) -> list[str]:
    legend = _safe_call(ax, "get_legend", None)
    if legend is None:
        return []
    texts = _safe_call(legend, "get_texts", None)
    if texts is not None:
        try:
            return [_text_value(text) for text in texts]
        except TypeError:
            pass
    handles_labels = _safe_call(ax, "get_legend_handles_labels", ([], []))
    try:
        return [str(label) for label in handles_labels[1]]
    except (IndexError, TypeError):
        return []


def _artist_families(ax: object) -> dict[str, int]:
    families: Counter[str] = Counter()
    groups = {
        "line": "lines",
        "collection": "collections",
        "image": "images",
        "patch": "patches",
        "text": "texts",
        "container": "containers",
        "table": "tables",
    }
    for family, attribute in groups.items():
        try:
            items = list(getattr(ax, attribute, []))
        except TypeError:
            continue
        if items:
            families[family] += len(items)
    return dict(sorted(families.items()))


def _axis_record(ax: object) -> dict[str, Any]:
    xlim = _float_pair(_safe_call(ax, "get_xlim", []))
    ylim = _float_pair(_safe_call(ax, "get_ylim", []))
    label = _safe_call(ax, "get_label", "")
    projection = getattr(ax, "name", getattr(ax, "_projection", "rectilinear"))
    xscale = _safe_call(ax, "get_xscale", getattr(ax, "_xscale", "linear"))
    yscale = _safe_call(ax, "get_yscale", getattr(ax, "_yscale", "linear"))
    record = {
        "bounds": _bounds(_safe_call(ax, "get_position", [])),
        "projection": str(projection),
        "xscale": str(xscale),
        "yscale": str(yscale),
        "xlim": xlim,
        "ylim": ylim,
        "x_inverted": bool(_safe_call(ax, "xaxis_inverted", len(xlim) == 2 and xlim[0] > xlim[1])),
        "y_inverted": bool(_safe_call(ax, "yaxis_inverted", len(ylim) == 2 and ylim[0] > ylim[1])),
        "x_autoscale": bool(_safe_call(ax, "get_autoscalex_on", True)),
        "y_autoscale": bool(_safe_call(ax, "get_autoscaley_on", True)),
        "title": str(_safe_call(ax, "get_title", "")),
        "xlabel": str(_safe_call(ax, "get_xlabel", "")),
        "ylabel": str(_safe_call(ax, "get_ylabel", "")),
        "legend_text": _legend_text(ax),
        "is_colorbar": bool(
            label == "<colorbar>"
            or getattr(ax, "_colorbar", None) is not None
            or getattr(ax, "_colorbar_info", None) is not None
        ),
        "artist_families": _artist_families(ax),
    }
    if callable(getattr(ax, "get_zlim", None)):
        zlim = _float_pair(_safe_call(ax, "get_zlim", []))
        zscale = _safe_call(ax, "get_zscale", getattr(ax, "_zscale", "linear"))
        record.update(
            {
                "zscale": str(zscale),
                "zlim": zlim,
                "z_inverted": bool(
                    _safe_call(ax, "zaxis_inverted", len(zlim) == 2 and zlim[0] > zlim[1])
                ),
                "z_autoscale": bool(_safe_call(ax, "get_autoscalez_on", True)),
                "zlabel": str(_safe_call(ax, "get_zlabel", "")),
            }
        )
    return record


def _figure_record(figure: object, number: object) -> dict[str, Any]:
    size_inches = _float_pair(_safe_call(figure, "get_size_inches", []))
    dpi = float(_safe_call(figure, "get_dpi", getattr(figure, "dpi", 100.0)))
    axes = list(getattr(figure, "axes", []))
    figure_texts = list(getattr(figure, "texts", getattr(figure, "_texts", [])))
    return {
        "figure_number": number,
        "size_inches": size_inches,
        "dpi": dpi,
        "pixel_dimensions": (
            [round(size_inches[0] * dpi), round(size_inches[1] * dpi)]
            if len(size_inches) == 2
            else []
        ),
        "axes": [_axis_record(ax) for ax in axes],
        "figure_text": [_text_value(text) for text in figure_texts],
    }


def _qualified_type(value: object | None) -> str | None:
    if value is None:
        return None
    return f"{type(value).__module__}.{type(value).__qualname__}"


def _figure_facecolor(figure: object) -> tuple[list[float], list[int]]:
    value = _safe_call(figure, "get_facecolor", [])
    try:
        channels = [float(channel) for channel in value]  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return [], []
    if len(channels) == 3:
        channels.append(1.0)
    if len(channels) != 4:
        return [], []
    background = [round(max(0.0, min(1.0, channel)) * 255) for channel in channels[:3]]
    return channels, background


def _capture_metadata(figure: object) -> dict[str, Any]:
    canvas = getattr(figure, "canvas", None)
    matplotlib = sys.modules.get("matplotlib")
    backend = _safe_call(matplotlib, "get_backend", None) if matplotlib is not None else None
    fallback_used = getattr(canvas, "fallback_used", None)
    if fallback_used is not True and fallback_used is not False:
        fallback_used = None
    facecolor, background = _figure_facecolor(figure)
    return {
        "backend": str(backend) if backend is not None else None,
        "canvas_type": _qualified_type(canvas),
        "fallback_used": fallback_used,
        "figure_facecolor_rgba": facecolor,
        "background_rgb": background,
    }


def _png_dimensions(path: Path) -> list[int]:
    try:
        header = path.read_bytes()[:24]
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return []
        return list(struct.unpack(">II", header[16:24]))
    except (OSError, struct.error):
        return []


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KiB; macOS and the BSDs report bytes.
    return value if sys.platform == "darwin" else value * 1024


class GalleryRuntime:
    """Capture figures, warnings, exceptions, and resource usage for one case."""

    def __init__(
        self,
        *,
        engine: str,
        output_dir: Path,
        source_path: Path,
        source_sha256: str,
        transformed_sha256: str,
        rewrite_count: int,
        behavior_requirements: tuple[str, ...] = (),
        extended_requirements: dict[str, Any] | None = None,
    ) -> None:
        self.engine = engine
        self.output_dir = output_dir
        self.source_path = source_path
        self.started = time.monotonic()
        self.deterministic_seed = _seed_random_generators()
        self.pyplot: ModuleType | None = None
        self.finished = False
        self.failed = False
        self.show_count = 0
        self.captures: list[dict[str, Any]] = []
        self.capture_errors: list[str] = []
        self.warnings: list[dict[str, Any]] = []
        self.behavior_requirements = behavior_requirements
        self.extended_requirements = extended_requirements or {}
        raw_driver = self.extended_requirements.get("driver", {})
        self._driver_settings = raw_driver if isinstance(raw_driver, Mapping) else {}
        self._configured_driver_fields = set(self._driver_settings)
        self._consumed_driver_fields: set[str] = set()
        self._driver_contract_errors = [
            f"unknown driver field: {field}"
            for field in sorted(self._configured_driver_fields - SUPPORTED_DRIVER_FIELDS)
        ]
        input_driver = ScriptedInputDriver(self._driver_settings)
        self._input_driver = input_driver if input_driver.configured else None
        self._extended_driver_evidence: dict[str, Any] = {}
        self._original_sleep = time.sleep
        self._scaled_sleep_calls = 0
        if "sleep_scale" in self._driver_settings:
            try:
                sleep_scale = float(self._driver_settings["sleep_scale"])
                if sleep_scale < 0:
                    raise ValueError("sleep scale cannot be negative")
            except (TypeError, ValueError) as exc:
                self._driver_contract_errors.append(f"sleep_scale: {exc}")
            else:

                def scaled_sleep(seconds: float) -> None:
                    self._scaled_sleep_calls += 1
                    self._original_sleep(float(seconds) * sleep_scale)

                time.sleep = scaled_sleep
                self._consumed_driver_fields.add("sleep_scale")
                self._extended_driver_evidence["sleep_scale"] = {
                    "status": "passed",
                    "scale": sleep_scale,
                    "call_count": 0,
                }
        self._original_clabel: Any = None
        self._owner_pid = os.getpid()
        self._tracked_animations: list[object] = []
        self._tracked_timers: list[object] = []
        self._pdf_page_capture_count = 0
        self._writer_frames: dict[int, dict[str, Any]] = {}
        self._pyplot_calls: dict[str, Any] = {
            "pause": {"count": 0, "states": []},
            "ginput": {"count": 0},
            "waitforbuttonpress": {"count": 0},
        }
        # Keep strong Figure keys so a closed figure's recycled ``id`` can
        # never overwrite the capture slot of a later, distinct figure.
        self._figure_capture_indexes: dict[object, int] = {}

        # Matplotlib's backend switcher attaches ``__signature__`` to
        # ``pyplot.show``. A plain closure supports that; a bound method does
        # not, so assigning ``self._capture_show`` would break first-figure
        # creation even though the call behavior is otherwise equivalent.
        def capture_show(*args: object, **kwargs: object) -> None:
            self._capture_show(*args, **kwargs)

        self._show_proxy = capture_show
        self.result: dict[str, Any] = {
            "schema_version": 2,
            "harness_version": HARNESS_VERSION,
            "engine": engine,
            "source": str(source_path),
            "source_sha256": source_sha256,
            "transformed_sha256": transformed_sha256,
            "rewrite_count": rewrite_count,
            "ast_rewrite_verified": engine == "matplotlib" or rewrite_count > 0,
            "python_interpreter": current_python_interpreter(),
            "requested_pyplot_mode": "compat" if engine == "xy" else None,
            "behavior_requirements": list(behavior_requirements),
            "extended_requirements": self.extended_requirements or None,
            "deterministic_seed": self.deterministic_seed,
            "owner_pid": self._owner_pid,
            "status": "running",
        }

        self._original_import = builtins.__import__
        self._original_excepthook = sys.excepthook
        self._original_showwarning = warnings.showwarning
        builtins.__import__ = self._import_hook
        builtins.input = lambda *_args, **_kwargs: ""
        webbrowser.open = lambda *_args, **_kwargs: False
        warnings.showwarning = self._showwarning
        sys.excepthook = self._excepthook
        atexit.register(self.finish)
        self._validate_multiprocessing_driver()

    @property
    def target_module(self) -> str:
        return "matplotlib.pyplot" if self.engine == "matplotlib" else "xy.pyplot"

    @property
    def _is_child_process(self) -> bool:
        return os.getpid() != self._owner_pid

    def _capture_path(self, sequence: int) -> Path:
        prefix = f"child-{os.getpid()}-" if self._is_child_process else ""
        return self.output_dir / f"{prefix}capture-{sequence:03d}.png"

    def _result_path(self) -> Path:
        if self._is_child_process:
            return self.output_dir / f"child-result-{os.getpid()}.json"
        return self.output_dir / "result.json"

    def _write_result(self) -> None:
        self.result["current_pid"] = os.getpid()
        self.result["is_child_process"] = self._is_child_process
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._result_path().write_text(
            json.dumps(self.result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _join_extended_children(self) -> None:
        if self._is_child_process:
            return
        if self._driver_settings.get("show_policy") != "native_until_close":
            return
        try:
            multiprocessing = importlib.import_module("multiprocessing")
            children = list(multiprocessing.active_children())
        except BaseException as exc:
            self._extended_driver_evidence["child_join"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            return

        records: list[dict[str, Any]] = []
        deadline = time.monotonic() + min(
            float(self.extended_requirements.get("timeout_seconds", 120)),
            10.0,
        )
        for child in children:
            remaining = max(0.0, deadline - time.monotonic())
            child.join(timeout=remaining)
            records.append(
                {
                    "pid": child.pid,
                    "exitcode": child.exitcode,
                    "alive": child.is_alive(),
                }
            )
        status = "passed" if all(not record["alive"] for record in records) else "failed"
        self._extended_driver_evidence["child_join"] = {
            "status": status,
            "processes": records,
        }
        if status == "passed":
            self._consumed_driver_fields.update(
                TIMER_DRIVER_FIELDS & self._configured_driver_fields
            )

    def _validate_multiprocessing_driver(self) -> None:
        field = "multiprocessing_start_method"
        if field not in self._driver_settings:
            return
        expected = self._driver_settings[field]
        try:
            multiprocessing = importlib.import_module("multiprocessing")
            actual = multiprocessing.get_start_method(allow_none=True)
        except BaseException as exc:
            self._driver_contract_errors.append(
                f"{field}: cannot inspect active start method: {type(exc).__name__}: {exc}"
            )
            return
        passed = isinstance(expected, str) and actual == expected
        self._extended_driver_evidence.setdefault("controls", {})[field] = {
            "status": "passed" if passed else "failed",
            "expected": expected,
            "actual": actual,
        }
        if passed:
            self._consumed_driver_fields.add(field)
        else:
            self._driver_contract_errors.append(
                f"{field}: active method {actual!r} != configured {expected!r}"
            )

    def _drive_declared_actions(
        self,
        namespace: Mapping[str, object] | None,
    ) -> None:
        configured = ACTION_DRIVER_FIELDS & self._configured_driver_fields
        if not configured:
            return
        evidence = drive_extended_actions(
            settings=self._driver_settings,
            figures=self._live_figures(),
            namespace=namespace,
        )
        self._extended_driver_evidence["actions"] = evidence
        drivers = evidence.get("drivers", {})
        if isinstance(drivers, Mapping):
            self._consumed_driver_fields.update(
                field
                for field in configured
                if isinstance(drivers.get(field), Mapping)
                and drivers[field].get("status") == "passed"
            )
        if evidence.get("status") != "passed":
            self._driver_contract_errors.extend(str(error) for error in evidence.get("errors", []))

    def _finalize_driver_contract(self) -> None:
        sleep_evidence = self._extended_driver_evidence.get("sleep_scale")
        if isinstance(sleep_evidence, dict):
            sleep_evidence["call_count"] = self._scaled_sleep_calls
        if time.sleep is not self._original_sleep:
            time.sleep = self._original_sleep

        unconsumed = sorted(self._configured_driver_fields - self._consumed_driver_fields)
        errors = [*self._driver_contract_errors]
        errors.extend(f"unconsumed driver field: {field}" for field in unconsumed)
        contract = {
            "status": "failed" if errors else "passed",
            "configured_fields": sorted(self._configured_driver_fields),
            "consumed_fields": sorted(self._consumed_driver_fields),
            "unconsumed_fields": unconsumed,
            "errors": errors,
        }
        self._extended_driver_evidence["driver_contract"] = contract
        if errors and not self.failed:
            self.failed = True
            self.result.update(
                {
                    "status": "harness_error",
                    "exception_type": "ExtendedDriverContractError",
                    "exception_message": "; ".join(errors),
                }
            )

    def _import_hook(
        self,
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        imported = self._original_import(name, globals, locals, fromlist, level)
        self._patch_matplotlib_hooks()
        module = sys.modules.get(self.target_module)
        package = self.target_module.removesuffix(".pyplot")
        requested_pyplot = name == self.target_module or (
            name == package and fromlist is not None and "pyplot" in fromlist
        )
        if module is not None and requested_pyplot:
            self.pyplot = module
            self._patch_pyplot(module)
            # Matplotlib registers its figure-manager teardown while pyplot is
            # importing. Register our callback afterwards so SystemExit still
            # captures live figures before that teardown runs. Normal source
            # completion also calls ``finish`` from the instrumented footer.
            atexit.unregister(self.finish)
            atexit.register(self.finish)
        return imported

    def _patch_initializer(
        self,
        owner: type[object],
        target: list[object],
    ) -> None:
        original = owner.__dict__.get("__init__")
        if not callable(original) or getattr(original, "__xy_gallery_tracking__", False):
            return

        @functools.wraps(original)
        def tracked(instance: object, *args: object, **kwargs: object) -> None:
            original(instance, *args, **kwargs)
            target.append(instance)

        tracked.__xy_gallery_tracking__ = True  # type: ignore[attr-defined]
        owner.__init__ = tracked  # type: ignore[method-assign]

    def _patch_writer(self, owner: type[object]) -> None:
        original = owner.__dict__.get("grab_frame")
        if not callable(original) or getattr(original, "__xy_gallery_tracking__", False):
            return

        @functools.wraps(original)
        def tracked(instance: object, *args: object, **kwargs: object) -> Any:
            value = original(instance, *args, **kwargs)
            identity = id(instance)
            record = self._writer_frames.setdefault(
                identity,
                {
                    "type": f"{type(instance).__module__}.{type(instance).__qualname__}",
                    "frame_count": 0,
                    "frames": [],
                },
            )
            frame_index = int(record["frame_count"])
            record["frame_count"] = frame_index + 1
            frame = {
                "frame_index": frame_index,
                "state_sha256": figure_state_sha256(getattr(instance, "fig", None)),
            }
            figure = getattr(instance, "fig", None)
            temporary_root = self.output_dir / "_behavior_frames"
            temporary_root.mkdir(parents=True, exist_ok=True)
            temporary_path = temporary_root / f"writer-{identity}-{frame_index:04d}.png"
            try:
                figure.savefig(temporary_path)
                frame["temporary_file"] = str(temporary_path)
                frame["capture_metadata"] = {
                    "figure_number": getattr(figure, "number", None),
                    "dimensions": _png_dimensions(temporary_path),
                    **_capture_metadata(figure),
                    "semantic": _figure_record(
                        figure,
                        getattr(figure, "number", None),
                    ),
                }
            except BaseException as exc:
                frame["capture_failure"] = (
                    f"{type(exc).__name__} while capturing writer frame {frame_index}: {exc}"
                )
            frames = record["frames"]
            if len(frames) < 4096:
                frames.append(frame)
            else:
                frames[-1] = frame
            return value

        tracked.__xy_gallery_tracking__ = True  # type: ignore[attr-defined]
        owner.grab_frame = tracked  # type: ignore[method-assign]

    def _patch_pdf_pages(self, owner: type[object]) -> None:
        original = owner.__dict__.get("savefig")
        if not callable(original) or getattr(original, "__xy_gallery_tracking__", False):
            return

        @functools.wraps(original)
        def tracked(
            instance: object,
            figure: object | None = None,
            **kwargs: object,
        ) -> Any:
            target = figure
            if target is None:
                module = self.pyplot or sys.modules.get(self.target_module)
                target = _safe_call(module, "gcf", None) if module is not None else None
            value = original(instance, figure, **kwargs)
            if target is None:
                self.capture_errors.append("PdfPages.savefig completed without a Figure to capture")
                return value

            page_index = self._pdf_page_capture_count
            candidate = self._capture_path(len(self.captures))
            try:
                capture = self._render_capture(
                    figure=target,
                    number=getattr(target, "number", None),
                    stage=f"pdf-page-{page_index + 1}",
                    candidate=candidate,
                    sequence=len(self.captures),
                )
            except BaseException as exc:
                self.capture_errors.append(
                    f"{type(exc).__name__} while capturing PDF page {page_index + 1}: {exc}"
                )
            else:
                capture["pdf_page_index"] = page_index
                self.captures.append(capture)
                self._pdf_page_capture_count += 1
            return value

        tracked.__xy_gallery_tracking__ = True  # type: ignore[attr-defined]
        owner.savefig = tracked  # type: ignore[method-assign]

    def _patch_figure_show(self, owner: type[object]) -> None:
        """Route ``Figure.show()`` through the same nonblocking gallery hook."""

        original = owner.__dict__.get("show")
        if not callable(original) or getattr(original, "__xy_gallery_tracking__", False):
            return

        @functools.wraps(original)
        def tracked(_instance: object, *_args: object, **_kwargs: object) -> None:
            self._capture_show()

        tracked.__xy_gallery_tracking__ = True  # type: ignore[attr-defined]
        owner.show = tracked  # type: ignore[method-assign]

    def _patch_matplotlib_hooks(self) -> None:
        figure_module = sys.modules.get("matplotlib.figure")
        figure_type = getattr(figure_module, "Figure", None)
        if isinstance(figure_type, type):
            self._patch_figure_show(figure_type)

        animation = sys.modules.get("matplotlib.animation")
        animation_type = getattr(animation, "Animation", None)
        if isinstance(animation_type, type):
            self._patch_initializer(animation_type, self._tracked_animations)
        for writer_name in ("AbstractMovieWriter", "MovieWriter"):
            writer_type = getattr(animation, writer_name, None)
            if isinstance(writer_type, type):
                self._patch_writer(writer_type)

        backend_bases = sys.modules.get("matplotlib.backend_bases")
        timer_type = getattr(backend_bases, "TimerBase", None)
        if isinstance(timer_type, type):
            self._patch_initializer(timer_type, self._tracked_timers)

        backend_pdf = sys.modules.get("matplotlib.backends.backend_pdf")
        pdf_pages_type = getattr(backend_pdf, "PdfPages", None)
        if isinstance(pdf_pages_type, type):
            self._patch_pdf_pages(pdf_pages_type)

    def _record_pyplot_call(self, name: str) -> None:
        record = self._pyplot_calls[name]
        record["count"] += 1
        if name != "pause" or len(record["states"]) >= 128:
            return
        figures = self._live_figures()
        state: dict[str, Any] = {
            "call_index": record["count"] - 1,
            "figures": [figure_state_sha256(figure) for figure in figures],
            "captures": [],
        }
        if "animation" in self.behavior_requirements:
            temporary_root = self.output_dir / "_behavior_frames"
            temporary_root.mkdir(parents=True, exist_ok=True)
            for figure_index, figure in enumerate(figures):
                temporary_path = (
                    temporary_root
                    / f"pause-{record['count'] - 1:04d}-figure-{figure_index:03d}.png"
                )
                try:
                    capture = self._render_capture(
                        figure=figure,
                        number=getattr(figure, "number", None),
                        stage="animation-pause-frame",
                        candidate=temporary_path,
                        sequence=record["count"] - 1,
                    )
                    capture["temporary_file"] = str(temporary_path)
                    state["captures"].append(capture)
                except BaseException as exc:
                    self.capture_errors.append(
                        f"{type(exc).__name__} while capturing pause frame "
                        f"{record['count'] - 1}: {exc}"
                    )
        record["states"].append(state)

    def _patch_pyplot(self, module: ModuleType) -> None:
        module.show = self._show_proxy

        def pause(*_args: object, **_kwargs: object) -> None:
            self._record_pyplot_call("pause")

        def waitforbuttonpress(*_args: object, **_kwargs: object) -> bool:
            self._record_pyplot_call("waitforbuttonpress")
            if self._input_driver is not None:
                return self._input_driver.waitforbuttonpress(*_args, **_kwargs)
            return False

        def ginput(
            n: int = 1,
            *_args: object,
            **_kwargs: object,
        ) -> list[tuple[float, float]]:
            self._record_pyplot_call("ginput")
            if self._input_driver is not None:
                return self._input_driver.ginput(n, *_args, **_kwargs)
            return []

        module.pause = pause
        module.waitforbuttonpress = waitforbuttonpress
        module.ginput = ginput
        if self._input_driver is not None:
            if self._original_clabel is None:
                self._original_clabel = module.clabel

            def clabel(*args: object, **kwargs: object) -> object:
                return self._input_driver.clabel(self._original_clabel, *args, **kwargs)

            module.clabel = clabel

    def _showwarning(
        self,
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: Any = None,
        line: str | None = None,
    ) -> None:
        self.warnings.append(
            {
                "category": category.__name__,
                "message": str(message),
                "filename": filename,
                "line": lineno,
            }
        )
        self._original_showwarning(message, category, filename, lineno, file=file, line=line)

    def _capture_show(self, *_args: object, **_kwargs: object) -> None:
        self.show_count += 1
        if self._driver_settings.get("show_policy") == "native_until_close":
            self._consumed_driver_fields.update(
                TIMER_DRIVER_FIELDS & self._configured_driver_fields
            )
            try:
                evidence = drive_timer_until_close(
                    timers=self._tracked_timers,
                    live_figures=self._live_figures,
                    checkpoint=self.finish,
                    settings=self._driver_settings,
                    timeout_seconds=float(self.extended_requirements.get("timeout_seconds", 120)),
                )
            except BaseException as exc:
                self.failed = True
                self.result.update(
                    {
                        "status": "harness_error",
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                    }
                )
                self._extended_driver_evidence["timer_show"] = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self._write_result()
                raise
            self._extended_driver_evidence["timer_show"] = evidence
            if not self.finished:
                self.finish()
            self._write_result()
            return
        if "animation" not in self.behavior_requirements:
            self.capture_open_figures(stage=f"show-{self.show_count}")

    def _live_figures(self) -> list[object]:
        module = self.pyplot or sys.modules.get(self.target_module)
        if module is None:
            return []
        numbers = list(_safe_call(module, "get_fignums", []))
        current = _safe_call(module, "gcf", None) if numbers else None
        figures: list[object] = []
        for number in numbers:
            try:
                figures.append(module.figure(number))
            except BaseException:
                continue
        current_number = getattr(current, "number", None)
        if current_number in numbers:
            _safe_call(module, "figure", None, current_number)
        return figures

    def capture_open_figures(self, *, stage: str) -> None:
        module = self.pyplot or sys.modules.get(self.target_module)
        if module is None:
            return
        numbers = list(_safe_call(module, "get_fignums", []))
        current = _safe_call(module, "gcf", None) if numbers else None
        for number in numbers:
            try:
                figure = module.figure(number)
                sequence = self._figure_capture_indexes.get(figure, len(self.captures))
                candidate = self._capture_path(sequence)
                capture = self._render_capture(
                    figure=figure,
                    number=number,
                    stage=stage,
                    candidate=candidate,
                    sequence=sequence,
                )
                if figure in self._figure_capture_indexes:
                    self.captures[sequence] = capture
                else:
                    self._figure_capture_indexes[figure] = sequence
                    self.captures.append(capture)
            except BaseException as exc:
                self.capture_errors.append(
                    f"{type(exc).__name__} while capturing figure {number}: {exc}"
                )
        current_number = getattr(current, "number", None)
        if current_number in numbers:
            _safe_call(module, "figure", None, current_number)

    def _render_capture(
        self,
        *,
        figure: object,
        number: object,
        stage: str,
        candidate: Path,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        figure.savefig(candidate)
        data = candidate.read_bytes()
        return {
            "file": candidate.name,
            "sequence": len(self.captures) if sequence is None else sequence,
            "stage": stage,
            "figure_number": number,
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_count": len(data),
            "dimensions": _png_dimensions(candidate),
            **_capture_metadata(figure),
            "semantic": _figure_record(figure, number),
        }

    def _capture_animation_phase(
        self,
        figure: object,
        role: str,
        frame_index: int,
    ) -> dict[str, Any]:
        number = getattr(figure, "number", len(self.captures) + 1)
        candidate = self._capture_path(len(self.captures))
        capture = self._render_capture(
            figure=figure,
            number=number,
            stage=f"animation-{role}",
            candidate=candidate,
            sequence=len(self.captures),
        )
        capture["animation_frame_index"] = frame_index
        self.captures.append(capture)
        return capture

    def _promote_temporary_animation_capture(
        self,
        *,
        metadata: Mapping[str, Any],
        temporary_file: object,
        stage: str,
        frame_index: int,
    ) -> dict[str, Any]:
        source = Path(str(temporary_file))
        candidate = self._capture_path(len(self.captures))
        candidate.write_bytes(source.read_bytes())
        data = candidate.read_bytes()
        capture = {
            "file": candidate.name,
            "sequence": len(self.captures),
            "stage": stage,
            "figure_number": metadata.get("figure_number"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_count": len(data),
            "dimensions": metadata.get("dimensions", _png_dimensions(candidate)),
            "backend": metadata.get("backend"),
            "canvas_type": metadata.get("canvas_type"),
            "fallback_used": metadata.get("fallback_used"),
            "figure_facecolor_rgba": metadata.get("figure_facecolor_rgba"),
            "background_rgb": metadata.get("background_rgb"),
            "semantic": metadata.get("semantic", {}),
            "animation_frame_index": frame_index,
        }
        self.captures.append(capture)
        return capture

    def _promote_animation_captures(self) -> None:
        roles = ("initial", "middle", "final")
        pause = self._pyplot_calls["pause"]
        pause_states = list(pause.get("states", []))
        if pause_states:
            indexes = (0, len(pause_states) // 2, len(pause_states) - 1)
            pause["phase_captures"] = {}
            for role, index in zip(roles, indexes, strict=True):
                state = pause_states[index]
                promoted: list[dict[str, Any]] = []
                for metadata in state.get("captures", []):
                    temporary_file = metadata.get("temporary_file")
                    if not temporary_file:
                        self.capture_errors.append(f"pause frame {index} has no temporary PNG")
                        continue
                    promoted.append(
                        self._promote_temporary_animation_capture(
                            metadata=metadata,
                            temporary_file=temporary_file,
                            stage=f"animation-pause-{role}",
                            frame_index=int(state.get("call_index", index)),
                        )
                    )
                pause["phase_captures"][role] = promoted
            for state in pause_states:
                state.pop("captures", None)

        for writer in self._writer_frames.values():
            frames = list(writer.get("frames", []))
            if not frames:
                continue
            indexes = (0, len(frames) // 2, len(frames) - 1)
            writer["phase_captures"] = {}
            for role, index in zip(roles, indexes, strict=True):
                frame = frames[index]
                temporary_file = frame.get("temporary_file")
                if not temporary_file:
                    message = frame.get(
                        "capture_failure",
                        f"writer frame {index} has no temporary PNG",
                    )
                    self.capture_errors.append(str(message))
                    continue
                metadata = frame.get("capture_metadata", {})
                capture = self._promote_temporary_animation_capture(
                    metadata=metadata,
                    temporary_file=temporary_file,
                    stage=f"animation-writer-{role}",
                    frame_index=int(frame["frame_index"]),
                )
                writer["phase_captures"][role] = capture
        temporary_root = self.output_dir / "_behavior_frames"
        if temporary_root.is_dir():
            for temporary_file in temporary_root.iterdir():
                temporary_file.unlink()
            temporary_root.rmdir()

    def _excepthook(
        self,
        exception_type: type[BaseException],
        exception: BaseException,
        tb: Any,
    ) -> None:
        self.failed = True
        self.result.update(
            {
                "status": "error",
                "exception_type": exception_type.__name__,
                "exception_message": str(exception),
                "traceback": "".join(traceback.format_exception(exception_type, exception, tb)),
            }
        )
        self.finish()
        self._original_excepthook(exception_type, exception, tb)

    def finish(self, namespace: Mapping[str, object] | None = None) -> None:
        if self.finished:
            return
        self.finished = True
        self._join_extended_children()
        self._drive_declared_actions(namespace)
        animation_required = "animation" in self.behavior_requirements
        if not animation_required:
            self.capture_open_figures(stage="final")
        else:
            self._promote_animation_captures()
        figures = self._live_figures()
        if self.failed:
            behavior = {
                "required": sorted(set(self.behavior_requirements) & GATED_BEHAVIORS),
                "status": "skipped_due_execution_failure",
                "errors": ["source execution did not complete"],
            }
        else:
            behavior = drive_behavior(
                engine=self.engine,
                requirements=self.behavior_requirements,
                figures=figures,
                namespace=namespace,
                tracked_animations=self._tracked_animations,
                tracked_timers=self._tracked_timers,
                writer_frames=self._writer_frames.values(),
                pyplot_calls=self._pyplot_calls,
                capture_animation_phase=(
                    self._capture_animation_phase if animation_required else None
                ),
                preserve_figures=bool(
                    self._is_child_process
                    and self._driver_settings.get("show_policy") == "native_until_close"
                ),
            )
        if self._input_driver is not None:
            input_evidence = self._input_driver.evidence()
            remaining = input_evidence.get("remaining", {})
            input_evidence["status"] = (
                "passed"
                if isinstance(remaining, Mapping)
                and all(int(value) == 0 for value in remaining.values())
                else "failed"
            )
            self._extended_driver_evidence["input"] = input_evidence
            if input_evidence["status"] != "passed":
                self.failed = True
                self.result.update(
                    {
                        "status": "harness_error",
                        "exception_type": "IncompleteInputDriver",
                        "exception_message": (
                            "source did not consume the complete deterministic input script"
                        ),
                    }
                )
            else:
                self._consumed_driver_fields.update(
                    INPUT_DRIVER_FIELDS & self._configured_driver_fields
                )
        self._finalize_driver_contract()
        if not self.failed:
            self.result["status"] = "passed"
        resolved_mode = (
            _safe_call(self.pyplot, "get_mode", None) if self.pyplot is not None else None
        )
        self.result.update(
            {
                "duration_seconds": round(time.monotonic() - self.started, 6),
                "peak_rss_bytes": _peak_rss_bytes(),
                "show_count": self.show_count,
                "capture_count": len(self.captures),
                "captures": self.captures,
                "fallback_used": aggregate_fallback_state(self.captures),
                "resolved_pyplot_mode": resolved_mode,
                "capture_errors": self.capture_errors,
                "warnings": self.warnings,
                "behavior": behavior,
                "extended_driver": self._extended_driver_evidence,
            }
        )
        self._write_result()


def activate(
    *,
    engine: str,
    output_dir: str,
    source_path: str,
    source_sha256: str,
    transformed_sha256: str,
    rewrite_count: int,
    behavior_requirements: tuple[str, ...] = (),
    extended_requirements: dict[str, Any] | None = None,
) -> GalleryRuntime:
    """Install instrumentation without importing or selecting a pyplot backend."""

    if engine not in {"matplotlib", "xy"}:
        raise ValueError(f"unsupported gallery engine: {engine}")
    return GalleryRuntime(
        engine=engine,
        output_dir=Path(output_dir),
        source_path=Path(source_path),
        source_sha256=source_sha256,
        transformed_sha256=transformed_sha256,
        rewrite_count=rewrite_count,
        behavior_requirements=behavior_requirements,
        extended_requirements=extended_requirements,
    )
