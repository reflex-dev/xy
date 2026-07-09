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

## Styling the marks

The marks themselves — bars, areas, lines, points — are painted on the WebGL2
canvas, so CSS *selectors* can't reach them. Instead, the mark props speak CSS:
every color accepts any CSS color the browser can resolve (`var(--accent)`,
`oklch(...)`, named colors, alpha hex), re-resolved live on theme change, and
fills accept real CSS `linear-gradient(...)` syntax. The border trio mirrors
CSS naming (`corner_radius`, `stroke`, `stroke_width`).

```python
# The classic dashboard look: smooth curve + gradient fade to the baseline
fig.area(x, y, color="#3b82f6", curve="smooth",
         fill="linear-gradient(currentColor, transparent)")

# Rounded, bordered, gradient bars
fig.bar(x, y,
    corner_radius=6,                                   # like CSS border-radius (px)
    stroke="var(--chart-axis)", stroke_width=1.5,      # like CSS border
    fill="linear-gradient(to top, #2563eb, #93c5fd)")  # per-bar gradient
```

### Gradient fills — `fill=` on `area`, `bar`, `column`, `histogram`

`fill` takes a CSS `linear-gradient(...)`: optional direction (`to top`,
`to bottom` — the default, `to left`/`to right` in plot space), then 2–8 color
stops with optional `%` positions (CSS rules: endpoints default to 0%/100%,
unpositioned stops spread evenly). Two special colors:

- `currentColor` — the mark's own resolved color (palette default, `var()`,
  anything), so one string works across every trace.
- `transparent` — stops interpolate in premultiplied alpha, so fades to
  transparent keep their hue (no gray fringe).

Gradients run in **mark space** by default: along each mark's value axis, `to
bottom` starting at the tip/line and ending at the base — an area fades from
its curve down to the baseline; every bar fades along its own height. For one
gradient across the whole plot box instead, opt into **plot space**:

```python
fill={"gradient": "linear-gradient(to right, var(--a), var(--b))", "space": "plot"}
```

### Borders & radius — `bar`, `column`, `histogram`

`corner_radius` (px, clamped to half the mark size — a radius of half-width
gives pill bars), `stroke` (any CSS color; defaults to the mark color when only
a width is given), `stroke_width` (px; a stroke color alone implies 1px).
Rendered as an antialiased SDF in the fragment shader — zero cost when unset,
and hover/tooltips still hit the full rectangular footprint.

`corner_radius` also takes a `(tip, base)` pair in mark space — the classic
rounded-top bar is `corner_radius=(6, 0)`: round the value end, keep the base
square on the axis. Like gradients, the pair is orientation-aware (a
horizontal bar rounds its right end) and correct for negative bars (the tip
is below the baseline).

### Opacity

Every mark takes `opacity` (0–1) for its fill/body; it composes with everything
— a solid color, a gradient fill (each stop is scaled, so a fade-to-transparent
stays proportional), and the antialiased corner/stroke coverage. `area` also has
`line_opacity` for its outline. For finer control, any color is a full CSS color
**including alpha** — `rgba(37,99,235,.5)`, `#2563eb80`, `oklch(... / 40%)` — and
because the stroke keeps its own color's alpha, a translucent fill with a solid
border is just `bar(opacity=0.3, stroke="#2563eb", stroke_width=2)`.

### Scatter markers — `symbol`, `stroke`, `stroke_width`

`scatter` markers take a `symbol` — `circle` (default), `square`, `diamond`,
`triangle`, or `cross` — plus a `stroke` color and `stroke_width` (px) for a
border, e.g. `scatter(x, y, symbol="triangle", stroke="#fff", stroke_width=2)`.
Each is an antialiased SDF in the point shader, so shapes stay crisp at any size
and the border is a true ring (a stroke width with no color borders in the mark
color). Symbols compose with the color/size channels and the selected/unselected
mark states.

### Interaction states — `mark_style` / `set_mark_style(...)`

Restyle marks by interaction state — `hover`, `selected`, `unselected` — each a
style dict of `color` / `opacity` (and `size` for hover). Selecting a region
recolors and dims in one pass on the GPU:

```python
fig.set_mark_style(
    hover={"color": "#0f172a", "size": 10},   # the point under the cursor
    selected={"color": "#f97316"},            # points inside the selection
    unselected={"opacity": 0.15},             # everything else fades back
)
```

`color` accepts any CSS color; a state that sets no `color` keeps the mark's
native color (so `unselected={"opacity": 0.15}` is the classic dim-the-rest
selection affordance).

### Smooth curves — `curve="smooth"` on `line`, `area`

Monotone cubic (Fritsch–Carlson) through the points: follows the data, never
overshoots (safe on decimated tiers), re-applied on every zoom-refined window.
Hover and tooltips keep reporting the real data points, not interpolated ones.
Densification caps at ~32k vertices — past that the polyline is sub-pixel
dense and smoothing is invisible by construction.

### The full mark-styling matrix

| Mark | Color/opacity | Gradient fill | Corner radius | Stroke | Curve | Dash | Size/width |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bar` / `column` | ✅ (+ per-series `colors`) | ✅ mark/plot space | ✅ all or `(tip, base)` | ✅ | — | — | ✅ `width` |
| `histogram` | ✅ | ✅ | ✅ all or `(tip, base)` | ✅ | — | — | bin-driven |
| `area` | ✅ (+ `line_width`/`line_opacity`) | ✅ | — | line is the stroke | ✅ | ✅ outline | ✅ |
| `line` | ✅ | — (stroke gradients: roadmap) | — | is a stroke | ✅ | ✅ | ✅ `width` |
| `scatter` | ✅ + color/size channels | — | `symbol` (circle/square/diamond/triangle/cross) | ✅ `stroke`/`stroke_width` | — | — | ✅ + size channel |
| `heatmap` | colormap + `domain` | colormap is the gradient | — | — | — | — | cell-driven |

State styling (`mark_style`: hover / selected / unselected opacity & color)
composes with all of the above. On the roadmap, in likely order: per-mark drop
shadows, gradient angles beyond the four axis directions, and stroke gradients.

### Dashes — `dash` on `line`, `area`

`dash` takes a preset — `"dashed"`, `"dotted"`, `"dashdot"` (or `"solid"`) — or
an explicit `[on, off, …]` px sequence (the SVG/CSS convention). The pattern is
measured in **screen-space arc length**, computed per frame, so dashes stay a
constant on-screen size through zoom and run continuously across every segment
of a curve — not reset per data point. `area` dashes its outline.

## What CSS cannot restyle

Annotation **shapes** (markers, arrows, filled zones) are canvas-painted; style
them through the annotation's own `color` / `stroke_color` / `stroke_width` /
`opacity` arguments. Only annotation **labels** are DOM (`annotation_label`)
and thus fully CSS-styleable.

## Static export

`fig.to_svg(path?, width=, height=)` renders the same decimated payload the
browser client consumes into a standalone, resolution-independent SVG — pure
Python, no browser, no extra dependencies. Because decimation runs first, the
file is **screen-bounded**: a 10M-point line exports in ~4 ms as a ~58 KB SVG.
Density/heatmap tiers embed as compact rasters.

`fig.to_png(path?, width=, height=, scale=)` defaults to `engine="native"`: the
built-in **Rust rasterizer** paints that same decimated payload — no browser,
millisecond export (a 10M-point line rasterizes in ~40 ms), and indexed-palette
PNGs for small files. Text uses a baked bitmap font (the dependency-free core
has no FreeType), so small labels are slightly less refined than a browser's.
For a pixel-exact match to the live WebGL chart, `engine="chromium"` screenshots
the standalone HTML (needs a local Chrome/Chromium).

Both static engines carry the full mark styling surface — gradients, dashes,
symbols, rounded/stroked bars, smooth curves — with the same two documented
approximations: an area's mark-space gradient uses the area's bounding box (no
per-column gradient), and `var(--x)` colors fall back to the mark color (no DOM
to resolve them against). SVG renders smooth curves as exact cubic Béziers; the
native raster flattens them to a fine polyline.
