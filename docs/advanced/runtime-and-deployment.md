---
title: Choosing a Runtime and Deployment Mode
description: Choose between notebooks, standalone HTML, Reflex runtimes, and static renderers based on interaction, state, and deployment needs.
---

# Choosing a Runtime and Deployment Mode

The same XY chart definition can run with a live Python kernel, as a portable
browser document, inside a Reflex application, or through a static renderer.
Choose the mode from the capabilities the deployed chart needs, not only from
where it was developed.

## Compare the modes

| Mode | Best for | Important tradeoff |
| --- | --- | --- |
| Notebook widget | Exploration, callbacks, streaming, and exact live refinement | Requires a running Python kernel |
| Standalone HTML | A portable interactive file that works without a server | Keeps browser interaction, but cannot call Python or request server-side exact refinement |
| Reflex fixed chart | Fixed application data and static `reflex export` deployments | Compiles to a content-addressed `.xyf` asset with no backend event handlers |
| Reflex `inline()` | Fixed data that still needs kernel round-trips and Reflex events | Must be registered at module scope; the live figure is shared rather than session-derived |
| Reflex `@reflex_xy.figure` | Per-session, state-driven charts, events, streaming, and multi-worker recovery | Requires the Reflex backend and its websocket data plane |
| Native PNG | Fast reports, tests, thumbnails, and batch output | No interaction and no browser-only CSS |
| Chromium PNG | A static image matching browser fonts, CSS, and WebGL rendering | Pays browser startup and rendering overhead |
| SVG | Scalable or editable browser-free output | Large reductions can contain compact raster data rather than one vector element per source row |

## Follow the decision path

1. **Do you need interaction?** If not, use native PNG for speed, Chromium PNG
   for browser fidelity, or SVG for scalable output.
2. **Must the interactive result work without a server?** If so, use
   standalone HTML or a fixed Reflex chart.
3. **Does the data depend on the current user or application state?** Use
   `@reflex_xy.figure`. For fixed data, pass the chart directly unless it needs
   a live kernel; then use module-scope `inline()`.
4. **Do you need Python callbacks, streaming, or exact deep refinement?** Keep
   a live notebook or Reflex-backed figure. A standalone payload cannot call a
   Python process that is not there.

## Understand the deployment boundary

Choosing the wrong mode often appears as a deployment bug: a chart still pans
and zooms, but callbacks never fire; a static export cannot drill past its
retained data; or a locally registered figure is unavailable on another
backend worker.

The key boundary is whether a live Python figure exists after deployment.
Notebook widgets and live Reflex figures can resolve exact rows, accept
streaming updates, and run Python callbacks. Standalone HTML and fixed Reflex
charts keep browser-local interaction but have no Python process to call.

Continue with [Display and Export](/docs/xy/guides/display-and-export/) for
output APIs, [Notebooks](/docs/xy/integrations/notebooks/) for live kernel
behavior, and [Reflex](/docs/xy/integrations/reflex/) for fixed, `inline()`, and
state-backed examples.
