"""Stable browser DOM slot names for CSS/Tailwind hooks."""

from __future__ import annotations

from collections.abc import Mapping

CHART_DOM_SLOTS: tuple[str, ...] = (
    "root",
    "title",
    "chrome",
    "canvas",
    "labels",
    "legend",
    "legend_item",
    "legend_swatch",
    "colorbar",
    "colorbar_bar",
    "colorbar_tick",
    "colorbar_title",
    "tooltip",
    "modebar",
    "modebar_button",
    "selection",
    "crosshair_x",
    "crosshair_y",
    "badge",
    "badge_item",
    "tick_label",
    "axis_title",
    "annotation_label",
)
"""Stable `class_names` / chrome `style` slots emitted by the browser client."""


def validate_dom_slots(mapping: Mapping[str, object], label: str) -> None:
    """Reject unknown DOM slots before they reach the standalone/widget spec."""
    unknown = sorted(set(mapping) - set(CHART_DOM_SLOTS))
    if unknown:
        slots = ", ".join(CHART_DOM_SLOTS)
        raise ValueError(f"{label} has unknown slot(s) {unknown}; expected one of: {slots}")
