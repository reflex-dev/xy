---
title: Components
description: Compose marks, axes, annotations, legends, tooltips, colorbars, and controls.
---

# Components

Components are lightweight Python specifications passed to a chart container.
They describe data geometry, coordinate systems, annotations, and browser
chrome; they do not render independently.

~~~python
import xy

chart = xy.line_chart(
    xy.line([0, 1, 2, 3], [2, 5, 3, 8], name="observed"),
    xy.x_axis(label="sample"),
    xy.y_axis(label="value"),
    xy.hline(6, text="target"),
    xy.legend(title="Series"),
    xy.tooltip(fields=["x", "y"]),
)
~~~

The child order controls mark layering. Chrome components of the same kind use
the last declaration as their effective configuration.

| Component guide | What it controls |
| --- | --- |
| [Marks](/docs/xy/components/marks/) | Data geometry, channels, layering, and shared mark behavior |
| [Axes](/docs/xy/components/axes/) | Scales, domains, ticks, labels, and named axes |
| [Legends](/docs/xy/components/legends/) | Named-series keys and framework replacements |
| [Tooltips](/docs/xy/components/tooltips/) | Hover fields, titles, formatting, and replacements |
| [Colorbars](/docs/xy/components/colorbars/) | Inferred continuous scales, orientation, ticks, slots, and custom replacements |
| [Modebars and interaction controls](/docs/xy/components/modebars-and-interaction-controls/) | Pan, zoom, selection, export controls, and linked viewports |
| [Annotations](/docs/xy/components/annotations/) | Rules, bands, text, markers, arrows, thresholds, and callouts |

These pages explain how to use the components. Exact signatures and defaults
live in [Marks and components reference](/docs/xy/api-reference/marks-and-components/).
