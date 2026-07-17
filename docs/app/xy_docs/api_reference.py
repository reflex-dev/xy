"""Generated API-reference sections for XY's public component factories."""

import reflex as rx
from reflex_site_shared.components.docs_api import (
    callable_api_group,
    callable_api_reference,
)

import xy

CHART_FACTORY_GROUPS = (
    (
        "Line and Area",
        (xy.line_chart, xy.area_chart, xy.step_chart, xy.stairs_chart),
    ),
    ("Scatter", (xy.scatter_chart,)),
    ("Bar and Column", (xy.bar_chart, xy.column_chart)),
    (
        "Distributions",
        (
            xy.histogram_chart,
            xy.ecdf_chart,
            xy.box_chart,
            xy.violin_chart,
        ),
    ),
    (
        "Density and Grids",
        (xy.hexbin_chart, xy.heatmap_chart, xy.contour_chart),
    ),
    ("Uncertainty", (xy.error_band_chart, xy.errorbar_chart)),
    (
        "Specialized",
        (xy.stem_chart, xy.segments_chart, xy.triangle_mesh_chart),
    ),
    ("Annotations", (xy.chart,)),
    ("Facets and Layers", (xy.chart, xy.facet_chart)),
)

MARKS = (
    xy.line,
    xy.scatter,
    xy.area,
    xy.bar,
    xy.column,
    xy.histogram,
    xy.box,
    xy.violin,
    xy.ecdf,
    xy.heatmap,
    xy.hexbin,
    xy.contour,
    xy.errorbar,
    xy.error_band,
    xy.step,
    xy.stairs,
    xy.stem,
    xy.segments,
    xy.triangle_mesh,
)

AXES_AND_ANNOTATIONS = (
    xy.x_axis,
    xy.y_axis,
    xy.vline,
    xy.hline,
    xy.x_band,
    xy.y_band,
    xy.threshold,
    xy.threshold_zone,
    xy.text,
    xy.label,
    xy.marker,
    xy.arrow,
    xy.callout,
)

CHROME_AND_BEHAVIOR = (
    xy.legend,
    xy.tooltip,
    xy.colorbar,
    xy.modebar,
    xy.theme,
    xy.interaction_config,
)


def chart_factories_api() -> rx.Component:
    """Render chart factories grouped like the Chart Gallery.

    Returns:
        Generated chart-factory reference.
    """
    return rx.box(
        *(
            rx.box(
                rx.heading(
                    group_name,
                    as_="h3",
                    size="5",
                    class_name="mb-2 mt-8 scroll-mt-24",
                ),
                callable_api_group(*factories, namespace="xy"),
                class_name="w-full",
            )
            for group_name, factories in CHART_FACTORY_GROUPS
        ),
        class_name="flex w-full flex-col",
    )


def chart_containers_api() -> rx.Component:
    """Render chart-container API tables.

    Returns:
        Generated chart-container reference.
    """
    return rx.box(
        callable_api_reference(
            xy.Chart.__init__,
            display_name="Shared chart props",
            exclude_parameters=("self", "kind"),
            parameter_descriptions={
                "children": "Marks, axes, annotations, and chart chrome.",
            },
        ),
        class_name="flex w-full flex-col",
    )


def marks_api() -> rx.Component:
    """Render mark API tables.

    Returns:
        Generated mark reference.
    """
    return callable_api_group(*MARKS, namespace="xy")


def axes_and_annotations_api() -> rx.Component:
    """Render axis and annotation API tables.

    Returns:
        Generated axis and annotation reference.
    """
    return callable_api_group(*AXES_AND_ANNOTATIONS, namespace="xy")


def chrome_and_behavior_api() -> rx.Component:
    """Render chart chrome and behavior API tables.

    Returns:
        Generated chrome and behavior reference.
    """
    return callable_api_group(*CHROME_AND_BEHAVIOR, namespace="xy")


__all__ = [
    "AXES_AND_ANNOTATIONS",
    "CHART_FACTORY_GROUPS",
    "CHROME_AND_BEHAVIOR",
    "MARKS",
    "axes_and_annotations_api",
    "chart_containers_api",
    "chart_factories_api",
    "chrome_and_behavior_api",
    "marks_api",
]
