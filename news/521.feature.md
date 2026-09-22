`xy.tooltip(format=...)` now formats dates and times. A strftime pattern —
`format={"time": "%b %d, %Y, %H:%M"}` — applies to any datetime-typed field,
including one sourced from a data table, which previously ignored the format
and rendered a raw ISO stamp such as `2026-09-17 10:03:05.264Z`. The format is
resolved from either the author's column name or the channel it is bound to,
per hovered trace, so two series binding different columns to `y` keep their
own formats and the band title under `mode="x"` takes the format keyed by the
time column. A time value with no `format=` no longer falls back to the ISO
stamp either: it follows the axis's own `format=` when there is one, and
otherwise the pattern the visible span reads best in (`Sep 17, 2026` for a
window of months, `Sep 17, 10:05` for hours or days, `10:05:00` for seconds),
sharpening as you zoom. `format=` also works on its own now, formatting the
default x/y/color/size rows without needing `fields=` or `title=`.
