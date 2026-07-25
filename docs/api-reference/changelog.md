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

Read [Chart methods](/docs/xy/api-reference/figure-methods/),
[Customize Each Part](/docs/xy/styling/customize/#fill,-stroke,-opacity,-and-gradients), and
[Limitations and alpha status](/docs/xy/api-reference/limitations-and-alpha-status/)
when upgrading code across alpha releases.
