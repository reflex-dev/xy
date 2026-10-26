"""Presentation helpers for styling examples."""

from __future__ import annotations

import reflex as rx
from reflex_site_shared.components.blocks.demo import _reflex_build_action

from xy_docs.code import doccode

_EXAMPLES_LAYOUT_CSS = """
main:has(#xy-chart-examples) > div:has(#toc-navigation) {
  display: none;
}
main:has(#xy-chart-examples) > div:has(article #xy-chart-examples) {
  max-width: 88rem;
}
"""

# Keep XY hooks for preview validation and use the shared docs pill treatment.
_EXAMPLE_TAB_LIST_CLASS = "xy-example-tab-list relative doc-demo-tab-list ml-auto flex items-center"


def _example_demo_header(*triggers: rx.Component) -> rx.Component:
    """Place the Build action and compact pill tabs above the preview card."""
    return rx.el.div(
        _reflex_build_action(),
        rx.tabs.list(*triggers, class_name=_EXAMPLE_TAB_LIST_CLASS),
        class_name=(
            "docs-demo-header flex w-full flex-wrap items-center justify-between gap-3 sm:flex-nowrap"
        ),
    )


_EXAMPLE_TAB_CLASS = (
    "xy-example-tab cursor-pointer doc-demo-tab inline-flex items-center "
    "rounded-full px-3 py-2 text-sm font-normal text-muted-foreground "
    "motion-reduce:transition-none [&_.rt-BaseTabListTriggerInner]:!bg-transparent"
)

_EXAMPLE_CARD_CLASS = (
    "doc-demo-tab-card relative w-full overflow-hidden rounded-[20px] border border-border bg-card"
)

_EXAMPLE_LEGENDS = {
    "layered-momentum-demo": (("This period", "#8e51ff", "solid"),),
    "solar-fleet-output-demo": (
        ("Solar panels", "#2b7fff", "solid"),
        ("Inverters", "#00bc7d", "solid"),
    ),
    "styling-overview-area-demo": (
        ("Solar panels", "#2b7fff", "solid"),
        ("Inverters", "#00bc7d", "solid"),
    ),
    "normalized-traffic-share-demo": (
        ("Desktop", "#8e51ff", "solid"),
        ("Mobile", "#00b8db", "solid"),
    ),
    "grouped-channel-mix-demo": (
        ("North America", "#2b7fff", "solid"),
        ("Europe", "#00bc7d", "solid"),
        ("Asia Pacific", "#8e51ff", "solid"),
        ("Latin America", "#fe9a00", "solid"),
        ("Middle East", "#6a7282", "solid"),
        ("Africa", "#00b8db", "solid"),
    ),
    "stacked-product-mix-demo": (
        ("Core", "#7c3aed", "solid"),
        ("Growth", "#db2777", "solid"),
        ("Enterprise", "#fb7185", "solid"),
    ),
    "conversion-by-stage-demo": (
        ("Workspace created", "#2b7fff", "solid"),
        ("Data connected", "#00bc7d", "solid"),
        ("First chart published", "#8e51ff", "solid"),
        ("Teammate invited", "#fe9a00", "solid"),
        ("Weekly habit formed", "#6a7282", "solid"),
    ),
    "monthly-balance-demo": (
        ("Gain", "#2b7fff", "solid"),
        ("Pullback", "#8e51ff", "solid"),
    ),
    "responsive-combo-chart-demo": (
        ("Solar panels", "#2b7fff", "bar"),
        ("Inverters", "#fe9a00", "solid"),
    ),
    "product-constellation-demo": (
        ("Platform", "#2b7fff", "point"),
        ("Growth", "#00bc7d", "point"),
        ("Intelligence", "#8e51ff", "point"),
        ("Operations", "#fe9a00", "point"),
        ("Security", "#6a7282", "point"),
        ("Collaboration", "#00b8db", "point"),
    ),
    "release-velocity-demo": (
        ("Stable", "#8e51ff", "solid"),
        ("Preview", "#00b8db", "solid"),
    ),
}

_BAR_LEGEND_IDS = {
    "conversion-by-stage-demo",
    "grouped-channel-mix-demo",
    "monthly-balance-demo",
    "stacked-product-mix-demo",
}


def chart_examples_layout_marker() -> rx.Component:
    """Widen the examples article and remove the right-side TOC."""
    return rx.fragment(
        rx.el.style(_EXAMPLES_LAYOUT_CSS),
        rx.el.div(
            id="xy-chart-examples",
            aria_hidden="true",
            class_name="hidden",
        ),
    )


def _chart_legend(component_id: str | None) -> rx.Component:
    """Render the compact chart legend for an example."""
    items = _EXAMPLE_LEGENDS.get(component_id or "", ())
    if not items:
        return rx.fragment()

    uses_bar_swatches = component_id in _BAR_LEGEND_IDS
    return rx.el.div(
        *(
            rx.el.div(
                rx.el.span(
                    class_name=(
                        "h-3 w-3 shrink-0 rounded-[3px]"
                        if uses_bar_swatches or line_style == "bar"
                        else "h-3 w-3 shrink-0 rounded-full"
                        if line_style == "point"
                        else "h-0 w-4 shrink-0 rounded-full border-t-[3px]"
                    ),
                    style=(
                        {"background": color}
                        if uses_bar_swatches or line_style in {"bar", "point"}
                        else {"border_top_style": line_style, "border_color": color}
                    ),
                    aria_hidden="true",
                ),
                rx.el.span(label),
                class_name=(
                    "inline-flex items-center gap-2 whitespace-nowrap text-sm "
                    "font-medium text-muted-foreground"
                ),
            )
            for label, color, line_style in items
        ),
        class_name=(
            "flex min-h-8 w-full flex-wrap items-center justify-end gap-x-5 gap-y-2 "
            "px-4 pt-4 sm:px-5 sm:pt-5"
        ),
        aria_label="Chart legend",
    )


def _example_tab_trigger(value: str, icon: str, label: str) -> rx.Component:
    """Render one pill tab in the demo header."""
    return rx.tabs.trigger(
        rx.el.span(
            rx.icon(icon, size=15, aria_hidden="true"),
            rx.el.span(label),
            class_name="inline-flex items-center gap-2",
        ),
        value=value,
        class_name=_EXAMPLE_TAB_CLASS,
    )


def _example_code_panel(source: str, value: str) -> rx.Component:
    """A code/data tab panel that sits on the card's own surface.

    ``doccode`` wraps long snippets in a ``bg-muted`` expand container with
    its own code-block fill and a matching fade gradient behind the Expand
    toggle. Strip every one of those backgrounds to transparent and recolor the
    fade to the card so the code reads on the same surface as the Preview tab.
    """
    panel_layout = (
        "w-full p-2" if value == "code" else "min-h-[430px] w-full px-1 py-2 sm:px-2 sm:py-7"
    )
    return rx.tabs.content(
        rx.el.div(
            doccode(source),
            class_name=(
                f"{panel_layout} "
                "[&>div]:!m-0 [&>div]:!rounded-none [&>div]:!border-0 "
                "[&_div]:!bg-transparent [&_pre]:!bg-transparent "
                "[&_.code-block]:!bg-transparent [&_.code-block]:!rounded-none "
                "[&_.code-block]:!border-0 [&_.code-block]:!shadow-none "
                "[&_summary]:!from-muted"
            ),
        ),
        value=value,
        class_name="w-full outline-none",
    )


def chart_example_demo(
    code: str,
    preview: rx.Component,
    *,
    component_id: str | None = None,
    data: str | None = None,
) -> rx.Component:
    """Render a chart demo with compact Preview/Code/Data pill tabs.

    When ``data`` is supplied (the hardcoded arrays split out of the fence, see
    ``markdown._split_demo_data``) a third "Data" tab appears so the Code tab can
    stay focused on the chart itself.
    """
    triggers = [
        _example_tab_trigger("preview", "eye", "Preview"),
        _example_tab_trigger("code", "code-xml", "Code"),
    ]
    if data:
        triggers.append(_example_tab_trigger("data", "database", "Data"))

    panels = [
        rx.tabs.content(
            rx.el.div(
                _chart_legend(component_id),
                rx.el.div(
                    preview,
                    class_name="flex w-full items-center overflow-hidden",
                ),
                class_name="flex w-full flex-col gap-2 overflow-hidden px-2 pb-2 pt-4",
            ),
            value="preview",
            class_name="w-full outline-none",
        ),
        _example_code_panel(code, "code"),
    ]
    if data:
        panels.append(_example_code_panel(data, "data"))

    return rx.tabs.root(
        _example_demo_header(*triggers),
        rx.el.div(*panels, class_name=_EXAMPLE_CARD_CLASS),
        default_value="preview",
        id=component_id,
        class_name="mb-14 flex w-full flex-col",
    )


__all__ = ["chart_example_demo", "chart_examples_layout_marker"]
