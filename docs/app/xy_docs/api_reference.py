"""Generated API-reference sections for XY's public component factories."""

import reflex as rx
import xy as fc
from reflex_site_shared.components.docs_api import (
    callable_api_group,
    callable_api_reference,
)

MARKS = (
    fc.line,
    fc.scatter,
    fc.area,
    fc.bar,
    fc.column,
    fc.histogram,
    fc.box,
    fc.violin,
    fc.ecdf,
    fc.heatmap,
    fc.hexbin,
    fc.contour,
    fc.errorbar,
    fc.error_band,
    fc.step,
    fc.stairs,
    fc.stem,
    fc.segments,
    fc.triangle_mesh,
)

AXES_AND_ANNOTATIONS = (
    fc.x_axis,
    fc.y_axis,
    fc.vline,
    fc.hline,
    fc.x_band,
    fc.y_band,
    fc.threshold,
    fc.threshold_zone,
    fc.text,
    fc.label,
    fc.marker,
    fc.arrow,
    fc.callout,
)

CHROME_AND_BEHAVIOR = (
    fc.legend,
    fc.tooltip,
    fc.colorbar,
    fc.modebar,
    fc.theme,
    fc.interaction_config,
)


def chart_containers_api() -> rx.Component:
    """Render chart-container API tables.

    Returns:
        Generated chart-container reference.
    """
    return rx.box(
        callable_api_reference(
            fc.Chart.__init__,
            display_name="Shared chart props",
            exclude_parameters=("self", "kind"),
            parameter_descriptions={
                "children": "Marks, axes, annotations, and chart chrome.",
            },
        ),
        callable_api_reference(fc.facet_chart, display_name="fc.facet_chart"),
        class_name="flex w-full flex-col",
    )


def marks_api() -> rx.Component:
    """Render mark API tables.

    Returns:
        Generated mark reference.
    """
    return callable_api_group(*MARKS, namespace="fc")


def axes_and_annotations_api() -> rx.Component:
    """Render axis and annotation API tables.

    Returns:
        Generated axis and annotation reference.
    """
    return callable_api_group(*AXES_AND_ANNOTATIONS, namespace="fc")


def chrome_and_behavior_api() -> rx.Component:
    """Render chart chrome and behavior API tables.

    Returns:
        Generated chrome and behavior reference.
    """
    return callable_api_group(*CHROME_AND_BEHAVIOR, namespace="fc")


__all__ = [
    "AXES_AND_ANNOTATIONS",
    "CHROME_AND_BEHAVIOR",
    "MARKS",
    "axes_and_annotations_api",
    "chart_containers_api",
    "chrome_and_behavior_api",
    "marks_api",
]
