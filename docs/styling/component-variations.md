---
title: Component Variations
description: Style legends, tooltips, axes, reference lines, annotations, and interaction chrome.
---

# Component Variations

Styling is split by what the renderer owns. Built-in chart chrome is browser
DOM, axes combine canvas geometry with DOM labels, and annotations combine
painted shapes with DOM labels. Custom framework components are a separate
integration boundary.

## Choose a component task

| I want to style... | Continue with |
| --- | --- |
| A built-in legend or tooltip | [Built-in legend and tooltip](#built-in-legend-and-tooltip) |
| Axes, secondary axes, rules, or bands | [Axes and reference lines or bands](#axes-and-reference-lines-or-bands) |
| Labels, markers, arrows, and callouts | [Annotation variants](#annotation-variants) |
| Crosshairs or selection feedback | [Crosshair and selection](#crosshair-and-selection) |
| A host-owned legend, tooltip, or color scale | [Custom component replacements](#custom-component-replacements) |
| Reduction badges or facet wrappers | [Conditional badges and facet wrappers](#conditional-badges-and-facet-wrappers) |

The key boundary is ownership: built-in chrome can be restyled through XY
slots, while a genuinely custom Reflex component must be rendered and updated
by the host application.

## Coverage matrix

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

legend_tooltip_chart = xy.line_chart(
    xy.line(
        x="month",
        y="actual",
        data=data,
        name="Actual",
        style={"stroke": "#6e56cf", "stroke-width": 2.5},
    ),
    xy.line(
        x="month",
        y="plan",
        data=data,
        name="Plan",
        style={
            "stroke": "#0ea5e9",
            "stroke-width": 2,
            "stroke-dasharray": "6px 4px",
        },
    ),
    xy.scatter(
        x="month",
        y="actual",
        data=data,
        name="Observed",
        size=8,
        style={"fill": "#ffffff", "stroke": "#6e56cf", "stroke-width": 2},
    ),
    xy.legend(
        loc="upper left",
        ncols=3,
        title="Revenue",
        style={
            "background": "var(--legend-bg, rgb(255 255 255 / 92%))",
            "color": "var(--legend-text, #0f172a)",
            "border": "1px solid var(--legend-border, #e2e8f0)",
            "border-radius": 10,
            "box-shadow": "0 8px 24px rgb(15 23 42 / 10%)",
        },
    ),
    xy.tooltip(
        fields=["month", "actual", "plan"],
        title="Month {month}",
        format={"actual": ",.0f", "plan": ",.0f"},
        style={
            "background": "rgb(24 24 27 / 94%)",
            "color": "#f8fafc",
            "border-radius": 8,
            "padding": "8px 10px",
        },
    ),
    xy.x_axis(label="month", tick_count=6),
    xy.y_axis(label="revenue", format=",.0f"),
    styles={
        "legend_item": {"gap": 6, "padding": "3px 5px"},
        "legend_swatch": {"border-radius": 3},
    },
    class_name=(
        "[--legend-bg:#fffffff0] [--legend-text:#0f172a] "
        "[--legend-border:#e2e8f0] dark:[--legend-bg:#27272af0] "
        "dark:[--legend-text:#e2e8f0] dark:[--legend-border:#475569]"
    ),
)


def legend_tooltip_styling_preview():
    return reflex_xy.chart(legend_tooltip_chart, height="380px")
~~~

The tooltip can only display values resident in the browser payload. Fields
used by x, y, color, size, or heatmap value channels are resident; naming an
otherwise-unused source column in `fields` does not ship it automatically.

## Axes and reference lines or bands

This example covers bottom and top x axes, left and right y axes, independently
styled named scales, both reference-line directions, and both band directions.
Annotation geometry uses explicit props, while its text box uses normal DOM
styles.

~~~python demo exec
import reflex_xy
import xy

x = [0, 1, 2, 3, 4, 5, 6]
latency = [82, 76, 71, 68, 64, 61, 58]
errors = [1.4, 1.7, 1.3, 2.1, 1.8, 1.2, 0.9]

reference_chart = xy.chart(
    xy.line(
        x,
        latency,
        name="Latency",
        style={"stroke": "#2563eb", "stroke-width": 2.5},
    ),
    xy.line(
        x,
        errors,
        y_axis="y2",
        name="Errors",
        style={"stroke": "#e11d48", "stroke-width": 2},
    ),
    xy.line(
        [10, 20, 30, 40, 50, 60, 70],
        [78, 74, 72, 69, 66, 63, 60],
        x_axis="x2",
        name="Load-index projection",
        style={
            "stroke": "#7c3aed",
            "stroke-width": 1.8,
            "stroke-dasharray": "5px 4px",
        },
    ),
    xy.x_band(
        3.3,
        4.3,
        text="deploy window",
        color="#f59e0b",
        opacity=0.12,
        style={
            "label_color": "var(--warning-label, #92400e)",
            "background": "var(--warning-bg, #fffbeb)",
            "padding": "2px 5px",
        },
    ),
    xy.y_band(
        72,
        77,
        text="watch band",
        color="#0d9488",
        opacity=0.10,
        style={
            "label_color": "var(--teal-label, #115e59)",
            "background": "var(--teal-bg, #f0fdfa)",
            "padding": "2px 5px",
        },
    ),
    xy.vline(
        2,
        text="release",
        color="#d97706",
        width=2,
        style={
            "label_color": "var(--warning-label, #92400e)",
            "background": "var(--warning-bg, #fffbeb)",
            "border": "1px solid var(--warning-border, #fde68a)",
            "border-radius": 5,
            "padding": "2px 5px",
        },
    ),
    xy.hline(
        65,
        text="SLO",
        color="#16a34a",
        width=2,
        style={
            "label_color": "var(--success-label, #166534)",
            "background": "var(--success-bg, #f0fdf4)",
            "border-radius": 5,
            "padding": "2px 5px",
        },
    ),
    xy.x_axis(
        label="release",
        style={
            "grid_color": "var(--axes-grid, rgb(148 163 184 / 20%))",
            "grid_dash": "dotted",
            "axis_color": "var(--axes-neutral, #475569)",
            "tick_color": "var(--axes-neutral, #475569)",
            "tick_direction": "out",
            "tick_length": 6,
        },
    ),
    xy.x_axis(
        id="x2",
        side="top",
        label="load index",
        domain=(10, 70),
        tick_count=4,
        style={
            "axis_color": "var(--axes-purple, #7c3aed)",
            "tick_color": "var(--axes-purple, #7c3aed)",
            "tick_label_color": "var(--axes-purple, #6d28d9)",
            "label_color": "var(--axes-purple, #6d28d9)",
        },
    ),
    xy.y_axis(
        label="latency (ms)",
        style={
            "label_color": "var(--axes-blue, #1d4ed8)",
            "tick_label_color": "var(--axes-blue, #1d4ed8)",
        },
    ),
    xy.y_axis(
        id="y2",
        side="right",
        label="errors (%)",
        domain=(0, 3),
        format=".1f",
        style={
            "axis_color": "var(--axes-red, #be123c)",
            "tick_color": "var(--axes-red, #be123c)",
            "tick_label_color": "var(--axes-red, #be123c)",
            "label_color": "var(--axes-red, #be123c)",
        },
    ),
    xy.legend(loc="upper right"),
    xy.theme(
        plot_background="var(--axes-bg, #ffffff)",
        text_color="var(--axes-text, #334155)",
        grid_color="var(--axes-grid, rgb(148 163 184 / 20%))",
        axis_color="var(--axes-neutral, #64748b)",
    ),
    class_name=(
        "[--axes-bg:#ffffff] [--axes-text:#334155] [--axes-grid:#94a3b833] "
        "[--axes-neutral:#475569] [--axes-purple:#6d28d9] "
        "[--axes-blue:#1d4ed8] [--axes-red:#be123c] "
        "[--warning-label:#92400e] [--warning-bg:#fffbeb] "
        "[--warning-border:#fde68a] [--teal-label:#115e59] "
        "[--teal-bg:#f0fdfa] [--success-label:#166534] "
        "[--success-bg:#f0fdf4] dark:[--axes-bg:#18181b] "
        "dark:[--axes-text:#e2e8f0] dark:[--axes-grid:#e2e8f01f] "
        "dark:[--axes-neutral:#94a3b8] dark:[--axes-purple:#c4b5fd] "
        "dark:[--axes-blue:#93c5fd] dark:[--axes-red:#fda4af] "
        "dark:[--warning-label:#fde68a] dark:[--warning-bg:#451a03] "
        "dark:[--warning-border:#92400e] dark:[--teal-label:#99f6e4] "
        "dark:[--teal-bg:#134e4a] dark:[--success-label:#bbf7d0] "
        "dark:[--success-bg:#14532d]"
    ),
    style={"background": "var(--axes-bg, #ffffff)"},
    title="Axes and reference geometry",
)


def axis_reference_styling_preview():
    return reflex_xy.chart(reference_chart, height="430px")
~~~

## Annotation variants

Every annotation splits into up to two styling layers: its canvas-painted
geometry and its DOM label. This example exercises the positioned text alias,
marker, arrow, semantic threshold, semantic threshold zone, and callout. The
preceding example covers the underlying rule and band primitives directly.
Geometry `opacity` does not fade label text; set `label_opacity` in the
annotation style when that label should also be translucent.

~~~python demo exec
import reflex_xy
import xy

annotation_chart = xy.line_chart(
    xy.line(
        [0, 1, 2, 3, 4, 5],
        [3, 5, 4, 7, 6, 9],
        style={"stroke": "#94a3b8", "stroke-width": 1.5},
    ),
    xy.text(
        0,
        3,
        "text",
        dx=0,
        dy=-14,
        anchor="middle",
        color="var(--chart-text)",
        class_name="font-medium",
    ),
    xy.label(
        1,
        5,
        "label alias",
        dx=0,
        dy=-16,
        anchor="middle",
        color="var(--purple-label, #7c3aed)",
        style={
            "background": "var(--purple-bg, #f5f3ff)",
            "padding": "2px 5px",
        },
    ),
    xy.marker(
        2,
        4,
        text="marker",
        symbol="diamond",
        size=11,
        color="#0ea5e9",
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
        color="#e11d48",
        width=2,
        style={
            "label_color": "var(--rose-label, #9f1239)",
            "background": "var(--rose-bg, #fff1f2)",
            "border-radius": 4,
            "padding": "1px 4px",
            "font_weight": 600,
        },
    ),
    xy.threshold(
        8,
        axis="y",
        text="threshold",
        color="#ea580c",
        width=2,
        style={
            "label_color": "var(--orange-label, #9a3412)",
            "background": "var(--orange-bg, #fff7ed)",
            "padding": "2px 5px",
        },
    ),
    xy.threshold_zone(
        3.5,
        4.5,
        axis="x",
        text="threshold zone",
        color="#14b8a6",
        opacity=0.12,
        style={
            "label_color": "var(--teal-label, #115e59)",
            "background": "var(--teal-bg, #f0fdfa)",
            "border": "1px solid var(--teal-border, #99f6e4)",
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
        color="#6e56cf",
        width=2,
        style={
            "label_color": "var(--purple-label, #6b21a8)",
            "background": "var(--purple-bg, #faf5ff)",
            "border": "1px solid var(--purple-border, #d8b4fe)",
            "border-radius": 6,
            "padding": "3px 6px",
        },
    ),
    xy.x_axis(domain=(-0.35, 5.35)),
    xy.y_axis(domain=(2, 10)),
    styles={"annotation_label": {"line_height": 1.2}},
    class_name=(
        "[--purple-label:#6b21a8] [--purple-bg:#faf5ff] "
        "[--purple-border:#d8b4fe] [--rose-label:#9f1239] "
        "[--rose-bg:#fff1f2] [--orange-label:#9a3412] "
        "[--orange-bg:#fff7ed] [--teal-label:#115e59] "
        "[--teal-bg:#f0fdfa] [--teal-border:#99f6e4] "
        "dark:[--purple-label:#e9d5ff] dark:[--purple-bg:#3b0764] "
        "dark:[--purple-border:#7e22ce] dark:[--rose-label:#fecdd3] "
        "dark:[--rose-bg:#4c0519] dark:[--orange-label:#fed7aa] "
        "dark:[--orange-bg:#431407] dark:[--teal-label:#99f6e4] "
        "dark:[--teal-bg:#134e4a] dark:[--teal-border:#0f766e]"
    ),
    padding=[48, 88, 52, 88],
    title="Annotation styling layers",
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
        style={"fill": "#7c3aed", "stroke": "#ffffff", "stroke-width": 1.5},
    ),
    xy.interaction_config(crosshair=True, select=True, brush=True),
    xy.modebar(
        class_name=(
            "rounded-lg border border-slate-200 bg-white/95 shadow-md "
            "dark:border-zinc-700 dark:bg-zinc-900/95"
        ),
        button_class_name=(
            "rounded-md hover:bg-violet-50 focus:ring-2 focus:ring-violet-500 "
            "dark:hover:bg-violet-950"
        ),
        style={"padding": 4},
        button_style={"color": "var(--chart-text)"},
    ),
    xy.theme(
        crosshair_color="#e11d48",
        selection_color="#7c3aed",
        selection_fill="rgb(124 58 237 / 16%)",
    ),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    styles={
        "crosshair_x": {"width": 2},
        "crosshair_y": {"height": 2},
        "selection": {"border-radius": 6},
    },
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
                    class_name="text-xs text-slate-500 dark:text-slate-400",
                ),
                rx.text(
                    InteractionChromeState.selected_count,
                    class_name=(
                        "text-2xl font-semibold text-violet-700 dark:text-violet-300"
                    ),
                ),
                align="start",
            ),
            rx.vstack(
                rx.text(
                    "Dataset share",
                    class_name="text-xs text-slate-500 dark:text-slate-400",
                ),
                rx.text(
                    InteractionChromeState.selected_share,
                    class_name=(
                        "text-2xl font-semibold text-violet-700 dark:text-violet-300"
                    ),
                ),
                align="start",
            ),
            rx.vstack(
                rx.text(
                    "Selection",
                    class_name="text-xs text-slate-500 dark:text-slate-400",
                ),
                rx.text(
                    InteractionChromeState.selection_shape,
                    class_name=(
                        "text-sm font-semibold text-slate-800 dark:text-slate-100"
                    ),
                ),
                rx.text(
                    InteractionChromeState.selection_region,
                    class_name="text-xs text-slate-500 dark:text-slate-400",
                ),
                align="start",
            ),
            width="100%",
            justify="between",
            align="start",
            class_name=(
                "rounded-lg border border-slate-200 bg-white p-4 "
                "dark:border-zinc-700 dark:bg-zinc-950"
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
   above. This works in the shipped browser client, Reflex adapter, standalone
   HTML, and Chromium export.
2. **Replace chrome with a framework component.** The built-in
   `reflex_xy.chart` adapter does not render components passed through
   `legend(render=...)`, `tooltip(render=...)`, or `colorbar(render=...)`.
   Standalone exports cannot include framework-owned components either.

For a framework-owned legend with the shipped Reflex adapter, compose it next
to the chart and hide XY's built-in legend:

~~~python demo exec
import reflex as rx
import reflex_xy
import xy

custom_legend_chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [2, 5, 3, 7], color="#6e56cf"),
    xy.line([0, 1, 2, 3], [1, 3, 4, 6], color="#0ea5e9"),
    xy.legend(show=False),
    title="Framework-owned legend",
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
            legend_key("#6e56cf", "Actual"),
            legend_key("#0ea5e9", "Plan"),
            spacing="4",
        ),
        width="100%",
        align="center",
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
