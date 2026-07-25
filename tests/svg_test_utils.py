from __future__ import annotations

import re


def tick_label_positions(svg: str) -> dict[str, tuple[float, float]]:
    """Return ``{label text: (x, y)}`` for every SVG text node."""
    return {
        match.group(3): (float(match.group(1)), float(match.group(2)))
        for match in re.finditer(r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*>([^<]*)</text>', svg)
    }
