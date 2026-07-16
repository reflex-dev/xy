---
title: Styling and Themes
description: Style chart chrome, DOM slots, canvas marks, and export output.
---

# Styling and Themes

XY separates DOM chrome from canvas-rendered marks. Use chart and slot styles
for containers, axes, legends, and tooltips; use mark props for lines, points,
areas, bars, and other geometry.

## Theme Tokens

~~~python
import xy as fc

chart = fc.line_chart(
    fc.line(
        [0, 1, 2, 3],
        [2, 5, 3, 8],
        color="var(--chart-accent)",
        curve="smooth",
        width=2.5,
    ),
    fc.theme(
        plot_background="#ffffff",
        grid_color="#e2e8f0",
        axis_color="#64748b",
        text_color="#1e293b",
    ),
)
~~~

## Chart and Slot Styles

`class_name` targets the chart root. `class_names` maps stable DOM slots to
classes, while `styles` maps slots to inline style dictionaries. Important slots
include chart, plot, title, axis labels, tick labels, legend, tooltip, colorbar,
modebar, and annotation labels.

~~~python
chart = fc.scatter_chart(
    fc.scatter([1, 2], [3, 5], class_name="points"),
    class_name="analytics-card",
    class_names={"tooltip": "rounded-xl shadow-lg"},
    styles={"title": {"font-weight": 700}},
)
~~~

## Mark Styling

- `line` and `area`: `color`, `width`, `opacity`, `curve`, and `dash`.
- `area`, `bar`, `column`, and `histogram`: CSS-like gradient `fill`.
- `bar`, `column`, and `histogram`: `corner_radius`, `stroke`, and
  `stroke_width`.
- `scatter`: `symbol`, `size`, `stroke`, and `stroke_width`.
- Encoded color marks: `colormap` and explicit color domains.

~~~python
bars = fc.column(
    ["A", "B", "C"],
    [4, 7, 5],
    fill="linear-gradient(to top, #6e56cf, #c4b5fd)",
    corner_radius=(6, 0),
    stroke="#4c3aa3",
    stroke_width=1,
)
~~~

Pass `custom_css=` to `to_html()` or Chromium-based PNG export when an exported
document needs author CSS. Native PNG intentionally accepts only renderable XY
styles, while SVG preserves its own vector styling.
