---
title: Integrations
description: Use XY in Reflex applications, notebooks, and Matplotlib-shaped workflows.
---

# Integrations

XY's core composition API is framework-neutral. Integrations decide how a
composed chart is displayed, how live data reaches it, and where Python event
handlers run.

- [Reflex](/docs/xy/integrations/reflex/) covers static and state-backed charts,
  semantic events, and streaming through the `reflex-xy` adapter.
- [Notebooks](/docs/xy/integrations/notebooks/) covers Jupyter, JupyterLab,
  VS Code, Colab, and Marimo through one bundled `anywidget` implementation.
- [Matplotlib (`xy.pyplot`)](/docs/xy/integrations/matplotlib/) covers the
  compatibility boundary and a gradual migration to XY's declarative API.

All three surfaces use the same chart engine. The differences are transport
and application lifecycle, not chart geometry.
