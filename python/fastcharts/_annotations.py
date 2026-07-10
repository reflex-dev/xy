"""Annotation builders for `Figure` (vline/hline/band/callout/text/marker/
arrow + reference-line and zone helpers) and the annotation spec compiler.

Split out of `_figure.py` as a mixin: `Figure` inherits `AnnotationsMixin`, so
`fig.vline(...)` etc. are unchanged and every `self.*` (validators, the column
store, `self.annotations`, rollback) resolves through the concrete `Figure` via
the MRO. Only numpy + the columns/channels helpers are needed at module level."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from . import channels, columns

if TYPE_CHECKING:
    # Type-only host base: `self.*` (validators, column store, annotations)
    # resolves against the Figure surface. `FigureHost` is a Protocol, so there
    # is no nominal inheritance cycle; at runtime the base is plain `object`.
    from ._figure import Figure  # noqa: F401  (resolves the `-> "Figure"` returns)
    from ._hosts import FigureHost as _Host
else:
    _Host = object


class AnnotationsMixin(_Host):
    def vline(
        self: "Figure",
        x: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#667085",
        width: float = 1.5,
        opacity: float = 1.0,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a vertical rule annotation at data coordinate `x`.

        Rules live in the chart chrome layer: they stay crisp during pan/zoom
        and annotate the current plot without adding a data trace or legend row.
        """
        return self._append_rule_annotation(
            "x",
            x,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def hline(
        self: "Figure",
        y: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#667085",
        width: float = 1.5,
        opacity: float = 1.0,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a horizontal rule annotation at data coordinate `y`."""
        return self._append_rule_annotation(
            "y",
            y,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def threshold(
        self: "Figure",
        value: Any,
        *,
        axis: str = "y",
        text: Optional[str] = None,
        color: Optional[str] = "#e11d48",
        width: float = 1.5,
        opacity: float = 1.0,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a semantic threshold rule on the x or y axis."""
        axis = self._annotation_axis(axis, "threshold axis")
        if axis == "x":
            return self.vline(
                value,
                text=text,
                color=color,
                width=width,
                opacity=opacity,
                class_name=class_name,
                style=style,
            )
        return self.hline(
            value,
            text=text,
            color=color,
            width=width,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def x_band(
        self: "Figure",
        x0: Any,
        x1: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#64748b",
        opacity: float = 0.14,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a vertical span annotation from `x0` to `x1`."""
        return self._append_band_annotation(
            "x",
            x0,
            x1,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def y_band(
        self: "Figure",
        y0: Any,
        y1: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#64748b",
        opacity: float = 0.14,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a horizontal span annotation from `y0` to `y1`."""
        return self._append_band_annotation(
            "y",
            y0,
            y1,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def threshold_zone(
        self: "Figure",
        start: Any,
        end: Any,
        *,
        axis: str = "y",
        text: Optional[str] = None,
        color: Optional[str] = "#e11d48",
        opacity: float = 0.12,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a semantic threshold band on the x or y axis."""
        axis = self._annotation_axis(axis, "threshold_zone axis")
        if axis == "x":
            return self.x_band(
                start,
                end,
                text=text,
                color=color,
                opacity=opacity,
                class_name=class_name,
                style=style,
            )
        return self.y_band(
            start,
            end,
            text=text,
            color=color,
            opacity=opacity,
            class_name=class_name,
            style=style,
        )

    def text(
        self: "Figure",
        x: Any,
        y: Any,
        text: str,
        *,
        dx: float = 6.0,
        dy: float = -6.0,
        color: Optional[str] = None,
        anchor: str = "start",
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a text annotation anchored at a data coordinate."""
        text = self._required_text(text, "text annotation text")
        dx = self._finite_scalar(dx, "text annotation dx")
        dy = self._finite_scalar(dy, "text annotation dy")
        if anchor not in {"start", "middle", "end"}:
            raise ValueError("text annotation anchor must be 'start', 'middle', or 'end'")
        self.annotations.append(
            {
                "kind": "text",
                "x": x,
                "y": y,
                "text": text,
                "dx": dx,
                "dy": dy,
                "anchor": anchor,
                "style": {
                    "color": self._optional_css_color(color, "text annotation color"),
                    **self._style_mapping(style or {}, "text annotation style"),
                },
                "class_name": self._optional_text(class_name, "text annotation class_name"),
            }
        )
        return self

    def label(
        self: "Figure",
        x: Any,
        y: Any,
        text: str,
        *,
        dx: float = 6.0,
        dy: float = -6.0,
        color: Optional[str] = None,
        anchor: str = "start",
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Alias for a positioned text annotation."""
        return self.text(
            x,
            y,
            text,
            dx=dx,
            dy=dy,
            color=color,
            anchor=anchor,
            class_name=class_name,
            style=style,
        )

    def marker(
        self: "Figure",
        x: Any,
        y: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#2563eb",
        size: float = 8.0,
        symbol: str = "circle",
        stroke_color: Optional[str] = "#ffffff",
        stroke_width: float = 1.5,
        opacity: float = 1.0,
        dx: float = 8.0,
        dy: float = -8.0,
        anchor: str = "start",
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a point marker annotation with an optional label."""
        size = self._positive_scalar(size, "marker size")
        stroke_width = self._nonnegative_scalar(stroke_width, "marker stroke_width")
        opacity = self._opacity(opacity, "marker opacity")
        dx = self._finite_scalar(dx, "marker dx")
        dy = self._finite_scalar(dy, "marker dy")
        symbol = self._annotation_symbol(symbol, "marker symbol")
        anchor = self._annotation_anchor(anchor, "marker anchor")
        self.annotations.append(
            {
                "kind": "marker",
                "x": x,
                "y": y,
                "text": self._optional_text(text, "marker text"),
                "dx": dx,
                "dy": dy,
                "anchor": anchor,
                "size": size,
                "symbol": symbol,
                "style": {
                    "color": self._optional_css_color(color, "marker color"),
                    "stroke_color": self._optional_css_color(stroke_color, "marker stroke_color"),
                    "stroke_width": stroke_width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, "marker style"),
                },
                "class_name": self._optional_text(class_name, "marker class_name"),
            }
        )
        return self

    def arrow(
        self: "Figure",
        x0: Any,
        y0: Any,
        x1: Any,
        y1: Any,
        *,
        text: Optional[str] = None,
        color: Optional[str] = "#667085",
        width: float = 1.5,
        opacity: float = 1.0,
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add an arrow annotation from (`x0`, `y0`) to (`x1`, `y1`)."""
        width = self._positive_scalar(width, "arrow width")
        opacity = self._opacity(opacity, "arrow opacity")
        self.annotations.append(
            {
                "kind": "arrow",
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "text": self._optional_text(text, "arrow text"),
                "style": {
                    "color": self._optional_css_color(color, "arrow color"),
                    "width": width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, "arrow style"),
                },
                "class_name": self._optional_text(class_name, "arrow class_name"),
            }
        )
        return self

    def callout(
        self: "Figure",
        x: Any,
        y: Any,
        text: str,
        *,
        dx: float = 36.0,
        dy: float = -30.0,
        color: Optional[str] = "#344054",
        width: float = 1.5,
        opacity: float = 1.0,
        anchor: str = "start",
        class_name: Optional[str] = None,
        style: Optional[dict[str, Any]] = None,
    ) -> "Figure":
        """Add a text callout offset from a data coordinate with a pointer arrow."""
        text = self._required_text(text, "callout text")
        dx = self._finite_scalar(dx, "callout dx")
        dy = self._finite_scalar(dy, "callout dy")
        width = self._positive_scalar(width, "callout width")
        opacity = self._opacity(opacity, "callout opacity")
        if anchor not in {"start", "middle", "end"}:
            raise ValueError("callout anchor must be 'start', 'middle', or 'end'")
        self.annotations.append(
            {
                "kind": "callout",
                "x": x,
                "y": y,
                "text": text,
                "dx": dx,
                "dy": dy,
                "anchor": anchor,
                "style": {
                    "color": self._optional_css_color(color, "callout color"),
                    "width": width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, "callout style"),
                },
                "class_name": self._optional_text(class_name, "callout class_name"),
            }
        )
        return self

    def _append_rule_annotation(
        self: "Figure",
        axis: str,
        value: Any,
        *,
        text: Optional[str],
        color: Optional[str],
        width: float,
        opacity: float,
        class_name: Optional[str],
        style: Optional[dict[str, Any]],
    ) -> "Figure":
        width = self._positive_scalar(width, f"{axis} rule width")
        opacity = self._opacity(opacity, f"{axis} rule opacity")
        self.annotations.append(
            {
                "kind": "rule",
                "axis": axis,
                "value": value,
                "text": self._optional_text(text, f"{axis} rule text"),
                "style": {
                    "color": self._optional_css_color(color, f"{axis} rule color"),
                    "width": width,
                    "opacity": opacity,
                    **self._style_mapping(style or {}, f"{axis} rule style"),
                },
                "class_name": self._optional_text(class_name, f"{axis} rule class_name"),
            }
        )
        return self

    def _append_band_annotation(
        self: "Figure",
        axis: str,
        start: Any,
        end: Any,
        *,
        text: Optional[str],
        color: Optional[str],
        opacity: float,
        class_name: Optional[str],
        style: Optional[dict[str, Any]],
    ) -> "Figure":
        opacity = self._opacity(opacity, f"{axis} band opacity")
        self.annotations.append(
            {
                "kind": "band",
                "axis": axis,
                "start": start,
                "end": end,
                "text": self._optional_text(text, f"{axis} band text"),
                "style": {
                    "color": self._optional_css_color(color, f"{axis} band color"),
                    "opacity": opacity,
                    **self._style_mapping(style or {}, f"{axis} band style"),
                },
                "class_name": self._optional_text(class_name, f"{axis} band class_name"),
            }
        )
        return self

    def _annotation_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for i, annotation in enumerate(self.annotations):
            kind = annotation.get("kind")
            label = f"annotation[{i}]"
            if kind == "rule":
                axis = self._annotation_axis(annotation.get("axis"), f"{label}.axis")
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "rule",
                        "axis": axis,
                        "value": self._annotation_value(
                            annotation.get("value"), axis, f"{label}.value"
                        ),
                    }
                )
            elif kind == "band":
                axis = self._annotation_axis(annotation.get("axis"), f"{label}.axis")
                start = self._annotation_value(annotation.get("start"), axis, f"{label}.start")
                end = self._annotation_value(annotation.get("end"), axis, f"{label}.end")
                if end <= start:
                    raise ValueError(f"{label} end must be greater than start")
                specs.append(
                    self._annotation_common(annotation)
                    | {"kind": "band", "axis": axis, "start": start, "end": end}
                )
            elif kind == "text":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "text",
                        "x": self._annotation_value(annotation.get("x"), "x", f"{label}.x"),
                        "y": self._annotation_value(annotation.get("y"), "y", f"{label}.y"),
                        "text": self._required_text(annotation.get("text"), f"{label}.text"),
                        "dx": self._finite_scalar(annotation.get("dx", 0.0), f"{label}.dx"),
                        "dy": self._finite_scalar(annotation.get("dy", 0.0), f"{label}.dy"),
                        "anchor": self._annotation_anchor(
                            annotation.get("anchor", "start"), f"{label}.anchor"
                        ),
                    }
                )
            elif kind == "marker":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "marker",
                        "x": self._annotation_value(annotation.get("x"), "x", f"{label}.x"),
                        "y": self._annotation_value(annotation.get("y"), "y", f"{label}.y"),
                        "size": self._positive_scalar(annotation.get("size", 8.0), f"{label}.size"),
                        "symbol": self._annotation_symbol(
                            annotation.get("symbol", "circle"), f"{label}.symbol"
                        ),
                        "dx": self._finite_scalar(annotation.get("dx", 0.0), f"{label}.dx"),
                        "dy": self._finite_scalar(annotation.get("dy", 0.0), f"{label}.dy"),
                        "anchor": self._annotation_anchor(
                            annotation.get("anchor", "start"), f"{label}.anchor"
                        ),
                    }
                )
            elif kind == "arrow":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "arrow",
                        "x0": self._annotation_value(annotation.get("x0"), "x", f"{label}.x0"),
                        "y0": self._annotation_value(annotation.get("y0"), "y", f"{label}.y0"),
                        "x1": self._annotation_value(annotation.get("x1"), "x", f"{label}.x1"),
                        "y1": self._annotation_value(annotation.get("y1"), "y", f"{label}.y1"),
                    }
                )
            elif kind == "callout":
                specs.append(
                    self._annotation_common(annotation)
                    | {
                        "kind": "callout",
                        "x": self._annotation_value(annotation.get("x"), "x", f"{label}.x"),
                        "y": self._annotation_value(annotation.get("y"), "y", f"{label}.y"),
                        "text": self._required_text(annotation.get("text"), f"{label}.text"),
                        "dx": self._finite_scalar(annotation.get("dx", 0.0), f"{label}.dx"),
                        "dy": self._finite_scalar(annotation.get("dy", 0.0), f"{label}.dy"),
                        "anchor": self._annotation_anchor(
                            annotation.get("anchor", "start"), f"{label}.anchor"
                        ),
                    }
                )
            else:
                raise ValueError(
                    f"{label} kind must be 'rule', 'band', 'text', 'marker', 'arrow', or 'callout'"
                )
        return specs

    def _annotation_common(self, annotation: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        text = self._optional_text(annotation.get("text"), "annotation text")
        if text is not None:
            out["text"] = text
        class_name = self._optional_text(annotation.get("class_name"), "annotation class_name")
        if class_name is not None:
            out["class_name"] = class_name
        raw_style = annotation.get("style", {})
        if not isinstance(raw_style, dict):
            raise ValueError("annotation style must be a dict[str, str | int | float]")
        raw_style = {key: value for key, value in raw_style.items() if value is not None}
        style = self._style_mapping(raw_style, "annotation style")
        if style:
            out["style"] = style
        return out

    @staticmethod
    def _annotation_axis(axis: Any, label: str) -> str:
        if axis not in {"x", "y"}:
            raise ValueError(f"{label} must be 'x' or 'y'")
        return axis

    @staticmethod
    def _annotation_anchor(anchor: Any, label: str) -> str:
        if anchor not in {"start", "middle", "end"}:
            raise ValueError(f"{label} must be 'start', 'middle', or 'end'")
        return anchor

    @staticmethod
    def _annotation_symbol(symbol: Any, label: str) -> str:
        allowed = {"circle", "square", "diamond", "cross"}
        if symbol not in allowed:
            raise ValueError(f"{label} must be one of {sorted(allowed)}")
        return symbol

    def _annotation_value(self, value: Any, axis: str, label: str) -> float:
        categories = self._axis_categories.get(axis)
        if isinstance(value, str) and categories is not None:
            normalized = channels.category_label(value)
            try:
                return float(categories.index(normalized))
            except ValueError as e:
                raise ValueError(
                    f"{label} category {value!r} is not present on the {axis}-axis"
                ) from e
        if isinstance(value, str):
            raise ValueError(
                f"{label} must be a finite coordinate; string coordinates require "
                f"a categorical {axis}-axis"
            )
        try:
            arr, _kind, _copies = columns._canonicalize([value])
        except ValueError as e:
            raise ValueError(f"{label} must be a finite coordinate") from e
        out = float(arr[0])
        if not np.isfinite(out):
            raise ValueError(f"{label} must be finite")
        return out
