---
title: Configuration
description: Configure chart-local defaults, interactions, themes, and output behavior.
---

# Configuration

XY's declarative chart API keeps configuration local to a chart. It has no
public mutable global-settings object: compose configuration components or pass
props where the behavior is used. This keeps notebooks, exports, and multiple
charts in one process from changing one another implicitly. The separate
`xy.pyplot` compatibility API retains Matplotlib-style mutable settings.

## Configuration stays local

The same data can use defaults in one chart and a chart-local theme,
interaction policy, axes, and layout in another:

~~~python demo exec
import xy

traffic = {
    "hour": list(range(8, 20)),
    "requests": [28, 35, 42, 39, 56, 63, 59, 71, 68, 74, 82, 77],
}

default_chart = xy.line_chart(
    xy.line(x="hour", y="requests"),
    data=traffic,
    title="Defaults",
)

configured_chart = xy.area_chart(
    xy.area(
        x="hour",
        y="requests",
        color="#8b5cf6",
        opacity=0.28,
        line_width=2,
    ),
    xy.scatter(x="hour", y="requests", color="#c4b5fd", size=7),
    xy.x_axis(label="hour", domain=(7.5, 19.5), tick_count=6),
    xy.y_axis(label="requests / min", domain=(20, 90), tick_count=5),
    xy.tooltip(fields=["hour", "requests"]),
    xy.interaction_config(
        hover=True,
        crosshair=True,
        select=True,
        brush=True,
        default_drag_action="select",
    ),
    xy.theme(
        background="#111827",
        plot_background="#0f172a",
        grid_color="#334155",
        axis_color="#64748b",
        text_color="#e2e8f0",
        crosshair_color="#22d3ee",
    ),
    data=traffic,
    title="Configured locally",
    width="100%",
    height=320,
    padding=(20, 20, 36, 52),
)


def chart_configuration_demo():
    import reflex as rx
    import reflex_xy

    return rx.el.div(
        reflex_xy.chart(default_chart, height="320px"),
        reflex_xy.chart(configured_chart, height="320px"),
        class_name="flex w-full flex-col gap-4",
    )
~~~

The second chart's dark theme, fixed domains, crosshair, and drag-to-select
behavior do not change the first chart.

| Surface | Configure with | Scope |
| --- | --- | --- |
| Dimensions and layout | `width`, `height`, `padding`, `title` | One chart |
| Data default | `data=` on the chart | Marks without their own `data=` |
| Scales and ticks | `x_axis()`, `y_axis()` | One named axis |
| Browser behavior | `interaction_config()` or chart flags | One chart |
| Theme tokens | `theme()` and chart `style=` | One chart and descendants |
| DOM chrome | `class_names=` and `styles=` | Stable slots in one chart |
| Rendered marks | Mark props and mark `style=` | One mark |
| Export defaults | `export_config()` | One chart |
| Export override | `to_image()`, `write_image()` arguments | One export call |

Chart dimensions default to 900×420 pixels. `width="100%"` fills the parent;
`height="100%"` also needs a parent with a defined height. Fixed dimensions
are preferable for deterministic static output and facet layouts.

## Configure export defaults

`export_config()` describes download and Python-export defaults without writing
a file at chart construction time. Hover the chart, then open its Export menu
to see the configured PNG, SVG, and CSV options:

~~~python demo exec
import xy
from xy import Engine

days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
signups = [320, 460, 510, 620, 780, 690, 540]

export_chart = xy.column_chart(
    xy.column(days, signups, color="#6e56cf"),
    xy.x_axis(label="day"),
    xy.y_axis(label="signups", domain=(0, 900)),
    xy.export_config(
        formats=["png", "svg", "csv"],
        filename="weekly-signups",
        width=1200,
        height=630,
        scale=1,
        background="#f8fafc",
    ),
    xy.modebar(show=True),
    title="Weekly signups",
)


def export_with_browser_css(path="weekly-signups-browser.png"):
    export_chart.write_image(
        path,
        engine=Engine.chromium,
        custom_css=".xy { font-family: Inter, sans-serif; }",
    )


def output_defaults_demo():
    import reflex_xy

    return reflex_xy.chart(export_chart, height="360px")
~~~

`export_with_browser_css()` is a per-call override for cases that require
browser fonts, author CSS, or WebGL screenshot fidelity. Ordinary
`export_chart.write_image("weekly-signups.png")` remains browser-free, uses the
native engine, and inherits the chart's configured dimensions and background.

Set the `XY_BROWSER` environment variable to a Chrome/Chromium/Edge executable
when browser discovery should not use the platform defaults. `custom_css` is
valid for standalone HTML and Chromium-backed PNG, JPEG, WebP, and PDF exports.
SVG is native-only.

## Engine thresholds are policy, not public configuration

Automatic decimation, density, sampling, and pyramid constants live in an
internal engine module so the Python kernel and interaction paths agree. They
are observable through tier metadata and described in
[Large data and performance](/docs/xy/core-concepts/large-data-and-performance/),
but importing or monkey-patching those constants is not a supported global
configuration API. The thresholds may change as the alpha is tuned.

Use [Themes and tokens](/docs/xy/styling/themes-and-tokens/) for reusable visual
defaults and host-framework state for application-wide reactive settings.
