---
title: Legends in Python
description: Label named series and configure built-in or framework-rendered legends.
components:
  - xy.legend
---

# Legends in Python

Marks with a `name=` participate in the chart legend. Add `legend()` to control
the built-in legend's placement, columns, title, visibility, and DOM styling.

~~~python
import xy

chart = xy.line_chart(
    xy.line([1, 2, 3], [4, 7, 6], name="Actual"),
    xy.line([1, 2, 3], [3, 5, 7], name="Plan"),
    xy.legend(
        loc="upper right",
        ncols=2,
        title="Series",
        class_name="rounded-lg shadow-sm",
    ),
)
~~~

The legend is available by default when the chart contains named series.
Use `show=False` to suppress it. If more than one legend component is present,
the last one supplies the effective built-in configuration.

## Style the Built-in Legend

`class_name` and `style` apply to the legend container. Chart-level
`class_names` and `styles` can separately target `legend`, `legend_item`, and
`legend_swatch` slots. Those are browser DOM hooks; native SVG and PNG use the
legend options and renderable style values carried in the chart specification.

See [Customize Each Part](/docs/xy/styling/customize/#legend) for the stable
legend-slot contract.

## Supply Framework Content

The positional child or `render=` value is an opaque replacement object for a
framework adapter:

~~~python
import reflex as rx
import xy

my_framework_legend = rx.hstack(
    rx.box(width="0.75rem", height="0.75rem", background="#6e56cf"),
    rx.text("Actual"),
    align="center",
    spacing="2",
)

chart = xy.line_chart(
    xy.line([1, 2, 3], [4, 7, 6], name="Actual"),
    xy.legend(render=my_framework_legend),
)

replacement = chart.chrome_components()["legend"]
assert replacement is my_framework_legend
~~~

Core XY neither imports nor serializes that object. The example is complete,
but it only demonstrates storage: the shipped `reflex_xy.chart` adapter does
not currently mount custom legend content. A custom adapter can read
`chrome_components()` and mount the returned component. Standalone HTML keeps
using safe built-in chrome, and the same object is also available through
`reflex_components()`.

Exact parameters and defaults are in
[Marks and components reference](/docs/xy/api-reference/marks-and-components/).

## FAQ

### How do I add a legend to a chart in Python?

Give each mark a `name=`, e.g. `xy.line(x, y, name="Actual")` — a chart with
named series shows the built-in legend by default. Add `xy.legend()` only when
you want to configure placement, columns, title, visibility, or styling.

### How do I change where the legend appears?

Pass `loc=` to `xy.legend()`, e.g. `xy.legend(loc="upper right")`. If more than
one `legend()` component is present, the last one supplies the effective
configuration.

### How do I arrange legend entries in multiple columns?

Set `ncols=` on the legend, e.g. `xy.legend(ncols=2, title="Series")`, which
lays the entries out in two columns under an optional legend title.

### How do I hide the legend or keep a series out of it?

Use `xy.legend(show=False)` to suppress the legend entirely. Only marks with a
`name=` participate in the legend, so omitting `name=` on a mark keeps that
series out.
