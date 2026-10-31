from __future__ import annotations

from dataclasses import dataclass

EXPERIMENTAL_PUBLIC_EXPORTS: tuple[str, ...] = ()
DEPRECATED_PUBLIC_EXPORTS: tuple[str, ...] = ()
PRIVATE_PUBLIC_EXPORTS: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublicApiInventory:
    """Machine-readable inventory of the supported public composition API."""

    component_reexports: tuple[str, ...]
    component_types: tuple[str, ...]
    mark_factories: tuple[str, ...]
    annotation_factories: tuple[str, ...]
    axis_factories: tuple[str, ...]
    chrome_factories: tuple[str, ...]
    chart_factories: tuple[str, ...]
    support_factories: tuple[str, ...]
    chart_methods: tuple[str, ...]
    selection_methods: tuple[str, ...]
    facet_chart_methods: tuple[str, ...] = ()
    experimental_exports: tuple[str, ...] = EXPERIMENTAL_PUBLIC_EXPORTS
    deprecated_exports: tuple[str, ...] = DEPRECATED_PUBLIC_EXPORTS
    private_exports: tuple[str, ...] = PRIVATE_PUBLIC_EXPORTS
    chart_factory_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def component_factories(self) -> tuple[str, ...]:
        return (
            *self.mark_factories,
            *self.annotation_factories,
            *self.axis_factories,
            *self.chrome_factories,
            *self.chart_factories,
            *self.support_factories,
        )

    @property
    def declarative_exports(self) -> tuple[str, ...]:
        return (
            *self.component_types,
            *self.component_factories,
        )

    @property
    def classified_component_exports(self) -> tuple[str, ...]:
        return (
            *self.component_reexports,
            *self.declarative_exports,
            *self.experimental_exports,
            *self.deprecated_exports,
            *self.private_exports,
        )


PUBLIC_API_MANIFEST = PublicApiInventory(
    component_reexports=("CHART_DOM_SLOTS", "structural_probe"),
    component_types=(
        "Animation",
        "Annotation",
        "Axis",
        "Chart",
        "Colorbar",
        "Component",
        "ExportConfig",
        "FacetChart",
        "Interaction",
        "Legend",
        "Mark",
        "Modebar",
        "Spring",
        "Theme",
        "Tooltip",
    ),
    mark_factories=(
        "area",
        "bar",
        "box",
        "column",
        "contour",
        "ecdf",
        "error_band",
        "errorbar",
        "funnel",
        "heatmap",
        "hexbin",
        "hist",
        "histogram",
        "line",
        "mark",
        "ribbon",
        "sankey",
        "scatter",
        "segments",
        "stairs",
        "stem",
        "step",
        "triangle_mesh",
        "violin",
    ),
    annotation_factories=(
        "arrow",
        "callout",
        "hline",
        "label",
        "marker",
        "text",
        "threshold",
        "threshold_zone",
        "vline",
        "x_band",
        "y_band",
    ),
    axis_factories=("r_axis", "theta_axis", "x_axis", "y_axis"),
    chrome_factories=("colorbar", "interaction_config", "legend", "modebar", "theme", "tooltip"),
    chart_factories=(
        "area_chart",
        "bar_chart",
        "box_chart",
        "chart",
        "column_chart",
        "contour_chart",
        "ecdf_chart",
        "error_band_chart",
        "errorbar_chart",
        "funnel_chart",
        "heatmap_chart",
        "hexbin_chart",
        "histogram_chart",
        "line_chart",
        "pie_chart",
        "polar_bar_chart",
        "polar_chart",
        "radar_chart",
        "sankey_chart",
        "scatter_chart",
        "segments_chart",
        "stairs_chart",
        "stem_chart",
        "step_chart",
        "triangle_mesh_chart",
        "violin_chart",
        "wind_rose",
    ),
    chart_factory_groups=(
        ("Line and Area", ("line_chart", "area_chart", "step_chart", "stairs_chart")),
        ("Scatter", ("scatter_chart",)),
        ("Polar", ("polar_chart", "radar_chart", "polar_bar_chart", "pie_chart", "wind_rose")),
        ("Bar and Column", ("bar_chart", "column_chart")),
        ("Distributions", ("histogram_chart", "ecdf_chart", "box_chart", "violin_chart")),
        ("Density and Grids", ("hexbin_chart", "heatmap_chart", "contour_chart")),
        ("Uncertainty", ("error_band_chart", "errorbar_chart")),
        (
            "Specialized",
            ("stem_chart", "segments_chart", "sankey_chart", "funnel_chart", "triangle_mesh_chart"),
        ),
        ("Annotations", ("chart",)),
        ("Facets and Layers", ("chart", "facet_chart")),
    ),
    support_factories=("animation", "export_config", "facet_chart", "spring"),
    chart_methods=(
        "figure",
        "chrome_components",
        "reflex_components",
        "widget",
        "show",
        "set_view",
        "reset_view",
        "select",
        "clear_selection",
        "view_state",
        "to_html",
        "html",
        "_repr_html_",
        "to_svg",
        "to_png",
        "to_image",
        "write_image",
        "memory_report",
        "append",
        "pick",
        "select_range",
    ),
    selection_methods=("index", "__len__", "xy", "rows"),
    facet_chart_methods=(
        "figure",
        "widget",
        "show",
        "to_html",
        "html",
        "_repr_html_",
        "to_svg",
        "to_png",
        "to_image",
        "write_image",
        "memory_report",
    ),
)
