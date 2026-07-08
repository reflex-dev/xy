# Styling FastCharts

Every rendered chrome element is a stable, CSS-addressable surface. You can
restyle the whole chart with plain CSS, attribute selectors, Tailwind, or
per-slot inline styles — and your styles always win, without `!important`.

This guide is the single reference for the styling contract. For the API shapes
see [reflex-shaped-api.md](design/reflex-shaped-api.md); for the render internals
see [renderer-architecture.md](design/renderer-architecture.md).

## The four ways to style

| Mechanism | Scope | Where |
| --- | --- | --- |
| `class_names={slot: "..."}` | Add classes to a chrome slot (great for Tailwind) | `fc.chart(...)` |
| `styles={slot: {...}}` | Inline CSS on a chrome slot | `fc.chart(...)` |
| `class_name=` / `style=` | A single annotation (per-call) | `.vline(...)`, `.text(...)`, … |
| `custom_css="..."` | A raw author stylesheet in the exported document | `to_html(fig, custom_css=...)` |

```python
import fastcharts as fc

chart = fc.chart(
    fc.scatter(x=xs, y=ys),
    class_names={
        "tooltip": "rounded-lg bg-slate-900/90 text-white shadow-xl",
        "legend": "text-xs font-medium",
        "modebar_button": "hover:bg-slate-200",
    },
    styles={"title": {"font_size": 18, "letter_spacing": "0.02em"}},
)
```

`styles` values follow the same numeric-length convention as common React/Python
style APIs: a bare number on a length property becomes `px` (`{"font_size": 18}`
→ `font-size:18px`), custom properties (`--x`) and unitless properties pass
through untouched.

## Slot reference

Every element below is rendered with `data-fc-slot="<slot>"`, so
`class_names[slot]`, `styles[slot]`, and a plain `[data-fc-slot="<slot>"]`
selector all target the same node. Slot names are validated — an unknown slot
raises before it reaches the client.

| Slot | Element |
| --- | --- |
| `root` | Outer chart container |
| `title` | Chart title |
| `chrome` | Non-plot chrome layer (legend/modebar/badges host) |
| `canvas` | WebGL2 plot canvas |
| `labels` | Axis/annotation label layer |
| `legend` | Legend container |
| `legend_item` | One legend row |
| `legend_swatch` | Legend color swatch |
| `tooltip` | Hover tooltip |
| `modebar` | Mode/tool bar container |
| `modebar_button` | One mode/tool button (`.fc-active` when engaged) |
| `selection` | Box/lasso selection rectangle |
| `crosshair_x` | Vertical crosshair line |
| `crosshair_y` | Horizontal crosshair line |
| `badge` | Reduction/density badge container |
| `badge_item` | One reduction/density badge |
| `tick_label` | Axis tick label |
| `axis_title` | Axis title label |
| `annotation_label` | Text/label/callout annotation (DOM overlay) |

```css
/* plain CSS — no build step, no classes on the Python side */
.fastcharts [data-fc-slot="tooltip"] { border-radius: 10px; }
.fastcharts [data-fc-slot="annotation_label"] { font-style: italic; }
.fastcharts [data-fc-slot="canvas"] { cursor: cell; }
```

```html
<!-- Tailwind arbitrary variant, targeting the same attribute -->
<div class="[&_[data-fc-slot=legend]]:bg-transparent"> … </div>
```

## Why your styles always win

The client injects one stylesheet of *visual* defaults (background, color,
padding, border, font, box-shadow, cursor). Every rule is wrapped in
[`:where(...)`](https://developer.mozilla.org/en-US/docs/Web/CSS/:where), which
has **zero specificity**. A Tailwind utility class (specificity `0,1,0`) or an
inline `styles[slot]` (inline, highest) therefore beats the default with no
`!important` and regardless of stylesheet source order.

The rendered elements carry only **structural** inline styles — position, size,
z-index, and interaction state (`data-fc-dragmode`, the `.fc-active` class).
Nothing themeable is pinned inline, so nothing themeable can shadow your class.
This is what "ultra customizable" means here: defaults are suggestions, your CSS
is authority.

> Annotation label color and the plot cursor follow the same rule: the default
> is a `:where()` stylesheet entry keyed on a slot/attribute, so `cursor-cell` or
> `text-rose-500` on the slot wins. (A per-annotation `style={"color": ...}` still
> pins that one label inline, as an explicit intent.)

## Theme tokens

All default colors flow through `--chart-*` custom properties, so container
theming cascades into the chart (including dark mode) without touching a slot.
Set them on `.fastcharts` or any ancestor:

```css
.fastcharts {
  --chart-bg: transparent;
  --chart-text: #e5e7eb;
  --chart-grid: rgba(255, 255, 255, 0.12);
  --chart-axis: rgba(255, 255, 255, 0.5);
  --chart-tooltip-bg: #0b1220;
  --chart-tooltip-text: #f8fafc;
}
```

| Token | Themes | Default |
| --- | --- | --- |
| `--chart-bg` | Plot background | transparent |
| `--chart-text` | Title, tick/axis titles, legend, annotation labels | inherited text (canvas labels: `currentColor` @ 85%) |
| `--chart-grid` | Grid lines (canvas) | `currentColor` @ 14% |
| `--chart-axis` | Axis lines (canvas), modebar glyphs | `currentColor` @ 55% |
| `--chart-tooltip-bg` / `--chart-tooltip-text` | Tooltip | `rgba(20,24,33,.92)` / `#fff` |
| `--chart-legend-bg` | Legend background | `rgba(128,128,128,.08)` |
| `--chart-badge-bg` / `--chart-badge-text` | Reduction badges | `rgba(255,255,255,.82)` / `#0f172a` |
| `--chart-modebar-bg` / `--chart-modebar-active` | Modebar / active button | `rgba(255,255,255,.78)` / `rgba(128,128,128,.22)` |
| `--chart-selection` / `--chart-selection-fill` | Selection rectangle | `rgba(90,140,240,.9)` / `…,.15)` |
| `--chart-crosshair` | Crosshair lines | `rgba(15,23,42,.42)` |
| `--chart-annotation-text` | Annotation label color | falls back to `--chart-text` |
| `--chart-cursor` / `--chart-cursor-pan` | Plot cursor (box-zoom / pan) | `crosshair` / `grab` |

## Standalone HTML

`to_html(fig, custom_css=...)` inlines the same client and your stylesheet into a
self-contained document, so exported charts style identically to the widget:

```python
from fastcharts import to_html

to_html(fig, "chart.html", custom_css="""
  .fastcharts { --chart-text: #1f2937; font-family: 'Inter', system-ui; }
  .fastcharts [data-fc-slot="tooltip"] { backdrop-filter: blur(4px); }
""")
```

`custom_css` is injected as an author `<style>` and is rejected if it tries to
break out of the tag (`</style>`, comment sequences).

## What CSS cannot restyle

The **marks themselves** — points, lines, bars, heatmap cells — and annotation
**shapes** (markers, arrows, filled zones) are painted on the WebGL2/2D canvas,
not the DOM, so CSS selectors do not reach them. Style them through data instead:

- Mark color/size/opacity: the trace's channels and `mark_style` (selected /
  unselected / hover states).
- Annotation shapes: the annotation's own `color` / `stroke_color` /
  `stroke_width` / `opacity` arguments.

Only annotation **labels** are DOM (`annotation_label`) and thus fully CSS-styleable.
