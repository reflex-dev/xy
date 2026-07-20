---
title: Configuration
description: Configure chart-local defaults, interactions, themes, and output behavior.
---

# Configuration

XY configuration is declarative and local to a chart. There is currently no
public mutable global-settings object: compose configuration components or pass
props where the behavior is used. This keeps notebooks, exports, and multiple
charts in one process from changing one another implicitly.

## Configure one chart

~~~python demo exec
import xy

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4]),
    xy.x_axis(label="sample", tick_count=5),
    xy.y_axis(label="value", domain=(0, 6)),
    xy.interaction_config(hover=True, crosshair=True, select=True),
    xy.theme(
        plot_background="#ffffff",
        grid_color="#e2e8f0",
        axis_color="#64748b",
        text_color="#1e293b",
    ),
    width="100%",
    height=420,
)


def chart_configuration_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="420px")
~~~

| Surface | Configure with | Scope |
| --- | --- | --- |
| Dimensions and layout | `width`, `height`, `padding`, `title` | One chart |
| Data default | `data=` on the chart | Marks without their own `data=` |
| Scales and ticks | `x_axis()`, `y_axis()` | One named axis |
| Browser behavior | `interaction_config()` or chart flags | One chart |
| Theme tokens | `theme()` and chart `style=` | One chart and descendants |
| DOM chrome | `class_names=` and `styles=` | Stable slots in one chart |
| Rendered marks | Mark props and mark `style=` | One mark |
| Static output | `to_png()`, `to_svg()`, `to_html()` arguments | One export call |

Chart dimensions default to 900×420 pixels. `width="100%"` fills the parent;
`height="100%"` also needs a parent with a defined height. Fixed dimensions
are preferable for deterministic static output and facet layouts.

## Output defaults

`chart.to_png()` uses XY's browser-free native engine by default. Choose the
Chromium engine when browser fonts, author CSS, or WebGL screenshot fidelity is
required:

~~~python demo exec
import xy
from xy import Engine

chart = xy.line_chart(
    xy.line([1, 2, 3, 4], [2, 5, 3, 7], color="#6e56cf"),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
)


def export_chart(path="chart.png"):
    chart.to_png(
        path,
        engine=Engine.chromium,
        custom_css=".xy { font-family: Inter, sans-serif; }",
    )


def output_defaults_demo():
    import reflex_xy

    return reflex_xy.chart(chart, height="360px")
~~~

Set the `XY_BROWSER` environment variable to a Chrome/Chromium/Edge executable
when browser discovery should not use the platform defaults. `custom_css` is
valid for standalone HTML and Chromium PNG; native PNG intentionally accepts
only styles its renderer can honor.

## Engine thresholds are policy, not public configuration

Automatic decimation, density, sampling, and pyramid constants live in an
internal engine module so the Python kernel and interaction paths agree. They
are observable through tier metadata and described in
[Large data and performance](/docs/xy/core-concepts/large-data-and-performance/),
but importing or monkey-patching those constants is not a supported global
configuration API. The thresholds may change as the alpha is tuned.

Use [Themes and tokens](/docs/xy/styling/themes-and-tokens/) for reusable visual
defaults and host-framework state for application-wide reactive settings.
