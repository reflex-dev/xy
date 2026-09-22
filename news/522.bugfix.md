`xy.x_axis(show=False)` and `xy.y_axis(show=False)` now collapse the axis's
layout slot instead of painting an invisible axis in a gutter it still
occupies. A chart with both axes switched off reaches the container edge — the
sparkline case the axes docs describe — rather than sitting 25 px in, and a
hidden right-side axis no longer reserves its flat 54 px. The visibility
shorthands compile to transparent paints rather than to a flag, and the browser
was measuring that invisible text back into the gutter; the SVG and PNG
exporters already skipped it on the left, so the same chart exported flush and
rendered inset. Both renderers now ask the same question about the paint, on
both sides. Axes that draw their text reserve exactly the room they did before.
