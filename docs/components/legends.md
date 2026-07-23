---
title: Legends in Python
description: Label named series and configure built-in or framework-rendered legends.
components:
  - xy.legend
---

# Legends in Python

Marks with a `name=` participate in the chart legend. Add `legend()` to control
the built-in legend's placement, columns, title, visibility, and DOM styling.

~~~python demo exec
import reflex_xy
import xy

legend_intro_chart = xy.line_chart(
    xy.line([1, 2, 3], [4, 7, 6], name="Actual"),
    xy.line([1, 2, 3], [3, 5, 7], name="Plan"),
    xy.legend(
        loc="upper right",
        ncols=2,
        title="Series",
        class_name="rounded-lg shadow-sm",
    ),
)


def legend_intro_demo():
    return reflex_xy.chart(legend_intro_chart, height="320px")
~~~

The legend is available by default when the chart contains named series.
Use `show=False` to suppress it. If more than one legend component is present,
the last one supplies the effective built-in configuration.

## Basic Legend from Named Series

Giving each mark a `name=` is all it takes — a bare `xy.legend()` simply opts
into the default placement for the named series.

~~~python demo exec
import reflex_xy
import xy

basic_legend_chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4], [12, 15, 14, 18, 21], name="North", color="#6e56cf"),
    xy.line([0, 1, 2, 3, 4], [9, 11, 13, 12, 16], name="South", color="#2563eb"),
    xy.legend(),
    xy.x_axis(label="quarter"),
    xy.y_axis(label="sales"),
    title="Regional sales",
)


def basic_legend_demo():
    return reflex_xy.chart(basic_legend_chart, height="320px")
~~~

## Position and Title the Legend

`loc=` moves the legend to a corner such as `"upper left"`, and `title=` adds a
heading above the entries.

~~~python demo exec
import reflex_xy
import xy

positioned_legend_chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4], [3, 6, 5, 9, 12], name="Alpha", color="#6e56cf"),
    xy.line([0, 1, 2, 3, 4], [2, 4, 7, 8, 10], name="Beta", color="#2563eb"),
    xy.line([0, 1, 2, 3, 4], [1, 3, 2, 5, 7], name="Gamma", color="#16a34a"),
    xy.legend(loc="upper left", title="Release train"),
    xy.x_axis(label="sprint"),
    xy.y_axis(label="features shipped"),
    title="Positioned, titled legend",
)


def positioned_legend_demo():
    return reflex_xy.chart(positioned_legend_chart, height="320px")
~~~

## Multi-Column Layout and Unnamed Series

With many series, `ncols=2` lays the entries out in two columns; the dashed
baseline mark has no `name=`, so it stays out of the legend entirely.

~~~python demo exec
import reflex_xy
import xy

multi_column_legend_chart = xy.line_chart(
    xy.line([0, 1, 2, 3, 4, 5], [10, 12, 15, 14, 18, 22], name="us-east", color="#6e56cf"),
    xy.line([0, 1, 2, 3, 4, 5], [8, 9, 12, 13, 15, 17], name="us-west", color="#2563eb"),
    xy.line([0, 1, 2, 3, 4, 5], [6, 8, 7, 10, 12, 14], name="eu-central", color="#16a34a"),
    xy.line([0, 1, 2, 3, 4, 5], [4, 5, 7, 8, 9, 11], name="ap-south", color="#f59e0b"),
    xy.line([0, 1, 2, 3, 4, 5], [7, 7, 7, 7, 7, 7], color="#94a3b8", dash="dashed", width=1.0),
    xy.legend(ncols=2, title="Regions", loc="upper left"),
    xy.x_axis(label="hour"),
    xy.y_axis(label="requests/s"),
    title="Two-column legend",
)


def multi_column_legend_demo():
    return reflex_xy.chart(multi_column_legend_chart, height="320px")
~~~

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
