# Styling XY

Every rendered chrome element is a stable, CSS-addressable surface. You can
restyle the whole chart with plain CSS, attribute selectors, Tailwind, or
per-slot inline styles — and your styles always win, without `!important`.

This engineering guide explains the implementation contract. The public,
task-oriented references are [Styling](../../docs/styling/index.md),
[Component Variations](../../docs/styling/component-variations.md), and
[Mark Styles](../../docs/styling/mark-styles.md). For the API shapes see
[reflex-shaped-api.md](../design/reflex-shaped-api.md); for the render internals
see [renderer-architecture.md](../design/renderer-architecture.md).

## The five ways to style

| Mechanism | Scope | Where |
| --- | --- | --- |
| `class_names={slot: "..."}` | Add classes to a chrome slot (great for Tailwind) | `xy.chart(...)` |
| `styles={slot: {...}}` | Inline CSS on a chrome slot | `xy.chart(...)` |
| `style={...}` | Cross-renderer CSS appearance subset for a rendered mark | `xy.line(...)`, `xy.scatter(...)`, … |
| `class_name=` / `style=` | One annotation label; geometry still uses typed props | `.vline(...)`, `.text(...)`, … |
| `custom_css="..."` | A raw author stylesheet in the exported document | `to_html(fig, custom_css=...)` |

```python
import xy

chart = xy.chart(
    xy.scatter(
        x=xs,
        y=ys,
        style={"fill": "var(--accent)", "stroke": "currentColor", "stroke-width": "1px"},
    ),
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

In Reflex, Tailwind utilities require `rx.plugins.TailwindV4Plugin()`. Complete
literal classes emitted into Reflex's generated JSX work with the plugin's
normal scan paths; the original Python or Markdown path does not need to be
added. See the public [Chrome Slots](../../docs/styling/chrome-slots.md) guide for the
standalone-export and dynamic-class boundaries.

## Rendered marks: standard CSS vocabulary

WebGL and native-raster marks are not DOM elements, so XY compiles a deliberate
CSS subset instead of pretending every browser property can work. Property
names are canonical CSS kebab-case; snake_case aliases remain accepted for
Python compatibility. Unsupported properties raise before the figure mutates.

```python
xy.line(
    x=x,
    y=y,
    style={
        "stroke": "var(--accent)",
        "stroke-width": "2px",
        "stroke-opacity": 0.85,
        "stroke-dasharray": "6px 3px",
    },
)

xy.bar(
    x=category,
    y=value,
    style={
        "fill": "linear-gradient(to top, #2563eb, #93c5fd)",
        "stroke": "#1e3a8a",
        "stroke-width": "1px",
        "border-radius": "4px",
    },
)
```

| Mark family | Supported CSS properties |
| --- | --- |
| line, step, stairs, ECDF | `stroke`, `stroke-width`, `stroke-opacity`, `stroke-dasharray`, `opacity` |
| area, error band | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `opacity`; area also supports `stroke-dasharray` |
| scatter | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `opacity` |
| histogram, bar, column | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `border-radius`, `opacity` |
| segments, error bars, contour, stem | `stroke`, `stroke-width`, `stroke-opacity`, `opacity` |
| box, violin | `fill`, `fill-opacity`, `opacity` |
| triangle mesh | `fill`, `fill-opacity`, `stroke`, `stroke-width`, `stroke-opacity`, `opacity` |
| heatmap, hexbin | `fill-opacity`, `opacity` |

Legacy appearance arguments such as `color=`, `width=`, and `opacity=` remain
supported; a CSS `style` declaration is the final override when both are set.
Within `style`, use the standard paint property for the geometry: `stroke` for
line-like marks and `fill` for filled marks. `color` is not a paint alias there;
this avoids ambiguous combinations such as `color` plus `stroke` and keeps the
same declarations meaningful in SVG, WebGL, and native PNG output.

A mark's `class_name` is adapter-only trace metadata. It does not create a DOM
node and is not interpreted as a paint selector by the shipped browser,
Reflex, SVG, or native renderers.

### Reflex integration boundary

Reflex owns reactive `Var` values, conditions, application state, event
handlers, layouts, and themes. XY does not duplicate those facilities. The
integration resolves them into concrete `style`, `styles`, `class_name`, and
`class_names` values and updates the renderer. CSS variables are the preferred
bridge for design tokens and theme changes.

### Axis paint and geometry

`xy.x_axis(style={...})` and `xy.y_axis(style={...})` accept a strict,
cross-renderer axis vocabulary. Unknown keys and invalid values raise when the
axis component is created, before the chart or an export is rendered. Keys may
use Python snake_case or CSS kebab-case; pixel geometry accepts a finite number
or a CSS `px` value such as `"3px"`.

| Axis style key | Value |
| --- | --- |
| `grid_color`, `axis_color`, `tick_color`, `tick_label_color`, `label_color` | CSS color |
| `grid_width`, `axis_width`, `tick_width` | Non-negative pixel length |
| `grid_dash` | `"solid"`, `"dashed"`, `"dotted"`, or `"dashdot"` |
| `grid_opacity` | Number from `0` to `1` |
| `tick_length` | Non-negative pixel length |
| `tick_size` / `tick_label_size`, `label_size` | Positive pixel font size |
| `tick_direction` | `"in"`, `"out"`, or `"inout"` |
| `tick_label_anchor` | `"start"`, `"center"`, or `"end"` (mpl `ha` aliases `"left"`/`"right"`/`"middle"` normalize) — which label edge pins to the tick; rotated labels pivot about the pinned edge. Also a first-class `x_axis`/`y_axis` option. X defaults to `"center"`; y defaults to the tick-side edge (`"end"` left of the plot, `"start"` right of it). Honored by static SVG/PNG exports. |

```python
xy.x_axis(
    label="time",
    style={
        "grid-color": "rgb(148 163 184 / 25%)",
        "grid-width": "1px",
        "grid-dash": "dashed",
        "grid-opacity": 0.7,
        "axis-color": "var(--axis)",
        "tick-length": "6px",
        "tick-direction": "out",
        "tick-color": "currentColor",
        "tick-label-color": "currentColor",
        "label-size": "13px",
    },
)
```

### Axis ticks and label formatting

Tick placement is computed in f64 on the CPU (§16), never through f32, and is
selected per scale kind with a target of 6 ticks. Every generator caps its
output at 200 ticks.

| Scale kind | Rule |
| --- | --- |
| linear | Step is the nice step for `(hi - lo) / target` — the smallest of `1, 2, 2.5, 5, 10` times the decade magnitude that covers the rough step. Ticks start at the first multiple of the step at or above `lo`. |
| log | Decade ticks from `floor(log10(lo))` to `ceil(log10(hi))`; multipliers `1, 2, 5` when the decade span is small, `1` alone otherwise. Only powers of ten are labeled, thinned so roughly `target` labels remain. Non-positive bounds yield no ticks. |
| category | Every `ceil(visible / target)`-th category index in view. |
| time | The smallest step in a fixed ladder from 1 ms through 14 days that covers the rough step. Above 14 days per tick, calendar ticks land on UTC month boundaries with a month step from `1, 2, 3, 6, 12, 24, 60, 120`. |

`xy.x_axis(format=...)` and `xy.y_axis(format=...)` take a format string whose
grammar depends on the axis kind. Both are deliberately small subsets, not full
d3-format or strftime, and neither raises on a spec it does not understand —
but they fail differently, and only the numeric grammar falls back.

- **Numeric axes** accept `.Nf` (fixed decimals), `,.Nf` (fixed decimals with
  locale group separators, via the runtime's default locale), and either form
  with a trailing `%`, which multiplies the value by 100 and appends the sign —
  for example `.2f`, `,.0f`, `.1%`. The trailing `f` is optional. Any other
  string **falls back**: `fmtNumberSpec` returns `null`
  (`js/src/30_ticks.ts:168`) and `fmtAxis` takes its `|| fmtLinear(...)` branch
  (`:209`), so the axis silently reverts to the automatic formatter. On a log
  axis, a value in `(0, 1)` that the spec would render as `"0"` falls back the
  same way.
- **Time axes** accept a strftime subset of exactly `%Y %m %d %H %M %S %b %B`.
  All fields are **UTC**; `%b`/`%B` are English month names. A time spec
  **never** falls back: `fmtTimeSpec` (`js/src/30_ticks.ts:180-200`)
  substitutes the tokens it knows and copies every other character through
  verbatim, so it always returns a string and the `|| fmtTime(...)` branch at
  `:204` is unreachable. An unrecognized `%` token such as `%y` therefore
  renders literally as `%y`. The automatic time formatter is reached only when
  `format` is absent or not a string.
- **Category axes** ignore `format=` and render the category label.

## Slot reference

Every element below is rendered with `data-xy-slot="<slot>"`, so
`class_names[slot]`, `styles[slot]`, and a plain `[data-xy-slot="<slot>"]`
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
| `colorbar` | Colorbar container |
| `colorbar_bar` | Colorbar gradient/bands |
| `colorbar_tick` | Colorbar tick label |
| `colorbar_title` | Colorbar title |
| `tooltip` | Hover tooltip |
| `modebar` | Mode/tool bar container |
| `modebar_button` | One mode/tool button (`.xy-active` when engaged) |
| `selection` | Active box-select or box-zoom rectangle |
| `crosshair_x` | Vertical crosshair line |
| `crosshair_y` | Horizontal crosshair line |
| `badge` | Reduction/density badge container |
| `badge_item` | One reduction/density badge |
| `tick_label` | Axis tick label |
| `axis_title` | Axis title label |
| `annotation_label` | Text/label/callout annotation (DOM overlay) |

```css
/* plain CSS — no build step, no classes on the Python side */
.xy [data-xy-slot="tooltip"] { border-radius: 10px; }
.xy [data-xy-slot="annotation_label"] { font-style: italic; }
.xy [data-xy-slot="canvas"] { cursor: cell; }
```

```html
<!-- Tailwind arbitrary variant, targeting the same attribute -->
<div class="[&_[data-xy-slot=legend]]:bg-transparent"> … </div>
```

## Why your styles always win

The client injects one stylesheet of *visual* defaults (background, color,
padding, border, font, box-shadow, cursor). It lives in the low-priority `base`
cascade layer, and every selector uses
[`:where(...)`](https://developer.mozilla.org/en-US/docs/Web/CSS/:where) for
**zero specificity**. Tailwind's later utility layer, unlayered author CSS, and
inline `styles[slot]` therefore beat the defaults without `!important`.

The rendered elements carry only **structural** inline styles — position, size,
z-index, and interaction state (`data-xy-dragmode`, the `.xy-active` class).
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
Set them on `.xy` or any ancestor:

```css
.xy {
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
| `--chart-bg` | Plot-rect background only (`theme(plot_background=)`, mpl `axes.facecolor`) | transparent |
| `--chart-text` | Title, tick/axis titles, legend, annotation labels, modebar glyphs | inherited text (canvas labels: `currentColor` @ 85%) |
| `--chart-grid` | Grid lines (canvas) | `currentColor` @ 14% |
| `--chart-axis` | Axis lines (canvas) | `currentColor` @ 55% |
| `--chart-tooltip-bg` / `--chart-tooltip-text` | Tooltip | `rgba(20,24,33,.92)` / `#fff` |
| `--chart-legend-bg` | Legend background | `rgba(128,128,128,.08)` |
| `--chart-badge-bg` / `--chart-badge-text` | Reduction badges | `rgba(255,255,255,.82)` / `#0f172a` |
| `--chart-modebar-bg` / `--chart-modebar-active` | Modebar / active button | `rgba(255,255,255,.78)` / `rgba(128,128,128,.2)` (light; see below) |
| `--chart-selection` / `--chart-selection-fill` | Box-select rectangle | `rgba(90,140,240,.9)` / `…,.15)` |
| `--chart-zoom-selection` / `--chart-zoom-selection-fill` | Box-zoom drag rectangle | `rgba(120,120,120,.9)` / `…,.12)` |
| `--chart-crosshair` | Crosshair lines | `rgba(15,23,42,.42)` |
| `--chart-annotation-text` | Annotation label color | falls back to `--chart-text` |
| `--chart-cursor` / `--chart-cursor-pan` | Plot cursor (box-zoom / pan) | `crosshair` / `grab` |
| `--chart-focus` | Keyboard focus ring on the plot canvas and modebar buttons | `#2563eb` |

The modebar defaults are **scheme-aware**: a `.dark` class on the chart root or
any ancestor flips the internal fallbacks to `rgba(37,42,52,.9)` /
`rgba(255,255,255,.16)`. The public `--chart-modebar-*` tokens override both
schemes; the modebar's border and shadow have no public token and are internal
`--xy-modebar-*` defaults only. `--chart-focus` is likewise not carried into
client-side PNG/SVG export, which snapshots the other `--chart-*` tokens.

The **figure background** (matplotlib's `figure.facecolor` — the whole card
including margins, title, and tick labels) is not a token: `theme(background=)`
sets the root element's CSS `background` directly, and the plot rect shows it
unless `plot_background` (`--chart-bg`) paints the rect separately. Static SVG
and PNG exports reproduce both fills (solid colors; gradients stay
browser-only), so a dark card exports dark.

The compact toolbar appears at the plot's top-left while the chart is hovered
or one of its controls has keyboard focus. Its background, padding, gaps, and
separators are draggable after a 5px movement threshold; controls and popovers
are not drag targets. A 26×28px external drag affordance appears on hover,
focus, or during a drag and flips between the toolbar's left and right sides
to avoid clipping the chart edge. Pan starts active and toggles off to release
drag and wheel gestures back to the containing page. Zoom and
selection modes are grouped into menus; completed lasso selections expose up
to 16 adaptively simplified handles that can be dragged to refine the selected
range. The export menu defaults to PNG, SVG, and the chart's resident data as
CSV. `xy.export_config(formats=[...])` governs which of `png`, `jpeg`, `webp`,
`svg`, and `csv` appear and in what order; `pdf` and `html` are Python-side
formats and are skipped in the client menu. An explicit empty list hides the
download trigger while the toolbar surface remains draggable.
Client PNG and SVG export snapshot the chart's computed `--chart-*` tokens,
text color, and font styles so themes inherited from a host application are
preserved in the downloaded image.

## Standalone HTML

`to_html(fig, custom_css=...)` inlines the same client and your stylesheet into a
self-contained document, so exported charts style identically to the widget:

```python
from xy import to_html

to_html(fig, "chart.html", custom_css="""
  .xy { --chart-text: #1f2937; font-family: 'Inter', system-ui; }
  .xy [data-xy-slot="tooltip"] { backdrop-filter: blur(4px); }
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

Every mark takes standard CSS `opacity` (0–1) for the whole mark. Standard SVG
CSS `fill-opacity` and `stroke-opacity` independently multiply the fill and
stroke channels. Effective alpha is therefore paint alpha × channel opacity ×
whole-mark opacity. These compose with everything
— a solid color, a gradient fill (each stop is scaled, so a fade-to-transparent
stays proportional), and the antialiased corner/stroke coverage. `area` also has
`line_opacity` for its outline. For finer control, any color is a full CSS color
**including alpha** — `rgba(37,99,235,.5)`, `#2563eb80`, `oklch(... / 40%)` — and
because the channels are separate, a translucent fill with a solid border is
`style={"fill-opacity": 0.3, "stroke-opacity": 1}`.

Whole-mark opacity applies to an area's outline as well as its fill. Therefore
the default area `opacity=0.35` produces a `0.35`-alpha outline. For a faint
fill with an opaque outline, keep whole-mark opacity at `1` and set
`style={"fill-opacity": 0.35, "stroke-opacity": 1}`.

### Vectorized instance styles

Instanced 2-D primitives accept scalar or per-item styles without splitting a
collection into one trace per mark:

| Mark | Direct paint | Numeric/glyph channels |
| --- | --- | --- |
| scatter | `color`, `stroke`: `(N, 3)` RGB or `(N, 4)` RGBA | `opacity`, `size`, `stroke_width`, `symbol` |
| bar, column, histogram, rectangles | `color`, `stroke`: `(N, 3|4)` | `opacity`, `stroke_width`, `corner_radius` (`N` or `N × 2`) |
| independent segments | `color`: `(N, 3|4)` | `opacity`, `width` |
| triangle mesh | `color`, `stroke`: `(N, 3|4)` | `opacity`, `stroke_width` |

Multi-series bars accept `(S, N, 3|4)` paint and `(S, N)` numeric channels.
A one-series `(N, …)` value never broadcasts into a differently shaped series;
shape mismatches fail before the figure is mutated. Direct RGBA is packed as
four normalized bytes per item. Scalar constants remain spec-only, while
semantic one-dimensional numeric/categorical color channels keep using a
scalar plus a lookup table and may produce a colorbar.

An outline that follows its item fill ships as the buffer-free `match_fill`
paint mode; it does not duplicate direct RGBA bytes.

Alpha composition is ordered and shared by WebGL, PNG, and SVG:

1. the paint contributes intrinsic alpha;
2. a Matplotlib artist-alpha override replaces that intrinsic alpha (`None`
   restores it);
3. core `opacity`, component `fill_opacity`/`stroke_opacity`, and selection
   opacity multiply the result.

A scalar `style={...}` declaration is intentionally scalar-only and overrides
the corresponding typed scalar/vector argument. Dense scatter aggregation can
discard exact instance styles above the direct-render ceiling; its warning
lists every dropped channel.

Streaming append accepts matching `color`, `size`, `stroke`, `opacity`,
`alpha`, `stroke_width`, and `symbol` tails for an existing per-item scatter
channel. All tail shapes are validated before geometry or style storage is
mutated, so a rejected append cannot leave channel lengths out of sync.

### Scatter markers — `symbol`, `stroke`, `stroke_width`

`scatter` markers take any of the 17 renderer-backed symbols listed in the
public [Mark styles](../../docs/styling/mark-styles.md#mark-specific-appearance) guide,
plus a `stroke` color and `stroke_width` (px) for a border, e.g.
`scatter(x, y, symbol="triangle", stroke="#fff", stroke_width=2)`. Each is an
antialiased SDF in the point shader, so shapes stay crisp at any size and the
border is a true ring (a stroke width with no color borders in the mark color).
Symbols compose with the color/size channels.

Interaction state belongs to the host framework. In Reflex, use Reflex state,
event handlers, conditions, and ordinary CSS classes/styles; XY only emits the
events and renders the resulting props. The component API deliberately does not
define a parallel hover/selected/unselected styling language.

### Smooth curves — `curve="smooth"` on `line`, `area`

Monotone cubic (Fritsch–Carlson) through the points: follows the data, never
overshoots (safe on decimated tiers), re-applied on every zoom-refined window.
Hover and tooltips keep reporting the real data points, not interpolated ones.
Densification caps at ~32k vertices — past that the polyline is sub-pixel
dense and smoothing is invisible by construction.

### Common typed appearance combinations

This table compares the most feature-rich typed appearance props. The public
[Mark Styles](../../docs/styling/mark-styles.md) matrix is exhaustive across every
rendered mark family and its accepted `style=` properties.

| Mark | Color/opacity | Gradient fill | Corner radius | Stroke | Curve | Dash | Size/width |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bar` / `column` | ✅ (+ per-series `colors`) | ✅ mark/plot space | ✅ all or `(tip, base)` | ✅ | — | — | ✅ `width` |
| `histogram` | ✅ | ✅ | ✅ all or `(tip, base)` | ✅ | — | — | bin-driven |
| `area` | ✅ (+ `line_width`/`line_opacity`) | ✅ | — | line is the stroke | ✅ | ✅ outline | ✅ |
| `line` | ✅ | — (stroke gradients: roadmap) | — | is a stroke | ✅ | ✅ | ✅ `width` |
| `scatter` | ✅ + color/size channels | — | 17 `symbol` glyphs | ✅ `stroke`/`stroke_width` | — | — | ✅ + size channel |
| `heatmap` | colormap + `domain` | colormap is the gradient | — | — | — | — | cell-driven |

On the roadmap, in likely order: per-mark drop
shadows, gradient angles beyond the four axis directions, and stroke gradients.

### Dashes — `dash` on `line`, `area`

`dash` takes a preset — `"dashed"`, `"dotted"`, `"dashdot"` (or `"solid"`) — or
an explicit `[on, off, …]` px sequence (the SVG/CSS convention). The pattern is
measured in **screen-space arc length**, computed per frame, so dashes stay a
constant on-screen size through zoom and run continuously across every segment
of a curve — not reset per data point. `area` dashes its outline.

## Validation — loud errors, never a silently wrong chart

Every color, gradient stop, and `style`/`styles` declaration is validated at
chart-build time by the native core's CSS grammar (`src/css.rs`, over
`kernels.css_check`) — the same parser the built-in PNG rasterizer paints
with, so what validates is exactly what renders:

- **Closed grammars parse strictly.** A bad hex digit (`#3b82zz`), an unknown
  color name (`bluu`), a non-length (`font_size: "big"`), or an unknown unit
  (`12parsecs`) raises `ValueError` at the chart call, naming the argument
  and the reason.
- **Browser-resolved forms pass through.** `var(--accent)`, `oklch(…)`,
  `color-mix(…)`, and `calc(…)` are shape-checked (known function, balanced)
  and left for the client's probe element to resolve.
- **Unknown DOM properties are allowed** — your CSS is authority — but every
  value must be declaration-safe: `;`, `{`, `}`, `</`, control characters,
  and unbalanced quotes/parentheses are rejected on every styling surface.
- **Canvas/WebGL mark properties use a strict CSS subset.** Unsupported mark
  declarations raise instead of silently disappearing in one renderer.
- **A string `color=` is a constant iff it parses as a CSS color**; any other
  string is a `data=` column name. The full named-color table counts, so
  `color="rebeccapurple"` is a color, and a color-shaped typo reports its
  CSS reason instead of a misleading column-lookup error.

## What CSS cannot restyle

Annotation **shapes** (markers, arrows, filled zones) are canvas-painted; style
them through the annotation's own `color` / `stroke_color` / `stroke_width` /
`opacity` arguments. Only annotation **labels** are DOM (`annotation_label`)
and thus fully CSS-styleable.

## Static export

`fig.to_image(format="png", *, width=, height=, scale=2.0, background=,
engine=xy.Engine.auto, quality=, optimize=, custom_css=)` returns image bytes,
and `fig.write_image(path, *, format=None, ...)` writes them (format inferred
from the path suffix when omitted). Both are mirrored on `Chart` and
`FacetChart`. The five formats are `png`, `jpeg` (alias `jpg`), `webp`, `svg`,
and `pdf`; `to_svg` and `to_png` remain as the two-format shorthands described
below.

| Format | Nature | Notes |
| --- | --- | --- |
| `png` | Raster | `optimize=True` trades latency for indexed-palette compression |
| `jpeg` | Raster, lossy | `quality` 1–100 (default 90); rejects `background="transparent"` |
| `webp` | Raster | Native encoder is lossless; `quality` applies to Chromium's lossy WebP |
| `svg` | Vector | Native-only — `engine=chromium` is not available |
| `pdf` | Vector | Text, axes, and marks stay vector; density and heatmap layers embed as bounded rasters (hybrid-vector policy) |

`scale` is the device-pixel ratio for raster output and is ignored by the vector
formats. `background` accepts `"auto"` (per-format default), a CSS color, or
`"transparent"`.

`engine=xy.Engine.auto` — the default for `to_image`/`write_image` — resolves
deterministically: the browser-free native path for every format, and Chromium
only when `custom_css` requires a real CSS engine. `xy.Engine.default` pins the
native path and `xy.Engine.chromium` pins the browser.

`fig.to_svg(path?, width=, height=)` renders the same decimated payload the
browser client consumes into a standalone, resolution-independent SVG — pure
Python, no browser, no extra dependencies. Because decimation runs first, the
file is **screen-bounded**: a 10M-point line exports in ~4 ms as a ~58 KB SVG.
Density/heatmap tiers embed as compact rasters.

`fig.to_png(path?, width=, height=, scale=)` defaults to
`engine=xy.Engine.default`: the
built-in **Rust rasterizer** paints that same decimated payload — no browser and
millisecond export. Pass `optimize=True` to trade latency for indexed-palette
PNG compression and smaller files. Text uses a baked bitmap font (the core has no FreeType),
so small labels are slightly less refined than a browser's.

**Native text coverage.** The atlas is a generated grayscale DejaVu Sans sheet
(`src/font.rs`, regenerated by `scripts/gen_font.py`) baked at a 16 px base
cell and blitted and scaled at runtime, so glyph coverage is a fixed set: ASCII
32–126 plus 110 enumerated extras (Greek, common math operators, arrows,
super/subscripts, typographic quotes and dashes). A codepoint outside that set
— CJK, Cyrillic, Arabic, emoji, most accented Latin — has no glyph and is
**silently skipped**, with no tofu box and no advance reserved, so a title,
tick label, legend entry, or annotation containing one renders shortened rather
than raising. Use `engine=xy.Engine.chromium` for full Unicode text.

The atlas bounds the native **raster** formats (PNG, JPEG, WebP) only. The
other two native formats carry their own text contracts: SVG emits real
`<text>` elements in a `system-ui` stack and so resolves against the viewer's
fonts, while PDF sets text with the base-14 Helvetica family in WinAnsiEncoding
and replaces any character outside WinAnsi with `?` — a deterministic,
locale-independent substitution.

For browser CSS, font, and WebGL fidelity, `engine=xy.Engine.chromium`
screenshots the standalone HTML with an installed Chrome, Chromium, Edge, or
`chrome-headless-shell`. Set `XY_BROWSER` to an executable path to override
automatic discovery. Pass `custom_css="..."` to inject an author stylesheet
into the captured standalone document. Since native export has no browser
cascade, it rejects `custom_css`. Legacy string engine values remain deprecated
aliases.

Both static engines carry the full mark styling surface — gradients, dashes,
symbols, rounded/stroked bars, smooth curves — with the same two documented
approximations: an area's mark-space gradient uses the area's bounding box (no
per-column gradient), and nested browser-only color expressions remain
browser-dependent in SVG and use the native rasterizer's static fallback in
PNG. Complete paint references such as `var(--accent)` resolve against custom
properties in the chart's own `style`, including nested token aliases and
`var()` fallbacks. SVG renders smooth curves as exact cubic Béziers; the native
raster flattens them to a fine polyline.
