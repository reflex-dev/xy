---
title: API Reference
description: Find XY chart factories, components, methods, and output APIs.
---

# API Reference

XY exports its declarative surface from `import xy as fc`. The
[component reference](/docs/xy/api-reference/components/) groups every public chart
factory and the methods available on a composed `Chart`.

The preferred API uses lowercase factory functions such as `fc.scatter()` and
`fc.x_axis()`. Dataclass node types such as `Mark`, `Axis`, and `Legend` are
public for inspection and type annotations, but most applications should create
them through factories.
