---
title: Troubleshooting
description: Diagnose installation, display, export, validation, streaming, and Reflex failures.
---

# Troubleshooting

XY validates contracts at the boundary so a bad option fails close to the
chart call instead of producing a silently wrong visualization. Start with the
exception text: public validation errors name the argument, unsupported value,
or mismatched lengths involved.

## Installation and Native Core

**The native library is missing or cannot load.** Install a published wheel for
the current Python and platform. XY's native core is required; it does not
silently fall back to a slower Python implementation. A source checkout or
unsupported platform needs a Rust build toolchain.

**The JavaScript client is missing.** Reinstall the XY wheel so its bundled
`python/xy/static` assets are present. In a development checkout, build the JS
client with the repository's documented Node command before using widgets or
HTML export.

## Blank or Collapsed Charts

**A responsive chart has no height.** `width="100%"` can follow its container,
but `height="100%"` needs an ancestor with a defined height. Set an explicit
chart or component height while debugging.

**A notebook remains blank after installation.** Restart the kernel so the
Python package and bundled `anywidget` client come from the same installation,
then display `chart.widget()` directly to isolate surrounding layout.

**Only some charts in a large dashboard remain live.** Browsers limit WebGL
contexts. Avoid keeping more than XY's default context budget of 12 charts
simultaneously visible; see
[Dashboards and linked views](/docs/xy/guides/dashboards-and-linked-views/).

## Loud Styling Validation

**A style raises `ValueError`.** This is intentional loud validation: colors,
lengths, gradients, and mark styles are parsed eagerly. Fix the named property
rather than moving the same invalid value into another styling surface. DOM
chrome accepts ordinary CSS properties, but declaration-breaking text is
rejected. Canvas/WebGL marks
support a documented CSS subset and reject properties they cannot render.

**A color string is treated as a column.** A string that parses as a CSS color
is constant; another string resolves as a column name against `data=`.
Color-shaped typos such as a malformed hex value raise their CSS error instead
of quietly becoming a column lookup.

See [Styling](/docs/xy/styling/) and
[Customize Each Part](/docs/xy/styling/customize/) for the supported surfaces.

## Data and Streaming

**Columns have different lengths or the wrong shape.** Marks require aligned
one-dimensional geometry columns unless their page documents a matrix or
grouped form. Normalize the inputs before chart construction.

**`append()` fails.** Streaming supports existing line and scatter traces.
Coordinate tails must have equal nonzero length; ordered line x values must
continue in ascending order; per-point color and size channels need matching
tails. Validation is atomic, so correct the batch and retry.

**An exported file did not update.** HTML, PNG, and SVG are snapshots. Export
again after appending, or use a live widget/adapter.

## Export

**Chromium cannot be found.** Install Chrome, Chromium, Edge, or
`chrome-headless-shell`, or set `XY_BROWSER` to its executable. Use the default
native PNG engine when browser CSS and WebGL fidelity are unnecessary.

**`custom_css` is rejected for PNG.** CSS injection requires
`engine=Engine.chromium`; the native rasterizer accepts chart styles but does
not execute a browser stylesheet.

**A strict host CSP blocks standalone HTML.** Single-file export uses inline
scripts and styles. Follow
[Serving, CSP, and offline use](/docs/xy/guides/serving-csp-and-offline-use/)
and use a host wrapper for nonce/hash-only policies.

## Reflex

**Events do not reach the backend.** `reflex_xy.chart(chart)` with a direct
`xy.Chart` is the static payload tier. For fixed data with backend events,
create `token = reflex_xy.inline(chart)` at module scope and render it with
`reflex_xy.chart(token)`. Use an `@reflex_xy.figure` state var instead when the
data depends on the current session. Only the live token tiers dispatch
semantic events or accept `reflex_xy.append(...)`.

**A notebook callback name does not work as a Reflex prop.** Core chart
callbacks such as `on_hover`, `on_brush`, and `on_select` are ordinary Python
callables for the notebook widget. Put Reflex handlers on the outer component
with `on_point_hover`, `on_point_click`, `on_select_end`, or `on_view_change`.
The selection payloads also differ: notebook `on_select` receives an
`xy.Selection`, while Reflex `on_select_end` receives a JSON-safe summary.

**Different workers cannot resolve an inline token.** Register
`reflex_xy.inline(chart)` at module scope so each backend worker creates the
same content-addressed registration.

When reporting a reproducible failure, include the XY version, Python version,
platform, output engine, chart dimensions, full exception, and a minimal chart
constructor. `chart.memory_report()` is useful for memory or large-data cases.
