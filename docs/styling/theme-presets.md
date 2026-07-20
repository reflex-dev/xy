---
title: Theme Preset Gallery
description: Compare every built-in XY theme preset in light and dark color schemes.
---

# Theme Preset Gallery

Each built-in declarative preset has a light and dark variant. These names are
specific to the XY token system; Matplotlib-compatible stylesheet names remain
under `xy.pyplot.style`.

The examples use identical data so the differences in chrome, palette, accent,
and contrast are easy to compare.

~~~python demo exec
import reflex as rx
import reflex_xy
import xy


def preset_example(preset: str, scheme: str):
    return xy.line_chart(
        xy.line([1, 2, 3, 4, 5], [3, 6, 4, 8, 7], name="Revenue"),
        xy.scatter([1, 2, 3, 4, 5], [2, 4, 5, 6, 9], name="Forecast"),
        xy.legend(loc="upper left"),
        xy.tooltip(),
        xy.theme(preset=preset, color_scheme=scheme),
        title=f"{preset.replace('_', ' ').title()} — {scheme}",
        width="100%",
        height=280,
    )


def theme_preset_gallery_preview():
    return rx.grid(
        *[
            reflex_xy.chart(preset_example(preset, scheme), height="280px")
            for preset in ("xy", "minimal", "dashboard", "publication", "high_contrast")
            for scheme in ("light", "dark")
        ],
        columns="2",
        spacing="4",
        width="100%",
    )
~~~

## XY

The default XY identity balances neutral chrome with a clear indigo accent.

## Minimal

Minimal removes the grid and uses a restrained muted palette.

## Dashboard

Dashboard adds a distinct plot card and a vivid categorical palette.

## Publication

Publication emphasizes dark axes, restrained colors, and print-like clarity.

## High contrast

High contrast uses pure foregrounds and the CVD-safe Okabe–Ito palette.

Use `palette=`, `accent=`, `contrast=`, named low-level arguments, or token
`style` overrides to adapt any preset. See
[Themes and Tokens](/docs/xy/styling/themes-and-tokens/) for precedence and
export behavior.
