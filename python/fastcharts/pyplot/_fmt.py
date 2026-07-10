"""matplotlib format-string parser: ``'r--o'`` → (color, linestyle, marker).

Grammar per matplotlib: a fmt string is any interleaving of one color code
(single letter or ``C0``–``C9``), one linestyle (``-``, ``--``, ``-.``,
``:``), and one marker character. Empty parts are None.
"""

from __future__ import annotations

from typing import Optional

_LINESTYLES = ("--", "-.", "-", ":")  # two-char tokens first

_MARKERS = set(".,ov^<>12348spP*hH+xXDd|_")

_COLOR_LETTERS = set("bgrcmykw")


def parse_fmt(fmt: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (color, linestyle, marker); raises on unparseable input."""
    color: Optional[str] = None
    linestyle: Optional[str] = None
    marker: Optional[str] = None
    i = 0
    while i < len(fmt):
        ch = fmt[i]
        if ch == "C" and i + 1 < len(fmt) and fmt[i + 1].isdigit() and color is None:
            color = fmt[i : i + 2]
            i += 2
            continue
        two = fmt[i : i + 2]
        matched_style = None
        for style in _LINESTYLES:
            if fmt.startswith(style, i):
                matched_style = style
                break
        if matched_style is not None and linestyle is None:
            linestyle = matched_style
            i += len(matched_style)
            continue
        if ch in _COLOR_LETTERS and color is None:
            color = ch
            i += 1
            continue
        if ch in _MARKERS and marker is None:
            marker = ch
            i += 1
            continue
        raise ValueError(f"unrecognized character {ch!r} in format string {fmt!r} (two={two!r})")
    return color, linestyle, marker
