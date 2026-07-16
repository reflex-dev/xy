---
title: Notebooks and Pyplot
description: Display charts interactively and migrate common Matplotlib workflows.
---

# Notebooks and Pyplot

Composed charts display interactively when they are the final expression in a
Jupyter, VS Code, Colab, or compatible notebook cell. Call `chart.show()` or
`chart.widget()` when explicit display is clearer.

## Matplotlib-Shaped Workflows

For common 2D plotting code, import `xy.pyplot` in place of
`matplotlib.pyplot`.

~~~python
import numpy as np
import xy.pyplot as plt

x = np.linspace(0, 10, 200)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), "r--", label="signal")
ax.set_xlabel("time")
ax.set_ylabel("value")
ax.legend()
plt.show()
~~~

The compatibility layer includes common line, scatter, bar, histogram,
distribution, image, contour, vector-field, triangulation, annotation,
multi-panel, ticks, scales, legends, colorbars, styles, and export workflows.
It also provides XY-owned locator, formatter, date, colormap, GridSpec, and
FacetGrid helpers.

## Compatibility Boundary

The goal is compatible intent and useful visual output, not arbitrary
Matplotlib Artist compatibility. Unsupported projections, animations,
third-party Artist graphs, arbitrary clipping/transform graphs, and material
options that XY cannot honor fail with an actionable error instead of being
silently ignored.

The declarative `xy` API remains the preferred surface for new applications.
Use `xy.pyplot` for migration, familiar scientific scripts, and notebook code
that benefits from pyplot's implicit state model.
