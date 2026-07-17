---
title: Matplotlib (`xy.pyplot`)
description: Migrate common Matplotlib workflows through XY's pyplot compatibility layer.
---

# Matplotlib (`xy.pyplot`)

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

The compatibility layer translates calls onto XY's declarative chart API. It
does not require Matplotlib at runtime and uses the same native compute,
screen-bounded representations, notebook widget, and exporters as ordinary XY
charts.

## What Is Covered

The shim includes every method in Matplotlib 3.11.0's 2-D `Axes` **Plotting**
inventory. A reviewed snapshot locks that surface, and CI checks it against the
released `matplotlib==3.11.0` package. The shim also covers common stateful
pyplot, multi-panel, ticks, scales, legends, colorbars, styles, and export
workflows, plus XY-owned locator, formatter, date, colormap, `GridSpec`, and
`FacetGrid` helpers.

Coverage means that a plotting entry point exists and its supported contract
is tested. Depending on the feature, output can have exact geometry,
equivalent semantics, or a documented visual approximation. It is not a claim
to reproduce Matplotlib's renderer or complete Artist graph.

## Compatibility Boundary

Unsupported projections, animations, GUI backends, arbitrary third-party
Artist graphs, clipping/transform graphs, and material options that XY cannot
honor fail with an actionable error instead of being silently ignored.

Consult the repository's
[generated compatibility matrix](https://github.com/reflex-dev/xy/blob/main/docs/engineering/matplotlib-compat-matrix.md)
when a workflow depends on a specific option. Compatibility shims remain
experimental and can change before XY 1.0.

## Migration Path

1. Change the pyplot import and run the existing plotting workflow.
2. Resolve every explicit warning or unsupported-option error instead of
   assuming it is cosmetic.
3. Compare the output contract that matters to the application: interactive
   HTML, notebook display, PNG, or SVG.
4. For new or performance-sensitive code, move incrementally to `xy` chart
   containers and marks. The declarative API exposes data binding,
   interactions, and CSS/Tailwind hooks without pyplot's implicit state.

Use `xy.pyplot` for migration and familiar scientific scripts; prefer the
declarative API for new applications.
