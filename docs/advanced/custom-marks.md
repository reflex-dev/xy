---
title: Custom Marks
description: Add a chart kind XY does not ship by composing its built-in marks, without forking the renderer.
---

# Custom Marks

XY ships twenty mark kinds. When you need one it does not have — a candlestick,
a high-low band, a ribbon, a dumbbell — you can register it instead of waiting
for it or forking the renderer.

A mark plugin is two functions and a name:

- **`calc`** turns your input columns into the columns you want to draw. It runs
  once, on arrays, before anything is built.
- **`build`** returns ordinary XY marks. Not shaders, not draw calls — the same
  `xy.segments(...)`, `xy.scatter(...)`, `xy.line(...)` you would write by hand.

That second constraint is the point rather than a limitation. Because a plugin's
output is ordinary traces, it reuses the built-in rendering, picking, and export
paths — including native PNG and SVG, which have no browser — rather than
reimplementing them.

## A worked example

~~~python
import numpy as np
import xy


def _calc(columns):
    """Columns in, columns out. Add whatever `build` needs to draw."""
    return {**columns, "mid": (columns["low"] + columns["high"]) / 2.0}


def _build(ctx):
    """Return built-in marks. `ctx.columns` is `_calc`'s output."""
    return [
        xy.segments(
            x0=ctx.columns["t"],
            x1=ctx.columns["t"],
            y0=ctx.columns["low"],
            y1=ctx.columns["high"],
            name=ctx.name,
            style=ctx.style,
        ),
        xy.scatter(
            x=ctx.columns["t"],
            y=ctx.columns["mid"],
            size=ctx.options.get("mid_size", 6),
        ),
    ]


xy.register_mark(
    xy.MarkPlugin(
        name="hilo",
        columns=("t", "low", "high"),
        calc=_calc,
        build=_build,
        doc="A high-low band with a midpoint marker.",
    )
)
~~~

Use it like any other mark:

~~~python
chart = xy.chart(
    xy.mark("hilo", t="day", low="low", high="high", data=frame, name="Range"),
    xy.y_axis(label="price"),
)
~~~

Fields you named in `columns` behave exactly like a built-in mark's `x` and `y`:
a string names a column in `data=`, anything else is used as values directly,
and they reach `calc` as arrays. Every other keyword — `mid_size` above — arrives
in `ctx.options` untouched.

## What a plugin can and cannot do

| Can | Cannot |
| --- | --- |
| Compute new columns from its inputs | Reach the `Figure`, the trace list, or the column store |
| Emit any number of built-in marks | Emit another plugin's mark (composition is one level deep) |
| Read the caller's `style`, `name`, and options | Ship its own GLSL or WGSL |
| Draw on a named axis via `xy.mark(..., y_axis="y2")` | Add a new GPU primitive |

The last two are the real boundary, and it is deliberate rather than temporary
scaffolding. A plugin that composes built-in marks cannot draw anything the
engine could not already draw, which is what lets it reuse the engine's
existing paths. A plugin carrying its own shader would reuse none of them and
would have to reimplement decimation, picking, and three export paths itself.
See [§24 of the design dossier](https://github.com/reflex-dev/xy/blob/main/spec/design-dossier.md).

## Registry rules

`register_mark` refuses two things outright, both because the alternative is a
bug someone debugs at runtime:

- **Shadowing a built-in.** `xy.register_mark(MarkPlugin(name="scatter", ...))`
  raises. A plugin cannot change what `xy.scatter` means.
- **Silently replacing another plugin.** Two libraries registering
  `"candlestick"` is a conflict their user needs to see, not a race that import
  order settles. Pass `replace=True` when that is genuinely what you want.

`xy.registered_marks()` lists what is contributed from outside;
`xy.unregister_mark(name)` removes one, which is mostly useful in tests.
