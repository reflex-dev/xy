"""Presentation helpers for styling examples."""

from __future__ import annotations

import reflex as rx
from reflex_site_shared.components.blocks.demo import doccode

_EXAMPLES_LAYOUT_CSS = """
main:has(#xy-chart-examples) > div:has(#toc-navigation) {
  display: none;
}
main:has(#xy-chart-examples) > div:has(article #xy-chart-examples) {
  max-width: 88rem;
}
"""

_EXAMPLE_TAB_LIST_CLASS = (
    "xy-example-tab-list inline-flex !w-fit !gap-1 !rounded-xl !border-b-0 "
    "!bg-[#f5f5f5] !p-1 "
    "shadow-[0_1px_2px_#0000000f,0_4px_12px_#0000000a] "
    "before:!hidden after:!hidden dark:!bg-[#171717] "
    "dark:shadow-[0_1px_2px_#ffffff0d,0_4px_12px_#00000052]"
)

_EXAMPLE_TAB_CLASS = (
    "xy-example-tab cursor-pointer appearance-none !rounded-[0.625rem] !border "
    "!border-transparent !bg-transparent !px-4 !py-2.5 !text-[0.9375rem] "
    "!leading-5 !text-[#525252] !shadow-none "
    "transition-[color,background-color,box-shadow] duration-[120ms] "
    "before:!hidden after:!hidden dark:!text-[#a3a3a3] "
    "data-[state=active]:!border-[#e5e5e5] data-[state=active]:!bg-white "
    "data-[state=active]:!text-[#171717] "
    "data-[state=active]:!shadow-[0_1px_2px_#00000014] "
    "dark:data-[state=active]:!border-[#262626] "
    "dark:data-[state=active]:!bg-black "
    "dark:data-[state=active]:!text-[#fafafa] "
    "dark:data-[state=active]:!shadow-[0_1px_2px_#00000066] "
    "[&_.rt-BaseTabListTriggerInner]:!bg-transparent"
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
                    "font-medium text-secondary-11"
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


def chart_example_demo(
    code: str,
    preview: rx.Component,
    *,
    component_id: str | None = None,
) -> rx.Component:
    """Render a spacious chart demo with controls above its content surface."""
    return rx.tabs.root(
        rx.el.div(
            rx.tabs.list(
                rx.tabs.trigger(
                    rx.el.span(
                        rx.icon("eye", size=15, aria_hidden="true"),
                        rx.el.span("Preview"),
                        class_name="inline-flex items-center gap-2",
                    ),
                    value="preview",
                    class_name=_EXAMPLE_TAB_CLASS,
                ),
                rx.tabs.trigger(
                    rx.el.span(
                        rx.icon("code-xml", size=15, aria_hidden="true"),
                        rx.el.span("Code"),
                        class_name="inline-flex items-center gap-2",
                    ),
                    value="code",
                    class_name=_EXAMPLE_TAB_CLASS,
                ),
                class_name=_EXAMPLE_TAB_LIST_CLASS,
            ),
            class_name="mb-4 flex items-center justify-start",
        ),
        rx.tabs.content(
            rx.el.div(
                _chart_legend(component_id),
                rx.el.div(
                    preview,
                    class_name="flex w-full items-center overflow-hidden",
                ),
                class_name=(
                    "flex w-full flex-col gap-2 overflow-hidden rounded-xl border "
                    "border-secondary-4 bg-white dark:bg-black"
                ),
            ),
            value="preview",
            class_name="w-full outline-none",
        ),
        rx.tabs.content(
            rx.el.div(
                doccode(code),
                class_name=(
                    "min-h-[430px] w-full px-1 py-2 sm:px-2 "
                    "sm:py-7 [&>div]:!m-0 [&>div]:!rounded-none "
                    "[&>div]:!border-0 [&>div]:!bg-transparent "
                    "[&_.code-block]:!rounded-none [&_.code-block]:!border-0 "
                    "[&_.code-block]:!shadow-none"
                ),
            ),
            value="code",
            class_name="w-full outline-none",
        ),
        default_value="preview",
        id=component_id,
        class_name="mb-14 w-full",
    )


__all__ = ["chart_example_demo", "chart_examples_layout_marker"]
