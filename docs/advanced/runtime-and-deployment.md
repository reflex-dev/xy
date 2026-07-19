---
title: Choosing a Runtime and Deployment Mode
description: Use Reflex for deployed interactive apps, notebooks for exploration, standalone HTML for sharing, or static renderers for reports.
---

# Choosing a Runtime and Deployment Mode

For a deployed interactive application, start with Reflex. XY charts become
first-class components in an all-Python web app: Reflex handles UI, state,
events, and deployment, while XY handles data transport, rendering, and
interaction math. Start with a fixed chart and move to a session-backed figure
when the app needs live data without rewriting the chart definition.

XY also works outside an application. Use notebooks for exploration,
standalone HTML for a portable interactive result, and PNG or SVG for static
output.

## Start with Reflex for Applications

Reflex gives XY the application capabilities a standalone chart cannot:

- Compose XY charts with normal Reflex components in Python.
- Drive charts from per-session state with `@reflex_xy.figure`.
- Connect hover, click, selection, and view changes to normal Reflex event
  handlers, then stream updates with `reflex_xy.append`.
- Reuse the app's existing websocket and XY's binary data plane instead of
  deploying a separate chart service.
- Compile fixed charts into assets that work with `reflex export` and need no
  backend connection.

The adapter is still experimental and installed from the matching XY Git tag.
See the [Reflex integration guide](/docs/xy/integrations/reflex/) for the
current installation and API boundary.

## Compare the modes

| Mode | Best for |
| --- | --- |
| Reflex `@reflex_xy.figure` | Stateful Python applications with per-session data, events, streaming, and exact live refinement |
| Reflex fixed chart | Exportable Reflex sites and application views with fixed data and browser interaction |
| Reflex `inline()` | Fixed application data that still needs live Python round-trips and Reflex events |
| Notebook widget | Exploration, callbacks, streaming, and exact live refinement |
| Standalone HTML | A portable interactive file that works without a server |
| Native PNG | Fast reports, tests, thumbnails, and batch output |
| Chromium PNG | Static output matching browser fonts, CSS, and WebGL rendering |
| SVG | Scalable or editable browser-free output |

## Follow the decision path

1. **Building an interactive application? Start with Reflex.** Pass an
   `xy.Chart` directly when its data is fixed and exportable. Use
   `@reflex_xy.figure` when data depends on the current session or Reflex
   state. Use module-scope `inline()` for fixed data that still needs live
   Python refinement.
2. **Exploring data? Use the notebook widget.** It keeps callbacks, streaming,
   and exact refinement close to the analysis kernel.
3. **Sharing an interactive result without a server?** Use standalone HTML.
4. **Producing a static artifact?** Choose native PNG for speed, SVG for
   scalable output, or Chromium PNG for browser-level visual fidelity.

## Understand the deployment boundary

Reflex makes the live Python boundary explicit. A direct `xy.Chart` becomes a
content-addressed asset that works with `reflex export`. An `inline()` or
`@reflex_xy.figure` source stays connected to the Reflex backend through the
app's existing websocket, enabling events, streaming, and exact row
resolution.

Notebook widgets also keep a live Python figure. Standalone HTML and fixed
Reflex charts retain browser-local hover, pan, zoom, and selection, but cannot
call a Python process after deployment. PNG and SVG are final static artifacts.

For most deployed interactive work, continue with
[Reflex](/docs/xy/integrations/reflex/). For exploration, see
[Notebooks](/docs/xy/integrations/notebooks/). For portable files and static
rendering, see [Display and Export](/docs/xy/guides/display-and-export/).
