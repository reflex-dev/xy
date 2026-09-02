"""Exponential tick labels stay distinct past 1e6, identically in Python and JS.

`_fmt_linear` / `fmtLinear` formatted every |v| >= 1e6 (or < 1e-4) tick with
one mantissa decimal regardless of the step, so a 50,000-step axis read
"1.0e6, 1.1e6, 1.1e6, 1.2e6, 1.2e6, 1.3e6, 1.3e6" and 1,250,000 was labelled
"1.2e6". The mantissa now carries the digits between the value's magnitude and
the step's last significant digit; the two implementations are asserted equal
so a PNG never disagrees with the browser.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from xy._svg import _fmt_linear  # noqa: E402

CASES: list[tuple[list[float], float]] = [
    ([1e6, 1.05e6, 1.1e6, 1.15e6, 1.2e6, 1.25e6, 1.3e6], 5e4),
    ([1e6, 1e6 + 20, 1e6 + 40, 1e6 + 60, 1e6 + 80, 1e6 + 100], 20.0),
    ([0.0, 5e5, 1e6, 1.5e6, 2e6], 5e5),
    ([1e6, 1.25e6, 1.5e6, 1.75e6, 2e6], 2.5e5),
    ([1e-5, 1.02e-5, 1.04e-5], 2e-7),
    ([-1e-12, -5e-13, 0.0, 5e-13, 1e-12], 5e-13),
    ([1e300, 2e300, 3e300], 1e300),
    ([1e6, 2e6, 3e6], 1e6),
    ([12345678.0, 12345679.0, 12345680.0], 1.0),
]


def test_exponential_labels_are_distinct_at_the_tick_step() -> None:
    for ticks, step in CASES:
        labels = [_fmt_linear(v, step) for v in ticks]
        assert len(set(labels)) == len(labels), (ticks, step, labels)
    assert [_fmt_linear(v, 5e4) for v in (1e6, 1.05e6, 1.3e6)] == ["1.00e6", "1.05e6", "1.30e6"]
    assert _fmt_linear(1.25e6, 2.5e5) == "1.25e6"
    assert _fmt_linear(1e6 + 20, 20.0) == "1.00002e6"
    # Below the exponential threshold nothing changed.
    assert [_fmt_linear(v, 0.25) for v in (0.0, 0.25, 0.5)] == ["0.00", "0.25", "0.50"]
    assert _fmt_linear(5e-13, 5e-13) == "5.0e-13"
    # Degenerate steps fall back to one decimal instead of failing.
    assert _fmt_linear(2e6, 0.0) == "2.0e6"
    assert _fmt_linear(2e6, float("nan")) == "2.0e6"


def test_python_and_client_formatters_agree() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available for the fmtLinear parity check")
    ticks_ts = (ROOT / "js" / "src" / "30_ticks.ts").resolve().as_uri()
    payload = base64.b64encode(json.dumps(CASES).encode()).decode("ascii")
    script = (
        f'const m = await import("{ticks_ts}");'
        f'const cases = JSON.parse(Buffer.from("{payload}", "base64").toString());'
        "console.log(JSON.stringify(cases.map(([ticks, step]) => ticks.map((v) => m.fmtLinear(v, step)))));"
    )
    completed = subprocess.run(
        [node, "--no-warnings", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    js_labels = json.loads(completed.stdout)
    py_labels = [[_fmt_linear(v, step) for v in ticks] for ticks, step in CASES]
    assert js_labels == py_labels


def test_exported_axis_labels_are_distinct_past_a_million() -> None:
    import xml.etree.ElementTree as ET

    import xy

    chart = xy.line_chart(
        xy.line([0.0, 1.0, 2.0], [1e6, 1e6 + 1.0, 1e6 + 2.0]), width=400, height=300
    )
    root = ET.fromstring(chart.to_svg())
    texts = [el.text for el in root.iter("{http://www.w3.org/2000/svg}text") if el.text]
    y_labels = [t for t in texts if t.endswith("e6")]
    assert len(y_labels) >= 3 and len(set(y_labels)) == len(y_labels), texts
    assert np.all(np.diff([float(t.replace("e6", "e+6")) for t in y_labels]) != 0)
