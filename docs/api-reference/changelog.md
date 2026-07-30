---
title: Changelog
description: Review migration notes and notable changes in the XY alpha series.
---

# Changelog

The canonical, complete history lives in the repository's
[CHANGELOG.md](https://github.com/reflex-dev/xy/blob/main/CHANGELOG.md). It
follows Keep a Changelog; semantic-versioning compatibility becomes the firm
contract at 1.0. Before 1.0, a minor release can contain breaking changes.

## Current Unreleased Migration Notes

- The fluent public `Figure` builder has been removed. Build with declarative
  chart and component factories; use `Chart` for display, export, streaming,
  and readout. `Chart.figure()` remains an advanced internal-engine escape
  hatch.
- Mark `style=` now uses paint-specific CSS: `stroke` for line-like marks and
  `fill` for filled marks. The legacy factory `color=` argument remains, but
  `color` is not an alias inside a style dictionary.
- The former `MarkStyle`/`mark_style()` state-styling surface is removed.
  Framework applications should derive ordinary props and styles from
  application state.
- PNG export defaults to the browser-free native renderer. Select
  `Engine.chromium` for browser CSS/WebGL fidelity.
- Chromium PNG accepts `custom_css=`. Native PNG rejects author CSS; complete
  chart-level tokens can still resolve through renderable chart styles.
- Browser executable parameters were replaced by automatic discovery or the
  `XY_BROWSER` environment variable.

## Recent Additions

The current alpha line added the compact accessible toolbar and editable lasso
selection, the versioned binary frame transport, declarative statistical and
density families, facets, live `Chart.append()`/`pick()`/`select_range()`,
browser-free native PNG, pure SVG export, CSS-compiled mark styling, and the
experimental `xy.pyplot` compatibility layer.

The Unreleased polar expansion adds heatmap, contour, and error-bar marks;
partial sectors, holes/data-space origins, categorical theta, log/symlog
radius, and polygonal grids; and matching pyplot theta/r-origin controls.
Protocol v12 prevents an older client from silently interpreting that geometry
as the previous full-circle surface.

Outlined radar charts now render reliably: `radar_chart(fill=False)` translates
area stroke settings into the corresponding line props, including color, width,
opacity, curve, and dash.

Default tooltips now lead with a named series and speak polar coordinates on
polar charts: θ values reuse authored tick labels or the axis unit, and radial
values are labeled r instead of appearing as Cartesian x/y rows.

Read [Chart methods](/docs/xy/api-reference/figure-methods/),
[Customize Each Part](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients), and
[Limitations and alpha status](/docs/xy/api-reference/limitations-and-alpha-status/)
when upgrading code across alpha releases.
