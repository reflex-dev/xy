"""Generate deterministic standalone fixtures for software-WebGL line timing."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

import xy

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
x = np.arange(1_000_000, dtype=float)
fixtures = []
for pattern in ("finite", "one_gap", "fragmented"):
    y = np.sin(x * 0.01)
    if pattern == "one_gap":
        y[len(x) // 2] = np.nan
    if pattern == "fragmented":
        y[50::100] = np.nan
    chart = xy.line_chart(
        xy.line(x, y),
        xy.legend(show=False),
        xy.modebar(show=False),
        width=720,
        height=320,
    )
    document = chart.to_html()
    for call in (
        'xy.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);',
        'xy.renderStandalone(document.getElementById("chart"), spec, buf);',
    ):
        document = document.replace(call, "window.liveGapView = " + call)
    path = args.output / f"{pattern}.html"
    path.write_text(document)
    fixtures.append({"pattern": pattern, "sha256": hashlib.sha256(document.encode()).hexdigest()})
(args.output / "fixtures.json").write_text(
    json.dumps({"source": xy.__file__, "rows": len(x), "fixtures": fixtures}, indent=2) + "\n"
)
