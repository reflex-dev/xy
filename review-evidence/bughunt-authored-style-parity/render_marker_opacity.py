from __future__ import annotations

import sys
from pathlib import Path

import xy


destination = Path(sys.argv[1])
svg = (
    xy.chart(
        xy.scatter(x=[0.0, 1.0], y=[0.0, 1.0], opacity=0.0),
        xy.marker(
            0.5,
            0.5,
            size=80,
            color="#b000d4",
            stroke_color="#00d5ff",
            stroke_width=18,
            opacity=0.22,
        ),
        width=400,
        height=260,
        title="alpha=0.22 applies to fill and outline",
    )
    .figure()
    .to_svg()
)
destination.write_text(svg)
