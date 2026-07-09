"""Type-only host contract for the `Figure` mixins.

`AnnotationsMixin` (`_annotations`) and `PayloadMixin` (`_payload`) are always
composed into `Figure`, and their methods reach the rest of `Figure` through
`self` (validators, the column store, axis/spec helpers). Declaring that surface
once as a `Protocol` lets the mixins type-check their `self.*` accesses without a
nominal inheritance cycle (a concrete `_Host = Figure` base is rejected as
cyclic). This module has no runtime role — it is imported only under
`TYPE_CHECKING`.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from .columns import ColumnStore


class FigureHost(Protocol):
    """The `Figure` surface the annotation/payload mixins consume via `self`."""

    # -- state --
    store: ColumnStore
    traces: list[Any]
    annotations: list[dict[str, Any]]
    axis_options: dict[str, dict[str, Any]]
    _axis_categories: dict[str, list[str]]
    title: Optional[str]
    width: Any
    height: Any
    padding: Any
    tooltip: Optional[dict[str, Any]]
    show_legend: bool
    show_modebar: bool
    show_tooltip: bool

    # -- shared validators (static on `Figure`, aliases of `_validate`) --
    @staticmethod
    def _finite_scalar(value: Any, label: str) -> float: ...
    @staticmethod
    def _positive_scalar(value: Any, label: str) -> float: ...
    @staticmethod
    def _nonnegative_scalar(value: Any, label: str) -> float: ...
    @staticmethod
    def _opacity(value: Any, label: str) -> float: ...
    @staticmethod
    def _optional_css_color(value: Any, label: str) -> Optional[str]: ...
    @staticmethod
    def _optional_text(value: Any, label: str) -> Optional[str]: ...
    @staticmethod
    def _required_text(value: Any, label: str) -> str: ...
    @staticmethod
    def _style_mapping(value: dict[str, Any], label: str) -> dict[str, Any]: ...

    # -- spec/axis helpers that stay on Figure --
    def _axis_scale(self, axis_id: str) -> str: ...
    def _axis_spec(self, axis_id: str, range_: tuple[float, float]) -> dict[str, Any]: ...
    def _dom_spec(self) -> dict[str, Any]: ...
    def _interaction_spec(self) -> dict[str, Any]: ...
    def _mark_style_spec(self) -> dict[str, Any]: ...
    def _range(self, *args: Any, **kwargs: Any) -> Any: ...
    def _rect_finite_sel(self, *args: Any, **kwargs: Any) -> Any: ...
    def _annotation_specs(self) -> list[dict[str, Any]]: ...
