---
title: Mark Styles
description: Style WebGL, SVG, and native-raster marks with XY's validated CSS subset.
---

# Mark Styles

Data marks are not DOM nodes. XY accepts familiar CSS property names through a
mark's `style=` mapping, validates them, and compiles them into a renderer-neutral
trace style. Unsupported properties raise before data is ingested, so one
renderer cannot silently ignore a declaration that another honors.

## Supported CSS properties

| Mark family | Supported properties in `style=` |
| --- | --- |
| `line`, `step`, `stairs`, `ecdf` | `stroke`, `stroke-width`, `stroke-opacity`, `stroke-dasharray`, `opacity` |
| `area`, `error_band` | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `opacity`; `area` also supports `stroke-dasharray` |
| `scatter` | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `opacity` |
| `histogram`, `bar`, `column` | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `border-radius`, `opacity` |
| `segments`, `errorbar`, `contour`, `stem` | `stroke`, `stroke-width`, `stroke-opacity`, `opacity` |
| `box`, `violin` | `fill`, `fill-opacity`, `opacity` |
| `triangle_mesh` | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `opacity` |
| `heatmap`, `hexbin` | `fill-opacity`, `opacity` |

Use canonical CSS kebab-case when sharing styles with web code; Python
snake_case aliases remain accepted.

~~~python
import xy

line = xy.line(
    [0, 1, 2, 3],
    [2, 5, 3, 8],
    style={
        "stroke": "var(--accent)",
        "stroke-width": "2px",
        "stroke-opacity": 0.85,
        "stroke-dasharray": "6px 3px",
    },
)

bars = xy.column(
    ["A", "B", "C"],
    [4, 7, 5],
    style={
        "fill": "linear-gradient(to top, #2563eb, #93c5fd)",
        "stroke": "#1e3a8a",
        "stroke-width": "1px",
        "border-radius": "4px",
    },
)
~~~

Legacy appearance props such as `color=`, `width=`, and `opacity=` remain part
of each mark's API. A declaration in `style=` is the final override when both
surfaces set the same rendered property. Inside `style`, use `stroke` for
line-like geometry and `fill` for filled geometry; `color` is deliberately not
a CSS paint alias there.

## Combine mark styles

This example combines the main paint paths in one chart: a gradient area, a
dashed line, bordered diamond markers, and explicitly styled axes.

~~~python demo exec
import reflex_xy
import xy

x = [0, 1, 2, 3, 4, 5]
y = [2, 4, 3, 6, 5, 8]

styled_marks = xy.chart(
    xy.area(
        x,
        y,
        style={
            "fill": "linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
            "fill-opacity": 1,
            "stroke": "#8e51ff",
            "stroke-width": 2,
        },
        color="#8e51ff",
    ),
    xy.line(
        x,
        y,
        style={
            "stroke": "#8e51ff",
            "stroke-width": 2,
            "stroke-dasharray": "7px 4px",
        },
    ),
    xy.scatter(
        x,
        y,
        symbol="diamond",
        size=9,
        style={
            "fill": "#f8fafc",
            "stroke": "#8e51ff",
            "stroke-width": 2,
        },
    ),
    xy.x_axis(
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.y_axis(
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
)


def mark_style_preview():
    return reflex_xy.chart(styled_marks, height="340px")
~~~

## Mark-specific appearance

Some visual features are clearer as typed mark props rather than CSS
declarations:

- `curve="smooth"` applies a monotone cubic to lines and areas without
  overshooting the data.
- `dash="dashed"`, `"dotted"`, `"dashdot"`, or an explicit pixel sequence
  controls line and area-outline dashes.
- `fill="linear-gradient(...)"` styles area, bar, column, and histogram fills.
  Use `{"gradient": "...", "space": "plot"}` for one plot-space gradient.
- `corner_radius=(tip, base)` rounds value and baseline ends independently for
  bars, columns, and histograms.
- Scatter `symbol` accepts all 17 renderer-backed shapes: `circle`, `square`,
  `diamond`, `triangle`, `triangle_down`, `triangle_left`, `triangle_right`,
  `cross`, `x`, `hexagon`, `pentagon`, `star`, `point`, `pixel`,
  `thin_diamond`, `plus_line`, and `x_line`. Every shape combines with
  `stroke` / `stroke_width`; the last two are intentionally line-only glyphs.

All CSS gradients accept two to eight color stops and the four axis-aligned
directions. `currentColor` resolves to the mark's color; `transparent` retains
the stop hue while alpha fades.

## Axis styles

Axes are partly canvas-painted and partly DOM, so `x_axis(style=...)` and
`y_axis(style=...)` use another strict cross-renderer vocabulary:

| Axis key | Accepted value |
| --- | --- |
| `grid_color`, `axis_color`, `tick_color`, `tick_label_color`, `label_color` | CSS color |
| `grid_width`, `axis_width`, `tick_width`, `tick_length` | Non-negative number or CSS `px` length |
| `tick_size`, `tick_label_size`, `label_size` | Positive number or CSS `px` length |
| `grid_dash` | `solid`, `dashed`, `dotted`, or `dashdot` |
| `grid_opacity` | Number from 0 through 1 |
| `tick_direction` | `in`, `out`, or `inout` |

Use the axis component's `style` mapping when the x and y axes need different
colors or sizes. Tick marks use `tick_*`, tick text uses `tick_label_*`, and the
axis title uses `label_*`:

~~~python
xy.x_axis(
    label="month",
    style={
        "axis_color": "#475569",
        "axis_width": 1,
        "tick_color": "#64748b",
        "tick_width": 1,
        "tick_length": 6,
        "tick_direction": "out",
        "tick_label_color": "#334155",
        "tick_label_size": 12,
        "label_color": "#0f172a",
        "label_size": 14,
    },
)

xy.y_axis(
    label="revenue",
    style={
        "grid_color": "rgb(148 163 184 / 25%)",
        "grid_width": 1,
        "grid_dash": "dashed",
        "axis_color": "#7c3aed",
        "tick_color": "#7c3aed",
        "tick_label_color": "#6d28d9",
        "label_color": "#5b21b6",
    },
)
~~~

The `tick_label` and `axis_title` DOM slots provide chart-wide CSS or Tailwind
hooks for tick text and axis titles. Use per-axis `style` as above when x and y
must differ. Grid lines, axis lines, and tick marks are canvas-painted, so style
them through the axis component rather than a CSS selector.

## Validation

XY's native CSS grammar validates colors, gradients, numeric ranges, lengths,
and declaration safety at chart-build time:

- malformed closed forms such as `#3b82zz`, unknown color names, and `12parsecs`
  raise a `ValueError` naming the argument;
- browser-resolved forms such as `var()`, `oklch()`, `color-mix()`, and
  `calc()` are shape-checked and resolved by the client;
- unsafe declaration fragments—semicolons, braces, `</`, control characters,
  and unbalanced quotes/parentheses—are rejected;
- an unsupported mark or axis property raises rather than disappearing in one
  output format.

## What CSS cannot reach

CSS selectors cannot target individual canvas points, bars, line segments, or
annotation shapes. A mark `class_name` does not turn its geometry into a DOM
element. XY preserves it as trace metadata, but browser, Reflex, SVG, and
native renderers do not interpret it as a paint selector. Use
mark props, channels, and the compiled `style=` subset for data geometry.

Arrow shafts, markers, rules, and filled annotation zones are also
canvas-painted; use their `color`, `stroke_color`, `stroke_width`, and
`opacity` props. Annotation labels are DOM and can use the `annotation_label`
slot or a per-annotation `class_name`/`style`.

XY does not define a parallel hover/selected/unselected mark-style language.
Application state belongs to the notebook or host framework, which can update
the chart's ordinary props and CSS variables.
