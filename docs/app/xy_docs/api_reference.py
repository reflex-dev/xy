"""Generated API-reference sections for XY's public component factories."""

import inspect
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

import reflex as rx
import reflex_xy
from reflex_site_shared.components.docs_api import (
    callable_api_group,
    callable_api_reference,
    docs_api_cell,
    docs_api_row,
    docs_api_table,
)

import xy

COMPONENT_API_METADATA_KEY = "components"
API_REFERENCE_HEADING = "API Reference"
_COMPONENT_API_NAMESPACES = {
    "reflex_xy": reflex_xy,
    "xy": xy,
}
_COMPONENT_API_COLUMN_WIDTHS = ("w-[20%]", "w-[25%]", "w-[55%]")
_NON_ID_CHARACTER = re.compile(r"[^a-z0-9]+")

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
_CHART_FACTORY_COMPONENTS = frozenset(
    factory for _group_name, factories in CHART_FACTORY_GROUPS for factory in factories
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
    xy.animation,
    xy.spring,
)


@dataclass(frozen=True, slots=True)
class ComponentApiParameter:
    """One generated callable parameter shared by HTML and Markdown output."""

    name: str
    type_name: str
    description: str


@dataclass(frozen=True, slots=True)
class ComponentApiReference:
    """Inspected public callable shared by all documentation renderers."""

    display_name: str
    summary: str
    parameters: tuple[ComponentApiParameter, ...]
    component: Callable[..., Any]


def _format_annotation(annotation: Any) -> str:
    """Format an inspected annotation like the shared Reflex docs API table."""
    if annotation is inspect.Parameter.empty:
        return "Any"
    if isinstance(annotation, str):
        return annotation.replace("typing.", "")
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def _format_default(default: Any) -> str | None:
    """Format a stable, compact default value for generated documentation."""
    if callable(default):
        return getattr(default, "__name__", type(default).__name__)
    value = repr(default)
    if " object at 0x" in value:
        return None
    return value if len(value) <= 80 else f"{value[:77]}..."


def _parameter_descriptions(docstring: str) -> dict[str, str]:
    """Extract Google-style argument descriptions from a callable docstring."""
    descriptions: dict[str, str] = {}
    current: str | None = None
    in_args = False
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped in {"Args:", "Arguments:", "Parameters:"}:
            in_args = True
            current = None
            continue
        if not in_args:
            continue
        if stripped and not line.startswith((" ", "\t")):
            break
        if not stripped:
            continue
        if ":" in stripped and not stripped.startswith(":"):
            name, description = stripped.split(":", 1)
            name = name.split("(", 1)[0].strip().lstrip("*")
            if name.isidentifier():
                current = name
                descriptions[current] = description.strip()
                continue
        if current is not None:
            descriptions[current] = f"{descriptions[current]} {stripped}".strip()
    return descriptions


def _summary(docstring: str) -> str:
    """Return the opening paragraph of a callable docstring."""
    return docstring.strip().split("\n\n", 1)[0].replace("\n", " ")


def _parameter_description(
    parameter: inspect.Parameter,
    descriptions: Mapping[str, str],
) -> str:
    """Return explicit or generated prose for one callable parameter."""
    if description := descriptions.get(parameter.name):
        return description
    is_required = parameter.default is inspect.Parameter.empty
    default = None if is_required else _format_default(parameter.default)
    if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
        return "Additional positional arguments."
    if parameter.kind is inspect.Parameter.VAR_KEYWORD:
        return "Additional keyword arguments."
    if is_required:
        return "Required."
    if default is None:
        return "Optional."
    return f"Defaults to {default}."


def _documented_parameters(
    component: Callable[..., Any],
    descriptions: Mapping[str, str],
) -> tuple[tuple[inspect.Parameter, Mapping[str, str]], ...]:
    """Expand chart-factory ``**props`` into the shared Chart constructor API."""
    parameters = tuple(inspect.signature(component).parameters.values())
    if component not in _CHART_FACTORY_COMPONENTS:
        return tuple((parameter, descriptions) for parameter in parameters)

    shared_descriptions = _parameter_descriptions(inspect.getdoc(xy.Chart.__init__) or "")
    merged_descriptions = {**shared_descriptions, **descriptions}
    existing_names = {
        parameter.name
        for parameter in parameters
        if parameter.kind is not inspect.Parameter.VAR_KEYWORD
    }
    shared_parameters = tuple(
        parameter
        for parameter in inspect.signature(xy.Chart).parameters.values()
        if parameter.name not in {"kind", "children", *existing_names}
    )

    documented: list[tuple[inspect.Parameter, Mapping[str, str]]] = []
    for parameter in parameters:
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            documented.extend(
                (shared_parameter, merged_descriptions) for shared_parameter in shared_parameters
            )
            continue
        documented.append((parameter, merged_descriptions))
    return tuple(documented)


def component_api_paths(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    """Read and validate the shape of a page's component API frontmatter.

    Args:
        metadata: Parsed Markdown frontmatter mapping.

    Returns:
        Declared component paths, or an empty tuple.

    Raises:
        TypeError: If ``components`` is not a list of strings.
        ValueError: If a path is duplicated or outside a supported namespace.
    """
    value = metadata.get(COMPONENT_API_METADATA_KEY)
    if value is None:
        return ()
    if not isinstance(value, list):
        msg = "Documentation frontmatter 'components' must be a list"
        raise TypeError(msg)

    paths: list[str] = []
    seen: set[str] = set()
    for component_path in value:
        if not isinstance(component_path, str):
            msg = "Documentation component paths must be strings"
            raise TypeError(msg)
        if component_path in seen:
            msg = f"Duplicate documentation component path: {component_path!r}"
            raise ValueError(msg)
        seen.add(component_path)
        namespace, separator, public_name = component_path.partition(".")
        if (
            namespace not in _COMPONENT_API_NAMESPACES
            or not separator
            or not public_name
            or "." in public_name
        ):
            msg = f"Invalid documentation component path: {component_path!r}"
            raise ValueError(msg)
        paths.append(component_path)
    return tuple(paths)


@cache
def _component_api_references(
    component_paths: tuple[str, ...],
) -> tuple[ComponentApiReference, ...]:
    """Resolve and inspect a validated tuple once for every docs compilation."""
    references: list[ComponentApiReference] = []
    for component_path in component_paths:
        namespace, _, public_name = component_path.partition(".")
        module = _COMPONENT_API_NAMESPACES[namespace]
        if public_name not in getattr(module, "__all__", ()):
            msg = f"Non-public documentation component: {component_path!r}"
            raise ValueError(msg)
        component = getattr(module, public_name, None)
        if not callable(component):
            msg = f"Unknown documentation component: {component_path!r}"
            raise ValueError(msg)

        docstring = inspect.getdoc(component) or ""
        descriptions = _parameter_descriptions(docstring)
        parameters: list[ComponentApiParameter] = []
        for parameter, parameter_descriptions in _documented_parameters(
            component,
            descriptions,
        ):
            prefix = (
                "**"
                if parameter.kind is inspect.Parameter.VAR_KEYWORD
                else "*"
                if parameter.kind is inspect.Parameter.VAR_POSITIONAL
                else ""
            )
            parameters.append(
                ComponentApiParameter(
                    name=f"{prefix}{parameter.name}",
                    type_name=_format_annotation(parameter.annotation),
                    description=_parameter_description(
                        parameter,
                        parameter_descriptions,
                    ),
                )
            )
        references.append(
            ComponentApiReference(
                display_name=component_path,
                summary=_summary(docstring) if docstring else "",
                parameters=tuple(parameters),
                component=component,
            )
        )
    return tuple(references)


def component_api_references(
    component_paths: Sequence[str],
) -> tuple[ComponentApiReference, ...]:
    """Resolve public callables into their shared documentation metadata.

    Args:
        component_paths: Validated public component paths.

    Returns:
        Cached callable metadata in declaration order.

    Raises:
        ValueError: If a component is not exported or callable.
    """
    return _component_api_references(tuple(component_paths))


def component_api_callables(
    component_paths: Sequence[str],
) -> tuple[Callable[..., Any], ...]:
    """Return resolved public callables from the cached metadata model."""
    return tuple(reference.component for reference in component_api_references(component_paths))


def _heading_id(name: str) -> str:
    """Convert a display name to the Reflex API table's fragment identifier."""
    return _NON_ID_CHARACTER.sub("-", name.lower()).strip("-")


def _component_api_reference(reference: ComponentApiReference) -> rx.Component:
    """Render one shared metadata entry with Reflex's standard API styling."""
    rows = tuple(
        docs_api_row(
            docs_api_cell(
                rx.code(
                    parameter.name,
                    class_name="code-style text-nowrap leading-normal",
                ),
                _COMPONENT_API_COLUMN_WIDTHS[0],
            ),
            docs_api_cell(
                rx.code(
                    parameter.type_name,
                    color_scheme="gray",
                    variant="soft",
                    class_name=("code-style leading-normal whitespace-normal break-words"),
                ),
                _COMPONENT_API_COLUMN_WIDTHS[1],
            ),
            docs_api_cell(
                rx.text(
                    parameter.description,
                    class_name=(
                        "font-small text-secondary-11 whitespace-normal leading-snug break-words"
                    ),
                ),
                _COMPONENT_API_COLUMN_WIDTHS[2],
            ),
        )
        for parameter in reference.parameters
    )
    return rx.box(
        rx.heading(
            reference.display_name,
            as_="h3",
            id=_heading_id(reference.display_name),
            class_name="font-large text-secondary-12 mt-8 mb-2",
        ),
        (
            rx.text(
                reference.summary,
                class_name="font-[475] text-secondary-11 mb-4 leading-7",
            )
            if reference.summary
            else rx.fragment()
        ),
        rx.heading(
            "Props",
            as_="h4",
            class_name="font-base text-secondary-12 mt-4 mb-2",
        ),
        docs_api_table(*rows),
        class_name="w-full",
    )


def component_page_api(
    references: Sequence[ComponentApiReference],
) -> rx.Component:
    """Render non-interactive API tables for one component guide.

    Args:
        references: Shared callable metadata declared by the guide.

    Returns:
        Generated callable documentation in declaration order.
    """
    return rx.box(
        *(_component_api_reference(reference) for reference in references),
        class_name="flex w-full flex-col",
    )


def _markdown_cell(value: str) -> str:
    """Escape generated text for one GitHub-Flavored Markdown table cell."""
    return " ".join(value.split()).replace("|", r"\|")


def component_api_markdown(
    references: Sequence[ComponentApiReference],
) -> str:
    """Serialize the same API metadata used by the Reflex component tables."""
    if not references:
        return ""
    lines = [f"## {API_REFERENCE_HEADING}", ""]
    for reference in references:
        lines.extend((f"### {reference.display_name}", ""))
        if reference.summary:
            lines.extend((reference.summary, ""))
        lines.extend(
            (
                "#### Props",
                "",
                "| Prop | Type | Description |",
                "| --- | --- | --- |",
            )
        )
        lines.extend(
            f"| {_markdown_cell(f'`{parameter.name}`')} "
            f"| {_markdown_cell(f'`{parameter.type_name}`')} "
            f"| {_markdown_cell(parameter.description)} |"
            for parameter in reference.parameters
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_FAQ_HEADING = re.compile(r"^## FAQ\s*$", re.MULTILINE)


def split_faq_section(content: str) -> tuple[str, str | None]:
    """Split authored Markdown at its FAQ heading.

    The generated API Reference is inserted between the body and the FAQ, so
    the FAQ stays the final section on every surface (HTML page, per-page
    Markdown, and llms-full.txt).
    """
    match = _FAQ_HEADING.search(content)
    if match is None:
        return content, None
    return content[: match.start()], content[match.start() :]


def append_component_api_markdown(
    content: str,
    metadata: Mapping[str, Any],
) -> str:
    """Insert a generated Markdown API section when frontmatter declares one.

    The section lands after the authored body but before any FAQ, matching the
    rendered page order.
    """
    paths = component_api_paths(metadata)
    if not paths:
        return content
    section = component_api_markdown(component_api_references(paths))
    body, faq = split_faq_section(content)
    if faq is None:
        return f"{content.rstrip()}\n\n{section}"
    return f"{body.rstrip()}\n\n{section.rstrip()}\n\n{faq.strip()}\n"


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
    "API_REFERENCE_HEADING",
    "AXES_AND_ANNOTATIONS",
    "CHART_FACTORY_GROUPS",
    "CHROME_AND_BEHAVIOR",
    "COMPONENT_API_METADATA_KEY",
    "MARKS",
    "ComponentApiParameter",
    "ComponentApiReference",
    "append_component_api_markdown",
    "axes_and_annotations_api",
    "chart_containers_api",
    "chart_factories_api",
    "chrome_and_behavior_api",
    "component_api_callables",
    "component_api_markdown",
    "component_api_paths",
    "component_api_references",
    "component_page_api",
    "marks_api",
]
