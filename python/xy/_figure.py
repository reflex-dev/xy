"""The Figure: a data-less spec + column handles (§9).

The spec is tiny JSON — trace kinds, styles, axis config, and *references* into
the column store. Data never rides in the spec: encoded f32 columns travel as
one binary blob beside it (§29: no JSON numbers, no re-encoding, parse-shaped
work is forbidden on the client).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from os import PathLike
from typing import Any, Optional, TypeAlias

import numpy as np

from . import _annotations, _validate, channels, columns, export, interaction, kernels, styles
from . import marks as _marks
from ._annotations import AnnotationsMixin
from ._buffers import WireBuffer, array_byte_view
from ._payload import PayloadMixin
from ._trace import Trace
from .channels import ColorChannel, SizeChannel
from .columns import Column, ColumnStore, ColumnStoreCheckpoint

# Tier/tuning constants live in config.py (shared with interaction/export/
# _payload); several are re-exported here — this module is their historic
# import path and tests import them from `xy._figure` (F401 kept for
# the re-exports; DIRECT_SOFT_CEILING/DEFAULT_PALETTE are also used below).
from .config import (  # noqa: E402, F401
    DECIMATION_THRESHOLD,
    DEFAULT_PALETTE,
    DENSITY_GRID,
    DENSITY_SAMPLE_SEED,
    DENSITY_SAMPLE_TARGET,
    DIRECT_SOFT_CEILING,
    PROTOCOL_VERSION,
    SCATTER_DENSITY_THRESHOLD,
)
from .dom import validate_dom_slots

_FigureCheckpoint: TypeAlias = tuple[ColumnStoreCheckpoint, int, dict[str, list[str]], int]

# "selection not passed" sentinel for state_patch_message: None is meaningful
# there (clear the selection), so absence needs its own marker.
_STATE_UNSET: Any = object()


class Selection:
    """The payload handed to an `on_select` callback. Holds the selected
    row indices per trace and lends convenient access to the underlying data —
    callbacks receive real arrays, never JSON."""

    def __init__(self, figure: "Figure", per_trace: dict[int, np.ndarray]) -> None:
        self._figure = figure
        self.per_trace = per_trace  # {trace_id: np.ndarray[uint32]}

    @property
    def index(self) -> np.ndarray:
        """Concatenated selected indices across all traces (single-trace charts
        are the common case, where this is just that trace's indices)."""
        arrs = list(self.per_trace.values())
        return np.concatenate(arrs) if arrs else np.empty(0, dtype="uint32")

    def __len__(self) -> int:
        return int(sum(len(v) for v in self.per_trace.values()))

    def xy(self, trace_id: int = 0) -> tuple[np.ndarray, np.ndarray]:
        """(x, y) f64 arrays for the selected points of a trace (from canonical)."""
        t = interaction._trace(self._figure, trace_id)
        idx = self.per_trace.get(t.id)
        if idx is None:
            return np.empty(0), np.empty(0)
        return t.x.values[idx], t.y.values[idx]

    def rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return deterministic JSON rows based on canonical indices.

        Traces and their indices are ordered ascending. ``limit`` bounds the
        projection without changing the complete selection held by this object.
        """
        rows, _ = interaction.selection_rows(self._figure, self.per_trace, limit)
        return rows


class Figure(AnnotationsMixin, PayloadMixin):
    """Build with `line()` / `scatter()`, display with `show()` (notebook) or
    `to_html()` (standalone file, no kernel round-trips)."""

    def __init__(
        self,
        *,
        width: "int | str" = 900,
        height: "int | str" = 420,
        title: Optional[str] = None,
        x_label: Optional[str] = None,
        y_label: Optional[str] = None,
        padding: Any = None,
    ) -> None:
        # width/height: pixels, or "100%" to fill the parent container — the
        # client measures the container and re-renders on resize
        # (ResizeObserver), re-requesting decimation/density at the new pixel
        # size (§28). height="100%" needs a parent with a defined height (the
        # usual CSS contract); otherwise the chart falls back to its 120px
        # min-height.
        self.width = self._pixel_dimension(width, "width")
        self.height = self._pixel_dimension(height, "height")
        # padding: override the auto plot margins (top, right, bottom, left) in
        # px — a scalar sets all four. None keeps the label-aware defaults. Zero
        # padding + hidden axes gives an edge-to-edge sparkline for dashboards.
        self.padding = self._padding(padding, "padding")
        self.title = self._optional_text(title, "title")
        self.x_label = self._optional_text(x_label, "x_label")
        self.y_label = self._optional_text(y_label, "y_label")
        self.axis_options: dict[str, dict[str, Any]] = {
            "x": {"label": self.x_label, "side": "bottom"},
            "y": {"label": self.y_label, "side": "left"},
        }
        self.store = ColumnStore()
        self.traces: list[Trace] = []
        self.show_legend = True
        self.legend_options: dict[str, Any] = {}
        # Additional legend boxes (each with its own explicit items + loc),
        # e.g. the pyplot shim's manually added Legend artists. Empty for the
        # ordinary single-legend case.
        self.extra_legends: list[dict[str, Any]] = []
        # None keeps the declarative engine's two-axis baseline convention;
        # pyplot sets an explicit Matplotlib-style spine list.
        self.frame_sides: Optional[list[str]] = None
        self.colorbar_options: Optional[dict[str, Any]] = None
        # Declarative export defaults (xy.export_config): governs the client
        # modebar's format menu + filename and the Python export defaults.
        self.export_options: Optional[dict[str, Any]] = None
        self.show_modebar = True
        self.show_tooltip = True
        self.class_name: Optional[str] = None
        self.class_names: dict[str, str] = {}
        self.style: dict[str, str | int | float] = {}
        self.chrome_styles: dict[str, dict[str, str | int | float]] = {}
        self.tooltip: Optional[dict[str, Any]] = None
        self.interaction: dict[str, Any] = {}
        # Browser-only motion policy. Static/native exporters intentionally
        # ignore this and always render the deterministic final scene.
        self.animation_options: Optional[dict[str, Any]] = None
        self.mark_style: dict[str, dict[str, str | int | float]] = {}
        self.annotations: list[dict[str, Any]] = []
        self._axis_categories: dict[str, list[str]] = {}
        # Declarative marks still call the shared fluent mark bodies with the
        # channel dimensions ("x"/"y").  Chart temporarily points those
        # dimensions at the mark's bound axis ids while it applies each mark,
        # so category registries stay independent for x, x2, y, y2, ... .
        self._active_axis_ids: dict[str, str] = {"x": "x", "y": "y"}
        self._widget: Any = None
        # Kernel-side durable view-state cache (spec/design/view-state.md
        # §5.1): the browser client owns the live state; this mirror is fed
        # by the view/selection events the transports already deliver, so
        # `view_state()` never round-trips. Reads are eventually consistent.
        self._view_state_ranges: Optional[dict[str, list[float]]] = None
        self._view_state_selection: Optional[dict[str, Any]] = None

    # -- axis config --------------------------------------------------------

    def set_axis(
        self,
        axis_id: str,
        *,
        label: Optional[str] = None,
        label_position: Optional[Any] = None,
        label_offset: Optional[float] = None,
        label_angle: Optional[float] = None,
        type_: Optional[str] = None,
        domain: Optional[tuple[float, float]] = None,
        bounds: Any = None,
        reverse: bool = False,
        format: Optional[str] = None,
        tick_count: Optional[int] = None,
        tick_values: Optional[Any] = None,
        tick_labels: Optional[Any] = None,
        tick_label_angle: Optional[float] = None,
        tick_label_strategy: Optional[str] = None,
        tick_label_anchor: Optional[str] = None,
        tick_label_min_gap: Optional[float] = None,
        side: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        axis_id = self._axis_id(axis_id, "axis id")
        axis_dim = self._axis_dim(axis_id)
        if type_ is not None and type_ not in {"linear", "time", "log"}:
            raise ValueError("axis type_ must be one of None, 'linear', 'time', or 'log'")
        if domain is not None:
            domain = self._finite_increasing_pair(domain, f"{axis_id} axis domain")
            if type_ == "log" and domain[0] <= 0:
                raise ValueError(f"{axis_id} log axis domain must be positive")
        if isinstance(bounds, str):
            if bounds != "data":
                raise ValueError(f"{axis_id} axis bounds must be an increasing pair or 'data'")
        elif bounds is not None:
            bounds = self._finite_increasing_pair(bounds, f"{axis_id} axis bounds")
            if type_ == "log" and bounds[0] <= 0:
                raise ValueError(f"{axis_id} log axis bounds must be positive")
        if side is None:
            side = "bottom" if axis_dim == "x" else ("right" if axis_id != "y" else "left")
        elif axis_dim == "x" and side not in {"top", "bottom"}:
            raise ValueError("x axis side must be 'top' or 'bottom'")
        elif axis_dim == "y" and side not in {"left", "right"}:
            raise ValueError("y axis side must be 'left' or 'right'")
        values = (
            None
            if tick_values is None
            else [self._finite_scalar(value, f"{axis_id} tick value") for value in tick_values]
        )
        labels = None if tick_labels is None else [str(value) for value in tick_labels]
        if labels is not None and (values is None or len(labels) != len(values)):
            raise ValueError(f"{axis_id} tick_labels must match tick_values")
        self.axis_options[axis_id] = {
            "label": self._optional_text(label, f"{axis_id} axis label"),
            "label_position": self._axis_label_position(
                label_position, f"{axis_id} axis label_position"
            ),
            "label_offset": self._optional_finite_scalar(
                label_offset, f"{axis_id} axis label_offset"
            ),
            "label_angle": self._optional_finite_scalar(label_angle, f"{axis_id} axis label_angle"),
            "type": type_,
            "domain": domain,
            "bounds": bounds,
            "reverse": self._bool_param(reverse, f"{axis_id} axis reverse"),
            "format": self._optional_text(format, f"{axis_id} axis format"),
            "tick_count": self._optional_positive_int(tick_count, f"{axis_id} axis tick_count"),
            "tick_values": values,
            "tick_labels": labels,
            "tick_label_angle": self._optional_finite_scalar(
                tick_label_angle, f"{axis_id} axis tick_label_angle"
            ),
            "tick_label_strategy": self._axis_tick_label_strategy(
                tick_label_strategy, f"{axis_id} axis tick_label_strategy"
            ),
            "tick_label_anchor": self._axis_tick_label_anchor(
                tick_label_anchor, f"{axis_id} axis tick_label_anchor"
            ),
            "tick_label_min_gap": None
            if tick_label_min_gap is None
            else self._nonnegative_scalar(tick_label_min_gap, f"{axis_id} axis tick_label_min_gap"),
            "side": side,
            "style": styles.compile_axis_style(style, f"{axis_id} axis style"),
        }
        if axis_id == "x":
            self.x_label = self.axis_options[axis_id]["label"]
        elif axis_id == "y":
            self.y_label = self.axis_options[axis_id]["label"]
        return self

    def _set_axis_domain(self, axis_id: str, domain: tuple[float, float]) -> "Figure":
        """Update only an axis domain, preserving every other configured option.

        Facet domain sharing must not reset `type_`/`label`/`reverse`/`format`/
        tick options the way a full `set_axis` replay from defaults would.
        """
        axis_id = self._axis_id(axis_id, "axis id")
        opts = self.axis_options.setdefault(axis_id, {})
        domain = self._finite_increasing_pair(domain, f"{axis_id} axis domain")
        if opts.get("type") == "log" and domain[0] <= 0:
            raise ValueError(f"{axis_id} log axis domain must be positive")
        opts["domain"] = domain
        return self

    def set_interaction(
        self,
        *,
        hover: Optional[bool] = None,
        click: Optional[bool] = None,
        select: Optional[bool] = None,
        brush: Optional[bool] = None,
        crosshair: Optional[bool] = None,
        navigation: Optional[bool] = None,
        pan: Optional[bool] = None,
        pan_axes: Optional[tuple[str, ...]] = None,
        zoom: Optional[bool] = None,
        default_drag_action: Optional[str] = None,
        zoom_axes: Optional[tuple[str, ...]] = None,
        zoom_limits: Any = None,
        wheel_zoom: Optional[bool] = None,
        box_zoom: Optional[bool] = None,
        zoom_buttons: Optional[bool] = None,
        double_click_reset: Optional[bool] = None,
        reset_axes: Optional[tuple[str, ...]] = None,
        link_group: Optional[str] = None,
        link_axes: Optional[tuple[str, ...]] = None,
        link_select: Optional[bool] = None,
        history: Optional[bool] = None,
    ) -> "Figure":
        updates: dict[str, Any] = {}
        for name, value in (
            ("hover", hover),
            ("click", click),
            ("select", select),
            ("brush", brush),
            ("crosshair", crosshair),
            ("navigation", navigation),
            ("pan", pan),
            ("zoom", zoom),
            ("wheel_zoom", wheel_zoom),
            ("box_zoom", box_zoom),
            ("zoom_buttons", zoom_buttons),
            ("double_click_reset", double_click_reset),
            ("link_select", link_select),
            ("history", history),
        ):
            normalized = self._optional_bool(value, f"interaction {name}")
            if normalized is not None:
                updates[name] = normalized
        for name, axes in (
            ("pan_axes", pan_axes),
            ("zoom_axes", zoom_axes),
            ("reset_axes", reset_axes),
        ):
            if axes is not None:
                updates[name] = self._axis_policy(axes, name)
        if zoom_limits is not None:
            updates["zoom_limits"] = zoom_limits
        if default_drag_action is not None:
            updates["default_drag_action"] = self._default_drag_action(default_drag_action)
        if link_group is not None:
            group = self._optional_text(link_group, "interaction link_group")
            if not group:
                raise ValueError("interaction link_group must be a non-empty string or None")
            updates["link_group"] = group
        if link_axes is not None:
            updates["link_axes"] = self._axis_policy(link_axes, "link_axes")
        self.interaction.update(updates)
        return self

    def set_mark_style(
        self,
        *,
        hover: Optional[dict[str, Any]] = None,
        selected: Optional[dict[str, Any]] = None,
        unselected: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Configure legacy standalone hover/selection styling.

        This low-level compatibility hook is intentionally not exposed by the
        declarative component API. Reflex integrations should derive ordinary
        mark props/styles from Reflex state instead of maintaining XY state.
        """
        for state, value in (
            ("hover", hover),
            ("selected", selected),
            ("unselected", unselected),
        ):
            style = self._optional_state_style(value, f"mark_style {state}")
            if style:
                self.mark_style[state] = {**self.mark_style.get(state, {}), **style}
        return self

    # -- trace builders -----------------------------------------------------

    def _ingest_xy(self, x: Any, y: Any, kind: str) -> tuple[Column, Column]:
        """Ingest an (x, y) pair into the column store with the equal-length
        contract every xy chart shares (line/scatter/area/bar/…)."""
        checkpoint = self.store.checkpoint()
        try:
            try:
                xc, yc = self.store.ingest_pair(x, y)
            except ValueError as error:
                if str(error).startswith("x and y must have equal length"):
                    raise ValueError(f"{kind} {error}") from error
                raise
            return xc, yc
        except Exception:
            self.store.rollback(checkpoint)
            raise

    def _checkpoint(self) -> _FigureCheckpoint:
        return (
            self.store.checkpoint(),
            len(self.traces),
            {axis: list(labels) for axis, labels in self._axis_categories.items()},
            len(self.annotations),
        )

    def _rollback(self, checkpoint: _FigureCheckpoint) -> None:
        store_checkpoint, trace_len, axis_categories, annotation_len = checkpoint
        self.store.rollback(store_checkpoint)
        del self.traces[trace_len:]
        del self.annotations[annotation_len:]
        self._axis_categories = axis_categories

    # The mark implementations live in the declarative core (marks.py); they
    # are bound here as the fluent methods, so `Figure.scatter is marks.scatter`
    # — one body, one signature, one set of defaults for both dialects.
    line = _marks.line
    area = _marks.area
    scatter = _marks.scatter
    histogram = _marks.histogram
    hist = _marks.hist
    error_band = _marks.error_band
    errorbar = _marks.errorbar
    box = _marks.box
    violin = _marks.violin
    ecdf = _marks.ecdf
    hexbin = _marks.hexbin
    contour = _marks.contour
    step = _marks.step
    stairs = _marks.stairs
    stem = _marks.stem
    segments = _marks.segments
    triangle_mesh = _marks.triangle_mesh
    bar = _marks.bar
    column = _marks.column
    heatmap = _marks.heatmap

    def _append_segment_trace(self, *args: Any, **kwargs: Any) -> None:
        _marks._append_segment_trace(self, *args, **kwargs)

    def _rect_mark_style(
        self,
        kind: str,
        corner_radius: Any,
        stroke: Optional[str],
        stroke_width: float,
        fill: Any,
    ) -> dict[str, Any]:
        """Validate the rect-family mark styling (rounded corners, border,
        gradient fill) into the sparse style keys the client renders.

        `corner_radius` is a px float for all four corners, or a `(tip, base)`
        pair in mark space — `(6, 0)` rounds only the value end of each bar
        (the top of a vertical bar), which stays correct for horizontal and
        negative bars. Setting `stroke` alone implies a 1px border, matching
        CSS expectations; the client defaults a widthed border with no color
        to the mark color."""
        style: dict[str, Any] = {}
        if isinstance(corner_radius, (tuple, list)):
            if len(corner_radius) != 2:
                raise ValueError(f"{kind} corner_radius pair must be (tip, base)")
            tip = self._nonnegative_scalar(corner_radius[0], f"{kind} corner_radius tip")
            base = self._nonnegative_scalar(corner_radius[1], f"{kind} corner_radius base")
            if tip or base:
                style["corner_radius"] = [tip, base]
        else:
            radius = self._nonnegative_scalar(corner_radius, f"{kind} corner_radius")
            if radius:
                style["corner_radius"] = radius
        stroke = self._optional_css_color(stroke, f"{kind} stroke")
        stroke_width = self._nonnegative_scalar(stroke_width, f"{kind} stroke_width")
        if stroke is not None and stroke_width == 0.0:
            stroke_width = 1.0
        fill_spec = _validate.mark_fill(fill, f"{kind} fill")
        if stroke is not None:
            style["stroke"] = stroke
        if stroke_width:
            style["stroke_width"] = stroke_width
        if fill_spec is not None:
            style["fill"] = fill_spec
        return style

    def _append_bar_rect(
        self,
        kind: str,
        orientation: str,
        pos0: np.ndarray,
        pos1: np.ndarray,
        value0: np.ndarray,
        value1: np.ndarray,
        *,
        name: Optional[str],
        color: Optional[str],
        opacity: float,
        role: str,
        extra_style: Optional[dict[str, Any]] = None,
        color_ch: Optional[ColorChannel] = None,
        stroke_ch: Optional[ColorChannel] = None,
        style_channels: Optional[dict[str, Any]] = None,
    ) -> None:
        if orientation == "vertical":
            self._append_rect_trace(
                kind,
                pos0,
                pos1,
                value0,
                value1,
                name=name,
                color=color,
                opacity=opacity,
                role=role,
                orientation=orientation,
                extra_style=extra_style,
                color_ch=color_ch,
                stroke_ch=stroke_ch,
                style_channels=style_channels,
            )
        else:
            self._append_rect_trace(
                kind,
                value0,
                value1,
                pos0,
                pos1,
                name=name,
                color=color,
                opacity=opacity,
                role=role,
                orientation=orientation,
                extra_style=extra_style,
                color_ch=color_ch,
                stroke_ch=stroke_ch,
                style_channels=style_channels,
            )

    @staticmethod
    def _as_1d_float(values: Any, label: str) -> np.ndarray:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{label} must be 1-D, got shape {arr.shape}")
        return Figure._real_float_array(arr, label)

    # Shared argument validators (bodies live in `_validate`); these thin
    # staticmethod aliases keep `self._foo(...)` call sites — and the two
    # helpers `components` reaches through `Figure` — unchanged.
    _finite_scalar = staticmethod(_validate.finite_scalar)
    _finite_increasing_pair = staticmethod(_validate.finite_increasing_pair)
    _positive_scalar = staticmethod(_validate.positive_scalar)
    _optional_finite_scalar = staticmethod(_validate.optional_finite_scalar)
    _optional_positive_int = staticmethod(_validate.optional_positive_int)
    _axis_tick_label_strategy = staticmethod(_validate.axis_tick_label_strategy)
    _axis_tick_label_anchor = staticmethod(_validate.axis_tick_label_anchor)
    _nonnegative_scalar = staticmethod(_validate.nonnegative_scalar)
    _opacity = staticmethod(_validate.opacity)
    _padding = staticmethod(_validate.plot_padding)
    _optional_bool = staticmethod(_validate.optional_bool)
    _bool_param = staticmethod(_validate.bool_param)
    _axis_id = staticmethod(_validate.axis_id)
    _optional_text = staticmethod(_validate.optional_text)
    _optional_css_color = staticmethod(_validate.optional_css_color)
    _string_mapping = staticmethod(_validate.string_mapping)
    _style_mapping = staticmethod(_validate.style_mapping)

    @staticmethod
    def _axis_dim(axis_id: str) -> str:
        return "x" if axis_id.startswith("x") else "y"

    def _axis_policy(self, value: Any, name: str) -> list[str]:
        if not isinstance(value, (tuple, list)):
            raise ValueError(f"interaction {name} must be a tuple/list of declared axis IDs")
        axes = list(value)
        if not axes:
            raise ValueError(f"interaction {name} must contain at least one axis")
        unknown = [axis for axis in axes if axis not in self.axis_options]
        if unknown:
            raise ValueError(
                f"interaction {name} contains unknown axis IDs {unknown!r}; "
                f"declared axes are {list(self.axis_options)!r}"
            )
        out: list[str] = []
        for axis in axes:
            if axis not in out:
                out.append(axis)
        return out

    @staticmethod
    def _default_drag_action(value: Any) -> str:
        allowed = {
            "auto",
            "none",
            "pan",
            "zoom",
            "select",
            "select-x",
            "select-y",
            "select-lasso",
        }
        if not isinstance(value, str) or value not in allowed:
            choices = ", ".join(repr(mode) for mode in sorted(allowed))
            raise ValueError(f"interaction default_drag_action must be one of {choices}")
        return value

    @staticmethod
    def _zoom_limit_pair(value: Any, label: str) -> list[Optional[float]]:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError(f"{label} must be a two-item tuple/list")
        normalized: list[Optional[float]] = []
        for endpoint in value:
            if endpoint is None:
                normalized.append(None)
                continue
            if isinstance(endpoint, (bool, np.bool_)):
                raise ValueError(f"{label} endpoints must be positive finite numbers or None")
            try:
                number = float(endpoint)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{label} endpoints must be positive finite numbers or None"
                ) from exc
            if not np.isfinite(number) or number <= 0:
                raise ValueError(f"{label} endpoints must be positive finite numbers or None")
            normalized.append(number)
        lower, upper = normalized
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"{label} lower endpoint must not exceed its upper endpoint")
        if (lower is not None and lower > 1.0) or (upper is not None and upper < 1.0):
            raise ValueError(f"{label} must contain home magnification 1.0")
        return normalized

    def _zoom_limits(self, value: Any) -> dict[str, list[Optional[float]]]:
        selected = self._interaction_axes("zoom_axes")
        default = [1.0, None]
        if isinstance(value, Mapping):
            unknown = [axis for axis in value if axis not in self.axis_options]
            if unknown:
                raise ValueError(f"interaction zoom_limits contains unknown axis IDs {unknown!r}")
            normalized = {axis: list(default) for axis in selected}
            for axis in self.axis_options:
                if axis in value:
                    normalized[axis] = self._zoom_limit_pair(
                        value[axis], f"interaction zoom_limits[{axis!r}]"
                    )
            return normalized
        pair = self._zoom_limit_pair(value, "interaction zoom_limits")
        return {axis: list(pair) for axis in selected}

    def _interaction_axes(self, name: str) -> list[str]:
        value = self.interaction.get(name)
        return list(self.axis_options) if value is None else self._axis_policy(value, name)

    def _validate_interaction(self) -> None:
        for name in ("pan_axes", "zoom_axes", "reset_axes", "link_axes"):
            if name in self.interaction:
                self._axis_policy(self.interaction[name], name)
        if "zoom_limits" in self.interaction:
            self._zoom_limits(self.interaction["zoom_limits"])
        action = self.interaction.get("default_drag_action")
        if action is None:
            return
        action = self._default_drag_action(action)
        if action in {"auto", "none"}:
            return

        def enabled(name: str) -> bool:
            return self.interaction.get(name, True) is not False

        if action == "pan" and not (enabled("navigation") and enabled("pan")):
            raise ValueError("interaction default_drag_action='pan' requires navigation and pan")
        if action == "zoom" and not (
            enabled("navigation") and enabled("zoom") and enabled("box_zoom")
        ):
            raise ValueError(
                "interaction default_drag_action='zoom' requires navigation, zoom, and box_zoom"
            )
        if action.startswith("select") and not (
            enabled("select") and enabled("brush") and any(t.kind == "scatter" for t in self.traces)
        ):
            raise ValueError(
                f"interaction default_drag_action={action!r} requires select, brush, and pickable data"
            )

    _axis_label_position = staticmethod(_validate.axis_label_position)

    @staticmethod
    def _required_text(value: Any, label: str) -> str:
        if isinstance(value, str):
            return value
        raise ValueError(f"{label} must be a string")

    @staticmethod
    def _pixel_dimension(value: Any, label: str) -> Any:
        if isinstance(value, str):
            if value == "100%":
                return value
            raise ValueError(f'{label} must be a positive integer pixel count or "100%"')
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
            raise ValueError(f'{label} must be a positive integer pixel count or "100%"')
        out = int(value)
        if out <= 0:
            raise ValueError(f'{label} must be a positive integer pixel count or "100%"')
        return out

    @staticmethod
    def _auto_domain(bounds: Optional[tuple[float, float]]) -> tuple[float, float]:
        """Finite increasing domain for auto-scaled scalar marks.

        Kernels require `hi > lo`; user data does not owe us variance. Expand a
        degenerate domain the same way autorange does so constant histograms and
        heatmaps render instead of tripping an internal precondition.
        """
        if bounds is None:
            return (0.0, 1.0)
        lo, hi = bounds
        if lo == hi:
            pad = abs(lo) * 0.05 or 0.5
            return (lo - pad, hi + pad)
        return (lo, hi)

    @staticmethod
    def _as_float_array(values: Any, label: str) -> np.ndarray:
        arrow = columns._arrow_to_numpy(values)
        if arrow is not None:  # pyarrow channel input: nulls become NaN
            values = arrow[0]
        elif hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim not in (1, 2):
            raise ValueError(f"{label} must be 1-D or 2-D, got shape {arr.shape}")
        return Figure._real_float_array(arr, label)

    @staticmethod
    def _real_float_array(arr: np.ndarray, label: str) -> np.ndarray:
        if np.issubdtype(arr.dtype, np.bool_):
            raise ValueError(f"{label} must be real numeric, not boolean")
        if arr.dtype == object and any(isinstance(value, (bool, np.bool_)) for value in arr.flat):
            raise ValueError(f"{label} must be real numeric, not boolean")
        if np.issubdtype(arr.dtype, np.complexfloating):
            raise ValueError(f"{label} must be real numeric")
        try:
            return arr.astype(np.float64, copy=False)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{label} must be real numeric") from e

    @staticmethod
    def _bar_value_matrix(values: Any, n_x: int, kind: str) -> np.ndarray:
        arr = Figure._as_float_array(values, f"{kind} y")
        if arr.ndim == 1:
            if len(arr) != n_x:
                raise ValueError(f"{kind} x and y must have equal length, got {n_x} and {len(arr)}")
            return arr.reshape(1, n_x)
        if arr.shape[1] == n_x:
            return arr
        if arr.shape[0] == n_x:
            return arr.T
        raise ValueError(
            f"{kind} 2-D y must have one dimension matching x length {n_x}, got {arr.shape}"
        )

    @staticmethod
    def _series_names(name: Optional[str], series: Optional[list[str]], n_series: int) -> list[str]:
        if series is not None:
            if len(series) != n_series:
                raise ValueError(f"series must have length {n_series}, got {len(series)}")
            names: list[str] = []
            for i, item in enumerate(series):
                if not isinstance(item, str):
                    raise ValueError(f"series[{i}] must be a string")
                names.append(item)
            return names
        if n_series == 1:
            return [name or ""]
        prefix = f"{name} " if name else "series "
        return [f"{prefix}{i + 1}" for i in range(n_series)]

    @staticmethod
    def _series_colors(
        color: Any, colors: Optional[list[str]], n_series: int
    ) -> list[Optional[str]]:
        if colors is not None:
            if len(colors) != n_series:
                raise ValueError(f"colors must have length {n_series}, got {len(colors)}")
            return [_validate.css_color(c, f"colors[{i}]") for i, c in enumerate(colors)]
        if isinstance(color, (list, tuple, np.ndarray)) and not isinstance(color, str):
            color_list: list[Optional[str]] = [
                _validate.css_color(str(c), f"color[{i}]") for i, c in enumerate(color)
            ]
            if len(color_list) != n_series:
                raise ValueError(
                    f"color sequence must have length {n_series}, got {len(color_list)}"
                )
            return color_list
        if color is not None:
            color = _validate.css_color(color, "color")
        return [color for _ in range(n_series)]

    @staticmethod
    def _is_category_like(values: Any) -> bool:
        if hasattr(values, "to_numpy"):
            try:
                values = values.to_numpy()
            except ValueError:
                # pyarrow Arrays with nulls refuse the default zero-copy
                # conversion (ArrowInvalid is a ValueError). This is only a
                # dtype probe, so inspect an empty slice instead of paying an
                # O(n) copy of the column.
                values = values[:0].to_numpy(zero_copy_only=False)
        arr = np.asarray(values)
        return arr.dtype.kind in ("U", "S", "O", "b")

    @staticmethod
    def _category_axis_labels(values: Any, axis: str) -> list[str]:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{axis} categories must be 1-D, got shape {arr.shape}")
        if arr.dtype.kind == "U":
            # A unicode array cannot hold missing/bytes values, so
            # `category_label` reduces to `str` — and `tolist()` already
            # yields plain `str`. Skips two O(n) Python passes per axis.
            return arr.tolist()
        return [channels.category_label(raw) for raw in arr.astype(object)]

    @staticmethod
    def _materialize_sequence(values: Any) -> Any:
        """Convert a plain list/tuple to an ndarray once, so the category
        probe and label extraction below don't each re-run the same O(n)
        conversion (`np.asarray` of an ndarray is free)."""
        if isinstance(values, (list, tuple)):
            return np.asarray(values)
        return values

    def _category_axis_id(self, axis: str) -> str:
        """Resolve a mark channel dimension to its active declarative axis id."""
        return self._active_axis_ids.get(axis, axis)

    def _axis_positions(self, values: Any, axis: str, *, commit: bool = True) -> np.ndarray:
        values = self._materialize_sequence(values)
        if not self._is_category_like(values):
            return self._as_1d_float(values, f"{axis} values")
        raw_labels = self._category_axis_labels(values, axis)
        axis_id = self._category_axis_id(axis)
        labels = (
            self._axis_categories.setdefault(axis_id, [])
            if commit
            else list(self._axis_categories.get(axis_id, []))
        )
        return self._category_positions(raw_labels, labels)

    @staticmethod
    def _category_positions(raw_labels: list[str], labels: list[str]) -> np.ndarray:
        """Positions for `raw_labels` against `labels`, provisioning new labels
        onto `labels` in first-appearance order (the category-axis contract)."""
        lookup = dict(zip(labels, range(len(labels)), strict=True))
        try:
            # Layered charts resolve the same categories once per mark, so the
            # every-label-known case is the hot one; it runs at C speed.
            return np.fromiter(
                map(lookup.__getitem__, raw_labels), np.float64, count=len(raw_labels)
            )
        except KeyError:
            pass
        # `dict.fromkeys` dedupes at C speed preserving first appearance, so
        # provisioning touches each distinct new label once.
        new_labels = [label for label in dict.fromkeys(raw_labels) if label not in lookup]
        start = len(labels)
        lookup.update(zip(new_labels, range(start, start + len(new_labels)), strict=True))
        labels.extend(new_labels)
        return np.fromiter(map(lookup.__getitem__, raw_labels), np.float64, count=len(raw_labels))

    def _axis_positions_with_labels(
        self, values: Any, axis: str
    ) -> tuple[np.ndarray, Optional[list[str]]]:
        """Uncommitted positions plus the normalized labels (None for numeric
        values), so validate-then-commit callers replay the commit as a label
        merge instead of re-running the O(n) conversion."""
        values = self._materialize_sequence(values)
        if not self._is_category_like(values):
            return self._as_1d_float(values, f"{axis} values"), None
        raw_labels = self._category_axis_labels(values, axis)
        axis_id = self._category_axis_id(axis)
        return self._category_positions(
            raw_labels, list(self._axis_categories.get(axis_id, []))
        ), raw_labels

    def _commit_category_labels(self, raw_labels: list[str], axis: str) -> None:
        axis_id = self._category_axis_id(axis)
        labels = self._axis_categories.setdefault(axis_id, [])
        # Insertion-ordered union: existing labels first, then new ones in
        # first-appearance order — identical to the provisioning loop above.
        merged = dict.fromkeys(labels)
        merged.update(dict.fromkeys(raw_labels))
        if len(merged) > len(labels):
            labels[:] = merged

    def _commit_axis_positions(self, values: Any, axis: str) -> None:
        if values is None:
            return
        values = self._materialize_sequence(values)
        if self._is_category_like(values):
            self._commit_category_labels(self._category_axis_labels(values, axis), axis)

    @staticmethod
    def _broadcast_base(base: Any, n: int, kind: str) -> np.ndarray:
        if np.isscalar(base):
            return np.full(n, Figure._finite_scalar(base, f"{kind} base"), dtype=np.float64)
        arr = Figure._as_1d_float(base, f"{kind} base")
        if len(arr) != n:
            raise ValueError(f"{kind} base must have length {n}, got {len(arr)}")
        return arr

    def _heatmap_axis_positions(self, values: Any, n: int, axis: str) -> np.ndarray:
        if values is None:
            return np.arange(n, dtype=np.float64)
        values = self._materialize_sequence(values)
        is_category = self._is_category_like(values)
        pos = self._axis_positions(values, axis, commit=False)
        if len(pos) != n:
            raise ValueError(f"heatmap {axis} must have length {n}, got {len(pos)}")
        if is_category:
            labels = self._category_axis_labels(values, axis)
            if len(set(labels)) != len(labels):
                raise ValueError(f"heatmap {axis} categories must be unique after normalization")
        return pos

    @staticmethod
    def _cell_edges(centers: np.ndarray, label: str) -> np.ndarray:
        centers = np.asarray(centers, dtype=np.float64)
        if centers.ndim != 1:
            raise ValueError(f"{label} centers must be 1-D")
        if len(centers) == 0:
            raise ValueError(f"{label} needs at least one center")
        if len(centers) == 1:
            return np.array([centers[0] - 0.5, centers[0] + 0.5], dtype=np.float64)
        diffs = np.diff(centers)
        if not np.all(np.isfinite(diffs)) or np.any(diffs <= 0):
            raise ValueError(f"{label} centers must be finite and strictly increasing")
        mids = (centers[:-1] + centers[1:]) / 2.0
        first = centers[0] - diffs[0] / 2.0
        last = centers[-1] + diffs[-1] / 2.0
        return np.concatenate(([first], mids, [last])).astype(np.float64, copy=False)

    def _append_rect_trace(
        self,
        kind: str,
        x0: Any,
        x1: Any,
        y0: Any,
        y1: Any,
        *,
        name: Optional[str],
        color: Optional[str],
        opacity: float,
        role: str,
        orientation: Optional[str] = None,
        color_ch: Optional[ColorChannel] = None,
        stroke_ch: Optional[ColorChannel] = None,
        size_ch: Optional[SizeChannel] = None,
        style_channels: Optional[dict[str, Any]] = None,
        count: Optional[int] = None,
        extra_style: Optional[dict[str, Any]] = None,
    ) -> None:
        name = self._optional_text(name, f"{kind} name")
        opacity = self._opacity(opacity, f"{kind} opacity")
        lengths = {
            self._rect_edge_len(x0, f"{kind} x0"),
            self._rect_edge_len(x1, f"{kind} x1"),
            self._rect_edge_len(y0, f"{kind} y0"),
            self._rect_edge_len(y1, f"{kind} y1"),
        }
        if len(lengths) != 1:
            raise ValueError(f"{kind} rectangle columns must have equal length")
        checkpoint = self._checkpoint()
        try:
            x0c = self.store.ingest(x0)
            x1c = self.store.ingest(x1)
            y0c = self.store.ingest(y0)
            y1c = self.store.ingest(y1)
            xc = self.store.ingest(x0c.values + (x1c.values - x0c.values) / 2.0)
            yc = self.store.ingest(y1c.values)
            style: dict[str, Any] = {"color": color, "opacity": opacity, "role": role}
            if orientation is not None:
                style["orientation"] = orientation
            if extra_style is not None:
                style.update(extra_style)
            self.traces.append(
                Trace(
                    id=len(self.traces),
                    kind=kind,
                    x=xc,
                    y=yc,
                    x0=x0c,
                    x1=x1c,
                    y0=y0c,
                    y1=y1c,
                    name=name,
                    style=style,
                    color_ch=color_ch,
                    stroke_ch=stroke_ch,
                    size_ch=size_ch,
                    style_channels=style_channels or {},
                    count=count,
                )
            )
        except Exception:
            self._rollback(checkpoint)
            raise

    @staticmethod
    def _rect_edge_len(values: Any, label: str) -> int:
        if hasattr(values, "to_numpy"):
            values = values.to_numpy()
        arr = np.asarray(values)
        if arr.ndim != 1:
            raise ValueError(f"{label} must be 1-D, got shape {arr.shape}")
        return len(arr)

    # -- ranges ---------------------------------------------------------------

    def x_range(self) -> tuple[float, float]:
        return self._range("x")

    def y_range(self) -> tuple[float, float]:
        return self._range("y")

    def _range(self, axis_id: str, *, use_domain: bool = True) -> tuple[float, float]:
        opts = self.axis_options.get(axis_id, {})
        fixed = opts.get("domain")
        if use_domain and fixed is not None:
            lo, hi = fixed
            return (hi, lo) if opts.get("reverse") else (lo, hi)

        # Autorange is O(chunks) via zone maps (§22), not an O(n) rescan.
        lo = np.inf
        hi = -np.inf
        for t in self.traces:
            for col in self._range_columns(t, axis_id):
                lo = min(lo, col.min)
                hi = max(hi, col.max)
        if not np.isfinite(lo) or not np.isfinite(hi):
            lo, hi = 0.0, 1.0
        scale = self._axis_scale(axis_id)
        if scale == "log":
            positive_los: list[float] = []
            positive_his: list[float] = []
            for t in self.traces:
                for col in self._range_columns(t, axis_id):
                    if np.isfinite(col.zone.positive_min):
                        positive_los.append(col.zone.positive_min)
                        positive_his.append(col.zone.positive_max)
            if not positive_los:
                raise ValueError(f"{axis_id} log axis requires at least one positive value")
            lo, hi = min(positive_los), max(positive_his)
        if lo == hi:
            pad = abs(lo) * 0.05 or 0.5
            lo, hi = lo - pad, hi + pad
            if scale == "log" and lo <= 0:
                lo = hi / 10.0
            return (hi, lo) if opts.get("reverse") else (lo, hi)
        pad = (hi - lo) * 0.03
        anchor = self._zero_baseline_anchor(axis_id)
        out_lo = lo - pad
        out_hi = hi + pad
        if anchor == "lo" and lo == 0.0 and hi > 0.0:
            out_lo = 0.0
        elif anchor == "hi" and hi == 0.0 and lo < 0.0:
            out_hi = 0.0
        if scale == "log":
            out_lo = max(out_lo, lo / 10.0, np.nextafter(0.0, 1.0))
        return (out_hi, out_lo) if opts.get("reverse") else (out_lo, out_hi)

    def _zero_baseline_anchor(self, axis_id: str) -> Optional[str]:
        """Pin zero to the plot edge for positive/negative rectangle charts.

        Histograms and bars encode their baseline as a rectangle edge. Padding
        away from that edge makes the bars visually float above the axis, so the
        value axis keeps zero flush when every mark extends in one direction.
        """
        axis = self._axis_dim(axis_id)
        for t in self.traces:
            if axis == "x" and t.x_axis != axis_id:
                continue
            if axis == "y" and t.y_axis != axis_id:
                continue
            if t.x0 is None or t.x1 is None or t.y0 is None or t.y1 is None:
                continue
            base = t.x0.values if axis == "x" else t.y0.values
            value = t.x1.values if axis == "x" else t.y1.values
            finite = np.isfinite(base) & np.isfinite(value)
            if not np.any(finite):
                continue
            base = base[finite]
            value = value[finite]
            if not np.all(base == 0.0):
                continue
            if np.all(value >= 0.0):
                return "lo"
            if np.all(value <= 0.0):
                return "hi"
        return None

    def _axis_scale(self, axis_id: str) -> str:
        return "log" if self.axis_options.get(axis_id, {}).get("type") == "log" else "linear"

    def _axis_kind(self, axis_id: str) -> str:
        axis = self._axis_dim(axis_id)
        forced = self.axis_options.get(axis_id, {}).get("type")
        if forced == "time":
            return "time"
        if axis_id in self._axis_categories:
            return "category"
        for t in self.traces:
            if axis == "x" and t.x_axis != axis_id:
                continue
            if axis == "y" and t.y_axis != axis_id:
                continue
            col = t.x if axis == "x" else t.y
            if col.kind == "time_ms":
                return "time"
        return "linear"

    def _axis_spec(self, axis_id: str, range_: tuple[float, float]) -> dict[str, Any]:
        axis = self._axis_dim(axis_id)
        opts = self.axis_options.get(axis_id, {})
        if axis_id == "x":
            label = self.x_label
        elif axis_id == "y":
            label = self.y_label
        else:
            label = opts.get("label")
        label = self._optional_text(label, f"{axis}_label")
        label_position = self._axis_label_position(
            opts.get("label_position"), f"{axis_id} axis label_position"
        )
        label_offset = self._optional_finite_scalar(
            opts.get("label_offset"), f"{axis_id} axis label_offset"
        )
        label_angle = self._optional_finite_scalar(
            opts.get("label_angle"), f"{axis_id} axis label_angle"
        )
        tick_count = self._optional_positive_int(
            opts.get("tick_count"), f"{axis_id} axis tick_count"
        )
        tick_label_angle = self._optional_finite_scalar(
            opts.get("tick_label_angle"), f"{axis_id} axis tick_label_angle"
        )
        tick_label_strategy = self._axis_tick_label_strategy(
            opts.get("tick_label_strategy"), f"{axis_id} axis tick_label_strategy"
        )
        tick_label_anchor = self._axis_tick_label_anchor(
            opts.get("tick_label_anchor"), f"{axis_id} axis tick_label_anchor"
        )
        tick_label_min_gap = (
            None
            if opts.get("tick_label_min_gap") is None
            else self._nonnegative_scalar(
                opts.get("tick_label_min_gap"), f"{axis_id} axis tick_label_min_gap"
            )
        )
        kind = self._axis_kind(axis_id)
        spec: dict[str, Any] = {
            "id": axis_id,
            "kind": kind,
            "label": label,
            "range": list(range_),
            "side": opts.get("side", "bottom" if axis == "x" else "left"),
        }
        if label_position is not None:
            spec["label_position"] = label_position
        if label_offset is not None:
            spec["label_offset"] = label_offset
        if label_angle is not None:
            spec["label_angle"] = label_angle
        if tick_count is not None:
            spec["tick_count"] = tick_count
        if opts.get("tick_values") is not None:
            spec["tick_values"] = list(opts["tick_values"])
        if opts.get("tick_labels") is not None:
            spec["tick_labels"] = list(opts["tick_labels"])
        if tick_label_angle is not None:
            spec["tick_label_angle"] = tick_label_angle
        if tick_label_strategy is not None:
            spec["tick_label_strategy"] = tick_label_strategy
        if tick_label_anchor is not None:
            spec["tick_label_anchor"] = tick_label_anchor
        if tick_label_min_gap is not None:
            spec["tick_label_min_gap"] = tick_label_min_gap
        if self._axis_scale(axis_id) == "log":
            spec["scale"] = "log"
        if opts.get("reverse"):
            spec["reverse"] = True
        if opts.get("domain") is not None:
            spec["domain"] = list(opts["domain"])
        bounds = opts.get("bounds")
        if bounds == "data":
            # Resolve once on the Python side so the client receives concrete
            # limits even when an independent explicit domain sets view0.
            bounds = self._range(axis_id, use_domain=False)
        if bounds is not None:
            spec["bounds"] = sorted(bounds)
        if opts.get("format") is not None:
            spec["format"] = opts["format"]
        style = styles.compile_axis_style(opts.get("style"), f"{axis_id} axis style")
        if style:
            spec["style"] = style
        if kind == "category":
            spec["categories"] = list(self._axis_categories.get(axis_id, []))
        return spec

    def _range_columns(self, t: Trace, axis_id: str) -> list[Column]:
        axis = self._axis_dim(axis_id)
        if axis == "x" and t.x_axis != axis_id:
            return []
        if axis == "y" and t.y_axis != axis_id:
            return []
        if t.kind in {"area", "error_band"} and t.base is not None:
            return [t.x] if axis == "x" else [t.y, t.base]
        if (
            t.kind == "triangle_mesh"
            and t.x0 is not None
            and t.x1 is not None
            and t.y0 is not None
            and t.y1 is not None
        ):
            return [t.x0, t.x1, t.x] if axis == "x" else [t.y0, t.y1, t.y]
        if t.x0 is not None and t.x1 is not None and t.y0 is not None and t.y1 is not None:
            return [t.x0, t.x1] if axis == "x" else [t.y0, t.y1]
        return [t.x if axis == "x" else t.y]

    # -- payload --------------------------------------------------------------

    def _interaction_spec(self) -> dict[str, Any]:
        self._validate_interaction()
        spec: dict[str, Any] = {}
        for name in (
            "hover",
            "click",
            "select",
            "brush",
            "crosshair",
            "navigation",
            "pan",
            "zoom",
            "wheel_zoom",
            "box_zoom",
            "zoom_buttons",
            "double_click_reset",
            "link_select",
            "history",
        ):
            if name in self.interaction:
                spec[name] = self._bool_param(self.interaction[name], f"interaction {name}")
        for name in ("pan_axes", "zoom_axes", "reset_axes", "link_axes"):
            if name in self.interaction:
                spec[name] = self._axis_policy(self.interaction[name], name)
        if "zoom_limits" in self.interaction:
            spec["zoom_limits"] = self._zoom_limits(self.interaction["zoom_limits"])
        if "default_drag_action" in self.interaction:
            spec["default_drag_action"] = self._default_drag_action(
                self.interaction["default_drag_action"]
            )
        link_group = self.interaction.get("link_group")
        if link_group is not None:
            group = self._optional_text(link_group, "interaction link_group")
            if not group:
                raise ValueError("interaction link_group must be a non-empty string or None")
            spec["link_group"] = group
        return spec

    def _mark_style_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {}
        for state in ("hover", "selected", "unselected"):
            style = self._optional_state_style(self.mark_style.get(state), f"mark_style {state}")
            if style:
                spec[state] = style
        return spec

    def dom_class_strings(self) -> list[str]:
        """Every DOM class string this figure emits, deduped in insertion order.

        Contract: this is the *complete* set of class strings that can reach
        the DOM — the chart root (``class_name``), the chrome slots
        (``class_names`` values), per-trace mark styles
        (``trace.style["class_name"]``), and annotation nodes
        (``annotation["class_name"]``). The Reflex adapter joins it into the
        Tailwind scan manifest for static charts (XYBF payloads are opaque to
        Tailwind's source scan), so this method must be extended whenever a
        new class-carrying surface is added to the figure.
        """
        class_strings: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            if isinstance(value, str) and value.strip() and value not in seen:
                seen.add(value)
                class_strings.append(value)

        add(self.class_name)
        for value in self.class_names.values():
            add(value)
        for trace in self.traces:
            add(trace.style.get("class_name"))
        for annotation in self.annotations:
            add(annotation.get("class_name"))
        return class_strings

    def _dom_spec(self) -> dict[str, Any]:
        dom: dict[str, Any] = {}
        class_name = self._optional_text(self.class_name, "class_name")
        if class_name:
            dom["class_name"] = class_name
        class_names = self._string_mapping(self.class_names, "class_names")
        validate_dom_slots(class_names, "class_names")
        if class_names:
            dom["class_names"] = class_names
        validate_dom_slots(self.chrome_styles, "chrome_styles")
        style = self._style_mapping(self.style, "style")
        if style:
            dom["style"] = style
        styles = {
            slot: self._style_mapping(slot_style, f"chrome_styles[{slot!r}]")
            for slot, slot_style in self.chrome_styles.items()
        }
        styles = {slot: slot_style for slot, slot_style in styles.items() if slot_style}
        if styles:
            dom["styles"] = styles
        return dom

    # -- per-kind payload emitters (extend here for new chart types) ---------

    def _rect_finite_sel(
        self,
        t: Trace,
        x0v: np.ndarray,
        x1v: np.ndarray,
        y0v: np.ndarray,
        y1v: np.ndarray,
    ) -> Optional[np.ndarray]:
        """Rows that can safely become rectangle vertices, or None for all rows."""
        geometry = (t.x0, t.x1, t.y0, t.y1)
        if any(column is None for column in geometry):
            raise ValueError(f"{t.kind} trace missing rectangle columns")
        # Zone maps already prove most generated rectangles fully finite. Scan
        # only columns that can actually reject a row; the native query keeps
        # this allocation-free when all candidates remain valid.
        candidates = [
            values
            for column, values in zip(geometry, (x0v, x1v, y0v, y1v), strict=True)
            if column is not None and column.zone.null_count
        ]
        if t.color_ch and t.color_ch.mode == "continuous":
            values = t.color_ch.values
            if values is None:
                raise ValueError(f"{t.kind} continuous color channel missing values")
            candidates.append(values)
        elif t.color_ch and t.color_ch.mode == "categorical":
            codes = t.color_ch.codes
            if codes is None:
                raise ValueError(f"{t.kind} categorical color channel missing codes")
            # Resolved categorical codes are u8/u32 and therefore always
            # finite; no source-sized pass is needed for them.
        if not candidates:
            return None
        return kernels.valid_indices_f64(tuple(candidates))

    # -- channel & density helpers -------------------------------------------

    # Interaction handlers live in interaction.py (§17/§34); these delegates are
    # the public API the widget and users call.

    def density_view(
        self, trace_id: int, x0: float, x1: float, y0: float, y1: float, w: int, h: int
    ) -> tuple[dict[str, Any], list[WireBuffer]]:
        """Re-bin a density-mode scatter's aggregation grid for a new viewport."""
        return interaction.density_view(self, trace_id, x0, x1, y0, y1, w, h)

    def pick(
        self, trace_id: int, index: int, drill_seq: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        """Exact source-row readout for a hover/pick; `index` is a shipped
        vertex index, translated to a canonical row when NaN rows were dropped
        at ship time. Pass the client's `drill_seq` to reject a pick that
        raced a drill update (wrong index space → None, never a wrong row)."""
        return interaction.pick(self, trace_id, index, drill_seq)

    def select_range(
        self, x0: float, x1: float, y0: float, y1: float, trace_id: Optional[int] = None
    ) -> dict[int, np.ndarray]:
        """Box-select: the canonical row indices inside the box, per scatter trace."""
        return interaction.select_range(self, x0, x1, y0, y1, trace_id)

    def select_polygon(self, points: Any, trace_id: Optional[int] = None) -> dict[int, np.ndarray]:
        """Lasso-select → canonical indices per scatter trace."""
        return interaction.select_polygon(self, points, trace_id)

    def to_shipped_indices(self, trace_id: int, canonical: np.ndarray) -> np.ndarray:
        """Canonical rows → shipped vertex positions (the client's mask space)."""
        return interaction.to_shipped_indices(self, trace_id, canonical)

    def decimate_view(
        self, x0: float, x1: float, px_width: int
    ) -> tuple[dict[str, Any], list[WireBuffer]]:
        """Re-decimate the visible line windows on zoom, re-centering the
        f32 upload offsets so precision holds at deep zoom."""
        return interaction.decimate_view(self, x0, x1, px_width)

    def append(
        self,
        trace_id: int,
        x: Any,
        y: Any,
        *,
        color: Any = None,
        size: Any = None,
        stroke: Any = None,
        opacity: Any = None,
        alpha: Any = None,
        stroke_width: Any = None,
        symbol: Any = None,
    ) -> tuple[dict[str, Any], list[WireBuffer]]:
        """Streaming append: extend a scatter/line trace's canonical columns
        and get the client refresh message back. The widget's `append` sends
        it; headless callers can inspect or discard it. Payloads stay
        screen-bounded, so this is O(pixels) on the wire regardless of how
        much data has accumulated."""
        return interaction.append_data(
            self,
            trace_id,
            x,
            y,
            color,
            size,
            stroke,
            opacity,
            alpha,
            stroke_width,
            symbol,
        )

    # -- unified view state (spec/design/view-state.md) ---------------------

    def _validated_state_ranges(self, ranges: Any) -> dict[str, list[float]]:
        """Validate a partial ranges mapping against the declared axes.

        Boundary rules match the §2 state document: exact axis IDs only,
        finite ``[lo, hi]`` pairs, no coercion of NaN/infinity.
        """
        if not isinstance(ranges, dict) or not ranges:
            raise ValueError("ranges must be a non-empty mapping of axis id to (lo, hi)")
        out: dict[str, list[float]] = {}
        for axis_id, pair in ranges.items():
            if axis_id not in self.axis_options:
                raise ValueError(f"unknown axis id {axis_id!r}")
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError(f"range for axis {axis_id!r} must be a (lo, hi) pair")
            lo, hi = float(pair[0]), float(pair[1])
            if not math.isfinite(lo) or not math.isfinite(hi) or lo == hi:
                raise ValueError(f"range for axis {axis_id!r} must be finite and non-empty")
            out[axis_id] = [lo, hi]
        return out

    @staticmethod
    def _validated_state_selection(
        range: Any = None, polygon: Any = None
    ) -> Optional[dict[str, Any]]:
        """Normalize a geometric selection to its §2 wire shape (or None)."""
        if range is not None and polygon is not None:
            raise ValueError("pass range= or polygon=, not both")
        if range is not None:
            if isinstance(range, dict):
                try:
                    values = [float(range[key]) for key in ("x0", "x1", "y0", "y1")]
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("selection range must supply finite x0, x1, y0, y1") from exc
            else:
                try:
                    values = [float(v) for v in range]
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "selection range must be a (x0, x1, y0, y1) tuple or dict"
                    ) from exc
                if len(values) != 4:
                    raise ValueError("selection range must have exactly x0, x1, y0, y1")
            if not all(math.isfinite(v) for v in values):
                raise ValueError("selection range must be finite")
            x0, x1, y0, y1 = values
            return {"range": {"x0": x0, "x1": x1, "y0": y0, "y1": y1}}
        if polygon is not None:
            try:
                points = [[float(p[0]), float(p[1])] for p in polygon]
            except (TypeError, ValueError, IndexError) as exc:
                raise ValueError("selection polygon must be a sequence of (x, y)") from exc
            if len(points) < 3:
                raise ValueError("selection polygon needs at least 3 points")
            if not all(math.isfinite(v) for point in points for v in point):
                raise ValueError("selection polygon must be finite")
            return {"polygon": points}
        return None

    def state_patch_message(
        self,
        *,
        ranges: Any = None,
        selection: Any = _STATE_UNSET,
        animate: bool = True,
        history: bool = True,
    ) -> dict[str, Any]:
        """Build one §8 ``state_patch`` message (merge-patch semantics: absent
        keys leave that facet of the client state alone)."""
        state: dict[str, Any] = {"v": 1}
        if ranges is not None:
            state["ranges"] = self._validated_state_ranges(ranges)
        if selection is not _STATE_UNSET:
            state["selection"] = selection
        if "ranges" not in state and "selection" not in state:
            raise ValueError("state patch must change ranges or selection")
        return {
            "type": "state_patch",
            "state": state,
            "animate": bool(animate),
            "history": bool(history),
        }

    def view_nav_message(self, axes: Any = None) -> dict[str, Any]:
        """Build the §8 ``view_nav`` reset message (axes=None → the client's
        configured reset_axes)."""
        message: dict[str, Any] = {"type": "view_nav", "op": "reset"}
        if axes is not None:
            message["axes"] = self._axis_policy(tuple(axes), "reset axes")
        return message

    def selection_rows_message(self, rows: Any) -> tuple[dict[str, Any], list[WireBuffer]]:
        """Kernel-resolve a per-trace row-index selection into the same binary
        mask buffers the gesture selection path ships (§5.1). Rows-selections
        are non-durable by design; the client applies them outside history."""
        if rows is None:
            raise ValueError("rows selection requires per-trace row indices")
        if not isinstance(rows, dict):
            rows = {0: rows}
        traces: list[dict[str, Any]] = []
        out: list[WireBuffer] = []
        total = 0
        for trace_id, indices in rows.items():
            tid = int(trace_id)
            if not 0 <= tid < len(self.traces):
                raise ValueError(f"unknown trace id {trace_id!r}")
            raw = np.asarray(indices)
            # Canonical row indices are validated here, before the uint32
            # wire encoding: a negative or oversized value would otherwise
            # wrap/ship silently (-1 -> 4294967295) and inflate `total`
            # while the browser highlights nothing (staff-review finding).
            integral = raw.size == 0 or (
                raw.dtype != np.bool_
                and (
                    np.issubdtype(raw.dtype, np.integer)
                    or (
                        np.issubdtype(raw.dtype, np.floating)
                        and bool(np.all(np.isfinite(raw)))
                        and bool(np.all(np.equal(np.mod(raw, 1), 0)))
                    )
                )
            )
            if not integral:
                raise ValueError(
                    f"row indices for trace {tid} must be integers, got dtype {raw.dtype}"
                )
            idx = np.unique(np.asarray(raw, dtype=np.int64).ravel())
            n_rows = len(self.traces[tid].x)
            if idx.size and (int(idx[0]) < 0 or int(idx[-1]) >= n_rows):
                raise ValueError(
                    f"row indices for trace {tid} must be in [0, {n_rows}), "
                    f"got {int(idx[0])}..{int(idx[-1])}"
                )
            wire_idx = self.to_shipped_indices(tid, idx)
            traces.append(
                {
                    "id": tid,
                    "count": int(len(wire_idx)),
                    "buf": len(out),
                    "drill_seq": self.traces[tid].drill_seq,
                }
            )
            out.append(array_byte_view(wire_idx))
            # Deduplicated, validated canonical rows — not the raw request
            # length and not only the currently-shipped subset.
            total += int(idx.size)
        return {"type": "selection_rows", "traces": traces, "total": total}, out

    def view_state(self) -> dict[str, Any]:
        """The last committed durable state (§5.1). Served from the kernel's
        event-fed cache — no client round-trip; reads are eventually
        consistent and start at the home ranges before any event arrives."""
        if self._view_state_ranges is not None:
            ranges = {axis_id: list(pair) for axis_id, pair in self._view_state_ranges.items()}
        else:
            ranges = {axis_id: list(self._range(axis_id)) for axis_id in self.axis_options}
        selection = self._view_state_selection
        if isinstance(selection, dict):
            selection = dict(selection)
        return {"v": 1, "ranges": ranges, "selection": selection}

    def _record_view_ranges(self, ranges: dict[str, list[float]]) -> None:
        """Fold a committed view event's ranges into the state cache."""
        if self._view_state_ranges is None:
            self._view_state_ranges = {
                axis_id: list(self._range(axis_id)) for axis_id in self.axis_options
            }
        for axis_id, pair in ranges.items():
            if axis_id in self.axis_options:
                self._view_state_ranges[axis_id] = [float(pair[0]), float(pair[1])]

    def _record_selection(self, selection: Optional[dict[str, Any]]) -> None:
        """Fold a committed selection into the state cache; rows-selections
        are recorded only as the opaque ``{"rows": true}`` marker (§2)."""
        self._view_state_selection = selection

    # -- output -----------------------------------------------------------

    def widget(self) -> Any:
        if self._widget is None:
            from .widget import FigureWidget

            self._widget = FigureWidget(self)
        return self._widget

    def show(self) -> Any:
        return self.widget()

    def _ipython_display_(self) -> None:
        from IPython.display import display  # type: ignore[import-not-found]

        display(self.widget())

    def to_html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
        animation_progress: Optional[float] = None,
    ) -> str:
        """Standalone interactive HTML: JS client + spec + base64 buffers in
        one self-contained file (base64 carries a ~33% size tax). `custom_css`
        injects an author stylesheet so `class_names` utility classes
        (e.g. Tailwind) resolve in the export."""
        return export.to_html(
            self,
            path,
            custom_css=custom_css,
            animation_progress=animation_progress,
        )

    def html(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        custom_css: Optional[str] = None,
        animation_progress: Optional[float] = None,
    ) -> str:
        """Alias for ``to_html`` for component-style API symmetry."""
        return self.to_html(
            path,
            custom_css=custom_css,
            animation_progress=animation_progress,
        )

    def _repr_html_(self) -> str:
        """Notebook HTML repr isolated from the host document's styles."""
        return export.notebook_iframe(self.to_html(), width=self.width, height=self.height)

    def to_svg(
        self,
        path: Optional[str | PathLike[str]] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> str:
        """Static SVG (_svg.py): a pure-Python render of the same decimated
        payload the browser client consumes — resolution-independent, tiny
        (screen-bounded regardless of source size), and dependency-free.
        `width`/`height` override the figure's pixel size."""
        from . import _svg

        return _svg.to_svg(self, path, width=width, height=height)

    def to_png(
        self,
        path: Optional[str] = None,
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        engine: export.Engine = export.Engine.default,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Static PNG (export.py). `engine=Engine.default` paints the
        decimated payload with the built-in Rust rasterizer — no browser,
        millisecond export. `optimize=True` uses the slower size-oriented
        indexed encoder. `engine=Engine.chromium` screenshots the standalone
        HTML with an automatically discovered installed browser for browser
        CSS/WebGL fidelity (see export.find_browser); `gl` selects its WebGL
        backend — "software" (default, deterministic SwiftShader) or
        "hardware" (real GPU). `custom_css` is Chromium-only and injects an
        author stylesheet into the captured document."""
        return export.to_png(
            self,
            path,
            width=width,
            height=height,
            scale=scale,
            engine=engine,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def to_image(
        self,
        format: str = "png",
        *,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        background: Optional[str] = None,
        engine: export.Engine | str = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Unified static export: PNG/JPEG/WebP/SVG/PDF bytes (export.py).

        `engine=Engine.auto` is deterministic — the browser-free native path
        for every format, Chromium only when `custom_css` needs a real CSS
        engine. See `export.to_image` for the format, quality, and background
        policies."""
        return export.to_image(
            self,
            format,
            width=width,
            height=height,
            scale=scale,
            background=background,
            engine=engine,
            quality=quality,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def write_image(
        self,
        path: str | PathLike[str],
        *,
        format: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        scale: float = 2.0,
        background: Optional[str] = None,
        engine: export.Engine | str = export.Engine.auto,
        quality: Optional[int] = None,
        optimize: bool = False,
        custom_css: Optional[str] = None,
        sandbox: bool = True,
        gl: str = "software",
    ) -> bytes:
        """Atomic file export with extension-inferred format (export.py):
        .png/.jpg/.jpeg/.webp/.svg/.pdf, plus .html routing to `to_html`."""
        return export.write_image(
            self,
            path,
            format=format,
            width=width,
            height=height,
            scale=scale,
            background=background,
            engine=engine,
            quality=quality,
            optimize=optimize,
            custom_css=custom_css,
            sandbox=sandbox,
            gl=gl,
        )

    def memory_report(self) -> dict[str, Any]:
        """Every byte class itemized; if it isn't in the report it isn't real."""
        from . import interaction  # method-local: no load-time cycle

        spec, blob = self.build_payload()
        report = self.store.memory_report()
        channel_arrays: list[np.ndarray] = []
        store_arrays = [column.values for column in self.store.columns]
        seen_channels: set[tuple[int, int]] = set()
        for trace in self.traces:
            for channel in (trace.color_ch, trace.size_ch):
                if channel is None:
                    continue
                values = (
                    getattr(channel, "codes", None)
                    if channel.mode == "categorical"
                    else channel.values
                )
                if values is None:
                    continue
                capacity = getattr(channel, "_buffer", None)
                arrays = [capacity if capacity is not None else values]
                counts = getattr(channel, "counts", None)
                if counts is not None:
                    arrays.append(counts)
                for array in arrays:
                    key = (int(array.__array_interface__["data"][0]), int(array.nbytes))
                    if key in seen_channels or any(
                        np.shares_memory(array, item) for item in store_arrays
                    ):
                        continue
                    seen_channels.add(key)
                    channel_arrays.append(array)
        report["channel_bytes"] = int(sum(array.nbytes for array in channel_arrays))
        report["transport_bytes_first_paint"] = len(blob)
        n_total = sum(t.n_points for t in self.traces) or 1
        report["transport_bytes_per_point"] = len(blob) / n_total
        report["pyramid_bytes"] = interaction.pyramid_report_bytes(self)
        report["resident_array_bytes"] = (
            report["canonical_bytes"] + report["channel_bytes"] + report["pyramid_bytes"]
        )
        report["backend"] = kernels.BACKEND
        return report

    @staticmethod
    def _optional_state_style(
        value: Optional[dict[str, Any]], label: str
    ) -> dict[str, str | int | float]:
        if value is None:
            return {}
        return Figure._style_mapping(value, label)


# The AnnotationsMixin methods (in `_annotations.py`) and the mark
# implementations (in `marks.py`) carry `-> "Figure"` / `self: "Figure"`
# annotations; expose the concrete class in those modules so
# `typing.get_type_hints` resolves it at runtime without a load-time cycle.
_annotations.Figure = Figure
_marks.Figure = Figure

# The bound mark methods report Figure-owned identity in tracebacks and docs
# even though the function objects live in the declarative core.
for _name in (
    "line",
    "area",
    "error_band",
    "errorbar",
    "scatter",
    "histogram",
    "hist",
    "box",
    "violin",
    "ecdf",
    "hexbin",
    "contour",
    "step",
    "stairs",
    "stem",
    "bar",
    "column",
    "heatmap",
):
    getattr(_marks, _name).__qualname__ = f"Figure.{_name}"
del _name
