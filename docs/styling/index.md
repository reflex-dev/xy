---
title: Styling Overview
description: Choose between CSS/Tailwind chrome hooks, mark styles, theme tokens, and export CSS.
---

# Styling Overview

XY has two rendering surfaces. Chart chrome—titles, axis labels, legends,
tooltips, controls, and annotation labels—is DOM and participates in the normal
CSS cascade. Data marks are painted by WebGL, SVG, or the native rasterizer, so
XY compiles a deliberate CSS-property subset for them instead of claiming that
arbitrary browser selectors can reach a canvas.

## Five ways to style

| Mechanism | Scope | Best for |
| --- | --- | --- |
| `class_names={slot: "..."}` | One stable chrome slot | Tailwind utilities or existing classes |
| `styles={slot: {...}}` | One stable chrome slot | Computed inline DOM styles |
| Mark `style={...}` | One rendered mark | Cross-renderer CSS paint vocabulary |
| Annotation `class_name=` / `style=` | One annotation | Label classes and explicit annotation appearance |
| `custom_css=` on `to_html()` | One exported document | Raw author CSS and attribute selectors |

Chart-level `class_name=` styles the root, while chart-level `style=` supplies
root CSS declarations and custom properties. Component helpers such as
`legend()`, `tooltip()`, and `modebar()` also accept local class/style props
that merge into their corresponding slots.

~~~python
import xy

chart = xy.scatter_chart(
    xy.scatter(
        [1, 2, 3],
        [3, 5, 4],
        style={
            "fill": "var(--accent)",
            "stroke": "currentColor",
            "stroke-width": "1px",
        },
    ),
    class_name="analytics-card",
    class_names={
        "tooltip": "rounded-lg bg-slate-900/90 text-white shadow-xl",
        "legend": "text-xs font-medium",
        "modebar_button": "hover:bg-slate-200",
    },
    styles={"title": {"font_size": 18, "letter_spacing": "0.02em"}},
    style={"--accent": "#6e56cf"},
    title="Styled scatter",
)
~~~

## What “your styles win” means

XY's built-in **visual** chrome rules use `:where(...)`, which has zero CSS
specificity. A utility class or ordinary author selector therefore overrides
the default background, color, padding, border, font, shadow, or cursor without
`!important`, even when the default stylesheet appears later.

The promise is scoped to built-in visual defaults. XY still applies structural
inline layout—position, size, z-index, and interaction state—and an explicit
inline `styles[slot]` or per-annotation style naturally outranks a class. Marks
follow their compiled style contract rather than the DOM cascade.

## Choose the next page

- [Chrome slots](/docs/xy/styling/chrome-slots/) lists every stable DOM hook
  and shows the Tailwind workflow.
- [Mark styles](/docs/xy/styling/mark-styles/) documents the compiled CSS
  subset, axis styles, validation, and canvas boundary.
- [Themes and tokens](/docs/xy/styling/themes-and-tokens/) defines reusable
  `--chart-*` variables and dark-mode patterns.
- [Recipes](/docs/xy/styling/recipes/) provides visual, copy-pasteable chart
  treatments.
