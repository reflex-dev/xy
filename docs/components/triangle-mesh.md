---
title: Triangle Mesh in Python
description: Build a triangle mesh in Python with xy. Plot irregular surfaces from explicit per-triangle vertices with a color channel, interactive by default.
components:
  - xy.triangle_mesh_chart
---

# Triangle Mesh Charts in Python

A **triangle mesh** (also called a triangle mesh chart or triangle mesh plot)
renders a surface from explicit triangles, each defined by its three vertices. With `xy` you build a triangle mesh in Python when you
already have irregular geometry or precomputed topology — the low-level choice
where a grid-based surface won't fit. You give each triangle its vertices and an
optional color value, and the mesh stays interactive with pan, zoom, and hover.

Jump to [creating a triangle mesh](#create-a-triangle-mesh),
[when to use one](#when-to-use-a-triangle-mesh), or the
[options](#triangle-mesh-options).

## Create a Triangle Mesh

Give `triangle_mesh` the three vertices of each triangle — (`x0`, `y0`),
(`x1`, `y1`), (`x2`, `y2`) — plus a per-triangle `color` value mapped through
the `colormap`:

~~~python demo exec
import reflex_xy
import xy

triangle_mesh_detail_chart = xy.triangle_mesh_chart(
    xy.triangle_mesh(
        x0=[0, 1, 1, 2],
        y0=[0, 0, 1, 0],
        x1=[1, 2, 2, 3],
        y1=[0, 0, 1, 0],
        x2=[0.5, 1.5, 1.5, 2.5],
        y2=[1.2, 1.4, 2.2, 1.6],
        color=[0.15, 0.4, 0.7, 1.0],
        colormap="purples",
        domain=(0, 1),
        stroke="#6d28d9",
        stroke_width=1.2,
        opacity=0.8,
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Irregular triangle surface",
)


def triangle_mesh_demo():
    return reflex_xy.chart(triangle_mesh_detail_chart, height="340px")
~~~

## Color a Computed Mesh by Value

Meshes are usually generated, not hand-written — here a small grid is
triangulated in a loop and each triangle's `color` is a function value at its
centroid, mapped through `colormap` over an explicit `domain` with no stroke:

~~~python demo exec
import math

import reflex_xy
import xy

mesh_grid_nx, mesh_grid_ny = 7, 5
mesh_grid_x0, mesh_grid_y0 = [], []
mesh_grid_x1, mesh_grid_y1 = [], []
mesh_grid_x2, mesh_grid_y2 = [], []
mesh_grid_values = []
for gi in range(mesh_grid_nx):
    for gj in range(mesh_grid_ny):
        cell = [(gi, gj), (gi + 1, gj), (gi + 1, gj + 1), (gi, gj + 1)]
        for ta, tb, tc in [(0, 1, 2), (0, 2, 3)]:
            (ax, ay), (bx, by), (cx, cy) = cell[ta], cell[tb], cell[tc]
            mesh_grid_x0.append(ax)
            mesh_grid_y0.append(ay)
            mesh_grid_x1.append(bx)
            mesh_grid_y1.append(by)
            mesh_grid_x2.append(cx)
            mesh_grid_y2.append(cy)
            mx, my = (ax + bx + cx) / 3, (ay + by + cy) / 3
            mesh_grid_values.append(math.sin(mx * 0.9) * math.cos(my * 1.1))

triangle_mesh_grid_chart = xy.triangle_mesh_chart(
    xy.triangle_mesh(
        x0=mesh_grid_x0,
        y0=mesh_grid_y0,
        x1=mesh_grid_x1,
        y1=mesh_grid_y1,
        x2=mesh_grid_x2,
        y2=mesh_grid_y2,
        color=mesh_grid_values,
        colormap="viridis",
        domain=(-1, 1),
        opacity=0.95,
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Triangulated grid colored by value",
)


def triangle_mesh_grid_demo():
    return reflex_xy.chart(triangle_mesh_grid_chart, height="340px")
~~~

## Layer Constant-Color and Value-Colored Meshes

`color` also accepts a single CSS color for a constant fill, and one chart can
layer several meshes — this fan pairs a value-colored inner ring with a
constant-fill outer ring whose edges are drawn via `stroke` and `stroke_width`:

~~~python demo exec
import math

import reflex_xy
import xy

fan_inner = {"x0": [], "y0": [], "x1": [], "y1": [], "x2": [], "y2": [], "c": []}
fan_outer = {"x0": [], "y0": [], "x1": [], "y1": [], "x2": [], "y2": []}
fan_wedges = 10
for wk in range(fan_wedges):
    ang0 = math.pi * wk / fan_wedges
    ang1 = math.pi * (wk + 1) / fan_wedges
    for ring, r_in, r_out in [(fan_inner, 0.0, 1.0), (fan_outer, 1.1, 1.6)]:
        pts = [
            (r_in * math.cos(ang0), r_in * math.sin(ang0)),
            (r_out * math.cos(ang0), r_out * math.sin(ang0)),
            (r_out * math.cos(ang1), r_out * math.sin(ang1)),
            (r_in * math.cos(ang1), r_in * math.sin(ang1)),
        ]
        tris = [(0, 1, 2), (0, 2, 3)] if r_in > 0 else [(0, 1, 2)]
        for va, vb, vc in tris:
            ring["x0"].append(pts[va][0])
            ring["y0"].append(pts[va][1])
            ring["x1"].append(pts[vb][0])
            ring["y1"].append(pts[vb][1])
            ring["x2"].append(pts[vc][0])
            ring["y2"].append(pts[vc][1])
    fan_inner["c"].append(wk / (fan_wedges - 1))

triangle_mesh_fan_chart = xy.triangle_mesh_chart(
    xy.triangle_mesh(
        x0=fan_inner["x0"],
        y0=fan_inner["y0"],
        x1=fan_inner["x1"],
        y1=fan_inner["y1"],
        x2=fan_inner["x2"],
        y2=fan_inner["y2"],
        color=fan_inner["c"],
        colormap="purples",
        domain=(0, 1),
        opacity=0.9,
    ),
    xy.triangle_mesh(
        x0=fan_outer["x0"],
        y0=fan_outer["y0"],
        x1=fan_outer["x1"],
        y1=fan_outer["y1"],
        x2=fan_outer["x2"],
        y2=fan_outer["y2"],
        color="#ede9fe",
        stroke="#4c1d95",
        stroke_width=1.6,
        opacity=0.7,
    ),
    xy.x_axis(label="x"),
    xy.y_axis(label="y"),
    title="Constant fill with visible edges vs value-colored fan",
)


def triangle_mesh_fan_demo():
    return reflex_xy.chart(triangle_mesh_fan_chart, height="340px")
~~~

## When to Use a Triangle Mesh

`triangle_mesh` takes explicit `x0`/`y0`, `x1`/`y1`, `x2`/`y2` vertices per
triangle — the low-level choice when you already have irregular surfaces or
precomputed topology and want full control over the geometry. When your surface
comes from values on a regular grid, a [heatmap](/docs/xy/charts/heatmap/) or
[contour plot](/docs/xy/charts/contour-plot/) is usually the simpler fit.

## Triangle Mesh Options

| Option | Purpose |
| --- | --- |
| `x0` / `y0`, `x1` / `y1`, `x2` / `y2` | The three vertices of each triangle. |
| `color` | Constant fill, or a per-triangle channel mapped through `colormap`. |
| `colormap` | Named colormap for the `color` channel, e.g. `"purples"`. |
| `domain` | Value range mapped onto the colormap, e.g. `(0, 1)`. |
| `stroke` | Edge color drawn around each triangle. |
| `stroke_width` | Edge stroke width in pixels. |
| `opacity` | Triangle fill opacity from 0 to 1. |

Pass column names with `data=` instead of arrays when your vertices live in a
table.

## Related Charts

- [Contour plots](/docs/xy/charts/contour-plot/) — level curves from values on a
  grid.
- [Heatmaps](/docs/xy/charts/heatmap/) — color a regular grid of values by
  magnitude.

## FAQ

### How do I make a triangle mesh in Python?

Call `xy.triangle_mesh(...)` with the three vertices of each triangle inside
`xy.triangle_mesh_chart(...)` and render it. Pan, zoom, and hover work on the
triangle mesh graph automatically.

### How do I color triangles by value?

Pass a per-triangle list to `color`, set a `colormap`, and give a `domain` for
the value range. Each triangle's value is mapped through the colormap; pass a
single CSS color instead for a constant fill.

### When should I use a triangle mesh instead of a heatmap?

Use a triangle mesh for irregular surfaces or precomputed topology where you
control each triangle's vertices. Use a heatmap or contour plot when your values
sit on a regular grid.

### How do I draw the edges of each triangle?

Set `stroke` for the edge color and `stroke_width` for its thickness, as the
demo does with a purple outline.
