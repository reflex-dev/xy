---
title: Component Variations
description: Style legends, tooltips, annotations, interaction feedback, and host-owned chart chrome.
---

# Component Variations

Styling is split by what the renderer owns. Built-in chart chrome is browser
DOM, axes combine canvas geometry with DOM labels, and annotations combine
painted shapes with DOM labels. Custom framework components are a separate
integration boundary. The sections below cover legend and tooltip chrome,
annotation variants, selection feedback, host-owned replacements, and
conditional wrappers. For axis paint and tick styling, continue to
[Customize Each Part](/docs/xy/styling/customize/#axes,-grid,-and-ticks).

## Choose a component task

| I want to style... | Continue with |
| --- | --- |
| A built-in legend or tooltip | [Built-in legend and tooltip](#built-in-legend-and-tooltip) |
| Labels, markers, arrows, and callouts | [Annotation variants](#annotation-variants) |
| Crosshairs or selection feedback | [Crosshair and selection](#crosshair-and-selection) |
| A host-owned legend, tooltip, or color scale | [Custom component replacements](#custom-component-replacements) |
| Reduction badges or facet wrappers | [Conditional badges and facet wrappers](#conditional-badges-and-facet-wrappers) |

The key boundary is ownership: built-in chrome can be restyled through XY
slots, while a genuinely custom Reflex component must be rendered and updated
by the host application.

## Component styling reference

Use this table to choose the API that configures each surface and the hook that
styles it.

| Surface | Configure content or behavior | Style it |
| --- | --- | --- |
| Built-in legend | `legend(loc=..., ncols=..., title=...)` | `legend(class_name=..., style=...)`; `legend`, `legend_item`, and `legend_swatch` slots |
| Built-in tooltip | `tooltip(fields=..., title=..., format=...)` | `tooltip(class_name=..., style=...)` or the `tooltip` slot |
| Colorbar chrome | `colorbar(title=..., orientation=..., ticks=...)` on a supported continuous mark | `colorbar`, `colorbar_bar`, `colorbar_tick`, and `colorbar_title` slots |
| X and Y axes | `x_axis(...)`, `y_axis(...)`, including named secondary axes | Validated axis `style`; `tick_label` and `axis_title` DOM slots |
| Reference lines | `vline(x)` and `hline(y)` | Geometry through `color`, `width`, and `opacity`; label through `class_name` and `style` |
| Reference bands | `x_band(...)`, `y_band(...)`, and `threshold_zone(...)` | Geometry through `color` and `opacity`; label through `class_name` and `style` |
| Labels and callouts | `text`, `label`, `marker`, `arrow`, and `callout` | Shape props plus the `annotation_label` slot or per-annotation class/style |
| Crosshair and selection | `interaction_config(crosshair=True, select=True, brush=True)` | Theme tokens or `crosshair_x`, `crosshair_y`, and `selection` slots |
| Modebar | `modebar(show=...)` | `modebar` and `modebar_button` slots or component-local class/style |
| Chart frame | Chart `class_name`, `class_names`, `style`, and `styles` | `root`, `title`, `chrome`, `canvas`, and `labels` slots |
| Reduction badges | Emitted automatically when XY reduces, samples, or rasterizes data | `badge` and `badge_item` slots plus badge theme tokens |
| Facets | `facet_chart(..., gap=...)` and the shared child chart styles | Per-panel chart slots; standalone grid selectors are `.xy-facet-grid`, `.xy-facet-panel`, and `.xy-facet-title` |
| Data marks | Mark factories such as `line`, `scatter`, and `bar` | The validated mark `style` subset, not DOM classes |

`vline` is the vertical **x reference line** and `hline` is the horizontal
**y reference line**. XY does not expose separate `x_line` or `y_line` names.

## Built-in legend and tooltip

Hover a point to see the formatted tooltip. The legend container, rows,
swatches, and tooltip use independent styling surfaces.

~~~python demo exec
import reflex_xy
import xy

data = {
    "month": [1, 2, 3, 4, 5, 6],
    "actual": [42_000, 47_000, 45_000, 53_000, 58_000, 64_000],
    "plan": [40_000, 44_000, 48_000, 52_000, 56_000, 60_000],
}

legend_tooltip_chart = xy.area_chart(
    xy.area(
        x="month",
        y="actual",
        data=data,
        name="Actual",
        color="#2b7fff",
        fill="linear-gradient(#2b7fff4d 5%, #2b7fff00 95%)",
        line_width=2,
        curve="smooth",
    ),
    xy.area(
        x="month",
        y="plan",
        data=data,
        name="Plan",
        color="#00bc7d",
        fill="linear-gradient(#00bc7d4d 5%, #00bc7d00 95%)",
        line_width=2,
        curve="smooth",
    ),
    xy.legend(
        loc="upper right",
        ncols=2,
        style={
            "background": "var(--legend-bg, #fffffff0)",
            "color": "var(--legend-text, #1d293d)",
            "border": "1px solid var(--legend-border, #e5e7eb)",
            "border-radius": 8,
            "box-shadow": "0 4px 12px #11182714",
        },
    ),
    xy.tooltip(
        fields=["month", "actual", "plan"],
        title="Month {month}",
        format={"actual": ",.0f", "plan": ",.0f"},
        style={
            "background": "#18181ff0",
            "color": "#f9fafb",
            "border": "1px solid #3f3f46",
            "border-radius": 8,
            "padding": "8px 10px",
            "box-shadow": "0 8px 24px #00000029",
        },
    ),
    xy.x_axis(
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.y_axis(
        format=",.0f",
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.theme(
        plot_background="var(--demo-surface, #ffffff)",
        grid_color="var(--demo-grid, #e5e7eb)",
        axis_color="var(--demo-axis, #d1d5db)",
        text_color="var(--demo-text, #6a7282)",
    ),
    styles={
        "legend_item": {"gap": 6, "padding": "3px 5px"},
        "legend_swatch": {"border-radius": 3},
    },
    class_name=(
        "bg-[#ffffff] py-4 sm:py-5 [--demo-surface:#ffffff] [--demo-grid:#e5e7eb] "
        "[--demo-axis:#d1d5db] [--demo-text:#6a7282] [--legend-bg:#fffffff0] "
        "[--legend-text:#1d293d] [--legend-border:#e5e7eb] dark:bg-[#000000] "
        "dark:[--demo-surface:#000000] dark:[--demo-grid:#27272a] "
        "dark:[--demo-axis:#3f3f46] dark:[--demo-text:#99a1af] "
        "dark:[--legend-bg:#18181ff0] dark:[--legend-text:#f3f4f6] "
        "dark:[--legend-border:#3f3f46]"
    ),
)


def legend_tooltip_styling_preview():
    return reflex_xy.chart(legend_tooltip_chart, height="380px")
~~~

The tooltip can only display values resident in the browser payload. Fields
used by x, y, color, size, or heatmap value channels are resident; naming an
otherwise-unused source column in `fields` does not ship it automatically.

## Annotation variants

Every annotation splits into up to two styling layers: its canvas-painted
geometry and its DOM label. The chart below shows positioned text, a marker,
an arrow, a threshold, a threshold zone, and a callout.
Geometry `opacity` does not fade label text; set `label_opacity` in the
annotation style when that label should also be translucent.

~~~python demo exec
import reflex_xy
import xy

annotation_chart = xy.line_chart(
    xy.line(
        [0, 1, 2, 3, 4, 5],
        [3, 5, 4, 7, 6, 9],
        style={"stroke": "#6a7282", "stroke-width": 2},
    ),
    xy.text(
        0,
        3,
        "text",
        dx=0,
        dy=-14,
        anchor="middle",
        color="var(--demo-text, #6a7282)",
        class_name="font-medium",
    ),
    xy.label(
        1,
        5,
        "label alias",
        dx=0,
        dy=-16,
        anchor="middle",
        color="#8e51ff",
        style={
            "background": "var(--violet-soft, #8e51ff1a)",
            "padding": "2px 5px",
        },
    ),
    xy.marker(
        2,
        4,
        text="marker",
        symbol="diamond",
        size=11,
        color="#00b8db",
        stroke_color="#ffffff",
        stroke_width=2,
        dx=0,
        dy=20,
        anchor="middle",
    ),
    xy.arrow(
        2.2,
        5.0,
        3,
        7,
        text="arrow",
        color="#2b7fff",
        width=2,
        style={
            "label_color": "#2b7fff",
            "background": "var(--blue-soft, #2b7fff1a)",
            "border-radius": 4,
            "padding": "1px 4px",
            "font_weight": 600,
        },
    ),
    xy.threshold(
        8,
        axis="y",
        text="threshold",
        color="#fe9a00",
        width=2,
        style={
            "label_color": "#fe9a00",
            "background": "var(--amber-soft, #fe9a001a)",
            "padding": "2px 5px",
        },
    ),
    xy.threshold_zone(
        3.5,
        4.5,
        axis="x",
        text="threshold zone",
        color="#00bc7d",
        opacity=0.12,
        style={
            "label_color": "#00bc7d",
            "background": "var(--emerald-soft, #00bc7d1a)",
            "border": "1px solid #00bc7d66",
            "border-radius": 4,
            "padding": "1px 4px",
        },
    ),
    xy.callout(
        5,
        9,
        "callout",
        dx=-18,
        dy=-28,
        anchor="end",
        color="#8e51ff",
        width=2,
        style={
            "label_color": "#8e51ff",
            "background": "var(--violet-soft, #8e51ff1a)",
            "border": "1px solid #8e51ff66",
            "border-radius": 6,
            "padding": "3px 6px",
        },
    ),
    xy.x_axis(
        domain=(-0.35, 5.35),
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.y_axis(
        domain=(2, 10),
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.theme(
        plot_background="var(--demo-surface, #ffffff)",
        grid_color="var(--demo-grid, #e5e7eb)",
        axis_color="var(--demo-axis, #d1d5db)",
        text_color="var(--demo-text, #6a7282)",
    ),
    styles={
        "annotation_label": {"line_height": 1.2},
    },
    class_name=(
        "bg-[#ffffff] [--demo-surface:#ffffff] [--demo-grid:#e5e7eb] "
        "[--demo-axis:#d1d5db] [--demo-text:#6a7282] [--blue-soft:#2b7fff1a] "
        "[--emerald-soft:#00bc7d1a] [--violet-soft:#8e51ff1a] "
        "[--amber-soft:#fe9a001a] dark:bg-[#000000] "
        "dark:[--demo-surface:#000000] dark:[--demo-grid:#27272a] "
        "dark:[--demo-axis:#3f3f46] dark:[--demo-text:#99a1af]"
    ),
    padding=[36, 72, 36, 72],
)


def annotation_variants_styling_preview():
    return reflex_xy.chart(annotation_chart, height="400px")
~~~

`label(...)` is a semantic alias of `text(...)`; it does not create a separate
DOM slot. `threshold(...)` resolves to `vline` or `hline`, and
`threshold_zone(...)` resolves to `x_band` or `y_band`, according to `axis`.
The alias names are useful for intent, while the renderer and styling contract
stay identical to the underlying primitive.

## Crosshair and selection

Move across the plot to show the crosshair. Shift-drag to reveal the styled
selection rectangle.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

interaction_chart = xy.scatter_chart(
    xy.scatter(
        [0, 1, 2, 3, 4, 5, 6, 7],
        [2, 5, 3, 7, 6, 9, 8, 11],
        size=10,
        style={"fill": "#00b8db", "stroke": "#ffffff", "stroke-width": 1.5},
    ),
    xy.interaction_config(crosshair=True, select=True, brush=True),
    xy.modebar(
        class_name=(
            "rounded-lg border border-[#e5e7eb] bg-[#fffffff2] shadow-md "
            "dark:border-[#3f3f46] dark:bg-[#18181ff2]"
        ),
        button_class_name=(
            "rounded-md hover:bg-[#8e51ff1a] focus:ring-2 focus:ring-[#8e51ff]"
        ),
        style={"padding": 4},
        button_style={"color": "var(--chart-text)"},
    ),
    xy.theme(
        plot_background="var(--demo-surface, #ffffff)",
        grid_color="var(--demo-grid, #e5e7eb)",
        axis_color="var(--demo-axis, #d1d5db)",
        text_color="var(--demo-text, #6a7282)",
        crosshair_color="#2b7fff",
        selection_color="#8e51ff",
        selection_fill="#8e51ff29",
    ),
    xy.x_axis(
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.y_axis(
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    styles={
        "crosshair_x": {"width": 2},
        "crosshair_y": {"height": 2},
        "selection": {"border-radius": 6},
    },
    class_name=(
        "bg-[#ffffff] [--demo-surface:#ffffff] [--demo-grid:#e5e7eb] "
        "[--demo-axis:#d1d5db] [--demo-text:#6a7282] dark:bg-[#000000] "
        "dark:[--demo-surface:#000000] dark:[--demo-grid:#27272a] "
        "dark:[--demo-axis:#3f3f46] dark:[--demo-text:#99a1af]"
    ),
)

interaction_token = reflex_xy.inline(interaction_chart)


class InteractionChromeState(rx.State):
    selected_count: int = 0
    selected_share: str = "0%"
    selection_shape: str = "None"
    selection_region: str = "Draw a box or lasso around a cohort."

    @rx.event
    def record_selection(self, selection: dict):
        total = int(selection.get("total") or 0)
        if selection.get("cleared"):
            self.selected_count = 0
            self.selected_share = "0%"
            self.selection_shape = "None"
            self.selection_region = "Selection cleared."
            return

        self.selected_count = total
        self.selected_share = f"{100 * total / 8:.0f}%"
        polygon = selection.get("polygon")
        if polygon:
            self.selection_shape = "Lasso"
            self.selection_region = f"Free-form region with {len(polygon)} vertices"
        else:
            self.selection_shape = "Box / range"
            bounds = [selection.get(key) for key in ("x0", "x1", "y0", "y1")]
            if all(isinstance(value, (int, float)) for value in bounds):
                x0, x1, y0, y1 = bounds
                self.selection_region = f"x: {x0:.1f}–{x1:.1f}; y: {y0:.1f}–{y1:.1f}"
            else:
                self.selection_region = "Selected chart region"


def interaction_chrome_styling_preview():
    return rx.vstack(
        reflex_xy.chart(
            interaction_token,
            on_select_end=InteractionChromeState.record_selection,
            height="360px",
        ),
        rx.hstack(
            rx.vstack(
                rx.text(
                    "Selected",
                    class_name="text-xs text-[#6a7282] dark:text-[#99a1af]",
                ),
                rx.text(
                    InteractionChromeState.selected_count,
                    class_name="text-2xl font-semibold text-[#8e51ff]",
                ),
                align="start",
            ),
            rx.vstack(
                rx.text(
                    "Dataset share",
                    class_name="text-xs text-[#6a7282] dark:text-[#99a1af]",
                ),
                rx.text(
                    InteractionChromeState.selected_share,
                    class_name="text-2xl font-semibold text-[#8e51ff]",
                ),
                align="start",
            ),
            rx.vstack(
                rx.text(
                    "Selection",
                    class_name="text-xs text-[#6a7282] dark:text-[#99a1af]",
                ),
                rx.text(
                    InteractionChromeState.selection_shape,
                    class_name=("text-sm font-semibold text-[#1d293d] dark:text-[#f3f4f6]"),
                ),
                rx.text(
                    InteractionChromeState.selection_region,
                    class_name="text-xs text-[#6a7282] dark:text-[#99a1af]",
                ),
                align="start",
            ),
            width="100%",
            justify="between",
            align="start",
            class_name=(
                "border-t border-[#e5e7eb] bg-[#ffffff] px-1 pt-3 "
                "dark:border-[#27272a] dark:bg-[#000000]"
            ),
        ),
        width="100%",
        align="stretch",
    )
~~~

The component-local modebar props merge into the same `modebar` and
`modebar_button` slots as chart-level `class_names` / `styles`. Open the
selection menu to choose box, lasso, X-range, or Y-range selection; Shift-drag
remains a shortcut for box selection. The analysis panel turns the compact
`on_select_end` summary into a selected count, dataset share, selection type,
and region readout. A production dashboard can use the same event to update
filters, aggregate cards, or related views.

## Custom component replacements

There are two different meanings of “custom”:

1. **Restyle built-in chrome.** Use the component and slot APIs demonstrated
   above. This works in browser and Reflex charts, standalone HTML, and
   Chromium export.
2. **Replace chrome with a framework component.** The built-in
   `reflex_xy.chart` adapter does not render components passed through
   `legend(render=...)`, `tooltip(render=...)`, or `colorbar(render=...)`.
   Standalone exports cannot include framework-owned components either.

For a framework-owned legend in Reflex, compose it next to the chart and hide
XY's built-in legend:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

custom_legend_chart = xy.line_chart(
    xy.line(
        [0, 1, 2, 3],
        [2, 5, 3, 7],
        name="Actual",
        color="#2b7fff",
        width=2,
        curve="smooth",
    ),
    xy.line(
        [0, 1, 2, 3],
        [1, 3, 4, 6],
        name="Plan",
        color="#00bc7d",
        width=2,
        curve="smooth",
    ),
    xy.legend(show=False),
    xy.x_axis(
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.y_axis(
        tick_label_strategy="none",
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        },
    ),
    xy.theme(
        plot_background="var(--custom-surface, #ffffff)",
        grid_color="var(--custom-grid, #e5e7eb)",
        axis_color="var(--custom-axis, #d1d5db)",
        text_color="var(--custom-text, #6a7282)",
    ),
    class_name=(
        "bg-[#ffffff] [--custom-surface:#ffffff] [--custom-grid:#e5e7eb] "
        "[--custom-axis:#d1d5db] [--custom-text:#6a7282] dark:bg-[#000000] "
        "dark:[--custom-surface:#000000] dark:[--custom-grid:#27272a] "
        "dark:[--custom-axis:#3f3f46] dark:[--custom-text:#99a1af]"
    ),
)


def legend_key(color: str, label: str) -> rx.Component:
    return rx.hstack(
        rx.box(width="0.75rem", height="0.75rem", border_radius="3px", bg=color),
        rx.text(label, size="2"),
        align="center",
        spacing="2",
    )


def custom_reflex_legend_preview():
    return rx.vstack(
        reflex_xy.chart(custom_legend_chart, height="300px"),
        rx.hstack(
            legend_key("#2b7fff", "Actual"),
            legend_key("#00bc7d", "Plan"),
            spacing="4",
        ),
        width="100%",
        align="center",
        class_name="py-4 sm:py-5",
    )
~~~

A truly custom hover tooltip needs host state: handle Reflex
`on_point_hover`, render your own component from the received row, and disable
the built-in tooltip with `tooltip(show=False)`. See the
[Reflex integration](/docs/xy/integrations/reflex/#events-and-streaming) for
the state-backed event contract.

## Conditional badges and facet wrappers

Reduction badges are not author-created children. They appear only when the
selected representation reports reduction, sampling, or density metadata, so
small examples commonly have no `badge` element to style. Configure both the
container and item slots up front when a dashboard may cross that threshold:

~~~python
chart = xy.scatter_chart(
    xy.scatter(x, y),
    class_names={"badge": "gap-1", "badge_item": "font-mono text-[10px]"},
    styles={"badge_item": {"border": "1px solid rgb(148 163 184 / 35%)"}},
)
~~~

`facet_chart` repeats the same child chart contract in every panel, so mark,
axis, annotation, legend, tooltip, theme, and chart-slot styling are shared by
default. Its standalone HTML wrapper additionally emits `.xy-facet-grid`,
`.xy-facet-panel`, and `.xy-facet-title`; target those through `custom_css`
when styling the layout around panels. These selectors belong to the facet
wrapper rather than a chart slot, so do not put them in `class_names` or
`styles`.
