---
title: Marks and Components
description: Generated signatures for XY marks, axes, annotations, chrome, themes, and behavior.
---

# Marks and Components

These tables are generated from XY's public Python signatures and docstrings.
Use the [Components guides](/docs/xy/components/) for composition patterns,
then return here for exact parameter names, types, and defaults.

## Marks

Marks accept arrays directly or resolve column names through mark-level or
chart-level `data=`. The `hist()` convenience wrapper accepts the same
parameters and produces the same histogram mark as `histogram()`.

~~~python exec
from xy_docs.api_reference import marks_api
~~~

~~~python eval
marks_api()
~~~

## Axes and Annotations

Axes configure scale presentation and named coordinate systems. Annotations
add rules, bands, text, markers, arrows, thresholds, and callouts. `threshold`
and `threshold_zone` are annotation conveniences, not data marks.

~~~python exec
from xy_docs.api_reference import axes_and_annotations_api
~~~

~~~python eval
axes_and_annotations_api()
~~~

## Chrome and Behavior

Chrome components configure legends, tooltips, colorbar hooks, the modebar,
theme tokens, and interaction behavior. The public colorbar component is
minimal; it does not independently author ticks, title, orientation, or domain.

~~~python exec
from xy_docs.api_reference import chrome_and_behavior_api
~~~

~~~python eval
chrome_and_behavior_api()
~~~

For rendering boundaries, see [Marks](/docs/xy/components/marks/),
[Colorbars](/docs/xy/components/colorbars/), and
[Modebars and interaction controls](/docs/xy/components/modebars-and-interaction-controls/).
