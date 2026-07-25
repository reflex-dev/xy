---
title: API Reference
description: Find XY chart factories, components, methods, callbacks, types, and status.
---

# API Reference

XY exports its supported declarative surface from `import xy`. Prefer
lowercase factories such as `xy.scatter()` and `xy.x_axis()`; public node types
are primarily useful for inspection and annotations.

- [Chart factories](/docs/xy/api-reference/chart-factories/) lists containers
  and their generated shared props.
- [Marks and components](/docs/xy/api-reference/marks-and-components/) renders
  generated signatures for marks, axes, annotations, chrome, themes, and
  behavior.
- [Chart methods](/docs/xy/api-reference/figure-methods/) covers notebook
  display, export, streaming, readout, and the internal-figure escape hatch.
- [Events and callbacks](/docs/xy/api-reference/events-and-callbacks/) defines
  Python callback, browser event, and `Selection` payloads.
- [Public types](/docs/xy/api-reference/public-types/) inventories the root
  type surface and constants.
- [Limitations and alpha status](/docs/xy/api-reference/limitations-and-alpha-status/)
  separates supported contracts from experimental or incomplete surfaces.
- [Changelog](/docs/xy/api-reference/changelog/) highlights migration-relevant
  changes and links to the canonical full history.
- [Contributing](/docs/xy/api-reference/contributing/) provides the development
  quick start and required checks.

Generated tables read the installed XY signatures, so parameter names, types,
and defaults remain aligned with the package used to build this site.
